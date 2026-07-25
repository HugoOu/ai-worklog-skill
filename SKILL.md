---
name: ai-worklog
description: |
  Parse multi-platform LLM conversation exports (ChatGPT, Gemini) into unified format and cluster them into structured work logs. This skill should be used when the user provides LLM platform export files (JSON/HTML/ZIP) and wants to convert them to a unified format, or when the user wants to generate work logs from their AI conversation history. Triggers include "解析对话", "导入对话记录", "生成工作日志", "ChatGPT 导出", "Gemini 导出", "parse conversations", "generate worklog".
agent_created: true
---

# AI Worklog

## 何时触发

- 用户提供 LLM 平台导出文件（JSON / HTML / ZIP），需要转为统一格式
- 用户想从 AI 对话历史生成结构化工作日志
- 用户想跨平台合并对话记录（如 ChatGPT + Gemini）
- 用户问"这些对话都讨论了什么主题"

## 前置条件

- **项目根目录**：`C:\Users\Exception2Rule\ai-worklog-skill`
- **Python 解释器**：`.venv/Scripts/python.exe`（项目内 venv）
- **LLM 配置**：`.env` 文件含 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `LLM_MODEL`（cluster 命令需要，parse 不需要）

## CLI 命令参考

所有命令在项目根目录执行。CLI 入口：`python -m src.cli`。

### 1. parse — 解析单个导出文件为统一格式

```bash
.venv/Scripts/python.exe -m src.cli parse <input_path> [options]
```

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--provider, -p` | `auto` | 平台标识：`auto`(自动探测) / `openai` / `google` |
| `--format, -f` | `json` | 输出格式：`json` / `jsonl` |
| `--outdir, -o` | `./output` | 输出目录 |
| `--tz` | `Asia/Shanghai` | 时区归一化目标 |
| `--group-by-date` | `false` | 额外输出 `daily_conversations.json`（按天归集） |

**示例**：
```bash
# 自动探测格式
.venv/Scripts/python.exe -m src.cli parse examples/conversations.json -o ./output

# 显式指定 Gemini
.venv/Scripts/python.exe -m src.cli parse examples/gemini_1000.html -p google -o ./output
```

**输出**：`<outdir>/unified_sessions.json`（UnifiedSession 数组）

### 2. cluster — 端到端聚类（解析 → 按天归集 → LLM 聚类）

```bash
.venv/Scripts/python.exe -m src.cli cluster <input1> <input2> ... [options]
```

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--outdir, -o` | `./output` | 输出目录 |
| `--tz` | `Asia/Shanghai` | 时区归一化目标 |
| `--dry-run` | `false` | 只做 parse + 按天归集，不调 LLM（快速预览数据分布） |

**示例**：
```bash
# 完整聚类（调 LLM，有延迟和费用）
.venv/Scripts/python.exe -m src.cli cluster examples/conversations.json examples/gemini_1000.html -o ./output

# 快速预览（不调 LLM，秒出按天归集结果）
.venv/Scripts/python.exe -m src.cli cluster examples/conversations.json --dry-run
```

**输出**（3 个文件）：
- `unified_sessions.json` — 统一格式解析结果（所有平台合并）
- `daily_conversations.json` — 按天归集（跨平台同一天的消息合并）
- `candidates.json` — 聚类候选工作项（每个含 topic / summary / evidence / dates）

### 3. adapters — 列出已注册 adapter

```bash
.venv/Scripts/python.exe -m src.cli adapters
```

### 4. parse-batch — 批量扫描目录

```bash
.venv/Scripts/python.exe -m src.cli parse-batch <input_dir> [--pattern "**/*.{json,jsonl,html,zip}"] [-o ./output]
```

## 输出格式契约

### unified_sessions.json

```json
[
  {
    "id": "会话唯一 ID",
    "title": "会话标题",
    "provider": "openai | google",
    "model": "gpt-5-2 | null",
    "messages": [
      {
        "id": "消息 ID",
        "session_id": "所属会话 ID",
        "role": "user | assistant | system | tool",
        "content": "纯文本内容",
        "provider": "openai | google",
        "model": "gpt-5-2 | null",
        "created_at": "2026-02-24T00:07:56.508145+08:00",
        "source": "chatgpt_export | gemini_export"
      }
    ],
    "created_at": "2026-02-24T00:07:56.508145+08:00",
    "source": "chatgpt_export | gemini_export"
  }
]
```

关键字段：
- `provider` + `model` 分离存储（借鉴 LobeChat）
- `created_at` 已归一化到 `Asia/Shanghai`（UTC+8）
- `content` 是纯文本（ChatGPT 内联实体标记已清理）

### candidates.json

```json
[
  {
    "topic": "主题名称（10-20字）",
    "summary": "主题讨论过程和结论的简要总结（50-150字）",
    "evidence": "对话中支持该主题的原始文本片段，一字不差",
    "dates": ["2026-05-20", "2026-05-21"]
  }
]
```

`dates` 含多个日期表示跨天合并的主题。

## Agent 决策规则

1. **用户给单个文件路径** → 调 `parse`
2. **用户给多个文件 + 想生成工作日志** → 调 `cluster`
3. **用户未指定 provider** → 用 `auto`（pipeline 自动探测格式）
4. **用户想快速看数据分布** → 调 `cluster --dry-run`（不调 LLM，秒出）
5. **用户想看支持哪些平台** → 调 `adapters`
6. **输出文件路径必须返回给用户确认**，不要静默处理
7. **cluster 不带 --dry-run 时会调 LLM**（有费用），先用 `--dry-run` 预览，确认数据无误后再跑完整聚类

## 支持的平台

| 平台 | provider | 输入格式 | 状态 |
|------|----------|----------|------|
| OpenAI ChatGPT | `openai` | `conversations.json`（裸 JSON 或 ZIP） | ✅ 已实现 |
| Google Gemini | `google` | My Activity HTML | ✅ 已实现 |
| Anthropic Claude | `anthropic` | JSON | ⏸️ 预留 |
| xAI Grok | `xai` | JSON | ⏸️ 预留 |
| DeepSeek | `deepseek` | JSON | ⏸️ 预留 |
| Qwen / 通义千问 | `qwen` | JSON | ⏸️ 预留 |
| GLM / 智谱 | `glm` | JSON | ⏸️ 预留 |
| Kimi / Moonshot | `kimi` | JSON | ⏸️ 预留 |
| MiniMax | `minimax` | JSON | ⏸️ 预留 |

预留平台只需在 `src/adapters/` 下新增 adapter 文件并注册到 `REGISTRY` 即可接入，接口已固化。

## 典型工作流

```
用户："帮我解析这个 ChatGPT 导出"
  ↓
Agent: aiworklog parse conversations.json -o ./output
  ↓
返回: unified_sessions.json 路径 + 会话数摘要

用户："把 ChatGPT 和 Gemini 的对话合并生成工作日志"
  ↓
Agent: aiworklog cluster conversations.json gemini_1000.html -o ./output --dry-run
  ↓ (先 dry-run 预览)
返回: 按天归集摘要，确认数据分布
  ↓
用户确认后:
Agent: aiworklog cluster conversations.json gemini_1000.html -o ./output
  ↓ (调 LLM 聚类)
返回: candidates.json 路径 + 候选工作项列表
```
