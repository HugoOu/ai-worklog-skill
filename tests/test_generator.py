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
)
from src.models import CandidateItem, WorkItem


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
