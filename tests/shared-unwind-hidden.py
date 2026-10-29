#!/usr/bin/env python3
"""A dependency's public unwind boundaries cannot preempt hidden runtime references."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
if not sys.platform.startswith('linux'):
    print('SKIP ELF hidden unwind boundary regression: Linux required')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-shared-unwind-hidden-') as temporary:
    work=Path(temporary)
    (work/'provider.c').write_text('unsigned char __start_dyn_unwind[8];\nunsigned char __stop_dyn_unwind[8];\nint dependency(void){return 42;}\n')
    subprocess.run(['cc','-shared','-fPIC',str(work/'provider.c'),'-o',str(work/'libunwind_provider.so')],check=True)
    (work/'main.dyn').write_text('''use "std/testing"
#link("unwind_provider")
extern fn dependency() i32
pub fn probe() i32 {
  testing.expect(dependency()==42,"dependency call")
  return 42
}
''')
    env=dict(os.environ,DYN_LIBRARY_PATH=str(work),DYN_LINKER='builtin',LD_LIBRARY_PATH=str(work)+os.pathsep+os.environ.get('LD_LIBRARY_PATH',''))
    for mode in ('--debug','--release'):
        output=work/('consumer'+mode+'.so')
        subprocess.run([DYN,'build',str(work),'--shared',mode,'--quiet','--no-cache','--output',str(output)],env=env,check=True,timeout=120)
        subprocess.run([sys.executable,'-c','import ctypes,sys; library=ctypes.CDLL(sys.argv[1]); assert library.probe()==42',str(output)],env=env,check=True,timeout=15)
        symbols=subprocess.check_output(['readelf','--dyn-syms','--wide',str(output)],text=True)
        assert '__start_dyn_unwind' not in symbols and '__stop_dyn_unwind' not in symbols, symbols
print('PASS shared dependency cannot preempt module-local unwind boundaries (debug/release)')
