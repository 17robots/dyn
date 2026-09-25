#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fault-alloc.h"
#include "../src/source_tree.c"

static void same_tree(TSNode a, TSNode b) {
  assert(!strcmp(ts_node_type(a), ts_node_type(b)));
  assert(ts_node_start_byte(a) == ts_node_start_byte(b));
  assert(ts_node_end_byte(a) == ts_node_end_byte(b));
  assert(ts_node_is_missing(a) == ts_node_is_missing(b));
  TSPoint x = ts_node_start_point(a), y = ts_node_start_point(b);
  assert(x.row == y.row && x.column == y.column);
  x = ts_node_end_point(a); y = ts_node_end_point(b);
  assert(x.row == y.row && x.column == y.column);
  assert(ts_node_child_count(a) == ts_node_child_count(b));
  for (uint32_t i = 0; i < ts_node_child_count(a); ++i)
    same_tree(ts_node_child(a, i), ts_node_child(b, i));
}
int main(void) {
  const char *edits[] = {
      "fn main() {}", "fn main() { /* 😀 */ _ = 1 }",
      "fn main() { /* 😁 */ _ = 12 }", "use \"std/", "use \"std/mem\"\nfn main() {}",
      "fn main() {\nconst x := [1, /* é */ 2]\n_ = x\n}",
      "fn main() {\nconst x := [1, /* ê */ 2]\n_ = x\n}",
      "fn main() {\nconst x := [1, /* ê */ 2]\n_ = x\n}",
      "fn main() {\nconst x := [1, /* ê */ 2]\n_ = x\n", "", "// é", "// e"};
  TSTree *tree = dyn_syntax_parse(edits[0], strlen(edits[0])); assert(tree);
  const char *before = edits[0];
  for (unsigned repeat = 0; repeat < 10; ++repeat)
    for (size_t i = 0; i < sizeof(edits) / sizeof(edits[0]); ++i) {
      dyn_syntax_edit_text(tree, before, edits[i]);
      TSTree *updated = dyn_syntax_reparse(edits[i], strlen(edits[i]), tree);
      TSTree *fresh = dyn_syntax_parse(edits[i], strlen(edits[i]));
      assert(updated && fresh);
      same_tree(ts_tree_root_node(updated), ts_tree_root_node(fresh));
      ts_tree_delete(tree); ts_tree_delete(fresh); tree = updated; before = edits[i];
    }
  ts_tree_delete(tree);
  size_t total = 0;
  for (size_t failure = 0; !failure || failure <= total; ++failure) {
    DynSyntaxCache cache = {0};
    DynSource source = {.path = "main.dyn", .text = "fn aa() {}", .length = 10,
                        .context = {.syntax_cache = &cache}};
    calls = failed = 0; fail_at = failure;
    assert(dyn_source_prepare(&source)); /* Optional cache allocation may fail. */
    if (!failure) total = calls; else assert(failed);
    fail_at = 0;
    dyn_syntax_cache_clear(&cache);
    assert(!ts_node_has_error(ts_tree_root_node(source.syntax)));
    dyn_source_discard_syntax(&source);
  }
  DynSyntaxCache cache = {0};
  DynSource source = {.path = "main.dyn", .text = "fn aa() {}", .length = 10,
                      .context = {.syntax_cache = &cache}};
  assert(dyn_source_prepare(&source));
  TSTree *held = source.syntax; source.syntax = NULL;
  assert(dyn_source_prepare(&source) && cache.hits == 1 && cache.misses == 1);
  /* Editing a returned copy must not mutate the cache's immutable tree. */
  dyn_syntax_edit_text(source.syntax, source.text, "fn a() { }");
  dyn_source_discard_syntax(&source);
  assert(dyn_source_prepare(&source) && cache.hits == 2);
  same_tree(ts_tree_root_node(source.syntax), ts_tree_root_node(held));
  dyn_source_discard_syntax(&source);
  source.text = "fn a() { }";
  assert(dyn_source_prepare(&source) && cache.misses == 2);
  TSTree *fresh = dyn_syntax_parse(source.text, source.length);
  same_tree(ts_tree_root_node(source.syntax), ts_tree_root_node(fresh));
  ts_tree_delete(fresh); dyn_source_discard_syntax(&source);
  for (unsigned i = 0; i < 100; ++i) {
    char path[64]; snprintf(path, sizeof(path), "file%u.dyn", i);
    source.path = path;
    assert(dyn_source_prepare(&source)); dyn_source_discard_syntax(&source);
    assert(cache.count <= 64 && cache.bytes <= 8u * 1024u * 1024u);
  }
  size_t large_length = 5u * 1024u * 1024u;
  char *large = malloc(large_length + 1); assert(large);
  memset(large, ' ', large_length); large[large_length] = 0;
  source.text = large; source.length = large_length;
  source.path = "large-one.dyn";
  assert(dyn_source_prepare(&source)); dyn_source_discard_syntax(&source);
  source.path = "large-two.dyn";
  assert(dyn_source_prepare(&source)); dyn_source_discard_syntax(&source);
  assert(cache.count == 1 && cache.bytes == large_length);
  free(large);
  dyn_syntax_cache_clear(&cache);
  assert(cache.count == 0 && cache.bytes == 0);
  assert(!ts_node_has_error(ts_tree_root_node(held))); ts_tree_delete(held);
  puts("PASS incremental/fresh trees, UTF-8 edits, immutable syntax cache, eviction and allocation failure");
}
