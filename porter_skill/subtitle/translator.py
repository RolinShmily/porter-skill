"""Subtitle translation and semantic optimization module."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import json_repair
import requests
from openai import OpenAI

from porter_skill.config import PorterConfig
from porter_skill.subtitle.formatter import SubtitleItem


def _get_videocaptioner_bin() -> str | None:
    """Resolve path to videocaptioner binary if available."""
    vc_bin = shutil.which("videocaptioner")
    if vc_bin:
        return vc_bin
    user_vc = Path.home() / ".local" / "bin" / "videocaptioner"
    if user_vc.is_file() and os.access(user_vc, os.X_OK):
        return str(user_vc)
    return None


def translate_with_google_http(
    items: list[SubtitleItem],
    target_lang: str = "zh-CN",
) -> list[SubtitleItem]:
    """
    Pure Python translation using Google Translate HTTP API (zero external CLI dependencies).
    Batches texts to reduce HTTP round-trips.
    """
    if not items:
        return []

    url = "https://translate.googleapis.com/translate_a/single"
    translated_items: list[SubtitleItem] = []

    # Batch lines with a unique delimiter to translate in fewer HTTP requests
    batch_size = 20
    delimiter = "\n=====\n"

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        combined_text = delimiter.join(it.source_text for it in batch)

        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": target_lang,
            "dt": "t",
            "q": combined_text,
        }

        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                translated_full = "".join([part[0] for part in data[0] if part[0]])
                translated_lines = [line.strip() for line in translated_full.split("=====")]

                for idx, it in enumerate(batch):
                    zh_text = (
                        translated_lines[idx].strip()
                        if idx < len(translated_lines) and translated_lines[idx].strip()
                        else it.source_text
                    )
                    translated_items.append(
                        SubtitleItem(
                            index=it.index,
                            start_ms=it.start_ms,
                            end_ms=it.end_ms,
                            source_text=it.source_text,
                            target_text=zh_text,
                        )
                    )
                continue
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] Google HTTP batch translation warning: {e}")

        # Individual fallback if batch failed
        for it in batch:
            try:
                resp = requests.get(
                    url,
                    params={
                        "client": "gtx",
                        "sl": "auto",
                        "tl": target_lang,
                        "dt": "t",
                        "q": it.source_text,
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    zh_text = "".join([part[0] for part in data[0] if part[0]])
                    translated_items.append(
                        SubtitleItem(
                            index=it.index,
                            start_ms=it.start_ms,
                            end_ms=it.end_ms,
                            source_text=it.source_text,
                            target_text=zh_text.strip() or it.source_text,
                        )
                    )
                else:
                    translated_items.append(it)
            except Exception:  # noqa: BLE001
                translated_items.append(it)

    return translated_items


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


def translate_with_direct_llm(
    items: list[SubtitleItem],
    config: PorterConfig,
) -> list[SubtitleItem]:
    """Translate and optimize subtitle items directly using LLM API (OpenAI / DeepSeek / etc.)."""
    api_key = config.llm.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return []

    client = OpenAI(
        api_key=api_key,
        base_url=config.llm.api_base
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.openai.com/v1",
        timeout=20.0,
    )

    batch_size = 25
    translated_items: list[SubtitleItem] = []

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        batch_payload = [{"id": item.index, "text": item.source_text} for item in batch]

        prompt = (
            "You are a master bilingual subtitle translator and video localization expert.\n"
            "Translate the following subtitle lines into natural, concise Simplified Chinese (zh-Hans).\n"
            "Rules:\n"
            "1. Fix any minor ASR / transcription / punctuation typos.\n"
            "2. Keep the translation concise, colloquial, and synchronized with video pacing.\n"
            "3. Output MUST be a strict JSON array of objects with keys: 'id' (number), 'zh' (Chinese translation).\n\n"
            f"Input subtitles:\n{json.dumps(batch_payload, ensure_ascii=False)}"
        )

        try:
            response = client.chat.completions.create(
                model=config.llm.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional video subtitle localization translator. Respond ONLY in valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )
            content = response.choices[0].message.content or ""
            parsed = json_repair.loads(content)

            if isinstance(parsed, list):
                trans_map = {
                    entry.get("id"): entry.get("zh", "")
                    for entry in parsed
                    if isinstance(entry, dict)
                }
                for item in batch:
                    zh_text = trans_map.get(item.index, item.source_text)
                    translated_items.append(
                        SubtitleItem(
                            index=item.index,
                            start_ms=item.start_ms,
                            end_ms=item.end_ms,
                            source_text=item.source_text,
                            target_text=zh_text,
                        )
                    )
            else:
                return []
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] Direct LLM request failed: {e}")
            return []

    return translated_items


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
