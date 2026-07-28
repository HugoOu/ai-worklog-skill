"""
Map 缓存层 — 避免重复调用 LLM 提取候选。

缓存策略：
- 每天一个 JSON 文件，存放在 {outdir}/.map_cache/ 下
- 文件名：{date}_{content_hash}.json
- 缓存命中条件：content_hash 相同 + prompt_version 相同 + 未截断
- 源数据变了（消息增删改）→ hash 变 → 自动失效
- prompt 改了 → prompt_version 递增 → 自动失效
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.models import DailyConversation, DayMapCache


class MapCacheStore:
    """Map 结果的磁盘缓存管理器。"""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, daily_conv: DailyConversation) -> Path:
        """缓存文件路径：{date}_{content_hash}.json"""
        return self.cache_dir / f"{daily_conv.date}_{daily_conv.content_hash}.json"

    def get(self, daily_conv: DailyConversation, prompt_version: str = "v1") -> Optional[DayMapCache]:
        """查询缓存。命中且有效则返回 DayMapCache，否则返回 None。"""
        path = self._cache_path(daily_conv)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cache = DayMapCache.model_validate(data)
            # 校验 prompt_version 一致性
            if cache.map_run.prompt_version != prompt_version:
                return None
            # 校验缓存有效性（有候选且未截断）
            if not cache.is_valid:
                return None
            return cache
        except Exception:
            return None

    def put(self, daily_conv: DailyConversation, cache: DayMapCache) -> Path:
        """写入缓存，返回文件路径。"""
        path = self._cache_path(daily_conv)
        path.write_text(
            cache.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return path

    def invalidate(self, daily_conv: DailyConversation) -> bool:
        """手动失效某天的缓存。返回是否删除了文件。"""
        path = self._cache_path(daily_conv)
        if path.exists():
            path.unlink()
            return True
        return False

    def clear(self) -> int:
        """清空所有缓存，返回删除文件数。"""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
            count += 1
        return count

    def stats(self) -> dict:
        """缓存统计。"""
        files = list(self.cache_dir.glob("*.json"))
        return {
            "cache_dir": str(self.cache_dir),
            "file_count": len(files),
            "total_size_kb": sum(f.stat().st_size for f in files) / 1024,
        }
