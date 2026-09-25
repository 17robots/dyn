#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static unsigned copies, fail_copy, live;
static void *strings[2];
static char *rewrite_test_copy(const char *text) {
  if (++copies == fail_copy) return NULL;
  char *copy = strdup(text);
  assert(copy);
  strings[live++] = copy;
  return copy;
}
static void rewrite_test_free(void *pointer) {
  for (unsigned i = 0; i < live; ++i) if (strings[i] == pointer) { strings[i] = strings[--live]; break; }
  free(pointer);
}
#define strdup rewrite_test_copy
#define free rewrite_test_free
#include "../compiler/src/module_rewrite.c"
#undef strdup
#undef free
int main(void) {
  for (fail_copy = 1; fail_copy <= 2; ++fail_copy) {
    copies = 0;
    Module module = {0};
    assert(!add_alias(&module, "alias", "target"));
    assert(module.alias_count == 0);
    free(module.aliases);
    assert(live == 0);
  }
  return 0;
}
