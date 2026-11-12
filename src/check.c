#include "dyn.h"
#include "frontend.h"
#include <stdlib.h>
#include <string.h>

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

static void vet_ignore(const char *severity, const char *path, unsigned line, unsigned column,
                       unsigned end_line, unsigned end_column, const char *message, void *data) {
  (void)severity, (void)path, (void)line, (void)column, (void)end_line, (void)end_column,
      (void)message, (void)data;
}
/* Checks the module on one more target with every diagnostic silenced, so
   that target can mark the collected casts it still needs. A target the
   module does not load on cannot build it, so it has no say. */
static void vet_confirm(const DynContext *base, const DynTarget *target, const char *input,
                        const char *main_path) {
  DynContext context = *base;
  context.target = target;
  context.diagnostic = vet_ignore;
  context.diagnostic_data = NULL;
  context.json_diagnostics = false;
  context.vet_findings = NULL;
  context.timings = false;
  DynSources loaded, project = {0};
  if (dyn_sources_load_quiet(&context, input, &loaded)) return;
  int failed = dyn_module_load_project(input, &loaded, &project);
  dyn_sources_free(&loaded);
  if (failed) {
    dyn_sources_free(&project);
    return;
  }
  DynSource merged = {0};
  if (!dyn_sources_merge(&project, main_path, &merged)) {
    DynAstProgram ast = {0};
    dyn_analyze(&merged, &ast, (DynAnalysisOptions){.main_path = main_path});
    dyn_ast_program_free(&ast);
  }
  dyn_source_free(&merged);
  dyn_sources_free(&project);
}
/* Targets that #target cannot tell apart (a board layout such as the
   NUCLEO-H753ZI) check identically, so one of them is enough. */
static bool vet_same_target(const DynTarget *a, const DynTarget *b) {
  static const char *const keys[] = {"arch", "kernel", "abi", "libc", "endian", "pointer_bits"};
  for (size_t i = 0; i < sizeof(keys) / sizeof(*keys); ++i)
    if (strcmp(dyn_target_property(a, keys[i]), dyn_target_property(b, keys[i]))) return false;
  return true;
}
static bool vet_target_seen(const DynTarget *target, const DynTarget *own, size_t index) {
  if (vet_same_target(target, own)) return true;
  for (size_t i = 0; i < index; ++i)
    if (vet_same_target(target, dyn_target_at(i))) return true;
  return false;
}
DynCheckResult dyn_vet_sources(const DynSources *sources, const char *main_path,
                               const char *input) {
  DynSource merged = {0};
  if (!sources->count || dyn_sources_merge(sources, main_path, &merged))
    return (DynCheckResult){.errors = 1};
  DynVetCasts *casts = merged.context.vet_casts;
  DynAstProgram ast = {0};
  DynAnalysisResult result =
      dyn_analyze(&merged, &ast, (DynAnalysisOptions){.main_path = main_path});
  dyn_ast_program_free(&ast);
  if (casts && !result.errors) {
    casts->confirm = true;
    const DynTarget *own = dyn_context_target(&merged.context), *target;
    for (size_t i = 0; casts->count && (target = dyn_target_at(i)); ++i) {
      if (vet_target_seen(target, own, i)) continue;
      vet_confirm(&sources->items[0].context, target, input, main_path);
      size_t kept = 0;
      for (size_t j = 0; j < casts->count; ++j) {
        if (!casts->items[j].needed) { casts->items[kept++] = casts->items[j]; continue; }
        /* Diagnostics come from the first pass's merged source. */
        free(casts->items[j].path);
      }
      casts->count = kept;
    }
    for (size_t i = 0; i < casts->count; ++i) {
      dyn_diagnostic_source("warning", &merged, casts->items[i].start, casts->items[i].end,
                            "cast is implicit here");
      if (merged.context.vet_findings) ++*merged.context.vet_findings;
    }
  }
  if (casts) {
    if (casts->failed) ++result.errors;
    for (size_t i = 0; i < casts->count; ++i) free(casts->items[i].path);
    free(casts->items);
    *casts = (DynVetCasts){0};
  }
  dyn_source_free(&merged);
  return (DynCheckResult){result.has_main, result.main_valid, result.errors};
}
