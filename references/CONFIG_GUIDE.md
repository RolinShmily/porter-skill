# Porter Skill Configuration Guide

This guide explains how to configure `porter-skill` for different runtime environments, ASR engines, LLM translators, and subtitle typography.

---

## 1. Configuration Hierarchy

Configurations are resolved using cascading priority (highest to lowest):

1. **CLI Arguments** (`--api-key`, `--api-base`, `--llm-model`, `--asr-engine`, `--config`)
2. **Specified Config File** (`--config <path>`)
3. **Project Root Config** (`./config.json` or `./porter_config.json`)
4. **Skill Global Config** (`~/.pi/agent/skills/porter-skill/config.json`)
5. **User Global Config** (`~/.config/porter-skill/config.json`)
6. **Environment Variables** (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `WHISPER_API_KEY`, etc.)
7. **VideoCaptioner Config** (`~/.config/videocaptioner/config.toml`)
8. **Built-in Defaults** (Free Google/Bing translation + Bijian/Jianying ASR)

---

## 2. JSON Configuration Schema

```json
{
  "llm": {
    "api_key": "sk-...",
    "api_base": "https://api.deepseek.com/v1",
    "model": "deepseek-chat"
  },
  "asr": {
    "engine": "bijian",
    "language": "auto",
    "whisper_api_key": "sk-...",
    "whisper_api_base": "https://api.openai.com/v1",
    "whisper_model": "whisper-1"
  },
  "style": {
    "zh_font": "Microsoft YaHei",
    "en_font": "Arial",
    "zh_font_size": 52,
    "en_font_size": 34,
    "zh_primary_color": "&H00FFFFFF",
    "en_primary_color": "&H0000FFFF",
    "outline_color": "&H00000000",
    "outline_width": 3.5,
    "shadow": 1.5,
    "margin_v": 30
  },
  "cookies_browser": "chrome",
  "cookies_file": ""
}
```

---

## 3. Cookie & Anti-Bot Configuration

- **`cookies_browser`**: Extract session cookies directly from your local browser (supports `"chrome"`, `"edge"`, `"firefox"`, `"brave"`, `"vivaldi"`, `"safari"`). Allows downloading age-restricted videos, member-only content, and prevents bot-detection 429 errors without exporting manual files.
- **`cookies_file`**: Path to a `cookies.txt` file (in Netscape format).

---

## 4. ASR Engine Options

- **`bijian` / `bcut`** (Default): Pure Python Bilibili/Bijian speech recognition. No API Key or external CLI required.
- **`google-stt`**: Pure Python Google Web Speech API with FFmpeg VAD interval detection. Zero-key, worldwide support.
- **`whisper-api`**: OpenAI Whisper API or any OpenAI-compatible transcription endpoint.
- **`jianying`**: Free CapCut/Jianying speech recognition (via VideoCaptioner CLI if available).
- **`whisper-cpp`**: Local offline whisper.cpp engine (via VideoCaptioner CLI if available).

---

## 5. Translation Engines & Subtitle Fast Path

1. **Pre-extracted Chinese Subtitles (Zero-Cost Fast Path)**: If the streaming platform provides a Chinese translation or auto-caption track (`zh-Hans`/`zh`), it is downloaded into `raw/subtitle_zh.srt` and aligned directly with `raw/subtitle.srt` with zero latency and zero API cost.
2. **LLM Translation**: When `llm.api_key` or `OPENAI_API_KEY` is present, performs contextual semantic translation and subtitle optimization.
3. **Bing Translator (Pure Python HTTP)**: Free Copilot/Bing translation with dynamic token retrieval. Excellent natural Chinese grammar and punctuation.
4. **Google Translator (Pure Python HTTP)**: Free translation fallback with multi-client rotation and browser User-Agent headers.
5. **MyMemory API**: Pure Python HTTP fallback using MyMemory API.
6. **VideoCaptioner CLI**: Optional external CLI translation booster when available.
7. **CJK Quality Assurance**: Built-in automated CJK detection checks if generated subtitles contain valid Chinese characters, automatically retrying fallbacks if untranslated.

---

## 7. Asynchronous Dual-Track Subtitles & Visual Transitions

`porter-skill` employs asynchronous dual-track ASS rendering for broadcast-grade subtitle presentation:

- **Asynchronous Dual-Track Independent Layers (`Layer 1: ZH`, `Layer 0: EN`)**: Chinese and English subtitles have completely decoupled timelines in ASS. The English subtitle follows natural spoken acoustic timing, while the Chinese subtitle adheres to semantic whole-sentence/phrase comprehension flow.
- **Fixed Vertical Margin Anchoring**: The English subtitle is anchored to `bilingual_en_margin_v: 35`, and the Chinese subtitle is anchored to `bilingual_zh_margin_v: 90`. Neither track suffers from vertical jump/jitter when the other track appears, refreshes, or disappears.
- **Smooth Alpha Fade Transitions (`\fad(120,120)`)**: Dialogue events include 120ms alpha fade-in and fade-out animations rendered natively by FFmpeg `libass`, eliminating jarring instant pop-ins while maintaining crisp readability.


`porter-skill` automatically detects host hardware capabilities and applies adaptive tuning:

- **Tier A (Hardware Acceleration)**: Detects NVIDIA NVENC (`h264_nvenc`), Intel QuickSync (`h264_qsv`), Apple VideoToolbox (`h264_videotoolbox`), or Linux VAAPI (`h264_vaapi`).
- **Tier B (Multi-Core CPU)**: Detected when CPU cores $\ge$ 8. Uses `libx264` with `preset="veryfast"` and `crf=18` for fast, broadcast-quality encoding.
- **Tier C (Lightweight / Edge CPU)**: Detected on low-power devices ($\le$ 4 cores, e.g. Intel N100, Raspberry Pi, entry-level VPS). Automatically switches `preset="ultrafast"` and `crf=22` for a 3x+ speedup with minimal visual impact.
- **Lossless Stream Copy (Remuxing)**: Media stream downloads are prioritized up to 1080p and standardized via lossless container remuxing (`-c copy`) whenever streams are already H.264/AAC MP4, eliminating unnecessary re-encoding in raw material preparation.
