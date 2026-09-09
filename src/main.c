#define _XOPEN_SOURCE 700
#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
extern char *realpath(const char *, char *);
typedef struct {
  const DynSource *merged;
  const DynInterface *interfaces;
  size_t interface_count;
  bool incremental_frontend;
  const DynOptions *options;
  const char *compiler, *output, *root, *cache_root;
} ModuleBuild;
static uint64_t path_hash(const char *s) {
  uint64_t h=UINT64_C(1469598103934665603);for(;*s;++s){h^=(unsigned char)*s;h*=UINT64_C(1099511628211);}return h;
}
static int build_module(const DynSources *sources,size_t first,size_t count,
                        void *raw,uint64_t *value) {
  ModuleBuild *b=raw;char object[4096],owner[32];
  if(snprintf(object,sizeof(object),"%s.dynmod.%zu.o",b->output,first)>=(int)sizeof(object))return 2;
  char *full=realpath(sources->items[first].path,NULL);if(!full)return 2;
  char *slash=strrchr(full,'/');if(slash)*slash=0;
  if(!strcmp(full,b->root))strcpy(owner,"root");else snprintf(owner,sizeof(owner),"dyn_m%016llx",(unsigned long long)path_hash(full));
  free(full);*value=first;
  if(dyn_module_cache_restore(sources,first,count,b->options,b->compiler,b->cache_root,object)){
    if(b->options->verbose)fprintf(stderr,"cached module %s\n",sources->items[first].path);
    return 0;
  }
  DynSource composed={0};const DynSource *input=b->merged;
  int result=0;
  if(b->incremental_frontend && strcmp(owner,"root")){
    result=dyn_interface_compose(sources,first,count,b->interfaces,
                                 b->interface_count,sources->items[first].path,
                                 &composed);
    input=&composed;
  }
  if(!result)result=dyn_codegen_module(input,object,NULL,NULL,b->options->release,
                                       b->options->debug_info,owner);
  dyn_source_free(&composed);
  if(!result)dyn_module_cache_store(sources,first,count,b->options,b->compiler,b->cache_root,object);
  return result;
}

