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
  /* Batch commands rely on the handwritten parser alone. Other callers keep
     Tree-sitter for anything the compact tree cannot certify. */
  bool strict = source->context.strict_syntax;
  if (!source->syntax && !source->context.syntax_cache &&
      (strict || (!source->context.work && !memchr(source->text, '\0', source->length)))) {
    source->syntax_too_deep=false;
    if (!source->compact) {
      ExpSnapshotError error;
      ExpOptions options={.work=compact_source_work,.data=&source->context,.recover=strict};
      source->compact=exp_snapshot_create(source->text,source->length,source->context.work || strict ? &options : NULL,&error);
      if (!source->compact && (error.kind==EXP_ALLOCATION_ERROR || error.kind==EXP_CANCELLED)) return false;
      if (!source->compact && strict && error.kind==EXP_SYNTAX_ERROR) {
        source->syntax_error=error.message;
        source->syntax_expected=error.expected;
        source->syntax_error_offset=error.offset;
        return false;
      }
      if (!source->compact && strict && error.kind==EXP_LIMIT_ERROR && strstr(error.message, "nesting")) {
        source->syntax_too_deep=true;
        return false;
      }
    }
    const ExpSnapshotTree *tree=dyn_compact_tree(source);
    if (tree && tree->error_count) {
      /* Recovered errors: the partial tree is kept only for reporting. */
      source->syntax_error=tree->errors[0].message;
      source->syntax_expected=tree->errors[0].expected;
      source->syntax_error_offset=tree->errors[0].offset;
      return false;
    }
    bool certified=exp_depth_certified(tree,DYN_SYNTAX_DEPTH_LIMIT);
    if (tree && strict && !certified) {
      exp_snapshot_release(source->compact); source->compact=NULL;
      source->syntax_too_deep=true;
      return false;
    }
    if (certified && (strict || compact_first_strings_safe(source,tree))) {
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
#ifdef DYN_EXPERIMENT_COMPACT_FIRST
static size_t syntax_token_end(const char *text, size_t length, size_t at) {
  unsigned char c = (unsigned char)text[at];
  size_t end = at + 1;
  if (c == '_' || (c >= '0' && c <= '9') || ((c | 32) >= 'a' && (c | 32) <= 'z')) {
    while (end < length) {
      c = (unsigned char)text[end];
      if (c != '_' && !(c >= '0' && c <= '9') && !((c | 32) >= 'a' && (c | 32) <= 'z')) break;
      ++end;
    }
  } else if (c >= 0x80)
    while (end < length && ((unsigned char)text[end] & 0xc0) == 0x80) ++end;
  else if (strchr(":=<>!&|+-*/%^.~", c))
    while (end < length && end - at < 3 && text[end] && strchr(":=<>!&|+-*/%^.~", text[end])) ++end;
  return end - at > 32 ? at + 32 : end;
}
#endif
#ifdef DYN_EXPERIMENT_COMPACT_FIRST
static void report_syntax_error(const DynSource *source, uint32_t offset,
                                const char *error, const char *expected) {
  size_t start = offset;
  if (start > source->length) start = source->length;
  size_t end = start;
  char found[48];
  if (start == source->length) snprintf(found, sizeof(found), "end of file");
  else {
    end = syntax_token_end(source->text, source->length, start);
    unsigned char c = (unsigned char)source->text[start];
    if (c == '\n') snprintf(found, sizeof(found), "end of line");
    else if (c < 0x20 || c == 0x7f) snprintf(found, sizeof(found), "U+%04X", c);
    else if (c >= 0x80) {
      /* Name the code point: it may be invisible or a line separator. */
      unsigned value = c >= 0xf0 ? c & 7 : c >= 0xe0 ? c & 15 : c & 31;
      for (size_t i = start + 1; i < end; ++i)
        value = value << 6 | ((unsigned char)source->text[i] & 63);
      snprintf(found, sizeof(found), "U+%04X", value);
    } else snprintf(found, sizeof(found), "'%.*s'", (int)(end - start), source->text + start);
  }
  char message[160];
  if (expected)
    snprintf(message, sizeof(message), "expected '%s', found %s", expected, found);
  else if (!strcmp(error, "unexpected token"))
    snprintf(message, sizeof(message), "unexpected %s", found);
  else if (!strcmp(error, "unexpected character"))
    snprintf(message, sizeof(message), "unexpected character %s", found);
  else if (!strncmp(error, "expected ", 9))
    snprintf(message, sizeof(message), "%s, found %s", error, found);
  else
    snprintf(message, sizeof(message), "%s", error);
  dyn_diagnostic_source("error", source, start, end, message);
}
#endif
bool dyn_source_report_syntax(const DynSource *source) {
#ifdef DYN_EXPERIMENT_COMPACT_FIRST
  if (!source->syntax_error) return false;
  const ExpSnapshotTree *tree = dyn_compact_tree(source);
  if (!tree || !tree->error_count) {
    report_syntax_error(source, source->syntax_error_offset, source->syntax_error,
                        source->syntax_expected);
    return true;
  }
  /* Later errors can follow from recovery; report a bounded prefix. */
  for (uint32_t i = 0; i < tree->error_count && i < DYN_SYNTAX_ERROR_LIMIT; ++i)
    report_syntax_error(source, tree->errors[i].offset, tree->errors[i].message,
                        tree->errors[i].expected);
  return true;
#else
  (void)source;
  return false;
#endif
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
  source->syntax_error = source->syntax_expected = NULL;
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
