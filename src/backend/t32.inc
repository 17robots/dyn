/* ARMv7E-M (Thumb-2, FPv5-D16) lowering of the 64-bit register model
   (included by driver.c after rv32.inc, whose operation selectors it shares).

   Every model register is a pair of 32-bit words. Thumb has too few core
   registers to keep all sixteen words in them, so the low words and the
   high words of A and C live in core registers and the other high words in
   callee-saved VFP registers:

     A r0:r4   C r2:r5   D r1:s16   SI r3:s17   DI r6:s18
     R8 r7:s19   R10 r8:s20   R11 r9:s21

   r11 is the frame base, biased by T32_BIAS so that one 12-bit positive
   offset reaches most locals; r10 and r12 are scratch, and lr holds
   addresses that do not fit an instruction's offset. A comparison stores its
   operands in s24-s27 (low words, then high words) and a branch evaluates
   the condition from them; add, subtract and negate keep their flags in s28
   for overflow checks. Values of 32 bits or fewer keep their high word
   extended, as on the 64-bit targets.

   Every function saves r3-r11 and lr, then d8-d15. Calls follow the AAPCS
   with the VFP variant: 32-bit values take one core register, 64-bit
   integers an even pair, doubles a d register and floats an s register.
   Division, checked multiplication and 64-bit integer/floating conversions
   call helpers in the start runtime (dyn_t32_*), which use the model
   directly.

   Soft mode uses integer AAPCS and dyn_soft_* helpers. The same 64-byte
   frame overhead replaces the VFP save area with a bank at unbiased FP-64:
   s16-s21 denote high-word slots, s24-s27 comparison slots, s28 flags.
   Negative local offsets are translated down 64 bytes by t32_frame and
   t32_frame_address; incoming positive offsets stay unchanged. DWARF local
   locations must apply the same -64 adjustment, but CFA and saved core
   offsets remain unchanged. Startup unwind snapshots this fixed bank. */
static const unsigned char t32_lo[] = {0,2,1,3,6,7,8,9};
static const unsigned char t32_hi[] = {4,5,16,17,18,19,20,21}; /* core for A and C, else s registers */
enum { T32_T1 = 10, T32_T2 = 12, T32_ADDRESS = 14, T32_FP = 11, T32_SP = 13,
       T32_LOW_A = 24, T32_HIGH_A = 26, T32_FLAGS = 28, T32_SAVED = 64 /* d8-d15 */,
       T32_PUSHED = 40 /* r3-r11 and lr */, T32_BIAS = 4092,
       T32_STRUCT_WORDS = 16 /* larger struct arguments pass a pointer to a copy */ };
enum { T32_AND = 0, T32_BIC = 1, T32_ORR = 2, T32_ORN = 3, T32_EOR = 4, T32_ADD = 8,
       T32_ADC = 10, T32_SBC = 11, T32_SUB = 13, T32_RSB = 14 };
enum { T32_LSL, T32_LSR, T32_ASR, T32_ROR };
/* ARM condition codes, in the order of Cond. */
static const unsigned char t32_cond[] = {0, 1, 3, 2, 9, 8, 11, 10, 13, 12, 7, 3};
enum { T32_EQ = 0, T32_NE = 1, T32_HS = 2, T32_LO = 3, T32_MI = 4, T32_VS = 6, T32_VC = 7,
       T32_HI = 8, T32_LS = 9, T32_GE = 10, T32_LT = 11, T32_GT = 12, T32_LE = 13, T32_AL = 14 };

static void t16(BackendContext *c, unsigned h) { byte(c,h&0xff); byte(c,(h>>8)&0xff); }
static void t32w(BackendContext *c, unsigned h1, unsigned h2) {
  /* Fail closed if a future path bypasses the soft-mode adapters. This
     encoding space contains Thumb coprocessor/VFP instructions. */
  if (c->soft_float && (h1 & 0xEC00) == 0xEC00) { c->text.failed = true; return; }
  t16(c,h1); t16(c,h2);
}
/* Register-shifted data processing: d <- n op (m shifted). */
static void t32_dp(BackendContext *c, unsigned op, bool s, unsigned d, unsigned n, unsigned m, unsigned type, unsigned amount) {
  t32w(c, 0xEA00|op<<5|(unsigned)s<<4|n, (amount>>2)<<12|d<<8|(amount&3)<<6|type<<4|m);
}
#define T32_OP(op,d,n,m) t32_dp(c,op,false,d,n,m,0,0)
#define T32_OPS(op,d,n,m) t32_dp(c,op,true,d,n,m,0,0)
#define T32_CMP(n,m) t32_dp(c,T32_SUB,true,15,n,m,0,0)
static void t32_mv(BackendContext *c, unsigned d, unsigned m) {
  if (d != m) t16(c, 0x4600|(d&8)<<4|m<<3|(d&7));
}
/* Thumb-2 modified immediate (i:imm3:imm8), or -1. */
static int t32_modimm(uint32_t v) {
  if (v <= 0xff) return (int)v;
  uint32_t b = v & 0xff, b2 = (v >> 8) & 0xff;
  if (v == (b | b << 16)) return 0x100 | (int)b;
  if (v == (b2 << 8 | b2 << 24)) return 0x200 | (int)b2;
  if (v == b * 0x01010101u) return 0x300 | (int)b;
  for (unsigned rot = 8; rot < 32; ++rot) {
    uint32_t x = v << rot | v >> (32 - rot);
    if (x >= 0x80 && x <= 0xff) return (int)(rot << 7 | (x & 0x7f));
  }
  return -1;
}
static void t32_dpi(BackendContext *c, unsigned op, bool s, unsigned d, unsigned n, unsigned e) {
  t32w(c, 0xF000|(e>>11)<<10|op<<5|(unsigned)s<<4|n, ((e>>8)&7)<<12|d<<8|(e&0xff));
}
static void t32_movw(BackendContext *c, unsigned top, unsigned d, uint32_t v) {
  t32w(c, top|((v>>11)&1)<<10|((v>>12)&15), ((v>>8)&7)<<12|d<<8|(v&0xff));
}
static void t32_li(BackendContext *c, unsigned d, uint32_t value) {
  int e = t32_modimm(value);
  if (e >= 0) { t32_dpi(c,T32_ORR,false,d,15,(unsigned)e); return; }
  e = t32_modimm(~value);
  if (e >= 0) { t32_dpi(c,T32_ORN,false,d,15,(unsigned)e); return; }
  t32_movw(c,0xF240,d,value & 0xffff);
  if (value >> 16) t32_movw(c,0xF2C0,d,value >> 16);
}
/* d <- n + value, d and n core registers; d must differ from n when the value
   needs more than twelve bits. */
