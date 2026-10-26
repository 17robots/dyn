#!/usr/bin/env python3
"""Mutable JSON scalar loops: grammar, byte classification, offsets and rollback."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
ENV = dict(os.environ, DYN_SDK=os.environ.get('DYN_SDK', str(ROOT)))
ENV.pop('DYN_NO_SSA', None)


def quote(data):
    return '"' + ''.join('\\x%02x' % byte for byte in data) + '"'


valid = [b'0', b'-0', b'1', b'-1', b'10', b'1234567890', b'0.0', b'-0.0',
         b'1.25', b'1e0', b'1E+9', b'1e-9', b'-1.2E+3',
         b'18446744073709551615', b'-9223372036854775808',
         b'1e309', b'1e-309', b'9007199254740991.5']
# Exact cursor positions independently specified at the rejected syntax byte.
invalid = [(b'', 0), (b' ', 1), (b'-', 1), (b'+1', 0), (b'.1', 0),
           (b'01', 1), (b'-01', 2), (b'1.', 2), (b'1e', 2), (b'1e+', 3),
           (b'1e-', 3), (b'1.e2', 2), (b'1e.2', 2), (b'--1', 1),
           (b'1..0', 2), (b'1e++2', 3), (b'1 2', 2), (b'0x1', 1),
           (b'\t- \r', 4), (b' [1,] ', 4), (b'{"a":1,}', 7)]
grammar = re.compile(rb'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?')
assert all(grammar.fullmatch(raw) for raw in valid)
assert all(not grammar.fullmatch(raw) for raw, _ in invalid)
checks = []
for index, raw in enumerate(valid):
    checks.append('''if true {
      raw := %s
      result := json.parse(arena, raw)
      require(result.ok && result.root.kind == json.KindNumber, "numeric kind %d")
      require(mem.equal(result.root.text, raw), "numeric exact token %d")
      state := json.tokenizer(raw)
      token := json.token_next(&state)
      require(token.kind == json.TokenKind.Number && token.offset == 0 && mem.equal(token.text, raw) && state.offset == #len(raw), "numeric tokenizer %d")
      require(json.token_next(&state).kind == json.TokenKind.End, "numeric end")
      mem.arena_rewind(arena, mark)
    }''' % (quote(raw), index, index, index))
for index, (raw, offset) in enumerate(invalid):
    detail = 'TrailingData' if raw in (b'01', b'-01', b'1 2', b'0x1') else 'Syntax'
    checks.append('''if true {
      result := json.parse(arena, %s)
      require(!result.ok && result.offset == %d && result.kind == errors.Kind.InvalidInput && result.error == 0 && result.detail == json.ErrorKind.%s, "failure offset %d")
      require(json.is_missing(result.root) && result.root == &json.nil_value && mem.arena_mark(arena) == mark, "failure stub/rollback %d")
    }''' % (quote(raw), offset, detail, index, index))
# These malformed numeric tokens fail as a whole; tokenizer resumes one byte
# after their starts, rather than retaining number()'s internal failure cursor.
for raw in [b'-', b'1.', b'1e', b'1e+', b'1e-', b'1.e2', b'1e.2']:
    checks.append('''if true {
      state := json.tokenizer(%s)
      token := json.token_next(&state)
      require(token.kind == json.TokenKind.Invalid && token.offset == 0 && state.offset == 1 && #len(token.text) == 1, "invalid tokenizer progress")
    }''' % quote(raw))
source = '''use "std/encoding/json" json
use "std/mem" mem
use "std/errors" errors
fn require(ok: bool, message: []const u8) { if !ok { #panic(message) } }
fn main() {
  arena := mem.arena_create(0)
  defer mem.arena_release(arena)
  _ = mem.push_bytes_uninit(arena, 7)
  mark := mem.arena_mark(arena)
  for item in 0..256 {
    byte := #cast(u8, item)
    accepted := byte == 32 || byte == 9 || byte == 10 || byte == 13
    data: [5]u8 = [byte, 'n', 'u', 'l', 'l']
    result := json.parse(arena, data[..])
    require(result.ok == accepted, "all-byte whitespace acceptance")
    state := json.tokenizer(data[..])
    token := json.token_next(&state)
    if accepted {
      require(result.root.kind == json.KindNull && token.kind == json.TokenKind.Null && token.offset == 1 && state.offset == 5, "whitespace token advancement")
      ending := json.token_next(&state)
      require(ending.kind == json.TokenKind.End && ending.offset == 5 && state.offset == 5, "whitespace EOF advancement")
    } else {
      require(token.offset == 0 && json.is_missing(result.root) && mem.arena_mark(arena) == mark, "non-whitespace does not skip")
    }
    mem.arena_rewind(arena, mark)
    suffix: [5]u8 = ['n', 'u', 'l', 'l', byte]
    result = json.parse(arena, suffix[..])
    require(result.ok == accepted, "all-byte trailing whitespace")
    mem.arena_rewind(arena, mark)
    numeric: [2]u8 = ['1', byte]
    result = json.parse(arena, numeric[..])
    decimal := byte >= '0' && byte <= '9'
    require(result.ok == (accepted || decimal), "all-byte numeric continuation")
    if result.ok {
      expected_width: usize = 1
      if decimal { expected_width = 2 }
      require(#len(result.root.text) == expected_width, "numeric continuation width")
    }
    mem.arena_rewind(arena, mark)
  }
''' + '\n'.join(checks) + '''
  if true {
    whitespace := mem.push_bytes_uninit(arena, 262144)
    for i in 0..#len(whitespace) { whitespace[i] = 32 }
    whitespace[131071] = '0'
    hold := mem.arena_mark(arena)
    result := json.parse(arena, whitespace)
    require(result.ok && mem.equal(result.root.text, "0"), "large whitespace bounds")
    mem.arena_rewind(arena, hold)
    whitespace[131071] = 32
    result = json.parse(arena, whitespace)
    require(!result.ok && result.offset == #len(whitespace) && mem.arena_mark(arena) == hold, "all whitespace EOF bounds")
    mem.arena_rewind(arena, mark)
  }
  if true {
    digits := mem.push_bytes_uninit(arena, 65536)
    for i in 0..#len(digits) { digits[i] = '9' }
    hold := mem.arena_mark(arena)
    result := json.parse(arena, digits)
    require(result.ok && #len(result.root.text) == #len(digits) && mem.equal(result.root.text, digits), "large number bounds")
    mem.arena_rewind(arena, hold)
    digits[#len(digits)-1] = '.'
    result = json.parse(arena, digits)
    require(!result.ok && result.offset == #len(digits) && mem.arena_mark(arena) == hold, "large fraction EOF bounds")
    mem.arena_rewind(arena, mark)
  }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-json-parser-loops-') as temporary:
    work = Path(temporary)
    project = work / 'main'
    project.mkdir()
    (project / 'main.dyn').write_text(source)
    for mode in ('--debug', '--release'):
        for tree in (False, True):
            env = dict(ENV)
            if tree:
                env['DYN_NO_SSA'] = '1'
            output = work / ('out.exe' if os.name == 'nt' else 'out')
            subprocess.run([str(DYN), 'build', str(project), '--no-cache', '--quiet',
                            '--output', str(output), mode], cwd=ROOT, env=env,
                           check=True, timeout=120)
            subprocess.run([str(output)], env=env, check=True, timeout=30)
            print('PASS JSON parser loops', mode[2:], 'tree' if tree else 'default',
                  '256 byte classifications, numeric grammar, exact offsets, rollback and large bounds')
