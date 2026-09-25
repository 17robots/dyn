#define _POSIX_C_SOURCE 200809L
#include "frontend.h"
#include "ir.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "fault-alloc.h"
static void ignore(const char *a, const char *b, unsigned c, unsigned d, unsigned e, unsigned f, const char *g, void *h) {
  (void)a; (void)b; (void)c; (void)d; (void)e; (void)f; (void)g; (void)h;
}
int main(void) {
  char text[16384] = "struct Pair { x: i32, flag: bool }\nenum Choice { A, B: i32 }\n"
    "const answer: i32 = 42\nfn add(value: i32) i32 { return value + answer }\n"
    "fn consume(value: i32) { _ = value }\n"
    "fn main() { consume(1) callback := &consume callback(2) p := Pair{x: add(1), flag: true} values := [1,2,3] for item in values { if item == p.x { break } } _ = \"hello\" }\n";
  // Cross the small-function threshold and exercise local-index growth/failure.
  strcat(text, "fn many() { ");
  for (unsigned i = 0; i < 80; ++i) {
    char local[64]; snprintf(local, sizeof(local), "value%u := %u _ = value%u ", i, i, i);
    strcat(text, local);
  }
  strcat(text, "}\n");
  for (unsigned i = 0; i < 40; ++i) {
    char declaration[128];
    snprintf(declaration, sizeof(declaration), "struct S%u { value: i32 }\ntype A%u = S%u\nfn f%u(x: A%u) { _ = x.value }\n", i, i, i, i, i);
    strcat(text, declaration);
  }
  strcat(text, "struct Wide { ");
  for (unsigned i = 0; i < 40; ++i) {
    char field[32]; snprintf(field, sizeof(field), "%sf%u: i32", i ? "," : "", i);
    strcat(text, field);
  }
  strcat(text, " }\nfn wide(x: Wide) { _ = x.f39 }\n");
  DynSource source = {.path = "main.dyn", .text = text, .length = strlen(text), .context = {.diagnostic = ignore}};
  size_t total = 0;
  for (size_t iteration = 0; !iteration || iteration <= total; ++iteration) {
    calls = failed = 0; fail_at = iteration;
    DynAstProgram ast;
    DynAnalysisResult result = dyn_analyze(&source, &ast, (DynAnalysisOptions){.require_main = true});
    if (!iteration) { assert(result.checked); total = calls; }
    else assert(failed && !result.checked);
    dyn_ast_program_free(&ast);
  }
  fail_at = 0;
  DynAstProgram ast;
  assert(dyn_analyze(&source, &ast, (DynAnalysisOptions){0}).checked);
  total = 0;
  for (size_t iteration = 0; !iteration || iteration <= total; ++iteration) {
    calls = failed = 0; fail_at = iteration;
    DynIrProgram ir;
    bool ok = dyn_ir_lower(&ast, &source, &ir);
    if (!iteration) { assert(ok); total = calls; }
    /* Optional range optimization may decline allocation and still lower safely. */
    else assert(failed);
    dyn_ir_free(&ir);
  }
#ifdef TEST_CODEGEN
  fail_at = 0;
  char object[] = "/tmp/dyn-codegen-failure-XXXXXX";
  int fd = mkstemp(object); assert(fd >= 0); close(fd);
  total = 0;
  for (size_t iteration = 0; !iteration || iteration <= total; ++iteration) {
    calls = failed = 0; fail_at = iteration;
    int result = dyn_codegen_main(&source, object, NULL, NULL, false, true, false);
    if (!iteration) { assert(!result); total = calls; }
    else { assert(failed); assert(result == 0 || result == 1 || result == 2); }
    unlink(object);
  }
#endif
  dyn_ast_program_free(&ast);
  return 0;
}
