#ifndef DYN_LINK_MACHO_H
#define DYN_LINK_MACHO_H
#include <stdbool.h>
#include <stddef.h>
typedef struct {
  bool shared; /* A dylib instead of an executable. */
  const char *entry; /* Executable entry symbol, such as "_dyn_start". */
  const char *install_name; /* Dylib install name; defaults to the output path. */
} DynMachOOptions;
/* Links arm64 Mach-O objects, archives, dylibs, .tbd stubs and "-lName"
   libraries into a signed macOS executable or dylib at output. Prints a
   diagnostic and returns nonzero on failure. */
int dyn_link_macho(const char *const *inputs, size_t input_count, const char *output, const DynMachOOptions *options);
/* Whether the built-in Mach-O linker reads this input. */
bool dyn_link_macho_supported(const char *path);
#endif
