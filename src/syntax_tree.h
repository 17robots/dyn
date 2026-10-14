#ifndef DYN_SYNTAX_TREE_H
#define DYN_SYNTAX_TREE_H
/* Read-only navigation of a parsed snapshot for editor features. A node is a
   tree plus an index; it borrows the snapshot and is null past any edge. */
#include "snapshot.h"
#include <string.h>

typedef struct {
  const ExpSnapshotTree *tree;
  uint32_t id;
} DynNode;
typedef struct {
  uint32_t row, column; /* Zero-based; column counts bytes. */
} DynPoint;
typedef enum {
  DYN_DECL_FUNCTION,
  DYN_DECL_STRUCT,
  DYN_DECL_ENUM,
  DYN_DECL_ALIAS,
  DYN_DECL_CONSTANT,
  DYN_DECL_VARIABLE
} DynDeclarationKind;
typedef struct {
  DynNode node, name; /* The declared item (inside any wrapper) and its name. */
  DynDeclarationKind kind;
  bool is_public;
} DynDeclaration;

static inline DynNode dyn_node(const ExpSnapshotTree *tree, uint32_t id) {
  return (DynNode){tree, tree && id < tree->count ? id : UINT32_MAX};
}
static inline DynNode dyn_node_root(const ExpSnapshotTree *tree) {
  return dyn_node(tree, tree ? tree->root : UINT32_MAX);
}
static inline bool dyn_node_null(DynNode n) {
  return !n.tree || n.id == UINT32_MAX;
}
static inline const ExpNode *dyn_node_data(DynNode n) {
  return &n.tree->nodes[n.id];
}
static inline unsigned dyn_node_kind(DynNode n) {
  return dyn_node_null(n) ? 0 : dyn_node_data(n)->kind;
}
static inline bool dyn_node_is(DynNode n, unsigned kind) {
  return !dyn_node_null(n) && dyn_node_data(n)->kind == kind;
}
static inline uint32_t dyn_node_start(DynNode n) {
  return dyn_node_null(n) ? 0 : dyn_node_data(n)->start;
}
static inline uint32_t dyn_node_end(DynNode n) {
  return dyn_node_null(n) ? 0 : dyn_node_data(n)->end;
}
static inline unsigned dyn_node_flags(DynNode n) {
  return dyn_node_null(n) ? 0 : dyn_node_data(n)->flags;
}
static inline DynNode dyn_node_first(DynNode n) {
  return dyn_node_null(n) ? n : dyn_node(n.tree, dyn_node_data(n)->first);
}
static inline DynNode dyn_node_next(DynNode n) {
  return dyn_node_null(n) ? n : dyn_node(n.tree, dyn_node_data(n)->next);
}
static inline DynNode dyn_node_parent(DynNode n) {
  return dyn_node_null(n) ? n : dyn_node(n.tree, dyn_node_data(n)->parent);
}
static inline uint32_t dyn_node_child_count(DynNode n) {
  uint32_t count = 0;
  for (DynNode c = dyn_node_first(n); !dyn_node_null(c); c = dyn_node_next(c)) ++count;
  return count;
}
static inline DynNode dyn_node_child(DynNode n, uint32_t index) {
  DynNode c = dyn_node_first(n);
  while (index-- && !dyn_node_null(c)) c = dyn_node_next(c);
  return c;
}
static inline DynNode dyn_node_last(DynNode n) {
  DynNode last = {n.tree, UINT32_MAX};
  for (DynNode c = dyn_node_first(n); !dyn_node_null(c); c = dyn_node_next(c)) last = c;
  return last;
}
/* First child with the given field role or kind. */
static inline DynNode dyn_node_field(DynNode n, ExpField field) {
  for (DynNode c = dyn_node_first(n); !dyn_node_null(c); c = dyn_node_next(c))
    if (dyn_node_data(c)->field == field) return c;
  return (DynNode){n.tree, UINT32_MAX};
}
static inline DynNode dyn_node_child_kind(DynNode n, unsigned kind) {
  for (DynNode c = dyn_node_first(n); !dyn_node_null(c); c = dyn_node_next(c))
    if (dyn_node_data(c)->kind == kind) return c;
  return (DynNode){n.tree, UINT32_MAX};
}
static inline DynNode dyn_node_ancestor(DynNode n, unsigned kind) {
  for (n = dyn_node_parent(n); !dyn_node_null(n); n = dyn_node_parent(n))
    if (dyn_node_data(n)->kind == kind) return n;
  return n;
}
/* Pre-order successor within root's subtree, in source order. */
static inline DynNode dyn_node_preorder(DynNode n, DynNode root) {
  DynNode child = dyn_node_first(n);
  if (!dyn_node_null(child)) return child;
  while (!dyn_node_null(n) && n.id != root.id) {
    DynNode next = dyn_node_next(n);
    if (!dyn_node_null(next)) return next;
    n = dyn_node_parent(n);
  }
  return (DynNode){root.tree, UINT32_MAX};
}
/* Deepest node whose span contains [start, end]. At a boundary between two
   siblings the later one wins, so a cursor at a name's end still selects it
   when nothing follows; null only for an empty tree. */
