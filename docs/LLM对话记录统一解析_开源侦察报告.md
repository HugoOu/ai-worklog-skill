# 多平台 LLM 对话记录统一解析 — 开源侦察报告

> 检索目标：为 Python AI Worklog Agent 寻找能"统一解析多平台 LLM 对话记录"的开源库 / Schema 参考
> 检索范围：GitHub · PyPI · HuggingFace
> 检索日期：2026-07-21

---

## TL;DR — 核心结论

| 维度 | 结论 |
|---|---|
| **是否有"开箱即用"的统一 Python 库？** | ❌ 没有一个库能同时覆盖 ChatGPT + Claude + Gemini + Qwen + GLM + DeepSeek + Kimi |
| **最接近的现成轮子** | `llm-logparser`（PyPI, MIT, 5 平台）+ `temnoon/openai_export_parser`（OpenAI+Claude, 媒体匹配强） |
| **国产模型（Qwen/GLM/DeepSeek/Kimi）现状** | ❌ GitHub 上几乎无可靠 Python 解析器；多数平台甚至没有官方批量导出 |
| **最值得借鉴的 Schema** | LobeChat（Drizzle/Postgres schema，字段最完备）+ Big-AGI（fragment 系统） |
| **事实标准中间格式** | ShareGPT V3 格式（HF 生态广泛采用） |
| **推荐策略** | **混合方案**：核心 OpenAI/Claude/Gemini 走 `llm-logparser`，国产模型自写轻量适配器，统一中间格式参考 LobeChat + ShareGPT |

---

## 一、核心候选 Python 项目（可直接 pip install）

### 1. ⭐ llm-logparser（最推荐 — 多平台 + 活跃维护）

| 字段 | 值 |
|---|---|
| **GitHub** | https://github.com/Syun-tnb/llm-logparser |
| **PyPI** | https://pypi.org/project/llm-logparser/ |
| **语言** | Python ≥ 3.10 |
| **License** | MIT |
| **当前版本** | v1.4.0（2026-05-17 发布） |
| **Star / Fork** | ⭐ ~0 / 🍴 ~0（**项目较新，关注度低，但代码活跃**） |
| **最近 commit** | 2026-07-05 |
| **维护状态** | 🟢 活跃（commit 数 393，作者在 GitHub Sponsors 持续维护） |

**支持的平台（5 个）**：
- ✅ OpenAI ChatGPT
- ✅ Anthropic Claude
- ✅ xAI Grok
- ✅ Mistral Le Chat
- ✅ Google Gemini（通过 "My Activity" 导入）
- ❌ Qwen / GLM / DeepSeek / Kimi（未支持）

**核心架构**：
```
Parse Adapter → parsed.jsonl (canonical) → Analyzers (tokens/metrics/stats) → Exporters (Markdown/JSONL)
```

**统一中间格式 — `parsed.jsonl`**：
```json
{
  "thread": "abc123",
  "provider": "openai",
  "messages": [
    {"message_id": "m1", "role": "user", "content": "...", "timestamp": "..."},
    {"message_id": "m2", "role": "assistant", "content": "...", "model": "gpt-4o"}
  ],
  "models": ["gpt-4o"],
  "range": "2025-10-01T01:00:00+00:00 〜 2025-10-18T10:15:00+00:00"
}
```

**CLI 用法**：
```bash
pip install llm-logparser
llm-logparser chain --provider openai --input export.jsonl --outdir artifacts --timezone Asia/Shanghai
```

**Python API**：
```python
from llm_logparser import parse, export
threads = parse(provider="openai", input_path="conversations.json")
export(threads, outdir="artifacts", timezone="Asia/Shanghai")
```

**亮点**：
- 离线优先、零遥测
- YAML front-matter + GFM Markdown 输出
- 支持时区与本地化（`--locale zh-CN --timezone Asia/Shanghai`）
- 链式流水线 `parse → analyze → export`
- 文件切分（按 size/count/auto）

**不足**：
- Star 极少，社区验证度低
- 仅支持 JSON/JSONL 输入，不支持 HTML 解析
- 国产模型未支持
- Token 分析仅 OpenAI/Anthropic/xAI

---

### 2. ⭐ temnoon/openai_export_parser（媒体匹配王 — OpenAI + Claude）

