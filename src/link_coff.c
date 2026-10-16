/* Built-in PE/COFF linker for x86-64 Windows, so building for Windows needs
   no external linker or Visual Studio libraries. Inputs are COFF objects and
   ar/.lib archives, whose members may be COFF objects or short import
   objects; the output is an executable at a fixed base, as GNU ld wrote it,
   or a relocatable DLL with an export table and a short-import library.
   Grouped sections ("name$suffix") merge in suffix order, which is how the
   runtime contributes its own import directory through .idata$2..$7; imports
   from libraries extend the same directory. Sections are kept whole: these
   objects keep each module in one .text, so garbage collection would gain
   little. Structures are read field by field so any host can link. */
#include "link_coff.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

enum {
  MACHINE_AMD64 = 0x8664, MACHINE_ARM64 = 0xaa64,
  SCN_CNT_CODE = 0x20, SCN_CNT_INITIALIZED = 0x40, SCN_CNT_UNINITIALIZED = 0x80, SCN_LNK_INFO = 0x200,
  SCN_LNK_REMOVE = 0x800, SCN_LNK_COMDAT = 0x1000, SCN_ALIGN_MASK = 0x00f00000, SCN_LNK_NRELOC_OVFL = 0x01000000,
  SCN_MEM_DISCARDABLE = 0x02000000, SCN_MEM_EXECUTE = 0x20000000, SCN_MEM_READ = 0x40000000,
  CLASS_EXTERNAL = 2, CLASS_STATIC = 3, CLASS_LABEL = 6, CLASS_FUNCTION = 101, CLASS_FILE = 103,
  CLASS_SECTION = 104, CLASS_WEAK_EXTERNAL = 105,
  COMDAT_ASSOCIATIVE = 5,
  REL_ABSOLUTE = 0, REL_ADDR64 = 1, REL_ADDR32 = 2, REL_ADDR32NB = 3, REL_REL32 = 4, REL_REL32_5 = 9,
  REL_SECTION = 10, REL_SECREL = 11,
  FILE_ALIGN = 0x200, SECTION_ALIGN = 0x1000,
};
#define SCN_MEM_WRITE 0x80000000u
#define EXE_BASE 0x140000000ull
#define DLL_BASE 0x180000000ull

typedef struct CObject CObject;
typedef struct CSymbol CSymbol;
typedef struct {
  uint32_t offset;
  uint16_t type;
  CSymbol *symbol;
} CReloc;
typedef struct CSection {
  CObject *object; /* NULL for synthetic sections. */
  char name[64]; /* Full input name, including any $suffix. */
  const uint8_t *data;
  uint8_t *owned;
  uint32_t size, align, flags;
  CReloc *relocs;
  size_t reloc_count;
  struct CSection *associate; /* Kept only with this COMDAT leader. */
  int output;
  uint32_t offset; /* Within the output section. */
  bool discarded;
} CSection;
struct CSymbol {
  const char *name;
  CSection *section;
  uint32_t value;
  uint32_t common_size;
  bool defined, absolute, common, referenced, external, code;
  CSymbol *weak_default; /* Weak external fallback. */
  int archive_member;
  size_t archive;
};
struct CObject {
  const char *path;
  CSection *sections;
  size_t section_count;
};
typedef struct {
  const char *path;
  const uint8_t *data;
  size_t size;
} CArchive;
typedef struct {
  char name[64]; /* Preserve full debug section names from CSection. */
  uint32_t characteristics;
  CSection **sections;
  size_t count, capacity;
  uint32_t rva, size, file_offset, file_size;
  uint16_t index; /* One-based section number. */
} COutput;
typedef struct {
  const char *dll;
  const char *symbol, *import_name;
  uint16_t hint;
  bool by_ordinal, code;
} CImport;
typedef struct {
  const char *output_path;
  bool shared;
  uint16_t machine;
  char error[512];
  CObject **objects;
  size_t object_count, object_capacity;
  CArchive *archives;
  size_t archive_count;
  uint8_t **buffers;
  size_t buffer_count, buffer_capacity;
  CSymbol **table;
  size_t table_capacity, table_count;
  CSymbol **locals; /* Owned symbols outside the global table. */
  size_t local_count, local_capacity;
  CSection **extra;
  size_t extra_count, extra_capacity;
  char **comdats;
  size_t comdat_count, comdat_capacity;
  CImport *imports;
  size_t import_count, import_capacity;
  COutput *outputs;
  size_t output_count, output_capacity;
  uint64_t base;
} CLinker;

static bool fail(CLinker *linker, const char *format, const char *a, const char *b) {
  if (!linker->error[0]) snprintf(linker->error, sizeof(linker->error), format, a, b);
  return false;
}
static uint16_t read16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static uint32_t read32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint64_t read64(const uint8_t *p) { return (uint64_t)read32(p) | (uint64_t)read32(p + 4) << 32; }
static void write16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void write32(uint8_t *p, uint32_t v) { for (int i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8 * i)); }
static void write64(uint8_t *p, uint64_t v) { write32(p, (uint32_t)v); write32(p + 4, (uint32_t)(v >> 32)); }
static void write32be(uint8_t *p, uint32_t v) { for (int i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (24 - 8 * i)); }
static uint32_t align_up(uint32_t value, uint32_t align) { return align > 1 ? (value + align - 1) & ~(align - 1) : value; }
static bool in_bounds(size_t size, uint64_t offset, uint64_t length) { return offset <= size && length <= size - offset; }
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
static CSymbol *symbol_find(CLinker *linker, const char *name) {
  if (!linker->table_capacity) return NULL;
  for (size_t i = hash_name(name) & (linker->table_capacity - 1);; i = (i + 1) & (linker->table_capacity - 1)) {
    if (!linker->table[i]) return NULL;
    if (!strcmp(linker->table[i]->name, name)) return linker->table[i];
  }
}
static CSymbol *symbol_intern(CLinker *linker, const char *name) {
  CSymbol *found = symbol_find(linker, name);
  if (found) return found;
  if ((linker->table_count + 1) * 2 > linker->table_capacity) {
    size_t capacity = linker->table_capacity ? linker->table_capacity * 2 : 1024;
    CSymbol **table = calloc(capacity, sizeof(*table));
    if (!table) return NULL;
    for (size_t i = 0; i < linker->table_capacity; ++i) {
      if (!linker->table[i]) continue;
      size_t at = hash_name(linker->table[i]->name) & (capacity - 1);
      while (table[at]) at = (at + 1) & (capacity - 1);
      table[at] = linker->table[i];
    }
    free(linker->table);
    linker->table = table;
    linker->table_capacity = capacity;
  }
  CSymbol *symbol = calloc(1, sizeof(*symbol));
  if (!symbol) return NULL;
  symbol->name = name;
  symbol->external = true;
  symbol->archive_member = -1;
  size_t at = hash_name(name) & (linker->table_capacity - 1);
  while (linker->table[at]) at = (at + 1) & (linker->table_capacity - 1);
  linker->table[at] = symbol;
  ++linker->table_count;
  return symbol;
}
static CSymbol *local_symbol(CLinker *linker, const char *name) {
  CSymbol *symbol = calloc(1, sizeof(*symbol));
  if (!symbol || !grow((void **)&linker->locals, &linker->local_capacity, linker->local_count, sizeof(*linker->locals))) {
    free(symbol);
    return NULL;
  }
  symbol->name = name;
  symbol->archive_member = -1;
  linker->locals[linker->local_count++] = symbol;
  return symbol;
}
static uint8_t *keep(CLinker *linker, uint8_t *data) {
  if (!data) return NULL;
  if (!grow((void **)&linker->buffers, &linker->buffer_capacity, linker->buffer_count, sizeof(*linker->buffers))) {
    free(data);
    return NULL;
  }
  linker->buffers[linker->buffer_count++] = data;
  return data;
}
static char *keep_string(CLinker *linker, const char *text, size_t length) {
  char *copy = malloc(length + 1);
  if (!copy) return NULL;
  memcpy(copy, text, length);
  copy[length] = 0;
  return (char *)keep(linker, (uint8_t *)copy);
}
static uint8_t *read_file(CLinker *linker, const char *path, size_t *size) {
  FILE *file = fopen(path, "rb");
  if (!file) { fail(linker, "cannot open '%s'%s", path, ""); return NULL; }
  struct stat info;
  uint8_t *data = NULL;
  if (!stat(path, &info) && info.st_size >= 0 && (data = malloc((size_t)info.st_size + 1)) &&
      fread(data, 1, (size_t)info.st_size, file) == (size_t)info.st_size) {
    *size = (size_t)info.st_size;
  } else {
    free(data);
    data = NULL;
    fail(linker, "cannot read '%s'%s", path, "");
  }
  fclose(file);
  return keep(linker, data);
}
static CSection *synthetic(CLinker *linker, const char *name, uint32_t size, uint32_t align, uint32_t flags) {
  CSection *section = calloc(1, sizeof(*section));
  if (!section || !grow((void **)&linker->extra, &linker->extra_capacity, linker->extra_count, sizeof(*linker->extra))) {
    free(section);
    return NULL;
  }
  linker->extra[linker->extra_count++] = section;
  snprintf(section->name, sizeof(section->name), "%s", name);
  section->size = size;
  section->align = align;
  section->flags = flags;
  section->output = -1;
  if (size && !(flags & SCN_CNT_UNINITIALIZED)) {
    section->owned = calloc(1, size);
    if (!section->owned) return NULL;
    section->data = section->owned;
  }
  return section;
}
static bool add_reloc(CSection *section, uint32_t offset, uint16_t type, CSymbol *symbol) {
  CReloc *relocs = realloc(section->relocs, (section->reloc_count + 1) * sizeof(*relocs));
  if (!relocs) return false;
  section->relocs = relocs;
  relocs[section->reloc_count++] = (CReloc){offset, type, symbol};
  return true;
}

