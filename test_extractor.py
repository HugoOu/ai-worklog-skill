from src.parser import parse_conversation
from src.extractor import extract_worklogs

# 1. 解析 HTML 获取按天分组的对话
daily_conversations = parse_conversation("examples/gemini_1000.html")
print(f"解析出 {len(daily_conversations)} 天的对话记录，开始调用 LLM 提取...\n")

# 2. 调用 LLM 提取工作日志
worklogs = extract_worklogs(daily_conversations)

# 3. 打印结果
for log in worklogs:
    print(f"\n=== 工作日报: {log.date} ===")
    if not log.work_items:
        print("  (当日无实质性工作记录)")
    for item in log.work_items:
        print(f"  [任务] {item.task}")
        print(f"  [详情] {item.detail}")
        print(f"  [证据] {item.evidence[:50]}...") # 只打印前50字
        print("-" * 30)