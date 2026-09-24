#!/usr/bin/env python3
"""Executable memory examples and compiler-backed declaration query contracts."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())


class AgentReadiness(unittest.TestCase):
    def test_memory_contracts_and_tour(self):
        with tempfile.TemporaryDirectory(prefix='dyn-memory-contracts-') as directory:
            for fixture in ('tests/sdk-memory-observation', 'projects/memory-tour'):
                for mode in ([], ['--release']):
                    with self.subTest(fixture=fixture, mode=mode):
                        program = str(Path(directory) / 'program')
                        subprocess.run([DYN, 'build', str(ROOT / fixture), '--no-cache',
                                        '--quiet', '--output', program, *mode], check=True, timeout=120)
                        subprocess.run([program], check=True, capture_output=True, text=True, timeout=20)

    def test_json_declarations(self):
        with tempfile.TemporaryDirectory(prefix='dyn-docs-"-') as directory:
            root = Path(directory)
            source = root / 'main.dyn'
            source.write_text('// Borrows "input"; slash \\ and tab\there.\n'
                              'pub fn view(input: []const u8) []const u8 { return input }\n'
                              'fn hidden() {}\npub struct Item { value: usize }\n'
                              'pub enum State { Missing, Present: usize }\n'
                              'pub const Limit: usize = 4\npub type Count = usize\n')
            (root / 'other.dyn').write_text('#target(kernel: windows)\npub fn other() {}\n')
            command = [DYN, 'docs', directory, '--json']
            run = subprocess.run(command, capture_output=True, text=True, check=True)
            report = json.loads(run.stdout)
            self.assertEqual(report['schema_version'], 1)
            self.assertEqual(report['analysis'], 'syntax-only')
            self.assertEqual(report['target_selection'], 'all-source-files')
            declarations = {d['name']: d for f in report['files'] for d in f['declarations']}
            self.assertEqual(set(declarations), {'view', 'Item', 'State', 'Limit', 'Count', 'other'})
            view = declarations['view']
            self.assertEqual(view['line'], 2)
            self.assertEqual(view['column'], 1)
            self.assertEqual(view['kind'], 'function')
            self.assertEqual(view['declaration'], 'pub fn view(input: []const u8) []const u8')
            self.assertIn('"input"', view['source_comments'])
            self.assertIn('\\ and tab\t', view['source_comments'])
            self.assertEqual([g for f in report['files'] for g in f['target_gates']], ['#target(kernel: windows)'])
            again = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertEqual(run.stdout, again.stdout)
            source.write_text(source.read_text().replace('Borrows', 'Retains'))
            changed = json.loads(subprocess.run(command, capture_output=True, text=True, check=True).stdout)
            self.assertNotEqual(report['source_fingerprint'], changed['source_fingerprint'])
            markdown = subprocess.run([DYN, 'docs', directory], capture_output=True, text=True, check=True).stdout
            self.assertIn('```dyn\npub fn view', markdown)
            self.assertNotIn('fn hidden', markdown)
            (root / 'z-broken.dyn').write_text('pub fn broken( {')
            broken = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(broken.returncode, 1)
            self.assertEqual(broken.stdout, '')

    def test_json_flag_is_docs_only(self):
        result = subprocess.run([DYN, 'check', str(ROOT / 'compiler/tests/smoke'), '--json'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--json is only supported by docs', result.stderr)


if __name__ == '__main__':
    unittest.main()
