/* COFF (x86-64 Windows) object writer, included by driver.c.

   The emitter records symbols and relocations in ELF form. This writer maps
   them onto four COFF sections and moves RELA addends into the relocated bytes,
   as COFF requires. Sections: .text, .rdata (string literals), .data (mutable
   globals), .rdata (constant globals, which carry ADDR64 relocations), and the
   .xdata/.pdata unwind tables Windows needs to walk native frames. */

enum { COFF_TEXT = 1, COFF_RODATA, COFF_DATA, COFF_CONSTANTS, COFF_XDATA, COFF_PDATA, COFF_SECTIONS = 6 };
enum { IMAGE_REL_AMD64_ADDR64 = 1, IMAGE_REL_AMD64_ADDR32NB = 3, IMAGE_REL_AMD64_REL32 = 4 };

static void put16(unsigned char *p, uint16_t v) { p[0] = (unsigned char)v; p[1] = (unsigned char)(v >> 8); }
static void put32(unsigned char *p, uint32_t v) { for (unsigned i = 0; i < 4; ++i) p[i] = (unsigned char)(v >> 8 * i); }
static void put64(unsigned char *p, uint64_t v) { for (unsigned i = 0; i < 8; ++i) p[i] = (unsigned char)(v >> 8 * i); }

static void coff_append(Bytes *b, const void *data, size_t n) {
  if (reserve(b, b->n + n)) { memcpy(b->data + b->n, data, n); b->n += n; }
}

/* ELF section index (driver.c layout) to COFF section number; 0 is undefined. */
static int coff_section(unsigned shndx) {
  return shndx == 1 ? COFF_TEXT : shndx == 2 ? COFF_RODATA : shndx == 8 ? COFF_DATA : shndx == 11 ? COFF_CONSTANTS : 0;
}

/* Relocations of one section: 10 bytes each, with the in-place addend written
   into `bytes`. A null symbol_map means the symbols are already COFF indices.
   Returns false for a relocation COFF cannot express. */
static bool coff_relocations(const Elf64_Rela *items, size_t count, unsigned char *bytes, size_t size,
                             const unsigned *symbol_map, unsigned symbol_count, unsigned char *out) {
  for (size_t i = 0; i < count; ++i) {
    const Elf64_Rela *r = &items[i];
    unsigned symbol = (unsigned)ELF64_R_SYM(r->r_info), type = (unsigned)ELF64_R_TYPE(r->r_info);
    if ((symbol_map && symbol >= symbol_count) || r->r_offset > UINT32_MAX) return false;
    unsigned coff;
    if (!symbol_map) {
      if (r->r_offset + 4 > size) return false;
      put32(bytes + r->r_offset, (uint32_t)r->r_addend); coff = IMAGE_REL_AMD64_ADDR32NB;
    } else if (type == R_X86_64_64) {
      if (r->r_offset + 8 > size) return false;
      put64(bytes + r->r_offset, (uint64_t)r->r_addend); coff = IMAGE_REL_AMD64_ADDR64;
    } else if (type == R_X86_64_PC32 || type == R_X86_64_PLT32) {
      /* COFF REL32 is relative to the end of the field; ELF folds that -4 into the addend. */
      int64_t addend = r->r_addend + 4;
      if (r->r_offset + 4 > size || addend < INT32_MIN || addend > INT32_MAX) return false;
      put32(bytes + r->r_offset, (uint32_t)addend); coff = IMAGE_REL_AMD64_REL32;
    } else return false;
    put32(out + 10 * i, (uint32_t)r->r_offset); put32(out + 10 * i + 4, symbol_map ? symbol_map[symbol] : symbol); put16(out + 10 * i + 8, (uint16_t)coff);
  }
  return true;
}

/* UNWIND_INFO for the isa_enter prologue: push rbp; mov rbp, rsp; save RSI/RDI
   in the home area; allocate the frame. Codes are listed last-instruction first. */
