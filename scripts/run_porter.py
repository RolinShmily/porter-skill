#!/usr/bin/env python3
"""Convenience runner script for porter-skill."""

import sys
from pathlib import Path

# Ensure skill repository root is on sys.path
SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from porter_skill.cli import main

if __name__ == "__main__":
    sys.exit(main())
