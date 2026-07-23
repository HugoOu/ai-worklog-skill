"""共享 pytest fixtures。"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def examples_dir() -> Path:
    """测试样本目录（真实导出文件）。"""
    return Path(__file__).parent.parent / "examples"


@pytest.fixture
def chatgpt_sample_path(examples_dir: Path) -> Path:
    """ChatGPT 真实导出样本路径（examples/conversations.json）。"""
    return examples_dir / "conversations.json"


@pytest.fixture
def gemini_sample_path(examples_dir: Path) -> Path:
    """Gemini 真实导出样本路径（examples/gemini_1000.html）。"""
    return examples_dir / "gemini_1000.html"
