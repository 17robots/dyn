#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fault-alloc.h"
#include "../src/source_tree.c"

static void same_tree(const ExpSnapshotTree *a, const ExpSnapshotTree *b) {
  assert(a->count == b->count && a->root == b->root && a->error_count == b->error_count);
  assert(!memcmp(a->nodes, b->nodes, a->count * sizeof(*a->nodes)));
}
int main(void) {
  /* Every allocation failure either fails preparation cleanly or succeeds
     without the optional cache entry. */
  size_t total = 0;
  for (size_t failure = 0; !failure || failure <= total; ++failure) {
    DynSyntaxCache cache = {0};
    DynSource source = {.path = "main.dyn", .text = "fn aa() {}", .length = 10,
                        .context = {.syntax_cache = &cache}};
    calls = failed = 0; fail_at = failure;
    bool prepared = dyn_source_prepare(&source);
    if (!failure) { assert(prepared); total = calls; } else assert(failed);
    fail_at = 0;
    assert(prepared ? source.compact && !dyn_compact_tree(&source)->error_count : !source.compact);
    dyn_source_discard_syntax(&source);
    dyn_syntax_cache_clear(&cache);
  }
  /* Small limits keep the eviction checks fast. */
  DynSyntaxCache cache = {.entry_limit = 64, .byte_limit = 8u * 1024u * 1024u};
  DynSource source = {.path = "main.dyn", .text = "fn aa() {}", .length = 10,
                      .context = {.syntax_cache = &cache}};
  assert(dyn_source_prepare(&source));
  ExpSnapshot *held = source.compact; source.compact = NULL;
  /* A hit shares the immutable snapshot. */
  assert(dyn_source_prepare(&source) && cache.hits == 1 && cache.misses == 1);
  assert(source.compact == held);
  dyn_source_discard_syntax(&source);
  source.text = "fn a() { }"; source.length = 10;
  assert(dyn_source_prepare(&source) && cache.misses == 2 && source.compact != held);
  ExpSnapshot *fresh = exp_snapshot_create(source.text, source.length, NULL, NULL);
  same_tree(dyn_compact_tree(&source), exp_snapshot_tree(fresh));
  exp_snapshot_release(fresh); dyn_source_discard_syntax(&source);
  /* Editor revisions keep their recovered errors. */
  source.text = "fn a( {"; source.length = 7;
  assert(dyn_source_prepare(&source) && dyn_compact_tree(&source)->error_count == 1);
  dyn_source_discard_syntax(&source);
  for (unsigned i = 0; i < 100; ++i) {
    char path[64]; snprintf(path, sizeof(path), "file%u.dyn", i);
    source.path = path;
    assert(dyn_source_prepare(&source)); dyn_source_discard_syntax(&source);
    assert(cache.count <= 64 && cache.bytes <= 8u * 1024u * 1024u);
  }
  size_t large_length = 3u * 1024u * 1024u;
  char *large = malloc(large_length + 1); assert(large);
  memset(large, ' ', large_length); large[large_length] = 0;
  source.text = large; source.length = large_length;
  source.path = "large-one.dyn";
  assert(dyn_source_prepare(&source)); dyn_source_discard_syntax(&source);
  source.path = "large-two.dyn";
  assert(dyn_source_prepare(&source)); dyn_source_discard_syntax(&source);
  assert(cache.count == 1 && cache.bytes > large_length);
  free(large);
  dyn_syntax_cache_clear(&cache);
  /* Dense trees must consume the budget even when their source is small. */
  size_t statements = 8000, dense_length = 14 + statements * 6;
  char *dense = malloc(dense_length + 1); assert(dense);
  memcpy(dense, "fn main() {\n", 12);
  for (size_t i = 0; i < statements; ++i)
    memcpy(dense + 12 + i * 6, "_ = 0\n", 6);
  memcpy(dense + 12 + statements * 6, "}\n", 3);
  source.text = dense; source.length = dense_length;
  for (unsigned i = 0; i < 64; ++i) {
    char path[64]; snprintf(path, sizeof(path), "dense%u.dyn", i);
    source.path = path;
    assert(dyn_source_prepare(&source)); dyn_source_discard_syntax(&source);
    assert(cache.bytes <= 8u * 1024u * 1024u);
  }
  assert(cache.count > 0 && cache.count < 16);
  assert(cache.bytes > cache.count * dense_length * 10);
  free(dense);
  dyn_syntax_cache_clear(&cache);
  assert(cache.count == 0 && cache.bytes == 0);
  assert(!exp_snapshot_tree(held)->error_count); exp_snapshot_release(held);
  puts("PASS immutable syntax cache, recovered editor revisions, eviction and allocation failure");
}
