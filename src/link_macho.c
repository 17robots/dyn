/* Built-in Mach-O linker for arm64 macOS, so building for macOS needs no
   external linker. Inputs are relocatable objects, ar archives, dylibs and
   text-based stubs (.tbd); the output is a position-independent executable
   or a dylib. Imports bind at load time through LC_DYLD_INFO_ONLY opcodes
   (no lazy binding), and the output carries the ad-hoc code signature that
   Apple silicon requires. Sections are kept whole, as the compiler's links
   never asked for -dead_strip. Debug sections stay in the objects, and no
   __unwind_info is written: Dyn unwinds itself and debuggers walk frame
   pointers. Structures are read field by field so any host can link. */
#include "link_macho.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

enum {
  CPU_ARM64 = 0x0100000c, CPU_X86_64 = 0x01000007,
  MH_OBJECT = 1, MH_EXECUTE = 2, MH_DYLIB = 6,
  MH_NOUNDEFS = 1, MH_DYLDLINK = 4, MH_TWOLEVEL = 0x80, MH_PIE = 0x200000, MH_NO_REEXPORTED_DYLIBS = 0x100000,
  LC_SYMTAB = 0x2, LC_DYSYMTAB = 0xb, LC_LOAD_DYLIB = 0xc, LC_ID_DYLIB = 0xd, LC_LOAD_DYLINKER = 0xe,
  LC_SEGMENT_64 = 0x19, LC_UUID = 0x1b, LC_CODE_SIGNATURE = 0x1d, LC_DYLD_INFO = 0x22, LC_BUILD_VERSION = 0x32,
  N_STAB = 0xe0, N_PEXT = 0x10, N_TYPE = 0x0e, N_EXT = 0x01, N_UNDF = 0, N_ABS = 2, N_SECT = 0xe,
  N_WEAK_REF = 0x40, N_WEAK_DEF = 0x80, REFERENCED_DYNAMICALLY = 0x10,
  S_ZEROFILL = 1, S_NON_LAZY_SYMBOL_POINTERS = 6, S_SYMBOL_STUBS = 8, S_GB_ZEROFILL = 12,
  S_ATTR_DEBUG = 0x02000000, S_ATTR_SOME_INSTRUCTIONS = 0x400,
  ARM64_RELOC_UNSIGNED = 0, ARM64_RELOC_SUBTRACTOR = 1, ARM64_RELOC_BRANCH26 = 2, ARM64_RELOC_PAGE21 = 3,
  ARM64_RELOC_PAGEOFF12 = 4, ARM64_RELOC_GOT_LOAD_PAGE21 = 5, ARM64_RELOC_GOT_LOAD_PAGEOFF12 = 6,
  ARM64_RELOC_POINTER_TO_GOT = 7, ARM64_RELOC_ADDEND = 10,
  REBASE_TYPE_POINTER = 1, BIND_TYPE_POINTER = 1, BIND_SYMBOL_FLAGS_WEAK_IMPORT = 1,
};
#define MH_MAGIC_64 0xfeedfacfu
#define LC_DYLD_INFO_ONLY 0x80000022u
#define LC_MAIN 0x80000028u
#define LC_DYLD_EXPORTS_TRIE 0x80000033u
#define S_ATTR_PURE_INSTRUCTIONS 0x80000000u
#define PAGE 0x4000u
#define TEXT_BASE 0x100000000ull
#define INDIRECT_SYMBOL_LOCAL 0x80000000u
#define STUB_SIZE 12

typedef struct MObject MObject;
typedef struct MSymbol MSymbol;
typedef struct MDylib MDylib;
typedef struct {
  uint64_t offset;
  int64_t addend;
  uint32_t symbol, subtrahend; /* Symbol indexes in the object; subtrahend for SUBTRACTOR pairs. */
  uint8_t type, length;
  bool pcrel, has_subtrahend;
} MReloc;
typedef struct {
  MObject *object;
  char segment[17], name[17];
  const uint8_t *data;
  uint64_t size, align, object_address, offset, address;
  uint32_t flags;
  MReloc *relocs;
  size_t reloc_count;
  int output;
} MSection;
struct MDylib {
  const char *install_name;
  uint32_t ordinal; /* One-based LC_LOAD_DYLIB index once used. */
  bool fallback; /* "-lName" with no symbol list: resolves anything left. */
};
struct MSymbol {
  const char *name;
  MSection *section; /* NULL when absolute or undefined. */
  uint64_t value; /* Offset in the section, or the absolute value. */
  uint64_t common_size, common_align;
  bool defined, absolute, weak_definition, private_extern, common, referenced, strong_reference, local;
  MDylib *dylib; /* Import source when no object defines it. */
  uint32_t got, stub; /* One-based slots. */
  uint32_t symtab; /* Index in the output symbol table plus one. */
  int archive_member;
  size_t archive;
};
struct MObject {
  const char *path;
  MSection *sections;
  size_t section_count;
  MSymbol **symbols;
  MSymbol *locals;
  size_t symbol_count;
};
typedef struct {
  const char *path;
  const uint8_t *data;
  size_t size;
} MArchive;
typedef struct {
  char segment[17], name[17];
  uint32_t flags;
  MSection **sections;
  size_t count, capacity;
  uint64_t align, size, address, file_offset;
  uint32_t reserved1, reserved2, ordinal;
} MOutput;
typedef struct {
  uint8_t *data;
  size_t size, capacity;
} MBytes;
typedef struct {
  const char *output_path;
  bool shared;
  uint32_t cpu;
  char error[512];
  MObject **objects;
  size_t object_count, object_capacity;
  MArchive *archives;
  size_t archive_count;
  MDylib **dylibs;
  size_t dylib_count, dylib_capacity;
  uint8_t **buffers;
  size_t buffer_count, buffer_capacity;
  MSymbol **table;
  size_t table_capacity, table_count;
  MSection **extra_sections; /* Commons and synthetic sections. */
  size_t extra_count, extra_capacity;
  MOutput *outputs;
  size_t output_count, output_capacity;
  int text_output, stubs_output, got_output;
  MSymbol **got_symbols, **stub_symbols;
  size_t got_count, got_capacity, stub_count, stub_capacity;
  struct { MSection *section; uint64_t offset; MSymbol *symbol; int64_t addend; bool bind; } *fixups;
  size_t fixup_count, fixup_capacity;
} MLinker;

static bool fail(MLinker *linker, const char *format, const char *a, const char *b) {
  if (!linker->error[0]) snprintf(linker->error, sizeof(linker->error), format, a, b);
  return false;
}
static uint32_t read32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint64_t read64(const uint8_t *p) { return (uint64_t)read32(p) | (uint64_t)read32(p + 4) << 32; }
static uint16_t read16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static void write32(uint8_t *p, uint32_t v) { for (int i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8 * i)); }
static void write64(uint8_t *p, uint64_t v) { write32(p, (uint32_t)v); write32(p + 4, (uint32_t)(v >> 32)); }
static void write32be(uint8_t *p, uint32_t v) { for (int i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (24 - 8 * i)); }
static void write64be(uint8_t *p, uint64_t v) { write32be(p, (uint32_t)(v >> 32)); write32be(p + 4, (uint32_t)v); }
static uint64_t align_up(uint64_t value, uint64_t align) { return align > 1 ? (value + align - 1) & ~(align - 1) : value; }
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
static bool bytes_reserve(MBytes *bytes, size_t extra) {
  while (bytes->size + extra > bytes->capacity) {
    size_t next = bytes->capacity ? bytes->capacity * 2 : 256;
    uint8_t *grown = realloc(bytes->data, next);
    if (!grown) return false;
    bytes->data = grown;
    bytes->capacity = next;
  }
  return true;
}
static bool bytes_append(MBytes *bytes, const void *data, size_t size) {
  if (!bytes_reserve(bytes, size)) return false;
  memcpy(bytes->data + bytes->size, data, size);
  bytes->size += size;
  return true;
}
static bool bytes_byte(MBytes *bytes, uint8_t value) { return bytes_append(bytes, &value, 1); }
static bool bytes_uleb(MBytes *bytes, uint64_t value) {
  do {
    uint8_t byte = value & 0x7f;
    value >>= 7;
    if (value) byte |= 0x80;
    if (!bytes_byte(bytes, byte)) return false;
  } while (value);
  return true;
}
static bool bytes_sleb(MBytes *bytes, int64_t value) {
  for (bool more = true; more;) {
    uint8_t byte = value & 0x7f;
    value >>= 7;
    more = !((value == 0 && !(byte & 0x40)) || (value == -1 && (byte & 0x40)));
    if (more) byte |= 0x80;
    if (!bytes_byte(bytes, byte)) return false;
  }
  return true;
}
static size_t uleb_size(uint64_t value) {
  size_t n = 1;
  while (value >>= 7) ++n;
  return n;
}

/* SHA-256 for the code signature and the UUID. */
typedef struct {
  uint32_t state[8];
  uint64_t length;
  uint8_t block[64];
  size_t used;
} Sha256;
static const uint32_t sha_k[64] = {
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};
static uint32_t rotate(uint32_t x, int n) { return x >> n | x << (32 - n); }
static void sha_block(Sha256 *sha, const uint8_t *p) {
  uint32_t w[64], s[8];
  for (int i = 0; i < 16; ++i) w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
  for (int i = 16; i < 64; ++i) {
    uint32_t s0 = rotate(w[i - 15], 7) ^ rotate(w[i - 15], 18) ^ w[i - 15] >> 3;
    uint32_t s1 = rotate(w[i - 2], 17) ^ rotate(w[i - 2], 19) ^ w[i - 2] >> 10;
    w[i] = w[i - 16] + s0 + w[i - 7] + s1;
  }
  memcpy(s, sha->state, sizeof(s));
  for (int i = 0; i < 64; ++i) {
    uint32_t t1 = s[7] + (rotate(s[4], 6) ^ rotate(s[4], 11) ^ rotate(s[4], 25)) + ((s[4] & s[5]) ^ (~s[4] & s[6])) + sha_k[i] + w[i];
    uint32_t t2 = (rotate(s[0], 2) ^ rotate(s[0], 13) ^ rotate(s[0], 22)) + ((s[0] & s[1]) ^ (s[0] & s[2]) ^ (s[1] & s[2]));
    memmove(s + 1, s, 7 * sizeof(*s));
    s[4] += t1;
    s[0] = t1 + t2;
  }
  for (int i = 0; i < 8; ++i) sha->state[i] += s[i];
}
static void sha256(const uint8_t *data, size_t size, uint8_t out[32]) {
  Sha256 sha = {{0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19}, 0, {0}, 0};
  size_t at = 0;
  for (; at + 64 <= size; at += 64) sha_block(&sha, data + at);
  uint8_t tail[128] = {0};
  size_t rest = size - at;
  memcpy(tail, data + at, rest);
  tail[rest] = 0x80;
  size_t total = rest + 9 <= 64 ? 64 : 128;
  write64be(tail + total - 8, (uint64_t)size * 8);
  for (size_t i = 0; i < total; i += 64) sha_block(&sha, tail + i);
  for (int i = 0; i < 8; ++i) write32be(out + 4 * i, sha.state[i]);
}

