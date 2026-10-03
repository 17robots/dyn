#!/usr/bin/env python3
"""Runtime cache inputs and per-thread unwind-frame isolation on a Linux host."""
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve()


def run(command, **kwargs):
    result = subprocess.run(list(map(str, command)), capture_output=True,
                            text=True, timeout=60, **kwargs)
    assert result.returncode == 0, (command, result.stdout, result.stderr)
    return result


HARNESS = r'''
#define _XOPEN_SOURCE 700
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct DynUnwind DynUnwind;
struct DynUnwind { DynUnwind *previous; uintptr_t saved[15]; };
void dyn_unwind_link(DynUnwind *);
void dyn_unwind_begin(const unsigned char *, uint64_t);
static pthread_barrier_t barrier;
static _Thread_local DynUnwind *expected;
static _Thread_local int jumped;
void dyn_unwind_jump(DynUnwind *frame) {
  if (frame != expected) abort();
  jumped = 1;
}
void dyn_panic(const unsigned char *message, uint64_t length) {
  (void)message; (void)length;
  abort();
}
long dyn_syscall6(long a, long b, long c, long d, long e, long f, long g) {
  (void)a; (void)b; (void)c; (void)d; (void)e; (void)f; (void)g;
#ifdef HARNESS_APPLE
  /* Darwin must use pthread_self directly, not a Linux gettid syscall. */
  abort();
#else
  return (long)(uintptr_t)pthread_self();
#endif
}
static void *worker(void *unused) {
  (void)unused;
  DynUnwind outer = {0}, inner = {0};
  dyn_unwind_link(&outer);
  dyn_unwind_link(&inner);
  expected = &inner;
  pthread_barrier_wait(&barrier);
  dyn_unwind_begin((const unsigned char *)"thread panic", 12);
  if (!jumped || inner.previous != &outer) abort();
  pthread_barrier_wait(&barrier);
  return NULL;
}
int main(void) {
  pthread_t threads[8];
  if (pthread_barrier_init(&barrier, NULL, 8)) return 2;
  for (unsigned i = 0; i < 8; ++i)
    if (pthread_create(&threads[i], NULL, worker, NULL)) return 2;
  for (unsigned i = 0; i < 8; ++i)
    if (pthread_join(threads[i], NULL)) return 2;
  pthread_barrier_destroy(&barrier);
  puts("correct thread frames");
  return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-runtime-audit-') as temporary:
    root = Path(temporary)
    if platform.system() == 'Linux':
        harness = root / 'thread-harness.c'
        harness.write_text(HARNESS)
        cc = shlex.split(os.environ.get('CC', 'cc'))
        for apple in (False, True):
            name = 'darwin-branch' if apple else 'linux-branch'
            runtime_object = root / (name + '.o')
            # Separate translation units keep Darwin's opaque pthread_self
            # declaration separate from the Linux host's pthread headers.
            run([*cc, '-std=c11', '-O2', '-fno-builtin',
                 *(['-D__APPLE__'] if apple else []), '-c',
                 ROOT / 'runtime/reference_support.c', '-o', runtime_object])
            executable = root / name
            run([*cc, '-std=c11', '-O2', '-fno-builtin', '-pthread',
                 *(['-DHARNESS_APPLE'] if apple else []), harness,
                 runtime_object, '-o', executable])
            result = run([executable])
            assert 'correct thread frames' in result.stdout
        print('PASS Linux-host unwind isolation: Linux and Darwin code branches')
    else:
        print('SKIP Linux-host unwind branch harness: requires Linux')

    if platform.system() == 'Linux' and platform.machine().lower() in ('x86_64', 'amd64'):
        objcopy = shutil.which('llvm-objcopy') or shutil.which('objcopy')
        assert objcopy, 'runtime cache regression requires objcopy'
        sdk = root / 'sdk'
        binary = sdk / 'bin'
        binary.mkdir(parents=True)
        compiler = binary / 'dyn'
        shutil.copy2(DYN, compiler)
        shutil.copytree(ROOT / 'std', sdk / 'std')
        for name in ('dynrt_start.o', 'dynrt_release.o', 'dynrt_support.o'):
            source = DYN.parent / name
            if not source.exists():
                source = DYN.parent.parent / 'lib/dyn' / name
            shutil.copy2(source, binary / name)
        project = root / 'app'
        project.mkdir()
        (project / 'main.dyn').write_text('fn main() {}\n')
        env = dict(os.environ, DYN_SDK=str(sdk), DYN_CACHE_DIR=str(root / 'cache'))

        for release in (False, True):
            output = root / ('program-release' if release else 'program-debug')
            command = [compiler, 'build', project, '--output', output,
                       '--jobs', '1', '--timings', *(['--release'] if release else [])]
            cold = run(command, env=env)
            assert 'timing link' in cold.stderr, cold.stderr
            warm = run(command, env=env)
            assert 'timing link' not in warm.stderr, warm.stderr
            for name in ('dynrt_release.o' if release else 'dynrt_start.o',
                         'dynrt_support.o'):
                runtime = binary / name
                original = runtime.read_bytes()
                marker = root / 'marker'
                marker.write_bytes(b'runtime fingerprint regression\n')
                replacement = root / 'changed.o'
                run([objcopy, '--add-section', f'.dyn.runtime.audit={marker}',
                     runtime, replacement])
                runtime.write_bytes(replacement.read_bytes())
                assert runtime.read_bytes() != original
                changed = run(command, env=env)
                assert 'timing link' in changed.stderr, (
                    name, release, 'changed runtime reused executable cache', changed.stderr)
                run([output])
                unchanged = run(command, env=env)
                assert 'timing link' not in unchanged.stderr, unchanged.stderr
                # A cached executable must not conceal missing or corrupt
                # selected runtime inputs. Only this disposable SDK is edited.
                runtime.unlink()
                missing = subprocess.run(list(map(str, command)), env=env,
                                         capture_output=True, text=True, timeout=60)
                assert missing.returncode != 0, (name, release, 'missing runtime cache hit')
                runtime.write_bytes(b'not an object file\n')
                corrupt = subprocess.run(list(map(str, command)), env=env,
                                         capture_output=True, text=True, timeout=60)
                assert corrupt.returncode != 0, (name, release, 'corrupt runtime cache hit')
                runtime.write_bytes(original)
                run(command, env=env)
        print('PASS isolated runtime-object cache invalidation (debug/release)')
    else:
        print('SKIP x86-64 Linux runtime cache fixture: requires matching host')

print('Native Windows/Darwin thread execution is not covered by this host harness.')