static size_t module_end(const DynSources *sources,size_t first){
  const char *slash=strrchr(sources->items[first].path,'/');
  size_t n=slash?(size_t)(slash-sources->items[first].path):0,end=first+1;
  while(end<sources->count){const char *s=strrchr(sources->items[end].path,'/');
    size_t m=s?(size_t)(s-sources->items[end].path):0;
    if(m!=n||memcmp(sources->items[first].path,sources->items[end].path,n))break;
    ++end;
  }return end;
}
typedef struct { const DynOptions *options; const char *root; } InterfaceBuild;
static bool interface_path(const DynSources *sources,size_t first,const char *root,
                           char *path,size_t capacity){
  char *full=realpath(sources->items[first].path,NULL);if(!full)return false;
  char *slash=strrchr(full,'/');if(slash)*slash=0;uint64_t key=path_hash(full);free(full);
  int n=snprintf(path,capacity,"%s/%016llx.dynmi",root,
    (unsigned long long)key);
  return n>0&&(size_t)n<capacity;
}
static int prepare_interface(const DynSources *sources,size_t first,size_t count,
                             void *raw,uint64_t *value){
  InterfaceBuild *build=raw;char path[4096];*value=first;
  if(!interface_path(sources,first,build->root,path,sizeof(path)))return 2;
  DynSources slice={sources->items+first,count};uint64_t hash=dyn_interface_source_hash(&slice);
  DynInterface interface={0};DynInterfaceStatus status=dyn_interface_load(
    path,build->options->target,"dyn-c-frontend-4",hash,&interface);
  if(status==DYN_INTERFACE_HIT){
    if(build->options->verbose)fprintf(stderr,"cached interface %s\n",sources->items[first].path);
    dyn_interface_free(&interface);return 0;
  }
  int result=dyn_interface_build(&slice,&interface);
  if(!result)result=dyn_interface_store(path,build->options->target,
                                        "dyn-c-frontend-4",&interface);
  dyn_interface_free(&interface);return result;
}
static int prepare_interfaces(const DynSources *sources,const DynOptions *o,
                              const char *cache_root,DynInterface **out,
                              size_t *out_count){
  *out=NULL;*out_count=0;InterfaceBuild build={o,cache_root};
  uint64_t *ids=NULL;size_t count=0;
  int result=dyn_build_plan_run(sources,o->jobs,prepare_interface,&build,&ids,&count);
  if(result){free(ids);return result;}
  DynInterface *values=calloc(count,sizeof(*values));if(!values){free(ids);return 2;}
  for(size_t module=0;module<count;++module){
    size_t first=(size_t)ids[module],end=module_end(sources,first);char path[4096];
    DynSources slice={sources->items+first,end-first};
    if(!interface_path(sources,first,cache_root,path,sizeof(path))||
       dyn_interface_load(path,o->target,"dyn-c-frontend-4",
         dyn_interface_source_hash(&slice),&values[module])!=DYN_INTERFACE_HIT){result=2;break;}
  }
  free(ids);
  if(result){for(size_t i=0;i<count;++i)dyn_interface_free(&values[i]);free(values);return result;}
  *out=values;*out_count=count;return 0;
}
static double elapsed_ms(struct timespec start) {
  struct timespec end;
  clock_gettime(CLOCK_MONOTONIC, &end);
  return (double)(end.tv_sec - start.tv_sec) * 1000.0 +
         (double)(end.tv_nsec - start.tv_nsec) / 1000000.0;
}
static struct timespec timer_start(void) {
  struct timespec value;
  clock_gettime(CLOCK_MONOTONIC, &value);
  return value;
}
static bool is_command(const DynOptions *o, const char *s) {
  return strcmp(o->command, s) == 0;
}
int main(int argc, char **argv) {
  if (argc == 2 && (strcmp(argv[1], "--help") == 0 ||
                    strcmp(argv[1], "-h") == 0)) {
    dyn_cli_help(NULL);
    return 0;
  }
  if (argc == 2 && strcmp(argv[1], "--version") == 0) {
    puts("dyn 0.1.0-dev");
    return 0;
  }
  DynOptions o;
  int cli = dyn_cli_parse(argc, argv, &o);
  if (cli) {
    dyn_cli_help(NULL);
    return cli;
  }
  dyn_diagnostic_mode(o.json_diagnostics);
  if (is_command(&o, "help")) {
    dyn_cli_help(o.input);
    return 0;
  }
  if (is_command(&o, "version")) {
    puts("dyn 0.1.0-dev");
    return 0;
  }
  if (is_command(&o, "lsp")) return dyn_lsp();
  if (is_command(&o, "cache")) return dyn_cache_command(o.input);
  if (is_command(&o, "fmt") || is_command(&o, "docs")) {
    if (!o.input || !dyn_path_is_directory(o.input)) {
      fprintf(stderr, "error: %s requires a module directory\n", o.command);
      return 2;
    }
    return is_command(&o, "fmt") ? dyn_format_directory(o.input, o.format_check)
                                  : dyn_docs_directory(o.input);
  }
  bool run = is_command(&o, "run");
  if (!is_command(&o, "check") && !is_command(&o, "build") && !run) {
    fprintf(stderr, "error: command '%s' is not implemented\n", o.command);
    return 2;
  }
  if (!o.input) {
    fprintf(stderr, "error: %s requires a module directory\n", o.command);
    return 2;
  }
  if (run && o.no_link) {
    fprintf(stderr, "error: run cannot be combined with --no-link\n");
    return 2;
  }
  if (!dyn_path_is_directory(o.input)) {
    fprintf(stderr, "error: input must be a module directory: '%s'\n", o.input);
    return 2;
  }
  if (!dyn_target_select(o.target)) {
    fprintf(stderr, "error: target '%s' is not implemented; supported targets: x86_64-linux, aarch64-linux, aarch64-macos, x86_64-windows\n",
            o.target);
    return 2;
  }
  bool early_build = is_command(&o, "build") && !o.no_link && !o.emit_ir &&
                     !o.emit_object && !o.emit_asm;
  if (early_build) {
    char *early_base = dyn_path_basename(o.input);
    const char *early_output = o.output ? o.output : early_base;
    if (dyn_cache_fast_hit(&o, argv[0], early_output)) {
      if (!o.quiet) printf("cached %s\n", early_output);
      free(early_base); return 0;
    }
    free(early_base);
  }
  struct timespec phase = timer_start();
  DynSources sources;
  int result = dyn_sources_load(o.input, &sources);
  if (result)
    return result;
  DynSources project_sources = {0};
  result = dyn_module_load_project(o.input, &sources, &project_sources);
  if (result) {
    dyn_sources_free(&sources);
    return result;
  }
  dyn_sources_free(&sources);
  sources = project_sources;
  if (strcmp(dyn_target->kernel, "linux")) {
    for (size_t i = 0; i < sources.count; ++i)
      if (strstr(sources.items[i].text, "#syscall(")) {
        fprintf(stderr,
                "error: target '%s' does not provide target-mapped "
                "#syscall numbers: %s\n", dyn_target->name,
                sources.items[i].path);
        dyn_sources_free(&sources);
        return 1;
      }
  }
  if (o.timings)
    fprintf(stderr, "timing load %.3f ms\n", elapsed_ms(phase));
  char *main_path = dyn_path_join(o.input, "main.dyn");
  bool build = is_command(&o, "build") || run;
  if (build && !o.no_link && !dyn_target->executable_link) {
    fprintf(stderr,
            "error: target '%s' supports object/assembly generation only; use --no-link\n",
            dyn_target->name);
    dyn_sources_free(&sources);
    free(main_path);
    return 1;
  }
  phase = timer_start();
  DynCheckResult checked = {0};
  if (!build) checked = dyn_check_sources(&sources, main_path, false);
  if (checked.errors) {
    dyn_sources_free(&sources);
    free(main_path);
    return 1;
  }
  if (o.timings)
    fprintf(stderr, "timing check %.3f ms\n", elapsed_ms(phase));
  if (!build) {
    if (!o.quiet)
      puts("ok");
    dyn_sources_free(&sources);
    free(main_path);
    return 0;
  }
  char *base = dyn_path_basename(o.input);
  char run_output[] = "/tmp/dyn-run-XXXXXX";
  if (run) {
    int temporary = mkstemp(run_output);
    if (temporary < 0) {
      perror("error: create run executable");
      dyn_sources_free(&sources);
      free(main_path);
      free(base);
      return 2;
    }
    close(temporary);
    remove(run_output);
  }
  const char *output = run ? run_output : o.output ? o.output : base;
  bool cacheable = !run && !o.no_link && !o.emit_ir && !o.emit_object &&
                   !o.emit_asm;
  if (cacheable && dyn_cache_hit(&sources, &o, argv[0], output)) {
    if (!o.quiet)
      printf("cached %s\n", output);
    dyn_sources_free(&sources);
    free(main_path);
    free(base);
    return 0;
  }
  char object[4096], ir[4096], assembly[4096];
  snprintf(object, sizeof(object), "%s.o", output);
  snprintf(ir, sizeof(ir), "%s.ll", output);
  snprintf(assembly, sizeof(assembly), "%s.s", output);
  DynSource module_source = {0};
  phase = timer_start();
  uint64_t *module_ids=NULL;size_t module_count=0;char **module_objects=NULL;
  DynInterface *interfaces=NULL;size_t interface_count=0;
  bool modular=cacheable;
  if(modular){
    char *root=realpath(o.input,NULL);char cache_root[4096];
    if(!root||!dyn_cache_directory(cache_root,sizeof(cache_root)))result=2;
    int prepared=!result?prepare_interfaces(&sources,&o,cache_root,&interfaces,&interface_count):2;
    bool incremental_frontend=prepared==0;
    if(prepared&&prepared!=3)result=prepared;
    if(!result)result=dyn_sources_merge(&sources,main_path,&module_source);
    ModuleBuild context={.merged=&module_source,.interfaces=interfaces,
      .interface_count=interface_count,.incremental_frontend=incremental_frontend,
      .options=&o,.compiler=argv[0],.output=output,.root=root,.cache_root=cache_root};
    if(!result)result=dyn_build_plan_run(&sources,o.jobs,build_module,&context,&module_ids,&module_count);
    free(root);
    if(!result){module_objects=calloc(module_count,sizeof(*module_objects));if(!module_objects)result=2;}
    for(size_t i=0;!result&&i<module_count;++i){module_objects[i]=malloc(4096);if(!module_objects[i]||snprintf(module_objects[i],4096,"%s.dynmod.%llu.o",output,(unsigned long long)module_ids[i])>=4096)result=2;}
  }else{
    result = dyn_sources_merge(&sources, main_path, &module_source);
    if (!result) result = dyn_codegen_main(&module_source, object, o.emit_ir ? ir : NULL,
                                           o.emit_asm ? assembly : NULL, o.release,
                                           o.debug_info);
  }
  if (o.timings)
    fprintf(stderr, "timing codegen %.3f ms\n", elapsed_ms(phase));
  dyn_source_free(&module_source);
  if(interfaces){for(size_t i=0;i<interface_count;++i)dyn_interface_free(&interfaces[i]);free(interfaces);}
  phase = timer_start();
  if (!result && !o.no_link)
    result = modular ? dyn_link_executable_objects((const char *const *)module_objects,module_count,output,o.link_inputs,o.link_input_count,o.release,o.verbose)
                     : dyn_link_executable(object, output, o.link_inputs,o.link_input_count,o.release,o.verbose);
  if (!result && cacheable)
    dyn_cache_store(&sources, &o, argv[0], output);
  if (o.timings && !o.no_link)
    fprintf(stderr, "timing link %.3f ms\n", elapsed_ms(phase));
  if (!o.emit_object && !o.no_link) remove(object);
  if(module_objects)for(size_t i=0;i<module_count;++i){if(module_objects[i])remove(module_objects[i]);free(module_objects[i]);}
  free(module_objects);free(module_ids);
  if (!result && !o.quiet)
    printf("built %s\n", o.no_link ? object : output);
  if (!result && run) {
    pid_t child = fork();
    if (child < 0) {
      perror("error: run");
      result = 2;
    } else if (child == 0) {
      execl(output, output, (char *)NULL);
      _exit(127);
    } else {
      int status = 0;
      if (waitpid(child, &status, 0) < 0) {
        perror("error: run");
        result = 2;
      } else if (WIFEXITED(status))
        result = WEXITSTATUS(status);
      else
        result = 128 + WTERMSIG(status);
    }
    remove(output);
  }
  dyn_sources_free(&sources);
  free(main_path);
  free(base);
  return result;
}