static void coff_unwind_info(Bytes *out, const uint32_t frame[3]) {
  uint32_t size = frame[2];
  unsigned char codes[20];
  unsigned n = 0;
  if (size <= 128) { codes[n++] = (unsigned char)frame[1]; codes[n++] = (unsigned char)(2 | (size - 8) / 8 << 4); }
  else if (size <= 524280) {
    codes[n++] = (unsigned char)frame[1]; codes[n++] = 1;
    put16(codes + n, (uint16_t)(size / 8)); n += 2;
  } else {
    codes[n++] = (unsigned char)frame[1]; codes[n++] = 1 | 1 << 4;
    put32(codes + n, size); n += 4;
  }
  /* UWOP_SAVE_NONVOL offsets are eight-byte units above the frame pointer. */
  const unsigned char fixed[] = {12, 4 | 7 << 4, 3, 0, 8, 4 | 6 << 4, 2, 0, 4, 3, 1, 0 | 5 << 4};
  memcpy(codes + n, fixed, sizeof(fixed)); n += sizeof(fixed);
  unsigned slots = n / 2;
  unsigned char header[4] = {1, (unsigned char)frame[1], (unsigned char)slots, 5};
  coff_append(out, header, 4); coff_append(out, codes, n);
  if (slots & 1) { unsigned char pad[2] = {0}; coff_append(out, pad, 2); }
}