/* COFF objects. */
static const char *coff_name(CLinker *linker, const uint8_t *field, const char *strings, uint32_t string_size,
                             bool section) {
  if (section && field[0] == '/') {
    uint32_t offset = (uint32_t)strtoul((const char *)field + 1, NULL, 10);
    return offset < string_size && memchr(strings + offset, 0, string_size - offset) ? strings + offset : "";
  }
  if (!section && !read32(field)) {
    uint32_t offset = read32(field + 4);
    return offset < string_size && memchr(strings + offset, 0, string_size - offset) ? strings + offset : "";
  }
  size_t length = 0;
  while (length < 8 && field[length]) ++length;
  return keep_string(linker, (const char *)field, length);
}
static bool comdat_seen(CLinker *linker, const char *key) {
  for (size_t i = 0; i < linker->comdat_count; ++i)
    if (!strcmp(linker->comdats[i], key)) return true;
  if (grow((void **)&linker->comdats, &linker->comdat_capacity, linker->comdat_count, sizeof(char *)))
    linker->comdats[linker->comdat_count++] = (char *)key;
  return false;
}
static bool load_object(CLinker *linker, const char *path, const uint8_t *data, size_t size) {
  if (size < 20 || (read16(data) != MACHINE_AMD64 && read16(data) != MACHINE_ARM64) ||
      (linker->machine && read16(data) != linker->machine))
    return fail(linker, "'%s' has an incompatible COFF architecture%s", path, "");
  linker->machine = read16(data);
  uint16_t section_count = read16(data + 2);
  uint32_t symbol_offset = read32(data + 8), symbol_count = read32(data + 12);
  uint16_t optional = read16(data + 16);
  size_t headers = 20 + optional;
  if (!in_bounds(size, headers, (uint64_t)section_count * 40) || !in_bounds(size, symbol_offset, (uint64_t)symbol_count * 18))
    return fail(linker, "'%s' is a malformed COFF object%s", path, "");
  uint64_t string_at = (uint64_t)symbol_offset + (uint64_t)symbol_count * 18;
  const char *strings = "";
  uint32_t string_size = 0;
  if (in_bounds(size, string_at, 4)) {
    string_size = read32(data + string_at);
    if (!in_bounds(size, string_at, string_size)) return fail(linker, "'%s' has a malformed string table%s", path, "");
    strings = (const char *)data + string_at;
  }
  CObject *object = calloc(1, sizeof(*object));
  if (!object || !grow((void **)&linker->objects, &linker->object_capacity, linker->object_count, sizeof(*linker->objects))) {
    free(object);
    return fail(linker, "out of memory%s%s", "", "");
  }
  linker->objects[linker->object_count++] = object;
  object->path = path;
  object->section_count = section_count;
  object->sections = calloc(section_count + 1u, sizeof(CSection));
  CSymbol **symbols = calloc(symbol_count + 1u, sizeof(CSymbol *));
  if (!object->sections || !symbols) { free(symbols); return fail(linker, "out of memory%s%s", "", ""); }
  for (uint16_t s = 0; s < section_count; ++s) {
    const uint8_t *h = data + headers + (size_t)s * 40;
    CSection *section = &object->sections[s];
    section->object = object;
    snprintf(section->name, sizeof(section->name), "%s", coff_name(linker, h, strings, string_size, true));
    section->size = read32(h + 16);
    section->flags = read32(h + 36);
    uint32_t align = (section->flags & SCN_ALIGN_MASK) >> 20;
    section->align = align ? 1u << (align - 1) : 16;
    section->output = -1;
    if (!(section->flags & SCN_CNT_UNINITIALIZED) && section->size) {
      if (!in_bounds(size, read32(h + 20), section->size)) { free(symbols); return fail(linker, "'%s' has a section outside the file%s", path, ""); }
      section->data = data + read32(h + 20);
    }
    if ((section->flags & (SCN_LNK_REMOVE | SCN_LNK_INFO)) || !strncmp(section->name, ".debug$", 7) ||
        !strcmp(section->name, ".llvm_addrsig"))
      section->discarded = true;
  }
  /* Symbols, with COMDAT selection from section-definition aux records. */
  uint8_t *selection = calloc(section_count + 1u, 1);
  uint16_t *associated = calloc(section_count + 1u, sizeof(uint16_t));
  bool *keyed = calloc(section_count + 1u, sizeof(bool));
  if (!selection || !associated || !keyed) { free(symbols); free(selection); free(associated); free(keyed); return fail(linker, "out of memory%s%s", "", ""); }
  bool ok = true;
  for (uint32_t i = 0; ok && i < symbol_count; ++i) {
    const uint8_t *entry = data + symbol_offset + (size_t)i * 18;
    const char *name = coff_name(linker, entry, strings, string_size, false);
    uint32_t value = read32(entry + 8);
    int16_t number = (int16_t)read16(entry + 12);
    uint16_t type = read16(entry + 14);
    uint8_t storage = entry[16], aux = entry[17];
    if (!name) { ok = fail(linker, "out of memory%s%s", "", ""); break; }
    CSection *section = number > 0 && number <= section_count ? &object->sections[number - 1] : NULL;
    if (storage == CLASS_STATIC && section && aux && value == 0 && (section->flags & SCN_LNK_COMDAT) &&
        i + 1 < symbol_count) {
      const uint8_t *definition = entry + 18;
      selection[number] = definition[14];
      associated[number] = read16(definition + 12);
    }
    if (storage == CLASS_EXTERNAL || storage == CLASS_WEAK_EXTERNAL) {
      CSymbol *symbol = symbol_intern(linker, name);
      if (!symbol) { ok = fail(linker, "out of memory%s%s", "", ""); break; }
      symbols[i] = symbol;
      /* The first external in a COMDAT section names its group. */
      if (section && (section->flags & SCN_LNK_COMDAT) && !keyed[number] && selection[number] != COMDAT_ASSOCIATIVE) {
        keyed[number] = true;
        if (comdat_seen(linker, name)) section->discarded = true;
      }
      if (storage == CLASS_WEAK_EXTERNAL) {
        symbol->referenced = true;
        if (aux && i + 1 < symbol_count) {
          uint32_t tag = read32(entry + 18);
          if (tag < symbol_count) symbol->weak_default = (CSymbol *)(uintptr_t)(tag + 1); /* Patched below. */
        }
      } else if (number == 0 && value) {
        if (!symbol->defined || symbol->common) {
          symbol->defined = symbol->common = true;
          if (value > symbol->common_size) symbol->common_size = value;
        }
      } else if (number == 0) {
        symbol->referenced = true;
      } else if (number == -1 || section) {
        if (section && section->discarded) {
          symbol->referenced = true;
        } else if (symbol->defined && !symbol->common) {
          if (!(section && (section->flags & SCN_LNK_COMDAT)))
            ok = fail(linker, "duplicate symbol '%s' (also in %s)", name, path);
        } else {
          symbol->defined = true;
          symbol->common = false;
          symbol->absolute = number == -1;
          symbol->section = section;
          symbol->value = value;
          symbol->code = (type >> 4) == 2 || (section && (section->flags & SCN_CNT_CODE));
          symbol->archive_member = -1;
        }
      }
    } else if (storage == CLASS_STATIC || storage == CLASS_LABEL || storage == CLASS_FUNCTION || storage == CLASS_SECTION) {
      CSymbol *symbol = local_symbol(linker, name);
      if (!symbol) { ok = fail(linker, "out of memory%s%s", "", ""); break; }
      symbol->external = false;
      symbol->defined = number > 0 || number == -1;
      symbol->absolute = number == -1;
      symbol->section = section;
      symbol->value = value;
      symbols[i] = symbol;
    }
    i += aux;
  }
  /* Weak externals point at their default by index; resolve now. */
  for (uint32_t i = 0; ok && i < symbol_count; ++i) {
    CSymbol *symbol = symbols[i];
    if (!symbol || !symbol->weak_default || (uintptr_t)symbol->weak_default > symbol_count) continue;
    uint32_t tag = (uint32_t)(uintptr_t)symbol->weak_default - 1;
    symbol->weak_default = symbols[tag];
  }
  for (uint16_t s = 1; ok && s <= section_count; ++s)
    if (selection[s] == COMDAT_ASSOCIATIVE && associated[s] && associated[s] <= section_count)
      object->sections[s - 1].associate = &object->sections[associated[s] - 1];
  for (uint16_t s = 0; ok && s < section_count; ++s) {
    CSection *section = &object->sections[s];
    for (CSection *leader = section->associate; leader; leader = leader->associate)
      if (leader->discarded) section->discarded = true;
    const uint8_t *h = data + headers + (size_t)s * 40;
    uint32_t relocation_offset = read32(h + 24), count = read16(h + 32);
    if ((section->flags & SCN_LNK_NRELOC_OVFL) && count == 0xffff && in_bounds(size, relocation_offset, 10)) {
      count = read32(data + relocation_offset) - 1;
      relocation_offset += 10;
    }
    if (!in_bounds(size, relocation_offset, (uint64_t)count * 10)) { ok = fail(linker, "'%s' has malformed relocations%s", path, ""); break; }
    section->relocs = calloc(count + 1u, sizeof(CReloc));
    if (!section->relocs) { ok = fail(linker, "out of memory%s%s", "", ""); break; }
    for (uint32_t r = 0; r < count; ++r) {
      const uint8_t *entry = data + relocation_offset + (size_t)r * 10;
      uint32_t index = read32(entry + 4);
      CSymbol *symbol = index < symbol_count ? symbols[index] : NULL;
      if (!symbol) { ok = fail(linker, "'%s' has a relocation to a missing symbol%s", path, ""); break; }
      uint16_t type=read16(entry+8);
      if (linker->machine == MACHINE_ARM64) {
        switch(type) {
        case 0: break;
        case 1: type=REL_ADDR32; break;
        case 2: type=REL_ADDR32NB; break;
        case 8: type=REL_SECREL; break;
        case 13: type=REL_SECTION; break;
        case 14: type=REL_ADDR64; break;
        default: type+=256; break;
        }
      }
      section->relocs[section->reloc_count++] = (CReloc){read32(entry), type, symbol};
    }
  }
  free(symbols);
  free(selection);
  free(associated);
  free(keyed);
  return ok;
}

