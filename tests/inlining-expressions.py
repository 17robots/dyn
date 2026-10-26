#!/usr/bin/env python3
"""Expression-spine expansion preserves checks/effects and lvalue snapshots."""
import ctypes
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()
SOURCE = 'use "std/io"\ntrace:u64=0\nfn step(p:*u32) u32 {\n trace=trace*10+1\n p.*=#wrap(p.* * 1664525+1013904223)\n return p.*\n}\nfn after() u32 {trace=trace*10+2\nreturn 3}\npub fn nested(p:*u32) u64 {return #cast(u64,1+(step(p)>>8)%1000)}\npub fn wrapped(p:*u32) u32 {return #wrap(step(p)+4294967295)}\npub fn left(p:*u32) u64 {trace=0\nv:=#cast(u64,step(p)+after())\nreturn trace*10000000000+v}\npub fn right_rejected(p:*u32) u64 {trace=0\nv:=#cast(u64,after()+step(p))\nreturn trace*10000000000+v}\npub fn conditional(p:*u32, enabled:bool) u64 {trace=0\nif enabled && step(p)>0 {return 90}\nreturn trace}\nstruct Pair {value:u32}\nfn change(index:*usize) u32 {index.*=1\nreturn 7}\nfn index_effect() usize {trace=trace*10+3\nreturn 0}\npub fn index_order(p:*u32) u64 {trace=0\na:[1]u32=[]\na[index_effect()]=step(p)\nreturn trace}\npub fn indexed(keep:*u32) u32 {a:[2]u32=[]\ni:usize=0\na[i]=change(&i)\nreturn a[0]*10+a[1]}\npub fn field(keep:*u32) u32 {a:Pair=Pair{}\na.value=change_field(&a)\nreturn a.value}\nfn change_field(a:*Pair) u32 {a.value=9\nreturn 7}\npacked struct Packed {pad:u8, value:u64}\npacked struct PackedArray {pad:u8, values:[2]u64}\nfn wide() u64 {trace+=1\nreturn trace}\npub fn packed_field(p:*Packed, keep:*u64) u64 {p.value=wide()\nreturn p.value}\npub fn packed_index(p:*PackedArray, keep:*u64) u64 {p.values[0]=wide()\nreturn p.values[0]}\nfn effect() u32 {_=io.write_all(io.stdout(),"RHS\\n")\nreturn 7}\npub fn bad_index(i:usize) {a:[1]u32=[]\na[i]=effect()}\npub fn bad_pointer(p:*u32) {p.*=effect()}\npub fn bad_overflow(p:*u32) u32 {return step(p)+4294967295}\n'
HARNESS = r'''
#include "native_opt.c"
#include <assert.h>
static size_t records(const DynIrProgram *p) {
 return p->expression_count+p->statement_count+p->item_count+p->child_count+
        p->case_arm_count+3*p->local_count;
}
static void wrappers(unsigned depth, bool accepted) {
 DynIrExpr expressions[36];memset(expressions,0,sizeof(expressions));
 expressions[0]=(DynIrExpr){.kind=DYN_EXPR_INT,.type=DYN_TYPE_U64,.integer=7,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR};
 expressions[1]=(DynIrExpr){.kind=DYN_EXPR_CALL,.type=DYN_TYPE_U64,.integer=0,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR};
 for(unsigned i=0;i<depth;i++)expressions[2+i]=(DynIrExpr){.kind=DYN_EXPR_BINARY,.type=DYN_TYPE_U64,.op=DYN_OP_ADD,.left=1+i,.right=0};
 DynIrFunction function={.return_type=DYN_TYPE_U64,.body_count=1};
 DynIrStmt statement={.kind=DYN_STMT_RETURN,.expression=0,.target=DYN_NO_EXPR};
 uint32_t child=0;bool active=false;unsigned cost=2;
 DynIrProgram p={.expressions=expressions,.expression_count=depth+2,.functions=&function,.function_count=1,
   .statements=&statement,.statement_count=1,.children=&child,.child_count=1};
 Inline b={.in=&p,.loop_stride=1,.budget=512,.resource_budget=4096,.active=&active,.costs=&cost};
 InlineScope scope={.function=&function,.expand=true};InlineList list={0};DynExprId result=DYN_NO_EXPR;
 bool ok=inline_cast_call(&b,&scope,depth+1,&list,&result,0);
 assert(ok==accepted && !b.failed);
 if(ok) {
  assert(b.expansions==1 && b.budget==508);
  /* Wrapper rebuilding replaces the unexpanded spine; added physical
     records remain within the actual debit, not a new allowance. */
  assert(records(&b.out)<=depth+4096-b.resource_budget);
 }else assert(b.expansions==0 && b.budget==512 && b.resource_budget==4096);
 free(list.ids);inline_free(&b.out);
}
static void sparse_loops(void) {
 uint32_t nested_children[]={1,4,5,2,3};
 DynIrStmt direct[6]={
  {.kind=DYN_STMT_FOR,.loop_id=UINT32_MAX,.body_start=0,.body_count=3},
  {.kind=DYN_STMT_FOR,.loop_id=17,.body_start=3,.body_count=2},
  {.kind=DYN_STMT_CONTINUE,.target_loop_id=17},
  {.kind=DYN_STMT_BREAK,.target_loop_id=17},
  {.kind=DYN_STMT_CONTINUE,.target_loop_id=UINT32_MAX},
  {.kind=DYN_STMT_BREAK,.target_loop_id=UINT32_MAX}};
 DynIrProgram p={.statements=direct,.statement_count=6,
                 .children=nested_children,.child_count=5};
 assert(inline_dense_loops(&p));
 assert(direct[0].loop_id==1 && direct[1].loop_id==0);
 assert(direct[2].target_loop_id==0 && direct[3].target_loop_id==0);
 assert(direct[4].target_loop_id==1 && direct[5].target_loop_id==1);
 assert(direct[0].body_start==0 && direct[0].body_count==3);
 assert(direct[1].body_start==3 && direct[1].body_count==2);
 for(unsigned i=0;i<5;i++)assert((nested_children[i]==(uint32_t[]){1,4,5,2,3}[i]));
 direct[5].target_loop_id=3;
 assert(!inline_dense_loops(&p));
 /* Many empty callers still reserve source-ID ranges. One late expansion
    previously generated loop IDs greater than its output statement count. */
 DynNativeOptimization o={0};
 DynIrFunction functions[202];memset(functions,0,sizeof(functions));
 functions[0]=(DynIrFunction){.return_type=DYN_TYPE_U64,.body_count=1};
 functions[201]=(DynIrFunction){.return_type=DYN_TYPE_VOID,.body_start=2,.body_count=1};
 uint32_t children[]={0,1,2};
 o.ir.functions=functions;o.ir.function_count=202;
 o.ir.children=children;o.ir.child_count=3;
 o.ir.expressions=calloc(2,sizeof(DynIrExpr));o.ir.expression_count=2;
 o.ir.expressions[0]=(DynIrExpr){.kind=DYN_EXPR_INT,.type=DYN_TYPE_U64,.integer=7,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR};
 o.ir.expressions[1]=(DynIrExpr){.kind=DYN_EXPR_CALL,.type=DYN_TYPE_U64,.integer=0,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR};
 o.ir.statements=calloc(3,sizeof(DynIrStmt));o.ir.statement_count=3;
 o.ir.statements[0]=(DynIrStmt){.kind=DYN_STMT_RETURN,.expression=0,.target=DYN_NO_EXPR};
 o.ir.statements[1]=(DynIrStmt){.kind=DYN_STMT_EXPR,.expression=1,.target=DYN_NO_EXPR};
 o.ir.statements[2]=(DynIrStmt){.kind=DYN_STMT_FOR,.expression=DYN_NO_EXPR,.target=DYN_NO_EXPR,.loop_id=0,.body_start=1,.body_count=1};
 assert(inline_program(&o,false,false) && o.owns_expansion && o.inlined==1);
 for(size_t i=0;i<o.ir.statement_count;i++) {
  DynIrStmt *st=&o.ir.statements[i];
  if(st->kind==DYN_STMT_FOR)assert(st->loop_id<o.ir.statement_count);
  if(st->kind==DYN_STMT_BREAK || st->kind==DYN_STMT_CONTINUE)assert(st->target_loop_id<o.ir.statement_count);
 }
 dyn_native_optimization_free(&o);
}
int main(void) {
 sparse_loops();
 wrappers(32,true);wrappers(33,false);
 DynIrExpr targets[2]={{.kind=DYN_EXPR_INDEX,.type=DYN_TYPE_U32,.left=1},{.kind=DYN_EXPR_NAME,.type=DYN_TYPE_U32}};
 DynIrPointer pointers[1025];memset(pointers,0,sizeof(pointers));
 DynIrProgram p={.expressions=targets,.expression_count=2,.pointers=pointers,.pointer_count=1};
 pointers[0].pointee=DYN_TYPE_U64;
 assert(inline_target_pointer(&p,0)==DYN_TYPE_VOID);
 pointers[0].pointee=DYN_TYPE_U32;pointers[0].is_const=true;
 assert(inline_target_pointer(&p,0)==DYN_TYPE_VOID);
 pointers[0].is_const=false;
 assert(inline_target_pointer(&p,0)==DYN_TYPE_POINTER_BASE);
 p.pointer_count=1025;
 assert(inline_target_pointer(&p,0)==DYN_TYPE_VOID);
 return 0;
}
'''


