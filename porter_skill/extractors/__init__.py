"""Platform extractors package."""

from porter_skill.extractors.base import (
    BasePlatformExtractor,
    RawMaterialResult,
    VideoMetadata,
    get_extractor,
    register_extractor,
    sanitize_filename,
)
from porter_skill.extractors.inspector import (
    InspectionResult,
    identify_platform,
    inspect_url,
    resolve_and_clean_url,
)
from porter_skill.extractors.x import XExtractor
from porter_skill.extractors.youtube import YouTubeExtractor

__all__ = [
    "BasePlatformExtractor",
    "InspectionResult",
    "RawMaterialResult",
    "VideoMetadata",
    "XExtractor",
    "YouTubeExtractor",
    "get_extractor",
    "identify_platform",
    "inspect_url",
    "register_extractor",
    "resolve_and_clean_url",
    "sanitize_filename",
]
