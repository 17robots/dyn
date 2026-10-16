#ifndef DYN_SNAPSHOT_H
#define DYN_SNAPSHOT_H
#include "parser.h"

typedef struct ExpSnapshot ExpSnapshot;
typedef struct {
  ExpError kind;
  const char *message; /* Static lifetime; NULL on success. */
  uint32_t offset;
  const char *expected; /* Static spelling a syntax error wanted, or NULL. */
} ExpSnapshotError;
/* Unlike const ExpTree, this view cannot expose mutable node storage. */
typedef struct {
  const ExpNode *nodes;
  uint32_t count, root;
  /* Nonempty only for recovering parses; such trees contain SRC_ERROR nodes. */
  const ExpSyntaxError *errors;
  uint32_t error_count;
} ExpSnapshotTree;

/* Copy the exact source revision and parse it before publication. The returned
   snapshot owns one reference. Options and callback data are borrowed only for
   this call. Copying and parsing share the work limit; copying adds one work
   unit per byte. The optional error output never borrows snapshot storage. */
ExpSnapshot *exp_snapshot_create(const char *text, size_t length,
                                 const ExpOptions *options,
                                 ExpSnapshotError *error);
/* Retaining requires an existing live reference or external synchronization
   protecting one. Independent references may be released on separate threads.
   Overflow refuses the retain without changing the reference count. */
bool exp_snapshot_retain(ExpSnapshot *snapshot);
void exp_snapshot_release(ExpSnapshot *snapshot);

/* All views borrow the snapshot and remain valid while a reference is held.
   Text has an additional NUL terminator, excluded from its exact byte length. */
const char *exp_snapshot_text(const ExpSnapshot *snapshot);
size_t exp_snapshot_length(const ExpSnapshot *snapshot);
const ExpNode *exp_snapshot_nodes(const ExpSnapshot *snapshot);
const ExpSnapshotTree *exp_snapshot_tree(const ExpSnapshot *snapshot);
#endif
