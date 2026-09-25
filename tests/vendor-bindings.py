#!/usr/bin/env python3
"""Compile generated bindings against a C oracle, including tricky ABI cases."""
import os
import re
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
CC = shlex.split(os.environ.get('CC', 'cc'))
CLANG = os.environ.get('DYN_BIND_CLANG', os.environ.get('CLANG', 'clang'))


def run(command, env):
    result = subprocess.run(list(map(str, command)), env=env, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, (command, result.returncode, result.stdout, result.stderr)
    return result


with tempfile.TemporaryDirectory(prefix='dyn-raw-bind-test-') as directory:
    work = Path(directory)
    (work / 'fixture.h').write_text(r'''
#include <stdint.h>
#include <stdarg.h>
typedef struct T_Nested { struct { int value; } *items; } T_Nested;
typedef unsigned char T_Bytes[8];
typedef struct T_Pair { int x; double y; } T_Pair;
typedef union T_Union { uint64_t word; T_Bytes bytes; const char *view; } T_Union;
typedef struct __attribute__((packed)) T_Packed { char tag; uint64_t word; T_Bytes bytes; } T_Packed;
typedef struct T_Aligned { int tag; _Alignas(8) char bytes[13]; } T_Aligned;
typedef struct T_Bits { unsigned low:3; signed high:5; } T_Bits;
typedef T_Pair (*T_Callback)(T_Pair);
T_Pair T_pair(int x);
T_Pair T_apply(T_Callback callback, T_Pair input);
void T_get_callback(T_Callback *out);
typedef int T_Function(int);
T_Function *T_get_function(void);
int (*T_callback(void))(int);
extern int T_count;
extern const char *T_view;
void T_text(const char **out);
void T_log_set(void (*callback)(void*, int, const char*, va_list));
enum { T_Zero, T_Negative = -7, T_Next };
#define T_BIG UINT64_C(18446744073709551615)
#define T_TEXT "a\0b"
#define T_NULL ((void*)0)
#define T_SENTINEL ((void*)(uintptr_t)-1)
''')
    (work / 'native.c').write_text('''#include "fixture.h"
void T_log_set(void (*callback)(void*, int, const char*, va_list)) { (void)callback; }
int T_count=3;
const char *T_view="original";
void T_text(const char **out) { *out="ok"; }
T_Pair T_pair(int x) { return (T_Pair){x, 4.5}; }
T_Pair T_apply(T_Callback callback, T_Pair input) { return callback(input); }
static int twice(int x) { return x*2; }
int (*T_callback(void))(int) { return twice; }
T_Function *T_get_function(void) { return twice; }
static T_Pair shift(T_Pair p) { p.x+=2; return p; }
void T_get_callback(T_Callback *out) { *out=shift; }
''')
    module = work / 'module'
    env = dict(os.environ, DYN_LIBRARY_PATH=str(work), LD_LIBRARY_PATH=str(work))
    run(['python3', ROOT / 'compiler/tools/vendor-bindings.py', '--header', 'fixture.h',
         '--prefix', '^T_', '--library', 'fixture', '--output', module,
         '--cflags=-I' + str(work), '--clang', CLANG], env)
    run([*CC, '-std=c11', '-fPIC', '-shared', '-I' + str(work), work / 'native.c',
         module / 'bridge.c', '-Wl,-z,defs', '-o', work / 'libfixture.so'], env)
    program = '''fn callback(value: T_Pair) T_Pair { return T_Pair{ x: value.x + 1, y: value.y + 2.0 } }
fn main() {
  if !verify_layout() { #panic("layout") }
  if T_Negative != -7 || T_Next != -6 || T_BIG != 18446744073709551615 { #panic("constants") }
  if #len(T_TEXT) != 3 || T_TEXT[1] != 0 || T_TEXT[2] != 'b' { #panic("string bytes") }
  if T_NULL != nil || #cast(usize) T_SENTINEL() != 18446744073709551615 { #panic("pointer constants") }
  pair := T_apply(&callback, T_pair(8))
  if pair.x != 9 || pair.y != 6.5 { #panic("aggregate calling convention") }
  returned: T_Callback = nil
  T_get_callback(&returned)
  changed := returned(T_pair(5))
  if changed.x != 7 { #panic("callback pointer output") }
  function := T_get_function()
  if function(3) != 6 { #panic("function typedef pointer") }
  twice := T_callback()
  if twice(6) != 12 { #panic("callback return") }
  text: *const c.char = nil
  T_log_set(nil)
  T_text(&text)
  if text == nil || text.* != 111 { #panic("const pointer output") }
  nested := T_Nested_items_C{ value: 17 }
  owner := T_Nested{ items: &nested }
  if owner.items.value != 17 { #panic("anonymous pointed record") }
  holder := T_view_address()
  holder.* = text
  if holder.* != text { #panic("mutable global pointer to const") }
  count := T_count_address()
  if count.* != 3 { #panic("variable") }
  count.* = 5
  if T_count_address().* != 5 { #panic("variable write") }
  packed := T_Packed{}
  T_Packed_word_set(&packed, 1234)
  if T_Packed_word_get(&packed) != 1234 { #panic("packed field") }
  bytes: T_Bytes = [1, 2, 3]
  result: T_Bytes = []
  T_Packed_bytes_set(&packed, &bytes)
  T_Packed_bytes_get(&packed, &result)
  if result[2] != 3 || result[7] != 0 { #panic("packed array") }
  bits := T_Bits{}
  T_Bits_low_set(&bits, 6)
  T_Bits_high_set(&bits, -3)
  if T_Bits_low_get(&bits) != 6 || T_Bits_high_get(&bits) != -3 { #panic("bitfields") }
  union := T_Union{}
  T_Union_bytes_set(&union, &bytes)
  T_Union_bytes_get(&union, &result)
  if result[0] != 1 { #panic("union array typedef") }
  T_Union_view_set(&union, text)
  if T_Union_view_get(&union) != text { #panic("mutable pointer to const field") }
}
'''
    program = re.sub(r'\bT_\w+', lambda match: 'raw.' + match[0], program).replace('verify_layout()', 'raw.verify_layout()')
    (work / 'main.dyn').write_text('use "./module" raw\nuse "std/c"\n' + program)
    for mode in ([], ['--release']):
        run([DYN, 'build', work, '--no-cache', '--output', work / 'test', *mode], env)
        run([work / 'test'], env)
    # A changed C layout must fail compilation of the old adapter.
    header = work / 'fixture.h'
    header.write_text(header.read_text().replace('int x; double y;', 'long long padding; int x; double y;'))
    failed = subprocess.run([*CC, '-std=c11', '-I' + str(work), '-c', module / 'bridge.c', '-o', work / 'wrong.o'], capture_output=True, text=True)
    assert failed.returncode != 0 and 'regenerate' in failed.stderr, failed.stderr
    # Unsupported alignments must be explicit failures, not plausible-looking ABI guesses.
    header.write_text('typedef struct { _Alignas(16) char value; } T_Unsupported;\n')
    failed = subprocess.run(['python3', str(ROOT / 'compiler/tools/vendor-bindings.py'),
                             '--header', 'fixture.h', '--prefix', '^T_', '--library', 'fixture',
                             '--output', str(work / 'unsupported'), '--cflags=-I' + str(work),
                             '--clang', CLANG], env=env, capture_output=True, text=True, timeout=120)
    assert failed.returncode != 0, failed.stdout
    assert 'unsupported alignment 16' in (work / 'unsupported/coverage.json').read_text()
print('PASS raw binding C ABI, constants, callbacks, packed fields, and stale-layout rejection')
