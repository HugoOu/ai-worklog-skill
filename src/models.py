"""
数据模型层 — 从底层消息到顶层主题树的完整结构。

层级关系（自底向上）：
  ConversationMessage          原始消息
  └─ DailyConversation         按天归集
     └─ CandidateTopic         Map 阶段提取的候选主题（缓存）
        └─ TopicNode           层级主题树节点（聚类/embedding 产出）

所有模型均为 Pydantic v2，支持 JSON round-trip。
"""
from __future__ import annotations

import hashlib
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


# ============================================================
# 基础层：消息与按天归集（原有，保持兼容）
# ============================================================

class ConversationMessage(BaseModel):
    """单条对话消息"""
    role: str = Field(description="消息发送者角色，如 'user' 或 'assistant'")
    content: str = Field(description="消息文本内容")
    date: str = Field(default="Unknown Date", description="对话日期 YYYY-MM-DD")
    session_id: str = Field(default="", description="来源 UnifiedSession.id（证据链回调用）")


class DailyConversation(BaseModel):
    """按天归集的对话记录"""
    date: str = Field(description="对话日期 YYYY-MM-DD")
    messages: List[ConversationMessage] = Field(description="当天所有消息")

    @property
    def content_hash(self) -> str:
        """基于消息内容的确定性哈希，用于缓存失效判断。"""
        raw = "|".join(f"{m.role}:{m.content}" for m in self.messages)
        return hashlib.sha256(f"{self.date}|{raw}".encode()).hexdigest()[:16]


# ============================================================
# 证据层：可回链的消息引用
# ============================================================

class MessageRef(BaseModel):
    """指向原始消息的精确定位，替代不可追溯的纯文本 evidence。

    通过 session_id + message_index 可回链到 UnifiedSession.messages[i]。
    snippet 保留一份原文快照，即使源文件丢失也能展示证据。
    """
    session_id: str = Field(description="来源 UnifiedSession.id")
    message_index: int = Field(description="消息在该 session.messages 中的索引（从 0 开始）")
    role: str = Field(default="user", description="消息角色（冗余存储，方便展示）")
    preview: str = Field(description="原文前 80 字预览")
    snippet: str = Field(default="", description="完整证据片段原文快照（≤500 字）")


# ============================================================
# Map 缓存层
# ============================================================

class MapRunMeta(BaseModel):
    """记录一次 Map 调用的完整元数据——谁在什么时候用什么模型、什么参数生成了这份结果。"""
    run_id: str = Field(description="本次运行唯一 ID（UUID4 hex）")
    model: str = Field(description="使用的 LLM 模型名称，如 qwen3.7-flash")
    temperature: float = Field(default=0.0, description="采样温度")
    max_tokens: int = Field(default=8192, description="最大输出 token 数")
    prompt_version: str = Field(default="v1", description="SYSTEM_PROMPT 的版本标识，改 prompt 时递增")
    created_at: str = Field(description="运行时间 ISO 8601（含时区），如 2026-07-29T00:06:36+08:00")
    duration_ms: Optional[int] = Field(default=None, description="本次 Map 调用耗时（毫秒）")
    finish_reason: str = Field(default="stop", description="LLM 返回的 finish_reason（stop/length/content_filter）")
    truncated: bool = Field(default=False, description="输出是否被截断（finish_reason == length）")
    repaired: bool = Field(default=False, description="是否经过 JSON 截断修复")


