"""共享 pytest fixtures。"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """测试样本目录。"""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def chatgpt_sample_path(fixtures_dir: Path) -> Path:
    """ChatGPT 测试样本路径。"""
    return fixtures_dir / "chatgpt_sample.json"


@pytest.fixture
def gemini_sample_path() -> Path:
    """Gemini 测试样本路径（用项目自带的 examples/gemini_1000.html）。"""
    return Path(__file__).parent.parent / "examples" / "gemini_1000.html"
