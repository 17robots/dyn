/* RISC-V64 emission for SSA code generation (included by ssa.inc).

   Register ids: 0-31 are x0-x31, X_XMM0 + n is fn. RISC-V has no condition
   flags: a comparison records its two operand registers and the following
   branch tests them directly. x5-x7 and x28-x31 are emitter scratch (x28 forms large memory addresses), as are
   f30 and f31; x8 (s0) is the frame pointer. */

enum { R_S1 = 30, R_S2 = 31, R_S3 = 29, R_S4 = 7, R_T = 28, R_F1 = 31, R_F2 = 30 };

static bool rvs_floating(unsigned reg) { return reg >= X_XMM0; }
static unsigned rvs_f(unsigned reg) { return reg - X_XMM0; }
static void rvs_mov(BackendContext *ctx, unsigned to, unsigned from) {
  if (to == from) return;
  if (rvs_floating(to) && rvs_floating(from)) rv_r(ctx, 0x53, rvs_f(to), rvs_f(from), rvs_f(from), 0, 0x11); /* fsgnj.d */
  else if (rvs_floating(to)) rv_r(ctx, 0x53, rvs_f(to), from, 0, 0, 0x79);                                /* fmv.d.x */
  else if (rvs_floating(from)) rv_r(ctx, 0x53, to, rvs_f(from), 0, 0, 0x71);                              /* fmv.x.d */
  else rv_move(ctx, to, from);
}
/* Single-precision values sit NaN-boxed in the 64-bit float registers, so
   f32 constants move with fmv.w.x. */
