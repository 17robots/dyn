#ifndef DYN_NATIVE_OPT_H
#define DYN_NATIVE_OPT_H
#include "ir.h"
typedef struct {
  DynIrProgram ir;
  size_t folded, propagated, branches, calls;
} DynNativeOptimization;
/* The result borrows all input arrays except expressions and statements.
   Input remains immutable, so concurrent module emission is safe. */
bool dyn_native_optimize(const DynSource *, const DynIrProgram *, unsigned,
                         DynNativeOptimization *);
void dyn_native_optimization_free(DynNativeOptimization *);
#endif
