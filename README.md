# AI Worklog Skill

把多平台 AI 对话导出（ChatGPT / Gemini）自动解析为统一格式，聚类成层级主题树，再由用户在树中选取需要的部分，生成符合指定需求或模板格式的 Markdown 工作日志。

- **确定性聚类**：LLM 只做 Map（带磁盘缓存），跨天合并交给 Embedding + 层次聚类，两次运行结果完全一致
- **证据可追溯**：session_id 全程贯通，从原始对话 → 候选 → 主题树叶子
- **以树为纲生成日志**：RAPTOR 层级主题树（`topic_tree.json`）是核心中间产物，工作日志生成服务于它——用户在树中按粒度（任务/主题/项目）选取节点，再渲染成 Markdown

## 项目结构

```
ai-worklog-skill/
├── README.md               # 本文件（架构演进 + 使用说明）
├── SKILL.md                # WorkBuddy Skill 定义（CLI 命令参考 + 平台支持表）
├── handoff.md              # 交接文档（现状快照 + 已知坑 + 设计决策）
├── pyproject.toml          # 依赖 + entry point: aiworklog = "src.cli:app"
├── .env                    # 【gitignore】OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL
├── src/
│   ├── cli.py              # typer 入口：parse / parse-batch / cluster / generate / tree / adapters / query
│   ├── pipeline.py         # run(): detect → parse → normalize(tz) → export
│   ├── unified_schema.py   # UnifiedSession / UnifiedMessage（Pydantic v2）
│   ├── bridge.py           # unified_to_daily(): UnifiedSession[] → DailyConversation[]
│   ├── models.py           # 数据模型全家桶
│   ├── extractor.py        # LLM Map + Reduce 逻辑、JSON 截断修复
│   ├── cache.py            # MapCacheStore：按 content_hash 的磁盘缓存
│   ├── embedding.py        # embed_texts() + cluster_candidates()（DashScope embedding）
│   ├── raptor.py           # build_topic_tree()：递归聚类建树
│   ├── clustering.py       # ClusteringStrategy 抽象 + MapReduce / Embedding 两种实现
│   ├── generator.py        # 候选筛选 + Markdown 工作日志生成
│   ├── mcp_server.py       # MCP server 包装（parse / cluster / list_adapters / generate）
│   ├── parser.py           # 早期遗留独立解析器（主链路不走这里）
│   └── adapters/
│       ├── __init__.py     # REGISTRY（已注册 ChatGPT + Gemini）
│       ├── base.py         # BaseAdapter 抽象（provider / detect() / parse()）
│       ├── chatgpt.py      # ✅ ChatGPT 导出解析
│       └── gemini.py       # ✅ Gemini My Activity HTML 解析
├── examples/               # 样本数据（conversations.json 为敏感真实数据，gitignore）
├── tests/                  # 116 个单元测试（pytest）
└── output/                 # 运行产物（unified_sessions / daily_conversations / candidates / topic_tree / worklog）
```

## 聚类架构

聚类核心被抽象为 `ClusteringStrategy` 接口，输入跨天的全部对话，输出聚类后的候选主题。
不同实现可无缝替换，下游（用户筛选、日志渲染）无需改动。

```python
class ClusteringStrategy(ABC):
    def cluster(self, daily_conversations: List[DailyConversation]) -> List[CandidateItem]: ...
```

### 演进路线图

按"先跑通、再优化、最后补边界"的顺序演进，每一步接口不变、可回退：

#### ① Map-Reduce 流水线（历史实现，保留兼容，用 `--legacy-reduce` 启用）

- **Map**：每天独立调用 LLM 提取日级候选（`extract_candidates_from_daily`）
- **Reduce**：汇总所有日级候选的 topic+summary，LLM 判断哪些属于同一跨天项目并合并；
  evidence 在代码中按索引拼接，保证一字不差
- **定位**：初期验证产品逻辑，链路最短、最快跑通；因结果不确定性已被 ③ 取代为默认
- **局限**：历史量大后 Reduce 输入线性膨胀，终会受 LLM 上下文窗口限制；不支持增量更新

#### ③ Embedding + 聚类算法（✅ 当前默认实现）

