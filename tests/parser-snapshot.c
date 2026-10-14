#include <assert.h>
#include <stdbool.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned allocations, fail_at, live;
static void *test_malloc(size_t bytes) {
  if (++allocations == fail_at) return NULL;
  void *p = malloc(bytes);
  if (p) ++live;
  return p;
}
static void *test_calloc(size_t count, size_t bytes) {
  if (++allocations == fail_at) return NULL;
  void *p = calloc(count, bytes);
  if (p) ++live;
  return p;
}
static void *test_realloc(void *p, size_t bytes) {
  if (++allocations == fail_at) return NULL;
  bool fresh = !p;
  void *result = realloc(p, bytes);
  if (result && fresh) ++live;
  return result;
}
static void test_free(void *p) {
  if (p) { assert(live); --live; }
  free(p);
}
#define malloc test_malloc
#define calloc test_calloc
#define realloc test_realloc
#define free test_free
#include "parser.c"
#include "snapshot.c"
#undef malloc
#undef calloc
#undef realloc
#undef free

static const char source[] = "use \"dep\" d pub fn f(a:i64) i64 { return a+1 }";
static void *reader(void *data) {
  ExpSnapshot *snapshot = data;
  for (unsigned i = 0; i < 10000; ++i) {
    assert(exp_snapshot_retain(snapshot));
    const ExpSnapshotTree *tree = exp_snapshot_tree(snapshot);
    assert(tree->nodes[tree->root].parent == UINT32_MAX);
    assert(!memcmp(exp_snapshot_text(snapshot), source, sizeof(source)));
    exp_snapshot_release(snapshot);
  }
  exp_snapshot_release(snapshot);
  return NULL;
}
typedef struct { unsigned calls, stop; } Probe;
static bool work(void *data, uint64_t units) {
  Probe *p = data;
  (void)units;
  return ++p->calls != p->stop;
}
int main(void) {
  ExpSnapshotError error;
  char original[sizeof(source)]; memcpy(original, source, sizeof(source));
  ExpSnapshot *snapshot = exp_snapshot_create(original, strlen(original), NULL, &error);
  assert(snapshot && error.kind == EXP_OK && !error.message);
  assert(snapshot->storage.capacity == snapshot->storage.count);
  unsigned total = allocations;
  assert(total >= 3);
  memset(original, 'x', strlen(original));
  assert(!strcmp(exp_snapshot_text(snapshot), source));
  assert(exp_snapshot_length(snapshot) == strlen(source));
  assert(exp_snapshot_nodes(snapshot) == exp_snapshot_tree(snapshot)->nodes);
  assert(exp_snapshot_retain(snapshot));
  exp_snapshot_release(snapshot);
  assert(!strcmp(exp_snapshot_text(snapshot), source));
  /* Overflow must not silently wrap and publish an unowned reference. */
  atomic_store(&snapshot->references, SIZE_MAX);
  assert(!exp_snapshot_retain(snapshot));
  assert(atomic_load(&snapshot->references) == SIZE_MAX);
  atomic_store(&snapshot->references, 1);
  pthread_t threads[4];
  for (unsigned i = 0; i < 4; ++i) {
    assert(exp_snapshot_retain(snapshot));
    assert(!pthread_create(&threads[i], NULL, reader, snapshot));
  }
  exp_snapshot_release(snapshot);
  for (unsigned i = 0; i < 4; ++i) assert(!pthread_join(threads[i], NULL));
  assert(!live);
  for (unsigned stop = 1; stop <= total; ++stop) {
    allocations = 0; fail_at = stop;
    assert(!exp_snapshot_create(source, strlen(source), NULL, &error));
    assert(error.kind == EXP_ALLOCATION_ERROR && !strcmp(error.message, "out of memory"));
    assert(!live);
    fail_at = 0;
    snapshot = exp_snapshot_create(source, strlen(source), NULL, &error);
    assert(snapshot && error.kind == EXP_OK);
    exp_snapshot_release(snapshot); assert(!live);
  }
  /* Includes copy checkpoints, parser lookahead, and finalization callbacks. */
  char large[8192]; memset(large, ' ', sizeof(large));
  memcpy(large + sizeof(large) - strlen(source), source, strlen(source));
  Probe probe = {0}; ExpOptions options = {.work = work, .data = &probe};
  snapshot = exp_snapshot_create(large, sizeof(large), &options, &error);
  assert(snapshot); unsigned calls = probe.calls;
  exp_snapshot_release(snapshot); assert(!live);
  for (unsigned stop = 1; stop <= calls; ++stop) {
    probe = (Probe){.stop = stop};
    assert(!exp_snapshot_create(large, sizeof(large), &options, &error));
    assert(error.kind == EXP_CANCELLED && error.offset <= sizeof(large));
    assert(probe.calls == stop && !live);
  }
  options = (ExpOptions){.max_work = strlen(source)};
  assert(!exp_snapshot_create(source, strlen(source), &options, &error));
  assert(error.kind == EXP_LIMIT_ERROR && !live);
  assert(!exp_snapshot_create("fn", 2, NULL, &error));
  assert(error.kind == EXP_SYNTAX_ERROR && error.offset <= 2 && !live);
  assert(!exp_snapshot_create("\0", 1, NULL, &error));
  assert(error.kind == EXP_SYNTAX_ERROR && !live);
  assert(!exp_snapshot_create(NULL, 1, NULL, &error));
  assert(error.kind == EXP_LIMIT_ERROR && !live);
  snapshot = exp_snapshot_create(NULL, 0, NULL, &error);
  assert(snapshot && !exp_snapshot_length(snapshot));
  exp_snapshot_release(snapshot); assert(!live);
  puts("PASS immutable snapshots: independent revisions, concurrent lifetime, allocation failures and cancellation");
}