| 字段 | 值 |
|---|---|
| **GitHub** | https://github.com/temnoon/openai_export_parser |
| **PyPI** | `pip install openai-export-parser` |
| **语言** | Python ≥ 3.8 |
| **License** | MIT |
| **Star / Fork** | ⭐ 1 / 🍴 2 |
| **最近 commit** | 2026-06-03 |
| **维护状态** | 🟢 活跃，已适配 2026 年最新 ChatGPT 导出格式 |

**支持的平台**：
- ✅ OpenAI ChatGPT（ZIP/嵌套 ZIP/.dat 媒体）
- ✅ Anthropic Claude（自动检测）
- 自动检测导出类型

**亮点**：
- **7 种媒体匹配策略**（file-hash / file-ID / filename+size / 目录 / size+metadata / size-only / filename-only），97.9% 匹配率
- 处理 OpenAI 新版"多 GB 嵌套 ZIP + .dat 媒体"格式
- 自动嗅探 `.dat` 文件的真实类型（PNG/JPEG/PDF/WAV）
- DALL-E 图像 + 上传文件 + 语音消息均支持
- 每对话输出独立 HTML + JSON + 媒体清单
- 主索引 `index.html` 提供搜索过滤

**Python API**：
```python
from openai_export_parser import ExportParser
parser = ExportParser(verbose=True)
parser.parse_export("export.zip", "output_directory")
# 输出: output/2025-11-06_xxx/conversation.json + conversation.html + media/
```

**不足**：
- 仅 2 个平台
- 输出偏"归档浏览器"，不直接产出 RAG 友好的统一 JSON
- 但其 `conversation.json` 结构可作为参考

---

### 3. nullhyeon/llm-conversation-parser（轻量 — Claude/GPT/Grok → RAG）

| 字段 | 值 |
|---|---|
| **GitHub** | https://github.com/nullhyeon/llm-conversation-parser |
| **PyPI** | `pip install llm-conversation-parser` |
| **语言** | Python ≥ 3.8 |
| **License** | MIT |
| **Star** | ⭐ 2 |
| **最近 commit** | 2025-10-13 |
| **维护状态** | 🟡 半活跃（仅 1 个 commit） |

**支持的平台**：
- ✅ Claude（Anthropic）
- ✅ ChatGPT（OpenAI）
- ✅ Grok（xAI）
- 自动检测 LLM 类型

**统一输出格式（RAG 优化）**：
```json
[
  {
    "id": "message_uuid",
    "content": {
      "user_query": "User's question",
      "conversation_flow": "[AI_ANSWER] Previous AI response\n[USER_QUESTION] User's question"
    },
    "metadata": {
      "previous_ai_answer": "Previous AI response or null",
      "conversation_id": "conversation_uuid"
    }
  }
]
```

**亮点**：
- **零依赖**（纯标准库）
- 自动 LLM 类型检测
- 批量处理多文件
- 提供 CLI

**不足**：
- 输出格式偏 RAG 向量化，**丢失了原始时间戳、模型名、token 数等元数据**
- 不适合"工作日志"场景（需要时间维度归集）
- 仅 JSON 输入，不支持 HTML

---

### 4. echomine（架构范本 — Adapter Pattern + Pydantic）

| 字段 | 值 |
|---|---|
| **PyPI** | `pip install echomine` |
| **GitHub** | https://github.com/echomine/echomine（**当前 404，疑似已下架/迁移**） |
| **语言** | Python ≥ 3.12 |
| **License** | **AGPLv3+**（⚠️ 有传染性，商用需注意） |
| **版本** | v1.3.0（2025-12 后） |
| **维护状态** | 🟡 PyPI 在更新，但 GitHub 仓库不可访问 |

**支持的平台**：
- ✅ OpenAI ChatGPT（已实现 `OpenAIAdapter`）
- ⏳ Claude / Gemini（架构预留，未实现）

**架构亮点（最值得借鉴）**：
- **Adapter Pattern**：每个 provider 一个 `XxxAdapter` 类，统一接口
- **Pydantic v2 强类型**，mypy --strict 合规
- **流式解析**（ijson）— 处理 1GB+ 导出文件常量内存
- **BM25 搜索**：内置全文检索 + 角色过滤 + 日期范围
- 多种导出格式：Markdown（YAML frontmatter）/ JSON / CSV
- 库优先设计：所有 CLI 功能均可作为 Python API 调用

