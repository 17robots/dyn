#ifndef DYN_H
#define DYN_H

#define DYN_FRONTEND_VERSION "7"
#define DYN_FRONTEND_STAMP "dyn-c-frontend-" DYN_FRONTEND_VERSION

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>
#include "host.h"

/* Single honest target seam. Keep target-specific policy out of CLI/backend. */
typedef struct {
  const char *name, *triple, *dynamic_linker;
  const char *arch, *kernel, *abi, *libc, *endian, *pointer_bits;
  bool executable_link;
} DynTarget;

unsigned dyn_target_pointer_bytes(const DynTarget *target);
const DynTarget *dyn_target_find(const char *name);
const char *dyn_target_property(const DynTarget *target, const char *key);
bool dyn_target_syscall_number(const DynTarget *target, uint64_t source,
                               uint64_t *native);

typedef struct DynSyntaxCacheEntry DynSyntaxCacheEntry;
typedef struct {
  DynSyntaxCacheEntry *entries;
  size_t count, bytes;
  uint64_t hits, misses;
} DynSyntaxCache;
void dyn_syntax_cache_clear(DynSyntaxCache *);

typedef void (*DynDiagnosticSink)(const char *, const char *, unsigned,
                                  unsigned, unsigned, unsigned, const char *,
                                  void *);
/* Borrowed cooperative frontend budget. A stopped analysis must not enter a
   semantic cache. Units cover input bytes and traversal checkpoints, not wall
   time. Deadlines use process CPU time; blocking filesystem I/O is not preempted. */
typedef enum { DYN_WORK_RUNNING, DYN_WORK_LIMIT, DYN_WORK_CANCELLED } DynWorkStatus;
typedef struct {
  uint64_t remaining, until_poll;
  clock_t deadline;
  bool (*cancelled)(void *);
  void *data;
  DynWorkStatus status;
  bool reported;
} DynWork;
/* Copyable compilation policy. Target is immutable; diagnostic storage is
   borrowed for the duration of analysis. No process-global compiler state. */
typedef struct {
  const DynTarget *target;
  DynDiagnosticSink diagnostic;
  void *diagnostic_data;
  bool json_diagnostics;
  bool timings;
  DynWork *work; /* Borrowed, never owned by a source or cached snapshot. */
  DynSyntaxCache *syntax_cache; /* Optional owner-scoped immutable source trees. */
} DynContext;
static inline bool dyn_work_step(const DynContext *context, uint64_t units) {
  DynWork *w = context ? context->work : NULL;
  if (!w) return true;
  if (w->status) return false;
  if (units > w->remaining) { w->status = DYN_WORK_LIMIT; return false; }
  w->remaining -= units;
  if (units < w->until_poll) { w->until_poll -= units; return true; }
  w->until_poll = 1024;
  if (w->cancelled && w->cancelled(w->data)) w->status = DYN_WORK_CANCELLED;
  else if (w->deadline && clock() >= w->deadline) w->status = DYN_WORK_LIMIT;
  return !w->status;
}
static inline const DynTarget *dyn_context_target(const DynContext *context) {
  return context && context->target ? context->target
                                    : dyn_target_find(DYN_HOST_TARGET);
}

typedef struct {
  const char *command;
  const char *input;
  const char *output;
  const char *target;
  bool release;
  bool debug_info;
  bool debug_info_set;
  bool quiet;
  bool verbose;
  bool emit_ir;
  bool emit_object;
  bool emit_asm;
  bool no_link;
  bool shared;
  bool warnings_as_errors;
  bool no_warnings;
  bool timings;
  bool no_cache;
  bool format_check;
  bool docs_json;
  bool json_diagnostics;
  unsigned jobs;
  uint64_t max_work;
  uint64_t compiler_hash; /* Command-scoped cache identity, inherited by workers. */
  const char *link_inputs[64];
  size_t link_input_count;
} DynOptions;

typedef struct {
  size_t generated_start, generated_end;
  size_t original_start, original_end;
} DynSourceSpan;
typedef struct {
  char *path;
  size_t start, end;
  char *original_text;
  size_t original_length;
  DynSourceSpan *spans;
  size_t span_count;
} DynSourceMap;
typedef struct TSTree TSTree;
typedef struct {
  char *path;
  char *text;
  size_t length;
  char *original_text;
  size_t original_length;
  DynSourceSpan *spans;
  size_t span_count;
  DynContext context;
  TSTree *syntax; /* Owned, immutable tree for this exact text revision. */
  bool syntax_too_deep;
  bool needs_reflection; /* Synthetic interface dependency on the compiler ABI.
                          */
  DynSourceMap *maps;
  size_t map_count;
  /* First source of each rewritten module owns its transitive dependencies,
     captured from resolved imports. Indices refer to the containing project. */
  size_t *dependency_sources;
  size_t dependency_count;
  uint64_t dependency_hash;
} DynSource;

typedef struct {
  DynSource *items;
  size_t count;
} DynSources;

/* Versioned, canonical public module interface. The payload is owned by the
   value and contains newline-separated declarations; no function bodies. */
typedef struct {
  char *data;
  size_t length;
  uint64_t source_hash, interface_hash;
} DynInterface;
typedef enum {
  DYN_INTERFACE_HIT,
  DYN_INTERFACE_MISS,
  DYN_INTERFACE_ERROR
} DynInterfaceStatus;
uint64_t dyn_interface_source_hash(const DynSources *);
int dyn_interface_build(const DynSources *, DynInterface *);
int dyn_interface_store(const char *, const char *target,
                        const char *compiler_schema, const DynInterface *);
