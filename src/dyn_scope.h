#ifndef DYN_SCOPE_H
#define DYN_SCOPE_H
#include "dyn_syntax.h"

/* An immutable index for one tree/text revision. Names borrow source bytes;
   entries describe visibility intervals, not semantic declarations or types. */
typedef struct {
  const char *name;
  size_t length;
  uint32_t start, end, prefix_end;
} DynScopeBinding;
typedef struct {
  DynScopeBinding *items;
  size_t count, capacity;
  bool recovery;
} DynScopeIndex;

static inline int dyn_scope_name_compare(const DynScopeBinding *a,
                                          const DynScopeBinding *b) {
  size_t length = a->length < b->length ? a->length : b->length;
  int order = memcmp(a->name, b->name, length);
  return order ? order : (a->length > b->length) - (a->length < b->length);
}
static inline int dyn_scope_compare(const void *left, const void *right) {
  const DynScopeBinding *a = left, *b = right;
  int order = dyn_scope_name_compare(a, b);
  return order ? order : (a->start > b->start) - (a->start < b->start);
}
static inline bool dyn_scope_add(DynScopeIndex *index, const DynSource *source,
                                 TSNode name, uint32_t start, uint32_t end) {
  const char *text;
  size_t length;
  if (start >= end || !dyn_syntax_text(name, source, false, &text, &length))
    return true;
  if (index->count == index->capacity) {
    size_t capacity = index->capacity ? index->capacity * 2 : 32;
    if (capacity < index->capacity || capacity > SIZE_MAX / sizeof(*index->items))
      return false;
    DynScopeBinding *items = realloc(index->items, capacity * sizeof(*items));
    if (!items) return false;
    index->items = items; index->capacity = capacity;
  }
  index->items[index->count++] = (DynScopeBinding){text, length, start, end, end};
  return true;
}
static inline bool dyn_scope_collect(DynScopeIndex *index, TSNode scope,
                                     const DynSource *source) {
  const char *kind = ts_node_type(scope);
  bool block = !strcmp(kind, "block"), function = !strcmp(kind, "fn"),
       loop = !strcmp(kind, "for_"), arm = !strcmp(kind, "case_arm");
  if (!block && !function && !loop && !arm) return true;
  uint32_t start = ts_node_start_byte(scope), end = ts_node_end_byte(scope);
  if (loop || arm) {
    TSNode body = {0};
    for (uint32_t i = 0; i < ts_node_named_child_count(scope); ++i) {
      TSNode child = ts_node_named_child(scope, i);
      if (!strcmp(ts_node_type(child), "block")) { body = child; break; }
    }
    if (ts_node_is_null(body)) return true;
    start = ts_node_start_byte(body); end = ts_node_end_byte(body);
  }
  TSTreeCursor cursor = ts_tree_cursor_new(scope);
  bool ok = true;
  if (ts_tree_cursor_goto_first_child(&cursor)) do {
    TSNode node = ts_tree_cursor_current_node(&cursor);
    if (!ts_node_is_named(node) || ts_node_is_extra(node)) continue;
    const char *child_kind = ts_node_type(node);
    if (block) {
      uint32_t visible = ts_node_end_byte(node);
      while (!ts_node_is_null(node) &&
             (!strcmp(ts_node_type(node), "statement") ||
              !strcmp(ts_node_type(node), "const_variable")))
        node = dyn_syntax_child(node, 0);
      if (!ts_node_is_null(node) && !strcmp(ts_node_type(node), "variable"))
        ok = dyn_scope_add(index, source, dyn_syntax_child(node, 0), visible, end);
    } else if (function) {
      if (strcmp(child_kind, "fn_param") && strcmp(child_kind, "variadic_param")) continue;
      for (uint32_t i = 0; ok && i < ts_node_named_child_count(node); ++i) {
        TSNode name = ts_node_named_child(node, i);
        if (!strcmp(ts_node_type(name), "identifier"))
          ok = dyn_scope_add(index, source, name, start, end);
      }
    } else if (loop) {
      if (!strcmp(child_kind, "for_condition") && dyn_syntax_has_token(node, "in"))
        ok = dyn_scope_add(index, source, dyn_syntax_child(node, 0), start, end);
    } else {
      if (!strcmp(child_kind, "type_pattern")) node = dyn_syntax_last_child(node);
      if (!strcmp(ts_node_type(node), "identifier"))
        ok = dyn_scope_add(index, source, node, start, end);
    }
    if (!ok) break;
  } while (ts_tree_cursor_goto_next_sibling(&cursor));
  ts_tree_cursor_delete(&cursor);
  return ok;
}
static inline void dyn_scope_free(DynScopeIndex *index) {
  free(index->items); memset(index, 0, sizeof(*index));
}
static inline bool dyn_scope_build(DynScopeIndex *index, TSNode root,
                                    const DynSource *source) {
  memset(index, 0, sizeof(*index));
  /* Recovery trees may contain bindings outside ordinary grammar scopes. Keep
     their established ancestor-based behavior rather than guessing intervals. */
  if (ts_node_has_error(root)) { index->recovery = true; return true; }
  TSTreeCursor cursor = ts_tree_cursor_new(root);
  bool ok = true, done = false;
  while (!done) {
    TSNode node = ts_tree_cursor_current_node(&cursor);
    if (!dyn_scope_collect(index, node, source)) { ok = false; break; }
    /* Expressions cannot introduce lexical scopes in Dyn. In particular,
       do not walk every scalar in large constant tables to find bindings. */
    if (strcmp(ts_node_type(node), "expression") &&
        ts_tree_cursor_goto_first_child(&cursor)) continue;
    while (!ts_tree_cursor_goto_next_sibling(&cursor))
      if (!ts_tree_cursor_goto_parent(&cursor)) { done = true; break; }
  }
  ts_tree_cursor_delete(&cursor);
  if (!ok) { dyn_scope_free(index); return false; }
  if (index->count) qsort(index->items, index->count, sizeof(*index->items), dyn_scope_compare);
  for (size_t i = 1; i < index->count; ++i)
    if (!dyn_scope_name_compare(&index->items[i - 1], &index->items[i]) &&
        index->items[i - 1].prefix_end > index->items[i].prefix_end)
      index->items[i].prefix_end = index->items[i - 1].prefix_end;
  return true;
}
static inline bool dyn_scope_local(const DynScopeIndex *index, TSNode use,
                                    const DynSource *source, const char *name) {
  if (index->recovery) return dyn_syntax_local(use, source, name);
  DynScopeBinding key = {.name = name, .length = strlen(name)};
  uint32_t byte = ts_node_start_byte(use);
  size_t first = 0, end = index->count;
  while (first < end) {
    size_t middle = first + (end - first) / 2;
    int order = dyn_scope_name_compare(&index->items[middle], &key);
    if (order < 0 || (!order && index->items[middle].start <= byte)) first = middle + 1;
    else end = middle;
  }
  /* Within one name, prefix_end answers whether any earlier-starting interval
     still contains this use. No scan through same-name sibling scopes. */
  return first && !dyn_scope_name_compare(&index->items[first - 1], &key) &&
         byte < index->items[first - 1].prefix_end;
}
#endif
