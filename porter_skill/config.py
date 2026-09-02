"""Configuration management for porter-skill."""

import json
import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """LLM configuration for subtitle optimization and translation."""

    api_key: str | None = None
    api_base: str | None = None
    model: str = "deepseek-chat"


class ASRConfig(BaseModel):
    """ASR (Speech-to-Text) configuration."""

    engine: str = "whisper-api"  # whisper-api, bijian, jianying, whisper-cpp
    language: str = "auto"
    whisper_api_key: str | None = None
    whisper_api_base: str | None = None
    whisper_model: str = "whisper-1"
    audio_denoise: bool = True


class FFmpegConfig(BaseModel):
    """FFmpeg encoding parameters."""

    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    video_codec: str = "libx264"
    preset: str = "veryfast"
    crf: int = 18
    pixel_format: str = "yuv420p"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    audio_sample_rate: int = 44100
    wav_sample_rate: int = 16000
    auto_tune: bool = True


class SubtitleStyleConfig(BaseModel):
    """ASS subtitle styling configuration."""

    zh_font: str = "Microsoft YaHei"
    en_font: str = "Arial"
    zh_font_size: int = 52
    en_font_size: int = 34
    zh_primary_color: str = "&H00FFFFFF"  # White
    en_primary_color: str = "&H0000FFFF"  # Yellow / Off-white
    outline_color: str = "&H00000000"  # Black
    outline_width: float = 3.5
    shadow: float = 1.5
    margin_v: int = 35
    margin_l: int = 20
    margin_r: int = 20
    bilingual_zh_margin_v: int = 90
    bilingual_en_margin_v: int = 35
    fade_in_ms: int = 120
    fade_out_ms: int = 120


class PorterConfig(BaseModel):
    """Global configuration for porter-skill."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    ffmpeg: FFmpegConfig = Field(default_factory=FFmpegConfig)
    style: SubtitleStyleConfig = Field(default_factory=SubtitleStyleConfig)
    output_dir: Path = Field(default_factory=lambda: Path("./porter_output"))
    cookies_file: str | None = None
    cookies_browser: str | None = None
    config_source: str | None = None


def find_candidate_config_paths() -> list[Path]:
    """Return prioritized list of potential configuration file paths."""
    skill_root = Path(__file__).resolve().parent.parent
    candidates: list[Path] = [
        # 1. Current working directory
        Path.cwd() / "config.json",
        Path.cwd() / "porter_config.json",
        # 2. Skill cloned root directory
        skill_root / "config.json",
        # 3. Installed Skill directory
        Path.home() / ".pi" / "agent" / "skills" / "porter-skill" / "config.json",
        # 4. User global config directory
        Path.home() / ".config" / "porter-skill" / "config.json",
        Path.home() / ".config" / "videocaptioner" / "config.toml",
    ]
    return candidates


def find_active_config_path() -> Path | None:
    """Find the highest priority existing configuration file."""
    for p in find_candidate_config_paths():
        if p.is_file():
            return p
    return None


def get_default_user_config_path() -> Path:
    """Return default user config file destination for saving settings."""
    skill_root = Path(__file__).resolve().parent.parent
    local_config = skill_root / "config.json"
    if local_config.parent.is_dir() and (skill_root / "SKILL.md").is_file():
        return local_config

    skill_config = Path.home() / ".pi" / "agent" / "skills" / "porter-skill" / "config.json"
    if skill_config.parent.is_dir():
        return skill_config
    return Path.home() / ".config" / "porter-skill" / "config.json"


def load_file_config(config_path: Path) -> dict[str, Any]:
    """Load configuration from a JSON or TOML file."""
    if not config_path.is_file():
        return {}
    try:
        if config_path.suffix.lower() == ".toml":
            with open(config_path, "rb") as f:
                toml_data = tomllib.load(f)
                return dict(toml_data)
        with open(config_path, encoding="utf-8") as f:
            json_data = json.load(f)
            if isinstance(json_data, dict):
                return dict(json_data)
            return {}
    except Exception:  # noqa: BLE001
        return {}


def load_videocaptioner_config() -> dict[str, Any]:
    """Load configuration from videocaptioner's config.toml if it exists."""
    config_path = Path.home() / ".config" / "videocaptioner" / "config.toml"
    return load_file_config(config_path)


