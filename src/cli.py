"""
typer CLI 入口 — Agent 与 shell 调用的统一界面。

命令:
  aiworklog parse <input> [-p auto] [-f json] [-o ./output]
  aiworklog parse-batch <dir> [--pattern] [-o ./output]
  aiworklog query [--db] [--date] [--provider] [--keyword]
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from src import pipeline
from src.adapters import REGISTRY

app = typer.Typer(
    name="aiworklog",
    help="AI Worklog — 多平台 LLM 对话解析器（ChatGPT / Gemini / ...）",
    no_args_is_help=True,
)
console = Console()


# ==========================================
# parse — 解析单个文件
# ==========================================
@app.command()
def parse(
    input_path: Path = typer.Argument(
        ..., help="导出文件路径 (JSON/JSONL/HTML/ZIP)"
    ),
    provider: str = typer.Option(
        "auto", "--provider", "-p",
        help="平台标识：auto(自动探测) | openai | google | claude | ...",
    ),
    out_format: str = typer.Option(
        "json", "--format", "-f",
        help="输出格式：json | jsonl | markdown",
    ),
    outdir: Path = typer.Option(
        Path("./output"), "--outdir", "-o", help="输出目录"
    ),
    timezone: str = typer.Option(
        "Asia/Shanghai", "--tz", help="时区归一化目标"
    ),
    group_by_date: bool = typer.Option(
        False, "--group-by-date",
        help="按天分组（与下游 clustering 衔接用）",
    ),
):
    """解析单个 LLM 导出文件为统一格式。"""
    if not input_path.exists():
        console.print(f"[red]错误：文件不存在 {input_path}[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]解析中[/cyan] {input_path} (provider={provider}) ...")

    try:
        sessions = pipeline.run(
            input_path=input_path,
            provider=provider,
            out_format=out_format,  # type: ignore[arg-type]
            outdir=outdir,
            timezone_str=timezone,
            group_by_date=group_by_date,
        )
    except NotImplementedError as e:
        console.print(f"[yellow]⏳ {e}[/yellow]")
        raise typer.Exit(2)
    except Exception as e:
        console.print(f"[red]解析失败：{e}[/red]")
        raise typer.Exit(1)

    # 打印摘要
    table = Table(title="解析结果摘要")
    table.add_column("会话 ID", style="cyan", no_wrap=False)
    table.add_column("标题", style="white")
    table.add_column("Provider", style="green")
    table.add_column("消息数", justify="right", style="yellow")
    table.add_column("创建时间", style="dim")

    for s in sessions:
        table.add_row(
            s.id[:12] + "...",
            (s.title or "(无标题)")[:40],
            s.provider,
            str(len(s.messages)),
            s.created_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)
    console.print(f"\n[green]✅ 共 {len(sessions)} 个会话 → {outdir}[/green]")


# ==========================================
# parse-batch — 批量解析目录
# ==========================================
@app.command(name="parse-batch")
def parse_batch(
    input_dir: Path = typer.Argument(..., help="批量扫描目录"),
    pattern: str = typer.Option(
        "**/*.{json,jsonl,html,zip}", "--pattern", help="glob 匹配模式"
    ),
    outdir: Path = typer.Option(Path("./output"), "--outdir", "-o"),
):
    """批量扫描目录下所有导出文件。"""
    if not input_dir.is_dir():
        console.print(f"[red]错误：不是目录 {input_dir}[/red]")
        raise typer.Exit(1)

    files = list(input_dir.glob(pattern))
    if not files:
        console.print(f"[yellow]未找到匹配文件: {input_dir}/{pattern}[/yellow]")
        raise typer.Exit(1)

    console.print(f"[cyan]发现 {len(files)} 个文件[/cyan]")
    for f in files:
        console.print(f"  • {f}")

    # TODO Phase 1: 循环调用 pipeline.run()
    console.print("[yellow]⏳ 批量解析待 Phase 1 实现[/yellow]")


# ==========================================
# query — 查询已落库对话
# ==========================================
@app.command()
def query(
    db_path: Path = typer.Option(Path("./worklog.db"), "--db", help="SQLite 数据库路径"),
    date: Optional[str] = typer.Option(None, "--date", help="按日期过滤 YYYY-MM-DD"),
    provider: Optional[str] = typer.Option(None, "--provider", help="按平台过滤"),
    keyword: Optional[str] = typer.Option(None, "--keyword", help="关键词搜索"),
):
    """查询已落库的对话记录。"""
    if not db_path.exists():
        console.print(f"[red]错误：数据库不存在 {db_path}[/red]")
        raise typer.Exit(1)

    # TODO Phase 2: 实现 SQLite 查询
    console.print("[yellow]⏳ 查询功能待 Phase 2 实现[/yellow]")


# ==========================================
# adapters — 列出已注册 adapter
# ==========================================
@app.command()
def adapters():
    """列出所有已注册的 adapter。"""
    table = Table(title="已注册 Adapter")
    table.add_column("Provider", style="green")
    table.add_column("类名", style="cyan")
    table.add_column("状态", style="yellow")

    if not REGISTRY:
        console.print("[yellow]⚠️  REGISTRY 为空（Phase 0 骨架阶段，adapter 待 Phase 1 实现）[/yellow]")
        return

    for cls in REGISTRY:
        table.add_row(cls.provider, cls.__name__, "✅ 已注册")

    console.print(table)


if __name__ == "__main__":
    app()
