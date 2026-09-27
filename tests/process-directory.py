#!/usr/bin/env python3
"""Child directories are isolated, failures synchronous, ownership transferable."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build'/('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve()
with tempfile.TemporaryDirectory(prefix='dyn process directory ') as temporary:
    root = Path(temporary)
    nested = root/'child directory'; nested.mkdir()
    (root/'marker').write_text('parent')
    (nested/'marker').write_text('child')
    child = root/'child'; child.mkdir()
    (child/'main.dyn').write_text('''use "std/fs"\nuse "std/io"\nuse "std/mem"
fn main() { storage: [128]u8 = [] arena := mem.arena_from_buffer(storage[..])
  value := fs.read_all(&arena, "marker", 16) if !value.ok { #panic("child cwd") }
  _ = io.write(io.stdout(), value.data)
}''')
    executable = root/('child.exe' if os.name == 'nt' else 'child-bin')
    subprocess.run([str(DYN),'build',str(child),'--output',str(executable),'--jobs','1'], check=True, timeout=30)
    parent = root/'parent'; parent.mkdir()
    source = '''use "std/process"\nuse "std/fs"\nuse "std/mem"\nuse "std/bytes"\nuse "std/errors"
use "std/io"
fn fail(message: []const u8) { _ = fs.write_all("failure", message) #panic(message) }
fn main() {
  storage: [65536]u8 = [] arena := mem.arena_from_buffer(storage[..])
  command: []const u8 = EXECUTABLE arguments: [1][]const u8 = [command]
  configuration := process.options() configuration.directory = DIRECTORY
  output: [32]u8 = [] error_output: [32]u8 = []
  result := process.capture(&arena, command, arguments[..], configuration, output[..], error_output[..], 2000)
  if !result.ok || !bytes.equal(result.output, "child") {
    report := fs.create("capture-result")
    if report.ok { _ = io.println(fs.writer(&report.file), "ok={} error={} exit={} output={} stderr={}", result.ok, result.error, result.exit.code, result.output, result.errors) _ = fs.close(&report.file) }
    fail("child directory capture")
  }
  current := fs.read_all(&arena, "marker", 16)
  if !current.ok || !bytes.equal(current.data, "parent") { fail("changed parent directory") }
  configuration.directory = "missing directory"
  rejected := process.spawn(&arena, command, arguments[..], configuration)
  if rejected.ok || rejected.child.active { fail("missing directory accepted") }
  configuration.directory = "bad\\0directory"
  if process.spawn(&arena, command, arguments[..], configuration).kind != errors.Kind.InvalidInput { fail("NUL directory") }
  configuration.directory = ""
  inherited := process.capture(&arena, command, arguments[..], configuration, output[..], error_output[..], 2000)
  if !inherited.ok || !bytes.equal(inherited.output, "parent") { fail("inherit directory") }
  owned := process.spawn(&arena, command, arguments[..], configuration)
  if !owned.ok { fail("spawn transfer") }
  moved := process.take(&owned.child)
  if owned.child.active || process.wait(&owned.child, false).kind != errors.Kind.InvalidState { fail("moved owner active") }
  completed := process.wait(&moved, false)
  if !completed.ok || !completed.finished || moved.active { fail("transferred child wait") }
}'''.replace('EXECUTABLE', json.dumps(str(executable),ensure_ascii=False)).replace('DIRECTORY', json.dumps(str(nested),ensure_ascii=False))
    (parent/'main.dyn').write_text(source,encoding='utf-8')
    for mode in ('debug','release'):
        program = root/('parent.exe' if os.name == 'nt' else 'parent-bin')
        subprocess.run([str(DYN),'build',str(parent),'--'+mode,'--output',str(program),'--jobs','1'],check=True,timeout=30)
        result = subprocess.run([str(program)],cwd=root,capture_output=True,timeout=10)
        detail = '\n'.join(path.read_text(errors='replace') for path in (root/'failure',root/'capture-result') if path.exists())
        assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr, detail)
print('PASS child cwd isolation, inheritance, synchronous failure and ownership transfer')
