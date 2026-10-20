/* COFF (x86-64 Windows) object writer, included by driver.c.

   The emitter records symbols and relocations in ELF form. This writer maps
   them onto four COFF sections and moves RELA addends into the relocated bytes,
   as COFF requires. Sections: .text, .rdata (string literals), .data (mutable
   globals), .rdata (constant globals, which carry ADDR64 relocations), the
   .xdata/.pdata unwind tables Windows needs to walk native frames, and, with
   debug info, DWARF sections as MinGW toolchains and LLVM's own Windows debug
   builds use. */

enum { COFF_TEXT = 1, COFF_RODATA, COFF_DATA, COFF_CONSTANTS, COFF_XDATA, COFF_PDATA, COFF_DEBUG, COFF_SECTION_LIMIT = COFF_DEBUG + BACKEND_DWARF_SECTION_COUNT - 1 };
enum { DYN_COFF_REL_AMD64_ADDR64 = 1, DYN_COFF_REL_AMD64_ADDR32NB = 3, DYN_COFF_REL_AMD64_REL32 = 4, DYN_COFF_REL_AMD64_SECREL = 11 };

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
   into `bytes`. A null symbol_map means the symbols are already COFF section
   symbols; there R_X86_64_32 is a section offset and type 0 an image-relative
   address. Returns false for a relocation COFF cannot express. */
static bool coff_relocations(bool a64, const Elf64_Rela *items, size_t count, unsigned char *bytes, size_t size,
                             const unsigned *symbol_map, unsigned symbol_count, unsigned char *out) {
  for (size_t i = 0; i < count; ++i) {
    const Elf64_Rela *r = &items[i];
    unsigned symbol = (unsigned)ELF64_R_SYM(r->r_info), type = (unsigned)ELF64_R_TYPE(r->r_info);
    if ((symbol_map && symbol >= symbol_count) || r->r_offset > UINT32_MAX) return false;
    unsigned coff;
    if (a64 && symbol_map) {
      uint32_t insn = r->r_offset+4<=size ? (uint32_t)bytes[r->r_offset] | (uint32_t)bytes[r->r_offset+1]<<8 | (uint32_t)bytes[r->r_offset+2]<<16 | (uint32_t)bytes[r->r_offset+3]<<24 : 0;
      switch (type) {
      case R_AARCH64_ABS64:
        if (r->r_offset+8>size) return false;
        put64(bytes+r->r_offset,(uint64_t)r->r_addend); coff=14; break;
      case R_AARCH64_CALL26: coff=3; break;
      case R_AARCH64_ADR_PREL_PG_HI21:
        if (r->r_addend<0 || r->r_addend>0x7fffff) return false;
        insn|=((uint32_t)r->r_addend & 3)<<29 | (((uint32_t)r->r_addend>>2)&0x7ffff)<<5;
        put32(bytes+r->r_offset,insn); coff=4; break;
      case R_AARCH64_ADD_ABS_LO12_NC:
        insn|=((uint32_t)r->r_addend & 0xfff)<<10; put32(bytes+r->r_offset,insn); coff=6; break;
      default: return false;
      }
      put32(out+10*i,(uint32_t)r->r_offset); put32(out+10*i+4,symbol_map[symbol]); put16(out+10*i+8,(uint16_t)coff);
      continue;
    }
    if (!symbol_map && type != R_X86_64_64) {
      if (r->r_offset + 4 > size || (type && type != R_X86_64_32)) return false;
      put32(bytes + r->r_offset, (uint32_t)r->r_addend);
      coff = type ? DYN_COFF_REL_AMD64_SECREL : DYN_COFF_REL_AMD64_ADDR32NB;
    } else if (type == R_X86_64_64) {
      if (r->r_offset + 8 > size) return false;
      put64(bytes + r->r_offset, (uint64_t)r->r_addend); coff = DYN_COFF_REL_AMD64_ADDR64;
    } else if (type == R_X86_64_PC32 || type == R_X86_64_PLT32) {
      /* COFF REL32 is relative to the end of the field; ELF folds that -4 into the addend. */
      int64_t addend = r->r_addend + 4;
      if (r->r_offset + 4 > size || addend < INT32_MIN || addend > INT32_MAX) return false;
      put32(bytes + r->r_offset, (uint32_t)addend); coff = DYN_COFF_REL_AMD64_REL32;
    } else return false;
    if (a64) coff = coff == DYN_COFF_REL_AMD64_ADDR64 ? 14 : coff == DYN_COFF_REL_AMD64_SECREL ? 8 : 2;
    put32(out + 10 * i, (uint32_t)r->r_offset); put32(out + 10 * i + 4, symbol_map ? symbol_map[symbol] : symbol); put16(out + 10 * i + 8, (uint16_t)coff);
  }
  return true;
}

