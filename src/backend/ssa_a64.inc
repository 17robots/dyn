/* AArch64 emission for SSA code generation (included by ssa.inc).

   Register ids follow ssa.inc: 0-31 are x0-x31 and X_XMM0 + n is vn. The
   emitter's scratch registers are x14-x17 and v29/v30/v31; the allocator never
   assigns them. Frame memory and spill slots sit below x29. */

enum { A_S1 = 16, A_S2 = 17, A_S3 = 15, A_S4 = 14, A_ZR = 31, A_F1 = 31, A_F2 = 30, A_F3 = 29 };

static bool a64s_floating(unsigned reg) { return reg >= X_XMM0; }
static unsigned a64s_v(unsigned reg) { return reg - X_XMM0; }
static void a64s_mov(BackendContext *ctx, unsigned to, unsigned from) {
  if (to == from) return;
  if (a64s_floating(to) && a64s_floating(from)) a64_word(ctx, 0x1e604000u | a64s_v(from) << 5 | a64s_v(to)); /* fmov d, d */
  else if (a64s_floating(to)) a64_word(ctx, 0x9e670000u | from << 5 | a64s_v(to));                           /* fmov d, x */
  else if (a64s_floating(from)) a64_word(ctx, 0x9e660000u | a64s_v(from) << 5 | to);                         /* fmov x, d */
  else a64_word(ctx, 0xaa0003e0u | from << 16 | to);                                                         /* mov x, x */
}
static void a64s_immediate(BackendContext *ctx, unsigned reg, uint64_t n) {
  if (a64s_floating(reg)) {
    if (!n) { a64_word(ctx, 0x9e6703e0u | a64s_v(reg)); return; } /* fmov d, xzr */
    a64_immediate(ctx, A_S2, n);
    a64s_mov(ctx, reg, A_S2);
    return;
  }
  if (!n) { a64_word(ctx, 0xd2800000u | reg); return; }
  if (~n <= 0xffff) { a64_word(ctx, 0x92800000u | (uint32_t)(~n & 0xffff) << 5 | reg); return; } /* movn */
  a64_immediate(ctx, reg, n);
}
/* rd <- rn + immediate, any 64-bit value; rd may equal rn. */
static void a64s_add_immediate(BackendContext *ctx, unsigned rd, unsigned rn, int64_t n) {
  if (n >= 0 && n < 4096) { if (n || rd != rn) a64_word(ctx, 0x91000000u | (uint32_t)n << 10 | rn << 5 | rd); return; }
  if (n < 0 && -n < 4096) { a64_word(ctx, 0xd1000000u | (uint32_t)(-n) << 10 | rn << 5 | rd); return; }
  if (n >= 0 && n < (1 << 24) && !(n & 0xfff)) { a64_word(ctx, 0x91400000u | (uint32_t)(n >> 12) << 10 | rn << 5 | rd); return; }
  unsigned temp = rd == rn ? A_S4 : rd;
  a64s_immediate(ctx, temp, (uint64_t)n);
  a64_word(ctx, 0x8b000000u | temp << 16 | rn << 5 | rd);
}
/* Load or store through base + index * scale + disp. `opcode` is the
   unsigned-offset form of the instruction and `log` the access size log2. */
static void a64s_access(BackendContext *ctx, uint32_t opcode, unsigned log, unsigned rt, SsaMemory m) {
  unsigned base = (unsigned)m.base;
  int64_t disp = m.disp;
  if (m.index >= 0) {
    unsigned shift = m.scale == 8 ? 3 : m.scale == 4 ? 2 : m.scale == 2 ? 1 : 0;
    if (!disp && (shift == 0 || shift == log)) {
      a64_word(ctx, (opcode & ~0x01000000u) | 0x00206800u | (uint32_t)m.index << 16 | (shift ? 1u : 0u) << 12 | base << 5 | rt);
      return;
    }
    bool direct = disp >= -256 && disp < 256;
    direct = direct || (disp >= 0 && !(disp & ((1 << log) - 1)) && (disp >> log) < 4096);
    if (!direct) {
      /* Fold the displacement first: adding it after the index would need
         a second scratch register, and A_S4 may hold the stored value. */
      a64s_add_immediate(ctx, A_S3, base, disp);
      a64_word(ctx, 0x8b000000u | shift << 10 | (uint32_t)m.index << 16 | A_S3 << 5 | A_S3);
      a64_word(ctx, opcode | A_S3 << 5 | rt);
      return;
    }
    a64_word(ctx, 0x8b000000u | shift << 10 | (uint32_t)m.index << 16 | base << 5 | A_S3); /* add x15, base, index, lsl */
    base = A_S3;
  }
  if (disp >= 0 && !(disp & ((1 << log) - 1)) && (disp >> log) < 4096) {
    a64_word(ctx, opcode | (uint32_t)(disp >> log) << 10 | base << 5 | rt);
    return;
  }
  if (disp >= -256 && disp < 256) {
    a64_word(ctx, (opcode & ~0x01000000u) | ((uint32_t)disp & 0x1ff) << 12 | base << 5 | rt);
    return;
  }
  a64s_add_immediate(ctx, A_S3, base, disp);
  a64_word(ctx, opcode | A_S3 << 5 | rt);
}
/* Unsigned-offset opcodes by access: bits, signed, floating; store or load. */
static uint32_t a64s_memory_opcode(unsigned bits, bool sign, bool floating, bool store, unsigned *log) {
  *log = bits == 8 ? 0 : bits == 16 ? 1 : bits == 32 ? 2 : 3;
  if (floating) return bits == 32 ? (store ? 0xbd000000u : 0xbd400000u) : (store ? 0xfd000000u : 0xfd400000u);
  if (store) return bits == 8 ? 0x39000000u : bits == 16 ? 0x79000000u : bits == 32 ? 0xb9000000u : 0xf9000000u;
  if (sign && bits < 64) return bits == 8 ? 0x39800000u : bits == 16 ? 0x79800000u : 0xb9800000u;
  return bits == 8 ? 0x39400000u : bits == 16 ? 0x79400000u : bits == 32 ? 0xb9400000u : 0xf9400000u;
}
static void a64s_memory(BackendContext *ctx, unsigned bits, bool sign, bool floating, bool store, unsigned rt, SsaMemory m) {
  unsigned log;
  uint32_t opcode = a64s_memory_opcode(bits, sign, floating, store, &log);
  a64s_access(ctx, opcode, log, rt, m);
}
static SsaMemory a64s_slot(SsaEmit *e, const SsaValue *v) {
  return (SsaMemory){A64_FP, -1, 1, (int32_t)(e->spill_base - 8 * (uint32_t)v->slot)};
}
static void a64s_slot_access(BackendContext *ctx, bool store, unsigned reg, SsaMemory m) {
  unsigned log;
  uint32_t opcode = a64s_memory_opcode(64, false, a64s_floating(reg), store, &log);
  a64s_access(ctx, opcode, log, a64s_floating(reg) ? a64s_v(reg) : reg, m);
}
static unsigned a64s_get(SsaEmit *e, int32_t id, unsigned scratch) {
  Ssa *s = e->s; BackendContext *ctx = e->ctx;
  SsaValue *v = &s->values[id];
  bool floating = v->cls == SC_F64 || v->cls == SC_F32;
  if (floating && !a64s_floating(scratch)) scratch = X_XMM0 + A_F1;
  if (v->op == SO_CONST && !ssa_located(v)) { a64s_immediate(ctx, scratch, (uint64_t)v->aux); return scratch; }
  if (v->op == SO_FRAME) { a64s_add_immediate(ctx, scratch, A64_FP, (int32_t)v->aux); return scratch; }
  if (v->reg >= 0) return (unsigned)v->reg;
  if (v->slot < 0) { ctx->text.failed = true; return scratch; }
  a64s_slot_access(ctx, false, scratch, a64s_slot(e, v));
  return scratch;
}
static unsigned a64s_target(const SsaValue *v) {
  if (v->reg >= 0) return (unsigned)v->reg;
  return v->cls == SC_F64 || v->cls == SC_F32 ? X_XMM0 + A_F1 : A_S1;
}
static void a64s_put(SsaEmit *e, const SsaValue *v, unsigned reg) {
  if (v->reg >= 0) { a64s_mov(e->ctx, (unsigned)v->reg, reg); return; }
  if (v->slot >= 0) a64s_slot_access(e->ctx, true, reg, a64s_slot(e, v));
}
static void a64s_transfer(SsaEmit *e, uint8_t dst_kind, int64_t dst, uint8_t src_kind, int64_t src, uint8_t cls) {
  BackendContext *ctx = e->ctx;
  bool fl = cls == SC_F64 || cls == SC_F32;
  unsigned reg = dst_kind == L_REG ? (unsigned)dst : fl ? X_XMM0 + A_F2 : A_S2;
  if (src_kind == L_REG) {
    if (dst_kind == L_REG) { a64s_mov(ctx, reg, (unsigned)src); return; }
    reg = (unsigned)src;
  } else if (src_kind == L_CONST) a64s_immediate(ctx, reg, (uint64_t)src);
  else if (src_kind == L_FRAME) a64s_add_immediate(ctx, reg, A64_FP, src);
  else a64s_slot_access(ctx, false, reg, (SsaMemory){src_kind == L_SLOT ? A64_FP : A64_SP, -1, 1, (int32_t)src});
  if (dst_kind == L_REG) return;
  a64s_slot_access(ctx, true, reg, (SsaMemory){dst_kind == L_SLOT ? A64_FP : A64_SP, -1, 1, (int32_t)dst});
}
/* Conditional branch on an AArch64 condition code, inverted over `b` like
   a64_branch so the range stays +-128 MiB. Returns the patch slot. */
