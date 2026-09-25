#!/usr/bin/env python3
"""Reject accidental parser regeneration with a different CLI version."""
from pathlib import Path
import json
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
expected = (root/'.tree-sitter-version').read_text().strip()
actual = subprocess.check_output([sys.argv[1] if len(sys.argv) > 1 else 'tree-sitter', '--version'], text=True).split()[1]
if actual != expected:
    raise SystemExit(f'Grammar generation requires tree-sitter {expected}; found {actual}')

package = json.loads((root/'package.json').read_text())
lock = json.loads((root/'package-lock.json').read_text())
assert package['devDependencies']['tree-sitter-cli'] == expected, 'package.json generator pin differs'
assert lock['packages']['']['devDependencies']['tree-sitter-cli'] == expected, 'npm importer pin differs'
assert lock['packages']['node_modules/tree-sitter-cli']['version'] == expected, 'npm generator pin differs'
assert 'tree-sitter-cli@' + expected + ':' in (root/'pnpm-lock.yaml').read_text(), 'pnpm generator pin differs'
