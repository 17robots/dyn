#!/usr/bin/env python3
"""Large request bodies are opt-in: a server that never calls
evented.large_bodies links none of the streaming-body code, and one that
does links it."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/mem"
use "std/net"
use "std/io"
use "std/net/http"
use "std/net/http/evented"

fn hello(response: *http.Response, request: *const http.Request) !io.IoErr {
  try http.text(response, 200, "hello\n")
}

fn main() {
  workers: [1]evented.Worker
  config := evented.default_config()
  LARGE
  arena := mem.arena_alloc(evented.storage_size(config, workers.len) + mem.MiB)
  defer mem.arena_release(arena)
  evented.serve(arena, workers[..], net.ipv4(127, 0, 0, 1, 18099), config, hello, nil) catch { #panic("serve") }
}
'''
STREAMING = ('body_begin', 'body_feed', 'body_end', 'settle_body', 'head_request')

if shutil.which('nm') is None:
    print('SKIP large body linking: no nm')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-large-body-') as temporary:
    work = Path(temporary)
    sizes = {}
    for name, line in (('plain', ''), ('large', 'config.large_body = evented.large_bodies(hello)')):
        project = work / name
        project.mkdir()
        (project / 'main.dyn').write_text(SOURCE.replace('LARGE', line))
        binary = work / (name + '.bin')
        subprocess.run([DYN, 'build', str(project), '--release', '--quiet', '--no-cache', '--output', str(binary)], check=True,
                       timeout=300)
        symbols = subprocess.run(['nm', str(binary)], capture_output=True, text=True, check=True).stdout
        linked = [s for s in STREAMING if s in symbols]
        if name == 'plain':
            assert not linked, linked
        else:
            assert len(linked) >= 3, linked
        sizes[name] = binary.stat().st_size
    assert sizes['plain'] < sizes['large'], sizes
print(f"PASS large body linking: {sizes['large'] - sizes['plain']} bytes only with evented.large_bodies")
