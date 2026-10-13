// Runs a command and prints wall seconds and the peak RSS of its process tree.
// RUSAGE_CHILDREN covers every descendant the command reaped, and this process
// stays small, so its own memory does not inflate small programs.
#define _GNU_SOURCE
#include <stdio.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

int main(int argc, char **argv) {
  if (argc < 2) return 2;
  struct timespec start, end;
  clock_gettime(CLOCK_MONOTONIC, &start);
  pid_t child = fork();
  if (child == 0) {
    execvp(argv[1], argv + 1);
    _exit(127);
  }
  int status = 0;
  struct rusage usage;
  if (wait4(child, &status, 0, &usage) < 0) return 2;
  clock_gettime(CLOCK_MONOTONIC, &end);
  struct rusage all;
  getrusage(RUSAGE_CHILDREN, &all);
  double seconds = (double)(end.tv_sec - start.tv_sec) + (double)(end.tv_nsec - start.tv_nsec) / 1e9;
  fprintf(stderr, "{\"seconds\": %.6f, \"rss_mib\": %.1f}\n", seconds, (double)all.ru_maxrss / 1024.0);
  return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
