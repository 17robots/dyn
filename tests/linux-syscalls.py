#!/usr/bin/env python3
"""#syscall maps every x86-64 Linux call to the aarch64 and riscv64 call of the
same name, as tools/linux-syscalls.tsv (the kernel's tables) records, and a
call a target lacks is an error that names its replacement. The std/os/linux/sys
names run on each Linux target: natively on x86-64, under qemu-user elsewhere
when it is installed."""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
ARCHES = ('aarch64', 'riscv64')
# Kept in step with ALIASES in tools/linux-syscalls.py.
ALIASES = {'dup2': 'dup3', 'epoll_wait': 'epoll_pwait'}

PROGRAM = '''use sys "std/os/linux/sys"
fn require(ok: bool, what: []const u8) {
  if !ok { #panic(what) }
}
fn main() {
  // Paths are relative to the working directory, a fresh temporary one.
  first: [2]u8 = [97, 0]
  second: [2]u8 = [98, 0]
  third: [2]u8 = [99, 0]
  name: [4]u8 = [100, 121, 110, 0]
  data: [4]u8 = [1, 2, 3, 4]
  file := #syscall(sys.Openat, -100, &first[0], 65, 384)
  require(file >= 0, "openat")
  require(#syscall(sys.Fchmod, file, 420) == 0, "fchmod")
  require(#syscall(sys.Write, file, &data[0], 4) == 4, "write")
  require(#syscall(sys.Close, file) == 0, "close")
  require(#syscall(sys.Renameat2, -100, &first[0], -100, &second[0], 0) == 0, "renameat2")
  require(#syscall(sys.Fchmodat, -100, &second[0], 384, 0) == 0, "fchmodat")
  require(#syscall(sys.Faccessat, -100, &second[0], 4) == 0, "faccessat")
  source := #syscall(sys.Openat, -100, &second[0], 0, 0)
  copy := #syscall(sys.Openat, -100, &third[0], 66, 384)
  require(source >= 0 && copy >= 0, "open copy ends")
  require(#syscall(sys.CopyFileRange, source, 0, copy, 0, 4, 0) == 4, "copy_file_range")
  data[3] = 0
  require(#syscall(sys.Pread64, copy, &data[0], 4, 0) == 4 && data[3] == 4, "pread64")
  require(#syscall(sys.Unlinkat, -100, &second[0], 0) == 0, "unlinkat")
  require(#syscall(sys.Unlinkat, -100, &third[0], 0) == 0, "unlinkat")
  memory := #syscall(sys.MemfdCreate, &name[0], 0)
  require(memory >= 0, "memfd_create")
  require(#syscall(sys.Ftruncate, memory, 4096) == 0, "ftruncate")
  require(#syscall(sys.Fdatasync, memory) == 0, "fdatasync")
  _ = #syscall(sys.Close, memory)
  pidfd := #syscall(sys.PidfdOpen, #syscall(sys.Getpid), 0)
  // qemu-user and old kernels may lack pidfds; a number the kernel rejects is ENOSYS.
  if pidfd != -38 {
    require(pidfd >= 0, "pidfd_open")
    require(#syscall(sys.PidfdSendSignal, pidfd, 0, 0, 0) == 0, "pidfd_send_signal")
    _ = #syscall(sys.Close, pidfd)
  }
  require(#syscall(sys.Dup2, source, copy) == copy, "dup2")
  _ = #syscall(sys.Close, source)
  _ = #syscall(sys.Close, copy)
  require(#syscall(sys.Getuid) >= 0 && #syscall(sys.Geteuid) >= 0, "getuid")
}
'''


def reference():
    rows = []
    for line in (ROOT / 'tools/linux-syscalls.tsv').read_text().splitlines():
        if line.startswith('#'):
            continue
        name, x86, *native = line.split('\t')
        rows.append((name, int(x86), dict(zip(ARCHES, (None if n == '-' else int(n) for n in native)))))
    return rows


def ir_syscalls(text):
    """(number, marker) for each #syscall(number, marker) in the IR dump."""
    bits, items, calls = {}, {}, []
    for line in text.splitlines():
        if match := re.match(r'expression (\d+) kind=int .*bits=([0-9a-f]+)', line):
            bits[int(match.group(1))] = int(match.group(2), 16)
        elif match := re.match(r'expression \d+ kind=syscall .*items=item:(\d+)\+2', line):
            calls.append(int(match.group(1)))
        elif match := re.match(r'item (\d+) expression=expression:(\d+)', line):
            items[int(match.group(1))] = int(match.group(2))
    return [(bits[items[start]], bits[items[start + 1]]) for start in calls]


