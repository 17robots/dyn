/* Built-in ELF linker, so a build needs no external linker. Inputs are
   relocatable objects, ar archives, shared libraries and GNU linker scripts
   (GROUP/INPUT/AS_NEEDED); the output is a non-PIE executable, dynamic when
   it uses shared libraries, or a shared library. Unused sections are
   removed, matching what the compiler previously asked ld.lld for. The host
   may be any OS, so ELF structures are read field by field instead of
   through <elf.h>. */
#include "link_elf.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

enum {
  ELF_REL = 1, ELF_EXEC = 2, ELF_DYN = 3,
  MACHINE_X86_64 = 62,
  SHT_PROGBITS = 1, SHT_SYMTAB = 2, SHT_STRTAB = 3, SHT_RELA = 4, SHT_NOBITS = 8,
  SHT_REL = 9, SHT_INIT_ARRAY = 14, SHT_FINI_ARRAY = 15, SHT_PREINIT_ARRAY = 16,
  SHT_GROUP = 17, SHT_SYMTAB_SHNDX = 18, SHT_X86_64_UNWIND = 0x70000001,
  SHT_CALL_GRAPH_PROFILE = 0x6fff4c09, SHT_HASH = 5, SHT_DYNAMIC = 6, SHT_DYNSYM = 11,
  SHT_VERDEF = 0x6ffffffd, SHT_VERNEED = 0x6ffffffe, SHT_VERSYM = 0x6fffffff,
  SHF_WRITE = 1, SHF_ALLOC = 2, SHF_EXEC = 4, SHF_GROUP = 0x200, SHF_TLS = 0x400,
  SHF_RETAIN = 0x200000,
  SHN_UNDEF = 0, SHN_ABS = 0xfff1, SHN_COMMON = 0xfff2, SHN_XINDEX = 0xffff,
  STB_LOCAL = 0, STB_GLOBAL = 1, STB_WEAK = 2,
  STT_NOTYPE = 0, STT_OBJECT = 1, STT_FUNC = 2, STT_SECTION = 3, STT_FILE = 4, STT_TLS = 6,
  STT_GNU_IFUNC = 10,
  STV_DEFAULT = 0, STV_PROTECTED = 3,
  PT_LOAD = 1, PT_DYNAMIC = 2, PT_INTERP = 3, PT_PHDR = 6, PT_GNU_STACK = 0x6474e551,
  DT_NULL = 0, DT_NEEDED = 1, DT_HASH = 4, DT_STRTAB = 5, DT_SYMTAB = 6, DT_RELA = 7, DT_RELASZ = 8,
  DT_RELAENT = 9, DT_STRSZ = 10, DT_SYMENT = 11, DT_SONAME = 14, DT_DEBUG = 21, DT_INIT_ARRAY = 25,
  DT_FINI_ARRAY = 26, DT_INIT_ARRAYSZ = 27, DT_FINI_ARRAYSZ = 28, DT_FLAGS = 30, DF_BIND_NOW = 8,
  DT_VERSYM = 0x6ffffff0, DT_FLAGS_1 = 0x6ffffffb, DF_1_NOW = 1, DT_VERNEED = 0x6ffffffe,
  DT_VERNEEDNUM = 0x6fffffff,
  GRP_COMDAT = 1,
};
enum {
  R_X86_64_NONE = 0, R_X86_64_64 = 1, R_X86_64_PC32 = 2, R_X86_64_PLT32 = 4,
  R_X86_64_GOTPCREL = 9, R_X86_64_32 = 10, R_X86_64_32S = 11, R_X86_64_PC64 = 24,
  R_X86_64_SIZE32 = 32, R_X86_64_SIZE64 = 33, R_X86_64_GOTPCRELX = 41,
  R_X86_64_REX_GOTPCRELX = 42, R_X86_64_COPY = 5, R_X86_64_GLOB_DAT = 6, R_X86_64_JUMP_SLOT = 7,
  R_X86_64_RELATIVE = 8,
};
#define PAGE 0x1000u
#define IMAGE_BASE 0x200000u
#define SHF_EXCLUDE 0x80000000u

typedef struct LinkObject LinkObject;
typedef struct {
  uint32_t from, to; /* Symbol indexes. */
  uint64_t weight;
} LinkProfileEdge;
typedef struct LinkSymbol LinkSymbol;
typedef struct {
  uint64_t offset, addend;
  uint32_t type, symbol;
} LinkRela;
/* Allocated outputs in address order: read-only, code, then writable. */
typedef enum {
  OUT_INTERP, OUT_HASH, OUT_DYNSYM, OUT_DYNSTR, OUT_VERSYM, OUT_VERNEED, OUT_RELA_DYN,
  OUT_RODATA, OUT_EH_FRAME, OUT_TEXT, OUT_PLT, OUT_DYNAMIC, OUT_INIT_ARRAY, OUT_FINI_ARRAY,
  OUT_DATA, OUT_GOT, OUT_BSS, OUT_ALLOC_COUNT
} OutputKind;
typedef struct {
  const char *path; /* As given; also the DT_NEEDED name without a soname. */
  const char *soname;
  const char **versions; /* Version names by verdef index. */
  size_t version_count;
  uint32_t name_string; /* Offset in .dynstr. */
  bool as_needed, used;
} LinkShared;
typedef struct {
  LinkObject *object; /* NULL for synthetic sections. */
  const char *name;
  const uint8_t *data;
  uint8_t *owned;
  uint64_t size, align, flags, address, offset; /* offset within its output. */
  uint32_t type, index;
  LinkRela *relas;
  size_t rela_count;
  int output;
  bool live, discarded, eh_frame;
} LinkSection;
struct LinkSymbol {
  const char *name;
  LinkSection *section;
  uint64_t value, size, common_align;
  uint8_t binding, type, visibility;
  bool defined, absolute, common, referenced, strong_reference;
  bool library_reference; /* A loaded shared library uses it. */
  bool canonical; /* Imported function whose address is its PLT entry. */
  bool copied; /* Imported data copied into the executable's .bss. */
  uint32_t got, plt, dynsym; /* One-based slots; 0 when absent. */
  uint32_t dynstr;
  uint16_t version; /* .gnu.version index. */
  /* First shared-library definition, used when no object defines it. */
  LinkShared *shared;
  const char *shared_version;
  uint64_t shared_value, shared_size;
  uint8_t shared_type;
  bool shared_hidden;
  int archive_member; /* Lazy archive member, or -1. */
  size_t archive;
};
typedef struct {
  LinkSection *section;
  uint64_t offset, addend;
  uint32_t type;
  LinkSymbol *symbol;
} DynamicRelocation;
struct LinkObject {
  const char *path;
  const uint8_t *data;
  size_t size;
  LinkSection *sections;
  size_t section_count;
  LinkSymbol **symbols;
  LinkSymbol *locals;
  size_t symbol_count;
  const char *strings;
  LinkProfileEdge *profile; /* .llvm.call-graph-profile entries. */
  size_t profile_count;
};
typedef struct {
  const char *path;
  const uint8_t *data;
  size_t size;
  bool *loaded;
} LinkArchive;
typedef struct {
  char *name;
  LinkSection **sections;
  size_t count, capacity;
  uint64_t align, size, address, file_offset, flags, entry_size;
  uint32_t type, header_index, info;
  int link; /* Output whose section index goes in sh_link, or -1. */
} LinkOutput;
typedef struct {
  const char *output_path;
  char error[512];
  LinkObject **objects;
  size_t object_count, object_capacity;
  LinkArchive *archives;
  size_t archive_count;
  uint8_t **buffers;
  size_t buffer_count, buffer_capacity;
  LinkSymbol **table;
  size_t table_capacity, table_count;
  LinkSection **commons;
  size_t common_count, common_capacity;
  LinkSection got;
  LinkSymbol **got_symbols;
  size_t got_count, got_capacity;
  LinkOutput outputs[OUT_ALLOC_COUNT];
  LinkOutput *extra; /* Non-allocated sections such as DWARF. */
  size_t extra_count, extra_capacity;
  char **signatures;
  size_t signature_count, signature_capacity;
  bool shared_output, dynamic;
  const char *interpreter;
  uint64_t base;
  LinkShared **shareds;
  size_t shared_count, shared_capacity;
  LinkSymbol **plt_symbols, **dynsyms;
  size_t plt_count, plt_capacity, dynsym_count, dynsym_capacity;
  DynamicRelocation *relocations;
  size_t relocation_count, relocation_capacity;
  LinkSection synthetic[OUT_ALLOC_COUNT];
  LinkSection **copies;
  size_t copy_count, copy_capacity;
  struct { LinkShared *library; const char *version; uint32_t string; } *needs;
  size_t need_count, need_capacity;
  uint8_t *dynstr;
  size_t dynstr_size, dynstr_capacity;
  size_t dynamic_entries;
} Linker;

static bool fail(Linker *linker, const char *format, const char *a, const char *b) {
  if (!linker->error[0])
    snprintf(linker->error, sizeof(linker->error), format, a, b);
  return false;
}
static uint16_t read16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static uint32_t read32(const uint8_t *p) { return (uint32_t)read16(p) | (uint32_t)read16(p + 2) << 16; }
static uint64_t read64(const uint8_t *p) { return (uint64_t)read32(p) | (uint64_t)read32(p + 4) << 32; }
static void write16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void write32(uint8_t *p, uint32_t v) { write16(p, (uint16_t)v); write16(p + 2, (uint16_t)(v >> 16)); }
static void write64(uint8_t *p, uint64_t v) { write32(p, (uint32_t)v); write32(p + 4, (uint32_t)(v >> 32)); }
static uint64_t align_up(uint64_t value, uint64_t align) {
  return align > 1 ? (value + align - 1) & ~(align - 1) : value;
}
static bool grow(void **items, size_t *capacity, size_t count, size_t size) {
  if (count < *capacity) return true;
  size_t next = *capacity ? *capacity * 2 : 16;
  void *grown = realloc(*items, next * size);
  if (!grown) return false;
  *items = grown;
  *capacity = next;
  return true;
}

static uint64_t hash_name(const char *name) {
  uint64_t hash = 14695981039346656037ull;
  for (; *name; ++name) hash = (hash ^ (uint8_t)*name) * 1099511628211ull;
  return hash;
}
static LinkSymbol *symbol_find(Linker *linker, const char *name) {
  if (!linker->table_capacity) return NULL;
  for (size_t i = hash_name(name) & (linker->table_capacity - 1);; i = (i + 1) & (linker->table_capacity - 1)) {
    LinkSymbol *symbol = linker->table[i];
    if (!symbol) return NULL;
    if (!strcmp(symbol->name, name)) return symbol;
  }
}
static LinkSymbol *symbol_intern(Linker *linker, const char *name) {
  LinkSymbol *found = symbol_find(linker, name);
  if (found) return found;
  if ((linker->table_count + 1) * 2 > linker->table_capacity) {
    size_t capacity = linker->table_capacity ? linker->table_capacity * 2 : 1024;
    LinkSymbol **table = calloc(capacity, sizeof(*table));
    if (!table) return NULL;
    for (size_t i = 0; i < linker->table_capacity; ++i) {
      LinkSymbol *symbol = linker->table[i];
      if (!symbol) continue;
      size_t at = hash_name(symbol->name) & (capacity - 1);
      while (table[at]) at = (at + 1) & (capacity - 1);
      table[at] = symbol;
    }
    free(linker->table);
    linker->table = table;
    linker->table_capacity = capacity;
  }
  LinkSymbol *symbol = calloc(1, sizeof(*symbol));
  if (!symbol) return NULL;
  symbol->name = name;
  symbol->archive_member = -1;
  size_t at = hash_name(name) & (linker->table_capacity - 1);
  while (linker->table[at]) at = (at + 1) & (linker->table_capacity - 1);
  linker->table[at] = symbol;
  ++linker->table_count;
  return symbol;
}

static uint8_t *read_file(Linker *linker, const char *path, size_t *size) {
  FILE *file = fopen(path, "rb");
  if (!file) { fail(linker, "cannot open '%s'%s", path, ""); return NULL; }
  struct stat info;
  uint8_t *data = NULL;
  if (!stat(path, &info) && info.st_size >= 0 &&
      (data = malloc((size_t)info.st_size + 1)) &&
      fread(data, 1, (size_t)info.st_size, file) == (size_t)info.st_size) {
    *size = (size_t)info.st_size;
  } else {
    free(data);
    data = NULL;
    fail(linker, "cannot read '%s'%s", path, "");
  }
  fclose(file);
  if (data && !grow((void **)&linker->buffers, &linker->buffer_capacity, linker->buffer_count, sizeof(*linker->buffers))) {
    free(data);
    return NULL;
  }
  if (data) linker->buffers[linker->buffer_count++] = data;
  return data;
}

