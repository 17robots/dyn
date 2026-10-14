#ifndef DYN_IMPORTS_H
#define DYN_IMPORTS_H
#include "dyn_syntax.h"
#include "dyn_compact.h"

/* Import consumers need text and diagnostic spans, not parser-owned nodes.
   The reader borrows the source revision until close. Recovery remains on the
   established Tree-sitter path; valid prepared compact snapshots need no tree. */
typedef struct {
  const char *path, *alias;
  size_t path_length, alias_length;
  uint32_t start, end;
  bool path_node, alias_node;
} DynImportView;
typedef struct {
  const DynSource *source;
  TSTree *tree;
  TSTreeCursor cursor;
  TSNode use;
  uint32_t child;
  bool started, done, failed;
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
  const ExpSnapshotTree *compact;
  uint32_t declaration, import;
#endif
} DynImports;
static inline bool dyn_imports_open(DynImports *reader, const DynSource *source) {
  memset(reader, 0, sizeof(*reader)); reader->source = source;
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
  reader->compact = dyn_compact_tree(source);
  if (reader->compact) {
    reader->declaration = reader->compact->nodes[reader->compact->root].first;
    reader->import = UINT32_MAX;
    return true;
  }
#endif
  reader->tree = dyn_source_tree(source);
  if (!reader->tree) return false;
  reader->cursor = ts_tree_cursor_new(ts_tree_root_node(reader->tree));
  return true;
}
static inline void dyn_imports_close(DynImports *reader) {
  if (reader->tree) {
    ts_tree_cursor_delete(&reader->cursor);
    ts_tree_delete(reader->tree);
  }
}
static inline bool dyn_imports_next(DynImports *reader, DynImportView *out) {
  memset(out, 0, sizeof(*out));
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
  if (reader->compact) {
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
#endif
  while (!reader->done) {
    while (!ts_node_is_null(reader->use) && reader->child < ts_node_named_child_count(reader->use)) {
      TSNode node = ts_node_named_child(reader->use, reader->child++);
      if (strcmp(ts_node_type(node), "import")) continue;
      TSNode path = ts_node_child_by_field_name(node, "path", 4);
      TSNode alias = ts_node_child_by_field_name(node, "alias", 5);
      out->start = ts_node_start_byte(node); out->end = ts_node_end_byte(node);
      out->path_node = !ts_node_is_null(path); out->alias_node = !ts_node_is_null(alias);
      dyn_syntax_text(path, reader->source, true, &out->path, &out->path_length);
      dyn_syntax_text(alias, reader->source, false, &out->alias, &out->alias_length);
      return true;
    }
    bool next = reader->started ? ts_tree_cursor_goto_next_sibling(&reader->cursor)
                                : ts_tree_cursor_goto_first_child(&reader->cursor);
    reader->started = true;
    if (!next) { reader->done = true; break; }
    TSNode node = dyn_syntax_declaration_node(ts_tree_cursor_current_node(&reader->cursor));
    reader->use = !strcmp(ts_node_type(node), "use") ? node : (TSNode){0};
    reader->child = 0;
  }
  return false;
}
static inline char *dyn_import_copy(const char *text, size_t length) {
  if (!text) return NULL;
  char *copy = malloc(length + 1);
  if (copy) { memcpy(copy, text, length); copy[length] = 0; }
  return copy;
}
#endif
