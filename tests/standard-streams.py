#!/usr/bin/env python3
"""Standard streams work with redirected input; generic I/O stays portable."""
import argparse
import os
from pathlib import Path
import subprocess
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build'/('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve())
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--host-only', action='store_true', help='Run native streams without cross-target runtimes')
args = parser.parse_args()
ENV = dict(os.environ, DYN_SDK=str(ROOT))


def run(*args, **kwargs):
    kwargs.setdefault('stdout', subprocess.PIPE)
    kwargs.setdefault('stderr', subprocess.PIPE)
    result = subprocess.run([str(a) for a in args], env=ENV, timeout=120, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{args}: exit {result.returncode}\n{result.stdout!r}\n{result.stderr!r}')
    return result


with tempfile.TemporaryDirectory(prefix='dyn-standard-streams-') as temporary:
    root = Path(temporary)
    project = root/'streams'; project.mkdir()
    (project/'main.dyn').write_text('''use "std/io"
use "std/bufio"
use "std/time"
fn main() {
  clock := time.monotonic_now()
  _ = clock
  scratch: [64]u8
  input := bufio.reader(io.stdin(), scratch[..])
  for {
    line := bufio.read_line(&input) catch { #panic("input failed") }
    if input.ended { break }
    io.println_to(io.stdout(), "[{}]", line) catch { #panic("output failed") }
  }
  io.write(io.stderr(), "done\\n") catch { #panic("stderr failed") }
}
''')
    for options in ([], ['--release']):
        executable = root/('streams-program.exe' if os.name == 'nt' else 'streams-program')
        run(DYN, 'build', project, '--quiet', '--no-cache', '--output', executable, *options)
        for data, expected in [(b'hello\n\nworld', b'[hello]\n[]\n[world]\n'), (b'', b''),
                               ('café\n'.encode(), '[café]\n'.encode()),
                               (b'windows\r\n', b'[windows]\n'),
                               (b'line\n' * 4096, b'[line]\n' * 4096)]:
            result = run(executable, input=data)
            assert (result.stdout, result.stderr) == (expected, b'done\n')
        # The same stdin reader also accepts an open regular file.
        source = root/'input.txt'; source.write_bytes(b'from file\n')
        with source.open('rb') as handle:
            result = run(executable, stdin=handle)
        assert (result.stdout, result.stderr) == (b'[from file]\n', b'done\n')
    errors = root/'errors'; errors.mkdir()
    (errors/'main.dyn').write_text('''use "std/io"
fn read_fails(destination: []u8) bool {
  _ = io.read(io.stdin(), destination) catch { return true }
  return false
}
fn write_fails() bool {
  output := io.stdout()
  _ = output.write(output.data, "x") catch { return true }
  return false
}
fn main() {
  bytes: [1]u8
  if !read_fails(bytes[..]) { #panic("missing read error") }
  if !write_fails() { #panic("missing write error") }
  if read_fails(bytes[..0]) { #panic("empty read") }
  io.eprint("errors handled\\n")
}
''')
    failure_program = root/('errors.exe' if os.name == 'nt' else 'errors-program')
    run(DYN, 'build', errors, '--quiet', '--no-cache', '--output', failure_program)
    with (root/'write-only').open('wb') as unreadable, (root/'input.txt').open('rb') as unwritable:
        result = run(failure_program, stdin=unreadable, stdout=unwritable)
    assert result.stderr == b'errors handled\n'
    if not args.host_only:
        # Link the WASI variant: accidental std/io -> std/os/wasi -> std/io cycles
        # and missing runtime imports must fail this check.
        # Both public APIs must share one declaration for each runtime symbol.
        (project/'wasi.dyn').write_text('''#target(kernel: wasi)
use "std/os/wasi"
fn check_descriptors() {
  bytes: [1]u8
  if (wasi.read(0, bytes[..0]) catch 99) != 0 { #panic("empty descriptor read") }
  _ = wasi.write(4294967295, "x") catch { return }
  #panic("descriptor error")
}
''')
        source = project/'main.dyn'
        source.write_text(source.read_text().replace('  clock :=', '  check_descriptors()\n  clock :='))
        for options in ([], ['--release']):
            run(DYN, 'build', project, '--target', 'wasm32-wasi', '--quiet', '--no-cache',
                '--output', root/'streams.wasm', *options)
            node = shutil.which('node')
            if node:
                runner = root/'wasi.cjs'
                runner.write_text("""const { WASI } = require('node:wasi');
        const fs = require('node:fs');
        const wasi = new WASI({version: 'preview1', returnOnExit: true});
        const moduleBytes = fs.readFileSync(process.argv[2]);
        const instance = new WebAssembly.Instance(new WebAssembly.Module(moduleBytes), wasi.getImportObject());
        process.exitCode = wasi.start(instance);
        """)
                result = run(node, '--no-warnings', runner, root/'streams.wasm', input=b'wasi\nlast')
                assert (result.stdout, result.stderr) == (b'[wasi]\n[last]\n', b'done\n')
                print('PASS WASI standard-stream execution')
    project = root/'portable'; project.mkdir()
    (project/'main.dyn').write_text('''use "std/io"
use "std/time"
fn main() {
  date := time.parse_iso8601("2024-02-29T12:34:56Z") catch { #panic("date failed") }
  if !time.valid(&date) { #panic("date failed") }
  cursor := io.cursor("ok")
  bytes: [2]u8
  read := io.read_exact(io.cursor_reader(&cursor), bytes[..]) catch { #panic("read failed") }
  if read != 2 { #panic("read failed") }
}
''')
    for target in ('x86_64-windows', 'aarch64-macos', 'wasm32-browser', 'aarch64-linux'):
        run(DYN, 'check', project, '--target', target, '--quiet', '--no-cache')
    if not args.host_only:
        project = root/'terminal'; project.mkdir()
        (project/'main.dyn').write_text('''use "std/terminal"
    fn main() {
      key := terminal.key_decode("a")
      if key.kind != terminal.KeyKind.Text || key.codepoint != 97 { #panic("key decode") }
      if terminal.is_attached(0) { #panic("redirected stdin is not a terminal") }
    }
    ''')
        run(DYN, 'build', project, '--quiet', '--no-cache', '--output', root/'terminal-program')
        run(root/'terminal-program', input=b'')
print('PASS standard streams: pipes, files, EOF, stderr, byte preservation and portable I/O')
