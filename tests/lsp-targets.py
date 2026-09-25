#!/usr/bin/env python3
"""LSP target selection must affect imported declarations and integer widths."""
from pathlib import Path
import runpy, tempfile
helpers=runpy.run_path(str(Path(__file__).with_name('lsp-contracts.py')))
with tempfile.TemporaryDirectory(prefix='dyn-lsp-target-') as directory:
 path=Path(directory)/'main.dyn'
 for text,target,expected in [
  ('fn main() { value: usize = 4294967296 _ = value }','wasm32-browser',True),
  ('fn main() { value: usize = 4294967296 _ = value }','x86_64-linux',False),
  ('use "std/os/wasi" wasi\nfn main() { _ = wasi.close(999) }','wasm32-wasi',False),
  ('use "std/os/wasi" wasi\nfn main() { _ = wasi.close(999) }','x86_64-linux',True),
 ]:
  path.write_text(text)
  responses,stderr=helpers['run_lsp']([helpers['opened'](path,text)],target=target)
  assert not stderr,stderr
  errors=[x for x in helpers['diagnostics'](responses,path) if x.get('severity')==1]
  assert bool(errors)==expected,(target,errors)
print('PASS LSP target-aware SDK declarations and pointer-sized integer diagnostics')