**典型 API**：
```python
from echomine import OpenAIAdapter, SearchQuery
adapter = OpenAIAdapter()
for conv in adapter.stream_conversations(Path("conversations.json")):
    print(f"[{conv.created_at.date()}] {conv.title} — {len(conv.messages)} msgs")

query = SearchQuery(keywords=["refactor"], role_filter="user",
                    from_date=date(2024,1,1), to_date=date(2024,3,31))
for result in adapter.search(Path("conversations.json"), query):
    print(f"{result.score:.2f} {result.conversation.title}")
```

**结论**：GitHub 仓库 404，**不建议直接依赖**；但其 Adapter Pattern + Pydantic 强类型设计是**最佳架构范本**。

---

### 5. chatgpt-export-tool（流式解析 + TOML 配置）

| 字段 | 值 |
|---|---|
| **PyPI** | `pip install chatgpt-export-tool` |
| **语言** | Python ≥ 3.10 |
| **License** | MIT |
| **版本** | v1.0.0（2026-03-27） |
| **依赖** | ijson, tomli |

**支持平台**：仅 ChatGPT 官方导出 `conversations.json`

**亮点**：
- **流式 ijson 解析**，支持超大导出文件
- 字段过滤 pipeline（`--fields` / `--include` / `--exclude`）
- 多种切分模式：single / subject / **date** / id
- TOML 配置 + 预设系统
- 支持 reasoning、tool calls、code execution 字段重建

**适合场景**：如果你只需要 ChatGPT 工作日志，且希望按日期切分，这是最专注的工具。

---

### 6. 其他单点工具（备选）

| 项目 | URL | 用途 | 备注 |
|---|---|---|---|
| `aghatpande/chatgpt-export` | https://github.com/aghatpande/chatgpt-export | 关键词筛选 + 相关对话扩展 + JSON/HTML 双视图 | MIT, Python 3.10+ |
| `open-export` | https://pypi.org/project/open-export/ | 通过 Chrome DevTools Protocol 直接抓取 ChatGPT（绕过官方导出） | MIT, ⚠️ 需开启 CDP 端口，有安全风险 |
| `pjh456/chatbot_dataset_tools` | https://github.com/pjh456/chatbot_dataset_tools | **ShareGPT ↔ OpenAI ChatML 互转** | Python, 角色映射可配置 |
| `ShareGPTQAExtractor-mnbvc` | https://github.com/pany8125/ShareGPTQAExtractor-mnbvc | ShareGPT 多轮 → 单轮 Q&A（中文 `问/答/来源/元数据`） | 中文社区 |
| HuggingFace TRL `maybe_convert_to_chatml` | https://huggingface.co/docs/trl/en/data_utils | 一行代码 ShareGPT → ChatML 转换 | 官方轻量工具 |
| FastChat `clean_sharegpt.py` | https://github.com/lm-sys/FastChat/blob/main/fastchat/data/clean_sharegpt.py | ShareGPT 清洗 + 长对话切分 | 清洗前置 pipeline |
| `claude-sharegpt-exporter` | https://github.com/EndlessReform/claude-sharegpt-exporter | 浏览器油猴脚本，从 Claude.ai 一键导出 ShareGPT JSON | Claude 上游采集器 |

---

## 二、多模型聚合客户端 Schema 借鉴（TS 项目，参考用）

虽然这些是 TypeScript 项目，但它们的**数据结构设计**值得 Python 项目借鉴。

### 对比表

| 项目 | Star | 维护 | 多平台解析 | 官方导出导入 | Python 借鉴价值 |
|---|---|---|---|---|---|
| **LobeChat** | 80.6k | 极活跃 | ✅ agent-runtime 适配层 | ✅ ChatGPT/Claude | ★★★★★ |
| NextChat | 88.5k | 活跃 | OpenAI 风格统一 | ✅ ChatGPT | ★★★ |
| Big-AGI | 7.05k | 极活跃 | 18+ provider + 上游容器 | ❌ | ★★★★ |
| chatbot-ui | 33.3k | 停更 | 枚举式 | ❌ | ★★ |
| BetterChatGPT | 8.4k | 停更 | 仅 OpenAI | ❌ | ★ |

### ⭐ LobeChat Schema（最完备，强烈推荐参考）

GitHub: https://github.com/lobehub/lobe-chat （现 monorepo: lobehub/lobehub）

