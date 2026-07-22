from pydantic import BaseModel, Field
from typing import List

class ConversationMessage(BaseModel):
    """单条对话消息的结构"""
    role: str = Field(description="消息发送者的角色，如 'user' 或 'assistant'")
    content: str = Field(description="消息的文本内容")
    date: str = Field(default="Unknown Date", description="对话发生的日期，格式为 YYYY-MM-DD")

class WorkItem(BaseModel):
    """最终生成单日工作日志的完整数据结构"""
    task: str = Field(description="具体完成的任务名称，简洁概括")
    detail: str = Field(description="任务的解决过程、关键决策或主要产出")
    evidence: str = Field(description="对话中支持该任务提取的原始文本片段，必须一字不差")

class CandidateItem(BaseModel):
    """LLM 聚类生成的候选工作项，等待用户筛选"""
    topic: str = Field(description="该段对话的核心主题或任务名称")
    summary: str = Field(description="对该主题下对话内容的简要总结")
    evidence: str = Field(description="对话中支持该主题的原始文本片段，必须一字不差")
    dates: List[str] = Field(default_factory=list, description="该主题涉及的日期列表；跨天合并后会有多个日期")

class WorklogData(BaseModel):
    """最终生成单日工作日志的完整数据结构"""
    date: str = Field(description="该工作日志对应的日期 YYYY-MM-DD")
    work_items: List[WorkItem] = Field(description="抽取出的所有工作项列表")

class DailyConversation(BaseModel):
    """按天归集的对话记录"""
    date: str = Field(description="对话发生的日期 YYYY-MM-DD")
    messages: List[ConversationMessage] = Field(description="当天的所有对话消息列表")