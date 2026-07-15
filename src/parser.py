from bs4 import BeautifulSoup, NavigableString
from typing import List
from models import ConversationMessage

# ==========================================
# 策略 1: Gemini HTML 解析器
# ==========================================
def parse_gemini_html(file_path: str) -> List[ConversationMessage]:
    """
    专门解析 Gemini 导出的 HTML 格式对话记录。
    基于 <br> 标签的层级切分用户输入与模型输出。
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'lxml')
    messages = []
    
    # 每个外层 cell 对应一次完整的问答交互
    chat_blocks = soup.find_all('div', class_='outer-cell')
    
    for block in chat_blocks:
        # 找到包含内容的 cell
        content_cell = block.find('div', class_='content-cell')
        if not content_cell:
            continue
            
        user_text = ""
        assistant_text = ""
        br_count = 0
        
        # 遍历该 cell 下的所有子节点（包括文本和标签）
        for content in content_cell.contents:
            # 遇到 <br> 标签，计数器加1
            if content.name == 'br':
                br_count += 1
                continue
                
            # 提取节点的纯文本内容
            if content.name:
                # 如果是 HTML 标签（如 <p>, <a>, <pre>），获取其内部所有文本，用换行符分隔
                text = content.get_text(separator='\n', strip=True)
            else:
                # 如果是纯文本节点
                text = str(content).strip()
                
            if not text:
                continue
                
            # 根据观察的结构：
            # 第1个 <br> 之前的内容是 User 的提问
            # 第1~2个 <br> 之间是时间戳（忽略）
            # 第2个 <br> 之后是 Assistant 的回答
            if br_count == 0:
                user_text += text + "\n"
            elif br_count >= 2:
                assistant_text += text + "\n"
                
        # 清理提取到的文本
        user_text = user_text.strip()
        assistant_text = assistant_text.strip()
        
        # 去除提问开头的 "Prompted " 前缀
        if user_text.startswith("Prompted"):
            user_text = user_text[len("Prompted"):].strip()
            
        # 如果有有效内容，则添加到消息列表中
        if user_text:
            messages.append(ConversationMessage(role="user", content=user_text))
        if assistant_text:
            messages.append(ConversationMessage(role="assistant", content=assistant_text))
        
    return messages

# ==========================================
# 策略 2: Markdown 解析器 (保留以备不时之需)
# ==========================================
def parse_markdown(file_path: str) -> List[ConversationMessage]:
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
            messages.append(ConversationMessage(role=role, content=clean_text))
            
    return messages

# ==========================================
# 统一解析路由入口
# ==========================================
def parse_conversation(file_path: str) -> List[ConversationMessage]:
    """
    根据文件后缀自动路由到对应的解析器。
    """
    if file_path.endswith('.html'):
        return parse_gemini_html(file_path)
    elif file_path.endswith('.md'):
        return parse_markdown(file_path)
    else:
        raise ValueError(f"暂不支持的文件格式: {file_path}")


if __name__ == "__main__":
    # 测试用例
    test_file = "tests\gemini_1000.html"
    messages = parse_conversation(test_file)
    print(messages)
    print(len(messages))