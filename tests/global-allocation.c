#include <assert.h>
#include <stdlib.h>
#include "../src/sema.h"

static size_t calls, fail_at, live;
static void *checked_calloc(size_t count, size_t size) {
  if (++calls == fail_at) return NULL;
  void *p = calloc(count, size);
  assert(p);
  ++live;
  return p;
}
static void checked_free(void *p) { if (p) { assert(live); --live; free(p); } }
#define calloc checked_calloc
#define free checked_free
#include "../src/sema_globals.c"
#undef calloc
#undef free

int main(void) {
  DynAstGlobal globals[2] = {{.initializer = 0}, {.initializer = DYN_NO_EXPR}};
  DynAstExpr expression = {.kind = DYN_EXPR_GLOBAL, .integer = 1,
                          .left = DYN_NO_EXPR, .right = DYN_NO_EXPR};
  DynSource source = {.path = "test.dyn", .text = ""};
  size_t total = 0;
  for (fail_at = 0; fail_at <= total; ++fail_at) {
    calls = 0;
    DynAstProgram ast = {.globals = globals, .global_count = 2,
                         .function_count = 1, .expressions = &expression,
                         .expression_count = 1};
    unsigned errors = 0;
    bool ok = order_initializers(&ast, &source, &errors);
    if (!fail_at) { assert(ok); total = calls; }
    else assert(!ok);
    checked_free(ast.global_init_order);
    assert(live == 0);
  }
  return 0;
}
