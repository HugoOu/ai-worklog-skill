# Handoff — ai-worklog-skill

> 写给接手这个项目的下一位 AI / 开发者。截至 2026-07-29 的完整状态快照。
> 仓库：`git@github.com:HugoOu/ai-worklog-skill.git`（SSH，main 分支）
> 作者：宇豪（上海财经大学 2026 级应用统计硕士，主目标就业方向 = AI Agent 开发）

---

## 1. 这是什么

一个把**多平台 AI 对话导出**（ChatGPT / Gemini / …）自动解析为统一格式，再聚类成结构化**工作日志**的工具。

核心流水线（自底向上）：

```
导出文件 (JSON/HTML/ZIP)
   │  parse (adapter 自动探测)
   ▼
UnifiedSession[]              src/unified_schema.py
   │  bridge (按天归集 + 注入 session_id)
   ▼
DailyConversation[]           src/models.py
   │  Map (LLM 提取日级候选，带磁盘缓存)
   ▼
CandidateItem[]               src/models.py (兼容层)
   │  Cluster (Embedding + AgglomerativeClustering，确定性)
   ▼
CandidateItem[] (跨天合并)     → candidates.json → generate 命令 → worklog.md
   │  （可选）RAPTOR 递归聚类
   ▼
TopicTree                     src/models.py → topic_tree.json
```

两条产出线：
- **candidates.json**（扁平候选）→ `generate` 命令 → Markdown 工作日志
- **topic_tree.json**（层级主题树）→ `tree` 命令，终端 rich 树状图 + JSON

---

## 2. 目录结构

```
ai-worklog-skill/
├── handoff.md              ← 本文件
├── README.md               ← 聚类架构演进路线图（① Map-Reduce / ③ Embedding / RAPTOR / ② Agent）
├── SKILL.md                ← WorkBuddy Skill 定义（CLI 命令参考 + 平台支持表）
├── pyproject.toml          ← 依赖 + entry point: aiworklog = "src.cli:app"
├── .env                    ← 【gitignore，勿提交】OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL
├── docs/
│   ├── LLM对话记录统一解析_开源侦察报告.md
│   └── 实现路径_多平台对话解析模块.md
├── examples/
│   ├── conversations.json  ← 【gitignore，敏感真实数据】ChatGPT 导出
│   ├── ai_history.html     ← Gemini 导出样本
│   └── gemini_1000.html
├── src/
│   ├── cli.py              ← typer 入口：parse / parse-batch / cluster / generate / tree / adapters / query
│   ├── pipeline.py         ← run(): detect → parse → normalize(tz) → export
│   ├── unified_schema.py   ← UnifiedSession / UnifiedMessage（Pydantic v2）
│   ├── bridge.py           ← unified_to_daily(): UnifiedSession[] → DailyConversation[]
│   ├── models.py           ← 数据模型全家桶（见 §4）
│   ├── extractor.py        ← LLM Map + Reduce 逻辑、SYSTEM_PROMPT、JSON 截断修复
│   ├── cache.py            ← MapCacheStore：按 content_hash 的磁盘缓存
│   ├── embedding.py        ← embed_texts() + cluster_candidates()（DashScope text-embedding-v3）
│   ├── raptor.py           ← build_topic_tree()：递归聚类建树
│   ├── clustering.py       ← ClusteringStrategy 抽象 + MapReduceClustering + EmbeddingClustering
│   ├── generator.py        ← 候选筛选 + Markdown 生成（filter_* / generate_markdown）
│   ├── mcp_server.py       ← MCP server 包装（parse / cluster / list_adapters 三个 tool）
│   ├── parser.py           ← 旧版独立解析器（早期遗留，pipeline 未直接使用）
│   └── adapters/
│       ├── __init__.py     ← REGISTRY（已注册 ChatGPT + Gemini）
│       ├── base.py         ← BaseAdapter 抽象（provider / detect() / parse()）
│       ├── chatgpt.py      ✅ 已实现（18 tests）
│       └── gemini.py       ✅ 已实现（14 tests）
└── tests/
    ├── conftest.py
    ├── test_chatgpt_adapter.py / test_gemini_adapter.py / test_pipeline.py
    ├── test_bridge.py (3) / test_cache.py (5) / test_generator.py
    ├── test_models_schema.py (14) / test_raptor.py (7)
    └── legacy/             ← 脚本式示例（test_extractor.py / test_parser.py，pytest 不收集）
```

测试规模：**116 passed**（截至最后一次端到端验证）。

---

## 3. 模块职责与关键 API

