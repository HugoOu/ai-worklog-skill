"""GeminiAdapter 单元测试。"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.adapters.gemini import GeminiAdapter
from src.unified_schema import UnifiedSession

tz_sh = timezone(timedelta(hours=8))


# ==========================================
# detect() 测试
# ==========================================
class TestDetect:
    def test_detect_gemini_html(self, gemini_sample_path: Path):
        """Gemini HTML 应被高置信度识别。"""
        adapter = GeminiAdapter()
        score = adapter.detect(gemini_sample_path)
        assert score == 0.95, f"Gemini HTML 探测置信度应为 0.95，实际 {score}"

    def test_detect_non_gemini_html(self, tmp_path: Path):
        """非 Gemini HTML 应返回低置信度。"""
        other_html = tmp_path / "other.html"
        other_html.write_text("<html><body><p>普通网页</p></body></html>", encoding="utf-8")
        adapter = GeminiAdapter()
        assert adapter.detect(other_html) == 0.0

    def test_detect_unsupported_extension(self, tmp_path: Path):
        """不支持的扩展名应返回 0.0。"""
        f = tmp_path / "file.json"
        f.write_text("{}", encoding="utf-8")
        adapter = GeminiAdapter()
        assert adapter.detect(f) == 0.0


# ==========================================
# parse() 测试
# ==========================================
class TestParse:
    def test_parse_returns_sessions(self, gemini_sample_path: Path):
        """应返回 UnifiedSession 列表。"""
        adapter = GeminiAdapter()
        sessions = adapter.parse(gemini_sample_path)
        assert len(sessions) > 0
        assert all(isinstance(s, UnifiedSession) for s in sessions)

    def test_parse_session_count(self, gemini_sample_path: Path):
        """应解析出 17 个会话（与 outer-cell 块数一致）。"""
        adapter = GeminiAdapter()
        sessions = adapter.parse(gemini_sample_path)
        assert len(sessions) == 17

    def test_parse_provider(self, gemini_sample_path: Path):
        """所有会话的 provider 应为 google。"""
        adapter = GeminiAdapter()
        sessions = adapter.parse(gemini_sample_path)
        for s in sessions:
            assert s.provider == "google"
            for m in s.messages:
                assert m.provider == "google"
                assert m.source == "gemini_export"

    def test_parse_message_structure(self, gemini_sample_path: Path):
        """每个会话应含 user + assistant 两条消息（部分会话可能只有 1 条）。"""
        adapter = GeminiAdapter()
        sessions = adapter.parse(gemini_sample_path)

        for s in sessions:
            assert len(s.messages) >= 1
            roles = {m.role for m in s.messages}
            # 至少含 user 或 assistant 之一
            assert roles & {"user", "assistant"}

    def test_parse_timestamp_complete(self, gemini_sample_path: Path):
        """时间戳应含完整时分秒（不只日期）。"""
        adapter = GeminiAdapter()
        sessions = adapter.parse(gemini_sample_path)

        # 第一个会话的时间戳应为 2026-05-21 10:43:45 +08:00
        first = sessions[0]
        assert first.created_at == datetime(2026, 5, 21, 10, 43, 45, tzinfo=tz_sh)
        assert first.created_at.tzinfo == tz_sh

    def test_parse_prompted_prefix_removed(self, gemini_sample_path: Path):
        """user 消息开头的 "Prompted " 前缀应被去除。"""
        adapter = GeminiAdapter()
        sessions = adapter.parse(gemini_sample_path)

        for s in sessions:
            for m in s.messages:
                if m.role == "user":
                    assert not m.content.startswith("Prompted"), \
                        f"消息 {m.id} 仍含 'Prompted' 前缀"

    def test_parse_user_content_nonempty(self, gemini_sample_path: Path):
        """user 消息内容应非空。"""
        adapter = GeminiAdapter()
        sessions = adapter.parse(gemini_sample_path)

        for s in sessions:
            for m in s.messages:
                if m.role == "user":
                    assert m.content.strip(), f"会话 {s.id} 的 user 消息内容为空"

    def test_parse_title_from_user_content(self, gemini_sample_path: Path):
        """会话标题应取自 user 消息前 40 字。"""
        adapter = GeminiAdapter()
        sessions = adapter.parse(gemini_sample_path)

        for s in sessions:
            if s.title and s.messages:
                user_msg = next((m for m in s.messages if m.role == "user"), None)
                if user_msg:
                    # 标题应是 user 内容的前缀（或截断）
                    expected_prefix = user_msg.content[:40]
                    assert s.title.startswith(expected_prefix[:20]), \
                        f"会话 {s.id} 标题 '{s.title}' 与 user 内容不匹配"

    def test_parse_session_ids_unique(self, gemini_sample_path: Path):
        """会话 ID 应唯一。"""
        adapter = GeminiAdapter()
        sessions = adapter.parse(gemini_sample_path)
        ids = [s.id for s in sessions]
        assert len(ids) == len(set(ids)), "会话 ID 有重复"

    def test_parse_file_not_found(self, tmp_path: Path):
        """文件不存在应抛 FileNotFoundError。"""
        adapter = GeminiAdapter()
        with pytest.raises(FileNotFoundError):
            adapter.parse(tmp_path / "nonexistent.html")


# ==========================================
# 时间戳解析单元测试
# ==========================================
class TestTimestampParsing:
    def test_timestamp_hkt(self):
        """应正确解析 HKT 时区时间戳。"""
        import re
        from src.adapters.gemini import _TIMESTAMP_PATTERN, GeminiAdapter

        text = "2026年5月21日 10:43:45 HKT"
        match = _TIMESTAMP_PATTERN.search(text)
        assert match is not None

        dt = GeminiAdapter._parse_timestamp(match)
        assert dt == datetime(2026, 5, 21, 10, 43, 45, tzinfo=tz_sh)

    def test_timestamp_no_tz(self):
        """无时区标注的时间戳应按 UTC+8 处理。"""
        import re
        from src.adapters.gemini import _TIMESTAMP_PATTERN, GeminiAdapter

        text = "2026年1月15日 09:30:00"
        match = _TIMESTAMP_PATTERN.search(text)
        assert match is not None

        dt = GeminiAdapter._parse_timestamp(match)
        assert dt == datetime(2026, 1, 15, 9, 30, 0, tzinfo=tz_sh)

    def test_timestamp_not_match_plain_date(self):
        """正则不应匹配无时间的纯日期（避免误匹配正文中的日期）。"""
        import re
        from src.adapters.gemini import _TIMESTAMP_PATTERN

        # 法规中常见的日期表述，不应被匹配
        text = "自2009年1月1日起实施"
        match = _TIMESTAMP_PATTERN.search(text)
        assert match is None
