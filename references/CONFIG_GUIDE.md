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

- **`bijian`** (Default): Free Bilibili/Bijian speech recognition. No API Key required.
- **`jianying`**: Free CapCut/Jianying speech recognition. High accuracy for short sentences. No API Key required.
- **`whisper-api`**: OpenAI Whisper API or any OpenAI-compatible transcription endpoint.
- **`whisper-cpp`**: Local offline whisper.cpp engine.

---

## 5. Translation Engines & Subtitle Fast Path

1. **Pre-extracted Chinese Subtitles (Zero-Cost Fast Path)**: If the streaming platform provides a Chinese translation or auto-caption track (`zh-Hans`/`zh`), it is downloaded into `raw/subtitle_zh.srt` and aligned directly with `raw/subtitle.srt` with zero latency and zero API cost.
2. **LLM Translation**: When `llm.api_key` or `OPENAI_API_KEY` is present, performs contextual semantic translation and subtitle optimization.
3. **Bing Translator**: Free translation fallback.
4. **Google Translator**: Free translation fallback (VideoCaptioner + Pure Python HTTP fallback).
