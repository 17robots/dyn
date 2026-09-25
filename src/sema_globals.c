#include "sema.h"
#include <stdio.h>
#include <stdlib.h>

typedef struct {
  DynAstProgram *a;
  const DynSource *s;
  unsigned *errors;
  unsigned char *state;
  bool *functions;
  uint32_t *order;
  size_t count;
  unsigned depth;
  bool stopped;
} InitGraph;
static bool visit_global(InitGraph *, uint32_t);
static bool visit_expr(InitGraph *g, DynExprId id);
static bool visit_block(InitGraph *g, uint32_t start, uint32_t count);
static bool enter_graph(InitGraph *g) {
  if (g->stopped) return false;
  if (g->depth >= 512 || !dyn_work_step(&g->s->context, 1)) {
    g->stopped = true;
    dyn_diagnostic_source("error", g->s, 0, 0,
        g->depth >= 512 ? "initializer dependency depth exceeds 512" :
                          "analysis work budget exceeded");
    ++*g->errors;
    return false;
  }
  ++g->depth;
  return true;
}


static void cycle_error(InitGraph *g, uint32_t id) {
  DynSpan span = g->a->globals[id].name;
  char message[256];
  snprintf(
      message, sizeof(message), "global initialization cycle involving '%.*s'",
      (int)(span.end_byte - span.start_byte), g->s->text + span.start_byte);
  dyn_diagnostic_source("error", g->s, span.start_byte, span.end_byte, message);
  ++*g->errors;
}
static bool visit_function(InitGraph *g, uint32_t id) {
  if (id >= g->a->function_count || g->functions[id])
    return true;
  g->functions[id] = true;
  DynAstFn *f = &g->a->functions[id];
  return visit_block(g, f->body_start, f->body_count);
}
static bool visit_expr_body(InitGraph *g, DynExprId id) {
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
static bool visit_expr(InitGraph *g, DynExprId id) {
  if (id == DYN_NO_EXPR) return true;
  if (!enter_graph(g)) return false;
  bool ok = visit_expr_body(g, id);
  --g->depth;
  return ok;
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
static bool visit_block_body(InitGraph *g, uint32_t start, uint32_t count) {
  for (uint32_t i = 0; i < count; ++i)
    if (!visit_stmt(g, &g->a->statements[g->a->children[start + i]]))
      return false;
  return true;
}
static bool visit_block(InitGraph *g, uint32_t start, uint32_t count) {
  if (!count) return true;
  if (!enter_graph(g)) return false;
  bool ok = visit_block_body(g, start, count);
  --g->depth;
  return ok;
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
  bool *functions = calloc(g->a->function_count, sizeof(*functions));
  if (g->a->function_count && !functions)
    return false;
  g->state[id] = 1;
  bool *saved = g->functions;
  g->functions = functions;
  bool ok = visit_expr(g, g->a->globals[id].initializer);
  free(g->functions);
  g->functions = saved;
  if (!ok) {
    g->state[id] = 0;
    return false;
  }
  g->state[id] = 2;
  if (g->a->globals[id].initializer != DYN_NO_EXPR)
    g->order[g->count++] = id;
  return true;
}
static bool order_initializers(DynAstProgram *a, const DynSource *s,
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
    if (!visit_global(&g, i)) {
      ok = false;
      if (g.stopped) break;
    }
  free(state);
  if (!ok) {
    free(order);
    return false;
  }
  a->global_init_order = order;
  a->global_init_count = g.count;
  return true;
}
bool dyn_sema_function(DynAstProgram *a, const DynSource *s, unsigned *errors) {
  if (!dyn_sema_base(a, s, errors))
    return false;
  return order_initializers(a, s, errors) && !*errors;
}
