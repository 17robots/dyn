#!/usr/bin/env python3
"""Phase 4 verification: nocopy + #take, shebang, CFG stack-escape, hardened arenas, mem.Ref, --check-lifetimes, --race, dyn test/bench/fuzz."""
import os
from pathlib import Path
import subprocess
import tempfile

DYN = str(Path(os.environ.get("DYN", "build/dyn")).resolve())


def run_cmd(args, cwd=None, timeout=30):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def check_dyn(source, expect_ok=True, expect_err=None, extra_args=()):
    with tempfile.TemporaryDirectory(prefix="dyn-p4-chk-") as d:
        p = Path(d) / "main.dyn"
        p.write_text(source, encoding="utf-8")
        res = run_cmd([DYN, "check", d, "--no-cache", *extra_args])
        if expect_ok:
            assert res.returncode == 0, f"expected ok, got rc={res.returncode}\n{res.stderr}\n---SOURCE---\n{source}"
        else:
            assert res.returncode != 0, f"expected error, succeeded!\n---SOURCE---\n{source}"
            if expect_err:
                assert expect_err in res.stderr, f"expected {expect_err!r} in stderr, got:\n{res.stderr}"


def run_dyn(source, extra_args=(), single_file=False, expect_rc=0):
    with tempfile.TemporaryDirectory(prefix="dyn-p4-run-") as d:
        p = Path(d) / "main.dyn"
        p.write_text(source, encoding="utf-8")
        target = str(p) if single_file else d
        res = run_cmd([DYN, "run", target, "--no-cache", *extra_args])
        if expect_rc is not None:
            assert res.returncode == expect_rc, (
                f"expected rc={expect_rc}, got {res.returncode}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
            )
        return res


# 1. Shebang support in single-file scripting + dyn fmt
shebang_src = """#!/usr/bin/env dyn run
use "std/io"

fn main() {
  io.println("shebang-ok")
}
"""
res = run_dyn(shebang_src, single_file=True, expect_rc=0)
assert "shebang-ok" in res.stdout, res.stdout
with tempfile.TemporaryDirectory(prefix="dyn-p4-fmt-") as d:
    sp = Path(d) / "script.dyn"
    sp.write_text(shebang_src, encoding="utf-8")
    f = run_cmd([DYN, "fmt", str(sp)])
    assert f.returncode == 0, f.stderr
    assert sp.read_text(encoding="utf-8").startswith("#!/usr/bin/env dyn run\n")

# 2. nocopy struct + #take(&x) with ZERO std imports
nocopy_runtime_src = """
nocopy struct Handle {
  fd: i32 = -1,
  tag: u32 = 7,
}

nocopy struct Box<T> {
  inner: T,
}

struct Wrapper {
  h: Handle,
}

enum MaybeHandle {
  Empty,
  Full(Handle),
}

fn open_handle(id: i32) Handle {
  return Handle{ fd: id, tag: 99 }
}

fn inspect(h: *const Handle) i32 {
  return h.fd
}

fn consume(h: Handle) i32 {
  return h.fd + #cast(i32, h.tag)
}

fn close_handle(h: *Handle) {
  h.fd = -1
}

fn main() {
  // Basic creation, borrow, #take reset-to-defaults, and re-open
  h1 := open_handle(42)
  if inspect(&h1) != 42 { #panic("inspect failed") }
  h2 := #take(&h1)
  if h1.fd != -1 || h1.tag != 7 { #panic("#take did not reset to defaults") }
  if h2.fd != 42 || h2.tag != 99 { #panic("#take did not transfer value") }

  // Reassign h1 after take, then move into function
  h1 = open_handle(10)
  if consume(#take(&h1)) != 109 { #panic("consume #take failed") }
  if h1.fd != -1 { #panic("h1 not reset after consume") }

  // Generic nocopy struct
  b1 := Box<Handle>{ inner: #take(&h2) }
  if h2.fd != -1 { #panic("h2 not reset") }
  b2 := #take(&b1)
  if b1.inner.fd != -1 || b2.inner.fd != 42 { #panic("generic nocopy take failed") }

  // Array pointer for-in over nocopy elements
  arr: [2]Handle = [open_handle(1), open_handle(2)]
  sum: i32 = 0
  for *item in arr {
    sum += item.fd
    close_handle(item)
  }
  if sum != 3 || arr[0].fd != -1 || arr[1].fd != -1 { #panic("for *item failed") }

  // Enum pointer case binding over nocopy payload
  mh := MaybeHandle.Full(open_handle(55))
  case mh {
    .Full(*fh) => {
      if fh.fd != 55 { #panic("case *fh failed") }
      fh.fd = 66
    }
    .Empty => { #panic("unexpected empty") }
  }
  case mh {
    .Full(*fh) => {
      if fh.fd != 66 { #panic("case *fh mutation lost") }
    }
    .Empty => {}
  }

  // nocopy contextual keyword still allowed as variable name
  nocopy: i32 = 123
  if nocopy != 123 { #panic("contextual nocopy variable failed") }
}
"""
run_dyn(nocopy_runtime_src, expect_rc=0)
run_dyn(nocopy_runtime_src, extra_args=("--release",), expect_rc=0)

