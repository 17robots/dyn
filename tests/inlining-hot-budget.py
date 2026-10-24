#!/usr/bin/env python3
"""Bounded original-loop reservations prioritize tiny calls without cap growth."""
import ctypes
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()
HARNESS = r'''
#include "native_opt.c"
#include <assert.h>
static unsigned calls(const DynIrProgram *p,uint32_t start,uint32_t n,unsigned target,unsigned depth) {
 assert(depth<1000);unsigned total=0;
 for(unsigned i=0;i<n;i++) {
  const DynIrStmt *s=&p->statements[p->children[start+i]];
  if(s->expression<p->expression_count) {
   const DynIrExpr *e=&p->expressions[s->expression];
   if(e->kind==DYN_EXPR_CALL && e->integer==target)total++;
  }
  total+=calls(p,s->body_start,s->body_count,target,depth+1);
  total+=calls(p,s->else_start,s->else_count,target,depth+1);
 }
 return total;
}
static void late(bool loop,bool o2) {
 DynNativeOptimization o={0};DynIrProgram *p=&o.ir;
 DynIrFunction functions[4]={
  {.return_type=DYN_TYPE_U64,.body_count=1},
  {.return_type=DYN_TYPE_U64,.body_start=1,.body_count=1},
  {.return_type=DYN_TYPE_U64,.body_start=2,.body_count=1},
  {.return_type=DYN_TYPE_VOID,.body_start=3,.body_count=81}};
 p->functions=functions;p->function_count=4;
 p->expressions=calloc(4,sizeof(DynIrExpr));p->expression_count=4;
 p->expressions[0]=(DynIrExpr){.kind=DYN_EXPR_INT,.type=DYN_TYPE_U64,.integer=7,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR};
 for(unsigned i=1;i<4;i++)p->expressions[i]=(DynIrExpr){.kind=DYN_EXPR_CALL,.type=DYN_TYPE_U64,.integer=i-1,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR};
 p->statements=calloc(85,sizeof(DynIrStmt));p->statement_count=85;
 uint32_t children[85];p->children=children;p->child_count=85;
 for(unsigned i=0;i<85;i++) {
  children[i]=i;p->statements[i]=(DynIrStmt){.kind=DYN_STMT_EXPR,.expression=2,.target=DYN_NO_EXPR};
 }
 for(unsigned i=0;i<3;i++){p->statements[i].kind=DYN_STMT_RETURN;p->statements[i].expression=i==1?1:0;}
 p->statements[83]=(DynIrStmt){.kind=loop?DYN_STMT_FOR:DYN_STMT_EXPR,.expression=loop?DYN_NO_EXPR:3,
   .target=DYN_NO_EXPR,.body_start=loop?84:0,.body_count=loop?1:0,.loop_id=0};
 p->statements[84].expression=3;
 assert(inline_program(&o,o2,false));
 if(o2 && !loop){assert(!o.owns_expansion);dyn_native_optimization_free(&o);return;}
 assert(o.owns_expansion);
 DynIrFunction *f=&o.ir.functions[3];
 assert(calls(&o.ir,f->body_start,f->body_count,2,0)==(loop?0:1));
 /* Existing O2 eligibility/allowance is unchanged: one actual loop leaf only.
    No-loop O3 retains its original 34 middle chains + one other expansion. */
 if(o2)assert(o.inlined==1);
 else if(!loop)assert(o.inlined==69);
 assert(o.ir.statement_count<85+4*512);
 dyn_native_optimization_free(&o);
}
static void reservation(unsigned count,unsigned locals) {
 DynIrExpr call={.kind=DYN_EXPR_CALL,.type=DYN_TYPE_U64,.integer=0,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR};
 DynIrStmt statements[2]={{.kind=DYN_STMT_FOR,.expression=DYN_NO_EXPR,.target=DYN_NO_EXPR,.body_start=1,.body_count=count},
  {.kind=DYN_STMT_EXPR,.expression=0,.target=DYN_NO_EXPR}};
 uint32_t *children=calloc(count+1,sizeof(uint32_t));for(unsigned i=1;i<=count;i++)children[i]=1;
 DynIrFunction f={.return_type=DYN_TYPE_U64,.local_count=locals};bool active=false;unsigned cost=2;
 DynIrProgram p={.expressions=&call,.expression_count=1,.statements=statements,.statement_count=2,
  .children=children,.child_count=count+1,.functions=&f,.function_count=1};
 Inline b={.in=&p,.budget=512,.resource_budget=4096,.costs=&cost,.active=&active};
 unsigned remaining=4096;bool ok=inline_reserve_hot(&b,0,1,false,true,0,&remaining);
 if(count>4095)assert(!ok);
 else {
  assert(ok && b.reserved_growth<=128 && b.reserved_resources<=1024);
  assert(b.budget==512 && b.resource_budget==4096);
  if(locals==0)assert(b.reserved_growth==128 && b.reserved_resources==768);
  else assert(b.reserved_growth==8 && b.reserved_resources==816);
 }
 /* Recursion/foreign callees cannot reserve, even when tiny. */
 active=true;b.reserved_growth=b.reserved_resources=0;remaining=4096;
 if(count<=4095){assert(inline_reserve_hot(&b,0,1,false,true,0,&remaining));assert(!b.reserved_growth && !b.reserved_resources);}
 free(children);
}
static void rejected_sites(void) {
 DynIrExpr exprs[3]={
  {.kind=DYN_EXPR_CALL,.type=DYN_TYPE_BOOL,.integer=0,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR},
  {.kind=DYN_EXPR_BOOL,.type=DYN_TYPE_BOOL,.integer=0,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR},
  {.kind=DYN_EXPR_BINARY,.type=DYN_TYPE_BOOL,.op=DYN_OP_LOGICAL_AND,.left=1,.right=0}};
 DynIrStmt statements[20];uint32_t children[20];memset(statements,0,sizeof(statements));
 for(unsigned i=0;i<19;i++) {
  children[i]=i;statements[i]=(DynIrStmt){.kind=DYN_STMT_FOR,.expression=DYN_NO_EXPR,.target=DYN_NO_EXPR,.body_start=i+1,.body_count=1};
 }
 children[19]=19;statements[19]=(DynIrStmt){.kind=DYN_STMT_EXPR,.expression=0,.target=DYN_NO_EXPR};
 DynIrFunction f={.return_type=DYN_TYPE_BOOL};bool active=false;unsigned cost=2;
 DynIrProgram p={.expressions=exprs,.expression_count=3,.statements=statements,.statement_count=20,
  .children=children,.child_count=20,.functions=&f,.function_count=1};
 Inline b={.in=&p,.budget=512,.resource_budget=4096,.active=&active,.costs=&cost};unsigned remaining=4096;
 assert(inline_reserve_hot(&b,0,1,false,true,0,&remaining));
 assert(!b.reserved_growth && !b.reserved_resources); /* Actual depth>16 rejects. */
 statements[0].body_start=19;statements[19].expression=2;remaining=4096;
 assert(inline_reserve_hot(&b,0,1,false,true,0,&remaining));
 assert(!b.reserved_growth && !b.reserved_resources); /* Conditional RHS. */
 statements[0].kind=DYN_STMT_DEFER;statements[19].expression=0;remaining=4096;
 assert(inline_reserve_hot(&b,0,1,true,true,0,&remaining));
 assert(!b.reserved_growth && !b.reserved_resources); /* Deferred capture. */
}
static void resources(void) {
 DynIrExpr exprs[2]={{.kind=DYN_EXPR_INT,.type=DYN_TYPE_U64,.integer=7,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR},
  {.kind=DYN_EXPR_CALL,.type=DYN_TYPE_U64,.integer=0,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR}};
 DynIrStmt ret={.kind=DYN_STMT_RETURN,.expression=0,.target=DYN_NO_EXPR};uint32_t child=0;
 DynIrFunction f={.return_type=DYN_TYPE_U64,.body_count=1};bool active=false;unsigned cost=2;
 DynIrProgram p={.expressions=exprs,.expression_count=2,.statements=&ret,.statement_count=1,
  .children=&child,.child_count=1,.functions=&f,.function_count=1};
 Inline b={.in=&p,.budget=512,.resource_budget=24,.reserved_growth=4,.reserved_resources=24,
  .active=&active,.costs=&cost,.loop_stride=1};InlineScope scope={.function=&f,.expand=true};InlineList list={0};DynExprId result=0;
 assert(!inline_call(&b,&scope,&exprs[1],&list,&result,0));
 assert(b.budget==512 && b.resource_budget==24 && b.reserved_growth==4);
 scope.in_loop=true;scope.returns=true;
 assert(!inline_call(&b,&scope,&exprs[1],&list,&result,0)); /* Nested own loops cannot steal root quota. */
 scope.returns=false;assert(inline_call(&b,&scope,&exprs[1],&list,&result,0));
 assert(b.budget==508 && b.resource_budget==0 && !b.reserved_growth && !b.reserved_resources);
 free(list.ids);inline_free(&b.out);
}
int main(void){late(true,false);late(false,false);late(true,true);late(false,true);reservation(1000,0);reservation(1000,128);reservation(5000,0);rejected_sites();resources();puts("PASS hot reservation: late loops, no-loop/O2 controls, quarter caps, bounded scan, resource debits, recursion");}
'''
SOURCE = '''use "std/io"
state:u64=0
fn leaf(x:u64) u64 {return #wrap(x+1)}
fn cold(x:u64) u64 {return leaf(x)}
fn tiny_hot(x:u64) u64 {return #wrap(x*3+1)}
fn checked(x:u8) u8 {return x+1}
pub fn hot(seed:u64,n:usize) u64 {
 value:=seed
COLD
 for i in 0..n {value=tiny_hot(value)}
 return value
}
pub fn cold_only(seed:u64) u64 {value:=seed
COLD
 return tiny_hot(value)
}
pub fn conditional(seed:u64,n:usize) u64 {
 value:=seed
 for i in 0..n {if false && tiny_hot(value)>0 {#panic("conditional")}}
 return value
}
pub fn fail(x:u8) u8 {
 defer {_=io.write_all(io.stdout(),"CLEAN\\n")}
 for i in 0..1 {return checked(x)}
 return x
}
'''.replace('COLD','\n'.join(' value=cold(value)' for _ in range(80)))

