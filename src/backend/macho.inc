/* Mach-O (AArch64 macOS) object writer, included by driver.c.

   Like the COFF writer it maps the emitter's ELF-form symbols and relocations.
   Section addresses are laid out from zero, so DWARF needs no relocations: its
   text addresses and section offsets are written in place, and the linker's
   debug map relates them to the executable. Sections: __TEXT,__text,
   __TEXT,__const (string literals), __DATA,__bss (mutable globals),
   __DATA,__const (constant globals) and the __DWARF sections. */

enum { MACHO_TEXT, MACHO_RODATA, MACHO_DATA, MACHO_CONSTANTS, MACHO_INIT, MACHO_DEBUG };
enum { ARM64_RELOC_UNSIGNED = 0, ARM64_RELOC_BRANCH26 = 2, ARM64_RELOC_PAGE21 = 3, ARM64_RELOC_PAGEOFF12 = 4,
       ARM64_RELOC_GOT_LOAD_PAGE21 = 5, ARM64_RELOC_GOT_LOAD_PAGEOFF12 = 6, ARM64_RELOC_ADDEND = 10 };

static uint32_t macho_relocation_info(unsigned symbol, bool pcrel, unsigned length, bool external, unsigned type) {
  return (symbol & 0xffffff) | (uint32_t)pcrel << 24 | length << 25 | (uint32_t)external << 27 | type << 28;
}

/* Count (out == NULL) or write the Mach-O entries for one section's relocations.
   Every reference is external: section-relative references use the local
   symbol placed at that section's start. */
static bool macho_relocations(bool a64, const Elf64_Rela *items, size_t count, unsigned char *bytes, size_t size,
                              const unsigned *symbol_map, unsigned symbol_count, unsigned char *out, size_t *written) {
  size_t n = 0;
  for (size_t i = 0; i < count; ++i) {
    const Elf64_Rela *r = &items[i];
    unsigned symbol = (unsigned)ELF64_R_SYM(r->r_info), type = (unsigned)ELF64_R_TYPE(r->r_info);
    if (symbol >= symbol_count || r->r_offset > INT32_MAX) return false;
    unsigned kind, length = 2; bool pcrel = false; int64_t addend = r->r_addend;
    if (!a64) {
      switch (type) {
      case R_X86_64_64: kind=0; length=3; break;
      case R_X86_64_PC32: kind=1; pcrel=true; addend+=4; break;
      case R_X86_64_PLT32: kind=2; pcrel=true; addend+=4; break;
      case R_X86_64_GOTPCREL: kind=3; pcrel=true; addend+=4; break;
      default: return false;
      }
      if (r->r_offset + (length==3?8:4) > size) return false;
      if (out) {
        if (length==3) put64(bytes+r->r_offset,(uint64_t)addend);
        else put32(bytes+r->r_offset,(uint32_t)addend);
      }
      addend=0;
    } else switch (type) {
    case R_AARCH64_ABS64:
      if (r->r_offset + 8 > size) return false;
      if (out) put64(bytes + r->r_offset, (uint64_t)addend);
      kind = ARM64_RELOC_UNSIGNED; length = 3; addend = 0; break;
    case R_AARCH64_CALL26: kind = ARM64_RELOC_BRANCH26; pcrel = true; break;
    case R_AARCH64_ADR_PREL_PG_HI21: kind = ARM64_RELOC_PAGE21; pcrel = true; break;
    case R_AARCH64_ADD_ABS_LO12_NC: kind = ARM64_RELOC_PAGEOFF12; break;
    case R_AARCH64_ADR_GOT_PAGE: kind = ARM64_RELOC_GOT_LOAD_PAGE21; pcrel = true; break;
    case R_AARCH64_LD64_GOT_LO12_NC: kind = ARM64_RELOC_GOT_LOAD_PAGEOFF12; break;
    default: return false;
    }
    if (addend) {
      /* A preceding ADDEND entry carries a signed 24-bit addend for page references. */
      if ((kind != ARM64_RELOC_PAGE21 && kind != ARM64_RELOC_PAGEOFF12) || addend < -0x800000 || addend > 0x7fffff) return false;
      if (out) {
        put32(out + 8 * n, (uint32_t)r->r_offset);
        put32(out + 8 * n + 4, macho_relocation_info((unsigned)addend, false, 2, false, ARM64_RELOC_ADDEND));
      }
      ++n;
    }
    if (out) {
      put32(out + 8 * n, (uint32_t)r->r_offset);
      put32(out + 8 * n + 4, macho_relocation_info(symbol_map[symbol], pcrel, length, true, kind));
    }
    ++n;
  }
  *written = n;
  return true;
}

