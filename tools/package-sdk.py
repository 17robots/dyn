#!/usr/bin/env python3
"""Compatibility entry point; SDK packaging belongs to compiler."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parents[1]/'compiler/tools/package-sdk.py'), run_name='__main__')
