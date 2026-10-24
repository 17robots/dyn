#!/usr/bin/env python3
"""Check narrow syntactic std API conventions, not semantic compliance.

Flag _into names, size/count companions of caller-storage APIs, pointer
parameters named out/output, and find names returning isize. Comments, contract
tags, ownership, and the behavior of function bodies are not checked.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def tokens(source):
    """Yield (text, original line); discard strings and nested comments."""
    i, line = 0, 1
    while i < len(source):
        start = i
        if source.startswith('//', i):
            end = source.find('\n', i)
            i = len(source) if end < 0 else end
        elif source.startswith('/*', i):
            depth = 1
            i += 2
            while i < len(source) and depth:
                if source.startswith('/*', i):
                    depth += 1
                    i += 2
                elif source.startswith('*/', i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            line += source[start:i].count('\n')
        elif source[i] in '\"\'':
            quote = source[i]
            i += 1
            while i < len(source):
                if source[i] == '\\':
                    i += 2
                elif source[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
            line += source[start:i].count('\n')
        elif source[i].isspace():
            if source[i] == '\n':
                yield '\n', line
                line += 1
            i += 1
        else:
            match = re.match(r'[A-Za-z_][A-Za-z_0-9]*', source[i:])
            i += len(match[0]) if match else 1
            yield source[start:i], line


def declarations(source):
    """Collect public names, top-level parameter tokens and return tokens."""
    stream = list(tokens(source))
    # Newlines matter only when delimiting a return type.
    def skip(i):
        while i < len(stream) and stream[i][0] == '\n':
            i += 1
        return i

    for start, (word, number) in enumerate(stream):
        if word != 'pub':
            continue
        i = skip(start + 1)
        raw = i < len(stream) and stream[i][0] == 'extern'
        if raw:
            i = skip(i + 1)
        if i >= len(stream) or stream[i][0] != 'fn':
            continue
        i = skip(i + 1)
        if i >= len(stream):
            continue
        name = stream[i][0]
        i = skip(i + 1)
        if i >= len(stream) or stream[i][0] != '(':
            continue
        i += 1
        depth, parameters, parameter = 1, [], []
        while i < len(stream) and depth:
            token = stream[i][0]
            i += 1
            if token == '(':
                depth += 1
            elif token == ')':
                depth -= 1
                if not depth:
                    break
            if token == ',' and depth == 1:
                parameters.append(parameter)
                parameter = []
            elif token != '\n':
                parameter.append(token)
        if depth:
            continue
        parameters.append(parameter)
        result = []
        i = skip(i)
        depth = 0
        while i < len(stream):
            token = stream[i][0]
            if depth == 0 and token in ('{', ';', '\n', 'pub', 'extern'):
                break
            if token in ('(', '['):
                depth += 1
            elif token in (')', ']'):
                depth -= 1
            if token != '\n':
                result.append(token)
            i += 1
        yield name, number, parameters, result, raw


def check(path):
    path = Path(path)
    problems = []
    declarations_found = list(declarations(path.read_text()))
    names = {name: parameters for name, _, parameters, _, _ in declarations_found}
    # Raw extern declarations must preserve the platform/C ABI, including out
    # pointers and signed results. This does not exempt ordinary wrappers in
    # these directories, or extern declarations elsewhere in std.
    raw_directory = any(path.parts[i:i + 2] in (('std', 'os'), ('std', 'c'))
                        for i in range(len(path.parts) - 1))
    for name, number, parameters, result, raw in declarations_found:
        if raw and raw_directory:
            continue
        if name.endswith('_into'):
            problems.append((number, f'{name}: caller-buffer form; take the arena first and drop _into'))
        for suffix in ('_size', '_count'):
            base = name[:-len(suffix)]
            if name.endswith(suffix) and base in names:
                if any(p[:2] in (['destination', ':'], ['storage', ':']) for p in names[base]):
                    problems.append((number, f'{name}: size companion of {base}; size the output inside it'))
        if any(p[:3] in (['output', ':', '*'], ['out', ':', '*']) for p in parameters):
            problems.append((number, f'{name}: out parameter; return a {{value, ok}} result'))
        if name.startswith('find') and result == ['isize']:
            problems.append((number, f'{name}: returns isize; return usize and the length on a miss'))
    return problems


def main():
    failures = 0
    for path in sorted((ROOT / 'std').rglob('*.dyn')):
        for number, message in check(path):
            print(f'{path.relative_to(ROOT)}:{number}: {message}')
            failures += 1
    if failures:
        return 1
    print('PASS std lint: no matches for the checked syntactic API heuristics')
    return 0


if __name__ == '__main__':
    sys.exit(main())
