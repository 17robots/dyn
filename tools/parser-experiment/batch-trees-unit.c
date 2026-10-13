#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include "ir.h"
#include "frontend.h"
#include "dyn_compact.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>

static void check(const char *text, bool owned, bool snapshot, bool valid, bool released) {
  DynSource source={.path=strdup("main.dyn"),.text=strdup(text),.length=strlen(text)};
  assert(dyn_source_prepare(&source));
  if (!snapshot) { exp_snapshot_release(source.compact); source.compact=NULL; }
  ExpSnapshot *original=source.compact;
  TSTree *survivor=ts_tree_copy(source.syntax);
  DynIrProgram ir;
  int result=owned ? dyn_codegen_prepare_owned(&source,false,NULL,&ir)
                   : dyn_codegen_prepare(&source,false,NULL,&ir);
  assert((result==0)==valid);
  assert((source.syntax==NULL)==released);
  assert(source.compact==original);
  assert(!ts_node_is_null(ts_tree_root_node(survivor)));
  if (!result) dyn_codegen_release(&ir);
  ts_tree_delete(survivor);
  dyn_source_free(&source);
}
static void early_release(void) {
  const char *texts[]={"type Word=i64", "fn main(){x:Word=1 _=#typeof(x)}"};
  DynSource items[2]={0};
  for(unsigned i=0;i<2;++i) {
    items[i]=(DynSource){.path=strdup(i?"main.dyn":"types.dyn"),.text=strdup(texts[i]),.length=strlen(texts[i])};
    assert(dyn_source_prepare(&items[i]));
  }
  DynSources project={.items=items,.count=2};
  DynWork work={.remaining=UINT64_MAX}; items[0].context.work=&work;
  assert(!dyn_ast_release_project_trees(&project) && items[0].syntax && items[1].syntax);
  items[0].context.work=NULL;
  assert(dyn_ast_release_project_trees(&project));
  assert(!items[0].syntax && !items[1].syntax);
  DynSource merged;
  assert(!dyn_sources_merge(&project,"main.dyn",&merged));
  assert(merged.compact_only && merged.syntax_part_count==3);
  for(unsigned i=0;i<3;++i) assert(!merged.syntax_parts[i]);
  DynIrProgram ir; assert(!dyn_codegen_prepare_owned(&merged,false,NULL,&ir));
  dyn_codegen_release(&ir);
  DynAstProgram recovered;
  DynAnalysisResult result=dyn_analyze(&merged,&recovered,(DynAnalysisOptions){.recover=true});
  assert(result.checked && !recovered.compact_complete);
  dyn_ast_program_free(&recovered);
  dyn_source_free(&merged);
  for(unsigned i=0;i<2;++i) dyn_source_free(&items[i]);
  /* One legacy-trivia partition prevents releasing any project tree. */
  const char *fallback[]={"fn main(){}","fn f(){case 1 {0.. /*comment*/ 2=>{},_=>{}}}"};
  for(unsigned i=0;i<2;++i) {
    items[i]=(DynSource){.path=strdup(i?"f.dyn":"main.dyn"),.text=strdup(fallback[i]),.length=strlen(fallback[i])};
    assert(dyn_source_prepare(&items[i]));
  }
  assert(!dyn_ast_release_project_trees(&project));
  for(unsigned i=0;i<2;++i) { assert(items[i].syntax && !items[i].compact_only); dyn_source_free(&items[i]); }
}
int main(void) {
  early_release();
  const char *generic="type Word=i64 fn identity(value:$T) T{return value} fn main(){x:Word=1 _=identity(x)}";
  check(generic,true,true,true,true);
  check(generic,false,true,true,false);
  check(generic,true,false,true,false);
  check("fn main(){case 1 {0.. /*comment*/ 2=>{},_=>{}}}",true,true,true,false);
  check("fn main(){_=missing}",true,true,false,false);
  check("fn main( {",true,true,false,false);
  DynSyntaxCache cache={0};
  DynSource cached={.path=strdup("main.dyn"),.text=strdup("fn main(){}"),.length=11,.context={.syntax_cache=&cache}};
  assert(dyn_source_prepare(&cached));
  TSTree *tree=cached.syntax;
  dyn_source_release_batch_trees(&cached);
  assert(cached.syntax==tree);
  cached.context.syntax_cache=NULL;
  DynWork stopped={.status=DYN_WORK_CANCELLED};
  cached.context.work=&stopped;
  DynIrProgram failed;
  assert(dyn_codegen_prepare_owned(&cached,false,NULL,&failed));
  assert(cached.syntax==tree);
  dyn_source_free(&cached);
  dyn_syntax_cache_clear(&cache);
  return 0;
}
