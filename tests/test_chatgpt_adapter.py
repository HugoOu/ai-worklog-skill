"""ChatGPTAdapter 单元测试 — 基于 examples/conversations.json 真实导出数据。"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.adapters.chatgpt import ChatGPTAdapter
from src.unified_schema import UnifiedSession

tz_utc = timezone.utc
tz_sh = timezone(timedelta(hours=8))


# ==========================================
# detect() 测试
# ==========================================
class TestDetect:
    def test_detect_real_json(self, chatgpt_sample_path: Path):
        """真实 ChatGPT 导出 JSON 应被高置信度识别。"""
        adapter = ChatGPTAdapter()
        score = adapter.detect(chatgpt_sample_path)
        assert score == 0.95, f"ChatGPT JSON 探测置信度应为 0.95，实际 {score}"

    def test_detect_zip_with_conversations(self, tmp_path: Path, chatgpt_sample_path: Path):
        """含 conversations.json 的 ZIP 应被识别。"""
        zip_path = tmp_path / "chatgpt_export.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(chatgpt_sample_path, "conversations.json")

        adapter = ChatGPTAdapter()
        score = adapter.detect(zip_path)
        assert score == 0.95

    def test_detect_bad_zip(self, tmp_path: Path):
        """损坏的 ZIP 应返回 0.0。"""
        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_bytes(b"not a zip file")
        adapter = ChatGPTAdapter()
        assert adapter.detect(bad_zip) == 0.0

    def test_detect_non_chatgpt_json(self, tmp_path: Path):
        """非 ChatGPT 结构的 JSON 应返回 0.0。"""
        other_json = tmp_path / "other.json"
        other_json.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        adapter = ChatGPTAdapter()
        assert adapter.detect(other_json) == 0.0

    def test_detect_unsupported_extension(self, tmp_path: Path):
        """不支持的扩展名应返回 0.0。"""
        f = tmp_path / "file.txt"
        f.write_text("hello", encoding="utf-8")
        adapter = ChatGPTAdapter()
        assert adapter.detect(f) == 0.0


# ==========================================
# parse() 测试 — 基于真实数据
# ==========================================
class TestParse:
    def test_parse_returns_sessions(self, chatgpt_sample_path: Path):
        """应返回 4 个 UnifiedSession（真实数据含 4 个会话）。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)
        assert len(sessions) == 4
        assert all(isinstance(s, UnifiedSession) for s in sessions)

    def test_parse_titles(self, chatgpt_sample_path: Path):
        """会话标题应正确提取（验证 3 个非敏感标题）。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)
        titles = {s.title for s in sessions}
        assert "研究生生活费预算" in titles
        assert "国内研究情况撰写" in titles
        assert "AI Harness Engineer招聘情况" in titles

    def test_parse_provider(self, chatgpt_sample_path: Path):
        """所有会话和消息的 provider 应为 openai。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)
        for s in sessions:
            assert s.provider == "openai"
            for m in s.messages:
                assert m.provider == "openai"
                assert m.source == "chatgpt_export"

    def test_parse_roles(self, chatgpt_sample_path: Path):
        """会话应含 user + assistant 角色。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        # 会话"研究生生活费预算"应有 1 轮 user-assistant
        budget_conv = next(s for s in sessions if s.title == "研究生生活费预算")
        roles = [m.role for m in budget_conv.messages]
        assert roles == ["user", "assistant"]

        # 会话"国内研究情况撰写"应有 10 轮（20 条消息）
        thesis_conv = next(s for s in sessions if s.title == "国内研究情况撰写")
        assert len(thesis_conv.messages) == 20
        # 奇数位 user，偶数位 assistant
        for i, m in enumerate(thesis_conv.messages):
            if i % 2 == 0:
                assert m.role == "user"
            else:
                assert m.role == "assistant"

    def test_parse_model_slug(self, chatgpt_sample_path: Path):
        """assistant 消息应含 model_slug。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        for s in sessions:
            assistant_msgs = [m for m in s.messages if m.role == "assistant"]
            for m in assistant_msgs:
                assert m.model is not None, f"会话 {s.title} 的 assistant 消息缺少 model_slug"
                assert m.model.startswith("gpt-"), f"model_slug 应以 gpt- 开头，实际 {m.model}"

    def test_parse_session_model(self, chatgpt_sample_path: Path):
        """会话级 model 应取最后一条 assistant 消息的 model。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        budget_conv = next(s for s in sessions if s.title == "研究生生活费预算")
        assert budget_conv.model == "gpt-5-2"

        thesis_conv = next(s for s in sessions if s.title == "国内研究情况撰写")
        assert thesis_conv.model == "gpt-5-3"

    def test_parse_timestamps_with_timezone(self, chatgpt_sample_path: Path):
        """时间戳应有时区信息（UTC，pipeline 后续归一化到本地时区）。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        for s in sessions:
            assert s.created_at is not None
            assert s.created_at.tzinfo is not None, f"会话 {s.title} 的 created_at 缺少时区"
            for m in s.messages:
                assert m.created_at.tzinfo is not None, f"消息 {m.id} 的 created_at 缺少时区"

    def test_parse_budget_conv_timestamp(self, chatgpt_sample_path: Path):
        """验证"研究生生活费预算"会话的时间戳（2026-02-24 00:07:56 +08:00）。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        budget_conv = next(s for s in sessions if s.title == "研究生生活费预算")
        # create_time=1771862876.508145 → 2026-02-23 16:07:56 UTC = 2026-02-24 00:07:56 +08:00
        assert budget_conv.created_at == datetime(2026, 2, 23, 16, 7, 56, 508145, tzinfo=tz_utc)

    def test_parse_messages_sorted_by_time(self, chatgpt_sample_path: Path):
        """消息应按 created_at 升序排列。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        for s in sessions:
            timestamps = [m.created_at for m in s.messages if m.created_at]
            assert timestamps == sorted(timestamps), f"会话 '{s.title}' 消息未按时间排序"

    def test_parse_content_no_private_chars(self, chatgpt_sample_path: Path):
        """所有消息内容应不含 Unicode 私有区字符（entity 标记已清理）。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        for s in sessions:
            for m in s.messages:
                for c in m.content:
                    assert not ("\ue000" <= c <= "\uf8ff"), \
                        f"消息 {m.id}（会话 {s.title}）含私有区字符 U+{ord(c):04X}"

    def test_parse_entity_marker_replaced(self, chatgpt_sample_path: Path):
        """entity 标记应被替换为实体名（如"上海财经大学"）。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        budget_conv = next(s for s in sessions if s.title == "研究生生活费预算")
        assistant_msg = next(m for m in budget_conv.messages if m.role == "assistant")
        # 原始标记 \ue200entity\ue202["organization","上海财经大学",...]\ue201 应被替换为"上海财经大学"
        assert "上海财经大学" in assistant_msg.content
        assert "\ue200" not in assistant_msg.content

    def test_parse_content_nonempty(self, chatgpt_sample_path: Path):
        """所有消息内容应非空。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        for s in sessions:
            for m in s.messages:
                assert m.content.strip(), f"会话 {s.title} 消息 {m.id} 内容为空"

    def test_parse_session_ids_unique(self, chatgpt_sample_path: Path):
        """会话 ID 应唯一。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)
        ids = [s.id for s in sessions]
        assert len(ids) == len(set(ids)), "会话 ID 有重复"

    def test_parse_file_not_found(self, tmp_path: Path):
        """文件不存在应抛 FileNotFoundError。"""
        adapter = ChatGPTAdapter()
        with pytest.raises(FileNotFoundError):
            adapter.parse(tmp_path / "nonexistent.json")

    def test_parse_zip_input_matches_json(self, tmp_path: Path, chatgpt_sample_path: Path):
        """ZIP 输入应与裸 JSON 解析结果一致。"""
        zip_path = tmp_path / "chatgpt.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(chatgpt_sample_path, "conversations.json")

        adapter = ChatGPTAdapter()
        zip_sessions = adapter.parse(zip_path)
        json_sessions = adapter.parse(chatgpt_sample_path)

        assert len(zip_sessions) == len(json_sessions)
        for zs, js in zip(zip_sessions, json_sessions):
            assert zs.id == js.id
            assert zs.title == js.title
            assert len(zs.messages) == len(js.messages)


