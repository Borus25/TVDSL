#!/usr/bin/env python3
"""Запуск генератора и 50 демонстрационных тестов со слайдов."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
command = [
    sys.executable,
    str(ROOT / "funny_lexer.py"),
    "--out",
    str(ROOT / "dfa.json"),
    "--tests",
]
raise SystemExit(subprocess.call(command, cwd=str(ROOT)))