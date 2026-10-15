#ifndef DYN_LINK_ELF_H
#define DYN_LINK_ELF_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
  uint64_t from, to, weight;
} DynLinkEdge;
/* Orders call-graph nodes for locality, writing node indexes to order. */
typedef bool (*DynLinkLayout)(const uint64_t *sizes, const uint64_t *counts, size_t node_count,
                              const DynLinkEdge *edges, const uint64_t *offsets, size_t edge_count,
                              uint64_t *order);
typedef struct {
  bool shared; /* A shared library instead of an executable. */
  const char *entry; /* Executable entry symbol. */
  const char *interpreter; /* Dynamic loader, for executables using shared libraries. */
  DynLinkLayout layout; /* Orders code by a call-graph profile; may be NULL. */
} DynLinkOptions;
/* Links x86-64 objects, archives, shared libraries and GNU linker scripts
   into an executable or shared library at output. Prints a diagnostic and
   returns nonzero on failure. */
int dyn_link_elf(const char *const *inputs, size_t input_count, const char *output, const DynLinkOptions *options);
/* Whether the built-in linker reads this input: x86-64 objects, archives,
   shared libraries and linker scripts. */
bool dyn_link_elf_supported(const char *path);
/* Global symbol names that objects, archive members and shared libraries
   define or reference; unreadable inputs are skipped. */
bool dyn_link_elf_symbols(const char *const *inputs, size_t input_count, char ***defined, size_t *defined_count,
                          char ***used, size_t *used_count);
void dyn_link_elf_names_free(char **names, size_t count);
#ifdef __cplusplus
}
#endif
#endif
