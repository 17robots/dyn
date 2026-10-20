#ifndef DYN_IMPORTS_H
#define DYN_IMPORTS_H
#include "dyn_compact.h"
#include <stdlib.h>
#include <string.h>

/* Import consumers need text and diagnostic spans, not parser-owned nodes.
   The reader borrows the prepared source revision until close. */
typedef struct {
  const char *path, *alias;
  size_t path_length, alias_length;
  uint32_t start, end;
  bool path_node, alias_node;
} DynImportView;
typedef struct {
  const DynSource *source;
  bool failed;
  const ExpSnapshotTree *compact;
  uint32_t declaration, import;
} DynImports;
static inline bool dyn_imports_open(DynImports *reader, const DynSource *source) {
  memset(reader, 0, sizeof(*reader)); reader->source = source;
  reader->compact = dyn_compact_tree(source);
  if (!reader->compact) return false;
  reader->declaration = reader->compact->nodes[reader->compact->root].first;
  reader->import = UINT32_MAX;
  return true;
}
static inline void dyn_imports_close(DynImports *reader) {
  (void)reader;
}
static inline bool dyn_imports_next(DynImports *reader, DynImportView *out) {
  memset(out, 0, sizeof(*out));
  {
    const ExpNode *nodes = reader->compact->nodes;
    while (reader->import == UINT32_MAX && reader->declaration != UINT32_MAX) {
      if (!dyn_work_step(&reader->source->context, 1)) { reader->failed = true; return false; }
      uint32_t wrapper = reader->declaration;
      reader->declaration = nodes[wrapper].next;
      if (nodes[wrapper].kind != SRC_DECLARATION) continue;
      uint32_t use = nodes[wrapper].first;
      if (use != UINT32_MAX && nodes[use].kind == SRC_USE) reader->import = nodes[use].first;
    }
    if (reader->import == UINT32_MAX) return false;
    if (!dyn_work_step(&reader->source->context, 1)) { reader->failed = true; return false; }
    uint32_t id = reader->import;
    reader->import = nodes[id].next;
    uint32_t path = dyn_compact_field(reader->compact, id, EXP_ROLE_PATH);
    uint32_t alias = dyn_compact_field(reader->compact, id, EXP_ROLE_ALIAS);
    out->start = nodes[id].start; out->end = nodes[id].end;
    out->path_node = path != UINT32_MAX; out->alias_node = alias != UINT32_MAX;
    if (out->path_node) {
      out->path = reader->source->text + nodes[path].start + 1;
      out->path_length = nodes[path].end - nodes[path].start - 2;
    }
    if (out->alias_node) {
      out->alias = reader->source->text + nodes[alias].start;
      out->alias_length = nodes[alias].end - nodes[alias].start;
    }
    return true;
  }
}
static inline char *dyn_import_copy(const char *text, size_t length) {
  if (!text) return NULL;
  char *copy = malloc(length + 1);
  if (copy) { memcpy(copy, text, length); copy[length] = 0; }
  return copy;
}
#endif
