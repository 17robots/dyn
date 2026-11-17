#!/usr/bin/env python3
"""The agent evaluation tasks stay correct: every reference solution in
tools/agent-eval builds with the current compiler and passes its grader."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if sys.platform != 'linux' or os.geteuid() == 0:
    print('SKIP agent evaluation references: graders need Linux and a non-root user')
    raise SystemExit(0)
raise SystemExit(subprocess.run([sys.executable, str(ROOT / 'tools/agent-eval/eval.py'), '--reference']).returncode)
