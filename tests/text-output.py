#!/usr/bin/env python3
"""Independent LLVM text: real parser/target oracles and reconstructed execution.

LLVM tools are test oracles only. The compiler produces the text with a PATH
containing no LLVM executables. Without oracles, output/isolation checks run.
"""
import os
from pathlib import Path
import shutil
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn')).resolve())
AS = shutil.which('llvm-as') if os.environ.get('DYN_TEXT_ORACLE') != '0' else None
CLANG = shutil.which('clang') if os.environ.get('DYN_TEXT_ORACLE') != '0' else None
LD = shutil.which('ld')
SOURCE = r'''
struct Pair { integer: i64, real: f64 }
struct Large { bytes: [40]u8, value: i64 }
packed struct Packed { small: u8, wide: i64 }
enum(i8) Sign { Minus = -1, Plus = 1 }
extern fn provider "provider"(x: Pair) Pair
extern fn large_provider "large_provider"(x: Large) Large
extern fn packed_provider "packed_provider"(x: Packed) Packed
counter: i32 = 0
message: []const u8 = "bytes\x00with null"
fn first(x: i32) i32 { return x + 2 }
callback: *fn(i32) i32 = &first
fn add(p: *i32) { p.* += 1 }
fn cleanup() { counter += 1 }
fn checked(x: i32) i32 { defer cleanup() return 12 / x }
fn aggregate(x: Pair) Pair { value := x value.integer += 1 return value }
fn main() {
  defer cleanup()
  original := Pair{integer: 7, real: 2.5}
  local := aggregate(original)
  foreign := provider(original)
  indirect := &provider
  foreign = indirect(foreign)
  if original.integer != 7 || local.integer != 8 || foreign.integer != 9 || foreign.real != 4.5 { #panic("pair ABI") }
  large := Large{value: 41}
  large.bytes[39] = 7
  other := large_provider(large)
  if large.value != 41 || other.value != 42 || other.bytes[39] != 7 { #panic("large byval ABI") }
  packed := packed_provider(Packed{small: 3, wide: 8})
  if packed.small != 3 || packed.wide != 9 { #panic("packed ABI") }
  values := [1, 2, 3, 4]
  sum: i32 = 0
  for value in values { sum += value }
  for i in 0..3 { sum += #cast(i32) i }
  if sum != 13 { #panic("loops") }
  ptr := &sum
  add(ptr)
  if ptr.* != 14 || callback(3) != 5 { #panic("pointer") }
  sign := #cast(Sign) -1
  if #cast(i8) sign != -1 { #panic("signed enum") }
  number: f32 = 1.25
  wide := #cast(f64) number
  if wide + 0.75 != 2.0 || #cast(i32) wide != 1 { #panic("float") }
  if checked(3) != 4 || counter != 1 || #len(message) != 15 { #panic("cleanup globals") }
}
'''
C = r'''
typedef struct { long long integer; double real; } Pair;
typedef struct { unsigned char bytes[40]; long long value; } Large;
typedef struct __attribute__((packed)) { unsigned char small; long long wide; } Packed;
Pair provider(Pair x) { ++x.integer; x.real += 1; return x; }
Large large_provider(Large x) { ++x.value; return x; }
Packed packed_provider(Packed x) { ++x.wide; return x; }
'''
TARGETS = [('x86_64-linux', 'x86_64-unknown-linux-gnu'),
           ('aarch64-linux', 'aarch64-unknown-linux-gnu'),
           ('aarch64-macos', 'arm64-apple-macos11'),
           ('x86_64-windows', 'x86_64-pc-windows-msvc'),
           ('wasm32-wasi', 'wasm32-unknown-wasi'),
           ('wasm32-browser', 'wasm32-unknown-unknown')]

def run(args, **kwargs):
    result = subprocess.run(list(map(str,args)), capture_output=True, text=True,
                            timeout=60, **kwargs)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result

