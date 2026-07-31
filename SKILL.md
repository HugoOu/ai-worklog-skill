---
name: ai-worklog
description: |
  Parse multi-platform LLM conversation exports (ChatGPT, Gemini) into a unified
  format, cluster them into a hierarchical topic tree, and generate Markdown work
  logs. Use this skill when the user provides LLM platform export files
  (JSON/HTML/ZIP) and wants to convert them to a unified format, cluster
  conversation history into themes, or generate structured work logs. Triggers
  include "解析对话", "导入对话记录", "生成工作日志", "聚类对话主题", "ChatGPT 导出",
  "Gemini 导出", "parse conversations", "cluster conversations", "generate worklog".
---

# AI Worklog

A platform-agnostic Agent Skill. Works with any coding agent that supports the
`SKILL.md` convention (Claude Code, Codex, Cursor, OpenClaw, WorkBuddy, etc.).
The agent shell-executes the CLI below; nothing in this skill is tied to a
specific agent platform.

## When to use

- The user provides an LLM platform export file (JSON / HTML / ZIP) and wants it converted to a unified format
- The user wants to generate a structured work log from their AI conversation history
- The user wants to merge conversation records across platforms (e.g. ChatGPT + Gemini)
- The user asks "what themes/topics are in these conversations"

## Prerequisites

