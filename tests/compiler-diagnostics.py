#!/usr/bin/env python3
"""Build/check report syntax failures consistently, including interface preparation."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-diagnostic-') as directory:
    root=Path(directory)
    for text in ('fn main( {', 'fn main() { if #typeof(i32).kind == TypeKind.Integer {} }'):
        (root/'main.dyn').write_text(text)
        for command in ('check','build'):
            result=subprocess.run([DYN,command,str(root),'--no-cache','--quiet','--diagnostics','json'],cwd=ROOT,capture_output=True,text=True)
            assert result.returncode==1,(command,result.returncode,result.stderr)
            assert 'invalid syntax' in result.stderr,(command,result.stderr)
print('PASS check/build syntax diagnostics')
