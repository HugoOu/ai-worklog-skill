from src.parser import parse_conversation

daily_conversations = parse_conversation("examples/gemini_1000.html")
print(f"✅ 成功解析出 {len(daily_conversations)} 天的对话记录！\n")

for daily_conv in daily_conversations:
    print(f"=== 日期: {daily_conv.date} | 消息数: {len(daily_conv.messages)} ===")
    for msg in daily_conv.messages:
        print(f"  [{msg.role}]: {msg.content[:30]}...")
    print()