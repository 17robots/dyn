#define _POSIX_C_SOURCE 200809L
#include "../../src/dyn_compact.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <tree_sitter/api.h>
static unsigned allocations,fail_at;
static void *test_malloc(size_t n) { return ++allocations==fail_at ? NULL : malloc(n); }
static void *test_calloc(size_t n,size_t m) { return ++allocations==fail_at ? NULL : calloc(n,m); }
static void *test_realloc(void *p,size_t n) { return ++allocations==fail_at ? NULL : realloc(p,n); }
#define malloc test_malloc
#define calloc test_calloc
#define realloc test_realloc
#include "parser.c"
#include "snapshot.c"
#undef malloc
#undef calloc
#undef realloc
static DynSource source(const char *text) {
  return (DynSource){.path=strdup("main.dyn"),.text=strdup(text),.length=strlen(text)};
}
int main(int argc,char **argv) {
  for(int i=1;i<argc;++i) {
    FILE *f=fopen(argv[i],"rb");assert(f);assert(!fseek(f,0,SEEK_END));long n=ftell(f);assert(n>=0);rewind(f);
    DynSource input={.path=strdup(argv[i]),.text=malloc((size_t)n+1),.length=(size_t)n};
    assert(input.text && fread(input.text,1,(size_t)n,f)==(size_t)n);fclose(f);input.text[n]=0;
    assert(dyn_source_prepare(&input) && input.syntax && !input.compact_validated);
    assert(ts_node_has_error(ts_tree_root_node(input.syntax)));
    DynSources sources={.items=&input,.count=1};DynSource merged;
    assert(!dyn_sources_merge(&sources,input.path,&merged));
    assert(merged.maps[0].original_length==input.length &&
           !memcmp(merged.maps[0].original_text,input.text,input.length));
    const char *path;unsigned line,column;
    dyn_source_location(&merged,merged.maps[0].end,&path,&line,&column);
    dyn_source_free(&merged);dyn_source_free(&input);
  }
  const char *valid="use \"dep\" fn main(){_=1+2}";
  /* Embedded NUL in comment text differs between the compact scanner and TS.
     Keep the entire byte revision on the legacy validation path. */
  static const char nul[]="fn main(){//comment\0\n_=1}\n";
  DynSource s={.path=strdup("main.dyn"),.text=malloc(sizeof(nul)),.length=sizeof(nul)-1};
  memcpy(s.text,nul,sizeof(nul));
  assert(dyn_source_prepare(&s) && s.syntax && !s.compact_validated);
  dyn_source_free(&s);
  s=source("fn main(){_=\"a//x\"}");
  assert(dyn_source_prepare(&s) && s.syntax && !s.compact_validated && !ts_node_has_error(ts_tree_root_node(s.syntax)));
  dyn_source_free(&s);
  s=source(valid);allocations=0;
  assert(dyn_source_prepare(&s) && s.compact_validated && !s.syntax);
  unsigned count=allocations;
  TSTree *bridge=dyn_source_tree(&s);assert(bridge && !ts_node_has_error(ts_tree_root_node(bridge)));
  ts_tree_delete(bridge);assert(!s.syntax);
  dyn_source_discard_syntax(&s);assert(!s.compact && !s.compact_validated && !s.compact_only);
  free(s.text);s.text=strdup("fn main( {");s.length=strlen(s.text);
  assert(dyn_source_prepare(&s) && s.syntax && !s.compact_validated);
  assert(ts_node_has_error(ts_tree_root_node(s.syntax)));dyn_source_free(&s);
  for(unsigned failure=1;failure<=count;++failure) {
    s=source(valid);allocations=0;fail_at=failure;
    assert(!dyn_source_prepare(&s));assert(!s.syntax && !s.compact_validated);
    fail_at=0;dyn_source_free(&s);
  }
  s=source(valid);DynWork work={.remaining=UINT64_MAX};s.context.work=&work;
  assert(dyn_source_prepare(&s) && s.syntax && !s.compact_validated);dyn_source_free(&s);
  s=source(valid);work=(DynWork){.status=DYN_WORK_CANCELLED};s.context.work=&work;
  assert(!dyn_source_prepare(&s) && !s.compact_validated);dyn_source_free(&s);
  DynSyntaxCache cache={0};s=source(valid);s.context.syntax_cache=&cache;
  assert(dyn_source_prepare(&s) && s.syntax && !s.compact_validated);
  dyn_source_free(&s);dyn_syntax_cache_clear(&cache);
  char deep[6000]="type T=";size_t at=strlen(deep);
  for(unsigned i=0;i<300;++i) deep[at++]='*';
  strcpy(deep+at,"u8");
  s=source(deep);assert(dyn_source_prepare(&s) && !s.syntax && s.compact_validated);dyn_source_free(&s);
  strcpy(deep,"const x:=1");at=strlen(deep);
  for(unsigned i=0;i<1100;++i) {deep[at++]='+';deep[at++]='1';}deep[at]=0;
  s=source(deep);assert(!dyn_source_prepare(&s) && s.syntax_too_deep && !s.compact_validated && !s.compact);
  dyn_source_discard_syntax(&s);free(s.text);s.text=strdup(valid);s.length=strlen(valid);
  allocations=0;fail_at=1;
  assert(!dyn_source_prepare(&s) && !s.syntax_too_deep && !s.syntax);
  fail_at=0;assert(dyn_source_prepare(&s) && !s.syntax_too_deep && s.compact_validated);
  dyn_source_free(&s);
  /* Batch commands never fall back: NUL, legacy string cases and budgets use
     the compact tree; errors and excess depth are reported without Tree-sitter. */
  s=(DynSource){.path=strdup("main.dyn"),.text=malloc(sizeof(nul)),.length=sizeof(nul)-1};
  memcpy(s.text,nul,sizeof(nul));s.context.strict_syntax=true;
  assert(!dyn_source_prepare(&s) && !s.syntax && s.syntax_error && s.syntax_error_offset==19);
  dyn_source_free(&s);
  s=source("fn main(){_=\"a//x\"}");s.context.strict_syntax=true;
  assert(dyn_source_prepare(&s) && !s.syntax && s.compact_validated);dyn_source_free(&s);
  s=source(valid);work=(DynWork){.remaining=UINT64_MAX};s.context.work=&work;s.context.strict_syntax=true;
  assert(dyn_source_prepare(&s) && !s.syntax && s.compact_validated);dyn_source_free(&s);
  s=source(valid);work=(DynWork){.status=DYN_WORK_CANCELLED};s.context.work=&work;s.context.strict_syntax=true;
  assert(!dyn_source_prepare(&s) && !s.syntax && !s.compact_validated && !s.syntax_error);dyn_source_free(&s);
  s=source("fn main( {");s.context.strict_syntax=true;
  assert(!dyn_source_prepare(&s) && !s.syntax && s.syntax_error && s.syntax_error_offset==9);dyn_source_free(&s);
  s=source(deep);s.context.strict_syntax=true;
  assert(!dyn_source_prepare(&s) && !s.syntax && s.syntax_too_deep && !s.compact);dyn_source_free(&s);
  return 0;
}
