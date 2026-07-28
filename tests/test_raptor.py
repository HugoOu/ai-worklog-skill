"""
RAPTOR 递归聚类树构建测试（mock embedding，不打 API）。
"""
from unittest.mock import patch

import numpy as np

from src.models import CandidateItem
from src.raptor import build_topic_tree, _strip_suffix


def _fake_embed(texts):
    """
    确定性假 embedding：按文本首字符分组。
    - 以 'R' 开头的 → 同一簇（向量相近）
    - 其余 → 各自独立
    """
    vecs = []
    for t in texts:
        if t.startswith("R"):
            vecs.append([1.0, 0.0, 0.0])
        elif t.startswith("M"):
            vecs.append([0.0, 1.0, 0.0])
        else:
            vecs.append([0.0, 0.0, 1.0])
    return np.array(vecs, dtype=np.float32)


def _make_candidates():
    return [
        CandidateItem(topic="RAGFlow检索调优", summary="检索相似度", dates=["2026-04-14"]),
        CandidateItem(topic="RAGFlow切片策略", summary="chunking", dates=["2026-04-15"]),
        CandidateItem(topic="MinerU部署", summary="本地部署", dates=["2026-04-16"]),
        CandidateItem(topic="开题报告撰写", summary="文献综述", dates=["2026-03-26"]),
    ]


def test_strip_suffix():
    """_strip_suffix 去除末尾单个 '等N项' 后缀。"""
    assert _strip_suffix("参考文献整理等2项") == "参考文献整理"
    assert _strip_suffix("RAGFlow检索") == "RAGFlow检索"
    assert _strip_suffix("预处理等4项等2项") == "预处理等4项"  # 只剥离末尾一个


@patch("src.raptor.embed_texts", side_effect=_fake_embed)
def test_build_tree_basic_structure(mock_embed):
    """构建树：4 叶子 → 应有聚类父节点，root 数 < 4。"""
    candidates = _make_candidates()
    tree = build_topic_tree(candidates, distance_threshold=0.5, log=lambda m: None)

    # 4 个叶子 + 至少 1 个父节点
    assert tree.meta.total_nodes > 4
    # 根节点数应少于叶子数（发生了聚合）
    assert len(tree.root_ids) < 4
    # 所有 root 都在 nodes 字典里
    for rid in tree.root_ids:
        assert rid in tree.nodes


@patch("src.raptor.embed_texts", side_effect=_fake_embed)
def test_build_tree_sessions_reachable(mock_embed):
    """从 root 递归应能覆盖所有叶子。"""
    candidates = _make_candidates()
    tree = build_topic_tree(candidates, distance_threshold=0.5, log=lambda m: None)

    # 收集所有 depth-0 叶子的 label
    leaf_labels = {n.label for n in tree.nodes.values() if n.depth == 0}
    expected = {c.topic for c in candidates}
    assert leaf_labels == expected


@patch("src.raptor.embed_texts", side_effect=_fake_embed)
def test_build_tree_json_roundtrip(mock_embed):
    """树 JSON round-trip 后结构一致。"""
    candidates = _make_candidates()
    tree = build_topic_tree(candidates, distance_threshold=0.5, log=lambda m: None)

    from src.models import TopicTree
    restored = TopicTree.from_json(tree.to_json())
    assert restored.meta.total_nodes == tree.meta.total_nodes
    assert len(restored.root_ids) == len(tree.root_ids)


def test_build_tree_empty():
    """空输入返回空树。"""
    tree = build_topic_tree([], log=lambda m: None)
    assert tree.meta.total_nodes == 0
    assert tree.root_ids == []


def test_build_tree_single():
    """单个候选 → 1 叶子即 root，无聚合。"""
    candidates = [CandidateItem(topic="唯一主题", summary="s", dates=["2026-01-01"])]
    tree = build_topic_tree(candidates, log=lambda m: None)
    assert tree.meta.total_nodes == 1
    assert len(tree.root_ids) == 1


@patch("src.raptor.embed_texts", side_effect=_fake_embed)
def test_session_ids_propagate_to_tree(mock_embed):
    """证据链：候选的 session_ids 应贯穿到叶子，并被父节点聚合。"""
    candidates = [
        CandidateItem(topic="RAGFlow检索调优", summary="检索相似度",
                      dates=["2026-04-14"], session_ids=["sess-A"]),
        CandidateItem(topic="RAGFlow切片策略", summary="chunking",
                      dates=["2026-04-15"], session_ids=["sess-B"]),
        CandidateItem(topic="MinerU部署", summary="本地部署",
                      dates=["2026-04-16"], session_ids=["sess-C"]),
    ]
    tree = build_topic_tree(candidates, distance_threshold=0.5, log=lambda m: None)

    # 叶子节点应携带各自的 session_ids
    leaves = {n.label: n for n in tree.nodes.values() if n.depth == 0}
    assert leaves["RAGFlow检索调优"].session_ids == ["sess-A"]
    assert leaves["MinerU部署"].session_ids == ["sess-C"]

    # 每个 root 的 session_ids 应等于其子树下所有叶子的并集
    for rid in tree.root_ids:
        node = tree.nodes[rid]
        if node.depth == 0:
            continue
        # 父节点 session_ids 非空，且与递归收集一致
        recursive = set(tree.get_sessions_under(rid))
        assert set(node.session_ids) == recursive
        assert node.session_ids  # 非空

    # 所有 session 都能从树中被找到
    all_sessions = set()
    for rid in tree.root_ids:
        all_sessions.update(tree.get_sessions_under(rid))
    assert all_sessions == {"sess-A", "sess-B", "sess-C"}
