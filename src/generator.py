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

from src.models import CandidateItem, WorkItem, TopicTree, TopicNode

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
# 树节点 → 候选投影（P2：以树为纲生成日志）
# ==========================================

def _leaf_ids_under(tree: TopicTree, node_id: str) -> List[str]:
    """递归收集 node_id 子树下所有叶子节点的 node_id（保序）。"""
    node = tree.nodes.get(node_id)
    if not node:
        return []
    if node.depth == 0:
        return [node_id]
    result: List[str] = []
    for cid in node.children:
        result.extend(_leaf_ids_under(tree, cid))
    return result


def _leaf_to_candidate(node: TopicNode) -> CandidateItem:
    """将叶子 TopicNode 投影为 CandidateItem（字段映射与 collect_candidates_under 一致）。"""
    return CandidateItem(
        topic=node.label,
        summary=node.summary,
        evidence=node.evidence,
        dates=list(node.dates),
        session_ids=list(node.session_ids),
    )


def select_by_tree_nodes(
    tree: TopicTree, node_ids: List[str]
) -> List[CandidateItem]:
    """从主题树的若干节点投影出候选工作项（1-B：任意节点自动展开整棵子树）。

    - 每个节点自动展开其子树下所有叶子（depth=0）
    - 多个节点选中时，按叶子 node_id 去重（选中父+子不会重复投影同一片叶子）
    - 投影结果按 (最早日期, topic) 排序，保证确定性

    Args:
        tree: 主题树
        node_ids: 选中的节点 ID 列表

    Returns:
        去重后的候选工作项列表
    """
    seen: set[str] = set()
    ordered_leaf_ids: List[str] = []
    for nid in node_ids:
        for leaf_id in _leaf_ids_under(tree, nid):
            if leaf_id not in seen:
                seen.add(leaf_id)
                ordered_leaf_ids.append(leaf_id)

    candidates = [_leaf_to_candidate(tree.nodes[lid]) for lid in ordered_leaf_ids]
    candidates.sort(key=lambda c: (c.dates[0] if c.dates else "", c.topic))
    return candidates


def flatten_tree_numbered(tree: TopicTree) -> List[tuple[int, TopicNode, int]]:
    """把主题树按 DFS 展平为带编号的列表，供交互式选择。

    Returns:
        [(编号, TopicNode, 缩进层级), ...]，编号从 1 开始。
        编号顺序 = 终端展示顺序，用户输入编号即可选中对应节点（自动展开子树）。
    """
    rows: List[tuple[int, TopicNode, int]] = []
    counter = [0]

    def _walk(node_id: str, indent: int):
        node = tree.nodes.get(node_id)
        if not node:
            return
        counter[0] += 1
        rows.append((counter[0], node, indent))
        for cid in node.children:
            _walk(cid, indent + 1)

    for root_id in tree.root_ids:
        _walk(root_id, 0)
    return rows


def interactive_tree_select(
    tree: TopicTree,
    input_func=input,
    print_func=print,
) -> List[CandidateItem]:
    """交互式树选择：打印带编号的主题树，用户输入节点编号，投影为候选。

    展示格式（缩进体现层级，[depth] 体现树深）：
      [ 1] RAGFlow 架构与核心痛点            (depth=2)
      [ 2]   RAG 基础概念与全流程            (depth=1)
      [ 3]     RAG 检索机制原理              (depth=0)

    用户选中任意编号 → 自动展开其子树（1-B）。

    Args:
        tree: 主题树
        input_func / print_func: 可注入，便于测试

    Returns:
        投影 + 去重后的候选工作项列表
    """
    rows = flatten_tree_numbered(tree)
    if not rows:
        print_func("（主题树为空）")
        return []

    print_func(f"\n主题树（共 {len(rows)} 个节点，选中任意节点自动展开其子树）：\n")
    for num, node, indent in rows:
        prefix = "  " * indent
        dates_str = ", ".join(node.dates) if node.dates else ""
        leaf_mark = "·" if node.depth == 0 else "▸"
        line = f"  [{num:2d}] {prefix}{leaf_mark} {node.label}"
        if dates_str:
            line += f"  ({dates_str})"
        print_func(line)

    print_func("\n输入要纳入工作日志的节点编号（逗号分隔，如 1,3,5-7；回车=全部根节点）:")
    raw = input_func("> ").strip()

    if not raw:
        # 默认选中所有根节点
        selected_ids = list(tree.root_ids)
    else:
        indices = _parse_indices(raw)
        selected_ids = []
        for idx in indices:
            if 1 <= idx <= len(rows):
                selected_ids.append(rows[idx - 1][1].node_id)
            else:
                print_func(f"  ⚠️ 编号 {idx} 超出范围（1-{len(rows)}），已忽略")

    if not selected_ids:
        return []

    return select_by_tree_nodes(tree, selected_ids)


# ==========================================
# CandidateItem → WorkItem 转换
# ==========================================

def candidate_to_workitem(cand: CandidateItem, polish: bool = True) -> WorkItem:
    """将 CandidateItem 转换为 WorkItem。

    默认调 LLM 润色为第一人称工作日志语气：
      topic   → task（动宾结构任务名）
      summary → detail（第一人称"我做了什么"）
      evidence → evidence（从原文中筛选工作成果片段）

    polish=False 时直接映射字段（不调 LLM，但语气是旁观描述，不推荐）。

    Args:
        cand: 候选工作项
        polish: 是否调 LLM 润色（默认 True）

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
    """调 LLM 把候选润色为第一人称工作日志条目。"""
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
        "你是工作日志撰写助手。把以下候选工作项润色为第一人称的工作日志条目。\n"
        "要求：\n"
        "1. task: 简洁的任务名称（10-20字，动宾结构，如'撰写开题报告国内研究综述'）\n"
        "2. detail: 以第一人称'我'描述工作过程与产出（50-150字）\n"
        "   - 写'我做了什么'，不要写'用户做了什么'\n"
        "   - 包含：做了什么 + 怎么做的 + 关键结果\n"
        "   - 语气简洁客观，像工作汇报而非对话记录\n"
        "3. evidence: 从下方原始证据中筛选最能体现工作成果的片段（保持原文措辞，不编造）\n"
        "   - 优先选 AI 回答中的关键结论/产出，而非用户的 prompt 指令\n"
        "   - 如果原文全是 prompt 指令，提取其中最核心的一两句\n"
        "   - 保留原文措辞，不改写\n\n"
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
            evidence=data.get("evidence", cand.evidence),
        )
    except Exception:
        # LLM 调用失败时降级为直接映射
        return WorkItem(task=cand.topic, detail=cand.summary, evidence=cand.evidence)


# ==========================================
# Markdown 格式化
# ==========================================

def generate_markdown(
    candidates: List[CandidateItem],
    polish: bool = True,
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
    polish: bool = True,
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