/* UNWIND_INFO for the isa_enter prologue: push rbp; mov rbp, rsp; save RSI/RDI
   in the home area; allocate the frame. Codes are listed last-instruction first. */
static void coff_unwind_info(Bytes *out, const uint32_t frame[4]) {
  uint32_t size = frame[2];
  unsigned char codes[32];
  unsigned n = 0;
  if (size <= 128) { codes[n++] = (unsigned char)frame[1]; codes[n++] = (unsigned char)(2 | (size - 8) / 8 << 4); }
  else if (size <= 524280) {
    codes[n++] = (unsigned char)frame[1]; codes[n++] = 1;
    put16(codes + n, (uint16_t)(size / 8)); n += 2;
  } else {
    codes[n++] = (unsigned char)frame[1]; codes[n++] = 1 | 1 << 4;
    put32(codes + n, size); n += 4;
  }
  /* Home-area saves of RSI, RDI, RBX and R12 (frame[3] bits), each a
     four-byte mov after push rbp; mov rbp, rsp, newest first.
     UWOP_SAVE_NONVOL offsets are eight-byte units above the frame pointer. */
  static const unsigned char registers[] = {6, 7, 3, 12};
  unsigned saved = 0, order[4];
  for (unsigned h = 0; h < 4; ++h) if (frame[3] >> h & 1) order[saved++] = h;
  for (unsigned k = saved; k > 0; --k) {
    unsigned h = order[k - 1];
    codes[n++] = (unsigned char)(4 + 4 * k); codes[n++] = (unsigned char)(4 | registers[h] << 4);
    codes[n++] = (unsigned char)(2 + h); codes[n++] = 0;
  }
  const unsigned char fixed[] = {4, 3, 1, 0 | 5 << 4};
  memcpy(codes + n, fixed, sizeof(fixed)); n += sizeof(fixed);
  unsigned slots = n / 2;
  unsigned char header[4] = {1, (unsigned char)frame[1], (unsigned char)slots, 5};
  coff_append(out, header, 4); coff_append(out, codes, n);
  if (slots & 1) { unsigned char pad[2] = {0}; coff_append(out, pad, 2); }
}

static bool coff_arm_unwind(BackendContext *ctx, Bytes *out, unsigned frame, uint32_t end) {
  const uint32_t *f=ctx->unwind_frames[frame];
  unsigned epilogues=0;
  for (unsigned i=0;i<ctx->arm_epilogue_count;++i) epilogues += ctx->arm_epilogues[i][0]==frame;
  if ((end-f[0])/4 > 0x3ffff || epilogues>65535) { backend_report(ctx,"native backend: Windows ARM64 unwind format limit exceeded (function must be below 1 MiB with at most 65535 epilogues)\n"); return false; }
  Bytes codes={0};
  uint32_t left=f[2], last=left%4080;
  while (left) {
    uint32_t chunk=last?last:4080; last=0;
    unsigned char bytes[3]={0xe3,0,0}; /* store probe has no unwind effect */
    if (chunk<512) { bytes[1]=(unsigned char)(chunk/16); coff_append(&codes,bytes,2); }
    else { bytes[1]=(unsigned char)(0xc0 | (chunk/16)>>8); bytes[2]=(unsigned char)(chunk/16); coff_append(&codes,bytes,3); }
    left-=chunk;
  }
  unsigned char tail[]={0xe1,0x81,0xe4}; /* set_fp; save_fplr_x 16; end */
  coff_append(&codes,tail,sizeof(tail));
  unsigned epilogue_index=(unsigned)codes.n;
  coff_append(&codes,tail,sizeof(tail));
  while (codes.n%4) { unsigned char pad=0xe3; coff_append(&codes,&pad,1); }
  unsigned words=(unsigned)codes.n/4;
  if (words>255 || epilogue_index>1023 || codes.failed) { backend_report(ctx,"native backend: Windows ARM64 unwind instruction record exceeds format capacity\n"); free(codes.data); return false; }
  bool extended=words>31 || epilogues>31;
  unsigned char header[8]={0};
  put32(header,(end-f[0])/4 | (extended?0:epilogues)<<22 | (extended?0:words)<<27);
  if (extended) put32(header+4,epilogues | words<<16);
  coff_append(out,header,extended?8:4);
  for (unsigned i=0;i<ctx->arm_epilogue_count;++i) if (ctx->arm_epilogues[i][0]==frame) {
    unsigned char scope[4]; put32(scope,(ctx->arm_epilogues[i][1]-f[0])/4 | epilogue_index<<22); coff_append(out,scope,4);
  }
  coff_append(out,codes.data,codes.n); free(codes.data); return !out->failed;
}

