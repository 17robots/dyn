#include "dyn.h"
#include "frontend.h"

DynCheckResult dyn_check_sources(const DynSources *sources,
                                 const char *main_path, bool require_main) {
  DynSource merged = {0};
  if (dyn_sources_merge(sources, main_path, &merged))
    return (DynCheckResult){.errors = 1};
  DynAstProgram ast = {0};
  DynAnalysisResult result =
      dyn_analyze(&merged, &ast,
                  (DynAnalysisOptions){.main_path = main_path,
                                       .require_main = require_main});
  dyn_ast_program_free(&ast);
  dyn_source_free(&merged);
  return (DynCheckResult){result.has_main, result.main_valid, result.errors};
}
