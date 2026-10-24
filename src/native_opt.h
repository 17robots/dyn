#ifndef DYN_NATIVE_OPT_H
#define DYN_NATIVE_OPT_H
#include "ir.h"
typedef struct {
  DynIrProgram ir;
  size_t folded, propagated, branches, calls, inlined;
  bool owns_expansion;
} DynNativeOptimization;
/* The result owns transformed node arrays and borrows names/types.
   Input remains immutable, so concurrent module emission is safe. */
bool dyn_native_optimize(const DynSource *, const DynIrProgram *, unsigned,
                         DynNativeOptimization *);
/* Target intrinsics need an SSA-capable emission mode. Debug/DWARF callers
   disable them while retaining ordinary scalar inlining. */
bool dyn_native_optimize_for_emission(const DynSource *, const DynIrProgram *, unsigned,
                                      bool, DynNativeOptimization *);
void dyn_native_optimization_free(DynNativeOptimization *);
#endif
