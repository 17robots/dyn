#define _POSIX_C_SOURCE 200809L
#include "frontend.h"
#include "dyn_compact.h"
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
    char text[] = "distinct type Value = i32\nfn add(x: Value) Value { return x + #cast(Value, 1) }\n"
                  "fn main() { x := add(#cast(Value, 2))\n for i in [0,1,2] { if i == 2 { break } }\n _ = #syscall(999) }";
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
/* Same shape and spans; offset shifts x into the merged text. */
static void same_subtree(const ExpSnapshotTree *xt, uint32_t x, uint32_t offset,
                         const ExpSnapshotTree *yt, uint32_t y) {
  const ExpNode *a = &xt->nodes[x], *b = &yt->nodes[y];
  assert(a->kind == b->kind && a->flags == b->flags && a->field == b->field);
  assert(a->start + offset == b->start && a->end + offset == b->end);
  uint32_t i = a->first, j = b->first;
  for (; i != UINT32_MAX && j != UINT32_MAX; i = xt->nodes[i].next, j = yt->nodes[j].next)
    same_subtree(xt, i, offset, yt, j);
  assert(i == UINT32_MAX && j == UINT32_MAX);
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
  assert(!dyn_sources_merge(&sources, "merged", &merged) && merged.syntax_part_count == 4);
  /* Per-file trees, shifted by their partition, match a fresh parse of the
     merged text. */
  ExpSnapshot *fresh = exp_snapshot_create(merged.text, merged.length, NULL, NULL);
  assert(fresh && !exp_snapshot_tree(fresh)->error_count);
  const ExpSnapshotTree *root = exp_snapshot_tree(fresh);
  uint32_t top = root->nodes[root->root].first;
  size_t prelude = merged.syntax_part_count - merged.map_count;
  for (size_t part = 0; part < merged.syntax_part_count; ++part) {
    const ExpSnapshotTree *shifted = exp_snapshot_tree(merged.compact_parts[part]);
    uint32_t offset = part < prelude ? 0 : (uint32_t)merged.maps[part - prelude].start;
    for (uint32_t i = shifted->nodes[shifted->root].first; i != UINT32_MAX; i = shifted->nodes[i].next) {
      assert(top != UINT32_MAX);
      same_subtree(shifted, i, offset, root, top);
      top = root->nodes[top].next;
    }
  }
  assert(top == UINT32_MAX);
  exp_snapshot_release(fresh);
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
