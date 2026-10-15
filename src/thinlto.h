#ifndef DYN_THINLTO_H
#define DYN_THINLTO_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "link_elf.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Release link-time optimization over ThinLTO bitcode, run in-process.
   Symbols that non-bitcode inputs define or use stay visible; all others may
   be internalized. */
typedef struct {
  const char *const *bitcode;
  size_t bitcode_count;
  const char *const *regular_defined;
  size_t regular_defined_count;
  const char *const *regular_used;
  size_t regular_used_count;
  unsigned level, jobs; /* jobs 0: one per core. */
  bool aggressive_codegen, remarks;
  const char *sample_profile, *cache_directory; /* Either may be NULL. */
  const char *output_prefix; /* Objects are written to <prefix>.lto.<n>.o. */
} DynThinLto;
/* Writes native objects and returns their paths; 0 on success. */
int dyn_thinlto_link(const DynThinLto *options, char ***objects, size_t *object_count);
/* Cache-directed function layout, as lld applies to call-graph profiles;
   matches DynLinkLayout. */
bool dyn_cache_directed_layout(const uint64_t *sizes, const uint64_t *counts, size_t node_count,
                               const DynLinkEdge *edges, const uint64_t *offsets, size_t edge_count,
                               uint64_t *order);
/* Removes the objects and frees the list. */
void dyn_thinlto_free(char **objects, size_t count);
#ifdef __cplusplus
}
#endif
#endif