static uint64_t hash_name(const char *name) {
  uint64_t hash = 14695981039346656037ull;
  for (; *name; ++name) hash = (hash ^ (uint8_t)*name) * 1099511628211ull;
  return hash;
}
static MSymbol *symbol_find(MLinker *linker, const char *name) {
  if (!linker->table_capacity) return NULL;
  for (size_t i = hash_name(name) & (linker->table_capacity - 1);; i = (i + 1) & (linker->table_capacity - 1)) {
    if (!linker->table[i]) return NULL;
    if (!strcmp(linker->table[i]->name, name)) return linker->table[i];
  }
}
static MSymbol *symbol_intern(MLinker *linker, const char *name) {
  MSymbol *found = symbol_find(linker, name);
  if (found) return found;
  if ((linker->table_count + 1) * 2 > linker->table_capacity) {
    size_t capacity = linker->table_capacity ? linker->table_capacity * 2 : 1024;
    MSymbol **table = calloc(capacity, sizeof(*table));
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
  MSymbol *symbol = calloc(1, sizeof(*symbol));
  if (!symbol) return NULL;
  symbol->name = name;
  symbol->archive_member = -1;
  size_t at = hash_name(name) & (linker->table_capacity - 1);
  while (linker->table[at]) at = (at + 1) & (linker->table_capacity - 1);
  linker->table[at] = symbol;
  ++linker->table_count;
  return symbol;
}
static uint8_t *keep(MLinker *linker, uint8_t *data) {
  if (!data) return NULL;
  if (!grow((void **)&linker->buffers, &linker->buffer_capacity, linker->buffer_count, sizeof(*linker->buffers))) {
    free(data);
    return NULL;
  }
  linker->buffers[linker->buffer_count++] = data;
  return data;
}
static char *keep_string(MLinker *linker, const char *text, size_t length) {
  char *copy = malloc(length + 1);
  if (!copy) return NULL;
  memcpy(copy, text, length);
  copy[length] = 0;
  return (char *)keep(linker, (uint8_t *)copy);
}
static uint8_t *read_file(MLinker *linker, const char *path, size_t *size) {
  FILE *file = fopen(path, "rb");
  if (!file) { fail(linker, "cannot open '%s'%s", path, ""); return NULL; }
  struct stat info;
  uint8_t *data = NULL;
  if (!stat(path, &info) && info.st_size >= 0 && (data = malloc((size_t)info.st_size + 1)) &&
      fread(data, 1, (size_t)info.st_size, file) == (size_t)info.st_size) {
    *size = (size_t)info.st_size;
    data[*size] = 0;
  } else {
    free(data);
    data = NULL;
    fail(linker, "cannot read '%s'%s", path, "");
  }
  fclose(file);
  return keep(linker, data);
}
static MDylib *add_dylib(MLinker *linker, const char *install_name, bool fallback) {
  for (size_t i = 0; i < linker->dylib_count; ++i)
    if (!strcmp(linker->dylibs[i]->install_name, install_name)) {
      linker->dylibs[i]->fallback |= fallback;
      return linker->dylibs[i];
    }
  MDylib *dylib = calloc(1, sizeof(*dylib));
  if (!dylib || !grow((void **)&linker->dylibs, &linker->dylib_capacity, linker->dylib_count, sizeof(*linker->dylibs))) {
    free(dylib);
    return NULL;
  }
  dylib->install_name = install_name;
  dylib->fallback = fallback;
  linker->dylibs[linker->dylib_count++] = dylib;
  return dylib;
}
static bool export_symbol(MLinker *linker, MDylib *dylib, const char *name) {
  MSymbol *symbol = symbol_intern(linker, name);
  if (!symbol) return fail(linker, "out of memory%s%s", "", "");
  if (!symbol->dylib) symbol->dylib = dylib;
  return true;
}

/* Relocatable objects. */
static void copy_name(char out[17], const uint8_t *field) {
  memcpy(out, field, 16);
  out[16] = 0;
}
static bool define(MLinker *linker, MObject *object, MSymbol *symbol, MSection *section, uint64_t value,
                   bool absolute, bool weak, bool private_extern) {
  if (symbol->defined && !symbol->common) {
    if (weak) return true;
    if (!symbol->weak_definition) return fail(linker, "duplicate symbol '%s' (also in %s)", symbol->name, object->path);
  }
  symbol->defined = true;
  symbol->common = false;
  symbol->section = section;
  symbol->value = value;
  symbol->absolute = absolute;
  symbol->weak_definition = weak;
  symbol->private_extern = private_extern;
  symbol->archive_member = -1;
  return true;
}
static bool load_object(MLinker *linker, const char *path, const uint8_t *data, size_t size) {
  if (size < 32 || read32(data) != MH_MAGIC_64 || read32(data + 12) != MH_OBJECT)
    return fail(linker, "'%s' is not a 64-bit Mach-O object%s", path, "");
  uint32_t cpu = read32(data + 4);
  if ((cpu != CPU_ARM64 && cpu != CPU_X86_64) || (linker->cpu && linker->cpu != cpu))
    return fail(linker, "'%s' has an incompatible Mach-O architecture%s", path, "");
  linker->cpu = cpu;
  MObject *object = calloc(1, sizeof(*object));
  if (!object || !grow((void **)&linker->objects, &linker->object_capacity, linker->object_count, sizeof(*linker->objects))) {
    free(object);
    return fail(linker, "out of memory%s%s", "", "");
  }
  linker->objects[linker->object_count++] = object;
  object->path = path;
  uint32_t commands = read32(data + 16), commands_size = read32(data + 20);
  if (!in_bounds(size, 32, commands_size)) return fail(linker, "'%s' has malformed load commands%s", path, "");
  const uint8_t *symtab = NULL;
  size_t at = 32;
  for (uint32_t c = 0; c < commands; ++c) {
    if (!in_bounds(size, at, 8)) return fail(linker, "'%s' has malformed load commands%s", path, "");
    uint32_t command = read32(data + at), command_size = read32(data + at + 4);
    if (command_size < 8 || !in_bounds(size, at, command_size)) return fail(linker, "'%s' has malformed load commands%s", path, "");
    if (command == LC_SEGMENT_64) {
      uint32_t count = read32(data + at + 64);
      if ((uint64_t)count * 80 + 72 > command_size) return fail(linker, "'%s' has a malformed segment%s", path, "");
      object->sections = calloc(count + 1, sizeof(MSection));
      if (!object->sections) return fail(linker, "out of memory%s%s", "", "");
      object->section_count = count;
      for (uint32_t s = 0; s < count; ++s) {
        const uint8_t *h = data + at + 72 + (size_t)s * 80;
        MSection *section = &object->sections[s];
        section->object = object;
        copy_name(section->name, h);
        copy_name(section->segment, h + 16);
        section->object_address = read64(h + 32);
        section->size = read64(h + 40);
        section->align = (uint64_t)1 << (read32(h + 52) & 31);
        section->flags = read32(h + 64);
        section->output = -1;
        uint8_t type = section->flags & 0xff;
        if (type != S_ZEROFILL && type != S_GB_ZEROFILL) {
          if (!in_bounds(size, read32(h + 48), section->size)) return fail(linker, "'%s' has a section outside the file%s", path, "");
          section->data = data + read32(h + 48);
        }
        uint32_t relocation_offset = read32(h + 56), relocation_count = read32(h + 60);
        if (!in_bounds(size, relocation_offset, (uint64_t)relocation_count * 8))
          return fail(linker, "'%s' has malformed relocations%s", path, "");
        section->relocs = calloc(relocation_count + 1, sizeof(MReloc));
        if (!section->relocs) return fail(linker, "out of memory%s%s", "", "");
        int64_t addend = 0;
        bool pending_addend = false, pending_subtractor = false;
        uint32_t subtrahend = 0;
        for (uint32_t r = 0; r < relocation_count; ++r) {
          const uint8_t *entry = data + relocation_offset + (size_t)r * 8;
          int32_t address = (int32_t)read32(entry);
          uint32_t info = read32(entry + 4);
          uint32_t symbol = info & 0xffffff;
          bool pcrel = (info >> 24) & 1, external = (info >> 27) & 1;
          uint8_t length = (info >> 25) & 3, type = (uint8_t)(info >> 28);
          if (address < 0) return fail(linker, "'%s' uses scattered relocations%s", path, "");
          if (linker->cpu == CPU_ARM64 && type == ARM64_RELOC_ADDEND) {
            addend = (int32_t)(symbol << 8) >> 8;
            pending_addend = true;
            continue;
          }
          if (type == (linker->cpu == CPU_ARM64 ? ARM64_RELOC_SUBTRACTOR : 5)) {
            if (!external) return fail(linker, "'%s' has a section-relative subtractor%s", path, "");
            subtrahend = symbol;
            pending_subtractor = true;
            continue;
          }
          MReloc *reloc = &section->relocs[section->reloc_count++];
          *reloc = (MReloc){(uint64_t)address, pending_addend ? addend : 0, symbol, subtrahend, type, length, pcrel, pending_subtractor};
          if (!external) {
            /* Section-relative: point at the section's own symbol below. */
            if ((type != ARM64_RELOC_UNSIGNED && !(linker->cpu == CPU_X86_64 && pcrel && (type == 1 || type == 2 || type == 6 || type == 7 || type == 8))) || symbol == 0 || symbol > count)
              return fail(linker, "'%s' has an unsupported section-relative relocation%s", path, "");
            reloc->symbol = UINT32_MAX - symbol;
          }
          pending_addend = pending_subtractor = false;
        }
      }
    } else if (command == LC_SYMTAB) {
      symtab = data + at;
    }
    at += command_size;
  }
  if (!symtab) return true;
  uint32_t symbol_offset = read32(symtab + 8), count = read32(symtab + 12);
  uint32_t string_offset = read32(symtab + 16), string_size = read32(symtab + 20);
  if (!in_bounds(size, symbol_offset, (uint64_t)count * 16) || !in_bounds(size, string_offset, string_size))
    return fail(linker, "'%s' has a malformed symbol table%s", path, "");
  const char *strings = (const char *)data + string_offset;
  object->symbol_count = count;
  object->symbols = calloc(count + object->section_count + 1, sizeof(MSymbol *));
  object->locals = calloc(count + object->section_count + 1, sizeof(MSymbol));
  if (!object->symbols || !object->locals) return fail(linker, "out of memory%s%s", "", "");
  for (uint32_t i = 0; i < count; ++i) {
    const uint8_t *entry = data + symbol_offset + (size_t)i * 16;
    uint32_t name = read32(entry);
    uint8_t type = entry[4], sect = entry[5];
    uint16_t desc = read16(entry + 6);
    uint64_t value = read64(entry + 8);
    if (name >= string_size || !memchr(strings + name, 0, string_size - name))
      return fail(linker, "'%s' has a malformed symbol name%s", path, "");
    if (type & N_STAB) continue;
    uint8_t kind = type & N_TYPE;
    MSection *section = NULL;
    if (kind == N_SECT) {
      if (sect == 0 || sect > object->section_count) return fail(linker, "'%s' has a symbol in a missing section%s", path, "");
      section = &object->sections[sect - 1];
      value -= section->object_address;
    }
    if (!(type & N_EXT)) {
      MSymbol *local = &object->locals[i];
      local->name = strings + name;
      local->section = section;
      local->value = value;
      local->defined = kind == N_SECT || kind == N_ABS;
      local->absolute = kind == N_ABS;
      local->local = true;
      local->archive_member = -1;
      object->symbols[i] = local;
      continue;
    }
    MSymbol *symbol = symbol_intern(linker, strings + name);
    if (!symbol) return fail(linker, "out of memory%s%s", "", "");
    object->symbols[i] = symbol;
    if (kind == N_UNDF && value) {
      /* A common definition: size in n_value, alignment in n_desc. */
      if (symbol->defined && !symbol->common) continue;
      symbol->common = symbol->defined = true;
      if (value > symbol->common_size) symbol->common_size = value;
      uint64_t align = (uint64_t)1 << ((desc >> 8) & 0xf);
      if (align > symbol->common_align) symbol->common_align = align;
      continue;
    }
    if (kind == N_UNDF) {
      symbol->referenced = true;
      if (!(desc & N_WEAK_REF)) symbol->strong_reference = true;
      continue;
    }
    if (kind != N_SECT && kind != N_ABS) return fail(linker, "'%s' uses an unsupported symbol kind%s", path, "");
    if (!define(linker, object, symbol, section, value, kind == N_ABS, (desc & N_WEAK_DEF) != 0, (type & N_PEXT) != 0))
      return false;
  }
  /* Section-relative relocations name these per-section symbols. */
  for (size_t s = 0; s < object->section_count; ++s) {
    MSymbol *local = &object->locals[count + s];
    local->name = "";
    local->section = &object->sections[s];
    local->defined = local->local = true;
    local->archive_member = -1;
  }
  for (size_t s = 0; s < object->section_count; ++s) {
    MSection *section = &object->sections[s];
    for (size_t r = 0; r < section->reloc_count; ++r) {
      MReloc *reloc = &section->relocs[r];
      if (reloc->symbol >= UINT32_MAX - object->section_count) {
        size_t target = UINT32_MAX - reloc->symbol - 1;
        reloc->symbol = count + (uint32_t)target;
        /* The pointer holds an address in the object's layout. */
        if (reloc->length == 3 && section->data && reloc->offset + 8 <= section->size)
          reloc->addend = (int64_t)(read64(section->data + reloc->offset) - object->sections[target].object_address);
        else if (reloc->length == 2 && section->data && reloc->offset + 4 <= section->size) {
          reloc->addend = (int64_t)(read32(section->data + reloc->offset) - object->sections[target].object_address);
          if (linker->cpu == CPU_X86_64 && reloc->pcrel) {
            unsigned extra = reloc->type >= 6 ? 1u << (reloc->type-6) : 0;
            reloc->addend = (int32_t)read32(section->data + reloc->offset) + (int64_t)(section->object_address + reloc->offset + 4 + extra - object->sections[target].object_address);
          }
        }
        reloc->length |= 0x80; /* Addend already taken from the contents. */
      } else if (reloc->symbol >= count || (reloc->has_subtrahend && reloc->subtrahend >= count)) {
        return fail(linker, "'%s' has a relocation to a missing symbol%s", path, "");
      }
    }
  }
  return true;
}

/* ar archives in GNU or BSD (__.SYMDEF) form. */
static size_t member_header(const uint8_t *data, size_t size, size_t at, const uint8_t **body, size_t *length) {
  if (at + 60 > size) return 0;
  size_t member_size = (size_t)strtoull((const char *)data + at + 48, NULL, 10);
  if (member_size > size - at - 60) return 0;
  *body = data + at + 60;
  *length = member_size;
  if (!memcmp(data + at, "#1/", 3)) {
    size_t skip = (size_t)strtoull((const char *)data + at + 3, NULL, 10);
    if (skip > member_size) return 0;
    *body += skip;
    *length -= skip;
  }
  return at + 60 + member_size + (member_size & 1);
}
static bool load_archive(MLinker *linker, const char *path, const uint8_t *data, size_t size) {
  MArchive *archives = realloc(linker->archives, (linker->archive_count + 1) * sizeof(*archives));
  if (!archives) return fail(linker, "out of memory%s%s", "", "");
  linker->archives = archives;
  size_t index = linker->archive_count++;
  archives[index] = (MArchive){path, data, size};
  const uint8_t *body;
  size_t length;
  size_t next = member_header(data, size, 8, &body, &length);
  if (!next) return fail(linker, "'%s' is a malformed archive%s", path, "");
  bool gnu = !memcmp(data + 8, "/               ", 16);
  bool bsd = !memcmp(data + 8, "__.SYMDEF", 9) || (!memcmp(data + 8, "#1/", 3) && size >= 77 && !memcmp(data + 68, "__.SYMDEF", 9));
  if (gnu && length >= 4) {
    uint32_t n = (uint32_t)body[0] << 24 | (uint32_t)body[1] << 16 | (uint32_t)body[2] << 8 | body[3];
    if ((uint64_t)n * 4 + 4 > length) return fail(linker, "'%s' has a malformed symbol index%s", path, "");
    const char *names = (const char *)body + 4 + (size_t)n * 4, *end = (const char *)body + length;
    for (uint32_t k = 0; k < n && names < end; ++k) {
      const uint8_t *p = body + 4 + (size_t)k * 4;
      uint32_t offset = (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
      const char *name_end = memchr(names, 0, (size_t)(end - names));
      if (!name_end) break;
      MSymbol *symbol = symbol_intern(linker, names);
      if (!symbol) return fail(linker, "out of memory%s%s", "", "");
      if (!symbol->defined && symbol->archive_member < 0) { symbol->archive_member = (int)offset; symbol->archive = index; }
      names = name_end + 1;
    }
    return true;
  }
  if (bsd && length >= 8) {
    /* The member name may sit at the start of the body (#1/n names). */
    const uint8_t *table = body;
    size_t table_length = length;
    uint32_t ranlib_size = read32(table);
    if ((uint64_t)ranlib_size + 8 > table_length) return fail(linker, "'%s' has a malformed symbol index%s", path, "");
    uint32_t string_size = read32(table + 4 + ranlib_size);
    const char *strings = (const char *)table + 8 + ranlib_size;
    if ((uint64_t)ranlib_size + 8 + string_size > table_length) return fail(linker, "'%s' has a malformed symbol index%s", path, "");
    for (uint32_t k = 0; k + 8 <= ranlib_size; k += 8) {
      uint32_t name = read32(table + 4 + k), offset = read32(table + 8 + k);
      if (name >= string_size || !memchr(strings + name, 0, string_size - name)) continue;
      MSymbol *symbol = symbol_intern(linker, strings + name);
      if (!symbol) return fail(linker, "out of memory%s%s", "", "");
      if (!symbol->defined && symbol->archive_member < 0) { symbol->archive_member = (int)offset; symbol->archive = index; }
    }
    return true;
  }
  return fail(linker, "'%s' has no symbol index (run ranlib)%s", path, "");
}
static bool resolve_archives(MLinker *linker) {
  for (bool changed = true; changed;) {
    changed = false;
    for (size_t i = 0; i < linker->table_capacity; ++i) {
      MSymbol *symbol = linker->table[i];
      if (!symbol || symbol->defined || symbol->dylib || !symbol->strong_reference || symbol->archive_member < 0) continue;
      MArchive *archive = &linker->archives[symbol->archive];
      const uint8_t *body;
      size_t length;
      size_t at = (size_t)symbol->archive_member;
      symbol->archive_member = -1;
      if (!member_header(archive->data, archive->size, at, &body, &length))
        return fail(linker, "'%s' has a malformed member offset%s", archive->path, "");
      if (!load_object(linker, archive->path, body, length)) return false;
      changed = true;
    }
  }
  return true;
}

/* Dylibs: the install name and the export trie. */
static bool walk_trie(MLinker *linker, MDylib *dylib, const uint8_t *trie, size_t size, size_t node, char *prefix,
                      size_t prefix_length, int depth) {
  if (node >= size || depth > 128) return true;
  const uint8_t *p = trie + node, *end = trie + size;
  uint64_t terminal = 0;
  int shift = 0;
  while (p < end) { terminal |= (uint64_t)(*p & 0x7f) << shift; shift += 7; if (!(*p++ & 0x80)) break; }
  if (terminal && !export_symbol(linker, dylib, keep_string(linker, prefix, prefix_length))) return false;
  p += terminal;
  if (p >= end) return true;
  uint8_t children = *p++;
  for (uint8_t c = 0; c < children && p < end; ++c) {
    const uint8_t *label = p;
    while (p < end && *p) ++p;
    size_t label_length = (size_t)(p - label);
    ++p;
    uint64_t child = 0;
    shift = 0;
    while (p < end) { child |= (uint64_t)(*p & 0x7f) << shift; shift += 7; if (!(*p++ & 0x80)) break; }
    if (prefix_length + label_length >= 4096) continue;
    memcpy(prefix + prefix_length, label, label_length);
    if (!walk_trie(linker, dylib, trie, size, (size_t)child, prefix, prefix_length + label_length, depth + 1)) return false;
  }
  return true;
}
static bool load_dylib(MLinker *linker, const char *path, const uint8_t *data, size_t size) {
  if (read32(data + 4) != linker->cpu) return fail(linker, "'%s' has an incompatible dylib architecture%s", path, "");
  uint32_t commands = read32(data + 16);
  const char *install_name = NULL;
  const uint8_t *trie = NULL;
  size_t trie_size = 0, at = 32;
  for (uint32_t c = 0; c < commands && in_bounds(size, at, 8); ++c) {
    uint32_t command = read32(data + at), command_size = read32(data + at + 4);
    if (command_size < 8 || !in_bounds(size, at, command_size)) break;
    if (command == LC_ID_DYLIB && command_size > 24) {
      uint32_t name = read32(data + at + 8);
      if (name < command_size && memchr(data + at + name, 0, command_size - name)) install_name = (const char *)data + at + name;
    } else if ((command == LC_DYLD_INFO || command == LC_DYLD_INFO_ONLY) && command_size >= 48) {
      if (in_bounds(size, read32(data + at + 40), read32(data + at + 44))) { trie = data + read32(data + at + 40); trie_size = read32(data + at + 44); }
    } else if (command == LC_DYLD_EXPORTS_TRIE && command_size >= 16) {
      if (in_bounds(size, read32(data + at + 8), read32(data + at + 12))) { trie = data + read32(data + at + 8); trie_size = read32(data + at + 12); }
    }
    at += command_size;
  }
  if (!install_name) return fail(linker, "'%s' has no install name%s", path, "");
  MDylib *dylib = add_dylib(linker, install_name, false);
  if (!dylib) return fail(linker, "out of memory%s%s", "", "");
  char prefix[4096];
  return !trie || walk_trie(linker, dylib, trie, trie_size, 0, prefix, 0, 0);
}
/* Text-based stubs (tbd v4): the "symbols" and "weak-symbols" lists under
   the top-level "exports" and "reexports" keys of every document bind to
   the first document's install name, which re-exports the others. */
static bool load_tbd(MLinker *linker, const char *path, const char *text, size_t size) {
  MDylib *dylib = NULL;
  const char *end = text + size;
  bool exporting = false, listing = false;
  for (const char *line = text; line < end;) {
    const char *line_end = memchr(line, '\n', (size_t)(end - line));
    if (!line_end) line_end = end;
    const char *at = line;
    if (!listing && at < line_end && *at != ' ' && *at != '-' && *at != '#') {
      /* A top-level key starts a new block. */
      exporting = !strncmp(at, "exports:", 8) || !strncmp(at, "reexports:", 10);
      if (!strncmp(at, "install-name:", 13) && !dylib) {
        const char *name = at + 13;
        while (name < line_end && (*name == ' ' || *name == '\'' || *name == '"')) ++name;
        const char *name_end = line_end;
        while (name_end > name && (name_end[-1] == ' ' || name_end[-1] == '\'' || name_end[-1] == '"' || name_end[-1] == '\r')) --name_end;
        char *install = keep_string(linker, name, (size_t)(name_end - name));
        if (!install || !(dylib = add_dylib(linker, install, false))) return fail(linker, "out of memory%s%s", "", "");
      }
    }
    if (!listing && exporting) {
      const char *key = NULL;
      for (const char *k = at; k + 8 <= line_end; ++k)
        if (!strncmp(k, "symbols:", 8) && (k == at || k[-1] == ' ' || k[-1] == '-' || k[-1] == '{' || k[-1] == ',')) { key = k; break; }
      if (key) {
        const char *open = memchr(key, '[', (size_t)(line_end - key));
        if (open) { listing = true; at = open + 1; }
      }
    }
    if (listing) {
      if (!dylib) return fail(linker, "'%s' lists symbols before its install-name%s", path, "");
      while (at < line_end) {
        while (at < line_end && (*at == ' ' || *at == ',' || *at == '\'' || *at == '"' || *at == '\r')) ++at;
        if (at < line_end && *at == ']') { listing = false; break; }
        const char *start = at;
        while (at < line_end && *at != ',' && *at != ']' && *at != ' ' && *at != '\'' && *at != '"' && *at != '\r') ++at;
        if (at > start) {
          char *symbol = keep_string(linker, start, (size_t)(at - start));
          if (!symbol || !export_symbol(linker, dylib, symbol)) return fail(linker, "out of memory%s%s", "", "");
        }
      }
    }
    line = line_end + 1;
  }
  return dylib ? true : fail(linker, "'%s' has no install-name%s", path, "");
}
static bool load_input(MLinker *linker, const char *path) {
  if (path[0] == '-' && path[1] == 'l') {
    /* No symbol list: unresolved names bind to this library. */
    char install[4096];
    const char *name = path + 2;
    if (!strcmp(name, "System")) snprintf(install, sizeof(install), "/usr/lib/libSystem.B.dylib");
    else snprintf(install, sizeof(install), "/usr/lib/lib%s.dylib", name);
    char *copy = keep_string(linker, install, strlen(install));
    return copy && add_dylib(linker, copy, true) ? true : fail(linker, "out of memory%s%s", "", "");
  }
  size_t size = 0;
  uint8_t *data = read_file(linker, path, &size);
  if (!data) return false;
  if (size >= 8 && !memcmp(data, "!<arch>\n", 8)) return load_archive(linker, path, data, size);
  if (size >= 32 && read32(data) == MH_MAGIC_64) {
    uint32_t type = read32(data + 12);
    if (type == MH_OBJECT) return load_object(linker, path, data, size);
    if (type == MH_DYLIB) return load_dylib(linker, path, data, size);
  }
  if (size >= 4 && (!memcmp(data, "---", 3) || strstr((const char *)data, "tbd-version"))) return load_tbd(linker, path, (const char *)data, size);
  return fail(linker, "'%s' is not a Mach-O object, archive, dylib or .tbd stub%s", path, "");
}

/* Output sections, in segment order: __TEXT, __DATA_CONST, __DATA. */
static bool dropped(const MSection *section) {
  if (section->flags & S_ATTR_DEBUG) return true;
  if (!strcmp(section->segment, "__DWARF") || !strcmp(section->segment, "__LD") || !strcmp(section->segment, "__LLVM")) return true;
  if (!strcmp(section->name, "__eh_frame") || !strcmp(section->name, "__compact_unwind") ||
      !strcmp(section->name, "__llvm_addrsig"))
    return true;
  return false;
}
static int output_for(MLinker *linker, const char *segment, const char *name, uint32_t flags) {
  for (size_t i = 0; i < linker->output_count; ++i)
    if (!strcmp(linker->outputs[i].segment, segment) && !strcmp(linker->outputs[i].name, name)) return (int)i;
  if (!grow((void **)&linker->outputs, &linker->output_capacity, linker->output_count, sizeof(*linker->outputs))) return -1;
  MOutput *output = &linker->outputs[linker->output_count];
  memset(output, 0, sizeof(*output));
  snprintf(output->segment, sizeof(output->segment), "%s", segment);
  snprintf(output->name, sizeof(output->name), "%s", name);
  output->flags = flags;
  output->align = 1;
  return (int)linker->output_count++;
}
static bool add_section(MLinker *linker, int index, MSection *section) {
  MOutput *output = &linker->outputs[index];
  if (!grow((void **)&output->sections, &output->capacity, output->count, sizeof(*output->sections)))
    return fail(linker, "out of memory%s%s", "", "");
  output->sections[output->count++] = section;
  if (section->align > output->align) output->align = section->align;
  section->output = index;
  return true;
}
static MSection *synthetic(MLinker *linker, const char *segment, const char *name, uint32_t flags, uint64_t size, uint64_t align) {
  MSection *section = calloc(1, sizeof(*section));
  if (!section || !grow((void **)&linker->extra_sections, &linker->extra_capacity, linker->extra_count, sizeof(*linker->extra_sections))) {
    free(section);
    return NULL;
  }
  linker->extra_sections[linker->extra_count++] = section;
  snprintf(section->segment, sizeof(section->segment), "%s", segment);
  snprintf(section->name, sizeof(section->name), "%s", name);
  section->flags = flags;
  section->size = size;
  section->align = align;
  section->output = -1;
  return section;
}
static bool zerofill(const MSection *section) {
  return (section->flags & 0xff) == S_ZEROFILL || (section->flags & 0xff) == S_GB_ZEROFILL;
}
static bool assign_outputs(MLinker *linker) {
  /* Fixed outputs first so the segment order is stable. */
  linker->text_output = output_for(linker, "__TEXT", "__text", S_ATTR_PURE_INSTRUCTIONS | S_ATTR_SOME_INSTRUCTIONS);
  linker->stubs_output = output_for(linker, "__TEXT", "__stubs", S_SYMBOL_STUBS | S_ATTR_PURE_INSTRUCTIONS | S_ATTR_SOME_INSTRUCTIONS);
  linker->got_output = output_for(linker, "__DATA_CONST", "__got", S_NON_LAZY_SYMBOL_POINTERS);
  if (linker->text_output < 0 || linker->stubs_output < 0 || linker->got_output < 0) return fail(linker, "out of memory%s%s", "", "");
  for (int pass = 0; pass < 3; ++pass) {
    for (size_t o = 0; o < linker->object_count; ++o) {
      MObject *object = linker->objects[o];
      for (size_t s = 0; s < object->section_count; ++s) {
        MSection *section = &object->sections[s];
        if (dropped(section)) continue;
        bool text = !strcmp(section->segment, "__TEXT");
        int wanted = text ? 0 : zerofill(section) ? 2 : 1;
        if (wanted != pass) continue;
        const char *segment = text ? "__TEXT" : "__DATA";
        int index = output_for(linker, segment, section->name, section->flags);
        if (index < 0 || !add_section(linker, index, section)) return fail(linker, "out of memory%s%s", "", "");
      }
    }
    if (pass == 2) {
      for (size_t i = 0; i < linker->table_capacity; ++i) {
        MSymbol *symbol = linker->table[i];
        if (!symbol || !symbol->common) continue;
        MSection *section = synthetic(linker, "__DATA", "__common", S_ZEROFILL, symbol->common_size,
                                      symbol->common_align ? symbol->common_align : 1);
        int index = output_for(linker, "__DATA", "__common", S_ZEROFILL);
        if (!section || index < 0 || !add_section(linker, index, section)) return fail(linker, "out of memory%s%s", "", "");
        symbol->common = false;
        symbol->section = section;
        symbol->value = 0;
      }
    }
  }
  return true;
}

static MSymbol *reloc_symbol(MObject *object, uint32_t index) {
  return index < object->symbol_count + object->section_count ? object->symbols[index] ? object->symbols[index]
                                                                                       : &object->locals[index]
                                                              : NULL;
}
static bool imported(const MSymbol *symbol) { return !symbol->defined && symbol->dylib; }
static bool add_slot(MLinker *linker, MSymbol ***list, size_t *count, size_t *capacity, MSymbol *symbol, uint32_t *slot) {
  if (*slot) return true;
  if (!grow((void **)list, capacity, *count, sizeof(**list))) return fail(linker, "out of memory%s%s", "", "");
  (*list)[(*count)++] = symbol;
  *slot = (uint32_t)*count;
  return true;
}
static bool add_fixup(MLinker *linker, MSection *section, uint64_t offset, MSymbol *symbol, int64_t addend, bool bind) {
  if (!grow((void **)&linker->fixups, &linker->fixup_capacity, linker->fixup_count, sizeof(*linker->fixups)))
    return fail(linker, "out of memory%s%s", "", "");
  linker->fixups[linker->fixup_count].section = section;
  linker->fixups[linker->fixup_count].offset = offset;
  linker->fixups[linker->fixup_count].symbol = symbol;
  linker->fixups[linker->fixup_count].addend = addend;
  linker->fixups[linker->fixup_count].bind = bind;
  ++linker->fixup_count;
  return true;
}
/* Imports, GOT slots, stubs, and the pointers dyld must rebase or bind. */
static bool plan(MLinker *linker) {
  MDylib *fallback = NULL;
  for (size_t i = 0; i < linker->dylib_count && !fallback; ++i)
    if (linker->dylibs[i]->fallback) fallback = linker->dylibs[i];
  for (size_t o = 0; o < linker->object_count; ++o) {
    MObject *object = linker->objects[o];
    for (size_t s = 0; s < object->section_count; ++s) {
      MSection *section = &object->sections[s];
      if (section->output < 0) continue;
      for (size_t r = 0; r < section->reloc_count; ++r) {
        MReloc *reloc = &section->relocs[r];
        MSymbol *symbol = reloc_symbol(object, reloc->symbol);
        if (!symbol) return fail(linker, "'%s' has a relocation to a missing symbol%s", object->path, "");
        if (!symbol->defined && !symbol->dylib && symbol->strong_reference) {
          if (!fallback) return fail(linker, "undefined symbol '%s' (referenced from %s)", symbol->name, object->path);
          symbol->dylib = fallback;
        }
        if (symbol->dylib && !symbol->defined && !symbol->dylib->ordinal) {
          uint32_t used = 0;
          for (size_t d = 0; d < linker->dylib_count; ++d) used += linker->dylibs[d]->ordinal != 0;
          symbol->dylib->ordinal = used + 1;
        }
        unsigned planned_type = reloc->type;
        if (linker->cpu == CPU_X86_64) {
          if (reloc->type == 3 || reloc->type == 4) planned_type = ARM64_RELOC_GOT_LOAD_PAGE21;
          else if (reloc->type == 2) planned_type = ARM64_RELOC_BRANCH26;
          else if (reloc->type) planned_type = 255;
        }
        switch (planned_type) {
        case ARM64_RELOC_GOT_LOAD_PAGE21: case ARM64_RELOC_GOT_LOAD_PAGEOFF12: case ARM64_RELOC_POINTER_TO_GOT:
          if (!add_slot(linker, &linker->got_symbols, &linker->got_count, &linker->got_capacity, symbol, &symbol->got)) return false;
          break;
        case ARM64_RELOC_BRANCH26:
          if (imported(symbol) &&
              !add_slot(linker, &linker->stub_symbols, &linker->stub_count, &linker->stub_capacity, symbol, &symbol->stub))
            return false;
          break;
        case ARM64_RELOC_UNSIGNED:
          if ((reloc->length & 3) != 3 || reloc->has_subtrahend) break;
          if (!strcmp(linker->outputs[section->output].segment, "__TEXT"))
            return fail(linker, "'%s' stores an absolute address in read-only '%s'; recompile as position-independent",
                        object->path, section->name);
          if (imported(symbol)) {
            if (!add_fixup(linker, section, reloc->offset, symbol, reloc->addend, true)) return false;
          } else if (symbol->defined && !symbol->absolute) {
            if (!add_fixup(linker, section, reloc->offset, symbol, 0, false)) return false;
          }
          break;
        default:
          if (imported(symbol)) return fail(linker, "'%s' refers to imported '%s' directly; it must go through the GOT", object->path, symbol->name);
          break;
        }
      }
    }
  }
  /* Stubs load through their own GOT slot. */
  for (size_t i = 0; i < linker->stub_count; ++i) {
    MSymbol *symbol = linker->stub_symbols[i];
    if (!add_slot(linker, &linker->got_symbols, &linker->got_count, &linker->got_capacity, symbol, &symbol->got)) return false;
  }
  MSection *stubs = synthetic(linker, "__TEXT", "__stubs", S_SYMBOL_STUBS, linker->stub_count * STUB_SIZE, 4);
  MSection *got = synthetic(linker, "__DATA_CONST", "__got", S_NON_LAZY_SYMBOL_POINTERS, linker->got_count * 8, 8);
  if (!stubs || !got || (linker->stub_count && !add_section(linker, linker->stubs_output, stubs)) ||
      (linker->got_count && !add_section(linker, linker->got_output, got)))
    return fail(linker, "out of memory%s%s", "", "");
  for (size_t i = 0; i < linker->got_count; ++i) {
    MSymbol *symbol = linker->got_symbols[i];
    if (imported(symbol) || (!symbol->defined && symbol->dylib)) {
      if (!add_fixup(linker, got, i * 8, symbol, 0, true)) return false;
    } else if (symbol->defined && !symbol->absolute) {
      if (!add_fixup(linker, got, i * 8, symbol, 0, false)) return false;
    }
  }
  return true;
}

/* Layout and addresses. */
static uint64_t symbol_address(const MSymbol *symbol, uint64_t stubs) {
  if (!symbol->defined) return symbol->stub ? stubs + (uint64_t)(symbol->stub - 1) * STUB_SIZE : 0;
  if (symbol->absolute || !symbol->section) return symbol->value;
  return symbol->section->address + symbol->value;
}
typedef struct {
  const char *name;
  uint64_t address, file_offset, vm_size, file_size;
  uint32_t protection;
  int first, last; /* Output range, inclusive; -1 when none. */
} MSegment;
static void place_outputs(MLinker *linker, MSegment *segment, uint64_t *address, uint64_t *offset, const char *name,
                          bool zero_pass) {
  for (size_t i = 0; i < linker->output_count; ++i) {
    MOutput *output = &linker->outputs[i];
    if (strcmp(output->segment, name) || !output->count) continue;
    bool zero = (output->flags & 0xff) == S_ZEROFILL || (output->flags & 0xff) == S_GB_ZEROFILL;
    if (zero != zero_pass) continue;
    *address = align_up(*address, output->align);
    if (!zero) *offset = align_up(*offset, output->align);
    output->address = *address;
    output->file_offset = zero ? 0 : *offset;
    uint64_t size = 0;
    for (size_t s = 0; s < output->count; ++s) {
      MSection *section = output->sections[s];
      size = align_up(size, section->align);
      section->offset = size;
      section->address = output->address + size;
      size += section->size;
    }
    output->size = size;
    *address += size;
    if (!zero) *offset += size;
    if (segment->first < 0) segment->first = (int)i;
    segment->last = (int)i;
  }
}

/* Export trie: a radix tree over the exported names. */
typedef struct {
  const char **names;
  uint64_t *addresses;
  size_t count;
} Exports;
typedef struct TrieNode {
  bool terminal;
  uint64_t address;
  struct TrieNode **children;
  char **labels;
  size_t child_count;
  uint64_t offset;
} TrieNode;
static void trie_free(TrieNode *node) {
  if (!node) return;
  for (size_t i = 0; i < node->child_count; ++i) { trie_free(node->children[i]); free(node->labels[i]); }
  free(node->children);
  free(node->labels);
  free(node);
}
static TrieNode *trie_build(const Exports *exports, size_t first, size_t last, size_t depth) {
  TrieNode *node = calloc(1, sizeof(*node));
  if (!node) return NULL;
  size_t i = first;
  if (i < last && strlen(exports->names[i]) == depth) { node->terminal = true; node->address = exports->addresses[i]; ++i; }
  while (i < last) {
    size_t j = i + 1;
    char c = exports->names[i][depth];
    while (j < last && exports->names[j][depth] == c) ++j;
    size_t common = strlen(exports->names[i]);
    for (size_t k = i + 1; k < j; ++k) {
      size_t n = depth;
      while (n < common && exports->names[k][n] == exports->names[i][n]) ++n;
      common = n;
    }
    TrieNode **children = realloc(node->children, (node->child_count + 1) * sizeof(*children));
    char **labels = realloc(node->labels, (node->child_count + 1) * sizeof(*labels));
    if (children) node->children = children;
    if (labels) node->labels = labels;
    char *label = malloc(common - depth + 1);
    TrieNode *child = children && labels && label ? trie_build(exports, i, j, common) : NULL;
    if (!child) { free(label); trie_free(node); return NULL; }
    memcpy(label, exports->names[i] + depth, common - depth);
    label[common - depth] = 0;
    node->children[node->child_count] = child;
    node->labels[node->child_count++] = label;
    i = j;
  }
  return node;
}
static size_t trie_node_size(const TrieNode *node) {
  size_t info = node->terminal ? 1 + uleb_size(node->address) : 0;
  size_t size = uleb_size(info) + info + 1;
  for (size_t i = 0; i < node->child_count; ++i) size += strlen(node->labels[i]) + 1 + uleb_size(node->children[i]->offset);
  return size;
}
static bool trie_offsets(TrieNode *node, uint64_t *offset) {
  bool changed = node->offset != *offset;
  node->offset = *offset;
  *offset += trie_node_size(node);
  for (size_t i = 0; i < node->child_count; ++i) changed |= trie_offsets(node->children[i], offset);
  return changed;
}
static bool trie_write(const TrieNode *node, MBytes *out) {
  size_t info = node->terminal ? 1 + uleb_size(node->address) : 0;
  if (!bytes_uleb(out, info)) return false;
  if (node->terminal && (!bytes_uleb(out, 0) || !bytes_uleb(out, node->address))) return false;
  if (!bytes_byte(out, (uint8_t)node->child_count)) return false;
  for (size_t i = 0; i < node->child_count; ++i)
    if (!bytes_append(out, node->labels[i], strlen(node->labels[i]) + 1) || !bytes_uleb(out, node->children[i]->offset))
      return false;
  for (size_t i = 0; i < node->child_count; ++i)
    if (!trie_write(node->children[i], out)) return false;
  return true;
}
static int compare_names(const void *a, const void *b) {
  return strcmp((*(const MSymbol *const *)a)->name, (*(const MSymbol *const *)b)->name);
}

/* Instruction fields. */
static bool fits(int64_t value, int bits) { return value >= -((int64_t)1 << (bits - 1)) && value < ((int64_t)1 << (bits - 1)); }
static void set_adrp(uint8_t *at, int64_t pages) {
  uint32_t insn = read32(at) & ~((3u << 29) | (0x7ffffu << 5));
  write32(at, insn | (uint32_t)(pages & 3) << 29 | (uint32_t)((pages >> 2) & 0x7ffff) << 5);
}
static void set_lo12(uint8_t *at, uint64_t target) {
  uint32_t insn = read32(at);
  uint32_t scale = 0;
  if ((insn & 0x3b000000u) == 0x39000000u) {
    scale = insn >> 30;
    if (scale == 0 && (insn & 0x04800000u) == 0x04800000u) scale = 4;
  }
  write32(at, (insn & ~(0xfffu << 10)) | (uint32_t)(((target & 0xfff) >> scale) & 0xfff) << 10);
}
static bool relocate(MLinker *linker, MSection *section, uint8_t *out, uint64_t stubs, uint64_t got) {
  MObject *object = section->object;
  for (size_t r = 0; r < section->reloc_count; ++r) {
    MReloc *reloc = &section->relocs[r];
    MSymbol *symbol = reloc_symbol(object, reloc->symbol);
    uint8_t *at = out + reloc->offset;
    uint64_t place = section->address + reloc->offset;
    unsigned length = reloc->length & 3;
    bool contents = (reloc->length & 0x80) != 0;
    if (reloc->offset + (length == 3 ? 8u : 4u) > section->size)
      return fail(linker, "relocation outside its section in '%s'%s", object->path, "");
    uint64_t target = symbol_address(symbol, stubs) + (uint64_t)reloc->addend;
    uint64_t slot = symbol->got ? got + (uint64_t)(symbol->got - 1) * 8 : 0;
    if (linker->cpu == CPU_X86_64 && reloc->type) {
      if (length != 2 || !reloc->pcrel || reloc->type > 8 || reloc->type == 5)
        return fail(linker, "unsupported x86-64 relocation in '%s'%s", object->path, "");
      /* External SIGNED_1/2/4 contents already include the trailing immediate
         bias. Section-relative addends above were normalized to the target
         address, so only those need the bias restored here. */
      int64_t extra = contents && reloc->type >= 6 ? (int64_t)1 << (reloc->type-6) : 0;
      int64_t delta = (int64_t)((reloc->type==3 || reloc->type==4 ? slot : target)-place-4-extra);
      if (!contents) delta += (int32_t)read32(at);
      if (!fits(delta,32)) return fail(linker,"relocation to '%s' out of range in '%s'",symbol->name,object->path);
      write32(at,(uint32_t)delta);
      continue;
    }
    switch (reloc->type) {
    case ARM64_RELOC_UNSIGNED: {
      uint64_t value = target;
      if (!contents) value += length == 3 ? read64(at) : read32(at);
      if (reloc->has_subtrahend) {
        MSymbol *subtrahend = reloc_symbol(object, reloc->subtrahend);
        value -= symbol_address(subtrahend, stubs);
      }
      if (imported(symbol) && !reloc->has_subtrahend) value = 0;
      if (length == 3) write64(at, value);
      else write32(at, (uint32_t)value);
      break;
    }
    case ARM64_RELOC_BRANCH26: {
      int64_t delta = (int64_t)(target - place);
      if (!fits(delta, 28)) return fail(linker, "branch to '%s' out of range in '%s'", symbol->name, object->path);
      write32(at, (read32(at) & 0xfc000000u) | (uint32_t)((delta >> 2) & 0x3ffffff));
      break;
    }
    case ARM64_RELOC_PAGE21: set_adrp(at, (int64_t)((target & ~0xfffull) - (place & ~0xfffull)) >> 12); break;
    case ARM64_RELOC_PAGEOFF12: set_lo12(at, target); break;
    case ARM64_RELOC_GOT_LOAD_PAGE21: set_adrp(at, (int64_t)((slot & ~0xfffull) - (place & ~0xfffull)) >> 12); break;
    case ARM64_RELOC_GOT_LOAD_PAGEOFF12: set_lo12(at, slot); break;
    case ARM64_RELOC_POINTER_TO_GOT: write32(at, (uint32_t)(slot - place)); break;
    default: {
      char type[16];
      snprintf(type, sizeof(type), "%u", reloc->type);
      return fail(linker, "unsupported relocation type %s in '%s'", type, object->path);
    }
    }
  }
  return true;
}

static void segment_command(MBytes *commands, MLinker *linker, const MSegment *segment) {
  uint32_t sections = 0;
  for (int i = segment->first; segment->first >= 0 && i <= segment->last; ++i)
    sections += linker->outputs[i].count != 0 && !strcmp(linker->outputs[i].segment, segment->name);
  uint8_t h[72] = {0};
  write32(h, LC_SEGMENT_64);
  write32(h + 4, 72 + 80 * sections);
  snprintf((char *)h + 8, 16, "%s", segment->name);
  write64(h + 24, segment->address);
  write64(h + 32, segment->vm_size);
  write64(h + 40, segment->file_offset);
  write64(h + 48, segment->file_size);
  write32(h + 56, segment->protection);
  write32(h + 60, segment->protection);
  write32(h + 64, sections);
  write32(h + 68, !strcmp(segment->name, "__DATA_CONST") ? 0x10 : 0); /* SG_READ_ONLY */
  bytes_append(commands, h, 72);
  for (int i = segment->first; segment->first >= 0 && i <= segment->last; ++i) {
    MOutput *output = &linker->outputs[i];
    if (!output->count || strcmp(output->segment, segment->name)) continue;
    uint8_t s[80] = {0};
    memcpy(s, output->name, strlen(output->name));
    memcpy(s + 16, output->segment, strlen(output->segment));
    write64(s + 32, output->address);
    write64(s + 40, output->size);
    write32(s + 48, (uint32_t)output->file_offset);
    uint32_t align = 0;
    while (((uint64_t)1 << align) < output->align) ++align;
    write32(s + 52, align);
    write32(s + 64, output->flags);
    write32(s + 68, output->reserved1);
    write32(s + 72, output->reserved2);
    bytes_append(commands, s, 80);
  }
}
static void dylib_command(MBytes *commands, uint32_t command, const char *name) {
  size_t size = align_up(24 + strlen(name) + 1, 8);
  uint8_t h[24] = {0};
  write32(h, command);
  write32(h + 4, (uint32_t)size);
  write32(h + 8, 24);
  write32(h + 12, 2);
  write32(h + 16, 0x10000);
  write32(h + 20, 0x10000);
  bytes_append(commands, h, 24);
  bytes_append(commands, name, strlen(name) + 1);
  uint8_t zero[8] = {0};
  bytes_append(commands, zero, size - 24 - strlen(name) - 1);
}

static bool write_output(MLinker *linker, const char *entry_name, const char *install_name) {
  bool executable = !linker->shared;
  MOutput *stubs_output = &linker->outputs[linker->stubs_output];
  MOutput *got_output = &linker->outputs[linker->got_output];
  stubs_output->reserved2 = STUB_SIZE;
  /* Load command sizes depend only on counts, so measure them first. */
  size_t used_dylibs = 0;
  for (size_t i = 0; i < linker->dylib_count; ++i) used_dylibs += linker->dylibs[i]->ordinal != 0;
  MSegment segments[5] = {
    {"__PAGEZERO", 0, 0, executable ? TEXT_BASE : 0, 0, 0, -1, -1},
    {"__TEXT", 0, 0, 0, 0, 5, -1, -1},
    {"__DATA_CONST", 0, 0, 0, 0, 3, -1, -1},
    {"__DATA", 0, 0, 0, 0, 3, -1, -1},
    {"__LINKEDIT", 0, 0, 0, 0, 1, -1, -1},
  };
  /* Emitted segments: __PAGEZERO for executables, __TEXT, __DATA_CONST and
     __DATA when they hold sections, and __LINKEDIT. */
  bool emitted[5] = {executable, true, false, false, true};
  size_t commands_size = 0;
  for (size_t i = 0; i < linker->output_count; ++i) {
    MOutput *output = &linker->outputs[i];
    if (!output->count) continue;
    commands_size += 80;
    if (!strcmp(output->segment, "__DATA_CONST")) emitted[2] = true;
    if (!strcmp(output->segment, "__DATA")) emitted[3] = true;
  }
  int segment_index[5];
  int emitted_count = 0;
  for (int s = 0; s < 5; ++s) {
    segment_index[s] = emitted[s] ? emitted_count++ : -1;
    if (emitted[s]) commands_size += 72;
  }
  commands_size += 48 + 24 + 80 + 24 + 24 + 16; /* dyld info, symtab, dysymtab, uuid, build version, code signature */
  if (executable) commands_size += 24 + 32; /* main, dylinker */
  else commands_size += align_up(24 + strlen(install_name) + 1, 8);
  for (size_t i = 0; i < linker->dylib_count; ++i)
    if (linker->dylibs[i]->ordinal) commands_size += align_up(24 + strlen(linker->dylibs[i]->install_name) + 1, 8);
  uint64_t base = executable ? TEXT_BASE : 0;
  uint64_t offset = 32 + commands_size, address = base + offset;
  segments[1].address = base;
  place_outputs(linker, &segments[1], &address, &offset, "__TEXT", false);
  segments[1].file_size = segments[1].vm_size = align_up(offset, PAGE);
  for (int s = 2; s <= 3; ++s) {
    offset = segments[s - 1].file_offset + segments[s - 1].file_size;
    address = segments[s - 1].address + segments[s - 1].vm_size;
    segments[s].file_offset = offset;
    segments[s].address = address;
    place_outputs(linker, &segments[s], &address, &offset, segments[s].name, false);
    uint64_t file_end = offset;
    place_outputs(linker, &segments[s], &address, &offset, segments[s].name, true);
    segments[s].file_size = align_up(file_end - segments[s].file_offset, PAGE);
    segments[s].vm_size = align_up(address - segments[s].address, PAGE);
  }
  uint64_t stubs = linker->outputs[linker->stubs_output].address;
  uint64_t got = linker->outputs[linker->got_output].address;
  /* Indirect symbol table: stubs, then GOT slots. */
  stubs_output->reserved1 = 0;
  got_output->reserved1 = (uint32_t)linker->stub_count;
  /* Output section ordinals, as nlist n_sect counts them. */
  uint32_t ordinal = 0;
  for (int s = 1; s <= 3; ++s)
    for (int i = segments[s].first; segments[s].first >= 0 && i <= segments[s].last; ++i)
      if (linker->outputs[i].count && !strcmp(linker->outputs[i].segment, segments[s].name))
        linker->outputs[i].ordinal = ++ordinal;
  if (executable) {
    MSymbol *header = symbol_find(linker, "__mh_execute_header");
    if (header && !header->defined) { header->defined = header->absolute = true; header->value = base; }
  }
  MSymbol *dso = symbol_find(linker, "___dso_handle");
  if (dso && !dso->defined) { dso->defined = dso->absolute = true; dso->value = base; }

  /* Symbol table: locals, exported definitions, then imports. */
  MSymbol **locals = NULL, **exports = NULL, **imports = NULL;
  size_t local_count = 0, export_count = 0, import_count = 0, local_capacity = 0, export_capacity = 0, import_capacity = 0;
  bool ok = true;
  for (size_t o = 0; ok && o < linker->object_count; ++o) {
    MObject *object = linker->objects[o];
    for (size_t i = 0; ok && i < object->symbol_count; ++i) {
      MSymbol *symbol = object->symbols[i];
      if (!symbol || !symbol->local || !symbol->defined || !symbol->name[0] || symbol->name[0] == 'l' ||
          symbol->name[0] == 'L' || (symbol->section && symbol->section->output < 0))
        continue;
      ok = grow((void **)&locals, &local_capacity, local_count, sizeof(*locals));
      if (ok) locals[local_count++] = symbol;
    }
  }
  for (size_t i = 0; ok && i < linker->table_capacity; ++i) {
    MSymbol *symbol = linker->table[i];
    if (!symbol) continue;
    if (symbol->defined && (!symbol->section || symbol->section->output >= 0)) {
      if (symbol->private_extern) {
        ok = grow((void **)&locals, &local_capacity, local_count, sizeof(*locals));
        if (ok) locals[local_count++] = symbol;
      } else {
        ok = grow((void **)&exports, &export_capacity, export_count, sizeof(*exports));
        if (ok) exports[export_count++] = symbol;
      }
    } else if (imported(symbol) && (symbol->got || symbol->stub || symbol->referenced)) {
      ok = grow((void **)&imports, &import_capacity, import_count, sizeof(*imports));
      if (ok) imports[import_count++] = symbol;
    }
  }
  if (export_count) qsort(exports, export_count, sizeof(*exports), compare_names);
  if (import_count) qsort(imports, import_count, sizeof(*imports), compare_names);
  MBytes symtab = {0}, strtab = {0}, indirect = {0}, rebase = {0}, bind = {0}, trie = {0};
  ok = ok && bytes_append(&strtab, " ", 2);
  MSymbol **groups[3] = {locals, exports, imports};
  size_t counts[3] = {local_count, export_count, import_count};
  for (int g = 0; ok && g < 3; ++g) {
    for (size_t i = 0; ok && i < counts[g]; ++i) {
      MSymbol *symbol = groups[g][i];
      uint8_t entry[16] = {0};
      write32(entry, (uint32_t)strtab.size);
      uint8_t type = g == 2 ? N_UNDF : (symbol->absolute || !symbol->section) ? N_ABS : N_SECT;
      if (g == 1) type |= N_EXT;
      if (g == 2) type |= N_EXT;
      if (g == 0 && !symbol->local) type |= N_EXT | N_PEXT;
      entry[4] = type;
      entry[5] = (uint8_t)((type & N_TYPE) == N_SECT ? linker->outputs[symbol->section->output].ordinal : 0);
      uint16_t desc = 0;
      if (g == 2) desc = (uint16_t)(symbol->dylib->ordinal << 8) | (symbol->strong_reference ? 0 : N_WEAK_REF);
      if (g == 1 && symbol->weak_definition) desc |= N_WEAK_DEF;
      if (g == 1 && !strcmp(symbol->name, "__mh_execute_header")) desc |= REFERENCED_DYNAMICALLY;
      write32(entry + 4, (uint32_t)entry[4] | (uint32_t)entry[5] << 8 | (uint32_t)desc << 16);
      write64(entry + 8, g == 2 ? 0 : symbol_address(symbol, stubs));
      symbol->symtab = (uint32_t)(symtab.size / 16) + 1;
      ok = bytes_append(&symtab, entry, 16) && bytes_append(&strtab, symbol->name, strlen(symbol->name) + 1);
    }
  }
  for (size_t i = 0; ok && i < linker->stub_count; ++i) {
    uint8_t entry[4];
    write32(entry, linker->stub_symbols[i]->symtab - 1);
    ok = bytes_append(&indirect, entry, 4);
  }
  for (size_t i = 0; ok && i < linker->got_count; ++i) {
    MSymbol *symbol = linker->got_symbols[i];
    uint8_t entry[4];
    write32(entry, imported(symbol) ? symbol->symtab - 1 : INDIRECT_SYMBOL_LOCAL);
    ok = bytes_append(&indirect, entry, 4);
  }
  /* Rebase and bind opcodes: one entry per pointer, segment-relative. */
  ok = ok && bytes_byte(&rebase, 0x10 | REBASE_TYPE_POINTER);
  ok = ok && bytes_byte(&bind, 0x50 | BIND_TYPE_POINTER);
  for (size_t i = 0; ok && i < linker->fixup_count; ++i) {
    MSection *section = linker->fixups[i].section;
    uint64_t at = section->address + linker->fixups[i].offset;
    int s = 2;
    if (!(emitted[2] && at >= segments[2].address && at < segments[2].address + segments[2].vm_size)) s = 3;
    uint64_t segment_offset = at - segments[s].address;
    if (!linker->fixups[i].bind) {
      ok = bytes_byte(&rebase, (uint8_t)(0x20 | segment_index[s])) && bytes_uleb(&rebase, segment_offset) &&
           bytes_byte(&rebase, 0x51);
      continue;
    }
    MSymbol *symbol = linker->fixups[i].symbol;
    uint8_t ordinal_byte = symbol->dylib->ordinal <= 15 ? (uint8_t)(0x10 | symbol->dylib->ordinal) : 0x20;
    ok = bytes_byte(&bind, ordinal_byte) && (symbol->dylib->ordinal <= 15 || bytes_uleb(&bind, symbol->dylib->ordinal)) &&
         bytes_byte(&bind, (uint8_t)(0x40 | (symbol->strong_reference ? 0 : BIND_SYMBOL_FLAGS_WEAK_IMPORT))) &&
         bytes_append(&bind, symbol->name, strlen(symbol->name) + 1) &&
         bytes_byte(&bind, 0x60) && bytes_sleb(&bind, linker->fixups[i].addend) &&
         bytes_byte(&bind, (uint8_t)(0x70 | segment_index[s])) && bytes_uleb(&bind, segment_offset) &&
         bytes_byte(&bind, 0x90);
  }
  ok = ok && bytes_byte(&rebase, 0) && bytes_byte(&bind, 0);
  /* Exports, relative to the image base. */
  if (ok && export_count) {
    Exports list = {calloc(export_count, sizeof(char *)), calloc(export_count, sizeof(uint64_t)), export_count};
    ok = list.names && list.addresses;
    for (size_t i = 0; ok && i < export_count; ++i) {
      list.names[i] = exports[i]->name;
      list.addresses[i] = symbol_address(exports[i], stubs) - base;
    }
    TrieNode *root = ok ? trie_build(&list, 0, export_count, 0) : NULL;
    ok = root != NULL;
    for (int round = 0; ok && round < 64; ++round) {
      uint64_t at = 0;
      if (!trie_offsets(root, &at)) break;
    }
    ok = ok && trie_write(root, &trie);
    trie_free(root);
    free(list.names);
    free(list.addresses);
  }
  while (ok && rebase.size % 8) ok = bytes_byte(&rebase, 0);
  while (ok && bind.size % 8) ok = bytes_byte(&bind, 0);
  while (ok && trie.size % 8) ok = bytes_byte(&trie, 0);
  while (ok && strtab.size % 8) ok = bytes_byte(&strtab, 0);
  /* __LINKEDIT: rebase, bind, exports, symbols, indirect symbols, strings,
     then the code signature. */
  segments[4].file_offset = segments[3].file_offset + segments[3].file_size;
  segments[4].address = segments[3].address + segments[3].vm_size;
  uint64_t rebase_offset = segments[4].file_offset, bind_offset = rebase_offset + rebase.size;
  uint64_t trie_offset = bind_offset + bind.size, symtab_offset = trie_offset + trie.size;
  uint64_t indirect_offset = symtab_offset + symtab.size, strtab_offset = indirect_offset + indirect.size;
  uint64_t signature_offset = align_up(strtab_offset + strtab.size, 16);
  const char *slash = strrchr(linker->output_path, '/');
  char identifier[256];
  snprintf(identifier, sizeof(identifier), "%s", slash ? slash + 1 : linker->output_path);
  size_t identifier_length = strlen(identifier);
  if (identifier_length > 4 && !strcmp(identifier + identifier_length - 4, ".tmp")) identifier[identifier_length -= 4] = 0;
  uint64_t slots = (signature_offset + 4095) / 4096;
  uint64_t directory_size = 88 + identifier_length + 1 + slots * 32;
  uint64_t signature_size = 12 + 8 + directory_size;
  uint64_t file_size = signature_offset + signature_size;
  segments[4].file_size = file_size - segments[4].file_offset;
  segments[4].vm_size = align_up(segments[4].file_size, PAGE);

  /* Load commands. */
  MBytes commands = {0};
  for (int s = 0; ok && s < 5; ++s)
    if (emitted[s]) segment_command(&commands, linker, &segments[s]);
  uint8_t info[48] = {0};
  write32(info, LC_DYLD_INFO_ONLY);
  write32(info + 4, 48);
  write32(info + 8, (uint32_t)rebase_offset); write32(info + 12, (uint32_t)rebase.size);
  write32(info + 16, (uint32_t)bind_offset); write32(info + 20, (uint32_t)bind.size);
  write32(info + 40, (uint32_t)trie_offset); write32(info + 44, (uint32_t)trie.size);
  ok = ok && bytes_append(&commands, info, 48);
  uint8_t symtab_command[24];
  write32(symtab_command, LC_SYMTAB); write32(symtab_command + 4, 24);
  write32(symtab_command + 8, (uint32_t)symtab_offset); write32(symtab_command + 12, (uint32_t)(symtab.size / 16));
  write32(symtab_command + 16, (uint32_t)strtab_offset); write32(symtab_command + 20, (uint32_t)strtab.size);
  ok = ok && bytes_append(&commands, symtab_command, 24);
  uint8_t dysymtab[80] = {0};
  write32(dysymtab, LC_DYSYMTAB); write32(dysymtab + 4, 80);
  write32(dysymtab + 8, 0); write32(dysymtab + 12, (uint32_t)local_count);
  write32(dysymtab + 16, (uint32_t)local_count); write32(dysymtab + 20, (uint32_t)export_count);
  write32(dysymtab + 24, (uint32_t)(local_count + export_count)); write32(dysymtab + 28, (uint32_t)import_count);
  write32(dysymtab + 56, (uint32_t)indirect_offset); write32(dysymtab + 60, (uint32_t)(indirect.size / 4));
  ok = ok && bytes_append(&commands, dysymtab, 80);
  if (executable) {
    uint8_t dylinker[32] = {0};
    write32(dylinker, LC_LOAD_DYLINKER); write32(dylinker + 4, 32); write32(dylinker + 8, 12);
    memcpy(dylinker + 12, "/usr/lib/dyld", 13);
    ok = ok && bytes_append(&commands, dylinker, 32);
  } else {
    dylib_command(&commands, LC_ID_DYLIB, install_name);
  }
  uint8_t uuid[24] = {0};
  write32(uuid, LC_UUID); write32(uuid + 4, 24);
  size_t uuid_at = commands.size + 8;
  ok = ok && bytes_append(&commands, uuid, 24);
  uint8_t build[24] = {0};
  write32(build, LC_BUILD_VERSION); write32(build + 4, 24);
  write32(build + 8, 1); /* PLATFORM_MACOS */
  write32(build + 12, 0x000f0000); write32(build + 16, 0x000f0000);
  ok = ok && bytes_append(&commands, build, 24);
  if (executable) {
    MSymbol *entry = entry_name ? symbol_find(linker, entry_name) : NULL;
    if (!entry || !entry->defined) {
      ok = false;
      fail(linker, "entry symbol '%s' is undefined%s", entry_name ? entry_name : "", "");
    }
    uint8_t main_command[24] = {0};
    write32(main_command, LC_MAIN); write32(main_command + 4, 24);
    if (entry && entry->defined) write64(main_command + 8, symbol_address(entry, stubs) - base);
    ok = ok && bytes_append(&commands, main_command, 24);
  }
  for (uint32_t ordinal_index = 1; ok && ordinal_index <= used_dylibs; ++ordinal_index)
    for (size_t i = 0; i < linker->dylib_count; ++i)
      if (linker->dylibs[i]->ordinal == ordinal_index) dylib_command(&commands, LC_LOAD_DYLIB, linker->dylibs[i]->install_name);
  uint8_t signature_command[16];
  write32(signature_command, LC_CODE_SIGNATURE); write32(signature_command + 4, 16);
  write32(signature_command + 8, (uint32_t)signature_offset); write32(signature_command + 12, (uint32_t)signature_size);
  ok = ok && bytes_append(&commands, signature_command, 16);
  if (ok && commands.size != commands_size) ok = fail(linker, "internal error: load command size%s%s", "", "");

  uint8_t *image = ok ? calloc(1, file_size) : NULL;
  if (ok && !image) ok = fail(linker, "out of memory%s%s", "", "");
  if (ok) {
    uint32_t command_count = 0;
    for (size_t at = 0; at < commands.size; at += read32(commands.data + at + 4)) {
      if (!read32(commands.data + at + 4)) break;
      ++command_count;
    }
    write32(image, MH_MAGIC_64);
    write32(image + 4, linker->cpu);
    write32(image + 8, linker->cpu == CPU_X86_64 ? 3 : 0);
    write32(image + 12, executable ? MH_EXECUTE : MH_DYLIB);
    write32(image + 16, command_count);
    write32(image + 20, (uint32_t)commands_size);
    write32(image + 24, MH_NOUNDEFS | MH_DYLDLINK | MH_TWOLEVEL | (executable ? MH_PIE : MH_NO_REEXPORTED_DYLIBS));
    memcpy(image + 32, commands.data, commands.size);
    for (size_t i = 0; ok && i < linker->output_count; ++i) {
      MOutput *output = &linker->outputs[i];
      if (!output->file_offset || !output->count) continue;
      for (size_t s = 0; ok && s < output->count; ++s) {
        MSection *section = output->sections[s];
        uint8_t *at = image + output->file_offset + section->offset;
        if (section->data) memcpy(at, section->data, section->size);
        if (section->object) ok = relocate(linker, section, at, stubs, got);
      }
    }
    /* Stubs: adrp x16, slot@PAGE; ldr x16, [x16, slot@PAGEOFF]; br x16. */
    for (size_t i = 0; ok && i < linker->stub_count; ++i) {
      MSection *section = stubs_output->sections[0];
      uint8_t *at = image + stubs_output->file_offset + section->offset + i * STUB_SIZE;
      uint64_t place = section->address + i * STUB_SIZE;
      uint64_t slot = got + (uint64_t)(linker->stub_symbols[i]->got - 1) * 8;
      if (linker->cpu == CPU_X86_64) {
        at[0]=0xff; at[1]=0x25;
        if (!fits((int64_t)(slot-place-6),32)) { ok=false; break; }
        write32(at+2,(uint32_t)(slot-place-6));
        memset(at+6,0x90,STUB_SIZE-6);
        continue;
      }
      write32(at, 0x90000010u);
      set_adrp(at, (int64_t)((slot & ~0xfffull) - (place & ~0xfffull)) >> 12);
      write32(at + 4, 0xf9400210u | (uint32_t)((slot & 0xfff) >> 3) << 10);
      write32(at + 8, 0xd61f0200u);
    }
    /* Local GOT slots hold unslid addresses for dyld to rebase. */
    MSection *got_section = linker->got_count ? got_output->sections[0] : NULL;
    for (size_t i = 0; ok && got_section && i < linker->got_count; ++i)
      if (!imported(linker->got_symbols[i]))
        write64(image + got_output->file_offset + got_section->offset + i * 8, symbol_address(linker->got_symbols[i], stubs));
    memcpy(image + rebase_offset, rebase.data, rebase.size);
    memcpy(image + bind_offset, bind.data, bind.size);
    if (trie.size) memcpy(image + trie_offset, trie.data, trie.size);
    memcpy(image + symtab_offset, symtab.data, symtab.size);
    if (indirect.size) memcpy(image + indirect_offset, indirect.data, indirect.size);
    memcpy(image + strtab_offset, strtab.data, strtab.size);
    /* UUID from the contents, then the ad-hoc signature over everything
       before it: one SHA-256 per 4 KiB page. */
    uint8_t digest[32];
    sha256(image, (size_t)signature_offset, digest);
    digest[6] = (uint8_t)((digest[6] & 0x0f) | 0x30);
    digest[8] = (uint8_t)((digest[8] & 0x3f) | 0x80);
    memcpy(image + 32 + uuid_at, digest, 16);
    uint8_t *blob = image + signature_offset;
    write32be(blob, 0xfade0cc0);
    write32be(blob + 4, (uint32_t)signature_size);
    write32be(blob + 8, 1);
    write32be(blob + 12, 0);
    write32be(blob + 16, 20);
    uint8_t *directory = blob + 20;
    write32be(directory, 0xfade0c02);
    write32be(directory + 4, (uint32_t)directory_size);
    write32be(directory + 8, 0x20400);
    write32be(directory + 12, 0x20002); /* CS_ADHOC | CS_LINKER_SIGNED */
    write32be(directory + 16, (uint32_t)(88 + identifier_length + 1));
    write32be(directory + 20, 88);
    write32be(directory + 24, 0);
    write32be(directory + 28, (uint32_t)slots);
    write32be(directory + 32, (uint32_t)signature_offset);
    directory[36] = 32;
    directory[37] = 2; /* SHA-256 */
    directory[38] = 0;
    directory[39] = 12;
    write64be(directory + 64, segments[1].file_offset);
    write64be(directory + 72, segments[1].file_size);
    write64be(directory + 80, executable ? 1 : 0); /* CS_EXECSEG_MAIN_BINARY */
    memcpy(directory + 88, identifier, identifier_length + 1);
    uint8_t *hashes = directory + 88 + identifier_length + 1;
    for (uint64_t page = 0; page < slots; ++page) {
      uint64_t start = page * 4096, end = start + 4096 > signature_offset ? signature_offset : start + 4096;
      sha256(image + start, (size_t)(end - start), hashes + page * 32);
    }
    FILE *file = fopen(linker->output_path, "wb");
    ok = file && fwrite(image, 1, file_size, file) == file_size;
    if (file && fclose(file)) ok = false;
    if (!ok) fail(linker, "cannot write '%s'%s", linker->output_path, "");
#ifndef _WIN32
    if (ok && chmod(linker->output_path, 0755)) ok = fail(linker, "cannot mark '%s' executable%s", linker->output_path, "");
#endif
  }
  free(image);
  free(locals); free(exports); free(imports);
  free(symtab.data); free(strtab.data); free(indirect.data); free(rebase.data); free(bind.data); free(trie.data);
  free(commands.data);
  return ok;
}

static void linker_free(MLinker *linker) {
  for (size_t o = 0; o < linker->object_count; ++o) {
    MObject *object = linker->objects[o];
    for (size_t s = 0; s < object->section_count; ++s) free(object->sections[s].relocs);
    free(object->sections);
    free(object->symbols);
    free(object->locals);
    free(object);
  }
  free(linker->objects);
  free(linker->archives);
  for (size_t i = 0; i < linker->dylib_count; ++i) free(linker->dylibs[i]);
  free(linker->dylibs);
  for (size_t i = 0; i < linker->buffer_count; ++i) free(linker->buffers[i]);
  free(linker->buffers);
  for (size_t i = 0; i < linker->table_capacity; ++i) free(linker->table[i]);
  free(linker->table);
  for (size_t i = 0; i < linker->extra_count; ++i) free(linker->extra_sections[i]);
  free(linker->extra_sections);
  for (size_t i = 0; i < linker->output_count; ++i) free(linker->outputs[i].sections);
  free(linker->outputs);
  free(linker->got_symbols);
  free(linker->stub_symbols);
  free(linker->fixups);
}

bool dyn_link_macho_supported(const char *path) {
  if (path[0] == '-' && path[1] == 'l') return true;
  FILE *file = fopen(path, "rb");
  if (!file) return true;
  uint8_t magic[16] = {0};
  size_t n = fread(magic, 1, sizeof(magic), file);
  fclose(file);
  if (n >= 8 && !memcmp(magic, "!<arch>\n", 8)) return true;
  if (n >= 16 && read32(magic) == MH_MAGIC_64) return read32(magic + 4) == CPU_ARM64 || read32(magic + 4) == CPU_X86_64;
  return n >= 3 && !memcmp(magic, "---", 3);
}

int dyn_link_macho(const char *const *inputs, size_t input_count, const char *output, const DynMachOOptions *options) {
  MLinker linker = {.output_path = output, .shared = options->shared};
  bool ok = true;
  for (size_t i = 0; ok && i < input_count; ++i) ok = load_input(&linker, inputs[i]);
  ok = ok && resolve_archives(&linker) && assign_outputs(&linker) && plan(&linker) &&
       write_output(&linker, options->shared ? NULL : options->entry,
                    options->install_name ? options->install_name : output);
  if (!ok) {
    fprintf(stderr, "error: link: %s\n", linker.error[0] ? linker.error : "out of memory");
    remove(output);
  }
  linker_free(&linker);
  return ok ? 0 : 2;
}
