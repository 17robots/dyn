#!/usr/bin/env python3
"""src/guide.inc matches docs/guide, and `dyn guide` prints the brief, the
topic list and each topic."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
subprocess.run([sys.executable, str(ROOT / 'tools/gen-guide.py'), '--check'], check=True)
brief = subprocess.run([DYN, 'guide', '--brief'], capture_output=True, text=True, check=True).stdout
assert brief == (ROOT / 'docs/guide/brief.md').read_text(), 'brief differs from docs/guide/brief.md'
listing = subprocess.run([DYN, 'guide'], capture_output=True, text=True, check=True).stdout
assert listing.startswith(brief) and '- `rules`:' in listing, listing[-400:]
rules = subprocess.run([DYN, 'guide', 'rules'], capture_output=True, text=True, check=True).stdout
assert rules == (ROOT / 'docs/guide/rules.md').read_text()
missing = subprocess.run([DYN, 'guide', 'nonsense'], capture_output=True, text=True)
assert missing.returncode == 2 and "no guide topic 'nonsense'" in missing.stderr, missing.stderr
print('PASS guide: embedded pages match docs/guide; brief, topic list and topics print')
