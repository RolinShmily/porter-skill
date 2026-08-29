"""YouTube platform material extractor."""

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


def _convert_vtt_to_srt(vtt_content: str) -> str:
    """Convert WebVTT text content to SubRip SRT format."""
    lines = vtt_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    srt_blocks = []
    block_num = 1

    time_pattern = re.compile(
        r"(\d{2}:)?(\d{2}):(\d{2})[\.,](\d{3})\s*-->\s*(\d{2}:)?(\d{2}):(\d{2})[\.,](\d{3})"
    )

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = time_pattern.search(line)
        if match:
            # Format timestamps to HH:MM:SS,mmm
            parts = match.groups()
            start_h = parts[0][:-1] if parts[0] else "00"
            start_m, start_s, start_ms = parts[1], parts[2], parts[3]
            end_h = parts[4][:-1] if parts[4] else "00"
            end_m, end_s, end_ms = parts[5], parts[6], parts[7]

            start_time = f"{int(start_h):02d}:{start_m}:{start_s},{start_ms}"
            end_time = f"{int(end_h):02d}:{end_m}:{end_s},{end_ms}"

            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip():
                text_line = lines[i].strip()
                # Remove VTT formatting tags like <c>, </c>, <v ...>
                clean_text = re.sub(r"<[^>]+>", "", text_line)
                if clean_text:
                    text_lines.append(clean_text)
                i += 1

            if text_lines:
                single_line_text = " ".join(text_lines)
                # Collapse multiple whitespace characters into a single space
                single_line_text = re.sub(r"\s+", " ", single_line_text).strip()
                if single_line_text:
                    srt_blocks.append(
                        f"{block_num}\n{start_time} --> {end_time}\n{single_line_text}"
                    )
                    block_num += 1
        else:
            i += 1

    return "\n\n".join(srt_blocks) + ("\n" if srt_blocks else "")


