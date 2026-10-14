#ifndef EXP_DEPTH_H
#define EXP_DEPTH_H
#include "snapshot.h"
/* Production syntax nesting limit, measured on the bound below. */
#define DYN_SYNTAX_DEPTH_LIMIT 1024u
/* Pinned grammar: expression/literal/statement are inline, primary is the only
   removed nonterminal and cannot directly contain another primary. All other
   discarded children (tokens, comments, escapes) are leaves. Thus retained
   edges cost one plus the child's primary flag; one extra terminal edge bounds
   the raw visible Tree-sitter depth. Synthetic empty slice nodes overestimate.
   This bounds depth conditional on the qualified normalized-tree parity; it is
   not a proof of acceptance equivalence. See check-depth.py and grammar-pin.py. */
static inline bool exp_depth_certified(const ExpSnapshotTree *tree, uint32_t limit) {
  if (!tree || tree->root >= tree->count) return false;
  uint32_t at=tree->root, depth=0, visited=0;
  for (;;) {
    if (++visited>tree->count || depth>=limit) return false;
    uint32_t child=tree->nodes[at].first;
    if (child!=UINT32_MAX) {
      if (child>=tree->count) return false;
      depth+=1+!!(tree->nodes[child].flags&EXP_PRIMARY); at=child; continue;
    }
    for (;;) {
      if (at==tree->root) return true;
      depth-=1+!!(tree->nodes[at].flags&EXP_PRIMARY);
      uint32_t next=tree->nodes[at].next;
      if (next!=UINT32_MAX) {
        if (next>=tree->count) return false;
        depth+=1+!!(tree->nodes[next].flags&EXP_PRIMARY); at=next; break;
      }
      at=tree->nodes[at].parent;
      if (at>=tree->count) return false;
    }
  }
}
#endif
