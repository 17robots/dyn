#ifndef DYN_BACKEND_DWARF_H
#define DYN_BACKEND_DWARF_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Debugger DWARF: source lines, functions, RBP frame unwinding, and frame-slot
   parameters/locals with base, pointer, struct, array and enum types. */
enum { BACKEND_DWARF_INFO, BACKEND_DWARF_ABBREV, BACKEND_DWARF_LINE,
       BACKEND_DWARF_FRAME, BACKEND_DWARF_SECTION_COUNT,
       BACKEND_DWARF_TEXT = BACKEND_DWARF_SECTION_COUNT };
typedef struct { unsigned char *data; size_t size, capacity; } BackendDwarfBytes;
typedef struct {
  unsigned section, target, type;
  size_t offset;
  int64_t addend;
} BackendDwarfRelocation;
typedef struct BackendDwarf BackendDwarf;
typedef struct {
  BackendDwarfBytes sections[BACKEND_DWARF_SECTION_COUNT];
  BackendDwarfRelocation *relocations;
  size_t relocation_count, relocation_capacity;
} BackendDwarfOutput;
BackendDwarf *backend_dwarf_create(void);
/* AArch64 frames: stp x29, x30, [sp, #-16]!; mov x29, sp ... mov sp, x29; ldp; ret. */
BackendDwarf *backend_dwarf_create_a64(void);
BackendDwarf *backend_dwarf_create_rv64(void);
void backend_dwarf_free(BackendDwarf *);
/* All offsets are relative to this object's .text. Functions cannot overlap.
   x86-64 frames begin with push rbp; mov rbp,rsp and end with leave; ret.
   Epilogue offsets mark the first epilogue instruction. Relocation types
   are x86-64 R_X86_64_32/64; AArch64 writers map them to ABS32/ABS64. */
bool backend_dwarf_begin(BackendDwarf *, size_t begin, const char *name,
                         const char *path, unsigned line, unsigned column);
bool backend_dwarf_line(BackendDwarf *, size_t pc, const char *path,
                        unsigned line, unsigned column, bool prologue_end);
bool backend_dwarf_epilogue(BackendDwarf *, size_t leave_pc);
bool backend_dwarf_end(BackendDwarf *, size_t end);
/* Type ids are nonzero; zero means unknown and suppresses dependent variables.
   Composite types reserve their member slots so nested types may be created
   before the members are filled in. */
unsigned backend_dwarf_base_type(BackendDwarf *, const char *name,
                                 unsigned encoding, unsigned size);
unsigned backend_dwarf_pointer_type(BackendDwarf *, unsigned target);
unsigned backend_dwarf_struct_type(BackendDwarf *, const char *name,
                                   uint64_t size, unsigned members);
bool backend_dwarf_member(BackendDwarf *, unsigned type, unsigned index,
                          const char *name, unsigned member_type, uint64_t offset);
unsigned backend_dwarf_union_type(BackendDwarf *, const char *name,
                                  uint64_t size, unsigned members);
unsigned backend_dwarf_array_type(BackendDwarf *, unsigned element, uint64_t count);
unsigned backend_dwarf_enum_type(BackendDwarf *, const char *name, unsigned base,
                                 uint64_t size, unsigned enumerators);
bool backend_dwarf_enumerator(BackendDwarf *, unsigned type, unsigned index,
                              const char *name, int64_t value);
/* A variable of the active function at a fixed RBP-relative frame offset.
   A nonempty [scope_begin, scope_end) text range nests it in a lexical block;
   otherwise it is visible in the whole function. */
bool backend_dwarf_variable(BackendDwarf *, const char *name, unsigned type,
                            int64_t frame_offset, bool parameter,
                            size_t scope_begin, size_t scope_end);
/* Output must initially be zeroed. Failure frees and zeros every output field.
   Relocation target indexes identify sections above, not ELF symbol indexes;
   callers map these to their final local section symbols. */
bool backend_dwarf_finish(BackendDwarf *, BackendDwarfOutput *);
void backend_dwarf_output_free(BackendDwarfOutput *);
#endif
