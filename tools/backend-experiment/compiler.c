/* Compiler adapter. The backend owns no frontend or CLI policy. */
#define DYN_BACKEND_EMBEDDED
#include "driver.c"

int dyn_native_object(const DynSource *source, const DynIrProgram *ir,
                      const char *path, bool runtime_trace, bool debug_info,
                      bool report) {
  (void)object_mode; (void)object_report; /* test and benchmark drivers share driver.c */
  bool a64 = !strcmp(dyn_context_target(&source->context)->arch, "aarch64");
  if (object_target(source, ir, path, runtime_trace, debug_info, report, a64)) return 0;
  if (report) fprintf(stderr, "error: native emission failed; use --backend llvm\n");
  return 1;
}
