#!/usr/bin/env python3
"""Linux preview runner: namespace/permission isolation, seccomp and bounded resources.

Requires bubblewrap and libseccomp; fails closed. No network or host home mounts.
This reduces exposure; it is not a claim against kernel vulnerabilities.
"""
import argparse
import ctypes
import ctypes.util
import errno
import hashlib
import json
import os
from pathlib import Path
import resource
import selectors
import shutil
import signal
import subprocess
import tempfile
import time


class Compare(ctypes.Structure):
    _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_int),
                ('datum_a', ctypes.c_uint64), ('datum_b', ctypes.c_uint64)]


def seccomp_filter(compiling):
    library = ctypes.util.find_library('seccomp')
    if not library:
        raise RuntimeError('libseccomp required; refusing unsandboxed execution')
    lib = ctypes.CDLL(library, use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(Compare)]
    lib.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    context = lib.seccomp_init(0x7fff0000)  # ALLOW, with explicit denied kernel interfaces.
    if not context:
        raise RuntimeError('cannot create seccomp policy')
    output = tempfile.TemporaryFile()
    try:
        denied = ('socket', 'socketpair', 'ptrace', 'process_vm_readv', 'process_vm_writev',
                  'mount', 'umount2', 'pivot_root', 'unshare', 'setns', 'bpf',
                  'keyctl', 'add_key', 'request_key', 'perf_event_open', 'userfaultfd',
                  'io_uring_setup', 'io_uring_enter', 'io_uring_register', 'reboot',
                  'kexec_load', 'kexec_file_load', 'init_module', 'finit_module',
                  'delete_module', 'open_by_handle_at')
        if not compiling:
            denied += ('clone', 'fork', 'vfork')
        for name in (*denied, 'clone3'):
            number = lib.seccomp_syscall_resolve_name(name.encode())
            if number < 0:
                continue
            code = errno.ENOSYS if name == 'clone3' else errno.EPERM
            if lib.seccomp_rule_add_array(context, 0x00050000 | code, number, 0, None):
                raise RuntimeError('cannot restrict syscall: ' + name)
        if lib.seccomp_export_bpf(context, output.fileno()):
            raise RuntimeError('cannot export seccomp policy')
        output.seek(0)
        return output
    except BaseException:
        output.close()
        raise
    finally:
        lib.seccomp_release(context)


def bounded(command, *, compiling=False, timeout=3, output_limit=65536):
    # rlimits are applied by a dedicated child launcher, not preexec_fn in a threaded server.
    launch = [os.sys.executable, str(Path(__file__).resolve()), '_limit',
              str(2048 if compiling else 256), str(max(1, int(timeout))), *command]
    with seccomp_filter(compiling) as policy:
        # Insert seccomp option immediately before sandbox command delimiter.
        at = launch.index('--')
        launch[at:at] = ['--seccomp', str(policy.fileno())]
        process = subprocess.Popen(launch, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, pass_fds=(policy.fileno(),), start_new_session=True)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
        selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
        captured = {'stdout': bytearray(), 'stderr': bytearray()}
        deadline = time.monotonic() + timeout
        reason = None
        try:
            while selector.get_map():
                if time.monotonic() >= deadline:
                    reason = 'timeout'; break
                for key, _ in selector.select(min(0.1, max(0, deadline-time.monotonic()))):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj); continue
                    destination = captured[key.data]
                    remaining = output_limit - sum(map(len, captured.values()))
                    destination.extend(chunk[:max(0,remaining)])
                    if len(chunk) > remaining:
                        reason = 'output-limit'; break
                if reason:
                    break
        finally:
            if reason or process.poll() is None:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            process.wait(timeout=5)
            selector.close()
            process.stdout.close(); process.stderr.close()
        return dict(exit_code=process.returncode, limit=reason,
                    **{key: value.decode('utf-8', errors='replace') for key, value in captured.items()})


def base_sandbox(work, reads=(), writes=()):
    bwrap = shutil.which('bwrap')
    if not bwrap:
        raise RuntimeError('bubblewrap required; refusing unsandboxed execution')
    command = [bwrap, '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
               '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'HOME', '/tmp',
               '--ro-bind', '/usr', '/usr', '--proc', '/proc', '--dev', '/dev',
               '--size', '67108864', '--tmpfs', '/tmp', '--bind', str(work), '/work', '--chdir', '/work']
    for directory in ('/bin','/lib','/lib64'):
        path=Path(directory)
        if path.is_symlink(): command += ['--symlink', os.readlink(path), directory]
        elif path.exists(): command += ['--ro-bind', directory, directory]
    if Path('/etc/ld.so.cache').exists():
        command += ['--ro-bind','/etc/ld.so.cache','/etc/ld.so.cache']
    for mode,paths in (('--ro-bind',reads),('--bind',writes)):
        for i,path in enumerate(paths):
            source=Path(path).resolve(strict=True)
            if not source.is_dir(): raise RuntimeError('capability mount must be a directory')
            destination=f'/cap/{"read" if mode=="--ro-bind" else "write"}/{i}'
            command += [mode,str(source),destination]
    return command


