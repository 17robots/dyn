#!/usr/bin/env python3
"""Checked arithmetic on hard-float RV32/Thumb, SSA versus tree.

ROOT selects the compiler directory; DYN selects its executable.
DYN_QEMU_RISCV32 and DYN_QEMU_ARM are shell-split command prefixes.
Container wrappers must mount TMPDIR at the same path and bound the guest
(e.g. timeout 15 qemu-system-arm). TemporaryDirectory respects TMPDIR.
37 arithmetic fixtures + 7 order/shift/cleanup fixtures + 1 extrema fixture.
"""
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import tempfile

ROOT = Path(os.environ.get('ROOT', Path(__file__).resolve().parents[1])).resolve()
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
TARGETS = (
    ('riscv32-none', 'DYN_QEMU_RISCV32', 'qemu-system-riscv32',
     ['-machine', 'virt', '-bios', 'none']),
    ('thumbv7em-none', 'DYN_QEMU_ARM', 'qemu-system-arm',
     ['-machine', 'mps2-an500', '-semihosting-config', 'enable=on,target=native']),
)

# Public functions keep operands dynamic; main supplies independent expected values.
funcs = ''
for ty in ['u64', 'i64', 'u32', 'i32', 'u8', 'i8']:
    for name, op in [('add', '+'), ('sub', '-'), ('mul', '*'), ('div', '/'), ('rem', '%')]:
        funcs += f'pub fn {name}_{ty}(a:{ty},b:{ty}) {ty} {{ return a{op}b }}\n'
funcs += 'pub fn preserved(a:u64,b:u64,c:u64) u64 { x:=a/b y:=a%b z:=b*c return #wrap(x+y+z+a+b+c) }\n'
success = []
for ty in ['u64', 'i64', 'u32', 'i32', 'u8', 'i8']:
    for name, a, b, want in [('add', 50, 7, 57), ('sub', 50, 7, 43), ('mul', 12, 7, 84), ('div', 50, 7, 7), ('rem', 50, 7, 1)]:
        success.append(f'if {name}_{ty}({a},{b})!={want} {{ #panic("bad") }}')
success += ['if div_i64(-9223372036854775807,3)!=-3074457345618258602 { #panic("signed") }', 'if rem_i64(-9223372036854775807,3)!=-1 { #panic("signed rem") }', 'if div_u64(18446744073709551615,3)!=6148914691236517205 { #panic("unsigned") }', 'if preserved(18446744073709551615,3,7)!=6148914691236517235 { #panic("preserve") }']
cases = [('success', ' '.join(success), '')]
for ty, maximum, minimum in [('u64', 2 ** 64 - 1, 0), ('i64', 2 ** 63 - 1, -2 ** 63), ('u32', 2 ** 32 - 1, 0), ('i32', 2 ** 31 - 1, -2 ** 31), ('u8', 255, 0), ('i8', 127, -128)]:
    for op, a, b in [('add', maximum, 1), ('sub', minimum, 1), ('mul', maximum, 2), ('div', 1, 0), ('rem', 1, 0)]:
        cases.append((op + '_' + ty, f'_={op}_{ty}({a},{b})', 'division by zero' if op in ['div', 'rem'] else 'overflow'))
    if ty.startswith('i'):
        for op in ['div', 'rem']:
            cases.append((op + '_min_' + ty, f'_={op}_{ty}({minimum},-1)', 'division overflow'))
funcs += '\npub fn ordered(a:u64,b:u64,c:u64,d:u64) u64 { return a/b+c*d }\npub fn shifts(a:u64,b:u64) u64 { return a<<b }\npub fn negated(a:i64) i64 { return -a }\npub fn shared(a:u64,b:u64,c:u64) u64 { return (a+b)+c }\nfn cleanup(a:u64,b:u64) u64 { defer { _=io.write_all(io.stdout(),"CLEAN\\n") } return a+b }\n'
cases += [('ordered', '_=ordered(1,0,18446744073709551615,2)', 'divide'), ('shiftcount', '_=shifts(1,64)', 'shift'), ('shiftbits', '_=shifts(18446744073709551615,1)', 'overflow'), ('negated', '_=negated(-9223372036854775808)', 'overflow'), ('shared', '_=shared(1,2,18446744073709551615)', 'overflow'), ('cleanup', '_=cleanup(18446744073709551615,1)', 'overflow'), ('caller_cleanup', 'defer { _=io.write_all(io.stdout(),"OUTER\\n") } _=add_u64(18446744073709551615,1)', 'overflow')]
cases += [('boundaries', 'if mul_i64(-9223372036854775808,1)!=-9223372036854775808 { #panic("mul min") } if mul_u64(18446744073709551615,1)!=18446744073709551615 { #panic("mul max") } if add_i64(-9223372036854775808,9223372036854775807)!=-1 { #panic("add") } if sub_i64(-1,9223372036854775807)!=-9223372036854775808 { #panic("sub") } if div_i64(-9223372036854775808,1)!=-9223372036854775808 { #panic("div") } if rem_i64(-9223372036854775808,1)!=0 { #panic("rem") }', '')]


