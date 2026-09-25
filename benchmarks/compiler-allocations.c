#define _POSIX_C_SOURCE 200809L
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* Link-time wrappers count compiler/generated-parser requests. Allocations
   internal to shared LLVM/Tree-sitter/libc libraries are outside this scope. */
void *__real_malloc(size_t);
void *__real_calloc(size_t, size_t);
void *__real_realloc(void *, size_t);
char *__real_strdup(const char *);
char *__real_strndup(const char *, size_t);
static _Atomic uint64_t calls, bytes;
static void record(size_t size) {
  atomic_fetch_add_explicit(&calls, 1, memory_order_relaxed);
  atomic_fetch_add_explicit(&bytes, size, memory_order_relaxed);
}
void *__wrap_malloc(size_t size) { record(size); return __real_malloc(size); }
void *__wrap_calloc(size_t n, size_t size) {
  record(size && n > SIZE_MAX / size ? SIZE_MAX : n * size);
  return __real_calloc(n, size);
}
void *__wrap_realloc(void *p, size_t size) { record(size); return __real_realloc(p, size); }
char *__wrap_strdup(const char *s) { record(strlen(s) + 1); return __real_strdup(s); }
char *__wrap_strndup(const char *s, size_t n) { record(strnlen(s, n) + 1); return __real_strndup(s, n); }
__attribute__((destructor)) static void report(void) {
  if (getenv("DYN_ALLOCATION_STATS"))
    fprintf(stderr, "compiler-allocations calls=%llu requested-bytes=%llu\n",
        (unsigned long long)atomic_load(&calls), (unsigned long long)atomic_load(&bytes));
}
