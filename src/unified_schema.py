"""
统一对话数据模型 — 融合 LobeChat 字段完备性 + Big-AGI Fragment 系统 + ShareGPT 兼容回退。

所有平台 adapter 输出 UnifiedSession 列表，下游 pipeline / clustering / bridge 统一消费。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# ==========================================
# 类型别名
# ==========================================

Provider = Literal[
    "openai", "anthropic", "google", "xai", "mistral",
    "deepseek", "qwen", "glm", "kimi", "minimax", "unknown",
]

MessageSource = Literal[
    "chatgpt_export", "claude_export", "gemini_export",
    "deepseek_export", "qwen_export", "glm_export", "kimi_export",
    "grok_export", "mistral_export", "minimax_export",
    "api", "manual",
]

MessageRole = Literal["user", "assistant", "system", "tool"]

FragmentKind = Literal[
    "text", "image", "tool_call", "tool_response", "code", "error", "reasoning",
]


# ==========================================
# 子模型
# ==========================================

class Fragment(BaseModel):
    """Big-AGI 风格 fragment — 一条消息可由多个 part 组成（文本/图片/工具调用/思维链等）。

    本期（Phase 1）仅填充 text 与 reasoning 类型；其他类型字段保留，待后续多模态扩展。
    """
    kind: FragmentKind = Field(description="fragment 类型")
    text: Optional[str] = Field(default=None, description="文本内容（text/reasoning/code/error 用）")
    mime_type: Optional[str] = Field(default=None, description="MIME 类型（image 用）")
    file_path: Optional[str] = Field(default=None, description="媒体文件本地相对路径（image 用）")
    tool_name: Optional[str] = Field(default=None, description="工具名称（tool_call/tool_response 用）")
    tool_args: Optional[dict] = Field(default=None, description="工具调用参数（tool_call 用）")
    tool_result: Optional[str] = Field(default=None, description="工具返回结果（tool_response 用）")


class TokenUsage(BaseModel):
    """Token 用量与成本（部分平台导出不含此信息时，字段留空）。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Optional[float] = None


# ==========================================
# 核心模型
# ==========================================

class UnifiedMessage(BaseModel):
    """统一消息模型 — 所有平台 adapter 输出的单条消息格式。

    设计原则：
    - `content` 字段始终填充纯文本（ShareGPT 兼容回退），保证下游最低可用性
    - `fragments` 字段保留多模态结构化内容，本期可留空
    - `provider` + `model` 分离存储（借鉴 LobeChat）
    - `reasoning` 独立字段（o1/Claude thinking）
    - `created_at` 必填，pipeline 会做时区归一化到 Asia/Shanghai
    """
    id: str = Field(description="消息唯一 ID（adapter 内生成或继承自上游）")
    session_id: str = Field(description="所属会话 ID")
    role: MessageRole
    content: str = Field(description="纯文本内容（ShareGPT 兼容回退）")
    fragments: list[Fragment] = Field(default_factory=list, description="多模态结构化内容，本期可留空")

    provider: Provider = "unknown"
    model: Optional[str] = Field(default=None, description="生成该消息的模型，如 gpt-4o / gemini-2.0-flash")

    # 对话结构
    parent_id: Optional[str] = Field(default=None, description="父消息 ID（树状对话）")
    thread_id: Optional[str] = Field(default=None, description="分支对话 ID")

    # 元数据
    usage: Optional[TokenUsage] = None
    reasoning: Optional[str] = Field(default=None, description="思维链纯文本（o1/Claude thinking）")
    tools: Optional[list[dict]] = None
    trace_id: Optional[str] = Field(default=None, description="厂商 trace ID（可观测性）")
    upstream_ref: Optional[str] = Field(default=None, description="厂商原始 message ID（去重/审计用）")

    # 时间戳
    created_at: datetime
    updated_at: Optional[datetime] = None

    # 来源
    source: MessageSource = "manual"


class UnifiedSession(BaseModel):
    """统一会话模型 — 一个完整对话（含多条消息）。"""
    id: str = Field(description="会话唯一 ID")
    title: Optional[str] = Field(default=None, description="会话标题（部分平台导出含标题）")
    provider: Provider
    model: Optional[str] = Field(default=None, description="会话级模型（如整段都是 gpt-4o）")
    messages: list[UnifiedMessage]

    created_at: datetime
    updated_at: Optional[datetime] = None

    source: str
    raw_metadata: Optional[dict] = Field(default=None, description="原始导出元数据保留（去重/审计用）")
