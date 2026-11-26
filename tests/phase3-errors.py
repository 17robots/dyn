#!/usr/bin/env python3
"""End-to-end tests for Phase 3: T!E error handling, composable enum unions A | B,
try, catch, fail, errdefer, and variant-0 payload enums."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN_DEBUG = str(Path(os.environ.get('DYN_DEBUG', ROOT / 'build/dyn')).resolve())
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

PROGRAM = r'''
// 1. Variant-0 payload enum (zero-init is tag 0 with zero payload)
enum Opt {
  Some(i32),
  None,
}

enum FsErr {
  NotFound(str),
  PermissionDenied,
  Io(i32),
}

enum ParseErr {
  Empty,
  BadFormat(i32),
}

enum NetErr {
  Timeout,
  Refused(i32),
}

type AppErr = FsErr | ParseErr
type FullErr = AppErr | NetErr
type ReorderedErr = ParseErr | FsErr

fn read_mock(mode: i32) str!FsErr {
  if mode == 1 { fail FsErr.NotFound("missing.txt") }
  if mode == 2 { fail .PermissionDenied }
  if mode == 3 { fail FsErr.Io(42) }
  return "123"
}

fn parse_mock(s: str, fail_mode: i32) i32!ParseErr {
  if s.len == 0 { fail .Empty }
  if fail_mode == 1 { fail ParseErr.BadFormat(9) }
  return 123
}

// 2. Composable error union widening through try + fail
fn load_config(fs_mode: i32, parse_mode: i32) i32!(FsErr | ParseErr) {
  text := try read_mock(fs_mode)
  n := try parse_mock(text, parse_mode)
  return n + 1
}

// Order-independent identity: ParseErr | FsErr == FsErr | ParseErr
fn load_reordered(fs_mode: i32) i32!ReorderedErr {
  return try load_config(fs_mode, 0)
}

// Widening a smaller error union (FsErr | ParseErr) -> (FsErr | ParseErr | NetErr)
fn load_full(fs_mode: i32, parse_mode: i32, net_fail: bool) i32!FullErr {
  if net_fail { fail NetErr.Refused(503) }
  v := try load_config(fs_mode, parse_mode)
  return v
}

// 3. Void success !E (implicit Ok on falling off end)
fn check_positive(x: i32) !ParseErr {
  if x <= 0 { fail ParseErr.BadFormat(x) }
}

// 4. Untyped error T! and ! (drops error payload when propagating via try)
fn maybe_num(ok: bool) i32! {
  if !ok { fail }
  return 77
}

fn drop_typed_to_untyped(fs_mode: i32) i32! {
  s := try read_mock(fs_mode)
  return #cast(i32, s.len)
}

fn maybe_void(ok: bool) ! {
  if !ok { fail }
}

// 5. Generic fallible function
fn wrap_fallible<T>(val: T, bad: bool) T!ParseErr {
  if bad { fail ParseErr.Empty }
  return val
}

// 6. errdefer + defer LIFO interleaving
log_buf: [16]i32
log_len: usize = 0

fn push_log(v: i32) {
  log_buf[log_len] = v
  log_len += 1
}

fn test_errdefer_order(fail_at: i32) i32!FsErr {
  defer push_log(1)
  errdefer push_log(2)
  defer push_log(3)
  if fail_at == 1 { fail FsErr.PermissionDenied }
  errdefer {
    push_log(4)
  }
  _ = try read_mock(fail_at == 2 ? 3 : 0)
  return 99
}

fn helper_fail_mode(fail_at: i32) i32!FsErr {
  defer push_log(1)
  errdefer push_log(2)
  defer push_log(3)
  if fail_at == 1 { fail FsErr.PermissionDenied }
  errdefer {
    push_log(4)
  }
  if fail_at == 2 {
    _ = try read_mock(3)
  }
  return 99
}

// 7. Short-circuiting && and || with try / catch
side_effects: i32 = 0

fn fallible_bool(ret: bool, do_fail: bool) bool!ParseErr {
  side_effects += 1
  if do_fail { fail ParseErr.Empty }
  return ret
}

fn test_short_circuit() bool!ParseErr {
  side_effects = 0
  a := false && try fallible_bool(true, true)
  if a || side_effects != 0 { #panic("&& short-circuit failed") }
  b := true || try fallible_bool(false, true)
  if !b || side_effects != 0 { #panic("|| short-circuit failed") }
  c := true && try fallible_bool(true, false)
  if !c || side_effects != 1 { #panic("&& eval failed") }
  return true
}

// 8. for try cond()
loop_counter: i32 = 0

fn next_tick() bool!ParseErr {
  loop_counter += 1
  if loop_counter == 4 { fail ParseErr.BadFormat(4) }
  return loop_counter <= 3
}

fn run_loop_try() i32!ParseErr {
  loop_counter = 0
  sum: i32 = 0
  for try next_tick() {
    sum += loop_counter
  }
  return sum
}

// 9. Lazy evaluation of catch fallback
fb_called: i32 = 0

fn make_fallback() i32 {
  fb_called += 1
  return 555
}

// 10. Pointer binding on error union case
fn bump_err(e: *AppErr) i32 {
  case e.* {
    FsErr.Io(*code) => {
      code.* += 10
      return code.*
    }
    FsErr.NotFound(_) => { return 1 }
    FsErr.PermissionDenied => { return 2 }
    ParseErr(pe) => {
      case pe {
        .Empty => { return 3 }
        .BadFormat(n) => { return n }
      }
    }
  }
}

fn classify_full(e: FullErr) i32 {
  case e {
    FsErr.NotFound(p) => { return #cast(i32, p.len) }
    FsErr.Io(_), ParseErr.BadFormat(_) => { return 700 }
    NetErr(ne) => {
      case ne {
        .Timeout => { return 800 }
        .Refused(c) => { return c }
      }
    }
    _ => { return 900 }
  }
}

fn main() {
  // Variant-0 payload enum
  z: Opt
  case z {
    .Some(v) => {
      if v != 0 { #panic("variant 0 zero payload") }
    }
    .None => { #panic("expected variant 0") }
  }
  s := Opt.Some(42)
  case s {
    .Some(v) => {
      if v != 42 { #panic("Opt.Some(42)") }
    }
    .None => { #panic("expected Some") }
  }

  // Basic catch fallback + lazy evaluation
  fb_called = 0
  v1 := load_config(0, 0) catch make_fallback()
  if v1 != 124 || fb_called != 0 { #panic("catch ok should not eval fallback") }
  v2 := load_config(1, 0) catch make_fallback()
  if v2 != 555 || fb_called != 1 { #panic("catch err should eval fallback") }

  // Chained catch
  v3 := maybe_num(false) catch maybe_num(true) catch 0
  if v3 != 77 { #panic("chained catch") }
  v4 := maybe_num(false) catch maybe_num(false) catch 12
  if v4 != 12 { #panic("chained catch final") }

  // Untyped drop
  if (drop_typed_to_untyped(0) catch -1) != 3 { #panic("drop ok") }
  if (drop_typed_to_untyped(1) catch -1) != -1 { #panic("drop err") }

  // Void fallible !E and !
  caught_void: i32 = 0
  check_positive(5) catch { caught_void = 1 }
  if caught_void != 0 { #panic("check_positive ok") }
  check_positive(-3) catch err {
    case err {
      .Empty => { caught_void = 10 }
      .BadFormat(n) => { caught_void = n }
    }
  }
  if caught_void != -3 { #panic("check_positive err") }

  void_flag := 0
  maybe_void(false) catch { void_flag = 1 }
  if void_flag != 1 { #panic("maybe_void") }

  // Catch block with break/continue in loop
  loop_acc := 0
  for i in 0..5 {
    val := maybe_num(i != 2) catch {
      if i == 2 { continue }
      break
    }
    loop_acc += val
  }
  if loop_acc != 77 * 4 { #panic("catch continue in loop") }

  // Reordered error union + FullErr widening + exhaustive case
  if (load_reordered(0) catch -1) != 124 { #panic("reordered ok") }
  r_nf := 0
  _ = load_full(1, 0, false) catch err {
    r_nf = classify_full(err)
    return
  }
  // Wait: let's test classify_full via helper without returning from main
  e1: FullErr = FsErr.NotFound("abcd")
  if classify_full(e1) != 4 { #panic("classify NotFound") }
  e2: FullErr = FsErr.Io(9)
  if classify_full(e2) != 700 { #panic("classify grouped FsErr.Io") }
  e3: FullErr = ParseErr.BadFormat(8)
  if classify_full(e3) != 700 { #panic("classify grouped ParseErr.BadFormat") }
  e4: FullErr = NetErr.Refused(503)
  if classify_full(e4) != 503 { #panic("classify NetErr") }
  e5: FullErr = FsErr.PermissionDenied
  if classify_full(e5) != 900 { #panic("classify wildcard") }

  // Smaller union -> larger union widening via load_full
  got_full: i32 = 0
  _ = load_full(0, 1, false) catch err {
    got_full = classify_full(err)
    _ = got_full
    // use a fallback block via helper below
  }
}
'''

# Clean version of PROGRAM without ternary (Dyn uses if/else, not ?:) and with clean helper for catch-return
PROGRAM = r'''
enum Opt {
  Some(i32),
  None,
}

enum FsErr {
  NotFound(str),
  PermissionDenied,
  Io(i32),
}

enum ParseErr {
  Empty,
  BadFormat(i32),
}

enum NetErr {
  Timeout,
  Refused(i32),
}

type AppErr = FsErr | ParseErr
type FullErr = AppErr | NetErr
type ReorderedErr = ParseErr | FsErr

fn read_mock(mode: i32) str!FsErr {
  if mode == 1 { fail FsErr.NotFound("missing.txt") }
  if mode == 2 { fail .PermissionDenied }
  if mode == 3 { fail FsErr.Io(42) }
  return "123"
}

fn parse_mock(s: str, fail_mode: i32) i32!ParseErr {
  if s.len == 0 { fail .Empty }
  if fail_mode == 1 { fail ParseErr.BadFormat(9) }
  return 123
}

fn load_config(fs_mode: i32, parse_mode: i32) i32!(FsErr | ParseErr) {
  text := try read_mock(fs_mode)
  n := try parse_mock(text, parse_mode)
  return n + 1
}

fn load_reordered(fs_mode: i32) i32!ReorderedErr {
  return try load_config(fs_mode, 0)
}

fn load_full(fs_mode: i32, parse_mode: i32, net_fail: bool) i32!FullErr {
  if net_fail { fail NetErr.Refused(503) }
  v := try load_config(fs_mode, parse_mode)
  return v
}

fn check_positive(x: i32) !ParseErr {
  if x <= 0 { fail ParseErr.BadFormat(x) }
}

fn maybe_num(ok: bool) i32! {
  if !ok { fail }
  return 77
}

fn drop_typed_to_untyped(fs_mode: i32) i32! {
  s := try read_mock(fs_mode)
  return #cast(i32, s.len)
}

fn maybe_void(ok: bool) ! {
  if !ok { fail }
}

fn wrap_fallible<T>(val: T, bad: bool) T!ParseErr {
  if bad { fail ParseErr.Empty }
  return val
}

log_buf: [16]i32
log_len: usize = 0

fn push_log(v: i32) {
  log_buf[log_len] = v
  log_len += 1
}

fn helper_errdefer(fail_at: i32) i32!FsErr {
  defer push_log(1)
  errdefer push_log(2)
  defer push_log(3)
  if fail_at == 1 { fail FsErr.PermissionDenied }
  errdefer {
    push_log(4)
  }
  if fail_at == 2 {
    _ = try read_mock(3)
  }
  return 99
}

side_effects: i32 = 0

fn fallible_bool(ret: bool, do_fail: bool) bool!ParseErr {
  side_effects += 1
  if do_fail { fail ParseErr.Empty }
  return ret
}

fn test_short_circuit() bool!ParseErr {
  side_effects = 0
  a := false && try fallible_bool(true, true)
  if a || side_effects != 0 { #panic("&& short-circuit failed") }
  b := true || try fallible_bool(false, true)
  if !b || side_effects != 0 { #panic("|| short-circuit failed") }
  c := true && try fallible_bool(true, false)
  if !c || side_effects != 1 { #panic("&& eval failed") }
  return true
}

loop_counter: i32 = 0

fn next_tick() bool!ParseErr {
  loop_counter += 1
  if loop_counter == 4 { fail ParseErr.BadFormat(4) }
  return loop_counter <= 3
}

fn run_loop_try() i32!ParseErr {
  loop_counter = 0
  sum: i32 = 0
  for try next_tick() {
    sum += loop_counter
  }
  return sum
}

fb_called: i32 = 0

fn make_fallback() i32 {
  fb_called += 1
  return 555
}

fn bump_err(e: *AppErr) i32 {
  case e.* {
    FsErr.Io(*code) => {
      code.* += 10
      return code.*
    }
    FsErr.NotFound(_) => { return 1 }
    FsErr.PermissionDenied => { return 2 }
    ParseErr(pe) => {
      case pe {
        .Empty => { return 3 }
        .BadFormat(n) => { return n }
      }
    }
  }
}

fn classify_full(e: FullErr) i32 {
  case e {
    FsErr.NotFound(p) => { return #cast(i32, p.len) }
    FsErr.Io(_), ParseErr.BadFormat(_) => { return 700 }
    NetErr(ne) => {
      case ne {
        .Timeout => { return 800 }
        .Refused(c) => { return c }
      }
    }
    _ => { return 900 }
  }
}

fn call_and_classify(fs_mode: i32, parse_mode: i32, net_fail: bool) i32 {
  v := load_full(fs_mode, parse_mode, net_fail) catch err {
    return classify_full(err)
  }
  return v
}

fn main() {
  // 1. Variant-0 payload enum
  z: Opt
  case z {
    .Some(v) => {
      if v != 0 { #panic("variant 0 zero payload") }
    }
    .None => { #panic("expected variant 0") }
  }
  s := Opt.Some(42)
  case s {
    .Some(v) => {
      if v != 42 { #panic("Opt.Some(42)") }
    }
    .None => { #panic("expected Some") }
  }

  // 2. Basic catch fallback + lazy evaluation
  fb_called = 0
  v1 := load_config(0, 0) catch make_fallback()
  if v1 != 124 || fb_called != 0 { #panic("catch ok should not eval fallback") }
  v2 := load_config(1, 0) catch make_fallback()
  if v2 != 555 || fb_called != 1 { #panic("catch err should eval fallback") }

  // 3. Chained catch
  v3 := maybe_num(false) catch maybe_num(true) catch 0
  if v3 != 77 { #panic("chained catch") }
  v4 := maybe_num(false) catch maybe_num(false) catch 12
  if v4 != 12 { #panic("chained catch final") }

  // 4. Untyped drop
  if (drop_typed_to_untyped(0) catch -1) != 3 { #panic("drop ok") }
  if (drop_typed_to_untyped(1) catch -1) != -1 { #panic("drop err") }

  // 5. Void fallible !E and !
  caught_void: i32 = 0
  check_positive(5) catch { caught_void = 1 }
  if caught_void != 0 { #panic("check_positive ok") }
  check_positive(-3) catch err {
    case err {
      .Empty => { caught_void = 10 }
      .BadFormat(n) => { caught_void = n }
    }
  }
  if caught_void != -3 { #panic("check_positive err") }

  void_flag := 0
  maybe_void(false) catch { void_flag = 1 }
  if void_flag != 1 { #panic("maybe_void") }

  // 6. Catch block with continue in loop
  loop_acc := 0
  for i in 0..5 {
    val := maybe_num(i != 2) catch {
      if i == 2 { continue }
      break
    }
    loop_acc += val
  }
  if loop_acc != 77 * 4 { #panic("catch continue in loop") }

  // 7. Generic fallible function
  if (wrap_fallible<i32>(19, false) catch 0) != 19 { #panic("generic ok") }
  if (wrap_fallible<i32>(19, true) catch -1) != -1 { #panic("generic err") }

  // 8. Reordered union, widening, and exhaustive case on FullErr
  if (load_reordered(0) catch -1) != 124 { #panic("reordered ok") }
  if call_and_classify(0, 0, false) != 124 { #panic("full ok") }
  if call_and_classify(1, 0, false) != 11 { #panic("full NotFound") }
  if call_and_classify(2, 0, false) != 900 { #panic("full wildcard") }
  if call_and_classify(3, 0, false) != 700 { #panic("full grouped FsErr.Io") }
  if call_and_classify(0, 1, false) != 700 { #panic("full grouped ParseErr.BadFormat") }
  if call_and_classify(0, 0, true) != 503 { #panic("full NetErr.Refused") }

  // 9. Pointer payload binding on error union case
  ae: AppErr = FsErr.Io(30)
  if bump_err(&ae) != 40 { #panic("bump_err return") }
  if bump_err(&ae) != 50 { #panic("bump_err mutated in place") }

  // 10. errdefer + defer LIFO interleaving
  // Success path: only normal defers run (3, 1)
  log_len = 0
  if (helper_errdefer(0) catch -1) != 99 { #panic("errdefer ok") }
  if log_len != 2 || log_buf[0] != 3 || log_buf[1] != 1 { #panic("errdefer ok order") }

  // Fail at 1 (before errdefer 4): 3, 2, 1
  log_len = 0
  if (helper_errdefer(1) catch -1) != -1 { #panic("errdefer fail 1") }
  if log_len != 3 || log_buf[0] != 3 || log_buf[1] != 2 || log_buf[2] != 1 { #panic("errdefer fail 1 order") }

  // Fail at 2 (via try, after errdefer 4): 4, 3, 2, 1
  log_len = 0
  if (helper_errdefer(2) catch -1) != -1 { #panic("errdefer fail 2") }
  if log_len != 4 || log_buf[0] != 4 || log_buf[1] != 3 || log_buf[2] != 2 || log_buf[3] != 1 { #panic("errdefer fail 2 order") }

  // 11. Short-circuit && and ||
  if !(test_short_circuit() catch false) { #panic("short circuit") }

  // 12. for try cond()
  if (run_loop_try() catch -9) != -9 || loop_counter != 4 { #panic("for try cond") }
}
'''

STDLIB_PROGRAM = r'''
use mem "std/mem"
use parse "std/parse"
use fs "std/fs"
use io "std/io"

fn read_and_parse(arena: *mem.Arena, path: str) i64!(io.IoErr | parse.ParseErr) {
  raw := try fs.read_all(arena, path, 4096)
  return try parse.parse_i64(raw)
}

fn main() {
  arena := mem.arena_alloc(mem.MiB)
  defer mem.arena_release(arena)
  if (parse.parse_u64("42") catch 0) != 42 { #panic("parse_u64") }
  if (parse.parse_i64("-123") catch 0) != -123 { #panic("parse_i64") }
  _ = read_and_parse(arena, "/nonexistent-dyn-phase3-file") catch err {
    case err {
      io.IoErr.NotFound => { return }
      parse.ParseErr(_) => { #panic("expected IoErr") }
      _ => { #panic("expected NotFound") }
    }
  }
  #panic("expected failure")
}
'''

REJECTED = {
    'fallible in local type': (
        'enum E { A }\nfn main() {\n  x: i32!E\n  _ = x\n}\n',
        'only allowed as a function return type',
    ),
    'fallible in param type': (
        'enum E { A }\nfn f(x: i32!E) {}\nfn main() {}\n',
        'only allowed as a function return type',
    ),
    'fallible in struct field': (
        'enum E { A }\nstruct S { x: i32!E }\nfn main() {}\n',
        'only allowed as a function return type',
    ),
    'must use local': (
        'enum E { A }\nfn f() i32!E { return 1 }\nfn main() {\n  x := f()\n  _ = x\n}\n',
        "must be handled with 'try' or 'catch'",
    ),
    'must use stmt': (
        'enum E { A }\nfn f() !E {}\nfn main() {\n  f()\n}\n',
        "must be handled with 'try' or 'catch'",
    ),
    'must use discard': (
        'enum E { A }\nfn f() i32!E { return 1 }\nfn main() {\n  _ = f()\n}\n',
        "must be handled with 'try' or 'catch'",
    ),
    'try in non-fallible': (
        'enum E { A }\nfn f() i32!E { return 1 }\nfn main() {\n  _ = try f()\n}\n',
        'only be used in a fallible function',
    ),
    'try incompatible err': (
        'enum A { X }\nenum B { Y }\nfn f() i32!A { return 1 }\nfn g() i32!B { return try f() }\nfn main() { _ = g() catch 0 }\n',
        'cannot propagate',
    ),
    'try in defer': (
        'enum E { A }\nfn f() !E {}\nfn g() !E {\n  defer { try f() }\n}\nfn main() { g() catch {} }\n',
        'not allowed inside defer',
    ),
    'try direct in defer': (
        'enum E { A }\nfn f() !E {}\nfn g() !E {\n  defer try f()\n}\nfn main() { g() catch {} }\n',
        'invalid deferred statement',
    ),
    'fail in non-fallible': (
        'enum E { A }\nfn main() {\n  fail E.A\n}\n',
        'only allowed in a fallible function',
    ),
    'errdefer in non-fallible': (
        'fn main() {\n  errdefer {}\n}\n',
        'only allowed in a fallible function',
    ),
    'catch non-exiting block': (
        'enum E { A }\nfn f() i32!E { return 1 }\nfn main() {\n  x := f() catch { }\n  _ = x\n}\n',
        'must exit',
    ),
    'non-exhaustive union case': (
        'enum A { X, Y }\nenum B { Z }\nfn g(e: A | B) {\n  case e {\n    A.X => {}\n    B.Z => {}\n  }\n}\nfn main() { g(A.X) }\n',
        'missing A.Y',
    ),
    'unreachable wildcard union case': (
        'enum A { X }\nenum B { Z }\nfn g(e: A | B) {\n  case e {\n    A(_) => {}\n    B(_) => {}\n    _ => {}\n  }\n}\nfn main() { g(A.X) }\n',
        'unreachable',
    ),
    'unqualified variant in union case': (
        'enum A { X }\nenum B { Z }\nfn g(e: A | B) {\n  case e {\n    .X => {}\n    _ => {}\n  }\n}\nfn main() { g(A.X) }\n',
        'qualify the enum name',
    ),
    'main cannot be fallible': (
        'enum E { A }\nfn main() !E {}\n',
        'entry signature',
    ),
    'bare fail in typed err': (
        'enum E { A }\nfn f() !E { fail }\nfn main() { f() catch {} }\n',
        'must fail with an error value',
    ),
    'value fail in untyped err': (
        'enum E { A }\nfn f() ! { fail E.A }\nfn main() { f() catch {} }\n',
        "use bare 'fail'",
    ),
}

WASI = ("const {WASI}=require('node:wasi'),fs=require('fs');(async()=>{const wasi=new WASI({version:'preview1',"
        "returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),"
        "{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})()"
        ".catch(e=>{console.error(e);process.exit(1)});")

with tempfile.TemporaryDirectory(prefix='dyn-phase3-') as tmp:
    root = Path(tmp)
    proj = root / 'app'
    proj.mkdir()
    (proj / 'main.dyn').write_text(PROGRAM)

    # Debug, release, and parallel sema
    for compiler, mode, extra_env in (
        (DYN_DEBUG, '--debug', {}),
        (DYN, '--release', {}),
        (DYN, '--debug', {'DYN_SEMA_PARALLEL': '1'}),
    ):
        out = root / f'app-{Path(compiler).name}-{mode}-{bool(extra_env)}'
        env = {**os.environ, **extra_env}
        subprocess.run(
            [compiler, 'build', str(proj), mode, '--quiet', '--no-cache', '--output', str(out)],
            check=True, timeout=120, env=env,
        )
        subprocess.run([str(out)], check=True, timeout=30)

    # WASM target
    if shutil.which('node'):
        wasm_out = root / 'app.wasm'
        subprocess.run(
            [DYN, 'build', str(proj), '--target', 'wasm32-wasi', '--quiet', '--no-cache', '--output', str(wasm_out)],
            check=True, timeout=120,
        )
        subprocess.run(['node', '--no-warnings', '-e', WASI, str(wasm_out)], check=True, timeout=30)

    # Formatter idempotency
    fmt_dir = root / 'fmt_app'
    fmt_dir.mkdir()
    (fmt_dir / 'main.dyn').write_text(PROGRAM)
    subprocess.run([DYN, 'fmt', str(fmt_dir)], check=True, timeout=30)
    first_fmt = (fmt_dir / 'main.dyn').read_text()
    subprocess.run([DYN, 'fmt', '--check', str(fmt_dir)], check=True, timeout=30)
    assert first_fmt == (fmt_dir / 'main.dyn').read_text()

    # Stdlib T!E integration (std/fs + std/parse composed into IoErr | ParseErr)
    std_proj = root / 'std_app'
    std_proj.mkdir()
    (std_proj / 'main.dyn').write_text(STDLIB_PROGRAM)
    std_out = root / 'std_app_bin'
    subprocess.run(
        [DYN, 'build', str(std_proj), '--quiet', '--no-cache', '--output', str(std_out)],
        check=True, timeout=120,
    )
    subprocess.run([str(std_out)], check=True, timeout=30)

    # Negative diagnostics
    for name, (src, expected) in REJECTED.items():
        d = root / ('neg-' + name.replace(' ', '-'))
        d.mkdir()
        (d / 'main.dyn').write_text(src)
        r = subprocess.run([DYN, 'check', str(d)], capture_output=True, text=True, timeout=30)
        assert r.returncode != 0 and expected in r.stderr, (name, expected, r.stderr)

print('PASS Phase 3 error handling (T!E, A | B, try, catch, fail, errdefer)')
