#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "dyn_scope.h"
#include "fault-alloc.h"

static bool named(const ExpSnapshotTree *t, uint32_t id, const DynSource *s, const char *name) {
  return id != UINT32_MAX && t->nodes[id].kind == EXP_NAME &&
         t->nodes[id].end - t->nodes[id].start == strlen(name) &&
         !memcmp(s->text + t->nodes[id].start, name, strlen(name));
}
/* Independent oracle: walk ancestors of a use, as the editor once did. */
static bool ancestor_local(const ExpSnapshotTree *t, uint32_t use, const DynSource *s, const char *name) {
  const ExpNode *n = t->nodes;
  uint32_t child = use;
  for (uint32_t scope = n[child].parent; scope != UINT32_MAX; child = scope, scope = n[scope].parent) {
    unsigned kind = n[scope].kind;
    if (kind == SRC_BLOCK) {
      for (uint32_t d = n[scope].first; d != UINT32_MAX; d = n[d].next) {
        if (n[d].end > n[child].start) break;
        uint32_t v = d;
        while (v != UINT32_MAX && n[v].kind == SRC_CONST) v = n[v].first;
        if (v != UINT32_MAX && n[v].kind == SRC_VARIABLE && named(t, n[v].first, s, name)) return true;
      }
    } else if (kind == SRC_FN) {
      for (uint32_t p = n[scope].first; p != UINT32_MAX; p = n[p].next)
        if (n[p].kind == SRC_FN_PARAM || n[p].kind == SRC_VARIADIC_PARAM)
          for (uint32_t id = n[p].first; id != UINT32_MAX; id = n[id].next)
            if (named(t, id, s, name)) return true;
      break;
    } else if (kind == SRC_FOR && n[child].kind == SRC_BLOCK) {
      for (uint32_t c = n[scope].first; c != UINT32_MAX; c = n[c].next)
        if (n[c].kind == SRC_FOR_CONDITION && (n[c].flags & EXP_ITERATION) && named(t, n[c].first, s, name))
          return true;
    } else if (kind == SRC_CASE_ARM && n[child].kind == SRC_BLOCK) {
      for (uint32_t b = n[scope].first; b != UINT32_MAX; b = n[b].next) {
        uint32_t binding = b;
        if (n[b].kind == SRC_TYPE_PATTERN)
          for (binding = n[b].first; binding != UINT32_MAX && n[binding].next != UINT32_MAX; binding = n[binding].next) {}
        if (named(t, binding, s, name)) return true;
      }
    }
  }
  return false;
}
static void compare(const DynSource *source, const DynScopeIndex *index) {
  const char *names[] = {"m", "value", "values", "item", "constant", "helper", "local", "absent"};
  const ExpSnapshotTree *t = dyn_compact_tree(source);
  for (uint32_t id = 0; id < t->count; ++id) {
    if (t->nodes[id].kind != EXP_NAME && t->nodes[id].kind != EXP_FIELD_TYPE) continue;
    if (id != t->root && t->nodes[id].parent == UINT32_MAX) continue;
    for (size_t i = 0; i < sizeof(names)/sizeof(names[0]); ++i) {
      bool expected = ancestor_local(t, id, source, names[i]);
      bool actual = dyn_scope_local_at(index, t->nodes[id].start, names[i]);
      if (actual != expected) {
        fprintf(stderr, "scope mismatch at byte %u, name %s: %d != %d\n%s\n",
                t->nodes[id].start, names[i], actual, expected, source->text);
        abort();
      }
    }
  }
}
int main(void) {
  const char *cases[] = {
    "use \"./m\" m\nfn helper(m: i32, values: ...i32) { _ = m\n _ = values }\nfn main() { m.call() }",
    "fn main() { _ = m.call()\n m := m.call()\n _ = m.value\n if true { local := m\n _ = local }\n _ = local }",
    "fn main() { const constant := 1\n _ = constant\n if true { m := constant\n _ = m.value }\n _ = m.value }",
    "fn helper(values: []i32) { for item in values { _ = item\n _ = values }\n _ = item }",
    "fn helper(values: []i32) { for *item in values { _ = item }\n _ = item }",
    "fn helper(value: any) { case value { is i32 item => { _ = item } _ => { _ = item } }\n _ = item }",
    "enum Choice { Item: i32, None } fn helper(value: Choice) { case value { Choice.Item item => { _ = item } Choice.None => {} } }",
    "// 😀\nfn helper(m: i32) { /* comment */ _ = m }",
    "fn helper(m: i32) { _ = m\n x := )\n _ = m }", // Recovered statements bind nothing.
    "fn main() { // comments do not define locals\n m := 1 // next use\n _ = #sizeof(m)\n _ = #typeof(m) }",
    "fn helper(m: i32) { if true { value := 1\n _ = value }\n if true { _ = value } }\nfn main() { _ = m }"
  };
  for (size_t c = 0; c < sizeof(cases)/sizeof(cases[0]); ++c) {
    DynSource source = {.text = (char *)cases[c], .length = strlen(cases[c])};
    assert(dyn_source_prepare(&source));
    if (c != 8 && dyn_compact_tree(&source)->error_count) { fprintf(stderr, "invalid fixture %zu: %s\n", c, source.text); abort(); }
    size_t total = 0;
    for (size_t failure = 0; !failure || failure <= total; ++failure) {
      DynScopeIndex index = {0}; calls = failed = 0; fail_at = failure;
      bool built = dyn_scope_build(&index, &source);
      fail_at = 0;
      if (!failure) { assert(built); total = calls; compare(&source, &index); }
      else { assert(failed && !built); assert(!index.items && !index.count); }
      dyn_scope_free(&index);
    }
    dyn_source_discard_syntax(&source);
  }
  // Many disjoint intervals for one name must not leak visibility between them.
  char text[65536] = "fn main() {\n";
  for (unsigned i = 0; i < 256; ++i) strcat(text, "if true { m := 1\n _ = m.value }\n _ = m.value\n");
  strcat(text, "}\n");
  DynSource source = {.text = text, .length = strlen(text)};
  assert(dyn_source_prepare(&source) && !dyn_compact_tree(&source)->error_count);
  size_t total = 0;
  for (size_t failure = 0; !failure || failure <= total; ++failure) {
    DynScopeIndex index = {0}; calls = failed = 0; fail_at = failure;
    bool built = dyn_scope_build(&index, &source);
    fail_at = 0;
    if (!failure) { assert(built); total = calls; compare(&source, &index); }
    else assert(failed && !built && !index.items && !index.count);
    dyn_scope_free(&index);
  }
  dyn_source_discard_syntax(&source);
  puts("PASS indexed/ancestor scope equivalence, recovered statements, disjoint scopes and allocation failures");
}
