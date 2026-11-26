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
fn main() { storage: [128 + mem.ArenaBufferOverhead]u8
arena := mem.arena_from_buffer(storage[..])
  value := fs.read_all(arena, "marker", 16) catch { #panic("child cwd") }
  io.print("{}", value)
}''')
    executable = root/('child.exe' if os.name == 'nt' else 'child-bin')
    subprocess.run([str(DYN),'build',str(child),'--output',str(executable),'--jobs','1'], check=True, timeout=30)
    parent = root/'parent'; parent.mkdir()
    source = r"""use "std/process"
use "std/fs"
use "std/mem"
use "std/bytes"
use "std/io"
// Leaves message where the test runner can read it, then stops.
fn stop(message: []const u8) {
  fs.write_all("failure", message) catch {}
  #panic(message)
}
fn is_kind(err: io.IoErr, invalid: bool) bool {
  case err {
    .InvalidInput => { return invalid }
    _ => { return !invalid }
  }
}
fn capture(arena: *mem.Arena, command: []const u8, arguments: [][]const u8, configuration: process.Options) process.Captured!io.IoErr {
  return try process.capture(arena, command, arguments, configuration, process.CaptureOptions{timeout_milliseconds: 2000})
}
// Whether spawning fails, and with InvalidInput when invalid is true.
fn spawn_fails(arena: *mem.Arena, command: []const u8, arguments: [][]const u8, configuration: process.Options, invalid: bool) bool {
  _ = process.spawn(arena, command, arguments, configuration) catch err { return is_kind(err, invalid) }
  return false
}
fn run(arena: *mem.Arena) !io.IoErr {
  command: []const u8 = EXECUTABLE
  arguments: [1][]const u8 = [command]
  configuration := process.Options{}
  configuration.directory = DIRECTORY
  result := try capture(arena, command, arguments[..], configuration)
  if !bytes.equal(result.output, "child") { stop("child directory capture") }
  current := try fs.read_all(arena, "marker", 16)
  if !bytes.equal(current, "parent") { stop("changed parent directory") }
  configuration.directory = "missing directory"
  if !spawn_fails(arena, command, arguments[..], configuration, false) { stop("missing directory accepted") }
  configuration.directory = "bad\0directory"
  if !spawn_fails(arena, command, arguments[..], configuration, true) { stop("NUL directory") }
  configuration.directory = ""
  inherited := try capture(arena, command, arguments[..], configuration)
  if !bytes.equal(inherited.output, "parent") { stop("inherit directory") }
  owned := try process.spawn(arena, command, arguments[..], configuration)
  completed := try process.wait(owned, false)
  if !completed.finished || owned.active { stop("child wait") }
  _ = process.wait(owned, false) catch err {
    if !is_kind(err, true) { stop("waited twice") }
    return
  }
  stop("waited twice")
}
fn main() {
  storage: [65536]u8
  arena := mem.arena_from_buffer(storage[..])
  run(arena) catch err {
    report := fs.create("capture-result") catch { #panic("report") }
    io.println_to(fs.writer(&report), "error={}", err) catch {}
    fs.close(&report)
    stop("process directory operations")
  }
}""".replace('EXECUTABLE', json.dumps(str(executable),ensure_ascii=False)).replace('DIRECTORY', json.dumps(str(nested),ensure_ascii=False))
    (parent/'main.dyn').write_text(source,encoding='utf-8')
    for mode in ('debug','release'):
        program = root/('parent.exe' if os.name == 'nt' else 'parent-bin')
        subprocess.run([str(DYN),'build',str(parent),'--'+mode,'--output',str(program),'--jobs','1'],check=True,timeout=30)
        result = subprocess.run([str(program)],cwd=root,capture_output=True,timeout=10)
        detail = '\n'.join(path.read_text(errors='replace') for path in (root/'failure',root/'capture-result') if path.exists())
        assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr, detail)
print('PASS child cwd isolation, inheritance, synchronous failure and ownership transfer')
