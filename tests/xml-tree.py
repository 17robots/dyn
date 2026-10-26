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
source = '''use "std/encoding/xml" xml
use "std/mem" mem
use "std/bytes" bytes
use "std/errors" errors
fn check(ok: bool) { if !ok { #panic("xml tree contract") } }
fn main() {
  arena := mem.arena_create(0)
  defer { mem.arena_release(arena) }
  zero: xml.Node
  check(xml.is_nil(&zero) && xml.is_nil(nil))
  check(xml.child(nil, "x") == &xml.nil_node && xml.at(nil, 0) == &xml.nil_node && xml.next_sibling(nil) == &xml.nil_node)
  r := xml.parse(arena, "<?xml version='1.0'?>\\n<!--before--><root a='&amp;' b=\\"2\\"><leaf/>raw&amp;<!--hi--><![CDATA[<raw>]]><?pi body  ?></root> ")
  check(r.ok && r.kind == errors.Kind.None && r.error == 0)
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
  borrowed_tree := xml.parse(arena, borrowed[..])
  borrowed_text := xml.at(xml.child(borrowed_tree.root, "t"), 0)
  check(borrowed_tree.ok && #cast(usize, &borrowed_text.text[0]) == #cast(usize, &borrowed[3]))
  borrowed[3] = 'y'
  check(bytes.equal(borrowed_text.text, "y"))
  mark := mem.arena_mark(arena)
'''
bad = [('', 0, 'Syntax'), ('<a></b>', 3, 'Mismatched'),
       ('<a/><b/>', 4, 'Syntax'), ('<a>', 3, 'Mismatched'),
       ('text<a/>', 0, 'Syntax'), ('<a/>text', 4, 'Syntax'),
       ('<!--only-->', 11, 'Syntax'), ('<a x=bad/>', 0, 'Syntax'),
       ('<a x="1" x="2"/>', 0, 'Syntax'), ('<a 1x="a"/>', 0, 'Syntax'),
       ('<a x="<"/>', 0, 'Syntax'), ('<a>&unknown;</a>', 3, 'Syntax'),
       ('<!DOCTYPE a><a/>', 1, 'Syntax'), ('<![CDATA[x]]><a/>', 0, 'Syntax'),
       ('<a><!--a--b--></a>', 3, 'Syntax'), ('<a><!--a---></a>', 3, 'Syntax'),
       ('<a', 2, 'Syntax'), ('</a>', 0, 'Mismatched')]
for value, offset, detail in bad:
    source += f'''  if true {{
    bad := xml.parse(arena, {json.dumps(value)})
    check(!bad.ok && bad.root == &xml.nil_node && bad.kind == errors.Kind.InvalidInput && bad.error == 0 && bad.offset == {offset} && bad.detail == xml.ErrorKind.{detail})
    check(mem.arena_mark(arena) == mark && bytes.equal(root.name, "root"))
    check(xml.child(bad.root, "a") == &xml.nil_node)
  }}
'''
source += '''
  invalid: [8]u8 = ['<', 'a', '>', 255, '<', '/', 'a', '>']
  bad_utf8 := xml.parse(arena, invalid[..])
  check(!bad_utf8.ok && bad_utf8.offset == 3 && bad_utf8.error == 0 && bad_utf8.kind == errors.Kind.InvalidInput && bad_utf8.detail == xml.ErrorKind.Syntax && bad_utf8.root == &xml.nil_node)
  check(mem.arena_mark(arena) == mark)
  backing: [4096]u8
  for i in 0..#len(backing) { backing[i] = 255 }
  fixed := mem.arena_from_buffer(backing[..])
  prefix := mem.push(u8, fixed)
  prefix.* = 42
  fixed_mark := mem.arena_mark(fixed)
  failed := xml.parse(fixed, "<a><b/></z>")
  check(!failed.ok && mem.arena_mark(fixed) == fixed_mark && prefix.* == 42)
  input: [11]u8 = ['<', 'a', ' ', 'x', '=', '"', 'v', '"', '/', '>', ' ']
  owned := xml.parse(fixed, input[..])
  element := xml.child(owned.root, "a")
  check(owned.ok && element.first == nil && element.last == nil && element.next == xml.at(owned.root, 1) && #len(element.text) == 0)
  check(#cast(usize, owned.root) >= #cast(usize, &backing[0]) && #cast(usize, owned.root) < #cast(usize, &backing[4095]))
  check(#cast(usize, element) >= #cast(usize, &backing[0]) && #cast(usize, element) < #cast(usize, &backing[4095]))
  check(#cast(usize, &element.name[0]) == #cast(usize, &input[1]) && #cast(usize, &element.attributes[0]) == #cast(usize, &input[2]))
  input[1] = 'z'
  input[6] = 'w'
  check(bytes.equal(element.name, "z") && bytes.equal(element.attributes, " x=\\"w\\""))
  deep := mem.push_array(u8, arena, 70000)
  for i in 0..10000 {
    deep[i * 3] = '<'
    deep[i * 3 + 1] = 'a'
    deep[i * 3 + 2] = '>'
    deep[30000 + i * 4] = '<'
    deep[30001 + i * 4] = '/'
    deep[30002 + i * 4] = 'a'
    deep[30003 + i * 4] = '>'
  }
  nested := xml.parse(arena, deep)
  check(nested.ok)
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
    for name, code in [('main', source), ('capacity', '''use "std/encoding/xml" xml
use "std/mem" mem
fn main() {
  backing: [8]u8
  arena := mem.arena_from_buffer(backing[..])
  _ = xml.parse(arena, "<a/>")
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