static void rvs_immediate_class(BackendContext *ctx, unsigned reg, uint64_t n, uint8_t cls) {
  if (rvs_floating(reg)) {
    unsigned source = 0;
    if (n) { rv_imm(ctx, R_S4, n); source = R_S4; }
    rv_r(ctx, 0x53, rvs_f(reg), source, 0, 0, cls == SC_F32 ? 0x78 : 0x79);
    return;
  }
  rv_imm(ctx, reg, n);
}
/* rd <- rn + n; rd may equal rn. Large constants go through x7. */
static void rvs_add_immediate(BackendContext *ctx, unsigned rd, unsigned rn, int64_t n) {
  if (n >= -2048 && n <= 2047) { if (n || rd != rn) rv_i(ctx, 0x13, rd, rn, n, 0); return; }
  rv_imm(ctx, R_S4, (uint64_t)n);
  rv_r(ctx, 0x33, rd, rn, R_S4, 0, 0);
}
/* Load or store: base + index * scale + disp, through x29 when needed. */
static void rvs_access(BackendContext *ctx, bool store, unsigned bits, bool sign, bool floating, unsigned reg, SsaMemory m) {
  unsigned base = (unsigned)m.base;
  int64_t disp = m.disp;
  if (disp < -2048 || disp > 2047) {
    /* Build the address in x28: rvs_add_immediate would use x7, which may
       hold the stored value. */
    rv_imm(ctx, R_T, (uint64_t)disp);
    rv_r(ctx, 0x33, R_T, R_T, base, 0, 0);
    base = R_T;
    disp = 0;
  }
  if (m.index >= 0) {
    unsigned shift = m.scale == 8 ? 3 : m.scale == 4 ? 2 : m.scale == 2 ? 1 : 0;
    unsigned index = (unsigned)m.index;
    if (shift) { rv_i(ctx, 0x13, R_S3, index, shift, 1); index = R_S3; }
    rv_r(ctx, 0x33, R_S3, base, index, 0, 0);
    base = R_S3;
  }
  unsigned f3;
  if (floating) f3 = bits == 32 ? 2 : 3;
  else if (store) f3 = bits == 8 ? 0 : bits == 16 ? 1 : bits == 32 ? 2 : 3;
  else f3 = bits == 8 ? (sign ? 0 : 4) : bits == 16 ? (sign ? 1 : 5) : bits == 32 ? (sign ? 2 : 6) : 3;
  rv_memory(ctx, store, floating ? rvs_f(reg) : reg, base, disp, f3, floating);
}
static void rvs_slot_access(BackendContext *ctx, bool store, unsigned reg, SsaMemory m) {
  rvs_access(ctx, store, 64, false, rvs_floating(reg), reg, m);
}
static SsaMemory rvs_slot(SsaEmit *e, const SsaValue *v) {
  return (SsaMemory){8, -1, 1, (int32_t)(e->spill_base - 8 * (uint32_t)v->slot)};
}
static unsigned rvs_get(SsaEmit *e, int32_t id, unsigned scratch) {
  Ssa *s = e->s; BackendContext *ctx = e->ctx;
  SsaValue *v = &s->values[id];
  bool floating = v->cls == SC_F64 || v->cls == SC_F32;
  if (floating && !rvs_floating(scratch)) scratch = X_XMM0 + R_F1;
  if (v->op == SO_CONST && !ssa_located(v)) {
    if (!floating && !v->aux) return 0; /* x0 */
    rvs_immediate_class(ctx, scratch, (uint64_t)v->aux, v->cls);
    return scratch;
  }
  if (v->op == SO_FRAME) { rvs_add_immediate(ctx, scratch, 8, (int32_t)v->aux); return scratch; }
  if (v->reg >= 0) return (unsigned)v->reg;
  if (v->slot < 0) { ctx->text.failed = true; return scratch; }
  rvs_slot_access(ctx, false, scratch, rvs_slot(e, v));
  return scratch;
}
static unsigned rvs_target(const SsaValue *v) {
  if (v->reg >= 0) return (unsigned)v->reg;
  return v->cls == SC_F64 || v->cls == SC_F32 ? X_XMM0 + R_F1 : R_S1;
}
static void rvs_put(SsaEmit *e, const SsaValue *v, unsigned reg) {
  if (v->reg >= 0) { rvs_mov(e->ctx, (unsigned)v->reg, reg); return; }
  if (v->slot >= 0) rvs_slot_access(e->ctx, true, reg, rvs_slot(e, v));
}
static void rvs_transfer(SsaEmit *e, uint8_t dst_kind, int64_t dst, uint8_t src_kind, int64_t src, uint8_t cls) {
  BackendContext *ctx = e->ctx;
  bool fl = cls == SC_F64 || cls == SC_F32;
  unsigned reg = dst_kind == L_REG ? (unsigned)dst : fl ? X_XMM0 + R_F2 : R_S2;
  if (src_kind == L_REG) {
    if (dst_kind == L_REG) { rvs_mov(ctx, reg, (unsigned)src); return; }
    reg = (unsigned)src;
  } else if (src_kind == L_CONST) rvs_immediate_class(ctx, reg, (uint64_t)src, cls);
  else if (src_kind == L_FRAME) rvs_add_immediate(ctx, reg, 8, src);
  else rvs_slot_access(ctx, false, reg, (SsaMemory){src_kind == L_SLOT ? 8 : 2, -1, 1, (int32_t)src});
  if (dst_kind == L_REG) return;
  rvs_slot_access(ctx, true, reg, (SsaMemory){dst_kind == L_SLOT ? 8 : 2, -1, 1, (int32_t)dst});
}
/* Branch operands for a condition: registers and funct3, swapping where
   RISC-V only has the mirrored comparison. */
static void rvs_condition(int cond, unsigned a, unsigned b, unsigned *x, unsigned *y, unsigned *f3) {
  *x = a; *y = b;
  switch (cond) {
  case CC_E: *f3 = 0; break;
  case CC_NE: *f3 = 1; break;
  case CC_L: *f3 = 4; break;
  case CC_GE: *f3 = 5; break;
  case CC_B: *f3 = 6; break;
  case CC_AE: *f3 = 7; break;
  case CC_LE: *x = b; *y = a; *f3 = 5; break;
  case CC_G: *x = b; *y = a; *f3 = 4; break;
  case CC_BE: *x = b; *y = a; *f3 = 7; break;
  default: *x = b; *y = a; *f3 = 6; break; /* CC_A */
  }
}
static uint32_t rvs_b_type(unsigned x, unsigned y, unsigned f3, int32_t offset) {
  uint32_t u = (uint32_t)offset;
  return 0x63 | ((u >> 11) & 1) << 7 | ((u >> 1) & 15) << 8 | f3 << 12 | x << 15 | y << 20 | ((u >> 5) & 63) << 25 | ((u >> 12) & 1) << 31;
}
static uint32_t rvs_j_type(int32_t offset) {
  uint32_t u = (uint32_t)offset;
  return 0x6f | ((u >> 12) & 255) << 12 | ((u >> 11) & 1) << 20 | ((u >> 1) & 1023) << 21 | ((u >> 20) & 1) << 31;
}
/* A branch on the recorded comparison (or always, condition < 0): a short branch is
   one instruction, far an inverted branch over auipc/jalr. Returns the slot
   ssa_jump_to records. */