static size_t a64s_branch(BackendContext *ctx, unsigned code) {
  a64_word(ctx, 0x54000040u | (code ^ 1));
  size_t at = ctx->text.n;
  a64_word(ctx, 0x14000000u);
  return at;
}
static void a64s_fail(SsaEmit *e, unsigned code, unsigned kind) {
  size_t at = a64s_branch(e->ctx, code);
  e->stub_uses = ssa_grow(e->stub_uses, &e->stub_use_capacity, e->stub_use_count + 1, sizeof(*e->stub_uses), &e->s->failed);
  if (!e->s->failed) { e->stub_uses[e->stub_use_count].at = at; e->stub_uses[e->stub_use_count].origin = e->check_origin; e->stub_uses[e->stub_use_count++].kind = kind; }
}
static Cond a64s_compare(SsaEmit *e, int32_t a, int32_t b, Cond cond) {
  Ssa *s = e->s; BackendContext *ctx = e->ctx;
  uint64_t c;
  if (ssa_is_const(s, a, &c) && !ssa_is_const(s, b, &c)) { int32_t t = a; a = b; b = t; cond = ssa_swap(cond); }
  unsigned ra = a64s_get(e, a, A_S1);
  if (ssa_is_const(s, b, &c) && c < 4096) { a64_word(ctx, 0xf100001fu | (uint32_t)c << 10 | ra << 5); return cond; }
  if (ssa_is_const(s, b, &c) && (0 - c) < 4096) { a64_word(ctx, 0xb100001fu | (uint32_t)(0 - c) << 10 | ra << 5); return cond; }
  unsigned rb = a64s_get(e, b, A_S2);
  a64_word(ctx, 0xeb00001fu | rb << 16 | ra << 5);
  return cond;
}
/* d = a op b for three-register integer instructions. */
static void a64s_binary(SsaEmit *e, SsaValue *v, uint32_t opcode) {
  unsigned d = a64s_target(v), ra = a64s_get(e, v->a, A_S1), rb = a64s_get(e, v->b, A_S2);
  a64_word(e->ctx, opcode | rb << 16 | ra << 5 | d);
  a64s_put(e, v, d);
}
static void a64s_float_binary(SsaEmit *e, SsaValue *v, uint32_t opcode) {
  unsigned d = a64s_target(v), ra = a64s_get(e, v->a, X_XMM0 + A_F1), rb = a64s_get(e, v->b, X_XMM0 + A_F2);
  if (v->cls == SC_F32) opcode &= ~0x00400000u;
  a64_word(e->ctx, opcode | a64s_v(rb) << 16 | a64s_v(ra) << 5 | a64s_v(d));
  a64s_put(e, v, d);
}
static void a64s_extend(BackendContext *ctx, unsigned d, unsigned n, unsigned bits, bool sign) {
  if (bits >= 64) { a64s_mov(ctx, d, n); return; }
  if (bits == 1) { a64_word(ctx, 0xd3400000u | n << 5 | d); return; } /* ubfx d, n, #0, #1 */
  uint32_t imms = bits - 1;
  a64_word(ctx, (sign ? 0x93400000u : 0xd3400000u) | imms << 10 | n << 5 | d);
}
static void a64s_cset(BackendContext *ctx, unsigned d, unsigned code) {
  a64_word(ctx, 0x9a9f07e0u | (code ^ 1) << 12 | d);
}
static void a64s_copy_words(BackendContext *ctx, uint32_t size, bool backward) {
  uint32_t at = backward ? size : 0, remaining = size;
  while (remaining) {
    unsigned width = remaining >= 8 ? 8 : remaining >= 4 ? 4 : remaining >= 2 ? 2 : 1;
    if (backward) at -= width;
    a64s_memory(ctx, width * 8, false, false, false, A_S4, (SsaMemory){A_S2, -1, 1, (int32_t)at});
    a64s_memory(ctx, width * 8, false, false, true, A_S4, (SsaMemory){A_S1, -1, 1, (int32_t)at});
    if (!backward) at += width;
    remaining -= width;
  }
}
/* memmove of aux bytes: destination in x16, source in x17. Large copies loop
   over eight-byte words, then bytes. */
