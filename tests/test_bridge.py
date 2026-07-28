"""
bridge 层测试 — 重点验证证据链源头：UnifiedSession.id → ConversationMessage.session_id。
"""
from datetime import datetime

from src.bridge import unified_to_daily
from src.unified_schema import UnifiedSession, UnifiedMessage


def _make_session(sess_id: str, day: str, contents):
    """构造一个 UnifiedSession，含若干消息（contents 为 (role, text) 列表）。"""
    msgs = []
    for i, (role, text) in enumerate(contents):
        msgs.append(UnifiedMessage(
            id=f"{sess_id}-m{i}",
            session_id=sess_id,
            role=role,
            content=text,
            created_at=datetime.fromisoformat(f"{day}T{10+i:02d}:00:00+08:00"),
        ))
    return UnifiedSession(
        id=sess_id,
        provider="openai",
        messages=msgs,
        created_at=msgs[0].created_at,
        source="manual",
    )


def test_session_id_propagated_to_messages():
    """每条 ConversationMessage 都应携带来源 session_id。"""
    sessions = [_make_session("sess-A", "2026-04-14", [("user", "你好"), ("assistant", "你好！")])]
    daily = unified_to_daily(sessions)

    assert len(daily) == 1
    for msg in daily[0].messages:
        assert msg.session_id == "sess-A"


def test_multi_session_same_day_distinct_session_ids():
    """同一天来自不同 session 的消息，各自保留正确的 session_id。"""
    sessions = [
        _make_session("sess-A", "2026-04-14", [("user", "问题1")]),
        _make_session("sess-B", "2026-04-14", [("user", "问题2")]),
    ]
    daily = unified_to_daily(sessions)

    # 同一天归集为一个 DailyConversation
    assert len(daily) == 1
    session_ids = {msg.session_id for msg in daily[0].messages}
    assert session_ids == {"sess-A", "sess-B"}


def test_multi_day_grouping():
    """跨天消息按日期分组，且 session_id 不丢失。"""
    sessions = [
        _make_session("sess-A", "2026-04-14", [("user", "day1")]),
        _make_session("sess-A", "2026-04-15", [("user", "day2")]),
    ]
    daily = unified_to_daily(sessions)

    assert [d.date for d in daily] == ["2026-04-14", "2026-04-15"]
    for d in daily:
        assert all(msg.session_id == "sess-A" for msg in d.messages)
