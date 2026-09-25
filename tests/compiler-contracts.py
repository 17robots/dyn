#!/usr/bin/env python3
"""Regression checks for imports, diagnostics and mapped runtime traces."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

DYN = str(Path(os.environ.get('DYN', './build/dyn')).resolve())

class Contracts(unittest.TestCase):
    def test_scratch_rejects_all_conflicting_candidates(self):
        with tempfile.TemporaryDirectory(prefix='dyn-scratch-conflict-') as directory:
            root = Path(directory)
            (root / 'main.dyn').write_text('use "std/mem"\nfn main() { storage: [8]u8 = [] '
                'arena := mem.arena_from_buffer(storage[..]) '
                '_ = mem.scratch_begin(&arena, &arena, &arena) }\n')
            subprocess.run([DYN, 'build', directory, '--quiet', '--no-cache', '--output', str(root / 'program')], check=True)
            result = subprocess.run([str(root / 'program')], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('scratch requires a non-conflicting arena', result.stderr)

    def test_public_entry_survives_dependency_interface_compilation(self):
        with tempfile.TemporaryDirectory(prefix='dyn-public-main-') as directory:
            root = Path(directory)
            (root / 'main.dyn').write_text('use "std/io"\npub fn main() { _ = io.Reader{} }\n')
            result = subprocess.run([DYN, 'build', directory, '--quiet', '--no-cache',
                                     '--output', str(root / 'program')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(subprocess.run([str(root / 'program')]).returncode, 0)

    def test_imported_enum_alias_variants_and_reflection_interfaces(self):
        with tempfile.TemporaryDirectory(prefix='dyn-alias-reflect-') as directory:
            root = Path(directory)
            (root / 'kinds').mkdir()
            (root / 'kinds/main.dyn').write_text('enum Internal { WantRead } pub type ErrorKind = Internal\n')
            (root / 'main.dyn').write_text(
                'use "std/reflect" reflection\nuse "./kinds" tls\n'
                'fn main() { kind := tls.ErrorKind.WantRead '
                'if kind != tls.ErrorKind.WantRead || reflection.category(#typeof(u8)) != reflection.Kind.Integer '
                '{ #panic("alias and reflection") } }\n')
            for options in ([], ['--release']):
                result = subprocess.run([DYN, 'build', directory, '--quiet', '--no-cache',
                                         '--output', str(root / 'program'), *options],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(subprocess.run([str(root / 'program')]).returncode, 0)

    def test_direct_local_borrows_cannot_escape_returns(self):
        invalid = [
            'fn bad() *i32 { x: i32 = 1 return &x }',
            'fn bad(x: i32) *i32 { return &x }',
            'fn bad() []u8 { x: [4]u8 = [] return x[..] }',
            'struct Box { data: []u8 } fn bad() Box { x: [4]u8 = [] return Box{data: x[..]} }',
            'struct Box { value: i32 } fn bad() *i32 { x := Box{} return &x.value }',
        ]
        valid = [
            'fn good(x: *i32) *i32 { return x }',
            'fn good(x: []u8) []u8 { return x[..] }',
            'fn good(x: []u8) *u8 { return &x[0] }',
            'struct Box { value: i32 } fn good(x: *Box) *i32 { return &x.value }',
            'data: [4]u8 = [] fn good() []u8 { return data[..] }',
            'fn good() [4]u8 { x: [4]u8 = [] return x }',
        ]
        with tempfile.TemporaryDirectory(prefix='dyn-local-borrow-') as directory:
            root = Path(directory)
            for accepted, cases in ((False, invalid), (True, valid)):
                for source in cases:
                    (root / 'main.dyn').write_text(source + '\nfn main() {}\n')
                    for command in ('check', 'build'):
                        result = subprocess.run([DYN, command, directory, '--quiet', '--no-cache',
                                                 '--no-link', '--output', str(root / 'program.o')],
                                                capture_output=True, text=True)
                        with self.subTest(source=source, command=command):
                            self.assertEqual(result.returncode, 0 if accepted else 1, result.stderr)
                            if not accepted:
                                self.assertIn('returned value borrows function-local storage', result.stderr)


    @unittest.skipUnless(os.uname().sysname == 'Linux', 'native Linux link fixture')
    def test_discovered_native_libraries_are_released_on_all_exits(self):
        with tempfile.TemporaryDirectory(prefix='dyn-native-ownership-') as directory:
            root = Path(directory)
            library = root / 'libcleanupfixture.so'
            subprocess.run(['cc', '-shared', '-fPIC', '-x', 'c', '-', '-o', str(library)],
                           input='int cleanupfixture(void) { return 0; }',
                           text=True, capture_output=True, check=True)
            source = root / 'main.dyn'
            source.write_text('#link("cleanupfixture")\nfn main() {}\n')
            env = dict(os.environ, DYN_LIBRARY_PATH=directory)
            command = [DYN, 'build', directory, '--quiet', '--output', str(root / 'program')]
            for _ in range(2):  # Fresh build and cache hit.
                result = subprocess.run(command, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            for text in ('#link("cleanupfixture")\nfn main() { unknown() }\n',
                         '#link("cleanupfixture")\n#link("cleanup_missing_fixture")\nfn main() {}\n'):
                source.write_text(text)
                result = subprocess.run(command, env=env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('Sanitizer', result.stderr)

    def test_reflection_text_in_comments_and_strings_is_not_a_builtin(self):
        with tempfile.TemporaryDirectory(prefix='dyn-reflection-text-') as directory:
            root = Path(directory)
            (root / 'main.dyn').write_text('struct Type { value: i32 }\n'
                '// #typeof(i32)\nfn main() { value := Type{value: 42} _ = "#typeof(i32)" _ = value }\n')
            for command in ('check', 'build'):
                result = subprocess.run([DYN, command, directory, '--quiet', '--no-cache',
                                         '--no-link', '--output', str(root / 'program.o')],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_local_types_fail_before_codegen(self):
        with tempfile.TemporaryDirectory(prefix='dyn-invalid-local-type-') as directory:
            root = Path(directory)
            for body in ('alias:r', 'x: Missing', 'x: *Missing', 'x: []Missing', 'x: Missing = 1'):
                (root / 'main.dyn').write_text('fn main() { ' + body + ' }\n')
                for command in ('check', 'build'):
                    with self.subTest(body=body, command=command):
                        result = subprocess.run([DYN, command, directory, '--quiet', '--no-cache',
                                                 '--no-link', '--output', str(root / 'program.o')],
                                                capture_output=True, text=True)
                        self.assertEqual(result.returncode, 1, result.stderr)
                        self.assertIn('unknown or invalid local type', result.stderr)
                        self.assertNotIn('Sanitizer', result.stderr)

    def test_comments_do_not_make_structs_packed(self):
        with tempfile.TemporaryDirectory(prefix='dyn-struct-layout-') as directory:
            root = Path(directory)
            (root / 'main.dyn').write_text('struct /* padding */ Natural { a: u8, b: u64 }\n'
                'packed struct /* padding */ Tight { a: u8, b: u64 }\n'
                'fn main() { if #sizeof(Natural) != 16 || #sizeof(Tight) != 9 { #panic("layout") } }\n')
            result = subprocess.run([DYN, 'build', directory, '--quiet', '--no-cache', '--output', str(root / 'program')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(subprocess.run([str(root / 'program')]).returncode, 0)

    def test_comments_are_not_expression_operands(self):
        cases = [
            'x := 1 p: * /* comment */ i32 = &x p.* = 2 if x != 2 { #panic("pointer") }',
            'values := [1,2] s: [] /* comment */ i32 = values[..] s[0] = 3 if values[0] != 3 { #panic("slice") }',
            'x := 0 for /* * const */ item in [1,2] { x += item } if x != 3 { #panic("loop") }',
            'x := 1 /* note */ + 2 if x != 3 { #panic("binary") }',
            'x := /* note */ 42 if x != 42 { #panic("initializer") }',
            'values := [1, /* note */ 2, 3] if values[/* index */ 1] != 2 { #panic("array") }',
            'x := answer(/* argument */ 42) if x != 42 { #panic("call") }',
            'x := (/* group */ 42) if /* condition */ x != 42 /* branch */ { #panic("group") }',
        ]
        with tempfile.TemporaryDirectory(prefix='dyn-comment-operands-') as directory:
            root = Path(directory)
            for body in cases:
                with self.subTest(body=body):
                    (root / 'main.dyn').write_text('fn answer(value: i32) i32 { return value }\nfn main() { ' + body + ' }\n')
                    result = subprocess.run([DYN, 'build', directory, '--quiet', '--no-cache', '--output', str(root / 'program')], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(subprocess.run([str(root / 'program')]).returncode, 0)

    def test_import_comments_and_multiline_alias(self):
        with tempfile.TemporaryDirectory(prefix='dyn-import-trivia-') as directory:
            root = Path(directory)
            (root / 'helper').mkdir()
            (root / 'helper/helper.dyn').write_text('pub fn answer() i32 { return 42 }\n')
            for use in ['use /* path */ "./helper" h',
                        'use "./helper" /* alias */ h',
                        'use "./helper"\nh',
                        'use\t"./helper" h']:
                with self.subTest(use=use):
                    (root / 'main.dyn').write_text(use + '\nfn main() { if h.answer() != 42 { #panic("import") } }\n')
                    for command in ['check', 'build']:
                        result = subprocess.run([DYN, command, directory, '--quiet', '--no-cache', '--output', str(root / 'program')], capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(subprocess.run([str(root / 'program')]).returncode, 0)

    def test_target_text_in_comments_and_strings_is_not_a_directive(self):
        examples = [
            '// #target(kernel: windows)\nfn main() {}\n',
            '/* #target(kernel: windows) */\nfn main() {}\n',
            'fn main() { _ = "#target(kernel: windows)" }\n',
        ]
        with tempfile.TemporaryDirectory(prefix='dyn-target-text-') as directory:
            source = Path(directory) / 'main.dyn'
            for text in examples:
                with self.subTest(text=text):
                    source.write_text(text)
                    result = subprocess.run([DYN, 'build', directory, '--quiet', '--no-cache',
                                             '--output', str(Path(directory) / 'program')],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_module_global_does_not_shadow_imported_local(self):
        with tempfile.TemporaryDirectory(prefix='dyn-module-scope-') as directory:
            root = Path(directory)
            (root / 'helper').mkdir()
            (root / 'helper' / 'helper.dyn').write_text('pub fn answer() i32 { sequence := 42 return sequence }\n')
            (root / 'main.dyn').write_text('use "./helper"\nsequence: i32 = 7\nfn main() { if helper.answer() != 42 || sequence != 7 { #panic("scope") } }\n')
            checked = subprocess.run([DYN, 'check', directory, '--quiet'], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            output = root / 'program'
            built = subprocess.run([DYN, 'build', directory, '--no-cache', '--quiet', '--output', str(output)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            self.assertEqual(subprocess.run([str(output)]).returncode, 0)

    def test_import_cannot_see_root_types_without_use(self):
        with tempfile.TemporaryDirectory(prefix='dyn-module-types-') as directory:
            root = Path(directory)
            (root / 'helper').mkdir()
            (root / 'helper' / 'helper.dyn').write_text('pub fn answer(value: Hidden) i32 { return value.value }\n')
            (root / 'main.dyn').write_text('use "./helper"\nstruct Hidden { value: i32 }\nfn main() { _ = helper.answer(Hidden{ value: 42 }) }\n')
            for command in ['check', 'build']:
                result = subprocess.run([DYN, command, directory, '--no-cache', '--quiet', '--output', str(root / 'program')], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, command)
                self.assertIn('unknown type', result.stderr)

    def test_nested_slice_index(self):
        with tempfile.TemporaryDirectory(prefix='dyn-slice-index-') as directory:
            root = Path(directory)
            (root / 'main.dyn').write_text('fn main() { values: [3]u8 = [4, 5, 6] if values[..][1] != 5 { #panic("nested index") } }\n')
            output = root / 'program'
            built = subprocess.run([DYN, 'build', directory, '--no-cache', '--quiet', '--output', str(output)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(output)], capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)

    def test_struct_alias_constructor(self):
        with tempfile.TemporaryDirectory(prefix='dyn-struct-alias-') as directory:
            root = Path(directory)
            (root / 'main.dyn').write_text('struct Item { value: i32 }\ntype Alias = Item\nfn main() { item := Alias{ value: 42 } if item.value != 42 { #panic("alias constructor") } }\n')
            output = root / 'program'
            built = subprocess.run([DYN, 'build', directory, '--no-cache', '--quiet', '--output', str(output)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(output)], capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)

    def test_import_field_collision(self):
        result = subprocess.run([DYN, 'check', 'tests/import-field-collision', '--quiet'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_qualifier_has_one_root_error(self):
        result = subprocess.run([DYN, 'check', 'tests/import-unknown-alias', '--quiet'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.count('error:'), 1, result.stderr)
        self.assertIn('unknown name', result.stderr)

    def test_trace_uses_original_file_and_line(self):
        with tempfile.TemporaryDirectory(prefix='dyn-trace-') as directory:
            root = Path(directory)
            (root / 'main.dyn').write_text('use "std/mem"\nfn main() {\n  storage: [16]u8 = []\n  arena := mem.arena_from_buffer(storage[..])\n  _ = arena\n  fail()\n}\n')
            helper = root / 'helper.dyn'
            helper.write_text('fn fail() { #panic("expected failure") }\n')
            output = root / 'program'
            built = subprocess.run([DYN, 'build', str(root), '--no-cache', '--output', str(output), '--quiet'], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 101)
            self.assertIn(f'fail ({helper}:1)', result.stderr)
            self.assertIn(f'main ({root / "main.dyn"}:2)', result.stderr)

if __name__ == '__main__':
    unittest.main()
