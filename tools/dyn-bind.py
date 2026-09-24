#!/usr/bin/env python3
"""Compatibility entry point/import; implementation ships with compiler."""
import runpy
from pathlib import Path
globals().update(runpy.run_path(str(Path(__file__).resolve().parents[1]/'compiler/tools/dyn-bind.py'), run_name=__name__))
