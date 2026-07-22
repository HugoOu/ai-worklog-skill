"""Gemini 导出解析器 — 解析 Google My Activity 导出的 HTML 对话记录。

迁移自原 src/parser.py 的 parse_gemini_html 逻辑，输出格式升级为 UnifiedSession。

主要变化：
- 输出从 DailyConversation 升级为 UnifiedSession（含完整元数据）
- 时间戳从 "2026年5月21日" 升级为完整 datetime（含时分秒 + 时区 HKT=UTC+8）
- 每个 outer-cell 块 = 一个会话（user 提问 + assistant 回答）

Gemini HTML 结构（Google My Activity 导出）：
    <div class="outer-cell ...">
      <div class="mdl-grid">
        <div class="header-cell ..."><p>Gemini Apps</p></div>
        <div class="content-cell mdl-typography--body-1">
          Prompted 用户的问题<br/>
          2026年5月21日 10:43:45 HKT<br/>
          <p>AI 的回答...</p>
        </div>
      </div>
    </div>
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

from src.adapters.base import BaseAdapter
from src.unified_schema import UnifiedMessage, UnifiedSession

# HKT = Hong Kong Time = UTC+8（与 Asia/Shanghai 同时区）
_HKT_TZ = timezone(timedelta(hours=8))

# 时间戳正则：匹配 "2026年5月21日 10:43:45 HKT" 等
# 必须含时间部分，避免误匹配对话正文中提及的日期（如法规"自2009年1月1日起实施"）
_TIMESTAMP_PATTERN = re.compile(
    r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2}):(\d{2})(?:\s+([A-Z]+))?"
)


class GeminiAdapter(BaseAdapter):
    """Google Gemini (My Activity) HTML 导出解析器。"""

    provider: str = "google"
    supported_extensions = (".html", ".htm")

    # ==========================================
    # 格式探测
    # ==========================================
    def detect(self, path: Path) -> float:
        """识别 Gemini My Activity HTML 导出。

        置信度规则：
        - .html 含 "outer-cell" + "mdl-typography--body-1" + "Gemini Apps" → 0.95
        - .html 含 "outer-cell" + "mdl-typography--body-1" → 0.85
        - 仅 .html 扩展名 → 0.3（低于阈值，不会被误选）
        """
        if path.suffix.lower() not in (".html", ".htm"):
            return 0.0

        try:
            # 读前 1MB 足够判断（CSS 在 head，结构在 body，outer-cell 可能在文件深处）
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                content = f.read(1_000_000)
        except OSError:
            return 0.0

        has_outer_cell = "outer-cell" in content
        has_body_1 = "mdl-typography--body-1" in content
        has_gemini = "Gemini Apps" in content or "Gemini" in content

        if has_outer_cell and has_body_1 and has_gemini:
            return 0.95
        if has_outer_cell and has_body_1:
            return 0.85
        return 0.0

    # ==========================================
    # 解析主入口
    # ==========================================
    def parse(self, path: Path) -> list[UnifiedSession]:
        """解析 Gemini HTML 导出，返回 UnifiedSession 列表。

        每个 outer-cell 块对应一个会话（user 提问 + assistant 回答）。

        Args:
            path: HTML 文件路径

        Returns:
            UnifiedSession 列表（按出现顺序）

        Raises:
            FileNotFoundError: 文件不存在
        """
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        html_content = path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html_content, "lxml")
        chat_blocks = soup.find_all("div", class_="outer-cell")

        sessions: list[UnifiedSession] = []

        for idx, block in enumerate(chat_blocks):
            session = self._parse_one_block(block, idx)
            if session is not None:
                sessions.append(session)

        return sessions

    # ==========================================
    # 内部：解析单个 outer-cell 块
    # ==========================================
    def _parse_one_block(self, block: BeautifulSoup, block_idx: int) -> UnifiedSession | None:
        """解析单个 outer-cell 块为一个 UnifiedSession（含 user + assistant 两条消息）。"""
        # 精准定位包含对话主体和时间的 cell
        content_cell = block.find("div", class_="mdl-typography--body-1")
        if not content_cell:
            return None

        user_text = ""
        assistant_text = ""
        timestamp_dt: datetime | None = None
        timestamp_found = False

        # 遍历该 cell 下的所有子节点
        for content in content_cell.contents:
            if content.name == "br":
                continue

            # 提取纯文本
            if content.name:
                text = content.get_text(separator="\n", strip=True)
            else:
                text = str(content).strip()

            if not text:
                continue

            # 1. 检查并提取时间戳
            match = _TIMESTAMP_PATTERN.search(text)
            if match:
                timestamp_dt = self._parse_timestamp(match)
                timestamp_found = True
                continue  # 时间戳节点本身不作为对话内容

            # 2. 根据是否找到时间戳，划分 User 和 Assistant 区域
            if not timestamp_found:
                # 过滤掉附件等无用提示行
                if "Attached" not in text and not text.startswith("-"):
                    user_text += text + "\n"
            else:
                assistant_text += text + "\n"

        # 清理提取到的文本
        user_text = user_text.strip()
        assistant_text = assistant_text.strip()

        # 去除提问开头的 "Prompted " 前缀
        if user_text.startswith("Prompted"):
            user_text = user_text[len("Prompted"):].strip()

        # 无任何内容则跳过
        if not user_text and not assistant_text:
            return None

        # 时间戳 fallback：若未提取到，用当前时间（理论不应发生）
        if timestamp_dt is None:
            timestamp_dt = datetime.now(_HKT_TZ)

        # 构造消息列表
        messages: list[UnifiedMessage] = []
        session_id = f"gemini-block-{block_idx:04d}"

        if user_text:
            messages.append(UnifiedMessage(
                id=f"{session_id}-u",
                session_id=session_id,
                role="user",
                content=user_text,
                provider="google",
                # Gemini 导出不含模型名，留空
                model=None,
                created_at=timestamp_dt,
                source="gemini_export",
            ))

        if assistant_text:
            messages.append(UnifiedMessage(
                id=f"{session_id}-a",
                session_id=session_id,
                role="assistant",
                content=assistant_text,
                provider="google",
                model=None,
                # assistant 回答时间略晚于提问（无精确时间，复用同一时间戳）
                created_at=timestamp_dt,
                source="gemini_export",
            ))

        if not messages:
            return None

        # 用 user 消息前 40 字作为标题
        title = (user_text[:40] + "...") if len(user_text) > 40 else user_text

        return UnifiedSession(
            id=session_id,
            title=title or None,
            provider="google",
            model=None,
            messages=messages,
            created_at=timestamp_dt,
            updated_at=timestamp_dt,
            source="gemini_export",
            raw_metadata={"block_index": block_idx},
        )

    # ==========================================
    # 内部：时间戳解析
    # ==========================================
    @staticmethod
    def _parse_timestamp(match: re.Match) -> datetime:
        """将正则匹配的时间戳转为 datetime。

        输入: "2026年5月21日 10:43:45 HKT"
        输出: datetime(2026, 5, 21, 10, 43, 45, tzinfo=UTC+8)

        时区处理：
        - HKT (Hong Kong Time) → UTC+8
        - 其他时区缩写暂按 UTC+8 处理（Gemini 导出主要来自 HKT）
        - 无时区标注也按 UTC+8（与 Asia/Shanghai 一致）
        """
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        hour = int(match.group(4))
        minute = int(match.group(5))
        second = int(match.group(6))
        # tz_abbr = match.group(7)  # HKT / CST / 等，本期统一按 UTC+8

        return datetime(year, month, day, hour, minute, second, tzinfo=_HKT_TZ)
