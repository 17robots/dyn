#!/usr/bin/env python3
"""Rewrite Dyn generics to the one-spelling syntax.

  struct Map($K: type, $V: type) -> struct Map(K, V)
  fn zero($T: type) T            -> fn zero(T: type) T
  fn eql(a: $T, b: T) bool       -> fn eql(a: $T, b: $T) bool

usage: tools/migrate-generics.py FILE...   (rewrites in place, prints changed files)

Two cases need a hand edit, and the compiler reports each one:
  - the old function-value form `f(T)` becomes `#instance(f, T)`;
  - `T: type` whose T a parameter's type also contains is inferred instead, and
    its callers drop the type argument.
"""
import re
import sys

DECL = re.compile(r'\b(struct|union|enum)(\s*\(\w+\))?\s+\w+\(')
FN = re.compile(r'\bfn\s+\w+\(')


def close_paren(text, open_at):
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i
    return -1


def split_top(params):
    pieces, depth, start = [], 0, 0
    for i, ch in enumerate(params):
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif ch == ',' and depth == 0:
            pieces.append(params[start:i])
            start = i + 1
    pieces.append(params[start:])
    return pieces


def rewrite_fn_params(params):
    pieces = split_top(params)
    inferred = set()
    for piece in pieces:
        if ':' in piece and not re.fullmatch(r'\s*\$?\w+\s*:\s*type\s*', piece):
            inferred.update(re.findall(r'\$(\w+)', piece.split(':', 1)[1]))
    out = []
    for piece in pieces:
        m = re.fullmatch(r'(\s*)\$(\w+)(\s*:\s*type\s*)', piece)
        if m:
            out.append(m.group(1) + m.group(2) + m.group(3))
            continue
        if ':' in piece and inferred:
            name, kind = piece.split(':', 1)
            for t in inferred:
                kind = re.sub(r'(?<![\$\w])' + re.escape(t) + r'\b', '$' + t, kind)
            piece = name + ':' + kind
        out.append(piece)
    return ','.join(out)


def rewrite(text):
    result, at = [], 0
    pattern = re.compile(DECL.pattern + '|' + FN.pattern)
    for m in pattern.finditer(text):
        if m.start() < at:
            continue
        open_at = m.end() - 1
        close = close_paren(text, open_at)
        if close < 0:
            continue
        params = text[open_at + 1:close]
        if '$' not in params:
            continue
        if m.group(0).startswith('fn'):
            params = rewrite_fn_params(params)
        else:
            params = re.sub(r'\$?(\w+)\s*:\s*type', r'\1', params)
        result.append(text[at:open_at + 1] + params)
        at = close
    result.append(text[at:])
    return ''.join(result)


if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
    print(__doc__.strip())
    sys.exit(0 if len(sys.argv) > 1 else 2)

for path in sys.argv[1:]:
    with open(path, encoding='utf-8') as f:
        text = f.read()
    new = rewrite(text)
    if new != text:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new)
        print(path)
