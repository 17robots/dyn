#include "native_asm.h"
#include "native_decode.h"
#include "backend/output.h"
#include <inttypes.h>
#include <stdarg.h>

typedef struct {
  char *p;
  size_t n, cap;
  bool failed;
} Text;
static void print(Text *t, const char *format, ...) {
  if (t->failed)
    return;
  va_list ap, copy;
  va_start(ap, format);
  va_copy(copy, ap);
  int n = vsnprintf(NULL, 0, format, copy);
  va_end(copy);
  if (n < 0 || (size_t)n > SIZE_MAX - t->n - 1) {
    t->failed = true;
    va_end(ap);
    return;
  }
  size_t need = t->n + (size_t)n + 1;
  if (need > t->cap) {
    size_t cap = need < 4096 ? 4096 : need * 2;
    char *p = realloc(t->p, cap);
    if (!p) {
      t->failed = true;
      va_end(ap);
      return;
    }
    t->p = p;
    t->cap = cap;
  }
  vsnprintf(t->p + t->n, t->cap - t->n, format, ap);
  t->n += (size_t)n;
  va_end(ap);
}
typedef struct {
  uint64_t at;
  unsigned symbol, type, width;
  int64_t addend;
} Reloc;
typedef struct {
  char *name, *segment;
  uint64_t size, address, flags, align;
  const unsigned char *data;
  Reloc *relocs;
  size_t count;
} Section;
typedef struct {
  char *name;
  unsigned section, type;
  uint64_t value, size;
  bool global, hidden, section_symbol;
} Symbol;
typedef struct {
  unsigned char *bytes;
  size_t size;
  Section *sections;
  size_t section_count;
  Symbol *symbols;
  size_t symbol_count;
  unsigned format, machine;
  Text text;
} Assembly;
enum { ELF = 1, COFF, MACHO };
static bool range(Assembly *a, uint64_t at, uint64_t n) {
  return at <= a->size && n <= a->size - at;
}
static uint64_t get(const unsigned char *p, unsigned n) {
  uint64_t x = 0;
  for (unsigned i = 0; i < n; ++i)
    x |= (uint64_t)p[i] << (8 * i);
  return x;
}
static char *name_at(Assembly *a, uint64_t base, uint64_t size, uint64_t at) {
  if (at >= size || !range(a, base, size))
    return NULL;
  const char *s = (const char *)a->bytes + base + at;
  const char *end = memchr(s, 0, (size_t)(size - at));
  if (!end)
    return NULL;
  size_t n = (size_t)(end - s);
  char *copy = malloc(n + 1);
  if (copy)
    memcpy(copy, s, n + 1);
  return copy;
}
static char *short_name(const unsigned char *p, unsigned width) {
  size_t n = 0;
  while (n < width && p[n])
    ++n;
  char *s = malloc(n + 1);
  if (s) {
    memcpy(s, p, n);
    s[n] = 0;
  }
  return s;
}
static bool arrays(Assembly *a, size_t sections, size_t symbols) {
  if (sections > 65536 || symbols > 10000000)
    return false;
  a->sections = calloc(sections ? sections : 1, sizeof(*a->sections));
  a->symbols = calloc(symbols ? symbols : 1, sizeof(*a->symbols));
  a->section_count = sections;
  a->symbol_count = symbols;
  return a->sections && a->symbols;
}
static bool elf(Assembly *a) {
  const unsigned char *b = a->bytes;
  if (!range(a, 0, 64) || b[4] != 2 || b[5] != 1 || get(b + 16, 2) != 1)
    return false;
  a->format = ELF;
  a->machine = (unsigned)get(b + 18, 2);
  uint64_t table = get(b + 40, 8);
  unsigned n = (unsigned)get(b + 60, 2), names = (unsigned)get(b + 62, 2);
  if (get(b + 58, 2) != 64 || !n || names >= n || !range(a, table, 64u * n))
    return false;
  const unsigned char *ns = b + table + 64u * names;
  uint64_t nb = get(ns + 24, 8), nz = get(ns + 32, 8), symbase = 0, symsize = 0,
           strbase = 0, strsize = 0;
  for (unsigned i = 0; i < n; ++i) {
    const unsigned char *s = b + table + 64u * i;
    if (get(s + 4, 4) == 2) {
      unsigned link = (unsigned)get(s + 40, 4);
      if (link >= n || get(s + 56, 8) != 24)
        return false;
      symbase = get(s + 24, 8);
      symsize = get(s + 32, 8);
      const unsigned char *str = b + table + 64u * link;
      strbase = get(str + 24, 8);
      strsize = get(str + 32, 8);
    }
  }
  if (symsize % 24 || !range(a, symbase, symsize) ||
      !arrays(a, n, (size_t)(symsize / 24)))
    return false;
  for (unsigned i = 1; i < n; ++i) {
    const unsigned char *s = b + table + 64u * i;
    unsigned type = (unsigned)get(s + 4, 4);
    if (type != 1 && type != 14 && type != 8)
      continue;
    Section *out = &a->sections[i];
    out->name = name_at(a, nb, nz, get(s, 4));
    out->flags = get(s + 8, 8);
    out->size = get(s + 32, 8);
    out->align = get(s + 48, 8);
    if (!out->name || !out->align || (out->align & (out->align - 1)))
      return false;
    if (type != 8) {
      uint64_t at = get(s + 24, 8);
      if (!range(a, at, out->size))
        return false;
      out->data = b + at;
    }
    if (type == 14)
      out->flags |= UINT64_C(1) << 63;
  }
  for (size_t i = 0; i < a->symbol_count; ++i) {
    const unsigned char *s = b + symbase + 24 * i;
    Symbol *out = &a->symbols[i];
    out->name = name_at(a, strbase, strsize, get(s, 4));
    out->section = (unsigned)get(s + 6, 2);
    out->value = get(s + 8, 8);
    out->size = get(s + 16, 8);
    out->type = s[4] & 15;
    out->global = (s[4] >> 4) != 0;
    out->hidden = (s[5] & 3) == 2;
    out->section_symbol = out->type == 3;
    if (!out->name || out->section >= n)
      return false;
    if (out->section && !out->section_symbol && !*out->name) {
      char label[64];snprintf(label,sizeof(label),".Ldyn_asm_anchor_%zu",i);
      free(out->name);out->name=malloc(strlen(label)+1);
      if(!out->name)return false;
      strcpy(out->name,label);
    }
  }
  for (unsigned i = 1; i < n; ++i) {
    const unsigned char *s = b + table + 64u * i;
    if (get(s + 4, 4) != 4)
      continue;
    unsigned target = (unsigned)get(s + 44, 4);
    uint64_t at = get(s + 24, 8), size = get(s + 32, 8);
    if (target >= n || size % 24 || !range(a, at, size))
      return false;
    Section *out = &a->sections[target];
    out->count = (size_t)(size / 24);
    out->relocs = calloc(out->count ? out->count : 1, sizeof(*out->relocs));
    if (!out->relocs)
      return false;
    for (size_t j = 0; j < out->count; ++j) {
      const unsigned char *r = b + at + 24 * j;
      out->relocs[j] = (Reloc){.at = get(r, 8),
                               .symbol = (unsigned)get(r + 12, 4),
                               .type = (unsigned)get(r + 8, 4),
                               .addend = (int64_t)get(r + 16, 8)};
    }
  }
  return true;
}
static bool coff(Assembly *a) {
  const unsigned char *b = a->bytes;
  if (!range(a, 0, 20) || (get(b, 2) != 0x8664 && get(b, 2) != 0xaa64) || get(b + 16, 2))
    return false;
  a->format = COFF;
  a->machine = get(b, 2) == 0xaa64 ? 183 : 62;
  unsigned n = (unsigned)get(b + 2, 2), count = (unsigned)get(b + 12, 4);
  uint64_t syms = get(b + 8, 4), str = syms + 18u * (uint64_t)count;
  if (!range(a, 20, 40u * n) || !range(a, syms, 18u * (uint64_t)count) ||
      !range(a, str, 4) || !arrays(a, n + 1, count))
    return false;
  uint64_t strsize = get(b + str, 4);
  if (!range(a, str, strsize))
    return false;
  for (unsigned i = 1; i <= n; ++i) {
    const unsigned char *s = b + 20 + 40u * (i - 1);
    Section *out = &a->sections[i];
    if (s[0] == '/') {
      char num[9] = {0};
      memcpy(num, s + 1, 7);
      out->name = name_at(a, str, strsize, strtoull(num, NULL, 10));
    } else
      out->name = short_name(s, 8);
    out->size = get(s + 16, 4);
    uint64_t at = get(s + 20, 4);
    out->flags = get(s + 36, 4);
    unsigned align = (unsigned)((out->flags >> 20) & 15);
    out->align = align ? UINT64_C(1) << (align - 1) : 1;
    /* Uninitialized data has a size but no file contents. */
    bool uninitialized = (out->flags & 0x80) != 0;
    if (!out->name || (!uninitialized && !range(a, at, out->size)))
      return false;
    out->data = uninitialized ? NULL : b + at;
    uint64_t rel = get(s + 24, 4);
    size_t nr = (size_t)get(s + 32, 2);
    if ((out->flags & 0x01000000) && nr == 65535) {
      if (!range(a, rel, 10))
        return false;
      nr = (size_t)get(b + rel, 4);
      if (!nr)
        return false;
      --nr;
      rel += 10;
    }
    if (!range(a, rel, 10u * (uint64_t)nr))
      return false;
    out->count = nr;
    out->relocs = calloc(nr ? nr : 1, sizeof(*out->relocs));
    if (!out->relocs)
      return false;
    for (size_t j = 0; j < nr; ++j) {
      const unsigned char *r = b + rel + 10 * j;
      Reloc *dest = &out->relocs[j];
      dest->at = get(r, 4);
      dest->symbol = (unsigned)get(r + 4, 4);
      dest->type = (unsigned)get(r + 8, 2);
      dest->width = dest->type == (a->machine == 183 ? 14u : 1u) ? 8 : 4;
      if (dest->at > out->size || dest->width > out->size - dest->at)
        return false;
      uint64_t v = get(out->data + dest->at, dest->width);
      dest->addend = dest->width == 4 ? (int32_t)v : (int64_t)v;
    }
  }
  for (unsigned i = 0; i < count; ++i) {
    const unsigned char *s = b + syms + 18u * i;
    Symbol *out = &a->symbols[i];
    out->name =
        get(s, 4) ? short_name(s, 8) : name_at(a, str, strsize, get(s + 4, 4));
    out->value = get(s + 8, 4);
    out->section = (unsigned)get(s + 12, 2);
    out->type = (get(s + 14, 2) & 32) ? 2 : 1;
    out->global = s[16] == 2;
    if (!out->name || out->section > n || s[17])
      return false; /* own writer uses no auxiliary records */
    out->section_symbol = !out->global && out->section && out->value == 0 &&
                          !strcmp(out->name, a->sections[out->section].name);
  }
  return true;
}
static bool macho(Assembly *a) {
  const unsigned char *b = a->bytes;
  if (!range(a, 0, 32) || (get(b + 4, 4) != 0x0100000c && get(b + 4, 4) != 0x01000007) || get(b + 12, 4) != 1)
    return false;
  a->format = MACHO;
  a->machine = get(b + 4, 4) == 0x01000007 ? 62 : 183;
  uint64_t at = 32, section_table = 0, syms = 0, strings = 0, strsize = 0;
  unsigned n = 0, count = 0;
  for (unsigned i = 0; i < get(b + 16, 4); ++i) {
    if (!range(a, at, 8))
      return false;
    uint64_t size = get(b + at + 4, 4);
    if (size < 8 || !range(a, at, size))
      return false;
    unsigned cmd = (unsigned)get(b + at, 4);
    if (cmd == 0x19) {
      if (size < 72)
        return false;
      n = (unsigned)get(b + at + 64, 4);
      if (size < 72 + 80u * (uint64_t)n)
        return false;
      section_table = at + 72;
    }
    if (cmd == 2) {
      if (size < 24)
        return false;
      syms = get(b + at + 8, 4);
      count = (unsigned)get(b + at + 12, 4);
      strings = get(b + at + 16, 4);
      strsize = get(b + at + 20, 4);
    }
    at += size;
  }
  if (!section_table || !range(a, syms, 16u * (uint64_t)count) ||
      !arrays(a, n + 1, count))
    return false;
  for (unsigned i = 1; i <= n; ++i) {
    const unsigned char *s = b + section_table + 80u * (i - 1);
    Section *out = &a->sections[i];
    out->name = short_name(s, 16);
    out->segment = short_name(s + 16, 16);
    out->address = get(s + 32, 8);
    out->size = get(s + 40, 8);
    unsigned shift = (unsigned)get(s + 52, 4);
    if (shift > 31)
      return false;
    out->align = UINT64_C(1) << shift;
    out->flags = get(s + 64, 4);
    uint64_t pos = get(s + 48, 4), rel = get(s + 56, 4);
    unsigned nr = (unsigned)get(s + 60, 4);
    /* Zero-fill sections have a size but no file contents. */
    bool zerofill = (out->flags & 255) == 1 || (out->flags & 255) == 12;
    if (!out->name || !out->segment || (!zerofill && !range(a, pos, out->size)) ||
        !range(a, rel, 8u * (uint64_t)nr))
      return false;
    out->data = zerofill ? NULL : b + pos;
    out->relocs = calloc(nr ? nr : 1, sizeof(*out->relocs));
    if (!out->relocs)
      return false;
    int64_t addend = 0;
    uint64_t add_at = UINT64_MAX;
    for (unsigned j = 0; j < nr; ++j) {
      const unsigned char *r = b + rel + 8u * j;
      uint32_t info = (uint32_t)get(r + 4, 4);
      unsigned type = info >> 28;
      uint64_t offset = get(r, 4);
      if (a->machine == 183 && type == 10) {
        addend = (int32_t)((info & 0xffffff) << 8) >> 8;
        add_at = offset;
        continue;
      }
      unsigned width = 1u << ((info >> 25) & 3);
      if (!(info & (1u << 27)) || offset > out->size ||
          width > out->size - offset ||
          (add_at != UINT64_MAX && add_at != offset))
        return false;
      if (type == 0 || a->machine == 62)
        addend = width == 4 ? (int32_t)get(out->data + offset, width) : (int64_t)get(out->data + offset, width);
      out->relocs[out->count++] = (Reloc){.at = offset,
                                          .symbol = info & 0xffffff,
                                          .type = type,
                                          .width = width,
                                          .addend = addend};
      addend = 0;
      add_at = UINT64_MAX;
    }
    if (add_at != UINT64_MAX)
      return false;
  }
  for (unsigned i = 0; i < count; ++i) {
    const unsigned char *s = b + syms + 16u * i;
    Symbol *out = &a->symbols[i];
    out->name = name_at(a, strings, strsize, get(s, 4));
    out->section = s[5];
    out->global = (s[4] & 1) != 0;
    out->value = get(s + 8, 8);
    if (!out->name || out->section > n)
      return false;
    if (out->section) {
      if (out->value < a->sections[out->section].address)
        return false;
      out->value -= a->sections[out->section].address;
    }
  }
  return true;
}
static void quoted(Text *t, const char *s) {
  print(t, "\"");
  for (; *s; ++s) {
    unsigned char c = (unsigned char)*s;
    if (c == '"' || c == '\\')
      print(t, "\\%c", c);
    else if (c < 32 || c > 126)
      print(t, "\\%03o", c);
    else
      print(t, "%c", c);
  }
  print(t, "\"");
}
static void section_label(Assembly *a, unsigned section) {
  print(&a->text, "%sdyn_asm_section_%u", a->format == MACHO ? "L" : ".L",
        section);
}
static bool symbol(Assembly *a, unsigned index) {
  if (index >= a->symbol_count)
    return false;
  Symbol *s = &a->symbols[index];
  if (s->section_symbol)
    section_label(a, s->section);
  else
    quoted(&a->text, s->name);
  return true;
}
static const char *elf_reloc(unsigned machine, unsigned type) {
  if (machine == 62)
    switch (type) {
    case 1:
      return "R_X86_64_64";
    case 2:
      return "R_X86_64_PC32";
    case 4:
      return "R_X86_64_PLT32";
    case 9:
      return "R_X86_64_GOTPCREL";
    case 10:
      return "R_X86_64_32";
    default:
      return NULL;
    }
  if (machine == 243) {
    switch(type) {
    case 1:return "R_RISCV_32";case 2:return "R_RISCV_64";
    case 19:return "R_RISCV_CALL_PLT";case 20:return "R_RISCV_GOT_HI20";
    case 23:return "R_RISCV_PCREL_HI20";case 24:return "R_RISCV_PCREL_LO12_I";
    default:return NULL;
    }
  }
  if (machine == 183)
    switch (type) {
    case 257:
      return "R_AARCH64_ABS64";
    case 258:
      return "R_AARCH64_ABS32";
    case 275:
      return "R_AARCH64_ADR_PREL_PG_HI21";
    case 277:
      return "R_AARCH64_ADD_ABS_LO12_NC";
    case 283:
      return "R_AARCH64_CALL26";
    case 311:
      return "R_AARCH64_ADR_GOT_PAGE";
    case 312:
      return "R_AARCH64_LD64_GOT_LO12_NC";
    default:
      return NULL;
    }
  return NULL;
}
static bool relocation(Assembly *a, Section *s, Reloc *r) {
  Text *t = &a->text;
  if (a->format == COFF && a->machine == 183) {
    uint32_t word=(uint32_t)get(s->data+r->at,4);
    unsigned rd=word&31,rn=(word>>5)&31;
    switch(r->type) {
    case 14: print(t,"  .quad "); break;
    case 2: print(t,"  .rva "); break;
    case 8: print(t,"  .secrel32 "); break;
    case 3: print(t,(word&0x80000000)?"  bl ":"  b "); break;
    case 4: print(t,"  adrp x%u, ",rd); break;
    case 6: print(t,"  add x%u, x%u, :lo12:",rd,rn); break;
    case 7: print(t,"  ldr x%u, [x%u, :lo12:",rd,rn); break;
    default: return false;
    }
    if(!symbol(a,r->symbol)) return false;
    if(r->type==7) print(t,"]");
    if(r->type==14 || r->type==2 || r->type==8)
      print(t," %c 0x%" PRIx64,r->addend<0?'-':'+',r->addend<0?UINT64_C(0)-(uint64_t)r->addend:(uint64_t)r->addend);
    print(t,"\n"); return true;
  }
  if (a->format == COFF) {
    switch (r->type) {
    case 1:
      print(t, "  .quad ");
      break;
    case 3:
      print(t, "  .rva ");
      break;
    case 4:
      print(t, "  .long ");
      break;
    case 11:
      print(t, "  .secrel32 ");
      break;
    default:
      return false;
    }
    if (!symbol(a, r->symbol))
      return false;
    if (r->type == 4)
      print(t, " - . - 4");
    print(t, " %c 0x%" PRIx64 "\n", r->addend < 0 ? '-' : '+',
          r->addend < 0 ? UINT64_C(0) - (uint64_t)r->addend
                        : (uint64_t)r->addend);
    return true;
  }
  if (a->format != MACHO)
    return false;
  if (a->machine == 62) {
    if (r->type > 4 || (r->width != 4 && r->width != 8)) return false;
    print(t, r->type == 0 ? "  .quad " : "  .long ");
    if (!symbol(a, r->symbol)) return false;
    if (r->type == 3 || r->type == 4) print(t, "@GOTPCREL");
    else if (r->type) print(t, " - .");
    int64_t addend = r->addend - (r->type ? 4 : 0);
    print(t, " %c 0x%" PRIx64 "\n", addend < 0 ? '-' : '+',
          addend < 0 ? UINT64_C(0)-(uint64_t)addend : (uint64_t)addend);
    return true;
  }
  uint32_t word = (uint32_t)get(s->data + r->at, 4);
  unsigned rd = word & 31, rn = (word >> 5) & 31;
  switch (r->type) {
  case 0:
    if (r->width != 8)
      return false;
    print(t, "  .quad ");
    break;
  case 2:
    if ((word & 0xfc000000) != 0x94000000)
      return false;
    print(t, "  bl ");
    break;
  case 3:
  case 5:
    if ((word & 0x9f000000) != 0x90000000)
      return false;
    print(t, "  adrp x%u, ", rd);
    break;
  case 4:
    if ((word & 0xffc00000) != 0x91000000)
      return false;
    print(t, "  add x%u, x%u, ", rd, rn);
    break;
  case 6:
    if ((word & 0xffc00000) != 0xf9400000)
      return false;
    print(t, "  ldr x%u, [x%u, ", rd, rn);
    break;
  default:
    return false;
  }
  if (!symbol(a, r->symbol))
    return false;
  if (r->type == 3)
    print(t, "@PAGE");
  if (r->type == 4)
    print(t, "@PAGEOFF");
  if (r->type == 5)
    print(t, "@GOTPAGE");
  if (r->type == 6)
    print(t, "@GOTPAGEOFF");
  if (r->addend)
    print(t, " %c 0x%" PRIx64, r->addend < 0 ? '-' : '+',
          r->addend < 0 ? UINT64_C(0) - (uint64_t)r->addend
                        : (uint64_t)r->addend);
  if (r->type == 6)
    print(t, "]");
  print(t, "\n");
  return true;
}
typedef struct {
  uint64_t at;
  unsigned index;
} Label;
static int label_order(const void *x, const void *y) {
  const Label *a = x, *b = y;
  return a->at < b->at ? -1 : a->at > b->at ? 1 : 0;
}
static int reloc_order(const void *x, const void *y) {
  const Reloc *a = x, *b = y;
  return a->at < b->at ? -1 : a->at > b->at ? 1 : 0;
}
static bool emit(Assembly *a) {
  Text *t = &a->text;
  print(t, "// Dyn independent assembly. Exact instruction encodings; symbolic "
           "relocations.\n");
  if (a->machine == 243) print(t,".option norelax\n.option norvc\n.attribute arch, \"rv64imafd\"\n");
  if (a->format == MACHO)
    print(t, ".build_version macos, 15, 0\n");
  for (size_t i = 0; i < a->symbol_count; ++i) {
    Symbol *s = &a->symbols[i];
    if (!s->name || !*s->name || s->section_symbol)
      continue;
    if (s->global) {
      print(t, ".globl ");
      quoted(t, s->name);
      print(t, "\n");
    }
    if (a->format == ELF) {
      if (!s->global) {
        print(t, ".local ");
        quoted(t, s->name);
        print(t, "\n");
      }
      if (s->hidden) {
        print(t, ".hidden ");
        quoted(t, s->name);
        print(t, "\n");
      }
      if (s->type == 1 || s->type == 2) {
        print(t, ".type ");
        quoted(t, s->name);
        print(t, ", %s%s\n", a->machine == 183 ? "%" : "@",
              s->type == 2 ? "function" : "object");
      }
    } else if (a->format == COFF) {
      print(t, ".def ");
      quoted(t, s->name);
      print(t, "; .scl %u; .type %u; .endef\n", s->global ? 2 : 3,
            s->type == 2 ? 32 : 0);
    }
  }
  Label *labels =
      malloc((a->symbol_count ? a->symbol_count : 1) * sizeof(*labels));
  if (!labels)
    return false;
  bool ok = true;
  for (unsigned index = 1; ok && index < a->section_count; ++index) {
    Section *s = &a->sections[index];
    if (!s->name)
      continue;
    print(t, "\n.section ");
    if (a->format == MACHO) {
      print(t, "%s,%s", s->segment, s->name);
      print(t, ",%s", (s->flags & 255) == 9 ? "mod_init_funcs" : !s->data ? "zerofill" : "regular");
      if (s->flags & 0x80000000)
        print(t, ",pure_instructions");
      else if (s->flags & 0x02000000)
        print(t, ",debug");
    } else {
      quoted(t, s->name);
      if (a->format == ELF)
        print(t, ",\"%s%s%s\",%s%s", s->flags & 2 ? "a" : "",
              s->flags & 1 ? "w" : "", s->flags & 4 ? "x" : "",
              a->machine == 183 ? "%" : "@",
              !s->data                         ? "nobits"
              : s->flags & (UINT64_C(1) << 63) ? "init_array"
                                               : "progbits");
      else
        print(t, ",\"%s%s%s%s\"", s->flags & 0x20 ? "x" : !s->data ? "b" : "d",
              s->flags & 0x80000000 ? "w" : "r",
              s->flags & 0x02000000 ? "D" : "", "");
    }
    unsigned exponent = 0;
    while (exponent < 63 && (UINT64_C(1) << exponent) < s->align)
      ++exponent;
    print(t, "\n.p2align %u\n", exponent);
    section_label(a, index);
    print(t, ":\n");
    size_t nl = 0;
    for (unsigned j = 0; j < a->symbol_count; ++j) {
      Symbol *sym = &a->symbols[j];
      if (sym->section == index && !sym->section_symbol && sym->name &&
          *sym->name) {
        if (sym->value > s->size) {
          ok = false;
          break;
        }
        labels[nl++] = (Label){sym->value, j};
      }
    }
    if (!ok)
      break;
    qsort(labels, nl, sizeof(*labels), label_order);
    if (s->count > 1)
      qsort(s->relocs, s->count, sizeof(*s->relocs), reloc_order);
    if (a->format == ELF)
      for (size_t j = 0; j < s->count; ++j) {
        Reloc *r = &s->relocs[j];
        const char *kind = elf_reloc(a->machine, r->type);
        if (!kind || r->at >= s->size) {
          ok = false;
          break;
        }
        print(t, "  .reloc ");
        section_label(a, index);
        print(t, " + 0x%" PRIx64 ", %s, ", r->at, kind);
        if (!symbol(a, r->symbol)) {
          ok = false;
          break;
        }
        print(t, " %c 0x%" PRIx64 "\n", r->addend < 0 ? '-' : '+',
              r->addend < 0 ? UINT64_C(0) - (uint64_t)r->addend
                            : (uint64_t)r->addend);
      }
    uint64_t at = 0, instruction_end = 0;
    bool executable = a->format == ELF ? (s->flags & 4) != 0
                    : a->format == COFF ? (s->flags & 0x20000000) != 0
                    : (s->flags & 0x80000400) != 0;
    bool decoding = executable;
    size_t li = 0, ri = 0, decoded_reloc = 0;
    while (ok && at <= s->size) {
      while (li < nl && labels[li].at == at) {
        Symbol *sym = &a->symbols[labels[li++].index];
        if (sym->type == 2) {
          print(t, "// Function boundary\n");
          decoding = executable;
          instruction_end = at;
        }
        quoted(t, sym->name);
        print(t, ":\n");
        if (a->format == ELF && sym->size) {
          print(t, ".size ");
          quoted(t, sym->name);
          print(t, ", 0x%" PRIx64 "\n", sym->size);
        }
      }
      if (at == s->size)
        break;
      if (a->format == MACHO && a->machine == 62 && s->data && ri<s->count &&
          s->relocs[ri].type==2 && s->relocs[ri].at==at+1 && at+5<=s->size &&
          (s->data[at]==0xe8 || s->data[at]==0xe9) && !(li<nl&&labels[li].at<at+5)) {
        Reloc *r=&s->relocs[ri++];print(t,"  %s ",s->data[at]==0xe8?"callq":"jmp");
        if(!symbol(a,r->symbol)) {ok=false;break;}
        if(r->addend)print(t," %c 0x%" PRIx64,r->addend<0?'-':'+',r->addend<0?UINT64_C(0)-(uint64_t)r->addend:(uint64_t)r->addend);
        print(t,"\n");at+=5;instruction_end=at;continue;
      }
      if (decoding && s->data && at >= instruction_end) {
        char instruction[512];
        size_t length = a->machine == 62
          ? nd_x64(s->data + at, (size_t)(s->size-at), instruction, sizeof instruction)
          : a->machine == 183
          ? nd_a64(s->data + at, (size_t)(s->size-at), instruction, sizeof instruction)
          : a->machine == 243 ? nd_rv64(s->data + at, (size_t)(s->size-at), instruction, sizeof instruction) : 0;
        if (length) {
          instruction_end = at + length;
          while (decoded_reloc < s->count && s->relocs[decoded_reloc].at +
                 (s->relocs[decoded_reloc].width ? s->relocs[decoded_reloc].width : 8) <= at)
            ++decoded_reloc;
          bool relocated = decoded_reloc < s->count && s->relocs[decoded_reloc].at < instruction_end;
          /* AArch64 encodings have a fixed width. The supported decoder forms
             round-trip exactly. x86 operands can select shorter encodings, so
             retain authoritative bytes except for fixed, operand-free forms. */
          unsigned op = s->data[at];
          bool exact = a->machine == 183 || (a->machine == 62 &&
              ((length == 1 && (op == 0xc3 || op == 0xc9 || op == 0x90 || op == 0xcc || op == 0xfc || op == 0xfd)) ||
               (length == 2 && ((op == 0x0f && (s->data[at+1] == 5 || s->data[at+1] == 11)) ||
                                (op == 0x48 && s->data[at+1] == 0x99)))));
          if (exact && !relocated && !(li < nl && labels[li].at < instruction_end)) {
            print(t, "  %s // +0x%" PRIx64 "\n", instruction, at);
            at = instruction_end;
            continue;
          }
          if (relocated)
            print(t, "  // +0x%" PRIx64 ": %s (encoded operand; relocation supplies final value)\n", at, instruction);
          else
            print(t, "  // +0x%" PRIx64 ": %s\n", at, instruction);
        } else {
          print(t, "  // Undecoded encoding at +0x%" PRIx64 "; raw bytes remain authoritative.\n", at);
          decoding = a->machine == 183 || a->machine == 243;
          instruction_end = at + (decoding ? 4 : 0);
        }
      }
      if (a->format != ELF && ri < s->count && s->relocs[ri].at == at) {
        Reloc *r = &s->relocs[ri++];
        if ((li < nl && labels[li].at < at + r->width) ||
            !relocation(a, s, r)) {
          ok = false;
          break;
        }
        at += r->width;
        continue;
      }
      uint64_t next = s->size;
      if (li < nl && labels[li].at < next)
        next = labels[li].at;
      if (a->format != ELF && ri < s->count && s->relocs[ri].at < next)
        next = s->relocs[ri].at;
      if (next <= at) {
        ok = false;
        break;
      }
      if (decoding && instruction_end > at && instruction_end < next)
        next = instruction_end;
      if (next - at > 16)
        next = at + 16;
      if (!s->data)
        print(t, "  .zero %" PRIu64 "\n", next - at);
      else {
        print(t, "  .byte ");
        for (uint64_t j = at; j < next; ++j)
          print(t, "%s0x%02x", j == at ? "" : ",", s->data[j]);
        print(t, "\n");
      }
      at = next;
    }
    if (a->format != ELF && ri != s->count)
      ok = false;
  }
  free(labels);
  return ok && !t->failed;
}
int dyn_native_assembly(const char *object, const char *output) {
  Assembly a = {0};
  FILE *f = fopen(object, "rb");
  bool ok = false;
  if (!f)
    return 1;
  if (fseek(f, 0, SEEK_END))
    goto done;
  long length = ftell(f);
  if (length < 4 || length > 1024L * 1024 * 1024 || fseek(f, 0, SEEK_SET))
    goto done;
  a.size = (size_t)length;
  a.bytes = malloc(a.size);
  if (!a.bytes || fread(a.bytes, 1, a.size, f) != a.size)
    goto done;
  if (!memcmp(a.bytes, "\177ELF", 4))
    ok = elf(&a);
  else if (get(a.bytes, 4) == 0xfeedfacf)
    ok = macho(&a);
  else
    ok = coff(&a);
  if (ok)
    ok = emit(&a);
  if (ok)
    ok = backend_write_object(output, a.text.p, a.text.n);
done:
  fclose(f);
  for (size_t i = 0; a.sections && i < a.section_count; ++i) {
    free(a.sections[i].name);
    free(a.sections[i].segment);
    free(a.sections[i].relocs);
  }
  for (size_t i = 0; a.symbols && i < a.symbol_count; ++i)
    free(a.symbols[i].name);
  free(a.sections);
  free(a.symbols);
  free(a.bytes);
  free(a.text.p);
  if (!ok)
    fprintf(stderr, "error: cannot render native assembly from '%s'\n", object);
  return ok ? 0 : 1;
}
