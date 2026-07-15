from pydantic import BaseModel, Field
from typing import List

class ConversationMessage(BaseModel):
    """单条对话消息的结构"""
    role: str = Field(description="消息发送者的角色，如 'user' 或 'assistant'")
    content: str = Field(description="消息的文本内容")

class WorkItem(BaseModel):
    """从对话中抽取的单个工作项"""
    task: str = Field(description="具体完成的任务名称，简洁概括")
    detail: str = Field(description="任务的解决过程、关键决策或主要产出")
    evidence: str = Field(description="对话中支持该任务提取的原始文本片段，必须一字不差")

class WorklogData(BaseModel):
    """最终生成工作日志的完整数据结构"""
    work_items: List[WorkItem] = Field(description="抽取出的所有工作项列表")