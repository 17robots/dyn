#!/usr/bin/env python3
"""docs/guide/std-index.md lists every public std declaration."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
raise SystemExit(subprocess.run([sys.executable, str(ROOT / 'tools/std-index.py'), '--check']).returncode)