static bool in_bounds(size_t size, uint64_t offset, uint64_t length) {
  return offset <= size && length <= size - offset;
}
static const char *section_name(const LinkObject *object, const uint8_t *headers, uint32_t strings, uint32_t name) {
  const uint8_t *table = headers + (size_t)strings * 64;
  uint64_t offset = read64(table + 24), size = read64(table + 32);
  if (name >= size || offset > object->size || size > object->size - offset) return "";
  const char *text = (const char *)object->data + offset;
  return memchr(text + name, 0, size - name) ? text + name : "";
}
static bool signature_seen(Linker *linker, const char *signature) {
  for (size_t i = 0; i < linker->signature_count; ++i)
    if (!strcmp(linker->signatures[i], signature)) return true;
  if (!grow((void **)&linker->signatures, &linker->signature_capacity, linker->signature_count, sizeof(char *)))
    return false;
  linker->signatures[linker->signature_count++] = (char *)signature;
  return false;
}

static void merge_visibility(LinkSymbol *symbol, uint8_t visibility) {
  if (visibility != STV_DEFAULT && (symbol->visibility == STV_DEFAULT || visibility < symbol->visibility))
    symbol->visibility = visibility;
}
static bool define_symbol(Linker *linker, LinkObject *object, LinkSymbol *symbol, const uint8_t *entry,
                          LinkSection *section) {
  uint8_t binding = entry[4] >> 4, type = entry[4] & 15;
  uint16_t index = read16(entry + 6);
  uint64_t value = read64(entry + 8), size = read64(entry + 16);
  if (index == SHN_COMMON) {
    if (symbol->defined && !symbol->common) return true;
    if (!symbol->common || size > symbol->size) symbol->size = size;
    if (value > symbol->common_align) symbol->common_align = value;
    symbol->common = symbol->defined = true;
    symbol->binding = binding;
    symbol->type = type;
    return true;
  }
  if (symbol->defined && !symbol->common) {
    if (binding == STB_WEAK || symbol->binding == STB_WEAK) {
      if (binding == STB_WEAK) return true;
    } else {
      return fail(linker, "duplicate symbol '%s' (also in %s)", symbol->name, object->path);
    }
  }
  symbol->defined = true;
  symbol->common = false;
  symbol->absolute = index == SHN_ABS;
  symbol->section = section;
  symbol->value = value;
  symbol->size = size;
  symbol->binding = binding;
  symbol->type = type;
  symbol->archive_member = -1;
  return true;
}

static bool kept_section(const LinkSection *section);
static bool load_object(Linker *linker, const char *path, const uint8_t *data, size_t size) {
  if (size < 64 || memcmp(data, "\x7f" "ELF", 4))
    return fail(linker, "'%s' is not an ELF object%s", path, "");
  if (data[4] != 2 || data[5] != 1 || read16(data + 16) != ELF_REL)
    return fail(linker, "'%s' is not a 64-bit little-endian relocatable object%s", path, "");
  if (read16(data + 18) != MACHINE_X86_64)
    return fail(linker, "'%s' is not an x86-64 object%s", path, "");
  LinkObject *object = calloc(1, sizeof(*object));
  if (!object || !grow((void **)&linker->objects, &linker->object_capacity, linker->object_count, sizeof(*linker->objects))) {
    free(object);
    return fail(linker, "out of memory%s%s", "", "");
  }
  linker->objects[linker->object_count++] = object;
  object->path = path;
  object->data = data;
  object->size = size;
  uint64_t header_offset = read64(data + 40);
  size_t count = read16(data + 60);
  uint32_t strings = read16(data + 62);
  if (header_offset && !count && in_bounds(size, header_offset, 64)) count = (size_t)read64(data + header_offset + 32);
  if (strings == SHN_XINDEX && in_bounds(size, header_offset, 64)) strings = read32(data + header_offset + 40);
  if (!in_bounds(size, header_offset, (uint64_t)count * 64) || strings >= count)
    return fail(linker, "'%s' has malformed section headers%s", path, "");
  const uint8_t *headers = data + header_offset;
  object->sections = calloc(count, sizeof(LinkSection));
  if (!object->sections) return fail(linker, "out of memory%s%s", "", "");
  object->section_count = count;
  uint32_t symtab = 0;
  for (uint32_t i = 1; i < count; ++i) {
    const uint8_t *h = headers + (size_t)i * 64;
    LinkSection *section = &object->sections[i];
    section->object = object;
    section->index = i;
    section->name = section_name(object, headers, strings, read32(h));
    section->type = read32(h + 4);
    section->flags = read64(h + 8);
    section->size = read64(h + 32);
    section->align = read64(h + 48) ? read64(h + 48) : 1;
    section->output = -1;
    if (section->type != SHT_NOBITS) {
      uint64_t offset = read64(h + 24);
      if (!in_bounds(size, offset, section->size))
        return fail(linker, "'%s' has a section outside the file%s", path, "");
      section->data = data + offset;
    }
    if (section->type == SHT_SYMTAB) symtab = i;
    section->eh_frame = !strcmp(section->name, ".eh_frame") || section->type == SHT_X86_64_UNWIND;
  }
  /* Later copies of a COMDAT group are dropped whole. */
  for (uint32_t i = 1; i < count; ++i) {
    LinkSection *group = &object->sections[i];
    if (group->type != SHT_GROUP || group->size < 4 || !symtab) continue;
    const uint8_t *h = headers + (size_t)i * 64;
    uint32_t info = read32(h + 44);
    const uint8_t *sh = headers + (size_t)symtab * 64;
    uint64_t sym_offset = read64(sh + 24), sym_size = read64(sh + 32);
    uint32_t link = read32(sh + 40);
    if ((uint64_t)info * 24 + 24 > sym_size || link >= count) continue;
    const uint8_t *entry = data + sym_offset + (size_t)info * 24;
    const LinkSection *names = &object->sections[link];
    uint32_t name = read32(entry);
    if (name >= names->size) continue;
    if (!(read32(group->data) & GRP_COMDAT)) continue;
    if (signature_seen(linker, (const char *)names->data + name)) {
      for (uint64_t at = 4; at + 4 <= group->size; at += 4) {
        uint32_t member = read32(group->data + at);
        if (member < count) object->sections[member].discarded = true;
      }
    }
  }
  if (!symtab) return true;
  const uint8_t *sh = headers + (size_t)symtab * 64;
  LinkSection *table = &object->sections[symtab];
  uint32_t link = read32(sh + 40);
  if (link >= count || object->sections[link].type != SHT_STRTAB)
    return fail(linker, "'%s' has a malformed symbol table%s", path, "");
  const LinkSection *names = &object->sections[link];
  object->strings = (const char *)names->data;
  object->symbol_count = (size_t)(table->size / 24);
  object->symbols = calloc(object->symbol_count ? object->symbol_count : 1, sizeof(LinkSymbol *));
  object->locals = calloc(object->symbol_count ? object->symbol_count : 1, sizeof(LinkSymbol));
  if (!object->symbols || !object->locals) return fail(linker, "out of memory%s%s", "", "");
  for (size_t i = 1; i < object->symbol_count; ++i) {
    const uint8_t *entry = table->data + i * 24;
    uint32_t name = read32(entry);
    if (name >= names->size || !memchr(names->data + name, 0, names->size - name))
      return fail(linker, "'%s' has a malformed symbol name%s", path, "");
    uint8_t binding = entry[4] >> 4, type = entry[4] & 15;
    uint16_t index = read16(entry + 6);
    if (type == STT_TLS) return fail(linker, "'%s' uses thread-local storage, which the linker does not support%s", path, "");
    if (index == SHN_XINDEX) return fail(linker, "'%s' needs extended section indexes%s", path, "");
    LinkSection *section = index && index < count ? &object->sections[index] : NULL;
    bool discarded = section && section->discarded;
    if (binding == STB_LOCAL) {
      LinkSymbol *local = &object->locals[i];
      local->name = (const char *)names->data + name;
      local->section = discarded ? NULL : section;
      local->value = read64(entry + 8);
      local->size = read64(entry + 16);
      local->binding = binding;
      local->type = type;
      local->defined = index != SHN_UNDEF && !discarded;
      local->absolute = index == SHN_ABS;
      local->archive_member = -1;
      object->symbols[i] = local;
      continue;
    }
    LinkSymbol *symbol = symbol_intern(linker, (const char *)names->data + name);
    if (!symbol) return fail(linker, "out of memory%s%s", "", "");
    object->symbols[i] = symbol;
    merge_visibility(symbol, entry[5] & 3);
    if (index == SHN_UNDEF || discarded) {
      symbol->referenced = true;
      if (binding != STB_WEAK) symbol->strong_reference = true;
      continue;
    }
    if (index >= count && index != SHN_ABS && index != SHN_COMMON)
      return fail(linker, "'%s' has a symbol in a missing section%s", path, "");
    if (!define_symbol(linker, object, symbol, entry, section)) return false;
  }
  for (uint32_t i = 1; i < count; ++i) {
    LinkSection *relocation = &object->sections[i];
    if (relocation->type != SHT_RELA && relocation->type != SHT_REL) continue;
    uint32_t target = read32(headers + (size_t)i * 64 + 44);
    if (target >= count) return fail(linker, "'%s' has a malformed relocation section%s", path, "");
    LinkSection *profile = &object->sections[target];
    if (profile->type == SHT_CALL_GRAPH_PROFILE && !object->profile) {
      /* Each 8-byte weight pairs with two relocations naming caller and callee. */
      size_t entry = relocation->type == SHT_RELA ? 24 : 16;
      size_t n = (size_t)(profile->size / 8);
      if (relocation->size / entry < (uint64_t)n * 2) continue;
      object->profile = calloc(n ? n : 1, sizeof(*object->profile));
      if (!object->profile) return fail(linker, "out of memory%s%s", "", "");
      for (size_t k = 0; k < n; ++k) {
        uint32_t from = (uint32_t)(read64(relocation->data + 2 * k * entry + 8) >> 32);
        uint32_t to = (uint32_t)(read64(relocation->data + (2 * k + 1) * entry + 8) >> 32);
        if (from >= object->symbol_count || to >= object->symbol_count) continue;
        object->profile[object->profile_count++] = (LinkProfileEdge){from, to, read64(profile->data + k * 8)};
      }
      continue;
    }
    /* Other metadata is not output. */
    if (!kept_section(profile)) continue;
    if (relocation->type == SHT_REL)
      return fail(linker, "'%s' uses REL relocations%s", path, "");
    LinkSection *section = &object->sections[target];
    size_t n = (size_t)(relocation->size / 24);
    section->relas = malloc((n ? n : 1) * sizeof(LinkRela));
    if (!section->relas) return fail(linker, "out of memory%s%s", "", "");
    section->rela_count = n;
    for (size_t k = 0; k < n; ++k) {
      const uint8_t *r = relocation->data + k * 24;
      uint64_t info = read64(r + 8);
      section->relas[k] = (LinkRela){read64(r), read64(r + 16), (uint32_t)info, (uint32_t)(info >> 32)};
      if (section->relas[k].symbol >= object->symbol_count || section->relas[k].offset > section->size)
        return fail(linker, "'%s' has a malformed relocation%s", path, "");
    }
  }
  return true;
}

/* A shared library contributes its exported definitions (preferring each
   name's default version) and its undefined names, which the output must
   export if it defines them. */
