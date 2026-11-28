#!/usr/bin/env python3
"""std/fs is one interface on every platform: the program below, which uses
every portable file primitive, type-checks for the six desktop targets and
runs on the host (Linux, macOS or Windows). On Linux it also runs as an
AArch64 program under qemu-aarch64 when that is installed, which exercises
the fallbacks for system calls the compiler does not map there yet.

Checked behavior: owner-only creation (0o600 / 0o700), exclusive rename
failing with AlreadyExists, open_no_follow refusing a symbolic link,
link_metadata, modification and change times moving after a write,
same_file and unchanged, clone_file and copy_range producing equal bytes
without moving the source, set_permissions, preserve_permissions,
is_executable, lock, truncate, read_link, copy_file, atomic writes,
sync_directory, app_directory and remove_tree not following links."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build' / ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve())
TARGETS = ('x86_64-linux', 'aarch64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows')

PROGRAM = r'''use fs "std/fs"
use io "std/io"
use mem "std/mem"
use time "std/time"

fn kind(err: io.IoErr) []const u8 {
  case err {
    .NotFound => { return "NotFound" }
    .PermissionDenied => { return "PermissionDenied" }
    .AlreadyExists => { return "AlreadyExists" }
    .InvalidInput => { return "InvalidInput" }
    .WouldBlock => { return "WouldBlock" }
    .Interrupted => { return "Interrupted" }
    .Unsupported => { return "Unsupported" }
    .Capacity => { return "Capacity" }
    .System(_) => { return "System" }
  }
}
fn require(ok: bool, what: []const u8) {
  if !ok {
    io.println("FAIL {}", what)
    #panic(what)
  }
}
fn stop(what: []const u8, err: io.IoErr) {
  io.println("FAIL {} {}", what, kind(err))
  #panic(what)
}
fn info_of(path: []const u8) fs.Metadata {
  return fs.metadata(path) catch err {
    stop(path, err)
    return fs.Metadata{}
  }
}
fn exists(path: []const u8) bool {
  _ = fs.link_metadata(path) catch { return false }
  return true
}
fn put(path: []const u8, text: []const u8) {
  fs.write_all(path, text) catch err { stop(path, err) }
}
fn same_text(arena: *mem.Arena, path: []const u8, expected: []const u8) bool {
  got := fs.read_all(arena, path, 1048576) catch { return false }
  if got.len != expected.len { return false }
  for i in 0..got.len {
    if got[i] != expected[i] { return false }
  }
  return true
}
fn position(file: *fs.File) usize {
  return fs.seek(file, 0, 1) catch err {
    stop("seek", err)
    return 0
  }
}

// Each reports its failure's kind and whether it opened a file anyway.
fn private_again(path: []const u8) bool {
  file := fs.create_private(path) catch err {
    io.println("private_again {}", kind(err))
    return false
  }
  fs.close(&file)
  return true
}
fn opened_no_follow(path: []const u8) bool {
  file := fs.open_no_follow(path) catch err {
    io.println("open_no_follow link {}", kind(err))
    return false
  }
  fs.close(&file)
  return true
}
fn cloned_again(source: *fs.File, path: []const u8, scratch: []u8) bool {
  file := fs.clone_file(source, path, scratch) catch err {
    io.println("clone_again {}", kind(err))
    return false
  }
  fs.close(&file)
  return true
}

fn main() {
  arena := mem.arena_alloc(0)
  scratch: [4096]u8

  // Owner-only creation, exclusive.
  private := fs.create_private("private") catch err {
    stop("create_private", err)
    return
  }
  fs.write(&private, "secret") catch err { stop("write private", err) }
  fs.close(&private)
  io.println("private_mode {}", info_of("private").mode & 0o7777)
  require(!private_again("private"), "create_private replaced a file")
  tool := fs.create_private_executable("tool.exe") catch err {
    stop("create_private_executable", err)
    return
  }
  fs.close(&tool)
  io.println("executable_mode {}", info_of("tool.exe").mode & 0o7777)
  io.println("is_executable tool {}", fs.is_executable("tool.exe"))
  io.println("is_executable private {}", fs.is_executable("private"))
  io.println("is_executable missing {}", fs.is_executable("missing"))

  // Exclusive rename.
  put("old", "old")
  put("new", "new")
  fs.rename_exclusive("old", "new") catch err { io.println("rename_existing {}", kind(err)) }
  require(same_text(arena, "old", "old") && same_text(arena, "new", "new"), "rename_exclusive changed files")
  fs.rename_exclusive("old", "fresh") catch err { stop("rename_exclusive", err) }
  require(same_text(arena, "fresh", "old"), "rename_exclusive lost contents")
  require(!exists("old"), "rename_exclusive kept the old name")

  // Symbolic links, where the system lets this process make them.
  put("target.txt", "target")
  linked := true
  fs.symbolic_link("target.txt", "link") catch err {
    io.println("symbolic_link {}", kind(err))
    linked = false
  }
  if linked {
    io.println("symbolic_link ok")
    require(!opened_no_follow("link"), "open_no_follow followed a link")
    plain := fs.open_no_follow("target.txt") catch err {
      stop("open_no_follow file", err)
      return
    }
    fs.close(&plain)
    link_info := fs.link_metadata("link") catch err {
      stop("link_metadata", err)
      return
    }
    require(fs.is_symbolic_link(link_info), "link_metadata saw no link")
    require(fs.is_file(info_of("link")), "metadata did not follow the link")
    require(!fs.is_symbolic_link(info_of("link")), "metadata reported a link")
    require(fs.same_file(info_of("link"), info_of("target.txt")), "a link and its target differ")
    target := fs.read_link(arena, "link") catch err {
      stop("read_link", err)
      return
    }
    io.println("read_link {}", target)
  }
  file_info := fs.link_metadata("target.txt") catch err {
    stop("link_metadata file", err)
    return
  }
  require(fs.is_file(file_info) && !fs.is_symbolic_link(file_info), "link_metadata of a file")

  // Times move after a write; same_file and unchanged tell versions apart.
  watched := fs.create("watched") catch err {
    stop("create watched", err)
    return
  }
  fs.write(&watched, "a") catch err { stop("write watched", err) }
  before := fs.file_metadata(&watched) catch err {
    stop("file_metadata", err)
    return
  }
  require(before.modified_seconds > 1600000000 && before.changed_seconds > 1600000000, "times are not since 1970")
  require(before.modified_nanoseconds < 1000000000 && before.changed_nanoseconds < 1000000000, "nanoseconds out of range")
  require(fs.unchanged(before, before) && fs.same_file(before, info_of("watched")), "a file differs from itself")
  moved := false
  for attempt in 0..300 {
    time.sleep(10000000)
    fs.write(&watched, "b") catch err { stop("write watched", err) }
    after := fs.file_metadata(&watched) catch err {
      stop("file_metadata", err)
      return
    }
    if after.modified_seconds != before.modified_seconds || after.modified_nanoseconds != before.modified_nanoseconds {
      require(!fs.unchanged(before, after), "unchanged missed a write")
      require(fs.same_file(before, after), "a write changed identity")
      require(after.changed_seconds > before.changed_seconds || (after.changed_seconds == before.changed_seconds && after.changed_nanoseconds >= before.changed_nanoseconds), "change time went back")
      moved = true
      break
    }
  }
  require(moved, "modification time never moved")
  fs.close(&watched)
  original := info_of("watched")
  fs.write_atomic("watched", "watched.tmp", "replaced") catch err { stop("write_atomic", err) }
  require(!fs.same_file(original, info_of("watched")), "a replaced file kept its identity")
  require(same_text(arena, "watched", "replaced"), "write_atomic contents")

  // A source over two 64 KiB blocks.
  pattern := fs.create("pattern") catch err {
    stop("create pattern", err)
    return
  }
  block: [1000]u8
  for i in 0..200 {
    for j in 0..1000 {
      block[j] = #cast(u8, (i * 7 + j * 13) % 251)
    }
    fs.write(&pattern, block[..]) catch err { stop("write pattern", err) }
  }
  fs.close(&pattern)
  expected := fs.read_all(arena, "pattern", 1048576) catch err {
    stop("read pattern", err)
    return
  }
  source := fs.open("pattern") catch err {
    stop("open pattern", err)
    return
  }
  _ = fs.seek(&source, 5, 0) catch err {
    stop("seek pattern", err)
    return
  }
  clone := fs.clone_file(&source, "clone", scratch[..]) catch err {
    stop("clone_file", err)
    return
  }
  require(position(&clone) == 0, "clone_file position")
  fs.close(&clone)
  require(position(&source) == 5, "clone_file moved the source")
  require(same_text(arena, "clone", expected), "clone_file bytes")
  require((info_of("clone").mode & 0o600) == 0o600, "clone_file owner bits")
  require(!cloned_again(&source, "clone", scratch[..]), "clone_file replaced a file")
  require(same_text(arena, "clone", expected), "a failed clone_file touched the file")

  ranged := fs.create("ranged") catch err {
    stop("create ranged", err)
    return
  }
  fs.write(&ranged, "head") catch err { stop("write ranged", err) }
  copied := fs.copy_range(&source, 70000, &ranged, 100000, scratch[..]) catch err {
    stop("copy_range", err)
    return
  }
  require(copied == 100000, "copy_range count")
  require(position(&ranged) == 100004, "copy_range destination position")
  short := fs.copy_range(&source, 199990, &ranged, 100, scratch[..]) catch err {
    stop("copy_range end", err)
    return
  }
  require(short == 10, "copy_range past the end")
  require(position(&source) == 5, "copy_range moved the source")
  fs.close(&ranged)
  fs.close(&source)
  wanted := mem.push_bytes(arena, 100014)
  wanted[0] = 'h'
  wanted[1] = 'e'
  wanted[2] = 'a'
  wanted[3] = 'd'
  for i in 0..100000 {
    wanted[4 + i] = expected[70000 + i]
  }
  for i in 0..10 {
    wanted[100004 + i] = expected[199990 + i]
  }
  require(same_text(arena, "ranged", wanted), "copy_range bytes")
  empty: [0]u8
  ranged_closed := fs.copy_range(&source, 0, &ranged, 1, empty[..]) catch 7
  require(ranged_closed == 7, "copy_range on closed files")

  // Permissions.
  shared := fs.create("shared") catch err {
    stop("create shared", err)
    return
  }
  fs.set_permissions(&shared, 0o640) catch err { io.println("set_permissions {}", kind(err)) }
  io.println("shared_mode {}", info_of("shared").mode & 0o7777)
  fs.set_permissions(&shared, 0o444) catch err { io.println("set_permissions {}", kind(err)) }
  io.println("read_only_mode {}", info_of("shared").mode & 0o7777)
  fs.set_permissions(&shared, 0o751) catch err { io.println("set_permissions {}", kind(err)) }
  fs.close(&shared)
  copy := fs.create_exclusive("copy") catch err {
    stop("create copy", err)
    return
  }
  fs.preserve_permissions(&copy, "shared") catch err { io.println("preserve_permissions {}", kind(err)) }
  fs.close(&copy)
  io.println("preserved_mode {}", info_of("copy").mode & 0o7777)
  refused_mode := true
  fs.set_permissions(&copy, 0o644) catch { refused_mode = false }
  require(!refused_mode, "set_permissions on a closed file")

  // Locks.
  put("lock", "")
  first := fs.open("lock") catch err {
    stop("open lock", err)
    return
  }
  second := fs.open("lock") catch err {
    stop("open lock", err)
    return
  }
  fs.lock(&first, 2) catch err { stop("lock", err) }
  fs.lock(&second, 6) catch err { io.println("lock busy {}", kind(err)) }
  fs.lock(&first, 8) catch err { stop("unlock", err) }
  fs.lock(&second, 6) catch err { stop("lock free", err) }
  fs.lock(&second, 8) catch err { stop("unlock", err) }
  fs.lock(&second, 8) catch err { stop("unlock unlocked", err) }
  fs.close(&first)
  fs.close(&second)

  // Length, copies, atomic files and directories.
  fs.truncate("pattern", 3) catch err { stop("truncate", err) }
  require(info_of("pattern").size == 3, "truncate length")
  count := fs.copy_file("fresh", "copied", scratch[..]) catch err {
    stop("copy_file", err)
    return
  }
  require(count == 3 && same_text(arena, "copied", "old"), "copy_file")
  aborted := fs.atomic_begin("kept", "kept.tmp") catch err {
    stop("atomic_begin", err)
    return
  }
  fs.atomic_abort(&aborted)
  require(!exists("kept.tmp"), "atomic_abort left the temporary")
  durable := fs.atomic_begin("kept", "kept.tmp") catch err {
    stop("atomic_begin", err)
    return
  }
  fs.write(&durable.file, "kept") catch err { stop("atomic write", err) }
  fs.atomic_commit_durable(&durable, ".") catch err { stop("atomic_commit_durable", err) }
  require(same_text(arena, "kept", "kept"), "atomic_commit_durable contents")
  fs.sync_directory(".") catch err { stop("sync_directory", err) }
  fs.sync_directory("missing") catch err { io.println("sync_missing {}", kind(err)) }
  home := fs.app_directory(arena, fs.AppDirectory.Home) catch err {
    stop("app_directory", err)
    return
  }
  require(home.len > 0, "app_directory home")
  config := fs.app_directory(arena, fs.AppDirectory.Config) catch err {
    stop("app_directory config", err)
    return
  }
  require(config.len > home.len || config.len > 3, "app_directory config")

  // remove_tree removes links, never what they point at.
  fs.make_directory("keep") catch err { stop("make keep", err) }
  put("keep/file", "keep")
  fs.make_directory("tree") catch err { stop("make tree", err) }
  fs.make_directory("tree/a") catch err { stop("make tree/a", err) }
  fs.make_directory("tree/a/b") catch err { stop("make tree/a/b", err) }
  put("tree/a/b/file", "x")
  put("tree/top", "x")
  locked := fs.create("tree/a/read-only") catch err {
    stop("create read-only", err)
    return
  }
  fs.set_permissions(&locked, 0o444) catch {}
  fs.close(&locked)
  if linked {
    fs.symbolic_link("../keep", "tree/a/outside") catch err { stop("symbolic_link directory", err) }
  }
  frames: [8]fs.RemovalFrame
  tree_scratch: [8 * fs.RemovalScratch]u8
  shallow: [1]fs.RemovalFrame
  fs.remove_tree("tree", shallow[..], tree_scratch[..fs.RemovalScratch]) catch err { io.println("remove_tree shallow {}", kind(err)) }
  fs.remove_tree("tree", frames[..], tree_scratch[..]) catch err { stop("remove_tree", err) }
  require(!exists("tree"), "remove_tree left the tree")
  require(same_text(arena, "keep/file", "keep"), "remove_tree followed a link")
  fs.remove_tree("target.txt", frames[..], tree_scratch[..]) catch err { stop("remove_tree file", err) }
  small: [1]u8
  fs.remove_tree("keep", frames[..], small[..]) catch err { io.println("remove_tree small {}", kind(err)) }
  io.println("PASS")
}
'''


def run(command, **options):
    return subprocess.run(command, capture_output=True, text=True, **options)


def lines(output):
    found = {}
    for line in output.splitlines():
        if line.startswith('FAIL'):
            raise AssertionError(line)
        name, _, value = line.rpartition(' ')
        found[name] = value
    return found


def expect(found, wanted, label):
    for name, value in wanted.items():
        assert found.get(name) == value, (label, name, found.get(name), value, found)


def execute(executable, label, system, emulator=()):
    with tempfile.TemporaryDirectory(prefix='dyn-fs-portable-run-') as work:
        result = run([*emulator, str(executable)], cwd=work, timeout=120)
        assert result.returncode == 0, (label, result.stdout, result.stderr)
        found = lines(result.stdout)
    assert found.get('PASS') is not None or 'PASS' in result.stdout, (label, result.stdout)
    common = {
        'private_again': 'AlreadyExists',
        'rename_existing': 'AlreadyExists',
        'clone_again': 'AlreadyExists',
        'lock busy': 'WouldBlock',
        'sync_missing': 'NotFound',
        'remove_tree shallow': 'Capacity',
        'remove_tree small': 'InvalidInput',
        'is_executable missing': 'false',
    }
    expect(found, common, label)
    if found.get('symbolic_link') == 'ok':
        expect(found, {'open_no_follow link': 'InvalidInput', 'read_link': 'target.txt'}, label)
    else:
        # Only Windows without Developer Mode or the privilege may refuse.
        assert system == 'Windows' and found.get('symbolic_link') == 'PermissionDenied', (label, found)
    if system == 'Windows':
        expect(found, {
            'private_mode': str(0o666), 'executable_mode': str(0o666),
            'shared_mode': str(0o666), 'read_only_mode': str(0o444),
            'preserved_mode': str(0o666),
            'is_executable tool': 'true', 'is_executable private': 'false',
        }, label)
        assert 'set_permissions' not in found and 'preserve_permissions' not in found, (label, found)
        return
    expect(found, {'private_mode': str(0o600), 'executable_mode': str(0o700), 'is_executable private': 'false'}, label)
    assert 'set_permissions' not in found and 'preserve_permissions' not in found, (label, found)
    expect(found, {
        'shared_mode': str(0o640), 'read_only_mode': str(0o444), 'preserved_mode': str(0o751),
        'is_executable tool': 'true',
    }, label)


with tempfile.TemporaryDirectory(prefix='dyn-fs-portable-') as directory:
    root = Path(directory)
    (root / 'main.dyn').write_text(PROGRAM)
    for target in TARGETS:
        checked = run([DYN, 'check', str(root), '--quiet', '--target', target])
        assert checked.returncode == 0, (target, checked.stdout, checked.stderr)
    system = 'Windows' if os.name == 'nt' else platform.system()
    program = root / ('program.exe' if os.name == 'nt' else 'program')
    built = run([DYN, 'build', str(root), '--quiet', '--no-cache', '--output', str(program)])
    assert built.returncode == 0, built.stderr
    execute(program, system.lower(), system)
    ran = [system]
    emulator = shutil.which('qemu-aarch64')
    if system == 'Linux' and platform.machine() == 'x86_64' and emulator:
        arm = root / 'program-aarch64'
        built = run([DYN, 'build', str(root), '--quiet', '--no-cache', '--target', 'aarch64-linux', '--output', str(arm)])
        assert built.returncode == 0, built.stderr
        execute(arm, 'aarch64-linux', system, (emulator,))
        ran.append('aarch64-linux under qemu')
print(f"PASS fs portable: six targets check; ran on {', '.join(ran)}")
