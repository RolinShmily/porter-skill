"""Instagram platform material extractor (Reels, Posts, IGTV, Carousels)."""

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
class InstagramExtractor(BasePlatformExtractor):
    """Extractor for Instagram video content (Reels, Posts, IGTV, Carousels)."""

    INSTAGRAM_URL_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        # Reels: /reel/ID or /reels/ID
        re.compile(
            r"^https?://(?:(?:www|m)\.)?(?:instagram\.com|instagr\.am)/(?:(?:share/)?reels?)/(?P<id>[a-zA-Z0-9_-]+)"
        ),
        # Posts / IGTV: /p/ID or /tv/ID
        re.compile(
            r"^https?://(?:(?:www|m)\.)?(?:instagram\.com|instagr\.am)/(?:(?:share/)?(?:p|tv))/(?P<id>[a-zA-Z0-9_-]+)"
        ),
        # Stories: /stories/username/ID
        re.compile(
            r"^https?://(?:(?:www|m)\.)?(?:instagram\.com|instagr\.am)/stories/(?P<user>[^/?#]+)/(?P<id>\d+)"
        ),
        # General user reel or post with username in path: instagram.com/username/reel/ID
        re.compile(
            r"^https?://(?:(?:www|m)\.)?(?:instagram\.com|instagr\.am)/(?!share/)[^/?#]+/(?:p|tv|reels?)/(?P<id>[a-zA-Z0-9_-]+)"
        ),
        # Share shortlinks: ig.me
        re.compile(r"^https?://ig\.me/(?P<id>[a-zA-Z0-9_-]+)"),
    ]

    def can_handle(self, url: str) -> bool:
        """Check if URL belongs to Instagram platform."""
        for pattern in self.INSTAGRAM_URL_PATTERNS:
            if pattern.search(url):
                return True
        return "instagram.com" in url or "instagr.am" in url or "ig.me" in url

    def _clean_caption_to_title(
        self, caption: str | None, uploader: str | None, post_id: str
    ) -> str:
        """Derive a clean, concise, safe title from Instagram caption text."""
        if not caption:
            return f"Instagram_by_{uploader or post_id}"

        # 1. Remove URLs (http/https/ig.me)
        cleaned = re.sub(r"https?://\S+", "", caption).strip()

        # 2. Extract non-empty lines
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        if not lines:
            return f"Instagram_by_{uploader or post_id}"

        # 3. Take first line and strip mentions and hashtags
        first_line = lines[0]
        first_line = re.sub(r"^(@\w+\s*)+", "", first_line).strip()
        first_line = re.sub(r"(#\w+\s*)+$", "", first_line).strip()

        # If first line was purely hashtags, try remaining text without hashtags
        if not first_line:
            no_hashtags = re.sub(r"#\w+", "", cleaned).strip()
            lines_no_tag = [line.strip() for line in no_hashtags.splitlines() if line.strip()]
            if lines_no_tag:
                first_line = lines_no_tag[0]

        if not first_line:
            return f"Instagram_by_{uploader or post_id}"

        return first_line[:50].strip()

    def _try_embed_fallback(self, url: str, post_id: str) -> dict[str, Any] | None:
        """
        Fallback Level 3: Attempt to scrape public embed page when login is required.
        Returns basic stream dict if successful, None otherwise.
        """
        try:
            embed_url = f"https://www.instagram.com/p/{post_id}/embed/captioned/"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            resp = requests.get(embed_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                # Look for video src in embed html
                video_src_match = re.search(r'class="EmbeddedVideo"[^>]*src="([^"]+)"', resp.text)
                if not video_src_match:
                    video_src_match = re.search(r'"video_url":"([^"]+)"', resp.text)

                if video_src_match:
                    video_url = video_src_match.group(1).replace("\\u0026", "&")
                    return {
                        "id": post_id,
                        "url": video_url,
                        "ext": "mp4",
                        "title": f"Instagram_Post_{post_id}",
                    }
        except Exception:  # noqa: BLE001, S110
            pass
        return None

    def extract_raw_materials(
        self,
        url: str,
        output_base_dir: Path,
        ffmpeg_path: str = "ffmpeg",
        cookies_file: str | None = None,
        cookies_browser: str | None = None,
    ) -> RawMaterialResult:
        """Extract and standardize Instagram video materials into raw/ directory."""
        output_base_dir = Path(output_base_dir)
        output_base_dir.mkdir(parents=True, exist_ok=True)

        canonical_url = resolve_and_clean_url(url)

        # 1. Fetch metadata using yt-dlp
        ydl_opts_info: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }
        if cookies_file:
            ydl_opts_info["cookiefile"] = cookies_file
        if cookies_browser:
            ydl_opts_info["cookiesfrombrowser"] = (cookies_browser,)

        info: dict[str, Any] | None = None
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            try:
                info = ydl.extract_info(canonical_url, download=False)
            except Exception as e:
                err_str = str(e)
                # Match post_id for embed fallback
                match = None
                for pat in self.INSTAGRAM_URL_PATTERNS:
                    match = pat.search(canonical_url)
                    if match and "id" in match.groupdict():
                        break
                post_id = match.group("id") if match and "id" in match.groupdict() else "video"

                # Check if restricted / login wall
                if (
                    "login" in err_str.lower()
                    or "checkpoint" in err_str.lower()
                    or "401" in err_str
                    or "429" in err_str
                ):
                    # Try Level 3 Embed fallback
                    embed_info = self._try_embed_fallback(canonical_url, post_id)
                    if embed_info:
                        info = embed_info
                    else:
                        raise RuntimeError(
                            f"Instagram platform access restricted / login required for {url}: {err_str}\n"
                            "Tip: Instagram requires authentication. Please configure cookies_browser: 'chrome' "
                            "(or edge/firefox) in config.json, or pass --cookies-from-browser chrome / --cookies-file <path>."
                        ) from e
                else:
                    raise RuntimeError(
                        f"Failed to fetch metadata from Instagram URL {url}: {err_str}"
                    ) from e

        if info is None:
            raise RuntimeError(f"Failed to fetch metadata from Instagram URL: {canonical_url}")

        # Handle Carousel (playlist of entries)
        carousel_index: int | None = None
        carousel_total: int | None = None
        target_info = info
        if info.get("_type") == "playlist" or (
            isinstance(info.get("entries"), list) and info["entries"]
        ):
            entries = info["entries"]
            carousel_total = len(entries)
            # Find the first entry that contains a video stream
            video_entry = None
            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                # Check for video markers
                formats = entry.get("formats") or []
                has_vcodec = any(f.get("vcodec") != "none" for f in formats if isinstance(f, dict))
                if has_vcodec or entry.get("duration") or entry.get("vcodec") != "none":
                    video_entry = entry
                    carousel_index = idx + 1
                    break

            if not video_entry:
                raise RuntimeError(
                    f"Instagram post {url} is a carousel containing only images (no video stream found)."
                )
            target_info = video_entry

        post_id = str(target_info.get("id") or info.get("id") or "unknown_id")
        uploader = (
            target_info.get("uploader")
            or target_info.get("channel")
            or info.get("uploader")
            or info.get("channel")
            or target_info.get("uploader_id")
        )
        caption_text = str(
            target_info.get("description")
            or info.get("description")
            or target_info.get("title")
            or ""
        )
        cleaned_title = self._clean_caption_to_title(caption_text, uploader, post_id)
        if carousel_total and carousel_total > 1 and carousel_index:
            cleaned_title = f"{cleaned_title}_C{carousel_index}of{carousel_total}"

        safe_title = sanitize_filename(cleaned_title, max_length=50)

        folder_name = f"{post_id}_{safe_title}"
        task_dir = output_base_dir / folder_name
        raw_dir = task_dir / "raw"
        cooked_dir = task_dir / "cooked"
        temp_dir = task_dir / ".tmp"

        raw_dir.mkdir(parents=True, exist_ok=True)
        cooked_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        width = target_info.get("width")
        height = target_info.get("height")
        is_vertical = bool(width and height and height > width)

        metadata = VideoMetadata(
            id=post_id,
            title=cleaned_title,
            safe_title=safe_title,
            url=canonical_url,
            platform="instagram",
            uploader=uploader,
            channel=target_info.get("channel") or info.get("channel"),
            duration=target_info.get("duration"),
            width=width,
            height=height,
            is_vertical=is_vertical,
            description=caption_text,
            thumbnail_url=target_info.get("thumbnail") or info.get("thumbnail"),
            has_official_subtitle=bool(target_info.get("subtitles") or info.get("subtitles")),
            raw_metadata={
                "id": post_id,
                "title": cleaned_title,
                "caption": caption_text,
                "uploader": uploader,
                "uploader_id": target_info.get("uploader_id") or info.get("uploader_id"),
                "duration": target_info.get("duration"),
                "width": width,
                "height": height,
                "like_count": target_info.get("like_count") or info.get("like_count"),
                "comment_count": target_info.get("comment_count") or info.get("comment_count"),
                "carousel_index": carousel_index,
                "carousel_total": carousel_total,
            },
        )

        # Resumption Check: If raw materials already exist and are valid, reuse directly
        standard_video_path = raw_dir / "video.mp4"
        standard_audio_path = raw_dir / "audio.wav"
        standard_cover_path = raw_dir / "cover.jpg"
        metadata_path = raw_dir / "metadata.json"

        if (
            standard_video_path.is_file()
            and standard_audio_path.is_file()
            and is_valid_video_file(standard_video_path)
        ):
            metadata_path.write_text(
                json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return RawMaterialResult(
                task_dir=task_dir,
                raw_dir=raw_dir,
                video_path=standard_video_path,
                audio_path=standard_audio_path,
                cover_path=standard_cover_path if standard_cover_path.is_file() else None,
                subtitle_path=None,
                metadata_path=metadata_path,
                metadata=metadata,
            )

        # 2. Download media stream via yt-dlp
        temp_video_template = str(temp_dir / "downloaded_raw.%(ext)s")
        ydl_opts_download: dict[str, Any] = {
            "format": "bestvideo+bestaudio/best",
            "outtmpl": temp_video_template,
            "writethumbnail": True,
            "quiet": True,
            "no_warnings": True,
        }
        if cookies_file:
            ydl_opts_download["cookiefile"] = cookies_file
        if cookies_browser:
            ydl_opts_download["cookiesfrombrowser"] = (cookies_browser,)

        download_url = target_info.get("webpage_url") or target_info.get("url") or canonical_url
        with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
            try:
                ydl.download([download_url])
            except Exception as e:
                raise RuntimeError(
                    f"Failed to download media stream from Instagram: {e}\n"
                    "Tip: Verify network connection or provide cookies via --cookies-from-browser."
                ) from e

        # Locate downloaded files in temp_dir
        downloaded_videos = [
            f
            for f in temp_dir.iterdir()
            if f.is_file() and f.suffix.lower() in [".mp4", ".mkv", ".webm", ".ts", ".mov"]
        ]
        if not downloaded_videos:
            raise RuntimeError(
                f"No video file found in temporary directory after Instagram download: {temp_dir}"
            )
        downloaded_video = downloaded_videos[0]

        # Standardize video: 1080p compatible, H.264 + AAC + yuv420p + faststart
        cmd_video = [
            ffmpeg_path,
            "-y",
            "-i",
            str(downloaded_video),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
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
        res_v = subprocess.run(cmd_video, capture_output=True, check=False, text=True)
        if res_v.returncode != 0 or not standard_video_path.is_file():
            raise RuntimeError(f"FFmpeg video standardization failed for Instagram: {res_v.stderr}")

        # Standardize audio: 16kHz mono baseline wav
        cmd_audio = [
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
        res_a = subprocess.run(cmd_audio, capture_output=True, check=False, text=True)
        if res_a.returncode != 0 or not standard_audio_path.is_file():
            raise RuntimeError(f"FFmpeg audio extraction failed for Instagram: {res_a.stderr}")

        # Process thumbnail / cover
        downloaded_covers = [
            f
            for f in temp_dir.iterdir()
            if f.is_file() and f.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]
        ]
        if downloaded_covers:
            raw_cover = downloaded_covers[0]
            try:
                with Image.open(raw_cover) as img:
                    rgb_img = img.convert("RGB")
                    rgb_img.save(standard_cover_path, "JPEG", quality=95)
            except Exception:  # noqa: BLE001
                shutil.copy2(raw_cover, standard_cover_path)
        else:
            # Fallback: extract frame from video at 1.0s or 0.0s
            cmd_frame = [
                ffmpeg_path,
                "-y",
                "-ss",
                "00:00:01.000",
                "-i",
                str(standard_video_path),
                "-vframes",
                "1",
                "-q:v",
                "2",
                str(standard_cover_path),
            ]
            subprocess.run(cmd_frame, capture_output=True, check=False, text=True)

        # Update metadata with physical video dimensions
        real_w, real_h = get_video_dimensions(
            standard_video_path, ffmpeg_path.replace("ffmpeg", "ffprobe")
        )
        if real_w and real_h:
            metadata.width = real_w
            metadata.height = real_h
            metadata.is_vertical = real_h > real_w
            if metadata.raw_metadata:
                metadata.raw_metadata["width"] = real_w
                metadata.raw_metadata["height"] = real_h

        # Save metadata.json
        metadata_path.write_text(
            json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Clean temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)

        return RawMaterialResult(
            task_dir=task_dir,
            raw_dir=raw_dir,
            video_path=standard_video_path,
            audio_path=standard_audio_path,
            cover_path=standard_cover_path if standard_cover_path.is_file() else None,
            subtitle_path=None,
            metadata_path=metadata_path,
            metadata=metadata,
        )