static void t32_add_imm(BackendContext *c, unsigned d, unsigned n, int64_t value) {
  if (value == 0) { t32_mv(c,d,n); return; }
  if (value > 0 && value <= 4095) { unsigned v = (unsigned)value; t32w(c,0xF200|((v>>11)&1)<<10|n,((v>>8)&7)<<12|d<<8|(v&0xff)); return; }
  if (value < 0 && value >= -4095) { unsigned v = (unsigned)-value; t32w(c,0xF2A0|((v>>11)&1)<<10|n,((v>>8)&7)<<12|d<<8|(v&0xff)); return; }
  unsigned t = d == n ? T32_ADDRESS : d;
  if (t == n) { c->text.failed = true; return; }
  t32_li(c,t,(uint32_t)value); T32_OP(T32_ADD,d,n,t);
}
/* Shift by an immediate: d <- m shifted. */
static void t32_shift_imm(BackendContext *c, unsigned type, unsigned d, unsigned m, unsigned amount) {
  if (!amount) { t32_mv(c,d,m); return; }
  t32_dp(c,T32_ORR,false,d,15,m,type,amount&31);
}
/* Shift by a register: d <- n shifted by the low byte of m. */
static void t32_shift_reg(BackendContext *c, unsigned type, unsigned d, unsigned n, unsigned m) {
  t32w(c,0xFA00|type<<5|n,0xF000|d<<8|m);
}
static void t32_it(BackendContext *c, unsigned cond) { t16(c,0xBF08|cond<<4); }
static void t32_mrs(BackendContext *c, unsigned d) { t32w(c,0xF3EF,0x8000|d<<8); }
static void t32_msr(BackendContext *c, unsigned n) { t32w(c,0xF380|n,0x8800); }
static void t32_mul(BackendContext *c, unsigned d, unsigned n, unsigned m) { t32w(c,0xFB00|n,0xF000|d<<8|m); }
static void t32_mla(BackendContext *c, unsigned d, unsigned n, unsigned m, unsigned a) { t32w(c,0xFB00|n,a<<12|d<<8|m); }
static void t32_mls(BackendContext *c, unsigned d, unsigned n, unsigned m, unsigned a) { t32w(c,0xFB00|n,a<<12|d<<8|0x10|m); }
static void t32_umull(BackendContext *c, unsigned lo, unsigned hi, unsigned n, unsigned m) { t32w(c,0xFBA0|n,lo<<12|hi<<8|m); }
static void t32_udiv(BackendContext *c, unsigned d, unsigned n, unsigned m) { t32w(c,0xFBB0|n,0xF0F0|d<<8|m); }
static void t32_clz(BackendContext *c, unsigned d, unsigned m) { t32w(c,0xFAB0|m,0xF080|d<<8|m); }
/* Soft mode replaces s16-s31 with a fixed 64-byte bank immediately
   below the unbiased frame base. Locals move down by 64; saved core
   registers, incoming stack arguments and T32_BIAS do not move. */
static void t32_soft_slot(BackendContext *c, bool load, unsigned r, unsigned s);
/* VFP transfers. */
static void t32_to_s(BackendContext *c, unsigned s, unsigned r) { if (c->soft_float) { t32_soft_slot(c,false,r,s); return; } t32w(c,0xEE00|s>>1,r<<12|0x0A10|(s&1)<<7); }
static void t32_from_s(BackendContext *c, unsigned r, unsigned s) { if (c->soft_float) { t32_soft_slot(c,true,r,s); return; } t32w(c,0xEE10|s>>1,r<<12|0x0A10|(s&1)<<7); }
static void t32_to_s2(BackendContext *c, unsigned s, unsigned r, unsigned r2) { if (c->soft_float) { t32_soft_slot(c,false,r,s); t32_soft_slot(c,false,r2,s+1); return; } t32w(c,0xEC40|r2,r<<12|0x0A10|(s&1)<<5|s>>1); }
static void t32_from_s2(BackendContext *c, unsigned r, unsigned r2, unsigned s) { if (c->soft_float) { t32_soft_slot(c,true,r,s); t32_soft_slot(c,true,r2,s+1); return; } t32w(c,0xEC50|r2,r<<12|0x0A10|(s&1)<<5|s>>1); }
static void t32_to_d(BackendContext *c, unsigned d, unsigned lo, unsigned hi) { if (c->soft_float) { c->text.failed = true; return; } t32w(c,0xEC40|hi,lo<<12|0x0B10|d); }
static void t32_from_d(BackendContext *c, unsigned lo, unsigned hi, unsigned d) { if (c->soft_float) { c->text.failed = true; return; } t32w(c,0xEC50|hi,lo<<12|0x0B10|d); }

/* Loads and stores with any offset; lr forms addresses out of range. */
enum { T32_STRB, T32_STRH, T32_STR, T32_LDRB, T32_LDRH, T32_LDR, T32_LDRSB, T32_LDRSH };
static const unsigned short t32_memory_op[] = {0xF880, 0xF8A0, 0xF8C0, 0xF890, 0xF8B0, 0xF8D0, 0xF990, 0xF9B0};
static void t32_mem(BackendContext *c, unsigned kind, unsigned t, unsigned n, int64_t offset) {
  if (offset >= 0 && offset <= 4095) { t32w(c,t32_memory_op[kind]|n,t<<12|(unsigned)offset); return; }
  if (offset < 0 && offset >= -255) { t32w(c,(t32_memory_op[kind]-0x80)|n,t<<12|0xC00|(unsigned)-offset); return; }
  t32_li(c,T32_ADDRESS,(uint32_t)offset); T32_OP(T32_ADD,T32_ADDRESS,n,T32_ADDRESS);
  t32w(c,t32_memory_op[kind]|T32_ADDRESS,t<<12);
}
static void t32_soft_slot(BackendContext *c, bool load, unsigned r, unsigned s) {
  if (s < 16 || s > 31) { c->text.failed = true; return; }
  t32_mem(c,load?T32_LDR:T32_STR,r,T32_FP,T32_BIAS-T32_SAVED+4*(s-16));
}
/* VFP load/store of s (single) or d (double) register v at [n + offset]. */
static void t32_vmem(BackendContext *c, bool load, bool dbl, unsigned v, unsigned n, int64_t offset) {
  if (c->soft_float) { c->text.failed = true; return; }
  if (offset < 0 || offset > 1020 || offset & 3) { t32_add_imm(c,T32_ADDRESS,n,offset); n = T32_ADDRESS; offset = 0; }
  unsigned h1 = 0xED80|(load?0x10:0)|n, h2 = (unsigned)offset/4;
  if (dbl) h2 |= v<<12|0x0B00; else { h1 |= (v&1)<<6; h2 |= (v>>1)<<12|0x0A00; }
  t32w(c,h1,h2);
}
/* Frame slots: r11 is the frame pointer minus T32_BIAS. */
static void t32_frame(BackendContext *c, unsigned kind, unsigned t, uint32_t offset) {
  t32_mem(c,kind,t,T32_FP,(int64_t)(int32_t)offset+T32_BIAS-(c->soft_float && (int32_t)offset < 0 ? T32_SAVED : 0));
}
static void t32_frame_address(BackendContext *c, unsigned d, uint32_t offset) {
  int64_t value = (int64_t)(int32_t)offset + T32_BIAS - (c->soft_float && (int32_t)offset < 0 ? T32_SAVED : 0);
  if (value >= -4095 && value <= 4095) { t32_add_imm(c,d,T32_FP,value); return; }
  t32_li(c,d,(uint32_t)value); T32_OP(T32_ADD,d,T32_FP,d);
}
/* High words: core registers for A and C, VFP registers otherwise. */
static bool t32_core_high(Reg r) { return r == R_A || r == R_C; }
static unsigned t32_high(BackendContext *c, Reg r, unsigned scratch) {
  if (t32_core_high(r)) return t32_hi[r];
  t32_from_s(c,scratch,t32_hi[r]); return scratch;
}
static unsigned t32_high_target(Reg r, unsigned scratch) { return t32_core_high(r) ? t32_hi[r] : scratch; }
static void t32_set_high(BackendContext *c, Reg r, unsigned from) {
  if (t32_core_high(r)) t32_mv(c,t32_hi[r],from); else t32_to_s(c,t32_hi[r],from);
}
static void t32_high_imm(BackendContext *c, Reg r, uint32_t value) {
  if (t32_core_high(r)) { t32_li(c,t32_hi[r],value); return; }
  t32_li(c,T32_T2,value); t32_to_s(c,t32_hi[r],T32_T2);
}

