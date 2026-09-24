#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

typedef struct { double wall, user, system; long rss; } Sample;

static double seconds(struct timeval t) { return t.tv_sec + t.tv_usec / 1e6; }
static double monotonic(void) {
  struct timespec t;
  if (clock_gettime(CLOCK_MONOTONIC, &t)) { perror("clock_gettime"); exit(2); }
  return t.tv_sec + t.tv_nsec / 1e9;
}
static int by_wall(const void *a, const void *b) {
  double x = ((const Sample *)a)->wall, y = ((const Sample *)b)->wall;
  return (x > y) - (x < y);
}
static int by_user(const void *a, const void *b) {
  double x = ((const Sample *)a)->user, y = ((const Sample *)b)->user;
  return (x > y) - (x < y);
}
static int by_system(const void *a, const void *b) {
  double x = ((const Sample *)a)->system, y = ((const Sample *)b)->system;
  return (x > y) - (x < y);
}
static int by_rss(const void *a, const void *b) {
  long x = ((const Sample *)a)->rss, y = ((const Sample *)b)->rss;
  return (x > y) - (x < y);
}
static Sample run(const char *exe, const char *input) {
  double start = monotonic();
  pid_t child = fork();
  if (child == 0) {
    int in = open(input, O_RDONLY), out = open("/dev/null", O_WRONLY);
    if (in < 0 || out < 0 || dup2(in, 0) < 0 || dup2(out, 1) < 0 || dup2(out, 2) < 0) _exit(126);
    execl(exe, exe, (char *)0);
    _exit(127);
  }
  if (child < 0) { perror("fork"); exit(2); }
  int status;
  struct rusage usage;
  if (wait4(child, &status, 0, &usage) < 0) { perror("wait4"); exit(2); }
  if (!WIFEXITED(status) || WEXITSTATUS(status)) {
    fprintf(stderr, "%s failed\n", exe); exit(2);
  }
  return (Sample){monotonic() - start, seconds(usage.ru_utime),
                  seconds(usage.ru_stime), usage.ru_maxrss};
}
int main(int argc, char **argv) {
  if (argc != 5) {
    fprintf(stderr, "usage: runner runs input label executable\n"); return 2;
  }
  int count = atoi(argv[1]);
  if (count < 3) return 2;
  Sample *samples = calloc((size_t)count, sizeof(*samples));
  (void)run(argv[4], argv[2]);
  for (int i = 0; i < count; ++i) samples[i] = run(argv[4], argv[2]);
  qsort(samples, (size_t)count, sizeof(*samples), by_wall);
  double wall = samples[count / 2].wall;
  qsort(samples, (size_t)count, sizeof(*samples), by_user);
  double user = samples[count / 2].user;
  qsort(samples, (size_t)count, sizeof(*samples), by_system);
  double system = samples[count / 2].system;
  qsort(samples, (size_t)count, sizeof(*samples), by_rss);
  long rss = samples[count / 2].rss;
  struct stat st;
  if (stat(argv[4], &st)) { perror("stat"); return 2; }
  printf("%s\t%.6f\t%.6f\t%.6f\t%ld\t%lld\n", argv[3], wall,
         user, system, rss, (long long)st.st_size);
  free(samples);
  return 0;
}