static bool write_macho(BackendContext *ctx, const char *path, const Elf64_Sym *symbols, unsigned symbol_count,
                        const char *strings, BackendDwarfOutput *debug) {
  bool dwarf = ctx->dwarf != NULL;
  unsigned section_count = MACHO_DEBUG + (dwarf ? BACKEND_DWARF_SECTION_COUNT : 0);
  uint64_t initialize=0;
  Elf64_Rela initializer={.r_info=ELF64_R_INFO(ctx->initializer_symbol,ctx->a64?R_AARCH64_ABS64:R_X86_64_64)};
  const void *contents[MACHO_DEBUG + BACKEND_DWARF_SECTION_COUNT] = {ctx->text.data, ctx->rodata.data, ctx->globals_data.data, ctx->constants_data.data, &initialize};
  size_t sizes[MACHO_DEBUG + BACKEND_DWARF_SECTION_COUNT] = {ctx->text.n, ctx->rodata.n, ctx->globals_data.n, ctx->constants_data.n, ctx->initializer_symbol?8:0};
  const char *section_names[][2] = {{"__text", "__TEXT"}, {"__const", "__TEXT"}, {"__bss", "__DATA"}, {"__const", "__DATA"}, {"__mod_init_func", "__DATA"},
                                    {"__debug_info", "__DWARF"}, {"__debug_abbrev", "__DWARF"}, {"__debug_line", "__DWARF"}, {"__debug_frame", "__DWARF"}};
  for (unsigned i = 0; dwarf && i < BACKEND_DWARF_SECTION_COUNT; ++i) {
    contents[MACHO_DEBUG + i] = debug->sections[i].data; sizes[MACHO_DEBUG + i] = debug->sections[i].size;
  }

  /* nlist order: locals, defined externals, undefined externals. ELF symbol 1
     (the .rodata section symbol) becomes a local at the start of __TEXT,__const. */
  unsigned *symbol_map = calloc(symbol_count, sizeof(*symbol_map));
  unsigned *order = calloc(symbol_count, sizeof(*order));
  if (!symbol_map || !order) { free(symbol_map); free(order); return false; }
  unsigned first = ctx->dwarf ? 7 : 2, nsyms = 0, locals, defined;
  order[nsyms++] = 1;
  for (unsigned i = first; i < symbol_count; ++i) if (ELF64_ST_BIND(symbols[i].st_info) == STB_LOCAL) order[nsyms++] = i;
  locals = nsyms;
  for (unsigned i = first; i < symbol_count; ++i)
    if (ELF64_ST_BIND(symbols[i].st_info) != STB_LOCAL && symbols[i].st_shndx != SHN_UNDEF) order[nsyms++] = i;
  defined = nsyms - locals;
  for (unsigned i = first; i < symbol_count; ++i)
    if (ELF64_ST_BIND(symbols[i].st_info) != STB_LOCAL && symbols[i].st_shndx == SHN_UNDEF) order[nsyms++] = i;
  for (unsigned i = 0; i < nsyms; ++i) symbol_map[order[i]] = i;

  /* Zero-fill storage belongs at the VM tail and consumes no file bytes. */
  uint64_t address[MACHO_DEBUG + BACKEND_DWARF_SECTION_COUNT], vm = 0;
  for (unsigned i = 0; i < section_count; ++i) {
    if (i == MACHO_DATA) continue;
    uint64_t alignment = i == MACHO_TEXT && ctx->function_alignment ? ctx->function_alignment : i == MACHO_CONSTANTS ? 16 : 8;
    vm = (vm + alignment - 1) & ~(alignment - 1); address[i] = vm; vm += sizes[i];
  }
  vm = (vm + 15) & ~(uint64_t)15; address[MACHO_DATA] = vm; vm += sizes[MACHO_DATA];
  size_t commands = 72 + 80 * (size_t)section_count + 24 + 24 + 80;
  size_t cursor = 32 + commands, offsets[MACHO_DEBUG + BACKEND_DWARF_SECTION_COUNT];
  size_t data_start = (cursor + 15) & ~(size_t)15;
  cursor = data_start;
  for (unsigned i = 0; i < section_count; ++i) {
    if (i == MACHO_DATA) { offsets[i] = 0; continue; }
    size_t alignment = i == MACHO_TEXT && ctx->function_alignment ? ctx->function_alignment : i == MACHO_CONSTANTS ? 16 : 8;
    cursor = (cursor + alignment - 1) & ~(alignment - 1); offsets[i] = cursor; cursor += sizes[i];
  }
  size_t data_end = cursor;
  const Elf64_Rela *relocations[3] = {ctx->relocations, ctx->constant_relocations, &initializer};
  size_t relocation_counts[3] = {ctx->relocation_count, ctx->constant_relocation_count, ctx->initializer_symbol?1:0}, entries[3], relocation_at[3];
  unsigned relocated[3] = {MACHO_TEXT, MACHO_CONSTANTS, MACHO_INIT};
  bool ok = true;
  for (unsigned i = 0; i < 3 && ok; ++i) {
    ok = macho_relocations(ctx->a64, relocations[i], relocation_counts[i], NULL, sizes[relocated[i]], symbol_map, symbol_count, NULL, &entries[i]);
    cursor = (cursor + 7) & ~(size_t)7; relocation_at[i] = cursor; cursor += 8 * entries[i];
  }
  size_t symbol_at = (cursor + 7) & ~(size_t)7, string_at = symbol_at + 16 * (size_t)nsyms, string_size = 2;
  for (unsigned i = 1; i < nsyms; ++i) string_size += strlen(strings + symbols[order[i]].st_name) + 2;
  string_size += sizeof("ltmp_rodata");
  size_t total = string_at + string_size;
  unsigned char *data = ok && total <= LIMIT ? calloc(total, 1) : NULL;
  if (!data) { free(symbol_map); free(order); return false; }

  unsigned char *h = data;
  put32(h, 0xfeedfacfu); put32(h + 4, ctx->a64 ? 0x0100000cu : 0x01000007u); put32(h + 8, ctx->a64 ? 0 : 3); /* MH_MAGIC_64, CPU_TYPE_ARM64 */
  put32(h + 12, 1); put32(h + 16, 4); put32(h + 20, (uint32_t)commands); /* MH_OBJECT, four commands */
  unsigned char *c = data + 32;
  put32(c, 0x19); put32(c + 4, (uint32_t)(72 + 80 * section_count)); /* LC_SEGMENT_64 */
  put64(c + 32, vm); put64(c + 40, data_start); put64(c + 48, data_end - data_start);
  put32(c + 56, 7); put32(c + 60, 7); put32(c + 64, section_count);
  unsigned text_alignment = 2;
  if (ctx->function_alignment) {
    text_alignment = 0;
    for (unsigned alignment = ctx->function_alignment; alignment > 1; alignment >>= 1) ++text_alignment;
  }
  for (unsigned i = 0; i < section_count; ++i) {
    unsigned char *s = c + 72 + 80 * i;
    memcpy(s, section_names[i][0], strlen(section_names[i][0])); memcpy(s + 16, section_names[i][1], strlen(section_names[i][1]));
    put64(s + 32, address[i]); put64(s + 40, sizes[i]); put32(s + 48, (uint32_t)offsets[i]);
    put32(s + 52, i == MACHO_TEXT ? text_alignment : i >= MACHO_DEBUG ? 0 :
                         (i == MACHO_DATA || i == MACHO_CONSTANTS) ? 4 : 3);
    put32(s + 64, i == MACHO_TEXT ? 0x80000400u : i == MACHO_INIT ? 9u : i == MACHO_DATA ? 1u : i >= MACHO_DEBUG ? 0x02000000u : 0); /* instructions; debug */
    for (unsigned k = 0; k < 3; ++k) if (relocated[k] == i && entries[k]) { put32(s + 56, (uint32_t)relocation_at[k]); put32(s + 60, (uint32_t)entries[k]); }
    if (sizes[i] && i != MACHO_DATA) memcpy(data + offsets[i], contents[i], sizes[i]);
  }
  c += 72 + 80 * section_count;
  put32(c, 0x32); put32(c + 4, 24); put32(c + 8, 1); put32(c + 12, 0x000f0000); /* LC_BUILD_VERSION macOS 15.0 */
  c += 24;
  put32(c, 0x2); put32(c + 4, 24); put32(c + 8, (uint32_t)symbol_at); put32(c + 12, nsyms);
  put32(c + 16, (uint32_t)string_at); put32(c + 20, (uint32_t)string_size); /* LC_SYMTAB */
  c += 24;
  put32(c, 0xb); put32(c + 4, 80); put32(c + 8, 0); put32(c + 12, locals); /* LC_DYSYMTAB */
  put32(c + 16, locals); put32(c + 20, defined); put32(c + 24, locals + defined); put32(c + 28, nsyms - locals - defined);

  for (unsigned i = 0; i < 3 && ok; ++i) {
    size_t written;
    ok = macho_relocations(ctx->a64, relocations[i], relocation_counts[i], data + offsets[relocated[i]], sizes[relocated[i]],
                           symbol_map, symbol_count, data + relocation_at[i], &written);
  }
  /* DWARF: resolve every relocation in place (text starts at address zero). */
  for (size_t i = 0; dwarf && ok && i < debug->relocation_count; ++i) {
    const BackendDwarfRelocation *r = &debug->relocations[i];
    unsigned bytes = r->type == R_X86_64_64 ? 8 : 4;
    if (r->offset + bytes > sizes[MACHO_DEBUG + r->section]) { ok = false; break; }
    unsigned char *at = data + offsets[MACHO_DEBUG + r->section] + r->offset;
    uint64_t value = (uint64_t)r->addend + (r->target == BACKEND_DWARF_TEXT ? address[MACHO_TEXT] : 0);
    if (bytes == 8) put64(at, value); else put32(at, (uint32_t)value);
  }

  unsigned char *table = data + symbol_at; char *names = (char *)data + string_at;
  size_t name = 2; /* index 0 and 1 hold " " and the empty string, as ld64 output does */
  names[0] = ' ';
  for (unsigned i = 0; i < nsyms && ok; ++i) {
    unsigned char *entry = table + 16 * i;
    const Elf64_Sym *symbol = &symbols[order[i]];
    const char *text = i ? strings + symbol->st_name : "ltmp_rodata";
    size_t length = strlen(text);
    put32(entry, (uint32_t)name);
    /* C symbols carry a leading underscore on Darwin; the section label does not. */
    if (i) names[name++] = '_';
    memcpy(names + name, text, length + 1); name += length + 1;
    if (!i) { entry[4] = 0x0e; entry[5] = MACHO_RODATA + 1; put64(entry + 8, address[MACHO_RODATA]); continue; }
    int section = symbol->st_shndx == 1 ? MACHO_TEXT : symbol->st_shndx == 2 ? MACHO_RODATA
                : symbol->st_shndx == 8 ? MACHO_DATA : symbol->st_shndx == 11 ? MACHO_CONSTANTS : -1;
    bool external = ELF64_ST_BIND(symbol->st_info) != STB_LOCAL;
    if (symbol->st_shndx == SHN_UNDEF) { entry[4] = 0x01; continue; } /* N_UNDF | N_EXT */
    if (section < 0) { ok = false; break; }
    entry[4] = (unsigned char)(0x0e | external | (external && symbol->st_other == 2 ? 0x10 : 0)); entry[5] = (unsigned char)(section + 1); /* N_SECT */
    put64(entry + 8, address[section] + symbol->st_value);
  }
  if (ok) ok = backend_write_object(path, data, total);
  free(data); free(symbol_map); free(order);
  return ok;
}