DynInterfaceStatus dyn_interface_load(const char *, const char *target,
                                      const char *compiler_schema,
                                      uint64_t source_hash, DynInterface *);
void dyn_interface_free(DynInterface *);
int dyn_interface_compose(const DynSources *, size_t owner_first,
                          size_t owner_count, const DynInterface *,
                          size_t interface_count, const char *path,
                          DynSource *);

/* Jobs receive one canonical, contiguous module slice. Context must be safe for
   concurrent calls. Values are returned in source order, never completion
   order. */
typedef int (*DynModuleBuildFn)(const DynSources *, size_t, size_t, void *,
                                uint64_t *);
int dyn_build_plan_run(const DynSources *, unsigned, DynModuleBuildFn, void *,
                       uint64_t **, size_t *);

typedef struct {
  bool has_main;
  bool main_valid;
  unsigned errors;
} DynCheckResult;

int dyn_cli_parse(int argc, char **argv, DynOptions *options);
void dyn_cli_help(const char *command);
int dyn_sources_load(const DynContext *context, const char *directory,
                     DynSources *sources);
void dyn_sources_free(DynSources *sources);
int dyn_source_target_enabled(const DynSource *source);
int dyn_sources_merge(const DynSources *sources, const char *module_name,
                      DynSource *merged);
/* Prepare caches a tree; tree returns an independently owned tree reference.
   Discard syntax before mutating source text. */
bool dyn_source_prepare(DynSource *);
TSTree *dyn_source_tree(const DynSource *);
void dyn_source_discard_syntax(DynSource *);
void dyn_source_free(DynSource *source);
void dyn_source_position(const DynSource *, size_t, const char **,
                         const char **, size_t *, size_t *);
void dyn_source_location(const DynSource *source, size_t byte,
                         const char **path, unsigned *line, unsigned *column);
DynCheckResult dyn_check_sources(const DynSources *sources,
                                 const char *main_path, bool require_main);
int dyn_codegen_main(const DynSource *source, const char *object_path,
                     const char *ir_path, const char *asm_path, bool release,
                     bool debug_info, bool shared);
/* owner_key is "root" or a rewritten dyn_m<hash> prefix. NULL emits one
   monolithic object. Every object sees the full typed program, but defines
   only symbols owned by owner_key. */
int dyn_codegen_module(const DynSource *source, const char *object_path,
                       const char *ir_path, const char *asm_path, bool release,
                       bool debug_info, bool shared, const char *owner_key);
int dyn_link_executable(const DynContext *context, const char *object_path,
                        const char *output_path, const char *const *link_inputs,
                        size_t link_input_count, bool release, bool verbose);
int dyn_link_executable_objects(const DynContext *context,
                                const char *const *object_paths,
                                size_t object_count, const char *output_path,
                                const char *const *link_inputs,
                                size_t link_input_count, bool release,
                                bool verbose);
int dyn_link_shared(const DynContext *context, const char *object_path,
                    const char *output_path, const char *const *link_inputs,
                    size_t link_input_count, bool verbose);
char *dyn_path_join(const char *left, const char *right);
char *dyn_path_basename(const char *path);
bool dyn_path_is_directory(const char *path);
int dyn_module_validate_imports(const char *project_root,
                                const DynSources *root_sources);
int dyn_module_load_project(const char *project_root,
                            const DynSources *root_sources,
                            DynSources *project_sources);
int dyn_module_load_project_overlay(const char *project_root,
                                    const DynSources *root_sources,
                                    const DynSources *overrides,
                                    DynSources *project_sources);
int dyn_module_rewrite_project(const char *project_root, DynSources *sources);
char *dyn_module_resolve_import(const DynContext *, const char *project_root,
                                const char *current, const char *path);
bool dyn_cache_hit(const DynSources *sources, const DynOptions *options,
                   const char *compiler_path, const char *output);
bool dyn_cache_fast_hit(const DynOptions *options, const char *compiler_path,
                        const char *output);
uint64_t dyn_cache_compiler_hash(const char *compiler_path);
bool dyn_cache_directory(char *path, size_t capacity);
int dyn_cache_command(const char *action);
void dyn_cache_store(const DynSources *sources, const DynOptions *options,
                     const char *compiler_path, const char *output);
bool dyn_object_cache_restore(const DynSources *sources,
                              const DynOptions *options,
                              const char *compiler_path, const char *output,
                              const char *object);
void dyn_object_cache_store(const DynSources *sources,
                            const DynOptions *options,
                            const char *compiler_path, const char *output,
                            const char *object);
bool dyn_module_cache_restore(const DynSources *, size_t first, size_t count,
                              const DynOptions *, const char *compiler_path,
                              const char *cache_root, const char *object);
void dyn_module_cache_store(const DynSources *, size_t first, size_t count,
                            const DynOptions *, const char *compiler_path,
                            const char *cache_root, const char *object);
void dyn_diagnostic(const DynContext *, const char *, const char *, unsigned,
                    unsigned, unsigned, unsigned, const char *);
void dyn_diagnostic_source(const char *severity, const DynSource *source,
                           size_t start, size_t end, const char *message);
bool dyn_format_source(const DynSource *, char **, size_t *);
int dyn_format_directory(const char *, bool);
int dyn_docs_directory(const char *, bool);
int dyn_query_sources(const DynSources *, const char *);
int dyn_lsp(const DynTarget *target);

#endif