### `src/cli.py` — 统一入口
命令（`python -m src.cli <cmd>` 或安装后 `aiworklog <cmd>`）：

| 命令 | 作用 | 关键选项 |
|------|------|----------|
| `parse` | 单文件解析 → unified_sessions.json | `-p auto\|openai\|google`, `-o`, `--group-by-date` |
| `parse-batch` | 目录批量解析 | `-o`, `--tz` |
| `cluster` | parse→bridge→Map(缓存)→聚类→candidates.json | `--dry-run`, `--legacy-reduce` |
| `generate` | 候选→Markdown 工作日志 | `--select 2,3,9-11`, `--date-range`, `--interactive`, `--all`, `--polish/--no-polish`(默认 True) |
| `tree` | 构建 RAPTOR 层级主题树 → topic_tree.json | `-t/--threshold`(默认 0.45), `-o` |
| `adapters` | 列出已注册 adapter | — |
| `query` | 查询落库对话 | ⏸️ TODO（Phase 2，当前仅占位） |

### `src/pipeline.py`
- `run(input_path, provider="auto", out_format="json", outdir=None, timezone_str="Asia/Shanghai", group_by_date=False) -> list[UnifiedSession]`
  - **注意：input_path 必须是 Path 对象，传 str 会 AttributeError。**
- `detect_provider(path)`：遍历 REGISTRY 取 detect() 置信度最高者，阈值 0.3，否则 ValueError。
- `normalize_timezone()`：统一 astimezone 到 Asia/Shanghai（无 tzinfo 假定 UTC）。

### `src/bridge.py`
- `unified_to_daily(sessions) -> list[DailyConversation]`
- **证据链关键点**：构造 `ConversationMessage` 时写入 `session_id=sess.id`，这是整条证据链的源头。

### `src/extractor.py` — LLM Map/Reduce
- `extract_candidates_from_daily(daily_conv, log=print) -> list[CandidateItem]`
  - `temperature=0`、`response_format={"type":"json_object"}`
  - 守卫 `if not response.choices`（DashScope 内容审核会返回 choices=None → 曾触发 `'NoneType' object is not subscriptable`）
  - `finish_reason=="length"` → `_repair_truncated_json()`（JSON 感知状态机：跟踪 in_string/escape/花括号深度，提取所有完整闭合对象，重建 `{"candidates":[...]}`）
  - 条目级容错：单条 `CandidateItem(**item)` 失败只跳过该条
  - **证据链**：捕获当天 `day_session_ids`（去重保序），赋给每个候选的 `cand.session_ids`（日级粗粒度归因）
- `merge_cross_day_candidates(candidates)`：Reduce 阶段，仅传 topic+summary+date 给 LLM，evidence 在代码按 `source_indices` 拼接（保证一字不差）。未引用候选兜底保留。
- 常量：`MSG_CHAR_LIMIT=1500`（每条消息截断），`MAX_TOKENS=8192`。

### `src/cache.py` — MapCacheStore
- 文件名：`{date}_{content_hash}.json`，content_hash = `sha256(f"{date}|{role:content...}")[:16]`
- 命中条件三合一：`content_hash 相同` + `prompt_version 相同` + `is_valid`（有候选且未截断）
- 改 SYSTEM_PROMPT → 递增 `clustering.PROMPT_VERSION`（当前 `"v2"`）触发全量失效
- API：`get/put/invalidate/clear/stats`

### `src/embedding.py` — 确定性聚类
- `EMBEDDING_MODEL = text-embedding-v3`（DashScope）
- **`embed_texts(texts, batch_size=10)`：DashScope 限制每次最多 10 条（不是 25！曾报 BadRequestError），按 index 排序保序。**
- `cluster_candidates(candidates, distance_threshold=None)`：
  - 文本 = `f"{topic}。{summary}"`
  - `AgglomerativeClustering(n_clusters=None, distance_threshold, metric="precomputed", linkage="average")` + `cosine_distances`
  - 同簇合并：dates 并集、session_ids 并集（保序去重）、topic 取公共前缀（≥6 字）否则 `"首项等N项"`

### `src/raptor.py` — 递归主题树
- `build_topic_tree(candidates, distance_threshold=None, log=print) -> TopicTree`
  - 每个 CandidateItem → depth-0 叶子（`session_ids=cand.session_ids`，证据链落到叶）
  - 逐层 embedding+聚类→合并父节点，收敛条件：`簇全为单例` 或 `节点数≤MIN_TOP_NODES` 或 `depth≥MAX_DEPTH`
  - 单节点簇直接提升、不建空父节点