/* Short import objects describe one DLL export: the code symbol gets a
   jmp thunk, and __imp_ names its IAT slot. */
static bool load_import(CLinker *linker, const char *path, const uint8_t *data, size_t size) {
  if (size < 20 || (read16(data+6)!=MACHINE_AMD64 && read16(data+6)!=MACHINE_ARM64) ||
      (linker->machine && read16(data+6)!=linker->machine))
    return fail(linker,"'%s' has an incompatible import architecture%s",path,"");
  linker->machine=read16(data+6);
  uint32_t length = read32(data + 12);
  if (!in_bounds(size, 20, length)) return fail(linker, "'%s' has a malformed import%s", path, "");
  const char *symbol = (const char *)data + 20, *end = symbol + length;
  const char *symbol_end = memchr(symbol, 0, (size_t)(end - symbol));
  if (!symbol_end) return fail(linker, "'%s' has a malformed import%s", path, "");
  const char *dll = symbol_end + 1, *dll_end = dll < end ? memchr(dll, 0, (size_t)(end - dll)) : NULL;
  if (!dll_end) return fail(linker, "'%s' has a malformed import%s", path, "");
  uint16_t info = read16(data + 18);
  unsigned type = info & 3, name_type = (info >> 2) & 7;
  const char *import_name = symbol;
  if (name_type >= 2) {
    /* Strip a leading ?, @ or _ and anything from the first @. */
    const char *start = symbol;
    if (*start == '?' || *start == '@' || *start == '_') ++start;
    const char *at = strchr(start, '@');
    import_name = keep_string(linker, start, at && name_type == 3 ? (size_t)(at - start) : strlen(start));
    if (!import_name) return fail(linker, "out of memory%s%s", "", "");
  }
  if (!grow((void **)&linker->imports, &linker->import_capacity, linker->import_count, sizeof(*linker->imports)))
    return fail(linker, "out of memory%s%s", "", "");
  linker->imports[linker->import_count++] = (CImport){dll, symbol, import_name, read16(data + 16), name_type == 0, type == 0};
  return true;
}

