#!/usr/bin/env python3
"""Bounded Linux capture regression: growth, policies, lifetimes and reaping."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
if sys.platform != 'linux':
    print('SKIP Linux capture regression')
    sys.exit(0)
with tempfile.TemporaryDirectory(prefix='dyn-capture-arena-') as temporary:
    root = Path(temporary)
    child = root / 'child.py'
    child.write_text('''import os, sys, time
mode = sys.argv[1]
if mode == 'large':
    for i in range(128):
        os.write(1, bytes([i]) * 1024)
        os.write(2, bytes([255-i]) * 1024)
elif mode == 'out':
    os.write(1, b'O' * 8192)
elif mode == 'err':
    os.write(2, b'E' * 8192)
elif mode == 'empty':
    pass
elif mode == 'limit':
    while True:
        os.write(1, b'O' * 1024)
        os.write(2, b'E' * 1024)
elif mode == 'sleep':
    os.write(1, b'prefix')
    os.write(2, b'error')
    time.sleep(30)
elif mode == 'exit':
    os.write(1, b'ok')
    sys.exit(7)
elif mode == 'exhaust':
    with open(sys.argv[2], 'w') as f: f.write(str(os.getpid()))
    while True: os.write(1, b'X' * 4096)
''')
    source = r'''use "std/process"
use "std/mem"
use "std/bytes"
use "std/errors"
fn copy(arena: *mem.Arena, source: []const u8) []u8 {
  destination := mem.push_bytes_uninit(arena, #len(source))
  _ = mem.move(destination, source)
  return destination
}
fn main() {
  storage: [2097152]u8 = [] arena := mem.arena_from_buffer(storage[..])
  // Live argument bytes allocated before capture must survive setup and growth.
  command := copy(&arena, PYTHON)
  script := copy(&arena, SCRIPT)
  argv: [3][]const u8 = [command, script, "large"]
  result := process.capture(&arena, command, argv[..], process.Options{}, process.CaptureOptions{})
  if !result.ok || #len(result.output) != 131072 || #len(result.errors) != 131072 { #panic("large lengths") }
  for i in 0..131072 {
    if result.output[i] != #cast(u8, i / 1024) || result.errors[i] != #cast(u8, 255 - i / 1024) { #panic("growth prefix") }
  }
  _ = copy(&arena, "later allocation")
  if result.output[0] != 0 || result.errors[131071] != 128 || !bytes.equal(command, PYTHON) { #panic("lifetime") }
  argv[2] = "exit"
  exited := process.capture(&arena, command, argv[..], process.Options{}, process.CaptureOptions{timeout_milliseconds: -9})
  if !exited.ok || exited.exit.code != 7 || !bytes.equal(exited.output, "ok") { #panic("nonzero exit") }
  argv[2] = "limit"
  limited := process.capture(&arena, command, argv[..], process.Options{}, process.CaptureOptions{output_limit: 4097, error_limit: 2049, timeout_milliseconds: 2000})
  if limited.ok || !limited.limit_reached || limited.timed_out || #len(limited.output) > 4097 || #len(limited.errors) > 2049 { #panic("explicit limits") }
  if #len(limited.output) != 4097 && #len(limited.errors) != 2049 { #panic("limit prefix") }
  argv[2] = "out"
  out_limit := process.capture(&arena, command, argv[..], process.Options{}, process.CaptureOptions{output_limit: 4097})
  if !out_limit.limit_reached || #len(out_limit.output) != 4097 || #len(out_limit.errors) != 0 { #panic("stdout limit") }
  argv[2] = "err"
  err_limit := process.capture(&arena, command, argv[..], process.Options{}, process.CaptureOptions{error_limit: 2049})
  if !err_limit.limit_reached || #len(err_limit.errors) != 2049 || #len(err_limit.output) != 0 { #panic("stderr limit") }
  argv[2] = "empty"
  empty := process.capture(&arena, command, argv[..], process.Options{}, process.CaptureOptions{})
  if !empty.ok || #len(empty.output) != 0 || #len(empty.errors) != 0 { #panic("empty zero policy") }
  argv[2] = "sleep"
  timed := process.capture(&arena, command, argv[..], process.Options{}, process.CaptureOptions{timeout_milliseconds: 200})
  if timed.ok || !timed.timed_out || !bytes.equal(timed.output, "prefix") || !bytes.equal(timed.errors, "error") { #panic("timeout partial") }
  mark := mem.arena_mark(&arena)
  invalid := process.capture(&arena, "", argv[..], process.Options{}, process.CaptureOptions{})
  if invalid.kind != errors.Kind.InvalidInput || #len(invalid.output) != 0 || #len(invalid.errors) != 0 || mem.arena_mark(&arena) != mark { #panic("invalid rollback") }
  rejected := process.capture(&arena, arena.data[mark..mark+1], argv[..], process.Options{}, process.CaptureOptions{})
  if rejected.kind != errors.Kind.InvalidInput || mem.arena_mark(&arena) != mark { #panic("input overlap") }
  alignment := #alignof([]const u8)
  slot_start := (mark + alignment - 1) & ~(alignment - 1)
  slots := (#cast(*[]const u8, &arena.data[slot_start]))[..1]
  slots[0] = command
  descriptors := process.capture(&arena, command, slots, process.Options{}, process.CaptureOptions{})
  if descriptors.kind != errors.Kind.InvalidInput || mem.arena_mark(&arena) != mark { #panic("descriptor overlap") }
  missing := process.capture(&arena, "/no/such/dyn-capture-program", argv[..], process.Options{}, process.CaptureOptions{})
  if missing.ok || #len(missing.output) != 0 || mem.arena_mark(&arena) != mark { #panic("spawn rollback") }
}'''
    source = source.replace('PYTHON', json.dumps(sys.executable)).replace('SCRIPT', json.dumps(str(child)))
    project = root / 'parent'; project.mkdir()
    (project / 'main.dyn').write_text(source)
    for mode in ('debug', 'release'):
        program = root / ('capture-' + mode)
        subprocess.run([str(DYN), 'build', str(project), '--'+mode, '--output', str(program), '--jobs', '1'], check=True, timeout=60)
        result = subprocess.run([str(program)], capture_output=True, timeout=10)
        assert result.returncode == 0, (mode, result.stdout, result.stderr)
        pidfile = root / ('pid-' + mode)
        (project / 'main.dyn').write_text('''use "std/process"\nuse "std/mem"
fn main() { storage: [16384]u8 = [] arena := mem.arena_from_buffer(storage[..])
argv: [4][]const u8 = [PYTHON, SCRIPT, "exhaust", PID]
_ = process.capture(&arena, PYTHON, argv[..], process.Options{}, process.CaptureOptions{})
}'''.replace('PYTHON', json.dumps(sys.executable)).replace('SCRIPT', json.dumps(str(child))).replace('PID', json.dumps(str(pidfile))))
        panic_program = root / ('panic-' + mode)
        subprocess.run([str(DYN), 'build', str(project), '--'+mode, '--output', str(panic_program), '--jobs', '1'], check=True, timeout=60)
        panic = subprocess.run([str(panic_program)], capture_output=True, timeout=10)
        assert panic.returncode != 0 and b'arena exhausted' in panic.stderr, panic
        assert pidfile.exists(), 'exhaustion must occur after spawn'
        pid = int(pidfile.read_text())
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            # Avoid leaving a child behind even when this assertion fails.
            os.kill(pid, 9)
            raise AssertionError(('unreaped capture child', pid))
        (project / 'main.dyn').write_text(source)
print('PASS arena capture growth, policies, rollback, lifetime and panic reaping (debug/release)')
