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
use "std/fail"
fn copy(arena: *mem.Arena, source: []const u8) []u8 {
  destination := mem.push_bytes_uninit(arena, #len(source))
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
  result_status: fail.Status
  result := process.capture(arena, &result_status, command, argv[..], process.Options{}, process.CaptureOptions{})
  if result_status.failed || #len(result.output) != 131072 || #len(result.errors) != 131072 { #panic("large lengths") }
  for i in 0..131072 {
    if result.output[i] != #cast(u8, i / 1024) || result.errors[i] != #cast(u8, 255 - i / 1024) { #panic("growth prefix") }
  }
  _ = copy(arena, "later allocation")
  if result.output[0] != 0 || result.errors[131071] != 128 || !bytes.equal(command, PYTHON) { #panic("lifetime") }
  argv[2] = "exit"
  exited_status: fail.Status
  exited := process.capture(arena, &exited_status, command, argv[..], process.Options{}, process.CaptureOptions{timeout_milliseconds: -9})
  if exited_status.failed || exited.exit.code != 7 || !bytes.equal(exited.output, "ok") { #panic("nonzero exit") }
  argv[2] = "limit"
  limited_status: fail.Status
  limited := process.capture(arena, &limited_status, command, argv[..], process.Options{}, process.CaptureOptions{output_limit: 4097, error_limit: 2049, timeout_milliseconds: 2000})
  if !limited_status.failed || !limited.limit_reached || limited.timed_out || #len(limited.output) > 4097 || #len(limited.errors) > 2049 { #panic("explicit limits") }
  if #len(limited.output) != 4097 && #len(limited.errors) != 2049 { #panic("limit prefix") }
  argv[2] = "out"
  out_limit_status: fail.Status
  out_limit := process.capture(arena, &out_limit_status, command, argv[..], process.Options{}, process.CaptureOptions{output_limit: 4097})
  if !out_limit.limit_reached || #len(out_limit.output) != 4097 || #len(out_limit.errors) != 0 { #panic("stdout limit") }
  argv[2] = "err"
  err_limit_status: fail.Status
  err_limit := process.capture(arena, &err_limit_status, command, argv[..], process.Options{}, process.CaptureOptions{error_limit: 2049})
  if !err_limit.limit_reached || #len(err_limit.errors) != 2049 || #len(err_limit.output) != 0 { #panic("stderr limit") }
  argv[2] = "empty"
  empty_status: fail.Status
  empty := process.capture(arena, &empty_status, command, argv[..], process.Options{}, process.CaptureOptions{})
  if empty_status.failed || #len(empty.output) != 0 || #len(empty.errors) != 0 { #panic("empty zero policy") }
  argv[2] = "sleep"
  timed_status: fail.Status
  timed := process.capture(arena, &timed_status, command, argv[..], process.Options{}, process.CaptureOptions{timeout_milliseconds: 200})
  if !timed_status.failed || !timed.timed_out || !bytes.equal(timed.output, "prefix") || !bytes.equal(timed.errors, "error") { #panic("timeout partial") }
  mark := mem.arena_mark(arena)
  invalid_status: fail.Status
  invalid := process.capture(arena, &invalid_status, "", argv[..], process.Options{}, process.CaptureOptions{})
  if invalid_status.failure.kind != fail.Kind.InvalidInput || #len(invalid.output) != 0 || #len(invalid.errors) != 0 || mem.arena_mark(arena) != mark { #panic("invalid rollback") }
  rejected_status: fail.Status
  rejected := process.capture(arena, &rejected_status, arena.data[mark..mark+1], argv[..], process.Options{}, process.CaptureOptions{})
  if rejected_status.failure.kind != fail.Kind.InvalidInput || mem.arena_mark(arena) != mark { #panic("input overlap") }
  alignment := #alignof([]const u8)
  slot_start := (mark + alignment - 1) & ~(alignment - 1)
  slots := #slice(#cast(*[]const u8, &arena.data[slot_start]), 1)
  slots[0] = command
  descriptors_status: fail.Status
  descriptors := process.capture(arena, &descriptors_status, command, slots, process.Options{}, process.CaptureOptions{})
  if descriptors_status.failure.kind != fail.Kind.InvalidInput || mem.arena_mark(arena) != mark { #panic("descriptor overlap") }
  missing_status: fail.Status
  missing := process.capture(arena, &missing_status, "/no/such/dyn-capture-program", argv[..], process.Options{}, process.CaptureOptions{})
  if !missing_status.failed || #len(missing.output) != 0 || mem.arena_mark(arena) != mark { #panic("spawn rollback") }
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
use "std/fail"
use "std/mem"
fn main() { storage: [16384]u8
arena := mem.arena_from_buffer(storage[..])
argv: [4][]const u8 = [PYTHON, SCRIPT, "exhaust", PID]
status: fail.Status
_ = process.capture(arena, &status, PYTHON, argv[..], process.Options{}, process.CaptureOptions{})
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
