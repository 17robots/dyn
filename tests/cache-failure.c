#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
static unsigned injected_reads;
static int inject_read_error;
static size_t failure_read(void *data, size_t size, size_t count, FILE *file) {
  if (!inject_read_error) return fread(data, size, count, file);
  ++injected_reads;
  if (injected_reads == 1 && size && count) { ((unsigned char *)data)[0] = 42; return 1; }
  return 0;
}
static int failure_error(FILE *file) { return inject_read_error ? 1 : ferror(file); }
#define fread failure_read
#define ferror failure_error
#include "../src/cache.c"
#undef fread
#undef ferror

static unsigned descriptor_count(void) {
  DIR *directory = opendir("/proc/self/fd");
  assert(directory);
  unsigned count = 0;
  while (readdir(directory)) ++count;
  closedir(directory);
  return count;
}

int main(void) {
  unsigned before = descriptor_count();
  assert(!copy_file("/tmp", "build/cache-failure-output"));
  assert(descriptor_count() == before);
  inject_read_error = 1;
  assert(hash_file(UINT64_C(1469598103934665603), "tests/cache-failure.c") == 0);
  assert(injected_reads == 1);
  injected_reads = 0;
  assert(!copy_file("tests/cache-failure.c", "build/cache-failure-output"));
  assert(injected_reads == 1);
  inject_read_error = 0;
  DynSources sources = {0};
  DynOptions options = {.target = "x86_64-linux"};
  // The cache is optional: a missing parent directory must not dereference FILE* NULL.
  fast_store(&sources, &options, "build/dyn", "/dev/null/dyn-cache-test");
  return 0;
}
