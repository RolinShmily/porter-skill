"""Pre-flight Link Inspector and URL Expansion Module."""

import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
import yt_dlp

from porter_skill.extractors.base import sanitize_filename

# Common tracking / noise query parameters to strip
STRIP_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "igshid",
    "ref_src",
    "ref_url",
    "s",  # Twitter/X share tracking param
    "t",  # Twitter/X share tracking param (unless on youtube)
}


@dataclass
class InspectionResult:
    """Structured pre-flight result from inspecting a media link."""

    input_url: str
    canonical_url: str
    platform: str
    is_valid: bool
    has_video: bool
    video_id: str | None = None
    title: str | None = None
    safe_title: str | None = None
    uploader: str | None = None
    channel: str | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    is_vertical: bool = False
    has_subtitles: bool = False
    thumbnail_url: str | None = None
    error_message: str | None = None
    raw_info: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert inspection result to dictionary."""
        data = asdict(self)
        if "raw_info" in data and len(str(data["raw_info"])) > 500:
            data["raw_info"] = {"id": self.video_id, "title": self.title}
        return data

    def format_summary(self) -> str:
        """Format human-readable pre-flight inspection report."""
        if not self.is_valid:
            return (
                f"✗ [Pre-flight Check Failed]\n"
                f"  URL: {self.input_url}\n"
                f"  Error: {self.error_message or 'Unknown error'}"
            )

        dur_str = (
            f"{int(self.duration_seconds // 60):02d}:{int(self.duration_seconds % 60):02d} ({self.duration_seconds:.0f}s)"
            if self.duration_seconds
            else "Unknown"
        )
        res_str = (
            f"{self.width}x{self.height} ({'Vertical 9:16' if self.is_vertical else 'Horizontal 16:9'})"
            if self.width and self.height
            else "Unknown"
        )

        lines = [
            "=================================================================",
            "                 PORTER-SKILL LINK PRE-FLIGHT PROBE              ",
            "=================================================================",
            f" [OK] Platform:      {self.platform.upper()}",
            f"      Canonical URL: {self.canonical_url}",
            f"      Video ID:      {self.video_id or 'N/A'}",
            f"      Title:         {self.title or 'N/A'}",
            f"      Author:        {self.uploader or self.channel or 'N/A'}",
            f"      Duration:      {dur_str}",
            f"      Resolution:    {res_str}",
            f"      Subtitles:     {'Available' if self.has_subtitles else 'None (ASR will be used)'}",
            "=================================================================",
        ]
        return "\n".join(lines)


def resolve_and_clean_url(url: str, timeout: float = 8.0) -> str:
    """
    Expand shortened URLs (t.co, bit.ly, etc.) via HTTP redirects and strip tracking query params.
    """
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    # Expand shortened domains or redirect links
    shortened_hosts = {"t.co", "bit.ly", "tinyurl.com", "is.gd", "buff.ly", "ow.ly", "ift.tt"}
    if hostname in shortened_hosts or hostname.endswith(".t.co"):
        try:
            resp = requests.head(
                url,
                allow_redirects=True,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            if resp.url:
                url = resp.url
                parsed = urlparse(url)
                hostname = (parsed.hostname or "").lower()
        except Exception:  # noqa: BLE001, S110
            pass

    # Clean tracking query parameters
    query_dict = parse_qs(parsed.query, keep_blank_values=True)
    cleaned_query: dict[str, list[str]] = {}

    is_youtube = "youtube.com" in hostname or "youtu.be" in hostname
    for k, v in query_dict.items():
        if k in STRIP_QUERY_PARAMS:
            # Preserve timestamp param 't' for YouTube
            if is_youtube and k == "t":
                cleaned_query[k] = v
            continue
        cleaned_query[k] = v

    new_query_str = urlencode(cleaned_query, doseq=True)
    cleaned_url = urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query_str, parsed.fragment)
    )
    return cleaned_url


def identify_platform(url: str) -> str:
    """Identify destination platform from URL."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "x.com" in host or "twitter.com" in host or "t.co" in host:
        return "x"
    return "generic"


