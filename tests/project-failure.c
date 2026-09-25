#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "fault-alloc.h"
static void write_source(const char *path, const char *text) {
  FILE *file = fopen(path, "wb"); assert(file); assert(fputs(text, file) >= 0); assert(!fclose(file));
}
int main(void) {
  char root[] = "/tmp/dyn-project-failure-XXXXXX"; assert(mkdtemp(root));
  char lib[256], main_path[256], lib_path[256], manifest[256];
  snprintf(lib, sizeof(lib), "%s/lib", root); assert(!mkdir(lib, 0700));
  snprintf(main_path, sizeof(main_path), "%s/main.dyn", root);
  snprintf(lib_path, sizeof(lib_path), "%s/lib/module.dyn", root);
  snprintf(manifest, sizeof(manifest), "%s/dyn.project", root);
  write_source(manifest, "dependency fixture lib\n");
  write_source(main_path, "use \"fixture\" lib\nfn main() { value := lib.answer() _ = value }\n");
  write_source(lib_path, "pub fn answer() i32 { return 42 }\n");
  size_t total = 0;
  for (size_t iteration = 0; !iteration || iteration <= total; ++iteration) {
    calls = failed = 0; fail_at = iteration;
    DynSources roots = {0}, project = {0}; DynSource merged = {0};
    int result = dyn_sources_load(NULL, root, &roots);
    if (result) assert(!roots.items && !roots.count);
    if (!result) result = dyn_module_load_project(root, &roots, &project);
    if (!result) result = dyn_sources_merge(&project, main_path, &merged);
    if (!iteration) { assert(!result); total = calls; }
    else { assert(failed); assert(result != 0); }
    dyn_source_free(&merged); dyn_sources_free(&project); dyn_sources_free(&roots);
  }
  unlink(manifest); unlink(main_path); unlink(lib_path); rmdir(lib); rmdir(root);
  return 0;
}
