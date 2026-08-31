"""Unit tests for Instagram platform extractor (Reels, Posts, IGTV, Carousels)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from porter_skill.extractors.base import get_extractor
from porter_skill.extractors.inspector import identify_platform, resolve_and_clean_url
from porter_skill.extractors.instagram import InstagramExtractor


def test_instagram_extractor_can_handle():
    """Test URL pattern detection for Instagram Reels, Posts, IGTV, and share links."""
    extractor = InstagramExtractor()
    assert extractor.can_handle("https://www.instagram.com/reel/Cxxxx123/") is True
    assert extractor.can_handle("https://www.instagram.com/reels/Cyyyy456/") is True
    assert extractor.can_handle("https://instagram.com/p/Czzzz789/") is True
    assert extractor.can_handle("https://m.instagram.com/tv/Caaaa000/") is True
    assert extractor.can_handle("https://www.instagram.com/share/reel/Cbbbb111/") is True
    assert extractor.can_handle("https://www.instagram.com/share/p/Ccccc222/") is True
    assert extractor.can_handle("https://www.instagram.com/stories/username/123456789/") is True
    assert extractor.can_handle("https://www.instagram.com/username/reel/Cdddd333/") is True
    assert extractor.can_handle("https://ig.me/abcXYZ123") is True
    assert extractor.can_handle("https://instagr.am/p/Ceeee444/") is True
    assert extractor.can_handle("https://www.youtube.com/watch?v=123") is False
    assert extractor.can_handle("https://x.com/user/status/123") is False

    # Check factory registration
    resolved = get_extractor("https://www.instagram.com/reel/Cxxxx123/")
    assert isinstance(resolved, InstagramExtractor)


def test_instagram_clean_caption_to_title():
    """Test caption text cleaning, mention/tag stripping, and title generation."""
    extractor = InstagramExtractor()

    # 1. Clean trailing links and multiple lines
    caption = "How Starship achieves rapid turnaround\nFull interview: https://ig.me/xyz #SpaceX #Starship"
    cleaned = extractor._clean_caption_to_title(caption, uploader="elonmusk", post_id="C123")
    assert cleaned == "How Starship achieves rapid turnaround"

    # 2. Clean leading @mentions
    caption_mentions = "@nasa @spacex Watch the hot fire test at Starbase! #rocket"
    cleaned_mentions = extractor._clean_caption_to_title(
        caption_mentions, uploader="TechDaily", post_id="C456"
    )
    assert cleaned_mentions == "Watch the hot fire test at Starbase!"

    # 3. Dense hashtags only fallback to text or default
    caption_tags = "#reels #trending #viral #fyp"
    cleaned_tags = extractor._clean_caption_to_title(
        caption_tags, uploader="creator", post_id="C789"
    )
    assert cleaned_tags == "Instagram_by_creator"

    # 4. Empty caption fallback
    empty_cleaned = extractor._clean_caption_to_title("", uploader="photographer", post_id="C999")
    assert empty_cleaned == "Instagram_by_photographer"


def test_instagram_inspector_identification():
    """Test Inspector platform detection and URL parameter cleaning."""
    url = "https://www.instagram.com/reel/Cxxxx123/?igshid=YmMyMTA2M2Y=&utm_source=ig_web_copy_link"
    cleaned = resolve_and_clean_url(url)
    assert "igshid" not in cleaned
    assert "utm_source" not in cleaned
    assert identify_platform(cleaned) == "instagram"


@patch("subprocess.run")
@patch("yt_dlp.YoutubeDL")
def test_instagram_extractor_extract_raw_materials(mock_ydl_cls, mock_subproc, tmp_path):
    """Test extracting Instagram Reel raw materials into raw/ directory."""
    extractor = InstagramExtractor()

    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

    mock_ydl.extract_info.return_value = {
        "id": "Cxxxx123",
        "description": "Fascinating robotics physics breakdown #robotics #ai",
        "uploader": "bostondynamics",
        "channel": "bostondynamics",
        "duration": 45.0,
        "width": 1080,
        "height": 1920,
        "subtitles": {},
        "thumbnail": None,
    }

    # Simulate yt-dlp downloading a mock video file into .tmp
    def fake_download(urls):
        for task_dir in tmp_path.glob("Cxxxx123_*"):
            tmp_download_dir = task_dir / ".tmp"
            tmp_download_dir.mkdir(parents=True, exist_ok=True)
            mock_video = tmp_download_dir / "downloaded_raw.mp4"
            mock_video.write_bytes(b"dummy mp4 video bytes")

    mock_ydl.download.side_effect = fake_download

    # Simulate ffmpeg subprocess creating files
    def fake_subprocess_run(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stderr = ""
        res.stdout = ""

        cmd_list = [str(x) for x in cmd]
        target_path = Path(cmd_list[-1])
        if target_path.name == "video.mp4":
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"standard h264 bytes")
        elif target_path.name == "audio.wav":
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"standard 16khz wav bytes")
        elif target_path.name == "cover.jpg":
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"standard cover jpg bytes")

        return res

    mock_subproc.side_effect = fake_subprocess_run

    with patch("porter_skill.extractors.instagram.get_video_dimensions", return_value=(1080, 1920)):
        result = extractor.extract_raw_materials(
            url="https://www.instagram.com/reel/Cxxxx123/",
            output_base_dir=tmp_path,
        )

    assert result.video_path.is_file()
    assert result.audio_path.is_file()
    assert result.metadata is not None
    assert result.metadata.platform == "instagram"
    assert result.metadata.uploader == "bostondynamics"
    assert result.metadata.is_vertical is True
    assert result.metadata_path is not None and result.metadata_path.is_file()

    metadata_data = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata_data["id"] == "Cxxxx123"
    assert "robotics" in metadata_data["title"].lower()


@patch("yt_dlp.YoutubeDL")
def test_instagram_carousel_smart_filter(mock_ydl_cls, tmp_path):
    """Test extracting first valid video in an Instagram Carousel post."""
    extractor = InstagramExtractor()

    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

    # Carousel: Item 1 is image, Item 2 is video
    mock_ydl.extract_info.return_value = {
        "_type": "playlist",
        "id": "Ccarousel456",
        "title": "Post by nasa",
        "description": "Artemis test series flight test",
        "uploader": "nasa",
        "entries": [
            {
                "id": "item1_img",
                "formats": [{"format_id": "img", "vcodec": "none"}],
                "vcodec": "none",
            },
            {
                "id": "item2_vid",
                "formats": [
                    {
                        "format_id": "1080p",
                        "vcodec": "h264",
                        "width": 1080,
                        "height": 1080,
                        "url": "https://instagram.com/vid.mp4",
                    }
                ],
                "vcodec": "h264",
                "duration": 30.0,
                "width": 1080,
                "height": 1080,
            },
        ],
    }

    # Simulate yt-dlp downloading
    def fake_download(urls):
        for task_dir in tmp_path.glob("item2_vid_*"):
            tmp_download_dir = task_dir / ".tmp"
            tmp_download_dir.mkdir(parents=True, exist_ok=True)
            mock_video = tmp_download_dir / "downloaded_raw.mp4"
            mock_video.write_bytes(b"dummy mp4 video bytes")

    mock_ydl.download.side_effect = fake_download

    def fake_carousel_subproc(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stderr = ""
        res.stdout = ""
        cmd_list = [str(x) for x in cmd]
        target_path = Path(cmd_list[-1])
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"mock bytes")
        return res

    with (
        patch("subprocess.run", side_effect=fake_carousel_subproc),
        patch("porter_skill.extractors.instagram.get_video_dimensions", return_value=(1080, 1080)),
    ):
        result = extractor.extract_raw_materials(
            url="https://www.instagram.com/p/Ccarousel456/",
            output_base_dir=tmp_path,
        )

    assert result.metadata is not None
    assert result.metadata.id == "item2_vid"
    assert result.metadata.raw_metadata["carousel_index"] == 2
    assert result.metadata.raw_metadata["carousel_total"] == 2


@patch("yt_dlp.YoutubeDL")
def test_instagram_login_restricted_error_guidance(mock_ydl_cls, tmp_path):
    """Test friendly error message with cookie guidance when encountering login wall."""
    extractor = InstagramExtractor()

    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
    mock_ydl.extract_info.side_effect = Exception(
        "HTTP Error 401: Login required to view this post"
    )

    with (
        patch.object(extractor, "_try_embed_fallback", return_value=None),
        pytest.raises(RuntimeError) as exc_info,
    ):
        extractor.extract_raw_materials(
            url="https://www.instagram.com/reel/Cxxxx123/",
            output_base_dir=tmp_path,
        )

    err_msg = str(exc_info.value)
    assert "cookies_browser" in err_msg
    assert "--cookies-from-browser" in err_msg
