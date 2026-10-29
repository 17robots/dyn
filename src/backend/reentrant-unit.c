#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <pthread.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
static _Thread_local unsigned allocation_count, fail_allocation;
static _Thread_local bool failed_optional_cache;
static bool emitter_allocation_fails(const char *caller) {
  if (++allocation_count != fail_allocation) return false;
  /* Deduplication and layout caches can fall back to uncached emission.
     Identify these allocations by owner, independent of order or size. */
  failed_optional_cache = !strcmp(caller,"literal") || !strcmp(caller,"layout_cache_begin");
  return true;
}
static void *emitter_calloc(size_t count,size_t size,const char *caller) {
  return emitter_allocation_fails(caller) ? NULL : calloc(count,size);
}
static void *emitter_malloc(size_t size,const char *caller) {
  return emitter_allocation_fails(caller) ? NULL : malloc(size);
}
#define calloc(count,size) emitter_calloc(count,size,__func__)
#define malloc(size) emitter_malloc(size,__func__)
#define main backend_cli_main
#include "driver.c"
#undef main
#undef calloc
#undef malloc

typedef struct { DynSource source; DynIrProgram ir; } Fixture;
typedef struct { const Fixture *fixture; const char *directory; unsigned id; } Job;
static void prepare(Fixture *fixture, const char *source) {
  fixture->source=(DynSource){.path=strdup("reentrant.dyn"),.text=strdup(source),.length=strlen(source)};
  fixture->source.context.target=dyn_target_find("x86_64-linux");
  DynAstProgram ast={0};
  assert(dyn_analyze(&fixture->source,&ast,(DynAnalysisOptions){0}).checked);
  assert(dyn_ir_lower(&ast,&fixture->source,&fixture->ir));
  dyn_ast_program_free(&ast);
}
static bool equal_files(const char *left,const char *right) {
  FILE *a=fopen(left,"rb"),*b=fopen(right,"rb"); assert(a && b);
  bool equal=true;
  for (;;) { int x=fgetc(a),y=fgetc(b); if(x!=y) {equal=false;break;} if(x==EOF)break; }
  assert(!ferror(a) && !ferror(b)); fclose(a);fclose(b);return equal;
}
static void *run(void *raw) {
  const Job *job=raw;
  char path[1024],expected[1024];
  for(unsigned i=0;i<4;++i) {
    bool debug=(i+job->id)%2;
    snprintf(path,sizeof(path),"%s/thread-%u-%u.o",job->directory,job->id,i);
    snprintf(expected,sizeof(expected),"%s/reference-%u-%u.o",job->directory,job->id%2,debug);
    assert(object_mode(&job->fixture->source,&job->fixture->ir,path,debug));
    assert(equal_files(path,expected)); assert(!unlink(path));
  }
  return NULL;
}
int main(void) {
  Fixture fixtures[2]={0};
  prepare(&fixtures[0],"pub fn identity(a:u64) u64 { return a }\n");
  prepare(&fixtures[1],"struct Pair { first:u64, second:u64 }\npub fn pair_value(a:u64) u64 { pair:=Pair{first:a,second:2}\nreturn pair.first+pair.second }\ncounter:u64=1\nfn add(a:u64){counter+=a}\npub fn work(a:u64) u64 {defer add(2)\nreturn a+counter}\npub fn second(a:u64) u64 {return work(a)*2}\n");
  char directory[]="/tmp/dyn-backend-reentrant-XXXXXX";assert(mkdtemp(directory));
  char path[1024],expected[1024];
  for(unsigned fixture=0;fixture<2;++fixture) for(unsigned debug=0;debug<2;++debug) {
    snprintf(path,sizeof(path),"%s/reference-%u-%u.o",directory,fixture,debug);
    assert(object_mode(&fixtures[fixture].source,&fixtures[fixture].ir,path,debug));
  }
  /* Fail after earlier functions emitted bytes, then reuse unrelated IR. */
  DynIrFunction *rejected=&fixtures[1].ir.functions[fixtures[1].ir.function_count-1];
  uint32_t local_count=rejected->local_count;rejected->local_count=257;
  snprintf(path,sizeof(path),"%s/rejected.o",directory);
  FILE *sentinel=fopen(path,"wb");assert(sentinel);assert(fputs("preserved",sentinel)>=0);assert(!fclose(sentinel));
  for(unsigned i=0;i<3;++i) assert(!object_mode(&fixtures[1].source,&fixtures[1].ir,path,i%2));
  sentinel=fopen(path,"rb");assert(sentinel);char bytes[16]={0};assert(fread(bytes,1,sizeof(bytes),sentinel)==9);assert(!strcmp(bytes,"preserved"));fclose(sentinel);unlink(path);
  rejected->local_count=local_count;
  /* An output-open failure must release the same context as rejection. */
  assert(!object_mode(&fixtures[1].source,&fixtures[1].ir,directory,true));
  for(unsigned i=0;i<8;++i) {
    unsigned fixture=i%2,debug=(i/2)%2;
    snprintf(path,sizeof(path),"%s/repeat.o",directory);
    snprintf(expected,sizeof(expected),"%s/reference-%u-%u.o",directory,fixture,debug);
    assert(debug ? object_mode(&fixtures[fixture].source,&fixtures[fixture].ir,path,true) : object(&fixtures[fixture].source,&fixtures[fixture].ir,path));
    assert(equal_files(path,expected));unlink(path);
  }
  snprintf(path,sizeof(path),"%s/allocation.o",directory);
  allocation_count=0;
  assert(object_mode(&fixtures[1].source,&fixtures[1].ir,path,true));
  unsigned allocations=allocation_count;unlink(path);
  unsigned optional_failures=0,required_failures=0;
  for(unsigned failure=1;failure<=allocations;++failure) {
    allocation_count=0;fail_allocation=failure;failed_optional_cache=false;
    bool emitted=object_mode(&fixtures[1].source,&fixtures[1].ir,path,true);
    assert(allocation_count>=failure);
    if(failed_optional_cache) {
      ++optional_failures;
      assert(emitted);
      snprintf(expected,sizeof(expected),"%s/reference-1-1.o",directory);
      assert(equal_files(path,expected));assert(!unlink(path));
    } else {
      ++required_failures;
      assert(!emitted);
      assert(access(path,F_OK));
    }
    fail_allocation=0;
    assert(object(&fixtures[0].source,&fixtures[0].ir,path));
    snprintf(expected,sizeof(expected),"%s/reference-0-0.o",directory);
    assert(equal_files(path,expected));unlink(path);
  }
  assert(optional_failures && required_failures);
  pthread_t threads[8];Job jobs[8];
  for(unsigned i=0;i<8;++i) {jobs[i]=(Job){&fixtures[i%2],directory,i};assert(!pthread_create(&threads[i],NULL,run,&jobs[i]));}
  for(unsigned i=0;i<8;++i)assert(!pthread_join(threads[i],NULL));
  for(unsigned fixture=0;fixture<2;++fixture) {
    for(unsigned debug=0;debug<2;++debug) {snprintf(path,sizeof(path),"%s/reference-%u-%u.o",directory,fixture,debug);unlink(path);}
    dyn_ir_free(&fixtures[fixture].ir);dyn_source_free(&fixtures[fixture].source);
  }
  assert(!rmdir(directory));
  puts("PASS backend contexts: alternating IR/modes, rejection recovery, deterministic bytes, eight concurrent emitters");
}