static bool load_shared(Linker *linker, const char *path, const uint8_t *data, size_t size, bool as_needed) {
  if (size < 64 || data[4] != 2 || data[5] != 1 || read16(data + 18) != MACHINE_X86_64)
    return fail(linker, "'%s' is not an x86-64 shared library%s", path, "");
  uint64_t header_offset = read64(data + 40);
  size_t count = read16(data + 60);
  if (!in_bounds(size, header_offset, (uint64_t)count * 64))
    return fail(linker, "'%s' has malformed section headers%s", path, "");
  const uint8_t *headers = data + header_offset;
  LinkShared *library = calloc(1, sizeof(*library));
  if (!library || !grow((void **)&linker->shareds, &linker->shared_capacity, linker->shared_count, sizeof(*linker->shareds))) {
    free(library);
    return fail(linker, "out of memory%s%s", "", "");
  }
  linker->shareds[linker->shared_count++] = library;
  library->path = path;
  library->as_needed = as_needed;
  const uint8_t *dynsym = NULL, *versym = NULL, *verdef = NULL, *dynamic = NULL;
  uint64_t dynsym_size = 0, verdef_size = 0, dynamic_size = 0, verdef_count = 0;
  const char *strings = NULL;
  uint64_t strings_size = 0;
  for (size_t i = 0; i < count; ++i) {
    const uint8_t *h = headers + i * 64;
    uint32_t type = read32(h + 4);
    uint64_t offset = read64(h + 24), length = read64(h + 32);
    if (!in_bounds(size, offset, length)) continue;
    if (type == SHT_DYNSYM) {
      dynsym = data + offset;
      dynsym_size = length;
      uint32_t link = read32(h + 40);
      if (link < count) {
        const uint8_t *sh = headers + (size_t)link * 64;
        if (in_bounds(size, read64(sh + 24), read64(sh + 32))) {
          strings = (const char *)data + read64(sh + 24);
          strings_size = read64(sh + 32);
        }
      }
    } else if (type == SHT_VERSYM) {
      versym = data + offset;
    } else if (type == SHT_VERDEF) {
      verdef = data + offset;
      verdef_size = length;
      verdef_count = read32(h + 44);
    } else if (type == SHT_DYNAMIC) {
      dynamic = data + offset;
      dynamic_size = length;
    }
  }
  if (!dynsym || !strings) return fail(linker, "'%s' has no dynamic symbol table%s", path, "");
  if (strings_size && strings[strings_size - 1]) return fail(linker, "'%s' has a malformed string table%s", path, "");
  for (uint64_t at = 0; dynamic && at + 16 <= dynamic_size; at += 16)
    if (read64(dynamic + at) == DT_SONAME && read64(dynamic + at + 8) < strings_size)
      library->soname = strings + read64(dynamic + at + 8);
  /* Version definitions name each verdef index. */
  for (uint64_t at = 0, n = 0; verdef && n < verdef_count && at + 20 <= verdef_size; ++n) {
    uint16_t index = read16(verdef + at + 4);
    uint32_t aux = read32(verdef + at + 12), next = read32(verdef + at + 16);
    if (at + aux + 8 <= verdef_size && read32(verdef + at + aux) < strings_size) {
      if (index >= library->version_count) {
        const char **versions = realloc(library->versions, (index + 1u) * sizeof(*versions));
        if (!versions) return fail(linker, "out of memory%s%s", "", "");
        for (size_t v = library->version_count; v <= index; ++v) versions[v] = NULL;
        library->versions = versions;
        library->version_count = index + 1u;
      }
      library->versions[index] = strings + read32(verdef + at + aux);
    }
    if (!next) break;
    at += next;
  }
  for (uint64_t i = 1; i < dynsym_size / 24; ++i) {
    const uint8_t *entry = dynsym + i * 24;
    uint8_t binding = entry[4] >> 4, type = entry[4] & 15;
    uint32_t name = read32(entry);
    if (binding == STB_LOCAL || name >= strings_size || !strings[name]) continue;
    uint16_t version = versym ? read16(versym + i * 2) : 1;
    uint16_t index = version & 0x7fff;
    bool hidden = (version & 0x8000) != 0;
    if (index == 0) continue;
    LinkSymbol *symbol = symbol_intern(linker, strings + name);
    if (!symbol) return fail(linker, "out of memory%s%s", "", "");
    if (read16(entry + 6) == SHN_UNDEF) {
      symbol->library_reference = true;
      continue;
    }
    if (symbol->shared && (symbol->shared != library || hidden || !symbol->shared_hidden)) continue;
    symbol->shared = library;
    symbol->shared_value = read64(entry + 8);
    symbol->shared_size = read64(entry + 16);
    symbol->shared_type = type;
    symbol->shared_hidden = hidden;
    symbol->shared_version = index >= 2 && index < library->version_count ? library->versions[index] : NULL;
  }
  return true;
}

static char *keep_string(Linker *linker, const char *text, size_t length) {
  char *copy = malloc(length + 1);
  if (!copy || !grow((void **)&linker->buffers, &linker->buffer_capacity, linker->buffer_count, sizeof(*linker->buffers))) {
    free(copy);
    return NULL;
  }
  memcpy(copy, text, length);
  copy[length] = 0;
  linker->buffers[linker->buffer_count++] = (uint8_t *)copy;
  return copy;
}
/* GNU linker scripts as installed for C libraries: GROUP, INPUT and
   AS_NEEDED lists of files, with OUTPUT_FORMAT and comments ignored. */
typedef bool (*ScriptFile)(void *context, const char *path, size_t length, bool as_needed);
static bool parse_script(const char *text, size_t size, ScriptFile file, void *context) {
  size_t at = 0;
  int depth = 0, needed_depth = -1;
  bool listing = false, skipping = false;
  while (at < size) {
    char c = text[at];
    if (c == '/' && at + 1 < size && text[at + 1] == '*') {
      const char *end = NULL;
      for (size_t k = at + 2; k + 1 < size; ++k)
        if (text[k] == '*' && text[k + 1] == '/') { end = text + k; break; }
      if (!end) return false;
      at = (size_t)(end - text) + 2;
      continue;
    }
    if (c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == ',') { ++at; continue; }
    if (c == '(') { ++depth; ++at; continue; }
    if (c == ')') {
      if (--depth < 0) return false;
      if (depth == needed_depth) needed_depth = -1;
      if (depth == 0) listing = skipping = false;
      ++at;
      continue;
    }
    size_t start = at;
    while (at < size && !strchr(" \t\n\r,()", text[at])) ++at;
    size_t length = at - start;
    const char *word = text + start;
    if (depth == 0) {
      listing = (length == 5 && !memcmp(word, "GROUP", 5)) || (length == 5 && !memcmp(word, "INPUT", 5));
      skipping = !listing;
      bool ignored = (length == 13 && !memcmp(word, "OUTPUT_FORMAT", 13)) ||
                     (length == 11 && !memcmp(word, "OUTPUT_ARCH", 11)) ||
                     (length == 10 && !memcmp(word, "SEARCH_DIR", 10));
      if (skipping && !ignored) return false;
      continue;
    }
    if (skipping) continue;
    if (length == 9 && !memcmp(word, "AS_NEEDED", 9)) { needed_depth = depth; continue; }
    if (!listing || !file(context, word, length, needed_depth >= 0)) return false;
  }
  return depth == 0;
}
static bool is_script(const uint8_t *data, size_t size) {
  size_t n = size < 512 ? size : 512;
  for (size_t i = 0; i < n; ++i)
    if (!data[i] || data[i] > 0x7e) return false;
  return n > 0;
}
static bool load_input(Linker *linker, const char *path, bool as_needed, int depth);
typedef struct {
  Linker *linker;
  const char *script;
  int depth;
} ScriptLoad;
static bool script_file(void *context, const char *word, size_t length, bool as_needed) {
  ScriptLoad *load = context;
  if (length >= 2 && word[0] == '-' && word[1] == 'l')
    return fail(load->linker, "linker script '%s' uses -l, which the linker does not support%s", load->script, "");
  char *path = keep_string(load->linker, word, length);
  if (!path) return fail(load->linker, "out of memory%s%s", "", "");
  return load_input(load->linker, path, as_needed, load->depth + 1);
}
static bool load_archive(Linker *linker, const char *path, const uint8_t *data, size_t size);
static bool load_input(Linker *linker, const char *path, bool as_needed, int depth) {
  size_t size = 0;
  uint8_t *data = read_file(linker, path, &size);
  if (!data) return false;
  if (size >= 8 && !memcmp(data, "!<arch>\n", 8)) return load_archive(linker, path, data, size);
  if (size >= 18 && !memcmp(data, "\x7f" "ELF", 4)) {
    if (read16(data + 16) == ELF_DYN) return load_shared(linker, path, data, size, as_needed);
    return load_object(linker, path, data, size);
  }
  if (depth < 4 && is_script(data, size)) {
    ScriptLoad load = {linker, path, depth};
    if (parse_script((const char *)data, size, script_file, &load)) return true;
    return fail(linker, "cannot read linker script '%s'%s", path, "");
  }
  return fail(linker, "'%s' is not an object, archive, shared library or linker script%s", path, "");
}

