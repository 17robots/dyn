#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <assert.h>
#include <stdlib.h>
#include <time.h>
#include <errno.h>
#include <sys/wait.h>
#include <unistd.h>

static int interrupt_wait;
static unsigned injected_interrupts;
pid_t __real_waitpid(pid_t pid, int *status, int options);
pid_t __wrap_waitpid(pid_t pid, int *status, int options) {
  if (interrupt_wait) {
    interrupt_wait = 0;
    ++injected_interrupts;
    errno = EINTR;
    return -1;
  }
  return __real_waitpid(pid, status, options);
}

static int run(const DynSources *sources, size_t first, size_t count,
               void *context, uint64_t *value) {
  (void)context;
  struct timespec delay = {0, (long)(sources->count - first) * 100000};
  nanosleep(&delay, NULL); /* Deliberately finish out of order. */
  *value = first * 10 + count;
  return 0;
}

static int errors(const DynSources *sources, size_t first, size_t count,
                  void *context, uint64_t *value) {
  (void)sources; (void)count; (void)value;
  if (context) assert(*(pid_t *)context == getpid());
  return first == 2 ? 7 : first == 3 ? 9 : 0;
}
static int crash(const DynSources *sources, size_t first, size_t count,
                 void *context, uint64_t *value) {
  (void)sources; (void)first; (void)count; (void)context; (void)value;
  _exit(3);
}
int main(void) {
  DynSource items[] = {{.path="a/1.dyn",.text=""}, {.path="a/2.dyn",.text=""},
                       {.path="b/1.dyn",.text=""}, {.path="c/1.dyn",.text=""}};
  DynSources sources = {items, 4};
  uint64_t *values = NULL;
  size_t count = 0;
  assert(!dyn_build_plan_run(&sources, 8, run, NULL, &values, &count));
  assert(count == 3 && values[0] == 2 && values[1] == 21 && values[2] == 31);
  free(values);
  pid_t parent = getpid();
  assert(dyn_build_plan_run(&sources, 1, errors, &parent, &values, &count) == 7);
  assert(!values && !count);
  assert(dyn_build_plan_run(&sources, 2, errors, NULL, &values, &count) == 7);
  assert(!values && !count);
  assert(dyn_build_plan_run(&sources, 2, crash, NULL, &values, &count) == 2);
  assert(!values && !count);
  assert(!dyn_build_plan_run(&sources, 1, run, NULL, &values, &count));
  assert(count == 3 && values[0] == 2 && values[1] == 21 && values[2] == 31);
  free(values);
  interrupt_wait = 1;
  assert(!dyn_build_plan_run(&sources, 8, run, NULL, &values, &count));
  assert(injected_interrupts == 1);
  assert(count == 3 && values[0] == 2 && values[1] == 21 && values[2] == 31);
  free(values);
  /* All workers must have been reaped even after an interrupted wait. */
  assert(waitpid(-1, NULL, WNOHANG) == -1 && errno == ECHILD);
  return 0;
}
