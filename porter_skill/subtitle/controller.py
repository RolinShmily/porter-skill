"""Subtitle extraction, fallback orchestration, transcript generation, and styling controller."""

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
from openai import OpenAI

from porter_skill.config import PorterConfig, get_default_config
from porter_skill.extractors.base import RawMaterialResult
from porter_skill.subtitle.formatter import (
    SubtitleItem,
    TranscriptSentence,
    align_bilingual_items,
    generate_bilingual_ass,
    generate_bilingual_srt,
    generate_zh_ass,
    generate_zh_srt,
    is_cjk,
    merge_short_fragments,
    ms_to_srt_time,
    normalize_subtitle_items,
    parse_srt,
    reconstruct_sentences_from_fragments,
    save_transcript_json,
    save_transcript_txt,
    split_chinese_sentence_into_cues,
)
from porter_skill.subtitle.translator import (
    _get_videocaptioner_bin,
    translate_sentences_with_bing_http,
    translate_sentences_with_direct_llm,
    translate_sentences_with_google_http,
    translate_sentences_with_mymemory_http,
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
    transcript_json_path: Path | None = None
    transcript_txt_path: Path | None = None
    sentences: list[TranscriptSentence] = field(default_factory=list)
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


def transcribe_with_bcut(
    audio_path: Path,
    output_srt: Path,
    config: PorterConfig | None = None,
) -> bool:
    """Pure-Python free speech recognition via Bilibili BCut ASR API with multipart upload & polling."""
    if not audio_path.exists():
        return False
    try:
        audio_data = audio_path.read_bytes()
        if not audio_data:
            return False

        api_base = "https://member.bilibili.com/x/bcut/rubick-interface"
        headers = {
            "User-Agent": "Bilibili/1.0.0 (https://www.bilibili.com)",
            "Content-Type": "application/json",
        }

        # 1. Request upload session
        payload = json.dumps(
            {
                "type": 2,
                "name": audio_path.name,
                "size": len(audio_data),
                "ResourceFileType": audio_path.suffix.lstrip(".") or "wav",
                "model_id": "8",
            }
        )
        resp = requests.post(
            f"{api_base}/resource/create", data=payload, headers=headers, timeout=15
        )
        resp.raise_for_status()
        res_data = resp.json().get("data", {})
        if not res_data or "upload_urls" not in res_data:
            return False

        in_boss_key = res_data["in_boss_key"]
        resource_id = res_data["resource_id"]
        upload_id = res_data["upload_id"]
        upload_urls = res_data["upload_urls"]
        per_size = res_data["per_size"]
        clips = len(upload_urls)

        # 2. Upload chunks
        etags: list[str] = []
        for clip in range(clips):
            start = clip * per_size
            end = (clip + 1) * per_size
            part_resp = requests.put(
                upload_urls[clip], data=audio_data[start:end], headers=headers, timeout=30
            )
            part_resp.raise_for_status()
            etag = part_resp.headers.get("Etag")
            if etag:
                etags.append(etag)

        # 3. Commit upload
        commit_data = json.dumps(
            {
                "InBossKey": in_boss_key,
                "ResourceId": resource_id,
                "Etags": ",".join(etags),
                "UploadId": upload_id,
                "model_id": "8",
            }
        )
        commit_resp = requests.post(
            f"{api_base}/resource/create/complete", data=commit_data, headers=headers, timeout=15
        )
        commit_resp.raise_for_status()
        download_url = commit_resp.json().get("data", {}).get("download_url")
        if not download_url:
            return False

        # 4. Create task
        task_resp = requests.post(
            f"{api_base}/task",
            json={"resource": download_url, "model_id": "8"},
            headers=headers,
            timeout=15,
        )
        task_resp.raise_for_status()
        task_id = task_resp.json().get("data", {}).get("task_id")
        if not task_id:
            return False

        # 5. Poll task status
        for _ in range(60):
            q_resp = requests.get(
                f"{api_base}/task/result",
                params={"model_id": 7, "task_id": task_id},
                headers=headers,
                timeout=15,
            )
            q_resp.raise_for_status()
            q_data = q_resp.json().get("data", {})
            state = q_data.get("state")
            if state == 4:
                result_str = q_data.get("result", "{}")
                result = json.loads(result_str) if isinstance(result_str, str) else result_str
                utterances = result.get("utterances", [])
                srt_lines: list[str] = []
                for idx, u in enumerate(utterances, 1):
                    start_ms = int(u.get("start_time", 0))
                    end_ms = int(u.get("end_time", 0))
                    text = u.get("transcript", "").strip()
                    if not text:
                        continue
                    start_str = ms_to_srt_time(start_ms)
                    end_str = ms_to_srt_time(end_ms)
                    srt_lines.append(f"{idx}\n{start_str} --> {end_str}\n{text}\n")

                if srt_lines:
                    output_srt.write_text("\n".join(srt_lines), encoding="utf-8")
                    return True
                return False
            time.sleep(1)
    except Exception as e:  # noqa: BLE001
        print(f"  [WARN] Bcut ASR transcription error: {e}")

    return False


def transcribe_with_google_stt(
    audio_path: Path,
    output_srt: Path,
    config: PorterConfig,
) -> bool:
    """Pure-Python free speech recognition via Google Web Speech API with FFmpeg VAD interval chunking."""
    try:
        import speech_recognition as sr

        cmd = [
            "ffmpeg",
            "-i",
            str(audio_path),
            "-af",
            "silencedetect=noise=-30dB:d=0.4",
            "-f",
            "null",
            "-",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        silence_starts = [float(m) for m in re.findall(r"silence_start:\s*([\d.]+)", res.stderr)]
        silence_ends = [float(m) for m in re.findall(r"silence_end:\s*([\d.]+)", res.stderr)]

        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, check=False)
        total_dur = float(probe_res.stdout.strip()) if probe_res.stdout.strip() else 0.0

        intervals: list[tuple[float, float]] = []
        curr = 0.0
        for s_start, s_end in zip(silence_starts, silence_ends, strict=False):
            if s_start > curr + 0.3:
                intervals.append((curr, s_start))
            curr = s_end
        if curr < total_dur - 0.3:
            intervals.append((curr, total_dur))

        if not intervals:
            intervals = [(0.0, total_dur)]

        r = sr.Recognizer()
        srt_lines: list[str] = []
        idx = 1
        lang = "zh-CN" if config.asr.language in ["zh", "zh-CN"] else "en-US"

        for start_s, end_s in intervals:
            p_start = max(0.0, start_s - 0.05)
            p_end = min(total_dur, end_s + 0.35)
            dur = max(0.5, p_end - p_start)
            with sr.AudioFile(str(audio_path)) as source:
                audio_data = r.record(source, offset=p_start, duration=dur)
                try:
                    text = r.recognize_google(audio_data, language=lang)
                    if text and text.strip():
                        start_str = ms_to_srt_time(int(start_s * 1000))
                        end_str = ms_to_srt_time(int(p_end * 1000))
                        srt_lines.append(f"{idx}\n{start_str} --> {end_str}\n{text.strip()}\n")
                        idx += 1
                except Exception:  # noqa: BLE001, S110
                    pass

        if srt_lines:
            output_srt.write_text("\n".join(srt_lines), encoding="utf-8")
            return True
    except Exception as e:  # noqa: BLE001
        print(f"  [WARN] Google STT transcription warning: {e}")
    return False


def run_asr_transcription(
    audio_path: Path,
    output_srt: Path,
    config: PorterConfig,
) -> bool:
    """Run universal ASR speech recognition with pure Python fallbacks & optional CLI booster."""
    vc_bin = _get_videocaptioner_bin()

    # 1. If VideoCaptioner CLI is available and a specific engine was configured, try it first
    if vc_bin and config.asr.engine in ["bijian", "jianying", "whisper-cpp"]:
        print(f"  -> Attempting VideoCaptioner CLI ASR with engine '{config.asr.engine}'...")
        cmd = [
            vc_bin,
            "transcribe",
            str(audio_path),
            "-o",
            str(output_srt),
            "--format",
            "srt",
            "--asr",
            config.asr.engine,
        ]
        if config.asr.language and config.asr.language != "auto":
            cmd.extend(["--language", config.asr.language])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
            if proc.returncode == 0 and output_srt.exists() and output_srt.stat().st_size > 0:
                print(f"  ✓ VideoCaptioner CLI ASR succeeded with engine '{config.asr.engine}'.")
                return True
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] VideoCaptioner CLI error: {e}. Falling back...")

    # 2. Pure Python OpenAI Whisper API if API key configured
    if config.asr.whisper_api_key or config.llm.api_key or os.environ.get("OPENAI_API_KEY"):
        print("  -> Attempting pure Python Whisper API transcription...")
        if transcribe_with_whisper_api(audio_path, output_srt, config):
            print("  ✓ Pure Python Whisper API transcription succeeded.")
            return True

    # 3. Pure Python Bcut ASR (Free Bilibili Cloud Speech-to-Text)
    print("  -> Attempting pure Python Bcut (Bilibili) ASR transcription...")
    if transcribe_with_bcut(audio_path, output_srt, config):
        print("  ✓ Pure Python Bcut ASR transcription succeeded.")
        return True

    # 4. Pure Python Google Web Speech STT (Free Google Speech API + VAD)
    print("  -> Attempting pure Python Google Web Speech STT transcription...")
    if transcribe_with_google_stt(audio_path, output_srt, config):
        print("  ✓ Pure Python Google Web Speech STT succeeded.")
        return True

    # 5. Fallback to remaining VideoCaptioner CLI engines if available
    if vc_bin:
        for engine in ["jianying", "whisper-cpp"]:
            if engine == config.asr.engine:
                continue
            print(f"  -> Attempting VideoCaptioner fallback engine '{engine}'...")
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
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
                if proc.returncode == 0 and output_srt.exists() and output_srt.stat().st_size > 0:
                    print(f"  ✓ VideoCaptioner ASR succeeded with engine '{engine}'.")
                    return True
            except Exception:  # noqa: BLE001, S110
                pass

    if not output_srt.exists():
        output_srt.write_text("", encoding="utf-8")
    return False


