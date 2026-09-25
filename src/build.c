#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <errno.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>

typedef struct {
  size_t first, count;
} Job;

static size_t directory_length(const char *path) {
  const char *slash = strrchr(path, '/');
  return slash ? (size_t)(slash - path) : 0;
}
static bool same_directory(const char *a, const char *b) {
  size_t an = directory_length(a), bn = directory_length(b);
  return an == bn && !memcmp(a, b, an);
}

int dyn_build_plan_run(const DynSources *sources, unsigned workers,
                       DynModuleBuildFn build, void *context, uint64_t **values,
                       size_t *value_count) {
  if (!sources || !build || !values || !value_count)
    return 2;
  *values = NULL;
  *value_count = 0;
  if (!sources->count)
    return 0;
  if (sources->count > SIZE_MAX / sizeof(Job) ||
      sources->count > SIZE_MAX / (sizeof(uint64_t) + sizeof(int)))
    return 2;
  Job *jobs = calloc(sources->count, sizeof(*jobs));
  if (!jobs)
    return 2;
  size_t count = 0;
  for (size_t i = 0; i < sources->count;) {
    size_t end = i + 1;
    while (end < sources->count &&
           same_directory(sources->items[i].path, sources->items[end].path))
      ++end;
    jobs[count++] = (Job){i, end - i};
    i = end;
  }
  long online = sysconf(_SC_NPROCESSORS_ONLN);
  if (!workers)
    workers = online > 0 ? (unsigned)online : 1;
  if (workers > count)
    workers = (unsigned)count;
  if (workers == 1) {
    uint64_t *out = calloc(count, sizeof(*out));
    if (!out) { free(jobs); return 2; }
    int result = 0;
    for (size_t id = 0; id < count; ++id) {
      int error = build(sources, jobs[id].first, jobs[id].count, context, &out[id]);
      if (!result) result = error;
    }
    free(jobs);
    if (result) { free(out); return result; }
    *values = out; *value_count = count;
    return 0;
  }
  /* The shared cursor assigns a new module as soon as any worker finishes.
     Output slots remain indexed by source order, independent of scheduling. */
  typedef struct { atomic_size_t next; uint64_t alignment; } Queue;
  if (count > (SIZE_MAX - sizeof(Queue)) / (sizeof(uint64_t) + sizeof(int))) {
    free(jobs); return 2;
  }
  size_t shared_size = sizeof(Queue) + count * (sizeof(uint64_t) + sizeof(int));
  unsigned char *shared = mmap(NULL, shared_size, PROT_READ | PROT_WRITE,
                               MAP_SHARED | MAP_ANONYMOUS, -1, 0);
  if (shared == MAP_FAILED) {
    free(jobs);
    return 2;
  }
  Queue *queue = (Queue *)shared;
  atomic_init(&queue->next, 0);
  bool dynamic = atomic_is_lock_free(&queue->next);
  uint64_t *out = (uint64_t *)(shared + sizeof(*queue));
  int *errors = (int *)(out + count);
  pid_t *pids = calloc(workers, sizeof(*pids));
  if (!pids) {
    munmap(shared, shared_size);
    free(jobs);
    return 2;
  }
  int result = 0;
  for (unsigned worker = 0; worker < workers; ++worker) {
    pids[worker] = fork();
    if (pids[worker] < 0) {
      result = 2;
      break;
    }
    if (!pids[worker]) {
      for (size_t fixed = worker;; fixed += workers) {
        size_t id = dynamic ? atomic_fetch_add_explicit(&queue->next, 1, memory_order_relaxed) : fixed;
        if (id >= count) break;
        errors[id] = build(sources, jobs[id].first, jobs[id].count, context, &out[id]);
      }
      _exit(0);
    }
  }
  for (unsigned worker = 0; worker < workers; ++worker)
    if (pids[worker] > 0) {
      int status = 0;
      pid_t waited;
      do {
        waited = waitpid(pids[worker], &status, 0);
      } while (waited < 0 && errno == EINTR);
      if (waited < 0 || !WIFEXITED(status) || WEXITSTATUS(status))
        result = 2;
    }
  for (size_t i = 0; i < count; ++i)
    if (errors[i] && !result)
      result = errors[i];
  uint64_t *copy = NULL;
  if (!result) {
    copy = malloc(count * sizeof(*copy));
    if (copy)
      memcpy(copy, out, count * sizeof(*copy));
    else
      result = 2;
  }
  free(pids);
  munmap(shared, shared_size);
  free(jobs);
  if (result) {
    free(copy);
    return result;
  }
  *values = copy;
  *value_count = count;
  return 0;
}
