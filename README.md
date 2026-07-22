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

#### ② Agent 层（未来边界增强）

- 不做聚类主干（聚类是步骤确定的任务，Agent 在此性价比低）
- 用于处理 ③ 的边界 case：低置信度簇 → Agent 自主检索相邻上下文判断归属
- **定位**：量大后出现疑难归组时叠加，非必需不引入

### 决策依据

| 维度 | ① Map-Reduce | ③ Embedding | ② Agent |
|------|------|------|------|
| 跨天聚类 | Reduce 强行合并 | 天然支持 | 逐对判断 |
| 可扩展性 | ❌ 线性膨胀 | ✅ O(n log n) | ❌ 更差 |
| 增量更新 | ❌ 全量重跑 | ✅ 新向量 assign | ⚠️ 复杂 |
| API 成本 | 每天+合并 | 仅簇内摘要 | 多轮最贵 |
| 语义深度 | ⚠️ 只看 summary | ⚠️ 词汇相关 | ✅ 最强 |

每阶段用最合适的组件：embedding 做"大规模相似度判断"，LLM 做"理解与生成"，Agent 做"疑难决策"。

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
