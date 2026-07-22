"""
解析流水线 — 完整链路: detect → parse → normalize(tz) → (optional) group by date → export。

CLI 与 MCP server 都调同一个 `run()` 入口，行为一致，避免功能割裂。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta, tzinfo
from pathlib import Path
from typing import Literal, Optional

from src.adapters import REGISTRY, BaseAdapter
from src.unified_schema import UnifiedSession

# ==========================================
# 时区常量
# ==========================================
DEFAULT_TIMEZONE: tzinfo = timezone(timedelta(hours=8))  # Asia/Shanghai (UTC+8)


# ==========================================
# 格式探测
# ==========================================
def detect_provider(path: Path) -> tuple[BaseAdapter, float]:
    """返回 (最佳 adapter 实例, 置信度)。

    遍历 REGISTRY 中所有已注册 adapter，选取 detect() 置信度最高者。
    无任何 adapter 置信度 > 0.3 时抛 ValueError。

    Args:
        path: 待探测文件路径

    Returns:
        (adapter 实例, 置信度)

    Raises:
        ValueError: 无法识别文件格式
    """
    if not REGISTRY:
        raise RuntimeError(
            "REGISTRY 为空 — 当前无已注册 adapter。"
            "请在 src/adapters/__init__.py 中注册至少一个 adapter。"
        )

    scored = [(cls(), cls().detect(path)) for cls in REGISTRY]
    scored.sort(key=lambda x: x[1], reverse=True)

    best_adapter, best_score = scored[0]
    if best_score < 0.3:
        raise ValueError(
            f"无法识别文件格式: {path}\n"
            f"最高置信度仅 {best_score:.2f}（阈值 0.3）。\n"
            f"请用 --provider 显式指定平台。"
        )
    return best_adapter, best_score


def get_adapter(provider: str) -> BaseAdapter:
    """按 provider 标识获取 adapter 实例。

    Args:
        provider: 平台标识，如 "openai" / "google" / "claude"

    Returns:
        adapter 实例

    Raises:
        ValueError: provider 未注册或未实现
    """
    for cls in REGISTRY:
        if cls.provider == provider:
            return cls()
    raise ValueError(
        f"未找到 provider='{provider}' 的 adapter。\n"
        f"已注册: {[cls.provider for cls in REGISTRY]}\n"
        f"若该 adapter 尚未实现，请参考 src/adapters/__init__.py 中的预留接口。"
    )


# ==========================================
# 时区归一化
# ==========================================
def normalize_timezone(
    sessions: list[UnifiedSession],
    tz: tzinfo = DEFAULT_TIMEZONE,
) -> list[UnifiedSession]:
    """将所有时间戳归一化到目标时区。

    保留原始 UTC 信息，仅调整显示时区（datetime.astimezone）。
    后续按日期分组时使用归一化后的本地日期。

    Args:
        sessions: UnifiedSession 列表
        tz: 目标时区，默认 Asia/Shanghai

    Returns:
        归一化后的 sessions（原地修改并返回）
    """
    for sess in sessions:
        if sess.created_at and sess.created_at.tzinfo is None:
            # 无时区信息，假定为 UTC
            sess.created_at = sess.created_at.replace(tzinfo=timezone.utc)
        sess.created_at = sess.created_at.astimezone(tz)

        for msg in sess.messages:
            if msg.created_at and msg.created_at.tzinfo is None:
                msg.created_at = msg.created_at.replace(tzinfo=timezone.utc)
            msg.created_at = msg.created_at.astimezone(tz)
            if msg.updated_at:
                if msg.updated_at.tzinfo is None:
                    msg.updated_at = msg.updated_at.replace(tzinfo=timezone.utc)
                msg.updated_at = msg.updated_at.astimezone(tz)

    return sessions


# ==========================================
# 导出
# ==========================================
def export(
    sessions: list[UnifiedSession],
    outdir: Path,
    out_format: Literal["json", "jsonl", "markdown"] = "json",
) -> Path:
    """将 UnifiedSession 列表导出到文件。

    Args:
        sessions: 待导出的会话列表
        outdir: 输出目录（不存在则创建）
        out_format: 输出格式
            - "json": 单个 JSON 数组文件
            - "jsonl": 每行一个 JSON（流式友好）
            - "markdown": 每会话一个 Markdown 文件（Phase 2 实现）

    Returns:
        输出文件（或目录）路径
    """
    import json

    outdir.mkdir(parents=True, exist_ok=True)

    if out_format == "json":
        out_path = outdir / "unified_sessions.json"
        out_path.write_text(
            json.dumps(
                [s.model_dump(mode="json") for s in sessions],
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        return out_path

    elif out_format == "jsonl":
        out_path = outdir / "unified_sessions.jsonl"
        with out_path.open("w", encoding="utf-8") as f:
            for s in sessions:
                f.write(json.dumps(s.model_dump(mode="json"), ensure_ascii=False) + "\n")
        return out_path

    elif out_format == "markdown":
        # TODO Phase 2: 实现 Markdown 导出（每会话一个 .md 文件，含 YAML frontmatter）
        raise NotImplementedError("Markdown 导出待 Phase 2 实现")

    else:
        raise ValueError(f"不支持的输出格式: {out_format}")


# ==========================================
# 主入口
# ==========================================
def run(
    input_path: Path,
    provider: str = "auto",
    out_format: Literal["json", "jsonl", "markdown"] = "json",
    outdir: Optional[Path] = None,
    timezone_str: str = "Asia/Shanghai",
    group_by_date: bool = False,
) -> list[UnifiedSession]:
    """完整流水线: detect → parse → normalize(tz) → (optional) group by date → export。

    Args:
        input_path: 导出文件路径 (JSON/JSONL/HTML/ZIP)
        provider: 平台标识，"auto" 自动探测；或显式指定 openai/google/claude/...
        out_format: 输出格式 json|jsonl|markdown
        outdir: 输出目录（None 则不写文件，仅返回 sessions）
        timezone_str: 时区归一化目标（IANA 名称如 "Asia/Shanghai"，或 UTC 偏移如 "+08:00"）
        group_by_date: 是否额外输出 daily_conversations.json（与下游 clustering 衔接用）

    Returns:
        UnifiedSession 列表

    Raises:
        FileNotFoundError: 输入文件不存在
        ValueError: 格式无法识别或 provider 未注册
    """
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")

    # 1. 选 adapter
    if provider == "auto":
        adapter, confidence = detect_provider(input_path)
    else:
        adapter = get_adapter(provider)
        confidence = 1.0

    # 2. 解析
    sessions = adapter.parse(input_path)

    # 3. 时区归一化
    tz = _parse_timezone(timezone_str)
    sessions = normalize_timezone(sessions, tz)

    # 4. 导出（如指定 outdir）
    if outdir is not None:
        export(sessions, outdir, out_format)

        # 额外输出 daily_conversations.json（与下游 clustering 衔接）
        if group_by_date:
            _export_daily_conversations(sessions, outdir)

    return sessions


def _parse_timezone(tz_str: str) -> tzinfo:
    """解析时区字符串为 tzinfo 对象。

    支持：
    - IANA 名称: "Asia/Shanghai" / "UTC" → 用 zoneinfo
    - UTC 偏移: "+08:00" / "UTC+8" / "+0800" → 手动解析

    fallback: 无法解析时返回 UTC+8（Asia/Shanghai）
    """
    from zoneinfo import ZoneInfo

    # 尝试 IANA 名称
    try:
        return ZoneInfo(tz_str)
    except Exception:
        pass

    # 尝试 UTC 偏移: "+08:00" / "UTC+8" / "+0800"
    offset_match = re.match(r"^(?:UTC)?([+-])(\d{1,2}):?(\d{2})?$", tz_str)
    if offset_match:
        sign = 1 if offset_match.group(1) == "+" else -1
        hours = int(offset_match.group(2))
        minutes = int(offset_match.group(3) or 0)
        return timezone(timedelta(hours=sign * hours, minutes=sign * minutes))

    # fallback
    return DEFAULT_TIMEZONE


def _export_daily_conversations(sessions: list[UnifiedSession], outdir: Path) -> Path:
    """将 UnifiedSession 转换为 DailyConversation 并导出，供下游 clustering.py 消费。

    输出文件: {outdir}/daily_conversations.json
    """
    import json

    from src.bridge import unified_to_daily

    daily = unified_to_daily(sessions)
    out_path = outdir / "daily_conversations.json"
    out_path.write_text(
        json.dumps(
            [d.model_dump(mode="json") for d in daily],
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return out_path
