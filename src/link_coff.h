#ifndef DYN_LINK_COFF_H
#define DYN_LINK_COFF_H
#include <stdbool.h>
#include <stddef.h>
typedef struct {
  bool shared; /* A DLL instead of an executable. */
  const char *entry; /* Entry symbol: "dyn_start", or "DllMainCRTStartup" for DLLs. */
  const char *dll_name; /* Name in the DLL's export table and import library. */
  const char *import_library; /* Where to write the DLL's import library, or NULL. */
} DynCoffOptions;
/* Links x86-64 and ARM64 COFF objects and archives (including short import objects)
   into a PE executable or DLL at output. Prints a diagnostic and returns
   nonzero on failure. */
int dyn_link_coff(const char *const *inputs, size_t input_count, const char *output, const DynCoffOptions *options);
/* Whether the built-in PE linker reads this input. */
bool dyn_link_coff_supported(const char *path);
#endif
