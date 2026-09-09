#ifndef DYN_H
#define DYN_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Single honest target seam. Keep target-specific policy out of CLI/backend. */
typedef struct {
  const char *name, *triple, *dynamic_linker;
  const char *arch, *kernel, *abi, *libc, *endian, *pointer_bits;
  bool executable_link;
} DynTarget;

extern const DynTarget *dyn_target;
bool dyn_target_select(const char *name);
const char *dyn_target_property(const DynTarget *target, const char *key);
bool dyn_target_syscall_number(uint64_t source, uint64_t *native);

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
  bool warnings_as_errors;
  bool no_warnings;
  bool timings;
  bool no_cache;
  bool format_check;
  bool json_diagnostics;
  unsigned jobs;
  const char *link_inputs[64];
  size_t link_input_count;
} DynOptions;

typedef struct {
  char *path;
  char *text;
  size_t length;
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
   concurrent calls. Values are returned in source order, never completion order. */
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
int dyn_sources_load(const char *directory, DynSources *sources);
void dyn_sources_free(DynSources *sources);
int dyn_source_target_enabled(const DynSource *source);
int dyn_sources_merge(const DynSources *sources, const char *module_name,
                      DynSource *merged);
void dyn_source_free(DynSource *source);
DynCheckResult dyn_check_sources(const DynSources *sources,
                                 const char *main_path, bool require_main);
int dyn_codegen_main(const DynSource *source, const char *object_path,
                     const char *ir_path, const char *asm_path, bool release,
                     bool debug_info);
/* owner_key is "root" or a rewritten dyn_m<hash> prefix. NULL emits one
   monolithic object. Every object sees the full typed program, but defines
   only symbols owned by owner_key. */
int dyn_codegen_module(const DynSource *source, const char *object_path,
                       const char *ir_path, const char *asm_path, bool release,
                       bool debug_info, const char *owner_key);
int dyn_link_executable(const char *object_path, const char *output_path,
                        const char *const *link_inputs, size_t link_input_count,
                        bool release, bool verbose);
int dyn_link_executable_objects(const char *const *object_paths,
                                size_t object_count, const char *output_path,
                                const char *const *link_inputs,
                                size_t link_input_count, bool release,
                                bool verbose);
char *dyn_path_join(const char *left, const char *right);
char *dyn_path_basename(const char *path);
bool dyn_path_is_directory(const char *path);
int dyn_module_validate_imports(const char *project_root,
                                const DynSources *root_sources);
int dyn_module_load_project(const char *project_root,
                            const DynSources *root_sources,
                            DynSources *project_sources);
int dyn_module_rewrite_project(const char *project_root, DynSources *sources);
char *dyn_module_resolve_import(const char *project_root, const char *current,
                                const char *path);
bool dyn_cache_hit(const DynSources *sources, const DynOptions *options,
                   const char *compiler_path, const char *output);
bool dyn_cache_fast_hit(const DynOptions *options, const char *compiler_path,
                        const char *output);
bool dyn_cache_directory(char *path, size_t capacity);
int dyn_cache_command(const char *action);
void dyn_cache_store(const DynSources *sources, const DynOptions *options,
                     const char *compiler_path, const char *output);
bool dyn_object_cache_restore(const DynSources *sources,
                              const DynOptions *options,
                              const char *compiler_path, const char *output,
                              const char *object);
void dyn_object_cache_store(const DynSources *sources, const DynOptions *options,
                            const char *compiler_path, const char *output,
                            const char *object);
bool dyn_module_cache_restore(const DynSources *, size_t first, size_t count,
                              const DynOptions *, const char *compiler_path,
                              const char *cache_root, const char *object);
void dyn_module_cache_store(const DynSources *, size_t first, size_t count,
                            const DynOptions *, const char *compiler_path,
                            const char *cache_root, const char *object);
void dyn_diagnostic_mode(bool json);
void dyn_diagnostic(const char *, const char *, unsigned, unsigned, unsigned,
                    unsigned, const char *);
int dyn_format_directory(const char *, bool);
int dyn_docs_directory(const char *);
int dyn_lsp(void);

#endif
