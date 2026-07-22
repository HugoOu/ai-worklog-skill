"""生成 ChatGPT 导出格式的测试样本 (tests/fixtures/chatgpt_sample.json)。

基于真实 ChatGPT conversations.json 结构：
- 顶层 list，每项含 id / title / create_time / update_time / mapping
- mapping 是 dict，key 为 node_id，value 含 message + parent + children
- message 含 author.role / content.content_type / content.parts / create_time / metadata.model_slug

构造 2 个会话：
1. conv-001: Python 列表去重（user → assistant → user → assistant），2026-05-21
2. conv-002: Git rebase 简介（system → user → assistant），2026-05-22
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

tz_sh = timezone(timedelta(hours=8))

def ts(dt_str: str) -> float:
    """'2026-05-21 10:43:45' (Asia/Shanghai) → Unix timestamp"""
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz_sh)
    return dt.timestamp()

def node(node_id: str, message: dict | None, parent: str | None, children: list[str]) -> dict:
    return {"id": node_id, "message": message, "parent": parent, "children": children}

def msg(msg_id: str, role: str, parts: list, create_time: float, model_slug: str | None = None) -> dict:
    m = {
        "id": msg_id,
        "author": {"role": role},
        "content": {"content_type": "text", "parts": parts},
        "create_time": create_time,
    }
    if model_slug:
        m["metadata"] = {"model_slug": model_slug}
    return m

# ==========================================
# 会话 1: Python 列表去重
# ==========================================
conv1 = {
    "title": "Python 列表去重",
    "create_time": ts("2026-05-21 10:43:45"),
    "update_time": ts("2026-05-21 10:46:00"),
    "mapping": {
        "root1": node("root1", None, None, ["m1u"]),
        "m1u": node("m1u", msg("m1u", "user", ["Python 列表怎么去重？"], ts("2026-05-21 10:43:45")), "root1", ["m1a"]),
        "m1a": node("m1a", msg("m1a", "assistant", ["可以用 set() 或 dict.fromkeys()。"], ts("2026-05-21 10:44:00"), "gpt-4o"), "m1u", ["m2u"]),
        "m2u": node("m2u", msg("m2u", "user", ["保留顺序怎么做？"], ts("2026-05-21 10:45:00")), "m1a", ["m2a"]),
        "m2a": node("m2a", msg("m2a", "assistant", ["用 dict.fromkeys(lst).keys() 或 OrderedDict。"], ts("2026-05-21 10:45:30"), "gpt-4o"), "m2u", []),
    },
    "id": "conv-001",
}

# ==========================================
# 会话 2: Git rebase 简介（含 system 消息 + 缺失 create_time 的边缘情况）
# ==========================================
conv2 = {
    "title": "Git rebase 简介",
    "create_time": ts("2026-05-22 14:00:00"),
    "update_time": ts("2026-05-22 14:05:00"),
    "mapping": {
        "root2": node("root2", None, None, ["sys2"]),
        "sys2": node("sys2", msg("sys2", "system", ["You are a helpful assistant."], ts("2026-05-22 14:00:00")), "root2", ["m3u"]),
        "m3u": node("m3u", msg("m3u", "user", ["git rebase 是什么？"], ts("2026-05-22 14:00:30")), "sys2", ["m3a"]),
        # m3a 故意不设 create_time，测试 adapter 的 fallback 逻辑
        "m3a": node("m3a", {
            "id": "m3a",
            "author": {"role": "assistant"},
            "content": {"content_type": "text", "parts": ["git rebase 是把分支的提交重新应用到另一个基线上的操作。"]},
            "metadata": {"model_slug": "gpt-4o-mini"},
        }, "m3u", []),
    },
    "id": "conv-002",
}

sample = [conv1, conv2]

out = Path(__file__).parent / "chatgpt_sample.json"
out.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✅ 生成 {out}")
print(f"   会话数: {len(sample)}")
for c in sample:
    print(f"   - {c['id']}: {c['title']} ({len(c['mapping'])} nodes)")
