"""
新数据结构的单元测试：
- DayMapCache / CandidateTopic / MapRunMeta / MessageRef
- TopicTree / TopicNode 层级遍历与 JSON round-trip
- DailyConversation.content_hash 确定性
"""
import json
from src.models import (
    ConversationMessage,
    DailyConversation,
    MessageRef,
    CandidateTopic,
    MapRunMeta,
    DayMapCache,
    TopicNode,
    TopicTree,
    TopicTreeMeta,
    CandidateItem,
    WorkItem,
    WorklogData,
)


# ============================================================
# DailyConversation.content_hash
# ============================================================

def test_content_hash_deterministic():
    """相同消息内容应产出相同 hash。"""
    msgs = [
        ConversationMessage(role="user", content="hello", date="2026-01-01"),
        ConversationMessage(role="assistant", content="world", date="2026-01-01"),
    ]
    dc1 = DailyConversation(date="2026-01-01", messages=msgs)
    dc2 = DailyConversation(date="2026-01-01", messages=msgs)
    assert dc1.content_hash == dc2.content_hash


def test_content_hash_changes_with_content():
    """消息内容不同应产出不同 hash。"""
    dc1 = DailyConversation(date="2026-01-01", messages=[
        ConversationMessage(role="user", content="hello", date="2026-01-01"),
    ])
    dc2 = DailyConversation(date="2026-01-01", messages=[
        ConversationMessage(role="user", content="goodbye", date="2026-01-01"),
    ])
    assert dc1.content_hash != dc2.content_hash


# ============================================================
# CandidateTopic 自动 ID
# ============================================================

def test_candidate_topic_auto_id():
    """未提供 candidate_id 时应自动生成。"""
    ct = CandidateTopic(topic="RAG学习", summary="系统学习RAG", date="2026-04-14")
    assert ct.candidate_id
    assert len(ct.candidate_id) == 12


def test_candidate_topic_explicit_id():
    """提供 candidate_id 时应保留。"""
    ct = CandidateTopic(candidate_id="abc123", topic="test", summary="test")
    assert ct.candidate_id == "abc123"


# ============================================================
# DayMapCache
# ============================================================

def test_day_map_cache_valid():
    """有候选且未截断 → is_valid True。"""
    cache = DayMapCache(
        cache_key="abc123",
        date="2026-04-14",
        input_message_count=18,
        map_run=MapRunMeta(
            run_id="run001",
            model="qwen3.7-flash",
            created_at="2026-07-29T00:00:00+08:00",
        ),
        candidates=[CandidateTopic(topic="RAG", summary="学习RAG")],
    )
    assert cache.is_valid


def test_day_map_cache_invalid_truncated():
    """截断 → is_valid False。"""
    cache = DayMapCache(
        cache_key="abc123",
        date="2026-04-14",
        map_run=MapRunMeta(
            run_id="run001",
            model="qwen3.7-flash",
            created_at="2026-07-29T00:00:00+08:00",
            truncated=True,
        ),
        candidates=[CandidateTopic(topic="RAG", summary="学习RAG")],
    )
    assert not cache.is_valid


def test_day_map_cache_json_roundtrip():
    """JSON 序列化/反序列化 round-trip。"""
    cache = DayMapCache(
        cache_key="abc123",
        date="2026-04-14",
        input_message_count=5,
        map_run=MapRunMeta(
            run_id="run001",
            model="qwen3.7-flash",
            created_at="2026-07-29T00:00:00+08:00",
            duration_ms=3200,
            finish_reason="stop",
        ),
        candidates=[
            CandidateTopic(
                topic="MinerU部署",
                summary="本地部署MinerU",
                source_refs=[
                    MessageRef(
                        session_id="sess-001",
                        message_index=2,
                        role="user",
                        preview="我现在想在 RAGFlow GUI 的模型供应商页面中加入 MinerU...",
                    )
                ],
            )
        ],
    )
    json_str = cache.model_dump_json()
    restored = DayMapCache.model_validate_json(json_str)
    assert restored.cache_key == cache.cache_key
    assert restored.candidates[0].source_refs[0].session_id == "sess-001"


# ============================================================
# TopicTree 层级遍历
# ============================================================

