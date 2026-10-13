#define _POSIX_C_SOURCE 200809L
#define DYN_EXPERIMENT_COMPACT_DECLARATIONS
#include "../../src/frontend.c"
#include <assert.h>

static unsigned allocations, fail_at;
void *__real_realloc(void *, size_t);
void *__wrap_realloc(void *p, size_t n) {
  if (++allocations == fail_at) return NULL;
  return __real_realloc(p, n);
}
typedef struct { char bytes[16384]; size_t length; } Diagnostics;
static void collect(const char *severity, const char *path, unsigned line,
                    unsigned column, unsigned end_line, unsigned end_column,
                    const char *message, void *data) {
  Diagnostics *d = data;
  int count = snprintf(d->bytes + d->length, sizeof(d->bytes) - d->length,
      "%s|%s|%u:%u-%u:%u|%s\n", severity, path, line, column, end_line, end_column, message);
  assert(count >= 0 && (size_t)count < sizeof(d->bytes) - d->length);
  d->length += (size_t)count;
}
static bool cancelled(void *data) { (void)data; return true; }
static DynSource make_source(const char *text, Diagnostics *d) {
  return (DynSource){.path = "original/main.dyn", .text = (char *)text, .length = strlen(text),
    .context = {.diagnostic = collect, .diagnostic_data = d}};
}
static void same_result(DynAnalysisResult a, DynAnalysisResult b) {
  assert(a.errors == b.errors && a.has_main == b.has_main && a.main_valid == b.main_valid);
}
static void compare(const char *text, const char *main_path, bool mapped) {
  Diagnostics expected = {0}, actual = {0};
  DynSource s = make_source(text, &expected);
  DynSourceMap map = {.path = "dependency/main.dyn", .end = strlen(text), .original_text = (char *)text, .original_length = strlen(text)};
  if (mapped) { s.maps = &map; s.map_count = 1; }
  TSTree *tree = dyn_source_tree(&s);
  assert(tree && !ts_node_has_error(ts_tree_root_node(tree)));
  DynAnalysisResult reference = {0}, result = {0};
  analysis_declarations(ts_tree_root_node(tree), &s, main_path, &reference);
  s.context.diagnostic_data = &actual;
  assert(analysis_compact_declarations(&s, 0, (uint32_t)s.length, main_path, &result) == COMPACT_DECL_USED);
  same_result(reference, result);
  assert(!strcmp(expected.bytes, actual.bytes));
  ts_tree_delete(tree);
}
int main(void) {
  compare("pub fn main(){}", "original/main.dyn", false);
  compare("// comment\nfn main(x:i64) i64 {return x} fn main() {}", "other/main.dyn", false);
  compare("extern fn main() fn normal(){}", NULL, false);
  compare("fn main(args:...u8){}", NULL, false);
  compare("const main:=1 type X=i64 struct S{x:X} fn main(){}", "original/main.dyn", true);
  compare("#target(os:linux) #link(\"c\") use \"dep\" d fn main(){}", NULL, false);
  Diagnostics diagnostics = {0};
  DynSource s = make_source("fn main(){}", &diagnostics);
  DynAnalysisResult result = {0};
  allocations = 0;
  assert(analysis_compact_declarations(&s, 0, (uint32_t)s.length, NULL, &result) == COMPACT_DECL_USED);
  unsigned total = allocations;
  assert(total);
  for (unsigned stop = 1; stop <= total; ++stop) {
    allocations = 0; fail_at = stop; result = (DynAnalysisResult){0};
    diagnostics = (Diagnostics){0};
    assert(analysis_compact_declarations(&s, 0, (uint32_t)s.length, NULL, &result) == COMPACT_DECL_FAILED);
    assert(result.errors == 1 && !result.has_main && strstr(diagnostics.bytes, "out of memory"));
    fail_at = 0;
  }
  DynWork work = {.remaining = UINT64_MAX, .cancelled = cancelled};
  s.context.work = &work; diagnostics = (Diagnostics){0}; result = (DynAnalysisResult){0};
  assert(analysis_compact_declarations(&s, 0, (uint32_t)s.length, NULL, &result) == COMPACT_DECL_FAILED);
  assert(work.status == DYN_WORK_CANCELLED && result.errors == 1 && !result.has_main);
  work = (DynWork){.remaining = 1}; result = (DynAnalysisResult){0};
  assert(analysis_compact_declarations(&s, 0, (uint32_t)s.length, NULL, &result) == COMPACT_DECL_FAILED);
  assert(work.status == DYN_WORK_LIMIT);
  /* Exhaust exactly after parsing and the outer declaration checkpoint. The
     remaining main-signature traversal must still honor the external budget. */
  work = (DynWork){.remaining = UINT64_MAX};
  ExpOptions parse_options = {.work = compact_work, .data = &s.context};
  ExpTree parsed = {0};
  assert(exp_parse_source_with_options(s.text, s.length, &parsed, &parse_options));
  uint64_t parse_work = UINT64_MAX - work.remaining;
  exp_free(&parsed);
  work = (DynWork){.remaining = parse_work + 1}; result = (DynAnalysisResult){0};
  assert(analysis_compact_declarations(&s, 0, (uint32_t)s.length, NULL, &result) == COMPACT_DECL_FAILED);
  assert(work.status == DYN_WORK_LIMIT && result.errors == 1 && !result.has_main);
  s.context.work = NULL;
  /* Exercise the actual frontend boundary: terminal failures must not emit
     a false missing-main diagnostic or retry through Tree-sitter. */
  s.syntax = dyn_source_tree(&s); assert(s.syntax);
  DynAstProgram ast;
  diagnostics = (Diagnostics){0};
  result = dyn_analyze(&s, &ast, (DynAnalysisOptions){.require_main = true});
  assert(result.checked && result.has_main && !result.errors && !diagnostics.length);
  dyn_ast_program_free(&ast);
  diagnostics = (Diagnostics){0}; allocations = 0; fail_at = 1;
  result = dyn_analyze(&s, &ast, (DynAnalysisOptions){.require_main = true});
  assert(result.parsed && !result.checked && result.errors == 1);
  assert(strstr(diagnostics.bytes, "out of memory") && !strstr(diagnostics.bytes, "requires"));
  dyn_ast_program_free(&ast); fail_at = 0;
  diagnostics = (Diagnostics){0}; work = (DynWork){.remaining = UINT64_MAX, .cancelled = cancelled};
  s.context.work = &work;
  result = dyn_analyze(&s, &ast, (DynAnalysisOptions){.require_main = true});
  assert(result.parsed && !result.checked && result.errors == 1);
  assert(work.status == DYN_WORK_CANCELLED && !strstr(diagnostics.bytes, "requires"));
  dyn_ast_program_free(&ast); s.context.work = NULL;
  dyn_source_discard_syntax(&s);
  /* Real merged-source partitions must use the new reader too. Allocation
     failure is injected after Tree-sitter preparation/merging, proving entry. */
  DynSource inputs[2] = {make_source("fn main(){}", &diagnostics),
                         make_source("// second file\nfn main(){}", &diagnostics)};
  inputs[1].path = "original/second.dyn";
  assert(dyn_source_prepare(&inputs[0]) && dyn_source_prepare(&inputs[1]));
  DynSources sources = {.items = inputs, .count = 2};
  DynSource merged;
  assert(!dyn_sources_merge(&sources, "merged", &merged));
  assert(merged.syntax_part_count == 2);
  diagnostics = (Diagnostics){0}; allocations = 0; fail_at = 1;
  result = dyn_analyze(&merged, &ast, (DynAnalysisOptions){.require_main = true});
  assert(result.parsed && !result.checked && result.errors == 1 && !result.has_main);
  assert(strstr(diagnostics.bytes, "out of memory") && !strstr(diagnostics.bytes, "requires"));
  dyn_ast_program_free(&ast); fail_at = 0; diagnostics = (Diagnostics){0};
  result = dyn_analyze(&merged, &ast, (DynAnalysisOptions){.require_main = true});
  assert(result.has_main && result.errors == 1 && !result.checked);
  assert(strstr(diagnostics.bytes, "original/second.dyn|2:4-2:8|duplicate function 'main'"));
  dyn_ast_program_free(&ast); dyn_source_free(&merged);
  dyn_source_discard_syntax(&inputs[0]); dyn_source_discard_syntax(&inputs[1]);
  /* Production-valid depth beyond the compact recursion cap must use the
     existing consumer. Its diagnostics and locations remain authoritative. */
  char deep[2048]; size_t n = 0;
  memcpy(deep, "fn main(){_=", 12); n = 12;
  memset(deep+n, '(', 300); n += 300; deep[n++] = '1';
  memset(deep+n, ')', 300); n += 300; deep[n++] = '}'; deep[n] = 0;
  s.text = deep; s.length = n; diagnostics = (Diagnostics){0}; result = (DynAnalysisResult){0};
  TSTree *tree = dyn_source_tree(&s); assert(tree && !ts_node_has_error(ts_tree_root_node(tree)));
  assert(analysis_compact_declarations(&s, 0, (uint32_t)s.length, NULL, &result) == COMPACT_DECL_FALLBACK);
  assert(!result.errors && !result.has_main && !diagnostics.length);
  analysis_declarations(ts_tree_root_node(tree), &s, NULL, &result);
  assert(result.has_main && !result.errors);
  ts_tree_delete(tree);
  /* Compact syntax rejection must not invent diagnostics for the old reader. */
  s.text = "fn"; s.length = 2; result = (DynAnalysisResult){0};
  assert(analysis_compact_declarations(&s, 0, (uint32_t)s.length, NULL, &result) == COMPACT_DECL_FALLBACK);
  assert(!result.errors);
  puts("PASS declaration consumer parity, original locations, depth fallback and resource failures");
}