def check_remarks(log, mode, names, fallback=()):
    if mode == 'tree':
        assert 'SSA code generation' not in log, log
        return
    for name in names:
        messages = re.findall(r'^remark: ' + re.escape(name) + r': (.*)$', log, re.MULTILINE)
        expected = ('tree emitter (paired SSA boundary)' if name in fallback
                    else 'SSA code generation,')
        assert any(message.startswith(expected) for message in messages), (name, expected, log)
        forbidden = 'SSA code generation' if name in fallback else 'tree emitter'
        assert not any(forbidden in message for message in messages), (name, messages)


def run_guest(command):
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise AssertionError(f'guest exceeded 30 seconds: {command}')
    return process.returncode, stdout.replace(b'\r\n', b'\n'), stderr


def main():
    # Negative control: success output alone must never stand in for SSA selection.
    try:
        check_remarks('', 'ssa', ['add_u64'])
    except AssertionError:
        pass
    else:
        raise AssertionError('missing named SSA remark was accepted')
    if not shutil.which(DYN):
        print(f'SKIP checked SSA: DYN executable unavailable: {DYN}', flush=True)
        return
    completed = 0
    for target, variable, program, board in TARGETS:
        qemu = shlex.split(os.environ.get(variable, '')) or [program]
        if not shutil.which(qemu[0]):
            print(f'SKIP {target}: {qemu[0]} unavailable; set {variable}', flush=True)
            continue
        with tempfile.TemporaryDirectory(prefix='dyn-checked-ssa-') as temporary:
            work = Path(temporary)
            for name, body, panic in cases:
                project = work/name
                project.mkdir()
                (project/'main.dyn').write_text('use "std/io"\n' + funcs +
                    'fn main() { ' + body + ' _=io.write_all(io.stdout(),"OK\\n") }')
                names = [fn for fn in re.findall(r'pub fn (\w+)', funcs) if fn+'(' in body]
                fallback = []
                if name in ('cleanup', 'caller_cleanup'):
                    names += ['main']
                assert names, name
                outputs = []
                for mode in ('ssa', 'tree'):
                    env = dict(os.environ)
                    env.pop('DYN_NO_SSA', None)
                    if mode == 'tree':
                        env['DYN_NO_SSA'] = '1'
                    image = project/(mode+'.elf')
                    build = subprocess.run([DYN, 'build', str(project), '--release',
                        '--target', target, '--no-cache', '--opt-remarks', '--output', str(image)],
                        env=env, capture_output=True, text=True, timeout=120)
                    log = build.stdout + build.stderr
                    assert build.returncode == 0, (target, name, mode, log)
                    check_remarks(log, mode, names, fallback)
                    outputs.append(run_guest([*qemu, *board, '-nographic', '-kernel', str(image)]))
                assert outputs[0] == outputs[1], (target, name, outputs)
                status, stdout, stderr = outputs[0]
                if panic:
                    predicate = {'division by zero': 'divide.ok',
                                 'division overflow': 'division.overflow.ok',
                                 'divide': 'divide.ok', 'shift': 'shift.count.ok',
                                 'overflow': 'overflow.ok'}[panic]
                    function = {'ordered': 'ordered', 'shiftcount': 'shifts',
                                'shiftbits': 'shifts', 'negated': 'negated',
                                'shared': 'shared', 'cleanup': 'cleanup',
                                'caller_cleanup': 'add_u64'}.get(name, name.replace('_min_', '_'))
                    prefix = {'cleanup': 'CLEAN\n', 'caller_cleanup': 'OUTER\n'}.get(name, '')
                    expected = (prefix + f'runtime check failed ({predicate}) in {function}\n').encode()
                    assert status == 101 and stdout == expected and stderr == b'', (target, name, outputs)
                else:
                    assert (status, stdout, stderr) == (0, b'OK\n', b''), (target, name, outputs)
                print(f'PASS {target} {name}: SSA/tree status and output; named lowering', flush=True)
            completed += 1
            print(f'PASS {target}: {len(cases)} paired fixtures, {2*len(cases)} guest runs', flush=True)
    if not completed:
        print('SKIP checked SSA: no QEMU targets executed', flush=True)


if __name__ == '__main__':
    main()
