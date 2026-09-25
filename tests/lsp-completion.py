#!/usr/bin/env python3
"""Completion coverage for builtins, package paths, and expression results."""
import json
import os
import subprocess
from pathlib import Path

root = Path("tests/lsp-completion").resolve()
uri = "file://" + str(root / "main.dyn")
base = (root / "main.dyn").read_text()
texts = {
    "builtins": base,
    "imports": 'use "std/io"\nfn main() {}\n',
    "imports_std": 'use "std/io"\nfn main() {}\n',
    "imports_std_net": 'use "std/net/http"\nfn main() {}\n',
    "imports_vendor": 'use "vendor/sqlite"\nfn main() {}\n',
    "imports_relative": 'use "./local"\nfn main() {}\n',
    "locals": base.replace("_ = opened.ok", "_ = ope"),
    "local": base.replace("_ = opened.ok", "opened."),
    "result": base.replace("_ = opened.ok", '_ = sqlite.open(":memory:", storage[..]).'),
    "if_local": base.replace("_ = opened.ok", "if ope"),
    "if_field": base.replace("_ = opened.ok", "if opened."),
    "for_local": base.replace("_ = opened.ok", "for ope"),
    "for_field": base.replace("_ = opened.ok", "for opened."),
    "if_body": base.replace("_ = opened.ok", "if opened.ok {\n    ope\n  }"),
    "for_body": base.replace("_ = opened.ok", "for item in storage {\n    ite\n  }"),
    "after_scope": base.replace("_ = opened.ok", "if opened.ok {\n    hidden := opened\n  }\n  hid"),
    "struct_fields": base.replace('opened := sqlite.open(":memory:", storage[..])',
                                  "opened := sqlite.OpenResult{ }")
                         .replace("_ = opened.ok", "_ = opened.ok"),
    "enum_variants": "enum Choice { One, Two: i32 }\nfn main() {\n  value := Choice.\n}\n",
    "expected_enum": "enum Choice { One, Two: i32 }\nfn main() {\n  value: Choice = O\n}\n",
    "expected_return": "enum Choice { One, Two: i32 }\nfn pick() Choice {\n  return O\n}\n",
    "expected_argument": "enum Choice { One, Two: i32 }\nfn take(value: Choice) {}\nfn main() {\n  take(O\n}\n",
    "auto_import": "fn main() {\n  OpenR\n}\n",
    "underscore_local": "fn main() {\n  name_storage: [32]u8 = []\n  name_\n}\n",
    "incomplete_call_local": "fn consume(value: []u8) {}\nfn main() {\n  name_storage: [32]u8 = []\n  consume(name_\n}\n",
}

messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"rootUri": "file://" + str(root)}}]
messages.append({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
    "textDocument": {"uri": "file:///external/package/module.dyn", "languageId": "dyn",
                     "version": 1, "text": "fn private_foreign() {}\npub fn public_foreign() {}\n"}}})
version = 1
messages.append({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
    "textDocument": {"uri": uri, "languageId": "dyn", "version": version, "text": texts["builtins"]}}})
messages.append({"jsonrpc": "2.0", "id": 2, "method": "textDocument/completion", "params": {
    "textDocument": {"uri": uri}, "position": {"line": 2, "character": 0}}})
for request_id, key, line, character in ((3, "imports", 0, 5), (4, "locals", 5, 9),
                                         (5, "local", 5, 9), (6, "result", 5, 50),
                                         (7, "if_local", 5, 8), (8, "if_field", 5, 12),
                                         (9, "for_local", 5, 9), (10, "for_field", 5, 13),
                                         (11, "if_body", 6, 7), (12, "for_body", 6, 7),
                                         (13, "imports_std", 0, 9),
                                         (14, "imports_std_net", 0, 13),
                                         (15, "imports_vendor", 0, 12),
                                         (16, "imports_relative", 0, 7),
                                         (17, "after_scope", 8, 5),
                                         (19, "struct_fields", 4, 31),
                                         (21, "enum_variants", 2, 18),
                                         (22, "expected_enum", 2, 19),
                                         (27, "expected_return", 2, 10),
                                         (28, "expected_argument", 3, 8),
                                         (30, "underscore_local", 2, 7),
                                         (31, "incomplete_call_local", 3, 15),
                                         (25, "auto_import", 1, 7)):
    version += 1
    messages.append({"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
        "textDocument": {"uri": uri, "version": version},
        "contentChanges": [{"text": texts[key]}]}})
    messages.append({"jsonrpc": "2.0", "id": request_id, "method": "textDocument/completion",
                     "params": {"textDocument": {"uri": uri},
                                "position": {"line": line, "character": character}}})
version += 1
messages.append({"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
    "textDocument": {"uri": uri, "version": version}, "contentChanges": [{"text":
        "struct Point { x: i32, name: []const u8, }\nfn main() {\n  p := Point{ x: 1 }\n}\n"}]}})