/* Branches. B<c>.W reaches 1 MiB and B.W 16 MiB from the following instruction. */
static void t32_branch_at(BackendContext *c, size_t at, size_t destination, unsigned cond) {
  int64_t offset = (int64_t)destination - (int64_t)(at + 4);
  if (at + 4 > c->text.n) { c->text.failed = true; return; }
  uint32_t u = (uint32_t)offset, s = offset < 0, h1, h2;
  if (cond == T32_AL) {
    if (offset < -(1 << 24) || offset >= (1 << 24)) { c->text.failed = true; return; }
    unsigned i1 = (u >> 23) & 1, i2 = (u >> 22) & 1, j1 = (~i1 ^ s) & 1, j2 = (~i2 ^ s) & 1;
    h1 = 0xF000|s<<10|((u>>12)&0x3ff); h2 = 0x9000|j1<<13|j2<<11|((u>>1)&0x7ff);
  } else {
    if (offset < -(1 << 20) || offset >= (1 << 20)) { c->text.failed = true; return; }
    h1 = 0xF000|s<<10|cond<<6|((u>>12)&63); h2 = 0x8000|((u>>18)&1)<<13|((u>>19)&1)<<11|((u>>1)&0x7ff);
  }
  patch_word(c, at, h1 | h2 << 16);
}
static size_t t32_skip(BackendContext *c, unsigned cond) {
  size_t at = c->text.n; t32w(c,0xF000|cond<<6,0x8000); return at;
}
static void t32_land(BackendContext *c, size_t at) {
  uint32_t insn; memcpy(&insn, c->text.data + at, 4);
  t32_branch_at(c,at,c->text.n,(insn >> 28) & 1 ? T32_AL : (insn >> 6) & 15); /* B.W has bit 12 of its second half set */
}
static size_t t32_jump(BackendContext *c) { size_t at = c->text.n; t32w(c,0xF000,0x9000); return at; }
static void t32_back(BackendContext *c, size_t destination, unsigned cond) {
  size_t at = cond == T32_AL ? t32_jump(c) : t32_skip(c,cond); t32_branch_at(c,at,destination,cond);
}

/* Comparisons store their operands; the branch decides. */
static void t32_compare_regs(BackendContext *c, unsigned alo, unsigned ahi, unsigned blo, unsigned bhi) {
  t32_to_s2(c,T32_LOW_A,alo,blo); t32_to_s2(c,T32_HIGH_A,ahi,bhi);
}
static void t32_save_flags(BackendContext *c) { t32_mrs(c,T32_T1); t32_to_s(c,T32_FLAGS,T32_T1); }
/* Set the flags for a condition; returns the ARM condition that holds when it does. */
static unsigned t32_condition(BackendContext *c, int cond) {
  unsigned arm = t32_cond[cond];
  switch (cond) {
  case CC_E: case CC_NE:
    t32_from_s2(c,T32_T1,T32_T2,T32_HIGH_A); T32_CMP(T32_T1,T32_T2);
    t32_from_s2(c,T32_T1,T32_T2,T32_LOW_A); t32_it(c,T32_EQ); T32_CMP(T32_T1,T32_T2);
    return arm;
  case CC_B: case CC_AE: case CC_L: case CC_GE:
    /* a - b over 64 bits: carry clear when a < b unsigned, N != V when signed. */
    t32_from_s2(c,T32_T1,T32_T2,T32_LOW_A); T32_CMP(T32_T1,T32_T2);
    t32_from_s2(c,T32_T1,T32_T2,T32_HIGH_A); T32_OPS(T32_SBC,T32_T1,T32_T1,T32_T2);
    return arm;
  case CC_A: case CC_BE: case CC_G: case CC_LE:
    /* b - a: the same test with the operands swapped. */
    t32_from_s2(c,T32_T1,T32_T2,T32_LOW_A); T32_CMP(T32_T2,T32_T1);
    t32_from_s2(c,T32_T1,T32_T2,T32_HIGH_A); T32_OPS(T32_SBC,T32_T2,T32_T2,T32_T1);
    return cond == CC_A ? T32_LO : cond == CC_BE ? T32_HS : cond == CC_G ? T32_LT : T32_GE;
  case CC_NO: case CC_NO_CARRY:
    t32_from_s(c,T32_T1,T32_FLAGS); t32_msr(c,T32_T1);
    return arm;
  default: c->text.failed = true; return T32_AL;
  }
}
/* Conditional jumps skip an unconditional B.W when the condition fails, so
   every branch reaches 16 MiB and patches the same way. */
static size_t t32_branch(BackendContext *c, int cond) {
  if (cond >= 0) { unsigned arm = t32_condition(c,cond); t16(c,0xD001|(arm^1)<<8); }
  return t32_jump(c);
}
static void t32_patch(BackendContext *c, size_t at, size_t destination) { t32_branch_at(c,at,destination,T32_AL); }

