#define _POSIX_C_SOURCE 200809L
#include "frontend.h"
#include "dyn_timing.h"
#include "dyn_syntax.h"
#include "dyn_compact.h"
#include "sema.h"
#ifdef DYN_EXPERIMENT_COMPACT_DECLARATIONS
#include "../tools/parser-experiment/parser.h"
#endif
#include <stdio.h>
#include <stdlib.h>
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
/* Declaration readers supply original byte spans; entry policy and diagnostics
   stay shared during the compact-parser consumer qualification. */
static void analysis_main(const DynSource *s, const char *main_path,
                          uint32_t name_start, uint32_t name_end,
                          uint32_t start, uint32_t end, bool has_signature,
                          DynAnalysisResult *r) {
  if (r->has_main) {
    dyn_diagnostic_source("error", s, name_start, name_end, "duplicate function 'main'");
    ++r->errors;
  }
  r->has_main = true;
  const char *path;
  unsigned line, column;
  dyn_source_location(s, name_start, &path, &line, &column);
  r->main_valid = !main_path || !strcmp(path, main_path);
  if (!r->main_valid) {
    dyn_diagnostic_source("error", s, name_start, name_end,
                          "entry function must be declared in main.dyn");
    ++r->errors;
  }
  if (has_signature) {
    dyn_diagnostic_source("error", s, start, end,
                          "entry signature must be exactly 'fn main()'");
    ++r->errors;
  }
}
#ifdef DYN_EXPERIMENT_COMPACT_DECLARATIONS
static bool compact_work(void *data, uint64_t units) {
  return dyn_work_step(data, units);
}
typedef enum { COMPACT_DECL_FALLBACK, COMPACT_DECL_USED, COMPACT_DECL_FAILED } CompactDeclarationStatus;
static CompactDeclarationStatus analysis_compact_tree(
    const DynSource *s, uint32_t start, const ExpNode *nodes, uint32_t root,
    const char *main_path, DynAnalysisResult *r) {
  for (uint32_t id = nodes[root].first; id != UINT32_MAX; id = nodes[id].next) {
    if (!dyn_work_step(&s->context, 1)) goto cancelled;
    const ExpNode *wrapper = &nodes[id];
    if (wrapper->kind != SRC_DECLARATION || wrapper->first == UINT32_MAX) continue;
    const ExpNode *declaration = &nodes[wrapper->first];
    if (declaration->kind != SRC_FN) continue;
    if (declaration->first == UINT32_MAX) continue;
    const ExpNode *name = &nodes[declaration->first];
    if (name->field != EXP_ROLE_NAME || name->end - name->start != 4 ||
        memcmp(s->text + start + name->start, "main", 4)) continue;
    bool signature = false;
    for (uint32_t child = name->next; child != UINT32_MAX; child = nodes[child].next) {
      if (!dyn_work_step(&s->context, 1)) goto cancelled;
      const ExpNode *n = &nodes[child];
      if (n->kind == SRC_FN_PARAM || n->kind == EXP_TYPE) { signature = true; break; }
    }
    analysis_main(s, main_path, start + name->start, start + name->end,
                  start + declaration->start, start + declaration->end, signature, r);
  }
  return COMPACT_DECL_USED;
cancelled:
  dyn_diagnostic_source("error", s, 0, 0, "analysis work budget exceeded or cancelled");
  ++r->errors;
  return COMPACT_DECL_FAILED;
}
/* This opt-in transition reads one complete, already validated source partition.
   The existing parser still owns syntax errors, recovery and raw-tree depth policy.
   Internal parser coverage/depth limits fall back to the existing declaration
   reader; allocation failure and external cancellation never do. */
