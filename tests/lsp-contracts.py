#!/usr/bin/env python3
"""Editor regressions for library modules, import failures and constants."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

DYN = str(Path(os.environ.get('DYN', './build/dyn')).resolve())


def request(method, params, ident=None):
    result = {'jsonrpc': '2.0', 'method': method, 'params': params}
    if ident is not None:
        result['id'] = ident
    return result


def opened(path, text):
    return request('textDocument/didOpen', {'textDocument': {
        'uri': path.as_uri(), 'languageId': 'dyn', 'version': 1, 'text': text}})


def run_lsp(messages, initialize=None, target=None):
    messages = [request('initialize', initialize or {}, 1), *messages,
                request('shutdown', None, 999), request('exit', None)]
    wire = bytearray()
    for message in messages:
        body = message if isinstance(message, bytes) else json.dumps(message).encode()
        wire.extend(b'Content-Length: %d\r\n\r\n' % len(body) + body)
    env = dict(os.environ, DYN_SDK=str(Path('compiler').resolve()))
    process = subprocess.run([DYN, 'lsp', *(['--target', target] if target else [])], input=wire, capture_output=True,
                             env=env, timeout=20, check=True)
    output = process.stdout
    responses = []
    while output:
        header, output = output.split(b'\r\n\r\n', 1)
        length = int(header.split(b':', 1)[1])
        responses.append(json.loads(output[:length]))
        output = output[length:]
    return responses, process.stderr.decode()


def diagnostics(responses, path):
    return [r['params']['diagnostics'] for r in responses
            if r.get('method') == 'textDocument/publishDiagnostics'
            and r['params']['uri'] == path.as_uri()][-1]


class Contracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dyn-lsp-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def file(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_diagnostics_and_hover_reuse_one_analysis(self):
        from unittest.mock import patch
        import re
        text = 'fn main() { value: i32 = true\n_ = value }\n'
        path = self.file('main.dyn', text)
        with patch.dict(os.environ, {'DYN_LSP_ANALYSIS_STATS': '1'}):
            responses, stderr = run_lsp([opened(path, text),
                request('workspace/didChangeWatchedFiles', {'changes': [{'uri': path.as_uri(), 'type': 2}]}),
                request('textDocument/hover', {'textDocument': {'uri': path.as_uri()},
                    'position': {'line': 1, 'character': 5}}, 2)])
        self.assertTrue(any('initializer type mismatch' in item['message'] for item in diagnostics(responses, path)))
        counts = re.search(r'hits=(\d+) misses=(\d+)', stderr)
        self.assertIsNotNone(counts, stderr)
        self.assertEqual(int(counts[2]), 1, stderr)
        self.assertGreaterEqual(int(counts[1]), 2, stderr)

    def complete(self, marked, extra_messages=()):
        before, after = marked.split('|')
        text = before + after
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text), *extra_messages,
            request('textDocument/completion', {'textDocument': {'uri': path.as_uri()},
                'position': {'line': before.count('\n'), 'character': len(before.rsplit('\n', 1)[-1])}}, 2)])
        self.assertEqual(stderr, '')
        return next(r['result'] for r in responses if r.get('id') == 2)

    def test_fill_fields_uses_imported_types_and_multiline_syntax(self):
        self.file('types/module.dyn', 'pub struct Record { name: []const u8, flag: bool, values: []i32, pointer: *i32 }\n')
        text = ('use "./types" t\nfn main() {\n value := t.Record{\n'
                '  name: "} flag: fake", // values: not a member\n'
                ' }\n _ = value\n}\n')
        path = self.file('main.dyn', text)
        point = {'line': 3, 'character': 4}
        responses, stderr = run_lsp([opened(path, text), request('textDocument/codeAction', {
            'textDocument': {'uri': path.as_uri()}, 'range': {'start': point, 'end': point},
            'context': {'diagnostics': []}}, 2)])
        self.assertEqual(stderr, '')
        actions = next(r['result'] for r in responses if r.get('id') == 2)
        action = next(a for a in actions if a['title'] == 'Fill missing struct fields')
        edit = action['edit']['changes'][path.as_uri()][0]
        self.assertEqual(edit['range']['start'], {'line': 4, 'character': 1})
        self.assertEqual(edit['newText'], 'flag: false, values: ([#cast(i32) 0])[..0], pointer: nil')
        lines = text.splitlines(keepends=True)
        offset = sum(map(len, lines[:4])) + 1
        path.write_text(text[:offset] + edit['newText'] + text[offset:])
        result = subprocess.run([DYN, 'check', str(self.root), '--quiet'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_enum_context_and_snippets_skip_comments(self):
        definitions = ('enum Choice { One, Two }\n'
                       'fn /* comment */ take(first, second: Choice) {}\n'
                       'fn /* return */ pick() Choice {\n return O|\n}\n')
        self.assertIn('One', {i['label'] for i in self.complete(definitions)})
        items = self.complete('fn take(first, /* misleading: comma, */ second: i32) {}\nfn main() { ta| }\n')
        take = next(i for i in items if i['label'] == 'take')
        self.assertEqual(take['insertText'], 'take(${1:first}, ${2:second})')

    def test_cached_import_analysis_tracks_open_change_and_close(self):
        imported = self.file('types/module.dyn', 'pub fn answer() i32 { return 1 }\n')
        text = 'use "./types"\nfn main() { value := types.answer()\n _ = value\n}\n'
        path = self.file('main.dyn', text)
        def hover(ident):
            return request('textDocument/hover', {'textDocument': {'uri': path.as_uri()},
                           'position': {'line': 2, 'character': 6}}, ident)
        responses, stderr = run_lsp([opened(path, text), hover(2), hover(3),
            opened(imported, 'pub fn answer() bool { return true }\n'), hover(4),
            request('textDocument/didClose', {'textDocument': {'uri': imported.as_uri()}}), hover(5)])
        self.assertEqual(stderr, '')
        for ident, expected in [(2, 'i32'), (3, 'i32'), (4, 'bool'), (5, 'i32')]:
            result = next(r['result'] for r in responses if r.get('id') == ident)
            self.assertIn(expected, result['contents']['value'])

    def test_auto_import_uses_public_syntax_declarations(self):
        self.file('library/exports.dyn',
                  '/*\npub fn ZebraPhantom() {}\n*/\n'
                  'pub /* visibility */ fn\nZebraReal() {}\n')
        result = self.complete('fn main() { Zebra| }')
        items = result['items'] if isinstance(result, dict) else result
        labels = {item['label'] for item in items}
        self.assertIn('ZebraReal', labels)
        self.assertNotIn('ZebraPhantom', labels)

    def test_symbols_share_syntax_declarations(self):
        text = ('/*\nfn phantom() {}\n*/\n'
                'pub /* visibility */ fn\nreal() {}\n'
                'const /* name */ answer: i32 = 42\n'
                'counter: i32 = 0\n')
        path = self.file('symbols.dyn', text)
        responses, stderr = run_lsp([opened(path, text),
            request('textDocument/documentSymbol',
                    {'textDocument': {'uri': path.as_uri()}}, 2),
            request('workspace/symbol', {'query': ''}, 3)])
        self.assertEqual(stderr, '')
        for ident in (2, 3):
            symbols = next(r['result'] for r in responses if r.get('id') == ident)
            self.assertEqual({s['name']: s['kind'] for s in symbols},
                             {'real': 12, 'answer': 14, 'counter': 13})
            real = next(s for s in symbols if s['name'] == 'real')
            span = real['selectionRange'] if ident == 2 else real['location']['range']
            self.assertEqual(span['start'], {'line': 4, 'character': 0})

    def test_partial_import_semantic_tokens_keep_server_alive(self):
        path = self.file('main.dyn', '')
        messages = [opened(path, '')]
        for index, text in enumerate(['use "', 'use "s', 'use "st', 'use "std', 'use "std/'], 2):
            messages.append(request('textDocument/didChange', {
                'textDocument': {'uri': path.as_uri(), 'version': index},
                'contentChanges': [{'text': text}]}))
            messages.append(request('textDocument/semanticTokens/full', {'textDocument': {'uri': path.as_uri()}}, index))
        messages.append(request('textDocument/completion', {
            'textDocument': {'uri': path.as_uri()}, 'position': {'line': 0, 'character': 9}}, 20))
        responses, stderr = run_lsp(messages)
        self.assertEqual(stderr, '')
        for index in range(2, 7):
            self.assertIn('result', next(r for r in responses if r.get('id') == index))
        result = next(r['result'] for r in responses if r.get('id') == 20)
        items = result.get('items', []) if isinstance(result, dict) else result
        self.assertTrue({'io', 'mem', 'net'} <= {item['label'] for item in items}, items)

    def test_completion_nested_import_paths_after_edits(self):
        path = self.file('main.dyn', 'use ""')
        messages = [opened(path, 'use ""')]
        cases = [('std/', {'io', 'mem', 'net'}),
                 ('std/bytes/', {'builder'}),
                 ('std/net/', {'http', 'tls', 'dns'}),
                 ('std/net/http/', {'concurrent'}),
                 ('std/encoding/', {'json', 'base64'})]
        previous = ''
        for ident, (typed, expected) in enumerate(cases, 2):
            messages.append(request('textDocument/didChange', {
                'textDocument': {'uri': path.as_uri(), 'version': ident},
                'contentChanges': [{'range': {'start': {'line': 0, 'character': 5},
                                             'end': {'line': 0, 'character': 5 + len(previous)}}, 'text': typed}]}))
            messages.append(request('textDocument/completion', {
                'textDocument': {'uri': path.as_uri()},
                'position': {'line': 0, 'character': 5 + len(typed)},
                'context': {'triggerKind': 2, 'triggerCharacter': '/'}}, ident))
            previous = typed
        responses, stderr = run_lsp(messages)
        self.assertEqual(stderr, '')
        for ident, (typed, expected) in enumerate(cases, 2):
            items = next(r['result'] for r in responses if r.get('id') == ident)
            self.assertTrue(expected <= {item['label'] for item in items}, (typed, items))

    def test_completion_after_typing_open_import_quote(self):
        for suffix in ['', '"']:
            with self.subTest(suffix=suffix):
                path = self.file('main.dyn', '')
                messages = [opened(path, '')]
                for version, (column, inserted) in enumerate([(0, 'u'), (1, 's'), (2, 'e'), (3, ' '), (4, '"' + suffix)], 2):
                    messages.append(request('textDocument/didChange', {
                        'textDocument': {'uri': path.as_uri(), 'version': version},
                        'contentChanges': [{'range': {'start': {'line': 0, 'character': column},
                                                     'end': {'line': 0, 'character': column}}, 'text': inserted}]}))
                messages.append(request('textDocument/completion', {
                    'textDocument': {'uri': path.as_uri()},
                    'position': {'line': 0, 'character': 5},
                    'context': {'triggerKind': 2, 'triggerCharacter': '"'}}, 2))
                responses, stderr = run_lsp(messages)
                self.assertEqual(stderr, '')
                capabilities = next(r['result']['capabilities'] for r in responses if r.get('id') == 1)
                self.assertIn('"', capabilities['completionProvider']['triggerCharacters'])
                items = next(r['result'] for r in responses if r.get('id') == 2)
                self.assertTrue({'std', 'vendor'} <= {item['label'] for item in items}, items)
                self.assertEqual(next(item['insertText'] for item in items if item['label'] == 'std'), 'std')

    def test_completion_declarations_follow_syntax(self):
        text = ('use "std/io" stream\n'
                'value: i32 = 42\nfn one() {} fn two() {}\n'
                'pub /* comment */ fn commented() {}\n'
                '/* fn fake() {} */\nfn main() { | }')
        labels = {i['label'] for i in self.complete(text)}
        self.assertTrue({'stream', 'value', 'one', 'two', 'commented'} <= labels, labels)
        self.assertNotIn('fake', labels)

    def test_completion_import_uses_unsaved_module(self):
        helper = self.file('helper/helper.dyn', 'pub fn disk() {}\n')
        items = self.complete('use "./helper"\nfn main() { helper.| }',
                              [opened(helper, 'pub fn unsaved() {}\nfn private_item() {}\n')])
        labels = {i['label'] for i in items}
        self.assertIn('unsaved', labels)
        self.assertNotIn('disk', labels)
        self.assertNotIn('private_item', labels)

    def test_completion_unopened_sibling_stays_in_module(self):
        self.file('sibling.dyn', 'fn sibling() {}\n')
        foreign = self.file('child/helper.dyn', 'pub fn foreign() {}\n')
        labels = {i['label'] for i in self.complete('fn main() { sib| }', [opened(foreign, foreign.read_text())])}
        self.assertIn('sibling', labels)
        self.assertNotIn('foreign', labels)

    def test_completion_import_path_whitespace(self):
        for prefix in ['use\t', 'use  ', 'use /* comment */ ']:
            with self.subTest(prefix=prefix):
                labels = {i['label'] for i in self.complete(prefix + '"std/|"\nfn main() {}')}
                self.assertTrue({'io', 'net', 'mem'} <= labels, labels)

    def test_completion_nested_fields_in_incomplete_statements(self):
        definitions = 'struct Inner { value: i32 }\nstruct Outer { inner: Inner }\n' + 'fn make() Inner { return Inner{ value: 1 } }\n'
        for body in ['fn main() {\n if make().|\n}',
                     'fn main() { item := Outer{ inner: Inner{ value: 1 } } item.inner.| }',
                     'fn main() {\n item := Outer{ inner: Inner{ value: 1 } }\n if item.inner.|\n}',
                     'fn main() {\n item := Outer{ inner: Inner{ value: 1 } }\n for item.inner.|\n}']:
            with self.subTest(body=body):
                labels = {i['label'] for i in self.complete(definitions + body)}
                self.assertIn('value', labels)

    def test_remove_unused_import_preserves_adjacent_code(self):
        self.file('helper/helper.dyn', 'pub fn answer() i32 { return 42 }\n')
        for text in ['use "./helper" h fn main() {}\n', 'use\t"./helper"\nh\nfn main() {}\n']:
            with self.subTest(text=text):
                path = self.file('main.dyn', text)
                end_line = 1 if '\nh\n' in text else 0
                end_column = 1 if end_line else len('use "./helper" h')
                params = {'textDocument': {'uri': path.as_uri()},
                          'range': {'start': {'line': 0, 'character': 0}, 'end': {'line': end_line, 'character': end_column}},
                          'context': {'diagnostics': [{'code': 'unused-use', 'message': 'unused import'}]}}
                responses, stderr = run_lsp([opened(path, text), request('textDocument/codeAction', params, 2)])
                self.assertEqual(stderr, '')
                actions = next(r['result'] for r in responses if r.get('id') == 2)
                action = next((a for a in actions if a['title'] == 'Remove unused use'), None)
                self.assertIsNotNone(action, actions)
                edit = action['edit']['changes'][path.as_uri()][0]
                lines = text.splitlines(keepends=True)
                def offset(position):
                    return sum(map(len, lines[:position['line']])) + position['character']
                updated = text[:offset(edit['range']['start'])] + edit['newText'] + text[offset(edit['range']['end']):]
                self.assertEqual(updated.strip(), 'fn main() {}')

    def test_import_comments_keep_path_and_alias(self):
        self.file('helper/helper.dyn', 'pub fn answer() i32 { return 42 }\n')
        for use in ['use /* path */ "./helper" h', 'use "./helper" /* alias */ h', 'use "./helper"\nh']:
            with self.subTest(use=use):
                text = use + '\nfn main() { _ = h.answer() }\n'
                path = self.file('main.dyn', text)
                responses, stderr = run_lsp([opened(path, text)])
                self.assertEqual(stderr, '')
                self.assertEqual(diagnostics(responses, path), [])

    def test_long_default_import_alias(self):
        name = 'a' * 200
        self.file(name + '/helper.dyn', 'pub fn answer() i32 { return 42 }\n')
        text = 'use "./' + name + '"\nfn main() {}\n'
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text)])
        self.assertEqual(stderr, '')
        warnings = diagnostics(responses, path)
        self.assertTrue(any(d.get('code') == 'unused-use' and name in d['message'] for d in warnings), warnings)

    def test_import_followed_by_global_keeps_declaration(self):
        self.file('helper/helper.dyn', 'pub fn answer() i32 { return 42 }\n')
        for alias in ['', ' h']:
            for declaration in ['value := 42', 'value: i32 = 42', 'const value := 42']:
                with self.subTest(alias=alias, declaration=declaration):
                    qualifier = 'h' if alias else 'helper'
                    text = ('use "./helper"' + alias + '\n' + declaration + '\n'
                            'fn main() { _ = value _ = ' + qualifier + '.answer() }\n')
                    path = self.file('main.dyn', text)
                    responses, stderr = run_lsp([opened(path, text)])
                    self.assertEqual(stderr, '')
                    self.assertEqual(diagnostics(responses, path), [])

    def test_unused_bindings_ignore_other_functions_and_fields(self):
        text = ('fn unused(value: i32) {}\n'
                'fn used(value: i32) { _ = value }\n'
                'struct Item { lonely: i32 }\n'
                'fn main() { lonely := 1 item := Item{ lonely: 2 } _ = item.lonely used(3) }\n')
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text)])
        self.assertEqual(stderr, '')
        warnings = diagnostics(responses, path)
        self.assertTrue(any(d.get('code') == 'unused-parameter' and d['range']['start']['line'] == 0 for d in warnings), warnings)
        self.assertTrue(any(d.get('code') == 'unused-variable' and "'lonely'" in d['message'] for d in warnings), warnings)
        self.assertFalse(any(d.get('code') == 'unused-parameter' and d['range']['start']['line'] == 1 for d in warnings), warnings)

    def test_default_utf16_positions_and_edits(self):
        text = 'fn main() { _ = "😀" missing() }\n'
        path = self.file('main.dyn', text)
        start = len(text[:text.index('missing')].encode('utf-16-le')) // 2
        responses, stderr = run_lsp([opened(path, text), request('textDocument/didChange', {
            'textDocument': {'uri': path.as_uri(), 'version': 2},
            'contentChanges': [{'range': {'start': {'line': 0, 'character': start},
                                         'end': {'line': 0, 'character': start + 9}}, 'text': ''}]
        })])
        self.assertEqual(stderr, '')
        initial = [r['params']['diagnostics'] for r in responses if r.get('method') == 'textDocument/publishDiagnostics' and r['params']['diagnostics']][0]
        self.assertEqual(initial[0]['range']['start']['character'], start, initial)
        self.assertFalse(any(d.get('severity') == 1 for d in diagnostics(responses, path)), diagnostics(responses, path))
        capabilities = next(r['result']['capabilities'] for r in responses if r.get('id') == 1)
        self.assertEqual(capabilities['positionEncoding'], 'utf-16')

    def test_utf8_negotiation_and_string_request_id(self):
        text = 'fn main() { _ = "😀" missing() }\n'
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text), request('unknown/method', {}, 'request-42')],
            {'capabilities': {'general': {'positionEncodings': ['utf-8', 'utf-16']}}})
        self.assertEqual(stderr, '')
        capabilities = next(r['result']['capabilities'] for r in responses if r.get('id') == 1)
        self.assertEqual(capabilities['positionEncoding'], 'utf-8')
        self.assertEqual(diagnostics(responses, path)[0]['range']['start']['character'], len(text[:text.index('missing')].encode()))
        self.assertTrue(any(r.get('id') == 'request-42' and r.get('error', {}).get('code') == -32601 for r in responses))

    def test_malformed_json_does_not_poison_next_request(self):
        responses, stderr = run_lsp([b'{"method":"textDocument/didOpen","params":',
            request('textDocument/didChange', {'textDocument': {'uri': self.root.as_uri() + '/unopened.dyn'}, 'contentChanges': [{'text': 'fn main() {}'}]}),
            b'{"jsonrpc":"2.0","id":4,"method":"\xff"}',
            request('unknown/method', {}, 42)])
        self.assertEqual(stderr, '')
        self.assertTrue(any(r.get('error', {}).get('code') == -32700 for r in responses))
        self.assertTrue(any(r.get('id') == 42 and r.get('error', {}).get('code') == -32601 for r in responses))

    def test_oversized_completion_returns_error_without_crashing(self):
        text = ''.join('pub fn function_' + str(i) + '_' + 'x' * 180 + '() {}\n' for i in range(1800))
        text += 'fn main() {}\n'
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text), request('textDocument/completion', {
            'textDocument': {'uri': path.as_uri()}, 'position': {'line': 1800, 'character': 12}}, 42)])
        self.assertEqual(stderr, '')
        response = next(r for r in responses if r.get('id') == 42)
        self.assertEqual(response.get('error', {}).get('code'), -32603, response.keys())
        self.assertTrue(any(r.get('id') == 999 for r in responses))

    def test_selection_range_returns_every_requested_position(self):
        text = 'fn main() {\n  _ = "😀"\n}\n'
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text), request('textDocument/selectionRange', {
            'textDocument': {'uri': path.as_uri()}, 'positions': [{'line': 0, 'character': 4}, {'line': 1, 'character': 8}]}, 42)])
        self.assertEqual(stderr, '')
        result = next(r['result'] for r in responses if r.get('id') == 42)
        self.assertEqual(len(result), 2)

    def test_rename_uses_each_documents_utf16_columns(self):
        declaration = self.file('helper.dyn', 'fn target() {}\n')
        text = 'fn main() { _ = "😀" target() }\n'
        main = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(declaration, declaration.read_text()), opened(main, text),
            request('textDocument/rename', {'textDocument': {'uri': declaration.as_uri()},
                'position': {'line': 0, 'character': 4}, 'newName': 'renamed'}, 42)])
        self.assertEqual(stderr, '')
        edits = next(r['result']['changes'] for r in responses if r.get('id') == 42)
        expected = len(text[:text.index('target')].encode('utf-16-le')) // 2
        self.assertEqual(edits[main.as_uri()][0]['range']['start']['character'], expected)

    def test_escaped_keys_and_negative_ids(self):
        responses, stderr = run_lsp([br'{"jsonrpc":"2.0","id":-42,"\u006dethod":"unknown/method","params":{}}'])
        self.assertEqual(stderr, '')
        self.assertTrue(any(r.get('id') == -42 and r.get('error', {}).get('code') == -32601 for r in responses))

    def test_semantic_tokens_use_utf16_after_non_bmp_text(self):
        text = 'fn main() { _ = "😀" const Thing: i32 = 42 _ = Thing }\n'
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text), request('textDocument/semanticTokens/full', {'textDocument': {'uri': path.as_uri()}}, 42)])
        self.assertEqual(stderr, '')
        data = next(r['result']['data'] for r in responses if r.get('id') == 42)
        row = column = 0
        found = []
        for i in range(0, len(data), 5):
            delta, offset, length, kind, modifiers = data[i:i+5]
            row += delta
            column = offset if delta else column + offset
            if row == 0 and length == 5 and modifiers & 1:
                found.append(column)
        expected = [len(text[:offset].encode('utf-16-le')) // 2 for offset in (text.index('Thing'), text.rindex('Thing'))]
        self.assertEqual(found, expected)

    def test_highlights_follow_local_bindings(self):
        text = 'fn first(value: i32) { _ = value }\nfn second(value: i32) { _ = value }\nfn main() { first(1) second(2) }\n'
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text), request('textDocument/documentHighlight', {
            'textDocument': {'uri': path.as_uri()}, 'position': {'line': 0, 'character': 10}}, 42)])
        self.assertEqual(stderr, '')
        highlights = next(r['result'] for r in responses if r.get('id') == 42)
        self.assertEqual(len(highlights), 2, highlights)
        self.assertTrue(all(h['range']['start']['line'] == 0 for h in highlights), highlights)

    def test_imported_rename_uses_original_identifier_ranges(self):
        helper = self.file('helper/helper.dyn', 'pub fn target() {}\n')
        text = 'use "./helper" h\nfn main() { h.target() }\n'
        main = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(main, text), request('textDocument/rename', {
            'textDocument': {'uri': main.as_uri()}, 'position': {'line': 1, 'character': 16}, 'newName': 'renamed'}, 42)])
        self.assertEqual(stderr, '')
        edits = next(r['result']['changes'] for r in responses if r.get('id') == 42)
        self.assertEqual(set(edits), {main.as_uri(), helper.as_uri()})
        for path in [main, helper]:
            source = path.read_text().splitlines(keepends=True)
            for edit in edits[path.as_uri()]:
                start, end = edit['range']['start'], edit['range']['end']
                self.assertEqual(start['line'], end['line'])
                self.assertEqual(source[start['line']][start['character']:end['character']], 'target')
                self.assertEqual(end['character'] - start['character'], 6)

    def test_imported_type_definition_has_original_range(self):
        helper = self.file('helper/helper.dyn', 'pub struct Item { value: i32 }\n')
        text = 'use "./helper" h\nfn main() { item := h.Item{ value: 42 } _ = item }\n'
        main = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(main, text), request('textDocument/typeDefinition', {
            'textDocument': {'uri': main.as_uri()}, 'position': {'line': 1, 'character': text.splitlines()[1].rindex('item')}}, 42)])
        self.assertEqual(stderr, '')
        result = next(r['result'] for r in responses if r.get('id') == 42)
        self.assertEqual(result['uri'], helper.as_uri())
        self.assertEqual(result['range']['end']['character'] - result['range']['start']['character'], 4)

    def test_folding_columns_use_utf16(self):
        text = 'fn main() { _ = "😀" if true {\n _ = 1\n}\n}\n'
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text), request('textDocument/foldingRange', {'textDocument': {'uri': path.as_uri()}}, 42)])
        self.assertEqual(stderr, '')
        folds = next(r['result'] for r in responses if r.get('id') == 42)
        first = text.splitlines()[0]
        expected = len(first[:first.rindex('{')].encode('utf-16-le')) // 2
        self.assertEqual(max(f['startCharacter'] for f in folds if f['startLine'] == 0), expected)

    def test_reordered_range_fields(self):
        path = self.file('main.dyn', 'fn main() { missing() }\n')
        responses, stderr = run_lsp([opened(path, path.read_text()), request('textDocument/didChange', {
            'textDocument': {'uri': path.as_uri(), 'version': 2},
            'contentChanges': [{'text': '', 'range': {'end': {'character': 21, 'line': 0}, 'start': {'character': 12, 'line': 0}}}]
        })])
        self.assertEqual(stderr, '')
        self.assertFalse(any(d.get('severity') == 1 for d in diagnostics(responses, path)), diagnostics(responses, path))

    def test_percent_encoded_uri(self):
        path = self.file('space dir/main.dyn', 'fn main() { sibling() }\n')
        self.file('space dir/helper.dyn', 'fn sibling() {}\n')
        responses, stderr = run_lsp([opened(path, path.read_text())])
        self.assertEqual(stderr, '')
        self.assertFalse(any(d.get('severity') == 1 for d in diagnostics(responses, path)), diagnostics(responses, path))

    def test_local_name_does_not_count_as_import_use(self):
        text = 'use "std/io"\nfn main() { io := 42 _ = io }\n'
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text)])
        self.assertEqual(stderr, '')
        self.assertTrue(any(d.get('code') == 'unused-use' for d in diagnostics(responses, path)), diagnostics(responses, path))

    def test_global_cycle_is_a_mapped_diagnostic(self):
        text = 'first: i32 = second\nsecond: i32 = first\nfn main() { _ = first }\n'
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text)])
        self.assertEqual(stderr, '')
        self.assertTrue(any('global initialization cycle' in d['message'] and d['range']['start']['line'] < 2 for d in diagnostics(responses, path)), diagnostics(responses, path))

    def test_sibling_update_preserves_syntax_error(self):
        broken = 'fn broken() {\n'
        path = self.file('broken.dyn', broken)
        good = 'pub fn helper() {}\n'
        sibling = self.file('helper.dyn', good)
        responses, stderr = run_lsp([opened(path, broken), opened(sibling, good)])
        self.assertEqual(stderr, '')
        self.assertTrue(any(d.get('code') == 'syntax' for d in diagnostics(responses, path)),
                        diagnostics(responses, path))

    def test_library_import_diagnostics(self):
        text = 'use "std/io"\npub struct Sink { writer: io.Writer }\n'
        path = self.file('library.dyn', text)
        checked = subprocess.run([DYN, 'check', str(self.root), '--quiet'], capture_output=True)
        self.assertEqual(checked.returncode, 0, checked.stderr.decode())
        responses, stderr = run_lsp([opened(path, text)])
        self.assertEqual(stderr, '')
        self.assertEqual(diagnostics(responses, path), [])

    def test_unopened_sibling_usage(self):
        text = 'const Answer: i32 = 42\nfn helper() i32 { return Answer }\n'
        path = self.file('values.dyn', text)
        self.file('main.dyn', 'fn main() { _ = helper() }\n')
        responses, stderr = run_lsp([opened(path, text)])
        self.assertEqual(stderr, '')
        self.assertEqual(diagnostics(responses, path), [])

    def test_speculative_import_errors_stay_in_protocol(self):
        text = 'use "./missing"\nfn main() {\n  item := missing.Value{}\n  item.\n}\n'
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text), request('textDocument/completion', {
            'textDocument': {'uri': path.as_uri()}, 'position': {'line': 3, 'character': 7}}, 2)])
        self.assertEqual(stderr, '')
        self.assertTrue(any(d.get('severity') == 1 for d in diagnostics(responses, path)))

    def test_request_for_unopened_document(self):
        path = self.root / 'missing.dyn'
        responses, stderr = run_lsp([request('textDocument/references', {
            'textDocument': {'uri': path.as_uri()}, 'position': {'line': 0, 'character': 0}}, 2)])
        self.assertEqual(stderr, '')
        self.assertIsNone(next(r['result'] for r in responses if r.get('id') == 2))

    def test_hover_isolated_from_other_projects(self):
        first = 'struct Item { first: i32 }\nfn main() { item := Item{} _ = item }\n'
        second = 'struct Item { second: bool }\nfn main() { item := Item{} _ = item }\n'
        one = self.file('one/main.dyn', first)
        two = self.file('two/main.dyn', second)
        responses, stderr = run_lsp([opened(one, first), opened(two, second), request('textDocument/hover', {
            'textDocument': {'uri': two.as_uri()}, 'position': {'line': 0, 'character': 8}}, 2)])
        self.assertEqual(stderr, '')
        hover = next(r['result']['contents']['value'] for r in responses if r.get('id') == 2)
        self.assertIn('second: bool', hover)
        self.assertNotIn('first: i32', hover)

    def test_batched_incremental_changes(self):
        text = 'const Count: i32 = 1\nfn main() { _ = Count }\n'
        path = self.file('main.dyn', text)
        changes = [
            {'range': {'start': {'line': 0, 'character': 6}, 'end': {'line': 0, 'character': 11}}, 'text': 'Value'},
            {'range': {'start': {'line': 1, 'character': 16}, 'end': {'line': 1, 'character': 21}}, 'text': 'Value'},
        ]
        responses, stderr = run_lsp([opened(path, text), request('textDocument/didChange', {
            'textDocument': {'uri': path.as_uri(), 'version': 2}, 'contentChanges': changes})])
        self.assertEqual(stderr, '')
        self.assertEqual(diagnostics(responses, path), [])

    def test_import_used_by_unopened_sibling(self):
        text = 'use "std/io"\n'
        path = self.file('imports.dyn', text)
        self.file('types.dyn', 'pub struct Sink { writer: io.Writer }\n')
        responses, stderr = run_lsp([opened(path, text)])
        self.assertEqual(stderr, '')
        self.assertEqual(diagnostics(responses, path), [])

    def test_unsaved_sibling_declaration(self):
        text = 'fn main() { _ = answer() }\n'
        path = self.file('main.dyn', text)
        sibling = self.root / 'unsaved.dyn'
        responses, stderr = run_lsp([opened(path, text), opened(sibling, 'fn answer() i32 { return 42 }\n')])
        self.assertEqual(stderr, '')
        self.assertEqual(diagnostics(responses, path), [])
        self.assertEqual(diagnostics(responses, sibling), [])

    def test_close_removes_unsaved_declarations(self):
        text = 'fn main() { _ = answer() }\n'
        path = self.file('main.dyn', text)
        sibling = self.root / 'unsaved.dyn'
        responses, stderr = run_lsp([opened(path, text), opened(sibling, 'fn answer() i32 { return 42 }\n'),
            request('textDocument/didClose', {'textDocument': {'uri': sibling.as_uri()}})])
        self.assertEqual(stderr, '')
        self.assertTrue(any(d['message'] == 'unknown function' for d in diagnostics(responses, path)))
        self.assertEqual(diagnostics(responses, sibling), [])

    def test_unicode_json_source(self):
        text = 'const Message: []const u8 = "π😀"\nfn main() { _ = Message }\n'
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text)])
        self.assertEqual(stderr, '')
        self.assertEqual(diagnostics(responses, path), [])

    def test_many_unused_declarations(self):
        text = ''.join(f'const Value{i}: i32 = {i}\n' for i in range(400))
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text)])
        self.assertEqual(stderr, '')
        self.assertTrue(diagnostics(responses, path))

    def test_const_declaration_tokens(self):
        text = 'const Answer: i32 = 42\nfn main() { _ = Answer }\n'
        path = self.file('main.dyn', text)
        responses, stderr = run_lsp([opened(path, text), request('textDocument/semanticTokens/full', {
            'textDocument': {'uri': path.as_uri()}}, 2)])
        self.assertEqual(stderr, '')
        legend = next(r['result']['capabilities']['semanticTokensProvider']['legend']
                      for r in responses if r.get('id') == 1)
        self.assertIn('readonly', legend['tokenModifiers'])
        data = next(r['result']['data'] for r in responses if r.get('id') == 2)
        line = column = 0
        readonly_answers = 0
        for index in range(0, len(data), 5):
            dl, dc, length, kind, modifiers = data[index:index + 5]
            line += dl
            column = dc if dl else column + dc
            if text.splitlines()[line][column:column + length] == 'Answer':
                self.assertEqual(length, 6)
                self.assertTrue(modifiers & (1 << legend['tokenModifiers'].index('readonly')))
                readonly_answers += 1
        self.assertEqual(readonly_answers, 2)


    def test_import_edit_uses_identifier_start_and_one_wire_conversion(self):
        text = 'fn main() { /* 😀 */ _ = OpenResult{} }\n'
        path = self.file('main.dyn', text)
        before = text[:text.index('OpenResult')]
        for encoding in ['utf-16', 'utf-8']:
            start = len(before.encode('utf-16-le')) // 2 if encoding == 'utf-16' else len(before.encode())
            for inside in [0, 3]:
                point = {'line': 0, 'character': start + inside}
                responses, stderr = run_lsp([opened(path, text), request('textDocument/codeAction', {
                    'textDocument': {'uri': path.as_uri()}, 'range': {'start': point, 'end': point},
                    'context': {'diagnostics': [{'message': 'unknown name'}]}}, 2)],
                    {'capabilities': {'general': {'positionEncodings': [encoding]}}})
                self.assertEqual(stderr, '')
                actions = next(r['result'] for r in responses if r.get('id') == 2)
                action = next(a for a in actions if a['title'] == 'Import OpenResult from std/dynlib')
                edit = next(e for e in action['edit']['changes'][path.as_uri()] if e['newText'] == 'dynlib.OpenResult')
                self.assertEqual(edit['range'], {'start': {'line': 0, 'character': start},
                                                'end': {'line': 0, 'character': start + len('OpenResult')}})

    def test_identical_edits_reuse_analysis_and_real_edits_reuse_disk_syntax(self):
        from unittest.mock import patch
        import re
        self.file('library/module.dyn', 'pub fn answer() i32 { return 42 }\n')
        text = 'use "./library" lib\nfn main() { _ = lib.answer() }\n'
        path = self.file('main.dyn', text)
        def change(value, version):
            return request('textDocument/didChange', {'textDocument': {'uri': path.as_uri(), 'version': version},
                           'contentChanges': [{'text': value}]})
        with patch.dict(os.environ, {'DYN_LSP_ANALYSIS_STATS': '1'}):
            responses, stderr = run_lsp([opened(path, text), change(text, 2),
                                        change(text, 3), change(text+'// actual edit\n', 4)])
        counts = re.search(r'analysis-cache hits=(\d+) misses=(\d+) syntax-hits=(\d+) syntax-misses=(\d+)', stderr)
        self.assertIsNotNone(counts, stderr)
        self.assertEqual(int(counts[2]), 0, stderr)
        modules = re.search(r'module-analysis hits=(\d+) misses=(\d+)', stderr)
        self.assertIsNotNone(modules, stderr)
        self.assertEqual(int(modules[2]), 3, stderr)
        self.assertGreaterEqual(int(modules[1]), 1, stderr)
        interfaces = re.search(r'interface-cache hits=(\d+) misses=(\d+)', stderr)
        self.assertIsNotNone(interfaces, stderr)
        self.assertEqual(int(interfaces[2]), 3, stderr)
        self.assertGreaterEqual(int(interfaces[1]), 1, stderr)
        self.assertGreaterEqual(int(counts[3]), 2, stderr)
        self.assertEqual(diagnostics(responses, path), [])

    def test_module_semantics_retain_unaffected_results(self):
        from unittest.mock import patch
        import re
        library = self.file('library/module.dyn', 'pub fn answer() i32 { return 41 }\n')
        self.file('other/module.dyn', 'pub fn zero() i32 { return 0 }\n')
        text = 'use "./library" lib\nuse "./other" o\nfn main() { _ = lib.answer() _ = o.zero() }\n'
        path = self.file('main.dyn', text)
        def change(value, version):
            return request('textDocument/didChange', {'textDocument': {'uri': library.as_uri(), 'version': version},
                           'contentChanges': [{'text': value}]})
        def barrier(ident):
            return request('textDocument/documentSymbol', {'textDocument': {'uri': path.as_uri()}}, ident)
        with patch.dict(os.environ, {'DYN_LSP_ANALYSIS_STATS': '1'}):
            messages, stderr = run_lsp([opened(path, text), opened(library, library.read_text()), barrier(10),
                change('pub fn answer() i32 { return 42 }\n', 2), barrier(11),
                change('pub fn answer() i64 { return 42 }\n', 3), barrier(12)])
        counts = re.search(r'module-analysis hits=(\d+) misses=(\d+)', stderr)
        self.assertIsNotNone(counts, stderr)
        self.assertEqual(int(counts[2]), 6, stderr)
        self.assertGreaterEqual(int(counts[1]), 6, stderr)
        self.assertEqual(diagnostics(messages, path), [])


if __name__ == '__main__':
    unittest.main()
