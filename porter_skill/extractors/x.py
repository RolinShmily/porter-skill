"""X (formerly Twitter) platform material extractor."""

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, ClassVar

import requests
import yt_dlp
from PIL import Image

from porter_skill.extractors.base import (
    BasePlatformExtractor,
    RawMaterialResult,
    VideoMetadata,
    register_extractor,
    sanitize_filename,
)
from porter_skill.extractors.inspector import resolve_and_clean_url
from porter_skill.synthesizer import get_video_dimensions, is_valid_video_file


@register_extractor
class XExtractor(BasePlatformExtractor):
    """Extractor for X (formerly Twitter) video content."""

    X_URL_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(
            r"^https?://(?:(?:www|m|mobile)\.)?(?:twitter|x)\.com/(?:(?:i/web|[^/]+)/status|statuses)/(?P<id>\d+)"
        ),
        re.compile(r"^https?://(?:(?:www|m|mobile)\.)?(?:twitter|x)\.com/i/status/(?P<id>\d+)"),
        re.compile(r"^https?://t\.co/(?P<id>[a-zA-Z0-9_-]+)"),
    ]

    def can_handle(self, url: str) -> bool:
        """Check if URL belongs to X / Twitter platform."""
        for pattern in self.X_URL_PATTERNS:
            if pattern.search(url):
                return True
        return "x.com" in url or "twitter.com" in url or "t.co" in url

    def _clean_tweet_title(
        self, tweet_text: str | None, uploader: str | None, status_id: str
    ) -> str:
        """Clean tweet text to derive a concise, safe video title."""
        if not tweet_text:
            return f"Tweet_by_{uploader or status_id}"

        # 1. Remove t.co or other URLs
        cleaned = re.sub(r"https?://\S+", "", tweet_text).strip()

        # 2. Extract first non-empty line
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        first_line = lines[0] if lines else ""

        # 3. Strip leading @ mentions or excess hashtags
        first_line = re.sub(r"^(@\w+\s*)+", "", first_line).strip()

        if not first_line:
            return f"Tweet_by_{uploader or status_id}"

        return first_line[:60].strip()

    def extract_raw_materials(
        self,
        url: str,
        output_base_dir: Path,
        ffmpeg_path: str = "ffmpeg",
        cookies_file: str | None = None,
        cookies_browser: str | None = None,
    ) -> RawMaterialResult:
        """Extract and standardize X / Twitter video materials into raw/ directory."""
        output_base_dir = Path(output_base_dir)
        output_base_dir.mkdir(parents=True, exist_ok=True)

        canonical_url = resolve_and_clean_url(url)

        # 1. Fetch metadata using yt-dlp
        ydl_opts_info: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "remote_components": {"ejs": "github"},
        }
        if cookies_file:
            ydl_opts_info["cookiefile"] = cookies_file
        if cookies_browser:
            ydl_opts_info["cookiesfrombrowser"] = (cookies_browser,)

        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            try:
                info = ydl.extract_info(canonical_url, download=False)
            except Exception as e:
                err_str = str(e)
                if "login" in err_str.lower() or "401" in err_str or "429" in err_str:
                    raise RuntimeError(
                        f"X platform access restricted for {url}: {err_str}\n"
                        "Tip: configure cookies_browser: 'chrome' in config.json or use --cookies-from-browser chrome."
                    ) from e
                raise RuntimeError(f"Failed to fetch metadata from X URL {url}: {err_str}") from e

        if info is None:
            raise RuntimeError(f"Failed to fetch metadata from X URL: {canonical_url}")

        status_id = str(info.get("id", "unknown_id"))
        uploader = info.get("uploader") or info.get("channel") or info.get("uploader_id")
        raw_text = str(info.get("description") or info.get("title") or "")
        cleaned_title = self._clean_tweet_title(raw_text, uploader, status_id)
        safe_title = sanitize_filename(cleaned_title, max_length=50)

        folder_name = f"{status_id}_{safe_title}"
        task_dir = output_base_dir / folder_name
        raw_dir = task_dir / "raw"
        cooked_dir = task_dir / "cooked"
        temp_dir = task_dir / ".tmp"

        raw_dir.mkdir(parents=True, exist_ok=True)
        cooked_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        width = info.get("width")
        height = info.get("height")
        is_vertical = bool(width and height and height > width)

        metadata = VideoMetadata(
            id=status_id,
            title=cleaned_title,
            safe_title=safe_title,
            url=canonical_url,
            platform="x",
            uploader=uploader,
            channel=info.get("channel"),
            duration=info.get("duration"),
            width=width,
            height=height,
            is_vertical=is_vertical,
            description=raw_text,
            thumbnail_url=info.get("thumbnail"),
            has_official_subtitle=bool(info.get("subtitles")),
            raw_metadata={
                "id": status_id,
                "title": cleaned_title,
                "full_text": raw_text,
                "uploader": uploader,
                "uploader_id": info.get("uploader_id"),
                "duration": info.get("duration"),
                "width": width,
                "height": height,
                "like_count": info.get("like_count"),
                "repost_count": info.get("repost_count"),
                "view_count": info.get("view_count"),
            },
        )

        # Resumption Check: If raw materials already exist and are valid, reuse directly
        standard_video_path = raw_dir / "video.mp4"
        standard_audio_path = raw_dir / "audio.wav"
        ffprobe_path = shutil.which("ffprobe") or "ffprobe"

        already_extracted = (
            standard_video_path.is_file()
            and standard_video_path.stat().st_size > 1024
            and standard_audio_path.is_file()
            and standard_audio_path.stat().st_size > 1024
        )

        if not already_extracted:
            # Check if temporary download already exists and is valid from prior run
            downloaded_video: Path | None = None
            for f in temp_dir.glob("download.*"):
                if f.suffix.lower() in [
                    ".mkv",
                    ".mp4",
                    ".webm",
                    ".ts",
                    ".flv",
                    ".mov",
                ] and is_valid_video_file(f, ffprobe_path):
                    downloaded_video = f
                    print(f"  ✓ Reusing existing valid temporary download: {downloaded_video.name}")
                    break

            if not downloaded_video:
                raw_download_template = str(temp_dir / "download.%(ext)s")
                format_spec = (
                    "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
                    "bestvideo[height<=1080]+bestaudio/"
                    "best[height<=1080]/best"
                )
                ydl_opts_download: dict[str, Any] = {
                    "format": format_spec,
                    "outtmpl": raw_download_template,
                    "merge_output_format": "mp4",
                    "remote_components": {"ejs": "github"},
                    "quiet": False,
                    "no_warnings": True,
                    "continuedl": True,
                    "nopart": False,
                    "concurrent_fragment_downloads": 5,
                    "retries": 10,
                    "fragment_retries": 10,
                    "buffersize": 1024 * 64,
                    "http_chunk_size": 10485760,
                }
                if cookies_file:
                    ydl_opts_download["cookiefile"] = cookies_file
                if cookies_browser:
                    ydl_opts_download["cookiesfrombrowser"] = (cookies_browser,)

                with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
                    ydl.download([canonical_url])

                downloaded_files = list(temp_dir.glob("download.*"))
                for f in downloaded_files:
                    if f.suffix.lower() in [".mkv", ".mp4", ".webm", ".ts", ".flv", ".mov"]:
                        downloaded_video = f
                        break

            if not downloaded_video or not downloaded_video.exists():
                raise RuntimeError(f"X video download failed: no media found in {temp_dir}")

            # 2. Standardize to raw/video.mp4 (Stream copy if H.264/AAC, else fast transcode)
            is_h264_aac = False
            try:
                probe_cmd = [
                    ffprobe_path,
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_name,codec_type",
                    "-of",
                    "json",
                    str(downloaded_video),
                ]
                probe_proc = subprocess.run(probe_cmd, capture_output=True, text=True, check=False)
                if probe_proc.returncode == 0:
                    probe_data = json.loads(probe_proc.stdout)
                    streams = probe_data.get("streams", [])
                    v_codecs = [
                        s.get("codec_name") for s in streams if s.get("codec_type") == "video"
                    ]
                    a_codecs = [
                        s.get("codec_name") for s in streams if s.get("codec_type") == "audio"
                    ]
                    if (
                        v_codecs
                        and v_codecs[0] in ["h264", "avc1"]
                        and a_codecs
                        and a_codecs[0] == "aac"
                    ):
                        is_h264_aac = True
            except Exception:  # noqa: BLE001, S110
                pass

            if is_h264_aac and downloaded_video.suffix.lower() == ".mp4":
                transcode_cmd = [
                    ffmpeg_path,
                    "-y",
                    "-i",
                    str(downloaded_video),
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(standard_video_path),
                ]
            else:
                transcode_cmd = [
                    ffmpeg_path,
                    "-y",
                    "-i",
                    str(downloaded_video),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-ar",
                    "44100",
                    "-movflags",
                    "+faststart",
                    str(standard_video_path),
                ]

            proc = subprocess.run(transcode_cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                raise RuntimeError(f"FFmpeg standardization failed:\n{proc.stderr}")

            # 3. Extract 16kHz WAV: raw/audio.wav
            wav_cmd = [
                ffmpeg_path,
                "-y",
                "-i",
                str(standard_video_path),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                str(standard_audio_path),
            ]
            proc_wav = subprocess.run(wav_cmd, capture_output=True, text=True, check=False)
            if proc_wav.returncode != 0:
                raise RuntimeError(f"Audio extraction failed:\n{proc_wav.stderr}")
        else:
            print(f"  ✓ Reusing existing standardized raw video and audio: {raw_dir}")

        # Update metadata with actual standardized video dimensions
        actual_w, actual_h = get_video_dimensions(standard_video_path, ffprobe_path)
        metadata.width = actual_w
        metadata.height = actual_h
        metadata.is_vertical = actual_h > actual_w

        # 4. Handle Cover Art: raw/cover.jpg
        cover_path = raw_dir / "cover.jpg"
        if metadata.thumbnail_url:
            try:
                resp = requests.get(metadata.thumbnail_url, timeout=15)
                if resp.status_code == 200:
                    temp_thumb = temp_dir / "thumb_raw"
                    temp_thumb.write_bytes(resp.content)
                    with Image.open(temp_thumb) as img:
                        rgb_img = img.convert("RGB")
                        rgb_img.save(cover_path, "JPEG", quality=95)
            except Exception:  # noqa: BLE001, S110
                pass

        # 5. Check if any native subtitles were downloaded
        subtitle_path: Path | None = None
        for sf in temp_dir.glob("download*"):
            if sf.suffix.lower() in [".srt", ".vtt"]:
                dest = raw_dir / "subtitle.srt"
                dest.write_text(sf.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
                subtitle_path = dest
                break

        # 6. Save metadata.json
        metadata_path = raw_dir / "metadata.json"
        metadata_path.write_text(
            json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Cleanup temp directory
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:  # noqa: BLE001, S110
            pass

        return RawMaterialResult(
            task_dir=task_dir,
            raw_dir=raw_dir,
            video_path=standard_video_path,
            audio_path=standard_audio_path,
            cover_path=cover_path if cover_path.exists() else None,
            subtitle_path=subtitle_path if (subtitle_path and subtitle_path.exists()) else None,
            metadata_path=metadata_path,
            metadata=metadata,
        )
