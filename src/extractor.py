import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from src.models import DailyConversation, CandidateItem
from typing import List

# 加载环境变量
load_dotenv()

# 初始化 OpenAI 客户端
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL")
)
MODEL_NAME = os.getenv("LLM_MODEL", "deepseek-chat")
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8192"))

# 每条消息送入 LLM 的最大字符数（超长截断，减少 token 消耗 & 防止输出截断）
MSG_CHAR_LIMIT = 1500

# 系统提示词：要求 LLM 进行主题聚类
SYSTEM_PROMPT = """你是一个专业的对话内容分析助手。你的任务是从用户提供的单日 AI 对话记录中，识别并聚类出不同的【主题或事件块】。

请遵循以下原则：
1. 将讨论相同问题、相同技术或相同任务的对话归为同一个主题块。
2. 忽略无意义的寒暄，但不要主观判断某个话题是否属于"工作"，只要是有实质内容的讨论，就提取出来作为候选。
3. 每天最多提取 5 个候选主题（合并相近主题，不要过度拆分）。
4. 每个候选块必须包含以下三个字段，缺一不可：
   - topic: 核心主题或任务名称 (10-20字)
   - summary: 对该主题讨论过程和结论的简要总结 (50-100字)
   - evidence: 对话中最能代表该主题的一句话或关键片段（≤200字，直接复制原文）。

你必须输出合法的 JSON 格式，结构如下：
{
  "candidates": [
    {
      "topic": "主题名称",
      "summary": "主题总结",
      "evidence": "≤200字的原文证据片段"
    }
  ]
}
"""

def format_conversation_for_llm(daily_conv: DailyConversation) -> str:
    """将 DailyConversation 对象格式化为 LLM 易读的纯文本（每条消息截断至 MSG_CHAR_LIMIT）"""
    text = f"日期: {daily_conv.date}\n对话记录:\n"
    for msg in daily_conv.messages:
        sender = "用户" if msg.role == "user" else "AI助手"
        content = msg.content
        if len(content) > MSG_CHAR_LIMIT:
            content = content[:MSG_CHAR_LIMIT] + "...（内容过长，已截断）"
        text += f"{sender}: {content}\n"
    return text


def _repair_truncated_json(raw: str) -> str:
    """
    尝试修复因 max_tokens 截断而不完整的 JSON。
    策略：用状态机跟踪字符串/转义/花括号深度，提取所有完整闭合的候选对象，
    重建合法的 {"candidates": [...]} JSON。
    """
    # 先尝试直接解析
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass

    # 状态机扫描：找到所有顶层数组元素的完整 {} 对象
    # 跟踪是否在字符串内、是否转义、花括号深度
    objects = []
    i = 0
    n = len(raw)
    in_string = False
    escape_next = False
    depth = 0
    obj_start = -1

    while i < n:
        ch = raw[i]
        if escape_next:
            escape_next = False
            i += 1
            continue
        if ch == '\\' and in_string:
            escape_next = True
            i += 1
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            i += 1
            continue
        if in_string:
            i += 1
            continue
        # 不在字符串内
        if ch == '{':
            if depth == 1:
                obj_start = i  # 候选对象开始
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 1 and obj_start >= 0:
                # 一个完整的候选对象
                obj_str = raw[obj_start:i+1]
                try:
                    obj = json.loads(obj_str)
                    objects.append(obj)
                except json.JSONDecodeError:
                    pass
                obj_start = -1
            elif depth == 0:
                break  # 外层对象闭合
        i += 1

    if objects:
        repaired = json.dumps({"candidates": objects}, ensure_ascii=False)
        return repaired

    return raw  # 无法修复，返回原文让调用方报错