/* ar archives (GNU .a and MSVC .lib share the first linker member). */
static size_t member(const uint8_t *data, size_t size, size_t at, const uint8_t **body, size_t *length) {
  if (at + 60 > size) return 0;
  size_t member_size = (size_t)strtoull((const char *)data + at + 48, NULL, 10);
  if (member_size > size - at - 60) return 0;
  *body = data + at + 60;
  *length = member_size;
  return at + 60 + member_size + (member_size & 1);
}
static bool load_archive(CLinker *linker, const char *path, const uint8_t *data, size_t size) {
  CArchive *archives = realloc(linker->archives, (linker->archive_count + 1) * sizeof(*archives));
  if (!archives) return fail(linker, "out of memory%s%s", "", "");
  linker->archives = archives;
  size_t index = linker->archive_count++;
  archives[index] = (CArchive){path, data, size};
  const uint8_t *body;
  size_t length;
  if (!member(data, size, 8, &body, &length) || memcmp(data + 8, "/               ", 16) || length < 4)
    return fail(linker, "'%s' has no symbol index (run ranlib)%s", path, "");
  uint32_t n = (uint32_t)body[0] << 24 | (uint32_t)body[1] << 16 | (uint32_t)body[2] << 8 | body[3];
  if ((uint64_t)n * 4 + 4 > length) return fail(linker, "'%s' has a malformed symbol index%s", path, "");
  const char *names = (const char *)body + 4 + (size_t)n * 4, *end = (const char *)body + length;
  for (uint32_t k = 0; k < n && names < end; ++k) {
    const uint8_t *p = body + 4 + (size_t)k * 4;
    uint32_t offset = (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
    const char *name_end = memchr(names, 0, (size_t)(end - names));
    if (!name_end) break;
    CSymbol *symbol = symbol_intern(linker, names);
    if (!symbol) return fail(linker, "out of memory%s%s", "", "");
    if (!symbol->defined && symbol->archive_member < 0) { symbol->archive_member = (int)offset; symbol->archive = index; }
    names = name_end + 1;
  }
  return true;
}
static bool load_member(CLinker *linker, CArchive *archive, size_t at) {
  const uint8_t *body;
  size_t length;
  if (!member(archive->data, archive->size, at, &body, &length))
    return fail(linker, "'%s' has a malformed member offset%s", archive->path, "");
  if (length >= 4 && read16(body) == 0 && read16(body + 2) == 0xffff) return load_import(linker, archive->path, body, length);
  return load_object(linker, archive->path, body, length);
}
static bool imported(CLinker *linker, const char *name) {
  for (size_t i = 0; i < linker->import_count; ++i) {
    const CImport *import = &linker->imports[i];
    if (!strcmp(import->symbol, name)) return import->code;
    if (!strncmp(name, "__imp_", 6) && !strcmp(import->symbol, name + 6)) return true;
  }
  return false;
}
static bool resolve_archives(CLinker *linker) {
  for (bool changed = true; changed;) {
    changed = false;
    for (size_t i = 0; i < linker->table_capacity; ++i) {
      CSymbol *symbol = linker->table[i];
      if (!symbol || symbol->defined || !symbol->referenced || symbol->archive_member < 0) continue;
      if (symbol->weak_default && symbol->weak_default->defined) continue;
      size_t at = (size_t)symbol->archive_member;
      CArchive *archive = &linker->archives[symbol->archive];
      symbol->archive_member = -1;
      if (imported(linker, symbol->name)) continue;
      /* Every other symbol the member defines is now loaded too. */
      for (size_t k = 0; k < linker->table_capacity; ++k) {
        CSymbol *other = linker->table[k];
        if (other && other->archive_member == (int)at && other->archive == symbol->archive) other->archive_member = -1;
      }
      if (!load_member(linker, archive, at)) return false;
      changed = true;
    }
  }
  return true;
}

/* The import directory for library imports: per DLL a descriptor ($2), a
   lookup table ($4) and IAT ($5) ending in zero, hint/names ($6) and the
   DLL name ($7); code imports also get a jmp thunk in .text. */
static bool build_imports(CLinker *linker) {
  for (size_t first = 0; first < linker->import_count; ++first) {
    const char *dll = linker->imports[first].dll;
    bool seen = false;
    for (size_t k = 0; k < first && !seen; ++k) seen = !strcmp(linker->imports[k].dll, dll);
    if (seen) continue;
    size_t count = 0;
    for (size_t k = first; k < linker->import_count; ++k) count += !strcmp(linker->imports[k].dll, dll);
    CSection *descriptor = synthetic(linker, ".idata$2", 20, 4, SCN_CNT_INITIALIZED | SCN_MEM_READ | SCN_MEM_WRITE);
    CSection *lookup = synthetic(linker, ".idata$4", (uint32_t)(count + 1) * 8, 8, SCN_CNT_INITIALIZED | SCN_MEM_READ | SCN_MEM_WRITE);
    CSection *iat = synthetic(linker, ".idata$5", (uint32_t)(count + 1) * 8, 8, SCN_CNT_INITIALIZED | SCN_MEM_READ | SCN_MEM_WRITE);
    CSection *name = synthetic(linker, ".idata$7", (uint32_t)strlen(dll) + 1, 2, SCN_CNT_INITIALIZED | SCN_MEM_READ | SCN_MEM_WRITE);
    CSymbol *lookup_symbol = local_symbol(linker, ""), *iat_symbol = local_symbol(linker, ""), *name_symbol = local_symbol(linker, "");
    if (!descriptor || !lookup || !iat || !name || !lookup_symbol || !iat_symbol || !name_symbol)
      return fail(linker, "out of memory%s%s", "", "");
    lookup_symbol->section = lookup;
    iat_symbol->section = iat;
    name_symbol->section = name;
    lookup_symbol->defined = iat_symbol->defined = name_symbol->defined = true;
    memcpy(name->owned, dll, strlen(dll) + 1);
    if (!add_reloc(descriptor, 0, REL_ADDR32NB, lookup_symbol) || !add_reloc(descriptor, 12, REL_ADDR32NB, name_symbol) ||
        !add_reloc(descriptor, 16, REL_ADDR32NB, iat_symbol))
      return fail(linker, "out of memory%s%s", "", "");
    uint32_t slot = 0;
    for (size_t k = first; k < linker->import_count; ++k) {
      CImport *import = &linker->imports[k];
      if (strcmp(import->dll, dll)) continue;
      if (import->by_ordinal) {
        write64(lookup->owned + slot * 8, 0x8000000000000000ull | import->hint);
        write64(iat->owned + slot * 8, 0x8000000000000000ull | import->hint);
      } else {
        size_t length = strlen(import->import_name);
        CSection *hint = synthetic(linker, ".idata$6", (uint32_t)align_up((uint32_t)(length + 3), 2), 2,
                                   SCN_CNT_INITIALIZED | SCN_MEM_READ | SCN_MEM_WRITE);
        CSymbol *hint_symbol = local_symbol(linker, "");
        if (!hint || !hint_symbol) return fail(linker, "out of memory%s%s", "", "");
        write16(hint->owned, import->hint);
        memcpy(hint->owned + 2, import->import_name, length);
        hint_symbol->section = hint;
        hint_symbol->defined = true;
        if (!add_reloc(lookup, slot * 8, REL_ADDR32NB, hint_symbol) || !add_reloc(iat, slot * 8, REL_ADDR32NB, hint_symbol))
          return fail(linker, "out of memory%s%s", "", "");
      }
      char slot_name[1024];
      snprintf(slot_name, sizeof(slot_name), "__imp_%s", import->symbol);
      char *kept = keep_string(linker, slot_name, strlen(slot_name));
      CSymbol *imp = kept ? symbol_intern(linker, kept) : NULL;
      if (!imp) return fail(linker, "out of memory%s%s", "", "");
      if (!imp->defined) {
        imp->defined = true;
        imp->section = iat;
        imp->value = slot * 8;
      }
      if (import->code) {
        CSymbol *code = symbol_intern(linker, import->symbol);
        if (!code) return fail(linker, "out of memory%s%s", "", "");
        if (!code->defined) {
          CSection *thunk = synthetic(linker, ".text$thunk", linker->machine==MACHINE_ARM64?12:8, 8, SCN_CNT_CODE | SCN_MEM_EXECUTE | SCN_MEM_READ);
          if (!thunk) return fail(linker, "out of memory%s%s", "", "");
          if (linker->machine==MACHINE_ARM64) {
            write32(thunk->owned,0x90000010); write32(thunk->owned+4,0xf9400210); write32(thunk->owned+8,0xd61f0200);
            if (!add_reloc(thunk,0,260,imp) || !add_reloc(thunk,4,263,imp)) return false;
          } else {
          thunk->owned[0] = 0xff;
          thunk->owned[1] = 0x25;
          memset(thunk->owned + 6, 0xcc, 2);
          if (!add_reloc(thunk, 2, REL_REL32, imp)) return fail(linker, "out of memory%s%s", "", "");
          }
          code->defined = code->code = true;
          code->section = thunk;
          code->value = 0;
        }
      }
      ++slot;
    }
  }
  return true;
}

/* Output sections: grouped names merge by the part before '$', ordered by
   suffix; code, data, read-only data, unwind tables, bss, imports, exports,
   relocations, then debug sections. */
static int rank(const char *name) {
  static const char *order[] = {".text", ".data", ".rdata", ".pdata", ".xdata", ".bss", ".edata", ".idata", ".reloc"};
  for (int i = 0; i < 9; ++i)
    if (!strcmp(name, order[i])) return i;
  return 9;
}
static int output_for(CLinker *linker, const char *base) {
  for (size_t i = 0; i < linker->output_count; ++i)
    if (!strcmp(linker->outputs[i].name, base)) return (int)i;
  if (!grow((void **)&linker->outputs, &linker->output_capacity, linker->output_count, sizeof(*linker->outputs))) return -1;
  COutput *output = &linker->outputs[linker->output_count];
  memset(output, 0, sizeof(*output));
  snprintf(output->name, sizeof(output->name), "%s", base);
  return (int)linker->output_count++;
}
static int compare_contributions(const void *a, const void *b) {
  const CSection *x = *(const CSection *const *)a, *y = *(const CSection *const *)b;
  const char *sx = strchr(x->name, '$'), *sy = strchr(y->name, '$');
  int c = strcmp(sx ? sx : "", sy ? sy : "");
  if (c) return c;
  /* Stable: input order breaks ties. */
  return x->offset < y->offset ? -1 : x->offset > y->offset;
}
static bool add_contribution(CLinker *linker, CSection *section) {
  char base[64];
  snprintf(base, sizeof(base), "%s", section->name);
  char *dollar = strchr(base, '$');
  if (dollar) *dollar = 0;
  if (strlen(base) > 8 && strncmp(base, ".debug_", 7)) base[8] = 0;
  int index = output_for(linker, base);
  if (index < 0) return fail(linker, "out of memory%s%s", "", "");
  COutput *output = &linker->outputs[index];
  if (!grow((void **)&output->sections, &output->capacity, output->count, sizeof(*output->sections)))
    return fail(linker, "out of memory%s%s", "", "");
  section->offset = (uint32_t)output->count; /* Input order, for the stable sort. */
  output->sections[output->count++] = section;
  output->characteristics |= section->flags & ~(SCN_ALIGN_MASK | SCN_LNK_COMDAT | SCN_LNK_NRELOC_OVFL);
  return true;
}
static bool assign_outputs(CLinker *linker) {
  for (size_t o = 0; o < linker->object_count; ++o) {
    CObject *object = linker->objects[o];
    for (size_t s = 0; s < object->section_count; ++s) {
      CSection *section = &object->sections[s];
      if (!section->discarded && !add_contribution(linker, section)) return false;
    }
  }
  for (size_t i = 0; i < linker->table_capacity; ++i) {
    CSymbol *symbol = linker->table[i];
    if (!symbol || !symbol->common) continue;
    CSection *section = synthetic(linker, ".bss$common", symbol->common_size,
                                  symbol->common_size >= 32 ? 32 : 8, SCN_CNT_UNINITIALIZED | SCN_MEM_READ | SCN_MEM_WRITE);
    if (!section) return fail(linker, "out of memory%s%s", "", "");
    symbol->common = false;
    symbol->section = section;
    symbol->value = 0;
  }
  for (size_t i = 0; i < linker->extra_count; ++i)
    if (!add_contribution(linker, linker->extra[i])) return false;
  /* The import directory ends with a zero descriptor after every $2 part. */
  CSection *terminator = synthetic(linker, ".idata$3", 20, 4, SCN_CNT_INITIALIZED | SCN_MEM_READ | SCN_MEM_WRITE);
  if (!terminator || !add_contribution(linker, terminator)) return fail(linker, "out of memory%s%s", "", "");
  for (size_t i = 0; i < linker->output_count; ++i) {
    COutput *output = &linker->outputs[i];
    qsort(output->sections, output->count, sizeof(*output->sections), compare_contributions);
  }
  /* Order outputs by rank, keeping first-seen order among equals. */
  for (size_t i = 1; i < linker->output_count; ++i)
    for (size_t j = i; j > 0 && rank(linker->outputs[j - 1].name) > rank(linker->outputs[j].name); --j) {
      COutput swap = linker->outputs[j - 1];
      linker->outputs[j - 1] = linker->outputs[j];
      linker->outputs[j] = swap;
    }
  for (size_t i = 0; i < linker->output_count; ++i)
    for (size_t s = 0; s < linker->outputs[i].count; ++s) linker->outputs[i].sections[s]->output = (int)i;
  return true;
}

static uint32_t symbol_rva(CLinker *linker, const CSymbol *symbol) {
  while (symbol && !symbol->defined && symbol->weak_default) symbol = symbol->weak_default;
  if (!symbol || !symbol->defined) return 0;
  if (symbol->absolute || !symbol->section) return (uint32_t)(symbol->value - (symbol->absolute ? 0 : 0));
  return linker->outputs[symbol->section->output].rva + symbol->section->offset + symbol->value;
}
static bool symbol_absolute(const CSymbol *symbol) {
  while (symbol && !symbol->defined && symbol->weak_default) symbol = symbol->weak_default;
  return symbol && symbol->defined && (symbol->absolute || !symbol->section);
}
typedef struct {
  uint32_t *rvas;
  size_t count, capacity;
} RelocationList;
static bool relocate(CLinker *linker, CSection *section, uint8_t *out, RelocationList *base_relocations) {
  COutput *output = &linker->outputs[section->output];
  uint32_t section_rva = output->rva + section->offset;
  bool debug = !strncmp(output->name, ".debug_", 7);
  for (size_t r = 0; r < section->reloc_count; ++r) {
    CReloc *reloc = &section->relocs[r];
    CSymbol *symbol = reloc->symbol;
    CSymbol *target = symbol;
    while (target && !target->defined && target->weak_default) target = target->weak_default;
    if (!target->defined && target->external && !debug)
      return fail(linker, "undefined symbol '%s' (referenced from %s)", symbol->name,
                  section->object ? section->object->path : "import table");
    uint32_t width = reloc->type == REL_ADDR64 ? 8 : reloc->type == REL_SECTION ? 2 : 4;
    if (reloc->type == REL_ABSOLUTE) continue;
    if (reloc->offset + width > section->size)
      return fail(linker, "relocation outside its section in '%s'%s", section->object ? section->object->path : "", "");
    uint8_t *at = out + reloc->offset;
    bool absolute = symbol_absolute(target);
    uint64_t address = absolute ? (uint64_t)target->value : linker->base + symbol_rva(linker, target);
    if (reloc->type>=256) {
      uint32_t insn=read32(at), type=reloc->type-256;
      int64_t place=(int64_t)(linker->base+section_rva+reloc->offset);
      if (type==3) {
        int64_t delta=(int64_t)address-place+((int64_t)((int32_t)(insn<<6)>>6)*4);
        if ((delta&3) || delta<-(1ll<<27) || delta>=(1ll<<27)) return fail(linker,"ARM64 branch to '%s' out of range%s",symbol->name,"");
        write32(at,(insn&0xfc000000)|((uint32_t)(delta>>2)&0x3ffffff));
      } else if(type==4) {
        int32_t immediate=(int32_t)((((insn>>5)&0x7ffff)<<2)|((insn>>29)&3));
        if (immediate & (1<<20)) immediate -= 1<<21;
        /* COFF stores a byte addend in ADRP's immediate, unlike the final
           instruction's page displacement (LLD applyArm64Addr). Include it
           before rounding the symbol address down to a page. */
        uint64_t destination=address+(uint64_t)(int64_t)immediate;
        int64_t pages=((int64_t)(destination&~4095ull)-(place&~4095ll))/4096;
        if(pages<-(1<<20)||pages>=(1<<20)) return fail(linker,"ARM64 page of '%s' out of range%s",symbol->name,"");
        write32(at,(insn&~0x60ffffe0u)|((uint32_t)pages&3)<<29|(((uint32_t)pages>>2)&0x7ffff)<<5);
      } else if(type==6 || type==7) {
        unsigned scale=type==7?insn>>30:0;
        uint32_t value=(uint32_t)(address&4095)+(((insn>>10)&4095)<<scale);
        if(value&((1u<<scale)-1)) return fail(linker,"unaligned ARM64 reference to '%s'%s",symbol->name,"");
        write32(at,(insn&~0x003ffc00u)|((value>>scale)&4095)<<10);
      } else return fail(linker,"unsupported ARM64 relocation for '%s'%s",symbol->name,"");
      continue;
    }
    switch (reloc->type) {
    case REL_ADDR64:
      write64(at, address + read64(at));
      if ((linker->shared || linker->machine == MACHINE_ARM64) && !absolute && !debug && base_relocations) {
        if (!grow((void **)&base_relocations->rvas, &base_relocations->capacity, base_relocations->count, sizeof(uint32_t)))
          return fail(linker, "out of memory%s%s", "", "");
        base_relocations->rvas[base_relocations->count++] = section_rva + reloc->offset;
      }
      break;
    case REL_ADDR32: {
      uint64_t value = address + read32(at);
      if (value > UINT32_MAX && !debug) return fail(linker, "32-bit absolute address of '%s' in '%s' does not fit", symbol->name, section->object ? section->object->path : "");
      write32(at, (uint32_t)value);
      break;
    }
    case REL_ADDR32NB: write32(at, (uint32_t)(absolute ? target->value : symbol_rva(linker, target)) + read32(at)); break;
    case REL_SECTION: write16(at, target->section ? linker->outputs[target->section->output].index : 0); break;
    case REL_SECREL:
      write32(at, (target->section ? symbol_rva(linker, target) - linker->outputs[target->section->output].rva : 0) + read32(at));
      break;
    default:
      if (reloc->type >= REL_REL32 && reloc->type <= REL_REL32_5) {
        int64_t delta = (int64_t)address + (int32_t)read32(at) -
                        (int64_t)(linker->base + section_rva + reloc->offset + 4 + (reloc->type - REL_REL32));
        if ((delta < INT32_MIN || delta > INT32_MAX) && !debug)
          return fail(linker, "relocation to '%s' out of range in '%s'", symbol->name, section->object ? section->object->path : "");
        write32(at, (uint32_t)delta);
        break;
      }
      char type[16];
      snprintf(type, sizeof(type), "%u", reloc->type);
      return fail(linker, "unsupported relocation type %s in '%s'", type, section->object ? section->object->path : "");
    }
  }
  return true;
}

/* DLL exports: every defined external except linker internals. */
static bool exported_symbol(const CSymbol *symbol) {
  if (!symbol->defined || !symbol->external || symbol->absolute) return false;
  if (!strncmp(symbol->name, "__imp_", 6) || !strncmp(symbol->name, "DllMain", 7) || !strcmp(symbol->name, "DllEntryPoint") ||
      !strcmp(symbol->name, "__ImageBase") || !strncmp(symbol->name, ".refptr.", 8))
    return false;
  return symbol->section && strncmp(symbol->section->name, ".idata", 6);
}
static int compare_symbols(const void *a, const void *b) {
  return strcmp((*(const CSymbol *const *)a)->name, (*(const CSymbol *const *)b)->name);
}

/* A small COFF object for the import library's helper members. */
typedef struct {
  const char *name;
  const uint8_t *data;
  uint32_t size;
  struct { uint32_t offset, symbol; } relocs[3];
  uint32_t reloc_count;
} TinySection;
typedef struct {
  const char *name;
  int16_t section;
  uint8_t storage;
} TinySymbol;
static size_t tiny_object(uint16_t machine, uint8_t *out, const TinySection *sections, size_t section_count, const TinySymbol *symbols,
                          size_t symbol_count) {
  size_t size = 20 + 40 * section_count;
  size_t data_at[4], relocs_at[4];
  for (size_t i = 0; i < section_count; ++i) {
    data_at[i] = size;
    size += sections[i].size;
    relocs_at[i] = size;
    size += 10 * sections[i].reloc_count;
  }
  size_t symbol_at = size;
  size += 18 * symbol_count;
  size_t strings_at = size;
  size_t strings = 4;
  for (size_t i = 0; i < symbol_count; ++i)
    if (strlen(symbols[i].name) > 8) strings += strlen(symbols[i].name) + 1;
  size += strings;
  if (!out) return size;
  memset(out, 0, size);
  write16(out, machine);
  write16(out + 2, (uint16_t)section_count);
  write32(out + 8, (uint32_t)symbol_at);
  write32(out + 12, (uint32_t)symbol_count);
  for (size_t i = 0; i < section_count; ++i) {
    uint8_t *h = out + 20 + 40 * i;
    memcpy(h, sections[i].name, strlen(sections[i].name));
    write32(h + 16, sections[i].size);
    write32(h + 20, sections[i].size ? (uint32_t)data_at[i] : 0);
    write32(h + 24, sections[i].reloc_count ? (uint32_t)relocs_at[i] : 0);
    write16(h + 32, (uint16_t)sections[i].reloc_count);
    /* Alignment as llvm-dlltool sets it: 4 for descriptors, 2 for names, 8 for tables. */
    const char *suffix = strchr(sections[i].name, '$');
    uint32_t align = suffix && (suffix[1] == '2' || suffix[1] == '3') ? 0x00300000u : suffix && suffix[1] == '6' ? 0x00200000u : 0x00400000u;
    write32(h + 36, SCN_CNT_INITIALIZED | SCN_MEM_READ | SCN_MEM_WRITE | align);
    if (sections[i].size) memcpy(out + data_at[i], sections[i].data, sections[i].size);
    for (uint32_t r = 0; r < sections[i].reloc_count; ++r) {
      uint8_t *entry = out + relocs_at[i] + 10 * r;
      write32(entry, sections[i].relocs[r].offset);
      write32(entry + 4, sections[i].relocs[r].symbol);
      write16(entry + 8, machine==MACHINE_ARM64?2:REL_ADDR32NB);
    }
  }
  uint32_t string_offset = 4;
  for (size_t i = 0; i < symbol_count; ++i) {
    uint8_t *entry = out + symbol_at + 18 * i;
    size_t length = strlen(symbols[i].name);
    if (length > 8) {
      write32(entry + 4, string_offset);
      memcpy(out + strings_at + string_offset, symbols[i].name, length + 1);
      string_offset += (uint32_t)length + 1;
    } else {
      memcpy(entry, symbols[i].name, length);
    }
    write16(entry + 12, (uint16_t)symbols[i].section);
    entry[16] = symbols[i].storage;
  }
  write32(out + strings_at, (uint32_t)strings);
  return size;
}

/* Import library for a DLL, laid out as llvm-dlltool writes it: GNU ar with
   a "/" index; the import descriptor, null descriptor and null thunk members
   that GNU ld and link.exe need; then one short import object per export,
   indexed under both its name and __imp_ name. */
static bool write_import_library(CLinker *linker, const char *path, const char *dll, CSymbol **exports, size_t count) {
  size_t dll_length = strlen(dll);
  char stem[256];
  snprintf(stem, sizeof(stem), "%s", dll);
  char *dot = strrchr(stem, '.');
  if (dot) *dot = 0;
  char descriptor_name[300], thunk_name[300];
  snprintf(descriptor_name, sizeof(descriptor_name), "__IMPORT_DESCRIPTOR_%s", stem);
  snprintf(thunk_name, sizeof(thunk_name), "\x7f%s_NULL_THUNK_DATA", stem);
  uint8_t zero[20] = {0};
  uint8_t name_data[300] = {0};
  uint32_t name_size = (uint32_t)dll_length + 1;
  memcpy(name_data, dll, dll_length);
  TinySection descriptor_sections[2] = {
    {".idata$2", zero, 20, {{12, 2}, {0, 3}, {16, 4}}, 3},
    {".idata$6", name_data, name_size, {{0, 0}}, 0},
  };
  TinySymbol descriptor_symbols[7] = {
    {descriptor_name, 1, CLASS_EXTERNAL}, {".idata$2", 1, CLASS_SECTION}, {".idata$6", 2, CLASS_STATIC},
    {".idata$4", 0, CLASS_SECTION}, {".idata$5", 0, CLASS_SECTION}, {"__NULL_IMPORT_DESCRIPTOR", 0, CLASS_EXTERNAL},
    {thunk_name, 0, CLASS_EXTERNAL},
  };
  TinySection null_sections[1] = {{".idata$3", zero, 20, {{0, 0}}, 0}};
  TinySymbol null_symbols[1] = {{"__NULL_IMPORT_DESCRIPTOR", 1, CLASS_EXTERNAL}};
  TinySection thunk_sections[2] = {{".idata$5", zero, 8, {{0, 0}}, 0}, {".idata$4", zero, 8, {{0, 0}}, 0}};
  TinySymbol thunk_symbols[1] = {{thunk_name, 1, CLASS_EXTERNAL}};
  size_t helper_sizes[3] = {tiny_object(linker->machine, NULL, descriptor_sections, 2, descriptor_symbols, 7),
                            tiny_object(linker->machine, NULL, null_sections, 1, null_symbols, 1),
                            tiny_object(linker->machine, NULL, thunk_sections, 2, thunk_symbols, 1)};
  const char *helper_names[3] = {descriptor_name, "__NULL_IMPORT_DESCRIPTOR", thunk_name};
  size_t names = 0, index_entries = 3;
  for (int h = 0; h < 3; ++h) names += strlen(helper_names[h]) + 1;
  for (size_t i = 0; i < count; ++i) {
    bool code = exports[i]->code;
    names += 6 + strlen(exports[i]->name) + 1 + (code ? strlen(exports[i]->name) + 1 : 0);
    index_entries += code ? 2 : 1;
  }
  size_t index_size = 4 + index_entries * 4 + names;
  size_t first = 8 + 60 + index_size + (index_size & 1);
  size_t total = first;
  for (int h = 0; h < 3; ++h) total += 60 + helper_sizes[h] + (helper_sizes[h] & 1);
  for (size_t i = 0; i < count; ++i) {
    size_t body = 20 + strlen(exports[i]->name) + 1 + dll_length + 1;
    total += 60 + body + (body & 1);
  }
  uint8_t *archive = calloc(1, total);
  if (!archive) return fail(linker, "out of memory%s%s", "", "");
  memcpy(archive, "!<arch>\n", 8);
  char size_text[24];
  #define MEMBER_HEADER(at, member_name, body_size) do { \
    uint8_t *header_ = archive + (at); \
    memset(header_, ' ', 60); \
    memcpy(header_, (member_name), strlen(member_name)); \
    header_[40] = '6'; header_[41] = '4'; header_[42] = '4'; \
    snprintf(size_text, sizeof(size_text), "%zu", (size_t)(body_size)); \
    memcpy(header_ + 48, size_text, strlen(size_text)); \
    header_[58] = '`'; header_[59] = '\n'; \
  } while (0)
  MEMBER_HEADER(8, "/", index_size);
  uint8_t *index = archive + 68;
  write32be(index, (uint32_t)index_entries);
  char *strings = (char *)index + 4 + index_entries * 4;
  char member_name[20];
  size_t member_length = dll_length < 15 ? dll_length : 15;
  memcpy(member_name, dll, member_length);
  member_name[member_length] = '/';
  member_name[member_length + 1] = 0;
  size_t entry = 0, at = first;
  for (int h = 0; h < 3; ++h) {
    write32be(index + 4 + entry++ * 4, (uint32_t)at);
    memcpy(strings, helper_names[h], strlen(helper_names[h]) + 1);
    strings += strlen(helper_names[h]) + 1;
    MEMBER_HEADER(at, member_name, helper_sizes[h]);
    if (h == 0) tiny_object(linker->machine, archive + at + 60, descriptor_sections, 2, descriptor_symbols, 7);
    if (h == 1) tiny_object(linker->machine, archive + at + 60, null_sections, 1, null_symbols, 1);
    if (h == 2) tiny_object(linker->machine, archive + at + 60, thunk_sections, 2, thunk_symbols, 1);
    at += 60 + helper_sizes[h];
    if (helper_sizes[h] & 1) archive[at++] = '\n';
  }
  for (size_t i = 0; i < count; ++i) {
    const char *name = exports[i]->name;
    size_t body = 20 + strlen(name) + 1 + dll_length + 1;
    if (exports[i]->code) {
      write32be(index + 4 + entry++ * 4, (uint32_t)at);
      memcpy(strings, name, strlen(name) + 1);
      strings += strlen(name) + 1;
    }
    write32be(index + 4 + entry++ * 4, (uint32_t)at);
    memcpy(strings, "__imp_", 6);
    memcpy(strings + 6, name, strlen(name) + 1);
    strings += 6 + strlen(name) + 1;
    MEMBER_HEADER(at, member_name, body);
    uint8_t *object = archive + at + 60;
    write16(object, 0);
    write16(object + 2, 0xffff);
    write16(object + 6, linker->machine);
    write32(object + 12, (uint32_t)(body - 20));
    write16(object + 16, (uint16_t)i);
    write16(object + 18, (uint16_t)((exports[i]->code ? 0 : 1) | 1 << 2)); /* IMPORT_NAME */
    memcpy(object + 20, name, strlen(name) + 1);
    memcpy(object + 20 + strlen(name) + 1, dll, dll_length + 1);
    at += 60 + body;
    if (body & 1) archive[at++] = '\n';
  }
  #undef MEMBER_HEADER
  FILE *file = fopen(path, "wb");
  bool ok = file && fwrite(archive, 1, total, file) == total;
  if (file && fclose(file)) ok = false;
  free(archive);
  return ok || fail(linker, "cannot write '%s'%s", path, "");
}

