"""
RAPTOR 风格递归聚类树构建器。

从 depth-0 叶子节点（每个 CandidateItem 一个）出发，
逐层 embedding → AgglomerativeClustering → 合并为父节点，
直到收敛（簇数 == 节点数，或节点数 ≤ 阈值）。

确定性：embedding + AgglomerativeClustering 均为确定性操作，
树结构在同一输入下完全可复现。
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import List

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_distances

from src.models import (
    CandidateItem,
    TopicNode,
    TopicTree,
    TopicTreeMeta,
)
from src.embedding import embed_texts, EMBEDDING_MODEL, CLUSTER_DISTANCE_THRESHOLD

# 递归停止条件：节点数 ≤ 此值时不再向上聚合
MAX_DEPTH = int(os.getenv("RAPTOR_MAX_DEPTH", "5"))
MIN_TOP_NODES = int(os.getenv("RAPTOR_MIN_TOP_NODES", "2"))


def _new_node_id() -> str:
    return os.urandom(6).hex()


def _build_leaf_nodes(candidates: List[CandidateItem]) -> List[TopicNode]:
    """将 CandidateItem 列表转为 depth-0 叶子节点。"""
    leaves = []
    for cand in candidates:
        node = TopicNode(
            node_id=_new_node_id(),
            depth=0,
            label=cand.topic,
            summary=cand.summary,
            session_ids=cand.session_ids,  # 证据链：来自 CandidateItem 的来源 session 列表
            dates=cand.dates,
        )
        leaves.append(node)
    return leaves


def _cluster_nodes_at_level(
    nodes: List[TopicNode],
    distance_threshold: float,
) -> List[List[int]]:
    """
    对一组同层节点做 embedding 聚类，返回簇的索引分组。
    每个簇是一组 nodes 的索引列表。
    """
    if len(nodes) <= 1:
        return [[i] for i in range(len(nodes))]

    texts = [f"{n.label}。{n.summary}" for n in nodes]
    embeddings = embed_texts(texts)
    dist_matrix = cosine_distances(embeddings)

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        metric="precomputed",
        linkage="average",
    )
    labels = clustering.fit_predict(dist_matrix)

    clusters: dict[int, List[int]] = {}
    for idx, label in enumerate(labels):
        clusters.setdefault(int(label), []).append(idx)

    return list(clusters.values())


def _strip_suffix(label: str) -> str:
    """去除标签末尾的 '等N项' 后缀，避免父标签层层叠加。"""
    import re
    return re.sub(r"等\d+项$", "", label).strip()


def _merge_nodes_to_parent(
    child_nodes: List[TopicNode],
    depth: int,
) -> TopicNode:
    """将一组子节点合并为一个父节点。"""
    all_dates = sorted(set(d for n in child_nodes for d in n.dates))
    children_ids = [n.node_id for n in child_nodes]

    # 证据链：父节点聚合所有子节点的 session_ids（保序去重）
    merged_session_ids: List[str] = []
    for n in child_nodes:
        for sid in n.session_ids:
            if sid not in merged_session_ids:
                merged_session_ids.append(sid)

    # 父节点 label：先去掉子标签已有的 "等N项" 后缀，再求最长公共前缀；
    # 公共前缀太短则用「最短标签 + 等N项」（N 为子节点数，不累积）。
    cleaned = [_strip_suffix(n.label) for n in child_nodes]
    prefix = os.path.commonprefix(cleaned).rstrip(" ,，、")
    if len(prefix) >= 6:
        parent_label = prefix
    else:
        base = min(cleaned, key=len)
        parent_label = f"{base}等{len(child_nodes)}项"

    # 摘要：拼接子节点摘要
    summaries = [n.summary for n in child_nodes if n.summary]
    if len(summaries) == 1:
        parent_summary = summaries[0]
    else:
        parent_summary = " | ".join(summaries)
        if len(parent_summary) > 300:
            parent_summary = parent_summary[:297] + "..."

    parent = TopicNode(
        node_id=_new_node_id(),
        depth=depth,
        label=parent_label,
        summary=parent_summary,
        children=children_ids,
        session_ids=merged_session_ids,
        dates=all_dates,
    )

    # 回写 parent_id
    for n in child_nodes:
        n.parent_id = parent.node_id

    return parent


def build_topic_tree(
    candidates: List[CandidateItem],
    distance_threshold: float | None = None,
    log=print,
) -> TopicTree:
    """
    从 CandidateItem 列表递归构建 TopicTree。

    流程：
    1. 每个 CandidateItem → depth-0 叶子节点
    2. 对当前层节点 embedding + 聚类
    3. 每个簇合并为一个父节点（depth+1）
    4. 重复 2-3 直到收敛（簇数 == 节点数 或 节点数 ≤ MIN_TOP_NODES 或 depth ≥ MAX_DEPTH）
    5. 最终顶层节点即为 root_ids

    返回完整 TopicTree（含所有层级节点）。
    """
    if not candidates:
        meta = TopicTreeMeta(
            tree_id=os.urandom(16).hex(),
            created_at=datetime.now().astimezone().isoformat(),
            method="embedding_raptor",
            embedding_model=EMBEDDING_MODEL,
            cluster_params={"distance_threshold": distance_threshold or CLUSTER_DISTANCE_THRESHOLD},
            total_sessions=0,
            total_nodes=0,
            depth=0,
        )
        return TopicTree(meta=meta, nodes={}, root_ids=[])

    threshold = distance_threshold or CLUSTER_DISTANCE_THRESHOLD

    # 所有节点的字典（node_id → TopicNode）
    all_nodes: dict[str, TopicNode] = {}

    # 1. 构建叶子层
    current_level = _build_leaf_nodes(candidates)
    for node in current_level:
        all_nodes[node.node_id] = node

    current_depth = 0
    log(f"  depth 0: {len(current_level)} 个叶子节点")

    # 2. 递归向上聚合
    while current_depth < MAX_DEPTH:
        if len(current_level) <= MIN_TOP_NODES:
            log(f"  节点数 ≤ {MIN_TOP_NODES}，停止聚合")
            break

        # 聚类当前层
        clusters = _cluster_nodes_at_level(current_level, threshold)

        # 检查是否收敛（每个簇只有自己 → 无法再合并）
        if all(len(c) == 1 for c in clusters):
            log(f"  depth {current_depth}: 聚类收敛（{len(clusters)} 个独立簇），停止")
            break

        current_depth += 1
        next_level: List[TopicNode] = []

        for cluster_indices in clusters:
            child_nodes = [current_level[i] for i in cluster_indices]
            if len(child_nodes) == 1:
                # 单节点簇：直接提升，不创建新父节点
                promoted = child_nodes[0]
                # 更新 depth（它现在属于更高一层）
                # 但不修改原节点 depth，保持叶子 depth=0
                next_level.append(promoted)
            else:
                parent = _merge_nodes_to_parent(child_nodes, depth=current_depth)
                all_nodes[parent.node_id] = parent
                next_level.append(parent)

        log(f"  depth {current_depth}: {len(current_level)} → {len(next_level)} 个节点")
        current_level = next_level

    # 3. 确定 root_ids（最终顶层节点）
    root_ids = [n.node_id for n in current_level]

    # 4. 计算树深度
    max_depth = max((n.depth for n in all_nodes.values()), default=0)

    meta = TopicTreeMeta(
        tree_id=os.urandom(16).hex(),
        created_at=datetime.now().astimezone().isoformat(),
        method="embedding_raptor",
        embedding_model=EMBEDDING_MODEL,
        cluster_params={"distance_threshold": threshold},
        total_sessions=len(candidates),
        total_nodes=len(all_nodes),
        depth=max_depth + 1,
    )

    return TopicTree(meta=meta, nodes=all_nodes, root_ids=root_ids)


def print_tree(tree: TopicTree, console=None) -> None:
    """用 rich Tree 在终端打印主题树。"""
    from rich.tree import Tree as RichTree
    from rich.console import Console as RichConsole

    con = console or RichConsole()

    def _add_subtree(rich_parent, node_id: str):
        node = tree.nodes.get(node_id)
        if not node:
            return
        dates_str = ", ".join(node.dates) if node.dates else ""
        label = f"[bold]{node.label}[/bold]"
        if dates_str:
            label += f" [dim]({dates_str})[/dim]"
        if node.summary:
            label += f"\n  [dim]{node.summary[:80]}{'...' if len(node.summary) > 80 else ''}[/dim]"
        child = rich_parent.add(label)
        for cid in node.children:
            _add_subtree(child, cid)

    rich_tree = RichTree(f"[bold cyan]主题树[/bold cyan] ({tree.meta.total_nodes} 节点, depth={tree.meta.depth})")
    for root_id in tree.root_ids:
        _add_subtree(rich_tree, root_id)

    con.print(rich_tree)
