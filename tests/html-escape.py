#!/usr/bin/env python3
"""Byte-exact HTML escaping and bounded partial-write behavior against Python."""
import ctypes
import os
import platform
import sys
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
ENTITIES = {38: b'&amp;', 60: b'&lt;', 62: b'&gt;', 34: b'&quot;', 39: b'&#39;'}
inputs = [bytes([value]) for value in range(256)]
inputs += [b'', bytes(range(256)), b'&<>"\'' * 32, b'ordinary ASCII text ' * 8,
           'UTF-8: café 日本語 😀 & < > " \''.encode(), b'\xff\xfe\x80\xc0\xaf\x00&\x00<>',
           b'prefix&&<middle>"\'suffix', b'&' * 140]

def oracle(source, capacity):
    """Match the original contiguous-span writes, including sticky failure."""
    output = b''
    failed = False
    def write(value):
        nonlocal output, failed
        if not failed:
            if len(value) > capacity - len(output):
                failed = True
            else:
                output += value
    start = 0
    for index, value in enumerate(source):
        if value in ENTITIES:
            write(source[start:index])
            write(ENTITIES[value])
            start = index + 1
    write(source[start:])
    return output, failed

backing = b''.join(inputs)
offset = 0
cases = []
for source in inputs:
    full, _ = oracle(source, 100000)
    cases.append(f'  Case{{ start: {offset}, length: {len(source)}, limit: {len(full) + 2} }}')
    offset += len(source)