static void t32_load(BackendContext *c, Reg r, uint32_t offset) {
  t32_frame(c,T32_LDR,t32_lo[r],offset);
  unsigned h = t32_high_target(r,T32_T1); t32_frame(c,T32_LDR,h,offset+4); t32_set_high(c,r,h);
}
static void t32_store(BackendContext *c, Reg r, uint32_t offset) {
  t32_frame(c,T32_STR,t32_lo[r],offset); t32_frame(c,T32_STR,t32_high(c,r,T32_T1),offset+4);
}
static void t32_lea(BackendContext *c, Reg r, uint32_t offset) {
  t32_frame_address(c,t32_lo[r],offset); t32_high_imm(c,r,0);
}
static void t32_immediate(BackendContext *c, Reg r, uint64_t n) {
  t32_li(c,t32_lo[r],(uint32_t)n); t32_high_imm(c,r,(uint32_t)(n >> 32));
}
static void t32_move(BackendContext *c, Reg to, Reg from) {
  t32_mv(c,t32_lo[to],t32_lo[from]);
  if (t32_core_high(to) || t32_core_high(from)) t32_set_high(c,to,t32_high(c,from,T32_T1));
  else if (to != from) { t32_from_s(c,T32_T1,t32_hi[from]); t32_to_s(c,t32_hi[to],T32_T1); }
}
/* Pushes take sixteen bytes, as on RV64 and AArch64. */
static void t32_push(BackendContext *c, Reg r) {
  bare_stack_check(c,16);
  ++c->stack_slots; unsigned h = t32_high(c,r,T32_T1);
  t32w(c,0xE96D,t32_lo[r]<<12|h<<8|4); /* strd lo, hi, [sp, #-16]! */
}
static void t32_pop(BackendContext *c, Reg r) {
  --c->stack_slots; unsigned h = t32_high_target(r,T32_T1);
  t32w(c,0xE8FD,t32_lo[r]<<12|h<<8|4); /* ldrd lo, hi, [sp], #16 */
  t32_set_high(c,r,h);
}
static void t32_peek(BackendContext *c, Reg r, unsigned slot) {
  t32_mem(c,T32_LDR,t32_lo[r],T32_SP,(int64_t)slot*16);
  unsigned h = t32_high_target(r,T32_T1); t32_mem(c,T32_LDR,h,T32_SP,(int64_t)slot*16+4); t32_set_high(c,r,h);
}
static void t32_drop(BackendContext *c, unsigned count) { c->stack_slots -= count; t32_add_imm(c,T32_SP,T32_SP,(int64_t)count*16); }
static void t32_test(BackendContext *c, Reg r) {
  t32_li(c,T32_T2,0); t32_compare_regs(c,t32_lo[r],t32_high(c,r,T32_T1),T32_T2,T32_T2);
}
static void t32_compare(BackendContext *c, Reg left, Reg right) {
  t32_compare_regs(c,t32_lo[left],t32_high(c,left,T32_T1),t32_lo[right],t32_high(c,right,T32_T2));
}
static void t32_compare_frame(BackendContext *c, uint32_t offset) {
  t32_frame(c,T32_LDR,T32_T1,offset); t32_to_s2(c,T32_LOW_A,0,T32_T1);
  t32_frame(c,T32_LDR,T32_T1,offset+4); t32_to_s2(c,T32_HIGH_A,4,T32_T1);
}
static void t32_set(BackendContext *c, Cond cond) {
  unsigned arm = t32_condition(c,cond);
  t32_li(c,0,0); t32_it(c,arm); t32_li(c,0,1); t32_li(c,4,0);
}
static void t32_trap(BackendContext *c) { t16(c,0xDE00); }
static void t32_call(BackendContext *c, unsigned symbol) {
  relocate(c,symbol,10 /* R_ARM_THM_CALL */,0); t32w(c,0xF000,0xD000);
}
static void t32_symbol(BackendContext *c, unsigned d, unsigned symbol, int64_t addend) {
  relocate(c,symbol,47 /* R_ARM_THM_MOVW_ABS_NC */,addend); t32_movw(c,0xF240,d,0);
  relocate(c,symbol,48 /* R_ARM_THM_MOVT_ABS */,addend); t32_movw(c,0xF2C0,d,0);
}
static void t32_local_address(BackendContext *c, Reg r, unsigned symbol, size_t offset) {
  t32_symbol(c,t32_lo[r],symbol,(int64_t)offset); t32_high_imm(c,r,0);
}
static void t32_symbol_address(BackendContext *c, Reg r, unsigned symbol) {
  t32_symbol(c,t32_lo[r],symbol,0); t32_high_imm(c,r,0);
}
/* (pointer, length) arguments: runtime_call moves the length to r2:r3, since
   it is a u64 in the runtime's signature. */
static void t32_string_arguments(BackendContext *c, size_t offset, size_t length) {
  t32_symbol(c,0,1,(int64_t)offset); t32_li(c,1,(uint32_t)length); t32_high_imm(c,R_D,0);
}
static void t32_reset_stack(BackendContext *c) {
  t32_li(c,T32_T1,(uint32_t)(T32_BIAS-(int64_t)c->frame_bytes-T32_SAVED));
  T32_OP(T32_ADD,T32_T1,T32_FP,T32_T1); t32_mv(c,T32_SP,T32_T1);
}
static void t32_extend(BackendContext *c, unsigned bits, bool sign) {
  if (bits >= 64) return;
  if (bits == 1) { t32_dpi(c,T32_AND,false,0,0,1); t32_li(c,4,0); return; }
  if (bits < 32) t32w(c,(sign?0xF340:0xF3C0),bits-1); /* sbfx/ubfx r0, r0, #0, #bits */
  if (sign) t32_shift_imm(c,T32_ASR,4,0,31); else t32_li(c,4,0);
}
static void t32_load_value(BackendContext *c, unsigned bits, bool sign) {
  if (bits >= 64) { t32_mem(c,T32_LDR,4,0,4); t32_mem(c,T32_LDR,0,0,0); return; }
  t32_mem(c,bits<=8?(sign?T32_LDRSB:T32_LDRB):bits==16?(sign?T32_LDRSH:T32_LDRH):T32_LDR,0,0,0);
  if (sign) t32_shift_imm(c,T32_ASR,4,0,31); else t32_li(c,4,0);
}
static void t32_store_value(BackendContext *c, unsigned bits) {
  t32_mem(c,bits<=8?T32_STRB:bits==16?T32_STRH:T32_STR,0,9,0);
  if (bits >= 64) t32_mem(c,T32_STR,4,9,4);
}
/* R10 <- size bytes at [R11 + offset], zero-extended, one byte at a time. */
static void t32_load_chunk(BackendContext *c, unsigned offset, unsigned size) {
  t32_li(c,8,0); t32_li(c,T32_T1,0);
  for (unsigned i = 0; i < size; ++i) {
    unsigned into = i < 4 ? 8 : T32_T1;
    t32_mem(c,T32_LDRB,T32_T2,9,offset+i);
    t32_dp(c,T32_ORR,false,into,into,T32_T2,T32_LSL,8*(i%4));
  }
  t32_to_s(c,t32_hi[R_10],T32_T1);
}
/* [DI + offset] <- the low bytes of R10. */
static void t32_store_chunk(BackendContext *c, unsigned offset, unsigned bytes) {
  if (bytes > 4) t32_from_s(c,T32_T1,t32_hi[R_10]);
  for (unsigned j = 0; j < bytes; ++j) {
    unsigned from = j < 4 ? 8 : T32_T1;
    t32_shift_imm(c,T32_LSR,T32_T2,from,8*(j%4));
    t32_mem(c,T32_STRB,T32_T2,6,offset+j);
  }
}
static void t32_test_mask(BackendContext *c, uint32_t mask) {
  t32_li(c,T32_T1,mask); T32_OP(T32_AND,T32_T1,0,T32_T1); t32_li(c,T32_T2,0);
  t32_compare_regs(c,T32_T1,T32_T2,T32_T2,T32_T2);
}
static void t32_compare_small(BackendContext *c, Reg r, int value) {
  unsigned h = t32_high(c,r,T32_T1);
  t32_li(c,T32_T2,(uint32_t)value); t32_to_s2(c,T32_LOW_A,t32_lo[r],T32_T2);
  t32_li(c,T32_T2,value < 0 ? UINT32_MAX : 0); t32_to_s2(c,T32_HIGH_A,h,T32_T2);
}
static bool t32_compare_immediate(BackendContext *c, uint64_t value) {
  t32_li(c,T32_T1,(uint32_t)value); t32_li(c,T32_T2,(uint32_t)(value >> 32));
  t32_compare_regs(c,0,4,T32_T1,T32_T2);
  return true;
}
enum { T32_UDIV, T32_UREM, T32_SDIV, T32_SREM };
static void t32_helper(BackendContext *c, unsigned runtime, uint32_t mode) { t32_li(c,T32_T1,mode); runtime_call(c,runtime); }
static void t32_divide(BackendContext *c, bool sign, bool remainder) {
  if (!sign) {
    /* Both high words zero: one 32-bit division. */
    T32_OPS(T32_ORR,T32_T1,4,5); size_t slow = t32_skip(c,T32_NE);
    if (remainder) { t32_udiv(c,T32_T1,0,2); t32_mls(c,0,T32_T1,2,0); } else t32_udiv(c,0,0,2);
    size_t done = t32_jump(c);
    t32_land(c,slow);
    t32_helper(c,RUNTIME_RV32_DIVIDE,remainder?T32_UREM:T32_UDIV);
    t32_land(c,done);
    return;
  }
  t32_helper(c,RUNTIME_RV32_DIVIDE,remainder?T32_SREM:T32_SDIV);
}
/* reg <- reg shifted by C (0-63). Register shifts of 32 or more give zero,
   so both halves combine without branches. */
