#include "dyn.h"
#include "dyn_ast.h"
#include "sema.h"
#include <stdio.h>
#include <string.h>
#include <tree_sitter/api.h>
extern const TSLanguage *tree_sitter_dyn(void);

static bool text_is(TSNode n, const DynSource *s, const char *t) {
  size_t len = strlen(t);
  return ts_node_end_byte(n) - ts_node_start_byte(n) == len &&
         !memcmp(s->text + ts_node_start_byte(n), t, len);
}
static void parse_errors(TSNode n, const DynSource *s, unsigned *errors) {
  if (*errors >= 20)
    return;
  if (ts_node_is_error(n) || ts_node_is_missing(n)) {
    TSPoint p = ts_node_start_point(n);
    char message[160];
    snprintf(message, sizeof(message), "invalid syntax near '%s'", ts_node_type(n));
    TSPoint e = ts_node_end_point(n);
    dyn_diagnostic("error", s->path, p.row + 1, p.column + 1,
                   e.row + 1, e.column + 1, message);
    ++*errors;
    return;
  }
  for (uint32_t i = 0; i < ts_node_child_count(n); ++i)
    parse_errors(ts_node_child(n, i), s, errors);
}
static TSNode check_decl_value(TSNode n) {
  if (!strcmp(ts_node_type(n), "declaration"))
    return ts_node_named_child(n, ts_node_named_child_count(n) - 1);
  return n;
}
static void inspect_declarations(TSNode root, const DynSource *s,
                                 const char *main_path, DynCheckResult *r) {
  for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
    TSNode d = check_decl_value(ts_node_named_child(root, i));
    const char *k = ts_node_type(d);
    if (!strcmp(k, "comment") || !strcmp(k, "use") || !strcmp(k, "struct") ||
        !strcmp(k, "enum") || !strcmp(k, "variable") ||
        !strcmp(k, "const_variable") || !strcmp(k, "type_alias") ||
        !strcmp(k, "extern_fn") || !strcmp(k, "extern_variable") ||
        !strcmp(k, "target_directive"))
      continue;
    if (strcmp(k, "fn")) {
      TSPoint p = ts_node_start_point(d);
      fprintf(stderr,
              "%s:%u:%u: error: '%s' is parsed but not implemented in "
              "bootstrap compiler\n",
              s->path, p.row + 1, p.column + 1, k);
      ++r->errors;
      continue;
    }
    TSNode name = ts_node_child_by_field_name(d, "name", 4);
    if (ts_node_is_null(name) || !text_is(name, s, "main"))
      continue;
    if (r->has_main) {
      fprintf(stderr, "%s: error: duplicate function 'main'\n", s->path);
      ++r->errors;
    }
    r->has_main = true;
    r->main_valid = !strcmp(s->path, main_path);
    if (!r->main_valid) {
      fprintf(stderr,
              "%s: error: entry function must be declared in main.dyn\n",
              s->path);
      ++r->errors;
    }
    for (uint32_t j = 0; j < ts_node_named_child_count(d); ++j) {
      const char *ck = ts_node_type(ts_node_named_child(d, j));
      if (!strcmp(ck, "fn_param") || !strcmp(ck, "type")) {
        TSPoint p = ts_node_start_point(d);
        fprintf(
            stderr,
            "%s:%u:%u: error: entry signature must be exactly 'fn main()'\n",
            s->path, p.row + 1, p.column + 1);
        ++r->errors;
        break;
      }
    }
  }
}
DynCheckResult dyn_check_sources(const DynSources *sources,
                                 const char *main_path, bool require_main) {
  DynCheckResult r = {0};
  TSParser *p = ts_parser_new();
  if (!p || !ts_parser_set_language(p, tree_sitter_dyn())) {
    fprintf(stderr, "error: failed to initialize Dyn parser\n");
    r.errors = 1;
    if (p)
      ts_parser_delete(p);
    return r;
  }
  for (size_t i = 0; i < sources->count; ++i) {
    const DynSource *s = &sources->items[i];
    if (dyn_source_target_enabled(s) == 0) continue;
    TSTree *t = ts_parser_parse_string(p, NULL, s->text, (uint32_t)s->length);
    TSNode root = ts_tree_root_node(t);
    parse_errors(root, s, &r.errors);
    if (!ts_node_has_error(root))
      inspect_declarations(root, s, main_path, &r);
    ts_tree_delete(t);
  }
  ts_parser_delete(p);
  if (require_main && !r.has_main) {
    fprintf(
        stderr,
        "%s:1:1: error: executable module requires 'fn main()' in main.dyn\n",
        main_path);
    ++r.errors;
  }
  if (!r.errors) {
    DynSource merged = {0};
    if (dyn_sources_merge(sources, main_path, &merged)) {
      ++r.errors;
    } else {
      DynAstFunction ast = {0};
      (void)dyn_ast_parse_main_source(&merged, &ast, &r.errors);
      if (ast.struct_count || ast.enum_count || ast.function_count)
        dyn_sema_function(&ast, &merged, &r.errors);
      dyn_ast_function_free(&ast);
      dyn_source_free(&merged);
    }
  }
  return r;
}
