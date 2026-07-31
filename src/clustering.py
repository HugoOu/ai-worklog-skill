"""
聚类策略抽象层 + 具体实现。

不同聚类方式实现同一个 ClusteringStrategy 接口，下游无需改动即可替换。
- MapReduceClustering: LLM Map + LLM Reduce（旧策略，不确定）
- EmbeddingClustering: LLM Map（带缓存）+ Embedding 聚类（新策略，确定性）
"""
import os
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List
from pathlib import Path

from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from src.models import DailyConversation, CandidateItem, CandidateTopic, DayMapCache, MapRunMeta
from src.extractor import extract_candidates_from_daily, merge_cross_day_candidates, MODEL_NAME, MAX_TOKENS
from src.cache import MapCacheStore

# Map 阶段并发数（可通过环境变量覆盖，默认 5）
MAP_WORKERS = int(os.getenv("MAP_WORKERS", "5"))
# Map prompt 版本（改 SYSTEM_PROMPT、Map 缓存数据结构或 LLM 模型时递增，触发缓存失效）
PROMPT_VERSION = "v4"


class ClusteringStrategy(ABC):
    """聚类策略抽象基类。输入跨天的全部对话，输出聚类后的候选主题。"""

    @abstractmethod
    def cluster(self, daily_conversations: List[DailyConversation]) -> List[CandidateItem]:
        ...


class MapReduceClustering(ClusteringStrategy):
    """
    策略①: Map-Reduce 两阶段聚类（旧版，保留兼容）。

    - Map: 多线程并发调用 LLM 提取日级候选
    - Reduce: LLM 跨天合并（不确定性来源）
    """

    def cluster(self, daily_conversations: List[DailyConversation]) -> List[CandidateItem]:
        all_candidates: List[CandidateItem] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Map 提取候选"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total} 天)"),
            TimeElapsedColumn(),
        ) as progress:
            task_id = progress.add_task("map", total=len(daily_conversations))

            def _extract_one(daily_conv: DailyConversation):
                return daily_conv, extract_candidates_from_daily(daily_conv, log=progress.console.print)

            with ThreadPoolExecutor(max_workers=MAP_WORKERS) as executor:
                futures = {executor.submit(_extract_one, dc): dc for dc in daily_conversations}
                for future in as_completed(futures):
                    daily_conv, day_candidates = future.result()
                    for cand in day_candidates:
                        cand.dates = [daily_conv.date]
                    all_candidates.extend(day_candidates)
                    progress.advance(task_id)

        if not all_candidates:
            return []

        all_candidates.sort(key=lambda c: (c.dates[0] if c.dates else "", c.topic))

        if len(daily_conversations) <= 1:
            return all_candidates

        print("Reduce: 跨天合并候选主题...")
        return merge_cross_day_candidates(all_candidates)


class EmbeddingClustering(ClusteringStrategy):
    """
    策略③: Embedding 聚类（新版，确定性）。

    - Map: LLM 提取日级候选（带磁盘缓存，相同输入不重复调 LLM）
    - Cluster: Embedding + AgglomerativeClustering 做跨天合并（确定性）

    确定性保证：
    - Map 结果缓存后不再变化（除非源数据或 prompt 改变）
    - Embedding 是确定性的
    - AgglomerativeClustering 无随机初始化，结果确定
    """

    def __init__(self, cache_dir: Path | None = None):
        if cache_dir is None:
            cache_dir = Path("./output/.map_cache")
        self.cache_store = MapCacheStore(cache_dir)

    def cluster(self, daily_conversations: List[DailyConversation]) -> List[CandidateItem]:
        # ---- Map 阶段（带缓存）----
        all_candidates: List[CandidateItem] = []
        cache_hits = 0
        cache_misses = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Map 提取候选"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total} 天)"),
            TimeElapsedColumn(),
        ) as progress:
            task_id = progress.add_task("map", total=len(daily_conversations))

            def _map_one(daily_conv: DailyConversation):
                # 1. 查缓存
                cached = self.cache_store.get(daily_conv, prompt_version=PROMPT_VERSION)
                if cached is not None:
                    return daily_conv, cached, True  # cache hit

                # 2. 缓存未命中 → 调 LLM
                start_ms = datetime.now()
                candidates = extract_candidates_from_daily(daily_conv, log=progress.console.print)
                duration_ms = int((datetime.now() - start_ms).total_seconds() * 1000)

                # 3. 构建缓存对象
                candidate_topics = [
                    CandidateTopic(
                        topic=c.topic,
                        summary=c.summary,
                        evidence=c.evidence,
                        date=daily_conv.date,
                        session_ids=c.session_ids,
                    )
                    for c in candidates
                ]
                cache_obj = DayMapCache(
                    cache_key=daily_conv.content_hash,
                    date=daily_conv.date,
                    input_message_count=len(daily_conv.messages),
                    map_run=MapRunMeta(
                        run_id=os.urandom(16).hex(),
                        model=MODEL_NAME,
                        temperature=0.0,
                        max_tokens=MAX_TOKENS,
                        prompt_version=PROMPT_VERSION,
                        created_at=datetime.now().astimezone().isoformat(),
                        duration_ms=duration_ms,
                    ),
                    candidates=candidate_topics,
                )

                # 4. 写入缓存
                self.cache_store.put(daily_conv, cache_obj)
                return daily_conv, cache_obj, False  # cache miss

            with ThreadPoolExecutor(max_workers=MAP_WORKERS) as executor:
                futures = {executor.submit(_map_one, dc): dc for dc in daily_conversations}
                for future in as_completed(futures):
                    daily_conv, cache_obj, was_cached = future.result()
                    if was_cached:
                        cache_hits += 1
                    else:
                        cache_misses += 1
                    # 转换 CandidateTopic → CandidateItem
                    for ct in cache_obj.candidates:
                        all_candidates.append(CandidateItem(
                            topic=ct.topic,
                            summary=ct.summary,
                            evidence=ct.evidence,
                            dates=[daily_conv.date],
                            session_ids=ct.session_ids,
                        ))
                    progress.advance(task_id)

        if cache_hits > 0 or cache_misses > 0:
            print(f"Map 完成：{cache_hits} 天命中缓存，{cache_misses} 天新调 LLM")

        if not all_candidates:
            return []

        # 按日期排序
        all_candidates.sort(key=lambda c: (c.dates[0] if c.dates else "", c.topic))

        # 单天无需聚类
        if len(all_candidates) <= 1:
            return all_candidates

        # ---- Cluster 阶段：Embedding + AgglomerativeClustering ----
        print("Cluster: Embedding 向量聚类（确定性）...")
        from src.embedding import cluster_candidates
        return cluster_candidates(all_candidates)
