#define _POSIX_C_SOURCE 200809L
#include "analysis_cache.h"
#include <dirent.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

/* Bound retained projects. Oversized sources still analyze without caching. */
enum {
  ANALYSIS_CACHE_LIMIT = 4,
  ANALYSIS_CACHE_SOURCE_LIMIT = 8 * 1024 * 1024
};
struct DynAnalysisCacheEntry {
  char *root;
  char **directories;
  size_t directory_count;
  uint64_t *directory_stamps;
  char **files;
  size_t file_count;
  uint64_t fingerprint, used;
  DynAnalysisSnapshot *snapshot;
  struct DynAnalysisCacheEntry *next;
};
struct DynModuleSnapshotEntry {
  DynAnalysisSnapshot *snapshot;
  size_t bytes;
  struct DynModuleSnapshotEntry *next;
};
/* This cache stores payloads only; source maps and disk validation continue
   through project loading on every request. No mtime-only invalidation. */
struct DynInterfaceCacheEntry {
  char *key, *data;
  size_t key_length, length;
  uint64_t source_hash, interface_hash;
  struct DynInterfaceCacheEntry *next;
};
static void analysis_interface_drop(DynAnalysisCache *cache, DynInterfaceCacheEntry **at) {
  DynInterfaceCacheEntry *entry = *at;
  *at = entry->next;
  --cache->interface_count;
  cache->interface_bytes -= entry->key_length + entry->length;
  free(entry->key); free(entry->data); free(entry);
}
static char *analysis_interface_key(const DynSources *sources, size_t *length) {
  if (sources->count && !dyn_work_step(&sources->items[0].context, 0)) return NULL;
  const size_t limit = 8u * 1024u * 1024u;
  const char *target = sources->count ? dyn_context_target(&sources->items[0].context)->triple : "";
  size_t total = strlen(target) + 1;
  for (size_t i = 0; i < sources->count; ++i) {
    const DynSource *source = &sources->items[i];
    size_t path = strlen(source->path) + 1;
    if (path > limit - total) return NULL;
    total += path;
    if (sizeof(size_t) > limit - total) return NULL;
    total += sizeof(size_t);
    if (source->length > limit - total) return NULL;
    total += source->length;
  }
  char *key = malloc(total);
  if (!key) return NULL;
  size_t at = strlen(target) + 1;
  memcpy(key, target, at);
  for (size_t i = 0; i < sources->count; ++i) {
    const DynSource *source = &sources->items[i];
    size_t path = strlen(source->path) + 1;
    memcpy(key + at, source->path, path); at += path;
    memcpy(key + at, &source->length, sizeof(source->length)); at += sizeof(source->length);
    memcpy(key + at, source->text, source->length); at += source->length;
  }
  *length = total;
  return key;
}
bool dyn_analysis_interface_get(DynAnalysisCache *cache, const DynSources *sources,
                                DynInterface *out) {
  size_t length = 0;
  char *key = analysis_interface_key(sources, &length);
  if (key) for (DynInterfaceCacheEntry **at = &cache->interfaces; *at; at = &(*at)->next) {
    DynInterfaceCacheEntry *entry = *at;
    if (entry->key_length != length || memcmp(entry->key, key, length)) continue;
    char *data = malloc(entry->length + 1);
    if (!data) break;
    memcpy(data, entry->data, entry->length + 1);
    *out = (DynInterface){data, entry->length, entry->source_hash, entry->interface_hash};
    *at = entry->next; entry->next = cache->interfaces; cache->interfaces = entry;
    ++cache->interface_hits; free(key); return true;
  }
  free(key); ++cache->interface_misses; return false;
}
void dyn_analysis_interface_put(DynAnalysisCache *cache, const DynSources *sources,
                                const DynInterface *value) {
  if (sources->count && !dyn_work_step(&sources->items[0].context, 0)) return;
  const size_t limit = 8u * 1024u * 1024u;
  size_t length = 0;
  char *key = analysis_interface_key(sources, &length);
  if (!key) return;
  if (value->length > limit - length) { free(key); return; }
  DynInterfaceCacheEntry *entry = calloc(1, sizeof(*entry));
  char *data = malloc(value->length + 1);
  if (!entry || !data) { free(entry); free(data); free(key); return; }
  memcpy(data, value->data, value->length + 1);
  *entry = (DynInterfaceCacheEntry){key, data, length, value->length,
      value->source_hash, value->interface_hash, NULL};
  while (cache->interfaces && (cache->interface_count >= 64 ||
         length + value->length > limit - cache->interface_bytes)) {
    DynInterfaceCacheEntry **last = &cache->interfaces;
    while ((*last)->next) last = &(*last)->next;
    analysis_interface_drop(cache, last);
  }
  entry->next = cache->interfaces; cache->interfaces = entry;
  ++cache->interface_count; cache->interface_bytes += length + value->length;
}
static void analysis_module_drop(DynAnalysisCache *cache, DynModuleSnapshotEntry **at) {
  DynModuleSnapshotEntry *entry = *at;
  *at = entry->next;
  --cache->module_count; cache->module_bytes -= entry->bytes;
  dyn_analysis_snapshot_release(entry->snapshot); free(entry);
}
static bool analysis_module_equal(const DynSource *a, const DynSource *b) {
  if (strcmp(a->path, b->path) || a->length != b->length ||
      memcmp(a->text, b->text, a->length) || a->map_count != b->map_count) return false;
  for (size_t i = 0; i < a->map_count; ++i) {
    const DynSourceMap *x = &a->maps[i], *y = &b->maps[i];
    if (strcmp(x->path, y->path) || x->start != y->start || x->end != y->end ||
        x->original_length != y->original_length ||
        memcmp(x->original_text, y->original_text, x->original_length) ||
        x->span_count != y->span_count) return false;
    for (size_t j = 0; j < x->span_count; ++j) {
      DynSourceSpan u = x->spans[j], v = y->spans[j];
      if (u.generated_start != v.generated_start || u.generated_end != v.generated_end ||
          u.original_start != v.original_start || u.original_end != v.original_end) return false;
    }
  }
  return true;
}
DynAnalysisSnapshot *dyn_analysis_module_get(DynAnalysisCache *cache, const DynSource *source) {
  for (DynModuleSnapshotEntry **at = &cache->modules; *at; at = &(*at)->next) {
    DynModuleSnapshotEntry *entry = *at;
    if (analysis_module_equal(&entry->snapshot->source, source)) {
      *at = entry->next; entry->next = cache->modules; cache->modules = entry;
      ++cache->module_hits; ++entry->snapshot->references;
      return entry->snapshot;
    }
  }
  ++cache->module_misses; return NULL;
}
DynAnalysisSnapshot *dyn_analysis_module_put(DynAnalysisCache *cache, DynSource *source,
                                             DynAstProgram *ast, DynAnalysisResult result) {
  const size_t limit = 16u * 1024u * 1024u;
  if (!dyn_work_step(&source->context, 0)) return NULL;
  if (!result.checked || ast->allocation_failed || source->length > limit) return NULL;
  size_t bytes = source->length;
  for (size_t i = 0; i < source->map_count; ++i) {
    if (source->maps[i].original_length > limit - bytes) return NULL;
    bytes += source->maps[i].original_length;
  }
  DynModuleSnapshotEntry *entry = calloc(1, sizeof(*entry));
  DynAnalysisSnapshot *snapshot = calloc(1, sizeof(*snapshot));
  if (!entry || !snapshot) { free(entry); free(snapshot); return NULL; }
  for (DynModuleSnapshotEntry **at = &cache->modules; *at;) {
    if (!strcmp((*at)->snapshot->source.path, source->path)) analysis_module_drop(cache, at);
    else at = &(*at)->next;
  }
  while (cache->modules && (cache->module_count >= 64 || bytes > limit - cache->module_bytes)) {
    DynModuleSnapshotEntry **last = &cache->modules;
    while ((*last)->next) last = &(*last)->next;
    analysis_module_drop(cache, last);
  }
  snapshot->source = *source; snapshot->ast = *ast; snapshot->result = result;
  snapshot->references = 2;
  snapshot->source.context.diagnostic = NULL;
  snapshot->source.context.diagnostic_data = NULL;
  memset(source, 0, sizeof(*source)); memset(ast, 0, sizeof(*ast));
  entry->snapshot = snapshot; entry->bytes = bytes; entry->next = cache->modules;
  cache->modules = entry; ++cache->module_count; cache->module_bytes += bytes;
  return snapshot;
}
static uint64_t analysis_hash(uint64_t hash, const void *data, size_t length) {
  const unsigned char *bytes = data;
  for (size_t i = 0; i < length; ++i)
    hash = (hash ^ bytes[i]) * UINT64_C(1099511628211);
  return hash;
}
uint64_t dyn_analysis_text_hash(const char *text, size_t length) {
  return analysis_hash(UINT64_C(14695981039346656037), text, length);
}
static uint64_t analysis_stat(const char *path) {
  struct stat value = {0};
  uint64_t hash =
      analysis_hash(UINT64_C(14695981039346656037), path, strlen(path));
  if (stat(path, &value))
    return hash;
  uint64_t fields[] = {
      (uint64_t)value.st_dev,          (uint64_t)value.st_ino,
      (uint64_t)value.st_size,         (uint64_t)value.st_mtim.tv_sec,
      (uint64_t)value.st_mtim.tv_nsec, (uint64_t)value.st_ctim.tv_sec,
      (uint64_t)value.st_ctim.tv_nsec};
  /* Hash numeric values in a defined byte order, independently of host object
   * representation and the analyzer's external stat model. */
  for (size_t i = 0; i < sizeof(fields) / sizeof(fields[0]); ++i)
    for (unsigned shift = 0; shift < 64; shift += 8)
      hash = (hash ^ ((fields[i] >> shift) & UINT64_C(255))) *
             UINT64_C(1099511628211);
  return hash;
}
static bool analysis_directory_add(DynAnalysisCacheEntry *entry,
                                   const char *path, bool file) {
  size_t length = strlen(path);
  if (file) {
    const char *slash = strrchr(path, '/');
    if (!slash)
      return false;
    length = slash == path ? 1 : (size_t)(slash - path);
  }
  for (size_t i = 0; i < entry->directory_count; ++i)
    if (strlen(entry->directories[i]) == length &&
        !memcmp(path, entry->directories[i], length))
      return true;
  char *copy = strndup(path, length);
  if (!copy)
    return false;
  char **next =
      realloc(entry->directories, (entry->directory_count + 1) * sizeof(*next));
  if (!next) {
    free(copy);
    return false;
  }
  entry->directories = next;
  entry->directories[entry->directory_count++] = copy;
  return true;
}
static bool analysis_in_directory(const char *path, const char *directory) {
  size_t length = strlen(directory);
  return !strncmp(path, directory, length) && path[length] == '/' &&
         !strchr(path + length + 1, '/');
}
/* Keep a file inventory while directory membership is unchanged. File stats
   still run on every hit, so missed watcher events cannot preserve stale text.
 */
