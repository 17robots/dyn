#ifndef DYN_TIMING_H
#define DYN_TIMING_H

#include "dyn.h"
#include <stdio.h>
#include <time.h>

/* Detailed phase durations are per invocation. Parallel module work overlaps;
   sum these as worker time, not command wall time. Disabled by default. */
static inline struct timespec dyn_timing_start(const DynContext *context) {
  struct timespec now = {0};
  if (context->timings)
    clock_gettime(CLOCK_MONOTONIC, &now);
  return now;
}
static inline void dyn_timing_phase(const DynContext *context,
                                    struct timespec *start, const char *phase) {
  if (!context->timings)
    return;
  struct timespec now = dyn_timing_start(context);
  double milliseconds = (now.tv_sec - start->tv_sec) * 1000.0 +
                        (now.tv_nsec - start->tv_nsec) / 1000000.0;
  fprintf(stderr, "timing detail %s %.3f ms\n", phase, milliseconds);
  *start = now;
}

#endif
