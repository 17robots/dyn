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

static void allocation_failures(const char *source, bool (*parse)(const char *, size_t, ExpTree *)) {
  ExpTree tree = {0};
  allocations = 0; fail_at = 0;
  assert(parse(source, strlen(source), &tree));
  unsigned total = allocations;
  exp_free(&tree);
  for (unsigned i = 1; i <= total; ++i) {
    allocations = 0; fail_at = i;
    assert(!parse(source, strlen(source), &tree));
    assert(tree.root == NONE && !strcmp(tree.error, "out of memory"));
    assert(tree.error_kind == EXP_ALLOCATION_ERROR);
    fail_at = 0;
    assert(parse(source, strlen(source), &tree));
    assert(!tree.error);
    exp_free(&tree);
  }
}
typedef struct { unsigned calls, stop; } WorkProbe;
static bool probe_work(void *data, uint64_t units) {
  WorkProbe *probe = data;
  (void)units;
  return ++probe->calls != probe->stop;
}
static void cancellation(const char *source, bool complete) {
  ExpTree tree = {0};
  WorkProbe probe = {0};
  ExpOptions options = {.work = probe_work, .data = &probe};
  bool (*parse)(const char *, size_t, ExpTree *, const ExpOptions *) =
      complete ? exp_parse_source_with_options : exp_parse_with_options;
  size_t length = strlen(source);
  assert(parse(source, length, &tree, &options));
  unsigned calls = probe.calls;
  assert(calls > 2);
  for (unsigned stop = 1; stop <= calls; ++stop) {
    probe = (WorkProbe){.stop = stop};
    if (parse(source, length, &tree, &options)) { fprintf(stderr, "missed cancellation stop=%u calls=%u source=%.80s\n", stop, probe.calls, source); abort(); }
    if (probe.calls != stop || tree.error_kind != EXP_CANCELLED) { fprintf(stderr, "cancel contract stop=%u calls=%u error=%u source=%.80s\n", stop, probe.calls, tree.error_kind, source); abort(); }
    assert(tree.root == NONE && tree.error_offset <= length);
    assert(parse(source, length, &tree, NULL));
    assert(tree.error_kind == EXP_OK);
  }
  exp_free(&tree);
}
static void options_contract(void) {
  cancellation("a", false);
  cancellation("#sizeof([1]*u8)+f([1,2],#typeof(a+b))", false);
  cancellation("fn f(){x:=1}", true);
  cancellation("fn f(){ if foo(x){ return Point{x:1} } for i in 0..=3 { foo(i) } }", true);
  /* UTF-8 and escapes can skip exact 1024-byte offsets. */
  char large[16390];
  large[0] = '"';
  for (unsigned i = 1; i < 16385; i += 4) memcpy(large + i, "\xf0\x9f\x98\x80", 4);
  large[16385] = '"'; large[16386] = 0;
  cancellation(large, false);
  for (unsigned i = 1; i < 16385; i += 4) memcpy(large + i, "\\x61", 4);
  cancellation(large, false);
  memset(large, 'a', 16384); large[16384] = 0;
  cancellation(large, false);
  large[0] = '/'; large[1] = '/';
  cancellation(large, true);
  memset(large, ' ', 16384);
  cancellation(large, true);
  memcpy(large, "#sizeof([1/*", 12);
  memset(large + 12, 'a', 16000);
  memcpy(large + 16012, "*/]u8)", 7);
  cancellation(large, false);
  ExpTree tree = {0};
  ExpOptions options = {.max_work = 1};
  assert(!exp_parse_with_options("a+b", 3, &tree, &options));
  assert(tree.root == NONE && tree.error_kind == EXP_LIMIT_ERROR);
  options = (ExpOptions){.max_depth = 2};
  assert(!exp_parse_with_options("(((a)))", 7, &tree, &options));
  assert(tree.root == NONE && tree.error_kind == EXP_LIMIT_ERROR);
  assert(exp_parse("a", 1, &tree) && tree.error_kind == EXP_OK);
  assert(!exp_parse("a+", 2, &tree) && tree.error_kind == EXP_SYNTAX_ERROR);
  assert(!exp_parse(NULL, 1, &tree) && tree.error_kind == EXP_LIMIT_ERROR);
  exp_free(&tree);
}
int main(void) {
  options_contract();
  allocations = 0; fail_at = 0;
  char source[16384]; size_t length = 0;
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
    uint32_t error_offset = tree.error_offset;
    const char *error = tree.error;
    assert(!exp_parse(invalid[i], strlen(invalid[i]), &tree));
    assert(tree.error_offset == error_offset && !strcmp(tree.error, error));
    assert(exp_parse("f(x)[..].*", 10, &tree));
  }
  assert(!exp_parse("a\0b", 3, &tree));
  assert(!exp_parse(NULL, 0, &tree));
  exp_free(&tree);
  allocation_failures("#cast(*fn([]const u8,[4]i32)*m.T)f($T,Point{x:[1,2,3],y:#sizeof(a+b)})", exp_parse);
  allocation_failures("f([1,2,3],#sizeof([1,2]),#typeof(a+b),[4]*const m.T)", exp_parse);
  allocation_failures("use \"dep\" d pub struct S {x:i32} pub fn f($T:any,x:T) T { if true { return x } else { return x } }", exp_parse_source);
  allocation_failures("#target(os:linux) #link(\"c\") extern fn puts(x:*const u8)i32 fn f() { for i in 0..10 { defer foo() } }", exp_parse_source);
  const char *bad_sources[] = {"fn", "fn f(){", "struct S{x:", "use", "fn f(){if x{", "fn f(){return #cast()}"};
  for (size_t i = 0; i < sizeof(bad_sources) / sizeof(*bad_sources); ++i) {
    assert(!exp_parse_source(bad_sources[i], strlen(bad_sources[i]), &tree));
    assert(tree.root == NONE && tree.error_offset <= strlen(bad_sources[i]));
    assert(exp_parse_source("fn f(){}", 8, &tree));
  }
  exp_free(&tree);
  /* Parser-call depth and tree depth are distinct: chains parse iteratively. */
  size_t chain_length = 40001;
  char *chain = malloc(chain_length);
  assert(chain);
  for (size_t i = 0; i < chain_length; ++i) chain[i] = i % 2 ? '+' : 'a';
  assert(exp_parse(chain, chain_length, &tree));
  assert(tree.count == chain_length);
  free(chain); exp_free(&tree);
  memset(source, '(', 1100); source[1100] = 'a'; memset(source + 1101, ')', 1100);
  assert(!exp_parse(source, 2201, &tree));
  assert(tree.root == NONE && !strcmp(tree.error, "expression nesting limit exceeded"));
  assert(exp_parse("a", 1, &tree));
  exp_free(&tree);
  /* Exhaustion must survive speculative type/condition rollback. */
  uint64_t remaining = 3;
  tree.root = NONE;
  Parser limited = {.text = "#sizeof([1]*u8)", .length = 15, .tree = &tree,
                    .work_remaining = &remaining};
  lex(&limited);
  assert(expression(&limited, 0) == NONE);
  assert(!remaining && !strcmp(tree.error, "parse work limit exceeded"));
  assert(tree.root == NONE);
  assert(exp_parse_source("fn f(){}", 8, &tree));
  exp_free(&tree);
  length = 0;
  memcpy(source, "fn f(){", 7); length = 7;
  for (unsigned i = 0; i < 1100; ++i) { memcpy(source + length, "if true{", 8); length += 8; }
  memset(source + length, '}', 1101); length += 1101;
  assert(!exp_parse_source(source, length, &tree));
  assert(tree.root == NONE && tree.error_offset <= length);
  assert(strstr(tree.error, "nesting limit exceeded"));
  exp_free(&tree);
  const char *metadata = "use \"a\" mod #link(\"c\") pub packed struct S{x:i32} distinct type T=i32 "
      "extern fn f \"c_f\"(...) *fn(i32)u8 fn g(p:*const T,x:[]const T){"
      "for *const v in x{v.* = 1} case p{_=>{}} foo($T,#bitcast(u64)p) }";
  cancellation(metadata, true);
  assert(exp_parse_source(metadata, strlen(metadata), &tree));
  assert(tree.nodes[tree.root].parent == NONE);
  unsigned flags = 0, fields = 0;
  for (uint32_t i = 0; i < tree.count; ++i) {
    ExpNode *n = &tree.nodes[i];
    if (i != tree.root && n->parent == NONE) continue;
    flags |= n->flags; fields |= 1u << n->field;
    for (uint32_t child = n->first; child != NONE; child = tree.nodes[child].next)
      assert(tree.nodes[child].parent == i);
  }
  assert((flags & (EXP_CONST|EXP_PUBLIC|EXP_PACKED|EXP_DISTINCT|EXP_POINTER_BINDING|EXP_ITERATION|EXP_PRIMARY|EXP_BITCAST|EXP_WILDCARD)) ==
      (EXP_CONST|EXP_PUBLIC|EXP_PACKED|EXP_DISTINCT|EXP_POINTER_BINDING|EXP_ITERATION|EXP_PRIMARY|EXP_BITCAST|EXP_WILDCARD));
  assert((fields & ((1u<<EXP_ROLE_PATH)|(1u<<EXP_ROLE_ALIAS)|(1u<<EXP_ROLE_LIBRARY)|(1u<<EXP_ROLE_NAME)|(1u<<EXP_ROLE_LINK_NAME)|(1u<<EXP_ROLE_RETURN)|(1u<<EXP_ROLE_CALL_ARGS))) ==
      ((1u<<EXP_ROLE_PATH)|(1u<<EXP_ROLE_ALIAS)|(1u<<EXP_ROLE_LIBRARY)|(1u<<EXP_ROLE_NAME)|(1u<<EXP_ROLE_LINK_NAME)|(1u<<EXP_ROLE_RETURN)|(1u<<EXP_ROLE_CALL_ARGS)));
  exp_free(&tree);
  puts("PASS parser metadata, ownership, allocation failures, cancellation, work/depth limits and reuse");
}
