#!/usr/bin/env python3
"""Seeded compiler + recovering/incremental editor differential fuzzing.
Failures retain source, edit sequence, seed, and diagnostics for reproduction.
"""
import json
import os
from pathlib import Path
import random
import runpy
import subprocess
import tempfile

h = runpy.run_path('tests/lsp-contracts.py')
seed = int(os.environ.get('DYN_FUZZ_SEED', '1'))
count = int(os.environ.get('DYN_FUZZ_CASES', '64'))
rng = random.Random(seed)
base = 'use "./helper" h\nconst answer: i32 = 42\nfn main() { value := h.answer()\n _ = value + answer\n}\n'
tokens = ['use', '"', '"std/', 'const', 'alias', 'fn', '{', '}', ':', '=', ':=',
          '/*', '*/', '// note\n', '"🚀"', '\n', ' ', 'answer', '(', ')', '.']
texts = ['', 'use "', 'use "std/', 'use "./helper"\nconst answer: i32 = 42\nfn main() {}',
         'use "./helper" h\nconst other: i32 = h.answer()\nfn main() {}',
         'use "." self\nfn main() {}', 'fn main() { alias:r }', base]
for _ in range(count):
    start = rng.randrange(len(base) + 1)
    end = rng.randrange(start, min(len(base), start + 16) + 1)
    texts.append(base[:start] + ''.join(rng.choices(tokens, k=rng.randrange(1, 5))) + base[end:])
    texts.append(base)  # Recovery must converge after every malformed version.

def point(text, offset):
    prefix = text[:offset]
    return {'line': prefix.count('\n'),
            'character': len(prefix.rsplit('\n', 1)[-1].encode('utf-16-le')) // 2}

artifact = {'seed': seed, 'texts': texts}
try:
    with tempfile.TemporaryDirectory(prefix='dyn-frontend-fuzz-') as directory:
        root = Path(directory)
        (root / 'helper').mkdir()
        (root / 'helper/module.dyn').write_text('pub fn answer() i32 { return 42 }\n')
        path = root / 'main.dyn'
        for number, text in enumerate(texts):
            path.write_text(text)
            for command in ('check', 'build'):
                args = [h['DYN'], command, str(root), '--quiet', '--no-cache']
                if command == 'build': args += ['--no-link', '--output', str(root / 'fuzz.o')]
                result = subprocess.run(args, capture_output=True, text=True, timeout=10)
                artifact.update(case=number, command=command, stderr=result.stderr)
                assert result.returncode in (0, 1), (number, command, result.returncode, result.stderr)
                assert not any(word in result.stderr for word in ('Sanitizer', 'runtime error:')), result.stderr
                if text == base: assert result.returncode == 0, result.stderr
        path.write_text(base)
        outputs = []
        for incremental in (True, False):
            messages = [h['opened'](path, '')]
            previous = ''
            for version, text in enumerate(texts, 2):
                if incremental:
                    start = 0
                    while start < min(len(previous), len(text)) and previous[start] == text[start]: start += 1
                    old_end, new_end = len(previous), len(text)
                    while old_end > start and new_end > start and previous[old_end - 1] == text[new_end - 1]:
                        old_end -= 1; new_end -= 1
                    change = {'range': {'start': point(previous, start), 'end': point(previous, old_end)},
                              'text': text[start:new_end]}
                else: change = {'text': text}
                messages.append(h['request']('textDocument/didChange', {
                    'textDocument': {'uri': path.as_uri(), 'version': version}, 'contentChanges': [change]}))
                for index, method in enumerate(('textDocument/documentSymbol', 'textDocument/semanticTokens/full')):
                    messages.append(h['request'](method, {'textDocument': {'uri': path.as_uri()}}, version * 2 + index))
                previous = text
            artifact.update(incremental=incremental, messages=messages)
            responses, stderr = h['run_lsp'](messages)
            assert not stderr, stderr
            outputs.append(({r['id']: r.get('result', r.get('error')) for r in responses if isinstance(r.get('id'), int) and 4 <= r['id'] < 999},
                            [r['params'] for r in responses if r.get('method') == 'textDocument/publishDiagnostics']))
        assert outputs[0] == outputs[1], 'incremental/full editor results differ'
except Exception:
    failure = Path('build/frontend-fuzz')
    failure.mkdir(parents=True, exist_ok=True)
    path = failure / f'failure-{seed}.json'
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
    print(f'Fuzz failure saved: {path}')
    raise
print(f'Frontend fuzz passed: seed={seed}, {len(texts)} versions, compiler check/build + incremental/full LSP')