def inspect_url(
    url: str,
    cookies_file: str | None = None,
    cookies_browser: str | None = None,
    timeout: float = 15.0,
) -> InspectionResult:
    """
    Perform 1-second pre-flight inspection on media URL.
    Validates link existence, extracts lightweight metadata, and detects video orientation.
    """
    canonical = resolve_and_clean_url(url, timeout=timeout)
    platform = identify_platform(canonical)

    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "remote_components": {"ejs": "github"},
        "extractor_args": {
            "youtube": {
                "player_client": ["web_embedded", "web", "mweb", "android_vr", "ios", "android"]
            }
        },
    }
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file
    if cookies_browser:
        ydl_opts["cookiesfrombrowser"] = (cookies_browser,)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(canonical, download=False)
    except Exception as e:  # noqa: BLE001
        err_msg = str(e)
        if "login" in err_msg.lower() or "authentication" in err_msg.lower():
            err_msg = "Authentication required. Please configure cookies_browser or --cookies."
        elif "429" in err_msg:
            err_msg = "Rate limit (HTTP 429) encountered. Please use --cookies-from-browser."
        elif "not found" in err_msg.lower() or "deleted" in err_msg.lower() or "404" in err_msg:
            err_msg = "Resource not found or deleted (404)."

        return InspectionResult(
            input_url=url,
            canonical_url=canonical,
            platform=platform,
            is_valid=False,
            has_video=False,
            error_message=err_msg,
        )

    if not info:
        return InspectionResult(
            input_url=url,
            canonical_url=canonical,
            platform=platform,
            is_valid=False,
            has_video=False,
            error_message="Could not extract metadata from URL.",
        )

    # Check if video formats exist
    formats = info.get("formats") or []
    has_video_stream = False
    width = info.get("width")
    height = info.get("height")

    # If top-level width/height missing, find best format
    for f in formats:
        if f.get("vcodec") and f.get("vcodec") != "none":
            has_video_stream = True
            if not width and f.get("width"):
                width = f.get("width")
            if not height and f.get("height"):
                height = f.get("height")

    # If direct duration / url exists, consider valid
    if info.get("duration") or info.get("url"):
        has_video_stream = True

    if not has_video_stream and not formats:
        return InspectionResult(
            input_url=url,
            canonical_url=canonical,
            platform=platform,
            is_valid=False,
            has_video=False,
            error_message="The provided post/link does not contain any video streams.",
            raw_info=info,
        )

    # Title extraction & cleaning
    raw_title = info.get("title") or info.get("description") or "video"
    # Clean leading tweet text if on X/Twitter
    if platform == "x":
        lines = [line.strip() for line in raw_title.splitlines() if line.strip()]
        first_line = lines[0] if lines else "video"
        # Remove trailing URLs
        first_line = re.sub(r"https?://\S+", "", first_line).strip()
        raw_title = first_line or "Tweet_video"

    safe_title = sanitize_filename(raw_title, max_length=60)
    video_id = str(info.get("id") or "unknown_id")
    is_vertical = bool(width and height and height > width)

    subtitles = info.get("subtitles") or {}
    auto_captions = info.get("automatic_captions") or {}
    has_subs = bool(subtitles or auto_captions)

    return InspectionResult(
        input_url=url,
        canonical_url=canonical,
        platform=platform,
        is_valid=True,
        has_video=True,
        video_id=video_id,
        title=raw_title,
        safe_title=safe_title,
        uploader=info.get("uploader") or info.get("channel"),
        channel=info.get("channel") or info.get("uploader"),
        duration_seconds=float(info.get("duration") or 0.0),
        width=width,
        height=height,
        is_vertical=is_vertical,
        has_subtitles=has_subs,
        thumbnail_url=info.get("thumbnail"),
        raw_info=info,
    )
