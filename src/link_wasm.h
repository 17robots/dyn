#ifndef DYN_LINK_WASM_H
#define DYN_LINK_WASM_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
int dyn_link_wasm_objects(const char *const *paths, size_t count,
                          const char *output,
                          const char *const *allowed_imports,
                          size_t import_count, bool wasi, uint32_t max_memory,
                          bool verbose);
#endif