static bool analysis_fingerprint(DynAnalysisCacheEntry *entry,
                                 const DynAnalysisInput *inputs, size_t count,
                                 uint64_t *out, bool capture) {
  bool scan = capture;
  for (size_t i = 0; !scan && i < entry->directory_count; ++i)
    scan = analysis_stat(entry->directories[i]) != entry->directory_stamps[i];
  uint64_t hash = 0;
  if (!scan) {
    for (size_t i = 0; i < entry->file_count; ++i)
      hash ^= analysis_stat(entry->files[i]);
  } else {
    for (size_t i = 0; i < entry->directory_count; ++i) {
      const char *directory = entry->directories[i];
      /* Stamp before scanning: a concurrent membership change forces another
         scan. A mismatched fingerprint evicts this entry, including its
         inventory. */
      entry->directory_stamps[i] = analysis_stat(directory);
      DIR *dir = opendir(directory);
      if (!dir)
        return false;
      struct dirent *item;
      while ((item = readdir(dir))) {
        size_t length = strlen(item->d_name);
        if (strcmp(item->d_name, "dyn.project") &&
            (length < 4 || strcmp(item->d_name + length - 4, ".dyn")))
          continue;
        char *path = dyn_path_join(directory, item->d_name);
        if (!path) {
          closedir(dir);
          return false;
        }
        hash ^= analysis_stat(path);
        if (capture) {
          char **files =
              realloc(entry->files, (entry->file_count + 1) * sizeof(*files));
          if (!files) {
            free(path);
            closedir(dir);
            return false;
          }
          entry->files = files;
          entry->files[entry->file_count++] = path;
        } else
          free(path);
      }
      closedir(dir);
    }
  }
  for (size_t i = 0; i < entry->directory_count; ++i)
    for (size_t j = 0; j < count; ++j) {
      if (!analysis_in_directory(inputs[j].path, entry->directories[i]))
        continue;
      uint64_t h = analysis_hash(UINT64_C(14695981039346656037), inputs[j].path,
                                 strlen(inputs[j].path));
      uint64_t content =
          inputs[j].content_hash
              ? inputs[j].content_hash
              : dyn_analysis_text_hash(inputs[j].text, inputs[j].length);
      hash ^= analysis_hash(h, &content, sizeof(content));
    }
  *out = hash;
  return true;
}
void dyn_analysis_snapshot_release(DynAnalysisSnapshot *snapshot) {
  if (!snapshot || --snapshot->references)
    return;
  dyn_ast_program_free(&snapshot->ast);
  dyn_source_free(&snapshot->source);
  free(snapshot->diagnostics.items);
  free(snapshot);
}
static void analysis_entry_free(DynAnalysisCacheEntry *entry) {
  for (size_t i = 0; i < entry->directory_count; ++i)
    free(entry->directories[i]);
  free(entry->directories);
  free(entry->directory_stamps);
  for (size_t i = 0; i < entry->file_count; ++i)
    free(entry->files[i]);
  free(entry->files);
  free(entry->root);
  dyn_analysis_snapshot_release(entry->snapshot);
  free(entry);
}
void dyn_analysis_cache_clear(DynAnalysisCache *cache) {
  while (cache->interfaces) analysis_interface_drop(cache, &cache->interfaces);
  while (cache->modules) analysis_module_drop(cache, &cache->modules);
  while (cache->entries) {
    DynAnalysisCacheEntry *entry = cache->entries;
    cache->entries = entry->next;
    analysis_entry_free(entry);
  }
  cache->count = 0;
  dyn_syntax_cache_clear(&cache->syntax);
}
DynAnalysisSnapshot *dyn_analysis_cache_get(DynAnalysisCache *cache,
                                            const char *root,
                                            const DynAnalysisInput *inputs,
                                            size_t count) {
  for (DynAnalysisCacheEntry **at = &cache->entries; *at; at = &(*at)->next) {
    DynAnalysisCacheEntry *entry = *at;
    if (strcmp(root, entry->root))
      continue;
    uint64_t fingerprint;
    if (analysis_fingerprint(entry, inputs, count, &fingerprint, false) &&
        fingerprint == entry->fingerprint) {
      entry->used = ++cache->clock;
      ++cache->hits;
      ++entry->snapshot->references;
      return entry->snapshot;
    }
    *at = entry->next;
    analysis_entry_free(entry);
    --cache->count;
    break;
  }
  ++cache->misses;
  return NULL;
}
DynAnalysisSnapshot *dyn_analysis_cache_put(
    DynAnalysisCache *cache, const char *root, const DynSources *dependencies,
    const DynAnalysisInput *inputs, size_t count, DynSource *source,
    DynAstProgram *ast, DynAnalysisResult result,
    const DynAnalysisDiagnostics *diagnostics) {
  if (!dyn_work_step(&source->context, 0)) return NULL;
  if (!result.parsed || ast->allocation_failed ||
      source->length > ANALYSIS_CACHE_SOURCE_LIMIT)
    return NULL;
  DynAnalysisCacheEntry *entry = calloc(1, sizeof(*entry));
  if (!entry)
    return NULL;
  entry->root = strdup(root);
  entry->snapshot = calloc(1, sizeof(*entry->snapshot));
  if (entry->snapshot)
    entry->snapshot->references = 1;
  if (!entry->root || !entry->snapshot ||
      !analysis_directory_add(entry, root, false))
    goto fail;
  for (size_t i = 0; i < dependencies->count; ++i)
    if (!analysis_directory_add(entry, dependencies->items[i].path, true))
      goto fail;
  entry->directory_stamps =
      calloc(entry->directory_count, sizeof(*entry->directory_stamps));
  if (!entry->directory_stamps)
    goto fail;
  for (size_t i = 0; i < entry->directory_count; ++i)
    entry->directory_stamps[i] = analysis_stat(entry->directories[i]);
  if (!analysis_fingerprint(entry, inputs, count, &entry->fingerprint, true))
    goto fail;
  if (diagnostics) {
    DynAnalysisDiagnostics *copy = &entry->snapshot->diagnostics;
    copy->allocation_failed = diagnostics->allocation_failed;
    if (diagnostics->count) {
      copy->items = malloc(diagnostics->count * sizeof(*copy->items));
      if (!copy->items) goto fail;
      memcpy(copy->items, diagnostics->items, diagnostics->count * sizeof(*copy->items));
      copy->count = copy->capacity = diagnostics->count;
    }
  }
  /* Build the entire replacement before modifying the cache or taking
   * ownership. */
  for (DynAnalysisCacheEntry **at = &cache->entries; *at; at = &(*at)->next)
    if (!strcmp(root, (*at)->root)) {
      DynAnalysisCacheEntry *old = *at;
      *at = old->next;
      analysis_entry_free(old);
      --cache->count;
      break;
    }
  if (cache->count >= ANALYSIS_CACHE_LIMIT) {
    /* Count and list are one invariant; corruption must not masquerade as a
     * cache miss or silently discard the new snapshot. */
    if (cache->count != ANALYSIS_CACHE_LIMIT || !cache->entries)
      abort();
    DynAnalysisCacheEntry **oldest = &cache->entries;
    for (DynAnalysisCacheEntry **at = &cache->entries; *at; at = &(*at)->next)
      if ((*at)->used < (*oldest)->used)
        oldest = at;
    DynAnalysisCacheEntry *old = *oldest;
    *oldest = old->next;
    analysis_entry_free(old);
    --cache->count;
  }
  entry->snapshot->source = *source;
  entry->snapshot->ast = *ast;
  entry->snapshot->result = result;
  entry->snapshot->references = 2;
  /* Retained snapshots never keep a request's borrowed diagnostic collector. */
  entry->snapshot->source.context.diagnostic = NULL;
  entry->snapshot->source.context.diagnostic_data = NULL;
  memset(source, 0, sizeof(*source));
  memset(ast, 0, sizeof(*ast));
  entry->used = ++cache->clock;
  entry->next = cache->entries;
  cache->entries = entry;
  ++cache->count;
  return entry->snapshot;
fail:
  analysis_entry_free(entry);
  return NULL;
}
