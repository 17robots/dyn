/* Built-in static ELF linker for executables, so a build needs no external
   linker. Inputs are relocatable objects and ar archives; the output is a
   non-PIE executable with unused sections removed, matching what the
   compiler previously asked ld.lld for. The host may be any OS, so ELF
   structures are read field by field instead of through <elf.h>. */
#include "link_elf.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

enum {
  ELF_REL = 1, ELF_EXEC = 2,
  MACHINE_X86_64 = 62,
  SHT_PROGBITS = 1, SHT_SYMTAB = 2, SHT_STRTAB = 3, SHT_RELA = 4, SHT_NOBITS = 8,
  SHT_REL = 9, SHT_INIT_ARRAY = 14, SHT_FINI_ARRAY = 15, SHT_PREINIT_ARRAY = 16,
  SHT_GROUP = 17, SHT_SYMTAB_SHNDX = 18, SHT_X86_64_UNWIND = 0x70000001,
  SHF_WRITE = 1, SHF_ALLOC = 2, SHF_EXEC = 4, SHF_GROUP = 0x200, SHF_TLS = 0x400,
  SHF_RETAIN = 0x200000,
  SHN_UNDEF = 0, SHN_ABS = 0xfff1, SHN_COMMON = 0xfff2, SHN_XINDEX = 0xffff,
  STB_LOCAL = 0, STB_GLOBAL = 1, STB_WEAK = 2,
  STT_NOTYPE = 0, STT_OBJECT = 1, STT_FUNC = 2, STT_SECTION = 3, STT_FILE = 4, STT_TLS = 6,
  PT_LOAD = 1, PT_GNU_STACK = 0x6474e551,
  GRP_COMDAT = 1,
};
enum {
  R_X86_64_NONE = 0, R_X86_64_64 = 1, R_X86_64_PC32 = 2, R_X86_64_PLT32 = 4,
  R_X86_64_GOTPCREL = 9, R_X86_64_32 = 10, R_X86_64_32S = 11, R_X86_64_PC64 = 24,
  R_X86_64_SIZE32 = 32, R_X86_64_SIZE64 = 33, R_X86_64_GOTPCRELX = 41,
  R_X86_64_REX_GOTPCRELX = 42,
};
#define PAGE 0x1000u
#define IMAGE_BASE 0x200000u
#define SHF_EXCLUDE 0x80000000u

typedef struct LinkObject LinkObject;
typedef struct LinkSymbol LinkSymbol;
typedef struct {
  uint64_t offset, addend;
  uint32_t type, symbol;
} LinkRela;
typedef enum {
  OUT_TEXT, OUT_RODATA, OUT_EH_FRAME, OUT_INIT_ARRAY, OUT_FINI_ARRAY,
  OUT_DATA, OUT_GOT, OUT_BSS, OUT_ALLOC_COUNT
} OutputKind;
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
  uint8_t binding, type;
  bool defined, absolute, common, referenced, strong_reference;
  uint32_t got; /* One-based GOT slot. */
  int archive_member; /* Lazy archive member, or -1. */
  size_t archive;
};
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
  uint64_t align, size, address, file_offset, flags;
  uint32_t type, header_index;
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
    if (relocation->type == SHT_REL)
      return fail(linker, "'%s' uses REL relocations%s", path, "");
    if (relocation->type != SHT_RELA) continue;
    uint32_t target = read32(headers + (size_t)i * 64 + 44);
    if (target >= count) return fail(linker, "'%s' has a malformed relocation section%s", path, "");
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
      if (!symbol || symbol->defined || !symbol->strong_reference || symbol->archive_member < 0) continue;
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
static bool collect_garbage(Linker *linker, const char *entry) {
  LinkSection **stack = NULL;
  size_t count = 0, capacity = 0;
  LinkSymbol *start = symbol_find(linker, entry);
  if (!start || !start->defined) return fail(linker, "entry symbol '%s' is undefined%s", entry, "");
  bool ok = mark(linker, &stack, &count, &capacity, symbol_section(start));
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
  static const char *names[OUT_ALLOC_COUNT] = {".text", ".rodata", ".eh_frame", ".init_array",
                                               ".fini_array", ".data", ".got", ".bss"};
  static const uint32_t types[OUT_ALLOC_COUNT] = {SHT_PROGBITS, SHT_PROGBITS, SHT_PROGBITS, SHT_INIT_ARRAY,
                                                  SHT_FINI_ARRAY, SHT_PROGBITS, SHT_PROGBITS, SHT_NOBITS};
  for (int k = 0; k < OUT_ALLOC_COUNT; ++k) {
    linker->outputs[k].name = (char *)names[k];
    linker->outputs[k].type = types[k];
    linker->outputs[k].align = 1;
    linker->outputs[k].flags = SHF_ALLOC | (k == OUT_TEXT ? SHF_EXEC : 0) |
                               (k >= OUT_INIT_ARRAY ? SHF_WRITE : 0);
  }
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
  /* One GOT slot per symbol a GOT-relative relocation in live code names. */
  for (size_t o = 0; o < linker->object_count; ++o) {
    LinkObject *object = linker->objects[o];
    for (size_t i = 1; i < object->section_count; ++i) {
      LinkSection *section = &object->sections[i];
      if (!section->live) continue;
      for (size_t r = 0; r < section->rela_count; ++r) {
        LinkSymbol *symbol = object->symbols[section->relas[r].symbol];
        if (!needs_got(section->relas[r].type) || !symbol || symbol->got) continue;
        if (!grow((void **)&linker->got_symbols, &linker->got_capacity, linker->got_count, sizeof(*linker->got_symbols)))
          return fail(linker, "out of memory%s%s", "", "");
        linker->got_symbols[linker->got_count++] = symbol;
        symbol->got = (uint32_t)linker->got_count;
      }
    }
  }
  if (linker->got_count) {
    linker->got = (LinkSection){.name = ".got", .size = linker->got_count * 8, .align = 8, .type = SHT_PROGBITS,
                                .flags = SHF_ALLOC | SHF_WRITE, .live = true, .output = OUT_GOT};
    if (!add_to_output(linker, &linker->outputs[OUT_GOT], &linker->got)) return false;
  }
  return true;
}

