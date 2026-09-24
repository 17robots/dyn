#!/usr/bin/env python3
"""A nonblocking pipe accepts a prefix, then fails with EAGAIN."""
import os
import fcntl
from pathlib import Path
import subprocess
compiler = os.environ.get('DYN', './build/dyn')
output = Path('build/terminal-progress').resolve()
subprocess.run([compiler, 'build', 'tests/terminal-progress', '--no-cache', '--quiet', '--output', str(output)], check=True)
reader, writer = os.pipe2(os.O_NONBLOCK)
try:
    fcntl.fcntl(writer, fcntl.F_SETPIPE_SZ, 4096)
    result = subprocess.run([str(output)], stdout=writer, stderr=subprocess.PIPE)
    assert result.returncode == 0, result.stderr.decode()
    assert len(os.read(reader, 65536)) > 0
finally:
    os.close(reader)
    os.close(writer)