```typescript
// packages/database/src/schemas/message.ts (Drizzle pgTable)
messages = pgTable('messages', {
  id: text('id').primaryKey(),
  role: varchar('role').notNull(),          // user/assistant/system/tool
  content: text('content'),
  editorData: jsonb,
  summary: text,
  reasoning: jsonb<ModelReasoning>(),       // 思维链独立列
  search: jsonb<GroundingSearch>(),         // 搜索 grounding 独立列
  metadata: jsonb,
  usage: jsonb<ModelUsage>(),               // token usage 独立列
  model: text,                              // 关键：provider/model 分离
  provider: text,
  favorite: boolean,
  error: jsonb,
  tools: jsonb,
  traceId: text,                            // 可观测性
  observationId: text,
  sessionId, topicId, threadId,             // threadId 支持分支对话
  parentId,                                 // 树状对话结构
  quotaId, agentId,
  messageGroupId,                           // 多模型并行回复
  workspaceId, userId,
  createdAt, updatedAt
});
```

**借鉴点**：
1. `provider` + `model` 分离存储
2. `reasoning` / `search` / `usage` 独立 jsonb 列（不污染 content）
3. `threadId`（分支对话）+ `parentId`（树状）
4. `messageGroupId`（多模型并行回复）
5. `traceId` 可观测性
6. 配套子表：`message_plugins` / `message_tts` / `message_translates` / `messages_files` / `message_chunks`（RAG）

### Big-AGI Fragment 系统（创新点）

GitHub: https://github.com/enricoros/big-AGI

```typescript
interface DMessage {
  id: string;
  role: 'user'|'assistant'|'system';
  fragments: DMessageFragment[];   // 关键：一条消息由多个 fragment 组成
  created: number;
  updated: number | null;
  tokenCount: number;
  generator?: {
    mgt: 'named'|'aix',
    name,
    upstreamContainer?: 'vnd.ant'|'vnd.oai'|'vnd.gem',  // 厂商容器
    upstreamHandle?: 'vnd.oai.responses'|'vnd.gem.interactions',
    tokenStopReason?
  };
}

type DMessageFragment =
  | { ft:'content',    part: {pt:'text'|'error'|'image_ref'|'tool_invocation'|'tool_response'} }
  | { ft:'attachment', part: {pt:'doc'|'image_ref'} }
  | { ft:'void',       part: ... };
```

**借鉴点**：Fragment 系统让一条消息可由文本/图像/工具调用/工具响应多种 part 组合，且 `upstreamContainer` 显式保留厂商容器 ID 便于回溯。

---

## 三、ShareGPT V3 — 事实标准中间格式

被 HuggingFace / Axolotl / LLaMA-Factory / TRL / FastChat 生态广泛采纳。

```json
{
  "id": "<对话唯一 ID>",
  "conversations": [
    {"from": "human",       "value": "..."},
    {"from": "gpt",         "value": "..."},
    {"from": "observation", "value": "<tool result>"},
    {"from": "function_call", "value": "<tool args JSON>"}
  ],
  "system": "<可选, 系统提示>",
  "tools":  "<可选, 工具描述 JSON>"
}
```

**角色约束**：奇数位必须是 `human`/`observation`；偶数位必须是 `gpt`/`function_call`

**HF ChatML 变体**（TRL 一行转换）：
```json
{"role": "user", "content": "..."}
```

---

## 四、各 LLM 平台官方导出格式速查表

| 平台 | 官方导出格式 | 是否有现成 Python 解析器 | 备注 |
|---|---|---|---|
| **OpenAI ChatGPT** | ZIP 内含 `conversations.json` + `model_comparisons.json` + 媒体文件（.dat） | ✅ 多个（`llm-logparser` / `temnoon` / `chatgpt-export-tool`） | 2026 新版多 GB 嵌套 ZIP |
| **Anthropic Claude** | JSON（conversations 数组） | ✅ `llm-logparser` / `temnoon` / `nullhyeon` | |
| **Google Gemini** | "My Activity" 导出（JSON/HTML） | ✅ `llm-logparser`（仅 My Activity） | 无官方对话级 JSON |
| **xAI Grok** | JSON | ✅ `llm-logparser` / `nullhyeon` | |
| **Mistral Le Chat** | JSON | ✅ `llm-logparser` | |
| **DeepSeek** | 网页端可下载对话 JSON | ❌ 需自写（结构简单） | 无批量导出 API |
| **Qwen / 通义千问** | ❌ 无批量导出 | ❌ 需浏览器扩展或 API | 仅单条分享 |
| **GLM / 智谱** | ❌ 无批量导出 | ❌ 需浏览器扩展或 API | |
| **Kimi / Moonshot** | 有官方导出（文档稀缺） | ❌ 仅 JS 扩展（`kimi-exporter`） | |

