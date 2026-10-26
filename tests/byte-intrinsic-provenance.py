#!/usr/bin/env python3
"""Trusted byte intrinsics: SDK relocation, lookalikes, structural IR and policy.

DYN selects the compiler; DYN_SDK selects the real SDK. DYN_PROVENANCE_BASELINE
optionally checks structural dumps against an unmodified compiler. No timings.
The file can live either at an artifact compiler root or under compiler/tests.
"""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE/'src/ir.h').exists() else HERE.parent
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()
SDK = Path(os.environ.get('DYN_SDK', (ROOT/'std').resolve().parent)).resolve()
if platform.system() != 'Linux' or platform.machine() != 'x86_64' or not shutil.which('objdump'):
    print('SKIP byte intrinsic provenance: requires x86-64 Linux and objdump')
    raise SystemExit(0)

WRAPPERS = '''pub fn probe_byte(source:[]const u8,needle:u8) usize { return bytes.find_byte(source,needle) }
pub fn probe_find(source:[]const u8,needle:[]const u8) usize { return bytes.find(source,needle) }
'''
LOOKALIKE = '''pub fn find_byte(source:[]const u8,needle:u8) usize { return 61 }
pub fn find(source:[]const u8,needle:[]const u8) usize { return 62 }
'''


def call(args, env):
    result = subprocess.run([str(x) for x in args], env=env, capture_output=True, timeout=120)
    assert result.returncode == 0, (args, result.returncode, result.stdout, result.stderr)
    return result


def project(path, imported, expected=(1, 1)):
    path.mkdir(parents=True, exist_ok=True)
    (path/'main.dyn').write_text('use "'+imported+'" bytes\n'+WRAPPERS+f'''fn main() {{
 if probe_byte("abc",98)!={expected[0]} || probe_find("abc","b")!={expected[1]} {{ #panic("provenance behavior") }}
}}
''')


def build(project, output, env, flags=(), simd=True):
    call([DYN, 'build', project, '--release', '--opt-level', '3', '--no-cache', '--quiet',
          '--emit-object', '--output', output, *flags], env)
    call([output], env)
    asm = call(['objdump', '-dr', '-Mintel', str(output)+'.o'], env).stdout.decode()
    for name in ('probe_byte', 'probe_find'):
        match = re.search(r'<'+name+r'>:\n(.*?)(?=\n\n|\Z)', asm, re.S)
        assert match, (name, asm)
        body = match.group(1)
        actual = all(op in body for op in ('movdqu', 'pcmpeqb', 'pmovmskb', 'bsf'))
        assert actual == simd, (name, simd, body)
        if not simd:
            assert 'pcmpeqb' not in body and 'pmovmskb' not in body, body
    return asm


def dump(project, env, compiler=DYN):
    return call([compiler, 'build', project, '--emit-ir', '--target', 'x86_64-linux'], env).stdout


with tempfile.TemporaryDirectory(prefix='dyn-byte-provenance-') as directory:
    work = Path(directory)
    env = dict(os.environ, DYN_SDK=str(SDK), DYN_NO_SSA='0', DYN_CACHE_DIR=str(work/'cache'))
    trusted = work/'trusted'
    project(trusted, 'std/bytes')
    build(trusted, work/'trusted-run', env)
    relocated = work/'relocated-sdk'
    (relocated/'std').mkdir(parents=True)
    shutil.copytree(SDK/'std/bytes', relocated/'std/bytes')
    moved_env = dict(env, DYN_SDK=str(relocated))
    build(trusted, work/'relocated-run', moved_env)
    # Explicit invalid SDKs and symlink escapes cannot authorize fallback code.
    build(trusted, work/'missing-sdk-run', dict(env, DYN_SDK=str(work/'missing-sdk')), simd=False)
    escaped = work/'escaped-sdk'
    escaped.mkdir()
    (escaped/'std').symlink_to(SDK/'std', target_is_directory=True)
    build(trusted, work/'escaped-sdk-run', dict(env, DYN_SDK=str(escaped)), simd=False)
    # A project-local std directory cannot replace a canonical std import.
    (trusted/'std/bytes').mkdir(parents=True)
    (trusted/'std/bytes/bytes.dyn').write_text(LOOKALIKE)
    build(trusted, work/'shadow-directory-run', moved_env)
    # Same declaration names/signatures and module tail remain ordinary code.
    local = work/'local'
    project(local, 'bytes', (61, 62))
    (local/'bytes').mkdir()
    (local/'bytes/bytes.dyn').write_text(LOOKALIKE)
    build(local, work/'local-run', moved_env, simd=False)
    # Even a byte-for-byte copy of the real module lacks SDK provenance.
    copied = work/'copied'
    project(copied, 'bytes')
    shutil.copytree(SDK/'std/bytes', copied/'bytes')
    build(copied, work/'copied-run', moved_env, simd=False)
    # Aliased same-spelling functions in another module cannot acquire identity.
    alias = work/'alias'
    project(alias, 'dep', (61, 62))
    (alias/'dep').mkdir()
    (alias/'dep/dep.dyn').write_text(LOOKALIKE)
    build(alias, work/'alias-run', moved_env, simd=False)
    for label, policy_env, flags in (
        ('tree', dict(moved_env, DYN_NO_SSA='1'), ()),
        ('debug-info', moved_env, ('--debug-info',))):
        build(trusted, work/label, policy_env, flags, simd=False)
    # Structural lowering uses proofs=false and dumps no derived identity.
    original_dump = dump(trusted, env)
    moved_dump = dump(trusted, moved_env)
    assert original_dump == moved_dump, 'SDK relocation changed structural IR'
    assert original_dump.startswith(b'dyn-ir1\n')
    assert b'byte_intrinsic' not in original_dump and b'math_intrinsic' not in original_dump
    assert dump(trusted, dict(moved_env, DYN_NO_SSA='1')) == moved_dump
    baseline = os.environ.get('DYN_PROVENANCE_BASELINE')
    if baseline:
        assert dump(trusted, moved_env, Path(baseline).resolve()) == moved_dump, 'derived identity changed baseline structural dump'
    print('PASS byte intrinsic provenance: relocated SDK, local shadows/lookalikes/copied modules, structural dumps, tree/debug-info scalar policy')
