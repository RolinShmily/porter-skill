"""Tests for configuration loading, priority resolution, and persistence."""

import json

from porter_skill.config import (
    PorterConfig,
    find_candidate_config_paths,
    get_default_config,
    load_file_config,
    save_config_key,
)


def test_load_file_config_json(tmp_path):
    """Verify loading JSON configuration file."""
    config_file = tmp_path / "config.json"
    data = {
        "llm": {
            "api_key": "sk-test-key",
            "api_base": "https://api.test.com/v1",
            "model": "test-model",
        },
        "asr": {
            "engine": "whisper-api",
            "whisper_model": "whisper-1",
        },
    }
    config_file.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_file_config(config_file)
    assert loaded["llm"]["api_key"] == "sk-test-key"
    assert loaded["llm"]["model"] == "test-model"

    parsed_config = get_default_config(config_file)
    assert parsed_config.llm.api_key == "sk-test-key"
    assert parsed_config.llm.api_base == "https://api.test.com/v1"
    assert parsed_config.llm.model == "test-model"
    assert parsed_config.asr.engine == "whisper-api"


def test_save_config_key(tmp_path):
    """Verify saving configuration keys dynamically."""
    dest = tmp_path / "subdir" / "config.json"
    save_config_key("llm.api_key", "sk-saved-key", target_file=dest)
    save_config_key("llm.api_base", "https://api.deepseek.com/v1", target_file=dest)

    assert dest.is_file()
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["llm"]["api_key"] == "sk-saved-key"
    assert data["llm"]["api_base"] == "https://api.deepseek.com/v1"


def test_candidate_paths():
    """Verify candidate config paths are generated."""
    paths = find_candidate_config_paths()
    assert len(paths) >= 3
    assert any("config.json" in str(p) for p in paths)


def test_porter_config_defaults():
    """Verify default model fallback."""
    cfg = PorterConfig()
    assert cfg.style.zh_font_size == 52
    assert cfg.style.en_font_size == 34
    assert cfg.ffmpeg.audio_codec == "aac"


def test_load_cookies_config(tmp_path):
    """Verify cookies loading from config file."""
    config_file = tmp_path / "config.json"
    data = {
        "cookies_browser": "chrome",
        "cookies_file": "/path/to/cookies.txt",
    }
    config_file.write_text(json.dumps(data), encoding="utf-8")
    cfg = get_default_config(config_file)
    assert cfg.cookies_browser == "chrome"
    assert cfg.cookies_file == "/path/to/cookies.txt"