static size_t rvs_branch(SsaEmit *e, int condition, bool short_branch) {
  BackendContext *ctx = e->ctx;
  unsigned x = 0, y = 0, f3 = 0;
  if (condition >= 0) rvs_condition(condition, e->rv_a, e->rv_b, &x, &y, &f3);
  if (short_branch) {
    size_t at = ctx->text.n;
    word(ctx, condition >= 0 ? rvs_b_type(x, y, f3, 0) : rvs_j_type(0));
    return at;
  }
  if (condition >= 0) word(ctx, rvs_b_type(x, y, f3 ^ 1, 12));
  size_t at = ctx->text.n;
  word(ctx, 0x00000317u);         /* auipc x6, 0 */
  rv_i(ctx, 0x67, 0, 6, 0, 0);     /* jalr x0, 0(x6) */
  return at;
}
static void rvs_patch_near(BackendContext *ctx, size_t at, size_t target) {
  uint32_t instruction = (uint32_t)ctx->text.data[at] | (uint32_t)ctx->text.data[at + 1] << 8 |
                         (uint32_t)ctx->text.data[at + 2] << 16 | (uint32_t)ctx->text.data[at + 3] << 24;
  int64_t delta = (int64_t)target - (int64_t)at;
  if ((instruction & 0x7f) == 0x63) {
    if (delta < -4096 || delta > 4094) { ctx->text.failed = true; return; }
    patch_word(ctx, at, rvs_b_type(instruction >> 15 & 31, instruction >> 20 & 31, instruction >> 12 & 7, (int32_t)delta));
  } else {
    if (delta < -(1 << 20) || delta >= (1 << 20)) { ctx->text.failed = true; return; }
    patch_word(ctx, at, rvs_j_type((int32_t)delta));
  }
}
static void rvs_fail(SsaEmit *e, int condition, unsigned kind) {
  size_t at = rvs_branch(e, condition, false);
  e->stub_uses = ssa_grow(e->stub_uses, &e->stub_use_capacity, e->stub_use_count + 1, sizeof(*e->stub_uses), &e->s->failed);
  if (!e->s->failed) { e->stub_uses[e->stub_use_count].at = at; e->stub_uses[e->stub_use_count++].kind = kind; }
}
/* Records a comparison of a and b for the next branch. */
static Cond rvs_compare(SsaEmit *e, int32_t a, int32_t b, Cond cond) {
  e->rv_a = rvs_get(e, a, R_S1);
  e->rv_b = rvs_get(e, b, R_S2);
  return cond;
}
static void rvs_set(BackendContext *ctx, unsigned d, Cond cond, unsigned a, unsigned b) {
  switch (cond) {
  case CC_E: rv_r(ctx, 0x33, d, a, b, 4, 0); rv_i(ctx, 0x13, d, d, 1, 3); break;    /* xor; sltiu 1 */
  case CC_NE: rv_r(ctx, 0x33, d, a, b, 4, 0); rv_r(ctx, 0x33, d, 0, d, 3, 0); break; /* xor; sltu x0 */
  case CC_L: rv_r(ctx, 0x33, d, a, b, 2, 0); break;
  case CC_GE: rv_r(ctx, 0x33, d, a, b, 2, 0); rv_i(ctx, 0x13, d, d, 1, 4); break;
  case CC_B: rv_r(ctx, 0x33, d, a, b, 3, 0); break;
  case CC_AE: rv_r(ctx, 0x33, d, a, b, 3, 0); rv_i(ctx, 0x13, d, d, 1, 4); break;
  case CC_G: rv_r(ctx, 0x33, d, b, a, 2, 0); break;
  case CC_LE: rv_r(ctx, 0x33, d, b, a, 2, 0); rv_i(ctx, 0x13, d, d, 1, 4); break;
  case CC_A: rv_r(ctx, 0x33, d, b, a, 3, 0); break;
  default: rv_r(ctx, 0x33, d, b, a, 3, 0); rv_i(ctx, 0x13, d, d, 1, 4); break; /* CC_BE */
  }
}
static void rvs_binary(SsaEmit *e, SsaValue *v, unsigned f3, unsigned f7) {
  unsigned d = rvs_target(v), ra = rvs_get(e, v->a, R_S1), rb = rvs_get(e, v->b, R_S2);
  rv_r(e->ctx, 0x33, d, ra, rb, f3, f7);
  rvs_put(e, v, d);
}
static void rvs_float_binary(SsaEmit *e, SsaValue *v, unsigned f7) {
  unsigned d = rvs_target(v), ra = rvs_get(e, v->a, X_XMM0 + R_F1), rb = rvs_get(e, v->b, X_XMM0 + R_F2);
  rv_r(e->ctx, 0x53, rvs_f(d), rvs_f(ra), rvs_f(rb), 7, f7 | (v->cls == SC_F32 ? 0 : 1));
  rvs_put(e, v, d);
}
static void rvs_extend(BackendContext *ctx, unsigned d, unsigned n, unsigned bits, bool sign) {
  if (bits >= 64) { rv_move(ctx, d, n); return; }
  if (bits == 1) { rv_i(ctx, 0x13, d, n, 1, 7); return; }
  rv_i(ctx, 0x13, d, n, 64 - bits, 1);
  rv_i(ctx, 0x13, d, d, (sign ? 0x400 : 0) + 64 - bits, 5);
}
/* Byte-wise memmove of aux bytes: x29 destination, x30 source, x31 count. */
static void rvs_copy_memory(SsaEmit *e, SsaValue *v) {
  BackendContext *ctx = e->ctx;
  uint32_t size = (uint32_t)v->aux;
  if (!size) return;
  unsigned rd = rvs_get(e, v->a, R_S3), rs = rvs_get(e, v->b, R_S1);
  rv_move(ctx, 5, rd); rv_move(ctx, R_S1, rs); rv_move(ctx, R_S3, 5);
  rv_imm(ctx, R_S2, size);
  /* Backward when the destination is above the source. */
  size_t forward = ctx->text.n;
  word(ctx, rvs_b_type(R_S1, R_S3, 7, 0)); /* bgeu src, dst, forward */
  size_t back = ctx->text.n;
  word(ctx, rvs_b_type(R_S2, 0, 0, 0)); /* beq count, x0, done */
  rv_i(ctx, 0x13, R_S2, R_S2, -1, 0);
  rv_r(ctx, 0x33, 6, R_S1, R_S2, 0, 0); rv_memory(ctx, false, 7, 6, 0, 4, false);
  rv_r(ctx, 0x33, 6, R_S3, R_S2, 0, 0); rv_memory(ctx, true, 7, 6, 0, 0, false);
  word(ctx, rvs_j_type((int32_t)((int64_t)back - (int64_t)ctx->text.n)));
  size_t forward_at = ctx->text.n;
  patch_word(ctx, forward, rvs_b_type(R_S1, R_S3, 7, (int32_t)(forward_at - forward)));
  size_t loop = ctx->text.n;
  word(ctx, rvs_b_type(R_S2, 0, 0, 0)); /* beq count, x0, done */
  rv_memory(ctx, false, 7, R_S1, 0, 4, false); rv_memory(ctx, true, 7, R_S3, 0, 0, false);
  rv_i(ctx, 0x13, R_S1, R_S1, 1, 0); rv_i(ctx, 0x13, R_S3, R_S3, 1, 0); rv_i(ctx, 0x13, R_S2, R_S2, -1, 0);
  word(ctx, rvs_j_type((int32_t)((int64_t)loop - (int64_t)ctx->text.n)));
  size_t done = ctx->text.n;
  patch_word(ctx, back, rvs_b_type(R_S2, 0, 0, (int32_t)(done - back)));
  patch_word(ctx, loop, rvs_b_type(R_S2, 0, 0, (int32_t)(done - loop)));
}
static void rvs_zero_memory(SsaEmit *e, SsaValue *v) {
  BackendContext *ctx = e->ctx;
  uint32_t size = (uint32_t)v->aux;
  if (!size) return;
  rv_move(ctx, R_S3, rvs_get(e, v->a, R_S3));
  if (size <= 64) {
    for (uint32_t at = 0; at < size;) {
      unsigned width = size - at >= 8 ? 8 : size - at >= 4 ? 4 : size - at >= 2 ? 2 : 1;
      rv_memory(ctx, true, 0, R_S3, at, width == 8 ? 3 : width == 4 ? 2 : width == 2 ? 1 : 0, false);
      at += width;
    }
    return;
  }
  rv_imm(ctx, R_S2, size);
  size_t loop = ctx->text.n;
  rv_memory(ctx, true, 0, R_S3, 0, 0, false);
  rv_i(ctx, 0x13, R_S3, R_S3, 1, 0); rv_i(ctx, 0x13, R_S2, R_S2, -1, 0);
  word(ctx, rvs_b_type(R_S2, 0, 1, (int32_t)((int64_t)loop - (int64_t)ctx->text.n))); /* bne count, x0, loop */
}
static void rvs_frame_argument(SsaEmit *e, uint32_t offset) { rvs_add_immediate(e->ctx, 10, 8, (int32_t)offset); }
static void rvs_protect_begin(SsaEmit *e, SsaBlock *block) {
  BackendContext *ctx = e->ctx;
  rvs_frame_argument(e, e->s->unwind_offset); runtime_call(ctx, 3);
  e->rv_a = 10; e->rv_b = 0;
  ssa_jump_to(e, CC_NE, block->succ[1]);
  rvs_frame_argument(e, e->s->unwind_offset); runtime_call(ctx, 4);
}
static void rvs_protect_end(SsaEmit *e) {
  BackendContext *ctx = e->ctx;
  int32_t at = (int32_t)e->s->results_offset;
  static const unsigned char saved[] = {10, 11, X_XMM0 + 10, X_XMM0 + 11};
  for (unsigned i = 0; i < 4; ++i) rvs_slot_access(ctx, true, saved[i], (SsaMemory){8, -1, 1, at + 8 * (int32_t)i});
  rvs_frame_argument(e, e->s->unwind_offset); runtime_call(ctx, 5);
  for (unsigned i = 0; i < 4; ++i) rvs_slot_access(ctx, false, saved[i], (SsaMemory){8, -1, 1, at + 8 * (int32_t)i});
}
static void rvs_emit_value(SsaEmit *e, SsaBlock *block, uint32_t *k) {
  Ssa *s = e->s; BackendContext *ctx = e->ctx;
  uint32_t id = block->values.items[*k];
  SsaValue *v = &s->values[id];
  if (v->dead && v->op != SO_CALL) return;
  unsigned d;
  uint64_t c;
  switch (v->op) {
  case SO_CONST:
    if (ssa_located(v)) { d = rvs_target(v); rvs_immediate_class(ctx, d, (uint64_t)v->aux, v->cls); rvs_put(e, v, d); }
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
    if (ssa_is_const(s, v->b, &c) && (int64_t)c >= -2047 && (int64_t)c <= 2047) {
      d = rvs_target(v);
      rvs_add_immediate(ctx, d, rvs_get(e, v->a, R_S1), v->op == SO_ADD ? (int64_t)c : -(int64_t)c);
      rvs_put(e, v, d);
      return;
    }
    rvs_binary(e, v, 0, v->op == SO_ADD ? 0 : 0x20);
    return;
  case SO_AND: rvs_binary(e, v, 7, 0); return;
  case SO_OR: rvs_binary(e, v, 6, 0); return;
  case SO_XOR: rvs_binary(e, v, 4, 0); return;
  case SO_MUL: rvs_binary(e, v, 0, 1); return;
  case SO_MULH: rvs_binary(e, v, v->aux2 ? 1 : 3, 1); return;
  case SO_SHL: case SO_SHR: case SO_SAR:
    d = rvs_target(v);
    if (ssa_is_const(s, v->b, &c)) {
      rv_i(ctx, 0x13, d, rvs_get(e, v->a, R_S1), (int64_t)(c & 63) | (v->op == SO_SAR ? 0x400 : 0), v->op == SO_SHL ? 1 : 5);
      rvs_put(e, v, d);
      return;
    }
    rvs_binary(e, v, v->op == SO_SHL ? 1 : 5, v->op == SO_SAR ? 0x20 : 0);
    return;
  case SO_DIV: rvs_binary(e, v, v->aux2 ? 4 : 5, 1); return;
  case SO_REM: rvs_binary(e, v, v->aux2 ? 6 : 7, 1); return;
  case SO_NEG:
    d = rvs_target(v);
    rv_r(ctx, 0x33, d, 0, rvs_get(e, v->a, R_S1), 0, 0x20);
    rvs_put(e, v, d);
    return;
  case SO_NOT:
    d = rvs_target(v);
    rv_i(ctx, 0x13, d, rvs_get(e, v->a, R_S1), -1, 4);
    rvs_put(e, v, d);
    return;
  case SO_EXT:
    d = rvs_target(v);
    rvs_extend(ctx, d, rvs_get(e, v->a, R_S1), (unsigned)v->aux, v->aux2 != 0);
    rvs_put(e, v, d);
    return;
  case SO_CMP: {
    if (v->fused) return;
    unsigned ra = rvs_get(e, v->a, R_S1), rb = rvs_get(e, v->b, R_S2);
    d = rvs_target(v);
    rvs_set(ctx, d, (Cond)v->cond, ra, rb);
    rvs_put(e, v, d);
    return;
  }
  case SO_FCMP: {
    bool f32 = s->values[v->a].cls == SC_F32;
    unsigned ra = rvs_get(e, v->a, X_XMM0 + R_F1), rb = rvs_get(e, v->b, X_XMM0 + R_F2), op = (unsigned)v->aux;
    unsigned left = op >= 4 ? rb : ra, right = op >= 4 ? ra : rb;
    d = rvs_target(v);
    rv_r(ctx, 0x53, d, rvs_f(left), rvs_f(right), op < 2 ? 2 : (op == 2 || op == 4) ? 1 : 0, f32 ? 0x50 : 0x51);
    if (op == 1) rv_i(ctx, 0x13, d, d, 1, 4);
    rvs_put(e, v, d);
    return;
  }
  case SO_FADD: rvs_float_binary(e, v, 0x00); return;
  case SO_FSUB: rvs_float_binary(e, v, 0x04); return;
  case SO_FMUL: rvs_float_binary(e, v, 0x08); return;
  case SO_FDIV: rvs_float_binary(e, v, 0x0c); return;
  case SO_FNEG: {
    d = rvs_target(v);
    unsigned ra = rvs_f(rvs_get(e, v->a, X_XMM0 + R_F1));
    rv_r(ctx, 0x53, rvs_f(d), ra, ra, 1, v->cls == SC_F32 ? 0x10 : 0x11);
    rvs_put(e, v, d);
    return;
  }
  case SO_ITOF:
    d = rvs_target(v);
    rv_r(ctx, 0x53, rvs_f(d), rvs_get(e, v->a, R_S1), v->aux ? 3 : 2, 7, v->cls == SC_F32 ? 0x68 : 0x69);
    rvs_put(e, v, d);
    return;
  case SO_FTOI: {
    bool f32 = s->values[v->a].cls == SC_F32;
    d = rvs_target(v);
    rv_r(ctx, 0x53, d, rvs_f(rvs_get(e, v->a, X_XMM0 + R_F1)), v->aux ? 3 : 2, 1, f32 ? 0x60 : 0x61);
    rvs_put(e, v, d);
    return;
  }
  case SO_FCVT:
    d = rvs_target(v);
    rv_r(ctx, 0x53, rvs_f(d), rvs_f(rvs_get(e, v->a, X_XMM0 + R_F1)), v->cls == SC_F32 ? 1 : 0, 7, v->cls == SC_F32 ? 0x20 : 0x21);
    rvs_put(e, v, d);
    return;
  case SO_BITS: {
    d = rvs_target(v);
    bool wide = v->cls == SC_F64 || s->values[v->a].cls == SC_F64;
    if (rvs_floating(d)) rv_r(ctx, 0x53, rvs_f(d), rvs_get(e, v->a, R_S1), 0, 0, wide ? 0x79 : 0x78);
    else {
      rv_r(ctx, 0x53, d, rvs_f(rvs_get(e, v->a, X_XMM0 + R_F1)), 0, 0, wide ? 0x71 : 0x70);
      if (!wide) rvs_extend(ctx, d, d, 32, false); /* fmv.x.w sign-extends */
    }
    rvs_put(e, v, d);
    return;
  }
  case SO_LOAD: case SO_STORE: case SO_LEA: {
    SsaMemory m = {8, -1, v->scale, 0};
    int64_t disp = v->aux;
    if (v->a >= 0 && s->values[v->a].op == SO_FRAME) disp += s->values[v->a].aux;
    else if (v->a >= 0) m.base = (int)rvs_get(e, v->a, R_S1);
    if (v->b >= 0 && ssa_is_const(s, v->b, &c)) disp += (int64_t)c * v->scale;
    else if (v->b >= 0) m.index = (int)rvs_get(e, v->b, R_S2);
    if (disp != (int32_t)disp) { ctx->text.failed = true; return; }
    m.disp = (int32_t)disp;
    unsigned bits = v->aux2 & 0xff;
    bool sign = v->aux2 >> 8 & 1, fl = v->aux2 >> 9 & 1;
    if (v->op == SO_LEA) {
      d = rvs_target(v);
      unsigned base = (unsigned)m.base;
      if (m.index >= 0) {
        unsigned shift = m.scale == 8 ? 3 : m.scale == 4 ? 2 : m.scale == 2 ? 1 : 0, index = (unsigned)m.index;
        if (shift) { rv_i(ctx, 0x13, R_S3, index, shift, 1); index = R_S3; }
        rv_r(ctx, 0x33, d, base, index, 0, 0);
        base = d;
      }
      rvs_add_immediate(ctx, d, base, m.disp);
      rvs_put(e, v, d);
      return;
    }
    if (v->op == SO_LOAD) {
      d = rvs_target(v);
      rvs_access(ctx, false, bits, sign, fl, d, m);
      rvs_put(e, v, d);
      return;
    }
    unsigned rv = rvs_get(e, v->c, fl ? X_XMM0 + R_F1 : R_S4);
    rvs_access(ctx, true, bits, false, fl, rv, m);
    return;
  }
  case SO_SYMBOL:
    d = rvs_target(v);
    rv_symbol(ctx, d, (unsigned)v->aux, v->aux2 == SYM_LOCAL ? v->c : 0, v->aux2 != SYM_LOCAL);
    rvs_put(e, v, d);
    return;
  case SO_CHECK: {
    Cond cond = rvs_compare(e, v->a, v->b, (Cond)v->cond);
    rvs_fail(e, cond ^ 1, (unsigned)v->aux);
    return;
  }
  case SO_TRAP: isa_trap(ctx); return;
  case SO_COPYMEM: rvs_copy_memory(e, v); return;
  case SO_ZEROMEM: rvs_zero_memory(e, v); return;
  case SO_CALL:
    if (v->cond) { rvs_protect_begin(e, block); ssa_call_emit(e, block, k); rvs_protect_end(e); }
    else ssa_call_emit(e, block, k);
    return;
  case SO_FAIL: {
    const char *name = function_name(s->f);
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
    moves[0].dst_kind = moves[1].dst_kind = L_REG; moves[0].dst = 10; moves[1].dst = 11;
    moves[0].cls = moves[1].cls = SC_INT;
    if (v->cond) rvs_protect_begin(e, block);
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
