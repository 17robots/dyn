#!/usr/bin/env python3
"""Word and line segmentation against the Unicode 17 conformance tests.

tests/data/unicode holds the WordBreakTest and LineBreakTest files from the
pinned Unicode 17 UCD.zip, compressed (Unicode-3.0, see LICENSE-UNICODE.txt).
"""
import gzip
import os
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
DATA = ROOT / 'tests/data/unicode'


def cases(text):
    for line in text.splitlines():
        line = line.split('#')[0].strip()
        if not line:
            continue
        tokens = line.split()
        codepoints, breaks = [], []
        for token in tokens[1:]:
            if token in ('÷', '×'):
                if token == '÷':
                    breaks.append(len(codepoints))
            else:
                codepoints.append(int(token, 16))
        yield codepoints, breaks


sources = {
    'word': gzip.decompress((DATA / 'WordBreakTest.txt.gz').read_bytes()).decode().splitlines(),
    'line': gzip.decompress((DATA / 'LineBreakTest.txt.gz').read_bytes()).decode().splitlines(),
}
assert any('17.0.0' in line for line in sources['line'][:3]), 'expected Unicode 17 test data'
SOURCE = '''use "std/unicode/text" text
use "std/mem" mem
use "std/io" io

const data: []const u8 = #load("cases.bin")

fn read_u32(at: usize) usize {
  return #cast(usize, data[at]) | #cast(usize, data[at + 1]) << 8 | #cast(usize, data[at + 2]) << 16 | #cast(usize, data[at + 3]) << 24
}

fn main() {
  arena := mem.arena_create(67108864)
  defer {
    mem.arena_release(&arena)
  }
  at: usize = 0
  for at < #len(data) {
    kind := data[at]
    length := read_u32(at + 1)
    sample := data[at + 5..at + 5 + length]
    at += 5 + length
    mark := mem.arena_mark(&arena)
    if kind == 0 {
      found := text.word_breaks(&arena, sample)
      for offset in found.value {
        _ = io.print(io.stdout(), "{} ", offset)
      }
    }
    else {
      found := text.line_breaks(&arena, sample)
      for entry in found.value {
        _ = io.print(io.stdout(), "{} ", entry.offset)
      }
    }
    _ = io.println(io.stdout(), "")
    mem.arena_rewind(&arena, mark)
  }
}
'''
all_cases = []
blob = bytearray()
for kind, name in ((0, 'word'), (1, 'line')):
    for codepoints, breaks in cases('\n'.join(sources[name])):
        encoded = ''.join(map(chr, codepoints)).encode('utf-8', 'surrogatepass')
        starts = [len(''.join(map(chr, codepoints[:i])).encode('utf-8', 'surrogatepass')) for i in range(len(codepoints) + 1)]
        all_cases.append((name, codepoints, [starts[b] for b in breaks if b != 0]))
        blob += struct.pack('<BI', kind, len(encoded)) + encoded
with tempfile.TemporaryDirectory(prefix='dyn-unicode-segment-') as directory:
    project = Path(directory)
    (project / 'main.dyn').write_text(SOURCE)
    (project / 'cases.bin').write_bytes(bytes(blob))
    output = project / 'program'
    subprocess.run([DYN, 'build', str(project), '--release', '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=300)
    lines = subprocess.run([str(output)], check=True, capture_output=True, text=True, timeout=300).stdout.split('\n')
assert len(lines) == len(all_cases) + 1 and lines[-1] == '', (len(lines), len(all_cases))
failures = {'word': 0, 'line': 0}
shown = 0
for (name, codepoints, expected), line in zip(all_cases, lines):
    got = [int(x) for x in line.split()]
    if got != expected:
        failures[name] += 1
        if shown < 12:
            shown += 1
            print('MISMATCH', name, ' '.join('%04X' % c for c in codepoints), 'expected', expected, 'got', got)
counts = {name: sum(1 for case in all_cases if case[0] == name) for name in failures}
assert not any(failures.values()), (failures, counts)
print(f'PASS unicode segmentation: {counts["word"]} word and {counts["line"]} line conformance cases')
