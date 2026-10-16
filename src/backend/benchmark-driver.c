/* Both emitters receive the same prepared IR in a fresh process. */
#define main backend_cli
#include "driver.c"
#undef main
#include <sys/resource.h>
#include <time.h>
static double seconds(void) {
  struct timespec t;
  if (clock_gettime(CLOCK_MONOTONIC, &t)) abort();
  return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}
int main(int argc, char **argv) {
  if (argc != 5 || (strcmp(argv[1], "scalar") && strcmp(argv[1], "llvm")) ||
      (strcmp(argv[2], "debug") && strcmp(argv[2], "release"))) return 2;
  DynSource source = {.path = strdup(argv[3])};
  source.context.target = dyn_target_find("x86_64-linux");
  source.text = calloc(16u * 1024u * 1024u + 1, 1);
  if (!source.path || !source.text || !source.context.target) { dyn_source_free(&source); return 2; }
  FILE *in = fopen(argv[3], "rb");
  if (!in) { dyn_source_free(&source); return 2; }
  source.length = fread(source.text, 1, 16u * 1024u * 1024u + 1, in);
  bool valid = !ferror(in) && source.length <= 16u * 1024u * 1024u;
  fclose(in);
  if (!valid) { dyn_source_free(&source); return 2; }
  DynIrProgram ir = {0};
  double start = seconds();
  int status = dyn_codegen_prepare(&source, true, NULL, &ir);
  double prepared = seconds();
  bool debug_mode = !strcmp(argv[2], "debug");
  if (!status) status = !strcmp(argv[1], "scalar") ? !(debug_mode ? object_mode(&source, &ir, argv[4], true) : object(&source, &ir, argv[4])) :
      dyn_codegen_emit(&source, &ir, argv[4], NULL, NULL, !debug_mode, false, true, NULL, 0, 1);
  double emitted = seconds();
  struct rusage usage;
  if (getrusage(RUSAGE_SELF, &usage)) status = 2;
  if (!status) printf("{\"prepare_seconds\":%.9f,\"emit_seconds\":%.9f,\"peak_rss_kib\":%ld}\n",
      prepared - start, emitted - prepared, usage.ru_maxrss);
  dyn_codegen_release(&ir); dyn_source_free(&source);
  return status;
}