size = max(max(len(oracle(source, 100000)[0]) + 2, 6 * len(source) + 2) for source in inputs) + 3
SOURCE = f'''use "std/fmt" fmt
use "std/html" html
use "std/io" io
struct Case {{ start: usize, length: usize, limit: usize }}
const backing: [{len(backing)}]u8 = [{','.join(map(str, backing))}]
const cases: [{len(cases)}]Case = [
{','.join(cases)}
]
fn reference(buffer: *fmt.Buffer, source: []const u8) bool {{
  start: usize = 0
  for i in 0..#len(source) {{
    replacement := html.entity(source[i])
    if #len(replacement) != 0 {{
      fmt.write(buffer, source[start..i])
      fmt.write(buffer, replacement)
      start = i + 1
    }}
  }}
  fmt.write(buffer, source[start..])
  return !buffer.failed
}}
pub fn guard_escape(destination: []u8, source: []const u8) usize {{
  buffer := fmt.buffer(destination)
  html.write_escaped(&buffer, source)
  if buffer.failed {{ #panic("guard capacity") }}
  return buffer.length
}}
fn overlap_cases() {{
  actual: [256]u8
  expected: [256]u8
  pattern: []const u8 = "ab&<\\\"'>Z"
  for source_offset in [0, 4, 20, 80] {{
    for destination_offset in [0, 8, 24, 100] {{
      for capacity in [12, 64] {{
        for prefix in 0..4 {{
          for i in 0..#len(actual) {{
            actual[i] = pattern[i % #len(pattern)]
            expected[i] = actual[i]
          }}
          left := fmt.buffer(actual[destination_offset..destination_offset + capacity])
          right := fmt.buffer(expected[destination_offset..destination_offset + capacity])
          left.length = prefix
          right.length = prefix
          html.write_escaped(&left, actual[source_offset..source_offset + 8])
          _ = reference(&right, expected[source_offset..source_offset + 8])
          if left.length != right.length || left.failed != right.failed {{ #panic("overlap state") }}
          for i in 0..#len(actual) {{ if actual[i] != expected[i] {{ #panic("overlap bytes") }} }}
        }}
      }}
    }}
  }}
}}
fn main() {{
  overlap_cases()
  storage: [{size}]u8
  for index in 0..#len(cases) {{
    item := cases[index]
    source := backing[item.start..item.start + item.length]
    for attempt in 0..item.limit + 2 {{
      capacity := attempt
      if attempt == item.limit {{ capacity = 6 * item.length }}
      else if attempt == item.limit + 1 {{ capacity = 6 * item.length + 1 }}
      for i in 0..#len(storage) {{ storage[i] = 165 }}
      buffer := fmt.buffer(storage[..capacity])
      html.write_escaped(&buffer, source)
      for i in capacity..#len(storage) {{
        if storage[i] != 165 {{ #panic("past destination") }}
      }}
      io.println("{{}} {{}} {{}} {{}}", index, capacity, buffer.length, buffer.failed)
      _ = io.write_all(io.stdout(), fmt.bytes(&buffer))
      _ = io.write_all(io.stdout(), "\\n")
      if buffer.failed {{
        old_length := buffer.length
        html.write_escaped(&buffer, "x<&")
        if !buffer.failed || buffer.length != old_length {{ #panic("sticky length") }}
        for i in old_length..#len(storage) {{
          if storage[i] != 165 {{ #panic("sticky bytes") }}
        }}
      }}
    }}
    for i in 0..#len(storage) {{ storage[i] = 165 }}
    failed := fmt.buffer(storage[..])
    failed.failed = true
    html.write_escaped(&failed, source)
    if !failed.failed || failed.length != 0 {{ #panic("preexisting failure") }}
    for byte in storage {{ if byte != 165 {{ #panic("failed writer changed bytes") }} }}
  }}
  invalid := fmt.buffer(storage[..3])
  invalid.length = 4
  html.write_escaped(&invalid, "<&")
  if !invalid.failed || invalid.length != 4 {{ #panic("invalid buffer state") }}
  prefixed := fmt.buffer(storage[..])
  fmt.write(&prefixed, "prefix:")
  html.write_escaped(&prefixed, "<&")
  if prefixed.failed {{ #panic("prefix append") }}
  if prefixed.length != 16 {{ #panic("prefix length") }}
}}
'''
with tempfile.TemporaryDirectory(prefix='dyn-html-escape-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    for release in (False, True):
        program = project / 'program'
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(program)] + (['--release'] if release else []), check=True, timeout=120)
        output = subprocess.run([str(program)], check=True, capture_output=True, timeout=30).stdout
        at = 0
        observations = 0
        for index, source in enumerate(inputs):
            full, _ = oracle(source, 100000)
            for capacity in [*range(len(full) + 2), 6 * len(source), 6 * len(source) + 1]:
                end = output.index(b'\n', at)
                header = output[at:end].split()
                actual_index, actual_capacity, length = map(int, header[:3])
                failed = header[3] == b'true'
                assert header[3] in (b'true', b'false'), header
                assert (actual_index, actual_capacity) == (index, capacity), header
                actual = output[end + 1:end + 1 + length]
                expected, expected_failed = oracle(source, capacity)
                assert (actual, failed) == (expected, expected_failed), (index, capacity, actual, expected, failed)
                at = end + 1 + length
                assert output[at:at+1] == b'\n'
                at += 1
                observations += 1
        assert at == len(output), (at, len(output))
    if sys.platform == 'linux' and platform.machine() == 'x86_64':
        shared = project / 'guard.so'
        subprocess.run([DYN, 'build', str(project), '--shared', '--release', '--no-cache', '--quiet', '--output', str(shared)], check=True, timeout=120)
        child = os.fork()
        if child == 0:
            try:
                library = ctypes.CDLL(str(shared))
                escape = library.guard_escape
                escape.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
                escape.restype = ctypes.c_size_t
                native = ctypes.CDLL(None)
                native.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
                native.mmap.restype = ctypes.c_void_p
                native.mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
                native.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
                page = os.sysconf('SC_PAGESIZE')
                maps = [native.mmap(None, 3 * page, 0, 0x22, -1, 0) for _ in range(2)]
                assert all(address != ctypes.c_void_p(-1).value for address in maps)
                for address in maps:
                    assert native.mprotect(address + page, page, 3) == 0
                for length in range(258):
                    source = bytes(b'&<>"\'ordinary'[i % 13] for i in range(length))
                    src = maps[0] + 2 * page - length
                    dst = maps[1] + 2 * page - 6 * length
                    if length:
                        ctypes.memmove(src, source, length)
                        ctypes.memset(dst, 165, 6 * length)
                    actual = escape(dst, 6 * length, src, length)
                    expected = b''.join(ENTITIES.get(value, bytes([value])) for value in source)
                    assert actual == len(expected)
                    assert ctypes.string_at(dst, actual) == expected
                    assert ctypes.string_at(dst + actual, 6 * length - actual) == b'\xa5' * (6 * length - actual)
                for address in maps:
                    assert native.munmap(address, 3 * page) == 0
            except BaseException:
                import traceback
                traceback.print_exc()
                os._exit(1)
            os._exit(0)
        _, status = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(status) == 0, ('guard pages', status)
print(f'PASS HTML escaping: {len(inputs)} byte sequences, {observations} bounded Python-oracle observations, sticky failures, overlap/reference equality, destination sentinels and Linux guard pages (debug/release)')
