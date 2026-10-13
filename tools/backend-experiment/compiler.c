/* Compiler adapter. The backend owns no frontend or CLI policy. */
#define DYN_BACKEND_EMBEDDED
#include "driver.c"

int dyn_native_object(const DynSource *source, const DynIrProgram *ir,
                      const char *path, bool runtime_trace, bool debug_info,
                      bool report) {
  (void)object_mode; /* test and benchmark drivers share driver.c */
  if (object_report(source, ir, path, runtime_trace, debug_info, report)) return 0;
  if (report) fprintf(stderr, "error: native emission failed; use --backend llvm\n");
  return 1;
}
