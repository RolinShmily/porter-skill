"""Unit tests for TikTok platform extractor (Videos, Embeds, Shortlinks, Subtitles)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from porter_skill.extractors.base import get_extractor
from porter_skill.extractors.inspector import identify_platform, resolve_and_clean_url
from porter_skill.extractors.tiktok import TikTokExtractor, _convert_vtt_to_srt


def test_tiktok_extractor_can_handle():
    """Test URL pattern detection for TikTok videos, shortlinks, embeds, and shares."""
    extractor = TikTokExtractor()
    assert (
        extractor.can_handle("https://www.tiktok.com/@corgibobaa/video/7170520270497680683") is True
    )
    assert extractor.can_handle("https://m.tiktok.com/@user/video/7170520270497680683") is True
    assert extractor.can_handle("https://tiktok.com/@user/photo/7170520270497680683") is True
    assert extractor.can_handle("https://vm.tiktok.com/ZTRC5xgJp/") is True
    assert extractor.can_handle("https://vt.tiktok.com/ZTRC5xgJp/") is True
    assert extractor.can_handle("https://www.tiktok.com/t/ZTRC5xgJp/") is True
    assert extractor.can_handle("https://www.tiktok.com/embed/7170520270497680683") is True
    assert extractor.can_handle("https://www.tiktok.com/share/video/7170520270497680683") is True
    assert extractor.can_handle("https://www.youtube.com/watch?v=123") is False
    assert extractor.can_handle("https://x.com/user/status/123") is False
    assert extractor.can_handle("https://instagram.com/reel/123") is False

    # Check factory registration
    resolved = get_extractor("https://www.tiktok.com/@corgibobaa/video/7170520270497680683")
    assert isinstance(resolved, TikTokExtractor)


def test_tiktok_clean_caption_to_title():
    """Test caption text cleaning, mention/tag stripping, and title generation."""
    extractor = TikTokExtractor()

    # 1. Clean trailing links and multiple lines
    caption = "How AI transforms modern robotics\nFull video: https://vm.tiktok.com/xyz #fyp #robotics #tech"
    cleaned = extractor._clean_caption_to_title(caption, uploader="TechDaily", post_id="712345")
    assert cleaned == "How AI transforms modern robotics"

    # 2. Clean leading @mentions
    caption_mentions = "@openai @deepseek Check out this amazing coding demonstration! #coding #ai"
    cleaned_mentions = extractor._clean_caption_to_title(
        caption_mentions, uploader="DevGuru", post_id="712346"
    )
    assert cleaned_mentions == "Check out this amazing coding demonstration!"

    # 3. Dense hashtags only fallback to title or default
    caption_tags = "#fyp #foryou #trending #viral #xyzbca"
    cleaned_tags = extractor._clean_caption_to_title(
        caption_tags, uploader="creator", post_id="712347"
    )
    assert cleaned_tags == "TikTok_by_creator"

    # 4. Empty caption fallback
    empty_cleaned = extractor._clean_caption_to_title("", uploader="creator2", post_id="712348")
    assert empty_cleaned == "TikTok_by_creator2"


def test_tiktok_inspector_identification():
    """Test Inspector platform detection and URL parameter cleaning."""
    url = "https://www.tiktok.com/@user/video/7170520270497680683?is_from_webapp=1&sender_device=pc&_r=1"
    cleaned = resolve_and_clean_url(url)
    assert "is_from_webapp" not in cleaned
    assert "sender_device" not in cleaned
    assert "_r" not in cleaned
    assert identify_platform(cleaned) == "tiktok"
    assert identify_platform("https://vm.tiktok.com/ZTRC5xgJp/") == "tiktok"
    assert identify_platform("https://vt.tiktok.com/ZTRC5xgJp/") == "tiktok"


def test_tiktok_convert_vtt_to_srt():
    """Test WebVTT to SRT conversion helper."""
    vtt = """WEBVTT

00:00:01.000 --> 00:00:03.500
<c>Hello</c> world!

