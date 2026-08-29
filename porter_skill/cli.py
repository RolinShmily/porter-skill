"""Command-line interface for Video Porter Skill."""

import argparse
import sys
from pathlib import Path

from porter_skill import __version__
from porter_skill.config import (
    find_active_config_path,
    get_default_config,
    get_default_user_config_path,
    save_config_key,
)
from porter_skill.env_check import print_doctor_report, run_doctor
from porter_skill.pipeline.runner import run_pipeline


def _mask_secret(secret: str | None) -> str:
    if not secret:
        return "<not set>"
    if len(secret) <= 8:
        return "***"
    return f"{secret[:3]}...{secret[-4:]}"


def print_config_summary(config_file: str | None = None) -> None:
    """Print effective resolved configuration."""
    cfg = get_default_config(config_file)
    active_path = find_active_config_path()

    print("=" * 60)
    print(" Video Porter Configuration Status")
    print("=" * 60)
    print(f"Active Config File:  {active_path or '<none> (using defaults/env)'}")
    print(f"Default Save Path:   {get_default_user_config_path()}")
    print("-" * 60)
    print("LLM Settings:")
    print(f"  API Key:           {_mask_secret(cfg.llm.api_key)}")
    print(f"  API Base:          {cfg.llm.api_base or '<default https://api.openai.com/v1>'}")
    print(f"  Model:             {cfg.llm.model}")
    print("-" * 60)
    print("ASR (Speech-to-Text) Settings:")
    print(f"  Engine:            {cfg.asr.engine}")
    print(f"  Whisper API Key:   {_mask_secret(cfg.asr.whisper_api_key)}")
    print(f"  Whisper API Base:  {cfg.asr.whisper_api_base or '<default>'}")
    print(f"  Whisper Model:     {cfg.asr.whisper_model}")
    print("-" * 60)
    print("Subtitle Style Settings:")
    print(f"  Fonts:             ZH='{cfg.style.zh_font}', EN='{cfg.style.en_font}'")
    print(f"  Font Sizes:        ZH={cfg.style.zh_font_size}px, EN={cfg.style.en_font_size}px")
    print("=" * 60)


def main() -> int:
    """CLI entrypoint for porter-skill."""
    parser = argparse.ArgumentParser(
        prog="porter",
        description="Video Porter Skill: Automated stream media download, AI subtitle translation, and hardsub release pipeline.",
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="YouTube video URL to download and localize.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default="./output",
        help="Target output directory (default: ./output).",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run environment self-check and print diagnosis report with remediation guides.",
    )
    parser.add_argument(
        "--config",
        help="Specify path to a custom configuration file (JSON or TOML).",
    )
    parser.add_argument(
        "--config-show",
        action="store_true",
        help="Show currently resolved configuration settings and exit.",
    )
    parser.add_argument(
        "--config-set",
        metavar="KEY=VALUE",
        help="Set a configuration key in config.json (e.g. --config-set llm.api_key=sk-xxx) and exit.",
    )
    parser.add_argument(
        "--skip-burn",
        action="store_true",
        help="Skip burning hard subtitles into video, only download and generate subtitles.",
    )
    parser.add_argument(
        "--only-zh",
        action="store_true",
        help="Burn only pure Chinese hardsub video (video_zh.mp4).",
    )
    parser.add_argument(
        "--only-bilingual",
        action="store_true",
        help="Burn only bilingual hardsub video (video_bilingual.mp4).",
    )
    parser.add_argument(
        "--asr-engine",
        choices=["whisper-api", "bijian", "jianying", "whisper-cpp"],
        help="ASR speech recognition engine (default: whisper-api).",
    )
    parser.add_argument(
        "--llm-model",
        help="LLM model for subtitle translation (e.g. deepseek-chat, gpt-4o-mini).",
    )
    parser.add_argument(
        "--api-key",
        help="LLM API key (or set OPENAI_API_KEY).",
    )
    parser.add_argument(
        "--api-base",
        help="LLM API Base URL (or set OPENAI_BASE_URL).",
    )
    parser.add_argument(
        "--whisper-api-key",
        help="OpenAI Whisper API key for speech-to-text (or set WHISPER_API_KEY).",
    )
    parser.add_argument(
        "--whisper-api-base",
        help="Whisper API Base URL (or set WHISPER_API_BASE).",
    )
    parser.add_argument(
        "--whisper-model",
        help="Whisper model name (default: whisper-1).",
    )
    parser.add_argument(
        "--cookies",
        help="Path to cookies.txt file for authentication.",
    )
    parser.add_argument(
        "--cookies-from-browser",
        help="Browser name to load cookies from (e.g. chrome, edge, firefox, brave, safari).",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()

    if args.doctor:
        report = run_doctor()
        print_doctor_report(report)
        return 0 if report.passed else 1

    if args.config_show:
        print_config_summary(args.config)
        return 0

    if args.config_set:
        if "=" not in args.config_set:
            print("Error: --config-set must be in KEY=VALUE format (e.g. llm.api_key=sk-...)")
            return 1
        k, v = args.config_set.split("=", 1)
        dest = save_config_key(
            key_path=k.strip(),
            value=v.strip(),
            target_file=Path(args.config) if args.config else None,
        )
        print(f"✓ Configuration key '{k.strip()}' saved to {dest}")
        return 0

    if not args.url:
        parser.print_help()
        print("\nError: Please provide a video URL or run with --doctor / --config-show.")
        return 1

    config = get_default_config(args.config)
    if args.asr_engine:
        config.asr.engine = args.asr_engine
    if args.llm_model:
        config.llm.model = args.llm_model
    if args.api_key:
        config.llm.api_key = args.api_key
    if args.api_base:
        config.llm.api_base = args.api_base
    if args.whisper_api_key:
        config.asr.whisper_api_key = args.whisper_api_key
    if args.whisper_api_base:
        config.asr.whisper_api_base = args.whisper_api_base
    if args.whisper_model:
        config.asr.whisper_model = args.whisper_model
    if args.cookies:
        config.cookies_file = args.cookies
    if args.cookies_from_browser:
        config.cookies_browser = args.cookies_from_browser

    try:
        run_pipeline(
            url=args.url,
            output_dir=Path(args.output_dir),
            config=config,
            skip_burn=args.skip_burn,
            only_bilingual=args.only_bilingual,
            only_zh=args.only_zh,
        )
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"\n[ERROR] Pipeline failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