---

## 五、最终推荐方案

### 方案 A — 直接使用 `llm-logparser` 作为底座（推荐 MVP 阶段）

**适用条件**：你的主要数据源是 ChatGPT / Claude / Gemini / Grok / Mistral，国产模型占比低。

```bash
pip install llm-logparser openai-export-parser
```

```python
from llm_logparser import parse
from openai_export_parser import ExportParser

# 1. 主流平台走 llm-logparser
threads = parse(provider="openai", input_path="conversations.json")

# 2. 需要媒体归档时用 temnoon
ExportParser().parse_export("chatgpt.zip", "archive/")

# 3. 国产模型自写薄适配器，输出 llm-logparser 兼容的 parsed.jsonl
def parse_deepseek(json_path):
    # 自定义解析逻辑
    return [{"thread": ..., "provider": "deepseek", "messages": [...]}]
```

**优点**：MVP 一周内可跑通；离线、MIT、活跃维护
**缺点**：`llm-logparser` Star 极少（社区验证度低），需自行承担稳定性风险

---

### 方案 B — 参考 LobeChat Schema 自写轻量适配器（推荐长期方案）

**适用条件**：你要做产品级 Worklog Agent，需要完整元数据（token 数、模型、成本、思维链等），且要支持国产模型。

**推荐架构**：

```
chatgpt_adapter.py    ─┐
claude_adapter.py     ─┤
gemini_adapter.py     ─┼─→  unified_schema.py (Pydantic)  ─→  worklog_db.sqlite
deepseek_adapter.py   ─┤                                      ↓
qwen_adapter.py       ─┤                                  daily_worklog.md
glm_adapter.py        ─┘
kimi_adapter.py
```

**统一中间层 JSON Schema（融合 LobeChat + Big-AGI + ShareGPT 优点）**：

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime

class Fragment(BaseModel):
    """Big-AGI 风格 fragment — 一条消息可由多个 part 组成"""
    kind: Literal["text", "image", "tool_call", "tool_response", "code", "error"]
    text: Optional[str] = None
    mime_type: Optional[str] = None
    file_path: Optional[str] = None        # 媒体文件本地路径
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    tool_result: Optional[str] = None

class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Optional[float] = None

class UnifiedMessage(BaseModel):
    """统一消息模型 — 融合 LobeChat + ShareGPT"""
    id: str
    session_id: str                          # 对话 ID
    role: Literal["user", "assistant", "system", "tool"]
    content: str                             # 纯文本回退（ShareGPT 兼容）
    fragments: list[Fragment] = []           # 多模态结构化内容
    provider: Literal[
        "openai", "anthropic", "google", "xai", "mistral",
        "deepseek", "qwen", "glm", "kimi", "unknown"
    ]
    model: Optional[str] = None              # gpt-4o / claude-3.5-sonnet / ...
    parent_id: Optional[str] = None          # 树状对话
    thread_id: Optional[str] = None          # 分支对话
    usage: Optional[TokenUsage] = None
    reasoning: Optional[dict] = None         # 思维链（o1/Claude thinking）
    tools: Optional[list[dict]] = None
    trace_id: Optional[str] = None           # 厂商 trace ID
    upstream_ref: Optional[str] = None       # 厂商原始 message ID
    created_at: datetime
    updated_at: Optional[datetime] = None
    source: Literal[
        "chatgpt_export", "claude_export", "gemini_export",
        "deepseek_export", "qwen_export", "glm_export", "kimi_export",
        "api", "manual"
    ]

class UnifiedSession(BaseModel):
    """统一对话模型"""
    id: str
    title: Optional[str] = None
    provider: str
    messages: list[UnifiedMessage]
    created_at: datetime
    updated_at: Optional[datetime] = None
    source: str
    raw_metadata: Optional[dict] = None      # 原始导出元数据保留