00:00:04.000 --> 00:00:06.200
This is a test.
"""
    srt = _convert_vtt_to_srt(vtt)
    assert "00:00:01,000 --> 00:00:03,500" in srt
    assert "Hello world!" in srt
    assert "00:00:04,000 --> 00:00:06,200" in srt
    assert "This is a test." in srt


@patch("porter_skill.extractors.tiktok.is_valid_video_file", return_value=True)
@patch("porter_skill.extractors.tiktok.get_video_dimensions", return_value=(1080, 1920))
@patch("subprocess.run")
@patch("yt_dlp.YoutubeDL")
def test_tiktok_extractor_extract_raw_materials(
    mock_ydl_cls, mock_subproc, mock_get_dim, mock_is_valid, tmp_path
):
    """Test extracting TikTok video raw materials into raw/ directory."""
    extractor = TikTokExtractor()

    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

    mock_ydl.extract_info.return_value = {
        "id": "7170520270497680683",
        "description": "Amazing dog solves math puzzle #smartdog #corgi",
        "uploader": "corgibobaa",
        "duration": 25.0,
        "width": 1080,
        "height": 1920,
        "subtitles": {},
        "thumbnail": None,
    }

    # Simulate yt-dlp downloading a mock video file into .download_temp
    def fake_download(urls):
        for task_dir in tmp_path.glob("7170520270497680683_*"):
            raw_dir = task_dir / "raw"
            tmp_download_dir = raw_dir / ".download_temp"
            tmp_download_dir.mkdir(parents=True, exist_ok=True)
            mock_video = tmp_download_dir / "7170520270497680683.mp4"
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
        url="https://www.tiktok.com/@corgibobaa/video/7170520270497680683",
        output_base_dir=tmp_path,
        ffmpeg_path="ffmpeg",
    )

    assert result.video_path.is_file()
    assert result.audio_path.is_file()
    assert result.metadata_path.is_file()
    assert result.metadata.id == "7170520270497680683"
    assert result.metadata.platform == "tiktok"
    assert result.metadata.is_vertical is True
    assert result.metadata.width == 1080
    assert result.metadata.height == 1920

    # Verify metadata JSON contents
    saved_meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert saved_meta["id"] == "7170520270497680683"
    assert saved_meta["platform"] == "tiktok"


@patch("porter_skill.extractors.tiktok.is_valid_video_file", return_value=True)
@patch("porter_skill.extractors.tiktok.get_video_dimensions", return_value=(1920, 1080))
@patch("subprocess.run")
@patch("yt_dlp.YoutubeDL")
def test_tiktok_extractor_with_subtitles(
    mock_ydl_cls, mock_subproc, mock_get_dim, mock_is_valid, tmp_path
):
    """Test extracting TikTok videos with native and Chinese subtitles."""
    extractor = TikTokExtractor()

    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

    mock_ydl.extract_info.return_value = {
        "id": "7170520270497680684",
        "description": "Tech lecture on quantum computing",
        "uploader": "QuantumLab",
        "duration": 60.0,
        "width": 1920,
        "height": 1080,
        "subtitles": {
            "en": [{"ext": "vtt", "url": "http://example.com/en.vtt"}],
            "zh-Hans": [{"ext": "vtt", "url": "http://example.com/zh.vtt"}],
        },
        "thumbnail": None,
    }

    def fake_download(urls):
        for task_dir in tmp_path.glob("7170520270497680684_*"):
            raw_dir = task_dir / "raw"
            tmp_download_dir = raw_dir / ".download_temp"
            tmp_download_dir.mkdir(parents=True, exist_ok=True)
            mock_video = tmp_download_dir / "7170520270497680684.mp4"
            mock_video.write_bytes(b"dummy mp4 video bytes" * 100)

            # Write downloaded subtitle files
            vtt_en = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nQuantum computers are fast.\n"
            vtt_zh = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n量子计算机非常快速。\n"
            (tmp_download_dir / "7170520270497680684.en.vtt").write_text(vtt_en, encoding="utf-8")
            (tmp_download_dir / "7170520270497680684.zh-Hans.vtt").write_text(
                vtt_zh, encoding="utf-8"
            )

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
        url="https://www.tiktok.com/@QuantumLab/video/7170520270497680684",
        output_base_dir=tmp_path,
        ffmpeg_path="ffmpeg",
    )

    assert result.subtitle_path is not None
    assert result.subtitle_path.is_file()
    assert "Quantum computers are fast." in result.subtitle_path.read_text(encoding="utf-8")

    assert result.subtitle_zh_path is not None
    assert result.subtitle_zh_path.is_file()
    assert "量子计算机非常快速。" in result.subtitle_zh_path.read_text(encoding="utf-8")
    assert result.metadata.is_vertical is False


@patch("yt_dlp.YoutubeDL")
def test_tiktok_extractor_slideshow_photo_mode_rejection(mock_ydl_cls, tmp_path):
    """Test rejecting pure image photo slideshows without video stream."""
    extractor = TikTokExtractor()

    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

    mock_ydl.extract_info.return_value = {
        "id": "7170520270497680685",
        "_type": "playlist",
        "title": "Photo slideshow",
        "entries": [
            {"id": "img1", "formats": []},
            {"id": "img2", "formats": []},
        ],
    }

    with pytest.raises(RuntimeError, match="photo slideshow without a downloadable video"):
        extractor.extract_raw_materials(
            url="https://www.tiktok.com/@user/photo/7170520270497680685",
            output_base_dir=tmp_path,
        )


@patch("yt_dlp.YoutubeDL")
def test_tiktok_extractor_login_anti_scraping_error(mock_ydl_cls, tmp_path):
    """Test informative error message on anti-scraping or login challenge."""
    extractor = TikTokExtractor()

    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
    mock_ydl.extract_info.side_effect = Exception("Captcha challenge required to view video")

    with pytest.raises(RuntimeError, match="--cookies-from-browser"):
        extractor.extract_raw_materials(
            url="https://www.tiktok.com/@user/video/7170520270497680686",
            output_base_dir=tmp_path,
        )
