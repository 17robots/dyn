#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* Isolate scheduling from codegen noise: expensive modules occupy the same
   old round-robin lane. This is a synthetic scheduler benchmark, not a claim
   about every project's build time. */
static int work(const DynSources *s, size_t first, size_t count, void *context,
                uint64_t *value) {
  (void)s; (void)count;
  if (context) {
    struct timespec delay = {0, first % 2 ? 1000000 : 40000000};
    nanosleep(&delay, NULL);
  }
  *value = first;
  return 0;
}
static void round_robin(const DynSources *s, unsigned workers, void *context) {
  pid_t pids[2];
  for (unsigned w = 0; w < workers; ++w) {
    pids[w] = fork(); assert(pids[w] >= 0);
    if (!pids[w]) {
      uint64_t value;
      for (size_t i = w; i < s->count; i += workers) work(s, i, 1, context, &value);
      _exit(0);
    }
  }
  for (unsigned w = 0; w < workers; ++w) {
    int status; assert(waitpid(pids[w], &status, 0) == pids[w]);
    assert(WIFEXITED(status) && !WEXITSTATUS(status));
  }
}
static double now(void) {
  struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec * 1000.0 + t.tv_nsec / 1000000.0;
}
int main(void) {
  DynSource items[] = {{.path="a/m.dyn"}, {.path="b/m.dyn"}, {.path="c/m.dyn"}, {.path="d/m.dyn"}};
  DynSources sources = {items, 4};
  puts("{\"samples\":[");
  for (unsigned workers = 1; workers <= 2; ++workers)
    for (unsigned sample = 0; sample < 5; ++sample) {
      unsigned repeats = workers == 1 ? 100 : 1;
      void *delays = workers == 2 ? &sources : NULL;
      double start = now();
      for (unsigned i = 0; i < repeats; ++i) round_robin(&sources, workers, delays);
      double old = now() - start;
      start = now();
      for (unsigned i = 0; i < repeats; ++i) {
        uint64_t *values; size_t count;
        assert(!dyn_build_plan_run(&sources, workers, work, delays, &values, &count));
        assert(count == 4);
        for (size_t j = 0; j < count; ++j) assert(values[j] == j);
        free(values);
      }
      printf("%s{\"workers\":%u,\"iterations\":%u,\"round_robin_ms\":%.3f,\"current_ms\":%.3f}",
             workers == 1 && !sample ? "" : ",\n", workers, repeats, old, now() - start);
    }
  puts("\n]}");
}
