#ifndef DYN_FRONTEND_H
#define DYN_FRONTEND_H
#include "dyn_ast.h"

typedef struct {
  const char *owner_key;
  const char *main_path;
  bool require_main;
  bool recover; /* Retain useful declarations from incomplete editor syntax. */
} DynAnalysisOptions;
typedef struct {
  unsigned errors;
  bool parsed, checked, has_main, main_valid;
} DynAnalysisResult;
/* Source is borrowed. Caller always frees ast, including partial/error results.
   Both strict builds and recovering editor requests cross this seam. */
DynAnalysisResult dyn_analyze(const DynSource *source, DynAstProgram *ast,
                              DynAnalysisOptions options);
#endif
