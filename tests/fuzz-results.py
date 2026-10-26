#!/usr/bin/env python3
"""std/testing fuzz: corpus replay, mutation finds planted failures, shrinking, reproducibility, Source decoding."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/testing" testing
use "std/bytes" bytes

fn no_fuzz(context: rawptr, input: []const u8) bool {
  _ = context
  return bytes.find(input, "FUZZ") == #len(input)
}

fn decoded(context: rawptr, input: []const u8) bool {
  _ = context
  source := testing.source(input)
  kind := testing.take_below(&source, 3)
  size := testing.take_u8(&source)
  return !(kind == 2 && size == 200 && testing.remaining(&source) >= 2)
}

fn always(context: rawptr, input: []const u8) bool {
  _ = context
  _ = input
  return true
}

// Fails on inputs of three or more bytes whose middle byte is at least 128.
fn short_or_plain(context: rawptr, input: []const u8) bool {
  _ = context
  return #len(input) < 3 || input[1] < 128
}

fn check(ok: bool) {
  if !ok {
    #panic("fuzz")
  }
}

fn main() {
  work: [512]u8 = []
  corpus: [2][]const u8 = ["hello FUZ", "abc"]
  found := testing.fuzz(testing.FuzzOptions{ seed: 7, cases: 200000, shrink_checks: 10000 }, corpus[..], work[..], no_fuzz, nil)
  check(!found.passed && bytes.equal(found.example, "FUZZ") && found.corpus_entry == 2)
  again := testing.fuzz(testing.FuzzOptions{ seed: 7, cases: 200000, shrink_checks: 10000 }, corpus[..], work[..], no_fuzz, nil)
  check(again.iteration == found.iteration)
  replay: [1][]const u8 = ["xxFUZZyy"]
  replayed := testing.fuzz(testing.FuzzOptions{ seed: 1, cases: 10, shrink_checks: 1000 }, replay[..], work[..], no_fuzz, nil)
  check(!replayed.passed && replayed.corpus_entry == 0 && replayed.iteration == 0 && bytes.equal(replayed.example, "FUZZ"))
  structured := testing.fuzz(testing.FuzzOptions{ seed: 3, cases: 200000, shrink_checks: 10000 }, corpus[..0], work[..], decoded, nil)
  check(!structured.passed && #len(structured.example) == 11)
  clean := testing.fuzz(testing.FuzzOptions{ seed: 3, cases: 5000, shrink_checks: 10 }, corpus[..], work[..], always, nil)
  check(clean.passed && clean.iteration == 5002)
  property := testing.check_property(testing.PropertyOptions{ seed: 9, cases: 100000, shrink_checks: 10000 }, work[..], short_or_plain, nil)
  check(!property.passed && #len(property.example) == 3 && property.example[0] == 0 && property.example[2] == 0)
  source := testing.source("\x01\x02\x03\x04\x05")
  check(testing.take_u32(&source) == 0x04030201 && testing.take_u8(&source) == 5 && testing.take_u64(&source) == 0)
  check(testing.remaining(&source) == 0 && #len(testing.take_rest(&source)) == 0)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-fuzz-results-') as directory:
    project = Path(directory)
    (project / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        output = project / 'program'
        subprocess.run([DYN, 'build', str(project), mode, '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=300)
        subprocess.run([str(output)], check=True, timeout=300)
print('PASS fuzz results: check_property shrinking, corpus replay, mutation, splice, shrinking to minimal inputs, reproducible runs, Source (debug/release)')