def get_default_config(config_file: str | Path | None = None) -> PorterConfig:
    """
    Load configuration with cascading priorities:
    1. Explicit config_file (JSON / TOML);
    2. Auto-discovered config.json (current dir -> skill dir -> ~/.config/video-porter);
    3. Environment variables (OPENAI_API_KEY, etc.);
    4. VideoCaptioner legacy config.toml;
    5. Built-in defaults.
    """
    active_path: Path | None = None
    file_cfg: dict[str, Any] = {}

    if config_file:
        p = Path(config_file)
        if p.is_file():
            active_path = p
            file_cfg = load_file_config(p)
    else:
        active_path = find_active_config_path()
        if active_path:
            file_cfg = load_file_config(active_path)

    # Legacy videocaptioner fallback
    vc_config = load_videocaptioner_config()
    vc_llm = vc_config.get("llm", {})
    vc_transcribe = vc_config.get("transcribe", {})

    file_llm = file_cfg.get("llm", {})
    file_asr = file_cfg.get("asr", {})
    file_ffmpeg = file_cfg.get("ffmpeg", {})
    file_style = file_cfg.get("style", {})

    # Resolve LLM
    api_key = os.environ.get("OPENAI_API_KEY") or file_llm.get("api_key") or vc_llm.get("api_key")
    api_base = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or file_llm.get("api_base")
        or vc_llm.get("api_base")
    )
    model = (
        os.environ.get("OPENAI_MODEL")
        or file_llm.get("model")
        or vc_llm.get("model")
        or "deepseek-chat"
    )

    # Resolve ASR
    asr_engine = (
        os.environ.get("PORTER_ASR_ENGINE")
        or file_asr.get("engine")
        or vc_transcribe.get("asr")
        or "whisper-api"
    )
    whisper_api_key = (
        os.environ.get("WHISPER_API_KEY") or file_asr.get("whisper_api_key") or api_key
    )
    whisper_api_base = (
        os.environ.get("WHISPER_API_BASE") or file_asr.get("whisper_api_base") or api_base
    )
    whisper_model = os.environ.get("WHISPER_MODEL") or file_asr.get("whisper_model") or "whisper-1"

    return PorterConfig(
        llm=LLMConfig(
            api_key=api_key,
            api_base=api_base,
            model=model,
        ),
        asr=ASRConfig(
            engine=asr_engine,
            language=file_asr.get("language", "auto"),
            whisper_api_key=whisper_api_key,
            whisper_api_base=whisper_api_base,
            whisper_model=whisper_model,
        ),
        ffmpeg=FFmpegConfig(**file_ffmpeg) if file_ffmpeg else FFmpegConfig(),
        style=SubtitleStyleConfig(**file_style) if file_style else SubtitleStyleConfig(),
        cookies_file=file_cfg.get("cookies_file") or file_cfg.get("cookies"),
        cookies_browser=file_cfg.get("cookies_browser") or file_cfg.get("cookies_from_browser"),
        config_source=str(active_path) if active_path else "Built-in Defaults / Environment",
    )


def save_config_key(key_path: str, value: Any, target_file: Path | None = None) -> Path:
    """
    Set a configuration key (e.g. 'llm.api_key' or 'llm.api_base') in config.json.
    Creates parent directories and file if not exist.
    """
    dest = target_file or find_active_config_path() or get_default_user_config_path()
    dest.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {}
    if dest.is_file():
        data = load_file_config(dest)

    parts = key_path.split(".")
    curr = data
    for part in parts[:-1]:
        if part not in curr or not isinstance(curr[part], dict):
            curr[part] = {}
        curr = curr[part]
    curr[parts[-1]] = value

    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return dest
