#!/usr/bin/env python3
"""Metadesk parsing: labels, groups, tags, nil-node lookups and errors, debug/release."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/bytes"
use "std/encoding/mdesk"
use "std/errors"
use "std/mem"

fn expect(condition: bool, message: []const u8) {
  if !condition {
    #panic(message)
  }
}

fn fails(arena: *mem.Arena, source: []const u8, error: mdesk.ErrorKind, offset: usize) {
  result := mdesk.parse(arena, source)
  expect(!result.ok && result.kind == errors.Kind.InvalidInput && result.error == 0 && result.detail == error && result.offset == offset, source)
  expect(result.root == &mdesk.nil_node && mdesk.is_nil(result.root), "stub root on failure")
}

fn main() {
  arena := mem.arena_create(mem.MiB)
  defer mem.arena_release(&arena)
  source := #load("types.mdesk")
  parsed := mdesk.parse(&arena, source)
  expect(parsed.ok, "parse")
  root := parsed.root
  expect(root.kind == mdesk.Kind.Root && mdesk.child_count(root) == 6, "root children")

  types := mdesk.child(root, "Types")
  expect(types.kind == mdesk.Kind.Main && types.group == '{' && mdesk.child_count(types) == 3, "Types group")
  table := mdesk.tag(types, "table")
  expect(mdesk.has_tag(types, "table") && table.group == '(', "table tag")
  expect(bytes.equal(mdesk.child_at(table, 1).string, "size"), "tag arguments")
  row := mdesk.child_at(types, 1)
  expect(row.label == mdesk.Label.None && row.group == '{', "unlabeled row")
  expect(bytes.equal(mdesk.child_at(row, 0).string, "Double"), "row name")
  expect(mdesk.child_at(row, 1).label == mdesk.Label.Number, "row size")
  half := mdesk.child_at(types, 2)
  expect(mdesk.has_tag(half, "hidden") && bytes.equal(mdesk.child_at(half, 1).string, "2.5"), "tagged row")

  title := mdesk.child(root, "title")
  expect(bytes.equal(mdesk.child_at(title, 0).string, "Hello, world"), "string")
  expect(bytes.equal(mdesk.child_at(mdesk.child(root, "path"), 0).string, "a \"b\" c"), "triple string")
  empty_string := mdesk.child_at(mdesk.child(root, "empty"), 0)
  expect(empty_string.label == mdesk.Label.String && #len(empty_string.string) == 0, "empty string")
  nested := mdesk.parse(&arena, "op: + version: 1.2.3 a: b: c")
  expect(nested.ok && mdesk.child_count(nested.root) == 3, "chained children")
  expect(mdesk.child_at(mdesk.child(nested.root, "op"), 0).label == mdesk.Label.Symbol, "symbol")
  expect(bytes.equal(mdesk.child(mdesk.child(mdesk.child(nested.root, "a"), "b"), "c").string, "c"), "a: b: c")

  missing := mdesk.child(mdesk.child_at(mdesk.child(root, "Nope"), 4), "deeper")
  expect(mdesk.is_nil(missing) && missing == mdesk.empty(), "nil chain")
  expect(#len(missing.string) == 0 && mdesk.child_count(missing) == 0 && !mdesk.has_tag(missing, "x"), "nil reads")
  expect(mdesk.line_of(source, types.offset) == 3, "line_of")

  fails(&arena, "a: {b c", mdesk.ErrorKind.Unclosed, 3)
  fails(&arena, "a }", mdesk.ErrorKind.Unexpected, 2)
  fails(&arena, "a: \"open", mdesk.ErrorKind.UnterminatedString, 3)
  fails(&arena, "/* open", mdesk.ErrorKind.UnterminatedComment, 0)
  fails(&arena, "@ x", mdesk.ErrorKind.MissingTagName, 0)
  fails(&arena, "a:", mdesk.ErrorKind.Unexpected, 2)
}
'''
DATA = """// Sizes of the scalar types.
@table(name, size)
Types: {
  {Float, 4}
  {Double, 8}; @hidden {Half 2.5},
}
/* block */ title: "Hello, world" path: '''a "b" c''' empty: ``
op: + version: 1.2.3
"""

with tempfile.TemporaryDirectory(prefix='dyn-mdesk-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    (project / 'types.mdesk').write_text(DATA)
    for mode in ('--debug', '--release'):
        output = project / mode.strip('-')
        subprocess.run([DYN, 'build', str(project), mode, '--no-cache', '--quiet', '--output', str(output)],
                       cwd=ROOT, check=True, timeout=120)
        subprocess.run([str(output)], check=True, timeout=10)
print('PASS Metadesk labels, groups, tags, nil-node lookups and errors (debug/release)')
