"""
聚类策略抽象层 + 具体实现。

不同聚类方式实现同一个 ClusteringStrategy 接口，下游无需改动即可替换。
当前实现策略①（Map-Reduce），未来可替换为策略③（Embedding）。
"""
from abc import ABC, abstractmethod
from typing import List
from src.models import DailyConversation, CandidateItem
from src.extractor import extract_candidates_from_daily, merge_cross_day_candidates


class ClusteringStrategy(ABC):
    """聚类策略抽象基类。输入跨天的全部对话，输出聚类后的候选主题。"""

    @abstractmethod
    def cluster(self, daily_conversations: List[DailyConversation]) -> List[CandidateItem]:
        ...


class MapReduceClustering(ClusteringStrategy):
    """
    策略①: Map-Reduce 两阶段聚类。

    - Map: 每天独立调用 LLM 提取日级候选（复用 extract_candidates_from_daily）
    - Reduce: 汇总所有日级候选，LLM 合并跨天同主题；evidence 在代码中按索引拼接保证一字不差

    适合初期验证产品逻辑。历史量大后替换为 EmbeddingClustering（策略③）。
    """

    def cluster(self, daily_conversations: List[DailyConversation]) -> List[CandidateItem]:
        # ---- Map 阶段：逐天提取日级候选 ----
        all_candidates: List[CandidateItem] = []
        for daily_conv in daily_conversations:
            day_candidates = extract_candidates_from_daily(daily_conv)
            # 标注每个候选的来源日期
            for cand in day_candidates:
                cand.dates = [daily_conv.date]
            all_candidates.extend(day_candidates)

        if not all_candidates:
            return []

        # 单天无需合并，直接返回
        if len(daily_conversations) <= 1:
            return all_candidates

        # ---- Reduce 阶段：跨天合并 ----
        return merge_cross_day_candidates(all_candidates)
