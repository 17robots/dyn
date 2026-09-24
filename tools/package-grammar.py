#!/usr/bin/env python3
"""Compatibility entry point for the grammar-owned release bundle."""
from pathlib import Path
import os
import subprocess
root = Path(__file__).resolve().parents[1]
subprocess.run(['just', '--justfile', str(root/'tree-sitter-dyn/justfile'), 'package'], env=dict(os.environ, DIST=str(root/"build/dist")), check=True)
