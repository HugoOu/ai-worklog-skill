# AI Worklog Skill

从 AI 对话记录（Gemini 导出 HTML 等）中自动聚类工作主题，生成结构化工作日志。

## 项目结构

```
src/
  parser.py       # 解析 HTML/Markdown 对话记录，按天归集
  models.py       # Pydantic 数据模型
  extractor.py    # LLM 调用：日级候选提取 + 跨天合并（Reduce）
  clustering.py   # 聚类策略抽象 + 具体实现（策略① Map-Reduce）
examples/
  gemini_1000.html    # 参考格式样本
  ai_history.html     # 待处理的完整对话记录
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

#### ① Map-Reduce 流水线（当前实现）

- **Map**：每天独立调用 LLM 提取日级候选（`extract_candidates_from_daily`）
- **Reduce**：汇总所有日级候选的 topic+summary，LLM 判断哪些属于同一跨天项目并合并；
  evidence 在代码中按索引拼接，保证一字不差
- **定位**：初期验证产品逻辑，链路最短、最快跑通
- **局限**：历史量大后 Reduce 输入线性膨胀，终会受 LLM 上下文窗口限制；不支持增量更新

#### ③ Embedding + 聚类算法（未来主干替换）

- 对每个对话块做向量化（可用本地模型如 `bge-small-zh`，零 API 成本）
- 用 HDBSCAN / 层次聚类跨天自动成簇（相似度与日期无关，天然解决跨天归组）
- 每簇内再调 LLM 生成主题名/摘要/证据（簇小，不超窗口，可并行）
- **定位**：解决①的扩展性和增量问题；向量化 O(n)，可扛上万条对话
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

**演进顺序**：先做单层 `EmbeddingClustering`（验证向量化+聚类效果），再在此基础上加递归升级为 `RaptorClustering`，接口不变。

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

```bash
# 安装依赖
pip install openai python-dotenv beautifulsoup4 lxml

# 配置 .env
# OPENAI_API_KEY=...
# OPENAI_BASE_URL=...
# LLM_MODEL=deepseek-chat

# 运行
python test_extractor.py
```