static bool write_coff(BackendContext *ctx, const char *path, const Elf64_Sym *symbols, unsigned symbol_count, const char *strings,
                       const BackendDwarfOutput *debug) {
  /* COFF symbols: one static symbol per section, then every ELF symbol after the
     section symbols driver.c reserved. */
  /* Null, the .rodata section symbol and, with debug info, the .text and DWARF
     section symbols; COFF section symbols replace them all. */
  unsigned section_symbols = ctx->dwarf ? 7 : 2;
  unsigned section_count = ctx->dwarf ? COFF_SECTION_LIMIT : COFF_PDATA;
  unsigned coff_count = section_count + symbol_count - section_symbols;
  unsigned *symbol_map = calloc(symbol_count, sizeof(*symbol_map));
  if (!symbol_map) return false;
  symbol_map[1] = COFF_RODATA - 1;
  for (unsigned i = section_symbols; i < symbol_count; ++i) symbol_map[i] = section_count + i - section_symbols;

  /* .pdata: {begin, end, unwind info} per function, image-relative. */
  Bytes xdata = {0}, pdata = {0};
  unsigned frames = ctx->unwind_frame_count;
  Elf64_Rela *table_relocations = calloc((ctx->a64?2:3) * (size_t)frames + 1, sizeof(*table_relocations));
  if (!table_relocations) { free(symbol_map); return false; }
  for (unsigned i = 0; i < frames; ++i) {
    const uint32_t *frame = ctx->unwind_frames[i];
    uint32_t entry[3] = {frame[0], i + 1 < frames ? ctx->unwind_frames[i + 1][0] : (uint32_t)ctx->text.n, (uint32_t)xdata.n};
    unsigned fields=ctx->a64?2:3;
    for (unsigned j = 0; j < fields; ++j) {
      bool unwind=j==fields-1;
      table_relocations[fields*i+j]=(Elf64_Rela){.r_offset=4*(size_t)(fields*i+j),
        .r_info=ELF64_R_INFO(unwind?COFF_XDATA-1u:COFF_TEXT-1u,0u), .r_addend=unwind?entry[2]:entry[j]};
    }
    unsigned char zero[12]={0}; coff_append(&pdata,zero,4*fields);
    if (ctx->a64) { if (!coff_arm_unwind(ctx,&xdata,i,entry[1])) { free(table_relocations); free(symbol_map); free(xdata.data); free(pdata.data); return false; } }
    else coff_unwind_info(&xdata, frame);
  }

  const unsigned char *contents[COFF_SECTION_LIMIT] = {ctx->text.data, ctx->rodata.data, ctx->globals_data.data,
    ctx->constants_data.data, xdata.data, pdata.data};
  size_t sizes[COFF_SECTION_LIMIT] = {ctx->text.n, ctx->rodata.n, ctx->globals_data.n, ctx->constants_data.n, xdata.n, pdata.n};
  const char *names[COFF_SECTION_LIMIT] = {".text", ".rdata", ".bss", ".rdata", ".xdata", ".pdata",
    ".debug_info", ".debug_abbrev", ".debug_line", ".debug_frame"};
  uint32_t flags[COFF_SECTION_LIMIT] = {
    0x60500020u, /* code, execute, read, 16-byte aligned */
    0x40400040u, /* initialized data, read, 8-byte aligned */
    0xc0400080u, /* zero-filled data, read, write */
    0x40400040u,
    0x40300040u, /* .xdata: initialized data, read, 4-byte aligned */
    0x40300040u};
  const Elf64_Rela *relocations[COFF_SECTION_LIMIT] = {ctx->relocations, NULL, NULL, ctx->constant_relocations, NULL, table_relocations};
  size_t relocation_counts[COFF_SECTION_LIMIT] = {ctx->relocation_count, 0, 0, ctx->constant_relocation_count, 0, (ctx->a64?2:3) * (size_t)frames};
  /* DWARF relocations name DWARF sections or .text; regroup them per section. */
  Elf64_Rela *debug_relocations = calloc(debug->relocation_count + 1, sizeof(*debug_relocations));
  if (!debug_relocations) { free(symbol_map); free(table_relocations); free(xdata.data); free(pdata.data); return false; }
  for (unsigned i = COFF_DEBUG - 1, at = 0; i < section_count; ++i) {
    const BackendDwarfBytes *section = &debug->sections[i - (COFF_DEBUG - 1)];
    contents[i] = section->data; sizes[i] = section->size;
    flags[i] = 0x42100040u; /* initialized data, discardable, read, 1-byte aligned */
    relocations[i] = debug_relocations + at;
    for (size_t j = 0; j < debug->relocation_count; ++j) {
      const BackendDwarfRelocation *r = &debug->relocations[j];
      if (r->section != i - (COFF_DEBUG - 1)) continue;
      unsigned target = r->target == BACKEND_DWARF_TEXT ? COFF_TEXT : COFF_DEBUG + r->target;
      debug_relocations[at++] = (Elf64_Rela){.r_offset = r->offset, .r_info = ELF64_R_INFO(target - 1u, r->type), .r_addend = r->addend};
      ++relocation_counts[i];
    }
  }

  size_t header = 20 + 40 * section_count, cursor = header, raw[COFF_SECTION_LIMIT], relocation_at[COFF_SECTION_LIMIT];
  for (unsigned i = 0; i < section_count; ++i) {
    raw[i] = cursor = (cursor + 15) & ~(size_t)15;
    if (i != COFF_DATA - 1) cursor += sizes[i];
    else raw[i] = 0;
    /* Over 65535 relocations: the count moves into an extra first entry. */
    size_t entries = relocation_counts[i] + (relocation_counts[i] > 0xfffe);
    relocation_at[i] = cursor; cursor += 10 * entries;
  }
  size_t symbol_table = cursor, string_size = 4;
  for (unsigned i = 0; i < section_count; ++i) if (strlen(names[i]) > 8) string_size += strlen(names[i]) + 1;
  for (unsigned i = section_symbols; i < symbol_count; ++i) {
    size_t length = strlen(strings + symbols[i].st_name);
    if (length > 8) string_size += length + 1;
  }
  bool ok = true;
  size_t total = symbol_table + 18 * (size_t)coff_count + string_size;
  if (total > LIMIT || xdata.failed || pdata.failed) ok = false;
  unsigned char *data = ok ? calloc(total, 1) : NULL;
  if (!data) {
    free(symbol_map); free(table_relocations); free(debug_relocations); free(xdata.data); free(pdata.data);
    return false;
  }

  put16(data, ctx->a64 ? 0xaa64 : 0x8664); put16(data + 2, section_count);
  put32(data + 8, (uint32_t)symbol_table); put32(data + 12, coff_count);
  unsigned char *table = data + symbol_table, *string_table = table + 18 * (size_t)coff_count;
  size_t string_at = 4;
  for (unsigned i = 0; i < section_count && ok; ++i) {
    unsigned char *h = data + 20 + 40 * i, *entry = table + 18 * i;
    size_t length = strlen(names[i]);
    /* Section names over eight bytes live in the string table: "/offset" in the
       header and a string table reference in the section symbol. */
    if (length <= 8) { memcpy(h, names[i], length); memcpy(entry, names[i], length); }
    else {
      snprintf((char *)h, 8, "/%zu", string_at); put32(entry + 4, (uint32_t)string_at);
      memcpy(string_table + string_at, names[i], length + 1); string_at += length + 1;
    }
    put16(entry + 12, (uint16_t)(i + 1));
    entry[16] = 3; /* IMAGE_SYM_CLASS_STATIC */
    put32(h + 16, (uint32_t)sizes[i]); put32(h + 20, sizes[i] ? (uint32_t)raw[i] : 0);
    if (sizes[i] && i != COFF_DATA - 1) memcpy(data + raw[i], contents[i], sizes[i]);
    size_t count = relocation_counts[i];
    uint32_t characteristics = flags[i];
    if (count) {
      unsigned char *out = data + relocation_at[i];
      put32(h + 24, (uint32_t)relocation_at[i]);
      if (count > 0xfffe) {
        characteristics |= 0x01000000u; /* IMAGE_SCN_LNK_NRELOC_OVFL */
        put16(h + 32, 0xffff); put32(out, (uint32_t)(count + 1)); out += 10;
      } else put16(h + 32, (uint16_t)count);
      ok = coff_relocations(ctx->a64, relocations[i], count, data + raw[i], sizes[i],
                           i >= COFF_PDATA - 1 ? NULL : symbol_map, symbol_count, out);
    }
    put32(h + 36, characteristics);
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
  free(data); free(symbol_map); free(table_relocations); free(debug_relocations); free(xdata.data); free(pdata.data);
  return ok;
}
