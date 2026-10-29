#include "dyn.h"
#include "dyn_compact.h"
#include "syntax_depth.h"
#include <stdlib.h>
#include <string.h>

static bool compact_source_work(void *data, uint64_t units) {
  return dyn_work_step(data, units);
}

/* Cache only parsed source, never diagnostics or semantic state. Compare exact
   freshly-read bytes so missed watcher events cannot preserve stale syntax. */
struct DynSyntaxCacheEntry {
  char *path, *text;
  size_t length, charge;
  ExpSnapshot *snapshot;
  struct DynSyntaxCacheEntry *next;
};
static void syntax_cache_drop(DynSyntaxCache *cache, DynSyntaxCacheEntry **at) {
  DynSyntaxCacheEntry *entry = *at;
  *at = entry->next;
  cache->bytes -= entry->charge;
  --cache->count;
  free(entry->path); free(entry->text);
  exp_snapshot_release(entry->snapshot); free(entry);
}
void dyn_syntax_cache_clear(DynSyntaxCache *cache) {
  while (cache->entries) syntax_cache_drop(cache, &cache->entries);
}
/* Snapshots are immutable; a hit shares one with an extra reference. */
static void syntax_cache_store(DynSyntaxCache *cache, const DynSource *source,
                               ExpSnapshot *snapshot) {
  const size_t limit = cache->byte_limit ? cache->byte_limit : DYN_SYNTAX_CACHE_BYTES;
  const size_t entries = cache->entry_limit ? cache->entry_limit : DYN_SYNTAX_CACHE_ENTRIES;
  const ExpSnapshotTree *tree = exp_snapshot_tree(snapshot);
  size_t path_bytes = strlen(source->path) + 1;
  /* Copied text twice (entry and snapshot), nodes, errors and metadata. */
  size_t charge = 2 * (source->length + 1) + sizeof(DynSyntaxCacheEntry);
  if (source->length > limit || charge > limit || path_bytes > limit - charge) return;
  charge += path_bytes;
  if (tree->count > (limit - charge) / sizeof(ExpNode)) return;
  charge += (size_t)tree->count * sizeof(ExpNode) + tree->error_count * sizeof(ExpSyntaxError);
  if (charge > limit) return;
  DynSyntaxCacheEntry *entry = calloc(1, sizeof(*entry));
  if (!entry) return;
  entry->path = malloc(path_bytes);
  entry->text = malloc(source->length + 1);
  if (!entry->path || !entry->text || !exp_snapshot_retain(snapshot)) {
    free(entry->path); free(entry->text); free(entry); return;
  }
  memcpy(entry->path, source->path, path_bytes);
  memcpy(entry->text, source->text, source->length);
  entry->text[source->length] = 0;
  entry->length = source->length; entry->charge = charge;
  entry->snapshot = snapshot;
  while (cache->entries &&
         (cache->count >= entries || charge > limit - cache->bytes)) {
    DynSyntaxCacheEntry **last = &cache->entries;
    while ((*last)->next) last = &(*last)->next;
    syntax_cache_drop(cache, last);
  }
  entry->next = cache->entries; cache->entries = entry;
  ++cache->count; cache->bytes += charge;
}
static ExpSnapshot *source_parse(DynSource *source, ExpSnapshotError *error) {
  DynSyntaxCache *cache = source->path ? source->context.syntax_cache : NULL;
  if (cache) {
    for (DynSyntaxCacheEntry **at = &cache->entries; *at; at = &(*at)->next) {
      DynSyntaxCacheEntry *entry = *at;
      if (strcmp(entry->path, source->path)) continue;
      if (entry->length == source->length &&
          !memcmp(entry->text, source->text, source->length) &&
          exp_snapshot_retain(entry->snapshot)) {
        ++cache->hits;
        *at = entry->next; entry->next = cache->entries; cache->entries = entry;
        *error = (ExpSnapshotError){EXP_OK, NULL, 0, NULL};
        return entry->snapshot;
      }
      syntax_cache_drop(cache, at);
      break;
    }
    ++cache->misses;
  }
  /* Every parse recovers: batch commands report the errors, editors keep the
     partial tree. */
  ExpOptions options = {.work = compact_source_work, .data = &source->context, .recover = true};
  ExpSnapshot *snapshot = exp_snapshot_create(source->text, source->length, &options, error);
  if (snapshot && cache) syntax_cache_store(cache, source, snapshot);
  return snapshot;
}
/* A source may arrive with an adopted snapshot of its exact text; its facts
   are derived here either way. */
bool dyn_source_prepare(DynSource *source) {
  if (!source->compact) {
    source->syntax_too_deep = false;
    source->syntax_error = source->syntax_expected = NULL;
    ExpSnapshotError error;
    source->compact = source_parse(source, &error);
    if (!source->compact) {
      if (error.kind == EXP_LIMIT_ERROR && error.message && strstr(error.message, "nesting"))
        source->syntax_too_deep = true;
      return false;
    }
  }
  const ExpSnapshotTree *tree = dyn_compact_tree(source);
  if (!exp_depth_certified(tree, DYN_SYNTAX_DEPTH_LIMIT)) {
    exp_snapshot_release(source->compact); source->compact = NULL;
    source->syntax_too_deep = true;
    return false;
  }
  source->compact_root_start = tree->nodes[tree->root].start;
  source->compact_root_end = tree->nodes[tree->root].end;
  source->compact_validated = source->compact_only = !tree->error_count;
  if (tree->error_count) {
    source->syntax_error = tree->errors[0].message;
    source->syntax_expected = tree->errors[0].expected;
    source->syntax_error_offset = tree->errors[0].offset;
    /* Batch commands stop here; editors keep the partial tree. */
    if (source->context.strict_syntax) return false;
  }
  source->compact_reflection = false;
  for (uint32_t i = 0; i < tree->count; ++i) {
    if (!dyn_work_step(&source->context, 1)) {
      exp_snapshot_release(source->compact); source->compact = NULL;
      source->compact_reflection = false; return false;
    }
    if (tree->nodes[i].parent != UINT32_MAX && tree->nodes[i].kind == EXP_TYPEOF)
      source->compact_reflection = true;
  }
  return true;
}
bool dyn_source_reflection(const DynSource *source, bool *reflection) {
  *reflection = source->needs_reflection || source->compact_reflection;
  return true;
}
void dyn_source_discard_syntax(DynSource *source) {
  source->syntax_error = source->syntax_expected = NULL;
  source->compact_only = false;
  source->compact_validated = false;
  source->compact_root_start = source->compact_root_end = 0;
  exp_snapshot_release(source->compact);
  source->compact = NULL;
  source->compact_reflection = false;
}