```

**优点**：
- 字段最完备（provider/model 分离、token usage、思维链、工具调用、分支树）
- Pydantic v2 强类型 + 自动校验
- 兼容 ShareGPT（content 字段做回退）
- 国产模型只需写 ~50 行 adapter 即可接入
- 可直接映射为 SQLite/Postgres 表

**缺点**：需自行实现各平台 adapter（每平台约 50-150 行）

---

### 方案 C — 混合策略（最务实，推荐）

| 数据源 | 处理方式 |
|---|---|
| ChatGPT 官方导出 | 用 `temnoon/openai_export_parser` 解析 ZIP + 媒体，再映射到 UnifiedMessage |
| Claude 官方导出 | 用 `llm-logparser` 或自写 adapter（JSON 结构简单） |
| Gemini My Activity | 用 `llm-logparser` |
| Grok / Mistral | 用 `llm-logparser` |
| DeepSeek | 自写 adapter（网页下载的 JSON） |
| Qwen / GLM | 自写 adapter + 浏览器扩展采集（参考 `claude-sharegpt-exporter` 模式） |
| Kimi | 用现有 `kimi-exporter` JS 扩展产出 JSON，再 Python 解析 |

**最终统一格式**：采用方案 B 的 Pydantic Schema，所有 adapter 输出 `UnifiedSession` 列表，落库 SQLite，按日期归集生成 worklog。

---

## 六、实施建议

### Phase 1 — MVP（1 周）
1. `pip install llm-logparser openai-export-parser`
2. 定义 `UnifiedMessage` / `UnifiedSession` Pydantic Schema（参考方案 B）
3. 写 `chatgpt_adapter.py`：调用 `temnoon` 解析 ZIP → 映射到 UnifiedMessage
4. 写 `claude_adapter.py`：直接解析 JSON（结构简单）
5. 按日期 group → 生成 `daily_worklog.md`

### Phase 2 — 扩展（2-3 周）
1. 加入 `gemini_adapter.py` / `grok_adapter.py`（走 llm-logparser）
2. 自写 `deepseek_adapter.py`（网页下载 JSON）
3. 浏览器扩展采集 Qwen / GLM / Kimi（参考 `claude-sharegpt-exporter` userscript 模式）

### Phase 3 — 增值（可选）
1. 接入 LobeChat 的 `traceId` / `messageGroupId` 字段
2. 加 Big-AGI 的 fragment 系统（多模态内容）
3. 加 token 成本统计（参考 `llm-logparser` 的 `analyze tokens`）
4. 加 BM25 搜索（参考 echomine 设计）

---

## 七、关键链接速查

### Python 库（PyPI）
- `llm-logparser` — https://pypi.org/project/llm-logparser/
- `openai-export-parser` — https://pypi.org/project/openai-export-parser/
- `llm-conversation-parser` — https://pypi.org/project/llm-conversation-parser/
- `chatgpt-export-tool` — https://pypi.org/project/chatgpt-export-tool/
- `echomine` — https://pypi.org/project/echomine/ （⚠️ AGPLv3）
- `open-export` — https://pypi.org/project/open-export/

### GitHub 仓库
- https://github.com/Syun-tnb/llm-logparser
- https://github.com/temnoon/openai_export_parser
- https://github.com/nullhyeon/llm-conversation-parser
- https://github.com/aghatpande/chatgpt-export
- https://github.com/lobehub/lobe-chat （Schema 参考）
- https://github.com/ChatGPTNextWeb/NextChat （Schema 参考）
- https://github.com/enricoros/big-AGI （fragment 系统）
- https://github.com/pjh456/chatbot_dataset_tools （ShareGPT 互转）

### HuggingFace 数据集（Schema 参考）
- ShareGPT — https://huggingface.co/datasets/anon8231489123/ShareGPT_Vicuna_unfiltered
- WildChat-1M — https://huggingface.co/datasets/allenai/WildChat-1M
- LMSYS-Chat-1M — https://huggingface.co/datasets/lmsys/lmsys-chat-1m （25 个 LLM 平台）

### 文档参考
- HuggingFace TRL 数据工具 — https://huggingface.co/docs/trl/en/data_utils
- FastChat ShareGPT 清洗 — https://github.com/lm-sys/FastChat/blob/main/fastchat/data/clean_sharegpt.py