# Negative nocopy tests
nocopy_negatives = [
    ("nocopy struct F { fd: i32 }\nfn main() { a := F{ fd: 1 }\n b := a\n _ = b }", "cannot copy nocopy type"),
    ("nocopy struct F { fd: i32 }\nfn main() { a := F{ fd: 1 }\n b: F\n b = a\n _ = b }", "cannot copy nocopy type"),
    ("nocopy struct F { fd: i32 }\nfn use_it(x: F) { _ = x }\nfn main() { a := F{ fd: 1 }\n use_it(a) }", "cannot copy nocopy type"),
    ("nocopy struct F { fd: i32 }\nfn ret_it() F { a := F{ fd: 1 }\n return a }\nfn main() { _ = ret_it() }", "cannot copy nocopy type"),
    ("nocopy struct F { fd: i32 }\nstruct W { f: F }\nfn main() { w := W{ f: F{ fd: 1 } }\n w2 := w\n _ = w2 }", "cannot copy nocopy type"),
    ("nocopy struct F { fd: i32 }\nfn main() { arr: [1]F = [F{ fd: 1 }]\n for item in arr { _ = item } }", "cannot copy nocopy type"),
    ("nocopy struct F { fd: i32 }\nenum E { A(F), B }\nfn main() { e := E.A(F{ fd: 1 })\n case e { .A(x) => { _ = x }\n .B => {} } }", "cannot copy nocopy type"),
    ("nocopy struct F { fd: i32 }\nfn bad(p: *const F) F { return #take(p) }\nfn main() {}", "#take requires a mutable pointer"),
    ("use \"std/mem\"\nfn main() { a := mem.arena_alloc(4096)\n defer mem.arena_release(a)\n b := a.*\n _ = b }", "cannot copy nocopy type"),
]
for src, msg in nocopy_negatives:
    check_dyn(src, expect_ok=False, expect_err=msg)

# 3. CFG stack-escape checking in lifetime.h
cfg_escape_negatives = [
    # Escape through if branch
    ("fn bad(c: bool, inp: *i32) *i32 { x: i32 = 1\n p := inp\n if c { p = &x }\n return p }\nfn main() {}", "borrows function-local"),
    # Escape surviving helper call (p not address-taken)
    ("fn noop() {}\nfn bad() *i32 { x: i32 = 1\n p := &x\n noop()\n return p }\nfn main() {}", "borrows function-local"),
    # Escape across for loop
    ("fn bad(n: i32, inp: *i32) *i32 { x: i32 = 1\n p := inp\n i: i32 = 0\n for i < n { p = &x\n i += 1 }\n return p }\nfn main() {}", "borrows function-local"),
    # Escape through break out of loop
    ("fn bad(inp: *i32) *i32 { x: i32 = 1\n p := inp\n for true { p = &x\n break }\n return p }\nfn main() {}", "borrows function-local"),
    # Escape through case arm
    ("fn bad(k: i32, inp: *i32) *i32 { x: i32 = 1\n p := inp\n case k { 1 => { p = &x }\n _ => {} }\n return p }\nfn main() {}", "borrows function-local"),
    # Escape into out-param inside branch
    ("fn bad(c: bool, out: **i32) { x: i32 = 1\n p := &x\n if c { out.* = p } }\nfn main() {}", "outlives the function"),
]
for src, msg in cfg_escape_negatives:
    check_dyn(src, expect_ok=False, expect_err=msg)

# Valid CFG cases that must NOT false-positive
cfg_escape_positives = [
    "fn good(c: bool, inp: *i32) *i32 { x: i32 = 1\n p := &x\n if c { return inp }\n p = inp\n return p }\nfn main() {}",
    "fn good(c: bool, inp: *i32) *i32 { x: i32 = 1\n p := &x\n if c { p = inp } else { p = inp }\n return p }\nfn main() {}",
]
for src in cfg_escape_positives:
    check_dyn(src, expect_ok=True)

# 4. Hardened Arenas: mem.Ref<T>, PROT_NONE trapping, thread-affinity, --check-lifetimes
ref_valid_src = """
use "std/mem"

struct Node { val: i64 }

fn main() {
  a := mem.arena_alloc(65536)
  defer mem.arena_release(a)
  mark := mem.arena_mark(a)
  r := mem.push_ref<Node>(a)
  if !mem.ref_valid(r) { #panic("expected valid ref") }
  mem.deref(r).val = 777
  if mem.deref(r).val != 777 { #panic("wrong value") }
  mem.arena_rewind(a, mark)
  if mem.ref_valid(r) { #panic("expected invalid ref after rewind") }
}
"""
run_dyn(ref_valid_src, expect_rc=0)

