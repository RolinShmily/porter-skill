#!/usr/bin/env python3
"""Convenience script for lightweight pre-flight link inspection with auto virtualenv re-execution."""

import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent

# 1. Automatically re-exec with local .venv python if available and not already using it
candidate_venvs = [
    SKILL_ROOT / ".venv" / "bin" / "python",
    Path.home() / ".pi" / "agent" / "skills" / "porter-skill" / ".venv" / "bin" / "python",
]

for venv_python in candidate_venvs:
    if venv_python.is_file() and sys.executable != str(venv_python):
        try:
            import pydantic  # noqa: F401
            import yt_dlp  # noqa: F401
        except ImportError:
            os.execv(str(venv_python), [str(venv_python), *sys.argv])
        break

# 2. Ensure skill repository root is on sys.path
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from porter_skill.config import get_default_config
from porter_skill.extractors.inspector import inspect_url


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python scripts/inspect_link.py <URL>")
        print("Runs 1-second pre-flight inspection on YouTube / X (Twitter) video links.")
        return 1

    url = sys.argv[1]
    cfg = get_default_config()
    res = inspect_url(url, cookies_file=cfg.cookies_file, cookies_browser=cfg.cookies_browser)
    print(res.format_summary())
    return 0 if res.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