static void a64s_copy_memory(SsaEmit *e, SsaValue *v) {
  BackendContext *ctx = e->ctx;
  uint32_t size = (uint32_t)v->aux;
  if (!size) return;
  unsigned rd = a64s_get(e, v->a, A_S1), rs = a64s_get(e, v->b, A_S2);
  if (rs == A_S1) { a64s_mov(ctx, A_S4, rs); rs = A_S4; }
  a64s_mov(ctx, A_S1, rd);
  a64s_mov(ctx, A_S2, rs);
  if (size <= 64) {
    if (v->aux2) { a64s_copy_words(ctx, size, false); return; }
    a64_word(ctx, 0xeb11021fu); /* cmp x16, x17 */
    size_t forward = a64s_branch(ctx, 9); /* ls */
    a64s_copy_words(ctx, size, true);
    size_t done = isa_branch(ctx, -1);
    isa_patch(ctx, forward, ctx->text.n);
    a64s_copy_words(ctx, size, false);
    isa_patch(ctx, done, ctx->text.n);
    return;
  }
  uint32_t words = size / 8, tail = size % 8;
  /* Forward when the destination is not above the source. */
  a64_word(ctx, 0xeb11021fu);
  size_t forward = a64s_branch(ctx, 9);
  /* Backward: tail bytes first, then words from the end. */
  for (uint32_t i = tail; i > 0; --i) {
    a64s_memory(ctx, 8, false, false, false, A_S4, (SsaMemory){A_S2, -1, 1, (int32_t)(words * 8 + i - 1)});
    a64s_memory(ctx, 8, false, false, true, A_S4, (SsaMemory){A_S1, -1, 1, (int32_t)(words * 8 + i - 1)});
  }
  a64s_immediate(ctx, A_S3, words);
  size_t back = ctx->text.n;
  a64_word(ctx, 0xd10005efu);                    /* sub x15, x15, #1 */
  a64_word(ctx, 0xf86f7a2eu);                    /* ldr x14, [x17, x15, lsl #3] */
  a64_word(ctx, 0xf82f7a0eu);                    /* str x14, [x16, x15, lsl #3] */
  a64_word(ctx, 0xb5000000u | (uint32_t)(((int64_t)back - (int64_t)ctx->text.n) / 4 & 0x7ffff) << 5 | A_S3); /* cbnz x15, back */
  size_t done = isa_branch(ctx, -1);
  isa_patch(ctx, forward, ctx->text.n);
  a64s_immediate(ctx, A_S3, 0);
  size_t loop = ctx->text.n;
  a64_word(ctx, 0xf86f7a2eu);
  a64_word(ctx, 0xf82f7a0eu);
  a64_word(ctx, 0x910005efu);                    /* add x15, x15, #1 */
  a64s_immediate(ctx, A_S4, words);
  a64_word(ctx, 0xeb0e01ffu);                    /* cmp x15, x14 */
  a64_word(ctx, 0x54000003u | (uint32_t)(((int64_t)loop - (int64_t)ctx->text.n) / 4 & 0x7ffff) << 5); /* b.lo loop */
  for (uint32_t i = 0; i < tail; ++i) {
    a64s_memory(ctx, 8, false, false, false, A_S4, (SsaMemory){A_S2, -1, 1, (int32_t)(words * 8 + i)});
    a64s_memory(ctx, 8, false, false, true, A_S4, (SsaMemory){A_S1, -1, 1, (int32_t)(words * 8 + i)});
  }
  isa_patch(ctx, done, ctx->text.n);
}
static void a64s_zero_memory(SsaEmit *e, SsaValue *v) {
  BackendContext *ctx = e->ctx;
  uint32_t size = (uint32_t)v->aux;
  if (!size) return;
  a64s_mov(ctx, A_S1, a64s_get(e, v->a, A_S1));
  uint32_t at = 0;
  if (size > 64) {
    uint32_t words = size / 8;
    a64s_immediate(ctx, A_S3, words);
    size_t loop = ctx->text.n;
    a64_word(ctx, 0xd10005efu);                  /* sub x15, x15, #1 */
    a64_word(ctx, 0xf82f7a1fu);                  /* str xzr, [x16, x15, lsl #3] */
    a64_word(ctx, 0xb5000000u | (uint32_t)(((int64_t)loop - (int64_t)ctx->text.n) / 4 & 0x7ffff) << 5 | A_S3);
    at = words * 8;
  }
  while (at < size) {
    unsigned width = size - at >= 8 ? 8 : size - at >= 4 ? 4 : size - at >= 2 ? 2 : 1;
    a64s_memory(ctx, width * 8, false, false, true, A_ZR, (SsaMemory){A_S1, -1, 1, (int32_t)at});
    at += width;
  }
}
static void a64s_symbol(SsaEmit *e, unsigned d, SsaValue *v) {
  BackendContext *ctx = e->ctx;
  bool got = v->aux2 != SYM_LOCAL && !ctx->winarm64; /* COFF uses direct symbol addresses. */
  if (got) {
    relocate(ctx, (unsigned)v->aux, R_AARCH64_ADR_GOT_PAGE, 0); a64_word(ctx, 0x90000000u | d);
    relocate(ctx, (unsigned)v->aux, R_AARCH64_LD64_GOT_LO12_NC, 0); a64_word(ctx, 0xf9400000u | d << 5 | d);
  } else {
    relocate(ctx, (unsigned)v->aux, R_AARCH64_ADR_PREL_PG_HI21, v->c); a64_word(ctx, 0x90000000u | d);
    relocate(ctx, (unsigned)v->aux, R_AARCH64_ADD_ABS_LO12_NC, v->c); a64_word(ctx, 0x91000000u | d << 5 | d);
  }
}
static void a64s_frame_argument(SsaEmit *e, uint32_t offset) { a64s_add_immediate(e->ctx, 0, A64_FP, (int32_t)offset); }
static void a64s_protect_begin(SsaEmit *e, SsaBlock *block) {
  BackendContext *ctx = e->ctx;
  a64s_frame_argument(e, e->s->unwind_offset); runtime_call(ctx, 3);
  a64_word(ctx, 0x7100001fu); /* cmp w0, #0 */
  ssa_jump_to(e, CC_NE, block->succ[1]);
  a64s_frame_argument(e, e->s->unwind_offset); runtime_call(ctx, 4);
}
static void a64s_protect_end(SsaEmit *e) {
  BackendContext *ctx = e->ctx;
  int32_t at = (int32_t)e->s->results_offset;
  static const unsigned char saved[] = {0, 1, X_XMM0, X_XMM0 + 1, X_XMM0 + 2, X_XMM0 + 3};
  for (unsigned i = 0; i < 6; ++i) a64s_slot_access(ctx, true, saved[i], (SsaMemory){A64_FP, -1, 1, at + 8 * (int32_t)i});
  a64s_frame_argument(e, e->s->unwind_offset); runtime_call(ctx, 5);
  for (unsigned i = 0; i < 6; ++i) a64s_slot_access(ctx, false, saved[i], (SsaMemory){A64_FP, -1, 1, at + 8 * (int32_t)i});
}
/* A stack argument: `width` bytes of the value at SP + offset. */
static void a64s_store_outgoing(SsaEmit *e, int32_t value, uint32_t offset, unsigned width) {
  SsaValue *v = &e->s->values[value];
  bool floating = v->cls == SC_F64 || v->cls == SC_F32;
  unsigned reg = a64s_get(e, value, floating ? X_XMM0 + A_F1 : A_S1);
  if (floating && width < 4) width = 4;
  a64s_memory(e->ctx, width * 8, false, floating, true, floating ? a64s_v(reg) : reg, (SsaMemory){A64_SP, -1, 1, (int32_t)offset});
}
/* A placeholder branch, patched once its target is known. */
static size_t a64s_later(BackendContext *ctx) {
  size_t at = ctx->text.n;
  a64_word(ctx, 0);
  return at;
}
static void a64s_conditional(BackendContext *ctx, size_t at, size_t target, unsigned condition) {
  patch_word(ctx, at, 0x54000000u | (uint32_t)(((int64_t)target - (int64_t)at) / 4 & 0x7ffff) << 5 | condition);
}
static void a64s_if_zero(BackendContext *ctx, size_t at, size_t target, unsigned reg) {
  patch_word(ctx, at, 0xb4000000u | (uint32_t)(((int64_t)target - (int64_t)at) / 4 & 0x7ffff) << 5 | reg);
}
static void a64s_back(BackendContext *ctx, size_t target, unsigned condition) {
  size_t at = a64s_later(ctx);
  a64s_conditional(ctx, at, target, condition);
}
/* Whole lanes sum in v29, then the tail runs one element at a time. */
static void a64s_sum(SsaEmit *e, SsaValue *v) {
  BackendContext *ctx = e->ctx;
  unsigned data = a64s_get(e, v->a, A_S1), count = a64s_get(e, v->b, A_S2), initial = a64s_get(e, v->c, A_S3);
  /* Operands sit in allocated registers or their own scratch. */
  a64s_mov(ctx, A_S1, data); a64s_mov(ctx, A_S2, count); a64s_mov(ctx, A_S3, initial);
  unsigned bytes = (unsigned)v->aux, lanes = 16 / bytes;
  bool wide = bytes == 8, square = v->aux2 & 1, sign = v->aux2 & 2;
  a64_word(ctx, 0x4f00e400u | A_F3); /* movi v29.16b, #0 */
  size_t loop = ctx->text.n;
  a64_word(ctx, 0xf100001fu | lanes << 10 | A_S2 << 5);
  size_t after = a64s_later(ctx);
  a64_word(ctx, 0x3cc10400u | A_S1 << 5 | A_F1); /* ldr q31, [x16], #16 */
  if (square) a64_word(ctx, 0x4ea09c00u | A_F1 << 16 | A_F1 << 5 | A_F1); /* mul */
  a64_word(ctx, (wide ? 0x4ee08400u : 0x4ea08400u) | A_F1 << 16 | A_F3 << 5 | A_F3);
  a64_word(ctx, 0xd1000000u | lanes << 10 | A_S2 << 5 | A_S2);
  a64_word(ctx, 0x14000000u | (uint32_t)(((int64_t)loop - (int64_t)ctx->text.n) / 4 & 0x3ffffff));
  a64s_conditional(ctx, after, ctx->text.n, 3); /* b.lo */
  if (wide) {
    a64_word(ctx, 0x5ef1b800u | A_F3 << 5 | A_F1); /* addp d31, v29.2d */
    a64_word(ctx, 0x9e660000u | A_F1 << 5 | A_S4);
  } else {
    a64_word(ctx, 0x4eb1b800u | A_F3 << 5 | A_F1); /* addv s31, v29.4s */
    a64_word(ctx, 0x1e260000u | A_F1 << 5 | A_S4);
  }
  a64_word(ctx, 0x8b000000u | A_S4 << 16 | A_S3 << 5 | A_S3);
  size_t empty = a64s_later(ctx), scalar = ctx->text.n;
  a64_word(ctx, (wide ? 0xf8408400u : 0xb8404400u) | A_S1 << 5 | A_S4);
  if (square) a64_word(ctx, 0x1b007c00u | A_S4 << 16 | A_S4 << 5 | A_S4);
  a64_word(ctx, 0x8b000000u | A_S4 << 16 | A_S3 << 5 | A_S3);
  a64_word(ctx, 0xf1000400u | A_S2 << 5 | A_S2);
  a64s_back(ctx, scalar, 1); /* b.ne */
  a64s_if_zero(ctx, empty, ctx->text.n, A_S2);
  if (!wide) a64_word(ctx, sign ? 0x93407c00u | A_S3 << 5 | A_S3 : 0x2a0003e0u | A_S3 << 16 | A_S3);
  unsigned d = a64s_target(v);
  a64s_mov(ctx, d, A_S3);
  a64s_put(e, v, d);
}
/* See ssa_axpy_emit: dst just above src runs one element at a time. */
static void a64s_axpy(SsaEmit *e, SsaValue *v) {
  BackendContext *ctx = e->ctx;
  a64s_add_immediate(ctx, A_S4, A64_FP, (int32_t)e->s->values[v->a].aux);
  unsigned bytes = (unsigned)v->aux, lanes = 16 / bytes;
  bool wide = bytes == 8, minus = v->aux2 == DYN_OP_SUB;
  a64_word(ctx, 0xf9400000u | 0u << 10 | A_S4 << 5 | A_S1);
  a64_word(ctx, 0xf9400000u | 1u << 10 | A_S4 << 5 | A_S2);
  a64_word(ctx, 0xf9400000u | 2u << 10 | A_S4 << 5 | A_S3);
  a64_word(ctx, wide ? 0xfd400000u | 3u << 10 | A_S4 << 5 | A_F3 : 0xbd400000u | 6u << 10 | A_S4 << 5 | A_F3);
  a64_word(ctx, (wide ? 0x4e080400u : 0x4e040400u) | A_F3 << 5 | A_F3); /* dup */
  a64_word(ctx, 0xcb000000u | A_S2 << 16 | A_S1 << 5 | A_S4);
  a64_word(ctx, 0xd1000400u | A_S4 << 5 | A_S4);
  a64_word(ctx, 0xf100001fu | 15u << 10 | A_S4 << 5);
  size_t overlap = a64s_later(ctx), loop = ctx->text.n;
  a64_word(ctx, 0xf100001fu | lanes << 10 | A_S3 << 5);
  size_t tail = a64s_later(ctx);
  a64_word(ctx, 0x3cc10400u | A_S2 << 5 | A_F1);
  a64_word(ctx, (wide ? 0x6e60dc00u : 0x6e20dc00u) | A_F3 << 16 | A_F1 << 5 | A_F1); /* fmul */
  a64_word(ctx, 0x3dc00000u | A_S1 << 5 | A_F2);
  a64_word(ctx, (minus ? (wide ? 0x4ee0d400u : 0x4ea0d400u) : (wide ? 0x4e60d400u : 0x4e20d400u)) | A_F1 << 16 | A_F2 << 5 | A_F2);
  a64_word(ctx, 0x3c810400u | A_S1 << 5 | A_F2);
  a64_word(ctx, 0xd1000000u | lanes << 10 | A_S3 << 5 | A_S3);
  a64_word(ctx, 0x14000000u | (uint32_t)(((int64_t)loop - (int64_t)ctx->text.n) / 4 & 0x3ffffff));
  a64s_conditional(ctx, overlap, ctx->text.n, 3);
  a64s_conditional(ctx, tail, ctx->text.n, 3);
  size_t empty = a64s_later(ctx), scalar = ctx->text.n;
  a64_word(ctx, (wide ? 0xfc408400u : 0xbc404400u) | A_S2 << 5 | A_F1);
  a64_word(ctx, (wide ? 0x1e600800u : 0x1e200800u) | A_F3 << 16 | A_F1 << 5 | A_F1);
  a64_word(ctx, (wide ? 0xfd400000u : 0xbd400000u) | A_S1 << 5 | A_F2);
  a64_word(ctx, (minus ? (wide ? 0x1e603800u : 0x1e203800u) : (wide ? 0x1e602800u : 0x1e202800u)) | A_F1 << 16 | A_F2 << 5 | A_F2);
  a64_word(ctx, (wide ? 0xfc008400u : 0xbc004400u) | A_S1 << 5 | A_F2);
  a64_word(ctx, 0xf1000400u | A_S3 << 5 | A_S3);
  a64s_back(ctx, scalar, 1);
  a64s_if_zero(ctx, empty, ctx->text.n, A_S3);
}
/* SO_VLOOP on AArch64: x8 the frame block, x9 the address index, x10 its end,
   x11 the vector iterations, x0-x3 the arrays, x16/x17 temporaries. Program
   registers 0-13 are v0-v7 and v16-v21; ld2/ld3/st2/st3 go through v29-v31,
   and v28 holds one lane of a sum. */
