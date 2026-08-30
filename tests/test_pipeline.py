"""Tests for pipeline coordinator and CLI."""

import subprocess
from unittest.mock import MagicMock, patch

from porter_skill.cli import main
from porter_skill.extractors.base import RawMaterialResult, VideoMetadata
from porter_skill.extractors.inspector import InspectionResult
from porter_skill.pipeline.runner import run_pipeline
from porter_skill.subtitle.controller import SubtitleResult
from porter_skill.subtitle.formatter import SubtitleItem


def test_pipeline_orchestration(tmp_path):
    """Test full pipeline execution with mocked extractor and subtitle steps."""
    task_dir = tmp_path / "vid123_Test_Video"
    raw_dir = task_dir / "raw"
    cooked_dir = task_dir / "cooked"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cooked_dir.mkdir(parents=True, exist_ok=True)

    # Generate synthetic raw video with ffmpeg
    raw_video = raw_dir / "video.mp4"
    raw_audio = raw_dir / "audio.wav"
    raw_cover = raw_dir / "cover.jpg"
    raw_meta = raw_dir / "metadata.json"

    subprocess.run(
        [
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
            str(raw_video),
        ],
        check=True,
        capture_output=True,
    )

    raw_audio.write_bytes(b"dummy wav")
    raw_cover.write_bytes(b"dummy jpg")
    raw_meta.write_text("{}", encoding="utf-8")

    mock_raw_result = RawMaterialResult(
        task_dir=task_dir,
        raw_dir=raw_dir,
        video_path=raw_video,
        audio_path=raw_audio,
        cover_path=raw_cover,
        metadata_path=raw_meta,
        metadata=VideoMetadata(
            id="vid123",
            title="Test Video",
            safe_title="Test_Video",
            url="https://www.youtube.com/watch?v=vid123",
            has_official_subtitle=True,
        ),
    )

    # Create dummy subtitle files in cooked_dir
    sub_bi_srt = cooked_dir / "subtitle_bilingual.srt"
    sub_bi_ass = cooked_dir / "subtitle_bilingual.ass"
    sub_zh_srt = cooked_dir / "subtitle_zh.srt"
    sub_zh_ass = cooked_dir / "subtitle_zh.ass"

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
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hello
"""
    sub_bi_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    sub_bi_ass.write_text(ass_content, encoding="utf-8")
    sub_zh_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    sub_zh_ass.write_text(ass_content, encoding="utf-8")

    mock_sub_result = SubtitleResult(
        subtitle_bilingual_srt=sub_bi_srt,
        subtitle_bilingual_ass=sub_bi_ass,
        subtitle_zh_srt=sub_zh_srt,
        subtitle_zh_ass=sub_zh_ass,
        items=[SubtitleItem(1, 0, 1000, "Hello", "你好")],
    )

    with (
        patch("porter_skill.pipeline.runner.inspect_url") as mock_inspect,
        patch("porter_skill.pipeline.runner.get_extractor") as mock_get_ext,
        patch("porter_skill.pipeline.runner.generate_subtitles") as mock_gen_sub,
    ):
        mock_inspect.return_value = InspectionResult(
            input_url="https://www.youtube.com/watch?v=vid123",
            canonical_url="https://www.youtube.com/watch?v=vid123",
            platform="youtube",
            is_valid=True,
            has_video=True,
            video_id="vid123",
            title="Test Video",
        )
        mock_extractor = MagicMock()
        mock_extractor.extract_raw_materials.return_value = mock_raw_result
        mock_get_ext.return_value = mock_extractor
        mock_gen_sub.return_value = mock_sub_result

        result = run_pipeline(
            url="https://www.youtube.com/watch?v=vid123",
            output_dir=tmp_path,
        )

        assert result.success is True
        assert result.task_dir == task_dir
        assert result.synthesis is not None
        assert result.synthesis.video_bilingual is not None
        assert result.synthesis.video_bilingual.exists()
        assert result.synthesis.video_zh is not None
        assert result.synthesis.video_zh.exists()


def test_cli_doctor(capsys):
    """Test CLI --doctor invocation."""
    with patch("sys.argv", ["porter", "--doctor"]):
        exit_code = main()
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "PORTER-SKILL DOCTOR" in captured.out


def test_cli_no_args(capsys):
    """Test CLI without arguments shows help."""
    with patch("sys.argv", ["porter"]):
        exit_code = main()
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error: Please provide a video URL or run with --doctor" in captured.out


def test_cli_inspect():
    """Test CLI -i / --inspect flag invocation."""
    with (
        patch("sys.argv", ["porter", "https://x.com/user/status/123", "--inspect"]),
        patch("porter_skill.cli.inspect_url") as mock_insp,
    ):
        mock_insp.return_value = InspectionResult(
            input_url="https://x.com/user/status/123",
            canonical_url="https://x.com/user/status/123",
            platform="x",
            is_valid=True,
            has_video=True,
            video_id="123",
            title="Test Post",
        )
        exit_code = main()
        assert exit_code == 0
