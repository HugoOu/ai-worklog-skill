"""
MapCacheStore 单元测试。
"""
import json
import tempfile
from pathlib import Path

from src.models import (
    ConversationMessage,
    DailyConversation,
    CandidateTopic,
    MapRunMeta,
    DayMapCache,
)
from src.cache import MapCacheStore


def _make_daily(date="2026-04-14", content="怎么学习 RAG？") -> DailyConversation:
    return DailyConversation(date=date, messages=[
        ConversationMessage(role="user", content=content, date=date),
        ConversationMessage(role="assistant", content="RAG 是...", date=date),
    ])


def _make_cache(daily: DailyConversation, prompt_version="v2") -> DayMapCache:
    return DayMapCache(
        cache_key=daily.content_hash,
        date=daily.date,
        input_message_count=len(daily.messages),
        map_run=MapRunMeta(
            run_id="test-run-001",
            model="qwen3.7-flash",
            prompt_version=prompt_version,
            created_at="2026-07-29T00:00:00+08:00",
        ),
        candidates=[
            CandidateTopic(topic="RAG学习路径", summary="系统学习RAG五阶段", date=daily.date),
        ],
    )


def test_cache_miss_then_hit():
    """首次 get 返回 None，put 后再 get 命中。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = MapCacheStore(Path(tmp))
        daily = _make_daily()

        # Miss
        assert store.get(daily, prompt_version="v2") is None

        # Put
        cache = _make_cache(daily)
        store.put(daily, cache)

        # Hit
        result = store.get(daily, prompt_version="v2")
        assert result is not None
        assert result.candidates[0].topic == "RAG学习路径"


def test_cache_invalidation_on_content_change():
    """源数据变化（hash 不同）→ 缓存不命中。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = MapCacheStore(Path(tmp))
        daily_v1 = _make_daily(content="怎么学习 RAG？")
        daily_v2 = _make_daily(content="怎么学习 Agent？")

        store.put(daily_v1, _make_cache(daily_v1))

        # 同一对象 → 命中
        assert store.get(daily_v1, prompt_version="v2") is not None
        # 内容变了 → 不命中
        assert store.get(daily_v2, prompt_version="v2") is None


def test_cache_invalidation_on_prompt_version_change():
    """prompt_version 不同 → 缓存不命中。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = MapCacheStore(Path(tmp))
        daily = _make_daily()
        store.put(daily, _make_cache(daily, prompt_version="v1"))

        # v1 → 命中
        assert store.get(daily, prompt_version="v1") is not None
        # v2 → 不命中
        assert store.get(daily, prompt_version="v2") is None


def test_cache_truncated_not_valid():
    """截断的缓存 → is_valid=False → get 返回 None。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = MapCacheStore(Path(tmp))
        daily = _make_daily()
        cache = _make_cache(daily)
        cache.map_run.truncated = True
        store.put(daily, cache)

        assert store.get(daily, prompt_version="v2") is None


def test_cache_clear():
    """clear 清空所有缓存。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = MapCacheStore(Path(tmp))
        for i in range(3):
            daily = _make_daily(content=f"content {i}")
            store.put(daily, _make_cache(daily))

        assert store.stats()["file_count"] == 3
        assert store.clear() == 3
        assert store.stats()["file_count"] == 0