static void t32_shift(BackendContext *c, Reg r, int kind) {
  unsigned lo = t32_lo[r], h = t32_high(c,r,T32_T2), n = 2;
  if (kind == SHIFT_LEFT) {
    t32_shift_reg(c,T32_LSL,h,h,n);
    t32_add_imm(c,T32_T1,n,-32); t32_shift_reg(c,T32_LSL,T32_T1,lo,T32_T1); T32_OP(T32_ORR,h,h,T32_T1);
    t32_dpi(c,T32_RSB,false,T32_T1,n,32); t32_shift_reg(c,T32_LSR,T32_T1,lo,T32_T1); T32_OP(T32_ORR,h,h,T32_T1);
    t32_shift_reg(c,T32_LSL,lo,lo,n);
  } else {
    t32_shift_reg(c,T32_LSR,lo,lo,n);
    t32_dpi(c,T32_RSB,false,T32_T1,n,32); t32_shift_reg(c,T32_LSL,T32_T1,h,T32_T1); T32_OP(T32_ORR,lo,lo,T32_T1);
    if (kind == SHIFT_RIGHT) {
      t32_add_imm(c,T32_T1,n,-32); t32_shift_reg(c,T32_LSR,T32_T1,h,T32_T1); T32_OP(T32_ORR,lo,lo,T32_T1);
      t32_shift_reg(c,T32_LSR,h,h,n);
    } else {
      t32_dpi(c,T32_SUB,true,T32_T1,n,32); t32_it(c,T32_GE); t32_shift_reg(c,T32_ASR,lo,h,T32_T1);
      t32_shift_reg(c,T32_ASR,h,h,n);
    }
  }
  t32_set_high(c,r,h);
}
static void t32_alu(BackendContext *c, int op, Reg to, Reg from) {
  unsigned l1 = t32_lo[to], l2 = t32_lo[from], h1 = t32_high(c,to,T32_T1), h2 = t32_high(c,from,T32_T2);
  if (op == ALU_AND || op == ALU_OR || op == ALU_XOR) {
    unsigned o = op == ALU_AND ? T32_AND : op == ALU_OR ? T32_ORR : T32_EOR;
    T32_OP(o,l1,l1,l2); T32_OP(o,h1,h1,h2);
  } else if (op == ALU_ADD) {
    T32_OPS(T32_ADD,l1,l1,l2); T32_OPS(T32_ADC,h1,h1,h2);
    t32_mrs(c,T32_T2); t32_to_s(c,T32_FLAGS,T32_T2);
  } else {
    t32_compare_regs(c,l1,h1,l2,h2);
    T32_OPS(T32_SUB,l1,l1,l2); T32_OPS(T32_SBC,h1,h1,h2);
    t32_mrs(c,T32_T2); t32_to_s(c,T32_FLAGS,T32_T2);
  }
  t32_set_high(c,to,h1);
}
static void t32_add_immediate(BackendContext *c, uint32_t n) {
  if (!n) return;
  t32_li(c,T32_T1,n); T32_OPS(T32_ADD,0,0,T32_T1); t32_dpi(c,T32_ADC,false,4,4,0);
}
static void t32_scale(BackendContext *c, Reg r, uint32_t n) {
  unsigned lo = t32_lo[r], h = t32_high(c,r,T32_T2);
  t32_li(c,T32_ADDRESS,n); t32_mul(c,h,h,T32_ADDRESS);
  t32_umull(c,lo,T32_T1,lo,T32_ADDRESS); T32_OP(T32_ADD,h,h,T32_T1);
  t32_set_high(c,r,h);
}
static void t32_small_immediate(BackendContext *c, Reg r, uint32_t n) { t32_li(c,t32_lo[r],n); t32_high_imm(c,r,0); }
/* Argument register cls <- the stack slot at byte offset. GP classes with bit
   5 set are register pairs; 8-15 are d registers and 16-31 s registers. */
static void t32_argument_load(BackendContext *c, int cls, uint32_t offset) {
  if (cls & 32) { unsigned k = (unsigned)cls & 31; t32_mem(c,T32_LDR,k,T32_SP,offset); t32_mem(c,T32_LDR,k+1,T32_SP,offset+4); return; }
  if (cls >= 16) { t32_vmem(c,true,false,(unsigned)cls-16,T32_SP,offset); return; }
  if (cls >= 8) { t32_vmem(c,true,true,(unsigned)cls-8,T32_SP,offset); return; }
  t32_mem(c,T32_LDR,(unsigned)cls,T32_SP,offset);
}
static void t32_stack_store(BackendContext *c, uint32_t from, uint32_t to, uint32_t bytes) {
  t32_mem(c,T32_LDR,T32_T1,T32_SP,from); t32_mem(c,T32_STR,T32_T1,T32_SP,to);
  if (bytes == 8) { t32_mem(c,T32_LDR,T32_T1,T32_SP,from+4); t32_mem(c,T32_STR,T32_T1,T32_SP,to+4); }
}
static void t32_call_stack(BackendContext *c, uint32_t offset) {
  t32_mem(c,T32_LDR,T32_T1,T32_SP,offset); t16(c,0x4780|T32_T1<<3); /* blx */
}
static void t32_a_to_float(BackendContext *c) { if (c->soft_float) { t32_mv(c,1,4); return; } t32_to_d(c,0,0,4); }
/* Descriptors in memory: slices hold a 32-bit pointer and length, any a
   64-bit type identifier and a 32-bit pointer at offset 8. */
