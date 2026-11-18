#!/usr/bin/env python3
"""src/prelude.inc is generated from src/prelude.dyn."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
raise SystemExit(subprocess.run([sys.executable, str(ROOT / 'tools/gen-prelude.py'), '--check']).returncode)