static inline DynNode dyn_node_at(const ExpSnapshotTree *tree, uint32_t start, uint32_t end) {
  DynNode n = dyn_node_root(tree);
  if (dyn_node_null(n)) return n;
  for (;;) {
    DynNode found = {tree, UINT32_MAX};
    for (DynNode c = dyn_node_first(n); !dyn_node_null(c); c = dyn_node_next(c))
      if (dyn_node_start(c) <= start && end <= dyn_node_end(c)) found = c;
    if (dyn_node_null(found)) return n;
    n = found;
  }
}
static inline bool dyn_node_text_is(DynNode n, const char *text, const char *word) {
  size_t length = strlen(word);
  return !dyn_node_null(n) && dyn_node_end(n) - dyn_node_start(n) == length &&
         !memcmp(text + dyn_node_start(n), word, length);
}
/* The name of a top-level item, and what it declares. */
static inline bool dyn_node_declaration(DynNode wrapper, DynDeclaration *out) {
  if (!dyn_node_is(wrapper, SRC_DECLARATION)) return false;
  DynNode node = dyn_node_first(wrapper), value = node;
  DynDeclarationKind kind;
  switch (dyn_node_kind(node)) {
  case SRC_FN: case SRC_EXTERN_FN: kind = DYN_DECL_FUNCTION; break;
  case SRC_STRUCT: kind = DYN_DECL_STRUCT; break;
  case SRC_ENUM: kind = DYN_DECL_ENUM; break;
  case SRC_ALIAS: kind = DYN_DECL_ALIAS; break;
  case SRC_CONST: kind = DYN_DECL_CONSTANT; value = dyn_node_first(node); break;
  case SRC_VARIABLE: case SRC_EXTERN_VARIABLE: kind = DYN_DECL_VARIABLE; break;
  default: return false;
  }
  DynNode name = dyn_node_child_kind(value, EXP_NAME);
  if (dyn_node_null(name)) return false;
  *out = (DynDeclaration){node, name, kind, (dyn_node_flags(wrapper) & EXP_PUBLIC) != 0};
  return true;
}
static inline DynPoint dyn_text_advance(DynPoint point, const char *text, size_t length) {
  for (size_t i = 0; i < length; ++i) {
    if (text[i] == '\n') { ++point.row; point.column = 0; }
    else ++point.column;
  }
  return point;
}
static inline DynPoint dyn_text_point(const char *text, uint32_t offset) {
  DynPoint point = {0, 0};
  for (uint32_t i = 0; i < offset && text[i]; ++i) {
    if (text[i] == '\n') { ++point.row; point.column = 0; }
    else ++point.column;
  }
  return point;
}
#endif