def has_chinese_translation(items: list[SubtitleItem] | list[TranscriptSentence]) -> bool:
    """Check if translated subtitle items or sentences actually contain Chinese (CJK) characters."""
    for it in items:
        target = it.zh_text if isinstance(it, TranscriptSentence) else it.target_text
        if target and is_cjk(target):
            return True
    return False


def generate_subtitles(
    raw_material: RawMaterialResult,
    cooked_dir: Path,
    config: PorterConfig | None = None,
) -> SubtitleResult:
    """
    Execute Phase 2 (Subtitle Resolution & Transcript Reconstruction) & Phase 3 (Whole-sentence Translation & Phrased Subtitles).

    Workflow:
    1. Extract/Transcribe base subtitle items;
    2. Reconstruct fragments into full sentences (raw/transcript.json & raw/transcript.txt);
    3. Whole-sentence semantic translation (LLM -> Bing -> Google -> MyMemory);
    4. Phrase-level Chinese typesetting & proportional timestamp alignment;
    5. Generate clean, non-overlapping dual-language subtitle files in cooked/.
    """
    if config is None:
        config = get_default_config()

    cooked_dir = Path(cooked_dir)
    cooked_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = raw_material.raw_dir

    raw_srt_path = raw_dir / "subtitle.srt"
    raw_zh_srt_path = raw_dir / "subtitle_zh.srt"
    transcript_json_path = raw_dir / "transcript.json"
    transcript_txt_path = raw_dir / "transcript.txt"
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

    # Step 2: Check for Pre-extracted Chinese Subtitles (Zero-latency fast path)
    if base_items and raw_zh_srt_path.exists() and raw_zh_srt_path.stat().st_size > 0:
        zh_content = raw_zh_srt_path.read_text(encoding="utf-8", errors="replace")
        zh_items = parse_srt(zh_content)
        if zh_items:
            print(
                "  ✓ Found pre-extracted Chinese subtitle (raw/subtitle_zh.srt). Aligning directly..."
            )
            aligned = align_bilingual_items(base_items, zh_items)
            base_items = merge_short_fragments(aligned)

    if base_items and not any(it.target_text for it in base_items):
        base_items = merge_short_fragments(base_items)

    if base_items:
        # Standardize raw_srt_path with clean single-line base items
        cleaned_raw_srt = (
            "\n\n".join(
                f"{it.index}\n{it.start_srt} --> {it.end_srt}\n{it.source_text}"
                for it in base_items
            )
            + "\n"
        )
        raw_srt_path.write_text(cleaned_raw_srt, encoding="utf-8")

    # Step 3: Reconstruct raw fragments into full grammatical sentences for transcript
    sentences = reconstruct_sentences_from_fragments(base_items)

    # Step 4: Whole-sentence translation orchestration
    translated_sentences: list[TranscriptSentence] = []

    # If sentences already have Chinese translation from fast path:
    if any(has_chinese_translation([s]) for s in sentences):
        translated_sentences = sentences
    elif sentences:
        # 1. Try Direct LLM Translation
        if config.llm.api_key:
            print("  -> Translating whole sentences with LLM...")
            direct_sents = translate_sentences_with_direct_llm(sentences, config)
            if direct_sents and has_chinese_translation(direct_sents):
                translated_sentences = direct_sents

        # 2. Try Pure Python Bing (Copilot) HTTP translation (Free, zero-key, LLM-enhanced)
        if not translated_sentences or not has_chinese_translation(translated_sentences):
            print("  -> Translating whole sentences with Bing Translator (Free HTTP)...")
            bing_sents = translate_sentences_with_bing_http(sentences, target_lang="zh-Hans")
            if bing_sents and has_chinese_translation(bing_sents):
                translated_sentences = bing_sents

        # 3. Try VideoCaptioner CLI if available (LLM / Bing)
        if not translated_sentences or not has_chinese_translation(translated_sentences):
            temp_translated_srt = cooked_dir / ".tmp_translated.srt"
            if config.llm.api_key:
                success_vc = translate_with_videocaptioner_cli(
                    raw_srt_path, temp_translated_srt, config
                )
                if success_vc and temp_translated_srt.exists():
                    cand_items = parse_srt(
                        temp_translated_srt.read_text(encoding="utf-8", errors="replace")
                    )
                    temp_translated_srt.unlink(missing_ok=True)
                    if cand_items and has_chinese_translation(cand_items):
                        translated_sentences = reconstruct_sentences_from_fragments(cand_items)

            if not translated_sentences or not has_chinese_translation(translated_sentences):
                success_bing_vc = translate_with_videocaptioner_free(
                    raw_srt_path, temp_translated_srt, engine="bing"
                )
                if success_bing_vc and temp_translated_srt.exists():
                    cand_items = parse_srt(
                        temp_translated_srt.read_text(encoding="utf-8", errors="replace")
                    )
                    temp_translated_srt.unlink(missing_ok=True)
                    if cand_items and has_chinese_translation(cand_items):
                        translated_sentences = reconstruct_sentences_from_fragments(cand_items)

        # 4. Free Translation: Try Google Translator fallback (Pure Python HTTP)
        if not translated_sentences or not has_chinese_translation(translated_sentences):
            print("  -> Falling back to Google Translator HTTP API...")
            google_sents = translate_sentences_with_google_http(sentences, target_lang="zh-CN")
            if google_sents and has_chinese_translation(google_sents):
                translated_sentences = google_sents

        # 5. Free Translation: Try MyMemory API fallback
        if not translated_sentences or not has_chinese_translation(translated_sentences):
            print("  -> Falling back to MyMemory API Translator...")
            mymemory_sents = translate_sentences_with_mymemory_http(sentences, target_lang="zh-CN")
            if mymemory_sents and has_chinese_translation(mymemory_sents):
                translated_sentences = mymemory_sents

        # 5. Safety fallback to original sentences
        if not translated_sentences:
            translated_sentences = sentences

    # Step 5: Save transcript files to raw/
    if translated_sentences:
        save_transcript_json(translated_sentences, transcript_json_path)
        save_transcript_txt(translated_sentences, transcript_txt_path)
        print(f"  ✓ Transcript saved to {transcript_json_path.name} & {transcript_txt_path.name}")

    # Step 6: Expand transcript sentences into phrased, visually balanced SubtitleItems
    is_vertical = bool(raw_material.metadata and raw_material.metadata.is_vertical)
    max_cjk_len = 13 if is_vertical else 20
    play_res_x = (
        raw_material.metadata.width
        if raw_material.metadata and raw_material.metadata.width
        else (1080 if is_vertical else 1920)
    )
    play_res_y = (
        raw_material.metadata.height
        if raw_material.metadata and raw_material.metadata.height
        else (1920 if is_vertical else 1080)
    )

    style_for_render = config.style.model_copy()
    if is_vertical:
        style_for_render.bilingual_zh_margin_v = int(play_res_y * 0.12)
        style_for_render.bilingual_en_margin_v = int(play_res_y * 0.06)
        style_for_render.margin_v = int(play_res_y * 0.08)

    zh_semantic_cues: list[SubtitleItem] = []
    final_cues: list[SubtitleItem] = []
    cue_idx = 1
    for s in translated_sentences:
        target_text = s.zh_text.strip() if s.zh_text else s.en_text.strip()
        sub_cues = split_chinese_sentence_into_cues(
            en_text=s.en_text,
            zh_text=target_text,
            start_ms=s.start_ms,
            end_ms=s.end_ms,
            start_index=cue_idx,
            max_cjk_len=max_cjk_len,
        )
        for c in sub_cues:
            final_cues.append(c)
            zh_semantic_cues.append(c)
            cue_idx += 1

    final_cues = normalize_subtitle_items(final_cues)
    zh_semantic_cues = normalize_subtitle_items(zh_semantic_cues)
    en_acoustic_cues = normalize_subtitle_items(base_items)

    # Step 7: Generate 4 cooked subtitle files
    bilingual_srt_path = cooked_dir / "subtitle_bilingual.srt"
    bilingual_ass_path = cooked_dir / "subtitle_bilingual.ass"
    zh_srt_path = cooked_dir / "subtitle_zh.srt"
    zh_ass_path = cooked_dir / "subtitle_zh.ass"

    # SRT: Synchronized dual-language for external player compatibility
    bilingual_srt_text = generate_bilingual_srt(final_cues)
    bilingual_srt_path.write_text(bilingual_srt_text, encoding="utf-8")

    # ASS: Asynchronous dual-track independent layers + fade-in/fade-out for video burning
    bilingual_ass_text = generate_bilingual_ass(
        items=final_cues,
        style=style_for_render,
        play_res_x=play_res_x,
        play_res_y=play_res_y,
        zh_items=zh_semantic_cues,
        en_items=en_acoustic_cues,
    )
    bilingual_ass_path.write_text(bilingual_ass_text, encoding="utf-8")

    zh_srt_text = generate_zh_srt(zh_semantic_cues)
    zh_srt_path.write_text(zh_srt_text, encoding="utf-8")

    zh_ass_text = generate_zh_ass(
        zh_semantic_cues,
        style=style_for_render,
        play_res_x=play_res_x,
        play_res_y=play_res_y,
    )
    zh_ass_path.write_text(zh_ass_text, encoding="utf-8")

    return SubtitleResult(
        subtitle_bilingual_srt=bilingual_srt_path,
        subtitle_bilingual_ass=bilingual_ass_path,
        subtitle_zh_srt=zh_srt_path,
        subtitle_zh_ass=zh_ass_path,
        items=final_cues,
        transcript_json_path=transcript_json_path,
        transcript_txt_path=transcript_txt_path,
        sentences=translated_sentences,
        used_asr=used_asr,
    )
