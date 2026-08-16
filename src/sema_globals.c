#include "sema.h"
#include <stdio.h>
#include <stdlib.h>
#undef dyn_sema_function

typedef struct {
  DynAstFunction *a;
  const DynSource *s;
  unsigned *errors;
  unsigned char *state;
  bool *functions;
  uint32_t *order;
  size_t count;
} InitGraph;
static bool visit_global(InitGraph *, uint32_t);
static bool visit_expr(InitGraph *g, DynExprId id);
static bool visit_block(InitGraph *g, uint32_t start, uint32_t count);

static void cycle_error(InitGraph *g, uint32_t id) {
  DynSpan span = g->a->globals[id].name;
  unsigned line = 1, column = 1;
  for (uint32_t i = 0; i < span.start_byte && i < g->s->length; ++i)
    if (g->s->text[i] == '\n') {
      ++line;
      column = 1;
    } else
      ++column;
  fprintf(stderr,
          "%s:%u:%u: error: global initialization cycle involving '%.*s'\n",
          g->s->path, line, column, (int)(span.end_byte - span.start_byte),
          g->s->text + span.start_byte);
  ++*g->errors;
}
static bool visit_function(InitGraph *g, uint32_t id) {
  if (id >= g->a->function_count || g->functions[id])
    return true;
  g->functions[id] = true;
  DynAstFn *f = &g->a->functions[id];
  return visit_block(g, f->body_start, f->body_count);
}
static bool visit_expr(InitGraph *g, DynExprId id) {
  if (id == DYN_NO_EXPR || id >= g->a->expression_count)
    return true;
  DynAstExpr *e = &g->a->expressions[id];
  if (e->kind == DYN_EXPR_GLOBAL && !visit_global(g, (uint32_t)e->integer))
    return false;
  if (e->kind == DYN_EXPR_CALL && !visit_function(g, (uint32_t)e->integer))
    return false;
  if (!visit_expr(g, e->left) || !visit_expr(g, e->right))
    return false;
  for (uint32_t i = 0; i < e->item_count; ++i)
    if (!visit_expr(g, g->a->items[e->item_start + i].expression))
      return false;
  return true;
}
static bool visit_stmt(InitGraph *g, DynAstStmt *st) {
  if (!visit_expr(g, st->expression) || !visit_expr(g, st->target))
    return false;
  if (!visit_block(g, st->body_start, st->body_count) ||
      !visit_block(g, st->else_start, st->else_count))
    return false;
  for (uint32_t i = 0; i < st->case_arm_count; ++i) {
    DynAstCaseArm *arm = &g->a->case_arms[st->case_arm_start + i];
    if (!visit_block(g, arm->body_start, arm->body_count))
      return false;
  }
  return true;
}
static bool visit_block(InitGraph *g, uint32_t start, uint32_t count) {
  for (uint32_t i = 0; i < count; ++i)
    if (!visit_stmt(g, &g->a->statements[g->a->children[start + i]]))
      return false;
  return true;
}
static bool visit_global(InitGraph *g, uint32_t id) {
  if (id >= g->a->global_count)
    return false;
  if (g->state[id] == 2)
    return true;
  if (g->state[id] == 1) {
    cycle_error(g, id);
    return false;
  }
  g->state[id] = 1;
  bool *saved = g->functions;
  g->functions = calloc(g->a->function_count, sizeof(*g->functions));
  if (g->a->function_count && !g->functions)
    return false;
  bool ok = visit_expr(g, g->a->globals[id].initializer);
  free(g->functions);
  g->functions = saved;
  if (!ok)
    return false;
  g->state[id] = 2;
  if (g->a->globals[id].initializer != DYN_NO_EXPR)
    g->order[g->count++] = id;
  return true;
}
static bool order_initializers(DynAstFunction *a, const DynSource *s,
                               unsigned *errors) {
  if (!a->global_count)
    return true;
  unsigned char *state = calloc(a->global_count, 1);
  uint32_t *order = calloc(a->global_count, sizeof(*order));
  if (!state || !order) {
    free(state);
    free(order);
    return false;
  }
  InitGraph g = {
      .a = a, .s = s, .errors = errors, .state = state, .order = order};
  bool ok = true;
  for (uint32_t i = 0; i < a->global_count; ++i)
    if (!visit_global(&g, i))
      ok = false;
  free(state);
  if (!ok) {
    free(order);
    return false;
  }
  a->global_init_order = order;
  a->global_init_count = g.count;
  return true;
}
bool dyn_sema_function(DynAstFunction *a, const DynSource *s,
                       unsigned *errors) {
  if (!dyn_sema_base(a, s, errors))
    return false;
  return order_initializers(a, s, errors) && !*errors;
}
