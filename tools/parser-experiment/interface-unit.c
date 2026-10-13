#define _POSIX_C_SOURCE 200809L
#include <stdlib.h>
#include <string.h>
#include <assert.h>
static size_t allocations,fail_at;
static void *interface_malloc(size_t n) { return ++allocations==fail_at ? NULL : malloc(n); }
static void *interface_calloc(size_t n,size_t size) { return ++allocations==fail_at ? NULL : calloc(n,size); }
static void *interface_realloc(void *p,size_t n) { return ++allocations==fail_at ? NULL : realloc(p,n); }
#define malloc interface_malloc
#define calloc interface_calloc
#define realloc interface_realloc
#include "../../src/interface.c"
#undef malloc
#undef calloc
#undef realloc
static unsigned comparisons;
static void compare(const char *first,const char *second) {
  DynSource items[2]={0};
  DynSources sources={.items=items,.count=second ? 2 : 1};
  const char *texts[]={first,second};
  ExpSnapshot *snapshots[2]={0};
  for(size_t i=0;i<sources.count;++i) {
    items[i]=(DynSource){.path=strdup(i ? "second.dyn" : "first.dyn"),.text=strdup(texts[i]),.length=strlen(texts[i])};
    assert(dyn_source_prepare(&items[i]) && items[i].compact);
    snapshots[i]=items[i].compact; items[i].compact=NULL;
  }
  DynInterface old={0},current={0};
  int expected=dyn_interface_build(&sources,&old);
  for(size_t i=0;i<sources.count;++i) items[i].compact=snapshots[i];
  int actual=dyn_interface_build(&sources,&current);
  bool equal=actual==expected;
  if(equal && !actual) equal=old.length==current.length && old.source_hash==current.source_hash &&
    old.interface_hash==current.interface_hash && !memcmp(old.data,current.data,old.length);
  if(!equal) {
    fprintf(stderr,"SOURCE %s\nSECOND %s\nOLD status%d %s\nNEW status%d %s\n",first,second ? second : "",
            expected,old.data ? old.data : "",actual,current.data ? current.data : ""); abort();
  }
  if(second) {
    dyn_interface_free(&current);
    items[1].compact=NULL;
    actual=dyn_interface_build(&sources,&current);
    items[1].compact=snapshots[1];
    assert(actual==expected);
    if(!actual) assert(old.length==current.length && old.source_hash==current.source_hash &&
      old.interface_hash==current.interface_hash && !memcmp(old.data,current.data,old.length));
    ++comparisons;
  }
  dyn_interface_free(&old); dyn_interface_free(&current);
  for(size_t i=0;i<sources.count;++i) dyn_source_free(&items[i]);
  ++comparisons;
}
static int collect_helpers(DynSources *sources) {
  InterfaceConstant *constants=NULL; size_t constant_count=0,count=0; char **decls=NULL;
  int status=1;
  if(!interface_constants(sources,&constants,&constant_count)) goto done;
  for(size_t i=0;i<sources->count;++i) {
    const DynSource *source=&sources->items[i]; const ExpSnapshotTree *tree=dyn_compact_tree(source);
    if(interface_compact_compatible(source,tree)!=1) goto done;
    if(interface_compact_declarations(source,tree,constants,constant_count,&decls,&count)) goto done;
  }
  status=0;
done:
  for(size_t i=0;i<count;++i) free(decls[i]);
  free(decls); free(constants); return status;
}
static void resources(void) {
  const char *texts[]={"pub struct Record{data:[Length]u8} pub fn f(a:[Length]u8){} pub global:i64=1",
                       "const Length:=Base+1 const Base:=3 const Unused:=99 pub const Public:=Base"};
  DynSource items[2]={0}; DynSources sources={.items=items,.count=2};
  for(size_t i=0;i<2;++i) {
    items[i]=(DynSource){.path=strdup(i ? "second.dyn" : "first.dyn"),.text=strdup(texts[i]),.length=strlen(texts[i])};
    assert(dyn_source_prepare(&items[i]) && items[i].compact);
  }
  DynWork work={.remaining=UINT64_MAX};
  for(size_t i=0;i<2;++i) items[i].context.work=&work;
  allocations=0; assert(!collect_helpers(&sources));
  size_t total=allocations; uint64_t used=UINT64_MAX-work.remaining;
  for(size_t i=0;i<2;++i) items[i].context.work=NULL;
  for(size_t n=1;n<=total;++n) {
    allocations=0; fail_at=n; assert(collect_helpers(&sources));
  }
  fail_at=0;
  for(size_t i=0;i<2;++i) items[i].context.work=&work;
  for(uint64_t budget=0;budget<used;++budget) {
    work=(DynWork){.remaining=budget}; assert(collect_helpers(&sources)); assert(work.status==DYN_WORK_LIMIT);
  }
  for(size_t i=0;i<2;++i) { items[i].context.work=NULL; dyn_source_free(&items[i]); }
}
int main(int argc,char **argv) {
  resources();
  const char *cases[]={
    "pub fn f(a:i64) i64 {return a} fn hidden(){} pub const value:=2 const hidden:=7",
    "const A:=B+1 const B:=4 const unused:=8 pub struct Record {items:[A]u8}",
    "const A:=B const B:=A type Alias=[A]u8",
    "const A:=3 pub fn f(a:[A]u8) [A]u8 {local:[99]u8 return a}",
    "pub value:i64 pub other:i64=4 pub extern outside \"native\":i32",
    "pub inferred:=3", "pub const public_size:=4 const private_size:=5",
    "pub value: /* type trivia */ i32", "pub value: // type trivia\n i32",
    "pub value: /* type trivia */ i32=2",
    "// before\npub fn f(a:i64) /* return */ i64 /* body */ {return a}",
    "const A:=3 enum(u8) Kind {Empty,Value:[A]u8} packed struct Record{x:[A]u8}",
    "#target(os:windows) pub value:i64", "use \"other\" lib pub type Alias=lib.Type"
  };
  for(size_t i=0;i<sizeof(cases)/sizeof(*cases);++i) compare(cases[i],NULL);
  compare("pub struct Record{data:[Length]u8}","const Length:=Base+1 const Base:=3 const Unused:=99");
  compare("pub fn f() {hidden:[Private]u8}","const Private:=7");
  for(int i=1;i<argc;++i) {
    FILE *file=fopen(argv[i],"rb"); assert(file);
    assert(!fseek(file,0,SEEK_END)); long size=ftell(file); assert(size>=0);
    rewind(file); char *text=calloc((size_t)size+1,1); assert(text);
    assert(fread(text,1,(size_t)size,file)==(size_t)size); fclose(file);
    compare(text,NULL); free(text);
  }
  printf("PASS %u compact serialized interface comparisons\n",comparisons);
}