class CandidateTopic(BaseModel):
    """Map 阶段从单日对话中提取的一个候选主题。

    相比旧 CandidateItem，增加了：
    - candidate_id: 稳定 ID（基于 date + topic 哈希）
    - source_refs: 可回链的证据引用列表
    - confidence: LLM 自评置信度（可选）
    """
    candidate_id: str = Field(description="候选主题稳定 ID（sha256[:12] of date+topic）")
    topic: str = Field(description="核心主题名称（10-20 字）")
    summary: str = Field(description="讨论过程与结论的简要总结（50-100 字）")
    evidence: str = Field(default="", description="对话中支持该主题的原始文本片段（一字不差，Map 阶段从 LLM 输出捕获）")
    source_refs: List[MessageRef] = Field(default_factory=list, description="证据引用列表")
    session_ids: List[str] = Field(default_factory=list, description="该候选涉及的来源 UnifiedSession.id 列表（证据链回调用）")
    confidence: Optional[float] = Field(default=None, ge=0, le=1, description="LLM 自评置信度 0-1")

    @model_validator(mode="before")
    @classmethod
    def _ensure_id(cls, data):
        """如果未提供 candidate_id，自动从 topic 生成。"""
        if isinstance(data, dict) and not data.get("candidate_id"):
            date = data.get("date", "")
            topic = data.get("topic", "")
            data["candidate_id"] = hashlib.sha256(f"{date}|{topic}".encode()).hexdigest()[:12]
        return data


class DayMapCache(BaseModel):
    """某一天的 Map 缓存——包含运行元数据 + 提取结果。

    缓存策略：
    - cache_key = content_hash（DailyConversation.content_hash）
    - 若源数据未变（hash 相同）且 prompt_version 未变，直接复用
    - 否则重新 Map 并覆盖写入
    """
    schema_version: str = Field(default="1.0", description="数据结构版本号")
    cache_key: str = Field(description="源数据哈希（DailyConversation.content_hash）")
    date: str = Field(description="对话日期 YYYY-MM-DD")
    input_message_count: int = Field(default=0, description="输入消息条数")
    map_run: MapRunMeta = Field(description="本次 Map 的运行元数据")
    candidates: List[CandidateTopic] = Field(default_factory=list, description="提取出的候选主题列表")

    @property
    def is_valid(self) -> bool:
        """缓存是否有效（有候选结果且未被截断）。"""
        return len(self.candidates) > 0 and not self.map_run.truncated


# ============================================================
# 层级主题树（RAPTOR 风格）
# ============================================================

class TopicNode(BaseModel):
    """层级主题树的单个节点。

    设计原则：
    - depth 由聚类算法自然产出（0=叶子/session, 1=第一层聚类簇, 2+=更高层聚合）
    - 不预设固定层级数，树的深度由数据决定
    - role_hint 为可选的人类语义标注，不影响算法逻辑
    - 叶子节点（depth=0）通过 session_ids 关联原始对话
    - 非叶子节点通过 children 关联子节点 ID
    - embedding 字段预留，供 embedding 聚类使用
    """
    node_id: str = Field(description="节点唯一 ID（UUID4 hex[:12]）")
    depth: int = Field(description="层级深度：0=叶子(session)，1+=聚类产出的上层节点")
    label: str = Field(description="主题名称（LLM 生成或用户手动命名）")
    summary: str = Field(default="", description="该节点覆盖内容的摘要")
    evidence: str = Field(default="", description="原始证据片段（叶子=CandidateItem.evidence，父节点=子节点拼接，分隔符 '\\n---\\n'）")
    role_hint: Optional[str] = Field(default=None, description="可选语义标签（task/component/project/other），仅供展示，不影响算法")

    # 结构关系
    children: List[str] = Field(default_factory=list, description="子节点 node_id 列表（非叶子节点有值）")
    session_ids: List[str] = Field(default_factory=list, description="关联的 UnifiedSession.id（叶子节点有值）")
    parent_id: Optional[str] = Field(default=None, description="父节点 node_id（根节点为 None）")

    # 时间范围
    dates: List[str] = Field(default_factory=list, description="覆盖的日期列表（YYYY-MM-DD）")

    # Embedding 预留
    embedding: Optional[List[float]] = Field(default=None, description="该节点的向量表示（供上层聚类用）")
    embedding_model: Optional[str] = Field(default=None, description="生成 embedding 的模型名称")

    # 溯源
    map_cache_keys: List[str] = Field(default_factory=list, description="该节点聚合了哪些 DayMapCache.cache_key")