/* GNU and BSD ar archives. Members load on demand from the symbol index. */
static bool load_archive(Linker *linker, const char *path, const uint8_t *data, size_t size) {
  LinkArchive *archive = realloc(linker->archives, (linker->archive_count + 1) * sizeof(*archive));
  if (!archive) return fail(linker, "out of memory%s%s", "", "");
  linker->archives = archive;
  size_t archive_index = linker->archive_count++;
  archive = &linker->archives[archive_index];
  *archive = (LinkArchive){path, data, size, NULL};
  size_t at = 8;
  while (at + 60 <= size) {
    const uint8_t *header = data + at;
    size_t member_size = (size_t)strtoull((const char *)header + 48, NULL, 10);
    size_t body = at + 60;
    if (member_size > size - body) return fail(linker, "'%s' is a malformed archive%s", path, "");
    if (!memcmp(header, "/               ", 16) && member_size >= 4) {
      const uint8_t *index = data + body;
      uint32_t n = (uint32_t)index[0] << 24 | (uint32_t)index[1] << 16 | (uint32_t)index[2] << 8 | index[3];
      if ((uint64_t)n * 4 + 4 > member_size) return fail(linker, "'%s' has a malformed symbol index%s", path, "");
      const char *names = (const char *)index + 4 + (size_t)n * 4, *end = (const char *)index + member_size;
      for (uint32_t k = 0; k < n && names < end; ++k) {
        const uint8_t *p = index + 4 + (size_t)k * 4;
        uint32_t offset = (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
        const char *name_end = memchr(names, 0, (size_t)(end - names));
        if (!name_end) break;
        LinkSymbol *symbol = symbol_intern(linker, names);
        if (!symbol) return fail(linker, "out of memory%s%s", "", "");
        if (!symbol->defined && symbol->archive_member < 0) {
          symbol->archive_member = (int)offset;
          symbol->archive = archive_index;
        }
        names = name_end + 1;
      }
      return true;
    }
    at = body + member_size + (member_size & 1);
  }
  return fail(linker, "'%s' has no symbol index (run ranlib)%s", path, "");
}
static bool load_member(Linker *linker, LinkSymbol *symbol) {
  LinkArchive *archive = &linker->archives[symbol->archive];
  size_t at = (size_t)symbol->archive_member;
  symbol->archive_member = -1;
  if (at + 60 > archive->size) return fail(linker, "'%s' has a malformed member offset%s", archive->path, "");
  size_t member_size = (size_t)strtoull((const char *)archive->data + at + 48, NULL, 10);
  size_t body = at + 60;
  if (member_size > archive->size - body) return fail(linker, "'%s' is a malformed archive%s", archive->path, "");
  const uint8_t *member = archive->data + body;
  /* BSD long names prefix the member body with the name. */
  if (!memcmp(archive->data + at, "#1/", 3)) {
    size_t skip = (size_t)strtoull((const char *)archive->data + at + 3, NULL, 10);
    if (skip > member_size) return fail(linker, "'%s' is a malformed archive%s", archive->path, "");
    member += skip;
    member_size -= skip;
  }
  for (size_t i = 0; i < linker->object_count; ++i)
    if (linker->objects[i]->data == member) return true;
  return load_object(linker, archive->path, member, member_size);
}
static bool resolve_archives(Linker *linker) {
  for (bool changed = true; changed;) {
    changed = false;
    for (size_t i = 0; i < linker->table_capacity; ++i) {
      LinkSymbol *symbol = linker->table[i];
      if (!symbol || symbol->defined || symbol->shared || !symbol->strong_reference || symbol->archive_member < 0)
        continue;
      if (!load_member(linker, symbol)) return false;
      changed = true;
    }
  }
  return true;
}

static int classify(const LinkSection *section) {
  if (!(section->flags & SHF_ALLOC)) return -1;
  if (section->eh_frame) return OUT_EH_FRAME;
  if (section->type == SHT_INIT_ARRAY || section->type == SHT_PREINIT_ARRAY ||
      !strncmp(section->name, ".init_array", 11))
    return OUT_INIT_ARRAY;
  if (section->type == SHT_FINI_ARRAY || !strncmp(section->name, ".fini_array", 11)) return OUT_FINI_ARRAY;
  if (section->flags & SHF_EXEC) return OUT_TEXT;
  if (section->type == SHT_NOBITS) return OUT_BSS;
  if (section->flags & SHF_WRITE) return OUT_DATA;
  return OUT_RODATA;
}
static bool kept_section(const LinkSection *section) {
  if (section->discarded || section->flags & SHF_EXCLUDE) return false;
  if (section->type == SHT_SYMTAB || section->type == SHT_STRTAB || section->type == SHT_RELA ||
      section->type == SHT_REL || section->type == SHT_GROUP || section->type == SHT_SYMTAB_SHNDX)
    return false;
  if (section->flags & SHF_ALLOC) return section->type == SHT_PROGBITS || section->type == SHT_NOBITS ||
                                         section->type == SHT_INIT_ARRAY || section->type == SHT_FINI_ARRAY ||
                                         section->type == SHT_PREINIT_ARRAY || section->type == SHT_X86_64_UNWIND;
  return !strncmp(section->name, ".debug_", 7);
}

static LinkSection *symbol_section(LinkSymbol *symbol) {
  return symbol && symbol->defined ? symbol->section : NULL;
}
static bool mark(Linker *linker, LinkSection ***stack, size_t *count, size_t *capacity, LinkSection *section) {
  if (!section || section->live || section->discarded || !kept_section(section) || section->eh_frame) return true;
  section->live = true;
  if (!grow((void **)stack, capacity, *count, sizeof(**stack))) return fail(linker, "out of memory%s%s", "", "");
  (*stack)[(*count)++] = section;
  return true;
}
static bool mark_relocations(Linker *linker, LinkSection ***stack, size_t *count, size_t *capacity,
                             LinkSection *section, uint64_t start, uint64_t end) {
  for (size_t i = 0; i < section->rela_count; ++i) {
    LinkRela *rela = &section->relas[i];
    if (rela->offset < start || rela->offset >= end) continue;
    LinkSymbol *symbol = section->object->symbols[rela->symbol];
    if (!symbol) continue;
    if (!mark(linker, stack, count, capacity, symbol_section(symbol))) return false;
  }
  return true;
}
/* Collects .eh_frame records; FDEs for dead code are dropped and the rest
   keep their CIEs, so the output stays a valid unwind table. */
typedef struct {
  uint64_t start, size, new_start, cie;
  bool fde, keep;
} FrameRecord;
static bool frame_records(Linker *linker, LinkSection *section, FrameRecord **out, size_t *out_count) {
  FrameRecord *records = NULL;
  size_t count = 0, capacity = 0;
  for (uint64_t at = 0; at + 4 <= section->size;) {
    uint64_t length = read32(section->data + at);
    if (!length) break;
    if (length == 0xffffffffu || length + 4 > section->size - at) {
      free(records);
      return fail(linker, "'%s' has a malformed .eh_frame%s", section->object->path, "");
    }
    if (!grow((void **)&records, &capacity, count, sizeof(*records))) { free(records); return false; }
    uint32_t id = length >= 4 ? read32(section->data + at + 4) : 0;
    records[count++] = (FrameRecord){at, length + 4, 0, id ? at + 4 - id : 0, id != 0, false};
    at += length + 4;
  }
  *out = records;
  *out_count = count;
  return true;
}
static LinkSection *fde_target(LinkSection *section, const FrameRecord *record) {
  for (size_t i = 0; i < section->rela_count; ++i) {
    LinkRela *rela = &section->relas[i];
    if (rela->offset != record->start + 8) continue;
    LinkSymbol *symbol = section->object->symbols[rela->symbol];
    return symbol_section(symbol);
  }
  return NULL;
}
static bool rewrite_frames(Linker *linker, LinkSection *section) {
  FrameRecord *records;
  size_t count;
  if (!frame_records(linker, section, &records, &count)) return false;
  for (size_t i = 0; i < count; ++i) {
    if (!records[i].fde) continue;
    LinkSection *target = fde_target(section, &records[i]);
    records[i].keep = target && target->live;
  }
  for (size_t i = 0; i < count; ++i) {
    if (records[i].fde) continue;
    for (size_t k = 0; k < count && !records[i].keep; ++k)
      records[i].keep = records[k].fde && records[k].keep && records[k].cie == records[i].start;
  }
  uint64_t size = 0;
  for (size_t i = 0; i < count; ++i) {
    records[i].new_start = size;
    if (records[i].keep) size += records[i].size;
  }
  uint8_t *data = malloc(size ? size : 1);
  LinkRela *relas = malloc((section->rela_count ? section->rela_count : 1) * sizeof(*relas));
  if (!data || !relas) { free(data); free(relas); free(records); return fail(linker, "out of memory%s%s", "", ""); }
  size_t rela_count = 0;
  for (size_t i = 0; i < count; ++i) {
    FrameRecord *record = &records[i];
    if (!record->keep) continue;
    memcpy(data + record->new_start, section->data + record->start, record->size);
    if (record->fde) {
      uint64_t cie = 0;
      bool found = false;
      for (size_t k = 0; k < count; ++k)
        if (!records[k].fde && records[k].start == record->cie) { cie = records[k].new_start; found = true; }
      if (!found) { free(data); free(relas); free(records); return fail(linker, "'%s' has an FDE without a CIE%s", section->object->path, ""); }
      write32(data + record->new_start + 4, (uint32_t)(record->new_start + 4 - cie));
    }
    for (size_t k = 0; k < section->rela_count; ++k) {
      LinkRela rela = section->relas[k];
      if (rela.offset < record->start || rela.offset >= record->start + record->size) continue;
      rela.offset = rela.offset - record->start + record->new_start;
      relas[rela_count++] = rela;
    }
  }
  free(records);
  free(section->relas);
  section->owned = data;
  section->data = data;
  section->size = size;
  section->relas = relas;
  section->rela_count = rela_count;
  section->live = size != 0;
  return true;
}
/* Dynamic symbols the output defines: everything visible from a shared
   library, or what an executable's libraries refer back to. */
static bool exported(const Linker *linker, const LinkSymbol *symbol) {
  if (!symbol->defined || (symbol->absolute && !linker->shared_output)) return false;
  if (symbol->visibility != STV_DEFAULT && symbol->visibility != STV_PROTECTED) return false;
  return linker->shared_output || (linker->dynamic && symbol->library_reference);
}
static bool collect_garbage(Linker *linker, const char *entry) {
  LinkSection **stack = NULL;
  size_t count = 0, capacity = 0;
  bool ok = true;
  if (entry) {
    LinkSymbol *start = symbol_find(linker, entry);
    if (!start || !start->defined) return fail(linker, "entry symbol '%s' is undefined%s", entry, "");
    ok = mark(linker, &stack, &count, &capacity, symbol_section(start));
  }
  for (size_t i = 0; ok && i < linker->table_capacity; ++i) {
    LinkSymbol *symbol = linker->table[i];
    if (symbol && exported(linker, symbol)) ok = mark(linker, &stack, &count, &capacity, symbol_section(symbol));
  }
  for (size_t o = 0; ok && o < linker->object_count; ++o) {
    LinkObject *object = linker->objects[o];
    for (size_t i = 1; ok && i < object->section_count; ++i) {
      LinkSection *section = &object->sections[i];
      int kind = classify(section);
      if (kind == OUT_INIT_ARRAY || kind == OUT_FINI_ARRAY || section->flags & SHF_RETAIN)
        ok = mark(linker, &stack, &count, &capacity, section);
    }
  }
  /* Personality routines and LSDAs of kept frames are live too. */
  for (bool again = true; ok && again;) {
    while (ok && count) {
      LinkSection *section = stack[--count];
      ok = mark_relocations(linker, &stack, &count, &capacity, section, 0, UINT64_MAX);
    }
    for (size_t o = 0; ok && o < linker->object_count; ++o) {
      LinkObject *object = linker->objects[o];
      for (size_t i = 1; ok && i < object->section_count; ++i) {
        LinkSection *section = &object->sections[i];
        if (!section->eh_frame || section->discarded || !(section->flags & SHF_ALLOC)) continue;
        FrameRecord *records;
        size_t record_count;
        if (!(ok = frame_records(linker, section, &records, &record_count))) break;
        for (size_t r = 0; ok && r < record_count; ++r) {
          if (!records[r].fde) continue;
          LinkSection *target = fde_target(section, &records[r]);
          if (!target || !target->live) continue;
          ok = mark_relocations(linker, &stack, &count, &capacity, section, records[r].start + 12,
                                records[r].start + records[r].size);
          for (size_t c = 0; ok && c < record_count; ++c)
            if (!records[c].fde && records[c].start == records[r].cie)
              ok = mark_relocations(linker, &stack, &count, &capacity, section, records[c].start,
                                    records[c].start + records[c].size);
        }
        free(records);
      }
    }
    again = count != 0;
  }
  free(stack);
  for (size_t o = 0; ok && o < linker->object_count; ++o) {
    LinkObject *object = linker->objects[o];
    for (size_t i = 1; ok && i < object->section_count; ++i) {
      LinkSection *section = &object->sections[i];
      if (section->eh_frame && !section->discarded && section->flags & SHF_ALLOC) ok = rewrite_frames(linker, section);
      else if (!(section->flags & SHF_ALLOC) && kept_section(section)) section->live = true;
    }
  }
  return ok;
}

static bool add_to_output(Linker *linker, LinkOutput *output, LinkSection *section) {
  if (!grow((void **)&output->sections, &output->capacity, output->count, sizeof(*output->sections)))
    return fail(linker, "out of memory%s%s", "", "");
  output->sections[output->count++] = section;
  if (section->align > output->align) output->align = section->align;
  return true;
}
static bool allocate_commons(Linker *linker) {
  for (size_t i = 0; i < linker->table_capacity; ++i) {
    LinkSymbol *symbol = linker->table[i];
    if (!symbol || !symbol->common) continue;
    LinkSection *section = calloc(1, sizeof(*section));
    if (!section || !grow((void **)&linker->commons, &linker->common_capacity, linker->common_count, sizeof(*linker->commons))) {
      free(section);
      return fail(linker, "out of memory%s%s", "", "");
    }
    linker->commons[linker->common_count++] = section;
    *section = (LinkSection){.name = ".bss", .size = symbol->size, .type = SHT_NOBITS,
                             .align = symbol->common_align ? symbol->common_align : 1,
                             .flags = SHF_ALLOC | SHF_WRITE, .live = true, .output = OUT_BSS};
    symbol->section = section;
    symbol->value = 0;
    symbol->common = false;
  }
  return true;
}
static bool needs_got(uint32_t type) {
  return type == R_X86_64_GOTPCREL || type == R_X86_64_GOTPCRELX || type == R_X86_64_REX_GOTPCRELX;
}
static bool assign_outputs(Linker *linker) {
  static const struct {
    const char *name;
    uint32_t type;
    uint64_t entry_size;
    int link;
  } kinds[OUT_ALLOC_COUNT] = {
    [OUT_INTERP] = {".interp", SHT_PROGBITS, 0, -1},
    [OUT_HASH] = {".hash", SHT_HASH, 4, OUT_DYNSYM},
    [OUT_DYNSYM] = {".dynsym", SHT_DYNSYM, 24, OUT_DYNSTR},
    [OUT_DYNSTR] = {".dynstr", SHT_STRTAB, 0, -1},
    [OUT_VERSYM] = {".gnu.version", SHT_VERSYM, 2, OUT_DYNSYM},
    [OUT_VERNEED] = {".gnu.version_r", SHT_VERNEED, 0, OUT_DYNSTR},
    [OUT_RELA_DYN] = {".rela.dyn", SHT_RELA, 24, OUT_DYNSYM},
    [OUT_RODATA] = {".rodata", SHT_PROGBITS, 0, -1},
    [OUT_EH_FRAME] = {".eh_frame", SHT_PROGBITS, 0, -1},
    [OUT_TEXT] = {".text", SHT_PROGBITS, 0, -1},
    [OUT_PLT] = {".plt", SHT_PROGBITS, 16, -1},
    [OUT_DYNAMIC] = {".dynamic", SHT_DYNAMIC, 16, OUT_DYNSTR},
    [OUT_INIT_ARRAY] = {".init_array", SHT_INIT_ARRAY, 8, -1},
    [OUT_FINI_ARRAY] = {".fini_array", SHT_FINI_ARRAY, 8, -1},
    [OUT_DATA] = {".data", SHT_PROGBITS, 0, -1},
    [OUT_GOT] = {".got", SHT_PROGBITS, 8, -1},
    [OUT_BSS] = {".bss", SHT_NOBITS, 0, -1},
  };
  for (int k = 0; k < OUT_ALLOC_COUNT; ++k) {
    LinkOutput *output = &linker->outputs[k];
    output->name = (char *)kinds[k].name;
    output->type = kinds[k].type;
    output->entry_size = kinds[k].entry_size;
    output->link = kinds[k].link;
    output->align = 1;
    output->flags = SHF_ALLOC | (k == OUT_TEXT || k == OUT_PLT ? SHF_EXEC : 0) |
                    (k >= OUT_DYNAMIC ? SHF_WRITE : 0);
  }
  linker->outputs[OUT_DYNSYM].info = 1;
  for (size_t o = 0; o < linker->object_count; ++o) {
    LinkObject *object = linker->objects[o];
    for (size_t i = 1; i < object->section_count; ++i) {
      LinkSection *section = &object->sections[i];
      if (!section->live) continue;
      if (section->flags & SHF_TLS)
        return fail(linker, "'%s' uses thread-local storage, which the linker does not support%s", object->path, "");
      int kind = classify(section);
      if (kind >= 0) {
        section->output = kind;
        if (!add_to_output(linker, &linker->outputs[kind], section)) return false;
        continue;
      }
      size_t e = 0;
      while (e < linker->extra_count && strcmp(linker->extra[e].name, section->name)) ++e;
      if (e == linker->extra_count) {
        if (!grow((void **)&linker->extra, &linker->extra_capacity, linker->extra_count, sizeof(*linker->extra)))
          return fail(linker, "out of memory%s%s", "", "");
        linker->extra[linker->extra_count++] = (LinkOutput){.name = (char *)section->name, .align = 1, .type = SHT_PROGBITS};
      }
      section->output = OUT_ALLOC_COUNT + (int)e;
      if (!add_to_output(linker, &linker->extra[e], section)) return false;
    }
  }
  for (size_t i = 0; i < linker->common_count; ++i)
    if (!add_to_output(linker, &linker->outputs[OUT_BSS], linker->commons[i])) return false;
  return true;
}

/* Dynamic linking: which symbols need GOT slots, PLT entries or copy
   relocations, what the dynamic symbol table holds, and the run-time
   relocations. Sizes are fixed here; contents are written after layout. */
/* Whether the dynamic loader decides what a reference means: imports, and
   in a shared library its own default-visibility definitions, which an
   executable may interpose or copy. */
static bool preemptible(const Linker *linker, const LinkSymbol *symbol) {
  if (symbol->defined)
    return linker->shared_output && symbol->binding != STB_LOCAL && symbol->visibility == STV_DEFAULT &&
           !symbol->absolute;
  return symbol->shared || (linker->shared_output && symbol->referenced);
}
static bool function_like(const LinkSymbol *symbol) {
  return symbol->shared_type == STT_FUNC || symbol->shared_type == STT_GNU_IFUNC;
}
static bool add_symbol(Linker *linker, LinkSymbol ***list, size_t *count, size_t *capacity, LinkSymbol *symbol,
                       uint32_t *slot) {
  if (*slot) return true;
  if (!grow((void **)list, capacity, *count, sizeof(**list))) return fail(linker, "out of memory%s%s", "", "");
  (*list)[(*count)++] = symbol;
  *slot = (uint32_t)*count;
  return true;
}
static bool add_relocation(Linker *linker, LinkSection *section, uint64_t offset, uint32_t type,
                           LinkSymbol *symbol, uint64_t addend) {
  if (!grow((void **)&linker->relocations, &linker->relocation_capacity, linker->relocation_count,
            sizeof(*linker->relocations)))
    return fail(linker, "out of memory%s%s", "", "");
  linker->relocations[linker->relocation_count++] = (DynamicRelocation){section, offset, addend, type, symbol};
  return true;
}
static bool add_dynsym(Linker *linker, LinkSymbol *symbol) {
  return add_symbol(linker, &linker->dynsyms, &linker->dynsym_count, &linker->dynsym_capacity, symbol,
                    &symbol->dynsym);
}
static uint32_t dynstr_add(Linker *linker, const char *text) {
  size_t length = strlen(text) + 1;
  while (linker->dynstr_size + length > linker->dynstr_capacity) {
    size_t next = linker->dynstr_capacity ? linker->dynstr_capacity * 2 : 1024;
    uint8_t *grown = realloc(linker->dynstr, next);
    if (!grown) return UINT32_MAX;
    linker->dynstr = grown;
    linker->dynstr_capacity = next;
  }
  memcpy(linker->dynstr + linker->dynstr_size, text, length);
  linker->dynstr_size += length;
  return (uint32_t)(linker->dynstr_size - length);
}
static uint32_t elf_hash(const char *name) {
  uint32_t hash = 0;
  for (; *name; ++name) {
    hash = (hash << 4) + (uint8_t)*name;
    uint32_t high = hash & 0xf0000000u;
    if (high) hash ^= high >> 24;
    hash &= ~high;
  }
  return hash;
}
static bool synthetic(Linker *linker, int kind, uint64_t size, uint64_t align) {
  LinkSection *section = &linker->synthetic[kind];
  *section = (LinkSection){.name = linker->outputs[kind].name, .size = size, .align = align,
                           .type = linker->outputs[kind].type, .flags = linker->outputs[kind].flags,
                           .live = true, .output = kind};
  if (size) {
    section->owned = calloc(1, size);
    if (!section->owned) return fail(linker, "out of memory%s%s", "", "");
    section->data = section->owned;
  }
  return add_to_output(linker, &linker->outputs[kind], section);
}
static bool needs_got(uint32_t type);
static bool plan_dynamic(Linker *linker) {
  for (size_t o = 0; o < linker->object_count; ++o) {
    LinkObject *object = linker->objects[o];
    for (size_t i = 1; i < object->section_count; ++i) {
      LinkSection *section = &object->sections[i];
      if (!section->live) continue;
      for (size_t r = 0; r < section->rela_count; ++r) {
        LinkRela *rela = &section->relas[r];
        LinkSymbol *symbol = object->symbols[rela->symbol];
        if (!symbol) continue;
        if (needs_got(rela->type)) {
          if (!add_symbol(linker, &linker->got_symbols, &linker->got_count, &linker->got_capacity, symbol, &symbol->got))
            return false;
          continue;
        }
        if (!(section->flags & SHF_ALLOC)) continue;
        bool absolute = rela->type == R_X86_64_64 || rela->type == R_X86_64_32 || rela->type == R_X86_64_32S;
        bool relative = rela->type == R_X86_64_PC32 || rela->type == R_X86_64_PC64;
        if (preemptible(linker, symbol)) {
          if (rela->type == R_X86_64_PLT32) {
            if (!add_symbol(linker, &linker->plt_symbols, &linker->plt_count, &linker->plt_capacity, symbol, &symbol->plt))
              return false;
          } else if (linker->shared_output) {
            if (rela->type != R_X86_64_64)
              return fail(linker, "'%s' cannot refer to '%s' this way in a shared library; recompile with -fPIC",
                          object->path, symbol->name);
            if (!add_relocation(linker, section, rela->offset, R_X86_64_64, symbol, rela->addend)) return false;
          } else if ((absolute || relative) && function_like(symbol)) {
            /* The PLT entry stands in as the function's address. */
            symbol->canonical = true;
            if (!add_symbol(linker, &linker->plt_symbols, &linker->plt_count, &linker->plt_capacity, symbol, &symbol->plt))
              return false;
          } else if (absolute || relative) {
            /* Data the executable addresses directly is copied into .bss. */
            LinkSection *copy = calloc(1, sizeof(*copy));
            if (!copy || !grow((void **)&linker->copies, &linker->copy_capacity, linker->copy_count, sizeof(*linker->copies))) {
              free(copy);
              return fail(linker, "out of memory%s%s", "", "");
            }
            linker->copies[linker->copy_count++] = copy;
            uint64_t align = 1;
            while (align < 64 && !(symbol->shared_value & align)) align <<= 1;
            *copy = (LinkSection){.name = ".bss", .size = symbol->shared_size, .type = SHT_NOBITS, .align = align,
                                  .flags = SHF_ALLOC | SHF_WRITE, .live = true, .output = OUT_BSS};
            if (!add_to_output(linker, &linker->outputs[OUT_BSS], copy) ||
                !add_relocation(linker, copy, 0, R_X86_64_COPY, symbol, 0))
              return false;
            symbol->defined = true;
            symbol->section = copy;
            symbol->value = 0;
            symbol->size = symbol->shared_size;
            symbol->type = symbol->shared_type;
            symbol->binding = STB_GLOBAL;
            symbol->copied = true;
            symbol->shared->used = true;
            if (!add_dynsym(linker, symbol)) return false;
          }
          continue;
        }
        if (linker->shared_output && absolute && symbol->defined && !symbol->absolute) {
          if (rela->type != R_X86_64_64)
            return fail(linker, "'%s' uses absolute addressing for '%s' in a shared library; recompile with -fPIC",
                        object->path, symbol->name);
          if (!add_relocation(linker, section, rela->offset, R_X86_64_RELATIVE, symbol, rela->addend)) return false;
        }
      }
    }
  }
  /* PLT slots follow the GOT. They bind with JUMP_SLOT, which never resolves
     to an executable's own canonical PLT entry. */
  size_t slots = linker->got_count + linker->plt_count;
  if (slots) {
    linker->got = (LinkSection){.name = ".got", .size = slots * 8, .align = 8, .type = SHT_PROGBITS,
                                .flags = SHF_ALLOC | SHF_WRITE, .live = true, .output = OUT_GOT};
    if (!add_to_output(linker, &linker->outputs[OUT_GOT], &linker->got)) return false;
  }
  if (!linker->dynamic) return true;
  /* GOT slots of imports are bound at load time; position-independent
     output also rebases slots of its own definitions. */
  for (size_t i = 0; i < linker->got_count; ++i) {
    LinkSymbol *symbol = linker->got_symbols[i];
    bool ok = true;
    if (preemptible(linker, symbol)) {
      ok = add_relocation(linker, &linker->got, i * 8, R_X86_64_GLOB_DAT, symbol, 0) && add_dynsym(linker, symbol);
    } else if (linker->shared_output && symbol->defined && !symbol->absolute) {
      ok = add_relocation(linker, &linker->got, i * 8, R_X86_64_RELATIVE, symbol, 0);
    }
    if (!ok) return false;
  }
  for (size_t i = 0; i < linker->plt_count; ++i) {
    LinkSymbol *symbol = linker->plt_symbols[i];
    if (!add_relocation(linker, &linker->got, (linker->got_count + i) * 8, R_X86_64_JUMP_SLOT, symbol, 0) ||
        !add_dynsym(linker, symbol))
      return false;
  }
  for (size_t i = 0; i < linker->relocation_count; ++i)
    if (linker->relocations[i].type == R_X86_64_64 && !add_dynsym(linker, linker->relocations[i].symbol)) return false;
  for (size_t i = 0; i < linker->table_capacity; ++i) {
    LinkSymbol *symbol = linker->table[i];
    if (symbol && exported(linker, symbol) && (!symbol->section || symbol->section->live) && !add_dynsym(linker, symbol))
      return false;
  }
  /* Strings, needed libraries and symbol versions. */
  if (dynstr_add(linker, "") == UINT32_MAX) return fail(linker, "out of memory%s%s", "", "");
  for (size_t i = 0; i < linker->dynsym_count; ++i) {
    LinkSymbol *symbol = linker->dynsyms[i];
    if (!symbol->defined && symbol->shared) symbol->shared->used = true;
    symbol->dynstr = dynstr_add(linker, symbol->name);
    if (symbol->dynstr == UINT32_MAX) return fail(linker, "out of memory%s%s", "", "");
  }
  size_t needed = 0;
  for (size_t i = 0; i < linker->shared_count; ++i) {
    LinkShared *library = linker->shareds[i];
    if (library->as_needed && !library->used) continue;
    library->used = true;
    library->name_string = dynstr_add(linker, library->soname ? library->soname : library->path);
    if (library->name_string == UINT32_MAX) return fail(linker, "out of memory%s%s", "", "");
    ++needed;
  }
  for (size_t i = 0; i < linker->dynsym_count; ++i) {
    LinkSymbol *symbol = linker->dynsyms[i];
    symbol->version = 1;
    bool imported = symbol->shared && (!symbol->defined || symbol->copied);
    if (!imported || !symbol->shared_version) continue;
    size_t n = 0;
    while (n < linker->need_count &&
           (linker->needs[n].library != symbol->shared || strcmp(linker->needs[n].version, symbol->shared_version)))
      ++n;
    if (n == linker->need_count) {
      if (!grow((void **)&linker->needs, &linker->need_capacity, linker->need_count, sizeof(*linker->needs)))
        return fail(linker, "out of memory%s%s", "", "");
      linker->needs[n].library = symbol->shared;
      linker->needs[n].version = symbol->shared_version;
      linker->needs[n].string = dynstr_add(linker, symbol->shared_version);
      if (linker->needs[n].string == UINT32_MAX) return fail(linker, "out of memory%s%s", "", "");
      ++linker->need_count;
    }
    symbol->version = (uint16_t)(n + 2);
  }
  size_t libraries = 0;
  for (size_t i = 0; i < linker->shared_count; ++i) {
    bool any = false;
    for (size_t n = 0; n < linker->need_count; ++n) any |= linker->needs[n].library == linker->shareds[i];
    libraries += any;
  }
  size_t symbols = linker->dynsym_count + 1;
  linker->dynamic_entries = needed + 5 + 3 + 1 + (linker->shared_output ? 0 : 1) + 2 +
                            (linker->outputs[OUT_INIT_ARRAY].count ? 2 : 0) +
                            (linker->outputs[OUT_FINI_ARRAY].count ? 2 : 0) + (linker->need_count ? 3 : 0);
  bool ok = (linker->shared_output || synthetic(linker, OUT_INTERP, strlen(linker->interpreter) + 1, 1)) &&
            synthetic(linker, OUT_HASH, 4 * (2 + 2 * (uint64_t)symbols), 4) &&
            synthetic(linker, OUT_DYNSYM, 24 * (uint64_t)symbols, 8) &&
            synthetic(linker, OUT_DYNSTR, linker->dynstr_size, 1) &&
            (!linker->need_count || (synthetic(linker, OUT_VERSYM, 2 * (uint64_t)symbols, 2) &&
                                     synthetic(linker, OUT_VERNEED, 16 * (uint64_t)(libraries + linker->need_count), 4))) &&
            synthetic(linker, OUT_RELA_DYN, 24 * (uint64_t)linker->relocation_count, 8) &&
            (!linker->plt_count || synthetic(linker, OUT_PLT, 16 * (uint64_t)linker->plt_count, 16)) &&
            synthetic(linker, OUT_DYNAMIC, 16 * (uint64_t)linker->dynamic_entries, 8);
  if (ok) {
    linker->outputs[OUT_VERNEED].info = (uint32_t)libraries;
    memcpy(linker->synthetic[OUT_DYNSTR].owned, linker->dynstr, linker->dynstr_size);
  }
  return ok;
}

/* Segments: headers and read-only data, then code, then writable data with
   zero-fill. Each starts on a page so it can carry its own permissions. */
typedef struct {
  uint64_t offset, address, file_size, memory_size;
  uint32_t flags;
} Segment;
static void place(LinkOutput *output, uint64_t *offset, uint64_t base, bool allocated) {
  *offset = align_up(*offset, output->align);
  output->file_offset = *offset;
  output->address = allocated ? base + *offset : 0;
  uint64_t size = 0;
  for (size_t i = 0; i < output->count; ++i) {
    LinkSection *section = output->sections[i];
    size = align_up(size, section->align);
    section->offset = size;
    section->address = output->address + size;
    size += section->size;
  }
  output->size = size;
  if (output->type != SHT_NOBITS) *offset += size;
}
static size_t layout(Linker *linker, Segment *segments, uint64_t header_size) {
  static const int groups[3][2] = {{OUT_INTERP, OUT_EH_FRAME}, {OUT_TEXT, OUT_PLT}, {OUT_DYNAMIC, OUT_GOT}};
  static const uint32_t flags[3] = {4, 5, 6};
  uint64_t offset = header_size, base = linker->base;
  size_t count = 0;
  for (int g = 0; g < 3; ++g) {
    bool any = g == 0;
    for (int k = groups[g][0]; k <= groups[g][1]; ++k) any |= linker->outputs[k].count != 0;
    if (g == 2) any |= linker->outputs[OUT_BSS].count != 0;
    if (!any) continue;
    if (g) offset = align_up(offset, PAGE);
    uint64_t start = g ? offset : 0;
    for (int k = groups[g][0]; k <= groups[g][1]; ++k) place(&linker->outputs[k], &offset, base, true);
    uint64_t file_end = offset, memory_end = offset;
    if (g == 2) {
      uint64_t bss = offset;
      place(&linker->outputs[OUT_BSS], &bss, base, true);
      memory_end = bss + linker->outputs[OUT_BSS].size;
    }
    segments[count++] = (Segment){start, base + start, file_end - start, memory_end - start, flags[g]};
  }
  for (size_t e = 0; e < linker->extra_count; ++e) place(&linker->extra[e], &offset, 0, false);
  return count;
}

/* Start of .plt for the link in progress; links run one at a time. */
static uint64_t plt_address;
static uint64_t symbol_address(const LinkSymbol *symbol) {
  if (!symbol->defined) return symbol->plt ? plt_address + (uint64_t)(symbol->plt - 1) * 16 : 0;
  if (symbol->absolute || !symbol->section) return symbol->value;
  return symbol->section->address + symbol->value;
}
static void define_linker_symbols(Linker *linker, Segment *segments, size_t segment_count) {
  const LinkOutput *init = &linker->outputs[OUT_INIT_ARRAY], *fini = &linker->outputs[OUT_FINI_ARRAY];
  const LinkOutput *bss = &linker->outputs[OUT_BSS], *text = &linker->outputs[OUT_TEXT];
  const Segment *last = &segments[segment_count - 1];
  struct { const char *name; uint64_t value; } defined[] = {
    {"__ehdr_start", linker->base}, {"__executable_start", linker->base},
    {"_DYNAMIC", linker->outputs[OUT_DYNAMIC].address},
    {"__init_array_start", init->address}, {"__init_array_end", init->address + init->size},
    {"__preinit_array_start", init->address}, {"__preinit_array_end", init->address},
    {"__fini_array_start", fini->address}, {"__fini_array_end", fini->address + fini->size},
    {"_etext", text->address + text->size}, {"etext", text->address + text->size},
    {"__bss_start", bss->address}, {"_edata", last->address + last->file_size},
    {"edata", last->address + last->file_size}, {"_end", last->address + last->memory_size},
    {"end", last->address + last->memory_size},
  };
  for (size_t i = 0; i < sizeof(defined) / sizeof(*defined); ++i) {
    LinkSymbol *symbol = symbol_find(linker, defined[i].name);
    if (!symbol || symbol->defined) continue;
    symbol->defined = symbol->absolute = true;
    symbol->value = defined[i].value;
  }
}

static bool relocate(Linker *linker, LinkSection *section, uint8_t *out) {
  LinkObject *object = section->object;
  bool debug = !(section->flags & SHF_ALLOC);
  for (size_t i = 0; i < section->rela_count; ++i) {
    LinkRela *rela = &section->relas[i];
    LinkSymbol *symbol = object->symbols[rela->symbol];
    uint8_t *at = out + rela->offset;
    uint64_t place = section->address + rela->offset, addend = rela->addend;
    uint64_t value = 0;
    bool dead = false;
    if (symbol) {
      LinkSection *target = symbol_section(symbol);
      dead = symbol->defined && target && !target->live;
      if (!symbol->defined && !symbol->shared && !linker->shared_output && symbol->strong_reference && !debug)
        return fail(linker, "undefined symbol '%s' (referenced from %s)", symbol->name, object->path);
      value = symbol_address(symbol);
    }
    if (dead && debug) {
      /* Point descriptions of discarded code at nothing, as lld does. */
      bool ranges = !strcmp(section->name, ".debug_ranges") || !strcmp(section->name, ".debug_loc");
      if (rela->type == R_X86_64_64) write64(at, ranges ? 1 : 0);
      else if (rela->type == R_X86_64_32) write32(at, 0);
      continue;
    }
    if (dead) return fail(linker, "'%s' references discarded section of '%s'", object->path, symbol->name);
    uint64_t result;
    int width;
    bool is_signed = true;
    switch (rela->type) {
    case R_X86_64_NONE: continue;
    case R_X86_64_64: result = value + addend; width = 64; break;
    case R_X86_64_32: result = value + addend; width = 32; is_signed = false; break;
    case R_X86_64_32S: result = value + addend; width = 32; break;
    case R_X86_64_PLT32:
      if (symbol && symbol->plt) value = plt_address + (uint64_t)(symbol->plt - 1) * 16;
      result = value + addend - place;
      width = 32;
      break;
    case R_X86_64_PC32: result = value + addend - place; width = 32; break;
    case R_X86_64_PC64: result = value + addend - place; width = 64; break;
    case R_X86_64_SIZE32: result = (symbol ? symbol->size : 0) + addend; width = 32; is_signed = false; break;
    case R_X86_64_SIZE64: result = (symbol ? symbol->size : 0) + addend; width = 64; break;
    case R_X86_64_GOTPCREL: case R_X86_64_GOTPCRELX: case R_X86_64_REX_GOTPCRELX:
      /* A load of a defined symbol's address becomes lea, as lld does. */
      if (rela->type != R_X86_64_GOTPCREL && symbol->defined && !symbol->absolute && !preemptible(linker, symbol) &&
          rela->offset >= 2 && at[-2] == 0x8b) {
        at[-2] = 0x8d;
        result = value + addend - place;
        width = 32;
        break;
      }
      result = linker->got.address + (uint64_t)(symbol->got - 1) * 8 + addend - place;
      width = 32;
      break;
    default: {
      char type[32];
      snprintf(type, sizeof(type), "%u", rela->type);
      return fail(linker, "unsupported relocation type %s in '%s'", type, object->path);
    }
    }
    if (rela->offset + width / 8 > section->size)
      return fail(linker, "relocation outside its section in '%s'%s", object->path, "");
    if (width == 64) { write64(at, result); continue; }
    bool fits = is_signed ? (int64_t)result == (int64_t)(int32_t)(uint32_t)result : result <= UINT32_MAX;
    if (!fits && !debug)
      return fail(linker, "relocation to '%s' out of range in '%s'", symbol ? symbol->name : "?", object->path);
    write32(at, (uint32_t)result);
  }
  return true;
}

/* A symbol table lets debuggers and profilers name code without DWARF. */
typedef struct {
  uint8_t *data;
  size_t size, capacity;
} Bytes;
static bool bytes_append(Bytes *bytes, const void *data, size_t size) {
  while (bytes->size + size > bytes->capacity) {
    size_t next = bytes->capacity ? bytes->capacity * 2 : 4096;
    uint8_t *grown = realloc(bytes->data, next);
    if (!grown) return false;
    bytes->data = grown;
    bytes->capacity = next;
  }
  memcpy(bytes->data + bytes->size, data, size);
  bytes->size += size;
  return true;
}
static uint16_t output_index(Linker *linker, const LinkSymbol *symbol) {
  if (symbol->absolute || !symbol->section) return SHN_ABS;
  int output = symbol->section->output;
  if (output < 0) return SHN_UNDEF;
  return (uint16_t)(output < OUT_ALLOC_COUNT ? linker->outputs[output].header_index
                                             : linker->extra[output - OUT_ALLOC_COUNT].header_index);
}
static bool symbol_entry(Linker *linker, Bytes *symbols, Bytes *names, const LinkSymbol *symbol, bool global) {
  uint8_t entry[24] = {0};
  write32(entry, (uint32_t)names->size);
  entry[4] = (uint8_t)((global ? symbol->binding : STB_LOCAL) << 4 | symbol->type);
  write16(entry + 6, output_index(linker, symbol));
  write64(entry + 8, symbol_address(symbol));
  write64(entry + 16, symbol->size);
  return bytes_append(names, symbol->name, strlen(symbol->name) + 1) && bytes_append(symbols, entry, 24);
}
static bool listed(const LinkSymbol *symbol) {
  if (!symbol->defined || !symbol->name[0]) return false;
  if (symbol->type != STT_FUNC && symbol->type != STT_OBJECT && symbol->type != STT_NOTYPE) return false;
  if (symbol->section && (!symbol->section->live || symbol->section->output < 0 ||
                          symbol->section->output >= OUT_ALLOC_COUNT))
    return false;
  return symbol->name[0] != '.';
}
static bool build_symtab(Linker *linker, Bytes *symbols, Bytes *names, uint32_t *first_global) {
  uint8_t zero[24] = {0};
  if (!bytes_append(symbols, zero, 24) || !bytes_append(names, "", 1)) return false;
  for (size_t o = 0; o < linker->object_count; ++o) {
    LinkObject *object = linker->objects[o];
    for (size_t i = 1; i < object->symbol_count; ++i) {
      LinkSymbol *symbol = object->symbols[i];
      if (symbol && symbol == &object->locals[i] && listed(symbol) &&
          !symbol_entry(linker, symbols, names, symbol, false))
        return false;
    }
  }
  *first_global = (uint32_t)(symbols->size / 24);
  for (size_t i = 0; i < linker->table_capacity; ++i) {
    LinkSymbol *symbol = linker->table[i];
    if (symbol && listed(symbol) && !symbol->absolute && !symbol_entry(linker, symbols, names, symbol, true))
      return false;
  }
  return true;
}

/* With a sample profile, order code by its call graph the way lld does by
   default (cache-directed sort): profiled sections first in layout order, then
   the rest in input order. */
typedef struct {
  LinkSection *from, *to;
  uint64_t weight;
} SectionEdge;
static bool order_text(Linker *linker, DynLinkLayout layout) {
  LinkOutput *text = &linker->outputs[OUT_TEXT];
  SectionEdge *edges = NULL;
  size_t edge_count = 0, edge_capacity = 0;
  bool ok = true;
  for (size_t o = 0; ok && o < linker->object_count; ++o) {
    LinkObject *object = linker->objects[o];
    for (size_t i = 0; ok && i < object->profile_count; ++i) {
      LinkSymbol *from = object->symbols[object->profile[i].from], *to = object->symbols[object->profile[i].to];
      LinkSection *a = from ? symbol_section(from) : NULL, *b = to ? symbol_section(to) : NULL;
      if (!a || !b) continue;
      size_t k = 0;
      while (k < edge_count && (edges[k].from != a || edges[k].to != b)) ++k;
      if (k == edge_count) {
        if (!(ok = grow((void **)&edges, &edge_capacity, edge_count, sizeof(*edges)))) break;
        edges[edge_count++] = (SectionEdge){a, b, 0};
      }
      edges[k].weight += object->profile[i].weight;
    }
  }
  LinkSection **nodes = NULL;
  uint64_t *sizes = NULL, *counts = NULL, *offsets = NULL, *order = NULL;
  DynLinkEdge *calls = NULL;
  size_t node_count = 0, call_count = 0;
  if (ok && edge_count) {
    nodes = calloc(edge_count * 2, sizeof(*nodes));
    sizes = calloc(edge_count * 2, sizeof(*sizes));
    counts = calloc(edge_count * 2, sizeof(*counts));
    order = calloc(edge_count * 2, sizeof(*order));
    offsets = calloc(edge_count, sizeof(*offsets));
    calls = calloc(edge_count, sizeof(*calls));
    ok = nodes && sizes && counts && order && offsets && calls;
  }
  for (size_t k = 0; ok && k < edge_count; ++k) {
    SectionEdge *edge = &edges[k];
    bool same = edge->from->live && edge->to->live && edge->from->output == edge->to->output;
    if (!same || !edge->weight) continue;
    size_t ends[2];
    LinkSection *pair[2] = {edge->from, edge->to};
    for (int e = 0; e < 2; ++e) {
      size_t n = 0;
      while (n < node_count && nodes[n] != pair[e]) ++n;
      if (n == node_count) {
        nodes[node_count] = pair[e];
        sizes[node_count] = pair[e]->size;
        counts[node_count++] = 0;
      }
      ends[e] = n;
    }
    if (ends[0] == ends[1]) continue;
    calls[call_count] = (DynLinkEdge){ends[0], ends[1], edge->weight};
    offsets[call_count++] = (sizes[ends[0]] + 1) / 2;
    counts[ends[1]] += edge->weight;
  }
  if (ok && node_count && nodes[0]->output == OUT_TEXT) {
    ok = layout(sizes, counts, node_count, calls, offsets, call_count, order);
    if (ok) {
      LinkSection **sorted = malloc(text->count * sizeof(*sorted));
      ok = sorted != NULL;
      size_t at = 0;
      for (size_t n = 0; ok && n < node_count; ++n)
        if (order[n] < node_count && nodes[order[n]]->output == OUT_TEXT) sorted[at++] = nodes[order[n]];
      for (size_t i = 0; ok && i < text->count; ++i) {
        size_t n = 0;
        while (n < node_count && nodes[n] != text->sections[i]) ++n;
        if (n == node_count) sorted[at++] = text->sections[i];
      }
      if (ok && at == text->count) memcpy(text->sections, sorted, at * sizeof(*sorted));
      free(sorted);
    }
  }
  free(edges); free(nodes); free(sizes); free(counts); free(offsets); free(order); free(calls);
  return ok || fail(linker, "call-graph ordering failed%s%s", "", "");
}
/* Writes .interp, .hash, .dynsym, versions, .rela.dyn, .plt and .dynamic
   once addresses and section indexes are final. */
static uint16_t output_index(Linker *linker, const LinkSymbol *symbol);
static void fill_dynamic(Linker *linker) {
  LinkSection *section = &linker->synthetic[OUT_INTERP];
  if (section->owned) memcpy(section->owned, linker->interpreter, strlen(linker->interpreter) + 1);
  size_t symbols = linker->dynsym_count + 1;
  uint8_t *dynsym = linker->synthetic[OUT_DYNSYM].owned;
  for (size_t i = 0; i < linker->dynsym_count; ++i) {
    LinkSymbol *symbol = linker->dynsyms[i];
    uint8_t *entry = dynsym + (i + 1) * 24;
    uint8_t binding = symbol->defined ? (symbol->binding == STB_WEAK ? STB_WEAK : STB_GLOBAL)
                                      : (symbol->strong_reference || symbol->shared ? STB_GLOBAL : STB_WEAK);
    uint8_t type = symbol->defined ? symbol->type : symbol->shared_type == STT_GNU_IFUNC ? STT_FUNC : symbol->shared_type;
    write32(entry, symbol->dynstr);
    entry[4] = (uint8_t)(binding << 4 | type);
    entry[5] = symbol->defined ? symbol->visibility : 0;
    write16(entry + 6, symbol->defined ? output_index(linker, symbol) : SHN_UNDEF);
    write64(entry + 8, symbol->defined || symbol->canonical ? symbol_address(symbol) : 0);
    write64(entry + 16, symbol->defined ? symbol->size : 0);
  }
  /* SysV hash: one bucket per symbol. */
  uint8_t *hash = linker->synthetic[OUT_HASH].owned;
  write32(hash, (uint32_t)symbols);
  write32(hash + 4, (uint32_t)symbols);
  for (size_t i = 0; i < linker->dynsym_count; ++i) {
    uint32_t bucket = elf_hash(linker->dynsyms[i]->name) % (uint32_t)symbols;
    uint8_t *head = hash + 8 + bucket * 4;
    write32(hash + 8 + (symbols + i + 1) * 4, read32(head));
    write32(head, (uint32_t)(i + 1));
  }
  if (linker->need_count) {
    uint8_t *versions = linker->synthetic[OUT_VERSYM].owned;
    for (size_t i = 0; i < linker->dynsym_count; ++i) write16(versions + (i + 1) * 2, linker->dynsyms[i]->version);
    uint8_t *need = linker->synthetic[OUT_VERNEED].owned, *previous = NULL;
    for (size_t l = 0; l < linker->shared_count; ++l) {
      LinkShared *library = linker->shareds[l];
      uint16_t count = 0;
      for (size_t n = 0; n < linker->need_count; ++n) count += linker->needs[n].library == library;
      if (!count) continue;
      if (previous) write32(previous + 12, (uint32_t)(need - previous));
      write16(need, 1);
      write16(need + 2, count);
      write32(need + 4, library->name_string);
      write32(need + 8, 16);
      uint8_t *aux = need + 16, *last = NULL;
      for (size_t n = 0; n < linker->need_count; ++n) {
        if (linker->needs[n].library != library) continue;
        if (last) write32(last + 12, 16);
        write32(aux, elf_hash(linker->needs[n].version));
        write16(aux + 6, (uint16_t)(n + 2));
        write32(aux + 8, linker->needs[n].string);
        last = aux;
        aux += 16;
      }
      previous = need;
      need = aux;
    }
  }
  uint8_t *rela = linker->synthetic[OUT_RELA_DYN].owned;
  for (size_t i = 0; i < linker->relocation_count; ++i) {
    DynamicRelocation *relocation = &linker->relocations[i];
    uint8_t *entry = rela + i * 24;
    bool relative = relocation->type == R_X86_64_RELATIVE;
    write64(entry, relocation->section->address + relocation->offset);
    write64(entry + 8, (uint64_t)(relative ? 0 : relocation->symbol->dynsym) << 32 | relocation->type);
    write64(entry + 16, relative ? symbol_address(relocation->symbol) + relocation->addend : relocation->addend);
  }
  /* Each PLT entry jumps through its GOT slot: jmp *slot(%rip), then traps. */
  uint8_t *plt = linker->synthetic[OUT_PLT].owned;
  for (size_t i = 0; plt && i < linker->plt_count; ++i) {
    uint8_t *entry = plt + i * 16;
    uint64_t at = linker->synthetic[OUT_PLT].address + i * 16;
    uint64_t slot = linker->got.address + (uint64_t)(linker->got_count + i) * 8;
    memset(entry, 0xcc, 16);
    entry[0] = 0xff;
    entry[1] = 0x25;
    write32(entry + 2, (uint32_t)(slot - (at + 6)));
  }
  uint8_t *dynamic = linker->synthetic[OUT_DYNAMIC].owned;
  size_t n = 0;
#define DYNAMIC_ENTRY(tag, value) (write64(dynamic + n * 16, (tag)), write64(dynamic + n * 16 + 8, (value)), ++n)
  for (size_t l = 0; l < linker->shared_count; ++l)
    if (linker->shareds[l]->used) DYNAMIC_ENTRY(DT_NEEDED, linker->shareds[l]->name_string);
  if (!linker->shared_output) DYNAMIC_ENTRY(DT_DEBUG, 0);
  if (linker->outputs[OUT_INIT_ARRAY].count) {
    DYNAMIC_ENTRY(DT_INIT_ARRAY, linker->outputs[OUT_INIT_ARRAY].address);
    DYNAMIC_ENTRY(DT_INIT_ARRAYSZ, linker->outputs[OUT_INIT_ARRAY].size);
  }
  if (linker->outputs[OUT_FINI_ARRAY].count) {
    DYNAMIC_ENTRY(DT_FINI_ARRAY, linker->outputs[OUT_FINI_ARRAY].address);
    DYNAMIC_ENTRY(DT_FINI_ARRAYSZ, linker->outputs[OUT_FINI_ARRAY].size);
  }
  DYNAMIC_ENTRY(DT_HASH, linker->synthetic[OUT_HASH].address);
  DYNAMIC_ENTRY(DT_STRTAB, linker->synthetic[OUT_DYNSTR].address);
  DYNAMIC_ENTRY(DT_SYMTAB, linker->synthetic[OUT_DYNSYM].address);
  DYNAMIC_ENTRY(DT_STRSZ, linker->dynstr_size);
  DYNAMIC_ENTRY(DT_SYMENT, 24);
  DYNAMIC_ENTRY(DT_RELA, linker->synthetic[OUT_RELA_DYN].address);
  DYNAMIC_ENTRY(DT_RELASZ, linker->relocation_count * 24);
  DYNAMIC_ENTRY(DT_RELAENT, 24);
  if (linker->need_count) {
    DYNAMIC_ENTRY(DT_VERSYM, linker->synthetic[OUT_VERSYM].address);
    DYNAMIC_ENTRY(DT_VERNEED, linker->synthetic[OUT_VERNEED].address);
    DYNAMIC_ENTRY(DT_VERNEEDNUM, linker->outputs[OUT_VERNEED].info);
  }
  /* Slots are filled at load time, so there is no lazy PLT. */
  DYNAMIC_ENTRY(DT_FLAGS, DF_BIND_NOW);
  DYNAMIC_ENTRY(DT_FLAGS_1, DF_1_NOW);
  DYNAMIC_ENTRY(DT_NULL, 0);
#undef DYNAMIC_ENTRY
}
static bool write_output(Linker *linker, const char *entry_name) {
  Segment segments[3];
  /* Loads and the stack note; dynamic output adds PT_DYNAMIC, and
     executables PT_PHDR and PT_INTERP. */
  const size_t phdr_count = linker->dynamic ? (linker->shared_output ? 5 : 7) : 4;
  uint64_t header_size = 64 + 56 * phdr_count;
  size_t segment_count = layout(linker, segments, header_size);
  plt_address = linker->outputs[OUT_PLT].address;
  define_linker_symbols(linker, segments, segment_count);
  /* Section headers: null, allocated outputs, extras, .symtab, .strtab, .shstrtab. */
  Bytes shstrtab = {0}, symtab = {0}, strtab = {0};
  uint32_t header_count = 1;
  bool ok = bytes_append(&shstrtab, "", 1);
  uint32_t name_offsets[OUT_ALLOC_COUNT + 64];
  for (int k = 0; ok && k < OUT_ALLOC_COUNT; ++k) {
    if (!linker->outputs[k].count) continue;
    linker->outputs[k].header_index = header_count++;
    name_offsets[k] = (uint32_t)shstrtab.size;
    ok = bytes_append(&shstrtab, linker->outputs[k].name, strlen(linker->outputs[k].name) + 1);
  }
  uint32_t *extra_names = calloc(linker->extra_count + 1, sizeof(*extra_names));
  ok = ok && extra_names;
  for (size_t e = 0; ok && e < linker->extra_count; ++e) {
    linker->extra[e].header_index = header_count++;
    extra_names[e] = (uint32_t)shstrtab.size;
    ok = bytes_append(&shstrtab, linker->extra[e].name, strlen(linker->extra[e].name) + 1);
  }
  uint32_t symtab_name = (uint32_t)shstrtab.size;
  ok = ok && bytes_append(&shstrtab, ".symtab", 8);
  uint32_t strtab_name = (uint32_t)shstrtab.size;
  ok = ok && bytes_append(&shstrtab, ".strtab", 8);
  uint32_t shstrtab_name = (uint32_t)shstrtab.size;
  ok = ok && bytes_append(&shstrtab, ".shstrtab", 10);
  uint32_t first_global = 0;
  ok = ok && build_symtab(linker, &symtab, &strtab, &first_global);
  if (ok && linker->dynamic) fill_dynamic(linker);
  if (!ok) {
    free(extra_names); free(shstrtab.data); free(symtab.data); free(strtab.data);
    return fail(linker, "out of memory%s%s", "", "");
  }
  uint64_t end = header_size;
  for (int k = 0; k < OUT_ALLOC_COUNT; ++k)
    if (linker->outputs[k].count && linker->outputs[k].type != SHT_NOBITS &&
        linker->outputs[k].file_offset + linker->outputs[k].size > end)
      end = linker->outputs[k].file_offset + linker->outputs[k].size;
  for (size_t e = 0; e < linker->extra_count; ++e)
    if (linker->extra[e].file_offset + linker->extra[e].size > end)
      end = linker->extra[e].file_offset + linker->extra[e].size;
  uint64_t symtab_offset = align_up(end, 8);
  uint64_t strtab_offset = symtab_offset + symtab.size;
  uint64_t shstrtab_offset = strtab_offset + strtab.size;
  uint64_t section_headers = align_up(shstrtab_offset + shstrtab.size, 8);
  header_count += 3;
  uint64_t file_size = section_headers + (uint64_t)header_count * 64;
  uint8_t *image = calloc(1, file_size);
  if (!image) {
    free(extra_names); free(shstrtab.data); free(symtab.data); free(strtab.data);
    return fail(linker, "out of memory%s%s", "", "");
  }
  /* Section contents, relocated in place. */
  for (int k = 0; ok && k < OUT_ALLOC_COUNT; ++k) {
    LinkOutput *output = &linker->outputs[k];
    if (output->type == SHT_NOBITS) continue;
    /* Gaps between functions trap, as with lld. */
    if (k == OUT_TEXT) memset(image + output->file_offset, 0xcc, output->size);
    for (size_t i = 0; ok && i < output->count; ++i) {
      LinkSection *section = output->sections[i];
      uint8_t *at = image + output->file_offset + section->offset;
      if (section == &linker->got) {
        for (size_t g = 0; g < linker->got_count; ++g)
          if (!preemptible(linker, linker->got_symbols[g])) write64(at + g * 8, symbol_address(linker->got_symbols[g]));
        continue;
      }
      if (section->data) memcpy(at, section->data, section->size);
      if (section->object) ok = relocate(linker, section, at);
    }
  }
  for (size_t e = 0; ok && e < linker->extra_count; ++e) {
    LinkOutput *output = &linker->extra[e];
    for (size_t i = 0; ok && i < output->count; ++i) {
      LinkSection *section = output->sections[i];
      uint8_t *at = image + output->file_offset + section->offset;
      if (section->data) memcpy(at, section->data, section->size);
      ok = relocate(linker, section, at);
    }
  }
  LinkSymbol *entry = entry_name ? symbol_find(linker, entry_name) : NULL;
  if (ok) {
    memcpy(image, "\x7f" "ELF\x02\x01\x01", 7);
    write16(image + 16, linker->shared_output ? ELF_DYN : ELF_EXEC);
    write16(image + 18, MACHINE_X86_64);
    write32(image + 20, 1);
    write64(image + 24, entry ? symbol_address(entry) : 0);
    write64(image + 32, 64);
    write64(image + 40, section_headers);
    write16(image + 52, 64);
    write16(image + 54, 56);
    write16(image + 56, (uint16_t)phdr_count);
    write16(image + 58, 64);
    write16(image + 60, (uint16_t)header_count);
    write16(image + 62, (uint16_t)(header_count - 1));
    uint8_t *p = image + 64;
#define PROGRAM_HEADER(type, flags, offset, address, file_size, memory_size, align)                                  \
  (write32(p, (type)), write32(p + 4, (flags)), write64(p + 8, (offset)), write64(p + 16, (address)),                 \
   write64(p + 24, (address)), write64(p + 32, (file_size)), write64(p + 40, (memory_size)), write64(p + 48, (align)), \
   p += 56)
    if (linker->dynamic && !linker->shared_output) {
      const LinkOutput *interp = &linker->outputs[OUT_INTERP];
      PROGRAM_HEADER(PT_PHDR, 4, 64, linker->base + 64, 56 * phdr_count, 56 * phdr_count, 8);
      PROGRAM_HEADER(PT_INTERP, 4, interp->file_offset, interp->address, interp->size, interp->size, 1);
    }
    for (size_t s = 0; s < segment_count; ++s)
      PROGRAM_HEADER(PT_LOAD, segments[s].flags, segments[s].offset, segments[s].address, segments[s].file_size,
                     segments[s].memory_size, PAGE);
    if (linker->dynamic) {
      const LinkOutput *dynamic = &linker->outputs[OUT_DYNAMIC];
      PROGRAM_HEADER(PT_DYNAMIC, 6, dynamic->file_offset, dynamic->address, dynamic->size, dynamic->size, 8);
    }
    PROGRAM_HEADER(PT_GNU_STACK, 6, 0, 0, 0, 0, 16);
#undef PROGRAM_HEADER
    memcpy(image + symtab_offset, symtab.data, symtab.size);
    memcpy(image + strtab_offset, strtab.data, strtab.size);
    memcpy(image + shstrtab_offset, shstrtab.data, shstrtab.size);
    uint8_t *h = image + section_headers + 64;
    for (int k = 0; k < OUT_ALLOC_COUNT; ++k) {
      LinkOutput *output = &linker->outputs[k];
      if (!output->count) continue;
      write32(h, name_offsets[k]);
      write32(h + 4, output->type);
      write64(h + 8, output->flags);
      write64(h + 16, output->address);
      write64(h + 24, output->file_offset);
      write64(h + 32, output->size);
      write64(h + 48, output->align);
      write64(h + 56, output->entry_size);
      if (output->link >= 0) write32(h + 40, linker->outputs[output->link].header_index);
      write32(h + 44, output->info);
      h += 64;
    }
    for (size_t e = 0; e < linker->extra_count; ++e) {
      LinkOutput *output = &linker->extra[e];
      write32(h, extra_names[e]);
      write32(h + 4, SHT_PROGBITS);
      write64(h + 24, output->file_offset);
      write64(h + 32, output->size);
      write64(h + 48, output->align);
      h += 64;
    }
    uint32_t base = header_count - 3;
    write32(h, symtab_name); write32(h + 4, SHT_SYMTAB);
    write64(h + 24, symtab_offset); write64(h + 32, symtab.size);
    write32(h + 40, base + 1); write32(h + 44, first_global);
    write64(h + 48, 8); write64(h + 56, 24);
    h += 64;
    write32(h, strtab_name); write32(h + 4, SHT_STRTAB);
    write64(h + 24, strtab_offset); write64(h + 32, strtab.size); write64(h + 48, 1);
    h += 64;
    write32(h, shstrtab_name); write32(h + 4, SHT_STRTAB);
    write64(h + 24, shstrtab_offset); write64(h + 32, shstrtab.size); write64(h + 48, 1);
  }
  free(extra_names); free(shstrtab.data); free(symtab.data); free(strtab.data);
  if (ok) {
    FILE *file = fopen(linker->output_path, "wb");
    ok = file && fwrite(image, 1, file_size, file) == file_size;
    if (file && fclose(file)) ok = false;
    if (!ok) fail(linker, "cannot write '%s'%s", linker->output_path, "");
#ifndef _WIN32
    if (ok && chmod(linker->output_path, 0755)) ok = fail(linker, "cannot mark '%s' executable%s", linker->output_path, "");
#endif
  }
  free(image);
  return ok;
}

static void linker_free(Linker *linker) {
  for (size_t o = 0; o < linker->object_count; ++o) {
    LinkObject *object = linker->objects[o];
    for (size_t i = 0; i < object->section_count; ++i) {
      free(object->sections[i].relas);
      free(object->sections[i].owned);
    }
    free(object->sections);
    free(object->symbols);
    free(object->locals);
    free(object->profile);
    free(object);
  }
  for (size_t i = 0; i < linker->shared_count; ++i) {
    free(linker->shareds[i]->versions);
    free(linker->shareds[i]);
  }
  free(linker->shareds);
  for (size_t i = 0; i < linker->copy_count; ++i) free(linker->copies[i]);
  free(linker->copies);
  for (int k = 0; k < OUT_ALLOC_COUNT; ++k) free(linker->synthetic[k].owned);
  free(linker->plt_symbols);
  free(linker->dynsyms);
  free(linker->relocations);
  free(linker->needs);
  free(linker->dynstr);
  free(linker->objects);
  free(linker->archives);
  for (size_t i = 0; i < linker->buffer_count; ++i) free(linker->buffers[i]);
  free(linker->buffers);
  for (size_t i = 0; i < linker->table_capacity; ++i) free(linker->table[i]);
  free(linker->table);
  for (size_t i = 0; i < linker->common_count; ++i) free(linker->commons[i]);
  free(linker->commons);
  free(linker->got_symbols);
  for (int k = 0; k < OUT_ALLOC_COUNT; ++k) free(linker->outputs[k].sections);
  for (size_t e = 0; e < linker->extra_count; ++e) free(linker->extra[e].sections);
  free(linker->extra);
  free(linker->signatures);
}

bool dyn_link_elf_supported(const char *path) {
  FILE *file = fopen(path, "rb");
  if (!file) return true; /* Let the link report the missing input. */
  uint8_t magic[20] = {0};
  size_t n = fread(magic, 1, sizeof(magic), file);
  fclose(file);
  if (n >= 8 && !memcmp(magic, "!<arch>\n", 8)) return true;
  if (n >= 20 && !memcmp(magic, "\x7f" "ELF", 4))
    return magic[4] == 2 && (read16(magic + 16) == ELF_REL || read16(magic + 16) == ELF_DYN) &&
           read16(magic + 18) == MACHINE_X86_64;
  return is_script(magic, n);
}

int dyn_link_elf(const char *const *inputs, size_t input_count, const char *output, const DynLinkOptions *options) {
  Linker linker = {.output_path = output, .shared_output = options->shared,
                   .interpreter = options->interpreter ? options->interpreter : "/lib64/ld-linux-x86-64.so.2",
                   .base = options->shared ? 0 : IMAGE_BASE};
  const char *entry = options->shared ? NULL : options->entry;
  bool ok = true;
  for (size_t i = 0; ok && i < input_count; ++i) ok = load_input(&linker, inputs[i], false, 0);
  linker.dynamic = linker.shared_output || linker.shared_count;
  ok = ok && resolve_archives(&linker) && allocate_commons(&linker) && collect_garbage(&linker, entry) &&
       assign_outputs(&linker) && plan_dynamic(&linker) && (!options->layout || order_text(&linker, options->layout)) &&
       write_output(&linker, entry);
  if (!ok) {
    fprintf(stderr, "error: link: %s\n", linker.error[0] ? linker.error : "out of memory");
    remove(output);
  }
  linker_free(&linker);
  return ok ? 0 : 2;
}

/* Global symbols that non-bitcode inputs define or reference, for ThinLTO
   symbol resolution. Archive members count only through their references,
   since a bitcode definition keeps them from loading. */
typedef struct {
  char **names;
  size_t count, capacity;
} NameList;
static bool name_add(NameList *list, const char *name, size_t length) {
  if (!grow((void **)&list->names, &list->capacity, list->count, sizeof(*list->names))) return false;
  char *copy = malloc(length + 1);
  if (!copy) return false;
  memcpy(copy, name, length);
  copy[length] = 0;
  list->names[list->count++] = copy;
  return true;
}
static bool scan_symbols(const uint8_t *data, size_t size, bool member, NameList *defined, NameList *used) {
  if (size < 64 || memcmp(data, "\x7f" "ELF", 4) || data[4] != 2 || data[5] != 1) return true;
  uint16_t kind = read16(data + 16);
  if (kind != ELF_REL && kind != 3) return true;
  uint64_t header_offset = read64(data + 40);
  size_t count = read16(data + 60);
  if (!in_bounds(size, header_offset, (uint64_t)count * 64)) return true;
  const uint8_t *headers = data + header_offset;
  uint32_t wanted = kind == ELF_REL ? SHT_SYMTAB : 11; /* SHT_DYNSYM */
  for (size_t i = 0; i < count; ++i) {
    const uint8_t *h = headers + i * 64;
    if (read32(h + 4) != wanted) continue;
    uint32_t link = read32(h + 40);
    if (link >= count) continue;
    const uint8_t *sh = headers + (size_t)link * 64;
    uint64_t offset = read64(h + 24), length = read64(h + 32);
    uint64_t names = read64(sh + 24), names_size = read64(sh + 32);
    if (!in_bounds(size, offset, length) || !in_bounds(size, names, names_size)) continue;
    for (uint64_t at = 24; at + 24 <= length; at += 24) {
      const uint8_t *entry = data + offset + at;
      uint8_t binding = entry[4] >> 4;
      uint32_t name = read32(entry);
      if (binding == STB_LOCAL || name >= names_size) continue;
      const char *text = (const char *)data + names + name;
      const char *end = memchr(text, 0, names_size - name);
      if (!end || !*text) continue;
      bool undefined = read16(entry + 6) == SHN_UNDEF;
      /* Shared libraries' definitions never displace bitcode ones. */
      NameList *list = undefined ? used : kind == ELF_REL && !member ? defined : NULL;
      if (list && !name_add(list, text, (size_t)(end - text))) return false;
    }
  }
  return true;
}
static bool scan_archive(const uint8_t *data, size_t size, NameList *defined, NameList *used) {
  for (size_t at = 8; at + 60 <= size;) {
    const uint8_t *header = data + at;
    size_t member_size = (size_t)strtoull((const char *)header + 48, NULL, 10);
    size_t body = at + 60;
    if (member_size > size - body) return true;
    const uint8_t *member = data + body;
    size_t length = member_size;
    if (!memcmp(header, "#1/", 3)) {
      size_t skip = (size_t)strtoull((const char *)header + 3, NULL, 10);
      if (skip > length) return true;
      member += skip;
      length -= skip;
    }
    if (!scan_symbols(member, length, true, defined, used)) return false;
    at = body + member_size + (member_size & 1);
  }
  return true;
}
void dyn_link_elf_names_free(char **names, size_t count) {
  for (size_t i = 0; i < count; ++i) free(names[i]);
  free(names);
}
typedef struct {
  NameList *defined, *used;
  int depth;
} ScanContext;
static bool scan_file(const char *path, NameList *defined, NameList *used, int depth);
static bool scan_script_file(void *context, const char *word, size_t length, bool as_needed) {
  ScanContext *scan = context;
  (void)as_needed;
  char path[4096];
  if (length >= sizeof(path)) return true;
  memcpy(path, word, length);
  path[length] = 0;
  return scan_file(path, scan->defined, scan->used, scan->depth + 1);
}
static bool scan_file(const char *path, NameList *defined, NameList *used, int depth) {
  Linker scratch = {0};
  size_t size = 0;
  uint8_t *data = read_file(&scratch, path, &size);
  bool ok = true;
  if (data) {
    if (size >= 8 && !memcmp(data, "!<arch>\n", 8)) {
      ok = scan_archive(data, size, defined, used);
    } else if (size >= 4 && !memcmp(data, "\x7f" "ELF", 4)) {
      ok = scan_symbols(data, size, false, defined, used);
    } else if (depth < 4 && is_script(data, size)) {
      ScanContext scan = {defined, used, depth};
      parse_script((const char *)data, size, scan_script_file, &scan);
    }
  }
  linker_free(&scratch);
  return ok;
}
bool dyn_link_elf_symbols(const char *const *inputs, size_t input_count, char ***defined, size_t *defined_count,
                          char ***used, size_t *used_count) {
  NameList define = {0}, use = {0};
  bool ok = true;
  for (size_t i = 0; ok && i < input_count; ++i) ok = scan_file(inputs[i], &define, &use, 0);
  if (!ok) {
    dyn_link_elf_names_free(define.names, define.count);
    dyn_link_elf_names_free(use.names, use.count);
    return false;
  }
  *defined = define.names;
  *defined_count = define.count;
  *used = use.names;
  *used_count = use.count;
  return true;
}