static unsigned a64vp_reg(uint32_t d) { return d < 8 ? d : d + 8; }
static void a64vp_copy(BackendContext *ctx, unsigned to, unsigned from) {
  if (to != from) a64_word(ctx, 0x4ea01c00u | from << 16 | from << 5 | to); /* mov to.16b, from.16b */
}
static void a64vp_address(BackendContext *ctx, unsigned base, unsigned scale) {
  unsigned shift = scale == 8 ? 3 : scale == 4 ? 2 : scale == 2 ? 1 : 0;
  a64_word(ctx, 0x8b000000u | 9u << 16 | shift << 10 | base << 5 | 16u);   /* add x16, base, x9, lsl shift */
}
static void a64vp_range(BackendContext *ctx, unsigned rd, unsigned base, unsigned index, unsigned scale) {
  unsigned shift = scale == 8 ? 3 : scale == 4 ? 2 : scale == 2 ? 1 : 0;
  a64_word(ctx, 0x8b000000u | index << 16 | shift << 10 | base << 5 | rd);
}
static void a64s_vloop(SsaEmit *e, SsaValue *v) {
  BackendContext *ctx = e->ctx;
  const uint32_t *w = &e->s->lists[v->list];
  uint32_t bases = w[0], sums_at = w[8], inputs_at = w[9], ops = w[3], step = w[16], counter_step = w[17];
  uint32_t bytes = w[18] & 0xff, lanes = 16 / bytes;
  bool wide = bytes == 8, integer = w[18] >> 8 & 1;
  uint32_t size = wide ? 3u << 10 : 2u << 10; /* .2d or .4s in ld/st */
  const uint32_t *stride = w + 4, *scale = w + 12, *program = w + VP_HEADER;
  size_t skips[2 + VP_MAX_BASES + VP_MAX_BASES * VP_MAX_BASES]; unsigned skip_count = 0;
  unsigned skip_kinds[2 + VP_MAX_BASES + VP_MAX_BASES * VP_MAX_BASES];
  a64s_add_immediate(ctx, 8, A64_FP, (int32_t)e->s->values[v->a].aux);
  a64_word(ctx, 0xf9400000u | 0u << 10 | 8u << 5 | 16u);                  /* ldr x16, [x8] */
  a64_word(ctx, 0xf9400000u | 1u << 10 | 8u << 5 | 10u);                  /* ldr x10, [x8, 8] */
  a64_word(ctx, 0xeb00001fu | 10u << 16 | 16u << 5);                      /* cmp x16, x10 */
  skip_kinds[skip_count] = 2; skips[skip_count++] = a64s_later(ctx);      /* b.hs */
  a64_word(ctx, 0xcb000000u | 16u << 16 | 10u << 5 | 10u);               /* sub x10, x10, x16 */
  if (counter_step > 1) {
    a64_word(ctx, 0x91000000u | (counter_step - 1) << 10 | 10u << 5 | 10u);
    a64s_immediate(ctx, 17, counter_step);
    a64_word(ctx, 0x9ac00800u | 17u << 16 | 10u << 5 | 10u);             /* udiv */
  }
  if (wide) a64_word(ctx, 0x92400000u | 63u << 16 | 62u << 10 | 10u << 5 | 11u); /* and x11, x10, ~1 */
  else a64_word(ctx, 0x92400000u | 62u << 16 | 61u << 10 | 10u << 5 | 11u);      /* and x11, x10, ~3 */
  skip_kinds[skip_count] = 0xff; skips[skip_count++] = a64s_later(ctx);   /* cbz x11 */
  for (uint32_t k = 0; k < w[10]; ++k) {
    a64_word(ctx, 0xf9400000u | 0u << 10 | 8u << 5 | 16u);
    a64_word(ctx, 0x8b000000u | 11u << 16 | 16u << 5 | 16u);             /* add x16, x16, x11 */
    a64_word(ctx, 0xf9400000u | (w[11] + 8 * k) / 8 << 10 | 8u << 5 | 17u);
    a64_word(ctx, 0xeb00001fu | 17u << 16 | 16u << 5);                    /* cmp x16, x17 */
    skip_kinds[skip_count] = 8; skips[skip_count++] = a64s_later(ctx);    /* b.hi */
  }
  a64_word(ctx, 0xf9400000u | 2u << 10 | 8u << 5 | 9u);                   /* ldr x9, [x8, 16] */
  if (step > 1) {
    a64s_immediate(ctx, 17, step);
    a64_word(ctx, 0x9b007c00u | 17u << 16 | 11u << 5 | 10u);             /* mul x10, x11, x17 */
    a64_word(ctx, 0x8b000000u | 9u << 16 | 10u << 5 | 10u);              /* add x10, x10, x9 */
  } else a64_word(ctx, 0x8b000000u | 9u << 16 | 11u << 5 | 10u);         /* add x10, x11, x9 */
  for (uint32_t j = 0; j < ops; ++j) {
    if (program[VP_WORDS * j] != VP_INDEX) continue;
    a64s_immediate(ctx, 17, UINT64_C(0x80000000));
    a64_word(ctx, 0xeb00001fu | 17u << 16 | 10u << 5);                    /* cmp x10, 2^31 */
    skip_kinds[skip_count] = 8; skips[skip_count++] = a64s_later(ctx);    /* b.hi */
    break;
  }
  for (uint32_t k = 0; k < bases; ++k)
    a64_word(ctx, 0xf9400000u | (3u + k) << 10 | 8u << 5 | k);
  for (uint32_t a = 0; a < bases; ++a) {
    bool stored = false;
    for (uint32_t j = 0; j < ops; ++j) {
      const uint32_t *o = program + VP_WORDS * j;
      stored |= (o[0] == VP_STORE || o[0] == VP_STORE2 || o[0] == VP_STORE3) && o[4] == a;
    }
    if (!stored) continue;
    for (uint32_t b = 0; b < bases; ++b) {
      if (b == a) continue;
      a64vp_range(ctx, 16, a, 9, scale[a]);
      a64vp_range(ctx, 17, b, 10, scale[b]);
      a64_word(ctx, 0xeb00001fu | 17u << 16 | 16u << 5);
      size_t fine = a64s_later(ctx);
      a64vp_range(ctx, 16, b, 9, scale[b]);
      a64vp_range(ctx, 17, a, 10, scale[a]);
      a64_word(ctx, 0xeb00001fu | 17u << 16 | 16u << 5);
      skip_kinds[skip_count] = 3; skips[skip_count++] = a64s_later(ctx);  /* b.lo */
      a64s_conditional(ctx, fine, ctx->text.n, 2);                        /* b.hs */
    }
  }
  for (uint32_t j = 0; j < ops; ++j) {
    const uint32_t *o = program + VP_WORDS * j;
    unsigned d = a64vp_reg(o[1]);
    if (o[0] == VP_CONST) {
      a64s_immediate(ctx, 16, wide ? (uint64_t)o[3] << 32 | o[5] : o[5]);
      a64_word(ctx, (wide ? 0x4e080c00u : 0x4e040c00u) | 16u << 5 | d);  /* dup d, x16/w16 */
    } else if (o[0] == VP_BCAST) {
      if (wide) a64_word(ctx, 0xfd400000u | (inputs_at + 8 * o[4]) / 8 << 10 | 8u << 5 | d);
      else a64_word(ctx, 0xbd400000u | (inputs_at + 4 * o[4]) / 4 << 10 | 8u << 5 | d);
      a64_word(ctx, (wide ? 0x4e080400u : 0x4e040400u) | d << 5 | d);    /* dup d, d[0] */
    } else if (o[0] == VP_SUM && integer) {
      a64_word(ctx, 0xbd400000u | (sums_at + 8 * o[4]) / 4 << 10 | 8u << 5 | d); /* ldr s: low 32 bits, rest zero */
    } else if (o[0] == VP_SUM) {
      if (wide) a64_word(ctx, 0xfd400000u | (sums_at + 8 * o[4]) / 8 << 10 | 8u << 5 | d);
      else a64_word(ctx, 0xbd400000u | (sums_at + 4 * o[4]) / 4 << 10 | 8u << 5 | d);
    } else if (o[0] == VP_LANES) {
      a64s_immediate(ctx, 16, UINT64_C(0x0000000100000000));
      a64s_immediate(ctx, 17, UINT64_C(0x0000000300000002));
      a64_word(ctx, 0x4e080c00u | 16u << 5 | d);                         /* dup d.2d, x16 */
      a64_word(ctx, 0x4e181c00u | 17u << 5 | d);                         /* ins d.d[1], x17 */
    }
  }
  size_t loop = ctx->text.n;
  for (uint32_t j = 0; j < ops; ++j) {
    const uint32_t *o = program + VP_WORDS * j;
    unsigned d = a64vp_reg(o[1]), x = a64vp_reg(o[2]), y = a64vp_reg(o[3]), base = o[4];
    switch (o[0]) {
    case VP_LOAD:
      a64vp_address(ctx, base, scale[base]);
      if (stride[base] == bytes) a64_word(ctx, 0x4c407000u | size | 16u << 5 | d); /* ld1 */
      else if (stride[base] == 2 * bytes) {
        a64_word(ctx, 0x4c408000u | size | 16u << 5 | 30u);              /* ld2 {v30, v31} */
        a64vp_copy(ctx, d, o[5] ? 31 : 30);
        const uint32_t *next = j + 1 < ops ? o + VP_WORDS : NULL;
        if (next && next[0] == VP_LOAD && next[4] == base && next[5] == (o[5] ^ bytes)) {
          a64vp_copy(ctx, a64vp_reg(next[1]), next[5] ? 31 : 30); ++j;
        }
      } else {
        a64_word(ctx, 0x4c404000u | size | 16u << 5 | 29u);              /* ld3 {v29, v30, v31} */
        a64vp_copy(ctx, d, 29);
        a64vp_copy(ctx, a64vp_reg(o[VP_WORDS + 1]), 30);
        a64vp_copy(ctx, a64vp_reg(o[2 * VP_WORDS + 1]), 31);
        j += 2;
      }
      break;
    case VP_STORE:
      a64vp_address(ctx, base, scale[base]);
      a64_word(ctx, 0x4c007000u | size | 16u << 5 | x);                  /* st1 */
      break;
    case VP_INDEX:
      a64_word(ctx, 0x4e040c00u | 9u << 5 | 28u);                        /* dup v28.4s, w9 */
      a64_word(ctx, 0x4ea08400u | x << 16 | 28u << 5 | 28u);             /* add v28.4s, v28.4s, lanes */
      a64_word(ctx, 0x4e21d800u | 28u << 5 | d);                         /* scvtf d.4s, v28.4s */
      break;
    case VP_STORE2:
      a64vp_address(ctx, base, scale[base]);
      a64vp_copy(ctx, 30, x); a64vp_copy(ctx, 31, y);
      a64_word(ctx, 0x4c008000u | size | 16u << 5 | 30u);                /* st2 */
      break;
    case VP_STORE3:
      a64vp_address(ctx, base, scale[base]);
      a64vp_copy(ctx, 29, x); a64vp_copy(ctx, 30, y); a64vp_copy(ctx, 31, a64vp_reg(o[5]));
      a64_word(ctx, 0x4c004000u | size | 16u << 5 | 29u);                /* st3 */
      break;
    case VP_ADD: case VP_SUB: case VP_MUL: case VP_DIV: {
      static const uint32_t codes[] = {0x4e20d400u, 0x4ea0d400u, 0x6e20dc00u, 0x6e20fc00u};
      if (integer) {
        uint32_t code = o[0] == VP_ADD ? 0x4ea08400u : o[0] == VP_SUB ? 0x6ea08400u : o[0] == VP_MUL ? 0x4ea09c00u : 0;
        a64_word(ctx, code | y << 16 | x << 5 | d);
        break;
      }
      a64_word(ctx, codes[o[0] - VP_ADD] | (wide ? 1u << 22 : 0) | y << 16 | x << 5 | d);
      break;
    }
    case VP_AND: case VP_OR: case VP_XOR: {
      uint32_t code = o[0] == VP_AND ? 0x4e201c00u : o[0] == VP_OR ? 0x4ea01c00u : 0x6e201c00u;
      a64_word(ctx, code | y << 16 | x << 5 | d);
      break;
    }
    case VP_SUM: {
      if (integer) { a64_word(ctx, (o[5] & 1 ? 0x6ea08400u : 0x4ea08400u) | x << 16 | d << 5 | d); break; }
      /* Lane 0, then lanes 1, 2 and 3: the scalar loop's order. */
      uint32_t code = (o[5] ? 0x1e203800u : 0x1e202800u) | (wide ? 1u << 22 : 0);
      a64_word(ctx, code | x << 16 | d << 5 | d);
      for (unsigned lane = 1; lane < lanes; ++lane) {
        if (wide) a64_word(ctx, 0x5e180400u | x << 5 | 28u);             /* dup d28, x.d[1] */
        else a64_word(ctx, 0x5e040400u | lane << 19 | x << 5 | 28u);     /* dup s28, x.s[lane] */
        a64_word(ctx, code | 28u << 16 | d << 5 | d);
      }
      break;
    }
    default: break;
    }
  }
  a64_word(ctx, 0x91000000u | (lanes * step) << 10 | 9u << 5 | 9u);      /* add x9, x9, lanes * step */
  a64_word(ctx, 0xeb00001fu | 10u << 16 | 9u << 5);                      /* cmp x9, x10 */
  a64s_back(ctx, loop, 3);                                                /* b.lo */
  a64_word(ctx, 0xf9000000u | 2u << 10 | 8u << 5 | 9u);                  /* str x9, [x8, 16] */
  if (counter_step > 1) {
    a64s_immediate(ctx, 17, counter_step);
    a64_word(ctx, 0x9b007c00u | 17u << 16 | 11u << 5 | 11u);
  }
  a64_word(ctx, 0xf9400000u | 0u << 10 | 8u << 5 | 16u);
  a64_word(ctx, 0x8b000000u | 11u << 16 | 16u << 5 | 16u);
  a64_word(ctx, 0xf9000000u | 0u << 10 | 8u << 5 | 16u);                 /* i += iterations * step */
  for (uint32_t j = 0; j < ops; ++j) {
    const uint32_t *o = program + VP_WORDS * j;
    if (o[0] == VP_SUM && integer) {
      unsigned d = a64vp_reg(o[1]);
      a64_word(ctx, 0x4eb1b800u | d << 5 | 28u);                         /* addv s28, d.4s */
      a64_word(ctx, 0x1e260000u | 28u << 5 | 16u);                       /* fmov w16, s28 */
      if (o[5] & 2) a64_word(ctx, 0x2a1003f0u);                          /* mov w16, w16 */
      else a64_word(ctx, 0x93407c00u | 16u << 5 | 16u);                  /* sxtw x16, w16 */
      a64_word(ctx, 0xf9000000u | (sums_at + 8 * o[4]) / 8 << 10 | 8u << 5 | 16u);
    } else if (o[0] == VP_SUM) {
      if (wide) a64_word(ctx, 0xfd000000u | (sums_at + 8 * o[4]) / 8 << 10 | 8u << 5 | a64vp_reg(o[1]));
      else a64_word(ctx, 0xbd000000u | (sums_at + 4 * o[4]) / 4 << 10 | 8u << 5 | a64vp_reg(o[1]));
    }
  }
  for (unsigned k = 0; k < skip_count; ++k) {
    if (skip_kinds[k] == 0xff) a64s_if_zero(ctx, skips[k], ctx->text.n, 11);
    else a64s_conditional(ctx, skips[k], ctx->text.n, skip_kinds[k]);
  }
}
static void a64s_emit_value(SsaEmit *e, SsaBlock *block, uint32_t *k) {
  Ssa *s = e->s; BackendContext *ctx = e->ctx;
  uint32_t id = block->values.items[*k];
  SsaValue *v = &s->values[id];
  e->check_origin = v->check_origin;
  if (v->dead && v->op != SO_CALL) return;
  unsigned d;
  uint64_t c;
  switch (v->op) {
  case SO_CONST:
    if (ssa_located(v)) { d = a64s_target(v); a64s_immediate(ctx, d, (uint64_t)v->aux); a64s_put(e, v, d); }
    return;
  case SO_RESULT:
    if (s->values[v->a].block != v->block) {
      uint32_t count = 1;
      while (*k + count < block->values.count && s->values[block->values.items[*k + count]].op == SO_RESULT) ++count;
      SsaMove moves[4]; uint32_t n = 0;
      for (uint32_t j = 0; j < count && j < 4; ++j) {
        SsaValue *r = &s->values[block->values.items[*k + j]];
        if (r->dead || (r->reg < 0 && r->slot < 0)) continue;
        SsaMove move = {.src_kind = L_REG, .src = ssa_result_register(ctx, r->aux), .cls = r->cls};
        ssa_destination(e, &move, (int32_t)block->values.items[*k + j]);
        moves[n++] = move;
      }
      ssa_parallel(e, moves, n);
      *k += count - 1;
    }
    return;
  case SO_FRAME: case SO_PHI: case SO_PARAM: case SO_COPY:
    return;
  case SO_ADD: case SO_SUB:
    if (ssa_is_const(s, v->b, &c) && (c < 4096 || 0 - c < 4096)) {
      d = a64s_target(v);
      int64_t n = v->op == SO_ADD ? (int64_t)c : -(int64_t)c;
      a64s_add_immediate(ctx, d, a64s_get(e, v->a, A_S1), n);
      a64s_put(e, v, d);
      return;
    }
    a64s_binary(e, v, v->op == SO_ADD ? 0x8b000000u : 0xcb000000u);
    return;
  case SO_AND: a64s_binary(e, v, 0x8a000000u); return;
  case SO_OR: a64s_binary(e, v, 0xaa000000u); return;
  case SO_XOR: a64s_binary(e, v, 0xca000000u); return;
  case SO_MUL: a64s_binary(e, v, 0x9b007c00u); return;
  case SO_MULH: a64s_binary(e, v, v->aux2 ? 0x9b407c00u : 0x9bc07c00u); return;
  case SO_ADDO: case SO_SUBO: {
    d = a64s_target(v);
    unsigned ra = a64s_get(e, v->a, A_S1), rb = a64s_get(e, v->b, A_S2);
    a64_word(ctx, (v->op == SO_ADDO ? 0xab000000u : 0xeb000000u) | rb << 16 | ra << 5 | d);
    /* Failure: signed overflow (vs), unsigned carry out (hs) or borrow (lo). */
    a64s_fail(e, v->aux2 ? 6 : v->op == SO_ADDO ? 2 : 3, GUARD_OVERFLOW);
    a64s_put(e, v, d);
    return;
  }
  case SO_MULO: {
    d = a64s_target(v);
    unsigned ra = a64s_get(e, v->a, A_S1), rb = a64s_get(e, v->b, A_S2);
    a64_word(ctx, (v->aux2 ? 0x9b407c00u : 0x9bc07c00u) | rb << 16 | ra << 5 | A_S3); /* high half */
    a64_word(ctx, 0x9b007c00u | rb << 16 | ra << 5 | d);
    if (v->aux2) a64_word(ctx, 0xeb80fc1fu | d << 16 | A_S3 << 5); /* cmp x15, d, asr #63 */
    else a64_word(ctx, 0xf100001fu | A_S3 << 5);
    a64s_fail(e, 1, GUARD_OVERFLOW);
    a64s_put(e, v, d);
    return;
  }
  case SO_SHL: case SO_SHR: case SO_SAR:
    d = a64s_target(v);
    if (ssa_is_const(s, v->b, &c)) {
      unsigned n = a64s_get(e, v->a, A_S1), amount = (unsigned)(c & 63);
      if (v->op == SO_SHL) a64_word(ctx, 0xd3400000u | ((64 - amount) & 63) << 16 | (63 - amount) << 10 | n << 5 | d);
      else a64_word(ctx, (v->op == SO_SHR ? 0xd340fc00u : 0x9340fc00u) | amount << 16 | n << 5 | d);
      a64s_put(e, v, d);
      return;
    }
    a64s_binary(e, v, v->op == SO_SHL ? 0x9ac02000u : v->op == SO_SHR ? 0x9ac02400u : 0x9ac02800u);
    return;
  case SO_DIV: case SO_REM: {
    d = a64s_target(v);
    unsigned ra = a64s_get(e, v->a, A_S1), rb = a64s_get(e, v->b, A_S2);
    if (v->op == SO_DIV) a64_word(ctx, (v->aux2 ? 0x9ac00c00u : 0x9ac00800u) | rb << 16 | ra << 5 | d);
    else {
      a64_word(ctx, (v->aux2 ? 0x9ac00c00u : 0x9ac00800u) | rb << 16 | ra << 5 | A_S3);
      a64_word(ctx, 0x9b008000u | rb << 16 | ra << 10 | A_S3 << 5 | d); /* msub d, x15, b, a */
    }
    a64s_put(e, v, d);
    return;
  }
  case SO_NEG: case SO_NOT:
    d = a64s_target(v);
    a64_word(ctx, (v->op == SO_NEG ? 0xcb0003e0u : 0xaa2003e0u) | a64s_get(e, v->a, A_S1) << 16 | d);
    a64s_put(e, v, d);
    return;
  case SO_EXT:
    d = a64s_target(v);
    a64s_extend(ctx, d, a64s_get(e, v->a, A_S1), (unsigned)v->aux, v->aux2 != 0);
    a64s_put(e, v, d);
    return;
  case SO_CMP: {
    if (v->fused) return;
    Cond cond = a64s_compare(e, v->a, v->b, (Cond)v->cond);
    d = a64s_target(v);
    a64s_cset(ctx, d, a64_cond[cond]);
    a64s_put(e, v, d);
    return;
  }
  case SO_FCMP: {
    static const unsigned char codes[] = {0, 1, 4, 9, 12, 10}; /* eq ne mi ls gt ge */
    bool f32 = s->values[v->a].cls == SC_F32;
    unsigned ra = a64s_get(e, v->a, X_XMM0 + A_F1), rb = a64s_get(e, v->b, X_XMM0 + A_F2);
    a64_word(ctx, (f32 ? 0x1e202000u : 0x1e602000u) | a64s_v(rb) << 16 | a64s_v(ra) << 5);
    d = a64s_target(v);
    a64s_cset(ctx, d, codes[v->aux]);
    a64s_put(e, v, d);
    return;
  }
  /* Two f32 lanes in the low 64 bits of a vector register. */
  case SO_VPAIR: {
    unsigned d = a64s_target(v), ra = a64s_get(e, v->a, X_XMM0 + A_F1), rb = a64s_get(e, v->b, X_XMM0 + A_F2);
    uint32_t opcode = v->aux == 0x58 ? 0x0e20d400u : v->aux == 0x5c ? 0x0ea0d400u : 0x2e20dc00u; /* fadd/fsub/fmul .2s */
    a64_word(e->ctx, opcode | a64s_v(rb) << 16 | a64s_v(ra) << 5 | a64s_v(d));
    a64s_put(e, v, d);
    return;
  }
  case SO_VPACK: {
    unsigned d = a64s_target(v), ra = a64s_get(e, v->a, X_XMM0 + A_F1), rb = a64s_get(e, v->b, X_XMM0 + A_F2);
    a64_word(e->ctx, 0x0e803800u | a64s_v(rb) << 16 | a64s_v(ra) << 5 | a64s_v(d)); /* zip1 .2s */
    a64s_put(e, v, d);
    return;
  }
  case SO_VLANE: {
    unsigned d = a64s_target(v), ra = a64s_get(e, v->a, X_XMM0 + A_F1);
    if (v->aux == 0) a64s_mov(e->ctx, d, ra);
    else a64_word(e->ctx, 0x5e0c0400u | a64s_v(ra) << 5 | a64s_v(d)); /* dup s, v.s[1] */
    a64s_put(e, v, d);
    return;
  }
  case SO_VHADD: {
    unsigned d = a64s_target(v), ra = a64s_get(e, v->a, X_XMM0 + A_F1);
    a64_word(e->ctx, 0x7e30d800u | a64s_v(ra) << 5 | a64s_v(d)); /* faddp s, v.2s */
    a64s_put(e, v, d);
    return;
  }
  case SO_FADD: a64s_float_binary(e, v, 0x1e602800u); return;
  case SO_FSUB: a64s_float_binary(e, v, 0x1e603800u); return;
  case SO_FMUL: a64s_float_binary(e, v, 0x1e600800u); return;
  case SO_FDIV: a64s_float_binary(e, v, 0x1e601800u); return;
  case SO_MATH: {
    d = a64s_target(v);
    unsigned ra = a64s_v(a64s_get(e, v->a, X_XMM0 + A_F1));
    bool f32 = v->cls == SC_F32;
    if (v->aux == DYN_MATH_INTRINSIC_FMA) {
      unsigned rb = a64s_v(a64s_get(e, v->b, X_XMM0 + A_F2));
      unsigned rc = a64s_v(a64s_get(e, v->c, X_XMM0 + A_F3));
      a64_word(ctx, (f32 ? 0x1f000000u : 0x1f400000u) | rb << 16 | rc << 10 | ra << 5 | a64s_v(d));
    } else {
      uint32_t opcode = v->aux == DYN_MATH_INTRINSIC_SQRT ? 0x1e61c000u :
                        v->aux == DYN_MATH_INTRINSIC_FLOOR ? 0x1e654000u :
                        v->aux == DYN_MATH_INTRINSIC_CEIL ? 0x1e64c000u :
                        v->aux == DYN_MATH_INTRINSIC_TRUNC ? 0x1e65c000u :
                        v->aux == DYN_MATH_INTRINSIC_ROUND ? 0x1e664000u : 0;
      if (!opcode) { ctx->text.failed = true; return; }
      a64_word(ctx, (opcode & ~(f32 ? 0x400000u : 0)) | ra << 5 | a64s_v(d));
    }
    a64s_put(e, v, d);
    return;
  }
  case SO_FNEG:
    d = a64s_target(v);
    a64_word(ctx, (v->cls == SC_F32 ? 0x1e214000u : 0x1e614000u) | a64s_v(a64s_get(e, v->a, X_XMM0 + A_F1)) << 5 | a64s_v(d));
    a64s_put(e, v, d);
    return;
  case SO_ITOF:
    d = a64s_target(v);
    a64_word(ctx, (v->cls == SC_F32 ? 0x9e220000u : 0x9e620000u) | (v->aux ? 0x10000u : 0) | a64s_get(e, v->a, A_S1) << 5 | a64s_v(d));
    a64s_put(e, v, d);
    return;
  case SO_FTOI: {
    bool f32 = s->values[v->a].cls == SC_F32;
    d = a64s_target(v);
    a64_word(ctx, (f32 ? 0x9e380000u : 0x9e780000u) | (v->aux ? 0x10000u : 0) | a64s_v(a64s_get(e, v->a, X_XMM0 + A_F1)) << 5 | d);
    a64s_put(e, v, d);
    return;
  }
  case SO_FCVT:
    d = a64s_target(v);
    a64_word(ctx, (v->cls == SC_F32 ? 0x1e624000u : 0x1e22c000u) | a64s_v(a64s_get(e, v->a, X_XMM0 + A_F1)) << 5 | a64s_v(d));
    a64s_put(e, v, d);
    return;
  case SO_BITS: {
    d = a64s_target(v);
    bool wide = v->cls == SC_F64 || s->values[v->a].cls == SC_F64;
    if (a64s_floating(d)) a64_word(ctx, (wide ? 0x9e670000u : 0x1e270000u) | a64s_get(e, v->a, A_S1) << 5 | a64s_v(d));
    else a64_word(ctx, (wide ? 0x9e660000u : 0x1e260000u) | a64s_v(a64s_get(e, v->a, X_XMM0 + A_F1)) << 5 | d);
    a64s_put(e, v, d);
    return;
  }
  case SO_LOAD: case SO_STORE: case SO_LEA: {
    SsaMemory m = {A64_FP, -1, v->scale, (int32_t)v->aux};
    int64_t disp = v->aux;
    if (v->a >= 0 && s->values[v->a].op == SO_FRAME) disp += s->values[v->a].aux;
    else if (v->a >= 0) m.base = (int)a64s_get(e, v->a, A_S1);
    if (v->b >= 0 && ssa_is_const(s, v->b, &c)) disp += (int64_t)c * v->scale;
    else if (v->b >= 0) m.index = (int)a64s_get(e, v->b, A_S2);
    if (disp != (int32_t)disp) { ctx->text.failed = true; return; }
    m.disp = (int32_t)disp;
    unsigned bits = v->aux2 & 0xff;
    bool sign = v->aux2 >> 8 & 1, fl = v->aux2 >> 9 & 1;
    if (v->op == SO_LEA) {
      d = a64s_target(v);
      if (m.index >= 0) {
        unsigned shift = m.scale == 8 ? 3 : m.scale == 4 ? 2 : m.scale == 2 ? 1 : 0;
        a64_word(ctx, 0x8b000000u | shift << 10 | (uint32_t)m.index << 16 | (uint32_t)m.base << 5 | d);
        a64s_add_immediate(ctx, d, d, m.disp);
      } else a64s_add_immediate(ctx, d, (unsigned)m.base, m.disp);
      a64s_put(e, v, d);
      return;
    }
    if (v->op == SO_LOAD) {
      d = a64s_target(v);
      a64s_memory(ctx, bits, sign, fl, false, fl ? a64s_v(d) : d, m);
      a64s_put(e, v, d);
      return;
    }
    unsigned rv;
    if (ssa_is_const(s, v->c, &c) && !c && !fl) rv = A_ZR;
    else rv = a64s_get(e, v->c, fl ? X_XMM0 + A_F1 : A_S4);
    a64s_memory(ctx, bits, false, fl, true, fl ? a64s_v(rv) : rv, m);
    return;
  }
  case SO_SYMBOL:
    d = a64s_target(v);
    a64s_symbol(e, d, v);
    a64s_put(e, v, d);
    return;
  case SO_CHECK: {
    Cond cond = a64s_compare(e, v->a, v->b, (Cond)v->cond);
    a64s_fail(e, a64_cond[cond] ^ 1, (unsigned)v->aux);
    return;
  }
  case SO_VECTOR: {
    /* x14/x15/x16 walk the arrays, x17 counts 16-byte lanes. */
    unsigned bytes = (unsigned)(v->aux2 >> 8), op = (unsigned)(v->aux2 & 0xff);
    a64s_add_immediate(ctx, A_S4, A64_FP, (int32_t)s->values[v->b].aux);
    a64s_add_immediate(ctx, A_S3, A64_FP, (int32_t)s->values[v->c].aux);
    a64s_add_immediate(ctx, A_S1, A64_FP, (int32_t)s->values[v->a].aux);
    a64s_immediate(ctx, A_S2, (uint64_t)v->aux * bytes / 16);
    size_t begin = ctx->text.n;
    a64_word(ctx, 0x3cc10400u | A_S4 << 5 | A_F2);  /* ldr q30, [x14], #16 */
    a64_word(ctx, 0x3cc10400u | A_S3 << 5 | A_F1);  /* ldr q31, [x15], #16 */
    uint32_t instruction = op == DYN_OP_ADD ? (bytes == 8 ? 0x4ee08400u : 0x4ea08400u)
        : op == DYN_OP_SUB ? (bytes == 8 ? 0x6ee08400u : 0x6ea08400u)
        : op == DYN_OP_BIT_AND ? 0x4e201c00u : op == DYN_OP_BIT_OR ? 0x4ea01c00u : 0x6e201c00u;
    a64_word(ctx, instruction | A_F1 << 16 | A_F2 << 5 | A_F2);
    a64_word(ctx, 0x3c810400u | A_S1 << 5 | A_F2);  /* str q30, [x16], #16 */
    a64_word(ctx, 0xf1000400u | A_S2 << 5 | A_S2);  /* subs x17, x17, #1 */
    a64_word(ctx, 0x54000001u | (uint32_t)(((int64_t)begin - (int64_t)ctx->text.n) / 4 & 0x7ffff) << 5); /* b.ne */
    return;
  }
  case SO_SUM: a64s_sum(e, v); return;
  case SO_AXPY: a64s_axpy(e, v); return;
  case SO_VLOOP: a64s_vloop(e, v); return;
  case SO_TRAP: isa_trap(ctx); return;
  case SO_COPYMEM: a64s_copy_memory(e, v); return;
  case SO_ZEROMEM: a64s_zero_memory(e, v); return;
  case SO_CALL:
    if (v->cond) { a64s_protect_begin(e, block); ssa_call_emit(e, block, k); a64s_protect_end(e); }
    else ssa_call_emit(e, block, k);
    return;
  case SO_FAIL: {
    const DynIrFunction *origin = v->check_origin && v->check_origin <= s->ir->function_count
        ? &s->ir->functions[v->check_origin - 1] : s->f;
    const char *name = function_name(origin);
    size_t length = strlen(name);
    if (length > 800) length = 800;
    isa_string_arguments(ctx, literal(ctx, name, length), (size_t)v->aux << 24 | length);
    runtime_call(ctx, RUNTIME_CHECK_FAILED);
    isa_trap(ctx);
    return;
  }
  case SO_CONTINUE: runtime_call(ctx, 6); isa_trap(ctx); return;
  case SO_PANIC: {
    SsaMove moves[2] = {ssa_source(e, v->a), ssa_source(e, v->b)};
    moves[0].dst_kind = moves[1].dst_kind = L_REG; moves[0].dst = 0; moves[1].dst = 1;
    moves[0].cls = moves[1].cls = SC_INT;
    if (v->cond) a64s_protect_begin(e, block);
    ssa_parallel(e, moves, 2);
    runtime_call(ctx, 0);
    isa_trap(ctx);
    return;
  }
  default:
    ctx->text.failed = true;
    return;
  }
}
