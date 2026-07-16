from bs4 import BeautifulSoup
from typing import List
from src.models import ConversationMessage, DailyConversation
from collections import OrderedDict
import re

# ==========================================
# 策略 1: Gemini HTML 解析器
# ==========================================
def parse_gemini_html(file_path: str) -> List[DailyConversation]:
    """
    专门解析 Gemini 导出的 HTML 格式对话记录。
    提取时间戳并按天归集对话。
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'lxml')
    chat_blocks = soup.find_all('div', class_='outer-cell')
    
    all_messages = []
    
    # 正则匹配 "2026年5月21日" 这样的日期
    date_pattern = re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日')
    
    for block in chat_blocks:
        # 精准定位包含对话主体和时间的 cell (具有 mdl-typography--body-1 类)
        content_cell = block.find('div', class_='mdl-typography--body-1')
        if not content_cell:
            continue
            
        user_text = ""
        assistant_text = ""
        date_str = "Unknown Date"
        timestamp_found = False
        
        # 遍历该 cell 下的所有子节点
        for content in content_cell.contents:
            if content.name == 'br':
                continue
                
            # 提取纯文本
            if content.name:
                text = content.get_text(separator='\n', strip=True)
            else:
                text = str(content).strip()
                
            if not text:
                continue
            
            # 1. 检查并提取时间戳
            match = date_pattern.search(text)
            if match:
                year, month, day = match.groups()
                date_str = f"{year}-{int(month):02d}-{int(day):02d}"
                timestamp_found = True
                continue # 时间戳节点本身不作为对话内容
                
            # 2. 根据是否找到时间戳，划分 User 和 Assistant 区域
            if not timestamp_found:
                # 过滤掉附件等无用提示行
                if "Attached" not in text and not text.startswith("-"):
                    user_text += text + "\n"
            else:
                assistant_text += text + "\n"
                
        # 清理提取到的文本
        user_text = user_text.strip()
        assistant_text = assistant_text.strip()
        
        # 去除提问开头的 "Prompted " 前缀
        if user_text.startswith("Prompted"):
            user_text = user_text[len("Prompted"):].strip()
            
        # 添加到消息列表
        if user_text:
            all_messages.append(ConversationMessage(role="user", content=user_text, date=date_str))
        if assistant_text:
            all_messages.append(ConversationMessage(role="assistant", content=assistant_text, date=date_str))
            
    # 按天归集对话
    grouped_by_date = OrderedDict()
    for msg in all_messages:
        if msg.date not in grouped_by_date:
            grouped_by_date[msg.date] = []
        grouped_by_date[msg.date].append(msg)
        
    # 转换为 DailyConversation 对象列表
    return [DailyConversation(date=d, messages=m) for d, m in grouped_by_date.items()]

# ==========================================
# 策略 2: Markdown 解析器 (保留备用)
# ==========================================
def parse_markdown(file_path: str) -> List[DailyConversation]:
    # 此处简化处理，Markdown 暂不拆分日期，统一归为 Unknown Date
    import re
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    pattern = r'\*\*(User|Assistant|You|ChatGPT|Claude)\*\*:\s*(.*?)(?=\n\*\*(?:User|Assistant|You|ChatGPT|Claude)\*\*:|\Z)'
    matches = re.findall(pattern, content, re.DOTALL)
    
    messages = []
    for role_str, text in matches:
        role = "user" if role_str.lower() in ["user", "you"] else "assistant"
        clean_text = text.strip()
        if clean_text:
            messages.append(ConversationMessage(role=role, content=clean_text, date="Unknown Date"))
            
    return [DailyConversation(date="Unknown Date", messages=messages)]

# ==========================================
# 统一解析路由入口
# ==========================================
def parse_conversation(file_path: str) -> List[DailyConversation]:
    """
    根据文件后缀自动路由到对应的解析器，返回按天归集的对话列表。
    """
    if file_path.endswith('.html'):
        return parse_gemini_html(file_path)
    elif file_path.endswith('.md'):
        return parse_markdown(file_path)
    else:
        raise ValueError(f"暂不支持的文件格式: {file_path}")