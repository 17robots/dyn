#include "dyn.h"
#include "dyn_syntax.h"

/* Cache only parsed source, never diagnostics or semantic state. Compare exact
   freshly-read bytes so missed watcher events cannot preserve stale syntax. */
struct DynSyntaxCacheEntry {
  char *path, *text;
  size_t length;
  TSTree *tree;
  struct DynSyntaxCacheEntry *next;
};
static void syntax_cache_drop(DynSyntaxCache *cache, DynSyntaxCacheEntry **at) {
  DynSyntaxCacheEntry *entry = *at;
  *at = entry->next;
  cache->bytes -= entry->length;
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
  DynSyntaxCacheEntry *entry = calloc(1, sizeof(*entry));
  if (!entry) return tree;
  entry->path = malloc(strlen(source->path) + 1);
  entry->text = malloc(source->length + 1);
  if (!entry->path || !entry->text) {
    free(entry->path); free(entry->text); free(entry); return tree;
  }
  strcpy(entry->path, source->path);
  memcpy(entry->text, source->text, source->length + 1);
  entry->length = source->length; entry->tree = ts_tree_copy(tree);
  while (cache->entries &&
         (cache->count >= 64 || source->length > limit - cache->bytes)) {
    DynSyntaxCacheEntry **last = &cache->entries;
    while ((*last)->next) last = &(*last)->next;
    syntax_cache_drop(cache, last);
  }
  entry->next = cache->entries; cache->entries = entry;
  ++cache->count; cache->bytes += source->length;
  return tree;
}
bool dyn_source_prepare(DynSource *source) {
  if (!source->syntax)
    source->syntax = source->context.syntax_cache && source->path
                         ? source_cached_tree(source)
                         : dyn_syntax_reparse_context(source->text, source->length, NULL, &source->syntax_too_deep, &source->context);
  return source->syntax != NULL;
}
TSTree *dyn_source_tree(const DynSource *source) {
  return source->syntax ? ts_tree_copy(source->syntax)
                        : dyn_syntax_reparse_context(source->text, source->length, NULL, NULL, &source->context);
}
void dyn_source_discard_syntax(DynSource *source) {
  if (source->syntax)
    ts_tree_delete(source->syntax);
  source->syntax = NULL;
}
