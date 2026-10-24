#!/usr/bin/env python3
"""Deterministic inliner allocation/size proof; no timing or global rebuild.

Compile the actual optimizer into a focused IR harness. This deliberately skips
scalar folding/backend optimization so residual calls measure inliner decisions.
Run from any directory: python3 tests/inlining-budget.py
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include "native_opt.c"
#include <assert.h>

/* Wide, reachable cold libraries precede a hot loop. Each caller has 80 calls;
   the middle function makes a two-level chain. Unreachable bodies are present
   in the input too, as with imported library declarations. */
static size_t records(const DynIrProgram *p);
static void run(unsigned cold, unsigned dead, bool hot_first, bool leaf_only) {
  unsigned n = cold + dead + 3;
  DynNativeOptimization o = {0};
  DynIrProgram *p = &o.ir;
  p->function_count = n;
  p->functions = calloc(n, sizeof(*p->functions));
  p->live.functions = calloc(n, sizeof(bool));
  p->expression_count = 3;
  p->expressions = calloc(3, sizeof(*p->expressions));
  p->expressions[0] = (DynIrExpr){.kind=DYN_EXPR_INT, .type=DYN_TYPE_I64,
      .integer=7, .left=DYN_NO_EXPR, .right=DYN_NO_EXPR};
  p->expressions[1] = (DynIrExpr){.kind=DYN_EXPR_CALL, .type=DYN_TYPE_I64,
      .integer=0, .left=DYN_NO_EXPR, .right=DYN_NO_EXPR};
  p->expressions[2] = p->expressions[1];
  p->expressions[2].integer = 1;
  p->statement_count = 83;
  p->statements = calloc(83, sizeof(*p->statements));
  p->child_count = 83;
  p->children = calloc(83, sizeof(*p->children));
  for (unsigned i=0; i<83; ++i) {
    p->children[i] = i;
    p->statements[i] = (DynIrStmt){.kind=DYN_STMT_EXPR,
        .expression=2, .target=DYN_NO_EXPR};
  }
  p->statements[0].kind = DYN_STMT_RETURN;
  p->statements[0].expression = 0;
  p->statements[1].kind = DYN_STMT_RETURN;
  p->statements[1].expression = 1;
  p->statements[82] = (DynIrStmt){.kind=DYN_STMT_FOR,
      .expression=DYN_NO_EXPR, .target=DYN_NO_EXPR,
      .body_start=2, .body_count=80};
  for (unsigned i=0; i<n; ++i) {
    p->functions[i] = (DynIrFunction){.return_type=DYN_TYPE_I64,
        .body_start=2, .body_count=80};
    p->live.functions[i] = i < cold+3;
  }
  p->functions[0].body_start=0; p->functions[0].body_count=1;
  p->functions[1].body_start=1; p->functions[1].body_count=1;
  unsigned hot = hot_first ? 2 : cold+2;
  p->functions[hot].body_start=82; p->functions[hot].body_count=1;
  /* O2 only permits straight-line leaves, so call the leaf directly. */
  if (leaf_only)
    for (unsigned i=2; i<82; ++i) p->statements[i].expression=1;
  uint32_t *children = p->children;
  DynIrFunction *functions = p->functions;
  bool *live = p->live.functions;
  assert(inline_program(&o, leaf_only, false));
  assert(o.owns_expansion);
  /* leaf costs 2+2=4; middle costs 9+2=11 plus the nested leaf's 4.
     O3 fits 34 chains (510), O2 fits six leaves (24).
     In particular, chain 18 was blocked by the former 256-unit budget;
     preceding cold callers cannot starve this later helper. */
  unsigned chains = leaf_only ? 6 : 34;
  assert(o.inlined == (leaf_only ? 6 : 1 + (cold+1)*68));
  DynIrFunction *f = &o.ir.functions[hot];
  DynIrStmt *loop = &o.ir.statements[o.ir.children[f->body_start]];
  assert(loop->kind == DYN_STMT_FOR);
  unsigned residual = 0;
  for (unsigned i=0; i<loop->body_count; ++i) {
    DynIrStmt *s = &o.ir.statements[o.ir.children[loop->body_start+i]];
    if (s->expression < o.ir.expression_count &&
        o.ir.expressions[s->expression].kind == DYN_EXPR_CALL) ++residual;
  }
  assert(residual == 80-chains);
  /* Physical statement growth stays linear even for the wide stress graph. */
  assert(o.ir.statement_count <= 83 + 512*(cold+3));
  /* Include original retained prefixes, declarations and a conservative
     unexpanded traversal (these input bodies intentionally share IDs). */
  assert(records(&o.ir) <= 86 + n + (cold+3)*(166 + 8*(leaf_only ? 24 : 512)));
  dyn_native_optimization_free(&o);
  free(children); free(functions); free(live);
}

/* Eighteen nested chains spend 270 units before a distinct late leaf.
   The former 256-unit allowance could not reach this helper. */
static void later_helper(void) {
  DynNativeOptimization o = {0};
  DynIrFunction functions[3] = {
    {.return_type=DYN_TYPE_I64,.body_count=1},
    {.return_type=DYN_TYPE_I64,.body_start=1,.body_count=1},
    {.return_type=DYN_TYPE_VOID,.body_start=2,.body_count=19}};
  uint32_t children[21];
  o.ir.functions=functions; o.ir.function_count=3;
  o.ir.children=children; o.ir.child_count=21;
  o.ir.expressions=calloc(3,sizeof(DynIrExpr)); o.ir.expression_count=3;
  o.ir.expressions[0]=(DynIrExpr){.kind=DYN_EXPR_INT,.type=DYN_TYPE_I64,
      .integer=7,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR};
  o.ir.expressions[1]=(DynIrExpr){.kind=DYN_EXPR_CALL,.type=DYN_TYPE_I64,
      .integer=0,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR};
  o.ir.expressions[2]=o.ir.expressions[1]; o.ir.expressions[2].integer=1;
  o.ir.statements=calloc(21,sizeof(DynIrStmt)); o.ir.statement_count=21;
  for (unsigned i=0;i<21;++i) {
    children[i]=i;
    o.ir.statements[i]=(DynIrStmt){.kind=i<2 ? DYN_STMT_RETURN : DYN_STMT_EXPR,
        .expression=i==0 ? 0 : i==1 || i==20 ? 1 : 2,.target=DYN_NO_EXPR};
  }
  assert(inline_program(&o,false,false) && o.owns_expansion);
  assert(o.inlined==38); /* middle's leaf, 18 chains, then the late leaf */
  DynIrFunction *caller=&o.ir.functions[2];
  for (unsigned i=0;i<caller->body_count;++i) {
    DynIrStmt *stmt=&o.ir.statements[o.ir.children[caller->body_start+i]];
    assert(stmt->expression==DYN_NO_EXPR ||
           o.ir.expressions[stmt->expression].kind!=DYN_EXPR_CALL);
  }
  dyn_native_optimization_free(&o);
}

static void recursion(void) {
  DynNativeOptimization o = {0};
  DynIrFunction f = {.return_type=DYN_TYPE_VOID, .body_count=1};
  uint32_t child = 0;
  o.ir.function_count=1; o.ir.functions=&f;
  o.ir.child_count=1; o.ir.children=&child;
  o.ir.expression_count=1; o.ir.expressions=calloc(1,sizeof(DynIrExpr));
  o.ir.expressions[0]=(DynIrExpr){.kind=DYN_EXPR_CALL, .integer=0,
      .left=DYN_NO_EXPR,.right=DYN_NO_EXPR};
  o.ir.statement_count=1; o.ir.statements=calloc(1,sizeof(DynIrStmt));
  o.ir.statements[0]=(DynIrStmt){.kind=DYN_STMT_EXPR,.expression=0,
      .target=DYN_NO_EXPR};
  assert(inline_program(&o,false,false));
  assert(!o.inlined && !o.owns_expansion);
  dyn_native_optimization_free(&o);
}

/* Count every owned record, including both per-local side tables. Patterns,
   type tables and strings are borrowed, never duplicated by this pass. */
static size_t records(const DynIrProgram *p) {
  return p->expression_count + p->statement_count + p->item_count +
      p->child_count + p->case_arm_count + 3*p->local_count +
      p->function_count + p->param_count;
}
static void resources(unsigned arms, unsigned locals, unsigned items) {
  DynNativeOptimization o = {0};
  DynIrProgram *p = &o.ir;
  DynIrFunction functions[3] = {
    {.return_type=DYN_TYPE_VOID,.body_count=1},
    {.return_type=DYN_TYPE_VOID,.body_start=1,.body_count=1,.local_count=locals},
    {.return_type=DYN_TYPE_VOID,.body_start=2,.body_count=41}};
  uint32_t children[43];
  DynIrLocal local_table[128] = {0};
  DynIrCaseArm *arm_table = calloc(arms ? arms : 1,sizeof(*arm_table));
  DynIrItem *item_table = calloc(items ? items : 1,sizeof(*item_table));
  p->functions=functions; p->function_count=3;
  p->children=children; p->child_count=43;
  p->locals=local_table; p->local_count=locals;
  p->case_arms=arm_table; p->case_arm_count=arms;
  p->items=item_table; p->item_count=items;
  p->expressions=calloc(5,sizeof(*p->expressions)); p->expression_count=5;
  for (unsigned i=0;i<5;++i)
    p->expressions[i]=(DynIrExpr){.kind=DYN_EXPR_INT,.type=DYN_TYPE_I64,
        .left=DYN_NO_EXPR,.right=DYN_NO_EXPR};
  p->expressions[1]=(DynIrExpr){.kind=DYN_EXPR_CALL,.integer=1,
      .type=DYN_TYPE_VOID,.left=DYN_NO_EXPR,.right=DYN_NO_EXPR};
  p->expressions[2]=p->expressions[1]; p->expressions[2].integer=0;
  p->expressions[3].kind=DYN_EXPR_ARRAY;
  p->expressions[3].item_count=items;
  /* Callee checks require cloning this operation even with constant inputs;
     the aggregate/item test must exercise real copying, not shared literals. */
  p->expressions[0].kind=DYN_EXPR_UNARY;
  p->expressions[0].op=DYN_OP_NEG;
  p->expressions[0].left=4;
  for (unsigned i=0;i<arms;++i) arm_table[i].local_id=UINT32_MAX;
  p->statements=calloc(43,sizeof(*p->statements)); p->statement_count=43;
  for (unsigned i=0;i<43;++i) {
    children[i]=i;
    p->statements[i]=(DynIrStmt){.kind=DYN_STMT_EXPR,.expression=1,
        .target=DYN_NO_EXPR,.local_id=UINT32_MAX};
  }
  p->statements[0].expression=0;
  p->statements[1].kind=items ? DYN_STMT_EXPR : DYN_STMT_CASE;
  p->statements[1].expression=items ? 3 : 0;
  p->statements[1].case_arm_count=arms;
  p->statements[42].expression=2; /* Always retain the transformed IR. */
  size_t input_records=records(p);
  assert(inline_program(&o,false,false) && o.owns_expansion);
  /* 40 calls to a 1000-empty-arm body used to produce 41000 arms.
     A whole local table must also be charged even with no local statements. */
  assert(o.ir.case_arm_count <= arms + 512);
  assert(o.ir.local_count <= locals + 4096/3);
  assert(records(&o.ir) <= input_records + 4096*3);
  if (arms==1000 || items==1000) assert(o.inlined==1);
  if (locals==128) assert(o.inlined>1 && o.inlined<12);
  if (arms==8 && !locals && !items) assert(o.inlined>1);
  if (items==8) {
    assert(o.inlined>1 && o.ir.item_count>items);
    assert(o.ir.local_count>locals && o.ir.unstable_locals && o.ir.local_statements);
  }
  /* Metadata contents and remapping survive accepted expansions. */
  for (size_t i=0;i<o.ir.case_arm_count;++i)
    assert(o.ir.case_arms[i].local_id==UINT32_MAX);
  assert(o.ir.items != item_table && o.ir.case_arms != arm_table);
  dyn_native_optimization_free(&o);
  free(arm_table); free(item_table);
}
int main(void) {
  for (unsigned cold=0; cold<=128; cold=cold ? cold*4 : 1)
    for (unsigned dead=0; dead<=256; dead+=256)
      for (unsigned first=0; first<2; ++first) {
        run(cold,dead,first,false);
        run(cold,dead,first,true);
      }
  later_helper();
  recursion();
  resources(1000,0,0);
  resources(0,128,0);
  resources(0,0,1000);
  resources(8,0,0);
  resources(0,8,8);
  resources(8,8,0);
  resources(60,64,0);
  puts("PASS caller reservations, nested charging, order/liveness stability, O2/O3 bounds, recursion, arm/local/item resources");
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-inlining-budget-') as directory:
    directory = Path(directory)
    source = directory/'test.c'
    source.write_text(HARNESS.replace('"native_opt.c"', '"'+os.environ.get('INLINE_OPT_SOURCE', 'native_opt.c')+'"'))
    output = directory/'test'
    subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-std=c11', '-O2',
                    '-D_POSIX_C_SOURCE=200809L', '-ffunction-sections', '-fdata-sections',
                    '-I'+str(ROOT/'src'), str(source), str(ROOT/'src/ast.c'), '-Wl,--gc-sections',
                    '-o', str(output)], check=True)
    subprocess.run([str(output)], check=True, timeout=30)
