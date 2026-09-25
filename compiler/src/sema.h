#ifndef DYN_SEMA_H
#define DYN_SEMA_H
#include "dyn_ast.h"
bool dyn_sema_function(DynAstProgram *ast, const DynSource *source,
                       unsigned *errors);
bool dyn_sema_base(DynAstProgram *ast, const DynSource *source,
                   unsigned *errors);
#endif
