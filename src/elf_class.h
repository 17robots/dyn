/* Conversion between ELF32 and ELF64 little-endian files.

   The backend and the linker work on ELF64 throughout. 32-bit targets convert
   at the edges: the backend narrows each finished object, the linker widens
   each ELF32 input on load and narrows the finished executable. Only the
   headers, symbol tables and relocation tables change shape; every other
   section keeps its bytes.

   Narrowing keeps each section at its original file offset, because the
   ELF32 forms are never larger: program headers stay valid without
   relayout. Widening lays sections out again, which is only done for
   relocatable inputs (they have no program headers). */
#ifndef DYN_ELF_CLASS_H
#define DYN_ELF_CLASS_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

enum { ELF_CLASS_SHT_SYMTAB = 2, ELF_CLASS_SHT_RELA = 4, ELF_CLASS_SHT_REL = 9, ELF_CLASS_SHT_DYNSYM = 11 };

static inline uint16_t elf_class_read16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static inline uint32_t elf_class_read32(const uint8_t *p) {
  return (uint32_t)elf_class_read16(p) | (uint32_t)elf_class_read16(p + 2) << 16;
}
static inline uint64_t elf_class_read64(const uint8_t *p) {
  return (uint64_t)elf_class_read32(p) | (uint64_t)elf_class_read32(p + 4) << 32;
}
static inline void elf_class_write16(uint8_t *p, uint64_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static inline void elf_class_write32(uint8_t *p, uint64_t v) {
  elf_class_write16(p, v); elf_class_write16(p + 2, v >> 16);
}
static inline void elf_class_write64(uint8_t *p, uint64_t v) {
  elf_class_write32(p, v); elf_class_write32(p + 4, v >> 32);
}
static inline bool elf_class_inside(size_t size, uint64_t offset, uint64_t length) {
  return offset <= size && length <= size - offset;
}
static inline bool elf_class_fits(uint64_t value) { return value <= UINT32_MAX; }

/* ELF64 to ELF32. Fails when a value does not fit in 32 bits. */
static inline bool dyn_elf_narrow(const uint8_t *in, size_t size, uint8_t **out, size_t *out_size) {
  *out = NULL; *out_size = 0;
  if (size < 64 || memcmp(in, "\x7f" "ELF", 4) || in[4] != 2 || in[5] != 1) return false;
  uint64_t phoff = elf_class_read64(in + 32), shoff = elf_class_read64(in + 40);
  unsigned phnum = elf_class_read16(in + 56), shnum = elf_class_read16(in + 60);
  if ((phnum && !elf_class_inside(size, phoff, (uint64_t)phnum * 56)) ||
      (shnum && !elf_class_inside(size, shoff, (uint64_t)shnum * 64))) return false;
  /* Section headers move to the end, after every section's bytes. */
  uint64_t end = shnum ? shoff : size;
  for (unsigned i = 0; i < shnum; ++i) {
    const uint8_t *s = in + shoff + (size_t)i * 64;
    uint64_t at = elf_class_read64(s + 24), length = elf_class_read64(s + 32);
    if (elf_class_read32(s + 4) != 8 && at + length > end) end = at + length; /* not NOBITS */
  }
  uint64_t headers = (end + 3) & ~UINT64_C(3), total = headers + (uint64_t)shnum * 40;
  if (!elf_class_fits(total) || total < 52) return false;
  uint8_t *o = calloc((size_t)total, 1);
  if (!o) return false;
  memcpy(o, in, (size_t)(end < size ? end : size));
  /* File header. */
  memset(o, 0, 64);
  memcpy(o, in, 16);
  o[4] = 1;
  uint64_t entry = elf_class_read64(in + 24);
  bool ok = elf_class_fits(entry) && elf_class_fits(phoff);
  elf_class_write16(o + 16, elf_class_read16(in + 16));
  elf_class_write16(o + 18, elf_class_read16(in + 18));
  elf_class_write32(o + 20, elf_class_read32(in + 20));
  elf_class_write32(o + 24, entry);
  elf_class_write32(o + 28, phnum ? phoff : 0);
  elf_class_write32(o + 32, shnum ? headers : 0);
  elf_class_write32(o + 36, elf_class_read32(in + 48));
  elf_class_write16(o + 40, 52);
  elf_class_write16(o + 42, phnum ? 32 : 0);
  elf_class_write16(o + 44, phnum);
  elf_class_write16(o + 46, shnum ? 40 : 0);
  elf_class_write16(o + 48, shnum);
  elf_class_write16(o + 50, elf_class_read16(in + 62));
  /* Program headers shrink in place. */
  for (unsigned i = 0; ok && i < phnum; ++i) {
    uint8_t p[56];
    memcpy(p, in + phoff + (size_t)i * 56, 56);
    uint8_t *q = o + phoff + (size_t)i * 32;
    for (unsigned field = 8; field < 56; field += 8) ok = ok && elf_class_fits(elf_class_read64(p + field));
    elf_class_write32(q, elf_class_read32(p));
    elf_class_write32(q + 4, elf_class_read64(p + 8));
    elf_class_write32(q + 8, elf_class_read64(p + 16));
    elf_class_write32(q + 12, elf_class_read64(p + 24));
    elf_class_write32(q + 16, elf_class_read64(p + 32));
    elf_class_write32(q + 20, elf_class_read64(p + 40));
    elf_class_write32(q + 24, elf_class_read32(p + 4));
    elf_class_write32(q + 28, elf_class_read64(p + 48));
  }
  if (phnum) memset(o + phoff + (size_t)phnum * 32, 0, (size_t)phnum * 24);
  /* Sections: tables are rewritten in place, every header is narrowed. */
  for (unsigned i = 0; ok && i < shnum; ++i) {
    const uint8_t *s = in + shoff + (size_t)i * 64;
    uint8_t *h = o + headers + (size_t)i * 40;
    uint32_t type = elf_class_read32(s + 4);
    uint64_t at = elf_class_read64(s + 24), length = elf_class_read64(s + 32), entsize = elf_class_read64(s + 56);
    if (type != 8 && !elf_class_inside(size, at, length)) { ok = false; break; }
    uint64_t narrowed = length, narrowed_entsize = entsize;
    if ((type == ELF_CLASS_SHT_SYMTAB || type == ELF_CLASS_SHT_DYNSYM) && entsize == 24) {
      size_t count = (size_t)(length / 24);
      memset(o + at, 0, (size_t)length);
      for (size_t k = 0; k < count; ++k) {
        const uint8_t *from = in + at + k * 24;
        uint8_t *to = o + at + k * 16;
        uint64_t value = elf_class_read64(from + 8), bytes = elf_class_read64(from + 16);
        ok = ok && elf_class_fits(value) && elf_class_fits(bytes);
        elf_class_write32(to, elf_class_read32(from));
        elf_class_write32(to + 4, value);
        elf_class_write32(to + 8, bytes);
        to[12] = from[4]; to[13] = from[5];
        elf_class_write16(to + 14, elf_class_read16(from + 6));
      }
      narrowed = (uint64_t)count * 16; narrowed_entsize = 16;
    } else if ((type == ELF_CLASS_SHT_RELA && entsize == 24) || (type == ELF_CLASS_SHT_REL && entsize == 16)) {
      bool addend = type == ELF_CLASS_SHT_RELA;
      size_t count = (size_t)(length / entsize), width = addend ? 12 : 8;
      memset(o + at, 0, (size_t)length);
      for (size_t k = 0; k < count; ++k) {
        const uint8_t *from = in + at + k * entsize;
        uint8_t *to = o + at + k * width;
        uint64_t offset = elf_class_read64(from), info = elf_class_read64(from + 8);
        uint64_t symbol = info >> 32, kind = info & 0xffffffffu;
        ok = ok && elf_class_fits(offset) && symbol < (1u << 24) && kind < 256;
        elf_class_write32(to, offset);
        elf_class_write32(to + 4, symbol << 8 | kind);
        if (addend) {
          int64_t value = (int64_t)elf_class_read64(from + 16);
          ok = ok && value >= INT32_MIN && value <= INT32_MAX;
          elf_class_write32(to + 8, (uint32_t)value);
        }
      }
      narrowed = (uint64_t)count * width; narrowed_entsize = width;
    }
    uint64_t flags = elf_class_read64(s + 8), address = elf_class_read64(s + 16), align = elf_class_read64(s + 48);
    ok = ok && elf_class_fits(flags) && elf_class_fits(address) && elf_class_fits(at) && elf_class_fits(narrowed) &&
         elf_class_fits(align) && elf_class_fits(narrowed_entsize);
    elf_class_write32(h, elf_class_read32(s));
    elf_class_write32(h + 4, type);
    elf_class_write32(h + 8, flags);
    elf_class_write32(h + 12, address);
    elf_class_write32(h + 16, at);
    elf_class_write32(h + 20, narrowed);
    elf_class_write32(h + 24, elf_class_read32(s + 40));
    elf_class_write32(h + 28, elf_class_read32(s + 44));
    elf_class_write32(h + 32, align);
    elf_class_write32(h + 36, narrowed_entsize);
  }
  if (!ok) { free(o); return false; }
  *out = o; *out_size = (size_t)total;
  return true;
}

/* ELF32 relocatable object to ELF64. Sections are laid out again. */
static inline bool dyn_elf_widen(const uint8_t *in, size_t size, uint8_t **out, size_t *out_size) {
  *out = NULL; *out_size = 0;
  if (size < 52 || memcmp(in, "\x7f" "ELF", 4) || in[4] != 1 || in[5] != 1 || elf_class_read16(in + 16) != 1)
    return false;
  uint32_t shoff = elf_class_read32(in + 32);
  unsigned shnum = elf_class_read16(in + 48);
  if (!shnum || !elf_class_inside(size, shoff, (uint64_t)shnum * 40)) return false;
  /* Sizes first: tables grow, everything else keeps its length. */
  uint64_t cursor = 64;
  uint64_t *offsets = calloc(shnum, sizeof(*offsets)), *lengths = calloc(shnum, sizeof(*lengths));
  if (!offsets || !lengths) { free(offsets); free(lengths); return false; }
  bool ok = true;
  for (unsigned i = 0; ok && i < shnum; ++i) {
    const uint8_t *s = in + shoff + (size_t)i * 40;
    uint32_t type = elf_class_read32(s + 4), length = elf_class_read32(s + 20), entsize = elf_class_read32(s + 36);
    uint32_t align = elf_class_read32(s + 32);
    uint64_t widened = length;
    if ((type == ELF_CLASS_SHT_SYMTAB || type == ELF_CLASS_SHT_DYNSYM) && entsize == 16) widened = (uint64_t)(length / 16) * 24, align = 8;
    else if (type == ELF_CLASS_SHT_RELA && entsize == 12) widened = (uint64_t)(length / 12) * 24, align = 8;
    else if (type == ELF_CLASS_SHT_REL && entsize == 8) widened = (uint64_t)(length / 8) * 16, align = 8;
    if (type != 8 && type != 0 && !elf_class_inside(size, elf_class_read32(s + 16), length)) ok = false;
    if (align > 1) cursor = (cursor + align - 1) / align * align;
    lengths[i] = widened;
    if (type != 8 && type != 0) { offsets[i] = cursor; cursor += widened; }
  }
  cursor = (cursor + 7) & ~UINT64_C(7);
  uint64_t headers = cursor, total = headers + (uint64_t)shnum * 64;
  uint8_t *o = ok ? calloc((size_t)total, 1) : NULL;
  if (!o) { free(offsets); free(lengths); return false; }
  memcpy(o, in, 16);
  o[4] = 2;
  elf_class_write16(o + 16, elf_class_read16(in + 16));
  elf_class_write16(o + 18, elf_class_read16(in + 18));
  elf_class_write32(o + 20, elf_class_read32(in + 20));
  elf_class_write64(o + 24, elf_class_read32(in + 24));
  elf_class_write64(o + 40, headers);
  elf_class_write32(o + 48, elf_class_read32(in + 36));
  elf_class_write16(o + 52, 64);
  elf_class_write16(o + 58, 64);
  elf_class_write16(o + 60, shnum);
  elf_class_write16(o + 62, elf_class_read16(in + 50));
  for (unsigned i = 0; i < shnum; ++i) {
    const uint8_t *s = in + shoff + (size_t)i * 40;
    uint8_t *h = o + headers + (size_t)i * 64;
    uint32_t type = elf_class_read32(s + 4), at = elf_class_read32(s + 16), length = elf_class_read32(s + 20);
    uint32_t entsize = elf_class_read32(s + 36), align = elf_class_read32(s + 32);
    uint8_t *to = o + offsets[i];
    if ((type == ELF_CLASS_SHT_SYMTAB || type == ELF_CLASS_SHT_DYNSYM) && entsize == 16) {
      for (size_t k = 0; k < length / 16; ++k) {
        const uint8_t *from = in + at + k * 16;
        uint8_t *e = to + k * 24;
        elf_class_write32(e, elf_class_read32(from));
        e[4] = from[12]; e[5] = from[13];
        elf_class_write16(e + 6, elf_class_read16(from + 14));
        elf_class_write64(e + 8, elf_class_read32(from + 4));
        elf_class_write64(e + 16, elf_class_read32(from + 8));
      }
      entsize = 24; align = 8;
    } else if ((type == ELF_CLASS_SHT_RELA && entsize == 12) || (type == ELF_CLASS_SHT_REL && entsize == 8)) {
      bool addend = type == ELF_CLASS_SHT_RELA;
      for (size_t k = 0; k < length / entsize; ++k) {
        const uint8_t *from = in + at + k * entsize;
        uint8_t *e = to + k * (addend ? 24 : 16);
        uint32_t info = elf_class_read32(from + 4);
        elf_class_write64(e, elf_class_read32(from));
        elf_class_write64(e + 8, (uint64_t)(info >> 8) << 32 | (info & 0xff));
        if (addend) elf_class_write64(e + 16, (uint64_t)(int64_t)(int32_t)elf_class_read32(from + 8));
      }
      entsize = addend ? 24 : 16; align = 8;
    } else if (type != 8 && type != 0 && length) memcpy(to, in + at, length);
    elf_class_write32(h, elf_class_read32(s));
    elf_class_write32(h + 4, type);
    elf_class_write64(h + 8, elf_class_read32(s + 8));
    elf_class_write64(h + 16, elf_class_read32(s + 12));
    elf_class_write64(h + 24, offsets[i]);
    elf_class_write64(h + 32, lengths[i]);
    elf_class_write32(h + 40, elf_class_read32(s + 24));
    elf_class_write32(h + 44, elf_class_read32(s + 28));
    elf_class_write64(h + 48, align);
    elf_class_write64(h + 56, entsize);
  }
  free(offsets); free(lengths);
  *out = o; *out_size = (size_t)total;
  return true;
}
#endif
