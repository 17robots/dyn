/* Conservative linear-scan allocation for integer locals. Structured control
   flow supplies lexical intervals; loop uses extend to the whole loop. Escaped
   locals and functions with deferred cleanup remain in memory. The assigned
   hardware registers are callee-saved and never used by expression lowering. */
typedef struct {
  uint32_t first, last, reads, local;
  bool escaped;
} AllocationInterval;
typedef struct {
  const DynIrProgram *ir;
  const DynIrFunction *function;
  AllocationInterval *intervals;
  uint32_t position;
  bool failed, deferred;
} AllocationPlan;
static void allocation_touch(AllocationPlan *p, uint32_t id, bool read, bool address) {
  if (id == UINT32_MAX) return;
  if (id < p->function->local_start || id - p->function->local_start >= p->function->local_count) {
    p->failed = true; return;
  }
  AllocationInterval *v = &p->intervals[id - p->function->local_start];
  if (v->first == UINT32_MAX) v->first = p->position;
  v->last = p->position;
  if (read && v->reads < UINT32_MAX) ++v->reads;
  v->escaped |= address;
}
static void allocation_expression(AllocationPlan *p, DynExprId id, bool address, unsigned depth) {
  if (id == DYN_NO_EXPR || p->failed) return;
  if (depth > MAX_DEPTH || id >= p->ir->expression_count) { p->failed = true; return; }
  const DynIrExpr *e = &p->ir->expressions[id];
  if (e->kind == DYN_EXPR_NAME) { allocation_touch(p, (uint32_t)e->integer, true, address); return; }
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_BOOL || e->kind == DYN_EXPR_CHAR ||
      e->kind == DYN_EXPR_FLOAT || e->kind == DYN_EXPR_GLOBAL || e->kind == DYN_EXPR_FUNCTION ||
      e->kind == DYN_EXPR_STRING || e->kind == DYN_EXPR_NIL) return;
  allocation_expression(p, e->left, address || (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_ADDRESS), depth + 1);
  allocation_expression(p, e->right, address, depth + 1);
  if (e->kind == DYN_EXPR_SLICE) allocation_expression(p, (DynExprId)e->integer, address, depth + 1);
  if ((uint64_t)e->item_start + e->item_count > p->ir->item_count) { p->failed = true; return; }
  for (uint32_t i = 0; i < e->item_count; ++i)
    allocation_expression(p, p->ir->items[e->item_start + i].expression, address, depth + 1);
}
static void allocation_block(AllocationPlan *p, uint32_t start, uint32_t count, unsigned depth) {
  if (depth > MAX_DEPTH || (uint64_t)start + count > p->ir->child_count) { p->failed = true; return; }
  for (uint32_t i = 0; i < count && !p->failed; ++i) {
    uint32_t id = p->ir->children[start + i];
    if (id >= p->ir->statement_count || p->position == UINT32_MAX) { p->failed = true; return; }
    const DynIrStmt *s = &p->ir->statements[id];
    uint32_t begin = ++p->position;
    if (s->kind == DYN_STMT_DEFER) p->deferred = true;
    allocation_expression(p, s->expression, false, 0);
    allocation_expression(p, s->target, false, 0);
    if (s->kind == DYN_STMT_LOCAL || s->kind == DYN_STMT_ASSIGN ||
        (s->kind == DYN_STMT_FOR && (s->for_range || s->target != DYN_NO_EXPR)))
      allocation_touch(p, s->local_id, false, false);
    allocation_block(p, s->body_start, s->body_count, depth + 1);
    allocation_block(p, s->else_start, s->else_count, depth + 1);
    if ((uint64_t)s->case_arm_start + s->case_arm_count > p->ir->case_arm_count) { p->failed = true; return; }
    for (uint32_t a = 0; a < s->case_arm_count; ++a) {
      const DynIrCaseArm *arm = &p->ir->case_arms[s->case_arm_start + a];
      allocation_touch(p, arm->local_id, false, arm->pointer_binding);
      allocation_block(p, arm->body_start, arm->body_count, depth + 1);
    }
    if (s->kind == DYN_STMT_FOR) {
      /* Any value touched inside a loop can be live across its backedge. */
      uint32_t end = ++p->position;
      for (uint32_t local = 0; local < p->function->local_count; ++local) {
        AllocationInterval *v = &p->intervals[local];
        if (v->first != UINT32_MAX && v->last >= begin) {
          if (v->first > begin) v->first = begin;
          v->last = end;
        }
      }
    }
  }
}
static int allocation_order(const void *a, const void *b) {
  const AllocationInterval *x = a, *y = b;
  if (x->first != y->first) return x->first < y->first ? -1 : 1;
  return x->local < y->local ? -1 : x->local > y->local;
}
static bool allocation_plan(BackendContext *ctx, const DynSource *source,
                            const DynIrProgram *ir, const DynIrFunction *f) {
  ctx->allocator_used = 0; ctx->allocator_local_count = 0;
  const DynOptimization *policy = source->context.optimization;
  if (ctx->debug_mode || ctx->dwarf || ctx->win64 || ctx->winarm64 || ctx->rv64 || !policy || policy->level < 3)
    return true;
  AllocationInterval *v = calloc(f->local_count ? f->local_count : 1, sizeof(*v));
  if (!v) return false;
  memset(ctx->allocator_registers, -1, f->local_count * sizeof(*ctx->allocator_registers));
  for (uint32_t i = 0; i < f->local_count; ++i) {
    v[i].first = UINT32_MAX; v[i].local = i;
    DynType t = ir->locals[f->local_start + i].type;
    v[i].escaped = !(t == DYN_TYPE_BOOL || (t >= DYN_TYPE_I8 && t <= DYN_TYPE_USIZE));
  }
  AllocationPlan plan = {.ir = ir, .function = f, .intervals = v};
  for (uint32_t i = 0; i < f->param_count; ++i)
    allocation_touch(&plan, ir->params[f->param_start + i].local_id, false, false);
  allocation_block(&plan, f->body_start, f->body_count, 0);
  if (plan.failed) { free(v); return false; }
  if (plan.deferred) { free(v); return true; }
  qsort(v, f->local_count, sizeof(*v), allocation_order);
  int active[4] = {-1, -1, -1, -1};
  unsigned assigned = 0;
  for (uint32_t i = 0; i < f->local_count; ++i) {
    if (v[i].escaped || v[i].reads < 2 || v[i].first == UINT32_MAX) continue;
    int available = -1, latest = 0;
    for (int r = 0; r < 4; ++r) {
      if (active[r] >= 0 && v[active[r]].last < v[i].first) active[r] = -1;
      if (active[r] < 0) available = r;
      else if (active[latest] < 0 || v[active[r]].last > v[active[latest]].last) latest = r;
    }
    if (available < 0 && active[latest] >= 0 && v[active[latest]].last > v[i].last) {
      ctx->allocator_registers[v[active[latest]].local] = -1;
      available = latest;
      --assigned;
    }
    if (available >= 0) {
      ctx->allocator_registers[v[i].local] = (signed char)available;
      active[available] = (int)i; ++assigned;
    }
  }
  for (uint32_t i = 0; i < f->local_count; ++i)
    if (ctx->allocator_registers[i] >= 0) ctx->allocator_used |= 1u << ctx->allocator_registers[i];
  ctx->allocator_local_count = f->local_count;
  if (policy->remarks && assigned)
    fprintf(stderr, "remark: %s: %u integer locals allocated to callee-saved registers\n", f->name, assigned);
  free(v);
  return true;
}
