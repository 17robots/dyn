#define _POSIX_C_SOURCE 200809L
#include "../../src/dyn_imports.h"
#include <assert.h>
#include <stdio.h>
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
static unsigned allocations, fail_at;
static void *test_malloc(size_t n) {
  return ++allocations == fail_at ? NULL : malloc(n);
}
static void *test_calloc(size_t n, size_t size) {
  return ++allocations == fail_at ? NULL : calloc(n, size);
}
static void *test_realloc(void *p, size_t n) {
  return ++allocations == fail_at ? NULL : realloc(p, n);
}
#define malloc test_malloc
#define calloc test_calloc
#define realloc test_realloc
#include "parser.c"
#include "snapshot.c"
#undef malloc
#undef calloc
#undef realloc
#endif

static DynSource source(const char *text) {
  DynSource s = {.path = strdup("fixture/main.dyn"), .text = strdup(text), .length = strlen(text)};
  assert(s.path && s.text && dyn_source_prepare(&s));
  return s;
}
static size_t imports(DynSource *s, DynImportView *items) {
  DynImports reader; assert(dyn_imports_open(&reader, s));
  size_t count = 0; DynImportView item;
  while (dyn_imports_next(&reader, &item)) { assert(count < 16); items[count++] = item; }
  assert(!reader.failed); dyn_imports_close(&reader); return count;
}
static void compare_imports(const char *text, size_t expected) {
  DynSource s = source(text);
  DynImportView a[16], b[16];
  size_t n = imports(&s, a);
  if (n != expected) fprintf(stderr, "imports: expected %zu, got %zu: %s\n", expected, n, text);
  assert(n == expected);
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
  assert(ts_node_has_error(ts_tree_root_node(s.syntax)) ? !s.compact : s.compact != NULL);
  ExpSnapshot *saved = s.compact; s.compact = NULL;
#endif
  assert(imports(&s, b) == n);
  for (size_t i = 0; i < n; ++i) {
    assert(a[i].start == b[i].start && a[i].end == b[i].end);
    assert(a[i].path_node == b[i].path_node && a[i].alias_node == b[i].alias_node);
    assert(a[i].path == b[i].path && a[i].path_length == b[i].path_length);
    assert(a[i].alias == b[i].alias && a[i].alias_length == b[i].alias_length);
  }
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
  s.compact = saved;
#endif
  dyn_source_free(&s);
}
int main(void) {
  static const char nul_text[]="fn main(){} // comment\0\nlast";
  DynSource nul={.path=strdup("nul.dyn"),.text=malloc(sizeof(nul_text)),.length=sizeof(nul_text)-1};
  memcpy(nul.text,nul_text,sizeof(nul_text));assert(dyn_source_prepare(&nul));
  DynSources originals={.items=&nul,.count=1};DynSource merged_nul;
  assert(!dyn_sources_merge(&originals,"nul.dyn",&merged_nul));
  assert(merged_nul.maps[0].original_length==nul.length &&
         !memcmp(merged_nul.maps[0].original_text,nul_text,sizeof(nul_text)));
  const char *nul_path;unsigned nul_line,nul_column;
  dyn_source_location(&merged_nul,merged_nul.maps[0].end,&nul_path,&nul_line,&nul_column);
  assert(nul_line==2 && nul_column==5);
  dyn_source_free(&merged_nul);dyn_source_free(&nul);
  /* The default cursor must handle no imports and declarations before imports. */
  compare_imports("", 0);
  compare_imports("// only trivia\n", 0);
  compare_imports("fn main(){}", 0);
  compare_imports("fn first(){} use \"a\" x, \"b\" use \"c\" y fn last(){}", 3);
  compare_imports("use /* before */ \"a\" /* between */ x // after\nuse \"b\"", 2);
  compare_imports("fn broken( use \"dep\"", 0);
  DynSource plain = source("// #typeof\nfn f(){s:=\"#typeof\"}");
  bool reflection; assert(dyn_source_reflection(&plain, &reflection) && !reflection);
  dyn_source_free(&plain);
  DynSource reflected = source("const T := #typeof(i32)");
  assert(dyn_source_reflection(&reflected, &reflection) && reflection);
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
  assert(reflected.compact && reflected.compact_reflection);
  ExpSnapshot *retained = reflected.compact; assert(exp_snapshot_retain(retained));
  DynSources inputs = {.items = &reflected, .count = 1};
  DynSource merged; assert(!dyn_sources_merge(&inputs, "merged", &merged));
  assert(merged.syntax_part_count == 2 && merged.compact_parts[0] && merged.compact_parts[1] == retained);
  dyn_source_free(&reflected);
  assert(!strcmp(exp_snapshot_text(retained), "const T := #typeof(i32)"));
  dyn_source_free(&merged); exp_snapshot_release(retained);
  DynSource revision = source("use \"old\" fn f(){}");
  retained = revision.compact; assert(exp_snapshot_retain(retained));
  dyn_source_discard_syntax(&revision); free(revision.text);
  revision.text = strdup("use \"new\" fn g(){}"); revision.length = strlen(revision.text);
  assert(dyn_source_prepare(&revision) && revision.compact != retained);
  assert(strstr(exp_snapshot_text(retained), "old"));
  exp_snapshot_release(retained); dyn_source_free(&revision);
  DynSource fault = {.path = strdup("fault.dyn"), .text = strdup("use \"dep\" fn f(){}")};
  fault.length = strlen(fault.text); fault.syntax = dyn_source_tree(&fault); assert(fault.syntax);
  allocations = 0; assert(dyn_source_prepare(&fault)); unsigned total = allocations;
  assert(total >= 3); exp_snapshot_release(fault.compact); fault.compact = NULL;
  for (unsigned i = 1; i <= total; ++i) {
    allocations = 0; fail_at = i;
    assert(!dyn_source_prepare(&fault) && !fault.compact);
    fail_at = 0;
    assert(dyn_source_prepare(&fault) && fault.compact);
    exp_snapshot_release(fault.compact); fault.compact = NULL;
  }
  DynWork work = {.remaining = 1}; fault.context.work = &work;
  assert(!dyn_source_prepare(&fault) && work.status == DYN_WORK_LIMIT && !fault.compact);
  fault.context.work = NULL; dyn_source_free(&fault);
#else
  dyn_source_free(&reflected);
#endif
  puts("PASS source imports, reflection, revision ownership, merged retention and preparation failures");
}
