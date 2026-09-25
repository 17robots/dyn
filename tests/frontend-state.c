#define _POSIX_C_SOURCE 200809L
#include "frontend.h"
#include "dyn_syntax.h"
#include "dyn_location.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>

typedef struct { unsigned diagnostics; bool nested; } Sink;
static void collect(const char *severity, const char *path, unsigned line,
                    unsigned column, unsigned end_line, unsigned end_column,
                    const char *message, void *data) {
  (void)path; (void)line; (void)column; (void)end_line; (void)end_column; (void)message;
  Sink *sink = data;
  if (!strcmp(severity, "error")) ++sink->diagnostics;
  if (!sink->nested) {
    sink->nested = true;
    char text[] = "fn main() { for i in [0,1,2] { if i == 2 { break } } }";
    DynSource source = {.path = "main.dyn", .text = text, .length = strlen(text)};
    DynAstProgram ast;
    DynAnalysisResult result = dyn_analyze(&source, &ast, (DynAnalysisOptions){0});
    assert(result.checked);
    dyn_ast_program_free(&ast);
  }
}
static void *analyze(void *argument) {
  const char *target = argument;
  for (unsigned i = 0; i < 40; ++i) {
    Sink sink = {0};
    char text[] = "distinct type Value = i32\nfn add(x: Value) Value { return x + #cast(Value) 1 }\n"
                  "fn main() { x := add(#cast(Value) 2) for i in [0,1,2] { if i == 2 { break } } _ = #syscall(999) }";
    DynSource source = {.path = "main.dyn", .text = text, .length = strlen(text),
      .context = {.target = dyn_target_find(target), .diagnostic = collect, .diagnostic_data = &sink}};
    DynAstProgram ast;
    DynAnalysisResult result = dyn_analyze(&source, &ast, (DynAnalysisOptions){.require_main = true});
    bool valid = !strcmp(target, "x86_64-linux");
    assert(result.checked == valid);
    assert(valid ? !sink.diagnostics : sink.diagnostics > 0);
    dyn_ast_program_free(&ast);
  }
  return NULL;
}
static void merged_syntax(void) {
  char table[32768] = "const values: [2048]i32 = [";
  size_t at = strlen(table);
  for (unsigned i = 0; i < 2048; ++i)
    at += (size_t)snprintf(table + at, sizeof(table) - at, "%s%u", i ? "," : "", i);
  strcpy(table + at, "]\n");
  DynSource inputs[] = {
    {.path = "before.dyn", .text = "// π\nfn before() {}\n", .needs_reflection = true},
    {.path = "table.dyn", .text = table},
    {.path = "after.dyn", .text = "fn main() {}\n"}};
  for (size_t i = 0; i < 3; ++i) {
    inputs[i].length = strlen(inputs[i].text);
    assert(dyn_source_prepare(&inputs[i]));
  }
  DynSource merged = {0}; DynSources sources = {inputs, 3};
  assert(!dyn_sources_merge(&sources, "merged", &merged) && merged.syntax);
  TSTree *fresh = dyn_syntax_parse(merged.text, merged.length);
  assert(fresh && !ts_node_has_error(ts_tree_root_node(fresh)));
  TSTreeCursor a = ts_tree_cursor_new(ts_tree_root_node(merged.syntax));
  TSTreeCursor b = ts_tree_cursor_new(ts_tree_root_node(fresh));
  bool done = false;
  while (!done) {
    TSNode x = ts_tree_cursor_current_node(&a), y = ts_tree_cursor_current_node(&b);
    assert(!strcmp(ts_node_type(x), ts_node_type(y)));
    assert(ts_node_start_byte(x) == ts_node_start_byte(y) && ts_node_end_byte(x) == ts_node_end_byte(y));
    TSPoint xp = ts_node_start_point(x), yp = ts_node_start_point(y);
    assert(xp.row == yp.row && xp.column == yp.column);
    bool child = ts_tree_cursor_goto_first_child(&a);
    assert(child == ts_tree_cursor_goto_first_child(&b));
    if (child) continue;
    for (;;) {
      bool sibling = ts_tree_cursor_goto_next_sibling(&a);
      assert(sibling == ts_tree_cursor_goto_next_sibling(&b));
      if (sibling) break;
      bool parent = ts_tree_cursor_goto_parent(&a);
      assert(parent == ts_tree_cursor_goto_parent(&b));
      if (!parent) { done = true; break; }
    }
  }
  ts_tree_cursor_delete(&a); ts_tree_cursor_delete(&b); ts_tree_delete(fresh);
  DynLocationIndex index = {0}; assert(dyn_location_build(&index, &merged));
  for (size_t i = 0; i <= merged.length + 1; ++i) {
    const char *a_path, *b_path; unsigned al, ac, bl, bc;
    dyn_source_location(&merged, i, &a_path, &al, &ac);
    dyn_location_get(&index, &merged, i, &b_path, &bl, &bc);
    assert(!strcmp(a_path, b_path) && al == bl && ac == bc);
  }
  dyn_location_free(&index); dyn_source_free(&merged);
  for (size_t i = 0; i < 3; ++i) dyn_source_discard_syntax(&inputs[i]);
}
int main(void) {
  merged_syntax();
  pthread_t threads[8];
  for (unsigned i = 0; i < 8; ++i)
    assert(!pthread_create(&threads[i], NULL, analyze, (void *)(i % 2 ? "aarch64-linux" : "x86_64-linux")));
  for (unsigned i = 0; i < 8; ++i) assert(!pthread_join(threads[i], NULL));
  return 0;
}
