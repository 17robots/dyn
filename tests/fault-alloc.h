#ifndef DYN_TEST_FAULT_ALLOC_H
#define DYN_TEST_FAULT_ALLOC_H
#include <stdbool.h>
#include <stdlib.h>
void *__real_malloc(size_t);
void *__real_calloc(size_t, size_t);
void *__real_realloc(void *, size_t);
char *__real_strdup(const char *);
char *__real_strndup(const char *, size_t);
static size_t calls, fail_at, failed;
static bool fail(void) { if (++calls == fail_at) { ++failed; return true; } return false; }
void *__wrap_malloc(size_t n) { return fail() ? NULL : __real_malloc(n); }
void *__wrap_calloc(size_t n, size_t size) { return n && size && fail() ? NULL : __real_calloc(n, size); }
void *__wrap_realloc(void *p, size_t n) { return fail() ? NULL : __real_realloc(p, n); }
char *__wrap_strdup(const char *p) { return fail() ? NULL : __real_strdup(p); }

char *__wrap_strndup(const char *p, size_t n) { return fail() ? NULL : __real_strndup(p, n); }

#endif
