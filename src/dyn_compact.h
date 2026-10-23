#ifndef DYN_COMPACT_H
#define DYN_COMPACT_H
#include "dyn.h"
#include "snapshot.h"
static inline const ExpSnapshotTree *dyn_compact_tree(const DynSource *source) {
  return exp_snapshot_tree(source->compact);
}
static inline uint32_t dyn_compact_field(const ExpSnapshotTree *tree, uint32_t node, ExpField field) {
  for (uint32_t child = tree->nodes[node].first; child != UINT32_MAX;
       child = tree->nodes[child].next)
    if (tree->nodes[child].field == field) return child;
  return UINT32_MAX;
}
/* Declaration names are a concrete module-interface fact, not a syntax API. */
static inline uint32_t dyn_compact_name(const ExpSnapshotTree *tree, uint32_t wrapper) {
  if (tree->nodes[wrapper].kind != SRC_DECLARATION) return UINT32_MAX;
  uint32_t node = tree->nodes[wrapper].first;
  if (node == UINT32_MAX) return node;
  switch (tree->nodes[node].kind) {
  case SRC_CONST: node = tree->nodes[node].first; break;
  case SRC_FN: case SRC_EXTERN_FN: case SRC_EXTERN_VARIABLE:
  case SRC_STRUCT: case SRC_ENUM: case SRC_ALIAS: case SRC_VARIABLE: break;
  default: return UINT32_MAX;
  }
  for (uint32_t child = tree->nodes[node].first; child != UINT32_MAX; child = tree->nodes[child].next) if (tree->nodes[child].kind == EXP_NAME) return child;
  return UINT32_MAX;
}
#endif
