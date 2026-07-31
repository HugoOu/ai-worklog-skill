"""generator.py 单元测试 — 筛选 + 转换 + Markdown 格式化。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.generator import (
    filter_by_indices,
    filter_by_date_range,
    interactive_select,
    candidate_to_workitem,
    generate_markdown,
    generate_worklog,
    _parse_indices,
    select_by_tree_nodes,
    flatten_tree_numbered,
    interactive_tree_select,
)
from src.models import CandidateItem, WorkItem, TopicTree, TopicTreeMeta, TopicNode


# ==========================================
# 测试 fixtures
# ==========================================

@pytest.fixture
def sample_candidates() -> list[CandidateItem]:
    """构造 3 个测试候选。"""
    return [
        CandidateItem(
            topic="开题报告撰写",
            summary="撰写国内研究综述、研究方法等章节",
            evidence="现在我已经有了...",
            dates=["2026-03-26"],
        ),
        CandidateItem(
            topic="FDM下载工具配置",
            summary="配置FDM扩展嗅探视频下载链接",
            evidence="目前只能在点击下载时唤起FDM",
            dates=["2026-05-20", "2026-05-21"],
        ),
        CandidateItem(
            topic="研究生生活费预算",
            summary="计算上财读研每月必要支出",
            evidence="好的，现在我想请你详细计算",
            dates=["2026-02-24"],
        ),
    ]


# ==========================================
# _parse_indices 测试
# ==========================================
class TestParseIndices:
    def test_single(self):
        assert _parse_indices("2") == [2]

    def test_comma_separated(self):
        assert _parse_indices("2,3,9") == [2, 3, 9]

    def test_range(self):
        assert _parse_indices("5-7") == [5, 6, 7]

    def test_mixed(self):
        assert _parse_indices("1,3,5-7") == [1, 3, 5, 6, 7]

    def test_with_spaces(self):
        assert _parse_indices(" 1 , 3 , 5-7 ") == [1, 3, 5, 6, 7]


# ==========================================
# filter_by_indices 测试
# ==========================================
class TestFilterByIndices:
    def test_select_some(self, sample_candidates):
        selected = filter_by_indices(sample_candidates, [2, 3])
        assert len(selected) == 2
        assert selected[0].topic == "FDM下载工具配置"
        assert selected[1].topic == "研究生生活费预算"

    def test_select_all(self, sample_candidates):
        selected = filter_by_indices(sample_candidates, [1, 2, 3])
        assert len(selected) == 3

    def test_out_of_range(self, sample_candidates):
        with pytest.raises(IndexError, match="超出范围"):
            filter_by_indices(sample_candidates, [0])

    def test_out_of_range_high(self, sample_candidates):
        with pytest.raises(IndexError, match="超出范围"):
            filter_by_indices(sample_candidates, [4])


# ==========================================
# filter_by_date_range 测试
# ==========================================
class TestFilterByDateRange:
    def test_select_single_day(self, sample_candidates):
        selected = filter_by_date_range(sample_candidates, "2026-03-26", "2026-03-26")
        assert len(selected) == 1
        assert selected[0].topic == "开题报告撰写"

    def test_select_range(self, sample_candidates):
        selected = filter_by_date_range(sample_candidates, "2026-05-01", "2026-05-31")
        assert len(selected) == 1
        assert selected[0].topic == "FDM下载工具配置"

    def test_select_all(self, sample_candidates):
        selected = filter_by_date_range(sample_candidates, "2026-01-01", "2026-12-31")
        assert len(selected) == 3

    def test_select_none(self, sample_candidates):
        selected = filter_by_date_range(sample_candidates, "2025-01-01", "2025-12-31")
        assert len(selected) == 0

    def test_cross_day_candidate(self, sample_candidates):
        """跨天候选在任一天落在范围内即选中。"""
        selected = filter_by_date_range(sample_candidates, "2026-05-20", "2026-05-20")
        assert len(selected) == 1
        assert selected[0].topic == "FDM下载工具配置"


# ==========================================
# interactive_select 测试
# ==========================================
class TestInteractiveSelect:
    def test_select_some(self, sample_candidates):
        """模拟用户输入 '2,3'。"""
        outputs = []
        result = interactive_select(
            sample_candidates,
            input_func=lambda _: "2,3",
            print_func=lambda *a: outputs.append(a),
        )
        assert len(result) == 2
        assert result[0].topic == "FDM下载工具配置"

    def test_select_empty(self, sample_candidates):
        """模拟用户输入空字符串。"""
        result = interactive_select(
            sample_candidates,
            input_func=lambda _: "",
            print_func=lambda *a: None,
        )
        assert len(result) == 0

    def test_select_range(self, sample_candidates):
        """模拟用户输入 '1-3'。"""
        result = interactive_select(
            sample_candidates,
            input_func=lambda _: "1-3",
            print_func=lambda *a: None,
        )
        assert len(result) == 3


# ==========================================
# candidate_to_workitem 测试
# ==========================================
class TestCandidateToWorkitem:
    def test_direct_mapping(self, sample_candidates):
        """polish=False 时直接映射字段。"""
        item = candidate_to_workitem(sample_candidates[0], polish=False)
        assert isinstance(item, WorkItem)
        assert item.task == "开题报告撰写"
        assert item.detail == "撰写国内研究综述、研究方法等章节"
        assert item.evidence == "现在我已经有了..."


# ==========================================
# generate_markdown 测试
# ==========================================
class TestGenerateMarkdown:
    def test_basic_structure(self, sample_candidates):
        """Markdown 应含 YAML frontmatter + 标题 + 按日期组织。"""
        md = generate_markdown(sample_candidates[:1], polish=False)
        assert md.startswith("---")
        assert "date_range:" in md
        assert "generated_at:" in md
        assert "# 工作日志" in md
        assert "## 2026-03-26" in md
        assert "### 开题报告撰写" in md

    def test_evidence_as_blockquote(self, sample_candidates):
        """证据应转为 Markdown 引用块。"""
        md = generate_markdown(sample_candidates[:1], polish=False)
        assert "> 现在我已经有了..." in md

    def test_cross_day_appears_under_both_dates(self, sample_candidates):
        """跨天候选应在两个日期下都出现。"""
        md = generate_markdown([sample_candidates[1]], polish=False)  # FDM，跨 5-20/5-21
        assert "## 2026-05-20" in md
        assert "## 2026-05-21" in md
        assert "### FDM下载工具配置" in md

    def test_yaml_frontmatter_date_range(self, sample_candidates):
        """YAML frontmatter 的 date_range 应覆盖所有日期。"""
        md = generate_markdown(sample_candidates, polish=False)
        # 3 个候选含 3 个不同日期：2026-02-24, 2026-03-26, 2026-05-20~21
        assert "2026-02-24" in md
        assert "2026-05-21" in md
        assert "total_items: 3" in md


# ==========================================
# generate_worklog 测试（主入口）
# ==========================================
class TestGenerateWorklog:
    def test_select_indices(self, sample_candidates):
        md = generate_worklog(sample_candidates, select_indices=[2], polish=False)
        assert "### FDM下载工具配置" in md
        assert "### 开题报告撰写" not in md

    def test_date_range(self, sample_candidates):
        md = generate_worklog(
            sample_candidates,
            date_range=("2026-03-26", "2026-03-26"),
            polish=False,
        )
        assert "### 开题报告撰写" in md
        assert "### FDM下载工具配置" not in md

    def test_select_all(self, sample_candidates):
        md = generate_worklog(sample_candidates, select_all=True, polish=False)
        assert "### 开题报告撰写" in md
        assert "### FDM下载工具配置" in md
        assert "### 研究生生活费预算" in md

    def test_empty_selection(self, sample_candidates):
        """未选中任何候选时应返回空日志。"""
        md = generate_worklog(sample_candidates, select_indices=[])
        assert "无选中工作项" in md


# ==========================================
# P2：树节点 → 候选投影
# ==========================================

def _make_tree() -> TopicTree:
    """构造一棵测试树：
    root-A (depth=2)
      ├─ comp-1 (depth=1)
      │    ├─ leaf-a1 (depth=0)  2026-05-20
      │    └─ leaf-a2 (depth=0)  2026-05-21
      └─ leaf-a3 (depth=0)        2026-05-22   （单节点簇直接提升）
    root-B (depth=1)
      └─ leaf-b1 (depth=0)        2026-06-01
    """
    nodes = {
        "leaf-a1": TopicNode(node_id="leaf-a1", depth=0, label="RAGFlow分块调优",
                             summary="s", evidence="e-a1", dates=["2026-05-20"], session_ids=["s1"]),
        "leaf-a2": TopicNode(node_id="leaf-a2", depth=0, label="RAGFlow检索过滤",
                             summary="s", evidence="e-a2", dates=["2026-05-21"], session_ids=["s2"]),
        "leaf-a3": TopicNode(node_id="leaf-a3", depth=0, label="MinerU部署",
                             summary="s", evidence="e-a3", dates=["2026-05-22"], session_ids=["s3"]),
        "comp-1": TopicNode(node_id="comp-1", depth=1, label="RAGFlow集成",
                            children=["leaf-a1", "leaf-a2"], dates=["2026-05-20", "2026-05-21"]),
        "root-A": TopicNode(node_id="root-A", depth=2, label="船检RAG知识库",
                            children=["comp-1", "leaf-a3"], dates=["2026-05-20", "2026-05-21", "2026-05-22"]),
        "leaf-b1": TopicNode(node_id="leaf-b1", depth=0, label="开题报告",
                             summary="s", evidence="e-b1", dates=["2026-06-01"], session_ids=["s9"]),
        "root-B": TopicNode(node_id="root-B", depth=1, label="毕业论文",
                            children=["leaf-b1"], dates=["2026-06-01"]),
    }
    meta = TopicTreeMeta(tree_id="t", created_at="2026-07-31T00:00:00+08:00",
                         total_nodes=len(nodes), depth=3)
    return TopicTree(meta=meta, nodes=nodes, root_ids=["root-A", "root-B"])


def test_select_by_tree_nodes_leaf():
    """选叶子 → 单候选，字段透传。"""
    tree = _make_tree()
    items = select_by_tree_nodes(tree, ["leaf-a1"])
    assert len(items) == 1
    assert items[0].topic == "RAGFlow分块调优"
    assert items[0].evidence == "e-a1"
    assert items[0].session_ids == ["s1"]


def test_select_by_tree_nodes_subtree_expansion():
    """选上层节点 → 自动展开整棵子树（决策 1-B）。"""
    tree = _make_tree()
    items = select_by_tree_nodes(tree, ["root-A"])
    assert {i.topic for i in items} == {"RAGFlow分块调优", "RAGFlow检索过滤", "MinerU部署"}


def test_select_by_tree_nodes_dedup_parent_and_child():
    """同时选父+子 → 叶子去重，不重复投影（决策 1-B 边界）。"""
    tree = _make_tree()
    items = select_by_tree_nodes(tree, ["root-A", "comp-1", "leaf-a1"])
    # comp-1 和 leaf-a1 的叶子都已被 root-A 覆盖 → 仍只 3 个
    assert len(items) == 3
    assert {i.topic for i in items} == {"RAGFlow分块调优", "RAGFlow检索过滤", "MinerU部署"}


def test_select_by_tree_nodes_sorted_by_date():
    """投影结果按 (最早日期, topic) 排序，保证确定性。"""
    tree = _make_tree()
    items = select_by_tree_nodes(tree, ["root-B", "root-A"])
    dates = [i.dates[0] for i in items]
    assert dates == sorted(dates)


def test_select_by_tree_nodes_missing_ignored():
    """不存在的节点 ID → 忽略，不影响其他节点。"""
    tree = _make_tree()
    items = select_by_tree_nodes(tree, ["nonexistent", "leaf-b1"])
    assert len(items) == 1
    assert items[0].topic == "开题报告"


def test_flatten_tree_numbered_order():
    """DFS 展平：编号连续，根→子顺序，携带缩进层级。"""
    tree = _make_tree()
    rows = flatten_tree_numbered(tree)
    nums = [r[0] for r in rows]
    assert nums == list(range(1, len(rows) + 1))  # 编号连续
    # 第一个是 root-A（depth=2，缩进 0）
    assert rows[0][1].node_id == "root-A"
    assert rows[0][2] == 0
    # root-A 的第一个孩子是 comp-1（缩进 1）
    assert rows[1][1].node_id == "comp-1"
    assert rows[1][2] == 1


def test_interactive_tree_select_by_number():
    """交互选择：输入编号 → 投影对应子树。"""
    tree = _make_tree()
    rows = flatten_tree_numbered(tree)
    # 找到 comp-1 的编号
    comp1_num = next(n for n, node, _ in rows if node.node_id == "comp-1")
    printed = []
    items = interactive_tree_select(
        tree, input_func=lambda _="": str(comp1_num), print_func=printed.append
    )
    assert {i.topic for i in items} == {"RAGFlow分块调优", "RAGFlow检索过滤"}
    assert any("主题树" in line for line in printed)  # 确认打印了树


def test_interactive_tree_select_empty_defaults_roots():
    """交互选择：回车（空输入）→ 默认选中所有根节点 = 全部叶子。"""
    tree = _make_tree()
    items = interactive_tree_select(tree, input_func=lambda _="": "", print_func=lambda *_: None)
    assert len(items) == 4  # a1,a2,a3,b1


def test_interactive_tree_select_range():
    """交互选择：支持范围语法 1-N。"""
    tree = _make_tree()
    rows = flatten_tree_numbered(tree)
    # 选前两个编号（root-A 及其第一个子节点 comp-1），去重后 = root-A 全部叶子
    items = interactive_tree_select(tree, input_func=lambda _="": "1-2", print_func=lambda *_: None)
    assert {i.topic for i in items} == {"RAGFlow分块调优", "RAGFlow检索过滤", "MinerU部署"}