# ==========================================
# _clean_inline_markers() 单元测试
# ==========================================
class TestCleanInlineMarkers:
    def test_clean_entity_marker(self):
        """应将 entity 标记替换为实体名。"""
        text = '你现在是在 **\ue200entity\ue202["organization","上海财经大学","university in shanghai china"]\ue201** 读研'
        cleaned = ChatGPTAdapter._clean_inline_markers(text)
        assert cleaned == '你现在是在 **上海财经大学** 读研'
        assert "\ue200" not in cleaned

    def test_clean_multiple_markers(self):
        """应清理多个 entity 标记。"""
        text = (
            '\ue200entity\ue202["organization","上海财经大学","university"]\ue201'
            ' 和 '
            '\ue200entity\ue202["location","五角场","district"]\ue201'
        )
        cleaned = ChatGPTAdapter._clean_inline_markers(text)
        assert cleaned == '上海财经大学 和 五角场'

    def test_clean_stray_private_chars(self):
        """残留的孤立私有区字符应被清除。"""
        text = "正常文本\ue200残留\ue201字符"
        cleaned = ChatGPTAdapter._clean_inline_markers(text)
        assert cleaned == "正常文本残留字符"

    def test_clean_no_markers(self):
        """无标记的文本应保持不变。"""
        text = "这是一段正常文本，不含任何标记。"
        cleaned = ChatGPTAdapter._clean_inline_markers(text)
        assert cleaned == text

    def test_clean_malformed_marker(self):
        """格式错误的标记应被删除（提取失败 fallback 为空）。"""
        text = '前缀\ue200entity\ue202[invalid json\ue201后缀'
        cleaned = ChatGPTAdapter._clean_inline_markers(text)
        # malformed JSON 提取失败，标记被删除，残留私有区字符被兜底清理
        assert "\ue200" not in cleaned
        assert "\ue201" not in cleaned
        assert "\ue202" not in cleaned
