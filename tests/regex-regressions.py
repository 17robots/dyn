#!/usr/bin/env python3
"""Counted repetition, capture priority, and bounded regex execution regressions."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build' / ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve()
SOURCE = r'''use "std/text/regex" regex
use "std/mem" memory
use "std/io" io
fn require(ok: bool, message: []const u8) { if !ok { #panic(message) } }
fn check(pattern: []const u8, text: []const u8, expected: usize, ok: bool) {
  code: [1024]regex.Instruction = []
  tokens: [2048]regex.Instruction = []
  scratch: [2048]usize = []
  captures: [4]regex.Match = []
  workspace: [32768]usize = []
  program := regex.compile(pattern, code[..], tokens[..], scratch[..])
  require(program.ok, "compile")
  result := regex.find_compiled_workspace(program, text, captures[..], workspace[..])
  require(result.error == regex.MatchError.None && result.ok == ok && (!ok || result.end == expected), pattern)
}
fn main() {
  require(regex.find("^a{1,}$", "aaaaaaaaaaaaaaaa").end == 16, "direct open count")
  require(regex.find("^a{0,}$", "aaaaaaaaaaaaaaaa").end == 16, "direct zero open count")
  require(regex.find("a{4}", "aaaaaaaa").end == 4, "direct exact count")
  require(regex.find("^a{20,}$", "aaaaaaaaaaaaaaaaaaaaaaaa").ok, "minimum longer than pattern")
  check("a{4}", "aaaaaaaa", 4, true)
  check("a{1,6}", "aaaaaaaa", 6, true)
  check("^a{1,}$", "aaaaaaaaaaaaaaaa", 16, true)
  check("^a{0,}$", "aaaaaaaaaaaaaaaa", 16, true)
  check("^a{20,}$", "aaaaaaaaaaaaaaaaaaaaaaaa", 24, true)
  check("^a{0}$", "", 0, true)
  check("^a{0,2}$", "aaa", 0, false)
  check("(a|aa)", "aa", 1, true)
  check("(aa|a)", "aa", 2, true)
  check("(a?)*b", "aaab", 4, true)
  check("(a*)*b", "aaab", 4, true)
  check("a*ab", "aaaab", 5, true)
  check("^a|b", "xb", 2, true)
  code: [1024]regex.Instruction = []
  tokens: [2048]regex.Instruction = []
  scratch: [2048]usize = []
  captures: [2]regex.Match = []
  invalid := regex.compile("a{18446744073709551616}", code[..], tokens[..], scratch[..])
  require(!invalid.ok && invalid.error == regex.CompileError.Syntax, "count overflow")
  invalid = regex.compile("a{1,18446744073709551616}", code[..], tokens[..], scratch[..])
  require(!invalid.ok && invalid.error == regex.CompileError.Syntax, "maximum overflow")
  program := regex.compile("(a)*", code[..], tokens[..], scratch[..])
  owned := memory.arena_create(100000)
  input := memory.arena_push(&owned.arena, 100000, 1)[..100000]
  for i in 0..#len(input) { input[i] = 'a' }
  result := regex.find_compiled(program, input, captures[..])
  require(result.ok && result.end == 100000, "long repetition")
  require(captures[0].ok && captures[0].start == 99999 && captures[0].end == 100000, "last capture")
  _ = memory.arena_release(&owned.arena)
  program = regex.compile("(a*)a", code[..], tokens[..], scratch[..])
  result = regex.find_compiled(program, "aaaa", captures[..])
  require(result.ok && result.end == 4 && captures[0].end == 3, "greedy backtracking capture")
  program = regex.compile("(a)b|(a)c", code[..], tokens[..], scratch[..])
  result = regex.find_compiled(program, "ac", captures[..])
  require(result.ok && !captures[0].ok && captures[1].ok && captures[1].end == 1, "failed branch capture rollback")
  program = regex.compile("(a){200}", code[..], tokens[..], scratch[..])
  needed := regex.match_workspace_size(program, 2)
  require(needed > 4096 && needed <= 32768, "large workspace requirement")
  workspace: [32768]usize = []
  long_input: [200]u8 = []
  for i in 0..200 { long_input[i] = 'a' }
  result = regex.find_compiled_workspace(program, long_input[..], captures[..], workspace[..needed])
  require(result.ok && result.end == 200 && captures[0].start == 199, "large caller workspace")
  result = regex.find_compiled(program, long_input[..], captures[..])
  require(!result.ok && result.error == regex.MatchError.Capacity && !captures[0].ok, "bounded compatibility workspace")
  result = regex.find_compiled_workspace(program, "a", captures[..], workspace[..needed - 1])
  require(!result.ok && result.error == regex.MatchError.Capacity && !captures[0].ok && !captures[1].ok, "short workspace")
  program = regex.compile("(a)*", code[..], tokens[..], scratch[..])
  needed = regex.match_workspace_size(program, 2)
  result = regex.find_compiled_workspace(program, "aaa", captures[..], workspace[..needed])
  require(result.ok && result.end == 3 && captures[0].start == 2, "exact workspace")
  _ = io.println(io.stdout(), "regex passed")
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-regex-') as temporary:
    work = Path(temporary)
    project = work / 'project'
    project.mkdir()
    (project / 'main.dyn').write_text(SOURCE, encoding='utf-8')
    for mode in ('--debug', '--release'):
        output = work / ('regex.exe' if os.name == 'nt' else 'regex')
        subprocess.run([str(DYN), 'build', str(project), '--no-cache', '--quiet', '--output', str(output), mode], cwd=work, check=True, timeout=120)
        result = subprocess.run([str(output)], cwd=work, capture_output=True, timeout=30)
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert result.stdout == b'regex passed\n', result.stdout
print('PASS regex counts, captures, workspace capacity, and long repetition (debug/release)')