/* Segments: headers and read-only data, then code, then writable data with
   zero-fill. Each starts on a page so it can carry its own permissions. */
typedef struct {
  uint64_t offset, address, file_size, memory_size;
  uint32_t flags;
} Segment;
static void place(LinkOutput *output, uint64_t *offset, bool allocated) {
  *offset = align_up(*offset, output->align);
  output->file_offset = *offset;
  output->address = allocated ? IMAGE_BASE + *offset : 0;
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
  static const int groups[3][4] = {{OUT_RODATA, OUT_EH_FRAME, -1, -1}, {OUT_TEXT, -1, -1, -1},
                                   {OUT_INIT_ARRAY, OUT_FINI_ARRAY, OUT_DATA, OUT_GOT}};
  static const uint32_t flags[3] = {4, 5, 6};
  uint64_t offset = header_size;
  size_t count = 0;
  for (int g = 0; g < 3; ++g) {
    bool any = g == 0;
    for (int k = 0; k < 4 && groups[g][k] >= 0; ++k) any |= linker->outputs[groups[g][k]].count != 0;
    if (g == 2) any |= linker->outputs[OUT_BSS].count != 0;
    if (!any) continue;
    if (g) offset = align_up(offset, PAGE);
    uint64_t start = g ? offset : 0;
    for (int k = 0; k < 4 && groups[g][k] >= 0; ++k) place(&linker->outputs[groups[g][k]], &offset, true);
    uint64_t file_end = offset, memory_end = offset;
    if (g == 2) {
      uint64_t bss = offset;
      place(&linker->outputs[OUT_BSS], &bss, true);
      memory_end = bss + linker->outputs[OUT_BSS].size;
    }
    segments[count++] = (Segment){start, IMAGE_BASE + start, file_end - start, memory_end - start, flags[g]};
  }
  for (size_t e = 0; e < linker->extra_count; ++e) place(&linker->extra[e], &offset, false);
  return count;
}

