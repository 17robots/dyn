#define _POSIX_C_SOURCE 200809L
#include "../../src/dyn.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned allocations, fail_at, compared, skipped;
static void *scope_realloc(void *p, size_t n) {
  return ++allocations == fail_at ? NULL : realloc(p, n);
}
#define realloc scope_realloc
#include "../../src/dyn_scope.h"
#undef realloc

static void compare(const char *text, bool required) {
  DynSource source = {.path=strdup("scope.dyn"), .text=strdup(text), .length=strlen(text)};
  assert(source.path && source.text && dyn_source_prepare(&source));
  if (!source.compact) { assert(!required); ++skipped; dyn_source_free(&source); return; }
  ++compared;
  DynScopeIndex expected, actual;
  TSNode root = ts_tree_root_node(source.syntax);
  struct ExpSnapshot *snapshot = source.compact;
  source.compact = NULL;
  assert(dyn_scope_build(&expected, root, &source));
  source.compact = snapshot;
  allocations = 0;
  DynWork work = {.remaining=UINT64_MAX};
  source.context.work = &work;
  assert(dyn_scope_build(&actual, (TSNode){0}, &source));
  uint64_t used = UINT64_MAX-work.remaining;
  source.context.work = NULL;
  unsigned total = allocations;
  assert(!actual.recovery && expected.count == actual.count);
  for (size_t i = 0; i < actual.count; ++i) {
    DynScopeBinding a=expected.items[i], b=actual.items[i];
    if (a.length != b.length || memcmp(a.name,b.name,a.length) ||
        a.start != b.start || a.end != b.end || a.prefix_end != b.prefix_end) {
      fprintf(stderr,"scope mismatch: %.*s %u:%u vs %.*s %u:%u\n",(int)a.length,a.name,a.start,a.end,
              (int)b.length,b.name,b.start,b.end); abort();
    }
  }
  dyn_scope_free(&actual); dyn_scope_free(&expected);
  for (unsigned n=1;n<=total;++n) {
    allocations=0; fail_at=n;
    assert(!dyn_scope_build(&actual,(TSNode){0},&source));
    assert(!actual.items && !actual.count);
  }
  fail_at=0;
  if (required) for (uint64_t budget=0;budget<used;++budget) {
    work=(DynWork){.remaining=budget}; source.context.work=&work;
    assert(!dyn_scope_build(&actual,(TSNode){0},&source));
    assert(work.status == DYN_WORK_LIMIT && !actual.items && !actual.count);
  }
  source.context.work=NULL;
  dyn_source_free(&source);
}
int main(int argc, char **argv) {
  const char *cases[] = {
    "fn f(a,b:i64,args:...u8) {x:=a const y:=x if true {x:=y _=x} _=x}",
    "fn f(a:i64) {for i in 0..a {_=i} outer:for *const p in a {_=p} for a>0 {a-=1}}",
    "fn f(a:any) {case a {is i64 x=>{_=x},_ other=>{_=other}}}",
    "fn f(a:i64) {case a {0,1 x=>{_=x},2..=4 y=>{_=y},_=>{}}}",
    "fn f(x:i64) {x:=x+1 if true {const x:=x+1 _=x} else {_=x} _=x}",
    "fn f(a:$T) T {return a} fn empty(){}",
    "// leading comment\nfn f(x:i64) { /*inner*/ x:=x _=x }"
  };
  for(size_t i=0;i<sizeof(cases)/sizeof(*cases);++i) compare(cases[i],true);
  for(int i=1;i<argc;++i) {
    FILE *file=fopen(argv[i],"rb"); assert(file);
    assert(!fseek(file,0,SEEK_END)); long length=ftell(file); assert(length>=0);
    rewind(file); char *text=calloc((size_t)length+1,1); assert(text);
    assert(fread(text,1,(size_t)length,file)==(size_t)length); fclose(file);
    compare(text,false); free(text);
  }
  printf("PASS compact scopes: %u compared, %u explicit fallbacks; visibility spans, allocation cleanup, work limits\n", compared, skipped);
}
