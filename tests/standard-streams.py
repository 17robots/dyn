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
  clock := time.try_monotonic_now()
  if !clock.ok { #panic("clock failed") }
  scratch: [8]u8 = []
  input := bufio.reader(io.stdin(), scratch[..])
  line: [64]u8 = []
  for {
    result := bufio.read_line(&input, line[..])
    if result.status == bufio.ReadStatus.Error { #panic("input failed") }
    if result.transferred > 0 || result.status != bufio.ReadStatus.End {
      written := io.println(io.stdout(), "[{}]", line[..result.transferred])
      if written.status == io.Status.Error { #panic("output failed") }
    }
    if result.status == bufio.ReadStatus.End { break }
  }
  finished := io.write_all(io.stderr(), "done\\n")
  if finished.status == io.Status.Error { #panic("stderr failed") }
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
fn main() {
  bytes: [1]u8 = []
  input := io.read(io.stdin(), bytes[..])
  if input.status != io.Status.Error || input.error == 0 || input.transferred != 0 { #panic("missing read error") }
  output := io.write_all(io.stdout(), "x")
  if output.status != io.Status.Error || output.error == 0 || output.transferred != 0 { #panic("missing write error") }
  empty := io.read(io.stdin(), bytes[..0])
  if empty.status != io.Status.Complete || empty.transferred != 0 { #panic("empty read") }
  _ = io.write_all(io.stderr(), "errors handled\\n")
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
        run(DYN, 'build', project, '--target', 'wasm32-wasi', '--quiet', '--no-cache',
            '--output', root/'streams.wasm')
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
  date := time.DateTime{}
  if !time.parse_iso8601("2024-02-29T12:34:56Z", &date) || !time.valid(&date) { #panic("date failed") }
  cursor := io.cursor("ok")
  bytes: [2]u8 = []
  result := io.read_exact(io.cursor_reader(&cursor), bytes[..])
  if result.status != io.Status.Complete { #panic("read failed") }
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
