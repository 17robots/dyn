#!/usr/bin/env python3
"""Read source-like Python string literals without importing or executing tests.

Each result records the Python file, literal-start byte offset, 1-based Python
line number, and decoded string contents. Offsets refer to the enclosing Python
file, not to a byte-for-byte source mapping inside escaped strings. Dynamic
f-strings and runtime concatenations are not evaluated. Invalid/incomplete Dyn
strings remain in the result so callers can compare parser rejection as well as
acceptance. A matching literal is a syntax probe, not necessarily a runnable test.
"""
import ast
from pathlib import Path
import re

SOURCE_HINT = re.compile(r'\b(?:fn|struct)\s|#target\s*\(|#link\s*\(')


def extract_test_sources(compiler_root):
    """Return provenance-bearing source candidates from tests/**/*.py."""
    compiler_root = Path(compiler_root).resolve()
    result = []
    for path in sorted((compiler_root / 'tests').rglob('*.py')):
        text = path.read_text(encoding='utf-8')
        module = ast.parse(text, filename=str(path))
        lines = text.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line.encode('utf-8')))
        constants = [node for node in ast.walk(module)
                     if isinstance(node, ast.Constant)
                     and isinstance(node.value, str)
                     and SOURCE_HINT.search(node.value)]
        for node in sorted(constants, key=lambda node: (node.lineno, node.col_offset)):
            result.append({'path': str(path), 'source': node.value,
                           'line': node.lineno,
                           'offset': offsets[node.lineno - 1] + node.col_offset})
    return result


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('compiler_root', nargs='?', type=Path,
                        default=Path(__file__).resolve().parents[2])
    print(json.dumps(extract_test_sources(parser.parse_args().compiler_root)))