def run_source(source, dyn, sdk, runtimes, *, reads=(), writes=(), compile_timeout=20, run_timeout=3):
    with tempfile.TemporaryDirectory(prefix='dyn-isolated-') as directory:
        work=Path(directory)
        (work/'input').mkdir()
        (work/'input/main.dyn').write_text(source)
        common=base_sandbox(work)
        for runtime in sorted(Path(runtimes).resolve().glob('dynrt_*.o')):
            common += ['--ro-bind',str(runtime),'/tool/'+runtime.name]
        sdk_path=Path(sdk).resolve()
        if (sdk_path/'std').is_dir():
            common += ['--ro-bind',str(sdk_path),'/sdk']
        else:
            common += ['--ro-bind',str(sdk_path),'/sdk/std']
            if (sdk_path/'vendor').is_dir():
                common += ['--ro-bind',str(sdk_path/'vendor'),'/sdk/vendor']
        compile_command=common+['--ro-bind',str(Path(dyn).resolve()),'/tool/dyn',
            '--setenv','DYN_SDK','/sdk','--setenv','DYN_CACHE_DIR','/tmp/cache',
            '--','/tool/dyn','build','/work/input','--jobs','1','--no-cache','--quiet',
            '--diagnostics','json','--output','/work/program']
        compiled=bounded(compile_command,compiling=True,timeout=compile_timeout)
        report={'schema':1,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
                'compiler_sha256':hashlib.sha256(Path(dyn).read_bytes()).hexdigest(),
                'compile':compiled,'run':None}
        if compiled['exit_code']==0 and not compiled['limit']:
            report['run']=bounded(base_sandbox(work,reads,writes)+['--','/work/program'],timeout=run_timeout)
        return report


def main():
    if len(os.sys.argv)>1 and os.sys.argv[1]=='_limit':
        memory=int(os.sys.argv[2])*1024*1024; cpu=int(os.sys.argv[3])
        resource.setrlimit(resource.RLIMIT_AS,(memory,memory))
        resource.setrlimit(resource.RLIMIT_CPU,(cpu,cpu))
        resource.setrlimit(resource.RLIMIT_FSIZE,(32*1024*1024,32*1024*1024))
        resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        # Linux NPROC counts all threads sharing this real UID, including host tools.
        existing = 0
        for entry in Path('/proc').iterdir():
            if entry.name.isdigit():
                try:
                    if entry.stat().st_uid == os.getuid():
                        existing += len(list((entry/'task').iterdir()))
                except (OSError, PermissionError):
                    pass
        process_limit = existing + 64
        resource.setrlimit(resource.RLIMIT_NPROC,(process_limit,process_limit))
        os.execvp(os.sys.argv[4],os.sys.argv[4:])
    parser=argparse.ArgumentParser(description=__doc__)
    installed = Path(__file__).resolve().parent.name == 'bin'
    prefix = Path(__file__).resolve().parents[1]
    parser.add_argument('source',type=Path)
    parser.add_argument('--dyn',default=os.environ.get('DYN',str(prefix/'bin/dyn') if installed else 'build/dyn'))
    parser.add_argument('--sdk',default=os.environ.get('DYN_SDK',str(prefix/'share/dyn') if installed else 'compiler'))
    parser.add_argument('--runtimes',default=str(prefix/'lib/dyn') if installed else 'build')
    parser.add_argument('--read',action='append',default=[])
    parser.add_argument('--write',action='append',default=[])
    args=parser.parse_args()
    try:
        report=run_source(args.source.read_text(),args.dyn,args.sdk,args.runtimes,reads=args.read,writes=args.write)
        print(json.dumps(report,indent=2))
        return 0 if report['run'] and report['run']['exit_code']==0 and not report['run']['limit'] else 1
    except (OSError,RuntimeError,subprocess.SubprocessError) as error:
        parser.exit(2,f'error: {error}\n')


if __name__=='__main__':
    raise SystemExit(main())