static CompactDeclarationStatus analysis_compact_declarations(
    const DynSource *s, uint32_t start, uint32_t end,
    const char *main_path, DynAnalysisResult *r) {
  ExpTree tree = {0};
  ExpOptions options = {.work = compact_work, .data = (void *)&s->context};
  if (!exp_parse_source_with_options(s->text + start, end - start, &tree, &options)) {
    ExpError kind = tree.error_kind;
    exp_free(&tree);
    if (kind != EXP_ALLOCATION_ERROR && kind != EXP_CANCELLED)
      return COMPACT_DECL_FALLBACK;
    dyn_diagnostic_source("error", s, 0, 0, kind == EXP_ALLOCATION_ERROR
        ? "out of memory" : "analysis work budget exceeded or cancelled");
    ++r->errors;
    return COMPACT_DECL_FAILED;
  }
  CompactDeclarationStatus status = analysis_compact_tree(s, start, tree.nodes,
      tree.root, main_path, r);
  exp_free(&tree);
  return status;
}
#endif
static void analysis_declarations(TSNode root, const DynSource *s,
                                  const char *main_path, DynAnalysisResult *r) {
  for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
    TSNode d = dyn_syntax_declaration_node(ts_node_named_child(root, i));
    const char *k = ts_node_type(d);
    if (!strcmp(k, "comment") || !strcmp(k, "use") || !strcmp(k, "struct") ||
        !strcmp(k, "enum") || !strcmp(k, "variable") ||
        !strcmp(k, "const_variable") || !strcmp(k, "type_alias") ||
        !strcmp(k, "extern_fn") || !strcmp(k, "extern_variable") ||
        !strcmp(k, "static_assert") || !strcmp(k, "target_directive") || !strcmp(k, "link_directive"))
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
    bool signature = false;
    for (uint32_t j = 0; j < ts_node_named_child_count(d); ++j) {
      const char *ck = ts_node_type(ts_node_named_child(d, j));
      if (!strcmp(ck, "fn_param") || !strcmp(ck, "type")) { signature = true; break; }
    }
    analysis_main(s, main_path, ts_node_start_byte(name), ts_node_end_byte(name),
                  ts_node_start_byte(d), ts_node_end_byte(d), signature, r);
  }
}
DynAnalysisResult dyn_analyze(const DynSource *source, DynAstProgram *ast,
                              DynAnalysisOptions options) {
  DynAnalysisResult result = {0};
  memset(ast, 0, sizeof(*ast));
  struct timespec phase = dyn_timing_start(&source->context);
  /* Copies: trees may be shared by concurrent module builds. */
  size_t count = source->syntax_part_count ? source->syntax_part_count : 1;
  bool certified = false;
#ifdef DYN_EXPERIMENT_COMPACT_AST
  certified = source->compact_only && !options.recover &&
              (!source->context.work || source->context.strict_syntax) && !source->context.syntax_cache;
#endif
  TSTree **trees = certified ? NULL : calloc(count, sizeof(*trees));
  TSNode *roots = certified ? NULL : calloc(count, sizeof(*roots));
  bool parsed = certified || (trees && roots);
  for (size_t i = 0; !certified && parsed && i < count; ++i) {
    if (!source->syntax_part_count) trees[i] = dyn_source_tree(source);
    else if (source->syntax_parts[i]) trees[i] = ts_tree_copy(source->syntax_parts[i]);
#ifdef DYN_EXPERIMENT_COMPACT_AST
    else if (source->compact_only && source->compact_parts && source->compact_parts[i]) {
      /* A later recovery request explicitly reconstructs its original partition. */
      ExpSnapshot *part=source->compact_parts[i];
      trees[i]=dyn_syntax_reparse_context(exp_snapshot_text(part),exp_snapshot_length(part),NULL,NULL,&source->context);
      if (trees[i]) {
        size_t prelude=count-source->map_count;
        uint32_t start=i<prelude ? 0 : (uint32_t)source->maps[i-prelude].start;
        TSPoint point=dyn_syntax_advance((TSPoint){0},source->text,start);
        TSInputEdit shift={0,0,start,{0},{0},point};
        ts_tree_edit(trees[i],&shift);
      }
    }
#endif
    parsed = trees[i] != NULL;
    if (parsed)
      roots[i] = ts_tree_root_node(trees[i]);
  }
  if (!parsed) {
    dyn_diagnostic_source("error", source, 0, 0, "failed to parse Dyn source");
    result.errors = 1;
    goto done;
  }
  result.parsed = true;
  bool syntax_error = false;
  for (size_t i = 0; !certified && i < count; ++i) {
    analysis_parse_errors(roots[i], source, &result.errors);
    syntax_error |= ts_node_has_error(roots[i]);
  }
  if (!syntax_error) {
    for (size_t i = 0; i < count; ++i) {
#ifdef DYN_EXPERIMENT_COMPACT_DECLARATIONS
      /* Merged source trees preserve file boundaries. Parse the same byte
         partitions: concatenating imports or optional return types can change
         their interpretation across a file boundary. Unknown partition shapes
         keep the existing reader. */
      bool compact = !options.recover;
      size_t start = 0, end = source->length;
      if (source->syntax_part_count) {
        compact &= source->map_count &&
            (count == source->map_count || count == source->map_count + 1);
        if (compact) {
          size_t prelude = count - source->map_count;
          if (prelude && !i) end = source->maps[0].start;
          else {
            start = source->maps[i - prelude].start;
            end = source->maps[i - prelude].end;
          }
        }
      }
      if (compact && start <= end && end <= source->length && end <= UINT32_MAX) {
        CompactDeclarationStatus status;
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
        const ExpSnapshotTree *prepared = exp_snapshot_tree(source->syntax_part_count
            ? (source->compact_parts ? source->compact_parts[i] : NULL) : source->compact);
        if (prepared)
          status = analysis_compact_tree(source, (uint32_t)start, prepared->nodes,
              prepared->root, options.main_path, &result);
        else
#endif
          status = analysis_compact_declarations(
              source, (uint32_t)start, (uint32_t)end, options.main_path, &result);
        if (status == COMPACT_DECL_FAILED) goto done;
        if (status == COMPACT_DECL_USED) continue;
      }
#endif
      analysis_declarations(roots[i], source, options.main_path, &result);
    }
  }
  if (options.require_main && !result.has_main &&
      (!options.owner_key || !strcmp(options.owner_key, "root"))) {
    dyn_diagnostic_source("error", source, 0, 0,
                          "executable module requires 'fn main()' in main.dyn");
    ++result.errors;
  }
  dyn_timing_phase(&source->context, &phase, "parse");
  if (dyn_work_step(&source->context, 1) && (!result.errors || options.recover)) {
#ifdef DYN_EXPERIMENT_COMPACT_AST
    /* Recovery keeps the editor's established syntax lowering even for complete files. */
    DynSource lowering_source = *source;
    if (options.recover) { lowering_source.compact = NULL; lowering_source.compact_parts = NULL; }
    if (certified)
      dyn_ast_lower_compact(&lowering_source, ast, &result.errors, options.owner_key);
    else
      dyn_ast_lower_roots(roots, count, &lowering_source, ast, &result.errors, options.owner_key);
#else
    dyn_ast_lower_roots(roots, count, source, ast, &result.errors, options.owner_key);
#endif
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
  result.checked = !result.errors;
done:
  for (size_t i = 0; trees && i < count; ++i)
    if (trees[i])
      ts_tree_delete(trees[i]);
  free(trees);
  free(roots);
  return result;
}
