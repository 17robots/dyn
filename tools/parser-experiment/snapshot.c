#include "snapshot.h"
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>

struct ExpSnapshot {
  atomic_size_t references;
  char *text;
  size_t length;
  ExpTree storage;
  ExpSnapshotTree view;
};

static void snapshot_error(ExpSnapshotError *out, ExpError kind,
                           const char *message, uint32_t offset) {
  if (out) *out = (ExpSnapshotError){kind, message, offset, NULL};
}

ExpSnapshot *exp_snapshot_create(const char *text, size_t length,
                                 const ExpOptions *options,
                                 ExpSnapshotError *error) {
  snapshot_error(error, EXP_OK, NULL, 0);
  if ((!text && length) || length > UINT32_MAX || length == SIZE_MAX) {
    snapshot_error(error, EXP_LIMIT_ERROR, "invalid source or source too large", 0);
    return NULL;
  }
  ExpOptions parse_options = options ? *options : (ExpOptions){0};
  uint64_t remaining = parse_options.max_work ? parse_options.max_work
                                              : (uint64_t)length * 128 + 1024;
  if (parse_options.work && !parse_options.work(parse_options.data, 0)) {
    snapshot_error(error, EXP_CANCELLED, "analysis work budget exceeded or cancelled", 0);
    return NULL;
  }
  if (length > remaining) {
    snapshot_error(error, EXP_LIMIT_ERROR, "parse work limit exceeded", 0);
    return NULL;
  }
  ExpSnapshot *snapshot = calloc(1, sizeof(*snapshot));
  if (!snapshot) {
    snapshot_error(error, EXP_ALLOCATION_ERROR, "out of memory", 0);
    return NULL;
  }
  atomic_init(&snapshot->references, 1);
  snapshot->text = malloc(length + 1);
  if (!snapshot->text) {
    snapshot_error(error, EXP_ALLOCATION_ERROR, "out of memory", 0);
    exp_snapshot_release(snapshot);
    return NULL;
  }
  for (size_t offset = 0; offset < length;) {
    size_t bytes = length - offset;
    if (bytes > 1024) bytes = 1024;
    if (bytes > remaining) {
      snapshot_error(error, EXP_LIMIT_ERROR, "parse work limit exceeded", (uint32_t)offset);
      exp_snapshot_release(snapshot);
      return NULL;
    }
    remaining -= bytes;
    if (parse_options.work && !parse_options.work(parse_options.data, bytes)) {
      snapshot_error(error, EXP_CANCELLED, "analysis work budget exceeded or cancelled", (uint32_t)offset);
      exp_snapshot_release(snapshot);
      return NULL;
    }
    memcpy(snapshot->text + offset, text + offset, bytes);
    offset += bytes;
  }
  snapshot->text[length] = 0;
  snapshot->length = length;
  /* A zero parser limit selects its default; do not accidentally reset an
     exhausted snapshot budget when handing off to the parser. */
  if (!remaining) {
    snapshot_error(error, EXP_LIMIT_ERROR, "parse work limit exceeded", (uint32_t)length);
    exp_snapshot_release(snapshot);
    return NULL;
  }
  parse_options.max_work = remaining;
  if (!exp_parse_source_with_options(snapshot->text, length, &snapshot->storage,
                                     &parse_options)) {
    snapshot_error(error, snapshot->storage.error_kind, snapshot->storage.error,
                    snapshot->storage.error_offset);
    if (error) error->expected = snapshot->storage.error_expected;
    exp_snapshot_release(snapshot);
    return NULL;
  }
  /* Frozen snapshots never append nodes. Do not retain the parser's geometric
     growth slack for every loaded module and lazy generic body. */
  if (snapshot->storage.capacity != snapshot->storage.count) {
    size_t bytes = (size_t)snapshot->storage.count * sizeof(*snapshot->storage.nodes);
    ExpNode *nodes = realloc(snapshot->storage.nodes, bytes);
    if (!nodes) {
      snapshot_error(error, EXP_ALLOCATION_ERROR, "out of memory", 0);
      exp_snapshot_release(snapshot);
      return NULL;
    }
    snapshot->storage.nodes = nodes;
    snapshot->storage.capacity = snapshot->storage.count;
  }
  snapshot->view = (ExpSnapshotTree){snapshot->storage.nodes,
                                    snapshot->storage.count,
                                    snapshot->storage.root};
  return snapshot;
}

bool exp_snapshot_retain(ExpSnapshot *snapshot) {
  if (!snapshot) return false;
  size_t count = atomic_load_explicit(&snapshot->references, memory_order_relaxed);
  while (count && count != SIZE_MAX) {
    if (atomic_compare_exchange_weak_explicit(&snapshot->references, &count,
          count + 1, memory_order_relaxed, memory_order_relaxed)) return true;
  }
  return false;
}

void exp_snapshot_release(ExpSnapshot *snapshot) {
  if (!snapshot) return;
  if (atomic_fetch_sub_explicit(&snapshot->references, 1, memory_order_acq_rel) != 1)
    return;
  exp_free(&snapshot->storage);
  free(snapshot->text);
  free(snapshot);
}

const char *exp_snapshot_text(const ExpSnapshot *snapshot) {
  return snapshot ? snapshot->text : NULL;
}
size_t exp_snapshot_length(const ExpSnapshot *snapshot) {
  return snapshot ? snapshot->length : 0;
}
const ExpNode *exp_snapshot_nodes(const ExpSnapshot *snapshot) {
  return snapshot ? snapshot->view.nodes : NULL;
}
const ExpSnapshotTree *exp_snapshot_tree(const ExpSnapshot *snapshot) {
  return snapshot ? &snapshot->view : NULL;
}
