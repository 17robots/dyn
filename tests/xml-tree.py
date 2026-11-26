#!/usr/bin/env python3
"""Bounded XML tree contract checks. Parent: register this script in the std
suite and document xml.parse alongside the XML scanner (these are separate edits).
Run with DYN=/path/to/compiler; both debug and release are checked.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
source = '''use xml "std/encoding/xml"
use mem "std/mem"
use bytes "std/bytes"
fn check(ok: bool) { if !ok { #panic("xml tree contract") } }
// code: 0 parsed, 1 Invalid at offset. A failed parse leaves the nil root.
struct Tree { root: *const xml.Node, offset: usize, code: u8 }
fn parse(arena: *mem.Arena, source: []const u8) Tree {
  root := xml.parse(arena, source) catch err {
    case err {
      .Invalid(at) => { return Tree{ root: &xml.nil_node, offset: at, code: 1 } }
      .TooLarge(at) => { return Tree{ root: &xml.nil_node, offset: at, code: 2 } }
    }
  }
  return Tree{ root: root, offset: 0 }
}
fn main() {
  arena := mem.arena_alloc(0)
  defer { mem.arena_release(arena) }
  zero: xml.Node
  check(xml.is_nil(&zero) && xml.is_nil(nil))
  check(xml.child(nil, "x") == &xml.nil_node && xml.at(nil, 0) == &xml.nil_node && xml.next_sibling(nil) == &xml.nil_node)
  r := parse(arena, "<?xml version='1.0'?>\\n<!--before--><root a='&amp;' b=\\"2\\"><leaf/>raw&amp;<!--hi--><![CDATA[<raw>]]><?pi body  ?></root> ")
  check(r.code == 0 && r.code == 0)
  check(r.root.kind == xml.NodeKind.Document && r.root.parent == nil)
  check(xml.at(r.root, 0).kind == xml.NodeKind.Processing && bytes.equal(xml.at(r.root, 0).text, " version='1.0'"))
  root := xml.child(r.root, "root")
  check(root.parent == r.root && bytes.equal(root.attributes, " a='&amp;' b=\\"2\\""))
  leaf := xml.child(root, "leaf")
  check(leaf == xml.at(root, 0) && leaf.parent == root && leaf.first == nil)
  check(xml.at(root, 1).kind == xml.NodeKind.Text && bytes.equal(xml.at(root, 1).text, "raw&amp;"))
  check(xml.at(root, 2).kind == xml.NodeKind.Comment && bytes.equal(xml.at(root, 2).text, "hi"))
  check(xml.at(root, 3).kind == xml.NodeKind.Cdata && bytes.equal(xml.at(root, 3).text, "<raw>"))
  check(xml.at(root, 4).kind == xml.NodeKind.Processing && root.last == xml.at(root, 4) && bytes.equal(xml.at(root, 4).text, " body  "))
  check(xml.next_sibling(leaf) == xml.at(root, 1) && xml.next_sibling(root.last) == &xml.nil_node)
  check(xml.child(root, "absent") == &xml.nil_node && xml.at(root, 5) == &xml.nil_node)
  check(xml.child(&xml.nil_node, "x") == &xml.nil_node && xml.at(&zero, 0) == &xml.nil_node)
  borrowed: [8]u8 = ['<', 't', '>', 'x', '<', '/', 't', '>']
  borrowed_tree := parse(arena, borrowed[..])
  borrowed_text := xml.at(xml.child(borrowed_tree.root, "t"), 0)
  check(borrowed_tree.code == 0 && #cast(usize, &borrowed_text.text[0]) == #cast(usize, &borrowed[3]))
  borrowed[3] = 'y'
  check(bytes.equal(borrowed_text.text, "y"))
  mark := mem.arena_mark(arena)
'''
bad = [('', 0, 'malformed XML'), ('<a></b>', 3, 'mismatched tag'),
       ('<a/><b/>', 4, 'malformed XML'), ('<a>', 3, 'mismatched tag'),
       ('text<a/>', 0, 'malformed XML'), ('<a/>text', 4, 'malformed XML'),
       ('<!--only-->', 11, 'malformed XML'), ('<a x=bad/>', 0, 'malformed XML'),
       ('<a x="1" x="2"/>', 0, 'malformed XML'), ('<a 1x="a"/>', 0, 'malformed XML'),
       ('<a x="<"/>', 0, 'malformed XML'), ('<a>&unknown;</a>', 3, 'malformed XML'),
       ('<!DOCTYPE a><a/>', 1, 'malformed XML'), ('<![CDATA[x]]><a/>', 0, 'malformed XML'),
       ('<a><!--a--b--></a>', 3, 'malformed XML'), ('<a><!--a---></a>', 3, 'malformed XML'),
       ('<a', 2, 'malformed XML'), ('</a>', 0, 'mismatched tag')]
for value, offset, detail in bad:
    source += f'''  if true {{
    bad := parse(arena, {json.dumps(value)})
    check(bad.code != 0 && bad.root == &xml.nil_node && bad.code == 1 && bad.offset == {offset})
    check(mem.arena_mark(arena) == mark && bytes.equal(root.name, "root"))
    check(xml.child(bad.root, "a") == &xml.nil_node)
  }}
'''
source += '''
  invalid: [8]u8 = ['<', 'a', '>', 255, '<', '/', 'a', '>']
  bad_utf8 := parse(arena, invalid[..])
  check(bad_utf8.code != 0 && bad_utf8.offset == 3 && bad_utf8.code == 1 && bad_utf8.code == 1 && bad_utf8.root == &xml.nil_node)
  check(mem.arena_mark(arena) == mark)
  backing: [4096]u8
  for i in 0..backing.len { backing[i] = 255 }
  fixed := mem.arena_from_buffer(backing[..])
  prefix := mem.push<u8>(fixed)
  prefix.* = 42
  fixed_mark := mem.arena_mark(fixed)
  failed := parse(fixed, "<a><b/></z>")
  check(failed.code != 0 && mem.arena_mark(fixed) == fixed_mark && prefix.* == 42)
  input: [11]u8 = ['<', 'a', ' ', 'x', '=', '"', 'v', '"', '/', '>', ' ']
  owned := parse(fixed, input[..])
  element := xml.child(owned.root, "a")
  check(owned.code == 0 && element.first == nil && element.last == nil && element.next == xml.at(owned.root, 1) && element.text.len == 0)
  check(#cast(usize, owned.root) >= #cast(usize, &backing[0]) && #cast(usize, owned.root) < #cast(usize, &backing[4095]))
  check(#cast(usize, element) >= #cast(usize, &backing[0]) && #cast(usize, element) < #cast(usize, &backing[4095]))
  check(#cast(usize, &element.name[0]) == #cast(usize, &input[1]) && #cast(usize, &element.attributes[0]) == #cast(usize, &input[2]))
  input[1] = 'z'
  input[6] = 'w'
  check(bytes.equal(element.name, "z") && bytes.equal(element.attributes, " x=\\"w\\""))
  deep := mem.push_array<u8>(arena, 70000)
  for i in 0..10000 {
    deep[i * 3] = '<'
    deep[i * 3 + 1] = 'a'
    deep[i * 3 + 2] = '>'
    deep[30000 + i * 4] = '<'
    deep[30001 + i * 4] = '/'
    deep[30002 + i * 4] = 'a'
    deep[30003 + i * 4] = '>'
  }
  nested := parse(arena, deep)
  check(nested.code == 0)
  cursor := nested.root
  for i in 0..10000 { cursor = xml.at(cursor, 0)
    check(cursor.kind == xml.NodeKind.Element) }
  check(xml.is_nil(xml.at(cursor, 0)))
  for i in 0..10000 { cursor = cursor.parent }
  check(cursor == nested.root)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-xml-tree-') as temporary:
    work = Path(temporary)
    for name, code in [('main', source), ('capacity', '''use xml "std/encoding/xml"
use mem "std/mem"
fn main() {
  backing: [8]u8
  arena := mem.arena_from_buffer(backing[..])
  _ = xml.parse(arena, "<a/>") catch { return }
}
''')]:
        project = work / name
        project.mkdir()
        (project / 'main.dyn').write_text(code)
    for mode in ('--debug', '--release'):
        for name in ('main', 'capacity'):
            output = work / f'{name}-out'
            subprocess.run([str(DYN), 'build', str(work / name), '--no-cache', '--quiet', '--output', str(output), mode], cwd=ROOT, check=True, timeout=120)
            result = subprocess.run([str(output)], capture_output=True, timeout=30)
            assert (result.returncode == 0) == (name == 'main'), (mode, name, result.stdout, result.stderr)
            if name == 'capacity':
                assert b'arena' in result.stderr.lower(), result.stderr
print('PASS XML tree goldens, navigation, offsets, rollback, borrowing, arena ownership, dirty arena, depth 10000, exhaustion (debug/release)')