static void t32_load_descriptor(BackendContext *c, bool any) {
  if (any) { t32_mem(c,T32_LDR,1,0,8); t32_mem(c,T32_LDR,4,0,4); t32_mem(c,T32_LDR,0,0,0); }
  else { t32_mem(c,T32_LDR,1,0,4); t32_mem(c,T32_LDR,0,0,0); t32_li(c,4,0); }
  t32_high_imm(c,R_D,0);
}
static void t32_store_descriptor(BackendContext *c, bool any) {
  t32_mem(c,T32_STR,0,9,0);
  if (any) { t32_mem(c,T32_STR,4,9,4); t32_mem(c,T32_STR,1,9,8); } else t32_mem(c,T32_STR,1,9,4);
}
static void t32_match_begin(BackendContext *c) { t32_li(c,7,0); t32_high_imm(c,R_8,0); }
static void t32_match_tag(BackendContext *c, uint64_t tag) {
  t32_li(c,T32_T1,(uint32_t)tag); T32_OP(T32_EOR,T32_T1,0,T32_T1);
  t32_li(c,T32_T2,(uint32_t)(tag >> 32)); T32_OP(T32_EOR,T32_T2,4,T32_T2);
  T32_OP(T32_ORR,T32_T1,T32_T1,T32_T2); t32_clz(c,T32_T1,T32_T1);
  t32_shift_imm(c,T32_LSR,T32_T1,T32_T1,5); T32_OP(T32_ORR,7,7,T32_T1);
}
static void t32_match_test(BackendContext *c) { t32_li(c,T32_T2,0); t32_compare_regs(c,7,T32_T2,T32_T2,T32_T2); }
/* Ordinary integer AAPCS helpers clobber r0-r3/r12/lr. Preserve C,
   D and SI low words; other logical words live in callee-saved registers
   or this frame's private bank. Keep eight-byte stack alignment. */
static void t32_soft_helper(BackendContext *c, unsigned runtime, bool input32,
                            bool binary, bool result32) {
  bare_stack_check(c,16);
  t32_add_imm(c,T32_SP,T32_SP,-16);
  for (unsigned i = 1; i <= 3; ++i) t32_mem(c,T32_STR,i,T32_SP,4*(i-1));
  if (!input32) t32_mv(c,1,4);
  if (binary) {
    if (input32) t32_mv(c,1,2);
    else t32_mv(c,3,5);
  }
  runtime_call(c,runtime);
  if (result32) t32_li(c,4,0); else t32_mv(c,4,1);
  for (unsigned i = 1; i <= 3; ++i) t32_mem(c,T32_LDR,i,T32_SP,4*(i-1));
  t32_add_imm(c,T32_SP,T32_SP,16);
}
enum { T32_FLOAT32 = 1, T32_UNSIGNED64 = 2 };
static void t32_int_to_float(BackendContext *c, bool f32, bool unsigned64) {
  if (c->soft_float) {
    unsigned helper = f32 ? (unsigned64 ? RUNTIME_SOFT_U64_TO_F32 : RUNTIME_SOFT_I64_TO_F32)
                          : (unsigned64 ? RUNTIME_SOFT_U64_TO_F64 : RUNTIME_SOFT_I64_TO_F64);
    t32_soft_helper(c,helper,false,false,f32); return;
  }
  t32_helper(c,RUNTIME_RV32_INT_TO_FLOAT,(f32?T32_FLOAT32:0)|(unsigned64?T32_UNSIGNED64:0));
}
static void t32_float_to_int(BackendContext *c, bool f32, bool unsigned64) {
  if (c->soft_float) {
    unsigned helper = f32 ? (unsigned64 ? RUNTIME_SOFT_F32_TO_U64 : RUNTIME_SOFT_F32_TO_I64)
                          : (unsigned64 ? RUNTIME_SOFT_F64_TO_U64 : RUNTIME_SOFT_F64_TO_I64);
    t32_soft_helper(c,helper,f32,false,false); return;
  }
  t32_helper(c,RUNTIME_RV32_FLOAT_TO_INT,(f32?T32_FLOAT32:0)|(unsigned64?T32_UNSIGNED64:0));
}
static void t32_float_convert(BackendContext *c, bool from32) {
  if (c->soft_float) {
    t32_soft_helper(c,from32?RUNTIME_SOFT_F32_TO_F64:RUNTIME_SOFT_F64_TO_F32,from32,false,!from32); return;
  }
  if (from32) { t32_to_s(c,0,0); t32w(c,0xEEB7,0x0AC0); t32_from_d(c,0,4,0); return; } /* vcvt.f64.f32 d0, s0 */
  t32_to_d(c,0,0,4); t32w(c,0xEEB7,0x0BC0); t32_from_s(c,0,0); t32_li(c,4,0); /* vcvt.f32.f64 s0, d0 */
}
static void t32_unary(BackendContext *c, int op) {
  if (op == UNARY_NOT) { T32_OP(T32_ORN,0,15,0); T32_OP(T32_ORN,4,15,4); return; }
  if (op == UNARY_BOOL_NOT) { t32_dpi(c,T32_EOR,false,0,0,1); return; }
  t32_li(c,T32_T1,0); t32_compare_regs(c,T32_T1,T32_T1,0,4);
  t32_dpi(c,T32_RSB,true,0,0,0); T32_OPS(T32_SBC,4,T32_T1,4);
  t32_save_flags(c);
}
static void t32_float_operands(BackendContext *c, bool f32) {
  if (c->soft_float) return; /* Raw bits already in A/C. */
  if (f32) { t32_to_s(c,0,0); t32_to_s(c,1,2); return; }
  t32_to_d(c,0,0,4); t32_to_d(c,1,2,5);
}
static void t32_float_result(BackendContext *c, bool f32) {
  if (c->soft_float) return; /* Raw bits already in A/C. */
  if (f32) { t32_from_s(c,0,0); t32_li(c,4,0); return; }
  t32_from_d(c,0,4,0);
}
/* op: 0 ==, 1 !=, 2 <, 3 <=, 4 >, 5 >=; unordered operands compare false
   except for !=. */