messages.append({"jsonrpc": "2.0", "id": 29, "method": "textDocument/codeAction", "params": {
    "textDocument": {"uri": uri}, "range": {"start": {"line": 2, "character": 13},
                                                   "end": {"line": 2, "character": 13}},
    "context": {"diagnostics": []}}})
messages += [{"jsonrpc": "2.0", "id": 23, "method": "workspace/symbol",
              "params": {"query": "Local"}},
             {"jsonrpc": "2.0", "id": 26, "method": "shutdown", "params": None},
             {"jsonrpc": "2.0", "method": "exit", "params": None}]

wire = b"".join((lambda body: b"Content-Length: %d\r\n\r\n" % len(body) + body)(
    json.dumps(message, separators=(",", ":")).encode()) for message in messages)
environment = os.environ.copy()
environment["DYN_SDK"] = str(Path("compiler").resolve())
process = subprocess.run([os.environ.get("DYN", "./build/dyn"), "lsp"], input=wire,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=environment, check=True)
assert not process.stderr, process.stderr.decode()

responses = {}
offset = 0
while offset < len(process.stdout):
    end = process.stdout.index(b"\r\n\r\n", offset)
    length = int(process.stdout[offset:end].split(b":", 1)[1])
    start = end + 4
    blob = process.stdout[start:start + length]
    try:
        message = json.loads(blob)
    except json.JSONDecodeError as error:
        raise AssertionError(blob[max(0, error.pos - 120):error.pos + 120]) from error
    offset = start + length
    if "id" in message:
        responses[message["id"]] = message.get("result")

labels = lambda request_id: {item["label"] for item in responses[request_id]}
assert len(responses[2]) == len(labels(2)), responses[2]
assert "private_foreign" not in labels(2) and "public_foreign" not in labels(2)
assert {"#alignof", "#bitcast", "#cast", "#len", "#link", "#panic", "#sizeof",
        "#syscall", "#target", "#typeof"} <= labels(2)
assert {"std", "vendor", "local", "."} <= labels(3), sorted(labels(3))
assert "std/io" not in labels(3)
assert {"database", "code", "ok"} <= labels(5), sorted(labels(5))
assert {"database", "code", "ok"} <= labels(6), sorted(labels(6))
assert {"storage", "opened"} <= labels(4), sorted(labels(4))
details = {item["label"]: item.get("detail") for item in responses[4]}
assert next(item for item in responses[4] if item["label"] == "opened")["sortText"].startswith("0_")
assert details["storage"] == "[64]u8"
assert details["opened"] == "OpenResult"
assert "opened" in labels(7), sorted(labels(7))
assert {"database", "code", "ok"} <= labels(8), sorted(labels(8))
assert "opened" in labels(9), sorted(labels(9))
assert {"database", "code", "ok"} <= labels(10), sorted(labels(10))
assert "opened" in labels(11), sorted(labels(11))
assert "item" in labels(12), sorted(labels(12))
assert {"io", "net", "crypto"} <= labels(13), sorted(labels(13))
assert {"http", "tls", "url"} <= labels(14), sorted(labels(14))
assert {"sqlite", "openssl", "sdl3"} <= labels(15), sorted(labels(15))
assert "local" in labels(16), sorted(labels(16))
assert "opened" in labels(17), sorted(labels(17))
assert "hidden" not in labels(17), sorted(labels(17))
assert {"database", "code", "ok"} <= labels(19), sorted(labels(19))
assert {"One", "Two"} <= labels(21), sorted(labels(21))
two = next(item for item in responses[21] if item["label"] == "Two")
assert two["insertText"] == "Two(${1:value})"
expected_one = next(item for item in responses[22] if item["label"] == "One")
assert expected_one["insertText"] == "Choice.One"
expected_two = next(item for item in responses[22] if item["label"] == "Two")
assert expected_two["insertText"] == "Choice.Two(${1:value})"
assert next(item for item in responses[27] if item["label"] == "One")["insertText"] == "Choice.One"
assert next(item for item in responses[28] if item["label"] == "Two")["insertText"] == "Choice.Two(${1:value})"
assert any(item["name"] == "Local" and item["location"]["uri"].endswith("/local/module.dyn")
           for item in responses[23]), responses[23]
auto = next(item for item in responses[25]
            if item["label"] == "OpenResult" and item["detail"] == "auto import vendor/sqlite")
assert auto["insertText"] == "sqlite.OpenResult"
assert auto["additionalTextEdits"][0]["newText"] == 'use "vendor/sqlite"\n'
assert "name_storage" in labels(30), responses[30]
assert "name_storage" in labels(31), responses[31]
fill = responses[29][0]
assert fill["title"] == "Fill missing struct fields"
assert fill["edit"]["changes"][uri][0]["newText"] == ', name: ""'

# Accepting a path segment must leave slash insertion to the user.
for request_id in (3, 13, 14, 15, 16):
    for item in responses[request_id]:
        assert not item.get("insertText", item["label"]).endswith("/"), item
