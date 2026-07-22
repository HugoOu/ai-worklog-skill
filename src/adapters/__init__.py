"""
Adapter 注册表 — 所有已实现 adapter 在此注册，pipeline 通过 REGISTRY 自动探测。

预留接口（未实现，后续按需补）：
- ChatGPTAdapter / GeminiAdapter（Phase 1 实现）
- ClaudeAdapter / GrokAdapter / MistralAdapter
- DeepSeekAdapter / KimiAdapter / QwenAdapter / GLMAdapter / MiniMaxAdapter

接入新平台步骤：
1. 创建 src/adapters/xxx.py，实现 BaseAdapter
2. 取消下方对应行的注释并 import
3. 在 REGISTRY 中取消注释注册
"""
from src.adapters.base import BaseAdapter

# ==========================================
# 预留 adapter（未实现，后续按需补）
# ==========================================
# from src.adapters.chatgpt import ChatGPTAdapter
# from src.adapters.gemini import GeminiAdapter
# from src.adapters.claude import ClaudeAdapter
# from src.adapters.grok import GrokAdapter
# from src.adapters.mistral import MistralAdapter
# from src.adapters.deepseek import DeepSeekAdapter
# from src.adapters.kimi import KimiAdapter
# from src.adapters.qwen import QwenAdapter
# from src.adapters.glm import GLMAdapter
# from src.adapters.minimax import MiniMaxAdapter


# ==========================================
# REGISTRY — pipeline 通过此列表自动探测格式
# ==========================================
REGISTRY: list[type[BaseAdapter]] = [
    # ChatGPTAdapter,        # 待 Phase 1 实现
    # GeminiAdapter,         # 待 Phase 1 实现
    # ClaudeAdapter,         # 预留
    # GrokAdapter,           # 预留
    # MistralAdapter,        # 预留
    # DeepSeekAdapter,       # 预留
    # KimiAdapter,           # 预留
    # QwenAdapter,           # 预留
    # GLMAdapter,            # 预留
    # MiniMaxAdapter,        # 预留
]

__all__ = ["BaseAdapter", "REGISTRY"]
