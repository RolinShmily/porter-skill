"""Tests for platform extractor module."""

from unittest.mock import MagicMock, patch

import pytest

from porter_skill.extractors.base import (
    enhance_audio_for_asr,
    get_extractor,
    sanitize_filename,
)
from porter_skill.extractors.youtube import YouTubeExtractor, _convert_vtt_to_srt


def test_sanitize_filename():
    """Verify filename sanitization eliminates invalid characters."""
    assert sanitize_filename('test / \\ : * ? " < > | name') == "test_name"
    assert sanitize_filename("  a   b   c  ") == "a_b_c"
    long_name = "a" * 200
    assert len(sanitize_filename(long_name, max_length=50)) <= 50


def test_youtube_extractor_can_handle():
    """Verify YouTubeExtractor correctly identifies YouTube URLs."""
    extractor = YouTubeExtractor()
    assert extractor.can_handle("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert extractor.can_handle("https://youtu.be/dQw4w9WgXcQ")
    assert extractor.can_handle("https://www.youtube.com/shorts/abcdefghijk")
    assert extractor.can_handle("https://youtube.com/embed/dQw4w9WgXcQ")
    assert not extractor.can_handle("https://www.bilibili.com/video/BV1xx411c7mD")
    assert not extractor.can_handle("https://twitter.com/user/status/123456")


def test_get_extractor_factory():
    """Verify get_extractor returns YouTubeExtractor for YouTube URLs."""
    extractor = get_extractor("https://www.youtube.com/watch?v=abc12345")
    assert isinstance(extractor, YouTubeExtractor)

    with pytest.raises(ValueError, match="Unsupported URL platform"):
        get_extractor("https://vimeo.com/12345678")


def test_youtube_extractor_subtitles_selection():
    """Verify source subtitle language selection logic."""
    extractor = YouTubeExtractor()

    # Prioritizes original language track in auto captions
    auto_subs = {
        "en-orig": [{"ext": "vtt"}],
        "zh-Hans": [{"ext": "vtt"}],
        "ja": [{"ext": "vtt"}],
    }
    assert extractor._select_source_subtitle_lang(auto_subs, is_auto=True) == "en-orig"

    # Standard source language selection
    subs_2 = {
        "fr": [{"ext": "vtt"}],
        "en": [{"ext": "vtt"}],
    }
    assert extractor._select_source_subtitle_lang(subs_2, is_auto=False) == "en"

    # Empty
    assert extractor._select_source_subtitle_lang({}) is None


def test_youtube_extractor_chinese_subtitles_selection():
    """Verify Chinese subtitle selection logic."""
    extractor = YouTubeExtractor()

    # Prioritizes zh-Hans
    subs = {
        "en": [{"ext": "vtt"}],
        "zh-Hans": [{"ext": "vtt"}],
        "zh-Hant": [{"ext": "vtt"}],
    }
    assert extractor._select_chinese_subtitle_lang(subs) == "zh-Hans"

    subs_hant = {
        "zh-Hant": [{"ext": "vtt"}],
        "ja": [{"ext": "vtt"}],
    }
    assert extractor._select_chinese_subtitle_lang(subs_hant) == "zh-Hant"
    assert extractor._select_chinese_subtitle_lang({}) is None


def test_convert_vtt_to_srt():
    """Verify WebVTT to SRT conversion."""
    vtt = """WEBVTT
Kind: captions
Language: en

00:00:01.500 --> 00:00:04.000
<c>Hello</c> <c.yellow>world!</c>

00:00:04.200 --> 00:00:08.500
This is a test subtitle.
Second line.
"""
    srt = _convert_vtt_to_srt(vtt)
    assert "1\n00:00:01,500 --> 00:00:04,000\nHello world!" in srt
    assert "2\n00:00:04,200 --> 00:00:08,500\nThis is a test subtitle. Second line." in srt


def test_youtube_extractor_mock_run(tmp_path):
    """Test extract_raw_materials with mocked yt-dlp and ffmpeg."""
    fake_info = {
        "id": "test_id_123",
        "title": "Test Video Title",
        "uploader": "Test Channel",
        "channel": "Test Channel",
        "duration": 60.0,
        "description": "Test description",
        "thumbnail": None,
        "subtitles": {},
        "automatic_captions": {},
    }

    extractor = YouTubeExtractor()

    with patch("yt_dlp.YoutubeDL") as mock_ydl_cls, patch("subprocess.run") as mock_subproc:
        mock_ydl_instance = MagicMock()
        mock_ydl_instance.extract_info.return_value = fake_info
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl_instance
        mock_subproc.return_value.returncode = 0

        # Create dummy download file in .tmp to simulate yt-dlp download
        task_dir = tmp_path / "test_id_123_Test_Video_Title"
        tmp_dir = task_dir / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        dummy_video = tmp_dir / "download.mp4"
        dummy_video.write_text("fake video data")

        # Also create expected output files when subprocess runs
        def fake_subprocess_side_effect(cmd, *args, **kwargs):
            if "raw/video.mp4" in str(cmd) or any("video.mp4" in str(arg) for arg in cmd):
                p = task_dir / "raw" / "video.mp4"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"dummy mp4")
            if "raw/audio.wav" in str(cmd) or any("audio.wav" in str(arg) for arg in cmd):
                p = task_dir / "raw" / "audio.wav"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"dummy wav")
            res = MagicMock()
            res.returncode = 0
            return res

        mock_subproc.side_effect = fake_subprocess_side_effect

        result = extractor.extract_raw_materials(
            url="https://www.youtube.com/watch?v=test_id_123",
            output_base_dir=tmp_path,
        )

        assert result.task_dir.exists()
        assert result.raw_dir.exists()
        assert result.metadata is not None
        assert result.metadata.id == "test_id_123"
        assert result.metadata.safe_title == "Test_Video_Title"
        assert (result.raw_dir / "metadata.json").exists()


def test_enhance_audio_for_asr(tmp_path):
    """Verify 3-in-1 vocal enhancement filter execution and failure fallback."""
    in_wav = tmp_path / "in.wav"
    in_wav.write_bytes(b"dummy wav data")
    out_wav = tmp_path / "out_enhanced.wav"

    # 1. Successful run
    with patch("subprocess.run") as mock_run:

        def fake_ffmpeg(cmd, *args, **kwargs):
            out_wav.write_bytes(b"enhanced audio data")
            res = MagicMock()
            res.returncode = 0
            return res

        mock_run.side_effect = fake_ffmpeg
        ok = enhance_audio_for_asr(in_wav, out_wav)
        assert ok is True
        assert out_wav.is_file()
        assert out_wav.read_bytes() == b"enhanced audio data"

    # 2. Non-existent input file returns False
    missing_wav = tmp_path / "missing.wav"
    assert enhance_audio_for_asr(missing_wav, out_wav) is False
