#!/usr/bin/env python3
"""Binding visibility, function isolation and mapped errors beyond index thresholds."""
import os, subprocess, tempfile
from pathlib import Path
DYN = str(Path(os.environ.get('DYN','build/dyn')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-wide-contracts-') as directory:
    root = Path(directory); (root/'lib').mkdir()
    (root/'lib/module.dyn').write_text('pub fn value() i32 { return 41 }\n')
    locals_ = ''.join(f'  value{i}: i32 = {i}\n' for i in range(96))
    prefix = 'use "./lib" m\nstruct Box { value: i32 }\nenum Result { Value: Box }\n'
    valid = prefix + '''fn parameter(m: Box) i32 { return m.value }
fn initializer() i32 { m := Box{value: m.value()} return m.value }
fn iteration() i32 { values := [Box{value: 7}] total: i32 = 0 for m in values { total += m.value } return total }
fn payload() i32 { result := Result.Value(Box{value: 3}) case result { Result.Value m => { return m.value } } }
fn variadic(m: ...Box) i32 { return m[0].value }
fn first() i32 {
''' + locals_ + '''  if true { hidden := 8 _ = hidden }
  return value95
}
fn second() i32 {
''' + locals_ + '''  return value0
}
fn main() {
  if first() != 95 || second() != 0 || initializer() != 41 || parameter(Box{value: 2}) != 2 || iteration() != 7 || payload() != 3 || variadic(Box{value: 9}) != 9 { #panic("binding") }
}
'''
    source = root/'main.dyn'; source.write_text(valid); output = root/'program'
    for flags in ([],['--release']):
        subprocess.run([DYN,'build',str(root),'--quiet','--no-cache','--output',str(output),*flags],check=True)
        subprocess.run([str(output)],check=True)
    for tail,expected in [
        ('value0 := 4', 'shadowing or duplicate local is forbidden'),
        ('if true { hidden := 1 _ = hidden } _ = hidden', 'unknown name'),
        ('if true { hidden := 1 _ = hidden } if true { hidden := 2 _ = hidden }', 'shadowing or duplicate local is forbidden')]:
        text = prefix+'fn main() {\n'+locals_+'// 😀 source-map positions must remain original\n'+tail+'\n}\n'
        source.write_text(text)
        expected_line = text[:text.index(tail)].count('\n')+1
        for command in ('check','build'):
            run = subprocess.run([DYN,command,str(root),'--quiet','--no-cache','--output',str(output)],capture_output=True,text=True)
            assert run.returncode != 0 and expected in run.stderr, run.stderr
            assert f'{source}:{expected_line}:' in run.stderr, run.stderr
print('PASS large-function binding visibility, local-index growth/reset, runtime values and diagnostic source lines')
