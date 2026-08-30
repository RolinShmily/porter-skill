"""Base classes and factory for platform media extractors."""

import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class VideoMetadata:
    """Standardized metadata structure for downloaded videos."""

    id: str
    title: str
    safe_title: str
    url: str
    platform: str = "youtube"
    uploader: str | None = None
    channel: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    is_vertical: bool = False
    description: str | None = None
    thumbnail_url: str | None = None
    has_official_subtitle: bool = False
    official_subtitle_lang: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to dictionary (excluding huge raw_metadata if needed or formatted)."""
        data = asdict(self)
        return data


@dataclass
class RawMaterialResult:
    """Output structure of Phase 1 material extraction in raw/ directory."""

    task_dir: Path
    raw_dir: Path
    video_path: Path
    audio_path: Path
    cover_path: Path | None = None
    subtitle_path: Path | None = None
    subtitle_zh_path: Path | None = None
    metadata_path: Path | None = None
    metadata: VideoMetadata | None = None


def sanitize_filename(name: str, max_length: int = 80) -> str:
    """
    Sanitize string for safe cross-platform folder/filename usage (Windows & Linux).
    Removes invalid characters: \\ / : * ? " < > | and control chars.
    """
    # Replace invalid chars with underscore
    sanitized = re.sub(r'[\\/*?:"<>|\r\n\t]', "_", name)
    # Replace multiple consecutive spaces or underscores
    sanitized = re.sub(r"[\s_]+", "_", sanitized).strip("._ ")
    if not sanitized:
        sanitized = "video"
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip("._ ")
    return sanitized


class BasePlatformExtractor(ABC):
    """Abstract base class for all streaming platform extractors."""

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Check if this extractor handles the given URL."""

    @abstractmethod
    def extract_raw_materials(
        self,
        url: str,
        output_base_dir: Path,
        ffmpeg_path: str = "ffmpeg",
        cookies_file: str | None = None,
        cookies_browser: str | None = None,
    ) -> RawMaterialResult:
        """
        Download and standardize raw materials into <output_base_dir>/<video_id>_<safe_title>/raw/:
        - raw/video.mp4 (H.264 + AAC + faststart)
        - raw/audio.wav (16kHz 16bit mono WAV)
        - raw/cover.jpg (High-res thumbnail)
        - raw/subtitle.srt (Official human subtitle if available)
        - raw/metadata.json (Video metadata)
        """


_EXTRACTORS: list[type[BasePlatformExtractor]] = []


def register_extractor(cls: type[BasePlatformExtractor]) -> type[BasePlatformExtractor]:
    """Decorator to register a platform extractor."""
    if cls not in _EXTRACTORS:
        _EXTRACTORS.append(cls)
    return cls


def get_extractor(url: str) -> BasePlatformExtractor:
    """Factory function to resolve the appropriate platform extractor."""
    for extractor_cls in _EXTRACTORS:
        instance = extractor_cls()
        if instance.can_handle(url):
            return instance
    raise ValueError(
        f"Unsupported URL platform: '{url}'. "
        f"v1 supports YouTube URLs (e.g. https://www.youtube.com/watch?v=..., https://youtu.be/...)"
    )
