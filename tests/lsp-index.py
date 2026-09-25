#!/usr/bin/env python3
"""Disk-backed LSP index coverage."""
import json
import os
from pathlib import Path
import subprocess

root = Path("tests/lsp-index").resolve()
main = root / "main.dyn"
uri = "file://" + str(main)
messages = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"rootUri": "file://" + str(root)}},
    {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
        "textDocument": {"uri": uri, "languageId": "dyn", "version": 1,
                         "text": main.read_text()}}},
    {"jsonrpc": "2.0", "id": 2, "method": "textDocument/references", "params": {
        "textDocument": {"uri": uri}, "position": {"line": 2, "character": 4},
        "context": {"includeDeclaration": True}}},
    {"jsonrpc": "2.0", "id": 3, "method": "textDocument/rename", "params": {
        "textDocument": {"uri": uri}, "position": {"line": 2, "character": 4},
        "newName": "renamed_shared"}},
    {"jsonrpc": "2.0", "id": 5, "method": "textDocument/references", "params": {
        "textDocument": {"uri": uri}, "position": {"line": 4, "character": 39},
        "context": {"includeDeclaration": True}}},
    {"jsonrpc": "2.0", "id": 6, "method": "textDocument/rename", "params": {
        "textDocument": {"uri": uri}, "position": {"line": 4, "character": 39},
        "newName": "renamed_exported"}},
    {"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": None},
    {"jsonrpc": "2.0", "method": "exit", "params": None},
]
wire = b"".join((lambda body: b"Content-Length: %d\r\n\r\n" % len(body) + body)(
    json.dumps(message, separators=(",", ":")).encode()) for message in messages)
process = subprocess.run([os.environ.get("DYN", "./build/dyn"), "lsp"], input=wire,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
assert not process.stderr, process.stderr.decode()
responses = {}
offset = 0
while offset < len(process.stdout):
    end = process.stdout.index(b"\r\n\r\n", offset)
    length = int(process.stdout[offset:end].split(b":", 1)[1])
    start = end + 4
    message = json.loads(process.stdout[start:start + length])
    offset = start + length
    if "id" in message:
        responses[message["id"]] = message.get("result")
uris = {item["uri"] for item in responses[2]}
assert len(responses[2]) == 3, responses[2]
assert any(value.endswith("/main.dyn") for value in uris), responses[2]
assert any(value.endswith("/extra.dyn") for value in uris), responses[2]
changes = responses[3]["changes"]
assert any(value.endswith("/main.dyn") for value in changes), changes
assert any(value.endswith("/extra.dyn") for value in changes), changes
assert all(edit["newText"] == "renamed_shared" for edits in changes.values() for edit in edits)
assert sum(len(edits) for edits in changes.values()) == 3, changes
import_refs = responses[5]
assert len(import_refs) == 2, import_refs
assert any(item["uri"].endswith("/main.dyn") for item in import_refs), import_refs
assert any(item["uri"].endswith("/lib/module.dyn") for item in import_refs), import_refs
import_changes = responses[6]["changes"]
assert sum(len(edits) for edits in import_changes.values()) == 2, import_changes
