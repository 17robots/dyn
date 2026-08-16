#ifndef DYN_H
#define DYN_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
  const char *command;
  const char *input;
  const char *output;
  const char *target;
  bool release;
  bool quiet;
  bool verbose;
  bool emit_ir;
  bool emit_object;
  bool emit_asm;
  bool no_link;
  bool warnings_as_errors;
  bool no_warnings;
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

typedef struct {
  bool has_main;
  bool main_valid;
  unsigned errors;
} DynCheckResult;

int dyn_cli_parse(int argc, char **argv, DynOptions *options);
void dyn_cli_help(const char *command);
int dyn_sources_load(const char *directory, DynSources *sources);
void dyn_sources_free(DynSources *sources);
int dyn_sources_merge(const DynSources *sources, const char *module_name,
                      DynSource *merged);
void dyn_source_free(DynSource *source);
DynCheckResult dyn_check_sources(const DynSources *sources,
                                 const char *main_path, bool require_main);
int dyn_codegen_main(const DynSource *source, const char *object_path,
                     const char *ir_path, const char *asm_path, bool release);
int dyn_link_executable(const char *object_path, const char *output_path,
                        const char *const *link_inputs, size_t link_input_count,
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

#endif
