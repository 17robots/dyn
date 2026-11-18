#!/usr/bin/env python3
"""Independent arena-owned flags parsing contract, debug and release."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/fail"
use "std/mem" mem
use "std/flags" flags
use "std/strings" strings
use "std/bytes"
fn check(ok: bool, message: []const u8) { if !ok { #panic(message) } }
struct Outcome { value: flags.Parsed, failure: fail.Failure }
fn parse(arena: *mem.Arena, options: []const flags.Option, arguments: [][]const u8) Outcome {
  status: fail.Status
  value := flags.parse(arena, &status, options, arguments)
  return Outcome{ value: value, failure: status.failure }
}
fn message(outcome: *const Outcome, text: []const u8) bool {
  return outcome.failure.kind == fail.Kind.InvalidInput && bytes.equal(fail.message_text(&outcome.failure), text)
}
fn main() {
  zero_result := flags.Parsed{}
  check(#len(zero_result.values) == 0 && #len(zero_result.positionals) == 0, "zero result")
  backing: [4096]u8
  arena := mem.arena_from_buffer(backing[..])
  prefix := mem.push_array(u8, arena, 3)
  prefix[0] = 91
  choices: [2][]const u8 = ["fast", "slow"]
  options: [5]flags.Option = [flags.bool_option("verbose", 'v'), flags.integer_option("count", 'n'), flags.float_option("ratio", 'r'), flags.choice_option("mode", 'm', choices[..]), flags.string_option("output", 'o')]
  options[3].default_value = "slow"
  output: [3]u8 = ['o', 'u', 't']
  positional: [3]u8 = ['s', 'r', 'c']
  args: [10][]const u8 = ["first", "-vvn-42", "--ratio=1.25e2", "-o", output[..], positional[..], "--count", "7", "--", "-v"]
  parsed := parse(arena, options[..], args[..])
  check(parsed.failure.kind == fail.Kind.Ok, "success")
  values := parsed.value.values
  check(#len(values) == 5 && values[0].occurrences == 2 && values[1].occurrences == 2, "occurrences")
  check(bytes.equal(values[1].text, "7") && bytes.equal(values[2].text, "1.25e2"), "typed/last wins")
  check(!values[3].found && bytes.equal(values[3].text, "slow"), "default")
  check(#len(parsed.value.positionals) == 3 && bytes.equal(parsed.value.positionals[0], "first") && bytes.equal(parsed.value.positionals[2], "-v"), "positional order/terminator")
  start := #cast(usize, &backing[0])
  check(#cast(usize, &values[0]) >= start && #cast(usize, &values[4]) < start + #len(backing), "values owned by fixed arena")
  check(#cast(usize, &parsed.value.positionals[0]) >= start && #cast(usize, &parsed.value.positionals[2]) < start + #len(backing), "positionals owned by fixed arena")
  output[0] = 'O'
  positional[0] = 'S'
  check(values[4].text[0] == 'O' && parsed.value.positionals[1][0] == 'S', "borrowed strings")
  mark := mem.arena_mark(arena)
  bad: [1][]const u8 = ["--unknown"]
  failure := parse(arena, options[..], bad[..])
  check(message(&failure, "unknown option") && failure.failure.offset == 0 && bytes.equal(fail.path_text(&failure.failure), bad[0]), "unknown diagnostic")
  check(#len(failure.value.values) == 0 && #len(failure.value.positionals) == 0 && mem.arena_mark(arena) == mark && prefix[0] == 91, "failure rollback")
  choice_args: [2][]const u8 = ["-m", "fast"]
  choice_result := parse(arena, options[..], choice_args[..])
  check(choice_result.failure.kind == fail.Kind.Ok && choice_result.value.values[3].found && bytes.equal(choice_result.value.values[3].text, "fast"), "explicit choice")
  mem.arena_rewind(arena, mark)
  bad[0] = "-n"
  missing := parse(arena, options[..], bad[..])
  check(message(&missing, "missing value"), "missing")
  bad[0] = "--verbose=yes"
  unexpected := parse(arena, options[..], bad[..])
  check(message(&unexpected, "unexpected value"), "bool value")
  for invalid in ["-nnope", "--ratio=bad", "--mode=other"] {
    bad[0] = invalid
    result := parse(arena, options[..], bad[..])
    check(message(&result, "invalid value") && result.failure.offset == 1, "invalid typed")
  }
  empty: [0][]const u8
  options[3].default_value = "invalid"
  invalid_default := parse(arena, options[..], empty[..])
  check(message(&invalid_default, "invalid value"), "invalid default")
  options[3].default_value = "fast"
  options[4].required = true
  required := parse(arena, options[..], empty[..])
  check(message(&required, "missing required option"), "required")
  check(mem.arena_mark(arena) == mark, "all failures rewind")
  none: [0]flags.Option
  tiny: [mem.ArenaBufferOverhead]u8
  tiny_pad := (16-(#cast(usize,&tiny[0])&15))&15
  zero := mem.arena_from_buffer(tiny[tiny_pad..tiny_pad+mem.ArenaHeader])
  result := parse(zero, none[..], empty[..])
  check(result.failure.kind == fail.Kind.Ok && #len(result.value.values) == 0 && #len(result.value.positionals) == 0 && mem.arena_used(zero) == 0, "empty")
}
'''
PANIC = '''use "std/mem" mem
use "std/fail"
use "std/flags" flags
fn main() {
  status: fail.Status
  storage: [1+mem.ArenaBufferOverhead]u8
  pad := (16-(#cast(usize,&storage[0])&15))&15
  arena := mem.arena_from_buffer(storage[pad..pad+mem.ArenaHeader+1])
  options: [1]flags.Option = [flags.bool_option("verbose", 'v')]
  arguments: [0][]const u8
  _ = flags.parse(arena, &status, options[..], arguments[..])
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-flags-arena-') as temporary:
    project = Path(temporary)
    source = project / 'main.dyn'
    output = project / 'out'
    for release in (False, True):
        for body, panic in ((SOURCE, False), (PANIC, True),
                            (PANIC.replace("options: [1]flags.Option = [flags.bool_option(\"verbose\", 'v')]", 'options: [0]flags.Option').replace('arguments: [0][]const u8', 'arguments: [1][]const u8 = ["file"]'), True)):
            source.write_text(body)
            subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output),
                            *(['--release'] if release else [])], cwd=ROOT, check=True, timeout=120)
            result = subprocess.run([str(output)], capture_output=True, text=True, timeout=20)
            if panic:
                assert result.returncode == 101 and 'arena exhausted' in result.stderr, result.stderr
            else:
                assert result.returncode == 0, result.stderr
print('PASS flags arena: typed/default/required/order/borrowing/ownership/rollback/exhaustion (debug/release)')
