#!/usr/bin/env python3
"""Native debug routing, LLVM fallback, frontend and whole-program runtime contracts."""
import argparse
import os
import shlex
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT/'build/dyn')
    parser.add_argument('--reference', type=Path, default=ROOT/'build/dyn-legacy')
    args = parser.parse_args()
    candidate, reference = args.compiler.resolve(), args.reference.resolve()
    checks = 0
    def run(command):
        result = subprocess.run(list(map(str, command)), capture_output=True, timeout=120)
        assert not any(marker in result.stderr for marker in
                       (b'AddressSanitizer', b'LeakSanitizer', b'runtime error:')), (command, result.stderr)
        return result
    def ok(command):
        result = run(command)
        assert result.returncode == 0, (command, result.returncode, result.stdout, result.stderr)
        return result
    with tempfile.TemporaryDirectory(prefix='dyn-native-compiler-') as directory:
        root = Path(directory); source = root/'main.dyn'; output = root/'app'
        source.write_text('''use "std/io"
counter:u64
fn next() u64 { counter+=1 return counter }
first:u64=next()
second:u64=next()
fn identity(x:$T) T { return x }
fn main() {
 if first!=1 || second!=2 || identity(counter)!=2 { #panic("startup") }
 _ = io.println(io.stdout(), "native compiler ok")
}
''')
        for compiler, mode in ((reference,'--debug'),(candidate,'--debug'),(candidate,'--release')):
            backend = ['--backend','native'] if compiler == candidate and mode == '--debug' else []
            result = ok([compiler,'build',root,mode,*backend,'--no-cache','--jobs','1','--output',output])
            result = ok([output]); assert result.stdout == b'native compiler ok\n', result.stdout
            checks += 1
        # Imported reflection must retain source names after module rewriting.
        model=root/'model';model.mkdir()
        (model/'main.dyn').write_text('pub struct Pair { first:u64, second:u8 }\n')
        original=source.read_text()
        source.write_text('''use "model"
fn write(text:[]const u8) { _ = #syscall(1,1,&text[0],#len(text)) }
fn main() {
 info:=#typeof(model.Pair)
 if info.kind!=TypeKind.Struct || info.size!=16 || info.alignment!=8 || info.member_count!=2 { #panic("reflection layout") }
 wide:=#typeof(u64) narrow:=#typeof(u8)
 if info.fields[0].type_id!=wide.id || info.fields[1].type_id!=narrow.id { #panic("field types") }
 write(info.name) write(info.fields[0].name) write(info.fields[1].name)
 if #syscall(999999)!=-38 { #panic("raw syscall") }
}
''')
        observed=[]
        for compiler in (reference,candidate):
            backend = ['--backend','native'] if compiler == candidate else []
            ok([compiler,'build',root,'--debug',*backend,'--no-cache','--output',output])
            observed.append(ok([output]).stdout)
        assert observed[0]==observed[1] and b'Pair' in observed[0] and observed[0].endswith(b'firstsecond'),observed
        checks += 1
        # Private ELF names cannot collide or interpose with linked providers.
        provider=root/'provider.c';provider.write_text('unsigned long backend_value=17;')
        provider_obj=root/'provider.o'
        ok([*shlex.split(os.environ.get('CC','cc')),'-c',provider,'-o',provider_obj])
        source.write_text('''extern value "backend_value":u64
private_value:u64=3
fn private_fn() u64 { return private_value+4 }
fn main() {
 if value!=17 || private_fn()!=7 { #panic("foreign/private symbol") }
 value=19
 if value!=19 { #panic("foreign write") }
}
''')
        for compiler in (reference,candidate):
            if compiler == candidate:
                provider.write_text('unsigned long backend_value=17; unsigned long private_value=999; unsigned long private_fn(void){return 999;}')
                ok([*shlex.split(os.environ.get('CC','cc')),'-c',provider,'-o',provider_obj])
            backend = ['--backend','native'] if compiler == candidate else []
            ok([compiler,'build',root,'--debug',*backend,'--no-cache','--link',provider_obj,'--output',output])
            ok([output])
        checks += 1
        source.write_text(original)
        # Native executables use the whole-executable cache, keyed apart from LLVM.
        cache=root/'cache'; env=dict(os.environ,DYN_CACHE_DIR=str(cache))
        def cached(*flags):
            result=subprocess.run(list(map(str,[candidate,'build',root,*flags,'--output',output])),
                                  capture_output=True,timeout=120,env=env)
            assert result.returncode == 0, result.stderr
            return b'cached ' in result.stdout
        assert not cached('--backend','native') and cached('--backend','native') and cached()
        assert not cached('--backend','llvm') and cached('--backend','llvm')
        assert ok([output]).stdout == b'native compiler ok\n'
        checks += 1
        # LLVM-only options route auto builds to LLVM; explicit native rejects them.
        for flags in (['--emit-ir'],['--emit-asm'],['--cpu','native'],
                      ['--opt-remarks'],['--release','--opt-level','2']):
            output.write_bytes(b'keep-existing-output')
            result=run([candidate,'build',root,'--backend','native',*flags,'--output',output])
            assert result.returncode == 2 and b'--backend native requires' in result.stderr, (flags,result.stderr)
            assert output.read_bytes() == b'keep-existing-output'
            checks += 1
        # Semantic and syntax errors use the ordinary frontend, including JSON spans.
        for text in ('fn main(){ missing() }', 'fn main( {'):
            source.write_text(text)
            for diagnostic in ([],['--diagnostics','json']):
                a=run([reference,'check',root,*diagnostic]);b=run([candidate,'check',root,*diagnostic])
                assert (a.returncode,a.stdout,a.stderr)==(b.returncode,b.stdout,b.stderr),(a,b)
                assert a.returncode != 0
                checks += 1
        source.write_text('fn inner(){ #panic("native trace") }\nfn main(){inner()}\n')
        ok([candidate,'build',root,'--backend','native','--output',output])
        result=run([output]);assert result.returncode != 0 and b'native trace' in result.stderr and b'inner' in result.stderr,result.stderr
        ok([reference,'build',root,'--debug','--no-cache','--output',output])
        oracle=run([output])
        assert (result.returncode,result.stdout,result.stderr)==(oracle.returncode,oracle.stdout,oracle.stderr),(result,oracle)
        checks += 1
        # Programs beyond native capacity fail under --backend native without
        # replacing a published object; auto falls back to LLVM and still runs.
        source.write_text('fn wide('+', '.join(f'a{i}: u64' for i in range(600))+') u64 { return a599 }\n'
                          'fn main() { if wide('+', '.join(map(str,range(600)))+') != 599 { #panic("wide") } }\n')
        obj=Path(str(output)+'.o');obj.write_bytes(b'previous object')
        result=run([candidate,'build',root,'--backend','native','--no-link','--output',output])
        assert result.returncode != 0 and b'use --backend llvm' in result.stderr,result.stderr
        assert obj.read_bytes() == b'previous object'
        result=ok([candidate,'build',root,'--verbose','--no-cache','--output',output])
        assert b'using LLVM' in result.stderr, result.stderr
        ok([output])
        checks += 1
        # Debug builds carry DWARF by default; --release objects come from LLVM.
        source.write_text('fn main() {}\n')
        ok([candidate,'build',root,'--backend','native','--no-link','--output',output])
        sections=ok(['readelf','-S',str(output)+'.o']).stdout
        assert b'.debug_info' in sections and b'.debug_line' in sections and b'.debug_frame' in sections
        checks += 1
    print(f'PASS {checks} native compiler routing/frontend/runtime contracts')

if __name__ == '__main__': main()
