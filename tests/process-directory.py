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
    (child/'main.dyn').write_text('''use "std/fail"
use "std/fs"
use "std/io"
use "std/mem"
fn main() { storage: [128 + mem.ArenaBufferOverhead]u8
arena := mem.arena_from_buffer(storage[..])
  status: fail.Status
  value := fs.read_all(arena, &status, "marker", 16)
  if status.failed { #panic("child cwd") }
  io.print("{}", value)
}''')
    executable = root/('child.exe' if os.name == 'nt' else 'child-bin')
    subprocess.run([str(DYN),'build',str(child),'--output',str(executable),'--jobs','1'], check=True, timeout=30)
    parent = root/'parent'; parent.mkdir()
    source = 'use "std/process"\nuse failures "std/fail"\nuse "std/fs"\nuse "std/mem"\nuse "std/bytes"\nuse "std/io"\nfn fail(message: []const u8) { status: failures.Status\nfs.write_all(&status, "failure", message)\n#panic(message) }\nfn main() {\n  storage: [65536]u8\n  arena := mem.arena_from_buffer(storage[..])\n  command: []const u8 = EXECUTABLE\n  arguments: [1][]const u8 = [command]\n  configuration := process.Options{}\n  configuration.directory = DIRECTORY\n  output: [32]u8\n  error_output: [32]u8\n  status: failures.Status\n  result := process.capture(arena, &status, command, arguments[..], configuration, process.CaptureOptions{timeout_milliseconds: 2000})\n  if status.failed || !bytes.equal(result.output, "child") {\n    report_status: failures.Status\n    report := fs.create(&report_status, "capture-result")\n    if !report_status.failed { io.println_to(&report_status, fs.writer(&report), "ok={} error={} exit={} output={} stderr={}", !status.failed, status.failure.native, result.exit.code, result.output, result.errors)\n    fs.close(&report) }\n    fail("child directory capture")\n  }\n  current_status: failures.Status\n  current := fs.read_all(arena, &current_status, "marker", 16)\n  if current_status.failed || !bytes.equal(current, "parent") { fail("changed parent directory") }\n  configuration.directory = "missing directory"\n  missing: failures.Status\n  rejected := process.spawn(arena, &missing, command, arguments[..], configuration)\n  if !missing.failed || rejected.active { fail("missing directory accepted") }\n  configuration.directory = "bad\\0directory"\n  bad: failures.Status\n  _ = process.spawn(arena, &bad, command, arguments[..], configuration)\n  if bad.failure.kind != failures.Kind.InvalidInput { fail("NUL directory") }\n  configuration.directory = ""\n  inherited := process.capture(arena, &status, command, arguments[..], configuration, process.CaptureOptions{timeout_milliseconds: 2000})\n  if status.failed || !bytes.equal(inherited.output, "parent") { fail("inherit directory") }\n  owned := process.spawn(arena, &status, command, arguments[..], configuration)\n  if status.failed { fail("spawn") }\n  completed := process.wait(&status, owned, false)\n  if status.failed || !completed.finished || owned.active { fail("child wait") }\n  twice: failures.Status\n  _ = process.wait(&twice, owned, false)\n  if twice.failure.kind != failures.Kind.InvalidState { fail("waited twice") }\n}'.replace('EXECUTABLE', json.dumps(str(executable),ensure_ascii=False)).replace('DIRECTORY', json.dumps(str(nested),ensure_ascii=False))
    (parent/'main.dyn').write_text(source,encoding='utf-8')
    for mode in ('debug','release'):
        program = root/('parent.exe' if os.name == 'nt' else 'parent-bin')
        subprocess.run([str(DYN),'build',str(parent),'--'+mode,'--output',str(program),'--jobs','1'],check=True,timeout=30)
        result = subprocess.run([str(program)],cwd=root,capture_output=True,timeout=10)
        detail = '\n'.join(path.read_text(errors='replace') for path in (root/'failure',root/'capture-result') if path.exists())
        assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr, detail)
print('PASS child cwd isolation, inheritance, synchronous failure and ownership transfer')
