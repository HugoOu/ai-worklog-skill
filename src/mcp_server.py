"""
MCP Server — 将 aiworklog CLI 能力暴露为 MCP 工具，供 Claude Desktop / Cursor / WorkBuddy 调用。

注册的 MCP 工具：
  1. parse_conversations — 解析单个 LLM 导出文件为统一格式
  2. cluster_conversations — 端到端聚类（parse → bridge → LLM 聚类）
  3. list_adapters — 列出已注册的平台 adapter

启动方式:
    pip install -e .[mcp]
    python -m src.mcp_server

MCP 配置（~/.workbuddy/mcp.json）:
    {
      "mcpServers": {
        "ai-worklog": {
          "command": "C:/Users/Exception2Rule/ai-worklog-skill/.venv/Scripts/python.exe",
          "args": ["-m", "src.mcp_server"],
          "cwd": "C:/Users/Exception2Rule/ai-worklog-skill"
        }
      }
    }
"""
from __future__ import annotations

import json
import traceback
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
from src.adapters import REGISTRY


def _build_server() -> "FastMCP":
    """构建 FastMCP 实例并注册工具。"""
    if not _MCP_AVAILABLE:
        raise ImportError(
            "mcp 包未安装。请运行: pip install -e .[mcp]"
        )

    mcp = FastMCP("ai-worklog-parser")

    # ==========================================
    # 工具 1: parse_conversations
    # ==========================================
    @mcp.tool()
    def parse_conversations(
        input_path: str,
        provider: str = "auto",
        out_format: str = "json",
        outdir: str = "./output",
        timezone: str = "Asia/Shanghai",
    ) -> str:
        """
        解析 LLM 平台导出的对话记录为统一格式（UnifiedSession）。

        支持的平台：ChatGPT (conversations.json)、Gemini (My Activity HTML)。
        自动探测格式，也可显式指定 provider。

        Args:
            input_path: 导出文件路径 (JSON/HTML/ZIP)
            provider: 平台标识，auto 自动探测；可选 openai/google
            out_format: 输出格式 json|jsonl
            outdir: 输出目录（生成 unified_sessions.json）
            timezone: 时区归一化目标（如 Asia/Shanghai）

        Returns:
            JSON 字符串，含解析后的会话列表，每个会话含 messages 数组。
            每条消息含 role/content/provider/model/created_at 等字段。
        """
        try:
            sessions = pipeline.run(
                input_path=Path(input_path),
                provider=provider,
                out_format=out_format,  # type: ignore[arg-type]
                outdir=Path(outdir),
                timezone_str=timezone,
            )
            result = {
                "success": True,
                "session_count": len(sessions),
                "message_count": sum(len(s.messages) for s in sessions),
                "sessions": [s.model_dump(mode="json") for s in sessions],
            }
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }, ensure_ascii=False, indent=2)

    # ==========================================
    # 工具 2: cluster_conversations
    # ==========================================
    @mcp.tool()
    def cluster_conversations(
        input_paths: str,
        outdir: str = "./output",
        timezone: str = "Asia/Shanghai",
        dry_run: bool = False,
    ) -> str:
        """
        端到端聚类：解析多平台导出 → 按天归集 → LLM 聚类 → 输出候选工作项。

        支持混合多个平台的导出文件，自动合并到同一时间线。
        dry_run=True 时只做 parse + 按天归集，不调 LLM（快速预览数据分布）。
        dry_run=False 时调 LLM 聚类（有延迟和费用），输出候选工作项。

        Args:
            input_paths: 多个导出文件路径，用逗号分隔（如 "chatgpt.json,gemini.html"）
            outdir: 输出目录
            timezone: 时区归一化目标
            dry_run: True=只预览按天归集不调LLM；False=完整聚类

        Returns:
            JSON 字符串。dry_run 时含按天归集摘要；完整聚类时含候选工作项列表。
            候选工作项每个含 topic/summary/evidence/dates 字段。
        """
        try:
            from src.bridge import unified_to_daily
            from src.unified_schema import UnifiedSession

            # 解析输入路径（逗号分隔）
            paths = [Path(p.strip()) for p in input_paths.split(",") if p.strip()]
            if not paths:
                return json.dumps({"success": False, "error": "未提供输入文件路径"}, ensure_ascii=False)

            # 1. 解析每个文件
            all_sessions: list[UnifiedSession] = []
            for p in paths:
                if not p.exists():
                    return json.dumps({"success": False, "error": f"文件不存在: {p}"}, ensure_ascii=False)
                sessions = pipeline.run(p, provider="auto", timezone_str=timezone)
                all_sessions.extend(sessions)

            # 2. 按天归集
            daily = unified_to_daily(all_sessions)

            # 输出文件
            outdir_path = Path(outdir)
            outdir_path.mkdir(parents=True, exist_ok=True)

            daily_file = outdir_path / "daily_conversations.json"
            daily_file.write_text(
                json.dumps([d.model_dump(mode="json") for d in daily], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            unified_file = outdir_path / "unified_sessions.json"
            unified_file.write_text(
                json.dumps([s.model_dump(mode="json") for s in all_sessions], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            if dry_run:
                result = {
                    "success": True,
                    "mode": "dry_run",
                    "session_count": len(all_sessions),
                    "day_count": len(daily),
                    "daily_summary": [
                        {"date": d.date, "message_count": len(d.messages)}
                        for d in daily
                    ],
                    "output_files": [str(daily_file), str(unified_file)],
                }
                return json.dumps(result, ensure_ascii=False, indent=2)

            # 3. LLM 聚类
            from src.clustering import MapReduceClustering

            clusterer = MapReduceClustering()
            candidates = clusterer.cluster(daily)

            # 输出 candidates.json
            candidates_file = outdir_path / "candidates.json"
            candidates_file.write_text(
                json.dumps([c.model_dump(mode="json") for c in candidates], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            result = {
                "success": True,
                "mode": "full_clustering",
                "session_count": len(all_sessions),
                "day_count": len(daily),
                "candidate_count": len(candidates),
                "candidates": [c.model_dump(mode="json") for c in candidates],
                "output_files": [str(unified_file), str(daily_file), str(candidates_file)],
            }
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }, ensure_ascii=False, indent=2)

    # ==========================================
    # 工具 3: list_adapters
    # ==========================================
    @mcp.tool()
    def list_adapters() -> str:
        """
        列出所有已注册的平台 adapter。

        Returns:
            JSON 字符串，含 adapter 列表（provider 标识 + 类名 + 状态）。
        """
        adapters = [
            {"provider": cls.provider, "class": cls.__name__, "status": "registered"}
            for cls in REGISTRY
        ]
        return json.dumps({
            "success": True,
            "adapter_count": len(adapters),
            "adapters": adapters,
        }, ensure_ascii=False, indent=2)

    # ==========================================
    # 工具 4: generate_worklog
    # ==========================================
    @mcp.tool()
    def generate_worklog(
        candidates_path: str,
        select_indices: str = "",
        date_range: str = "",
        polish: bool = True,
        outdir: str = "./output",
    ) -> str:
        """
        从候选工作项（candidates.json）生成 Markdown 工作日志。

        筛选方式（互斥，优先级从高到低）：
        - select_indices: 逗号分隔索引（如 "2,3,9"），空字符串=全选
        - date_range: 日期范围（如 "2026-05-20:2026-05-21"），空字符串=不筛选

        Args:
            candidates_path: candidates.json 文件路径
            select_indices: 选中索引（逗号分隔，从 1 开始），空=不按索引筛选
            date_range: 日期范围 "YYYY-MM-DD:YYYY-MM-DD"，空=不按日期筛选
            polish: 是否调 LLM 润色为正式工作日志语言
            outdir: 输出目录（生成 worklog.md）

        Returns:
            JSON 字符串，含 success 字段和生成的 Markdown 工作日志内容。
        """
        try:
            from src.models import CandidateItem
            from src.generator import (
                filter_by_indices, filter_by_date_range,
                generate_markdown, _parse_indices,
            )

            # 加载候选
            path = Path(candidates_path)
            if not path.exists():
                return json.dumps({"success": False, "error": f"文件不存在: {candidates_path}"}, ensure_ascii=False)
            data = json.loads(path.read_text(encoding="utf-8"))
            candidates = [CandidateItem(**c) for c in data]

            # 筛选
            if select_indices:
                indices = _parse_indices(select_indices)
                selected = filter_by_indices(candidates, indices)
            elif date_range:
                parts = date_range.split(":")
                if len(parts) != 2:
                    return json.dumps({"success": False, "error": "日期范围格式应为 YYYY-MM-DD:YYYY-MM-DD"}, ensure_ascii=False)
                selected = filter_by_date_range(candidates, parts[0], parts[1])
            else:
                selected = candidates  # 默认全选

            if not selected:
                return json.dumps({"success": True, "message": "未选中任何候选", "worklog": ""}, ensure_ascii=False)

            # 生成 Markdown
            md = generate_markdown(selected, polish)

            # 写入文件
            outdir_path = Path(outdir)
            outdir_path.mkdir(parents=True, exist_ok=True)
            out_file = outdir_path / "worklog.md"
            out_file.write_text(md, encoding="utf-8")

            result = {
                "success": True,
                "selected_count": len(selected),
                "total_candidates": len(candidates),
                "output_file": str(out_file),
                "worklog": md,
            }
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }, ensure_ascii=False, indent=2)

    return mcp


def main() -> None:
    """MCP server 入口。"""
    if not _MCP_AVAILABLE:
        print(
            "mcp 包未安装。\n\n"
            "请运行:\n"
            "  pip install -e .[mcp]\n\n"
            "然后重新启动 MCP server。"
        )
        return

    server = _build_server()
    server.run()


if __name__ == "__main__":
    main()
