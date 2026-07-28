"""
桥接层 — UnifiedSession → DailyConversation 适配。

下游 clustering.py（MapReduceClustering）的输入是 list[DailyConversation]，
本模块把 pipeline 产出的 list[UnifiedSession] 转换为该格式，实现零改动衔接。

迁移完成后，下游 clustering 完全无感知数据源是 ChatGPT 还是 Gemini。
"""
from __future__ import annotations

from collections import OrderedDict
from typing import List

from src.models import ConversationMessage, DailyConversation
from src.unified_schema import UnifiedSession


def unified_to_daily(sessions: List[UnifiedSession]) -> List[DailyConversation]:
    """UnifiedSession 列表 → DailyConversation 列表（按天归集）。

    规则:
    - 取每条 message 的 created_at（已时区归一化到 Asia/Shanghai）的日期部分
    - 同一天的所有消息归入同一个 DailyConversation
    - 保持时间顺序
    - 丢弃无 created_at 的消息（理论上 pipeline 已保证必填）

    Args:
        sessions: pipeline 产出的 UnifiedSession 列表

    Returns:
        按天归集的 DailyConversation 列表，按日期升序
    """
    grouped: "OrderedDict[str, List[ConversationMessage]]" = OrderedDict()

    for sess in sessions:
        for msg in sess.messages:
            if msg.created_at is None:
                continue

            date_str = msg.created_at.strftime("%Y-%m-%d")
            grouped.setdefault(date_str, []).append(
                ConversationMessage(
                    role=msg.role,
                    content=msg.content,
                    date=date_str,
                    session_id=sess.id,
                )
            )

    # 按日期排序
    result = [
        DailyConversation(date=d, messages=m)
        for d, m in sorted(grouped.items())
    ]
    return result
