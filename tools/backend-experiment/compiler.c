/* Compiler adapter. The backend owns no frontend or CLI policy. */
#define DYN_BACKEND_EMBEDDED
#include "driver.c"

int dyn_native_object(const DynSource *source, const DynIrProgram *ir,
                      const char *path, bool runtime_trace, bool debug_info,
                      bool report) {
  (void)object_mode; (void)object_report; /* test and benchmark drivers share driver.c */
  const DynTarget *target = dyn_context_target(&source->context);
  bool a64 = !strcmp(target->arch, "aarch64");
  ObjectTarget object = !strcmp(target->kernel, "windows") ? TARGET_X64_COFF
                      : !strcmp(target->kernel, "darwin") ? TARGET_A64_MACHO
                      : a64 ? TARGET_A64_ELF : TARGET_X64_ELF;
  if (object_target(source, ir, path, runtime_trace, debug_info, report, object)) return 0;
  if (report) fprintf(stderr, "error: native emission failed; use --backend llvm\n");
  return 1;
}