static void t32_float_compare(BackendContext *c, bool f32, unsigned op) {
  if (c->soft_float) {
    static const unsigned helpers[2][6] = {
      {RUNTIME_SOFT_F64_EQ,RUNTIME_SOFT_F64_NE,RUNTIME_SOFT_F64_LT,RUNTIME_SOFT_F64_LE,RUNTIME_SOFT_F64_GT,RUNTIME_SOFT_F64_GE},
      {RUNTIME_SOFT_F32_EQ,RUNTIME_SOFT_F32_NE,RUNTIME_SOFT_F32_LT,RUNTIME_SOFT_F32_LE,RUNTIME_SOFT_F32_GT,RUNTIME_SOFT_F32_GE}
    };
    if (op >= 6) { c->text.failed = true; return; }
    t32_soft_helper(c,helpers[f32][op],f32,true,true); return;
  }
  static const unsigned char holds[] = {T32_EQ, T32_NE, T32_MI, T32_LS, T32_GT, T32_GE};
  if (f32) t32w(c,0xEEB4,0x0A60); else t32w(c,0xEEB4,0x0B41); /* vcmp s0, s1 / d0, d1 */
  t32w(c,0xEEF1,0xFA10); /* vmrs APSR_nzcv, fpscr */
  t32_li(c,0,0); t32_it(c,holds[op]); t32_li(c,0,1); t32_li(c,4,0);
}
static inline void t32_float_remainder(BackendContext *c, bool f32) {
  if (!c->soft_float) { c->text.failed = true; return; }
  t32_soft_helper(c,f32?RUNTIME_SOFT_F32_REM:RUNTIME_SOFT_F64_REM,f32,true,f32);
}
static void t32_float_arithmetic(BackendContext *c, bool f32, int op) {
  if (c->soft_float) {
    static const unsigned helpers[2][4] = {
      {RUNTIME_SOFT_F64_ADD,RUNTIME_SOFT_F64_SUB,RUNTIME_SOFT_F64_MUL,RUNTIME_SOFT_F64_DIV},
      {RUNTIME_SOFT_F32_ADD,RUNTIME_SOFT_F32_SUB,RUNTIME_SOFT_F32_MUL,RUNTIME_SOFT_F32_DIV}
    };
    if ((unsigned)op >= 4) { c->text.failed = true; return; }
    t32_soft_helper(c,helpers[f32][op],f32,true,f32); return;
  }
  static const unsigned short top[] = {0xEE30, 0xEE30, 0xEE20, 0xEE80};
  unsigned bottom = (op == FLOAT_SUB ? 0x40 : 0) | (f32 ? 0x0A20 : 0x0B01);
  t32w(c,top[op],bottom); t32_float_result(c,f32);
}
static void t32_multiply(BackendContext *c, bool checked, bool sign) {
  if (checked) {
    /* The helper leaves overflow (0 or 1) in r10; success compares equal to zero. */
    t32_helper(c,RUNTIME_RV32_MULTIPLY,sign);
    t32_li(c,T32_T2,0); t32_compare_regs(c,T32_T1,T32_T2,T32_T2,T32_T2);
    return;
  }
  t32_mul(c,T32_T1,0,5); t32_mla(c,T32_T1,4,2,T32_T1);
  t32_umull(c,0,T32_T2,0,2); T32_OP(T32_ADD,4,T32_T2,T32_T1);
}
static void t32_trace_pop(BackendContext *c, bool descriptor_result) {
  t32_push(c,R_A);
  if (descriptor_result) t32_push(c,R_D);
  runtime_call(c,2);
  if (descriptor_result) t32_pop(c,R_D);
  t32_pop(c,R_A);
}
/* Hard frame: saved cores, locals, d8-d15. Soft frame: saved cores,
   private 64-byte bank, locals. Both have identical total size and FP/CFA. */
