"""Subtitle translation, transcript optimization, and fallback orchestration module."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import json_repair
import requests
from openai import OpenAI

from porter_skill.config import PorterConfig
from porter_skill.subtitle.formatter import SubtitleItem, TranscriptSentence

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _get_videocaptioner_bin() -> str | None:
    """Resolve path to videocaptioner binary if available."""
    vc_bin = shutil.which("videocaptioner")
    if vc_bin:
        return vc_bin
    user_vc = Path.home() / ".local" / "bin" / "videocaptioner"
    if user_vc.is_file() and os.access(user_vc, os.X_OK):
        return str(user_vc)
    return None


def translate_sentences_with_google_http(
    sentences: list[TranscriptSentence],
    target_lang: str = "zh-CN",
) -> list[TranscriptSentence]:
    """
    Pure Python translation of full transcript sentences using Google Translate HTTP API.
    Uses browser User-Agent headers, rotating client IDs, and robust fallback.
    """
    if not sentences:
        return []

    url = "https://translate.googleapis.com/translate_a/single"
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    translated_sentences: list[TranscriptSentence] = []

    # Strategy 1: Batch translation with newline delimiter
    batch_size = 15
    delimiter = "\n=====\n"

    for i in range(0, len(sentences), batch_size):
        batch = sentences[i : i + batch_size]
        combined_text = delimiter.join(s.en_text for s in batch)

        batch_success = False
        for client_id in ["gtx", "dict-chrome-ex"]:
            params = {
                "client": client_id,
                "sl": "auto",
                "tl": target_lang,
                "dt": "t",
                "q": combined_text,
            }
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=12)
                if resp.status_code == 200:
                    data = resp.json()
                    translated_full = "".join([part[0] for part in data[0] if part and part[0]])
                    translated_lines = [line.strip() for line in translated_full.split("=====")]

                    if len(translated_lines) == len(batch):
                        for idx, s in enumerate(batch):
                            zh_text = (
                                translated_lines[idx].strip()
                                if translated_lines[idx].strip()
                                else s.en_text
                            )
                            translated_sentences.append(
                                TranscriptSentence(
                                    sentence_id=s.sentence_id,
                                    start_ms=s.start_ms,
                                    end_ms=s.end_ms,
                                    en_text=s.en_text,
                                    zh_text=zh_text,
                                    fragment_indices=s.fragment_indices,
                                )
                            )
                        batch_success = True
                        break
            except Exception:  # noqa: BLE001, S110
                pass

        if batch_success:
            continue

        # Strategy 2: Individual line-by-line fallback
        for s in batch:
            line_translated = ""
            for client_id in ["dict-chrome-ex", "gtx"]:
                try:
                    resp = requests.get(
                        url,
                        params={
                            "client": client_id,
                            "sl": "auto",
                            "tl": target_lang,
                            "dt": "t",
                            "q": s.en_text,
                        },
                        headers=headers,
                        timeout=8,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        line_translated = "".join(
                            [part[0] for part in data[0] if part and part[0]]
                        ).strip()
                        if line_translated:
                            break
                except Exception:  # noqa: BLE001, S110
                    pass

            translated_sentences.append(
                TranscriptSentence(
                    sentence_id=s.sentence_id,
                    start_ms=s.start_ms,
                    end_ms=s.end_ms,
                    en_text=s.en_text,
                    zh_text=line_translated or s.en_text,
                    fragment_indices=s.fragment_indices,
                )
            )

    return translated_sentences


def translate_with_google_http(
    items: list[SubtitleItem],
    target_lang: str = "zh-CN",
) -> list[SubtitleItem]:
    """Pure Python translation of SubtitleItems using Google Translate HTTP API."""
    if not items:
        return []
    dummy_sentences = [
        TranscriptSentence(
            sentence_id=it.index,
            start_ms=it.start_ms,
            end_ms=it.end_ms,
            en_text=it.source_text,
            zh_text=it.target_text,
        )
        for it in items
    ]
    trans_sents = translate_sentences_with_google_http(dummy_sentences, target_lang=target_lang)
    return [
        SubtitleItem(
            index=s.sentence_id,
            start_ms=s.start_ms,
            end_ms=s.end_ms,
            source_text=s.en_text,
            target_text=s.zh_text,
        )
        for s in trans_sents
    ]


def translate_sentences_with_mymemory_http(
    sentences: list[TranscriptSentence],
    target_lang: str = "zh-CN",
) -> list[TranscriptSentence]:
    """Pure Python translation fallback of full sentences using MyMemory Translated API."""
    if not sentences:
        return []

    url = "https://api.mymemory.translated.net/get"
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    translated_sentences: list[TranscriptSentence] = []

    for s in sentences:
        if not s.en_text.strip():
            translated_sentences.append(s)
            continue

        zh_text = ""
        try:
            params = {
                "q": s.en_text,
                "langpair": f"en|{target_lang}",
            }
            resp = requests.get(url, params=params, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                response_data = data.get("responseData", {})
                translated = response_data.get("translatedText", "")
                if translated and not translated.startswith("MYMEMORY WARNING"):
                    zh_text = translated.strip()
        except Exception:  # noqa: BLE001, S110
            pass

        translated_sentences.append(
            TranscriptSentence(
                sentence_id=s.sentence_id,
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                en_text=s.en_text,
                zh_text=zh_text or s.zh_text or s.en_text,
                fragment_indices=s.fragment_indices,
            )
        )

    return translated_sentences


def translate_with_mymemory_http(
    items: list[SubtitleItem],
    target_lang: str = "zh-CN",
) -> list[SubtitleItem]:
    """Pure Python translation fallback of SubtitleItems using MyMemory API."""
    if not items:
        return []
    dummy_sentences = [
        TranscriptSentence(
            sentence_id=it.index,
            start_ms=it.start_ms,
            end_ms=it.end_ms,
            en_text=it.source_text,
            zh_text=it.target_text,
        )
        for it in items
    ]
    trans_sents = translate_sentences_with_mymemory_http(dummy_sentences, target_lang=target_lang)
    return [
        SubtitleItem(
            index=s.sentence_id,
            start_ms=s.start_ms,
            end_ms=s.end_ms,
            source_text=s.en_text,
            target_text=s.zh_text,
        )
        for s in trans_sents
    ]


def translate_with_videocaptioner_free(
    input_srt: Path,
    output_srt: Path,
    engine: str = "bing",
) -> bool:
    """Attempt translation using videocaptioner CLI with free translators (bing or google)."""
    vc_bin = _get_videocaptioner_bin()
    if not vc_bin:
        return False

    cmd = [
        vc_bin,
        "subtitle",
        str(input_srt),
        "-o",
        str(output_srt),
        "--format",
        "srt",
        "--target-language",
        "zh-Hans",
        "--layout",
        "target-above",
        "--translator",
        engine,
        "--no-optimize",
        "--no-split",
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if proc.returncode == 0 and output_srt.exists() and output_srt.stat().st_size > 0:
            return True
    except Exception:  # noqa: BLE001, S110
        pass

    return False


def translate_sentences_with_direct_llm(
    sentences: list[TranscriptSentence],
    config: PorterConfig,
) -> list[TranscriptSentence]:
    """Translate and optimize transcript sentences directly using LLM API (OpenAI / DeepSeek / etc.)."""
    api_key = config.llm.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return []

    client = OpenAI(
        api_key=api_key,
        base_url=config.llm.api_base
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.openai.com/v1",
        timeout=30.0,
    )

    batch_size = 20
    translated_sentences: list[TranscriptSentence] = []

    for i in range(0, len(sentences), batch_size):
        batch = sentences[i : i + batch_size]
        batch_payload = [{"id": s.sentence_id, "en": s.en_text} for s in batch]

        prompt = (
            "You are a master bilingual subtitle translator and video localization expert.\n"
            "Below is a list of complete sentences extracted from a video transcript.\n"
            "Please translate each English sentence into natural, fluent, and concise Simplified Chinese (zh-Hans).\n"
            "Rules:\n"
            "1. Fix any remaining ASR / transcription / punctuation typos in the English sentence.\n"
            "2. Keep the Chinese translation idiomatic, colloquial, and synchronized with conversational pacing.\n"
            "3. Output MUST be a strict JSON array of objects with keys: 'id' (number), 'en' (refined English), 'zh' (Chinese translation).\n\n"
            f"Input transcript sentences:\n{json.dumps(batch_payload, ensure_ascii=False)}"
        )

        try:
            response = client.chat.completions.create(
                model=config.llm.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional video transcript translator. Respond ONLY in valid JSON array.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )
            content = response.choices[0].message.content or ""
            parsed = json_repair.loads(content)

            if isinstance(parsed, list):
                trans_map = {
                    entry.get("id"): (entry.get("en", ""), entry.get("zh", ""))
                    for entry in parsed
                    if isinstance(entry, dict)
                }
                for s in batch:
                    ref_en, ref_zh = trans_map.get(s.sentence_id, ("", ""))
                    translated_sentences.append(
                        TranscriptSentence(
                            sentence_id=s.sentence_id,
                            start_ms=s.start_ms,
                            end_ms=s.end_ms,
                            en_text=ref_en.strip() if ref_en.strip() else s.en_text,
                            zh_text=ref_zh.strip() if ref_zh.strip() else s.zh_text,
                            fragment_indices=s.fragment_indices,
                        )
                    )
            else:
                return []
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] Direct LLM request failed: {e}")
            return []

    return translated_sentences


def translate_with_direct_llm(
    items: list[SubtitleItem],
    config: PorterConfig,
) -> list[SubtitleItem]:
    """Translate and optimize subtitle items directly using LLM API."""
    if not items:
        return []
    dummy_sentences = [
        TranscriptSentence(
            sentence_id=it.index,
            start_ms=it.start_ms,
            end_ms=it.end_ms,
            en_text=it.source_text,
            zh_text=it.target_text,
        )
        for it in items
    ]
    trans_sents = translate_sentences_with_direct_llm(dummy_sentences, config)
    return [
        SubtitleItem(
            index=s.sentence_id,
            start_ms=s.start_ms,
            end_ms=s.end_ms,
            source_text=s.en_text,
            target_text=s.zh_text,
        )
        for s in trans_sents
    ]


def translate_with_videocaptioner_cli(
    input_srt: Path,
    output_srt: Path,
    config: PorterConfig,
) -> bool:
    """Attempt translation using videocaptioner CLI with LLM (optional)."""
    vc_bin = _get_videocaptioner_bin()
    if not vc_bin or not config.llm.api_key:
        return False

    cmd = [
        vc_bin,
        "subtitle",
        str(input_srt),
        "-o",
        str(output_srt),
        "--format",
        "srt",
        "--target-language",
        "zh-Hans",
        "--layout",
        "target-above",
        "--translator",
        "llm",
        "--api-key",
        config.llm.api_key,
    ]

    if config.llm.api_base:
        cmd.extend(["--api-base", config.llm.api_base])
    if config.llm.model:
        cmd.extend(["--model", config.llm.model])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if proc.returncode == 0 and output_srt.exists() and output_srt.stat().st_size > 0:
            return True
    except Exception:  # noqa: BLE001, S110
        pass

    return False