- 对每个对话块做向量化（当前用 DashScope `text-embedding-v3`，OpenAI 兼容端点）
- 用层次聚类（`AgglomerativeClustering` + 余弦距离）跨天自动成簇（相似度与日期无关，天然解决跨天归组）
- Map 阶段（日级候选提取）带磁盘缓存，相同输入不重复调 LLM；聚类为确定性操作，两次运行结果完全一致
- **定位**：解决①的扩展性和不确定性问题；向量化 O(n)，可扛上万条对话
- **迁移方式**：新增 `EmbeddingClustering(ClusteringStrategy)`，替换策略实例即可，接口与下游不变

##### 借鉴 RAPTOR 的多层递归增强（策略③的进阶形态）

单层 embedding 聚类只能产出单一粒度的主题（"配置 FDM 嗅探"），无法表达"任务 → 主题 → 项目"的层级关系。借鉴 [RAPTOR（Sarthi et al., ICLR 2024）](https://arxiv.org/abs/2401.18059) 的递归思想，将单层聚类升级为多层树结构：

```
对话块 → embedding → 聚类 → LLM 摘要 → 候选（叶节点，具体任务）
候选 → embedding → 聚类 → LLM 摘要 → 主题（中间层，主题汇总）
主题 → embedding → 聚类 → LLM 摘要 → 项目（根节点，大项目）
```

**借鉴点**：
1. **递归聚类+摘要**：每一层对上一层的摘要节点重新 embedding + 聚类 + LLM 摘要，形成从细到粗的多层级结构
2. **GMM + UMAP 降维 + BIC 选簇数**（RAPTOR 的具体聚类方法，可替换为 HDBSCAN，但 GMM 能给出簇数最优解，HDBSCAN 需调参）
3. **collapsed tree 检索**：扁平化所有层级节点统一检索，不限定从哪一层取结果

**工作日志场景的适配**：
- 叶节点 = 具体任务（如"配置 FDM 嗅探视频下载"）
- 中间层 = 主题（如"视频下载工具系列"）
- 根节点 = 大项目（如"多媒体工具链建设"）
- 用户可选择查看哪个粒度的日志

**关键区别**：RAPTOR 原场景是文档检索（一篇长文档内部的多层摘要），本项目是跨对话的主题归集（多个独立对话的层级聚类）。借用的是"递归聚类+摘要"的树构建思想，不是检索时的树遍历。

**当前落地状态**：单层 `EmbeddingClustering` 与递归 `build_topic_tree`（RAPTOR 风格，`src/raptor.py`）均已实现，`tree` 命令可输出多层级 `topic_tree.json`。

#### ② Agent 层（未来边界增强）

- 不做聚类主干（聚类是步骤确定的任务，Agent 在此性价比低）
- 用于处理 ③ 的边界 case：低置信度簇 → Agent 自主检索相邻上下文判断归属
- **定位**：量大后出现疑难归组时叠加，非必需不引入

### 决策依据

| 维度 | ① Map-Reduce | ③ Embedding | ③+RAPTOR 递归 | ② Agent |
|------|------|------|------|------|
| 跨天聚类 | Reduce 强行合并 | 天然支持 | 天然支持 | 逐对判断 |
| 可扩展性 | ❌ 线性膨胀 | ✅ O(n) | ✅ O(n)，多层递归每层 O(n) | ❌ 更差 |
| 增量更新 | ❌ 全量重跑 | ✅ 新向量 assign | ⚠️ 需局部重建树 | ⚠️ 复杂 |
| API 成本 | 每天+合并 | 仅簇内摘要 | 每层簇内摘要（更多次） | 多轮最贵 |
| 语义深度 | ⚠️ 只看 summary | ⚠️ 词汇相关 | ✅ 多层级语义聚合 | ✅ 最强 |
| 输出粒度 | 单一 | 单一 | ✅ 多层级（任务/主题/项目） | 单一 |

每阶段用最合适的组件：embedding 做"大规模相似度判断"，LLM 做"理解与生成"，RAPTOR 递归做"多层级语义聚合"，Agent 做"疑难决策"。

## 使用

### 0. 环境准备

项目依赖一个本地 venv（Windows 下为 `.venv/Scripts/python.exe`）。下文所有命令均在**项目根目录**执行。

```bash
cd C:\Users\Exception2Rule\ai-worklog-skill

# 安装依赖（首次或依赖变更后执行；-e 为可编辑安装，注册 aiworklog 命令）
.venv/Scripts/python.exe -m pip install -e .
```

配置 `.env`（项目根目录，已在 .gitignore，**勿提交**）。LLM 与 embedding 复用同一端点：

```bash
OPENAI_API_KEY=<你的 key>
OPENAI_BASE_URL=<DashScope OpenAI 兼容端点>
LLM_MODEL=<如 qwen3.7-flash>
# 可选：EMBEDDING_MODEL=text-embedding-v3（默认即是）
```

> 提示：`parse` / `parse-batch` / `adapters` **不需要** LLM 配置；`cluster` / `generate` / `tree` 需要。

为方便，下文用环境变量 `PY` 代指解释器（Git Bash）：

```bash
PY=.venv/Scripts/python.exe
```

### 1. 健康检查（接手后先跑这些，确认环境 OK）

```bash
# 1.1 全量单元测试（不联网、不花钱，期望 116 passed）
$PY -m pytest tests/ -q

# 1.2 列出已注册的平台 adapter（应看到 openai + google）
$PY -m src.cli adapters

# 1.3 干跑预览数据分布（只 parse + 按天归集，不调 LLM，秒出）
$PY -m src.cli cluster examples/conversations.json --dry-run
```

三步全绿即说明解析链路、依赖、样本数据均正常。

### 2. CLI 命令详解

所有命令等价于 `aiworklog <cmd>`（`pip install -e .` 后）或 `$PY -m src.cli <cmd>`。

#### `parse` — 解析单个导出文件为统一格式

```bash
$PY -m src.cli parse <input_path> [-p auto|openai|google] [-f json|jsonl] [-o ./output] [--tz Asia/Shanghai] [--group-by-date]
```

```bash
# 自动探测格式
$PY -m src.cli parse examples/conversations.json -o ./output

# 显式指定 Gemini，并额外输出按天归集
$PY -m src.cli parse examples/gemini_1000.html -p google --group-by-date -o ./output
```

输出：`<outdir>/unified_sessions.json`（UnifiedSession 数组）。

#### `parse-batch` — 批量扫描目录

```bash
$PY -m src.cli parse-batch <input_dir> [-o ./output] [--tz Asia/Shanghai]
```

递归扫描目录下所有 `.json/.jsonl/.html/.htm/.zip`，逐个解析并合并统计。

#### `cluster` — 端到端聚类（核心命令）

```bash
$PY -m src.cli cluster <input1> <input2> ... [-o ./output] [--tz Asia/Shanghai] [--dry-run] [--legacy-reduce]
```

流程：parse → bridge 按天归集 → Map（带缓存）→ Embedding 聚类 → candidates.json。

```bash
# 先干跑预览（不调 LLM，免费，秒出）
$PY -m src.cli cluster examples/conversations.json --dry-run

# 确认无误后正式聚类（默认 Embedding 模式，带 Map 缓存）
$PY -m src.cli cluster examples/conversations.json -o ./output

# 混合多平台输入
$PY -m src.cli cluster examples/conversations.json examples/gemini_1000.html -o ./output

# 用旧版 LLM Map-Reduce（不确定，仅兼容）
$PY -m src.cli cluster examples/conversations.json --legacy-reduce
```

输出 3 个文件：
- `unified_sessions.json` — 统一格式解析结果
- `daily_conversations.json` — 按天归集
- `candidates.json` — 聚类候选工作项（每个含 topic / summary / evidence / dates / session_ids）

> 缓存：Map 结果按天缓存到 `<outdir>/.map_cache/`。**第二次跑同样输入会命中缓存，0 次 LLM 调用、亚秒级完成**。改了 SYSTEM_PROMPT 或缓存数据结构需递增 `clustering.PROMPT_VERSION` 触发失效。

#### `generate` — 从候选生成 Markdown 工作日志

```bash
$PY -m src.cli generate <candidates.json> [--select 2,3,9-11] [--date-range A:B] [--interactive] [--all] [--polish/--no-polish] [-o ./output]
```

筛选方式互斥（优先级 select > date-range > interactive > all）：

```bash
# 全选并润色为第一人称工作日志（默认 polish 开启）
$PY -m src.cli generate output/candidates.json --all -o ./output

# 只选第 2、3、9-11 个候选
$PY -m src.cli generate output/candidates.json --select 2,3,9-11

# 按日期范围筛选
$PY -m src.cli generate output/candidates.json --date-range 2026-03-26:2026-06-09

# 交互式选择（终端列出候选，输入编号）
$PY -m src.cli generate output/candidates.json --interactive

# 不润色（直接用候选原文，省一次 LLM 调用）
$PY -m src.cli generate output/candidates.json --all --no-polish
```

输出：`<outdir>/worklog.md`（YAML frontmatter + 按日期组织的工作项）。

#### `tree` — 构建 RAPTOR 层级主题树

```bash
$PY -m src.cli tree <input1> <input2> ... [-o ./output] [--tz Asia/Shanghai] [-t/--threshold 0.45]
```

流程：parse → bridge → Map（带缓存）→ 递归 Embedding 聚类 → TopicTree。

```bash
# 默认阈值
$PY -m src.cli tree examples/conversations.json -o ./output

# 更严格的聚类（阈值越小，簇越少、聚合越狠）
$PY -m src.cli tree examples/conversations.json -t 0.3 -o ./output
```

输出：`<outdir>/topic_tree.json` + 终端 rich 树状图打印。叶子节点 `session_ids` 可回链到原始对话。

> **定位**：主题树是生成工作日志的**核心中间产物**，不是独立产出线。目标工作流是：先建树 → 用户在树中按粒度（任务/主题/项目）选取需要的节点 → 按指定需求或模板渲染 Markdown 日志。
> **当前状态**：`generate` 命令暂直接消费 `candidates.json`（扁平候选）；"从树节点选取 → 生成日志"的衔接是下一步方向（见 handoff.md §8），尚未接入。

#### `query` — 查询落库对话（占位，Phase 2 未实现）

```bash
$PY -m src.cli query [--db worklog.db] [--date] [--provider] [--keyword]
```

### 3. 检查运行产物

跑完 `cluster` / `tree` 后，可直接检查 `output/` 下的 JSON 验证正确性：

```bash
# 看候选数量与字段（evidence / session_ids 应非空）
$PY -c "import json; d=json.load(open('output/candidates.json',encoding='utf-8')); print(len(d),'candidates'); print(json.dumps(d[0],ensure_ascii=False,indent=2))"

# 看主题树结构与叶子证据链（session_ids 应贯通）
$PY -c "import json; t=json.load(open('output/topic_tree.json',encoding='utf-8')); print('nodes',t['meta']['total_nodes'],'depth',t['meta']['depth'],'roots',len(t['root_ids']))"
```

预期（以 examples/conversations.json 为例）：
- `candidates.json`：4 个候选，每个 `evidence` 非空（约 100–160 字符）、`session_ids` 含 1 个 UUID
- `topic_tree.json`：4 节点 / depth=1，每个叶子 `session_ids` 非空

### 4. 可调环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `MAP_WORKERS` | 5 | Map 阶段并发线程数 |
| `CLUSTER_DISTANCE_THRESHOLD` | 0.45 | 聚类距离阈值（越小越严格） |
| `EMBEDDING_MODEL` | text-embedding-v3 | DashScope embedding 模型 |
| `RAPTOR_MAX_DEPTH` | 5 | 主题树最大递归深度 |
| `RAPTOR_MIN_TOP_NODES` | 2 | 顶层节点数 ≤ 此值停止聚合 |
| `LLM_MAX_TOKENS` | 8192 | Map 阶段单次输出上限 |

### 5. MCP server（可选）

将能力暴露给 Claude Desktop / Cursor / WorkBuddy：

```bash
$PY -m pip install -e .[mcp]
$PY -m src.mcp_server
```

注册 4 个工具：`parse_conversations` / `cluster_conversations` / `list_adapters` / `generate_worklog`。`cluster_conversations` 已使用与 CLI 一致的 EmbeddingClustering（确定性，带缓存）。

### 6. 测试

```bash
$PY -m pytest tests/ -q          # 116 passed，全 mock 不打 API
$PY -m pytest tests/test_raptor.py -v   # 单看 RAPTOR 树测试
```

`tests/legacy/` 下是早期脚本式示例，pytest 不收集（见 pyproject.toml `norecursedirs`）。