- 父节点 label：先 `_strip_suffix()` 去掉子标签的 `"等N项"`（修复了 `"X等2项等2项等2项"` 层层叠加 bug），再求 commonprefix（≥6 用前缀，否则 `"最短标签等N项"`，N=当层子数不累积）
- 环境变量：`RAPTOR_MAX_DEPTH`(默认 5)、`RAPTOR_MIN_TOP_NODES`(默认 2)
- `print_tree(tree, console)`：rich Tree 终端可视化

### `src/clustering.py` — 策略层
- `ClusteringStrategy.cluster(daily) -> list[CandidateItem]`（抽象，下游不感知实现）
- `MapReduceClustering`：旧版，LLM Map(并发) + LLM Reduce（不确定性来源，用 `--legacy-reduce` 启用）
- `EmbeddingClustering`（默认）：LLM Map(缓存) + embedding 聚类（确定性）
- 并发：`MAP_WORKERS`（默认 5，ThreadPoolExecutor）

---

## 4. 数据模型（`src/models.py`）

层级（自底向上）：

```
ConversationMessage   role/content/date/session_id
DailyConversation     date/messages  +  content_hash 属性
MessageRef            session_id/message_index/role/preview/snippet  ← 证据层（预留，尚未全链路接入）
CandidateTopic        candidate_id/topic/summary/source_refs/session_ids/confidence  ← Map 缓存用
MapRunMeta            run_id/model/temperature/max_tokens/prompt_version/created_at/duration_ms/finish_reason/truncated/repaired
DayMapCache           cache_key/date/input_message_count/map_run/candidates  +  is_valid 属性
TopicNode             node_id/depth/label/summary/role_hint/children/session_ids/parent_id/dates/embedding/embedding_model/map_cache_keys
TopicTreeMeta         tree_id/created_at/method/embedding_model/cluster_params/total_sessions/total_nodes/depth
TopicTree             meta/nodes(dict)/root_ids  +  get_children()/get_sessions_under()(递归)/to_json()/from_json()
```

兼容层（**不要删，CLI/generator/tests 仍在用**）：`CandidateItem`(topic/summary/evidence/dates/session_ids)、`WorkItem`、`WorklogData`。

**设计要点**：
- 曾考虑固定 4 级 `TopicLevel` 枚举（session/task/component/project），被否决 → 改用 `depth: int`（聚类自然产出）+ 可选 `role_hint`（仅展示）。理由见 §5。
- 所有模型 Pydantic v2，支持 JSON round-trip。

---

## 5. 关键设计决策（为什么这么做）

1. **从 LLM Map-Reduce 切到 Embedding 聚类 —— 用户驱动的架构转向。**
   - 痛点：(a) 每次跑结果不同（5 vs 10 个候选，temperature 降到 0 也压不住服务端非确定性）；(b) JSON 输出截断；(c) 18 天串行调 LLM 要 10+ 分钟。
   - 解法：LLM 只做 Map（且缓存），跨天合并交给确定性的 embedding+层次聚类。验证：两次运行 `diff` 完全一致，Map 命中缓存后 0 次 LLM 调用、亚秒级。

2. **拒绝固定 4 级层级枚举。** 用户自己质疑"四个 TopicNode 层级是拍脑袋想的"。实际数据里多数对话是单日的，硬塞 4 级会产生大量空层。改为 depth 由数据决定。

3. **证据链（session_id 全程贯通）。** 从 `UnifiedSession.id` → `ConversationMessage.session_id`（bridge 注入）→ `CandidateItem.session_ids`（Map 日级归因）→ `TopicNode` 叶子 → 父节点并集聚合。端到端验证 28/28 消息携带 session_id。

4. **缓存用 content_hash 而非时间戳。** 内容变了才失效；prompt 改了靠 `prompt_version` 失效。双保险。

5. **evidence 不让 LLM 改写。** Reduce/合并时 LLM 只碰 topic+summary，evidence 在代码按索引拼接，保证原文一字不差。

---

## 6. 环境配置与运行

```bash
cd C:\Users\Exception2Rule\ai-worklog-skill

# 依赖（项目内 venv 已建好，优先用它）
.venv/Scripts/python.exe -m pip install -e .
# 核心依赖：pydantic>=2.5 typer rich beautifulsoup4 lxml python-dotenv openai numpy>=1.24 scikit-learn>=1.3

# .env（gitignore，必填 LLM 配置；embedding 复用同一 OPENAI_BASE_URL=DashScope 兼容端点）
OPENAI_API_KEY=...
OPENAI_BASE_URL=...     # DashScope OpenAI 兼容端点
LLM_MODEL=...           # 如 qwen3.7-flash
```

