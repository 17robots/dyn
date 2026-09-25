#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "dyn_scope.h"
#include "fault-alloc.h"

static void compare(TSNode root, const DynSource *source, const DynScopeIndex *index) {
  const char *names[] = {"m", "value", "values", "item", "constant", "helper", "local", "absent"};
  TSTreeCursor cursor = ts_tree_cursor_new(root);
  bool done = false;
  while (!done) {
    TSNode node = ts_tree_cursor_current_node(&cursor);
    const char *kind = ts_node_type(node);
    if (!strcmp(kind, "identifier") || !strcmp(kind, "field_type"))
      for (size_t i = 0; i < sizeof(names)/sizeof(names[0]); ++i) {
        bool expected = dyn_syntax_local(node, source, names[i]);
        bool actual = dyn_scope_local(index, node, source, names[i]);
        if (actual != expected) {
          fprintf(stderr, "scope mismatch at byte %u (%s), name %s: %d != %d\n%s\n",
                  ts_node_start_byte(node), kind, names[i], actual, expected, source->text);
          abort();
        }
      }
    if (ts_tree_cursor_goto_first_child(&cursor)) continue;
    while (!ts_tree_cursor_goto_next_sibling(&cursor))
      if (!ts_tree_cursor_goto_parent(&cursor)) { done = true; break; }
  }
  ts_tree_cursor_delete(&cursor);
}
int main(void) {
  const char *cases[] = {
    "use \"./m\" m\nfn helper(m: i32, values: ...i32) { _ = m _ = values }\nfn main() { m.call() }",
    "fn main() { _ = m.call() m := m.call() _ = m.value if true { local := m _ = local } _ = local }",
    "fn main() { const constant := 1 _ = constant if true { m := constant _ = m.value } _ = m.value }",
    "fn helper(values: []i32) { for item in values { _ = item _ = values } _ = item }",
    "fn helper(values: []i32) { for *item in values { _ = item } _ = item }",
    "fn helper(value: any) { case value { is i32 item => { _ = item }, _ => { _ = item } } _ = item }",
    "enum Choice { Item: i32, None } fn helper(value: Choice) { case value { Choice.Item item => { _ = item }, Choice.None => {} } }",
    "// 😀\nfn helper(m: i32) { /* unsupported comment for recovery */ _ = m }",
    "fn helper(m: i32) { _ = m", // Recovery keeps the original ancestor query.
    "fn main() { // comments do not define locals\n m := 1 // next use\n _ = #sizeof(m) _ = #typeof(m) }",
    "fn helper(m: i32) { if true { value := 1 _ = value } if true { _ = value } }\nfn main() { _ = m }"
  };
  for (size_t c = 0; c < sizeof(cases)/sizeof(cases[0]); ++c) {
    DynSource source = {.text = (char *)cases[c], .length = strlen(cases[c])};
    TSTree *tree = dyn_syntax_parse(source.text, source.length); assert(tree);
    TSNode root = ts_tree_root_node(tree);
    if (c != 7 && c != 8 && ts_node_has_error(root)) { fprintf(stderr, "invalid fixture %zu: %s\n", c, source.text); abort(); }
    size_t total = 0;
    for (size_t failure = 0; !failure || failure <= total; ++failure) {
      DynScopeIndex index = {0}; calls = failed = 0; fail_at = failure;
      bool built = dyn_scope_build(&index, root, &source);
      fail_at = 0;
      if (!failure) { assert(built); total = calls; compare(root, &source, &index); }
      else { assert(failed && !built); assert(!index.items && !index.count); }
      dyn_scope_free(&index);
    }
    ts_tree_delete(tree);
  }
  // Many disjoint intervals for one name must not leak visibility between them.
  char text[65536] = "fn main() {\n";
  for (unsigned i = 0; i < 256; ++i) strcat(text, "if true { m := 1 _ = m.value } _ = m.value\n");
  strcat(text, "}\n");
  DynSource source = {.text = text, .length = strlen(text)};
  TSTree *tree = dyn_syntax_parse(text, source.length); assert(tree);
  assert(!ts_node_has_error(ts_tree_root_node(tree)));
  size_t total = 0;
  for (size_t failure = 0; !failure || failure <= total; ++failure) {
    DynScopeIndex index = {0}; calls = failed = 0; fail_at = failure;
    bool built = dyn_scope_build(&index, ts_tree_root_node(tree), &source);
    fail_at = 0;
    if (!failure) { assert(built); total = calls; compare(ts_tree_root_node(tree), &source, &index); }
    else assert(failed && !built && !index.items && !index.count);
    dyn_scope_free(&index);
  }
  ts_tree_delete(tree);
  puts("PASS indexed/ancestor scope equivalence, recovery, disjoint scopes and allocation failures");
}
