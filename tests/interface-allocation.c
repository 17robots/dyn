#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "../src/dyn.h"

/* Only the included compiler unit is intercepted; parser allocations are independent. */
static struct { void *pointer; size_t size; } allocations[64];
static size_t calls, fail_at, live;
static void *checked_malloc(size_t size) {
  if (++calls == fail_at) return NULL;
  void *p = malloc(size ? size : 1);
  assert(p);
  for (size_t i = 0; i < 64; ++i) if (!allocations[i].pointer) {
    allocations[i].pointer = p; allocations[i].size = size; ++live; return p;
  }
  abort();
}
static void checked_free(void *p) {
  if (!p) return;
  for (size_t i = 0; i < 64; ++i) if (allocations[i].pointer == p) {
    allocations[i].pointer = NULL; --live; free(p); return;
  }
  assert(!"free of stale allocation");
}
static void *checked_realloc(void *p, size_t size) {
  size_t old_size = 0;
  if (p) {
    size_t i = 0;
    while (i < 64 && allocations[i].pointer != p) ++i;
    assert(i < 64); old_size = allocations[i].size;
  }
  void *next = checked_malloc(size);
  if (!next) return NULL;
  if (p) memcpy(next, p, old_size < size ? old_size : size);
  checked_free(p);
  return next;
}
#ifdef TEST_MODULE
static char *checked_strdup(const char *s) {
  size_t n = strlen(s) + 1;
  char *p = checked_malloc(n);
  if (p) memcpy(p, s, n);
  return p;
}
#define strdup checked_strdup
#endif
#define malloc checked_malloc
#define realloc checked_realloc
#define free checked_free
#ifdef TEST_MODULE
#include "../src/module.c"
#else
#include "../src/interface.c"
#endif
#undef malloc
#undef realloc
#undef free

int dyn_source_target_enabled(const DynSource *source) { (void)source; return 1; }
int dyn_sources_merge(const DynSources *sources, const char *name, DynSource *out) {
  (void)sources; (void)name; (void)out; return 1;
}
int main(void) {
  char text[] = "pub fn first() {}\npub fn second() {}\npub value: i32 = 1\npub type Count = i32\n";
  DynSource source = {.path = "test.dyn", .text = text, .length = strlen(text)};
  DynSources sources = {.items = &source, .count = 1};
  size_t total = 0;
  for (fail_at = 0; fail_at <= total; ++fail_at) {
    calls = 0;
#ifdef TEST_MODULE
    Resolver resolver = {0};
    int status = extract_interface(&resolver, ".", &sources);
    if (!fail_at) { assert(status == 0); total = calls; }
    if (status) assert(resolver.interface_count == 0);
    for (size_t i = 0; i < resolver.interface_count; ++i)
      free_interface(&resolver.interfaces[i]);
    checked_free(resolver.interfaces);
#else
    DynInterface value;
    int status = dyn_interface_build(&sources, &value);
    if (!fail_at) { assert(status == 0); total = calls; }
    if (status) assert(!value.data && !value.length);
    dyn_interface_free(&value);
#endif
    assert(live == 0);
  }
  puts("interface allocation failure cleanup passed");
}
