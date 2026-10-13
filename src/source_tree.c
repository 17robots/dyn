#include "dyn.h"
#include "dyn_syntax.h"
#include "dyn_compact.h"
#ifdef DYN_EXPERIMENT_COMPACT_FIRST
#include "../tools/parser-experiment/depth.h"
/* The pinned lexer can choose a comment extra at a string-fragment
   boundary (including after an escape). Keep those literals on the TS path. */
static bool compact_first_strings_safe(const DynSource *source,const ExpSnapshotTree *tree) {
  if (!tree) return false;
  for (uint32_t i=0;i<tree->count;++i) {
    const ExpNode *node=&tree->nodes[i];
    if (node->kind!=EXP_STRING || node->parent==UINT32_MAX) continue;
    for (uint32_t at=node->start;at+1<node->end;++at)
      if (source->text[at]=='/' && (source->text[at+1]=='/' || source->text[at+1]=='*')) return false;
  }
  return true;
}
#endif
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
static bool compact_source_work(void *data, uint64_t units) {
  return dyn_work_step(data, units);
}
#endif

/* Cache only parsed source, never diagnostics or semantic state. Compare exact
   freshly-read bytes so missed watcher events cannot preserve stale syntax. */
struct DynSyntaxCacheEntry {
  char *path, *text;
  size_t length, charge;
  TSTree *tree;
  struct DynSyntaxCacheEntry *next;
};
static void syntax_cache_drop(DynSyntaxCache *cache, DynSyntaxCacheEntry **at) {
  DynSyntaxCacheEntry *entry = *at;
  *at = entry->next;
  cache->bytes -= entry->charge;
  --cache->count;
  free(entry->path); free(entry->text);
  ts_tree_delete(entry->tree); free(entry);
}
void dyn_syntax_cache_clear(DynSyntaxCache *cache) {
  while (cache->entries) syntax_cache_drop(cache, &cache->entries);
}
static TSTree *source_cached_tree(DynSource *source) {
  DynSyntaxCache *cache = source->context.syntax_cache;
  for (DynSyntaxCacheEntry **at = &cache->entries; *at; at = &(*at)->next) {
    DynSyntaxCacheEntry *entry = *at;
    if (strcmp(entry->path, source->path)) continue;
    if (entry->length == source->length &&
        !memcmp(entry->text, source->text, source->length)) {
      ++cache->hits;
      *at = entry->next; entry->next = cache->entries; cache->entries = entry;
      return ts_tree_copy(entry->tree);
    }
    syntax_cache_drop(cache, at);
    break;
  }
  ++cache->misses;
  TSTree *tree = dyn_syntax_reparse_context(source->text, source->length, NULL, &source->syntax_too_deep, &source->context);
  const size_t limit = 8u * 1024u * 1024u;
  if (!tree || source->length > limit) return tree;
  /* Tree-sitter has no retained-size API. Budget a conservative estimate per
     visible node as well as the copied source and cache metadata. Source bytes
     alone severely undercount dense syntax trees. This is an eviction estimate,
     not an exact bound on the parser's allocations. */
  size_t nodes = ts_node_descendant_count(ts_tree_root_node(tree));
  size_t path_bytes = strlen(source->path) + 1;
  size_t charge = source->length + 1 + sizeof(DynSyntaxCacheEntry);
  if (charge > limit || path_bytes > limit - charge) return tree;
  charge += path_bytes;
  if (nodes > (limit - charge) / 128u) return tree;
  charge += nodes * 128u;
  DynSyntaxCacheEntry *entry = calloc(1, sizeof(*entry));
  if (!entry) return tree;
  entry->path = malloc(strlen(source->path) + 1);
  entry->text = malloc(source->length + 1);
  if (!entry->path || !entry->text) {
    free(entry->path); free(entry->text); free(entry); return tree;
  }
  strcpy(entry->path, source->path);
  memcpy(entry->text, source->text, source->length + 1);
  entry->length = source->length; entry->charge = charge;
  entry->tree = ts_tree_copy(tree);
  while (cache->entries &&
         (cache->count >= 64 || charge > limit - cache->bytes)) {
    DynSyntaxCacheEntry **last = &cache->entries;
    while ((*last)->next) last = &(*last)->next;
    syntax_cache_drop(cache, last);
  }
  entry->next = cache->entries; cache->entries = entry;
  ++cache->count; cache->bytes += charge;
  return tree;
}
bool dyn_source_prepare(DynSource *source) {
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
  bool inspect_compact = source->compact == NULL;
#endif
#ifdef DYN_EXPERIMENT_COMPACT_FIRST
  if (!source->syntax && !source->context.work && !source->context.syntax_cache &&
      !memchr(source->text, '\0', source->length)) {
    source->syntax_too_deep=false;
    if (!source->compact) {
      ExpSnapshotError error;
      source->compact=exp_snapshot_create(source->text,source->length,NULL,&error);
      if (!source->compact && (error.kind==EXP_ALLOCATION_ERROR || error.kind==EXP_CANCELLED)) return false;
    }
    const ExpSnapshotTree *tree=dyn_compact_tree(source);
    if (exp_depth_certified(tree,DYN_SYNTAX_DEPTH_LIMIT) && compact_first_strings_safe(source,tree)) {
      source->compact_validated=true;
      source->compact_root_start=tree->nodes[tree->root].start;
      source->compact_root_end=tree->nodes[tree->root].end;
    }
  }
  if (!source->compact_validated)
#endif
  if (!source->syntax)
    source->syntax = source->context.syntax_cache && source->path
                         ? source_cached_tree(source)
                         : dyn_syntax_reparse_context(source->text, source->length, NULL, &source->syntax_too_deep, &source->context);
#ifdef DYN_EXPERIMENT_COMPACT_FIRST
  /* A speculative snapshot is not published after legacy validation rejects it. */
  if (!source->compact_validated && source->compact &&
      (!source->syntax || ts_node_has_error(ts_tree_root_node(source->syntax)))) {
    exp_snapshot_release(source->compact); source->compact=NULL;
    source->compact_reflection=false;
  }
#endif
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
  if (source->syntax && !source->compact &&
      !ts_node_has_error(ts_tree_root_node(source->syntax))) {
    ExpSnapshotError error;
    ExpOptions options = {.work = compact_source_work, .data = &source->context};
    source->compact = exp_snapshot_create(source->text, source->length, &options, &error);
    if (!source->compact && (error.kind == EXP_ALLOCATION_ERROR || error.kind == EXP_CANCELLED))
      return false;
  }
  const ExpSnapshotTree *tree = dyn_compact_tree(source);
  if (inspect_compact && tree) for (uint32_t i = 0; i < tree->count; ++i) {
    if (!dyn_work_step(&source->context, 1)) {
      exp_snapshot_release(source->compact); source->compact = NULL;
      source->compact_reflection = false; return false;
    }
    if (tree->nodes[i].parent != UINT32_MAX && tree->nodes[i].kind == EXP_TYPEOF)
      source->compact_reflection = true;
  }
#endif
#ifdef DYN_EXPERIMENT_COMPACT_FIRST
  if (source->compact_validated) return true;
#endif
  return source->syntax != NULL;
}
TSTree *dyn_source_tree(const DynSource *source) {
  return source->syntax ? ts_tree_copy(source->syntax)
                        : dyn_syntax_reparse_context(source->text, source->length, NULL, NULL, &source->context);
}
bool dyn_source_reflection(const DynSource *source, bool *reflection) {
  if (source->needs_reflection) { *reflection = true; return true; }
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
  if (source->compact) { *reflection = source->compact_reflection; return true; }
#endif
  *reflection = false;
  if (!strstr(source->text, "#typeof")) return true;
  TSTree *tree = dyn_source_tree(source);
  if (!tree) return false;
  *reflection = dyn_syntax_has_reflection(ts_tree_root_node(tree));
  ts_tree_delete(tree);
  return true;
}
void dyn_source_discard_syntax(DynSource *source) {
#ifdef DYN_EXPERIMENT_COMPACT_AST
  source->compact_only = false;
#ifdef DYN_EXPERIMENT_COMPACT_FIRST
  source->compact_validated = false;
#endif
  source->compact_root_start = source->compact_root_end = 0;
#endif
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
  exp_snapshot_release(source->compact);
  source->compact = NULL;
  source->compact_reflection = false;
#endif
  if (source->syntax)
    ts_tree_delete(source->syntax);
  source->syntax = NULL;
}

#ifdef DYN_EXPERIMENT_COMPACT_AST
void dyn_source_release_batch_trees(DynSource *source) {
  if (!source || source->context.syntax_cache) return;
  if (source->syntax) ts_tree_delete(source->syntax);
  source->syntax = NULL;
  for (size_t i = 0; i < source->syntax_part_count; ++i) {
    if (source->syntax_parts[i]) ts_tree_delete(source->syntax_parts[i]);
    source->syntax_parts[i] = NULL;
  }
  /* The count also owns compact_parts; keep it until normal source cleanup. */
}
#endif
