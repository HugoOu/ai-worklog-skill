import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from src.models import DailyConversation, WorklogData, WorkItem
from typing import List

# 加载环境变量
load_dotenv()

# 初始化 OpenAI 客户端 (兼容任何基于 OpenAI 格式的 API)
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL")
)
MODEL_NAME = os.getenv("LLM_MODEL", "deepseek-chat")

# 系统提示词，定义 Agent 的角色、任务和严格约束
SYSTEM_PROMPT = """你是一个专业的工作日志助手。你的任务是从用户提供的 AI 对话记录中，提取出用户当天真实完成的工作项。

请遵循以下原则：
1. 只提取用户【实际做过、讨论过、或产出的】工作任务。忽略纯粹的闲聊或无意义的对话。
2. 每一个工作项必须包含：
   - task: 简洁的任务名称 (10-20字)
   - detail: 任务的解决过程、关键决策或主要产出 (50-100字)
   - evidence: 对话中支持该任务提取的原始文本片段，必须一字不差，不能篡改。
3. 如果对话中没有实质性的工作内容，返回空的 work_items 列表。

你必须输出合法的 JSON 格式，结构如下：
{
  "date": "YYYY-MM-DD",
  "work_items": [
    {
      "task": "任务名称",
      "detail": "任务详情",
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

def extract_worklog_from_daily(daily_conv: DailyConversation) -> WorklogData:
    """
    调用 LLM 从单日对话中提取结构化工作日志。
    包含 JSON 解析容错和 Pydantic 强校验。
    """
    user_prompt = format_conversation_for_llm(daily_conv)
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"}, # 强制模型输出 JSON
            temperature=0.2 # 降低随机性，保证抽取稳定
        )
        
        # 获取模型输出的 JSON 字符串
        content = response.choices[0].message.content
        
        # 解析 JSON
        data_dict = json.loads(content)
        
        # 强制覆盖日期，确保与输入的对话日期一致
        data_dict["date"] = daily_conv.date
        
        # 使用 Pydantic 进行严格的数据校验和转换
        worklog_data = WorklogData(**data_dict)
        
        return worklog_data
        
    except json.JSONDecodeError as e:
        print(f"[日期: {daily_conv.date}] JSON 解析失败: {e}")
        # 容错：返回一个空的工作日志
        return WorklogData(date=daily_conv.date, work_items=[])
    except Exception as e:
        print(f"[日期: {daily_conv.date}] LLM 调用或校验出错: {e}")
        return WorklogData(date=daily_conv.date, work_items=[])

def extract_worklogs(daily_conversations: List[DailyConversation]) -> List[WorklogData]:
    """
    批量处理多天的对话记录，生成多天的工作日志。
    """
    all_worklogs = []
    for daily_conv in daily_conversations:
        print(f"正在提取 {daily_conv.date} 的工作日志...")
        worklog = extract_worklog_from_daily(daily_conv)
        all_worklogs.append(worklog)
    return all_worklogs