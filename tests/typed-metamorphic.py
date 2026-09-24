#!/usr/bin/env python3
"""Valid typed programs preserve behavior through import/comment transformations."""
import os
from pathlib import Path
import random
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())
rng=random.Random(901)
with tempfile.TemporaryDirectory(prefix='dyn-typed-') as directory:
    root=Path(directory);(root/'library').mkdir();(root/'direct').mkdir()
    for case in range(24):
        a,b,c=[rng.randrange(1,100) for _ in range(3)]
        # Both a parameter and a local can share spelling with a module function.
        library=f'''pub fn answer() i32 {{ return 999 }}
pub fn local() i32 {{ return 888 }}
pub fn evaluate(answer: i32) i32 {{
  const local: i32 = {b}
  values: [3]i32 = [answer, local, {c}]
  total: i32 = 0
  for value in values {{ total += value }}
  if answer > 0 {{ total += answer }}
  return total
}}
'''
        library += """pub fn named(value: i32) i32 { return value + 1 }
pub fn increment(value: i32) i32 { return value + 2 }
pub fn select(named: *fn(i32) i32) i32 {
  info := #typeof(named)
  if info.kind != TypeKind.Pointer { #panic("reflection resolved function over local") }
  pointer := &named
  if pointer.* != named { #panic("address resolved function over local") }
  return named(40)
}
"""
        (root/'library/module.dyn').write_text(library)
        expected=2*a+b+c
        (root/'direct/main.dyn').write_text(library+f'fn main() {{ if evaluate({a}) != {expected} || select(&increment) != 42 {{ #panic("root behavior") }} }}\n')
        for comment in ('','/* imported member */'):
            (root/'main.dyn').write_text(f'use "./library" /* use comment */ lib\nfn main() {{ if lib.{comment}evaluate({a}) != {expected} || lib.select(&lib.increment) != 42 {{ #panic("import behavior") }} }}\n')
            for package in (root,root/'direct'):
                for mode in ([],['--release']):
                    subprocess.run([DYN,'build',str(package),'--quiet','--no-cache','--output',str(root/'run'),*mode],cwd=ROOT,check=True)
                    subprocess.run([str(root/'run')],check=True,timeout=5)
print('PASS 24 typed programs, root/imported, comments, debug/release (192 builds)')
