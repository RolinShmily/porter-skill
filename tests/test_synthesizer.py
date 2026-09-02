"""Tests for FFmpeg subtitle synthesis and path escaping."""

import subprocess

import pytest

from porter_skill.config import PorterConfig
from porter_skill.synthesizer.burn import (
    burn_dual_release,
    burn_hardsub,
    get_video_dimensions,
    is_valid_video_file,
)
from porter_skill.synthesizer.utils import escape_ffmpeg_filter_path


def test_escape_ffmpeg_filter_path():
    """Verify path escaping for FFmpeg filters across Windows and Linux path formats."""
    # Standard linux path
    p1 = "/home/user/output/video.ass"
    escaped1 = escape_ffmpeg_filter_path(p1)
    assert "\\:" in escaped1 or ":" not in escaped1
    assert "\\" not in escaped1.replace(r"\:", "")

    # Path with spaces and quotes
    p2 = "/tmp/my's [video]/sub.ass"
    escaped2 = escape_ffmpeg_filter_path(p2)
    assert r"\'" in escaped2
    assert r"\[" in escaped2
    assert r"\]" in escaped2

    # Windows-style simulated path with colon
    p3 = "C:/Users/user/sub.ass"
    escaped3 = escape_ffmpeg_filter_path(p3)
    assert r"\:" in escaped3


@pytest.fixture
def synthetic_video_and_sub(tmp_path):
    """Generate a minimal 1-second synthetic MP4 video and test ASS subtitle."""
    video_path = tmp_path / "test_video.mp4"
    ass_path = tmp_path / "test_sub.ass"
    srt_path = tmp_path / "test_sub.srt"

    # Create 1s synthetic MP4 with FFmpeg
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=1:size=320x240:rate=24",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-t",
        "1",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        str(video_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # Create ASS subtitle
    ass_content = """[Script Info]
Title: Test
ScriptType: v4.00+
PlayResX: 320
PlayResY: 240

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hello Test
"""
    ass_path.write_text(ass_content, encoding="utf-8")

    # Create SRT subtitle
    srt_content = """1
00:00:00,000 --> 00:00:01,000
Hello Test
"""
    srt_path.write_text(srt_content, encoding="utf-8")

    return video_path, ass_path, srt_path


def test_burn_hardsub_real_ffmpeg(synthetic_video_and_sub, tmp_path):
    """Test burning hard subtitles into real video using FFmpeg libass."""
    video_in, ass_sub, _ = synthetic_video_and_sub
    video_out = tmp_path / "output_burned.mp4"

    res = burn_hardsub(video_in, ass_sub, video_out)
    assert res.exists()
    assert res.stat().st_size > 0


def test_burn_hardsub_updates_existing_video(synthetic_video_and_sub, tmp_path):
    """Verify burn_hardsub properly updates video when file already exists."""
    video_in, ass_sub, _ = synthetic_video_and_sub
    video_out = tmp_path / "output_existing.mp4"

    # 1. Initial burn
    res1 = burn_hardsub(video_in, ass_sub, video_out)
    assert res1.exists()

    # 2. Modify subtitle content
    modified_ass = tmp_path / "modified_sub.ass"
    modified_ass.write_text(
        ass_sub.read_text(encoding="utf-8").replace("Hello Test", "Updated Subtitle Text"),
        encoding="utf-8",
    )

    # 3. Second burn with overwrite=True should re-burn and update video
    res2 = burn_hardsub(video_in, modified_ass, video_out, overwrite=True)
    assert res2.exists()
    assert res2.stat().st_size > 0


def test_burn_dual_release(synthetic_video_and_sub, tmp_path):
    """Test burning dual release videos."""
    video_in, ass_sub, _ = synthetic_video_and_sub
    cooked_dir = tmp_path / "cooked"
    cooked_dir.mkdir(parents=True, exist_ok=True)

    bi_ass = cooked_dir / "subtitle_bilingual.ass"
    zh_ass = cooked_dir / "subtitle_zh.ass"
    bi_ass.write_text(ass_sub.read_text(encoding="utf-8"), encoding="utf-8")
    zh_ass.write_text(ass_sub.read_text(encoding="utf-8"), encoding="utf-8")

    res = burn_dual_release(
        raw_video=video_in,
        bilingual_ass=bi_ass,
        zh_ass=zh_ass,
        cooked_dir=cooked_dir,
        config=PorterConfig(),
    )

    assert res.video_bilingual is not None and res.video_bilingual.exists()
    assert res.video_zh is not None and res.video_zh.exists()
    assert res.video_bilingual.stat().st_size > 0
    assert res.video_zh.stat().st_size > 0


def test_is_valid_video_file(synthetic_video_and_sub, tmp_path):
    """Test video validity check with ffprobe."""
    video_in, _, _ = synthetic_video_and_sub
    assert is_valid_video_file(video_in) is True

    # Fake corrupted file
    bad_video = tmp_path / "corrupted.mp4"
    bad_video.write_bytes(b"corrupted binary header without moov atom")
    assert is_valid_video_file(bad_video) is False


def test_get_video_dimensions(synthetic_video_and_sub, tmp_path):
    """Test probing video dimensions with ffprobe."""
    video_in, _, _ = synthetic_video_and_sub
    width, height = get_video_dimensions(video_in)
    assert width == 320
    assert height == 240

    # Non-existent file fallback
    non_existent = tmp_path / "does_not_exist.mp4"
    w2, h2 = get_video_dimensions(non_existent)
    assert w2 == 1920
    assert h2 == 1080
