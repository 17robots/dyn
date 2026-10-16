/* Compiler adapter. The backend owns no frontend or CLI policy. */
#define DYN_BACKEND_EMBEDDED
#include "driver.c"

int dyn_native_object(const DynSource *source, const DynIrProgram *ir,
                      const char *path, bool runtime_trace, bool debug_info,
                      bool shared, bool report) {
  (void)object_mode; (void)object_report; /* test and benchmark drivers share driver.c */
  const DynTarget *target = dyn_context_target(&source->context);
  bool a64 = !strcmp(target->arch, "aarch64");
  ObjectTarget object = !strcmp(target->arch,"riscv64") ? TARGET_RV64_ELF : !strcmp(target->kernel, "windows") ? (a64 ? TARGET_A64_COFF : TARGET_X64_COFF)
                      : !strcmp(target->kernel, "darwin") ? (a64 ? TARGET_A64_MACHO : TARGET_X64_MACHO)
                      : a64 ? TARGET_A64_ELF : TARGET_X64_ELF;
  if (object_target_mode(source, ir, path, runtime_trace, debug_info, report, object, shared)) return 0;
  if (report)
    fprintf(stderr, "error: native emission failed\n");
  return 1;
}