def extract_candidates_from_daily(daily_conv: DailyConversation, log=print) -> List[CandidateItem]:
    """
    调用 LLM 从单日对话中进行主题聚类，生成候选工作项。
    log: 日志输出函数，默认 print；在 rich 进度条上下文中可传 progress.console.print 避免打断渲染。

    证据链：捕获当天消息涉及的 session_id 列表，随每个候选一起返回（日级粗粒度归因）。
    """
    user_prompt = format_conversation_for_llm(daily_conv)
    # 当天涉及的 session_ids（去重，保序）
    day_session_ids: List[str] = []
    for msg in daily_conv.messages:
        if msg.session_id and msg.session_id not in day_session_ids:
            day_session_ids.append(msg.session_id)
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=MAX_TOKENS
        )
        
        if not response.choices:
            log(f"[日期: {daily_conv.date}] LLM 返回空 choices（可能触发内容审核），跳过")
            return []
        content = response.choices[0].message.content
        if not content:
            log(f"[日期: {daily_conv.date}] LLM 返回空内容，跳过")
            return []

        # 检查是否因 max_tokens 截断（finish_reason == "length"）
        finish_reason = response.choices[0].finish_reason
        if finish_reason == "length":
            log(f"  ⚠️ [日期: {daily_conv.date}] LLM 输出被截断，尝试修复 JSON...")
            content = _repair_truncated_json(content)

        data_dict = json.loads(content)
        candidates_data = data_dict.get("candidates", [])
        candidates = []
        
        # 增加条目级容错：即使某一条数据格式不对，也只跳过这一条，不影响全局
        for item in candidates_data:
            try:
                cand = CandidateItem(**item)
                # 证据链：日级粗粒度归因——当天所有候选共享当天涉及的 session 列表
                cand.session_ids = list(day_session_ids)
                candidates.append(cand)
            except Exception as e:
                log(f"  ⚠️ 跳过一个格式错误的候选主题: {item.get('topic', '未知主题')}, 错误: {e}")
        
        return candidates
        
    except json.JSONDecodeError as e:
        log(f"[日期: {daily_conv.date}] JSON 解析失败: {e}")
        return []
    except Exception as e:
        log(f"[日期: {daily_conv.date}] LLM 调用或校验出错: {e}")
        return []


# ==========================================
# Reduce 阶段：跨天合并
# ==========================================
MERGE_SYSTEM_PROMPT = """你是一个专业的对话内容分析助手。你的任务是将从不同日期提取的候选主题进行跨天合并，识别出属于同一跨天工作项目的候选。

请遵循以下原则：
1. 将讨论相同问题、相同技术、相同任务的候选合并为一个主题。
2. 不同项目不要强行合并。
3. 每个候选必须且只能归入一个合并组——即使是独立主题（不与其他合并），也要单独成组，source_indices 只含自己的索引。
4. 每个合并结果包含：
   - topic: 最能概括整体的主题名称 (10-20字)
   - summary: 综合多天进展的摘要 (50-150字)
   - source_indices: 要合并的候选在输入列表中的索引（从0开始）

你必须输出合法的 JSON 格式，结构如下：
{
  "merged": [
    {
      "topic": "统一主题名称",
      "summary": "综合摘要",
      "source_indices": [0, 3, 7]
    }
  ]
}
"""

def merge_cross_day_candidates(candidates: List[CandidateItem]) -> List[CandidateItem]:
    """
    Reduce 阶段：将所有日级候选汇总后交给 LLM 做跨天合并。

    输入 LLM 的仅为各候选的 topic+summary+date（体量小，不超窗口）。
    evidence 不交给 LLM 改写，而是在代码中按 source_indices 拼接，保证一字不差。
    """
    # 构造精简输入：只传 topic + summary + date
    brief_lines = []
    for i, cand in enumerate(candidates):
        date_str = ", ".join(cand.dates) if cand.dates else "未知日期"
        brief_lines.append(f"[{i}] 日期:{date_str} | 主题:{cand.topic} | 摘要:{cand.summary}")
    user_prompt = "候选主题列表：\n" + "\n".join(brief_lines)

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": MERGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )

        if not response.choices:
            print("跨天合并: LLM 返回空 choices，降级返回未合并候选")
            return candidates
        content = response.choices[0].message.content
        if not content:
            print("跨天合并: LLM 返回空内容，降级返回未合并候选")
            return candidates
        data_dict = json.loads(content)
        merged_data = data_dict.get("merged", [])
        result: List[CandidateItem] = []
        referenced = set()

        for item in merged_data:
            try:
                source_indices = item.get("source_indices", [])
                if not source_indices:
                    continue

                # 在代码中拼接 evidence，保证一字不差
                evidence_parts = []
                merged_dates = set()
                for idx in source_indices:
                    if 0 <= idx < len(candidates):
                        evidence_parts.append(candidates[idx].evidence)
                        merged_dates.update(candidates[idx].dates)
                        referenced.add(idx)

                if not evidence_parts:
                    continue

                result.append(CandidateItem(
                    topic=item["topic"],
                    summary=item["summary"],
                    evidence="\n---\n".join(evidence_parts),
                    dates=sorted(merged_dates)
                ))
            except Exception as e:
                print(f"  ⚠️ 跳过一个格式错误的合并项: {item.get('topic', '未知')}, 错误: {e}")

        # 兜底：未被任何合并组引用的候选保留为独立主题
        for i, cand in enumerate(candidates):
            if i not in referenced:
                result.append(cand)

        return result

    except json.JSONDecodeError as e:
        print(f"跨天合并 JSON 解析失败: {e}")
        return candidates  # 降级：返回未合并的原始候选
    except Exception as e:
        print(f"跨天合并出错: {e}")
        return candidates  # 降级