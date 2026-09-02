"""FFmpeg fast hardsub synthesis module for dual-version release."""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from porter_skill.config import FFmpegConfig, PorterConfig, get_default_config
from porter_skill.env_check import detect_hardware_profile
from porter_skill.synthesizer.utils import escape_ffmpeg_filter_path


@dataclass
class DualReleaseResult:
    """Output structure of Phase 4 video synthesis."""

    video_bilingual: Path | None = None
    video_zh: Path | None = None


def is_valid_video_file(video_path: Path, ffprobe_path: str = "ffprobe") -> bool:
    """
    Check if a video file exists, is non-empty, and has valid moov atom / duration via ffprobe.
    Prevents half-written / interrupted files from being mistaken as completed.
    """
    path = Path(video_path)
    if not path.is_file() or path.stat().st_size < 1024:
        return False
    resolved_ffprobe = shutil.which(ffprobe_path) or ffprobe_path
    try:
        res = subprocess.run(
            [
                resolved_ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if res.returncode == 0 and res.stdout.strip():
            duration = float(res.stdout.strip())
            return duration > 0
    except Exception:  # noqa: BLE001, S110
        pass
    return False


def get_video_dimensions(video_path: Path, ffprobe_path: str = "ffprobe") -> tuple[int, int]:
    """Probe exact pixel width and height of a video file using ffprobe."""
    path = Path(video_path)
    if not path.is_file() or path.stat().st_size < 1024:
        return (1920, 1080)
    resolved_ffprobe = shutil.which(ffprobe_path) or ffprobe_path
    try:
        res = subprocess.run(
            [
                resolved_ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=x:p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split("x")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                return (int(parts[0]), int(parts[1]))
    except Exception:  # noqa: BLE001, S110
        pass
    return (1920, 1080)


def _ensure_fontconfig_configured() -> None:
    """Ensure fontconfig in user environment includes system / WSL font directories."""
    config_file = Path.home() / ".config" / "fontconfig" / "fonts.conf"
    if not config_file.exists():
        try:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            xml = """<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir>/mnt/c/Windows/Fonts</dir>
  <dir>~/.local/share/fonts</dir>
  <dir>~/.fonts</dir>
  <dir>/usr/share/fonts</dir>
</fontconfig>
"""
            config_file.write_text(xml, encoding="utf-8")
            subprocess.run(["fc-cache", "-f"], capture_output=True, text=True, check=False)
        except Exception:  # noqa: BLE001, S110
            pass


def get_font_dir() -> Path | None:
    """Find system font directory for FFmpeg fontsdir parameter."""
    candidate_dirs = [
        Path("/mnt/c/Windows/Fonts"),
        Path("C:/Windows/Fonts"),
        Path("/usr/share/fonts"),
        Path("/Library/Fonts"),
        Path.home() / ".local" / "share" / "fonts",
        Path.home() / ".fonts",
    ]
    for p in candidate_dirs:
        if p.is_dir():
            return p
    return None


def burn_hardsub(
    video_input: Path,
    subtitle_path: Path,
    video_output: Path,
    ffmpeg_config: FFmpegConfig | None = None,
    overwrite: bool = True,
) -> Path:
    """
    Burn ASS or SRT subtitle into video with -c:a copy and faststart.
    Employs atomic temporary file writes to prevent corrupted outputs on interruptions.
    """
    _ensure_fontconfig_configured()
    if ffmpeg_config is None:
        ffmpeg_config = FFmpegConfig()

    video_input = Path(video_input)
    subtitle_path = Path(subtitle_path)
    video_output = Path(video_output)
    video_output.parent.mkdir(parents=True, exist_ok=True)

    # Check if target file already exists and is completely valid and fresher than inputs when overwrite=False
    if (
        not overwrite
        and video_output.is_file()
        and is_valid_video_file(video_output, ffmpeg_config.ffprobe_path)
    ):
        out_mtime = video_output.stat().st_mtime
        in_mtime = video_input.stat().st_mtime if video_input.is_file() else 0.0
        sub_mtime = subtitle_path.stat().st_mtime if subtitle_path.is_file() else 0.0
        if out_mtime >= in_mtime and out_mtime >= sub_mtime:
            print(f"  ✓ Reusing existing up-to-date release video: {video_output.name}")
            return video_output

    # Use atomic temporary destination
    temp_output = video_output.with_name(f".tmp_{video_output.name}")
    if temp_output.exists():
        temp_output.unlink(missing_ok=True)

    escaped_sub = escape_ffmpeg_filter_path(subtitle_path)
    is_ass = subtitle_path.suffix.lower() == ".ass"
    filter_expr = f"ass='{escaped_sub}'" if is_ass else f"subtitles='{escaped_sub}'"

    # Determine adaptive codec and tuning options
    codec = ffmpeg_config.video_codec
    preset = ffmpeg_config.preset
    crf = ffmpeg_config.crf
    pix_fmt = ffmpeg_config.pixel_format

    if ffmpeg_config.auto_tune and codec == "libx264":
        profile = detect_hardware_profile(ffmpeg_config.ffmpeg_path)
        preset = profile.recommended_x264_preset
        crf = profile.recommended_x264_crf

    cmd = [
        ffmpeg_config.ffmpeg_path,
        "-y",
        "-i",
        str(video_input),
        "-vf",
        filter_expr,
        "-c:v",
        codec,
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        pix_fmt,
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(temp_output),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        # If ASS filter failed, fallback to subtitles filter if srt exists in same dir
        fallback_srt = subtitle_path.with_suffix(".srt")
        if is_ass and fallback_srt.exists():
            escaped_srt = escape_ffmpeg_filter_path(fallback_srt)
            cmd_fallback = [
                ffmpeg_config.ffmpeg_path,
                "-y",
                "-i",
                str(video_input),
                "-vf",
                f"subtitles='{escaped_srt}'",
                "-c:v",
                codec,
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-pix_fmt",
                pix_fmt,
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                str(temp_output),
            ]
            proc_fb = subprocess.run(cmd_fallback, capture_output=True, text=True, check=False)
            if proc_fb.returncode == 0 and temp_output.exists():
                temp_output.replace(video_output)
                return video_output

        # Clean up temporary corrupt file
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)

        raise RuntimeError(
            f"FFmpeg hardsub burning failed for {subtitle_path.name}:\n{proc.stderr}"
        )

    # Validate output file integrity before atomic replacement
    if temp_output.exists():
        temp_output.replace(video_output)
        return video_output

    raise RuntimeError(f"FFmpeg completed but output file not found: {video_output.name}")


def burn_dual_release(
    raw_video: Path,
    bilingual_ass: Path,
    zh_ass: Path,
    cooked_dir: Path,
    config: PorterConfig | None = None,
    only_bilingual: bool = False,
    only_zh: bool = False,
    overwrite: bool = True,
) -> DualReleaseResult:
    """
    Synthesize dual-version cooked release videos:
    - cooked/video_bilingual.mp4 (Bilingual hardsub)
    - cooked/video_zh.mp4 (Pure Chinese hardsub)
    """
    if config is None:
        config = get_default_config()

    cooked_dir = Path(cooked_dir)
    cooked_dir.mkdir(parents=True, exist_ok=True)

    result = DualReleaseResult()

    # 1. Burn bilingual hardsub video
    if not only_zh:
        bilingual_output = cooked_dir / "video_bilingual.mp4"
        burn_hardsub(
            video_input=raw_video,
            subtitle_path=bilingual_ass,
            video_output=bilingual_output,
            ffmpeg_config=config.ffmpeg,
            overwrite=overwrite,
        )
        result.video_bilingual = bilingual_output

    # 2. Burn pure Chinese hardsub video
    if not only_bilingual:
        zh_output = cooked_dir / "video_zh.mp4"
        burn_hardsub(
            video_input=raw_video,
            subtitle_path=zh_ass,
            video_output=zh_output,
            ffmpeg_config=config.ffmpeg,
            overwrite=overwrite,
        )
        result.video_zh = zh_output

    return result