static bool write_output(CLinker *linker, const char *entry_name, const char *import_library, const char *dll_name) {
  bool shared = linker->shared;
  /* DLL exports, sized before layout. */
  CSymbol **exports = NULL;
  size_t export_count = 0, export_capacity = 0;
  CSection *edata = NULL;
  size_t name_bytes = 0;
  if (shared) {
    for (size_t i = 0; i < linker->table_capacity; ++i) {
      CSymbol *symbol = linker->table[i];
      if (!symbol || !exported_symbol(symbol)) continue;
      if (!grow((void **)&exports, &export_capacity, export_count, sizeof(*exports))) return fail(linker, "out of memory%s%s", "", "");
      exports[export_count++] = symbol;
      name_bytes += strlen(symbol->name) + 1;
    }
    if (export_count) qsort(exports, export_count, sizeof(*exports), compare_symbols);
    uint32_t size = 40 + (uint32_t)export_count * 10 + (uint32_t)name_bytes + (uint32_t)strlen(dll_name) + 1;
    edata = synthetic(linker, ".edata", size, 4, SCN_CNT_INITIALIZED | SCN_MEM_READ);
    if (!edata || !add_contribution(linker, edata)) { free(exports); return fail(linker, "out of memory%s%s", "", ""); }
    /* Keep .edata in rank order. */
    for (size_t i = linker->output_count - 1; i > 0 && rank(linker->outputs[i - 1].name) > rank(linker->outputs[i].name); --i) {
      COutput swap = linker->outputs[i - 1];
      linker->outputs[i - 1] = linker->outputs[i];
      linker->outputs[i] = swap;
    }
    for (size_t i = 0; i < linker->output_count; ++i)
      for (size_t s = 0; s < linker->outputs[i].count; ++s) linker->outputs[i].sections[s]->output = (int)i;
  }
  /* Sizes first: Windows rejects a section with neither virtual nor raw
     size, so empty outputs get no header (their symbols take the next RVA). */
  for (size_t i = 0; i < linker->output_count; ++i) {
    COutput *output = &linker->outputs[i];
    uint32_t size = 0;
    for (size_t s = 0; s < output->count; ++s) {
      CSection *section = output->sections[s];
      size = align_up(size, section->align ? section->align : 1);
      section->offset = size;
      size += section->size;
    }
    output->size = size;
    if (!size) output->count = 0;
  }
  size_t section_count = 0;
  for (size_t i = 0; i < linker->output_count; ++i) section_count += linker->outputs[i].count != 0;
  bool relocatable = shared || linker->machine == MACHINE_ARM64;
  size_t reloc_section = relocatable ? 1 : 0;
  uint32_t headers = align_up((uint32_t)(0x80 + 4 + 20 + 240 + 40 * (section_count + reloc_section)), FILE_ALIGN);
  uint32_t rva = align_up(headers, SECTION_ALIGN), file_offset = headers;
  uint16_t index = 0;
  for (size_t i = 0; i < linker->output_count; ++i) {
    COutput *output = &linker->outputs[i];
    output->rva = rva;
    if (!output->count) continue;
    output->index = ++index;
    uint32_t size = output->size;
    bool uninitialized = (output->characteristics & SCN_CNT_UNINITIALIZED) &&
                         !(output->characteristics & (SCN_CNT_INITIALIZED | SCN_CNT_CODE));
    output->file_size = uninitialized ? 0 : align_up(size, FILE_ALIGN);
    output->file_offset = output->file_size ? file_offset : 0;
    file_offset += output->file_size;
    rva = align_up(rva + (size ? size : 1), SECTION_ALIGN);
  }
  if (linker->shared) {
    CSymbol *image = symbol_find(linker, "__ImageBase");
    if (image && !image->defined) { image->defined = image->absolute = true; image->value = 0; }
  }
  /* Relocate, collecting DLL base relocations. */
  RelocationList base_relocations = {0};
  bool ok = true;
  uint8_t **contents = calloc(linker->output_count + 1, sizeof(*contents));
  if (!contents) ok = fail(linker, "out of memory%s%s", "", "");
  for (size_t i = 0; ok && i < linker->output_count; ++i) {
    COutput *output = &linker->outputs[i];
    if (!output->count || !output->file_size) continue;
    contents[i] = calloc(1, output->file_size);
    if (!contents[i]) { ok = fail(linker, "out of memory%s%s", "", ""); break; }
    /* Gaps in code trap. */
    if (output->characteristics & SCN_CNT_CODE) memset(contents[i], 0xcc, output->size);
    for (size_t s = 0; ok && s < output->count; ++s) {
      CSection *section = output->sections[s];
      uint8_t *at = contents[i] + section->offset;
      if (section->data) memcpy(at, section->data, section->size);
      else if (output->characteristics & SCN_CNT_CODE) memset(at, 0, section->size);
      ok = relocate(linker, section, at, &base_relocations);
    }
  }
  /* Export directory. */
  if (ok && edata) {
    COutput *output = &linker->outputs[edata->output];
    uint8_t *e = contents[edata->output] + edata->offset;
    uint32_t e_rva = output->rva + edata->offset;
    uint32_t functions = e_rva + 40, names = functions + (uint32_t)export_count * 4, ordinals = names + (uint32_t)export_count * 4;
    uint32_t strings = ordinals + (uint32_t)export_count * 2;
    write32(e + 12, strings); /* DLL name first. */
    write32(e + 16, 1);
    write32(e + 20, (uint32_t)export_count);
    write32(e + 24, (uint32_t)export_count);
    write32(e + 28, functions);
    write32(e + 32, names);
    write32(e + 36, ordinals);
    uint8_t *string = e + (strings - e_rva);
    memcpy(string, dll_name, strlen(dll_name) + 1);
    uint32_t string_rva = strings + (uint32_t)strlen(dll_name) + 1;
    string += strlen(dll_name) + 1;
    for (size_t k = 0; k < export_count; ++k) {
      write32(e + 40 + k * 4, symbol_rva(linker, exports[k]));
      write32(e + 40 + export_count * 4 + k * 4, string_rva);
      write16(e + 40 + export_count * 8 + k * 2, (uint16_t)k);
      size_t length = strlen(exports[k]->name) + 1;
      memcpy(string, exports[k]->name, length);
      string += length;
      string_rva += (uint32_t)length;
    }
  }
  /* Base relocations, one block per 4 KiB page. */
  uint8_t *reloc_data = NULL;
  uint32_t reloc_size = 0, reloc_rva = rva, reloc_file = file_offset, reloc_file_size = 0;
  if (ok && relocatable) {
    for (size_t i = 1; i < base_relocations.count; ++i)
      for (size_t j = i; j > 0 && base_relocations.rvas[j - 1] > base_relocations.rvas[j]; --j) {
        uint32_t swap = base_relocations.rvas[j - 1];
        base_relocations.rvas[j - 1] = base_relocations.rvas[j];
        base_relocations.rvas[j] = swap;
      }
    reloc_data = calloc(1, base_relocations.count * 4 + 16);
    if (!reloc_data) ok = fail(linker, "out of memory%s%s", "", "");
    for (size_t i = 0; ok && i < base_relocations.count;) {
      uint32_t page = base_relocations.rvas[i] & ~0xfffu;
      size_t start = reloc_size;
      reloc_size += 8;
      size_t entries = 0;
      for (; i < base_relocations.count && (base_relocations.rvas[i] & ~0xfffu) == page; ++i, ++entries) {
        write16(reloc_data + reloc_size, (uint16_t)(0xa000 | (base_relocations.rvas[i] & 0xfff))); /* DIR64 */
        reloc_size += 2;
      }
      if (entries & 1) reloc_size += 2;
      write32(reloc_data + start, page);
      write32(reloc_data + start + 4, (uint32_t)(reloc_size - start));
    }
    reloc_file_size = align_up(reloc_size ? reloc_size : 1, FILE_ALIGN);
    rva = align_up(rva + (reloc_size ? reloc_size : 1), SECTION_ALIGN);
    file_offset += reloc_file_size;
  }
  /* COFF string table for long section names. */
  char *string_table = NULL;
  uint32_t string_size = 4;
  for (size_t i = 0; i < linker->output_count; ++i)
    if (linker->outputs[i].count && strlen(linker->outputs[i].name) > 8) string_size += (uint32_t)strlen(linker->outputs[i].name) + 1;
  string_table = calloc(1, string_size);
  if (!string_table) ok = fail(linker, "out of memory%s%s", "", "");
  uint32_t file_size = file_offset + (string_size > 4 ? string_size : 0);
  uint8_t *image = ok ? calloc(1, file_size) : NULL;
  if (ok && !image) ok = fail(linker, "out of memory%s%s", "", "");
  CSymbol *entry = entry_name ? symbol_find(linker, entry_name) : NULL;
  if (ok && entry_name && (!entry || !entry->defined)) {
    if (!shared) ok = fail(linker, "entry symbol '%s' is undefined%s", entry_name, "");
    entry = NULL;
  }
  if (ok) {
    /* DOS header pointing at the PE header. */
    image[0] = 'M';
    image[1] = 'Z';
    write32(image + 0x3c, 0x80);
    uint8_t *pe = image + 0x80;
    memcpy(pe, "PE\0\0", 4);
    uint8_t *coff = pe + 4;
    write16(coff, linker->machine);
    write16(coff + 2, (uint16_t)(section_count + reloc_section));
    write32(coff + 8, string_size > 4 ? file_offset : 0);
    write16(coff + 16, 240);
    write16(coff + 18, (uint16_t)(0x0002 | 0x0020 | (shared ? 0x2000 : 0x0004)));
    uint8_t *optional = coff + 20;
    uint32_t code_size = 0, data_size = 0, bss_size = 0, code_base = 0;
    for (size_t i = 0; i < linker->output_count; ++i) {
      COutput *output = &linker->outputs[i];
      if (!output->count) continue;
      if (output->characteristics & SCN_CNT_CODE) { code_size += output->file_size; if (!code_base) code_base = output->rva; }
      else if (output->file_size) data_size += output->file_size;
      else bss_size += align_up(output->size, FILE_ALIGN);
    }
    write16(optional, 0x20b);
    optional[2] = 2;
    optional[3] = 40;
    write32(optional + 4, code_size);
    write32(optional + 8, data_size + reloc_file_size);
    write32(optional + 12, bss_size);
    write32(optional + 16, entry ? symbol_rva(linker, entry) : 0);
    write32(optional + 20, code_base);
    write64(optional + 24, linker->base);
    write32(optional + 32, SECTION_ALIGN);
    write32(optional + 36, FILE_ALIGN);
    write16(optional + 40, linker->machine == MACHINE_ARM64 ? 6 : 4);
    write16(optional + 48, linker->machine == MACHINE_ARM64 ? 6 : 5);
    write16(optional + 50, linker->machine == MACHINE_ARM64 ? 0 : 2);
    write32(optional + 56, rva);
    write32(optional + 60, headers);
    write16(optional + 68, 3); /* Console. */
    /* ARM64 requires ASLR (Microsoft /DYNAMICBASE); match the LLD ARM64
       OS/subsystem 6.0 and NX-compatible image policy for EXEs and DLLs. */
    write16(optional + 70, linker->machine == MACHINE_ARM64 ? 0x0160 : shared ? 0x0060 : 0);
    write64(optional + 72, 0x200000);
    write64(optional + 80, 0x1000);
    write64(optional + 88, 0x100000);
    write64(optional + 96, 0x1000);
    write32(optional + 108, 16);
    uint8_t *directories = optional + 112;
    for (size_t i = 0; i < linker->output_count; ++i) {
      COutput *output = &linker->outputs[i];
      if (!output->count) continue;
      if (!strcmp(output->name, ".edata")) { write32(directories, output->rva); write32(directories + 4, output->size); }
      if (!strcmp(output->name, ".pdata")) { write32(directories + 24, output->rva); write32(directories + 28, output->size); }
      if (!strcmp(output->name, ".idata")) {
        /* Import descriptors: $2 parts plus the terminator; IAT: $5 parts. */
        uint32_t descriptors_start = UINT32_MAX, descriptors_end = 0, iat_start = UINT32_MAX, iat_end = 0;
        for (size_t s = 0; s < output->count; ++s) {
          CSection *section = output->sections[s];
          const char *suffix = strchr(section->name, '$');
          uint32_t start = output->rva + section->offset, end = start + section->size;
          if (suffix && (!strcmp(suffix, "$2") || !strcmp(suffix, "$3"))) {
            if (start < descriptors_start) descriptors_start = start;
            if (end > descriptors_end) descriptors_end = end;
          }
          if (suffix && !strcmp(suffix, "$5")) {
            if (start < iat_start) iat_start = start;
            if (end > iat_end) iat_end = end;
          }
        }
        if (descriptors_end) { write32(directories + 8, descriptors_start); write32(directories + 12, descriptors_end - descriptors_start); }
        if (iat_end) { write32(directories + 96, iat_start); write32(directories + 100, iat_end - iat_start); }
      }
    }
    if (relocatable && reloc_size) { write32(directories + 40, reloc_rva); write32(directories + 44, reloc_size); }
    uint8_t *section_header = optional + 240;
    uint32_t string_at = 4;
    for (size_t i = 0; i < linker->output_count; ++i) {
      COutput *output = &linker->outputs[i];
      if (!output->count) continue;
      if (strlen(output->name) > 8) {
        char reference[9];
        snprintf(reference, sizeof(reference), "/%u", string_at);
        memcpy(section_header, reference, strlen(reference));
        memcpy(string_table + string_at, output->name, strlen(output->name) + 1);
        string_at += (uint32_t)strlen(output->name) + 1;
      } else {
        memcpy(section_header, output->name, strlen(output->name));
      }
      write32(section_header + 8, output->size);
      write32(section_header + 12, output->rva);
      write32(section_header + 16, output->file_size);
      write32(section_header + 20, output->file_offset);
      uint32_t flags = output->characteristics & ~(SCN_LNK_INFO | SCN_LNK_REMOVE);
      if (!strncmp(output->name, ".debug_", 7)) flags |= SCN_MEM_DISCARDABLE;
      write32(section_header + 36, flags);
      section_header += 40;
      if (output->file_size) memcpy(image + output->file_offset, contents[i], output->file_size);
    }
    if (relocatable) {
      memcpy(section_header, ".reloc", 6);
      write32(section_header + 8, reloc_size);
      write32(section_header + 12, reloc_rva);
      write32(section_header + 16, reloc_file_size);
      write32(section_header + 20, reloc_file);
      write32(section_header + 36, SCN_CNT_INITIALIZED | SCN_MEM_READ | SCN_MEM_DISCARDABLE);
      if (reloc_size) memcpy(image + reloc_file, reloc_data, reloc_size);
    }
    if (string_size > 4) {
      write32((uint8_t *)string_table, string_size);
      memcpy(image + file_offset, string_table, string_size);
    }
    FILE *file = fopen(linker->output_path, "wb");
    ok = file && fwrite(image, 1, file_size, file) == file_size;
    if (file && fclose(file)) ok = false;
    if (!ok) fail(linker, "cannot write '%s'%s", linker->output_path, "");
  }
  if (ok && shared && import_library) ok = write_import_library(linker, import_library, dll_name, exports, export_count);
  for (size_t i = 0; contents && i < linker->output_count; ++i) free(contents[i]);
  free(contents);
  free(image);
  free(string_table);
  free(reloc_data);
  free(base_relocations.rvas);
  free(exports);
  return ok;
}

