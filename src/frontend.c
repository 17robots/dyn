#define _POSIX_C_SOURCE 200809L
#include "frontend.h"
#include "dyn_timing.h"
#include "dyn_compact.h"
#include "sema.h"
#include "parser.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Entry declarations: original byte spans keep diagnostics in the right file. */
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
typedef enum { COMPACT_DECL_USED, COMPACT_DECL_FAILED } CompactDeclarationStatus;
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
/* Partition i of a merged source starts at its map; a reflection prelude
   precedes the maps. Unmerged sources are one partition at zero. */
static uint32_t analysis_partition_start(const DynSource *source, size_t i) {
  if (!source->syntax_part_count) return 0;
  size_t prelude = source->syntax_part_count - source->map_count;
  return i < prelude ? 0 : (uint32_t)source->maps[i - prelude].start;
}
DynAnalysisResult dyn_analyze(const DynSource *source, DynAstProgram *ast,
                              DynAnalysisOptions options) {
  DynAnalysisResult result = {0};
  memset(ast, 0, sizeof(*ast));
  if (!source->compact && !source->syntax_part_count) {
    /* An unprepared text: parse a private copy of its description. */
    DynSource prepared = *source;
    if (!dyn_source_prepare(&prepared) && !prepared.compact) {
      if (prepared.syntax_too_deep)
        dyn_diagnostic_source("error", source, 0, 0, "syntax nesting exceeds 1024 tree levels");
      else if (!dyn_source_report_syntax(&prepared))
        dyn_diagnostic_source("error", source, 0, 0, "failed to parse Dyn source");
      result.errors = 1;
      return result;
    }
    result = dyn_analyze(&prepared, ast, options);
    exp_snapshot_release(prepared.compact);
    return result;
  }
  struct timespec phase = dyn_timing_start(&source->context);
  size_t count = source->syntax_part_count ? source->syntax_part_count : 1;
  for (size_t i = 0; i < count; ++i)
    if (!exp_snapshot_tree(source->syntax_part_count ? source->compact_parts[i] : source->compact)) {
      dyn_diagnostic_source("error", source, 0, 0, "failed to parse Dyn source");
      result.errors = 1;
      return result;
    }
  result.parsed = true;
  /* Recovered syntax errors; editors still lower the partial trees. */
  bool syntax_error = false;
  for (size_t i = 0; i < count; ++i) {
    const ExpSnapshotTree *tree = exp_snapshot_tree(source->syntax_part_count ? source->compact_parts[i] : source->compact);
    uint32_t start = analysis_partition_start(source, i);
    for (uint32_t e = 0; e < tree->error_count; ++e) {
      syntax_error = true;
      if (result.errors >= DYN_SYNTAX_ERROR_LIMIT) break;
      dyn_report_syntax_error(source, start + tree->errors[e].offset,
                              tree->errors[e].message, tree->errors[e].expected);
      ++result.errors;
    }
  }
  if (!syntax_error)
    for (size_t i = 0; i < count; ++i) {
      const ExpSnapshotTree *tree = exp_snapshot_tree(source->syntax_part_count ? source->compact_parts[i] : source->compact);
      if (analysis_compact_tree(source, analysis_partition_start(source, i), tree->nodes,
                                tree->root, options.main_path, &result) == COMPACT_DECL_FAILED)
        return result;
    }
  if (options.require_main && !result.has_main &&
      (!options.owner_key || !strcmp(options.owner_key, "root"))) {
    dyn_diagnostic_source("error", source, 0, 0,
                          "executable module requires 'fn main()' in main.dyn");
    ++result.errors;
  }
  dyn_timing_phase(&source->context, &phase, "parse");
  if (dyn_work_step(&source->context, 1) && (!result.errors || options.recover)) {
    dyn_ast_lower_compact(source, ast, &result.errors, options.owner_key);
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
  return result;
}