static void t32_enter(BackendContext *c) {
  t32w(c,0xE92D,0x4FF8); /* push {r3-r11, lr} */
  t32_add_imm(c,T32_FP,T32_SP,-T32_BIAS);
  int64_t frame = (int64_t)c->frame_bytes + (c->soft_float ? T32_SAVED : 0);
  if (frame <= 4095) t32_add_imm(c,T32_SP,T32_SP,-frame);
  else { t32_li(c,T32_T1,(uint32_t)frame); T32_OP(T32_SUB,T32_T1,T32_SP,T32_T1); t32_mv(c,T32_SP,T32_T1); }
  if (!c->soft_float) t32w(c,0xED2D,0x8B10); /* vpush {d8-d15} */
  /* Incoming banks: core registers at i*8, VFP registers at 64 (d i at 64+i*8). */
  t32_add_imm(c,T32_SP,T32_SP,-128);
  for (unsigned i = 0; i < 4; ++i) t32_mem(c,T32_STR,i,T32_SP,i*8);
  if (!c->soft_float) for (unsigned i = 0; i < 8; ++i) t32_vmem(c,false,true,i,T32_SP,64+i*8);
}
static void t32_release_bank(BackendContext *c) { t32_add_imm(c,T32_SP,T32_SP,128); }
static void t32_return(BackendContext *c) {
  t32_reset_stack(c);
  if (!c->soft_float) t32w(c,0xECBD,0x8B10); /* vpop {d8-d15} */
  t32_add_imm(c,T32_T1,T32_FP,T32_BIAS); t32_mv(c,T32_SP,T32_T1);
  t32w(c,0xE8BD,0x8FF8); /* pop {r3-r11, pc} */
}
static void t32_zero_fill(BackendContext *c, uint32_t size) {
  t32_li(c,T32_T1,size); t32_mv(c,T32_ADDRESS,0); t32_li(c,T32_T2,0);
  size_t loop = c->text.n; T32_CMP(T32_T1,T32_T2); size_t done = t32_skip(c,T32_EQ);
  /* Byte prefixes align arbitrary pointers; short tails never overrun. */
  t32_dpi(c,T32_SUB,true,15,T32_T1,4); size_t tail = t32_skip(c,T32_LO);
  t32_dpi(c,T32_AND,true,15,T32_ADDRESS,3); size_t unaligned = t32_skip(c,T32_NE);
  t32w(c,0xF840|T32_ADDRESS,T32_T2<<12|0x0B04); /* str t2, [lr], #4 */
  t32_dpi(c,T32_SUB,false,T32_T1,T32_T1,4); t32_back(c,loop,T32_AL);
  t32_land(c,tail); t32_land(c,unaligned);
  t32w(c,0xF800|T32_ADDRESS,T32_T2<<12|0x0B01); /* strb t2, [lr], #1 */
  t32_dpi(c,T32_SUB,false,T32_T1,T32_T1,1); t32_back(c,loop,T32_AL);
  t32_land(c,done);
}
/* memmove of size bytes from A to the popped destination. */
static void t32_copy(BackendContext *c, uint32_t size) {
  t32_mv(c,3,0); t32_pop(c,R_DI); t32_li(c,T32_T1,size);
  T32_CMP(6,3); size_t forward = t32_skip(c,T32_LO); /* destination below the source: forward */
  size_t back = c->text.n;
  t32_dpi(c,T32_SUB,true,15,T32_T1,4); size_t back_tail = t32_skip(c,T32_LO);
  /* Both end pointers must be aligned: unequal residues stay bytewise. */
  T32_OP(T32_ADD,T32_ADDRESS,3,T32_T1); T32_OP(T32_ADD,T32_T2,6,T32_T1);
  T32_OP(T32_ORR,T32_T2,T32_ADDRESS,T32_T2);
  t32_dpi(c,T32_AND,true,15,T32_T2,3); size_t back_unaligned = t32_skip(c,T32_NE);
  t32_mem(c,T32_LDR,T32_T2,T32_ADDRESS,-4);
  T32_OP(T32_ADD,T32_ADDRESS,6,T32_T1); t32_mem(c,T32_STR,T32_T2,T32_ADDRESS,-4);
  t32_dpi(c,T32_SUB,false,T32_T1,T32_T1,4); t32_back(c,back,T32_AL);
  t32_land(c,back_tail); t32_land(c,back_unaligned);
  t32_dpi(c,T32_SUB,true,T32_T1,T32_T1,1); size_t back_done = t32_skip(c,T32_LO);
  T32_OP(T32_ADD,T32_ADDRESS,3,T32_T1); t32_mem(c,T32_LDRB,T32_T2,T32_ADDRESS,0);
  T32_OP(T32_ADD,T32_ADDRESS,6,T32_T1); t32_mem(c,T32_STRB,T32_T2,T32_ADDRESS,0); t32_back(c,back,T32_AL);
  t32_land(c,forward);
  size_t next = c->text.n;
  t32_dpi(c,T32_SUB,true,15,T32_T1,4); size_t tail = t32_skip(c,T32_LO);
  T32_OP(T32_ORR,T32_T2,3,6);
  t32_dpi(c,T32_AND,true,15,T32_T2,3); size_t unaligned = t32_skip(c,T32_NE);
  t32w(c,0xF850|3,T32_T2<<12|0x0B04); /* ldr t2, [r3], #4 */
  t32w(c,0xF840|6,T32_T2<<12|0x0B04); /* str t2, [r6], #4 */
  t32_dpi(c,T32_SUB,false,T32_T1,T32_T1,4); t32_back(c,next,T32_AL);
  t32_land(c,tail); t32_land(c,unaligned);
  t32_dpi(c,T32_SUB,true,T32_T1,T32_T1,1); size_t done = t32_skip(c,T32_LO);
  t32w(c,0xF810|3,T32_T2<<12|0x0B01); /* ldrb t2, [r3], #1 */
  t32w(c,0xF800|6,T32_T2<<12|0x0B01); /* strb t2, [r6], #1 */
  t32_back(c,next,T32_AL);
  t32_land(c,done); t32_land(c,back_done);
}
static void t32_step(BackendContext *c, int delta) {
  t32_dpi(c,delta > 0 ? T32_ADD : T32_SUB,true,0,0,1); t32_dpi(c,delta > 0 ? T32_ADC : T32_SBC,false,4,4,0);
}
static void t32_add_frame(BackendContext *c, uint32_t offset) {
  t32_frame(c,T32_LDR,T32_T1,offset); t32_frame(c,T32_LDR,T32_T2,offset+4);
  T32_OPS(T32_ADD,0,0,T32_T1); T32_OP(T32_ADC,4,4,T32_T2);
}
static void t32_store_result_pointer(BackendContext *c, uint32_t offset) {
  t32_frame(c,T32_STR,0,offset); t32_li(c,T32_T1,0); t32_frame(c,T32_STR,T32_T1,offset+4);
}
static void t32_result_pointer(BackendContext *c, uint32_t offset) { t32_frame_address(c,0,offset); }
/* Bank offsets of an incoming argument class: low and high words. */
static void t32_bank(int cls, int32_t *low, int32_t *high) {
  if (cls & 32) { int k = cls & 31; *low = k * 8; *high = (k + 1) * 8; return; }
  if (cls >= 16) { *low = 64 + (cls - 16) * 4; *high = -1; return; }
  if (cls >= 8) { *low = 64 + (cls - 8) * 8; *high = *low + 4; return; }
  *low = cls * 8; *high = -1;
}
static void t32_store_argument(BackendContext *c, int cls, uint32_t offset) {
  if (c->soft_float && !(cls & 32) && cls >= 8) { c->text.failed = true; return; }
  int32_t low, high; t32_bank(cls,&low,&high);
  t32_mem(c,T32_LDR,T32_T1,T32_SP,low); t32_frame(c,T32_STR,T32_T1,offset);
  if (high >= 0) t32_mem(c,T32_LDR,T32_T1,T32_SP,high); else t32_li(c,T32_T1,0);
  t32_frame(c,T32_STR,T32_T1,offset+4);
}
static void t32_argument_to_a(BackendContext *c, int cls) {
  if (c->soft_float && !(cls & 32) && cls >= 8) { c->text.failed = true; return; }
  int32_t low, high; t32_bank(cls,&low,&high);
  t32_mem(c,T32_LDR,0,T32_SP,low);
  if (high >= 0) t32_mem(c,T32_LDR,4,T32_SP,high); else t32_li(c,4,0);
}
static size_t t32_once(BackendContext *c) {
  t32_mem(c,T32_LDRB,T32_T1,0,0); t32_li(c,T32_T2,0); t32_compare_regs(c,T32_T1,T32_T2,T32_T2,T32_T2);
  size_t done = t32_branch(c,CC_NE);
  t32_li(c,T32_T1,1); t32_mem(c,T32_STRB,T32_T1,0,0);
  return done;
}
static void t32_test32(BackendContext *c) {
  t32_shift_imm(c,T32_ASR,T32_T1,0,31); t32_li(c,T32_T2,0); t32_compare_regs(c,0,T32_T1,T32_T2,T32_T2);
}
static void t32_compare_top(BackendContext *c) {
  t32_mem(c,T32_LDR,T32_T1,T32_SP,0); t32_to_s2(c,T32_LOW_A,0,T32_T1);
  t32_mem(c,T32_LDR,T32_T1,T32_SP,4); t32_to_s2(c,T32_HIGH_A,4,T32_T1);
}
/* Runtime routines that take (pointer, u64): the u64 goes in r2:r3. */
static void t32_runtime_arguments(BackendContext *c, unsigned runtime) {
  if (runtime == 0 || runtime == 1 || runtime == RUNTIME_CHECK_FAILED) { t32_mv(c,2,1); t32_from_s(c,3,t32_hi[R_D]); }
}
/* Results: r0, r0:r1 for 64-bit integers and slices, r0-r2 for any, s0/d0
   for floats. */
static void t32_return_registers(BackendContext *c, DynType type, bool wide) {
  if (c->soft_float && (type == DYN_TYPE_F32 || type == DYN_TYPE_F64)) {
    if (type == DYN_TYPE_F64) t32_mv(c,1,4);
    return;
  }
  if (type == DYN_TYPE_F32) t32_to_s(c,0,0);
  else if (type == DYN_TYPE_F64) t32_to_d(c,0,0,4);
  else if (type == DYN_TYPE_ANY) { t32_mv(c,2,1); t32_mv(c,1,4); }
  else if (wide) t32_mv(c,1,4);
}
static void t32_call_result(BackendContext *c, DynType type, bool descriptor_type, bool wide) {
  if (c->soft_float && (type == DYN_TYPE_F32 || type == DYN_TYPE_F64)) {
    if (type == DYN_TYPE_F64) t32_mv(c,4,1); else t32_li(c,4,0);
    return;
  }
  if (type == DYN_TYPE_F32 || type == DYN_TYPE_F64) return; /* isa_float_result reads s0/d0 */
  if (type == DYN_TYPE_ANY) { t32_mv(c,4,1); t32_mv(c,1,2); t32_high_imm(c,R_D,0); }
  else if (descriptor_type) { t32_li(c,4,0); t32_high_imm(c,R_D,0); }
  else if (wide) t32_mv(c,4,1);
}