@register_extractor
class YouTubeExtractor(BasePlatformExtractor):
    """YouTube platform extractor implementing BasePlatformExtractor."""

    YOUTUBE_URL_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"^https?://(www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]+)"),
        re.compile(r"^https?://(www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]+)"),
        re.compile(r"^https?://(www\.)?youtube\.com/embed/([a-zA-Z0-9_-]+)"),
        re.compile(r"^https?://(www\.)?youtube\.com/v/([a-zA-Z0-9_-]+)"),
        re.compile(r"^https?://youtu\.be/([a-zA-Z0-9_-]+)"),
    ]

    def can_handle(self, url: str) -> bool:
        """Check if URL matches standard YouTube patterns."""
        for pattern in self.YOUTUBE_URL_PATTERNS:
            if pattern.search(url):
                return True
        return "youtube.com" in url or "youtu.be" in url

    def _select_source_subtitle_lang(
        self, subtitles_dict: dict[str, Any], is_auto: bool = False
    ) -> str | None:
        """Select best original speech source subtitle language code."""
        if not subtitles_dict:
            return None

        # 1. Prefer original speech track (-orig / -original)
        for k in subtitles_dict:
            if k.endswith(("-orig", "-original")):
                return k

        # 2. Prefer standard source languages
        preferred_langs = [
            "en",
            "en-US",
            "en-GB",
            "en-CA",
            "zh-Hans",
            "zh-CN",
            "zh-Hans-CN",
            "zh",
            "zh-Hant",
            "zh-TW",
            "zh-HK",
            "ja",
            "ko",
            "es",
            "fr",
            "de",
            "ru",
        ]

        for lang in preferred_langs:
            if subtitles_dict.get(lang):
                return lang

        # If not automatic captions, return first available non-empty subtitle lang
        if not is_auto:
            for lang, formats in subtitles_dict.items():
                if formats and not lang.startswith("live_"):
                    return lang

        return None

    def _select_chinese_subtitle_lang(self, subtitles_dict: dict[str, Any]) -> str | None:
        """Select best Chinese subtitle language code."""
        if not subtitles_dict:
            return None
        preferred_zh = ["zh-Hans", "zh-CN", "zh-Hans-CN", "zh", "zh-Hant", "zh-TW", "zh-HK"]
        for lang in preferred_zh:
            if subtitles_dict.get(lang):
                return lang
        return None

    # Backward compatibility alias
    _select_official_subtitle_lang = _select_source_subtitle_lang

    def extract_raw_materials(
        self,
        url: str,
        output_base_dir: Path,
        ffmpeg_path: str = "ffmpeg",
        cookies_file: str | None = None,
        cookies_browser: str | None = None,
    ) -> RawMaterialResult:
        """Extract and standardize YouTube video materials."""
        output_base_dir = Path(output_base_dir)
        output_base_dir.mkdir(parents=True, exist_ok=True)

        # 1. Fetch info metadata with yt-dlp
        player_clients = ["web_embedded", "web", "mweb", "android_vr", "ios", "android"]
        ydl_opts_info: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "remote_components": {"ejs": "github"},
            "extractor_args": {"youtube": {"player_client": player_clients}},
        }
        if cookies_file:
            ydl_opts_info["cookiefile"] = cookies_file
        if cookies_browser:
            ydl_opts_info["cookiesfrombrowser"] = (cookies_browser,)

        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise RuntimeError(f"Failed to fetch metadata from YouTube URL: {url}")

        video_id = str(info.get("id", "unknown_id"))
        raw_title = str(info.get("title", "video"))
        safe_title = sanitize_filename(raw_title)
        folder_name = f"{video_id}_{safe_title}"

        task_dir = output_base_dir / folder_name
        raw_dir = task_dir / "raw"
        cooked_dir = task_dir / "cooked"
        temp_dir = task_dir / ".tmp"

        raw_dir.mkdir(parents=True, exist_ok=True)
        cooked_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Check subtitles: official human vs automatic_captions
        subtitles_dict = info.get("subtitles") or {}
        auto_captions_dict = info.get("automatic_captions") or {}

        official_source_lang = self._select_source_subtitle_lang(subtitles_dict, is_auto=False)
        official_zh_lang = self._select_chinese_subtitle_lang(subtitles_dict)
        auto_source_lang = self._select_source_subtitle_lang(auto_captions_dict, is_auto=True)
        auto_zh_lang = self._select_chinese_subtitle_lang(auto_captions_dict)

        chosen_source_lang = official_source_lang or auto_source_lang
        chosen_zh_lang = official_zh_lang or auto_zh_lang
        has_official_subtitle = official_source_lang is not None

        # Build VideoMetadata
        metadata = VideoMetadata(
            id=video_id,
            title=raw_title,
            safe_title=safe_title,
            url=url,
            platform="youtube",
            uploader=info.get("uploader"),
            channel=info.get("channel"),
            duration=info.get("duration"),
            description=info.get("description"),
            thumbnail_url=info.get("thumbnail"),
            has_official_subtitle=has_official_subtitle,
            official_subtitle_lang=chosen_source_lang,
            raw_metadata={
                "id": video_id,
                "title": raw_title,
                "duration": info.get("duration"),
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "uploader": info.get("uploader"),
                "uploader_id": info.get("uploader_id"),
                "upload_date": info.get("upload_date"),
                "has_subtitles": bool(subtitles_dict),
                "has_auto_captions": bool(auto_captions_dict),
            },
        )

        # 2. Download media streams to temp_dir
        raw_download_template = str(temp_dir / "download.%(ext)s")
        ydl_opts_download: dict[str, Any] = {
            "format": "bestvideo+bestaudio/best",
            "outtmpl": raw_download_template,
            "merge_output_format": "mkv",  # intermediate container
            "remote_components": {"ejs": "github"},
            "quiet": False,
            "no_warnings": True,
            "overwrites": True,
            "extractor_args": {"youtube": {"player_client": player_clients}},
        }
        if cookies_file:
            ydl_opts_download["cookiefile"] = cookies_file
        if cookies_browser:
            ydl_opts_download["cookiesfrombrowser"] = (cookies_browser,)

        # Request source subtitles and Chinese subtitles if available
        requested_subs: list[str] = []
        if chosen_source_lang:
            requested_subs.append(chosen_source_lang)
        if chosen_zh_lang and chosen_zh_lang != chosen_source_lang:
            requested_subs.append(chosen_zh_lang)

        if requested_subs:
            if official_source_lang or official_zh_lang:
                ydl_opts_download["writesubtitles"] = True
            if auto_source_lang or auto_zh_lang:
                ydl_opts_download["writeautomaticsub"] = True
            ydl_opts_download["subtitleslangs"] = requested_subs
            ydl_opts_download["subtitlesformat"] = "srt/vtt/best"

        try:
            with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
                ydl.download([url])
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] Initial download with subtitles encountered issue: {e}")
            print("  -> Retrying download without subtitles (will use ASR fallback)...")
            ydl_opts_retry = dict(ydl_opts_download)
            ydl_opts_retry.pop("writesubtitles", None)
            ydl_opts_retry.pop("writeautomaticsub", None)
            ydl_opts_retry.pop("subtitleslangs", None)
            ydl_opts_retry.pop("subtitlesformat", None)
            with yt_dlp.YoutubeDL(ydl_opts_retry) as ydl:
                ydl.download([url])

        # Find downloaded video in temp_dir
        downloaded_files = list(temp_dir.glob("download.*"))
        downloaded_video = None
        for f in downloaded_files:
            if f.suffix.lower() in [".mkv", ".mp4", ".webm", ".ts", ".flv", ".mov"]:
                downloaded_video = f
                break

        if not downloaded_video or not downloaded_video.exists():
            raise RuntimeError(f"Download failed: video file not found in {temp_dir}")

        # 3. Transcode to standardized raw/video.mp4 (H.264 High Profile + AAC 192k + yuv420p + faststart)
        standard_video_path = raw_dir / "video.mp4"
        transcode_cmd = [
            ffmpeg_path,
            "-y",
            "-i",
            str(downloaded_video),
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-preset",
            "medium",
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

        # 4. Extract 16kHz 16bit mono WAV: raw/audio.wav
        standard_audio_path = raw_dir / "audio.wav"
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

        # 5. Handle Cover Art: raw/cover.jpg
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
                # If network fetch fails, ignore cover failure
                pass

        # 6. Handle Subtitles: raw/subtitle.srt & raw/subtitle_zh.srt
        subtitle_path: Path | None = None
        subtitle_zh_path: Path | None = None

        def _save_sub(lang_tag: str, dest_name: str) -> Path | None:
            sub_files = list(temp_dir.glob(f"download*.{lang_tag}.*")) + list(
                temp_dir.glob(f"download*.{lang_tag}*")
            )
            for sf in sub_files:
                if sf.suffix.lower() == ".srt":
                    dest = raw_dir / dest_name
                    dest.write_text(
                        sf.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
                    )
                    return dest
                elif sf.suffix.lower() == ".vtt":
                    dest = raw_dir / dest_name
                    vtt_text = sf.read_text(encoding="utf-8", errors="replace")
                    srt_text = _convert_vtt_to_srt(vtt_text)
                    dest.write_text(srt_text, encoding="utf-8")
                    return dest
            return None

        if chosen_source_lang:
            subtitle_path = _save_sub(chosen_source_lang, "subtitle.srt")

        if chosen_zh_lang:
            subtitle_zh_path = _save_sub(chosen_zh_lang, "subtitle_zh.srt")

        # 7. Save metadata JSON
        metadata_path = raw_dir / "metadata.json"
        metadata_dict = metadata.to_dict()
        metadata_path.write_text(
            json.dumps(metadata_dict, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 8. Clean up temp_dir
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
            subtitle_zh_path=subtitle_zh_path
            if (subtitle_zh_path and subtitle_zh_path.exists())
            else None,
            metadata_path=metadata_path,
            metadata=metadata,
        )
