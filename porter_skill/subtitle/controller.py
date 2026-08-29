"""Subtitle extraction, fallback orchestration, and generation controller."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from porter_skill.config import PorterConfig, get_default_config
from porter_skill.extractors.base import RawMaterialResult
from porter_skill.subtitle.formatter import (
    SubtitleItem,
    align_bilingual_items,
    generate_bilingual_ass,
    generate_bilingual_srt,
    generate_zh_ass,
    generate_zh_srt,
    merge_short_fragments,
    parse_srt,
)
from porter_skill.subtitle.translator import (
    _get_videocaptioner_bin,
    translate_with_direct_llm,
    translate_with_google_http,
    translate_with_videocaptioner_cli,
    translate_with_videocaptioner_free,
)


@dataclass
class SubtitleResult:
    """Output structure of Phase 2 & 3 in cooked/ directory."""

    subtitle_bilingual_srt: Path
    subtitle_bilingual_ass: Path
    subtitle_zh_srt: Path
    subtitle_zh_ass: Path
    items: list[SubtitleItem]
    used_asr: bool = False


def transcribe_with_whisper_api(
    audio_path: Path,
    output_srt: Path,
    config: PorterConfig,
) -> bool:
    """Pure Python ASR using OpenAI Whisper API (requires OPENAI_API_KEY)."""
    api_key = config.asr.whisper_api_key or config.llm.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return False

    try:
        client = OpenAI(
            api_key=api_key,
            base_url=config.asr.whisper_api_base
            or config.llm.api_base
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1",
            timeout=120.0,
        )
        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model=config.asr.whisper_model or "whisper-1",
                file=audio_file,
                response_format="srt",
            )
            if transcript:
                output_srt.write_text(str(transcript), encoding="utf-8")
                return True
    except Exception as e:  # noqa: BLE001
        print(f"  [WARN] Whisper API transcription warning: {e}")

    return False


def run_asr_transcription(
    audio_path: Path,
    output_srt: Path,
    config: PorterConfig,
) -> bool:
    """Run universal ASR speech recognition, testing candidate engines sequentially."""
    vc_bin = _get_videocaptioner_bin()

    # Candidate ASR engines in priority order: bijian -> jianying -> whisper-api -> whisper-cpp
    engines_to_try: list[str] = []
    if config.asr.engine:
        engines_to_try.append(config.asr.engine)
    for fallback in ["bijian", "jianying", "whisper-api", "whisper-cpp"]:
        if fallback not in engines_to_try:
            engines_to_try.append(fallback)

    if vc_bin:
        for engine in engines_to_try:
            print(f"  -> Attempting ASR transcription with engine '{engine}'...")
            cmd = [
                vc_bin,
                "transcribe",
                str(audio_path),
                "-o",
                str(output_srt),
                "--format",
                "srt",
                "--asr",
                engine,
            ]
            if config.asr.language and config.asr.language != "auto":
                cmd.extend(["--language", config.asr.language])
            if config.asr.whisper_api_key:
                cmd.extend(["--whisper-api-key", config.asr.whisper_api_key])
            if config.asr.whisper_api_base:
                cmd.extend(["--whisper-api-base", config.asr.whisper_api_base])
            if config.asr.whisper_model:
                cmd.extend(["--whisper-model", config.asr.whisper_model])

            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
                if proc.returncode == 0 and output_srt.exists() and output_srt.stat().st_size > 0:
                    print(f"  ✓ ASR transcription succeeded with engine '{engine}'.")
                    return True
                print(f"  [WARN] Engine '{engine}' did not produce subtitles. Trying next...")
            except Exception as e:  # noqa: BLE001
                print(f"  [WARN] Engine '{engine}' error: {e}. Trying next...")

    # Fallback to Pure Python OpenAI Whisper API if configured
    if config.asr.whisper_api_key or config.llm.api_key or os.environ.get("OPENAI_API_KEY"):
        print("  -> Attempting pure Python Whisper API transcription...")
        if transcribe_with_whisper_api(audio_path, output_srt, config):
            print("  ✓ Pure Python Whisper API transcription succeeded.")
            return True

    if not output_srt.exists():
        output_srt.write_text("", encoding="utf-8")
    return False


def generate_subtitles(
    raw_material: RawMaterialResult,
    cooked_dir: Path,
    config: PorterConfig | None = None,
) -> SubtitleResult:
    """
    Execute Phase 2 (Subtitle Resolution) & Phase 3 (Translation & ASS Styling).

    Translation Strategy:
    1. LLM Translation (if configured);
    2. Free Translation: Bing translator first;
    3. Free Translation: Google translator fallback;
    4. Safety fallback to original text.
    """
    if config is None:
        config = get_default_config()

    cooked_dir = Path(cooked_dir)
    cooked_dir.mkdir(parents=True, exist_ok=True)

    raw_srt_path = raw_material.raw_dir / "subtitle.srt"
    raw_zh_srt_path = raw_material.raw_dir / "subtitle_zh.srt"
    used_asr = False

    # Step 1: Subtitle Check (YouTube Captions / ASR)
    if not raw_srt_path.exists() or raw_srt_path.stat().st_size == 0:
        run_asr_transcription(raw_material.audio_path, raw_srt_path, config)
        used_asr = True

    # Read base SRT
    base_srt_content = (
        raw_srt_path.read_text(encoding="utf-8", errors="replace") if raw_srt_path.exists() else ""
    )
    base_items = parse_srt(base_srt_content)
    translated_items: list[SubtitleItem] = []

    # Step 2: Check for Pre-extracted Chinese Subtitles (Zero-latency / Zero-cost fast path)
    if base_items and raw_zh_srt_path.exists() and raw_zh_srt_path.stat().st_size > 0:
        zh_content = raw_zh_srt_path.read_text(encoding="utf-8", errors="replace")
        zh_items = parse_srt(zh_content)
        if zh_items:
            print(
                "  ✓ Found pre-extracted Chinese subtitle (raw/subtitle_zh.srt). Aligning directly..."
            )
            aligned = align_bilingual_items(base_items, zh_items)
            merged_bilingual = merge_short_fragments(aligned)
            if any(it.target_text for it in merged_bilingual):
                translated_items = merged_bilingual
                base_items = [
                    SubtitleItem(
                        index=it.index,
                        start_ms=it.start_ms,
                        end_ms=it.end_ms,
                        source_text=it.source_text,
                        target_text="",
                    )
                    for it in merged_bilingual
                ]

    if base_items and not translated_items:
        # Merge short consecutive fragments into natural single lines
        base_items = merge_short_fragments(base_items)

    if base_items:
        # Update raw_srt_path with clean single-line cues
        cleaned_raw_srt = (
            "\n\n".join(
                f"{it.index}\n{it.start_srt} --> {it.end_srt}\n{it.source_text}"
                for it in base_items
            )
            + "\n"
        )
        raw_srt_path.write_text(cleaned_raw_srt, encoding="utf-8")

    if base_items and not translated_items:
        temp_translated_srt = cooked_dir / ".tmp_translated.srt"

        # 1. Try LLM Translation (if API Key provided)
        if config.llm.api_key:
            # 1.1 Direct LLM
            direct_items = translate_with_direct_llm(base_items, config)
            if direct_items and any(
                it.target_text and it.target_text != it.source_text for it in direct_items
            ):
                translated_items = direct_items

            # 1.2 VideoCaptioner LLM
            if not translated_items:
                success = translate_with_videocaptioner_cli(
                    raw_srt_path, temp_translated_srt, config
                )
                if success and temp_translated_srt.exists():
                    translated_content = temp_translated_srt.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    translated_items = parse_srt(translated_content)
                    temp_translated_srt.unlink(missing_ok=True)

        # 2. Free Translation: Try Bing Translator first
        if not translated_items or all(
            not it.target_text or it.target_text == it.source_text for it in translated_items
        ):
            print("  -> Attempting free translation with Bing Translator...")
            success_bing = translate_with_videocaptioner_free(
                raw_srt_path, temp_translated_srt, engine="bing"
            )
            if success_bing and temp_translated_srt.exists():
                translated_content = temp_translated_srt.read_text(
                    encoding="utf-8", errors="replace"
                )
                cand_items = parse_srt(translated_content)
                temp_translated_srt.unlink(missing_ok=True)
                if cand_items and any(
                    it.target_text and it.target_text != it.source_text for it in cand_items
                ):
                    translated_items = cand_items

        # 3. Free Translation: Try Google Translator fallback (VideoCaptioner / Pure Python HTTP)
        if not translated_items or all(
            not it.target_text or it.target_text == it.source_text for it in translated_items
        ):
            print("  -> Falling back to Google Translator...")
            success_google = translate_with_videocaptioner_free(
                raw_srt_path, temp_translated_srt, engine="google"
            )
            if success_google and temp_translated_srt.exists():
                translated_content = temp_translated_srt.read_text(
                    encoding="utf-8", errors="replace"
                )
                translated_items = parse_srt(translated_content)
                temp_translated_srt.unlink(missing_ok=True)
            else:
                # Built-in Pure Python Google HTTP Translator
                translated_items = translate_with_google_http(base_items, target_lang="zh-CN")

        # 4. Final safety check
        if not translated_items:
            translated_items = base_items

    # Step 3: Generate 4 cooked subtitle files
    bilingual_srt_path = cooked_dir / "subtitle_bilingual.srt"
    bilingual_ass_path = cooked_dir / "subtitle_bilingual.ass"
    zh_srt_path = cooked_dir / "subtitle_zh.srt"
    zh_ass_path = cooked_dir / "subtitle_zh.ass"

    # Write files with UTF-8 encoding
    bilingual_srt_text = generate_bilingual_srt(translated_items)
    bilingual_srt_path.write_text(bilingual_srt_text, encoding="utf-8")

    bilingual_ass_text = generate_bilingual_ass(translated_items, config.style)
    bilingual_ass_path.write_text(bilingual_ass_text, encoding="utf-8")

    zh_srt_text = generate_zh_srt(translated_items)
    zh_srt_path.write_text(zh_srt_text, encoding="utf-8")

    zh_ass_text = generate_zh_ass(translated_items, config.style)
    zh_ass_path.write_text(zh_ass_text, encoding="utf-8")

    return SubtitleResult(
        subtitle_bilingual_srt=bilingual_srt_path,
        subtitle_bilingual_ass=bilingual_ass_path,
        subtitle_zh_srt=zh_srt_path,
        subtitle_zh_ass=zh_ass_path,
        items=translated_items,
        used_asr=used_asr,
    )
