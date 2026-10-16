#!/usr/bin/env python3
"""Qualify the built-in linker against independently generated wasm32 objects.

Clang supplies oracle fixtures only; the tested linker is compiled using CC and
never invokes LLVM, wasm-ld, or another external linker.
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, **kwargs)
    assert result.returncode == 0, shlex.join(map(str, args)) + '\n' + result.stdout + result.stderr
    return result


def archive(path, members, bsd=False):
    data = bytearray(b'!<arch>\n')
    for index, (name, body) in enumerate(members):
        if bsd:
            encoded = name.encode()
            label = f'#1/{len(encoded)}'
            body = encoded + body
        else:
            label = f'm{index}.o/'
        header = f'{label:<16}{0:<12}{0:<6}{0:<6}{644:<8}{len(body):<10}`\n'.encode()
        assert len(header) == 60
        data += header + body
        if len(body) % 2:
            data += b'\n'
    path.write_bytes(data)


with tempfile.TemporaryDirectory(prefix='dyn-wasm-linker-') as directory:
    work = Path(directory)
    harness = work / 'link.c'
    harness.write_text('#include "link_wasm.h"\n'
                       'int main(int n,char **v) {'
                       'return dyn_link_wasm_objects((const char *const *)v+2,n-2,v[1],0,0,0,0,0);}\n')
    linker = work / ('link.exe' if os.name == 'nt' else 'link')
    run([*shlex.split(os.environ.get('CC', 'cc')), '-std=c11', '-Wall', '-Wextra', '-Werror',
         '-I', ROOT / 'src', harness, ROOT / 'src/link_wasm.c', '-o', linker])

    def obj(name, source):
        source_path = work / (name + '.c')
        source_path.write_text(source)
        output = work / (name + '.o')
        run([*shlex.split(os.environ.get('CLANG', 'clang')), '--target=wasm32-unknown-unknown',
             '-ffreestanding', '-O1', '-c', source_path, '-o', output])
        return output

    caller = obj('caller', 'extern int add(int); extern int *address(void);\n'
                 '__attribute__((export_name("run"))) int run(int x) {'
                 'int (*volatile p)(int)=add; return p(x)+*address();}\n')
    add = obj('add', 'extern int offset; int add(int x) { return x+offset; }\n')
    data = obj('data', 'int offset=2; int *pointer=&offset; int *address(void) {return pointer;}\n')
    unused = obj('unused', 'extern int unavailable(void); int unused(void) {return unavailable();}\n')
    output = work / 'result.wasm'
    for bsd in (False, True):
        library = work / ('bsd.a' if bsd else 'gnu.a')
        archive(library, [('very-long-member-name-add.o', add.read_bytes()),
                          ('data.o', data.read_bytes()), ('unused.o', unused.read_bytes())], bsd)
        run([linker, output, caller, library])
        run(['node', '-e', 'WebAssembly.instantiate(require("fs").readFileSync(process.argv[1]))'
             '.then(({instance})=>{if(instance.exports.run(38)!==42)process.exit(1)})'
             '.catch(e=>{console.error(e);process.exit(1)})', output])

    def fails(inputs, diagnostic):
        output.write_bytes(b'preserved output')
        result = subprocess.run([str(linker), str(output), *map(str, inputs)], capture_output=True, text=True)
        assert result.returncode != 0 and diagnostic in result.stderr, result.stderr
        assert output.read_bytes() == b'preserved output'

    fails([caller], 'undefined symbol')
    fails([caller, add, data, add], 'duplicate symbol')
    wrong = obj('wrong', 'float add(float x) { return x; }\n')
    fails([caller, wrong, data], 'function type mismatch')
    malformed = work / 'malformed.o'
    malformed.write_bytes(b'\0asm\1\0\0\0\1\xff\xff\xff\xff\x7f')
    fails([malformed], 'invalid u32 LEB')
    malformed.write_bytes(caller.read_bytes()[:-1])
    fails([malformed], 'truncated object')
    # The relocation kind lives immediately after target section and count,
    # both one byte for this small independent fixture.
    raw = bytearray(caller.read_bytes())
    at = raw.index(b'reloc.CODE') + len(b'reloc.CODE') + 2
    raw[at] = 127
    malformed.write_bytes(raw)
    fails([malformed, add, data], 'unsupported relocation type')
    raw = bytearray(caller.read_bytes())
    at = raw.index(b'reloc.CODE') + len(b'reloc.CODE') + 3
    raw[at] = 0  # relocation must not overwrite the code vector count
    malformed.write_bytes(raw)
    fails([malformed, add, data], 'relocation outside function/data payload')

print('PASS built-in Wasm linker: lazy GNU/BSD archives, pointers, data, type checking, malformed inputs, atomic failure')
