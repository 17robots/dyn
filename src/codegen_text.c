/* Compile the established semantic lowering against the standalone syntax
 * writer. This translation unit never links to LLVM, including in reference
 * builds. Shared frontend and linker entry points remain in codegen.c. */
#ifndef DYN_NO_LLVM
#define DYN_NO_LLVM
#endif
#define DYN_TEXT_ONLY
#define dyn_codegen_emit dyn_codegen_text_impl
#include "codegen.c"

int dyn_codegen_text(const DynSource *source, const DynIrProgram *prepared,
                     const char *ir_path, bool release, bool debug_info,
                     bool shared) {
  return dyn_codegen_text_impl(source, prepared, "", ir_path, NULL, release,
                               debug_info, shared, NULL, 0, 1);
}
