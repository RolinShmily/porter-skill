#!/usr/bin/env python3
"""Convenience runner script for porter-skill with auto virtualenv re-execution."""

import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent

# 1. Automatically re-exec with local .venv python if available and not already using it
candidate_venvs = [
    SKILL_ROOT / ".venv" / "bin" / "python",
    Path.home() / ".pi" / "agent" / "skills" / "porter-skill" / ".venv" / "bin" / "python",
]

# If dependencies are missing, look for candidate venvs or auto-bootstrap
try:
    import pydantic  # noqa: F401
    import requests  # noqa: F401
    import yt_dlp  # noqa: F401
except ImportError:
    for venv_python in candidate_venvs:
        if venv_python.is_file() and sys.executable != str(venv_python):
            os.execv(str(venv_python), [str(venv_python), *sys.argv])

    # Auto-bootstrap if setup_env.sh exists and .venv is not present
    setup_script = SKILL_ROOT / "scripts" / "setup_env.sh"
    if setup_script.is_file() and not (SKILL_ROOT / ".venv").exists():
        print("  -> Initializing porter-skill virtual environment on first run...")
        import subprocess

        subprocess.run(["bash", str(setup_script)], cwd=str(SKILL_ROOT), check=False)
        local_venv = SKILL_ROOT / ".venv" / "bin" / "python"
        if local_venv.is_file():
            os.execv(str(local_venv), [str(local_venv), *sys.argv])

# 2. Ensure skill repository root is on sys.path
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from porter_skill.cli import main

if __name__ == "__main__":
    sys.exit(main())
