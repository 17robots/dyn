#define _POSIX_C_SOURCE 200809L
#include <stdlib.h>
#include <string.h>
#include <assert.h>
static size_t allocations, fail_at;
static void *rewrite_malloc(size_t n) { return ++allocations == fail_at ? NULL : malloc(n); }
static void *rewrite_calloc(size_t n,size_t size) { return ++allocations == fail_at ? NULL : calloc(n,size); }
static void *rewrite_realloc(void *p,size_t n) { return ++allocations == fail_at ? NULL : realloc(p,n); }
static char *rewrite_strdup(const char *text) { return ++allocations == fail_at ? NULL : strdup(text); }
#define malloc rewrite_malloc
#define calloc rewrite_calloc
#define realloc rewrite_realloc
#define strdup rewrite_strdup
#include "../../src/module_rewrite.c"
#undef malloc
#undef calloc
#undef realloc
#undef strdup
static void clear_declarations(Module *module) {
  for(size_t i=0;i<module->decl_count;++i) free(module->decls[i].name);
  free(module->decls); free(module->decl_buckets); *module=(Module){0};
}
static void clear_edits(Edits *edits) {
  for(size_t i=0;i<edits->count;++i) free(edits->items[i].text);
  free(edits->items); *edits=(Edits){0};
}
static void normalize(Edits *edits) {
  if(edits->count) qsort(edits->items,edits->count,sizeof(*edits->items),edit_compare);
  size_t count=0;
  for(size_t i=0;i<edits->count;++i) {
    if(count && !edit_compare(&edits->items[count-1],&edits->items[i])) {
      assert(!strcmp(edits->items[count-1].text,edits->items[i].text));
      free(edits->items[i].text);
    } else edits->items[count++]=edits->items[i];
  }
  edits->count=count;
}
static void compare(Module *modules, const char *text, bool root_module, bool resources) {
  DynSource source={.path=strdup("rewrite.dyn"),.text=strdup(text),.length=strlen(text)};
  assert(dyn_source_prepare(&source));
  if(!source.compact) { fprintf(stderr,"missing compact snapshot: %s\n",text); abort(); }
  TSNode root=ts_tree_root_node(source.syntax);
  assert(!ts_node_has_error(root));
  DynScopeIndex scopes={0}; assert(dyn_scope_build(&scopes,root,&source));
  source.original_text=strdup("// original source has different line lengths\n\n");
  source.original_length=strlen(source.original_text);
  source.spans=malloc(sizeof(*source.spans)); assert(source.spans);
  source.spans[0]=(DynSourceSpan){0,source.length,0,source.original_length}; source.span_count=1;
  Module expected_declarations={0},actual_declarations={0};
  for(uint32_t i=0;i<ts_node_named_child_count(root);++i) {
    DynDeclaration declaration;
    if(dyn_syntax_declaration(ts_node_named_child(root,i),&declaration) &&
       !ts_node_is_null(declaration.name)) {
      char *name=dyn_syntax_copy_text(declaration.name,&source,false); assert(name);
      assert(add_decl(&expected_declarations,name)); free(name);
    }
  }
  allocations=0;
  DynWork metadata_work={.remaining=UINT64_MAX}; source.context.work=&metadata_work;
  assert(compact_rewrite_declarations(&source,dyn_compact_tree(&source),&actual_declarations,false));
  assert(compact_rewrite_declarations(&source,dyn_compact_tree(&source),&actual_declarations,true));
  size_t metadata_allocations=allocations;
  uint64_t metadata_used=UINT64_MAX-metadata_work.remaining;
  source.context.work=NULL;
  assert(expected_declarations.decl_count==actual_declarations.decl_count);
  for(size_t i=0;i<expected_declarations.decl_count;++i)
    assert(has_decl(&actual_declarations,expected_declarations.decls[i].name));
  clear_declarations(&expected_declarations); clear_declarations(&actual_declarations);
  if(resources) {
    for(size_t n=1;n<=metadata_allocations;++n) {
      allocations=0; fail_at=n;
      bool ok=compact_rewrite_declarations(&source,dyn_compact_tree(&source),&actual_declarations,false) &&
        compact_rewrite_declarations(&source,dyn_compact_tree(&source),&actual_declarations,true);
      assert(!ok); clear_declarations(&actual_declarations);
    }
    fail_at=0;
    for(uint64_t budget=0;budget<metadata_used;++budget) {
      metadata_work=(DynWork){.remaining=budget}; source.context.work=&metadata_work;
      bool ok=compact_rewrite_declarations(&source,dyn_compact_tree(&source),&actual_declarations,false) &&
        compact_rewrite_declarations(&source,dyn_compact_tree(&source),&actual_declarations,true);
      assert(!ok && metadata_work.status==DYN_WORK_LIMIT); clear_declarations(&actual_declarations);
    }
    source.context.work=NULL;
  }
  Module old_abi={.abi=123},new_abi={.abi=123};
  rewrite_abi_tree(&source,root,&old_abi);
  assert(compact_rewrite_abi(&source,dyn_compact_tree(&source),&new_abi));
  if(old_abi.abi!=new_abi.abi) { fprintf(stderr,"ABI hash mismatch: %s\n",text); abort(); }
  modules[0].root=root_module;
  Edits expected={0},actual={0};
  assert(rewrite_node(root,&source,modules,modules,2,&expected,&scopes));
  DynWork work={.remaining=UINT64_MAX}; source.context.work=&work;
  allocations=0;
  assert(rewrite_source_nodes((TSNode){0},&source,modules,modules,2,&actual,&scopes));
  size_t total=allocations;
  uint64_t used=UINT64_MAX-work.remaining;
  source.context.work=NULL;
  normalize(&expected); normalize(&actual);
  bool equal=expected.count==actual.count;
  for(size_t i=0;equal && i<expected.count;++i) {
    Edit a=expected.items[i],b=actual.items[i];
    equal=a.start==b.start && a.end==b.end && !strcmp(a.text,b.text) &&
      a.start_point.row==b.start_point.row && a.start_point.column==b.start_point.column &&
      a.end_point.row==b.end_point.row && a.end_point.column==b.end_point.column;
  }
  if(!equal) {
    fprintf(stderr,"SOURCE %s\n",text);
    for(size_t i=0;i<expected.count;++i) fprintf(stderr,"OLD %u:%u %s\n",expected.items[i].start,expected.items[i].end,expected.items[i].text);
    for(size_t i=0;i<actual.count;++i) fprintf(stderr,"NEW %u:%u %s\n",actual.items[i].start,actual.items[i].end,actual.items[i].text);
    abort();
  }
  clear_edits(&expected); clear_edits(&actual);
  if(resources) {
    for(size_t n=1;n<=total;++n) {
      allocations=0; fail_at=n;
      assert(!rewrite_source_nodes((TSNode){0},&source,modules,modules,2,&actual,&scopes));
      clear_edits(&actual);
    }
    fail_at=0;
    for(uint64_t budget=0;budget<used;++budget) {
      work=(DynWork){.remaining=budget}; source.context.work=&work;
      assert(!rewrite_source_nodes((TSNode){0},&source,modules,modules,2,&actual,&scopes));
      assert(work.status==DYN_WORK_LIMIT); clear_edits(&actual);
    }
    source.context.work=NULL;
  }
  dyn_scope_free(&scopes); dyn_source_free(&source);
}
static void reflection_dependency(void) {
  char root_dir[]="/tmp/dyn-rewrite-root-XXXXXX",dep_dir[]="/tmp/dyn-rewrite-dep-XXXXXX";
  assert(mkdtemp(root_dir) && mkdtemp(dep_dir));
  Module *modules=calloc(2,sizeof(*modules)); assert(modules);
  modules[0].dir=strdup(root_dir); modules[1].dir=strdup(dep_dir);
  assert(add_alias(&modules[0],"dep",dep_dir));
  DynSource items[2]={0}; DynSources sources={.items=items,.count=2};
  for(size_t i=0;i<2;++i) {
    char path[256]; snprintf(path,sizeof(path),"%s/main.dyn",i ? dep_dir : root_dir);
    items[i].path=strdup(path);
  }
  for(unsigned reflected=0;reflected<2;++reflected) {
    free(items[0].text); dyn_source_discard_syntax(&items[0]);
    items[0].text=strdup(reflected ? "fn main(){_=#typeof(i64)}" : "fn main(){}");
    items[0].length=strlen(items[0].text); assert(dyn_source_prepare(&items[0]));
    assert(items[0].compact_reflection==(bool)reflected);
    uint64_t before=0;
    for(unsigned revision=0;revision<2;++revision) {
      free(items[1].text); dyn_source_discard_syntax(&items[1]);
      items[1].text=strdup(revision ? "pub fn f() i64 {return 2}" : "pub fn f() i64 {return 1}");
      items[1].length=strlen(items[1].text); assert(dyn_source_prepare(&items[1]));
      for(size_t i=0;i<2;++i) {
        free(items[i].dependency_sources); items[i].dependency_sources=NULL; items[i].dependency_count=0;
      }
      assert(capture_dependencies(&sources,modules,2));
      if(!revision) before=items[0].dependency_hash;
      else assert((before!=items[0].dependency_hash)==(bool)reflected);
    }
  }
  for(size_t i=0;i<2;++i) dyn_source_free(&items[i]);
  free_modules(modules,2); assert(!rmdir(root_dir) && !rmdir(dep_dir));
}
static void nul_original_text(void) {
  static const char text[]="fn main(){_=1}//comment\0\n";
  DynSource source={.path=strdup("nul.dyn"),.text=malloc(sizeof(text)),.length=sizeof(text)-1};
  memcpy(source.text,text,sizeof(text));assert(dyn_source_prepare(&source));
  Edits edits={0};
  assert(append_edit(&edits,(Edit){3,7,strdup("renamed"),{0,3},{0,7}}));
  assert(apply_edits(&source,&edits));
  assert(source.original_length==sizeof(text)-1 && !memcmp(source.original_text,text,sizeof(text)));
  const char *path;unsigned line,column;
  dyn_source_location(&source,source.length,&path,&line,&column);
  assert(line==2 && column==1);
  clear_edits(&edits);dyn_source_free(&source);
}
int main(int argc,char **argv) {
  nul_original_text();
  reflection_dependency();
  Module *modules=calloc(2,sizeof(*modules)); assert(modules);
  modules[0].dir=strdup("/root"); modules[1].dir=strdup("/dependency");
  assert(add_alias(&modules[0],"mod","/dependency"));
  const char *names[]={"Record","call","value","main","f","Alias","Kind"};
  for(size_t i=0;i<sizeof(names)/sizeof(*names);++i) assert(add_decl(&modules[0],names[i]));
  const char *expressions[]={"mod.call()","call()","(call)()","(mod.call)()",
    "mod.Record{}","Record{}","wrong.Record{}","#sizeof(Record)","#sizeof(mod.Record)",
    "#alignof(mod.value)","#typeof(mod.value)","mod.value.x","(mod).value", "(&mod).value",
    "mod.call(call())","[mod.value,call()]","#cast(mod.Record) 0",
    "#sizeof(*mod.value)","#typeof(mod.Record.x)","#cast(*fn(mod.Record) Record) nil"};
  const char *prefixes[]={"", "mod:=1 ", "Record:=1 ", "call:=1 ", "const mod:=1 ",
    "for mod in 0..1 {", "if true {mod:=1 ", "case 1 {_ mod=>{"};
  const char *suffixes[]={"", "", "", "", "", "}","}","}}"};
  unsigned cases=0;
  for(size_t i=0;i<sizeof(expressions)/sizeof(*expressions);++i)
    for(size_t j=0;j<sizeof(prefixes)/sizeof(*prefixes);++j) {
      char text[2048];
      snprintf(text,sizeof(text),"// UTF-8: λ\nfn main(){%s _ = %s %s}\n",prefixes[j],expressions[i],suffixes[j]);
      compare(modules,text,false,true); compare(modules,text,true,true); cases+=2;
    }
  const char *declarations[]={"fn f(x:mod.Record) Record {a:Record b:mod.Record return mod.Record{}}",
    "fn f(mod,call:Record) {call() _=mod.value}",
    "struct Record {x:i64} enum(i32) Kind {a, b} type Alias = Record value:i64 const call:=1 extern f:i64"};
  for(size_t i=0;i<sizeof(declarations)/sizeof(*declarations);++i) {
    compare(modules,declarations[i],false,true); ++cases;
  }
  for(int i=1;i<argc;++i) {
    FILE *file=fopen(argv[i],"rb"); assert(file);
    assert(!fseek(file,0,SEEK_END)); long size=ftell(file); assert(size>=0);
    rewind(file); char *text=calloc((size_t)size+1,1); assert(text);
    assert(fread(text,1,(size_t)size,file)==(size_t)size); fclose(file);
    compare(modules,text,false,false); free(text); ++cases;
  }
  free_modules(modules,2);
  printf("PASS %u compact rewrite comparisons\n",cases);
}