static void linker_free(CLinker *linker) {
  for (size_t o = 0; o < linker->object_count; ++o) {
    CObject *object = linker->objects[o];
    for (size_t s = 0; s < object->section_count; ++s) free(object->sections[s].relocs);
    free(object->sections);
    free(object);
  }
  free(linker->objects);
  free(linker->archives);
  for (size_t i = 0; i < linker->buffer_count; ++i) free(linker->buffers[i]);
  free(linker->buffers);
  for (size_t i = 0; i < linker->table_capacity; ++i) free(linker->table[i]);
  free(linker->table);
  for (size_t i = 0; i < linker->local_count; ++i) free(linker->locals[i]);
  free(linker->locals);
  for (size_t i = 0; i < linker->extra_count; ++i) {
    free(linker->extra[i]->owned);
    free(linker->extra[i]->relocs);
    free(linker->extra[i]);
  }
  free(linker->extra);
  free(linker->comdats);
  free(linker->imports);
  for (size_t i = 0; i < linker->output_count; ++i) free(linker->outputs[i].sections);
  free(linker->outputs);
}

bool dyn_link_coff_supported(const char *path) {
  FILE *file = fopen(path, "rb");
  if (!file) return true;
  uint8_t magic[8] = {0};
  size_t n = fread(magic, 1, sizeof(magic), file);
  fclose(file);
  if (n >= 8 && !memcmp(magic, "!<arch>\n", 8)) return true;
  return n >= 2 && (read16(magic) == MACHINE_AMD64 || read16(magic) == MACHINE_ARM64);
}

int dyn_link_coff(const char *const *inputs, size_t input_count, const char *output, const DynCoffOptions *options) {
  CLinker linker = {.output_path = output, .shared = options->shared, .base = options->shared ? DLL_BASE : EXE_BASE};
  bool ok = true;
  for (size_t i = 0; ok && i < input_count; ++i) {
    size_t size = 0;
    uint8_t *data = read_file(&linker, inputs[i], &size);
    if (!data) { ok = false; break; }
    if (size >= 8 && !memcmp(data, "!<arch>\n", 8)) ok = load_archive(&linker, inputs[i], data, size);
    else if (size >= 4 && read16(data) == 0 && read16(data + 2) == 0xffff) ok = load_import(&linker, inputs[i], data, size);
    else ok = load_object(&linker, inputs[i], data, size);
  }
  const char *dll_name = options->dll_name ? options->dll_name : output;
  ok = ok && resolve_archives(&linker) && build_imports(&linker) && assign_outputs(&linker) &&
       write_output(&linker, options->entry, options->import_library, dll_name);
  if (!ok) {
    fprintf(stderr, "error: link: %s\n", linker.error[0] ? linker.error : "out of memory");
    remove(output);
  }
  linker_free(&linker);
  return ok ? 0 : 2;
}
