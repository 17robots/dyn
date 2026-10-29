#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "../src/dyn_ast.h"

static bool fail_blocks;
static unsigned failures;
static void *ast_test_calloc(size_t count, size_t size);
#define calloc ast_test_calloc
#include "../src/ast.c"
#undef calloc
/* Declaration references: one allocation per lowering. */
static void *ast_test_calloc(size_t count, size_t size) {
  if (fail_blocks && count && size == sizeof(struct DynCompactDeclaration) &&
      size != sizeof(struct DynCompactBody)) { ++failures; return NULL; }
  return calloc(count, size);
}

int main(void) {
  char text[] = "fn main() {\n  case 1 {\n    1 => {}\n    _ => {}\n  }\n}\n";
  DynSource source = {.path = "test.dyn", .text = text, .length = strlen(text)};
  for (unsigned test = 0; test < 2; ++test) {
    DynAstProgram ast = {0};
    unsigned errors = 0;
    fail_blocks = test != 0;
    assert(dyn_source_prepare(&source));
    bool ok = dyn_ast_lower_compact(&source, &ast, &errors, NULL);
    assert(test ? (!ok && errors == 1 && failures == 1) : (ok && !errors));
    dyn_source_discard_syntax(&source);
    dyn_ast_program_free(&ast);
  }
  return 0;
}
