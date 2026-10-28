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
    (child/'main.dyn').write_text('''use "std/fs"
use "std/io"
use "std/mem"
fn main() { storage: [128 + mem.ArenaBufferOverhead]u8 = []
arena := mem.arena_from_buffer(storage[..])
  value := fs.read_all(arena, "marker", 16)
  if !value.ok { #panic("child cwd") }
  _ = io.write(io.stdout(), value.value)
}''')
    executable = root/('child.exe' if os.name == 'nt' else 'child-bin')
    subprocess.run([str(DYN),'build',str(child),'--output',str(executable),'--jobs','1'], check=True, timeout=30)
    parent = root/'parent'; parent.mkdir()
    source = 'use "std/process"\nuse "std/fs"\nuse "std/mem"\nuse "std/bytes"\nuse "std/errors"\nuse "std/io"\nfn fail(message: []const u8) { _ = fs.write_all("failure", message)\n#panic(message) }\nfn main() {\n  storage: [65536]u8 = []\n  arena := mem.arena_from_buffer(storage[..])\n  command: []const u8 = EXECUTABLE\n  arguments: [1][]const u8 = [command]\n  configuration := process.Options{}\n  configuration.directory = DIRECTORY\n  output: [32]u8 = []\n  error_output: [32]u8 = []\n  result := process.capture(arena, command, arguments[..], configuration, process.CaptureOptions{timeout_milliseconds: 2000})\n  if !result.ok || !bytes.equal(result.output, "child") {\n    report := fs.create("capture-result")\n    if report.ok { _ = io.println(fs.writer(&report.value), "ok={} error={} exit={} output={} stderr={}", result.ok, result.error, result.exit.code, result.output, result.errors)\n    _ = fs.close(&report.value) }\n    fail("child directory capture")\n  }\n  current := fs.read_all(arena, "marker", 16)\n  if !current.ok || !bytes.equal(current.value, "parent") { fail("changed parent directory") }\n  configuration.directory = "missing directory"\n  rejected := process.spawn(arena, command, arguments[..], configuration)\n  if rejected.ok || rejected.value.active { fail("missing directory accepted") }\n  configuration.directory = "bad\\0directory"\n  if process.spawn(arena, command, arguments[..], configuration).kind != errors.Kind.InvalidInput { fail("NUL directory") }\n  configuration.directory = ""\n  inherited := process.capture(arena, command, arguments[..], configuration, process.CaptureOptions{timeout_milliseconds: 2000})\n  if !inherited.ok || !bytes.equal(inherited.output, "parent") { fail("inherit directory") }\n  owned := process.spawn(arena, command, arguments[..], configuration)\n  if !owned.ok { fail("spawn transfer") }\n  moved := process.take(&owned.value)\n  if owned.value.active || process.wait(&owned.value, false).kind != errors.Kind.InvalidState { fail("moved owner active") }\n  completed := process.wait(&moved, false)\n  if !completed.ok || !completed.finished || moved.active { fail("transferred child wait") }\n}'.replace('EXECUTABLE', json.dumps(str(executable),ensure_ascii=False)).replace('DIRECTORY', json.dumps(str(nested),ensure_ascii=False))
    (parent/'main.dyn').write_text(source,encoding='utf-8')
    for mode in ('debug','release'):
        program = root/('parent.exe' if os.name == 'nt' else 'parent-bin')
        subprocess.run([str(DYN),'build',str(parent),'--'+mode,'--output',str(program),'--jobs','1'],check=True,timeout=30)
        result = subprocess.run([str(program)],cwd=root,capture_output=True,timeout=10)
        detail = '\n'.join(path.read_text(errors='replace') for path in (root/'failure',root/'capture-result') if path.exists())
        assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr, detail)
print('PASS child cwd isolation, inheritance, synchronous failure and ownership transfer')
