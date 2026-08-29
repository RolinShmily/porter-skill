"""FFmpeg fast hardsub synthesis module for dual-version release."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from porter_skill.config import FFmpegConfig, PorterConfig, get_default_config
from porter_skill.synthesizer.utils import escape_ffmpeg_filter_path


@dataclass
class DualReleaseResult:
    """Output structure of Phase 4 video synthesis."""

    video_bilingual: Path | None = None
    video_zh: Path | None = None


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
) -> Path:
    """
    Burn ASS or SRT subtitle into video with -c:a copy and faststart.
    """
    _ensure_fontconfig_configured()
    if ffmpeg_config is None:
        ffmpeg_config = FFmpegConfig()

    video_input = Path(video_input)
    subtitle_path = Path(subtitle_path)
    video_output = Path(video_output)
    video_output.parent.mkdir(parents=True, exist_ok=True)

    escaped_sub = escape_ffmpeg_filter_path(subtitle_path)
    font_dir = get_font_dir()
    fontsdir_opt = f":fontsdir='{escape_ffmpeg_filter_path(font_dir)}'" if font_dir else ""

    is_ass = subtitle_path.suffix.lower() == ".ass"
    filter_expr = (
        f"ass='{escaped_sub}'{fontsdir_opt}"
        if is_ass
        else f"subtitles='{escaped_sub}'{fontsdir_opt}"
    )

    cmd = [
        ffmpeg_config.ffmpeg_path,
        "-y",
        "-i",
        str(video_input),
        "-vf",
        filter_expr,
        "-c:v",
        ffmpeg_config.video_codec,
        "-preset",
        ffmpeg_config.preset,
        "-crf",
        str(ffmpeg_config.crf),
        "-pix_fmt",
        ffmpeg_config.pixel_format,
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(video_output),
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
                ffmpeg_config.video_codec,
                "-preset",
                ffmpeg_config.preset,
                "-crf",
                str(ffmpeg_config.crf),
                "-pix_fmt",
                ffmpeg_config.pixel_format,
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                str(video_output),
            ]
            proc_fb = subprocess.run(cmd_fallback, capture_output=True, text=True, check=False)
            if proc_fb.returncode == 0 and video_output.exists():
                return video_output

        raise RuntimeError(
            f"FFmpeg hardsub burning failed for {subtitle_path.name}:\n{proc.stderr}"
        )

    return video_output


def burn_dual_release(
    raw_video: Path,
    bilingual_ass: Path,
    zh_ass: Path,
    cooked_dir: Path,
    config: PorterConfig | None = None,
    only_bilingual: bool = False,
    only_zh: bool = False,
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
        )
        result.video_zh = zh_output

    return result
