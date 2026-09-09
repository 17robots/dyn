#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <sys/mman.h>
#include <unistd.h>

typedef struct { size_t first, count; } Job;

static size_t directory_length(const char *path) {
  const char *slash = strrchr(path, '/');
  return slash ? (size_t)(slash - path) : 0;
}
static bool same_directory(const char *a, const char *b) {
  size_t an = directory_length(a), bn = directory_length(b);
  return an == bn && !memcmp(a, b, an);
}

int dyn_build_plan_run(const DynSources *sources, unsigned workers,
                       DynModuleBuildFn build, void *context,
                       uint64_t **values, size_t *value_count) {
  if (!sources || !build || !values || !value_count) return 2;
  *values = NULL;
  *value_count = 0;
  if (!sources->count) return 0;
  Job *jobs = malloc(sources->count * sizeof(*jobs));
  if (!jobs) return 2;
  size_t count = 0;
  for (size_t i = 0; i < sources->count;) {
    size_t end = i + 1;
    while (end < sources->count &&
           same_directory(sources->items[i].path, sources->items[end].path))
      ++end;
    jobs[count++] = (Job){i, end - i};
    i = end;
  }
  long online = sysconf(_SC_NPROCESSORS_ONLN);
  if (!workers) workers = online > 0 ? (unsigned)online : 1;
  if (workers > count) workers = (unsigned)count;
  size_t shared_size=count*(sizeof(uint64_t)+sizeof(int));
  unsigned char *shared=mmap(NULL,shared_size,PROT_READ|PROT_WRITE,
    MAP_SHARED|MAP_ANONYMOUS,-1,0);
  if(shared==MAP_FAILED){free(jobs);return 2;}
  uint64_t *out=(uint64_t *)shared;int *errors=(int *)(shared+count*sizeof(*out));
  pid_t *pids=calloc(workers,sizeof(*pids));if(!pids){munmap(shared,shared_size);free(jobs);return 2;}
  int result=0;
  for(unsigned worker=0;worker<workers;++worker){
    pids[worker]=fork();
    if(pids[worker]<0){result=2;break;}
    if(!pids[worker]){
      for(size_t id=worker;id<count;id+=workers)
        errors[id]=build(sources,jobs[id].first,jobs[id].count,context,&out[id]);
      _exit(0);
    }
  }
  for(unsigned worker=0;worker<workers;++worker)if(pids[worker]>0){
    int status=0;if(waitpid(pids[worker],&status,0)<0||!WIFEXITED(status)||WEXITSTATUS(status))result=2;
  }
  for(size_t i=0;i<count;++i)if(errors[i]&&!result)result=errors[i];
  uint64_t *copy=NULL;if(!result){copy=malloc(count*sizeof(*copy));if(copy)memcpy(copy,out,count*sizeof(*copy));else result=2;}
  free(pids);munmap(shared,shared_size);
  free(jobs);
  if (result) { free(copy); return result; }
  *values = copy;
  *value_count = count;
  return 0;
}