ref_dangling_src = """
use "std/mem"
fn main() {
  a := mem.arena_alloc(65536)
  defer mem.arena_release(a)
  mark := mem.arena_mark(a)
  r := mem.push_ref<i64>(a)
  mem.arena_rewind(a, mark)
  _ = mem.deref(r).*
}
"""
res = run_dyn(ref_dangling_src, expect_rc=101)
assert "dangling mem.Ref" in res.stderr, res.stderr

# PROT_NONE trapping on rewound OS pages + restore on subsequent push
prot_restore_src = """
use "std/mem"
fn main() {
  a := mem.arena_alloc(65536)
  defer mem.arena_release(a)
  mem.arena_enable_protect(a)
  mark := mem.arena_mark(a)
  b1 := mem.push_bytes(a, 16384)
  b1[8192] = 42
  mem.arena_rewind(a, mark)
  // Re-allocating must restore PROT_READ|PROT_WRITE cleanly
  b2 := mem.push_bytes(a, 16384)
  b2[8192] = 99
  if b2[8192] != 99 { #panic("restore failed") }
}
"""
run_dyn(prot_restore_src, expect_rc=0)
run_dyn(prot_restore_src, extra_args=("--check-lifetimes",), expect_rc=0)

prot_trap_src = """
use "std/mem"
fn main() {
  a := mem.arena_alloc(65536)
  defer mem.arena_release(a)
  mark := mem.arena_mark(a)
  b1 := mem.push_bytes(a, 16384)
  b1[8192] = 42
  mem.arena_rewind(a, mark)
  // Accessing rewound page under --check-lifetimes must fault!
  if b1[8192] == 42 { #panic("should have faulted") }
}
"""
res = run_dyn(prot_trap_src, extra_args=("--check-lifetimes",), expect_rc=None)
assert res.returncode != 0, "expected PROT_NONE fault under --check-lifetimes"
assert "should have faulted" not in res.stderr, res.stderr

# Thread-affinity check + arena_transfer
thread_affinity_bad = """
use "std/mem"
use "std/thread"
use "std/fail"

struct Ctx { arena: *mem.Arena }

fn worker(ctx: *Ctx) isize {
  _ = mem.push<u64>(ctx.arena)
  return 0
}

fn main() {
  a := mem.arena_alloc(65536)
  defer mem.arena_release(a)
  ta := mem.arena_alloc(65536)
  defer mem.arena_release(ta)
  ctx := Ctx{ arena: a }
  st := fail.Status{}
  t := thread.spawn_with_size(ta, &st, 65536, worker, &ctx)
  thread.join(&st, t)
}
"""
res = run_dyn(thread_affinity_bad, extra_args=("--check-lifetimes",), expect_rc=101)
assert "other than its owner" in res.stderr, res.stderr

thread_affinity_transfer = """
use "std/mem"
use "std/thread"
use "std/fail"

struct Ctx { arena: *mem.Arena }

fn worker(ctx: *Ctx) isize {
  mem.arena_transfer(ctx.arena)
  p := mem.push<u64>(ctx.arena)
  p.* = 123
  return 0
}

fn main() {
  a := mem.arena_alloc(65536)
  defer mem.arena_release(a)
  ta := mem.arena_alloc(65536)
  defer mem.arena_release(ta)
  ctx := Ctx{ arena: a }
  st := fail.Status{}
  t := thread.spawn_with_size(ta, &st, 65536, worker, &ctx)
  thread.join(&st, t)
  mem.arena_transfer(a)
  _ = mem.push<u64>(a)
}
"""
run_dyn(thread_affinity_transfer, extra_args=("--check-lifetimes",), expect_rc=0)

# 5. Dynamic Data-Race Detector (--race)
race_bad_src = """
use "std/mem"
use "std/thread"
use "std/fail"

shared_counter: u64 = 0

struct Ctx { dummy: u64 }

fn racer(ctx: *Ctx) isize {
  _ = ctx
  for i in 0..20000 {
    shared_counter = shared_counter + 1
  }
  return 0
}

fn main() {
  ta := mem.arena_alloc(65536)
  defer mem.arena_release(ta)
  ctx := Ctx{ dummy: 0 }
  st := fail.Status{}
  t := thread.spawn_with_size(ta, &st, 65536, racer, &ctx)
  for i in 0..20000 {
    shared_counter = shared_counter + 1
  }
  thread.join(&st, t)
}
"""
res = run_dyn(race_bad_src, extra_args=("--race",), expect_rc=101)
assert "DATA RACE" in res.stderr, res.stderr

