"""Unit tests for Bilibili platform extractor (Videos, Bangumi, Cheese, Opus, Subtitles)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from porter_skill.extractors.base import get_extractor
from porter_skill.extractors.bilibili import (
    BilibiliExtractor,
    _convert_bilibili_json_to_srt,
    _convert_vtt_to_srt,
)
from porter_skill.extractors.inspector import identify_platform, resolve_and_clean_url


def test_bilibili_extractor_can_handle():
    """Test URL pattern detection for Bilibili videos, bangumi, cheese, and shortlinks."""
    extractor = BilibiliExtractor()
    assert extractor.can_handle("https://www.bilibili.com/video/BV13x41117TL") is True
    assert extractor.can_handle("https://m.bilibili.com/video/BV13x41117TL") is True
    assert extractor.can_handle("https://www.bilibili.com/video/av92494333") is True
    assert extractor.can_handle("https://www.bilibili.com/bangumi/play/ep21495") is True
    assert extractor.can_handle("https://www.bilibili.com/bangumi/play/ss26801") is True
    assert extractor.can_handle("https://www.bilibili.com/cheese/play/ep229832") is True
    assert extractor.can_handle("https://b23.tv/BV13x41117TL") is True
    assert extractor.can_handle("https://www.bilibili.tv/en/play/34613/341736") is True
    assert extractor.can_handle("https://t.bilibili.com/998134289197432852") is True
    assert extractor.can_handle("https://www.bilibili.com/opus/998134289197432852") is True
    assert extractor.can_handle("https://www.youtube.com/watch?v=123") is False
    assert extractor.can_handle("https://x.com/user/status/123") is False
    assert extractor.can_handle("https://instagram.com/reel/123") is False
    assert extractor.can_handle("https://www.tiktok.com/@user/video/123") is False

    # Check factory registration
    resolved = get_extractor("https://www.bilibili.com/video/BV13x41117TL")
    assert isinstance(resolved, BilibiliExtractor)


def test_bilibili_clean_title():
    """Test title cleaning and suffix stripping."""
    extractor = BilibiliExtractor()

    # 1. Clean trailing _哔哩哔哩_bilibili
    raw1 = "深度拆解大模型强化学习与推理优化_哔哩哔哩_bilibili"
    assert extractor._clean_title(raw1, "BV123") == "深度拆解大模型强化学习与推理优化"

    # 2. Clean trailing - 哔哩哔哩
    raw2 = "2026最新科技趋势演讲 - 哔哩哔哩"
    assert extractor._clean_title(raw2, "BV124") == "2026最新科技趋势演讲"

    # 3. Clean empty fallback
    assert extractor._clean_title("", "BV125") == "bilibili_BV125"


def test_bilibili_inspector_identification():
    """Test Inspector platform detection and URL parameter cleaning."""
    url = (
        "https://www.bilibili.com/video/BV13x41117TL?"
        "spm_id_from=333.999.0.0&vd_source=abcdef123456&from_source=weibo&share_source=copy_link"
    )
    cleaned = resolve_and_clean_url(url)
    assert "spm_id_from" not in cleaned
    assert "vd_source" not in cleaned
    assert "from_source" not in cleaned
    assert "share_source" not in cleaned
    assert identify_platform(cleaned) == "bilibili"
    assert identify_platform("https://b23.tv/BV13x41117TL") == "bilibili"


def test_bilibili_convert_subtitles():
    """Test converting Bilibili JSON BCC format and WebVTT to SubRip SRT."""
    # Test JSON BCC conversion
    bcc_json = json.dumps(
        {
            "body": [
                {"from": 1.25, "to": 4.50, "content": "欢迎观看本期深度技术分享"},
                {"from": 4.60, "to": 8.00, "content": "今天我们将探讨注意力机制与推理加速"},
            ]
        }
    )
    srt_out = _convert_bilibili_json_to_srt(bcc_json)
    assert "00:00:01,250 --> 00:00:04,500" in srt_out
    assert "欢迎观看本期深度技术分享" in srt_out
    assert "00:00:04,600 --> 00:00:08,000" in srt_out
    assert "今天我们将探讨注意力机制与推理加速" in srt_out

    # Test WebVTT conversion
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello Bilibili\n"
    vtt_srt = _convert_vtt_to_srt(vtt)
    assert "00:00:01,000 --> 00:00:03,000" in vtt_srt
    assert "Hello Bilibili" in vtt_srt


@patch("porter_skill.extractors.bilibili.is_valid_video_file", return_value=True)
@patch("porter_skill.extractors.bilibili.get_video_dimensions", return_value=(1920, 1080))
@patch("subprocess.run")
@patch("yt_dlp.YoutubeDL")
def test_bilibili_extractor_extract_raw_materials(
    mock_ydl_cls, mock_subproc, mock_get_dim, mock_is_valid, tmp_path
):
    """Test extracting Bilibili video raw materials into raw/ directory."""
    extractor = BilibiliExtractor()

    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

    mock_ydl.extract_info.return_value = {
        "id": "BV13x41117TL",
        "title": "大语言模型系统全栈剖析_哔哩哔哩_bilibili",
        "uploader": "技术极客",
        "channel": "技术极客频道",
        "duration": 180.0,
        "width": 1920,
        "height": 1080,
        "subtitles": {},
        "thumbnail": None,
    }

    # Simulate yt-dlp downloading a mock video file into .download_temp
    def fake_download(urls):
        for task_dir in tmp_path.glob("BV13x41117TL_*"):
            raw_dir = task_dir / "raw"
            tmp_download_dir = raw_dir / ".download_temp"
            tmp_download_dir.mkdir(parents=True, exist_ok=True)
            mock_video = tmp_download_dir / "BV13x41117TL.mp4"
            mock_video.write_bytes(b"dummy mp4 video bytes" * 100)

    mock_ydl.download.side_effect = fake_download

    # Mock subprocess for ffmpeg/ffprobe
    def fake_subprocess_run(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stderr = ""
        res.stdout = ""

        # ffmpeg video conversion
        if "-c:v" in cmd and "libx264" in cmd:
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"fake standardized mp4 video bytes" * 50)
            return res

        # ffmpeg audio extraction
        if "-acodec" in cmd and "pcm_s16le" in cmd:
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"fake wav bytes" * 100)
            return res

        # ffmpeg cover frame
        if "-vframes" in cmd:
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"fake cover jpg bytes")
            return res

        return res

    mock_subproc.side_effect = fake_subprocess_run

    result = extractor.extract_raw_materials(
        url="https://www.bilibili.com/video/BV13x41117TL",
        output_base_dir=tmp_path,
        ffmpeg_path="ffmpeg",
    )

    assert result.video_path.is_file()
    assert result.audio_path.is_file()
    assert result.metadata_path.is_file()
    assert result.metadata.id == "BV13x41117TL"
    assert result.metadata.platform == "bilibili"
    assert result.metadata.is_vertical is False
    assert result.metadata.width == 1920
    assert result.metadata.height == 1080

    # Verify metadata JSON contents
    saved_meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert saved_meta["id"] == "BV13x41117TL"
    assert saved_meta["platform"] == "bilibili"
    assert "大语言模型" in saved_meta["title"]


@patch("porter_skill.extractors.bilibili.is_valid_video_file", return_value=True)
@patch("porter_skill.extractors.bilibili.get_video_dimensions", return_value=(1920, 1080))
@patch("subprocess.run")
@patch("yt_dlp.YoutubeDL")
def test_bilibili_extractor_with_subtitles(
    mock_ydl_cls, mock_subproc, mock_get_dim, mock_is_valid, tmp_path
):
    """Test extracting Bilibili video with CC JSON subtitles."""
    extractor = BilibiliExtractor()

    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

    mock_ydl.extract_info.return_value = {
        "id": "BV12N4y1M7rh",
        "title": "斯坦福机器学习第1讲_哔哩哔哩_bilibili",
        "uploader": "公开课搬运",
        "duration": 300.0,
        "width": 1920,
        "height": 1080,
        "subtitles": {
            "en": [{"ext": "srt", "url": "http://example.com/en.srt"}],
            "zh-CN": [{"ext": "json", "url": "http://example.com/zh.json"}],
        },
        "thumbnail": None,
    }

    def fake_download(urls):
        for task_dir in tmp_path.glob("BV12N4y1M7rh_*"):
            raw_dir = task_dir / "raw"
            tmp_download_dir = raw_dir / ".download_temp"
            tmp_download_dir.mkdir(parents=True, exist_ok=True)
            mock_video = tmp_download_dir / "BV12N4y1M7rh.mp4"
            mock_video.write_bytes(b"dummy mp4 video bytes" * 100)

            # Write downloaded subtitle files
            srt_en = "1\n00:00:01,000 --> 00:00:04,000\nWelcome to CS229 machine learning.\n"
            json_zh = json.dumps(
                {"body": [{"from": 1.0, "to": 4.0, "content": "欢迎来到 CS229 机器学习课程。"}]}
            )
            (tmp_download_dir / "BV12N4y1M7rh.en.srt").write_text(srt_en, encoding="utf-8")
            (tmp_download_dir / "BV12N4y1M7rh.zh-CN.json").write_text(json_zh, encoding="utf-8")

    mock_ydl.download.side_effect = fake_download

    def fake_subprocess_run(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stderr = ""
        res.stdout = ""
        if "-c:v" in cmd and "libx264" in cmd:
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"fake standardized mp4 video bytes" * 50)
            return res
        if "-acodec" in cmd and "pcm_s16le" in cmd:
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"fake wav bytes" * 100)
            return res
        return res

    mock_subproc.side_effect = fake_subprocess_run

    result = extractor.extract_raw_materials(
        url="https://www.bilibili.com/video/BV12N4y1M7rh",
        output_base_dir=tmp_path,
        ffmpeg_path="ffmpeg",
    )

    assert result.subtitle_path is not None and result.subtitle_path.is_file()
    assert result.subtitle_zh_path is not None and result.subtitle_zh_path.is_file()

    en_content = result.subtitle_path.read_text(encoding="utf-8")
    zh_content = result.subtitle_zh_path.read_text(encoding="utf-8")
    assert "CS229 machine learning" in en_content
    assert "机器学习课程" in zh_content


@patch("porter_skill.extractors.bilibili.is_valid_video_file", return_value=True)
@patch("porter_skill.extractors.bilibili.get_video_dimensions", return_value=(1080, 1920))
@patch("subprocess.run")
@patch("yt_dlp.YoutubeDL")
def test_bilibili_extractor_vertical_detection(
    mock_ydl_cls, mock_subproc, mock_get_dim, mock_is_valid, tmp_path
):
    """Test Bilibili vertical video (Story/Shorts format) detection."""
    extractor = BilibiliExtractor()

    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

    mock_ydl.extract_info.return_value = {
        "id": "BV1Story999",
        "title": "竖屏短视频实拍",
        "uploader": "短视频UP",
        "duration": 15.0,
        "width": 1080,
        "height": 1920,
        "subtitles": {},
        "thumbnail": None,
    }

    def fake_download(urls):
        for task_dir in tmp_path.glob("BV1Story999_*"):
            raw_dir = task_dir / "raw"
            tmp_download_dir = raw_dir / ".download_temp"
            tmp_download_dir.mkdir(parents=True, exist_ok=True)
            mock_video = tmp_download_dir / "BV1Story999.mp4"
            mock_video.write_bytes(b"dummy mp4 video bytes" * 100)

    mock_ydl.download.side_effect = fake_download

    def fake_subprocess_run(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stderr = ""
        res.stdout = ""
        if "-c:v" in cmd and "libx264" in cmd:
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"fake standardized mp4 video bytes" * 50)
            return res
        if "-acodec" in cmd and "pcm_s16le" in cmd:
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"fake wav bytes" * 100)
            return res
        return res

    mock_subproc.side_effect = fake_subprocess_run

    result = extractor.extract_raw_materials(
        url="https://www.bilibili.com/video/BV1Story999",
        output_base_dir=tmp_path,
        ffmpeg_path="ffmpeg",
    )

    assert result.metadata.is_vertical is True
    assert result.metadata.width == 1080
    assert result.metadata.height == 1920


@patch("yt_dlp.YoutubeDL")
def test_bilibili_extractor_auth_restriction_hint(mock_ydl_cls, tmp_path):
    """Test that Bilibili login/SESSDATA restrictions provide clear cookie hints."""
    extractor = BilibiliExtractor()

    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
    mock_ydl.extract_info.side_effect = Exception(
        "login required to view this content with SESSDATA"
    )

    with pytest.raises(RuntimeError) as excinfo:
        extractor.extract_raw_materials(
            url="https://www.bilibili.com/video/BV1VipOnly",
            output_base_dir=tmp_path,
        )

    assert "cookies-from-browser" in str(excinfo.value)
    assert "SESSDATA" in str(excinfo.value)
