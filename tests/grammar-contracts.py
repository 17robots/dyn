#!/usr/bin/env python3
"""Compatibility entry point for grammar-owned workspace checks."""
from pathlib import Path
import os
import subprocess
root = Path(__file__).resolve().parents[1]
subprocess.run(['just', '--justfile', str(root/'tree-sitter-dyn/justfile'), 'check-workspace'], env=dict(os.environ, WORKSPACE=str(root)), check=True)
