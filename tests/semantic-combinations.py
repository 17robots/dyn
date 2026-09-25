#!/usr/bin/env python3
"""Exercise interactions between module constants/aliases, casts, callbacks and defer."""
import json,os,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
rows=[]
with tempfile.TemporaryDirectory(prefix='dyn-semantic-combinations-') as d:
    root=Path(d);lib=root/'lib';lib.mkdir()
    (lib/'module.dyn').write_text('pub type Count = i64\npub const Base: Count = 40\npub struct Pair { value: Count }\n')
    for alias in ('lib','data'):
      for comment in ('','/* between import and declaration */'):
       for expression in (f'{alias}.Base + 2',f'#cast({alias}.Count) 42'):
        use='use "./lib"'+(' data' if alias=='data' else '')
        source=f'''{use}
{comment}
const Expected: {alias}.Count = {expression}
calls: i32 = 0
fn callback(value: {alias}.Pair) {alias}.Pair {{
  defer {{ calls += 1 }}
  return {alias}.Pair{{value: value.value + 2}}
}}
fn early(stop: bool) i32 {{
  defer {{ calls += 10 }}
  if stop {{ defer {{ calls += 100 }} return 7 }}
  return 8
}}
fn main() {{
  function := &callback
  raw := #cast(rawptr) function
  restored := #cast(*fn({alias}.Pair) {alias}.Pair) raw
  value := restored({alias}.Pair{{value: {alias}.Base}})
  if value.value != Expected || calls != 1 {{ #panic("alias/import/callback/cast") }}
  if early(true) != 7 || calls != 111 {{ #panic("defer early return") }}
  if early(false) != 8 || calls != 121 {{ #panic("defer fallthrough") }}
}}
'''
        (root/'main.dyn').write_text(source)
        for release in (False,True):
          for cached in (False,True):
            output=root/'run'
            command=[DYN,'build',str(root),'--quiet','--output',str(output)]+(['--release'] if release else [])+([] if cached else ['--no-cache'])
            subprocess.run(command,check=True,timeout=30)
            subprocess.run([str(output)],check=True,timeout=5)
            rows.append(dict(alias=alias,comment=bool(comment),expression=expression,release=release,cached=cached,status='passed'))
    # Forward constants and field defaults are validated after all names resolve.
    (root/'main.dyn').write_text('const First: i64 = Second + 1\nconst Second: i64 = #cast(i64) 41\nstruct Defaults { value: i64 = First }\nconst Arithmetic: i64 = '+ '+'.join(['1']*40)+'\nfn main() { value := Defaults{} if value.value != 42 || Arithmetic != 40 { #panic("constants") } }\n')
    for release in (False,True):
        subprocess.run([DYN,'build',str(root),'--quiet','--no-cache','--output',str(root/'run')]+(['--release'] if release else []),check=True)
        subprocess.run([str(root/'run')],check=True)
    for source in ('use "./lib" data\nconst Bad: data.Count = 1.5\nfn main() {}',
                   'const A: i64 = B\nconst B: i64 = A\nfn main() {}',
                   'use "./lib" data\nfn main() { _ = data.Pair(i32){value: 1} }',
                   'use "./lib" data\nfn f(x: data.Pair) data.Pair { return x }\nfn main() { callback: *fn(i32) i32 = &f _ = callback(1) }'):
        (root/'main.dyn').write_text(source)
        for command in ('check','build'):
            r=subprocess.run([DYN,command,str(root),'--quiet','--no-cache','--output',str(root/'run')],capture_output=True,text=True,timeout=30)
            assert r.returncode==1 and 'error:' in r.stderr,(source,r.stderr)
    # A foreign call may invoke a Dyn callback that panics. The Dyn caller's
    # defer must run even though the intervening C function has no cleanup hook.
    (root/'provider.c').write_text('void invoke(void (*callback)(void)) { callback(); }\n')
    subprocess.run(['cc','-fno-stack-protector','-c',str(root/'provider.c'),'-o',str(root/'provider.o')],check=True)
    (root/'main.dyn').write_text('use "std/io"\nextern fn invoke "invoke"(callback: *fn())\nfn fails() { #panic("callback failure") }\nfn main() { defer { _ = io.println(io.stdout(),"caller cleanup") } invoke(&fails) }\n')
    for release in (False,True):
        subprocess.run([DYN,'build',str(root),'--quiet','--no-cache','--link',str(root/'provider.o'),'--output',str(root/'run')]+(['--release'] if release else []),check=True)
        r=subprocess.run([str(root/'run')],capture_output=True,text=True,timeout=5)
        assert r.returncode==101 and 'caller cleanup' in r.stdout and 'callback failure' in r.stderr,(r.returncode,r.stdout,r.stderr)
(ROOT/'build/readiness').mkdir(parents=True,exist_ok=True)
(ROOT/'build/readiness/semantic-combinations.json').write_text(json.dumps(rows,indent=2)+'\n')
print(f'PASS {len(rows)} semantic combinations, eight negative check/build cases, forward constants and field defaults, foreign callback panic/defer debug/release')
