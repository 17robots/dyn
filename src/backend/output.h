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

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <wchar.h>

/* CREATE_NEW reserves a sibling path; publication replaces the destination
   only after every byte is written and the handle is closed. */
static inline bool backend_write_object(const char *path, const void *data, size_t length) {
  int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, NULL, 0);
  if (!count || count > 32700) return false;
  wchar_t *target = malloc((size_t)count * sizeof(*target));
  wchar_t *temporary = malloc(((size_t)count + 64) * sizeof(*temporary));
  if (!target || !temporary) { free(target); free(temporary); return false; }
  if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, target, count)) {
    free(target); free(temporary); return false;
  }
  static volatile LONG sequence;
  HANDLE file = INVALID_HANDLE_VALUE;
  for (unsigned attempt = 0; attempt < 128; ++attempt) {
    swprintf(temporary, (size_t)count + 64, L"%ls.dyn-object.%lu.%lu", target,
             (unsigned long)GetCurrentProcessId(), (unsigned long)InterlockedIncrement(&sequence));
    file = CreateFileW(temporary, GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file != INVALID_HANDLE_VALUE || GetLastError() != ERROR_FILE_EXISTS) break;
  }
  bool ok = file != INVALID_HANDLE_VALUE;
  size_t at = 0;
  while (ok && at < length) {
    DWORD amount = length-at > 0x40000000 ? 0x40000000 : (DWORD)(length-at), wrote = 0;
    ok = WriteFile(file, (const unsigned char *)data + at, amount, &wrote, NULL) && wrote != 0;
    at += wrote;
  }
  if (file != INVALID_HANDLE_VALUE) {
    if (!CloseHandle(file)) ok = false;
    if (ok) ok = MoveFileExW(temporary, target, MOVEFILE_REPLACE_EXISTING) != 0;
    if (!ok) DeleteFileW(temporary);
  }
  free(target); free(temporary);
  return ok;
}
#else
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
#endif /* _WIN32 */
#endif
