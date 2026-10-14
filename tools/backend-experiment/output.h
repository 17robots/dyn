#ifndef DYN_BACKEND_OUTPUT_H
#define DYN_BACKEND_OUTPUT_H
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Publish a complete object in one rename. A private sibling directory lets
   open apply the caller's umask without changing process-global state. This
   guarantees atomic visibility, not persistence across a system crash. */
static inline bool backend_write_object(const char *path, const void *data, size_t length) {
  size_t n = strlen(path);
  if (n > SIZE_MAX - 32) return false;
  char *directory = malloc(n + 32), *temporary = malloc(n + 32);
  if (!directory || !temporary) { free(directory); free(temporary); return false; }
  const char *slash = strrchr(path, '/');
  size_t parent = slash ? (size_t)(slash - path) + 1 : 0;
  memcpy(directory, path, parent);
  memcpy(directory + parent, ".dyn-object.XXXXXX", sizeof(".dyn-object.XXXXXX"));
  if (!mkdtemp(directory)) { free(directory); free(temporary); return false; }
  snprintf(temporary, n + 32, "%s/object", directory);
  int fd = open(temporary, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0666);
  bool ok = fd >= 0;
  size_t at = 0;
  while (ok && at < length) {
    size_t count = length - at;
    if (count > (size_t)SSIZE_MAX) count = (size_t)SSIZE_MAX;
    ssize_t wrote = write(fd, (const unsigned char *)data + at, count);
    if (wrote < 0 && errno == EINTR) continue;
    if (wrote <= 0) { ok = false; break; }
    at += (size_t)wrote;
  }
  /* Never retry close: on Linux an error can still mean the fd was released. */
  if (fd >= 0 && close(fd)) ok = false;
  if (ok) ok = rename(temporary, path) == 0;
  if (!ok) unlink(temporary);
  rmdir(directory);
  free(directory); free(temporary);
  return ok;
}
#endif
