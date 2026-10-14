#!/usr/bin/env python3
"""Fail closed when the grammar underpinning the depth certificate changes."""
import hashlib
from pathlib import Path
PINS={
    'src/scanner.c':'73e621e7656892f1af18dba5b98e24a9d68de84b133f64f32bb05cb6250a589e',
    'grammar.js':'52bf2cf661487d62966c394eb71366e68b275cc7c934951f6a400251e59cfb2a',
    'src/parser.c':'dae5cfc58e244e0289512e5fd48007120413fe7e6a280cd0c4139124995fceee',
}
def verify(root):
    for name, expected in PINS.items():
        actual=hashlib.sha256((Path(root)/name).read_bytes()).hexdigest()
        if actual!=expected:
            raise SystemExit(f'compact-first depth grammar pin mismatch: {name}; audit grammar and bound before updating')
if __name__=='__main__':
    import sys
    verify(sys.argv[1])
