#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

enum { NONE, ALLOCATION, DIRECTORY, OPEN, WRITE, ZERO_WRITE, CLOSE, RENAME, INTERRUPTED_SHORT };
static _Thread_local unsigned failure, allocations, writes;
static void *test_malloc(size_t n) {
  if (failure == ALLOCATION && ++allocations == 2) return NULL;
  return malloc(n);
}
static char *test_mkdtemp(char *path) {
  if (failure == DIRECTORY) { errno = EACCES; return NULL; }
  return mkdtemp(path);
}
static int test_open(const char *path, int flags, mode_t mode) {
  if (failure == OPEN) { errno = EACCES; return -1; }
  return open(path, flags, mode);
}
static ssize_t test_write(int fd, const void *data, size_t n) {
  ++writes;
  if (failure == WRITE && writes == 2) { errno = ENOSPC; return -1; }
  if (failure == ZERO_WRITE) return 0;
  if (failure == INTERRUPTED_SHORT && writes == 1) { errno = EINTR; return -1; }
  if ((failure == WRITE || failure == INTERRUPTED_SHORT) && n > 1) n = 1;
  return write(fd, data, n);
}
static int test_close(int fd) {
  int result = close(fd);
  if (failure == CLOSE) { errno = EIO; return -1; }
  return result;
}
static int test_rename(const char *from, const char *to) {
  if (failure == RENAME) { errno = EACCES; return -1; }
  return rename(from, to);
}
#define malloc test_malloc
#define mkdtemp test_mkdtemp
#define open test_open
#define write test_write
#define close test_close
#define rename test_rename
#include "output.h"
#undef malloc
#undef mkdtemp
#undef open
#undef write
#undef close
#undef rename

static const char *destination;
static atomic_uint completed;
static const char *const payloads[] = {"one", "two two", "three three three", "four four",
  "five five five five", "six", "seven seven seven", "eight eight eight eight eight"};
static void read_expected(const char *expected) {
  FILE *f = fopen(destination, "rb"); assert(f);
  char value[128] = {0}; size_t n = fread(value, 1, sizeof(value), f);
  assert(!ferror(f) && n == strlen(expected) && !memcmp(value, expected, n));
  assert(!fclose(f));
}
static void clean_directory(const char *path, bool exists) {
  DIR *dir = opendir(path); assert(dir); unsigned files = 0;
  for (struct dirent *entry; (entry = readdir(dir));) {
    if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
    assert(!strcmp(entry->d_name, strrchr(destination, '/') + 1)); ++files;
  }
  closedir(dir); assert(files == (unsigned)exists);
}
static void *concurrent_write(void *data) {
  const char *text = data;
  for (unsigned i = 0; i < 20; ++i) assert(backend_write_object(destination, text, strlen(text)));
  atomic_fetch_add(&completed, 1);
  return NULL;
}
int main(void) {
  char directory[] = "/tmp/dyn-backend-output-XXXXXX"; assert(mkdtemp(directory));
  char path[1024]; snprintf(path, sizeof(path), "%s/result.o", directory); destination = path;
  for (unsigned existing = 0; existing < 2; ++existing) {
    if (existing) assert(backend_write_object(path, "sentinel", 8));
    for (unsigned mode = ALLOCATION; mode <= RENAME; ++mode) {
      failure = mode; allocations = writes = 0;
      assert(!backend_write_object(path, "replacement", 11));
      failure = NONE;
      if (existing) read_expected("sentinel"); else assert(access(path, F_OK));
      clean_directory(directory, existing);
    }
  }
  failure = INTERRUPTED_SHORT; writes = 0;
  assert(backend_write_object(path, "replacement", 11));
  failure = NONE; read_expected("replacement"); clean_directory(directory, true);
  /* This serial test changes umask before starting threads; the writer never does. */
  mode_t prior = umask(0077); assert(backend_write_object(path, "private", 7));
  umask(prior); struct stat st; assert(!stat(path, &st) && (st.st_mode & 0777) == 0600);
  assert(backend_write_object(path, payloads[0], strlen(payloads[0])));
  pthread_t threads[8];
  for (unsigned i = 0; i < 8; ++i) assert(!pthread_create(&threads[i], NULL, concurrent_write, (void *)payloads[i]));
  do {
    FILE *f = fopen(path, "rb"); assert(f);
    char value[128] = {0}; size_t n = fread(value, 1, sizeof(value), f);
    assert(!ferror(f) && !fclose(f)); bool matches = false;
    for (unsigned i = 0; i < 8; ++i)
      matches |= n == strlen(payloads[i]) && !memcmp(value, payloads[i], n);
    assert(matches);
  } while (atomic_load(&completed) < 8);
  for (unsigned i = 0; i < 8; ++i) assert(!pthread_join(threads[i], NULL));
  clean_directory(directory, true);
  assert(!unlink(path));
  char name[256]; memset(name, 'a', sizeof(name) - 1); name[sizeof(name) - 1] = 0;
  snprintf(path, sizeof(path), "%s/%s", directory, name);
  assert(backend_write_object(path, "long name", 9));
  read_expected("long name"); clean_directory(directory, true);
  assert(!unlink(path) && !rmdir(directory));
  puts("PASS atomic object output, failure preservation, umask and concurrent publication");
  return 0;
}
