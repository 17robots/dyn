#!/usr/bin/env python3
"""Cross-check Windows ARM64 SSA selection, stack probing and unwind metadata.

Native execution remains part of tools/build-native-probes.py and its ARM64 CI job.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()
SOURCE = '''use "std/io"
struct Pair { a: i64, b: f64 }
struct Wide { a: i64, b: i64, c: i64 }
fn many(a: i64, b: i8, c: i64, d: u16, e: i64, f: i32, g: i64, h: u8, i: i64, j: i8, k: f32, l: f64, m: Pair, n: Wide) f64 {
  return #cast(f64, a + #cast(i64, b) + c + #cast(i64, d) + e + #cast(i64, f) + g + #cast(i64, h) + i + #cast(i64, j) + m.a + n.a + n.b + n.c) + #cast(f64, k) + l + m.b
}
fn floats(a: f64, b: f64, c: f64, d: f64, e: f64, f: f64, g: f64, h: f64, i: f32, j: f64, k: f32) f64 {
  return a + b * 2.0 + c * 3.0 + d * 4.0 + e * 5.0 + f * 6.0 + g * 7.0 + h * 8.0 + #cast(f64, i) * 9.0 + j * 10.0 + #cast(f64, k) * 11.0
}
fn big(value: i64) i64 {
  bytes: [12288]u8
  bytes[0] = #cast(u8, value)
  bytes[8192] = 19
  return #cast(i64, bytes[0]) + #cast(i64, bytes[8192])
}
fn retained(value: i64) i64 {
  x := big(value)
  return x + big(value + 1) + value
}
fn main() {
  x := many(1, -2, 3, 4, 5, -6, 7, 8, 9, -10, 1.5, 2.25, Pair{a: 11, b: 0.5}, Wide{a: 12, b: 13, c: 14})
  y := floats(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.5, 10.0, 11.5)
  if y != 516.0 { #panic("Windows ARM64 SSA floating stack arguments") }
  if #cast(i64, x * 4.0) != 293 || retained(7) != 60 { #panic("Windows ARM64 SSA ABI") }
  _ = io.println(io.stdout(), "Windows ARM64 SSA ready")
}
'''

def main():
    with tempfile.TemporaryDirectory(prefix='dyn-winarm-ssa-') as directory:
        work = Path(directory)
        (work/'main.dyn').write_text(SOURCE)
        output = work/'probe'
        command = [DYN, 'build', work, '--target', 'aarch64-windows', '--release', '--opt-remarks',
                   '--no-cache', '--quiet', '--emit-object', '--no-link', '--output', output]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        for function in ('many', 'floats', 'big', 'retained', 'main'):
            assert re.search(r'remark: '+function+r': SSA code generation', result.stderr), result.stderr
        reader = shutil.which('llvm-readobj')
        if reader:
            text = subprocess.check_output([reader, '--unwind', output.with_suffix('.o')], text=True)
            assert 'RuntimeFunction' in text and 'EpilogueScopes' in text, text
            starts = re.findall(r'Function: .*?\(0x([0-9A-Fa-f]+)\)', text)
            assert starts and len(starts) == len(set(starts)), 'Duplicate unwind records after SSA measurement'
            assert text.count('sub sp, #4080') >= 3, 'Large SSA frame does not probe each page'
            assert 'save_reg' not in text, 'Windows SSA must leave callee-saved registers untouched'
        fallback = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True,
                                  env={**os.environ, 'DYN_NO_SSA': '1'})
        assert 'SSA code generation' not in fallback.stderr
    print('PASS Windows ARM64 SSA selection, unwind records and tree fallback')

if __name__ == '__main__':
    main()
