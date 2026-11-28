#!/usr/bin/env python3
"""std/process/pty runs a child on a pseudo-terminal: it reads the child's
output, types into it, resizes the window, collects the exit status, and
close leaves no descriptor or unreaped child. The same program type-checks
for Linux, macOS and Windows on x86-64 and AArch64, and runs on the host:
on Linux and macOS through /bin/sh and stty, everywhere through a Dyn child
that reports its arguments, environment, directory and window size."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build' / ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve())
TARGETS = ('x86_64-linux', 'aarch64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows')

# The child: prints what it was given and its window, prints the window again
# for each "size" line it reads, then echoes the first other line and exits 7.
# With "hang" it waits on its input forever instead.
CHILD = r'''use io "std/io"
use bytes "std/bytes"
use fs "std/fs"
use mem "std/mem"
use process "std/process"
use terminal "std/terminal"
fn line(buffer: []u8) []u8 {
  used: usize = 0
  for used < buffer.len {
    count := io.read(io.stdin(), buffer[used..used + 1]) catch { return buffer[..used] }
    if count == 0 { break }
    if buffer[used] == '\n' { break }
    if buffer[used] != '\r' {
      used += 1
    }
  }
  return buffer[..used]
}
fn show_size() {
  size := terminal.size(1) catch { #panic("size") }
  io.println("size:{}x{}", size.rows, size.columns)
}
fn main() i32 {
  arena := mem.arena_alloc(0)
  arguments := process.arguments(arena) catch { #panic("arguments") }
  value := process.environment_or(arena, "PTY_VALUE", "unset")
  marker := fs.read_all(arena, "marker", 64) catch { #panic("marker") }
  buffer: [256]u8
  if arguments.len > 1 && bytes.equal(arguments[1], "hang") {
    io.println("hanging")
    for {
      _ = line(buffer[..])
    }
  }
  io.println("ready:{}:{}:{}", arguments[1], value, marker)
  show_size()
  for {
    got := line(buffer[..])
    if !bytes.equal(got, "size") {
      io.println("got:{}", got)
      return 7
    }
    show_size()
  }
}
'''

PROGRAM = r'''use pty "std/process/pty"
use process "std/process"
use event "std/event"
use mem "std/mem"
use io "std/io"
use bytes "std/bytes"

// What the child printed, with terminal escape sequences removed: Windows
// pseudoconsoles redraw text with cursor and mode sequences between runs.
struct Output { storage: [8192]u8, used: usize, raw: [1024]u8, state: u8 }

// Reads once into output; the byte count read, 0 at the end.
fn take(terminal: *pty.Terminal, output: *Output) usize!io.IoErr {
  count := try pty.read(terminal, output.raw[..])
  if output.used > 6144 {
    _ = mem.copy(output.storage[..1024], output.storage[output.used - 1024..output.used])
    output.used = 1024
  }
  for byte in output.raw[..count] {
    if output.state == 0 {
      if byte == 27 {
        output.state = 1
      } else if byte != '\r' {
        output.storage[output.used] = byte
        output.used += 1
      }
    } else if output.state == 1 {
      if byte == '[' {
        output.state = 2
      } else if byte == ']' {
        output.state = 3
      } else {
        output.state = 0
      }
    } else if output.state == 2 {
      if byte >= 64 && byte <= 126 {
        output.state = 0
      }
    } else if output.state == 3 {
      if byte == 7 {
        output.state = 0
      } else if byte == 27 {
        output.state = 4
      }
    } else {
      output.state = 0
    }
  }
  return count
}

fn invalid(err: io.IoErr) bool {
  case err {
    .InvalidInput => { return true }
    _ => { return false }
  }
}

// Reads into output until it holds needle, waiting with pty.readable.
fn expect(terminal: *pty.Terminal, output: *Output, needle: []const u8) {
  if !arrives(terminal, output, needle, 400) {
    io.println("output so far: {}", output.storage[..output.used])
    #panic("expected output did not arrive")
  }
}

// Whether output comes to hold needle within rounds waits of 50 ms.
fn arrives(terminal: *pty.Terminal, output: *Output, needle: []const u8, rounds: usize) bool {
  for round in 0..rounds {
    if bytes.contains(output.storage[..output.used], needle) { return true }
    ready := pty.readable(terminal, 50) catch { #panic("readable") }
    if ready {
      count := take(terminal, output) catch err {
        case err {
          .WouldBlock => { continue }
          _ => { #panic("read") }
        }
      }
      if count == 0 { break }
    }
  }
  return bytes.contains(output.storage[..output.used], needle)
}

// Reads into output until it holds needle, waiting on a std/event queue.
fn expect_evented(scratch: *mem.Arena, queue: *event.Queue, terminal: *pty.Terminal, output: *Output, needle: []const u8) {
  for round in 0..400 {
    if bytes.contains(output.storage[..output.used], needle) { return }
    mark := mem.arena_mark(scratch)
    events := event.wait(scratch, queue, 50) catch { #panic("event wait") }
    mem.arena_rewind(scratch, mark)
    if events.len == 0 { continue }
    count := take(terminal, output) catch err {
      case err {
        .WouldBlock => { continue }
        _ => { #panic("evented read") }
      }
    }
    if count == 0 { break }
  }
  if !bytes.contains(output.storage[..output.used], needle) {
    io.println("output so far: {}", output.storage[..output.used])
    #panic("expected output did not arrive")
  }
}

fn type_line(terminal: *pty.Terminal, text: []const u8) {
  sent: usize = 0
  for sent < text.len {
    count := pty.write(terminal, text[sent..]) catch err {
      case err {
        .WouldBlock => { continue }
        _ => { #panic("write") }
      }
    }
    sent += count
  }
}

// Drains what is left so the child never blocks on a full terminal.
fn drain(terminal: *pty.Terminal, output: *Output) {
  for round in 0..100 {
    ready := pty.readable(terminal, 20) catch { return }
    if !ready { return }
    count := take(terminal, output) catch { return }
    if count == 0 { return }
  }
}

// Prints why a call failed, so CI logs show the system's own reason.
fn explain(what: []const u8, err: io.IoErr) {
  code: isize = 0
  case err {
    .System(value) => { code = value }
    _ => {}
  }
  io.println("{} failed: {} (code {})", what, io.text(err), code)
}

// /bin/sh on a terminal, as Linux and macOS run it, read through std/event.
fn shell(arena: *mem.Arena, directory: []const u8) {
  script: []const u8 = "exec 3</dev/tty && printf ctty:; printf ready:%s:%s: \"$PTY_VALUE\" \"$(cat marker)\"; stty size; read a; stty size; read x; echo got:$x; exit 7"
  arguments: [3][]const u8 = ["sh", "-c", script]
  environment: [2][]const u8 = ["PATH=/usr/bin:/bin", "PTY_VALUE=shell"]
  options := pty.Options{ environment: environment[..], directory: directory, size: pty.Size{ columns: 80, rows: 24 } }
  terminal := pty.spawn(arena, "/bin/sh", arguments[..], options) catch err {
    explain("spawn shell", err)
    #panic("spawn shell")
  }
  defer pty.close(terminal)
  queue := event.open(arena, 4) catch { #panic("event open") }
  defer event.close(&queue)
  event.add(&queue, terminal.terminal, event.Readable, 1) catch { #panic("event add") }
  scratch := mem.arena_alloc(0)
  defer mem.arena_release(scratch)
  output: Output
  expect_evented(scratch, &queue, terminal, &output, "ctty:ready:shell:parent-marker:")
  expect_evented(scratch, &queue, terminal, &output, "24 80")
  pty.resize(terminal, pty.Size{ columns: 100, rows: 40, width: 800, height: 600 }) catch { #panic("resize") }
  type_line(terminal, "\n")
  expect_evented(scratch, &queue, terminal, &output, "40 100")
  type_line(terminal, "hello\n")
  expect_evented(scratch, &queue, terminal, &output, "got:hello")
  event.remove(&queue, terminal.terminal) catch { #panic("event remove") }
  drain(terminal, &output)
  exit := pty.wait(terminal, false) catch { #panic("wait shell") }
  if !exit.finished || exit.code != 7 || exit.signal != 0 { #panic("shell exit status") }
  // Every holder closed the terminal: it reads as ended.
  ended: [64]u8
  for round in 0..200 {
    count := pty.read(terminal, ended[..]) catch err {
      case err {
        .WouldBlock => {
          _ = pty.readable(terminal, 10) catch { #panic("readable after exit") }
          continue
        }
        _ => { #panic("read after exit") }
      }
    }
    if count == 0 { return }
  }
  #panic("terminal never ended")
}

// The Dyn child, on every platform.
fn child(arena: *mem.Arena, executable: []const u8, directory: []const u8) {
  arguments: [2][]const u8 = [executable, "first-argument"]
  environment: [2][]const u8 = ["PTY_VALUE=dyn", "SystemRoot=C:\\Windows"]
  options := pty.Options{ environment: environment[..], directory: directory, size: pty.Size{ columns: 90, rows: 30 } }
  terminal := pty.spawn(arena, executable, arguments[..], options) catch { #panic("spawn child") }
  defer pty.close(terminal)
  output: Output
  expect(terminal, &output, "ready:first-argument:dyn:child-marker")
  expect(terminal, &output, "size:30x90")
  pty.resize(terminal, pty.Size{ columns: 120, rows: 50 }) catch { #panic("child resize") }
  // A pseudoconsole applies a resize asynchronously: ask until it shows.
  resized: bool = false
  for attempt in 0..20 {
    if !resized {
      type_line(terminal, "size\r")
      resized = arrives(terminal, &output, "size:50x120", 10)
    }
  }
  if !resized {
    io.println("output so far: {}", output.storage[..output.used])
    #panic("resize never reached the child")
  }
  type_line(terminal, "hello\r")
  expect(terminal, &output, "got:hello")
  for round in 0..400 {
    drain(terminal, &output)
    exit := pty.wait(terminal, true) catch { #panic("wait child") }
    if exit.finished {
      if exit.code != 7 { #panic("child exit status") }
      _ = pty.wait(terminal, false) catch err {
        if !invalid(err) { #panic("second wait") }
        return
      }
      #panic("waited twice")
    }
  }
  #panic("child never exited")
}

// close on a running child kills and reaps it.
fn abandon(arena: *mem.Arena, executable: []const u8, directory: []const u8) {
  arguments: [2][]const u8 = [executable, "hang"]
  options := pty.Options{ directory: directory }
  terminal := pty.spawn(arena, executable, arguments[..], options) catch { #panic("spawn hang") }
  output: Output
  expect(terminal, &output, "hanging")
  running := pty.wait(terminal, true) catch { #panic("wait hang") }
  if running.finished { #panic("hang ended early") }
  pty.close(terminal)
  pty.close(terminal)
  buffer: [8]u8
  _ = pty.read(terminal, buffer[..]) catch err {
    if !invalid(err) { #panic("read after close") }
    _ = pty.resize(terminal, pty.Size{ columns: 1, rows: 1 }) catch resize_err {
      if !invalid(resize_err) { #panic("resize after close") }
      return
    }
    #panic("resize after close")
  }
  #panic("read after close")
}

fn rejects(arena: *mem.Arena, executable: []const u8) {
  arguments: [1][]const u8 = [executable]
  none: [0][]const u8
  _ = pty.spawn(arena, executable, none[..], pty.Options{}) catch err {
    if !invalid(err) { #panic("empty argv") }
    bad: [1][]const u8 = ["NOEQUALS"]
    _ = pty.spawn(arena, executable, arguments[..], pty.Options{ environment: bad[..] }) catch environment_err {
      if !invalid(environment_err) { #panic("environment entry") }
      missing: [1][]const u8 = ["missing"]
      _ = pty.spawn(arena, "/nonexistent/program", missing[..], pty.Options{}) catch {
        _ = pty.spawn(arena, executable, arguments[..], pty.Options{ directory: "/nonexistent/directory" }) catch { return }
        #panic("missing directory accepted")
      }
      #panic("missing program accepted")
    }
    #panic("environment entry accepted")
  }
  #panic("empty argv accepted")
}

fn main() {
  arena := mem.arena_alloc(0)
  before := open_descriptors(arena)
  if SHELL {
    shell(arena, PARENT)
  }
  child(arena, CHILD_PATH, CHILD_DIRECTORY)
  abandon(arena, CHILD_PATH, CHILD_DIRECTORY)
  rejects(arena, CHILD_PATH)
  after := open_descriptors(arena)
  if before != after {
    io.println("descriptors before {} after {}", before, after)
    #panic("descriptor leak")
  }
  if !no_children() { #panic("unreaped child") }
  io.println("PASS")
}
'''

# How many descriptors are open, and whether any child is left unreaped.
UNIX = r'''#target(family: unix)
use mem "std/mem"
use fs "std/fs"
fn open_descriptors(arena: *mem.Arena) usize {
  mark := mem.arena_mark(arena)
  defer mem.arena_rewind(arena, mark)
  entries := fs.list(arena, DESCRIPTOR_DIRECTORY) catch { #panic("list descriptors") }
  return entries.len
}
'''
LINUX = r'''#target(kernel: linux)
use "std/os/linux/sys"
const DESCRIPTOR_DIRECTORY: []const u8 = "/proc/self/fd"
// wait4(-1, WNOHANG) fails with ECHILD once every child is reaped.
fn no_children() bool {
  status: i32 = 0
  return #syscall(sys.Wait4, -1, &status, 1, 0) == -10
}
'''
MACOS = r'''#target(kernel: darwin)
const DESCRIPTOR_DIRECTORY: []const u8 = "/dev/fd"
fn no_children() bool {
  status: i32 = 0
  return #syscall(7, -1, &status, 1, 0) == -10
}
'''
WINDOWS = r'''#target(kernel: windows)
use mem "std/mem"
// Windows has no zombies; handle counts are not checked here.
fn open_descriptors(_arena: *mem.Arena) usize {
  return 0
}
fn no_children() bool {
  return true
}
'''


def dyn_text(value):
    return json.dumps(str(value), ensure_ascii=False)


def write_program(directory, shell, parent, child_path, child_directory):
    directory.mkdir(exist_ok=True)
    source = (PROGRAM.replace('SHELL', 'true' if shell else 'false')
              .replace('CHILD_PATH', dyn_text(child_path))
              .replace('CHILD_DIRECTORY', dyn_text(child_directory))
              .replace('PARENT', dyn_text(parent)))
    (directory / 'main.dyn').write_text(source, encoding='utf-8')
    (directory / 'unix.dyn').write_text(UNIX)
    (directory / 'linux.dyn').write_text(LINUX)
    (directory / 'macos.dyn').write_text(MACOS)
    (directory / 'windows.dyn').write_text(WINDOWS)


with tempfile.TemporaryDirectory(prefix='dyn process pty ') as temporary:
    root = Path(temporary)
    (root / 'marker').write_text('parent-marker')
    child_directory = root / 'child directory'
    child_directory.mkdir()
    (child_directory / 'marker').write_text('child-marker')
    child_source = root / 'child'
    child_source.mkdir()
    (child_source / 'main.dyn').write_text(CHILD)
    windows = os.name == 'nt'
    child_executable = root / ('child.exe' if windows else 'child-bin')
    program = root / 'program'
    write_program(program, not windows, root, child_executable, child_directory)
    for target in TARGETS:
        for checked_source in (program, child_source):
            checked = subprocess.run([DYN, 'check', str(checked_source), '--quiet', '--target', target], capture_output=True, text=True)
            assert checked.returncode == 0, (target, checked_source.name, checked.stdout, checked.stderr)
    if sys.platform.startswith('linux') and os.uname().machine not in ('x86_64', 'AMD64'):
        print('PASS pty programs check on six targets; Linux on this architecture lacks setsid, not run')
        sys.exit(0)
    built = subprocess.run([DYN, 'build', str(child_source), '--quiet', '--output', str(child_executable)], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    for mode in ('debug', 'release'):
        executable = root / ('program.exe' if windows else 'program-bin')
        built = subprocess.run([DYN, 'build', str(program), '--' + mode, '--quiet', '--output', str(executable)], capture_output=True, text=True)
        assert built.returncode == 0, (mode, built.stderr)
        ran = subprocess.run([str(executable)], cwd=root, capture_output=True, timeout=60)
        assert ran.returncode == 0 and b'PASS' in ran.stdout, (mode, ran.returncode, ran.stdout[-4000:], ran.stderr[-4000:])
print('PASS pty: shell and Dyn child on a terminal, resize, exit status, no leaked descriptor or child; six targets check')
