"""Bilibili platform material extractor (Videos, Bangumi, Cheese, Opus, Shortlinks)."""

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, ClassVar

import requests
import yt_dlp
from PIL import Image

from porter_skill.extractors.base import (
    BasePlatformExtractor,
    RawMaterialResult,
    VideoMetadata,
    enhance_audio_for_asr,
    register_extractor,
    sanitize_filename,
)
from porter_skill.extractors.inspector import resolve_and_clean_url
from porter_skill.subtitle.formatter import ms_to_srt_time
from porter_skill.synthesizer import get_video_dimensions, is_valid_video_file


def _convert_vtt_to_srt(vtt_content: str) -> str:
    """Convert WebVTT text content to SubRip SRT format."""
    lines = vtt_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    srt_blocks: list[str] = []
    block_num = 1

    time_pattern = re.compile(
        r"(\d{2}:)?(\d{2}):(\d{2})[\.,](\d{3})\s*-->\s*(\d{2}:)?(\d{2}):(\d{2})[\.,](\d{3})"
    )

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = time_pattern.search(line)
        if match:
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
                clean_text = re.sub(r"<[^>]+>", "", text_line)
                if clean_text:
                    text_lines.append(clean_text)
                i += 1

            if text_lines:
                single_line_text = " ".join(text_lines)
                single_line_text = re.sub(r"\s+", " ", single_line_text).strip()
                if single_line_text:
                    srt_blocks.append(
                        f"{block_num}\n{start_time} --> {end_time}\n{single_line_text}"
                    )
                    block_num += 1
        else:
            i += 1

    return "\n\n".join(srt_blocks) + ("\n" if srt_blocks else "")


def _convert_bilibili_json_to_srt(json_content: str) -> str:
    """Convert Bilibili JSON CC subtitle body to standard SRT format."""
    try:
        data = json.loads(json_content)
        body = data.get("body") or []
        if not isinstance(body, list):
            return ""

        srt_blocks: list[str] = []
        block_idx = 1
        for item in body:
            if not isinstance(item, dict):
                continue
            from_val = item.get("from")
            to_val = item.get("to")
            content = str(item.get("content") or "").strip()
            if from_val is not None and to_val is not None and content:
                start_ms = max(0, int(float(from_val) * 1000))
                end_ms = max(start_ms + 100, int(float(to_val) * 1000))
                start_time = ms_to_srt_time(start_ms)
                end_time = ms_to_srt_time(end_ms)
                srt_blocks.append(f"{block_idx}\n{start_time} --> {end_time}\n{content}")
                block_idx += 1

        return "\n\n".join(srt_blocks) + ("\n" if srt_blocks else "")
    except Exception:  # noqa: BLE001
        return ""


