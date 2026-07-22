from src.parser import parse_conversation
from src.clustering import MapReduceClustering

# 1. 解析 HTML 获取按天分组的对话
daily_conversations = parse_conversation("examples/ai_history.html")
print(f"解析出 {len(daily_conversations)} 天的对话记录，开始聚类...\n")

# 2. 使用聚类策略提取跨天候选主题
#    未来替换为 EmbeddingClustering() 只需改这一行
strategy = MapReduceClustering()
candidates = strategy.cluster(daily_conversations)

if not candidates:
    print("未提取到有效候选主题")
else:
    print(f"共聚类出 {len(candidates)} 个跨天候选主题：\n")
    for i, cand in enumerate(candidates):
        dates = ", ".join(cand.dates) if cand.dates else "未知日期"
        print(f"[{i+1}] 主题: {cand.topic}  (日期: {dates})")
        print(f"    概要: {cand.summary}")
        print(f"    证据: {cand.evidence[:60]}...")
        print()

    # 在真实的 CLI 工具中，这里会提示用户输入要保留的序号
    # selected_indices = input("请输入要保留的序号(逗号分隔), 回车全选: ")
    selected_items = candidates

    print(f"✅ 已选中 {len(selected_items)} 个主题，将渲染为工作日志...")
