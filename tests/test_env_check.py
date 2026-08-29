"""Tests for environment diagnostic module."""

import platform
from unittest.mock import patch

from porter_skill.env_check import (
    check_ffmpeg,
    check_llm,
    check_packages,
    check_python,
    get_linux_ffmpeg_guide,
    get_linux_python_guide,
    get_windows_ffmpeg_guide,
    get_windows_python_guide,
    run_doctor,
)


def test_check_python_current_env():
    """Verify python check succeeds on current >=3.10 python."""
    res = check_python()
    assert res.status is True
    assert "Python" in res.message


def test_check_python_mock_old_version():
    """Verify python check fails with appropriate guide when python < 3.10."""
    with patch("sys.version_info", (3, 9, 7)):
        res = check_python()
        assert res.status is False
        assert "< 3.10" in res.message
        assert res.guide is not None


def test_check_ffmpeg_current_env():
    """Verify ffmpeg check detects installed ffmpeg with libass."""
    res = check_ffmpeg()
    assert res.status is True
    assert "FFmpeg" in res.name


def test_check_ffmpeg_missing_binary():
    """Verify check fails when ffmpeg is missing."""
    with patch("shutil.which", return_value=None):
        res = check_ffmpeg()
        assert res.status is False
        assert "Missing binary" in res.message
        assert res.guide is not None


def test_check_packages_current_env():
    """Verify package checking for yt-dlp and videocaptioner."""
    res = check_packages()
    assert "Core Packages" in res.name
    # status should be True or Warning
    assert res.status is True or res.is_warning is True


def test_check_llm():
    """Verify LLM check."""
    res = check_llm()
    assert "LLM" in res.name


def test_doctor_guides_content():
    """Verify Windows and Linux guides contain required instructions."""
    win_ffmpeg = get_windows_ffmpeg_guide()
    assert "winget install Gyan.FFmpeg" in win_ffmpeg
    assert "Path" in win_ffmpeg

    win_py = get_windows_python_guide()
    assert "winget install Python.Python.3.12" in win_py
    assert "Add python.exe to PATH" in win_py

    linux_ffmpeg = get_linux_ffmpeg_guide()
    assert "apt install -y ffmpeg" in linux_ffmpeg
    assert "pacman -S ffmpeg" in linux_ffmpeg

    linux_py = get_linux_python_guide()
    assert "apt install -y python3" in linux_py


def test_run_doctor():
    """Verify run_doctor aggregates all checks."""
    report = run_doctor()
    assert len(report.results) >= 4
    assert report.system == platform.system()
