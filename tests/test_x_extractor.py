"""Unit tests for X (formerly Twitter) platform extractor."""

import json
from unittest.mock import MagicMock, patch

from porter_skill.extractors.base import get_extractor
from porter_skill.extractors.x import XExtractor


def test_x_extractor_can_handle():
    """Test URL pattern detection for X / Twitter."""
    extractor = XExtractor()
    assert extractor.can_handle("https://x.com/elonmusk/status/1895000000000000000") is True
    assert extractor.can_handle("https://twitter.com/user/status/123456789") is True
    assert extractor.can_handle("https://mobile.twitter.com/user/status/123456789") is True
    assert extractor.can_handle("https://x.com/i/status/123456789") is True
    assert extractor.can_handle("https://t.co/abcXYZ123") is True
    assert extractor.can_handle("https://www.youtube.com/watch?v=123") is False

    # Check factory registration
    resolved = get_extractor("https://x.com/OpenAI/status/1895000000")
    assert isinstance(resolved, XExtractor)


def test_x_extractor_clean_tweet_title():
    """Test tweet text cleaning and title generation."""
    extractor = XExtractor()

    # 1. Clean trailing t.co links and multiple lines
    text = "Amazing breakthrough in robotics!\nWatch full demonstration here: https://t.co/demo123"
    cleaned = extractor._clean_tweet_title(text, uploader="TechDaily", status_id="123")
    assert cleaned == "Amazing breakthrough in robotics!"

    # 2. Clean leading @mentions
    text_with_mentions = "@sama @karpathy Incredible work on model reasoning!"
    cleaned_mentions = extractor._clean_tweet_title(
        text_with_mentions, uploader="AIResearch", status_id="456"
    )
    assert cleaned_mentions == "Incredible work on model reasoning!"

    # 3. Empty text fallback
    empty_cleaned = extractor._clean_tweet_title("", uploader="ElonMusk", status_id="789")
    assert empty_cleaned == "Tweet_by_ElonMusk"


@patch("subprocess.run")
@patch("yt_dlp.YoutubeDL")
def test_x_extractor_extract_raw_materials(mock_ydl_cls, mock_subproc, tmp_path):
    """Test extracting X video raw materials into raw/ directory."""
    extractor = XExtractor()

    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

    mock_ydl.extract_info.return_value = {
        "id": "1895123456",
        "title": "Exciting AI announcement! https://t.co/xyz",
        "uploader": "SamAltman",
        "uploader_id": "sama",
        "duration": 62.0,
        "width": 1080,
        "height": 1920,
        "subtitles": {},
        "thumbnail": None,
    }

    # Simulate yt-dlp downloading a mock video file into .tmp
    def fake_download(urls):
        for task_dir in tmp_path.glob("1895123456_*"):
            tmp_download_dir = task_dir / ".tmp"
            tmp_download_dir.mkdir(parents=True, exist_ok=True)
            mock_video = tmp_download_dir / "download.mp4"
            mock_video.write_bytes(b"fake video data")
        return 0

    mock_ydl.download.side_effect = fake_download

    # Mock subprocess.run for ffprobe, ffmpeg video standardizer and audio wav extraction
    def fake_subprocess_run(cmd, *args, **kwargs):
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        if "ffprobe" in str(cmd[0]):
            proc_mock.stdout = json.dumps(
                {
                    "streams": [
                        {"codec_name": "h264", "codec_type": "video"},
                        {"codec_name": "aac", "codec_type": "audio"},
                    ]
                }
            )
        else:
            # When ffmpeg is called, write fake output files
            target_path = cmd[-1]
            try:
                with open(target_path, "wb") as f:
                    f.write(b"standardized media content" * 100)
            except Exception:  # noqa: BLE001, S110
                pass
        return proc_mock

    mock_subproc.side_effect = fake_subprocess_run

    res = extractor.extract_raw_materials(
        url="https://x.com/sama/status/1895123456",
        output_base_dir=tmp_path,
    )

    assert res.task_dir.exists()
    assert res.raw_dir.exists()
    assert res.video_path.name == "video.mp4"
    assert res.audio_path.name == "audio.wav"
    assert res.metadata is not None
    assert res.metadata.id == "1895123456"
    assert res.metadata.is_vertical is True
    assert res.metadata.platform == "x"
    assert res.metadata_path is not None and res.metadata_path.exists()

    meta_json = json.loads(res.metadata_path.read_text(encoding="utf-8"))
    assert meta_json["id"] == "1895123456"
    assert meta_json["is_vertical"] is True
