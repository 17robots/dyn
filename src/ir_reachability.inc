typedef struct {
  const DynIrProgram *ir;
  bool *live;
  bool *globals; /* optional: when set, only referenced globals are live */
  unsigned char *expressions, *statements;
  uint32_t *queue;
  size_t count;
} Reachability;
static bool reachable_function(Reachability *p, uint64_t id) {
  if (id >= p->ir->function_count) return false;
  if (!p->live[id] && !p->ir->functions[id].generic) {
    p->live[id] = true;
    p->queue[p->count++] = (uint32_t)id;
  }
  return true;
}
static bool reachable_expression(Reachability *p, DynExprId id, unsigned depth);
static bool reachable_global(Reachability *p, uint64_t id, unsigned depth) {
  if (id >= p->ir->global_count) return false;
  if (!p->globals || p->globals[id]) return true;
  p->globals[id] = true;
  return reachable_expression(p, p->ir->globals[id].initializer, depth + 1);
}
/* A global whose initializer calls a function may have effects: keep it. */
static bool initializer_calls(const DynIrProgram *ir, DynExprId id, unsigned depth) {
  if (id == DYN_NO_EXPR) return false;
  if (id >= ir->expression_count || depth > 1024) return true;
  const DynIrExpr *e = &ir->expressions[id];
  if (e->kind == DYN_EXPR_CALL) return true;
  if (initializer_calls(ir, e->left, depth + 1) || initializer_calls(ir, e->right, depth + 1)) return true;
  if (e->kind == DYN_EXPR_SLICE && initializer_calls(ir, (DynExprId)e->integer, depth + 1)) return true;
  if ((uint64_t)e->item_start + e->item_count > ir->item_count) return true;
  for (uint32_t i = 0; i < e->item_count; ++i)
    if (initializer_calls(ir, ir->items[e->item_start + i].expression, depth + 1)) return true;
  return false;
}
static bool reachable_expression(Reachability *p, DynExprId id, unsigned depth) {
  if (id == DYN_NO_EXPR) return true;
  if (id >= p->ir->expression_count || depth > 1024) return false;
  if (p->expressions[id]) return true;
  p->expressions[id] = 1;
  const DynIrExpr *e = &p->ir->expressions[id];
  if (e->kind == DYN_EXPR_FUNCTION) return reachable_function(p, e->integer);
  if (e->kind == DYN_EXPR_GLOBAL) return reachable_global(p, e->integer, depth);
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_FLOAT || e->kind == DYN_EXPR_BOOL ||
      e->kind == DYN_EXPR_CHAR || e->kind == DYN_EXPR_STRING || e->kind == DYN_EXPR_NIL ||
      e->kind == DYN_EXPR_NAME) return true;
  if (e->kind == DYN_EXPR_CALL && !reachable_function(p, e->integer)) return false;
  if (!reachable_expression(p, e->left, depth + 1) ||
      !reachable_expression(p, e->right, depth + 1)) return false;
  if (e->kind == DYN_EXPR_SLICE && !reachable_expression(p, (DynExprId)e->integer, depth + 1)) return false;
  if ((uint64_t)e->item_start + e->item_count > p->ir->item_count) return false;
  for (uint32_t i = 0; i < e->item_count; ++i)
    if (!reachable_expression(p, p->ir->items[e->item_start + i].expression, depth + 1)) return false;
  return true;
}
static bool reachable_block(Reachability *p, uint32_t start, uint32_t count, unsigned depth) {
  if (depth > 1024 || (uint64_t)start + count > p->ir->child_count) return false;
  for (uint32_t i = 0; i < count; ++i) {
    uint32_t id = p->ir->children[start + i];
    if (id >= p->ir->statement_count) return false;
    if (p->statements[id]) continue;
    p->statements[id] = 1;
    const DynIrStmt *s = &p->ir->statements[id];
    if (!reachable_expression(p, s->expression, 0) || !reachable_expression(p, s->target, 0) ||
        !reachable_block(p, s->body_start, s->body_count, depth + 1) ||
        !reachable_block(p, s->else_start, s->else_count, depth + 1)) return false;
    if ((uint64_t)s->case_arm_start + s->case_arm_count > p->ir->case_arm_count) return false;
    for (uint32_t a = 0; a < s->case_arm_count; ++a) {
      const DynIrCaseArm *arm = &p->ir->case_arms[s->case_arm_start + a];
      if (!reachable_block(p, arm->body_start, arm->body_count, depth + 1)) return false;
    }
  }
  return true;
}
/* Public functions are roots for reusable objects and libraries. Executables
   without external link inputs can instead start at main and initializers. */
static bool reachable_collect(Reachability *p, bool public_roots, bool all_roots) {
  bool ok = p->expressions && p->statements && p->queue;
  const DynIrProgram *ir = p->ir;
  for (size_t i = 0; ok && i < ir->function_count; ++i) {
    const DynIrFunction *f = &ir->functions[i];
    if (f->is_main || (public_roots && f->is_public) || f->foreign || all_roots)
      ok = reachable_function(p, i);
  }
  /* Without a globals map every initializer is a root. With one, roots are
     public globals of libraries and initializers that may have effects;
     the rest stay only when live code names them. */
  for (size_t i = 0; ok && i < ir->global_count; ++i) {
    const DynIrGlobal *g = &ir->globals[i];
    if (!p->globals) ok = reachable_expression(p, g->initializer, 0);
    else if (all_roots || (public_roots && g->is_public) || g->foreign || initializer_calls(ir, g->initializer, 0))
      ok = reachable_global(p, i, 0);
  }
  for (size_t at = 0; ok && at < p->count; ++at) {
    const DynIrFunction *f = &ir->functions[p->queue[at]];
    if (!f->foreign) ok = reachable_block(p, f->body_start, f->body_count, 0);
  }
  return ok;
}