class TopicTreeMeta(BaseModel):
    """主题树的构建元数据。"""
    tree_id: str = Field(description="树唯一 ID（UUID4 hex）")
    created_at: str = Field(description="构建时间 ISO 8601")
    method: str = Field(default="map_reduce", description="构建方法：map_reduce / embedding_raptor / manual")
    embedding_model: Optional[str] = Field(default=None, description="若用 embedding 聚类，记录模型名")
    cluster_params: Optional[dict] = Field(default=None, description="聚类参数快照（如 HDBSCAN min_cluster_size）")
    total_sessions: int = Field(default=0, description="输入会话总数")
    total_nodes: int = Field(default=0, description="树中节点总数")
    depth: int = Field(default=1, description="树的实际深度（层级数）")


class TopicTree(BaseModel):
    """完整的层级主题树——顶层容器。

    使用 nodes 字典（node_id → TopicNode）存储所有节点，
    通过 root_ids 指向顶层节点（PROJECT 级）。
    序列化后可存为 JSON 文件，前端可渲染为可折叠大纲。
    """
    meta: TopicTreeMeta = Field(description="树的构建元数据")
    nodes: dict[str, TopicNode] = Field(default_factory=dict, description="所有节点（node_id → TopicNode）")
    root_ids: List[str] = Field(default_factory=list, description="顶层节点 ID 列表（PROJECT 级）")

    def get_children(self, node_id: str) -> List[TopicNode]:
        """获取某节点的直接子节点列表。"""
        node = self.nodes.get(node_id)
        if not node:
            return []
        return [self.nodes[cid] for cid in node.children if cid in self.nodes]

    def get_sessions_under(self, node_id: str) -> List[str]:
        """递归获取某节点下所有叶子 session_ids。"""
        node = self.nodes.get(node_id)
        if not node:
            return []
        if node.depth == 0:
            return node.session_ids
        result = []
        for child_id in node.children:
            result.extend(self.get_sessions_under(child_id))
        return result

    def collect_candidates_under(self, node_id: str) -> List["CandidateItem"]:
        """递归收集 node_id 子树下所有叶子，投影为 CandidateItem 列表。

        树节点 → 工作日志的衔接点：用户选中任意节点（叶子或上层），自动展开
        其子树，投影成扁平候选，直接喂给 generator 渲染。

        字段映射：label→topic，summary/evidence/dates/session_ids 透传。
        节点不存在时返回空列表。
        """
        node = self.nodes.get(node_id)
        if not node:
            return []
        if node.depth == 0:
            return [CandidateItem(
                topic=node.label,
                summary=node.summary,
                evidence=node.evidence,
                dates=list(node.dates),
                session_ids=list(node.session_ids),
            )]
        result: List["CandidateItem"] = []
        for child_id in node.children:
            result.extend(self.collect_candidates_under(child_id))
        return result

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(indent=2, **kwargs)

    @classmethod
    def from_json(cls, json_str: str) -> "TopicTree":
        return cls.model_validate_json(json_str)


# ============================================================
# 兼容层：保留旧接口（CandidateItem / WorkItem / WorklogData）
# ============================================================

class CandidateItem(BaseModel):
    """【兼容旧接口】LLM 聚类生成的候选工作项。

    新代码请使用 CandidateTopic + DayMapCache。
    此类保留是为了不破坏现有 CLI / generator / tests。
    """
    topic: str = Field(description="该段对话的核心主题或任务名称")
    summary: str = Field(description="对该主题下对话内容的简要总结")
    evidence: str = Field(default="", description="对话中支持该主题的原始文本片段")
    dates: List[str] = Field(default_factory=list, description="该主题涉及的日期列表")
    session_ids: List[str] = Field(default_factory=list, description="该候选涉及的来源 UnifiedSession.id 列表（证据链回调用）")


class WorkItem(BaseModel):
    """最终生成单日工作日志的工作项"""
    task: str = Field(description="具体完成的任务名称")
    detail: str = Field(description="解决过程、关键决策或主要产出")
    evidence: str = Field(description="支持该任务的原始文本片段")


class WorklogData(BaseModel):
    """单日工作日志完整数据"""
    date: str = Field(description="日期 YYYY-MM-DD")
    work_items: List[WorkItem] = Field(description="工作项列表")