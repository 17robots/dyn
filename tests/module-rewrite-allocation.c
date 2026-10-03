#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned copies, fail_copy, live, allocations, fail_allocation;
static void *strings[256];
static void *rewrite_test_calloc(size_t count, size_t size) {
  return ++allocations == fail_allocation ? NULL : calloc(count, size);
}
static void *rewrite_test_realloc(void *pointer, size_t size) {
  return ++allocations == fail_allocation ? NULL : realloc(pointer, size);
}
static char *rewrite_test_copy(const char *text) {
  ++copies;
  ++allocations;
  if (copies == fail_copy || allocations == fail_allocation) return NULL;
  char *copy = strdup(text);
  assert(copy);
  assert(live < sizeof(strings) / sizeof(*strings));
  strings[live++] = copy;
  return copy;
}
static void rewrite_test_free(void *pointer) {
  for (unsigned i = 0; i < live; ++i)
    if (strings[i] == pointer) {
      strings[i] = strings[--live];
      break;
    }
  free(pointer);
}
#define calloc rewrite_test_calloc
#define realloc rewrite_test_realloc
#define strdup rewrite_test_copy
#define free rewrite_test_free
#include "../src/module_rewrite.c"
#undef calloc
#undef realloc
#undef strdup
#undef free

static unsigned declaration_index(unsigned failure) {
  Module *module = calloc(1, sizeof(*module));
  assert(module);
  allocations = copies = 0;
  fail_copy = 0;
  fail_allocation = failure;
  bool failed = false;
  assert(!has_decl(module, "missing"));
  for (unsigned i = 0; i < 160; ++i) {
    char name[64];
    snprintf(name, sizeof(name), "same_prefix_%u", i);
    if (!add_decl(module, name)) {
      assert(failure && allocations == failure);
      assert(module->decl_count == i);
      assert(!has_decl(module, name));
      /* A failed growth or name copy leaves the index usable for retry. */
      fail_allocation = 0;
      assert(add_decl(module, name));
      assert(has_decl(module, name));
      failed = true;
      break;
    }
    assert(has_decl(module, name));
    unsigned before = allocations;
    assert(add_decl(module, name));
    assert(allocations == before);
    assert(module->decl_count == i + 1);
  }
  assert(failed == (failure != 0));
  for (size_t i = 0; i < module->decl_count; ++i) {
    char name[64];
    snprintf(name, sizeof(name), "same_prefix_%zu", i);
    assert(has_decl(module, name));
  }
  assert(!has_decl(module, "absent"));
  unsigned count = allocations;
  free_modules(module, 1);
  assert(live == 0);
  return count;
}

int main(void) {
  for (fail_copy = 1; fail_copy <= 2; ++fail_copy) {
    copies = 0;
    Module module = {0};
    assert(!add_alias(&module, "alias", "target"));
    assert(module.alias_count == 0);
    free(module.aliases);
    assert(live == 0);
  }
  unsigned count = declaration_index(0);
  for (unsigned failure = 1; failure <= count; ++failure)
    declaration_index(failure);
  return 0;
}