@register_extractor
class BilibiliExtractor(BasePlatformExtractor):
    """Extractor for Bilibili video content (Videos, Bangumi, Cheese, Opus, Shortlinks)."""

    BILIBILI_URL_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        # Standard video: bilibili.com/video/BV1... or av...
        re.compile(
            r"^https?://(?:(?:www|m)\.)?bilibili\.com/(?:video/|festival/[^/?#]+\?(?:[^#]*&)?bvid=)(?P<id>[a-zA-Z0-9]+)"
        ),
        # Bangumi: bilibili.com/bangumi/play/ep... or ss...
        re.compile(r"^https?://(?:(?:www|m)\.)?bilibili\.com/bangumi/play/(?P<id>(?:ep|ss)\d+)"),
        # Cheese / Courses: bilibili.com/cheese/play/ep... or ss...
        re.compile(r"^https?://(?:(?:www|m)\.)?bilibili\.com/cheese/play/(?P<id>(?:ep|ss)\d+)"),
        # Short links: b23.tv/ID
        re.compile(r"^https?://(?:www\.)?b23\.tv/(?P<id>[a-zA-Z0-9]+)"),
        # International: bilibili.tv / biliintl.com
        re.compile(
            r"^https?://(?:(?:www)\.)?bili(?:bili\.tv|intl\.com)/(?:[a-zA-Z]{2}/)?(?:play|video)/(?P<id>\d+)"
        ),
        # Opus / Dynamic: t.bilibili.com/ID or bilibili.com/opus/ID
        re.compile(r"^https?://(?:t\.bilibili\.com|(?:www\.)?bilibili\.com/opus)/(?P<id>\d+)"),
    ]

    def can_handle(self, url: str) -> bool:
        """Check if URL belongs to Bilibili platform."""
        for pattern in self.BILIBILI_URL_PATTERNS:
            if pattern.search(url):
                return True
        return (
            "bilibili.com" in url
            or "b23.tv" in url
            or "bilibili.tv" in url
            or "biliintl.com" in url
        )

    def _clean_title(self, raw_title: str | None, bvid: str) -> str:
        """Derive a clean, concise, safe title from Bilibili title text."""
        if not raw_title:
            return f"bilibili_{bvid}"

        # Clean trailing _哔哩哔哩_bilibili / - 哔哩哔哩 / _bilibili
        clean = re.sub(
            r"(_|\s*-\s*)(哔哩哔哩|bilibili).*", "", raw_title, flags=re.IGNORECASE
        ).strip()
        # Clean URLs if present
        clean = re.sub(r"https?://\S+", "", clean).strip()

        if not clean:
            return f"bilibili_{bvid}"

        return clean[:60].strip()

    def _select_source_subtitle_lang(self, subtitles_dict: dict[str, Any]) -> str | None:
        """Select preferred source speech subtitle language code."""
        if not subtitles_dict:
            return None

        # 1. Prioritize original speech tags
        for k in subtitles_dict:
            if k.endswith(("-orig", "-original")):
                return k

        # 2. Preferred languages (prioritize English/Foreign if source, or Chinese)
        preferred_langs = [
            "en",
            "en-US",
            "en-GB",
            "zh-CN",
            "zh-Hans",
            "zh-Hans-CN",
            "ai-zh",
            "zh",
            "ja",
            "ko",
            "de",
            "fr",
            "es",
        ]
        for lang in preferred_langs:
            if lang in subtitles_dict:
                return lang

        for lang in preferred_langs:
            for k in subtitles_dict:
                if k.lower().startswith(lang.lower()):
                    return k

        return next(iter(subtitles_dict.keys()), None)

    def _select_chinese_subtitle_lang(self, subtitles_dict: dict[str, Any]) -> str | None:
        """Select preferred Chinese translation or official track if available."""
        if not subtitles_dict:
            return None

        zh_preferred = [
            "zh-CN",
            "zh-Hans",
            "zh-Hans-CN",
            "ai-zh",
            "zh",
            "zh-Hant",
            "zh-TW",
            "zh-HK",
            "chinese",
        ]
        for lang in zh_preferred:
            if lang in subtitles_dict:
                return lang

        for k in subtitles_dict:
            lower_k = k.lower()
            if lower_k.startswith("zh") or "chinese" in lower_k or "中文" in lower_k:
                return k

        return None

    def extract_raw_materials(
        self,
        url: str,
        output_base_dir: Path,
        ffmpeg_path: str = "ffmpeg",
        cookies_file: str | None = None,
        cookies_browser: str | None = None,
    ) -> RawMaterialResult:
        """Extract and standardize Bilibili video materials into raw/ directory."""
        output_base_dir = Path(output_base_dir)
        output_base_dir.mkdir(parents=True, exist_ok=True)

        canonical_url = resolve_and_clean_url(url)

        # 1. Fetch metadata using yt-dlp with auto-retry on rate limit / transient challenge
        ydl_opts_info: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "retries": 10,
            "fragment_retries": 10,
            "http_headers": {
                "Referer": "https://www.bilibili.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
            },
        }
        if cookies_file:
            ydl_opts_info["cookiefile"] = cookies_file
        if cookies_browser:
            ydl_opts_info["cookiesfrombrowser"] = (cookies_browser,)

        info: dict[str, Any] | None = None
        last_err: Exception | None = None

        for attempt in range(1, 4):
            try:
                with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                    info = ydl.extract_info(canonical_url, download=False)
                    if info:
                        break
            except Exception as e:
                last_err = e
                err_str = str(e)
                if (
                    "login" in err_str.lower()
                    or "sessdata" in err_str.lower()
                    or "大会员" in err_str
                    or "permission" in err_str.lower()
                ):
                    raise RuntimeError(
                        f"Bilibili video access restricted / login required for {url}: {err_str}\n"
                        "Tip: Bilibili requires authentication (e.g. 1080p+ / 大会员 / SESSDATA). "
                        "Please pass browser cookies using --cookies-from-browser chrome / edge / firefox."
                    ) from e
                if attempt < 3:
                    time.sleep(1.5 * attempt)

        if not info:
            raise RuntimeError(
                f"Failed to fetch metadata from Bilibili URL {url}: {last_err}"
            ) from last_err

        bvid = str(info.get("id") or "video")
        uploader = info.get("uploader") or info.get("uploader_id") or "up_user"
        raw_title = info.get("title") or ""
        clean_title = self._clean_title(raw_title, bvid)
        safe_title = sanitize_filename(clean_title, max_length=60)

        task_dir_name = f"{bvid}_{safe_title}"
        task_dir = output_base_dir / task_dir_name
        raw_dir = task_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        standard_video_path = raw_dir / "video.mp4"
        standard_audio_path = raw_dir / "audio.wav"
        standard_enhanced_audio_path = raw_dir / "audio_enhanced.wav"
        cover_path = raw_dir / "cover.jpg"
        metadata_path = raw_dir / "metadata.json"
        source_srt_path = raw_dir / "subtitle.srt"
        zh_srt_path = raw_dir / "subtitle_zh.srt"

        # Check if already completed
        if (
            is_valid_video_file(standard_video_path, ffmpeg_path.replace("ffmpeg", "ffprobe"))
            and standard_audio_path.is_file()
            and standard_audio_path.stat().st_size > 1024
            and metadata_path.is_file()
        ):
            meta_json = json.loads(metadata_path.read_text(encoding="utf-8"))
            meta = VideoMetadata(**meta_json)
            cached_enhanced_audio = (
                standard_enhanced_audio_path
                if standard_enhanced_audio_path.is_file()
                and standard_enhanced_audio_path.stat().st_size > 0
                else None
            )
            return RawMaterialResult(
                task_dir=task_dir,
                raw_dir=raw_dir,
                video_path=standard_video_path,
                audio_path=standard_audio_path,
                enhanced_audio_path=cached_enhanced_audio,
                metadata_path=metadata_path,
                cover_path=cover_path if cover_path.is_file() else None,
                subtitle_path=source_srt_path if source_srt_path.is_file() else None,
                subtitle_zh_path=zh_srt_path if zh_srt_path.is_file() else None,
                metadata=meta,
            )

        duration = float(info.get("duration") or 0.0)
        width = info.get("width")
        height = info.get("height")
        is_vertical = False
        if width and height and height > width:
            is_vertical = True

        metadata = VideoMetadata(
            id=bvid,
            title=raw_title or clean_title,
            safe_title=safe_title,
            url=canonical_url,
            platform="bilibili",
            uploader=uploader,
            channel=info.get("channel"),
            duration=duration,
            width=width,
            height=height,
            is_vertical=is_vertical,
            description=info.get("description") or "",
            thumbnail_url=info.get("thumbnail"),
            has_official_subtitle=bool(info.get("subtitles") or info.get("automatic_captions")),
            raw_metadata={
                "id": bvid,
                "title": raw_title or clean_title,
                "uploader": uploader,
                "duration": duration,
                "width": width,
                "height": height,
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "danmaku_count": info.get("comment_count"),
            },
        )

        # 2. Download media and subtitles
        temp_dir = raw_dir / ".download_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_video_tmpl = str(temp_dir / "%(id)s.%(ext)s")

        ydl_opts_download: dict[str, Any] = {
            "outtmpl": temp_video_tmpl,
            "format": (
                "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/"
                "bestvideo[height<=1080]+bestaudio/"
                "best[ext=mp4][height<=1080]/"
                "best[height<=1080]/best"
            ),
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "srt/vtt/json/best",
            "subtitleslangs": ["all"],
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": "only_download",
            "retries": 10,
            "fragment_retries": 10,
            "http_headers": {
                "Referer": "https://www.bilibili.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
            },
        }
        if cookies_file:
            ydl_opts_download["cookiefile"] = cookies_file
        if cookies_browser:
            ydl_opts_download["cookiesfrombrowser"] = (cookies_browser,)

        # Check existing valid download before re-downloading
        downloaded_video: Path | None = None
        for cand in temp_dir.glob("*.*"):
            if cand.suffix.lower() in (
                ".mp4",
                ".mkv",
                ".webm",
                ".flv",
                ".mov",
            ) and is_valid_video_file(cand, ffmpeg_path.replace("ffmpeg", "ffprobe")):
                downloaded_video = cand
                break

        if not downloaded_video:
            try:
                with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
                    ydl.download([canonical_url])
            except Exception as e:  # noqa: BLE001
                # Retry with fallback format
                try:
                    ydl_opts_download["format"] = "best"
                    with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
                        ydl.download([canonical_url])
                except Exception as retry_err:
                    raise RuntimeError(
                        f"Failed to download media stream from Bilibili: {e}\nRetry error: {retry_err}"
                    ) from retry_err

            downloaded_videos = [
                f
                for f in temp_dir.glob("*.*")
                if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".flv", ".mov")
                and is_valid_video_file(f, ffmpeg_path.replace("ffmpeg", "ffprobe"))
            ]
            if not downloaded_videos:
                raise RuntimeError(
                    f"No video file found in temporary directory after Bilibili download: {temp_dir}"
                )
            downloaded_video = downloaded_videos[0]

        # 3. Standardize video to H.264 + AAC MP4
        cmd_v = [
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
            "-movflags",
            "+faststart",
            str(standard_video_path),
        ]
        res_v = subprocess.run(cmd_v, capture_output=True, text=True, check=False)
        if res_v.returncode != 0:
            raise RuntimeError(f"FFmpeg video standardization failed for Bilibili: {res_v.stderr}")

        # 4. Extract 16kHz Mono WAV Audio
        cmd_a = [
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
        res_a = subprocess.run(cmd_a, capture_output=True, text=True, check=False)
        if res_a.returncode != 0:
            raise RuntimeError(f"FFmpeg audio extraction failed for Bilibili: {res_a.stderr}")

        # 4.1 ASR Vocal Enhancement: raw/audio_enhanced.wav
        enhanced_audio_path: Path | None = None
        if (
            standard_enhanced_audio_path.is_file()
            and standard_enhanced_audio_path.stat().st_size > 0
        ) or enhance_audio_for_asr(standard_audio_path, standard_enhanced_audio_path, ffmpeg_path):
            enhanced_audio_path = standard_enhanced_audio_path

        # 5. Extract thumbnail cover
        thumbnail_url = info.get("thumbnail")
        if thumbnail_url:
            try:
                headers = {"Referer": "https://www.bilibili.com/"}
                resp = requests.get(thumbnail_url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    cover_temp = temp_dir / "cover_raw"
                    cover_temp.write_bytes(resp.content)
                    with Image.open(cover_temp) as img:
                        img.convert("RGB").save(cover_path, "JPEG", quality=95)
            except Exception:  # noqa: BLE001, S110
                pass

        # If no thumbnail downloaded, extract frame at 1s
        if not cover_path.is_file():
            cmd_cover = [
                ffmpeg_path,
                "-y",
                "-ss",
                "00:00:01",
                "-i",
                str(standard_video_path),
                "-vframes",
                "1",
                "-q:v",
                "2",
                str(cover_path),
            ]
            subprocess.run(cmd_cover, capture_output=True, check=False)

        # 6. Process downloaded subtitles if present
        all_subs = {**(info.get("subtitles") or {}), **(info.get("automatic_captions") or {})}
        source_lang = self._select_source_subtitle_lang(all_subs)
        zh_lang = self._select_chinese_subtitle_lang(all_subs)

        found_sub_path: Path | None = None
        found_zh_sub_path: Path | None = None

        # Search downloaded subtitle files in temp directory
        for f in temp_dir.glob("*.*"):
            s_ext = f.suffix.lower()
            if s_ext in (".vtt", ".srt", ".json"):
                fname = f.name.lower()
                if zh_lang and zh_lang.lower() in fname:
                    found_zh_sub_path = f
                elif (source_lang and source_lang.lower() in fname) or not found_sub_path:
                    found_sub_path = f

        def _load_to_srt(file_path: Path) -> str:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            ext = file_path.suffix.lower()
            if ext == ".vtt":
                return _convert_vtt_to_srt(content)
            if ext == ".json":
                return _convert_bilibili_json_to_srt(content)
            return content

        if found_sub_path and found_sub_path.is_file():
            srt_content = _load_to_srt(found_sub_path)
            if srt_content.strip():
                source_srt_path.write_text(srt_content, encoding="utf-8")

        if found_zh_sub_path and found_zh_sub_path.is_file():
            zh_srt_content = _load_to_srt(found_zh_sub_path)
            if zh_srt_content.strip():
                zh_srt_path.write_text(zh_srt_content, encoding="utf-8")

        # 7. Update metadata with physical video dimensions
        real_w, real_h = get_video_dimensions(
            standard_video_path, ffmpeg_path.replace("ffmpeg", "ffprobe")
        )
        if real_w and real_h:
            metadata.width = real_w
            metadata.height = real_h
            metadata.is_vertical = real_h > real_w

        # Save metadata.json
        metadata_path.write_text(
            json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Cleanup temp directory
        try:
            shutil.rmtree(temp_dir)
        except Exception:  # noqa: BLE001, S110
            pass

        return RawMaterialResult(
            task_dir=task_dir,
            raw_dir=raw_dir,
            video_path=standard_video_path,
            audio_path=standard_audio_path,
            enhanced_audio_path=enhanced_audio_path,
            metadata_path=metadata_path,
            cover_path=cover_path if cover_path.is_file() else None,
            subtitle_path=source_srt_path if source_srt_path.is_file() else None,
            subtitle_zh_path=zh_srt_path if zh_srt_path.is_file() else None,
            metadata=metadata,
        )
