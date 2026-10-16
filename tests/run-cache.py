#!/usr/bin/env python3
"""Run executes current code each time and cleans temporary outputs.
Native debug emission regenerates the whole program instead; it is covered below."""
import os
from pathlib import Path
import subprocess
import tempfile
DYN = os.environ.get('DYN', str(Path(__file__).resolve().parents[1]/'build/dyn'))
with tempfile.TemporaryDirectory(prefix='dyn-run-cache-') as directory:
    root=Path(directory); source=root/'app'; source.mkdir(); temporary=root/'tmp'; temporary.mkdir()
    (source/'main.dyn').write_text('use "std/io" io\nfn main() { _ = io.println(io.stdout(), "first") }\n')
    env=dict(os.environ,DYN_CACHE_DIR=str(root/'cache'),TMPDIR=str(temporary),
             PATH=str(Path(DYN).resolve().parent)+os.pathsep+os.environ.get('PATH',''))
    # A shell passes just `dyn` as argv[0]. An absolute test path used to hide
    # the compiler fingerprint failure that disabled every cache hit.
    command=Path(DYN).name
    def run(*options):
        p=subprocess.run([command,'run',str(source),'--jobs','1','--timings','--backend','native',*options],env=env,capture_output=True,text=True,timeout=30)
        assert p.returncode==0,p.stderr
        assert not list(temporary.iterdir()),list(temporary.iterdir())
        return p
    cold=run(); warm=run()
    assert 'first' in cold.stdout and 'first' in warm.stdout
    assert 'timing detail native emit' in cold.stderr,cold.stderr
    # Run regenerates its private executable; each invocation must execute.
    (source/'main.dyn').write_text('use "std/io" io\nfn main() { _ = io.println(io.stdout(), "second") }\n')
    changed=run();assert 'second' in changed.stdout and 'timing detail native emit' in changed.stderr
    fresh=run('--no-cache');assert 'second' in fresh.stdout and 'timing detail native emit' in fresh.stderr
    (source/'main.dyn').write_text('fn main() { ffefefefefefe }\n')
    invalid=subprocess.run([command,'run',str(source)],env=env,capture_output=True,text=True,timeout=30)
    assert invalid.returncode != 0, 'invalid source executed a cached program'
    assert 'second' not in invalid.stdout
    assert not list(temporary.iterdir()),list(temporary.iterdir())
    (source/'main.dyn').write_text('use "std/io" io\nfn main() { _ = io.println(io.stdout(), "native") }\n')
    for _ in range(2):
        native=subprocess.run([command,'run',str(source)],env=env,capture_output=True,text=True,timeout=30)
        assert native.returncode==0 and 'native' in native.stdout,native.stderr
        assert not list(temporary.iterdir()),list(temporary.iterdir())
print('PASS run execution, invalidation, no-cache, temporary cleanup')