with tempfile.TemporaryDirectory(prefix='dyn-text-') as directory:
    work = Path(directory)
    module = work/'module'
    module.mkdir()
    (module/'main.dyn').write_text(SOURCE)
    (work/'provider.c').write_text(C)
    empty = work/'empty-path'
    empty.mkdir()
    env = dict(os.environ, DYN_SDK=str(ROOT), PATH=str(empty))
    # Windows needs DLL lookup through its normal PATH; noLLVM compilation is
    # additionally enforced by independent SDK qualification on that platform.
    if os.name == 'nt':
        env['PATH'] = os.environ.get('PATH','')
    for target, triple in TARGETS:
        for release in (False, True):
            output = work/(target + ('-release' if release else '-debug'))
            flags = ['--backend','native','--target',target,'--no-cache',
                     '--emit-object','--no-link','--output',output]
            if release:
                flags += ['--release', '--debug-info']
            if target == 'wasm32-browser':
                flags += ['--shared']
            run([DYN,'build',module,*flags],env=env,cwd=ROOT)
            object_path = Path(str(output)+'.o')
            original = object_path.read_bytes()
            run([DYN,'build',module,*flags,'--emit-ir'],env=env,cwd=ROOT)
            assert object_path.read_bytes() == original, 'IR export replaced native object'
            ll = Path(str(output)+'.ll')
            text = ll.read_text()
            assert 'independent LLVM syntax writer' in text
            assert 'DICompileUnit' in text and 'DISubprogram' in text
            assert 'llvm.memmove' in text and 'getelementptr' in text
            if AS:
                parsed = run([AS,ll,'-o',os.devnull])
                assert 'invalid debug info' not in parsed.stderr, parsed.stderr
            if CLANG:
                obj = work/'oracle.o'
                compiled = run([CLANG,'--target='+triple,'-c','-x','ir',ll,'-o',obj])
                assert 'invalid debug info' not in compiled.stderr, compiled.stderr
                if target == 'x86_64-linux' and LD and platform.system() == 'Linux' and platform.machine() == 'x86_64':
                    runtime = Path(DYN).parent
                    if (runtime/'dynrt_start.o').exists() and (runtime/'dynrt_support.o').exists():
                        provider = work/'provider.o'
                        run([CLANG,'--target='+triple,'-ffreestanding','-fno-stack-protector',
                             '-c',work/'provider.c','-o',provider])
                        executable = work/'oracle'
                        run([LD,'-o',executable,runtime/'dynrt_start.o',
                             runtime/'dynrt_support.o',obj,provider])
                        run([executable])
    # Execute checked failure from the exported IR itself, including cleanup.
    runtime = Path(DYN).parent
    if CLANG and LD and platform.system() == 'Linux' and platform.machine() == 'x86_64' and (runtime/'dynrt_start.o').exists():
        (module/'main.dyn').write_text('extern fn report "report"()\nfn divide(x: i32) i32 { defer report() return 10 / x }\nfn main() { _ = divide(0) }\n')
        (work/'report.c').write_text('extern long dyn_syscall6(long,long,long,long,long,long,long);\nvoid report(void) { static const char text[]="cleanup\\n"; dyn_syscall6(1,2,(long)text,8,0,0,0); }\n')
        report = work/'report.o'
        run([CLANG,'--target=x86_64-unknown-linux-gnu','-ffreestanding','-fno-stack-protector','-c',work/'report.c','-o',report])
        for mode in ([], ['--release']):
            out = work/'checked'
            run([DYN,'build',module,'--backend','native','--emit-ir','--no-link','--no-cache','--output',out,*mode],env=env,cwd=ROOT)
            obj = work/'checked-oracle.o'
            run([CLANG,'--target=x86_64-unknown-linux-gnu','-c','-x','ir',str(out)+'.ll','-o',obj])
            exe = work/'checked-oracle'
            run([LD,'-o',exe,runtime/'dynrt_start.o',runtime/'dynrt_support.o',obj,report])
            result = subprocess.run([exe],capture_output=True,text=True,timeout=10)
            assert result.returncode != 0
            assert result.stderr.startswith('cleanup\n') and 'runtime check failed' in result.stderr, result.stderr
        (module/'main.dyn').write_text(SOURCE)
    # Failed publication cannot remove an existing destination or leak staging
    # files. A directory destination fails identically across supported hosts.
    blocked = work/'blocked.ll'
    blocked.mkdir()
    (blocked/'sentinel').write_text('keep')
    result = subprocess.run([DYN,'build',str(module),'--backend','native',
                             '--emit-ir','--no-link','--output',str(work/'blocked')],
                            env=env,cwd=ROOT,capture_output=True,text=True)
    assert result.returncode != 0
    assert (blocked/'sentinel').read_text() == 'keep'
    assert not list(work.glob('.dyn-object.*'))
    # Failed frontend input must leave a previously published sidecar intact.
    sentinel = work/'preserved.ll'
    sentinel.write_text('previous successful export\n')
    (module/'main.dyn').write_text('fn main( { invalid')
    result = subprocess.run([DYN,'build',str(module),'--backend','native',
                             '--emit-ir','--no-link','--output',str(work/'preserved')],
                            env=env,cwd=ROOT,capture_output=True,text=True)
    assert result.returncode != 0
    assert sentinel.read_text() == 'previous successful export\n'
print('PASS independent LLVM IR across six targets: isolated export, native object preservation, debug metadata'
      + (', LLVM parser' if AS else '') + (', target compilation/runtime oracle' if CLANG else ''))
