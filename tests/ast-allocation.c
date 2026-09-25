#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <tree_sitter/api.h>
#include "../src/dyn_ast.h"

static bool fail_blocks;
static unsigned failures;
static void *ast_test_calloc(size_t count, size_t size) {
  if (fail_blocks && count && size == sizeof(TSNode)) { ++failures; return NULL; }
  return calloc(count, size);
}
#define calloc ast_test_calloc
#include "../src/ast.c"
#undef calloc

int main(void) {
  char text[] = "fn main() { case 1 { 1 => {}, _ => {}, } }\n";
  DynSource source = {.path = "test.dyn", .text = text, .length = strlen(text)};
  for (unsigned test = 0; test < 2; ++test) {
    DynAstProgram ast = {0};
    unsigned errors = 0;
    fail_blocks = test != 0;
    bool ok = dyn_ast_parse_main_source(&source, &ast, &errors);
    assert(ok); /* The return value reports entrypoint presence; errors reports lowering failures. */
    assert(test ? (errors == 1 && failures == 1) : !errors);
    dyn_ast_program_free(&ast);
  }
  return 0;
}
