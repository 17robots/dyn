#!/usr/bin/env python3
"""Standard streams work with redirected input; generic I/O stays portable."""
import os
from pathlib import Path
import subprocess
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
ENV = dict(os.environ, DYN_SDK=str(ROOT))


def run(*args, **kwargs):
    result = subprocess.run([str(a) for a in args], env=ENV,
                            capture_output=True, timeout=120, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{args}: exit {result.returncode}\n{result.stdout!r}\n{result.stderr!r}')
    return result


with tempfile.TemporaryDirectory(prefix='dyn-standard-streams-') as temporary:
    root = Path(temporary)
    project = root/'streams'; project.mkdir()
    (project/'main.dyn').write_text('''use "std/io"
use "std/bufio"
fn main() {
  scratch: [8]u8 = []
  input := bufio.reader(io.stdin(), scratch[..])
  line: [64]u8 = []
  for {
    result := bufio.read_line(&input, line[..])
    if result.status == io.Status.Error { #panic("input failed") }
    if result.transferred > 0 || result.status != io.Status.End {
      written := io.println(io.stdout(), "[{}]", line[..result.transferred])
      if written.status == io.Status.Error { #panic("output failed") }
    }
    if result.status == io.Status.End { break }
  }
  finished := io.write_all(io.stderr(), "done\\n")
  if finished.status == io.Status.Error { #panic("stderr failed") }
}
''')
    for options in ([], ['--release']):
        executable = root/'streams-program'
        run(DYN, 'build', project, '--quiet', '--no-cache', '--output', executable, *options)
        for data, expected in [(b'hello\n\nworld', b'[hello]\n[]\n[world]\n'), (b'', b'')]:
            result = run(executable, input=data)
            assert (result.stdout, result.stderr) == (expected, b'done\n')
        # The same stdin reader also accepts an open regular file.
        source = root/'input.txt'; source.write_bytes(b'from file\n')
        with source.open('rb') as handle:
            result = run(executable, stdin=handle)
        assert (result.stdout, result.stderr) == (b'[from file]\n', b'done\n')
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
fn main() {
  cursor := io.cursor("ok")
  bytes: [2]u8 = []
  result := io.read_exact(io.cursor_reader(&cursor), bytes[..])
  if result.status != io.Status.Complete { #panic("read failed") }
}
''')
    for target in ('x86_64-windows', 'aarch64-macos', 'wasm32-browser', 'aarch64-linux'):
        run(DYN, 'check', project, '--target', target, '--quiet', '--no-cache')
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
print('PASS standard streams: pipes, files, EOF, stderr, WASI link, portable I/O and terminal controls')
