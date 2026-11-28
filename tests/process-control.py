#!/usr/bin/env python3
"""std/process controls child programs: Options.group puts a child and its
descendants in one tree that terminate_tree and close kill (a grandchild never
outlives them), open_pipe ends do not block and read_pipe/write_pipe report
WouldBlock (and a reader-less write fails without SIGPIPE), find_executable
searches PATH like `which`, and shell/Windows quoting round-trips through
`sh -c`, the Windows command-line parser and a real spawn. The same programs
type-check for Linux, macOS and Windows on x86-64 and AArch64, and run on the
host (Linux, macOS or Windows)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build' / ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve())
TARGETS = ('x86_64-linux', 'aarch64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows')
WINDOWS = os.name == 'nt'

# helper parent: starts helper leaf (inheriting every stream), prints P, sleeps.
# helper leaf: prints L and sleeps. helper echo ARGS...: writes each argument
# followed by NUL.
HELPER = r'''use process "std/process"
use io "std/io"
use time "std/time"
use bytes "std/bytes"
fn main() {
  program := process.start()
  args := program.args
  if args.len < 2 { #panic("mode") }
  if bytes.equal(args[1], "parent") {
    leaf: [2][]const u8 = [args[0], "leaf"]
    _ = process.spawn(program.arena, args[0], leaf[..], process.Options{}) catch { #panic("leaf") }
    io.print("P")
    time.sleep(30 * time.Second)
  } else if bytes.equal(args[1], "leaf") {
    io.print("L")
    time.sleep(30 * time.Second)
  } else {
    out := io.stdout()
    nul: [1]u8 = [0]
    for at in 2..args.len {
      io.write(out, args[at]) catch { #panic("echo") }
      io.write(out, nul[..]) catch { #panic("echo") }
    }
  }
}
'''

MAIN = r'''use process "std/process"
use io "std/io"
use mem "std/mem"
use time "std/time"
use bytes "std/bytes"
use event "std/event"
const Helper: []const u8 = HELPER_PATH
const Fixture: []const u8 = FIXTURE_PATH
// A variable, not a const: folding these branches away made the compiler
// fail with "failed to lower typed Dyn IR".
Posix: bool = POSIX_HOST

fn check(ok: bool, message: []const u8) {
  if !ok {
    io.println("FAIL {}", message)
    #panic(message)
  }
}
// What a fallible call did: its count, or which kind of failure.
struct Outcome { count: usize, failed: bool, would_block: bool, system: bool, not_found: bool, invalid: bool }
fn failure(err: io.IoErr) Outcome {
  result := Outcome{ failed: true }
  case err {
    .WouldBlock => { result.would_block = true }
    .System(_) => { result.system = true }
    .NotFound => { result.not_found = true }
    .InvalidInput => { result.invalid = true }
    _ => {}
  }
  return result
}
fn read_some(handle: isize, destination: []u8) Outcome {
  count := process.read_pipe(handle, destination) catch err { return failure(err) }
  return Outcome{ count: count }
}
fn write_some(handle: isize, source: []const u8) Outcome {
  count := process.write_pipe(handle, source) catch err { return failure(err) }
  return Outcome{ count: count }
}
fn find_in(arena: *mem.Arena, name: []const u8, list: []const u8) Outcome {
  found := process.find_executable_in(arena, name, list) catch err { return failure(err) }
  return Outcome{ count: found.len }
}
fn tree_kill(child: *process.Child) Outcome {
  process.terminate_tree(child) catch err { return failure(err) }
  return Outcome{}
}
fn line_of(arena: *mem.Arena, arguments: [][]const u8) Outcome {
  line := process.windows_command_line(arena, arguments) catch err { return failure(err) }
  return Outcome{ count: line.len }
}
fn now_ms() i64 {
  return time.elapsed(time.Instant{}, time.monotonic_now()) / time.Millisecond
}
// Reads count bytes from a nonblocking end within ten seconds.
fn read_exactly(handle: isize, destination: []u8) {
  used: usize = 0
  started := now_ms()
  for used < destination.len {
    got := read_some(handle, destination[used..])
    if got.failed {
      check(got.would_block, "read failed")
      check(now_ms() - started < 10000, "no output from the tree")
      time.sleep(time.Millisecond)
      continue
    }
    check(got.count > 0, "tree ended early")
    used += got.count
  }
}
// Whether every writer is gone within milliseconds: true at end of stream.
fn ends_within(handle: isize, milliseconds: i64) bool {
  started := now_ms()
  buffer: [64]u8
  for now_ms() - started < milliseconds {
    got := read_some(handle, buffer[..])
    if !got.failed && got.count == 0 { return true }
    check(!got.failed || got.would_block, "read failed while waiting for the end")
    time.sleep(time.Millisecond)
  }
  return false
}
struct Tree { child: *process.Child, input: isize }
fn tree(arena: *mem.Arena) Tree {
  out := process.open_pipe(process.PipeOptions{ nonblocking_input: true }) catch { #panic("pipe") }
  argv: [2][]const u8 = [Helper, "parent"]
  options := process.Options{ output: process.redirect(out.output), group: true }
  child := process.spawn(arena, Helper, argv[..], options) catch { #panic("spawn tree") }
  process.close_pipe(out.output)
  started: [2]u8
  read_exactly(out.input, started[..])
  check(started[0] != started[1], "parent and leaf both started")
  return Tree{ child: child, input: out.input }
}

fn trees(arena: *mem.Arena) {
  // A plain terminate leaves the grandchild; terminate_tree ends it, after
  // the leader was reaped too.
  first := tree(arena)
  child := first.child
  check(child.group, "group child")
  process.terminate(child) catch { #panic("terminate") }
  exited := process.wait(child, false) catch { #panic("wait") }
  check(exited.finished && !child.active, "leader reaped")
  check(!ends_within(first.input, 300), "grandchild survives a plain terminate")
  process.terminate_tree(child) catch { #panic("terminate_tree") }
  check(ends_within(first.input, 10000), "terminate_tree ends the grandchild")
  process.terminate_tree(child) catch { #panic("terminate_tree on an empty tree") }
  process.close(child)
  check(!child.group && !child.active, "closed")
  process.close_pipe(first.input)
  check(tree_kill(child).invalid, "terminate_tree after close")
  process.close(child)
  // close alone kills the whole tree.
  second := tree(arena)
  process.close(second.child)
  check(ends_within(second.input, 10000), "close ends the tree")
  process.close_pipe(second.input)
  io.println("PASS tree")
}

fn shell_tree(arena: *mem.Arena) {
  out := process.open_pipe(process.PipeOptions{ nonblocking_input: true }) catch { #panic("pipe") }
  argv: [3][]const u8 = ["/bin/sh", "-c", "sleep 30 & echo started; sleep 30"]
  options := process.Options{ output: process.redirect(out.output), group: true }
  child := process.spawn(arena, "/bin/sh", argv[..], options) catch { #panic("spawn sh") }
  process.close_pipe(out.output)
  started: [8]u8
  read_exactly(out.input, started[..])
  check(bytes.equal(started[..], "started\n"), "sh started")
  check(!ends_within(out.input, 200), "sh tree running")
  process.terminate_tree(child) catch { #panic("terminate_tree sh") }
  process.close(child)
  check(ends_within(out.input, 10000), "sh grandchild gone")
  process.close_pipe(out.input)
  io.println("PASS sh tree")
}

// A capture of a group child kills the tree when it stops: the grandchild
// held the input pipe, which has no reader afterwards.
fn capture_tree(arena: *mem.Arena) {
  feed := process.open_pipe(process.PipeOptions{ nonblocking_output: true }) catch { #panic("pipe") }
  argv: [2][]const u8 = [Helper, "parent"]
  options := process.Options{ input: process.redirect(feed.input), group: true }
  result := process.capture(arena, Helper, argv[..], options, process.CaptureOptions{ timeout_milliseconds: 1500 }) catch { #panic("capture") }
  check(result.timed_out, "the grandchild keeps output open")
  process.close_pipe(feed.input)
  started := now_ms()
  for {
    wrote := write_some(feed.output, "x")
    if wrote.system { break }
    check(!wrote.failed || wrote.would_block, "write kind")
    check(now_ms() - started < 10000, "capture left the grandchild running")
    time.sleep(time.Millisecond)
  }
  process.close_pipe(feed.output)
  io.println("PASS capture tree")
}

fn pipes(arena: *mem.Arena) {
  both := process.open_pipe(process.PipeOptions{ nonblocking_input: true, nonblocking_output: true }) catch { #panic("pipe") }
  buffer: [4096]u8
  check(read_some(both.input, buffer[..]).would_block, "empty read is WouldBlock")
  filled: usize = 0
  full := false
  for filled < 67108864 && !full {
    wrote := write_some(both.output, buffer[..])
    if wrote.failed {
      check(wrote.would_block, "full write is WouldBlock")
      full = true
    }
    filled += wrote.count
  }
  check(full && filled > 0, "pipe filled")
  drained: usize = 0
  for drained < filled {
    got := read_some(both.input, buffer[..])
    check(!got.failed && got.count > 0, "drain")
    drained += got.count
  }
  check(drained == filled, "drained all")
  check(read_some(both.input, buffer[..]).would_block, "drained read is WouldBlock")
  if Posix {
    queue := event.open(arena, 4) catch { #panic("queue") }
    event.add(&queue, both.input, event.Readable, 7) catch { #panic("add") }
    quiet := event.wait(arena, &queue, 0) catch { #panic("event wait") }
    check(quiet.len == 0, "empty pipe not readable")
    check(write_some(both.output, "x").count == 1, "write one")
    ready := event.wait(arena, &queue, 5000) catch { #panic("event wait") }
    check(ready.len == 1 && ready[0].token == 7 && (ready[0].events & event.Readable) != 0, "readable event")
    got := read_some(both.input, buffer[..])
    check(got.count == 1 && buffer[0] == 120, "read the byte")
    event.remove(&queue, both.input) catch { #panic("remove") }
    event.close(&queue)
  }
  process.close_pipe(both.input)
  // No reader: a failure, and no SIGPIPE kills this program.
  check(write_some(both.output, "x").system, "write without a reader")
  check(!write_some(both.output, "").failed, "empty write")
  process.close_pipe(both.output)
  io.println("PASS pipes")
}

fn search(arena: *mem.Arena) {
  if Posix {
    search_posix(arena)
  } else {
    search_windows(arena)
  }
  check(find_in(arena, "", "").invalid, "empty name")
  io.println("PASS search")
}
fn search_posix(arena: *mem.Arena) {
  mark := mem.arena_mark(arena)
  shell := process.find_executable(arena, "sh") catch { #panic("sh on PATH") }
  check(bytes.ends_with(shell, "/sh"), "sh path")
  check(mem.arena_mark(arena) == mark + shell.len, "only the result stays")
  entries := mem.push_bytes(arena, Fixture.len * 2 + 4)
  used := mem.copy(entries, "::")
  used += mem.copy(entries[used..], Fixture)
  entries[used] = 58
  used += 1
  list := entries[..used]
  tool := process.find_executable_in(arena, "tool", list) catch { #panic("tool") }
  check(bytes.ends_with(tool, "/tool") && bytes.starts_with(tool, Fixture), "tool path")
  check(find_in(arena, "plain", list).not_found, "a file without execute bits")
  check(find_in(arena, "folder", list).not_found, "a directory")
  check(find_in(arena, "tool", "").not_found, "an empty search")
  direct := process.find_executable_in(arena, tool, "") catch { #panic("direct") }
  check(bytes.equal(direct, tool), "a path is itself")
  plain := mem.push_bytes(arena, Fixture.len + 6)
  _ = mem.copy(plain, Fixture)
  _ = mem.copy(plain[Fixture.len..], "/plain")
  check(find_in(arena, plain, list).not_found, "a path without execute bits")
}
fn search_windows(arena: *mem.Arena) {
  shell := process.find_executable(arena, "cmd") catch { #panic("cmd on PATH") }
  lowered := mem.push_bytes(arena, shell.len)
  for at in 0..shell.len {
    byte := shell[at]
    if byte >= 65 && byte <= 90 {
      byte += 32
    }
    lowered[at] = byte
  }
  check(bytes.ends_with(lowered, "\\cmd.exe"), "cmd path")
  entries := mem.push_bytes(arena, Fixture.len * 2 + 8)
  used := mem.copy(entries, ";;\"")
  used += mem.copy(entries[used..], Fixture)
  used += mem.copy(entries[used..], "\";")
  list := entries[..used]
  tool := process.find_executable_in(arena, "tool", list) catch { #panic("tool") }
  check(bytes.starts_with(tool, Fixture) && tool.len == Fixture.len + 9, "tool path")
  check(find_in(arena, "tool.exe", list).count == Fixture.len + 9, "tool.exe path")
  check(find_in(arena, "plain", list).not_found, "no extension")
  check(find_in(arena, "notes.txt", list).not_found, "an extension not in PATHEXT")
  check(find_in(arena, "folder", list).not_found, "a directory")
}

fn quoting(arena: *mem.Arena) {
  tricky: [11][]const u8 = ["", "plain", "two words", "it's", "say \"hi\"", "back\\slash", "trail\\", "\\\\\"", "$HOME *", "tab\there", "line\nbreak"]
  argv: [12][]const u8
  argv[0] = "C:\\Program Files\\tool.exe"
  for at in 0..tricky.len {
    argv[at + 1] = tricky[at]
  }
  line := process.windows_command_line(arena, argv[..]) catch { #panic("command line") }
  parsed := process.windows_arguments(arena, line) catch { #panic("parse") }
  check(parsed.len == argv.len, "argument count")
  for at in 0..argv.len {
    check(bytes.equal(parsed[at], argv[at]), "windows round trip")
  }
  one := process.windows_quote(arena, "a\\\"b\\")
  check(bytes.equal(one, "\"a\\\\\\\"b\\\\\""), "windows_quote")
  known := process.windows_arguments(arena, "  prog\\x.exe  a\\\\\\\"b \"c d\"\"e\" \\\\\\\\\"f g\" ") catch { #panic("known") }
  check(known.len == 4, "known count")
  check(bytes.equal(known[0], "prog\\x.exe"), "argv0 keeps backslashes")
  check(bytes.equal(known[1], "a\\\"b"), "escaped quote")
  check(bytes.equal(known[2], "c d\"e"), "doubled quote")
  check(bytes.equal(known[3], "\\\\f g"), "even backslashes")
  bad: [1][]const u8 = ["a\"b"]
  check(line_of(arena, bad[..]).invalid, "argv0 with a quote")
  if Posix {
    quoted := process.shell_command(arena, tricky[..])
    check(bytes.equal(process.shell_quote(arena, "it's"), "'it'\\''s'"), "shell_quote")
    script := mem.push_bytes(arena, quoted.len + 32)
    used := mem.copy(script, "printf '<%s>' ")
    used += mem.copy(script[used..], quoted)
    shell: [3][]const u8 = ["/bin/sh", "-c", script[..used]]
    result := process.capture(arena, "/bin/sh", shell[..], process.Options{}, process.CaptureOptions{ timeout_milliseconds: 10000 }) catch { #panic("sh capture") }
    at: usize = 0
    for word in tricky {
      check(at < result.output.len && result.output[at] == 60, "open")
      check(bytes.equal(result.output[at + 1..at + 1 + word.len], word), "sh round trip")
      at += word.len + 1
      check(result.output[at] == 62, "close")
      at += 1
    }
    check(at == result.output.len, "sh output length")
  }
  // A real spawn passes every argument through unchanged.
  echo: [13][]const u8
  echo[0] = Helper
  echo[1] = "echo"
  for index in 0..tricky.len {
    echo[index + 2] = tricky[index]
  }
  echoed := process.capture(arena, Helper, echo[..], process.Options{}, process.CaptureOptions{ timeout_milliseconds: 10000 }) catch { #panic("echo capture") }
  offset: usize = 0
  for expected in tricky {
    check(offset + expected.len < echoed.output.len, "echo length")
    check(bytes.equal(echoed.output[offset..offset + expected.len], expected), "spawn round trip")
    check(echoed.output[offset + expected.len] == 0, "echo separator")
    offset += expected.len + 1
  }
  check(offset == echoed.output.len, "echo total")
  io.println("PASS quoting")
}

fn main() {
  arena := mem.arena_alloc(0)
  quoting(arena)
  search(arena)
  pipes(arena)
  trees(arena)
  if Posix {
    shell_tree(arena)
  }
  capture_tree(arena)
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-process-control-') as directory:
    root = Path(directory)
    fixture = root / 'fixture'
    fixture.mkdir()
    (fixture / 'folder').mkdir()
    if WINDOWS:
        (fixture / 'tool.exe').write_bytes(b'MZ')
        (fixture / 'plain').write_text('x')
        (fixture / 'notes.txt').write_text('x')
    else:
        (fixture / 'tool').write_text('#!/bin/sh\n')
        (fixture / 'tool').chmod(0o755)
        (fixture / 'plain').write_text('x')
        (fixture / 'plain').chmod(0o644)
        (fixture / 'folder').chmod(0o755)
    helper_source = root / 'helper'
    helper_source.mkdir()
    (helper_source / 'main.dyn').write_text(HELPER)
    helper = root / ('helper.exe' if WINDOWS else 'helper-bin')
    main_source = root / 'main'
    main_source.mkdir()
    (main_source / 'main.dyn').write_text(
        MAIN.replace('HELPER_PATH', json.dumps(str(helper), ensure_ascii=False))
            .replace('FIXTURE_PATH', json.dumps(str(fixture), ensure_ascii=False))
            .replace('POSIX_HOST', 'false' if WINDOWS else 'true'), encoding='utf-8')
    for source in (helper_source, main_source):
        for target in TARGETS:
            checked = subprocess.run([DYN, 'check', str(source), '--quiet', '--target', target], capture_output=True, text=True)
            assert checked.returncode == 0, (source.name, target, checked.stdout, checked.stderr)
    built = subprocess.run([DYN, 'build', str(helper_source), '--quiet', '--output', str(helper)], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    for mode in ('--debug', '--release'):
        program = root / ('main.exe' if WINDOWS else 'main-bin')
        built = subprocess.run([DYN, 'build', str(main_source), mode, '--quiet', '--output', str(program)], capture_output=True, text=True)
        assert built.returncode == 0, (mode, built.stderr)
        result = subprocess.run([str(program)], cwd=root, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr)
        expected = ['PASS quoting', 'PASS search', 'PASS pipes', 'PASS tree'] + ([] if WINDOWS else ['PASS sh tree']) + ['PASS capture tree']
        assert result.stdout.splitlines() == expected, (mode, result.stdout, result.stderr)
print('PASS process control: group trees end with terminate_tree/close/capture, nonblocking pipes, PATH search, quoting round trips; six targets check')
