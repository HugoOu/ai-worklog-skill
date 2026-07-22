"""Pipeline 集成测试。"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.pipeline import (
    run,
    detect_provider,
    get_adapter,
    normalize_timezone,
    _parse_timezone,
    DEFAULT_TIMEZONE,
)
from src.unified_schema import UnifiedSession, UnifiedMessage

tz_sh = timezone(timedelta(hours=8))
tz_utc = timezone.utc


# ==========================================
# detect_provider 测试
# ==========================================
class TestDetectProvider:
    def test_detect_chatgpt_auto(self, chatgpt_sample_path: Path):
        """自动探测 ChatGPT 样本。"""
        adapter, score = detect_provider(chatgpt_sample_path)
        assert adapter.provider == "openai"
        assert score >= 0.9

    def test_detect_gemini_auto(self, gemini_sample_path: Path):
        """自动探测 Gemini 样本。"""
        adapter, score = detect_provider(gemini_sample_path)
        assert adapter.provider == "google"
        assert score >= 0.9

    def test_detect_unknown_format(self, tmp_path: Path):
        """未知格式应抛 ValueError。"""
        f = tmp_path / "unknown.txt"
        f.write_text("hello", encoding="utf-8")
        with pytest.raises(ValueError, match="无法识别文件格式"):
            detect_provider(f)


# ==========================================
# get_adapter 测试
# ==========================================
class TestGetAdapter:
    def test_get_openai(self):
        adapter = get_adapter("openai")
        assert adapter.provider == "openai"

    def test_get_google(self):
        adapter = get_adapter("google")
        assert adapter.provider == "google"

    def test_get_unknown_provider(self):
        with pytest.raises(ValueError, match="未找到 provider"):
            get_adapter("nonexistent")


# ==========================================
# run() 端到端测试
# ==========================================
class TestRun:
    def test_run_chatgpt_auto(self, chatgpt_sample_path: Path):
        """ChatGPT 自动探测端到端。"""
        sessions = run(chatgpt_sample_path, provider="auto")
        assert len(sessions) == 2
        assert all(s.provider == "openai" for s in sessions)

    def test_run_gemini_auto(self, gemini_sample_path: Path):
        """Gemini 自动探测端到端。"""
        sessions = run(gemini_sample_path, provider="auto")
        assert len(sessions) == 17
        assert all(s.provider == "google" for s in sessions)

    def test_run_chatgpt_explicit_provider(self, chatgpt_sample_path: Path):
        """显式指定 provider。"""
        sessions = run(chatgpt_sample_path, provider="openai")
        assert len(sessions) == 2

    def test_run_timezone_normalization(self, chatgpt_sample_path: Path):
        """时间戳应归一化到 Asia/Shanghai (+08:00)。"""
        sessions = run(chatgpt_sample_path, provider="openai", timezone_str="Asia/Shanghai")
        conv1 = next(s for s in sessions if s.id == "conv-001")
        first_msg = conv1.messages[0]
        # 2026-05-21 10:43:45 +08:00
        assert first_msg.created_at == datetime(2026, 5, 21, 10, 43, 45, tzinfo=tz_sh)
        # 时区偏移应为 +08:00
        assert first_msg.created_at.utcoffset() == timedelta(hours=8)

    def test_run_export_json(self, chatgpt_sample_path: Path, tmp_path: Path):
        """应导出 JSON 文件。"""
        outdir = tmp_path / "output"
        sessions = run(
            chatgpt_sample_path, provider="openai",
            out_format="json", outdir=outdir,
        )
        out_file = outdir / "unified_sessions.json"
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["provider"] == "openai"

    def test_run_export_jsonl(self, chatgpt_sample_path: Path, tmp_path: Path):
        """应导出 JSONL 文件（每行一个 JSON）。"""
        outdir = tmp_path / "output"
        sessions = run(
            chatgpt_sample_path, provider="openai",
            out_format="jsonl", outdir=outdir,
        )
        out_file = outdir / "unified_sessions.jsonl"
        assert out_file.exists()
        lines = out_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert "id" in obj
            assert "messages" in obj

    def test_run_group_by_date(self, chatgpt_sample_path: Path, tmp_path: Path):
        """group_by_date=True 应额外输出 daily_conversations.json。"""
        outdir = tmp_path / "output"
        run(
            chatgpt_sample_path, provider="openai",
            outdir=outdir, group_by_date=True,
        )
        daily_file = outdir / "daily_conversations.json"
        assert daily_file.exists()
        data = json.loads(daily_file.read_text(encoding="utf-8"))
        # ChatGPT 样本含 2 天（2026-05-21 和 2026-05-22）
        dates = {d["date"] for d in data}
        assert "2026-05-21" in dates
        assert "2026-05-22" in dates

    def test_run_file_not_found(self, tmp_path: Path):
        """文件不存在应抛 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            run(tmp_path / "nonexistent.json")


# ==========================================
# normalize_timezone 测试
# ==========================================
class TestNormalizeTimezone:
    def test_normalize_naive_datetime(self):
        """无时区信息的 datetime 应假定为 UTC 并转换。"""
        msg = UnifiedMessage(
            id="m1", session_id="s1", role="user", content="test",
            provider="openai",
            created_at=datetime(2026, 5, 21, 2, 43, 45),  # 无 tzinfo
            source="chatgpt_export",
        )
        sess = UnifiedSession(
            id="s1", provider="openai", messages=[msg],
            created_at=datetime(2026, 5, 21, 2, 43, 45),
            source="chatgpt_export",
        )
        normalize_timezone([sess], tz=tz_sh)
        # UTC 02:43:45 → +08:00 10:43:45
        assert sess.messages[0].created_at == datetime(2026, 5, 21, 10, 43, 45, tzinfo=tz_sh)

    def test_normalize_already_has_tz(self):
        """已有时区信息的 datetime 应正常转换。"""
        msg = UnifiedMessage(
            id="m1", session_id="s1", role="user", content="test",
            provider="openai",
            created_at=datetime(2026, 5, 21, 2, 43, 45, tzinfo=tz_utc),
            source="chatgpt_export",
        )
        sess = UnifiedSession(
            id="s1", provider="openai", messages=[msg],
            created_at=datetime(2026, 5, 21, 2, 43, 45, tzinfo=tz_utc),
            source="chatgpt_export",
        )
        normalize_timezone([sess], tz=tz_sh)
        assert sess.messages[0].created_at == datetime(2026, 5, 21, 10, 43, 45, tzinfo=tz_sh)


# ==========================================
# _parse_timezone 测试
# ==========================================
class TestParseTimezone:
    def test_parse_iana(self):
        """应解析 IANA 时区名称。"""
        tz = _parse_timezone("Asia/Shanghai")
        # 应有 +08:00 偏移
        assert tz.utcoffset(datetime(2026, 1, 1)) == timedelta(hours=8)

    def test_parse_utc_offset(self):
        """应解析 UTC 偏移。"""
        tz = _parse_timezone("+08:00")
        assert tz.utcoffset(None) == timedelta(hours=8)

    def test_parse_utc_offset_short(self):
        """应解析短格式 UTC 偏移。"""
        tz = _parse_timezone("UTC+8")
        assert tz.utcoffset(None) == timedelta(hours=8)

    def test_parse_invalid_fallback(self):
        """无效时区应 fallback 到默认 (UTC+8)。"""
        tz = _parse_timezone("invalid/timezone")
        assert tz.utcoffset(None) == timedelta(hours=8)
