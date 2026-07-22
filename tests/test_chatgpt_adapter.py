"""ChatGPTAdapter 单元测试。"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.adapters.chatgpt import ChatGPTAdapter
from src.unified_schema import UnifiedSession, UnifiedMessage

tz_utc = timezone.utc
tz_sh = timezone(timedelta(hours=8))


# ==========================================
# detect() 测试
# ==========================================
class TestDetect:
    def test_detect_json_chatgpt(self, chatgpt_sample_path: Path):
        """ChatGPT 裸 JSON 应被高置信度识别。"""
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
        """非 ChatGPT 结构的 JSON 应返回低置信度。"""
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
# parse() 测试
# ==========================================
class TestParse:
    def test_parse_returns_sessions(self, chatgpt_sample_path: Path):
        """应返回 UnifiedSession 列表。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)
        assert len(sessions) == 2
        assert all(isinstance(s, UnifiedSession) for s in sessions)

    def test_parse_session_ids(self, chatgpt_sample_path: Path):
        """会话 ID 应正确提取。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)
        ids = {s.id for s in sessions}
        assert ids == {"conv-001", "conv-002"}

    def test_parse_titles(self, chatgpt_sample_path: Path):
        """会话标题应正确提取。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)
        titles = {s.title for s in sessions}
        assert "Python 列表去重" in titles
        assert "Git rebase 简介" in titles

    def test_parse_provider(self, chatgpt_sample_path: Path):
        """所有会话的 provider 应为 openai。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)
        for s in sessions:
            assert s.provider == "openai"
            for m in s.messages:
                assert m.provider == "openai"
                assert m.source == "chatgpt_export"

    def test_parse_roles(self, chatgpt_sample_path: Path):
        """应正确提取 user/assistant/system 角色。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        conv1 = next(s for s in sessions if s.id == "conv-001")
        roles = [m.role for m in conv1.messages]
        assert roles == ["user", "assistant", "user", "assistant"]

        conv2 = next(s for s in sessions if s.id == "conv-002")
        roles2 = [m.role for m in conv2.messages]
        assert roles2 == ["system", "user", "assistant"]

    def test_parse_model_slug(self, chatgpt_sample_path: Path):
        """assistant 消息应含 model_slug。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        conv1 = next(s for s in sessions if s.id == "conv-001")
        assistant_msgs = [m for m in conv1.messages if m.role == "assistant"]
        assert all(m.model == "gpt-4o" for m in assistant_msgs)

        conv2 = next(s for s in sessions if s.id == "conv-002")
        assistant_msg2 = next(m for m in conv2.messages if m.role == "assistant")
        assert assistant_msg2.model == "gpt-4o-mini"

    def test_parse_session_model(self, chatgpt_sample_path: Path):
        """会话级 model 应取最后一条 assistant 消息的 model。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        conv1 = next(s for s in sessions if s.id == "conv-001")
        assert conv1.model == "gpt-4o"

        conv2 = next(s for s in sessions if s.id == "conv-002")
        assert conv2.model == "gpt-4o-mini"

    def test_parse_timestamps_utc(self, chatgpt_sample_path: Path):
        """时间戳应为 UTC 时区（pipeline 后续会归一化到本地时区）。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        conv1 = next(s for s in sessions if s.id == "conv-001")
        first_msg = conv1.messages[0]
        # 2026-05-21 10:43:45 +08:00 = 2026-05-21 02:43:45 UTC
        assert first_msg.created_at == datetime(2026, 5, 21, 2, 43, 45, tzinfo=tz_utc)
        assert first_msg.created_at.tzinfo == tz_utc

    def test_parse_missing_create_time_fallback(self, chatgpt_sample_path: Path):
        """缺失 create_time 的消息应有 fallback 时间（不为 None）。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        conv2 = next(s for s in sessions if s.id == "conv-002")
        assistant_msg = next(m for m in conv2.messages if m.role == "assistant")
        # conv-002 的 assistant 消息在样本中故意缺失 create_time
        assert assistant_msg.created_at is not None

    def test_parse_content_text(self, chatgpt_sample_path: Path):
        """应正确提取文本内容。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        conv1 = next(s for s in sessions if s.id == "conv-001")
        first_user = next(m for m in conv1.messages if m.role == "user")
        assert "Python 列表怎么去重" in first_user.content

    def test_parse_messages_sorted_by_time(self, chatgpt_sample_path: Path):
        """消息应按 created_at 排序。"""
        adapter = ChatGPTAdapter()
        sessions = adapter.parse(chatgpt_sample_path)

        for s in sessions:
            timestamps = [m.created_at for m in s.messages if m.created_at]
            assert timestamps == sorted(timestamps), f"会话 {s.id} 消息未按时间排序"

    def test_parse_file_not_found(self, tmp_path: Path):
        """文件不存在应抛 FileNotFoundError。"""
        adapter = ChatGPTAdapter()
        with pytest.raises(FileNotFoundError):
            adapter.parse(tmp_path / "nonexistent.json")

    def test_parse_zip_input(self, tmp_path: Path, chatgpt_sample_path: Path):
        """应支持 ZIP 输入（仅解压读 conversations.json）。"""
        zip_path = tmp_path / "chatgpt.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(chatgpt_sample_path, "conversations.json")

        adapter = ChatGPTAdapter()
        sessions = adapter.parse(zip_path)
        assert len(sessions) == 2  # 与裸 JSON 解析结果一致