def _build_sample_tree() -> TopicTree:
    """构建一棵示例树：
    depth 3: 船检法规RAG知识库 (role_hint=project)
      ├─ depth 2: MinerU集成 (role_hint=component)
      │    ├─ depth 1: 本地部署 (role_hint=task)
      │    │    └─ depth 0: sess-001 (叶子)
      │    └─ depth 1: 排障修复 (role_hint=task)
      │         └─ depth 0: sess-002 (叶子)
      └─ depth 2: 检索调优 (role_hint=component)
           └─ depth 1: CoT截断修复 (role_hint=task)
                └─ depth 0: sess-003 (叶子)
    """
    nodes = {}

    # Leaves (depth=0)
    for sid, label in [("sess-001", "MinerU部署对话"), ("sess-002", "MinerU排障"), ("sess-003", "CoT截断")]:
        nodes[sid] = TopicNode(
            node_id=sid,
            depth=0,
            label=label,
            session_ids=[sid],
            dates=["2026-04-16"],
        )

    # depth 1 (task)
    nodes["task-deploy"] = TopicNode(node_id="task-deploy", depth=1, role_hint="task", label="本地部署", children=["sess-001"], dates=["2026-04-16"])
    nodes["task-fix"] = TopicNode(node_id="task-fix", depth=1, role_hint="task", label="排障修复", children=["sess-002"], dates=["2026-05-19"])
    nodes["task-cot"] = TopicNode(node_id="task-cot", depth=1, role_hint="task", label="CoT截断修复", children=["sess-003"], dates=["2026-05-13"])

    # depth 2 (component)
    nodes["comp-mineru"] = TopicNode(node_id="comp-mineru", depth=2, role_hint="component", label="MinerU集成", children=["task-deploy", "task-fix"], dates=["2026-04-16", "2026-05-19"])
    nodes["comp-retrieval"] = TopicNode(node_id="comp-retrieval", depth=2, role_hint="component", label="检索调优", children=["task-cot"], dates=["2026-05-13"])

    # depth 3 (project)
    nodes["proj-rag"] = TopicNode(node_id="proj-rag", depth=3, role_hint="project", label="船检法规RAG知识库", children=["comp-mineru", "comp-retrieval"], dates=["2026-04-16", "2026-05-13", "2026-05-19"])

    # Set parent_ids
    nodes["sess-001"].parent_id = "task-deploy"
    nodes["sess-002"].parent_id = "task-fix"
    nodes["sess-003"].parent_id = "task-cot"
    nodes["task-deploy"].parent_id = "comp-mineru"
    nodes["task-fix"].parent_id = "comp-mineru"
    nodes["task-cot"].parent_id = "comp-retrieval"
    nodes["comp-mineru"].parent_id = "proj-rag"
    nodes["comp-retrieval"].parent_id = "proj-rag"

    meta = TopicTreeMeta(
        tree_id="tree-001",
        created_at="2026-07-29T00:00:00+08:00",
        method="embedding_raptor",
        total_sessions=3,
        total_nodes=len(nodes),
        depth=4,
    )
    return TopicTree(meta=meta, nodes=nodes, root_ids=["proj-rag"])


def test_tree_get_children():
    tree = _build_sample_tree()
    children = tree.get_children("proj-rag")
    assert len(children) == 2
    labels = {c.label for c in children}
    assert "MinerU集成" in labels
    assert "检索调优" in labels


def test_tree_get_sessions_under_project():
    tree = _build_sample_tree()
    sessions = tree.get_sessions_under("proj-rag")
    assert set(sessions) == {"sess-001", "sess-002", "sess-003"}


def test_tree_get_sessions_under_component():
    tree = _build_sample_tree()
    sessions = tree.get_sessions_under("comp-mineru")
    assert set(sessions) == {"sess-001", "sess-002"}


def test_tree_json_roundtrip():
    tree = _build_sample_tree()
    json_str = tree.to_json()
    restored = TopicTree.from_json(json_str)
    assert restored.meta.tree_id == "tree-001"
    assert len(restored.nodes) == len(tree.nodes)
    assert restored.get_sessions_under("proj-rag") == tree.get_sessions_under("proj-rag")


def test_tree_node_embedding_field():
    """embedding 字段可存储向量。"""
    node = TopicNode(
        node_id="n1",
        depth=1,
        role_hint="task",
        label="test",
        embedding=[0.1, 0.2, 0.3],
        embedding_model="text-embedding-v3",
    )
    assert node.embedding == [0.1, 0.2, 0.3]
    assert node.embedding_model == "text-embedding-v3"


# ============================================================
# 兼容层
# ============================================================

def test_candidate_item_compat():
    """旧 CandidateItem 仍可用。"""
    ci = CandidateItem(topic="test", summary="test summary", evidence="some text", dates=["2026-01-01"])
    assert ci.topic == "test"


def test_worklog_data_compat():
    wd = WorklogData(date="2026-01-01", work_items=[
        WorkItem(task="task1", detail="detail1", evidence="ev1")
    ])
    assert len(wd.work_items) == 1
