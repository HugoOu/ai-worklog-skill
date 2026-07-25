"""
工作日志生成器 — 从候选工作项（CandidateItem）筛选并生成工作日志。

流程：
  candidates.json → 用户筛选（索引/日期范围/交互式）→ CandidateItem → WorkItem → Markdown

最简 Markdown 模板：
    ---
    date_range: "2026-05-20 ~ 2026-05-21"
    generated_at: "2026-07-26T01:23:00+08:00"
    ---

    # 工作日志

    ## 2026-05-20

    ### FDM与猫抓下载工具使用问题

    用户多次咨询FDM扩展和猫抓插件...

    > 目前只能在"点击下载"时唤起 FDM...
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List, Optional

from src.models import CandidateItem, WorkItem

tz_sh = timezone(timedelta(hours=8))


# ==========================================
# 筛选函数
# ==========================================

def filter_by_indices(
    candidates: List[CandidateItem], indices: List[int]
) -> List[CandidateItem]:
    """按索引筛选候选工作项（索引从 1 开始）。

    Args:
        candidates: 全部候选
        indices: 选中索引列表（从 1 开始，如 [2, 3, 9]）

    Returns:
        选中的候选子集
    """
    selected = []
    for idx in indices:
        if 1 <= idx <= len(candidates):
            selected.append(candidates[idx - 1])
        else:
            raise IndexError(f"索引 {idx} 超出范围（1-{len(candidates)}）")
    return selected


def filter_by_date_range(
    candidates: List[CandidateItem], date_start: str, date_end: str
) -> List[CandidateItem]:
    """按日期范围筛选候选工作项。

    候选的 dates 列表中任一日期落在 [date_start, date_end] 区间内即选中。

    Args:
        candidates: 全部候选
        date_start: 起始日期 "YYYY-MM-DD"
        date_end: 结束日期 "YYYY-MM-DD"

    Returns:
        日期范围内的候选子集
    """
    selected = []
    for cand in candidates:
        for d in cand.dates:
            if date_start <= d <= date_end:
                selected.append(cand)
                break
    return selected


def interactive_select(
    candidates: List[CandidateItem],
    input_func=input,
    print_func=print,
) -> List[CandidateItem]:
    """交互式筛选候选工作项。

    在终端显示候选列表，用户输入编号选择（如 "2,3,9-11"）。

    Args:
        candidates: 全部候选
        input_func: 输入函数（默认 input，可注入用于测试）
        print_func: 输出函数（默认 print，可注入用于测试）

    Returns:
        选中的候选子集
    """
    print_func(f"\n候选工作项（共 {len(candidates)} 个）：\n")
    for i, cand in enumerate(candidates, 1):
        dates_str = ", ".join(cand.dates) if cand.dates else "无日期"
        cross_day = " [跨天]" if len(cand.dates) > 1 else ""
        print_func(f"  [{i:2d}] {cand.topic} | {dates_str}{cross_day}")

    print_func(f"\n选择要纳入工作日志的项（输入编号，逗号分隔，如 1,3,5-7）:")
    raw = input_func("> ").strip()

    if not raw:
        return []

    # 解析 "1,3,5-7" → [1, 3, 5, 6, 7]
    indices = _parse_indices(raw)
    return filter_by_indices(candidates, indices)


def _parse_indices(raw: str) -> List[int]:
    """解析用户输入的索引字符串。

    支持格式：
      "2,3,9"       → [2, 3, 9]
      "1-3,5,7-9"   → [1, 2, 3, 5, 7, 8, 9]
    """
    indices = []
    for part in raw.split(","):
        part = part.strip()
        if "-" in part:
            # 范围 "5-7"
            start_str, end_str = part.split("-", 1)
            start, end = int(start_str.strip()), int(end_str.strip())
            indices.extend(range(start, end + 1))
        else:
            indices.append(int(part))
    return indices


# ==========================================
# CandidateItem → WorkItem 转换
# ==========================================

def candidate_to_workitem(cand: CandidateItem, polish: bool = False) -> WorkItem:
    """将 CandidateItem 转换为 WorkItem。

    默认直接映射字段（不调 LLM）：
      topic   → task
      summary → detail
      evidence → evidence

    Args:
        cand: 候选工作项
        polish: 是否调 LLM 润色为正式工作日志语言

    Returns:
        WorkItem 实例
    """
    if polish:
        return _polish_candidate(cand)
    return WorkItem(
        task=cand.topic,
        detail=cand.summary,
        evidence=cand.evidence,
    )


def _polish_candidate(cand: CandidateItem) -> WorkItem:
    """调 LLM 把候选润色为正式工作日志语言。"""
    import json
    import os
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv()
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )
    model = os.getenv("LLM_MODEL", "deepseek-chat")

    prompt = (
        "你是工作日志撰写助手。把以下候选工作项润色为正式的工作日志条目。\n"
        "要求：\n"
        "1. task: 简洁的任务名称（10-20字，动宾结构，如'配置FDM视频下载嗅探'）\n"
        "2. detail: 工作过程与产出（50-150字，客观陈述，不含'用户'字样）\n"
        "3. evidence: 原文证据，一字不差保留\n\n"
        f"候选主题: {cand.topic}\n"
        f"候选摘要: {cand.summary}\n"
        f"候选证据: {cand.evidence}\n\n"
        "输出 JSON: {\"task\": \"...\", \"detail\": \"...\", \"evidence\": \"...\"}"
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        data = json.loads(resp.choices[0].message.content)
        return WorkItem(
            task=data["task"],
            detail=data["detail"],
            evidence=cand.evidence,  # evidence 不让 LLM 改，保证一字不差
        )
    except Exception:
        # LLM 调用失败时降级为直接映射
        return WorkItem(task=cand.topic, detail=cand.summary, evidence=cand.evidence)


# ==========================================
# Markdown 格式化
# ==========================================

def generate_markdown(
    candidates: List[CandidateItem],
    polish: bool = False,
) -> str:
    """从候选工作项生成 Markdown 工作日志。

    最简模板：YAML frontmatter + 按日期组织的正文。

    Args:
        candidates: 选中的候选工作项
        polish: 是否调 LLM 润色

    Returns:
        Markdown 字符串
    """
    # 转换为 WorkItem
    work_items = [candidate_to_workitem(c, polish) for c in candidates]

    # 收集所有日期
    all_dates = sorted({d for c in candidates for d in c.dates})
    if all_dates:
        if len(all_dates) == 1:
            date_range = all_dates[0]
        else:
            date_range = f"{all_dates[0]} ~ {all_dates[-1]}"
    else:
        date_range = "未知日期"

    now = datetime.now(tz_sh).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # 构建 Markdown
    lines: list[str] = []
    # YAML frontmatter
    lines.append("---")
    lines.append(f'date_range: "{date_range}"')
    lines.append(f'generated_at: "{now}"')
    lines.append(f'total_items: {len(work_items)}')
    lines.append("---")
    lines.append("")
    lines.append("# 工作日志")
    lines.append("")

    # 按日期组织
    # 一个候选可能跨多天，在每个相关日期下都出现
    for date_str in all_dates:
        lines.append(f"## {date_str}")
        lines.append("")
        for cand, item in zip(candidates, work_items):
            if date_str in cand.dates:
                lines.append(f"### {item.task}")
                lines.append("")
                lines.append(item.detail)
                lines.append("")
                if item.evidence:
                    # 证据用引用块，多行用 > 前缀
                    evidence_lines = item.evidence.strip().split("\n")
                    lines.append("> " + evidence_lines[0])
                    for ev_line in evidence_lines[1:]:
                        if ev_line.strip():
                            lines.append(f"> {ev_line}")
                        else:
                            lines.append(">")
                    lines.append("")
                lines.append("---")
                lines.append("")

    return "\n".join(lines)


# ==========================================
# 主入口
# ==========================================

def generate_worklog(
    candidates: List[CandidateItem],
    select_indices: Optional[List[int]] = None,
    date_range: Optional[tuple[str, str]] = None,
    polish: bool = False,
    select_all: bool = False,
) -> str:
    """生成工作日志的统一入口。

    筛选优先级：select_indices > date_range > select_all > 全部

    Args:
        candidates: 全部候选工作项
        select_indices: 指定选中的索引（从 1 开始）
        date_range: (start, end) 日期范围
        polish: 是否调 LLM 润色
        select_all: 是否全选

    Returns:
        Markdown 格式的工作日志
    """
    # 筛选
    if select_indices is not None:
        selected = filter_by_indices(candidates, select_indices) if select_indices else []
    elif date_range:
        selected = filter_by_date_range(candidates, date_range[0], date_range[1])
    elif select_all:
        selected = candidates
    else:
        selected = candidates  # 默认全选

    if not selected:
        return "---\n---\n\n# 工作日志\n\n（无选中工作项）\n"

    return generate_markdown(selected, polish)
