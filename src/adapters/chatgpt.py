"""ChatGPT 导出解析器 — 解析 OpenAI 官方导出的 conversations.json。

支持两种输入：
- 裸 JSON 文件（conversations.json，用户已从 ZIP 解压）
- ZIP 文件（仅解压读取 conversations.json，不处理媒体）

本期只处理文本内容：
- content.content_type == "text" 的 parts 提取文本
- image_asset_pointer / code 等非文本 part 暂时跳过（Fragment 字段保留待后续扩展）
- reasoning 字段（o1/o3 系列思维链）保留，作为 Fragment(kind="reasoning")

ChatGPT conversations.json 结构：
    [
      {
        "title": "...",
        "create_time": 1716234567.89,    # Unix 时间戳
        "update_time": 1716234999.12,
        "mapping": {
          "ROOT": {"id":"ROOT","message":null,"parent":null,"children":["aaa"]},
          "aaa":  {"id":"aaa","message":{...},"parent":"ROOT","children":["bbb"]},
          ...
        },
        "id": "conv-001"
      }
    ]
"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from src.adapters.base import BaseAdapter
from src.unified_schema import (
    Fragment,
    UnifiedMessage,
    UnifiedSession,
)

# ChatGPT 导出中 author.role 的合法值
_VALID_ROLES = {"user", "assistant", "system", "tool"}


class ChatGPTAdapter(BaseAdapter):
    """OpenAI ChatGPT 官方导出解析器。"""

    provider: str = "openai"
    supported_extensions = (".json", ".zip")

    # ==========================================
    # 格式探测
    # ==========================================
    def detect(self, path: Path) -> float:
        """识别 ChatGPT 导出文件。

        置信度规则：
        - .zip 含 conversations.json → 0.95
        - .json 顶层 list 且首项含 title + mapping → 0.95
        - 仅扩展名匹配 → 0.5（fallback 到基类）
        """
        suffix = path.suffix.lower()

        if suffix == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    if "conversations.json" in zf.namelist():
                        return 0.95
            except zipfile.BadZipFile:
                return 0.0
            return 0.0

        if suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list) and len(data) > 0:
                    first = data[0]
                    if isinstance(first, dict) and "title" in first and "mapping" in first:
                        return 0.95
            except (json.JSONDecodeError, UnicodeDecodeError):
                return 0.0

        return 0.0

    # ==========================================
    # 解析主入口
    # ==========================================
    def parse(self, path: Path) -> list[UnifiedSession]:
        """解析 ChatGPT 导出文件，返回 UnifiedSession 列表。

        Args:
            path: .json 或 .zip 文件路径

        Returns:
            UnifiedSession 列表（一个 ChatGPT 导出通常含数十到数百个会话）

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式不符合 ChatGPT 导出预期
        """
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        raw = self._load_raw(path)
        if not isinstance(raw, list):
            raise ValueError(
                f"ChatGPT 导出应为顶层 JSON 数组，实际类型: {type(raw).__name__}"
            )

        sessions: list[UnifiedSession] = []
        for conv in raw:
            session = self._parse_one_conv(conv)
            if session is not None:
                sessions.append(session)

        return sessions

    # ==========================================
    # 内部：读取原始数据
    # ==========================================
    def _load_raw(self, path: Path) -> list | dict:
        """从 .json 或 .zip 读取 conversations.json 内容。"""
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                with zf.open("conversations.json") as f:
                    return json.loads(f.read().decode("utf-8"))
        return json.loads(path.read_text(encoding="utf-8"))

    # ==========================================
    # 内部：解析单个会话
    # ==========================================
    def _parse_one_conv(self, conv: dict) -> UnifiedSession | None:
        """解析单个 conversation（含 mapping 树）。"""
        conv_id = conv.get("id") or conv.get("conversation_id")
        if not conv_id:
            return None

        mapping = conv.get("mapping", {})
        if not mapping:
            return None

        messages: list[UnifiedMessage] = []

        # 遍历 mapping 所有节点，提取有效 message
        for node_id, node in mapping.items():
            msg = node.get("message") if isinstance(node, dict) else None
            if not msg:
                continue

            unified = self._parse_one_message(msg, conv_id, node_id)
            if unified is not None:
                messages.append(unified)

        if not messages:
            return None

        # 按 created_at 排序（null 排到最后）
        messages.sort(key=lambda m: (m.created_at is None, m.created_at or datetime.min.replace(tzinfo=timezone.utc)))

        # 会话级时间戳
        created_at = self._ts_to_dt(conv.get("create_time")) or messages[0].created_at
        updated_at = self._ts_to_dt(conv.get("update_time")) or messages[-1].created_at

        # 会话级模型：取最后一条 assistant 消息的 model
        session_model = None
        for m in reversed(messages):
            if m.role == "assistant" and m.model:
                session_model = m.model
                break

        return UnifiedSession(
            id=conv_id,
            title=conv.get("title"),
            provider="openai",
            model=session_model,
            messages=messages,
            created_at=created_at or datetime.now(timezone.utc),
            updated_at=updated_at,
            source="chatgpt_export",
            raw_metadata={
                "weight": conv.get("weight"),
                "conversation_id_from_source": conv.get("conversation_id"),
            },
        )

    # ==========================================
    # 内部：解析单条消息
    # ==========================================
    def _parse_one_message(
        self, msg: dict, conv_id: str, fallback_id: str
    ) -> UnifiedMessage | None:
        """解析单条 message，返回 UnifiedMessage 或 None（跳过无效消息）。"""
        author = msg.get("author", {})
        role = author.get("role", "")
        if role not in _VALID_ROLES:
            return None

        # 提取文本内容
        content = msg.get("content", {})
        text_parts: list[str] = []
        fragments: list[Fragment] = []

        parts = content.get("parts", []) if isinstance(content, dict) else []
        for part in parts:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                ct = part.get("content_type")
                if ct == "text":
                    text_parts.append(part.get("text", ""))
                # image_asset_pointer / code / 等非文本 part 本期跳过
                # 后续多模态扩展时在此填 fragments.append(Fragment(...))

        # 思维链（o1/o3 系列）— 本期保留，属纯文本范畴
        reasoning_text = msg.get("reasoning")
        if reasoning_text:
            fragments.append(Fragment(kind="reasoning", text=reasoning_text))

        # 如果有 tool_calls（部分版本导出含此字段），跳过解析但保留 raw
        # 本期不处理工具调用

        content_text = "\n".join(p for p in text_parts if p).strip()
        # 跳过完全无内容且无 fragments 的消息
        if not content_text and not fragments:
            return None

        # 时间戳（Unix float → datetime UTC；可能缺失）
        created_at = self._ts_to_dt(msg.get("create_time"))
        updated_at = self._ts_to_dt(msg.get("update_time"))

        # 模型标识
        model_slug = None
        metadata = msg.get("metadata")
        if isinstance(metadata, dict):
            model_slug = metadata.get("model_slug")

        msg_id = msg.get("id") or fallback_id

        return UnifiedMessage(
            id=msg_id,
            session_id=conv_id,
            role=role,  # type: ignore[arg-type]
            content=content_text,
            fragments=fragments,
            provider="openai",
            model=model_slug,
            created_at=created_at or datetime.now(timezone.utc),  # fallback
            updated_at=updated_at,
            source="chatgpt_export",
            upstream_ref=msg.get("id"),
        )

    # ==========================================
    # 内部：Unix 时间戳 → datetime
    # ==========================================
    @staticmethod
    def _ts_to_dt(ts: float | int | None) -> datetime | None:
        """Unix 时间戳（秒，float）→ datetime（UTC）。

        ChatGPT 导出的 create_time 是 Unix 时间戳（如 1716234567.89）。
        """
        if ts is None:
            return None
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None
