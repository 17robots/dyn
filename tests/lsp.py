#!/usr/bin/env python3
"""Deterministic stdio protocol coverage for Dyn's bounded LSP document state."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

temporary = tempfile.TemporaryDirectory(prefix="dyn-lsp-protocol-")
import_path = Path(temporary.name) / "imports" / "main.dyn"
import_error_path = Path(temporary.name) / "errors" / "main.dyn"
for path in (import_path, import_error_path):
    path.parent.mkdir()
    path.write_text("")
import_uri = import_path.as_uri()
import_error_uri = import_error_path.as_uri()
public_struct_path = os.path.join(os.getcwd(), "tests", "lsp-public-struct", "main.dyn")
public_struct_uri = "file://" + public_struct_path
public_struct_text = open(public_struct_path, encoding="utf-8").read()
unresolved_struct_path = os.path.join(os.getcwd(), "tests", "lsp-unresolved-same-struct", "module.dyn")
unresolved_struct_uri = "file://" + unresolved_struct_path
unresolved_struct_text = open(unresolved_struct_path, encoding="utf-8").read()
same_struct_path = os.path.join(os.getcwd(), "tests", "import-same-struct", "main.dyn")
same_struct_uri = "file://" + same_struct_path
same_struct_text = open(same_struct_path, encoding="utf-8").read()
bufio_path = os.path.join(os.getcwd(), "compiler", "std", "bufio", "bufio.dyn")
bufio_uri = "file://" + bufio_path
bufio_text = open(bufio_path, encoding="utf-8").read()

def bufio_position(name):
    offset = bufio_text.index(name) + 3
    return {"line": bufio_text.count("\n", 0, offset),
            "character": offset - bufio_text.rfind("\n", 0, offset) - 1}

messages = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
        "uri": "file:///work/main.dyn", "languageId": "dyn", "version": 1,
        "text": "fn main() {\n  count := helper(2)\n  _ = count\n  point := Point{ x: 1, name: \"a\" }\n  _ = point.x\n}\n"}}},
    {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
        "uri": "file:///work/helper.dyn", "languageId": "dyn", "version": 1,
        "text": "fn helper(value: i32) i32 { return value }\nstruct Point { x: i32, name: []const u8, }\nfn pair(x, y: i32) i32 { return x + y }\n"}}},
    {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 1, "character": 12}}},
    {"jsonrpc": "2.0", "id": 3, "method": "textDocument/definition", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 1, "character": 12}}},
    {"jsonrpc": "2.0", "id": 5, "method": "textDocument/references", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 1, "character": 12}, "context": {"includeDeclaration": True}}},
    {"jsonrpc": "2.0", "id": 6, "method": "textDocument/rename", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 1, "character": 12}, "newName": "renamed"}},
    {"jsonrpc": "2.0", "id": 7, "method": "textDocument/signatureHelp", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 1, "character": 19}}},
    {"jsonrpc": "2.0", "id": 8, "method": "textDocument/completion", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 0, "character": 3}}},
    {"jsonrpc": "2.0", "id": 9, "method": "textDocument/hover", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"character": 7, "line": 2}}},
    {"jsonrpc": "2.0", "id": 10, "method": "textDocument/definition", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 2, "character": 7}}},
    {"jsonrpc": "2.0", "id": 11, "method": "textDocument/hover", "params": {
        "textDocument": {"uri": "file:///work/helper.dyn"}, "position": {"line": 0, "character": 4}}},
    {"jsonrpc": "2.0", "id": 15, "method": "textDocument/hover", "params": {
        "textDocument": {"uri": "file:///work/helper.dyn"}, "position": {"line": 1, "character": 8}}},
    {"jsonrpc": "2.0", "id": 16, "method": "textDocument/documentSymbol", "params": {
        "textDocument": {"uri": "file:///work/helper.dyn"}}},
    {"jsonrpc": "2.0", "id": 17, "method": "textDocument/formatting", "params": {
        "textDocument": {"uri": "file:///work/helper.dyn"}, "options": {"tabSize": 2, "insertSpaces": True}}},
    {"jsonrpc": "2.0", "id": 18, "method": "textDocument/inlayHint", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "range": {"start": {"line": 0, "character": 0}, "end": {"line": 3, "character": 0}}}},
    {"jsonrpc": "2.0", "id": 19, "method": "textDocument/signatureHelp", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 1, "character": 19}}},
    {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
        "uri": import_uri, "languageId": "dyn", "version": 1,
        "text": "use \"std/io\"\nuse \"std/math\" math\nfn demo() {\n  #panic(\"x\")\n  io.println(\"x\")\n}\n"}}},
    {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
        "uri": import_error_uri, "languageId": "dyn", "version": 1,
        "text": "use \"std/io\"\nfn demo() {\n  io.println(OpenResult)\n}\n"}}},
    {"jsonrpc": "2.0", "id": 12, "method": "textDocument/definition", "params": {
        "textDocument": {"uri": import_uri}, "position": {"line": 0, "character": 8}}},
    {"jsonrpc": "2.0", "id": 13, "method": "textDocument/definition", "params": {
        "textDocument": {"uri": import_uri}, "position": {"line": 4, "character": 6}}},
    {"jsonrpc": "2.0", "id": 14, "method": "textDocument/completion", "params": {
        "textDocument": {"uri": import_uri}, "position": {"line": 4, "character": 5}}},
    {"jsonrpc": "2.0", "id": 20, "method": "textDocument/hover", "params": {
        "textDocument": {"uri": import_uri}, "position": {"line": 4, "character": 6}}},
    {"jsonrpc": "2.0", "id": 27, "method": "textDocument/hover", "params": {
        "textDocument": {"uri": import_uri}, "position": {"line": 3, "character": 4}}},
    {"jsonrpc": "2.0", "id": 26, "method": "textDocument/signatureHelp", "params": {
        "textDocument": {"uri": import_uri}, "position": {"line": 4, "character": 13}}},
    {"jsonrpc": "2.0", "id": 42, "method": "textDocument/codeAction", "params": {
        "textDocument": {"uri": import_error_uri}, "range": {"start": {"line": 2, "character": 13}, "end": {"line": 2, "character": 23}},
        "context": {"diagnostics": [{"message": "unknown name"}]}}},
    {"jsonrpc": "2.0", "id": 21, "method": "workspace/symbol", "params": {"query": "Point"}},
    {"jsonrpc": "2.0", "id": 22, "method": "textDocument/codeAction", "params": {
        "textDocument": {"uri": import_uri}, "range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 19}}, "context": {"diagnostics": [{"code": "unused-use"}]}}},
    {"jsonrpc": "2.0", "id": 23, "method": "textDocument/semanticTokens/full", "params": {
        "textDocument": {"uri": "file:///work/helper.dyn"}}},
    {"jsonrpc": "2.0", "id": 24, "method": "textDocument/rename", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 2, "character": 7}, "newName": "result"}},
    {"jsonrpc": "2.0", "id": 25, "method": "textDocument/completion", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 4, "character": 12}}},
    {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
        "uri": public_struct_uri, "languageId": "dyn", "version": 1,
        "text": public_struct_text}}},
    {"jsonrpc": "2.0", "id": 28, "method": "textDocument/completion", "params": {
        "textDocument": {"uri": public_struct_uri}, "position": {"line": 3, "character": 20}}},
    {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
        "uri": unresolved_struct_uri, "languageId": "dyn", "version": 1,
        "text": unresolved_struct_text}}},
    {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
        "uri": same_struct_uri, "languageId": "dyn", "version": 1,
        "text": same_struct_text}}},
    {"jsonrpc": "2.0", "id": 29, "method": "textDocument/hover", "params": {
        "textDocument": {"uri": same_struct_uri}, "position": {"line": 2, "character": 9}}},
    {"jsonrpc": "2.0", "id": 30, "method": "textDocument/hover", "params": {
        "textDocument": {"uri": same_struct_uri}, "position": {"line": 3, "character": 22}}},
    {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
        "uri": bufio_uri, "languageId": "dyn", "version": 1, "text": bufio_text}}},
    {"jsonrpc": "2.0", "id": 31, "method": "textDocument/hover", "params": {
        "textDocument": {"uri": bufio_uri}, "position": bufio_position("io.Writer")}},
    {"jsonrpc": "2.0", "id": 32, "method": "textDocument/hover", "params": {
        "textDocument": {"uri": bufio_uri}, "position": bufio_position("io.Reader")}},
    {"jsonrpc": "2.0", "id": 33, "method": "textDocument/documentHighlight", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 4, "character": 7}}},
    {"jsonrpc": "2.0", "id": 34, "method": "textDocument/foldingRange", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}}},
    {"jsonrpc": "2.0", "id": 35, "method": "textDocument/selectionRange", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "positions": [{"line": 4, "character": 7}]}},
    {"jsonrpc": "2.0", "id": 36, "method": "textDocument/prepareRename", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 4, "character": 7}}},
    {"jsonrpc": "2.0", "id": 38, "method": "textDocument/typeDefinition", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 4, "character": 7}}},
    {"jsonrpc": "2.0", "id": 39, "method": "textDocument/declaration", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 1, "character": 12}}},
    {"jsonrpc": "2.0", "id": 40, "method": "textDocument/implementation", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 1, "character": 12}}},
    {"jsonrpc": "2.0", "id": 41, "method": "textDocument/inlayHint", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "range": {"start": {"line": 3, "character": 0}, "end": {"line": 4, "character": 99}}}},
    {"jsonrpc": "2.0", "id": 44, "method": "textDocument/prepareCallHierarchy", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 1, "character": 12}}},
    {"jsonrpc": "2.0", "id": 45, "method": "callHierarchy/incomingCalls", "params": {
        "item": {"data": "1|file:///work/main.dyn"}}},
    {"jsonrpc": "2.0", "id": 46, "method": "callHierarchy/outgoingCalls", "params": {
        "item": {"data": "0|file:///work/main.dyn"}}},
    {"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
        "textDocument": {"uri": "file:///work/main.dyn", "version": 2},
        "contentChanges": [{"range": {"start": {"line": 1, "character": 2},
                                        "end": {"line": 1, "character": 7}},
                            "text": "total"}]}},
    {"jsonrpc": "2.0", "id": 37, "method": "textDocument/documentHighlight", "params": {
        "textDocument": {"uri": "file:///work/main.dyn"}, "position": {"line": 1, "character": 4}}},
    {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
        "uri": "file:///work/incomplete.dyn", "languageId": "dyn", "version": 1,
        "text": "fn unfinished(value: i32)\n"}}},
    {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
        "uri": "file:///work/incomplete-call.dyn", "languageId": "dyn", "version": 1,
        "text": "fn main() {\n  helper(1,\n"}}},
    {"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
        "textDocument": {"uri": "file:///work/main.dyn", "version": 3},
        "contentChanges": [{"text": "fn main() { missing() }\n"}]}},
    {"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": None},
    {"jsonrpc": "2.0", "method": "exit", "params": None},
]
wire = b"".join((lambda b: b"Content-Length: %d\r\n\r\n" % len(b) + b)(
    json.dumps(message, separators=(",", ":")).encode()) for message in messages)
environment = os.environ.copy()
environment["DYN_SDK"] = os.path.join(os.getcwd(), "compiler")
process = subprocess.run([os.environ.get("DYN", "./build/dyn"), "lsp"], input=wire,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, check=True)
result = process.stdout.decode()
assert not process.stderr, process.stderr.decode()
assert "import './missing' does not resolve inside project root" in result
assert '"textDocumentSync":{"openClose":true,"change":2}' in result
assert '"hoverProvider":true' in result
assert '"semanticTokensProvider":' in result and '"positionEncoding":"utf-16"' in result
assert '"documentHighlightProvider":true' in result
assert '"foldingRangeProvider":true' in result
assert '"selectionRangeProvider":true' in result
assert '"renameProvider":{"prepareProvider":true}' in result
assert '"typeDefinitionProvider":true' in result
assert '"declarationProvider":true' in result and '"implementationProvider":true' in result
assert '"callHierarchyProvider":true' in result
assert '"triggerCharacters":[".","/","#","\\\"","_","a"' in result
assert '"value":"fn helper(value: i32) i32"' in result
assert '"line":0,"character":3' in result
assert '"uri":"file:///work/helper.dyn"' in result
assert '"id":5,"result":[' in result
assert '"id":6,"result":{"changes":{' in result and '"newText":"renamed"' in result
assert '"id":7,"result":{"signatures":[{"label":"fn helper(value: i32) i32"}]' in result
assert '"id":8,"result":[' in result and '"label":"helper"' in result
assert '"insertText":"helper(${1:value})","insertTextFormat":2' in result
assert '"detail":"fn helper(value: i32) i32"' in result
assert '"label":"#panic","kind":3,"detail":"#panic(message: []const u8) -> never"' in result
assert '"insertText":"#panic(${1:message})","insertTextFormat":2' in result
assert '"label":"#cast","kind":3,"detail":"#cast(type) value -> type"' in result
assert '"insertText":"#cast(${1:type}) ${2:value}"' in result
assert '"label":"#syscall","kind":3' in result
completion_8 = result[result.find('"id":8'):result.find('"id":8') + 20000]
assert completion_8.count('"label":"main"') == 1
assert '"id":9,"result":{"contents":{"kind":"plaintext","value":"variable count: i32"}}' in result
assert '"id":10,"result":{"uri":"file:///work/main.dyn","range":{"start":{"line":1,"character":2}' in result
assert result.count('"value":"fn helper(value: i32) i32"') >= 2
assert '"id":15,"result":{"contents":{"kind":"plaintext","value":"struct Point {\\n  x: i32\\n  name: []const u8\\n}"}}' in result
assert '"id":16,"result":[' in result and '"name":"Point","kind":23' in result
assert '"id":17,"result":[' in result and '"newText":' in result
assert '"id":18,"result":[' in result and '"label":": i32"' in result
assert '"label":"value:","kind":2' in result
assert '"id":19,"result":{"signatures":[' in result and '"activeParameter":0' in result
assert '"code":"unused-use","message":"unused use \'std/math\' (alias \'math\')"' in result
assert '"message":"unreachable statement"' in result
publications = []
responses = {}
wire_output = process.stdout
while wire_output:
    header, wire_output = wire_output.split(b"\r\n\r\n", 1)
    length = int(header.split(b":", 1)[1])
    publication = json.loads(wire_output[:length])
    if "id" in publication:
        responses[publication["id"]] = publication
    wire_output = wire_output[length:]
    if publication.get("method") == "textDocument/publishDiagnostics":
        publications.append(publication["params"])
assert any(item["message"] == "unknown name" and item["range"]["start"] == {"line": 2, "character": 13}
           for publication in publications if publication["uri"] == import_error_uri
           for item in publication["diagnostics"])
assert '"id":12,"result":{"uri":"file://' in result and '/compiler/std/io/' in result
assert '"id":13,"result":{"uri":"file://' in result and '/compiler/std/io/io.dyn"' in result
assert '"id":14,"result":[' in result and '"label":"println"' in result
assert '"insertText":"println(${1:writer}, ${2:template}, ${3:arguments})","insertTextFormat":2' in result
assert '"id":20,"result":{"contents":{"kind":"plaintext","value":"pub fn println(writer: Writer, template: []const u8, arguments: ...any) Result"}}' in result
assert '"id":27,"result":{"contents":{"kind":"plaintext","value":"#panic(message: []const u8) -> never\\nRuns active defers, prints a stack trace, and terminates execution."}}' in result
assert '"id":26,"result":{"signatures":[{"label":"pub fn println(writer: Writer, template: []const u8, arguments: ...any) Result"}]' in result
assert '"id":21,"result":[' in result and '"name":"Point"' in result
assert '"id":22,"result":[{"title":"Remove unused use"' in result and '"code":"unused-use"' in result
titles_42 = [action["title"] for action in responses[42]["result"]]
assert titles_42 == sorted(set(titles_42))
assert "Import OpenResult from std/fs/watch" in titles_42
assert not any(action["isPreferred"] for action in responses[42]["result"])
action_42 = next(action for action in responses[42]["result"]
                 if action["title"] == "Import OpenResult from std/dynlib")
new_texts = [edit["newText"] for edits in action_42["edit"]["changes"].values() for edit in edits]
assert any('use "std/dynlib"\n' in text for text in new_texts)
assert 'dynlib.OpenResult' in new_texts
assert '"id":23,"result":{"data":[' in result
assert '"id":24,"result":{"changes":{"file:///work/main.dyn":[' in result
assert '"id":25,"result":[' in result and '"label":"x","kind":5,"detail":"i32"' in result
assert ('"uri":"' + public_struct_uri + '","diagnostics":[]') in result
assert '"id":28,"result":[' in result and '"label":"View","kind":22,"detail":"struct"' in result
assert 'struct contains itself by value' not in result
assert '"id":29,"result":{"contents":{"kind":"plaintext","value":"struct Writer {\\n  destination: stream.Writer\\n}"}}' in result
assert '"id":30,"result":{"contents":{"kind":"plaintext","value":"pub struct Writer {\\n  descriptor: isize\\n}"}}' in result
assert '"id":31,"result":{"contents":{"kind":"plaintext","value":"pub struct Writer {\\n  data: rawptr\\n  write: *fn(rawptr, []const u8) Result\\n}"}}' in result
assert '"id":32,"result":{"contents":{"kind":"plaintext","value":"pub struct Reader {\\n  data: rawptr\\n  read: *fn(rawptr, []u8) Result\\n}"}}' in result
assert '"id":33,"result":[' in result and '"kind":2' in result
assert '"id":34,"result":[' in result and '"startLine":0' in result
assert '"id":35,"result":[{"range":' in result and '"parent":' in result
assert '"id":36,"result":{"range":' in result and '"placeholder":"point"' in result
assert '"id":37,"result":[{"range":{"start":{"line":1,"character":2},"end":{"line":1,"character":7}' in result
assert '"id":38,"result":{"uri":"file:///work/helper.dyn","range":{"start":{"line":1,"character":7}' in result, result[result.find('"id":38'):result.find('"id":38')+300]
assert '"id":39,"result":{"uri":"file:///work/helper.dyn"' in result
assert '"id":40,"result":{"uri":"file:///work/helper.dyn"' in result
assert '"id":44,"result":[{"name":"helper"' in result
assert '"id":45,"result":[{"from":{"name":"main"' in result
assert '"id":46,"result":[{"to":{"name":"helper"' in result
range_hints = result[result.find('"id":41'):result.find('"id":41') + 500]
assert '"label":": Point"' in range_hints and '"label":"value:"' not in range_hints
assert '"insertText":"pair(${1:x}, ${2:y})"' in result
assert '"code":"syntax"' in result and '"message":"incomplete function declaration; expected a function body"' in result
assert '"message":"incomplete function call; expected \')\'"' in result
assert '"method":"textDocument/publishDiagnostics"' in result
assert ('unknown name' in result or 'unknown function' in result)
assert '"id":4,"result":null' in result