def run(command, env=None, timeout=120):
    return subprocess.run(list(map(str,command)),env=env,capture_output=True,text=True,timeout=timeout)

def main():
    cc=shlex.split(os.environ.get('CC','cc'))
    if not cc or not shutil.which(cc[0]):
        print('SKIP hot budget: C compiler unavailable');return
    with tempfile.TemporaryDirectory(prefix='dyn-inline-hot-') as directory:
        work=Path(directory);(work/'harness.c').write_text(HARNESS)
        built=run([*cc,'-std=c11','-O1','-D_POSIX_C_SOURCE=200809L','-ffunction-sections','-fdata-sections','-I'+str(ROOT/'src'),work/'harness.c',ROOT/'src/ast.c','-Wl,--gc-sections','-o',work/'harness'])
        assert built.returncode==0,built.stderr
        result=run([work/'harness'],timeout=30);assert result.returncode==0,(result.returncode,result.stderr);print(result.stdout.strip(),flush=True)
        if platform.system()!='Linux' or platform.machine().lower() not in ('x86_64','amd64') or not shutil.which('objdump'):
            print('SKIP hot budget executable proof: Linux x86-64/objdump required');return
        module=work/'module';module.mkdir();(module/'main.dyn').write_text(SOURCE)
        env=dict(os.environ,DYN_SDK=str(ROOT));env.pop('DYN_NO_SSA',None)
        for mode in ('ssa','tree'):
            current=dict(env)
            if mode=='tree':current['DYN_NO_SSA']='1'
            binary=work/(mode+'.so');built=run([DYN,'build',module,'--release','--shared','--opt-level','3','--no-cache','--quiet','--output',binary],current)
            assert built.returncode==0,built.stderr
            lib=ctypes.CDLL(str(binary));lib.hot.restype=lib.cold_only.restype=lib.conditional.restype=ctypes.c_uint64
            lib.hot.argtypes=[ctypes.c_uint64,ctypes.c_size_t];lib.cold_only.argtypes=[ctypes.c_uint64];lib.conditional.argtypes=[ctypes.c_uint64,ctypes.c_size_t]
            for seed in (0,1,1000,(1<<64)-100):
                for n in (0,1,3,100):
                    expected=(seed+80)&((1<<64)-1)
                    for _ in range(n):expected=(expected*3+1)&((1<<64)-1)
                    assert lib.hot(seed,n)==expected
                    assert lib.conditional(seed,n)==seed
                assert lib.cold_only(seed)==(((seed+80)*3+1)&((1<<64)-1))
            if mode=='ssa':
                asm=run(['objdump','-d',binary]).stdout
                body=re.search(r'<hot>:\n(.*?)(?=\n\n|\Z)',asm,re.S)
                assert body and not re.search(r'call.*<tiny_hot(?:@plt)?>',body[1]),body[1] if body else asm
            import sys
            failure=run([sys.executable,'-c',f'import ctypes;lib=ctypes.CDLL({str(binary)!r});lib.fail(255)'],timeout=10)
            assert failure.returncode==101 and failure.stdout=='CLEAN\n',failure
            if mode=='ssa':expected_failure=failure.stderr
            else:assert failure.stderr==expected_failure,(failure.stderr,expected_failure)
            print('PASS hot reservation',mode,'late-helper values, wraps, conditional exclusion, overflow cleanup/origin',flush=True)

if __name__=='__main__':main()
