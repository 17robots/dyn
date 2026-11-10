#!/usr/bin/env python3
"""Typed HTTP state and HTML markup are checked at compile time: a handler for
another state type, a route for another router, and plain bytes passed as
markup are compile errors; the correct program checks cleanly."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())
PRELUDE = '''use "std/html"
use "std/net/http"

struct App { count: i32 }
struct Other { name: i32 }

fn for_app(response: *http.Response, request: *const http.Request, app: *App) http.Result {
  return http.Result{}
}

fn for_other(response: *http.Response, request: *const http.Request, other: *Other) http.Result {
  return http.Result{}
}

'''
CASES = {
    'good': ('''fn main() {
  app := App{}
  typed := http.Typed(App){ state: &app, handler: for_app }
  _ = http.bind(&typed)
  storage: [4]http.TypedRoute(App)
  router := http.typed_routes(storage[..], &app)
  _ = http.add(&router, "GET", "/", for_app)
  _ = http.bind_routes(&router)
  page_storage: [64]u8
  page := html.writer(page_storage[..])
  html.markup(&page, html.trusted("<p>"))
  html.text(&page, "<script>")
}
''', None),
    'typed handler': ('''fn main() {
  app := App{}
  typed := http.Typed(App){ state: &app, handler: for_other }
  _ = http.bind(&typed)
}
''', 'type mismatch'),
    'route handler': ('''fn main() {
  app := App{}
  storage: [4]http.TypedRoute(App)
  router := http.typed_routes(storage[..], &app)
  _ = http.add(&router, "GET", "/", for_other)
}
''', 'error'),
    'raw markup': ('''fn main() {
  page_storage: [64]u8
  page := html.writer(page_storage[..])
  html.markup(&page, "<p>")
}
''', 'error'),
}
with tempfile.TemporaryDirectory(prefix='dyn-http-typed-') as temporary:
    for name, (body, expected) in CASES.items():
        work = Path(temporary) / name.replace(' ', '-')
        work.mkdir()
        (work / 'main.dyn').write_text(PRELUDE + body)
        result = subprocess.run([DYN, 'check', str(work)], capture_output=True, text=True, timeout=60)
        if expected is None:
            assert result.returncode == 0, (name, result.stderr)
        else:
            errors = [line for line in result.stderr.splitlines() if ': error:' in line]
            assert result.returncode != 0 and errors, (name, result.stderr)
            assert expected in errors[0] and 'main.dyn' in errors[0], (name, result.stderr)
print('PASS typed HTTP state and HTML markup: mismatches are compile errors')
