"""
Embedding 聚类策略 — 用向量距离替代 LLM Reduce 做跨天合并。

流程：
1. 收集所有 CandidateItem（来自 Map 缓存或实时 Map）
2. 拼接 topic + summary 为文本 → 调 DashScope embedding API 获取向量
3. AgglomerativeClustering（余弦距离）做确定性聚类
4. 每个簇生成一个合并后的 CandidateItem

确定性保证：embedding 是确定性的，聚类算法是确定性的（无随机初始化），
唯一不确定来源是 Map 阶段的 LLM 措辞——但通过缓存消除了重复 Map。
"""
from __future__ import annotations

import os
from typing import List

import numpy as np
from openai import OpenAI
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_distances

from src.models import CandidateItem

# Embedding 配置
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
# 聚类距离阈值：越小越严格（簇越少、越大）；0.5 是经验值
CLUSTER_DISTANCE_THRESHOLD = float(os.getenv("CLUSTER_DISTANCE_THRESHOLD", "0.45"))

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        from dotenv import load_dotenv
        load_dotenv()
        _client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )
    return _client


def embed_texts(texts: List[str], batch_size: int = 10) -> np.ndarray:
    """批量获取 embedding 向量。DashScope 限制每次最多 10 条。"""
    client = _get_client()
    all_embeddings: List[List[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=batch,
        )
        # 按 index 排序确保顺序
        sorted_data = sorted(response.data, key=lambda x: x.index)
        all_embeddings.extend([d.embedding for d in sorted_data])

    return np.array(all_embeddings, dtype=np.float32)


def cluster_candidates(
    candidates: List[CandidateItem],
    distance_threshold: float | None = None,
) -> List[CandidateItem]:
    """
    对候选工作项做 embedding 聚类，合并语义相近的主题。

    输入：Map 阶段产出的 CandidateItem 列表（已按日期排序）
    输出：聚类后的 CandidateItem 列表（每个簇合并为一个）

    确定性：embedding + AgglomerativeClustering 均为确定性操作。
    """
    if len(candidates) <= 1:
        return candidates

    threshold = distance_threshold or CLUSTER_DISTANCE_THRESHOLD

    # 构造聚类文本：topic + summary
    texts = [f"{c.topic}。{c.summary}" for c in candidates]

    # 获取 embedding
    embeddings = embed_texts(texts)

    # 计算余弦距离矩阵
    dist_matrix = cosine_distances(embeddings)

    # AgglomerativeClustering（确定性，无随机种子问题）
    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold,
        metric="precomputed",
        linkage="average",
    )
    labels = clustering.fit_predict(dist_matrix)

    # 按簇合并候选
    clusters: dict[int, List[CandidateItem]] = {}
    for idx, label in enumerate(labels):
        clusters.setdefault(int(label), []).append(candidates[idx])

    merged: List[CandidateItem] = []
    for label in sorted(clusters.keys()):
        group = clusters[label]
        if len(group) == 1:
            merged.append(group[0])
        else:
            # 合并同簇候选
            all_dates = sorted(set(d for c in group for d in c.dates))
            # 证据链：并集所有子候选的 session_ids（保序去重）
            merged_session_ids: List[str] = []
            for c in group:
                for sid in c.session_ids:
                    if sid not in merged_session_ids:
                        merged_session_ids.append(sid)
            # 取最短 topic 作为簇名（或拼接）
            topics = [c.topic for c in group]
            # 选最长公共前缀或直接用最短的
            cluster_topic = _merge_topics(topics)
            cluster_summary = " | ".join(c.summary for c in group)
            if len(cluster_summary) > 300:
                cluster_summary = cluster_summary[:297] + "..."
            cluster_evidence = "\n---\n".join(c.evidence for c in group if c.evidence)

            merged.append(CandidateItem(
                topic=cluster_topic,
                summary=cluster_summary,
                evidence=cluster_evidence,
                dates=all_dates,
                session_ids=merged_session_ids,
            ))

    # 按最早日期排序
    merged.sort(key=lambda c: c.dates[0] if c.dates else "")
    return merged


def _merge_topics(topics: List[str]) -> str:
    """合并多个 topic 为一个簇名称。"""
    if len(topics) == 1:
        return topics[0]
    # 找最长公共前缀
    prefix = os.path.commonprefix(topics)
    prefix = prefix.rstrip(" ,，、")
    if len(prefix) >= 6:
        return prefix
    # 否则用第一个 + "等N项"
    return f"{topics[0]}等{len(topics)}项"