- **Project root**: the directory containing this `SKILL.md` (e.g. `C:\Users\Exception2Rule\ai-worklog-skill`)
- **Python interpreter**: prefer the project venv. On Windows: `.venv/Scripts/python.exe`; on macOS/Linux: `.venv/bin/python`. Fall back to system `python3` if no venv exists (run `python3 -m pip install -e .` first).
- **LLM config**: a `.env` file in the project root with `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `LLM_MODEL`. Required by `cluster` / `generate` / `tree`; **not** required by `parse` / `parse-batch` / `adapters`.

Throughout this document `$PY` denotes the interpreter. Set it once:

```bash
# Windows (Git Bash)
PY=.venv/Scripts/python.exe
# macOS / Linux
PY=.venv/bin/python
```

All commands run from the project root. CLI entry: `$PY -m src.cli <cmd>`
(equivalent to `aiworklog <cmd>` after `pip install -e .`).

## CLI command reference

### 1. parse — parse a single export file into the unified format

```bash
$PY -m src.cli parse <input_path> [options]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--provider, -p` | `auto` | Platform: `auto` (detect) / `openai` / `google` |
| `--format, -f` | `json` | Output format: `json` / `jsonl` |
| `--outdir, -o` | `./output` | Output directory |
| `--tz` | `Asia/Shanghai` | Timezone normalization target |
| `--group-by-date` | `false` | Also emit `daily_conversations.json` |

Examples:

```bash
$PY -m src.cli parse examples/conversations.json -o ./output          # auto-detect
$PY -m src.cli parse examples/gemini_1000.html -p google -o ./output  # explicit Gemini
```

Output: `<outdir>/unified_sessions.json` (array of UnifiedSession).

### 2. parse-batch — batch-scan a directory

```bash
$PY -m src.cli parse-batch <input_dir> [-o ./output] [--tz Asia/Shanghai]
```

Recursively scans `*.json/*.jsonl/*.html/*.htm/*.zip`, parses each, and merges.

### 3. cluster — end-to-end clustering (parse → daily grouping → Map → cluster)

```bash
$PY -m src.cli cluster <input1> <input2> ... [options]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--outdir, -o` | `./output` | Output directory |
| `--tz` | `Asia/Shanghai` | Timezone normalization target |
| `--dry-run` | `false` | Parse + daily grouping only, no LLM (fast preview) |
| `--legacy-reduce` | `false` | Use legacy LLM Map-Reduce instead of embedding clustering |

Examples:

```bash
# Preview data distribution (no LLM, instant, free)
$PY -m src.cli cluster examples/conversations.json --dry-run

# Full clustering (default: embedding mode with Map cache; deterministic)
$PY -m src.cli cluster examples/conversations.json examples/gemini_1000.html -o ./output
```

Output (3 files):
- `unified_sessions.json` — unified parse result (all platforms merged)
- `daily_conversations.json` — grouped by day (cross-platform same-day messages merged)
- `candidates.json` — clustered candidate work items (each has topic / summary / evidence / dates / session_ids)

Map results are cached per day under `<outdir>/.map_cache/`; a rerun on the same
input hits the cache (0 LLM calls, sub-second).

### 4. tree — build the RAPTOR hierarchical topic tree

```bash
$PY -m src.cli tree <input1> <input2> ... [-o ./output] [--tz Asia/Shanghai] [-t/--threshold 0.45]
```

Flow: parse → daily grouping → Map (cached) → recursive embedding clustering → TopicTree.

```bash
$PY -m src.cli tree examples/conversations.json -o ./output
$PY -m src.cli tree examples/conversations.json -t 0.3 -o ./output   # stricter clustering
```

Output: `<outdir>/topic_tree.json` + a rich tree printout in the terminal. Leaf
nodes carry `session_ids` that link back to the original conversations.

> The topic tree is the **core intermediate artifact** for log generation — not a
> separate deliverable. Workflow: build the tree → user selects nodes at the
> desired granularity (task / theme / project) → render Markdown log. Selecting
> any node auto-expands its entire subtree (see `generate --tree` below).

### 5. generate — produce a Markdown work log

Two modes (pick one):

**Flat mode** (default, from `candidates.json`):

```bash
$PY -m src.cli generate <candidates.json> [--select 2,3,9-11] [--date-range A:B] [--interactive] [--all] [--polish/--no-polish] [-o ./output]
```

Selection modes are mutually exclusive (priority: select > date-range > interactive > all).

```bash
$PY -m src.cli generate output/candidates.json --all -o ./output            # select all, polish to first person
$PY -m src.cli generate output/candidates.json --select 2,3,9-11            # by index
$PY -m src.cli generate output/candidates.json --date-range 2026-03-26:2026-06-09
$PY -m src.cli generate output/candidates.json --all --no-polish            # skip LLM polish
```

**Tree mode** (`--tree`, tree-as-outline):

```bash
$PY -m src.cli generate --tree <topic_tree.json> [--nodes <id1>,<id2>] [--interactive] [--polish/--no-polish] [-o ./output]
```

Each selected node auto-expands its whole subtree; overlapping selections are
de-duplicated by leaf. With neither `--nodes` nor `--interactive`, all root nodes
are selected by default. `--interactive` prints a numbered tree to pick from.

```bash
$PY -m src.cli generate --tree output/topic_tree.json --interactive          # numbered tree, type numbers
$PY -m src.cli generate --tree output/topic_tree.json --nodes <id1>,<id2>    # specific node ids
$PY -m src.cli generate --tree output/topic_tree.json --no-polish            # all roots, no LLM polish
```

Output: `<outdir>/worklog.md` (YAML frontmatter + date-organized work items).

### 6. adapters — list registered platform adapters

```bash
$PY -m src.cli adapters
```

### 7. query — query stored conversations (placeholder, Phase 2, not implemented)

```bash
$PY -m src.cli query [--db worklog.db] [--date] [--provider] [--keyword]
```

## Output format contract

### unified_sessions.json

```json
[
  {
    "id": "session unique ID",
    "title": "session title",
    "provider": "openai | google",
    "model": "gpt-5-2 | null",
    "messages": [
      {
        "id": "message ID",
        "session_id": "owning session ID",
        "role": "user | assistant | system | tool",
        "content": "plain text content",
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

Key fields:
- `provider` + `model` stored separately
- `created_at` normalized to `Asia/Shanghai` (UTC+8)
- `content` is plain text (ChatGPT inline entity markers already cleaned)

### candidates.json

```json
[
  {
    "topic": "theme name (10-20 chars)",
    "summary": "brief summary of the discussion and conclusion (50-150 chars)",
    "evidence": "verbatim source snippet supporting the theme",
    "dates": ["2026-05-20", "2026-05-21"],
    "session_ids": ["origin UnifiedSession.id"]
  }
]
```

Multiple `dates` indicate a cross-day merged theme; `session_ids` form the evidence chain back to source conversations.

### topic_tree.json

```json
{
  "meta": { "total_nodes": 12, "depth": 3, "total_sessions": 9, "cluster_params": {"distance_threshold": 0.45} },
  "nodes": {
    "<node_id>": {
      "node_id": "...", "depth": 0, "label": "...", "summary": "...",
      "children": [], "session_ids": ["..."], "dates": ["..."], "parent_id": null
    }
  },
  "root_ids": ["<top-level node_id>"]
}
```

`depth=0` nodes are leaves (carry `session_ids`); higher depths are cluster-produced parents (`children` links to child node_ids).

## Agent decision rules

1. **User gives a single file path** → call `parse`
2. **User gives multiple files and wants a work log** → call `cluster` (or `tree` for hierarchical structure)
3. **User does not specify a provider** → use `auto` (pipeline auto-detects the format)
4. **User wants a quick look at data distribution** → call `cluster --dry-run` (no LLM, instant)
5. **User wants to know which platforms are supported** → call `adapters`
6. **Always return output file paths to the user for confirmation** — do not handle silently
7. **`cluster`/`tree`/`generate` (without `--dry-run`/`--no-polish`) call an LLM** (costs money). Preview with `--dry-run` first, then run the full pipeline once the data looks right.

## Supported platforms

| Platform | provider | Input format | Status |
|----------|----------|--------------|--------|
| OpenAI ChatGPT | `openai` | `conversations.json` (bare JSON or ZIP) | ✅ implemented |
| Google Gemini | `google` | My Activity HTML | ✅ implemented |
| Anthropic Claude | `anthropic` | JSON | ⏸️ reserved |
| xAI Grok | `xai` | JSON | ⏸️ reserved |
| DeepSeek | `deepseek` | JSON | ⏸️ reserved |
| Qwen | `qwen` | JSON | ⏸️ reserved |
| GLM / Zhipu | `glm` | JSON | ⏸️ reserved |
| Kimi / Moonshot | `kimi` | JSON | ⏸️ reserved |
| MiniMax | `minimax` | JSON | ⏸️ reserved |

Reserved platforms only need a new adapter file under `src/adapters/` registered in `REGISTRY`; the interface is frozen.

## Typical workflow

```
User: "parse this ChatGPT export"
  → Agent: $PY -m src.cli parse conversations.json -o ./output
  → returns: unified_sessions.json path + session count

User: "merge ChatGPT + Gemini and generate a work log"
  → Agent: $PY -m src.cli cluster conversations.json gemini_1000.html -o ./output --dry-run   # preview first
  → returns: daily-grouping summary; confirm data distribution
  → after user confirms:
  → Agent: $PY -m src.cli cluster conversations.json gemini_1000.html -o ./output             # full clustering
  → returns: candidates.json path + candidate list
  → Agent: $PY -m src.cli generate output/candidates.json --all -o ./output
  → returns: worklog.md path
```

## MCP server (optional)

The same capabilities are also exposed as an MCP server (`src/mcp_server.py`) with
4 tools: `parse_conversations` / `cluster_conversations` / `list_adapters` /
`generate_worklog`. Install with `pip install -e .[mcp]` and run
`$PY -m src.mcp_server`. This is a generic MCP server usable by any MCP client,
not tied to a specific agent platform.