static bool write_coff(BackendContext *ctx, const char *path, const Elf64_Sym *symbols, unsigned symbol_count, const char *strings) {
  /* COFF symbols: one static symbol per section, then every ELF symbol after the
     section symbols driver.c reserved. */
  unsigned section_symbols = 2; /* null and the .rodata section symbol */
  unsigned coff_count = COFF_SECTIONS + symbol_count - section_symbols;
  unsigned *symbol_map = calloc(symbol_count, sizeof(*symbol_map));
  if (!symbol_map) return false;
  symbol_map[1] = COFF_RODATA - 1;
  for (unsigned i = section_symbols; i < symbol_count; ++i) symbol_map[i] = COFF_SECTIONS + i - section_symbols;

  /* .pdata: {begin, end, unwind info} per function, image-relative. */
  Bytes xdata = {0}, pdata = {0};
  unsigned frames = ctx->unwind_frame_count;
  Elf64_Rela *table_relocations = calloc(3 * (size_t)frames + 1, sizeof(*table_relocations));
  if (!table_relocations) { free(symbol_map); return false; }
  for (unsigned i = 0; i < frames; ++i) {
    const uint32_t *frame = ctx->unwind_frames[i];
    uint32_t entry[3] = {frame[0], i + 1 < frames ? ctx->unwind_frames[i + 1][0] : (uint32_t)ctx->text.n, (uint32_t)xdata.n};
    for (unsigned j = 0; j < 3; ++j) {
      table_relocations[3 * i + j] = (Elf64_Rela){.r_offset = 12 * (size_t)i + 4 * j,
        .r_info = ELF64_R_INFO(j == 2 ? COFF_XDATA - 1u : COFF_TEXT - 1u, 0u), .r_addend = entry[j]};
    }
    unsigned char zero[12] = {0};
    coff_append(&pdata, zero, sizeof(zero));
    coff_unwind_info(&xdata, frame);
  }
  const Bytes *contents[COFF_SECTIONS] = {&ctx->text, &ctx->rodata, &ctx->globals_data, &ctx->constants_data, &xdata, &pdata};
  const char *names[COFF_SECTIONS] = {".text", ".rdata", ".data", ".rdata", ".xdata", ".pdata"};
  const uint32_t flags[COFF_SECTIONS] = {
    0x60500020u, /* code, execute, read, 16-byte aligned */
    0x40400040u, /* initialized data, read, 8-byte aligned */
    0xc0400040u, /* initialized data, read, write */
    0x40400040u,
    0x40300040u, /* .xdata: initialized data, read, 4-byte aligned */
    0x40300040u};
  const Elf64_Rela *relocations[COFF_SECTIONS] = {ctx->relocations, NULL, NULL, ctx->constant_relocations, NULL, table_relocations};
  size_t relocation_counts[COFF_SECTIONS] = {ctx->relocation_count, 0, 0, ctx->constant_relocation_count, 0, 3 * (size_t)frames};

  size_t header = 20 + 40 * COFF_SECTIONS, cursor = header, raw[COFF_SECTIONS], relocation_at[COFF_SECTIONS];
  for (unsigned i = 0; i < COFF_SECTIONS; ++i) {
    raw[i] = cursor = (cursor + 15) & ~(size_t)15; cursor += contents[i]->n;
    /* Over 65535 relocations: the count moves into an extra first entry. */
    size_t entries = relocation_counts[i] + (relocation_counts[i] > 0xfffe);
    relocation_at[i] = cursor; cursor += 10 * entries;
  }
  size_t symbol_table = cursor, string_size = 4;
  for (unsigned i = section_symbols; i < symbol_count; ++i) {
    size_t length = strlen(strings + symbols[i].st_name);
    if (length > 8) string_size += length + 1;
  }
  bool ok = true;
  size_t total = symbol_table + 18 * (size_t)coff_count + string_size;
  if (total > LIMIT || xdata.failed || pdata.failed) ok = false;
  unsigned char *data = ok ? calloc(total, 1) : NULL;
  if (!data) {
    free(symbol_map); free(table_relocations); free(xdata.data); free(pdata.data);
    return false;
  }

  put16(data, 0x8664); put16(data + 2, COFF_SECTIONS);
  put32(data + 8, (uint32_t)symbol_table); put32(data + 12, coff_count);
  for (unsigned i = 0; i < COFF_SECTIONS && ok; ++i) {
    unsigned char *h = data + 20 + 40 * i;
    memcpy(h, names[i], strlen(names[i]));
    put32(h + 16, (uint32_t)contents[i]->n); put32(h + 20, contents[i]->n ? (uint32_t)raw[i] : 0);
    if (contents[i]->n) memcpy(data + raw[i], contents[i]->data, contents[i]->n);
    size_t count = relocation_counts[i];
    uint32_t characteristics = flags[i];
    if (count) {
      unsigned char *out = data + relocation_at[i];
      put32(h + 24, (uint32_t)relocation_at[i]);
      if (count > 0xfffe) {
        characteristics |= 0x01000000u; /* IMAGE_SCN_LNK_NRELOC_OVFL */
        put16(h + 32, 0xffff); put32(out, (uint32_t)(count + 1)); out += 10;
      } else put16(h + 32, (uint16_t)count);
      ok = coff_relocations(relocations[i], count, data + raw[i], contents[i]->n,
                           i == COFF_PDATA - 1 ? NULL : symbol_map, symbol_count, out);
    }
    put32(h + 36, characteristics);
  }

  unsigned char *table = data + symbol_table, *string_table = table + 18 * (size_t)coff_count;
  size_t string_at = 4;
  for (unsigned i = 0; i < COFF_SECTIONS; ++i) {
    unsigned char *entry = table + 18 * i;
    memcpy(entry, names[i], strlen(names[i])); put16(entry + 12, (uint16_t)(i + 1));
    entry[16] = 3; /* IMAGE_SYM_CLASS_STATIC */
  }
  for (unsigned i = section_symbols; i < symbol_count && ok; ++i) {
    const Elf64_Sym *symbol = &symbols[i];
    unsigned char *entry = table + 18 * (size_t)symbol_map[i];
    const char *name = strings + symbol->st_name;
    size_t length = strlen(name);
    if (length <= 8) memcpy(entry, name, length);
    else { put32(entry + 4, (uint32_t)string_at); memcpy(string_table + string_at, name, length + 1); string_at += length + 1; }
    int section = coff_section(symbol->st_shndx);
    if (symbol->st_shndx != SHN_UNDEF && !section) { ok = false; break; }
    put32(entry + 8, (uint32_t)symbol->st_value); put16(entry + 12, (uint16_t)section);
    put16(entry + 14, (symbol->st_info & 0xf) == STT_FUNC ? 0x20 : 0);
    entry[16] = ELF64_ST_BIND(symbol->st_info) == STB_GLOBAL ? 2 : 3; /* EXTERNAL or STATIC */
  }
  put32(string_table, (uint32_t)string_size);
  if (ok) ok = backend_write_object(path, data, total);
  free(data); free(symbol_map); free(table_relocations); free(xdata.data); free(pdata.data);
  return ok;
}
