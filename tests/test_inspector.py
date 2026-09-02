"""Unit tests for pre-flight link inspector and URL expansion."""

from unittest.mock import MagicMock, patch

from porter_skill.extractors.inspector import (
    identify_platform,
    inspect_url,
    resolve_and_clean_url,
)


def test_resolve_and_clean_url():
    """Test stripping noise tracking query parameters."""
    raw_x = "https://x.com/elonmusk/status/1895000000000000000?s=20&t=abcdef&utm_source=twitter"
    cleaned_x = resolve_and_clean_url(raw_x)
    assert "utm_source" not in cleaned_x
    assert "s=" not in cleaned_x
    assert "t=" not in cleaned_x
    assert "https://x.com/elonmusk/status/1895000000000000000" in cleaned_x

    raw_yt = "https://www.youtube.com/watch?v=gYxZt9Qe0fk&t=15s&utm_campaign=share"
    cleaned_yt = resolve_and_clean_url(raw_yt)
    assert "utm_campaign" not in cleaned_yt
    assert "v=gYxZt9Qe0fk" in cleaned_yt
    assert "t=15s" in cleaned_yt


def test_identify_platform():
    """Test platform detection from URLs."""
    assert identify_platform("https://www.youtube.com/watch?v=123") == "youtube"
    assert identify_platform("https://youtu.be/123") == "youtube"
    assert identify_platform("https://x.com/elonmusk/status/1895000") == "x"
    assert identify_platform("https://twitter.com/user/status/1895000") == "x"
    assert identify_platform("https://t.co/abcXYZ") == "x"
    assert identify_platform("https://example.com/video.mp4") == "generic"


@patch("yt_dlp.YoutubeDL")
def test_inspect_url_success(mock_ydl_cls):
    """Test successful link inspection for vertical X video."""
    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
    mock_ydl.extract_info.return_value = {
        "id": "1895000123",
        "title": "Exciting demo of new AI robot! https://t.co/xyz",
        "uploader": "TechInsider",
        "duration": 45.0,
        "width": 1080,
        "height": 1920,
        "formats": [{"vcodec": "h264", "width": 1080, "height": 1920}],
    }

    res = inspect_url("https://x.com/TechInsider/status/1895000123")
    assert res.is_valid is True
    assert res.has_video is True
    assert res.platform == "x"
    assert res.video_id == "1895000123"
    assert res.is_vertical is True
    assert res.duration_seconds == 45.0
    assert "Exciting demo" in (res.title or "")
    summary = res.format_summary()
    assert "Vertical 9:16" in summary


@patch("yt_dlp.YoutubeDL")
def test_inspect_url_no_video(mock_ydl_cls):
    """Test inspection when tweet contains only text/photos without video."""
    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
    mock_ydl.extract_info.return_value = {
        "id": "1895000999",
        "title": "Just a text tweet without any video attachment.",
        "uploader": "RandomUser",
        "formats": [],
    }

    res = inspect_url("https://x.com/RandomUser/status/1895000999")
    assert res.is_valid is False
    assert res.has_video is False
    assert "does not contain any video" in (res.error_message or "")


@patch("yt_dlp.YoutubeDL")
def test_inspect_url_network_error(mock_ydl_cls):
    """Test inspection failure handling on 404 or 429."""
    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
    mock_ydl.extract_info.side_effect = Exception("HTTP Error 429: Too Many Requests")

    res = inspect_url("https://x.com/user/status/1895000000")
    assert res.is_valid is False
    assert "HTTP 429" in (res.error_message or "")