常用命令（Windows，venv）：

```bash
PY=.venv/Scripts/python.exe

# 预览数据分布（不调 LLM，秒出）
$PY -m src.cli cluster examples/conversations.json --dry-run

# 端到端聚类（默认 Embedding，带缓存；第二次跑命中缓存秒出）
$PY -m src.cli cluster examples/conversations.json -o ./output

# 生成工作日志
$PY -m src.cli generate output/candidates.json --all -o ./output
$PY -m src.cli generate output/candidates.json --select 2,3,9-11

# 构建主题树
$PY -m src.cli tree examples/conversations.json -o ./output -t 0.3
```

可调环境变量：`MAP_WORKERS`(5)、`CLUSTER_DISTANCE_THRESHOLD`(0.45)、`EMBEDDING_MODEL`(text-embedding-v3)、`RAPTOR_MAX_DEPTH`(5)、`RAPTOR_MIN_TOP_NODES`(2)、`LLM_MAX_TOKENS`(8192)。

**验证清单**（接手后先跑这些确认环境 OK）：

```bash
$PY -m pytest tests/ -q            # 期望 116 passed
$PY -m src.cli cluster examples/conversations.json --dry-run   # 看按天归集
```

---

## 7. 已知坑 / 易踩点

- **`pipeline.run()` 必须传 Path，不能传 str**（str 会 AttributeError）。
- **DashScope embedding 单批上限 10 条**，`embed_texts` 的 `batch_size` 不要调大。
- **改 SYSTEM_PROMPT 后必须递增 `clustering.PROMPT_VERSION`**，否则旧缓存命中、改动不生效。
- **`.env` 与 `examples/conversations.json` 都在 .gitignore**（后者是敏感真实数据）。曾发生 `.gitignore` 追加时因缺尾换行把两行粘成 `examples/conversations.json.trae/`、导致两条 ignore 全失效的 bug，已修复——**编辑 .gitignore 务必确认每条规则独占一行**。
- **Git push 用 SSH 可行**：之前"必须用户手动 push"的结论已作废，远端切 SSH 后 sandbox 内 `git push origin main` 直接成功。
- **`parser.py` 是早期遗留独立解析器**，主链路走 `pipeline.py` + adapters，改解析逻辑别改错文件。
- **`MessageRef` / `CandidateTopic.source_refs` 是预留的证据细化结构**，目前 Map 走的是日级粗粒度 `session_ids`，消息级精确归因（填 MessageRef.message_index）尚未接入。

---

## 8. 未来技术路径

README 里有完整的演进路线图（① Map-Reduce / ③ Embedding / ③+RAPTOR / ② Agent 的决策对比表）。当前已落地 ③ + RAPTOR。下一步候选（按性价比排序）：

1. **TopicTree 前端可视化**（HTML 可折叠树）——接现有 `topic_tree.json`，纯前端即可，用户此前表达过兴趣。
2. **worklog 接入树**：让 `generate` 支持从某个 TopicNode 往下取工作项，输出按层级组织的日志。
3. **消息级精确归因**：把 `MessageRef` 真正填起来（Map prompt 让 LLM 返回 message_index），证据从"日级"细化到"句级"。
4. **增量更新**：embedding 方案天然支持新对话 assign 到已有簇，但目前是全量重建；量大后可做局部增量。
5. **更多 adapter**：Claude / Grok / DeepSeek / Qwen / GLM / Kimi / MiniMax 均已在 SKILL.md 预留，接口固化，新增文件注册到 `REGISTRY` 即可。
6. **`query` 命令 + SQLite 落库**（`store.py` 尚未实现，Phase 2）。
7. **② Agent 层**：仅用于处理低置信度疑难归组，非必需不引入（聚类是确定步骤，Agent 性价比低）。

---

## 9. 交接备注

- 项目是宇豪"个人日常管理系统"的一部分，也是他 AI Agent 方向的作品集素材——代码质量、可复现性、确定性这些点对他很重要，改动时尽量保持。
- 最近 git 历史（新→旧）：`e8438f8`(embedding+cache+RAPTOR+证据链) → `9011d51` → `1f0930c`(generator) → `04eed86`(MCP server) → `684d9ff`(cluster+SKILL) …
- 工作日志记录在 `.workbuddy/memory/YYYY-MM-DD.md`（append-only），长期决策在 `.workbuddy/memory/MEMORY.md`。
- 遇到拿不准的架构选择，先问宇豪——他对此项目的方向（确定性、层级结构、证据可追溯）有明确主张，且会直接指出拍脑袋的设计。
