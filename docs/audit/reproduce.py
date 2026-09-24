#!/usr/bin/env python3
"""Compatibility entry point for the audit's now-gating regression suite."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[2] / 'tests/audit-contracts.py'), run_name='__main__')