def write(project, body):
    project.mkdir(exist_ok=True)
    (project / 'main.dyn').write_text(body)


def main():
    status = subprocess.run([sys.executable, str(ROOT / 'tools/linux-syscalls.py'), '--check'])
    if status.returncode:
        raise SystemExit('src/linux_syscalls.inc does not match tools/linux-syscalls.tsv')
    rows = reference()
    by_name = {name: native for name, _, native in rows}
    assert by_name['renameat2'] == {'aarch64': 276, 'riscv64': 276}
    assert by_name['renameat'] == {'aarch64': 38, 'riscv64': None}
    env = dict(os.environ, DYN_SDK=str(ROOT))
    with tempfile.TemporaryDirectory(prefix='dyn-linux-syscalls-') as temporary:
        root = Path(temporary)
        for arch in ARCHES:
            target = f'{arch}-linux'
            expected = {}
            for name, x86, native in rows:
                number = native[arch] if name not in ALIASES else by_name[ALIASES[name]][arch]
                if number is not None:
                    expected[x86] = number
            # Every mapped call translates to the reference number.
            mapped = root / f'mapped-{arch}'
            write(mapped, 'fn main() {\n' + ''.join(
                f'  _ = #syscall({x86}, {x86})\n' for x86 in expected) + '}\n')
            result = subprocess.run([DYN, 'build', str(mapped), '--emit-ir', '--target', target],
                                    env=env, capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise SystemExit(result.stdout + result.stderr)
            found = {marker: number for number, marker in ir_syscalls(result.stdout)}
            if found != expected:
                wrong = {x86: (found.get(x86), number) for x86, number in expected.items()
                         if found.get(x86) != number}
                raise SystemExit(f'{target}: (got, want) by x86-64 number: {wrong}')
            # Every call the target lacks is an error naming the call and its replacement.
            missing = [(name, x86) for name, x86, _ in rows if x86 not in expected]
            unmapped = root / f'unmapped-{arch}'
            write(unmapped, 'fn main() {\n' + ''.join(
                f'  _ = #syscall({x86})\n' for _, x86 in missing) + '  _ = #syscall(999)\n}\n')
            result = subprocess.run([DYN, 'check', '--target', target, str(unmapped)], env=env,
                                    capture_output=True, text=True, timeout=120)
            output = result.stdout + result.stderr
            assert result.returncode, output
            errors = re.findall(r'error: syscall (\d+) \((\w+)\) does not exist on ' + target +
                                r'; (.+)', output)
            assert [(name, x86) for x86, name, _ in errors] == [(n, str(x)) for n, x in missing], output
            assert all(hint and 'no portable replacement' not in hint for _, _, hint in errors), output
            assert 'syscall 999 is not an x86-64 Linux syscall number' in output, output
            assert ('(renameat) does not exist' in output) == (arch == 'riscv64'), output
            print(f'PASS linux syscalls {target}: {len(expected)} mapped, {len(missing)} '
                  'rejected with a replacement')
        # The std names type-check on every Linux target and run where possible.
        program = root / 'program'
        write(program, PROGRAM)
        runners = {'x86_64-linux': [] if platform.machine() == 'x86_64' else None,
                   'aarch64-linux': [] if platform.machine() == 'aarch64' else None,
                   'riscv64-linux': [] if platform.machine() == 'riscv64' else None}
        for target, tool in (('aarch64-linux', 'qemu-aarch64'), ('riscv64-linux', 'qemu-riscv64')):
            if runners[target] is None and shutil.which(tool):
                runners[target] = [shutil.which(tool)]
        for target, runner in runners.items():
            subprocess.run([DYN, 'check', '--target', target, str(program)], env=env, check=True,
                           stdout=subprocess.DEVNULL, timeout=120)
            if platform.system() != 'Linux' or runner is None:
                print(f'PASS linux syscalls std names check on {target} (not run)')
                continue
            output = root / f'probe-{target}'
            subprocess.run([DYN, 'build', str(program), '--quiet', '--release', '--target', target,
                            '--output', str(output)], env=env, check=True, timeout=120)
            work = root / f'work-{target}'
            work.mkdir()
            subprocess.run([*runner, str(output)], cwd=work, check=True, timeout=30)
            print(f'PASS linux syscalls std names run on {target}')


if __name__ == '__main__':
    main()
