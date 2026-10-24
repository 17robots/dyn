#!/usr/bin/env python3
"""Independent source fixtures for the syntactic std API lint."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('std_lint', ROOT / 'tools/std-lint.py')
LINT = importlib.util.module_from_spec(SPEC)
with contextlib.redirect_stdout(io.StringIO()) as IMPORT_OUTPUT:
    SPEC.loader.exec_module(LINT)


class StdLint(unittest.TestCase):
    def check_source(self, source, relative='fixture.dyn'):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
            return LINT.check(path)

    def test_import_has_no_scan(self):
        self.assertEqual(IMPORT_OUTPUT.getvalue(), '')

    def test_multiline_and_original_lines(self):
        problems = self.check_source('''// heading
pub
fn copy_into(
    callback: fn(fn(u8) bool, usize) bool,
    out: *u8,
) usize {
}

pub fn find_item(
    value: usize,
)
    isize
{
}
''')
        self.assertEqual([line for line, _ in problems], [2, 2, 9])
        self.assertIn('copy_into: caller-buffer', problems[0][1])
        self.assertIn('out parameter', problems[1][1])
        self.assertIn('returns isize', problems[2][1])

    def test_nested_parameters_are_not_outer_parameters(self):
        self.assertEqual(self.check_source('''pub fn visit(
 callback: fn(out: *u8, nested: fn(storage: *u8) bool) bool
) bool {}
pub fn visit_size() usize {}
'''), [])

    def test_comments_and_quoted_fake_declarations(self):
        problems = self.check_source('''/* pub fn fake_into(out: *u8) isize {}
 /* nested */ still comment */
const text = "pub fn quoted_into(out: *u8) isize {}"
const escaped = "\\\" pub fn escaped_into() {}"
// pub fn line_into() {}
pub /* explanation */ fn real_into(
 callback: fn(u8 /* ) */, fn(u8) bool) bool,
 output: /* pointer */ *u8
) {}
''')
        self.assertEqual([line for line, _ in problems], [6, 6])
        self.assertTrue(all('real_into:' in message for _, message in problems))

    def test_size_and_count_companions(self):
        problems = self.check_source('''pub fn encode(
 storage: []u8, callback: fn(u8) bool
) usize {}
pub fn encode_size() usize {}
pub fn encode_count() usize {}
pub fn unrelated_size() usize {}
pub fn plain(value: usize) usize {}
pub fn plain_count() usize {}
''')
        self.assertEqual([line for line, _ in problems], [4, 5])

    def test_narrow_heuristics_and_actual_miss(self):
        problems = self.check_source('''pub fn allowed(target: *u8, out: usize) isize {}
pub fn find_ok() usize {}
pub fn actual_into() {}
pub fn find_missing() isize {}
pub fn output_value(output: *u8) {}
''')
        self.assertEqual([line for line, _ in problems], [3, 4, 5])

    def test_only_raw_abi_bindings_in_os_and_c_are_exempt(self):
        source = '''pub extern fn find_raw_into "native_symbol"(
 out: *u8, callback: fn(u8) bool
) isize
pub fn wrapper_into(out: *u8) {}
'''
        for relative in ('std/os/raw.dyn', 'std/c/raw.dyn'):
            with self.subTest(relative=relative):
                self.assertEqual([line for line, _ in self.check_source(source, relative)], [4, 4])
        self.assertEqual([line for line, _ in self.check_source(source, 'std/other/raw.dyn')],
                         [1, 1, 1, 4, 4])


if __name__ == '__main__':
    unittest.main()
