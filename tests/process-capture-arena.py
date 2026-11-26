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
use "std/io"
// The capture, or why it failed.
struct Capture { result: process.Captured, failed: bool, error: io.IoErr }
fn run_capture(arena: *mem.Arena, path: []const u8, arguments: [][]const u8, options: process.Options, policy: process.CaptureOptions) Capture {
  result := process.capture(arena, path, arguments, options, policy) catch err { return Capture{ failed: true, error: err } }
  return Capture{ result: result }
}
fn invalid_input(capture: Capture) bool {
  if !capture.failed { return false }
  case capture.error {
    .InvalidInput => { return true }
    _ => { return false }
  }
}
fn copy(arena: *mem.Arena, source: []const u8) []u8 {
  destination := mem.push_bytes(arena, source.len)
  _ = mem.move(destination, source)
  return destination
}
fn main() {
  storage: [2097152]u8
  arena := mem.arena_from_buffer(storage[..])
  // Live argument bytes allocated before capture must survive setup and growth.
  command := copy(arena, PYTHON)
  script := copy(arena, SCRIPT)
  argv: [3][]const u8 = [command, script, "large"]
  result_status := run_capture(arena, command, argv[..], process.Options{}, process.CaptureOptions{})
  result := result_status.result
  if result_status.failed || result.output.len != 131072 || result.errors.len != 131072 { #panic("large lengths") }
  for i in 0..131072 {
    if result.output[i] != #cast(u8, i / 1024) || result.errors[i] != #cast(u8, 255 - i / 1024) { #panic("growth prefix") }
  }
  _ = copy(arena, "later allocation")
  if result.output[0] != 0 || result.errors[131071] != 128 || !bytes.equal(command, PYTHON) { #panic("lifetime") }
  argv[2] = "exit"
  exited_status := run_capture(arena, command, argv[..], process.Options{}, process.CaptureOptions{timeout_milliseconds: -9})
  exited := exited_status.result
  if exited_status.failed || exited.exit.code != 7 || !bytes.equal(exited.output, "ok") { #panic("nonzero exit") }
  argv[2] = "limit"
  limited_status := run_capture(arena, command, argv[..], process.Options{}, process.CaptureOptions{output_limit: 4097, error_limit: 2049, timeout_milliseconds: 2000})
  limited := limited_status.result
  if limited_status.failed || !limited.limit_reached || limited.timed_out || limited.output.len > 4097 || limited.errors.len > 2049 { #panic("explicit limits") }
  if limited.output.len != 4097 && limited.errors.len != 2049 { #panic("limit prefix") }
  argv[2] = "out"
  out_limit_status := run_capture(arena, command, argv[..], process.Options{}, process.CaptureOptions{output_limit: 4097})
  out_limit := out_limit_status.result
  if !out_limit.limit_reached || out_limit.output.len != 4097 || out_limit.errors.len != 0 { #panic("stdout limit") }
  argv[2] = "err"
  err_limit_status := run_capture(arena, command, argv[..], process.Options{}, process.CaptureOptions{error_limit: 2049})
  err_limit := err_limit_status.result
  if !err_limit.limit_reached || err_limit.errors.len != 2049 || err_limit.output.len != 0 { #panic("stderr limit") }
  argv[2] = "empty"
  empty_status := run_capture(arena, command, argv[..], process.Options{}, process.CaptureOptions{})
  empty := empty_status.result
  if empty_status.failed || empty.output.len != 0 || empty.errors.len != 0 { #panic("empty zero policy") }
  argv[2] = "sleep"
  timed_status := run_capture(arena, command, argv[..], process.Options{}, process.CaptureOptions{timeout_milliseconds: 200})
  timed := timed_status.result
  if timed_status.failed || !timed.timed_out || !bytes.equal(timed.output, "prefix") || !bytes.equal(timed.errors, "error") { #panic("timeout partial") }
  mark := mem.arena_mark(arena)
  invalid_status := run_capture(arena, "", argv[..], process.Options{}, process.CaptureOptions{})
  invalid := invalid_status.result
  if !invalid_input(invalid_status) || invalid.output.len != 0 || invalid.errors.len != 0 || mem.arena_mark(arena) != mark { #panic("invalid rollback") }
  rejected_status := run_capture(arena, arena.data[mark..mark+1], argv[..], process.Options{}, process.CaptureOptions{})
  rejected := rejected_status.result
  if !invalid_input(rejected_status) || mem.arena_mark(arena) != mark { #panic("input overlap") }
  alignment := #alignof([]const u8)
  slot_start := (mark + alignment - 1) & ~(alignment - 1)
  slots := #slice(#cast(*[]const u8, &arena.data[slot_start]), 1)
  slots[0] = command
  descriptors_status := run_capture(arena, command, slots, process.Options{}, process.CaptureOptions{})
  descriptors := descriptors_status.result
  if !invalid_input(descriptors_status) || mem.arena_mark(arena) != mark { #panic("descriptor overlap") }
  missing_status := run_capture(arena, "/no/such/dyn-capture-program", argv[..], process.Options{}, process.CaptureOptions{})
  missing := missing_status.result
  if !missing_status.failed || missing.output.len != 0 || mem.arena_mark(arena) != mark { #panic("spawn rollback") }
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
        (project / 'main.dyn').write_text('''use "std/process"
use "std/mem"
fn main() { storage: [16384]u8
arena := mem.arena_from_buffer(storage[..])
argv: [4][]const u8 = [PYTHON, SCRIPT, "exhaust", PID]
_ = process.capture(arena, PYTHON, argv[..], process.Options{}, process.CaptureOptions{}) catch { return }
}'''.replace('PYTHON', json.dumps(sys.executable)).replace('SCRIPT', json.dumps(str(child))).replace('PID', json.dumps(str(pidfile))))
        panic_program = root / ('panic-' + mode)
        subprocess.run([str(DYN), 'build', str(project), '--'+mode, '--output', str(panic_program), '--jobs', '1'], check=True, timeout=60)
        panic = subprocess.run([str(panic_program)], capture_output=True, timeout=10)
        assert panic.returncode != 0 and b'arena exhausted' in panic.stderr, panic
        assert pidfile.exists(), 'exhaustion must occur after spawn'
        pid = int(pidfile.read_text())
        # A panic ends the parent without running defers, so the child is not
        # reaped by capture; the operating system reparents it. Stop it here.
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
        (project / 'main.dyn').write_text(source)
print('PASS arena capture growth, policies, rollback, lifetime and panic exit (debug/release)')