race_good_src = """
use "std/mem"
use "std/thread"
use "std/sync"
use "std/fail"

shared_counter: u64 = 0
mu: sync.Mutex

struct Ctx { dummy: u64 }

fn safe_worker(ctx: *Ctx) isize {
  _ = ctx
  for i in 0..200 {
    sync.lock(&mu)
    shared_counter = shared_counter + 1
    sync.unlock(&mu)
  }
  return 0
}

fn main() {
  mu = sync.mutex()
  ta := mem.arena_alloc(65536)
  defer mem.arena_release(ta)
  ctx := Ctx{ dummy: 0 }
  st := fail.Status{}
  t := thread.spawn_with_size(ta, &st, 65536, safe_worker, &ctx)
  for i in 0..200 {
    sync.lock(&mu)
    shared_counter = shared_counter + 1
    sync.unlock(&mu)
  }
  thread.join(&st, t)
  if shared_counter != 400 { #panic("wrong count") }
}
"""
run_dyn(race_good_src, extra_args=("--race",), expect_rc=0)

# 6. *_test.dyn exclusion + dyn test / dyn bench / dyn fuzz
with tempfile.TemporaryDirectory(prefix="dyn-p4-suite-") as d:
    root = Path(d)
    (root / "main.dyn").write_text("""
use "std/io"

pub fn add(a, b: i64) i64 {
  return a + b
}

fn main() {
  io.println("prod-main")
}
""", encoding="utf-8")
    (root / "math_test.dyn").write_text("""
enum MathErr { Bad }

fn checked_add(a, b: i64) i64!MathErr {
  if a < 0 { fail .Bad }
  return a + b
}

fn test_add_basic() {
  if add(2, 3) != 5 { #panic("add failed") }
}

fn test_add_fallible() !MathErr {
  v := try checked_add(4, 5)
  if v != 9 { fail .Bad }
}

fn test_only_helper() i64 {
  // Referencing a symbol that does not break prod builds because *_test.dyn is excluded from normal builds
  return add(10, 20)
}

fn bench_add() {
  _ = add(123, 456)
}

fn fuzz_parser(data: []const u8) {
  acc: u64 = 0
  for b in data {
    acc += #cast(u64, b)
  }
  _ = acc
}
""", encoding="utf-8")

    # Normal build/run must ignore *_test.dyn cleanly
    prod = run_cmd([DYN, "run", d, "--no-cache"])
    assert prod.returncode == 0, prod.stderr
    assert "prod-main" in prod.stdout, prod.stdout

    # dyn test runs both void and fallible tests
    t = run_cmd([DYN, "test", d])
    assert t.returncode == 0, f"dyn test failed:\n{t.stdout}\n{t.stderr}"
    assert "PASS test_add_basic" in t.stdout, t.stdout
    assert "PASS test_add_fallible" in t.stdout, t.stdout
    assert "2 passed; 0 failed" in t.stdout, t.stdout

    # dyn test --filter
    tf = run_cmd([DYN, "test", d, "--filter", "fallible"])
    assert tf.returncode == 0, tf.stderr
    assert "PASS test_add_fallible" in tf.stdout and "test_add_basic" not in tf.stdout, tf.stdout

    # dyn test with --check-lifetimes and --race
    tl = run_cmd([DYN, "test", d, "--check-lifetimes", "--race"])
    assert tl.returncode == 0, f"dyn test --check-lifetimes --race failed:\n{tl.stdout}\n{tl.stderr}"

    # dyn bench
    b = run_cmd([DYN, "bench", d, "--iterations", "50"])
    assert b.returncode == 0, f"dyn bench failed:\n{b.stdout}\n{b.stderr}"
    assert "BENCH bench_add:" in b.stdout and "median=" in b.stdout and "p95=" in b.stdout, b.stdout

    # dyn fuzz
    fz = run_cmd([DYN, "fuzz", d, "--iterations", "50"])
    assert fz.returncode == 0, f"dyn fuzz failed:\n{fz.stdout}\n{fz.stderr}"
    assert "FUZZ fuzz_parser: OK (50 iterations)" in fz.stdout, fz.stdout

    # Failing fallible test exits non-zero
    (root / "fail_test.dyn").write_text("""
enum FailErr { Boom }
fn test_fail_case() !FailErr { fail .Boom }
""", encoding="utf-8")
    tfail = run_cmd([DYN, "test", d, "--filter", "fail_case"])
    assert tfail.returncode != 0, tfail.stdout
    assert "FAIL test_fail_case" in tfail.stdout, tfail.stdout

print("PASS Phase 4 safety & tooling (shebang, nocopy/#take, CFG lifetime, hardened arenas, --check-lifetimes, --race, dyn test/bench/fuzz)")
