#!/usr/bin/env python3
"""Compare language-server responses of two compilers over real sources.

Each source opens in its own session. The same requests run at sampled
positions (identifiers, member access, call arguments, line ends), then again
after deterministic edits that break or extend the source. Responses and
published diagnostics must match exactly unless a method is listed with
--ignore. Used to qualify parser migrations of the language server."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys

POSITION_METHODS = ['textDocument/hover', 'textDocument/definition', 'textDocument/typeDefinition',
                    'textDocument/references', 'textDocument/documentHighlight', 'textDocument/completion',
                    'textDocument/signatureHelp', 'textDocument/prepareRename', 'textDocument/selectionRange',
                    'textDocument/prepareCallHierarchy', 'textDocument/codeAction', 'textDocument/implementation']
DOCUMENT_METHODS = ['textDocument/documentSymbol', 'textDocument/foldingRange', 'textDocument/semanticTokens/full',
                    'textDocument/inlayHint', 'textDocument/formatting']


def frame(message):
    body = json.dumps(message).encode()
    return b'Content-Length: %d\r\n\r\n' % len(body) + body


def session(binary, root, messages, timeout):
    wire = b''.join(frame(m) for m in [
        {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {
            'rootUri': root.as_uri(), 'capabilities': {'general': {'positionEncodings': ['utf-16']}}}},
        {'jsonrpc': '2.0', 'method': 'initialized', 'params': {}}, *messages,
        {'jsonrpc': '2.0', 'id': 999999, 'method': 'shutdown', 'params': None},
        {'jsonrpc': '2.0', 'method': 'exit', 'params': None}])
    try:
        process = subprocess.run([str(binary), 'lsp'], input=wire, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'timeout': True}
    output, results, notifications = process.stdout, {}, []
    while output:
        header, output = output.split(b'\r\n\r\n', 1)
        size = int(header.split(b':', 1)[1])
        message = json.loads(output[:size])
        output = output[size:]
        if 'id' in message and 'method' not in message:
            results[message['id']] = message.get('result', message.get('error'))
        else:
            notifications.append(message)
    return {'status': process.returncode, 'results': results, 'notifications': notifications}


def positions(text, count, rng):
    lines = text.split('\n')
    candidates = []
    for row, line in enumerate(lines):
        for match in re.finditer(r'[A-Za-z_][A-Za-z0-9_]*', line):
            candidates.append((row, match.start()))
            candidates.append((row, match.end()))
        for match in re.finditer(r'[.(,]', line):
            candidates.append((row, match.end()))
        candidates.append((row, len(line)))
    rng.shuffle(candidates)
    return sorted(set(candidates[:count]))


def edits(text, rng):
    lines = text.split('\n')
    result = []
    for _ in range(3):
        row = rng.randrange(len(lines))
        line = lines[row]
        kind = rng.choice(['delete', 'dot', 'truncate', 'call'])
        if kind == 'delete' and line:
            column = rng.randrange(len(line))
            new = line[:column] + line[column + 1:]
        elif kind == 'dot':
            column = len(line)
            new = line + '.'
        elif kind == 'truncate' and line:
            column = rng.randrange(len(line))
            new = line[:column]
        else:
            column = len(line)
            new = line + ' foo('
        result.append((row, line, new, min(column, len(new))))
    return result


def requests(uri, points, start_id):
    messages, ident = [], start_id
    for method in DOCUMENT_METHODS:
        params = {'textDocument': {'uri': uri}}
        if method == 'textDocument/inlayHint':
            params['range'] = {'start': {'line': 0, 'character': 0}, 'end': {'line': 100000, 'character': 0}}
        if method == 'textDocument/formatting':
            params['options'] = {'tabSize': 2, 'insertSpaces': True}
        messages.append({'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params})
        ident += 1
    for row, column in points:
        for method in POSITION_METHODS:
            point = {'line': row, 'character': column}
            params = {'textDocument': {'uri': uri}, 'position': point}
            if method == 'textDocument/references':
                params['context'] = {'includeDeclaration': True}
            if method == 'textDocument/selectionRange':
                params = {'textDocument': {'uri': uri}, 'positions': [point]}
            if method == 'textDocument/codeAction':
                params = {'textDocument': {'uri': uri}, 'range': {'start': point, 'end': point},
                          'context': {'diagnostics': []}}
            messages.append({'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params})
            ident += 1
    return messages, ident


def first_difference(left, right):
    """The first differing list element (with its index), else whole values."""
    if isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys():
        for key in left:
            if left[key] != right[key]:
                a, b = first_difference(left[key], right[key])
                return f'{key}: {a}', f'{key}: {b}'
    if isinstance(left, list) and isinstance(right, list):
        for i, (a, b) in enumerate(zip(left, right)):
            if a != b:
                return f'[{i}/{len(left)}] {json.dumps(a)[:400]}', f'[{i}/{len(right)}] {json.dumps(b)[:400]}'
        return f'length {len(left)}', f'length {len(right)}'
    return json.dumps(left)[:600], json.dumps(right)[:600]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--corpus', action='append', required=True, type=Path)
    parser.add_argument('--positions', type=int, default=12)
    parser.add_argument('--files', type=int, default=0, help='limit sources per corpus (0: all)')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--ignore', action='append', default=[], help='method whose results may differ')
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--show', type=int, default=8)
    args = parser.parse_args()
    differences, shown, compared = Counter(), 0, 0
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(2)
    for corpus in args.corpus:
        corpus = corpus.resolve()
        files = sorted(p for p in corpus.rglob('*.dyn') if 'build' not in p.relative_to(corpus).parts)
        if args.files:
            files = files[:args.files]
        for path in files:
            rng = random.Random(f'{args.seed}:{path}')
            text = path.read_text(errors='replace')
            uri = path.as_uri()
            messages = [{'jsonrpc': '2.0', 'method': 'textDocument/didOpen', 'params': {'textDocument': {
                'uri': uri, 'languageId': 'dyn', 'version': 1, 'text': text}}}]
            batch, ident = requests(uri, positions(text, args.positions, rng), 1)
            messages += batch
            phases = {m['id']: 'original' for m in batch}
            version = 1
            for row, old, new, column in edits(text, rng):
                version += 1
                messages.append({'jsonrpc': '2.0', 'method': 'textDocument/didChange', 'params': {
                    'textDocument': {'uri': uri, 'version': version}, 'contentChanges': [{
                        'range': {'start': {'line': row, 'character': 0},
                                  'end': {'line': row, 'character': len(old)}}, 'text': new}]}})
                batch, ident = requests(uri, [(row, column)], ident)
                messages += batch
                phases.update({m['id']: f'edit{version - 1}' for m in batch})
            outputs = list(pool.map(lambda binary: session(binary, corpus, messages, args.timeout),
                                    (args.reference, args.candidate)))
            compared += 1
            if outputs[0].get('timeout') or outputs[1].get('timeout') or outputs[0]['status'] != outputs[1]['status']:
                differences['session'] += 1
                print(f'SESSION {path}: {[o.get("timeout") or o.get("status") for o in outputs]}')
                continue
            methods = {m['id']: m['method'] for m in messages if 'id' in m}
            for key in sorted(set(outputs[0]['results']) | set(outputs[1]['results'])):
                method = methods.get(key, 'shutdown')
                left, right = outputs[0]['results'].get(key), outputs[1]['results'].get(key)
                if left != right and method not in args.ignore:
                    differences[(method, phases.get(key, '?') == 'original')] += 1
                    if shown < args.show:
                        shown += 1
                        request = next(m for m in messages if m.get('id') == key)
                        print(f'DIFF {method} {phases.get(key)} {path}:{json.dumps(request.get("params", {}).get("position"))}')
                        print('  reference:', first_difference(left, right)[0])
                        print('  candidate:', first_difference(left, right)[1])
            if outputs[0]['notifications'] != outputs[1]['notifications'] and \
                    'publishDiagnostics' not in args.ignore:
                differences['publishDiagnostics'] += 1
                if shown < args.show:
                    shown += 1
                    print(f'DIFF publishDiagnostics {path}')
                    for left, right in zip(outputs[0]['notifications'], outputs[1]['notifications']):
                        if left != right:
                            print('  reference:', json.dumps(left)[:600])
                            print('  candidate:', json.dumps(right)[:600])
                            break
    summary = {f'{m}{"" if original else " (edited)"}': n for (m, original), n in
               ((k if isinstance(k, tuple) else (k, True), v) for k, v in differences.items())}
    print(f'{compared} sources; differences: {summary or "none"}')
    return 1 if differences else 0


if __name__ == '__main__':
    sys.exit(main())
