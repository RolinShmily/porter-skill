#!/usr/bin/env bash
# Environment setup helper for porter-skill
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "=== Setting up Porter Skill Python Environment ==="

if command -v uv &>/dev/null; then
    echo "Found uv, creating virtual environment with uv..."
    uv venv .venv
    source .venv/bin/activate
    uv pip install -e ".[dev]"
else
    echo "Creating virtual environment with python3 -m venv..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"
fi

echo "=== Environment Ready! ==="
echo "Run diagnostics with: python -m porter_skill --doctor"
