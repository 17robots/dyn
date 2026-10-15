#ifndef DYN_LINK_ELF_H
#define DYN_LINK_ELF_H
#include <stdbool.h>
#include <stddef.h>
/* Links x86-64 relocatable objects and archives into a static executable at
   output. Prints a diagnostic and returns nonzero on failure. */
int dyn_link_elf(const char *const *inputs, size_t input_count, const char *output, const char *entry);
/* Whether the built-in linker reads this input: objects and archives, not
   shared libraries or linker scripts. */
bool dyn_link_elf_supported(const char *path);
#endif
