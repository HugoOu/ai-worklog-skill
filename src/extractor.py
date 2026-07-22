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

# 系统提示词：改为要求 LLM 进行主题聚类
SYSTEM_PROMPT = """你是一个专业的对话内容分析助手。你的任务是从用户提供的单日 AI 对话记录中，识别并聚类出不同的【主题或事件块】。

请遵循以下原则：
1. 将讨论相同问题、相同技术或相同任务的对话归为同一个主题块。
2. 忽略无意义的寒暄，但不要主观判断某个话题是否属于“工作”，只要是有实质内容的讨论，就提取出来作为候选。
3. 每个候选块必须包含：
   - topic: 核心主题或任务名称 (10-20字)
   - summary: 对该主题讨论过程和结论的简要总结 (50-100字)
   - evidence: 对话中支持该主题的原始文本片段，必须一字不差。

你必须输出合法的 JSON 格式，结构如下：
{
  "candidates": [
    {
      "topic": "主题名称",
      "summary": "主题总结",
      "evidence": "对话中的原话片段"
    }
  ]
}
"""

def format_conversation_for_llm(daily_conv: DailyConversation) -> str:
    """将 DailyConversation 对象格式化为 LLM 易读的纯文本"""
    text = f"日期: {daily_conv.date}\n对话记录:\n"
    for msg in daily_conv.messages:
        sender = "用户" if msg.role == "user" else "AI助手"
        text += f"{sender}: {msg.content}\n"
    return text

def extract_candidates_from_daily(daily_conv: DailyConversation) -> List[CandidateItem]:
    """
    调用 LLM 从单日对话中进行主题聚类，生成候选工作项。
    """
    user_prompt = format_conversation_for_llm(daily_conv)
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        
        content = response.choices[0].message.content
        if not content:
            print(f"[日期: {daily_conv.date}] LLM 返回空内容，跳过")
            return []
        data_dict = json.loads(content)
        candidates_data = data_dict.get("candidates", [])
        candidates = []
        
        # 增加条目级容错：即使某一条数据格式不对，也只跳过这一条，不影响全局
        for item in candidates_data:
            try:
                candidates.append(CandidateItem(**item))
            except Exception as e:
                print(f"  ⚠️ 跳过一个格式错误的候选主题: {item.get('topic', '未知主题')}, 错误: {e}")
        
        return candidates
        
    except json.JSONDecodeError as e:
        print(f"[日期: {daily_conv.date}] JSON 解析失败: {e}")
        return []
    except Exception as e:
        print(f"[日期: {daily_conv.date}] LLM 调用或校验出错: {e}")
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
            temperature=0.2
        )

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