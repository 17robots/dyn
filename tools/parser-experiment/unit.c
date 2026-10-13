#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
static unsigned allocations, fail_at;
static void *allocate(void *pointer, size_t size) {
  if (++allocations == fail_at) return NULL;
  return realloc(pointer, size);
}
#define realloc allocate
#include "parser.c"
#undef realloc

int main(void) {
  char source[8192]; size_t length = 0;
  for (unsigned i = 0; i < 500; ++i) {
    memcpy(source + length, i ? "+a*b" : "a*b", i ? 4 : 3);
    length += i ? 4 : 3;
  }
  ExpTree tree = {0};
  assert(exp_parse(source, length, &tree));
  unsigned total = allocations;
  assert(total > 1 && tree.count == 1999);
  exp_free(&tree);
  for (unsigned i = 1; i <= total; ++i) {
    allocations = 0; fail_at = i;
    assert(!exp_parse(source, length, &tree));
    assert(!strcmp(tree.error, "out of memory") && tree.root == NONE);
    fail_at = 0;
    assert(exp_parse("x", 1, &tree));
    assert(tree.count == 1 && !tree.error);
    exp_free(&tree);
  }
  const char *invalid[] = {"a+", "f(a,", "a[..", "\"\\x\"", "\"\xf0\x80\x80\x80\"", "\"\xed\xa0\x80\""};
  for (size_t i = 0; i < sizeof(invalid)/sizeof(*invalid); ++i) {
    assert(!exp_parse(invalid[i], strlen(invalid[i]), &tree));
    assert(tree.root == NONE && tree.error_offset <= strlen(invalid[i]));
    assert(exp_parse("f(x)[..].*", 10, &tree));
  }
  assert(!exp_parse("a\0b", 3, &tree));
  assert(!exp_parse(NULL, 0, &tree));
  exp_free(&tree);
  puts("PASS parser ownership, allocation failures, bounded reads and reuse");
}