def run(command, env=None, timeout=120):
    return subprocess.run(list(map(str, command)), env=env, text=True,
                          capture_output=True, timeout=timeout)


def main():
    if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64') or not shutil.which('objdump'):
        print('SKIP inline expressions: Linux x86-64/objdump required')
        return
    env = dict(os.environ, DYN_SDK=str(ROOT))
    env.pop('DYN_NO_SSA', None)
    with tempfile.TemporaryDirectory(prefix='dyn-inline-expressions-') as tmp:
        work = Path(tmp)
        module = work/'module'
        module.mkdir()
        # Dyn separates statements with newlines, not semicolons.
        source = SOURCE.replace(' return ', '\n return ').replace(' v:=', '\n v:=').replace(' i:usize', '\n i:usize').replace(' a[i]=', '\n a[i]=').replace(' a.value=', '\n a.value=').replace(' if enabled', '\n if enabled')
        (module/'main.dyn').write_text(source)
        for mode in ('ssa', 'tree'):
            current = dict(env)
            if mode == 'tree':
                current['DYN_NO_SSA'] = '1'
            libpath = work/(mode+'.so')
            result = run([DYN, 'build', module, '--shared', '--release', '--opt-level', '3', '--no-cache', '--quiet', '--output', libpath], current)
            assert result.returncode == 0, result.stderr
            lib = ctypes.CDLL(str(libpath))
            for seed in (0, 1, 19, 100000, 0x7fffffff):
                expected = (seed*1664525+1013904223)&0xffffffff
                x = ctypes.c_uint32(seed)
                lib.nested.restype = ctypes.c_uint64
                assert lib.nested(ctypes.byref(x)) == 1+(expected >> 8)%1000
                x.value = seed
                lib.wrapped.restype = ctypes.c_uint32
                assert lib.wrapped(ctypes.byref(x)) == (expected-1)&0xffffffff
                x.value = seed
                lib.index_order.restype = ctypes.c_uint64
                assert lib.index_order(ctypes.byref(x)) == 31
                # Keep addition below u32 overflow in these order checks.
                x.value = seed
                lib.left.restype = ctypes.c_uint64
                assert lib.left(ctypes.byref(x)) == 12*10000000000+expected+3
                x.value = seed
                lib.right_rejected.restype = ctypes.c_uint64
                assert lib.right_rejected(ctypes.byref(x)) == 21*10000000000+expected+3
                x.value = seed
                lib.conditional.restype = ctypes.c_uint64
                assert lib.conditional(ctypes.byref(x), False) == 0 and x.value == seed
            x = ctypes.c_uint32()
            assert lib.indexed(ctypes.byref(x)) == 70
            assert lib.field(ctypes.byref(x)) == 7
            # Offset-one packed fields/arrays must retain their original
            # unaligned store semantics, despite an existing canonical *u64.
            wide = ctypes.c_uint64()
            packed = (ctypes.c_ubyte*17)()
            lib.packed_field.restype = ctypes.c_uint64
            result = lib.packed_field(ctypes.byref(packed), ctypes.byref(wide))
            assert result == int.from_bytes(bytes(packed[1:9]), 'little')
            lib.packed_index.restype = ctypes.c_uint64
            result = lib.packed_index(ctypes.byref(packed), ctypes.byref(wide))
            assert result == int.from_bytes(bytes(packed[1:9]), 'little')
            failures = []
            for statement in ('lib.bad_index(1)', 'lib.bad_pointer(None)',
                              'lib.bad_pointer(ctypes.c_void_p(1))',
                              'x=ctypes.c_uint32(1);lib.bad_overflow(ctypes.byref(x))',
                              'lib.bad_overflow(None)'):
                command = f'import ctypes;lib=ctypes.CDLL({str(libpath)!r});' + statement
                failed = run([sys.executable, '-c', command], timeout=10)
                assert failed.returncode == 101, failed
                assert 'RHS' not in failed.stdout, failed
                failures.append((failed.returncode, failed.stdout, failed.stderr))
            if mode == 'ssa':
                expected_failures = failures
            else:
                assert failures == expected_failures, (failures, expected_failures)
            if mode == 'ssa':
                asm = run(['objdump', '-d', libpath]).stdout
                for name in ('nested', 'wrapped', 'left', 'indexed', 'field', 'index_order'):
                    body = re.search(r'<'+name+r'>:\n(.*?)(?=\n\n|\Z)', asm, re.S)
                    assert body, name
                    assert not re.search(r'call.*<(?:step|change|change_field)(?:@plt)?>', body[1]), body[1]
                for name in ('packed_field', 'packed_index'):
                    body = re.search(r'<'+name+r'>:\n(.*?)(?=\n\n|\Z)', asm, re.S)
                    assert body and re.search(r'call.*<wide(?:@plt)?>', body[1]), name
                for name in ('right_rejected', 'conditional'):
                    body = re.search(r'<'+name+r'>:\n(.*?)(?=\n\n|\Z)', asm, re.S)
                    assert body and re.search(r'call.*<step(?:@plt)?>', body[1]), name
            print('PASS inline expressions', mode, 'nested values, side effects, conditional, indexed/field alias snapshots', flush=True)
        cc = shlex.split(os.environ.get('CC', 'cc'))
        (work/'harness.c').write_text(HARNESS)
        result = run([*cc, '-std=c11', '-D_POSIX_C_SOURCE=200809L', '-O1', '-ffunction-sections', '-fdata-sections', '-I'+str(ROOT/'src'), work/'harness.c', ROOT/'src/ast.c', '-Wl,--gc-sections', '-pthread', '-lm', '-o', work/'harness'])
        assert result.returncode == 0, result.stderr
        assert run([work/'harness']).returncode == 0
        print('PASS inline expressions pointer-type absence/const/table-limit fallbacks', flush=True)

if __name__ == '__main__':
    main()
