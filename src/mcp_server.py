"""
MCP Server 包装层 — 将 pipeline 能力暴露为 MCP 工具，供 Claude Desktop / Cursor / WorkBuddy 调用。

Phase 3 才完整实现。本期仅提供骨架，且 mcp 包未安装时也能 import 此模块（仅 run() 会失败）。

启动方式（Phase 3）:
    pip install -e .[mcp]
    python -m src.mcp_server

MCP 配置（~/.workbuddy/mcp.json）:
    {
      "mcpServers": {
        "ai-worklog": {
          "command": "python",
          "args": ["-m", "src.mcp_server"],
          "cwd": "C:/Users/Exception2Rule/ai-worklog-skill"
        }
      }
    }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# 延迟 import mcp，避免未装时整个模块导入失败
try:
    from mcp.server.fastmcp import FastMCP
    _MCP_AVAILABLE = True
except ImportError:
    FastMCP = None  # type: ignore[assignment,misc]
    _MCP_AVAILABLE = False

from src import pipeline


def _build_server() -> "FastMCP":
    """构建 FastMCP 实例并注册工具。Phase 3 实现。"""
    if not _MCP_AVAILABLE:
        raise ImportError(
            "mcp 包未安装。请运行: pip install -e .[mcp]\n"
            "MCP 包装在 Phase 3 才启用。"
        )

    mcp = FastMCP("ai-worklog-parser")

    @mcp.tool()
    def parse_conversations(
        input_path: str,
        provider: str = "auto",
        out_format: str = "json",
        outdir: str = "./output",
        timezone: str = "Asia/Shanghai",
    ) -> str:
        """
        解析 LLM 平台导出的对话记录为统一格式。

        Args:
            input_path: 导出文件路径 (JSON/JSONL/HTML/ZIP)
            provider: 平台标识，auto 自动探测；可选 openai/google/claude/...
            out_format: 输出格式 json|jsonl|markdown
            outdir: 输出目录
            timezone: 时区归一化目标

        Returns:
            JSON 字符串，含解析后的 UnifiedSession 列表
        """
        sessions = pipeline.run(
            input_path=Path(input_path),
            provider=provider,
            out_format=out_format,  # type: ignore[arg-type]
            outdir=Path(outdir),
            timezone_str=timezone,
        )
        return json.dumps(
            [s.model_dump(mode="json") for s in sessions],
            ensure_ascii=False, indent=2,
        )

    @mcp.tool()
    def query_worklog(
        db_path: str,
        date: Optional[str] = None,
        provider: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> str:
        """查询已落库的对话记录。Phase 2 实现。"""
        # TODO Phase 2
        return json.dumps({"error": "query_worklog 待 Phase 2 实现"}, ensure_ascii=False)

    return mcp


def main() -> None:
    """MCP server 入口。"""
    if not _MCP_AVAILABLE:
        print(
            "❌ mcp 包未安装。\n\n"
            "请运行:\n"
            "  pip install -e .[mcp]\n\n"
            "MCP 包装在 Phase 3 才启用，本期（Phase 0）仅提供骨架。"
        )
        return

    server = _build_server()
    server.run()


if __name__ == "__main__":
    main()