static uint64_t symbol_address(const LinkSymbol *symbol) {
  if (!symbol->defined) return 0;
  if (symbol->absolute || !symbol->section) return symbol->value;
  return symbol->section->address + symbol->value;
}
static void define_linker_symbols(Linker *linker, Segment *segments, size_t segment_count) {
  const LinkOutput *init = &linker->outputs[OUT_INIT_ARRAY], *fini = &linker->outputs[OUT_FINI_ARRAY];
  const LinkOutput *bss = &linker->outputs[OUT_BSS], *text = &linker->outputs[OUT_TEXT];
  const Segment *last = &segments[segment_count - 1];
  struct { const char *name; uint64_t value; } defined[] = {
    {"__ehdr_start", IMAGE_BASE}, {"__executable_start", IMAGE_BASE},
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
      if (!symbol->defined && symbol->binding != STB_WEAK && symbol->strong_reference && !debug)
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
    case R_X86_64_PC32: case R_X86_64_PLT32: result = value + addend - place; width = 32; break;
    case R_X86_64_PC64: result = value + addend - place; width = 64; break;
    case R_X86_64_SIZE32: result = (symbol ? symbol->size : 0) + addend; width = 32; is_signed = false; break;
    case R_X86_64_SIZE64: result = (symbol ? symbol->size : 0) + addend; width = 64; break;
    case R_X86_64_GOTPCREL: case R_X86_64_GOTPCRELX: case R_X86_64_REX_GOTPCRELX:
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

static bool write_output(Linker *linker, const char *entry_name) {
  Segment segments[3];
  const size_t phdr_count = 4; /* Up to three loads plus the stack note. */
  uint64_t header_size = 64 + 56 * phdr_count;
  size_t segment_count = layout(linker, segments, header_size);
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
    for (size_t i = 0; ok && i < output->count; ++i) {
      LinkSection *section = output->sections[i];
      uint8_t *at = image + output->file_offset + section->offset;
      if (section == &linker->got) {
        for (size_t g = 0; g < linker->got_count; ++g) write64(at + g * 8, symbol_address(linker->got_symbols[g]));
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
  LinkSymbol *entry = symbol_find(linker, entry_name);
  if (ok) {
    memcpy(image, "\x7f" "ELF\x02\x01\x01", 7);
    write16(image + 16, ELF_EXEC);
    write16(image + 18, MACHINE_X86_64);
    write32(image + 20, 1);
    write64(image + 24, symbol_address(entry));
    write64(image + 32, 64);
    write64(image + 40, section_headers);
    write16(image + 52, 64);
    write16(image + 54, 56);
    write16(image + 56, (uint16_t)phdr_count);
    write16(image + 58, 64);
    write16(image + 60, (uint16_t)header_count);
    write16(image + 62, (uint16_t)(header_count - 1));
    for (size_t s = 0; s < phdr_count; ++s) {
      uint8_t *p = image + 64 + s * 56;
      if (s < segment_count) {
        write32(p, PT_LOAD);
        write32(p + 4, segments[s].flags);
        write64(p + 8, segments[s].offset);
        write64(p + 16, segments[s].address);
        write64(p + 24, segments[s].address);
        write64(p + 32, segments[s].file_size);
        write64(p + 40, segments[s].memory_size);
        write64(p + 48, PAGE);
      } else if (s == segment_count) {
        write32(p, PT_GNU_STACK);
        write32(p + 4, 6);
        write64(p + 48, 16);
      }
    }
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
      write64(h + 56, k == OUT_GOT || k == OUT_INIT_ARRAY || k == OUT_FINI_ARRAY ? 8 : 0);
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
    free(object);
  }
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
  return n >= 20 && !memcmp(magic, "\x7f" "ELF", 4) && read16(magic + 16) == ELF_REL;
}

int dyn_link_elf(const char *const *inputs, size_t input_count, const char *output, const char *entry) {
  Linker linker = {.output_path = output};
  bool ok = true;
  for (size_t i = 0; ok && i < input_count; ++i) {
    size_t size = 0;
    uint8_t *data = read_file(&linker, inputs[i], &size);
    if (!data) { ok = false; break; }
    if (size >= 8 && !memcmp(data, "!<arch>\n", 8)) ok = load_archive(&linker, inputs[i], data, size);
    else ok = load_object(&linker, inputs[i], data, size);
  }
  ok = ok && resolve_archives(&linker) && allocate_commons(&linker) && collect_garbage(&linker, entry) &&
       assign_outputs(&linker) && write_output(&linker, entry);
  if (!ok) {
    fprintf(stderr, "error: link: %s\n", linker.error[0] ? linker.error : "out of memory");
    remove(output);
  }
  linker_free(&linker);
  return ok ? 0 : 2;
}
