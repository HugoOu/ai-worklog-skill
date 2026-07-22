"""
Adapter 抽象基类 — 所有平台 adapter 的统一接口。

每个 adapter 实现两个方法：
- `parse(path)`: 解析导出文件，返回 UnifiedSession 列表
- `detect(path)`: 格式探测置信度 [0, 1]，pipeline 据此自动选 adapter

后续接入新平台只需：
1. 创建 src/adapters/xxx.py，继承 BaseAdapter
2. 实现 parse() 和 detect()
3. 在 __init__.py 的 REGISTRY 中注册
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.unified_schema import UnifiedSession


class BaseAdapter(ABC):
    """所有平台 adapter 的统一接口。"""

    # 子类必填：provider 标识（与 UnifiedSession.provider 对应）
    provider: str = "unknown"

    # 子类可覆盖：支持的文件扩展名（用于 detect 启发式）
    supported_extensions: tuple[str, ...] = (".json", ".jsonl", ".html", ".zip")

    @abstractmethod
    def parse(self, path: Path) -> list[UnifiedSession]:
        """解析导出文件，返回统一会话列表。

        Args:
            path: 导出文件路径

        Returns:
            UnifiedSession 列表（可能含多个会话）

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式不符合预期
        """
        ...

    def detect(self, path: Path) -> float:
        """格式探测置信度 [0, 1]。

        - 1.0: 文件特征完全匹配（如 ChatGPT 的 conversations.json 顶层有 'title' + 'mapping'）
        - 0.5: 仅扩展名匹配
        - 0.0: 明确不匹配

        pipeline 选取置信度最高的 adapter；默认实现仅检查扩展名，子类应覆盖以提供更精准探测。

        Args:
            path: 待探测文件路径

        Returns:
            置信度 [0, 1]
        """
        if path.suffix.lower() in self.supported_extensions:
            return 0.5
        return 0.0
