#define _POSIX_C_SOURCE 200809L
#include "frontend.h"
#include "dyn_timing.h"
#include "dyn_syntax.h"
#include "sema.h"
#include <stdio.h>
#include <string.h>

static void analysis_parse_errors(TSNode n, const DynSource *s,
                                  unsigned *errors) {
  if (*errors >= 20)
    return;
  if (ts_node_is_error(n) || ts_node_is_missing(n)) {
    char message[160];
    snprintf(message, sizeof(message), "invalid syntax near '%s'",
             ts_node_type(n));
    dyn_syntax_diagnostic(n, s, "error", message);
    ++*errors;
    return;
  }
  if (!ts_node_has_error(n))
    return;
  for (uint32_t i = 0; i < ts_node_child_count(n); ++i)
    analysis_parse_errors(ts_node_child(n, i), s, errors);
}
static void analysis_declarations(TSNode root, const DynSource *s,
                                  const char *main_path, DynAnalysisResult *r) {
  for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
    TSNode d = dyn_syntax_declaration_node(ts_node_named_child(root, i));
    const char *k = ts_node_type(d);
    if (!strcmp(k, "comment") || !strcmp(k, "use") || !strcmp(k, "struct") ||
        !strcmp(k, "enum") || !strcmp(k, "variable") ||
        !strcmp(k, "const_variable") || !strcmp(k, "type_alias") ||
        !strcmp(k, "extern_fn") || !strcmp(k, "extern_variable") ||
        !strcmp(k, "target_directive") || !strcmp(k, "link_directive"))
      continue;
    if (strcmp(k, "fn")) {
      char message[160];
      snprintf(message, sizeof(message), "unsupported declaration '%s'", k);
      dyn_syntax_diagnostic(d, s, "error", message);
      ++r->errors;
      continue;
    }
    TSNode name = ts_node_child_by_field_name(d, "name", 4);
    if (ts_node_is_null(name) || !dyn_syntax_text_is(name, s, "main"))
      continue;
    if (r->has_main) {
      dyn_syntax_diagnostic(name, s, "error", "duplicate function 'main'");
      ++r->errors;
    }
    r->has_main = true;
    const char *path;
    unsigned line, column;
    dyn_source_location(s, ts_node_start_byte(name), &path, &line, &column);
    r->main_valid = !main_path || !strcmp(path, main_path);
    if (!r->main_valid) {
      dyn_syntax_diagnostic(name, s, "error",
                            "entry function must be declared in main.dyn");
      ++r->errors;
    }
    for (uint32_t j = 0; j < ts_node_named_child_count(d); ++j) {
      const char *ck = ts_node_type(ts_node_named_child(d, j));
      if (!strcmp(ck, "fn_param") || !strcmp(ck, "type")) {
        dyn_syntax_diagnostic(d, s, "error",
                              "entry signature must be exactly 'fn main()'");
        ++r->errors;
        break;
      }
    }
  }
}
DynAnalysisResult dyn_analyze(const DynSource *source, DynAstProgram *ast,
                              DynAnalysisOptions options) {
  DynAnalysisResult result = {0};
  memset(ast, 0, sizeof(*ast));
  struct timespec phase = dyn_timing_start(&source->context);
  TSTree *tree = dyn_source_tree(source);
  if (!tree) {
    dyn_diagnostic_source("error", source, 0, 0, "failed to parse Dyn source");
    result.errors = 1;
    return result;
  }
  result.parsed = true;
  TSNode root = ts_tree_root_node(tree);
  analysis_parse_errors(root, source, &result.errors);
  if (!ts_node_has_error(root))
    analysis_declarations(root, source, options.main_path, &result);
  if (options.require_main && !result.has_main &&
      (!options.owner_key || !strcmp(options.owner_key, "root"))) {
    dyn_diagnostic_source("error", source, 0, 0,
                          "executable module requires 'fn main()' in main.dyn");
    ++result.errors;
  }
  dyn_timing_phase(&source->context, &phase, "parse");
  if (dyn_work_step(&source->context, 1) && (!result.errors || options.recover)) {
    dyn_ast_lower_source(root, source, ast, &result.errors, options.owner_key);
    dyn_timing_phase(&source->context, &phase, "ast");
    if (!ast->allocation_failed && (ast->struct_count || ast->enum_count ||
                                    ast->function_count || ast->global_count))
      if (!dyn_sema_function(ast, source, &result.errors) && !result.errors)
        ast->allocation_failed = true;
    dyn_timing_phase(&source->context, &phase, "sema");
  }
  if (!dyn_work_step(&source->context, 1)) {
    dyn_diagnostic_source("error", source, 0, 0, "analysis work budget exceeded or cancelled");
    ++result.errors;
  }
  if (ast->allocation_failed && !result.errors) {
    dyn_diagnostic_source("error", source, 0, 0, "out of memory");
    ++result.errors;
  }
  ts_tree_delete(tree);
  result.checked = !result.errors;
  return result;
}
