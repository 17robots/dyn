/* Symbolic WebAssembly stack assembly from the same lowered bodies as objects.
   The assembly dialect is accepted by the WebAssembly integrated assembler;
   emission itself invokes no external tool. */
#include <inttypes.h>
#include <stdarg.h>

typedef struct {
  const unsigned char *p;
  size_t at, end;
  WG *g;
} WARead;
static uint64_t wa_unsigned(WARead *r) {
  uint64_t v = 0;
  unsigned shift = 0;
  while (r->at < r->end && shift < 64) {
    unsigned c = r->p[r->at++];
    v |= (uint64_t)(c & 127) << shift;
    if (!(c & 128))
      return v;
    shift += 7;
  }
  r->g->failed = true;
  return 0;
}
static int64_t wa_signed(WARead *r) {
  uint64_t v = 0;
  unsigned shift = 0, c = 0;
  do {
    if (r->at >= r->end || shift >= 64) {
      r->g->failed = true;
      return 0;
    }
    c = r->p[r->at++];
    v |= (uint64_t)(c & 127) << shift;
    shift += 7;
  } while (c & 128);
  if (shift < 64 && (c & 64))
    v |= UINT64_MAX << shift;
  return (int64_t)v;
}
static void wa_print(WB *out, const char *format, ...) {
  va_list a, b;
  va_start(a, format);
  va_copy(b, a);
  int count = vsnprintf(NULL, 0, format, a);
  va_end(a);
  if (count < 0) {
    va_end(b);
    allocation_failure();
  }
  char *text = malloc((size_t)count + 1);
  vsnprintf(text, (size_t)count + 1, format, b);
  va_end(b);
  wn(out, text, (size_t)count);
  free(text);
}
static const char *wa_type(unsigned type) {
  return type == 0x7f   ? "i32"
         : type == 0x7e ? "i64"
         : type == 0x7d ? "f32"
         : type == 0x7c ? "f64"
                        : NULL;
}
static void wa_signature(WG *g, WB *out, unsigned index) {
  WARead r = {g->types.p, 0, g->types.n, g};
  for (unsigned i = 0; i <= index && !g->failed; ++i) {
    if (r.at >= r.end || r.p[r.at++] != 0x60) {
      g->failed = true;
      return;
    }
    unsigned n = (unsigned)wa_unsigned(&r);
    if (i == index)
      wa_print(out, "(");
    for (unsigned j = 0; j < n; ++j) {
      const char *type = r.at < r.end ? wa_type(r.p[r.at++]) : NULL;
      if (!type) {
        g->failed = true;
        return;
      }
      if (i == index)
        wa_print(out, "%s%s", j ? ", " : "", type);
    }
    if (i == index)
      wa_print(out, ") -> (");
    n = (unsigned)wa_unsigned(&r);
    for (unsigned j = 0; j < n; ++j) {
      const char *type = r.at < r.end ? wa_type(r.p[r.at++]) : NULL;
      if (!type) {
        g->failed = true;
        return;
      }
      if (i == index)
        wa_print(out, "%s%s", j ? ", " : "", type);
    }
    if (i == index)
      wa_print(out, ")");
  }
}
static const WR *wa_relocation(WG *g, size_t offset) {
  for (size_t i = 0; i < g->relocs.n; ++i)
    if (g->relocs.p[i].offset == offset)
      return &g->relocs.p[i];
  return NULL;
}
static void wa_symbol(WG *g, WB *out, const WR *relocation) {
  if (!relocation || relocation->symbol >= g->ns) {
    g->failed = true;
    return;
  }
  wa_print(out, "%s", g->symbols[relocation->symbol].name);
  if (relocation->addend)
    wa_print(out, "%+" PRId32, relocation->addend);
}
static const char *wa_numeric(unsigned opcode) {
  static const char *const names[] = {"i32.eqz",
                                      "i32.eq",
                                      "i32.ne",
                                      "i32.lt_s",
                                      "i32.lt_u",
                                      "i32.gt_s",
                                      "i32.gt_u",
                                      "i32.le_s",
                                      "i32.le_u",
                                      "i32.ge_s",
                                      "i32.ge_u",
                                      "i64.eqz",
                                      "i64.eq",
                                      "i64.ne",
                                      "i64.lt_s",
                                      "i64.lt_u",
                                      "i64.gt_s",
                                      "i64.gt_u",
                                      "i64.le_s",
                                      "i64.le_u",
                                      "i64.ge_s",
                                      "i64.ge_u",
                                      "f32.eq",
                                      "f32.ne",
                                      "f32.lt",
                                      "f32.gt",
                                      "f32.le",
                                      "f32.ge",
                                      "f64.eq",
                                      "f64.ne",
                                      "f64.lt",
                                      "f64.gt",
                                      "f64.le",
                                      "f64.ge",
                                      "i32.clz",
                                      "i32.ctz",
                                      "i32.popcnt",
                                      "i32.add",
                                      "i32.sub",
                                      "i32.mul",
                                      "i32.div_s",
                                      "i32.div_u",
                                      "i32.rem_s",
                                      "i32.rem_u",
                                      "i32.and",
                                      "i32.or",
                                      "i32.xor",
                                      "i32.shl",
                                      "i32.shr_s",
                                      "i32.shr_u",
                                      "i32.rotl",
                                      "i32.rotr",
                                      "i64.clz",
                                      "i64.ctz",
                                      "i64.popcnt",
                                      "i64.add",
                                      "i64.sub",
                                      "i64.mul",
                                      "i64.div_s",
                                      "i64.div_u",
                                      "i64.rem_s",
                                      "i64.rem_u",
                                      "i64.and",
                                      "i64.or",
                                      "i64.xor",
                                      "i64.shl",
                                      "i64.shr_s",
                                      "i64.shr_u",
                                      "i64.rotl",
                                      "i64.rotr",
                                      "f32.abs",
                                      "f32.neg",
                                      "f32.ceil",
                                      "f32.floor",
                                      "f32.trunc",
                                      "f32.nearest",
                                      "f32.sqrt",
                                      "f32.add",
                                      "f32.sub",
                                      "f32.mul",
                                      "f32.div",
                                      "f32.min",
                                      "f32.max",
                                      "f32.copysign",
                                      "f64.abs",
                                      "f64.neg",
                                      "f64.ceil",
                                      "f64.floor",
                                      "f64.trunc",
                                      "f64.nearest",
                                      "f64.sqrt",
                                      "f64.add",
                                      "f64.sub",
                                      "f64.mul",
                                      "f64.div",
                                      "f64.min",
                                      "f64.max",
                                      "f64.copysign",
                                      "i32.wrap_i64",
                                      "i32.trunc_f32_s",
                                      "i32.trunc_f32_u",
                                      "i32.trunc_f64_s",
                                      "i32.trunc_f64_u",
                                      "i64.extend_i32_s",
                                      "i64.extend_i32_u",
                                      "i64.trunc_f32_s",
                                      "i64.trunc_f32_u",
                                      "i64.trunc_f64_s",
                                      "i64.trunc_f64_u",
                                      "f32.convert_i32_s",
                                      "f32.convert_i32_u",
                                      "f32.convert_i64_s",
                                      "f32.convert_i64_u",
                                      "f32.demote_f64",
                                      "f64.convert_i32_s",
                                      "f64.convert_i32_u",
                                      "f64.convert_i64_s",
                                      "f64.convert_i64_u",
                                      "f64.promote_f32",
                                      "i32.reinterpret_f32",
                                      "i64.reinterpret_f64",
                                      "f32.reinterpret_i32",
                                      "f64.reinterpret_i64",
                                      "i32.extend8_s",
                                      "i32.extend16_s",
                                      "i64.extend8_s",
                                      "i64.extend16_s",
                                      "i64.extend32_s"};
  return opcode >= 0x45 && opcode - 0x45 < sizeof(names) / sizeof(*names)
             ? names[opcode - 0x45]
             : NULL;
}
static void wa_body(WG *g, WB *out, WARead *r, const WSym *symbol,
                    unsigned type) {
  uint64_t size = wa_unsigned(r);
  if (size > r->end - r->at) {
    g->failed = true;
    return;
  }
  size_t end = r->at + (size_t)size;
  wa_print(out, "\n.section .text.%s,\"\",@\n.globl %s\n.type %s,@function\n",
           symbol->name, symbol->name, symbol->name);
  if (symbol->flags & 0x20)
    wa_print(out, ".export_name %s, %s\n", symbol->name, symbol->name);
  wa_print(out, "%s:\n.functype %s ", symbol->name, symbol->name);
  wa_signature(g, out, type);
  wa_print(out, "\n");
  unsigned groups = (unsigned)wa_unsigned(r), locals = 0;
  for (unsigned i = 0; i < groups; ++i) {
    unsigned count = (unsigned)wa_unsigned(r);
    const char *name = r->at < end ? wa_type(r->p[r->at++]) : NULL;
    if (!name) {
      g->failed = true;
      return;
    }
    for (unsigned j = 0; j < count; ++j)
      wa_print(out, "%s%s", locals++ ? ", " : ".local ", name);
  }
  if (locals)
    wa_print(out, "\n");
  unsigned blocks[1024], depth = 0;
  static const char *const memory[] = {
      "i32.load",     "i64.load",     "f32.load",     "f64.load",
      "i32.load8_s",  "i32.load8_u",  "i32.load16_s", "i32.load16_u",
      "i64.load8_s",  "i64.load8_u",  "i64.load16_s", "i64.load16_u",
      "i64.load32_s", "i64.load32_u", "i32.store",    "i64.store",
      "f32.store",    "f64.store",    "i32.store8",   "i32.store16",
      "i64.store8",   "i64.store16",  "i64.store32"};
  while (r->at < end && !g->failed) {
    unsigned opcode = r->p[r->at++];
    const WR *reloc = wa_relocation(g, r->at);
    const char *numeric = wa_numeric(opcode);
    if (numeric) {
      wa_print(out, "\t%s\n", numeric);
      continue;
    }
    if (opcode == 0 || opcode == 1 || opcode == 5 || opcode == 0x0f ||
        opcode == 0x1a || opcode == 0x1b) {
      wa_print(out, "\t%s\n",
               opcode == 0      ? "unreachable"
               : opcode == 1    ? "nop"
               : opcode == 5    ? "else"
               : opcode == 0x0f ? "return"
               : opcode == 0x1a ? "drop"
                                : "select");
    } else if (opcode >= 2 && opcode <= 4) {
      if (depth == 1024 || r->at == end) {
        g->failed = true;
        break;
      }
      blocks[depth++] = opcode;
      unsigned value = r->p[r->at++];
      const char *name = wa_type(value);
      if (value != 0x40 && !name) {
        g->failed = true;
        break;
      }
      wa_print(out, "\t%s%s%s\n",
               opcode == 2   ? "block"
               : opcode == 3 ? "loop"
                             : "if",
               name ? " " : "", name ? name : "");
    } else if (opcode == 0x0b) {
      unsigned block = depth ? blocks[--depth] : 0;
      wa_print(out, "\t%s\n",
               block == 2   ? "end_block"
               : block == 3 ? "end_loop"
               : block == 4 ? "end_if"
                            : "end_function");
      if (!block && r->at != end)
        g->failed = true;
    } else if (opcode == 0x0c || opcode == 0x0d ||
               (opcode >= 0x20 && opcode <= 0x22)) {
      uint64_t value = wa_unsigned(r);
      wa_print(out, "\t%s %" PRIu64 "\n",
               opcode == 0x0c   ? "br"
               : opcode == 0x0d ? "br_if"
               : opcode == 0x20 ? "local.get"
               : opcode == 0x21 ? "local.set"
                                : "local.tee",
               value);
    } else if (opcode == 0x10 || opcode == 0x23 || opcode == 0x24) {
      (void)wa_unsigned(r);
      wa_print(out, "\t%s ",
               opcode == 0x10   ? "call"
               : opcode == 0x23 ? "global.get"
                                : "global.set");
      wa_symbol(g, out, reloc);
      wa_print(out, "\n");
    } else if (opcode == 0x11) {
      (void)wa_unsigned(r);
      unsigned table = (unsigned)wa_unsigned(r);
      if (table || !reloc || reloc->type != 6) {
        g->failed = true;
        break;
      }
      wa_print(out, "\tcall_indirect __indirect_function_table, ");
      wa_signature(g, out, reloc->symbol);
      wa_print(out, "\n");
    } else if (opcode >= 0x28 && opcode <= 0x3e) {
      uint64_t alignment = wa_unsigned(r), offset_ = wa_unsigned(r);
      wa_print(out, "\t%s %" PRIu64 ":p2align=%" PRIu64 "\n",
               memory[opcode - 0x28], offset_, alignment);
    } else if (opcode == 0x3f || opcode == 0x40) {
      if (wa_unsigned(r))
        g->failed = true;
      wa_print(out, "\t%s 0\n", opcode == 0x3f ? "memory.size" : "memory.grow");
    } else if (opcode == 0x41 || opcode == 0x42) {
      int64_t value = wa_signed(r);
      wa_print(out, "\t%s.const ", opcode == 0x41 ? "i32" : "i64");
      if (reloc)
        wa_symbol(g, out, reloc);
      else
        wa_print(out, "%" PRId64, value);
      wa_print(out, "\n");
    } else if (opcode == 0x43 || opcode == 0x44) {
      unsigned bytes = opcode == 0x43 ? 4 : 8;
      if (bytes > end - r->at) {
        g->failed = true;
        break;
      }
      uint64_t bits = 0;
      for (unsigned i = 0; i < bytes; ++i)
        bits |= (uint64_t)r->p[r->at++] << (8 * i);
      /* Integer reinterpretation preserves every NaN payload and signed zero,
         independent of host printf floating-point spellings or locale. */
      if (bytes == 4)
        wa_print(out, "\ti32.const %" PRId32 "\n\tf32.reinterpret_i32\n",
                 (int32_t)bits);
      else
        wa_print(out, "\ti64.const %" PRId64 "\n\tf64.reinterpret_i64\n",
                 (int64_t)bits);
    } else if (opcode == 0xfc) {
      uint64_t sub = wa_unsigned(r);
      if (sub == 10) {
        if (wa_unsigned(r) || wa_unsigned(r))
          g->failed = true;
        wa_print(out, "\tmemory.copy 0, 0\n");
      } else if (sub == 11) {
        if (wa_unsigned(r))
          g->failed = true;
        wa_print(out, "\tmemory.fill 0\n");
      } else
        g->failed = true;
    } else
      g->failed = true;
  }
  if (depth || r->at != end)
    g->failed = true;
}
static bool wasm_assembly_write(WG *g, const char *path, unsigned init_type) {
  WB out = {0};
  wa_print(
      &out,
      "# Dyn independent WebAssembly assembly\n.tabletype "
      "__indirect_function_table, funcref\n.globaltype __stack_pointer, i32\n");
  for (size_t i = 0; i < g->ir->function_count; ++i) {
    const DynIrFunction *f = &g->ir->functions[i];
    if (f->generic && !f->instance)
      continue;
    wa_print(&out, ".functype %s ", g->symbols[g->fn_symbol[i]].name);
    wa_signature(g, &out, g->fn_type[i]);
    wa_print(&out, "\n");
  }
  wa_print(&out, ".functype dyn_initialize () -> ()\n");
  WARead r = {g->code.p, 0, g->code.n, g};
  (void)wa_unsigned(&r);
  for (size_t i = 0; i < g->ir->function_count && !g->failed; ++i) {
    const DynIrFunction *f = &g->ir->functions[i];
    if (f->foreign || (f->generic && !f->instance))
      continue;
    wa_body(g, &out, &r, &g->symbols[g->fn_symbol[i]], g->fn_type[i]);
  }
  if (!g->failed)
    wa_body(g, &out, &r, &g->symbols[g->init_symbol], init_type);
  wa_print(&out, "\n.section .data.dyn,\"\",@\n.p2align 4\n");
  size_t pos = 0;
  for (size_t i = 0; i <= g->ns; ++i) {
    const WSym *s = i < g->ns ? &g->symbols[i] : NULL;
    if (s && (s->kind != 1 || (s->flags & 0x10)))
      continue;
    size_t stop = s ? s->offset : g->data.n;
    if (stop < pos || stop > g->data.n) {
      g->failed = true;
      break;
    }
    while (pos < stop) {
      wa_print(&out, ".ascii \"");
      for (unsigned j = 0; j < 16 && pos < stop; ++j)
        wa_print(&out, "\\%03o", g->data.p[pos++]);
      wa_print(&out, "\"\n");
    }
    if (!s)
      break;
    if (!(s->flags & 2))
      wa_print(&out, ".globl %s\n", s->name);
    wa_print(&out, ".type %s,@object\n%s:\n.size %s,%u\n", s->name, s->name,
             s->name, s->size);
  }
  bool ok = !g->failed && backend_write_object(path, out.p, out.n);
  free(out.p);
  return ok;
}
