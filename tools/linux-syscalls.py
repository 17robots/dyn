#!/usr/bin/env python3
"""Maintains the Linux #syscall translation table.

Dyn's portable Linux syscall numbers are the x86-64 ones. The compiler maps
each to the AArch64 and RISC-V 64 number of the call with the same name, using
src/linux_syscalls.inc. That file is generated from tools/linux-syscalls.tsv,
the reference table of kernel numbers, plus the policy below: the two aliases
and the replacement named in the error for a call a target lacks.

  tools/linux-syscalls.py                 regenerate src/linux_syscalls.inc
  tools/linux-syscalls.py --check         exit 1 when it is out of date
  tools/linux-syscalls.py --kernel X86 GENERIC VERSION
      rebuild the reference from a kernel tree's tables: X86 is
      arch/x86/entry/syscalls/syscall_64.tbl (or the installed
      asm/unistd_64.h), GENERIC is scripts/syscall.tbl, VERSION is the
      kernel version they come from, such as 7.3.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / 'tools/linux-syscalls.tsv'
OUTPUT = ROOT / 'src/linux_syscalls.inc'
ARCHES = ('aarch64', 'riscv64')

# The scripts/syscall.tbl ABIs each 64-bit target selects
# (arch/arm64/kernel/Makefile.syscalls, arch/riscv/kernel/Makefile.syscalls).
GENERIC_ABIS = {
    'aarch64': {'common', '64', 'renameat', 'rlimit', 'memfd_secret'},
    'riscv64': {'common', '64', 'riscv', 'rlimit', 'memfd_secret'},
}

# x86-64 calls the generic table replaces with a superset taking one more
# trailing argument that is zero, or NULL, for the old behaviour. #syscall
# passes zero in every register a call leaves out, so these translate.
ALIASES = {
    'dup2': 'dup3',  # flags 0; dup3 fails with EINVAL when both descriptors match
    'epoll_wait': 'epoll_pwait',  # NULL signal mask
}

# The call to use instead of an x86-64 call another target lacks. Every such
# call needs an entry, so a kernel update cannot add a silent gap.
REPLACEMENTS = {
    'open': 'use openat with AT_FDCWD',
    'stat': 'use statx or newfstatat',
    'lstat': 'use statx or newfstatat with AT_SYMLINK_NOFOLLOW',
    'poll': 'use ppoll',
    'access': 'use faccessat',
    'pipe': 'use pipe2',
    'select': 'use pselect6',
    'pause': 'use rt_sigsuspend or ppoll',
    'alarm': 'use setitimer',
    'fork': 'use clone with SIGCHLD',
    'vfork': 'use clone with CLONE_VM | CLONE_VFORK | SIGCHLD',
    'getdents': 'use getdents64',
    'rename': 'use renameat2',
    'renameat': 'use renameat2',
    'mkdir': 'use mkdirat',
    'rmdir': 'use unlinkat with AT_REMOVEDIR',
    'creat': 'use openat with O_CREAT | O_WRONLY | O_TRUNC',
    'link': 'use linkat',
    'unlink': 'use unlinkat',
    'symlink': 'use symlinkat',
    'readlink': 'use readlinkat',
    'chmod': 'use fchmodat',
    'chown': 'use fchownat',
    'lchown': 'use fchownat with AT_SYMLINK_NOFOLLOW',
    'getpgrp': 'use getpgid(0)',
    'utime': 'use utimensat',
    'utimes': 'use utimensat',
    'futimesat': 'use utimensat',
    'mknod': 'use mknodat',
    'ustat': 'use statfs',
    'time': 'use clock_gettime',
    'epoll_create': 'use epoll_create1',
    'inotify_init': 'use inotify_init1',
    'signalfd': 'use signalfd4',
    'eventfd': 'use eventfd2',
    'sysfs': 'read /proc/filesystems instead',
    '_sysctl': 'removed from Linux; use /proc/sys',
    'uselib': 'removed from Linux',
    'modify_ldt': 'it is x86-only',
    'arch_prctl': 'it is x86-only',
    'iopl': 'it is x86-only',
    'ioperm': 'it is x86-only',
    'set_thread_area': 'it is x86-only',
    'get_thread_area': 'it is x86-only',
    'uretprobe': 'it is x86-only',
    'uprobe': 'it is x86-only',
    'create_module': 'Linux does not implement it',
    'get_kernel_syms': 'Linux does not implement it',
    'query_module': 'Linux does not implement it',
    'getpmsg': 'Linux does not implement it',
    'putpmsg': 'Linux does not implement it',
    'afs_syscall': 'Linux does not implement it',
    'tuxcall': 'Linux does not implement it',
    'security': 'Linux does not implement it',
    'vserver': 'Linux does not implement it',
    'epoll_ctl_old': 'Linux does not implement it',
    'epoll_wait_old': 'Linux does not implement it',
}


def read_x86(path):
    """name -> number from syscall_64.tbl (common/64 rows) or unistd_64.h."""
    text = Path(path).read_text()
    table = {}
    for match in re.finditer(r'^#define __NR_(\w+)\s+(\d+)\s*$', text, re.M):
        table[match.group(1)] = int(match.group(2))
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0].isdigit() and fields[1] in ('common', '64'):
            table[fields[2]] = int(fields[0])
    return table


def read_generic(path, abis):
    table = {}
    for line in Path(path).read_text().splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0].isdigit() and fields[1] in abis:
            table[fields[2]] = int(fields[0])
    return table


def write_reference(x86_path, generic_path, version):
    x86 = read_x86(x86_path)
    arch = {name: read_generic(generic_path, abis) for name, abis in GENERIC_ABIS.items()}
    lines = [f'# Linux {version} syscall numbers: x86_64 from the x86-64 table ({Path(x86_path).name}),',
             '# aarch64 and riscv64 from scripts/syscall.tbl with the ABIs arm64 and riscv',
             '# select. "-" marks a call the target does not have. Regenerate with',
             '# tools/linux-syscalls.py --kernel; do not edit the rows by hand.',
             '# name\tx86_64\taarch64\triscv64']
    for name, number in sorted(x86.items(), key=lambda item: item[1]):
        native = [str(arch[a][name]) if name in arch[a] else '-' for a in ARCHES]
        lines.append('\t'.join([name, str(number), *native]))
    REFERENCE.write_text('\n'.join(lines) + '\n')


def read_reference():
    version = None
    rows = []
    for line in REFERENCE.read_text().splitlines():
        if line.startswith('#'):
            match = re.match(r'# Linux (\S+) syscall numbers', line)
            version = version or (match and match.group(1))
            continue
        name, x86, *native = line.split('\t')
        rows.append((name, int(x86), [None if n == '-' else int(n) for n in native]))
    return version, rows


def generate():
    version, rows = read_reference()
    by_name = {name: native for name, _, native in rows}
    missing = 'NONE'
    lines = [f'/* Generated by tools/linux-syscalls.py from tools/linux-syscalls.tsv (Linux {version}); */',
             '/* edit those. One row per x86-64 call: its number, the aarch64 and riscv64 */',
             '/* numbers (NONE: the target lacks it), its name, and what to use instead. */']
    problems = []
    # The compiler binary-searches the rows by x86-64 number.
    for name, x86, native in sorted(rows, key=lambda row: row[1]):
        target = ALIASES.get(name)
        if target:
            native = by_name[target]
        numbers = [missing if n is None else n for n in native]
        replacement = REPLACEMENTS.get(name)
        if missing in numbers and replacement is None:
            problems.append(name)
        if missing not in numbers:
            replacement = None
        note = f'"{replacement}"' if replacement else 'NULL'
        lines.append(f'{{{x86}, {numbers[0]}, {numbers[1]}, "{name}", {note}}},')
    if problems:
        raise SystemExit('tools/linux-syscalls.py: add a REPLACEMENTS entry for: ' + ', '.join(problems))
    return '\n'.join(lines) + '\n'


arguments = sys.argv[1:]
if arguments[:1] == ['--kernel'] and len(arguments) == 4:
    write_reference(*arguments[1:])
    arguments = []
text = generate()
if arguments == ['--check']:
    if not OUTPUT.exists() or OUTPUT.read_text() != text:
        print('src/linux_syscalls.inc is out of date: run tools/linux-syscalls.py')
        raise SystemExit(1)
    print('PASS linux syscalls: src/linux_syscalls.inc matches tools/linux-syscalls.tsv')
elif not arguments:
    OUTPUT.write_text(text)
else:
    raise SystemExit(__doc__)
