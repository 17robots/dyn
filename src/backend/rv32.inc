/* RV32IMAFD lowering of the 64-bit register model (included by driver.c after
   rv64.inc, whose encoders it reuses).

   Every model register is a pair of 32-bit registers: the low words live
   where RV64 keeps the whole register (a0, t0, a1-a6) and the high words in
   s2-s9. Values of 32 bits or fewer keep their high word extended, exactly
   as the 64-bit targets keep their upper bits, so the emitter's width checks
   work unchanged. s10/s11 and t5/t6 hold the high and low words of the last
   comparison, t3/t4 the overflow and carry flags, and t1, t2, a7 are
   scratch. s1-s11 are saved in every frame.

   Calls follow ILP32D: 32-bit values take one register, 64-bit integers a
   register pair, doubles an FP register. Division, checked multiplication
   and 64-bit integer/floating conversions call helpers in the start runtime
   (dyn_rv32_*), which use the register model directly. */
/* Operation selectors shared with isa.inc. */
enum { SHIFT_LEFT, SHIFT_RIGHT, SHIFT_ARITHMETIC };
enum { ALU_ADD, ALU_SUB, ALU_AND, ALU_OR, ALU_XOR };
enum { UNARY_NOT, UNARY_NEGATE, UNARY_BOOL_NOT };
enum { FLOAT_ADD, FLOAT_SUB, FLOAT_MUL, FLOAT_DIV };
static const unsigned char r32_lo[] = {10,5,11,12,13,14,15,16};
static const unsigned char r32_hi[] = {18,19,20,21,22,23,24,25};
enum { R32_T1 = 6, R32_T2 = 7, R32_A7 = 17, R32_LA = 30, R32_LB = 31, R32_HA = 26, R32_HB = 27,
       R32_OVERFLOW = 28, R32_CARRY = 29, R32_SAVED = 48 /* s1-s11, rounded to 16 bytes */ };
static void r32_li(BackendContext *c, unsigned d, uint32_t value) {
  int32_t n = (int32_t)value;
  if (n >= -2048 && n <= 2047) { rv_i(c,0x13,d,0,n,0); return; }
  int32_t low = (int32_t)(value << 20) >> 20;
  word(c, 0x37 | d << 7 | ((value - (uint32_t)low) & 0xfffff000u)); /* lui */
  if (low) rv_i(c,0x13,d,d,low,0);
}
static void r32_mv(BackendContext *c, unsigned d, unsigned s) { if (d != s) rv_move(c,d,s); }
static void r32_op(BackendContext *c, unsigned f3, unsigned f7, unsigned d, unsigned a, unsigned b) { rv_r(c,0x33,d,a,b,f3,f7); }
#define R32_ADD(d,a,b) r32_op(c,0,0,d,a,b)
#define R32_SUB(d,a,b) r32_op(c,0,32,d,a,b)
#define R32_SLT(d,a,b) r32_op(c,2,0,d,a,b)
#define R32_SLTU(d,a,b) r32_op(c,3,0,d,a,b)
#define R32_XOR(d,a,b) r32_op(c,4,0,d,a,b)
#define R32_OR(d,a,b) r32_op(c,6,0,d,a,b)
#define R32_AND(d,a,b) r32_op(c,7,0,d,a,b)
#define R32_SLL(d,a,b) r32_op(c,1,0,d,a,b)
#define R32_SRL(d,a,b) r32_op(c,5,0,d,a,b)
#define R32_SRA(d,a,b) r32_op(c,5,32,d,a,b)
#define R32_MUL(d,a,b) r32_op(c,0,1,d,a,b)
#define R32_MULHU(d,a,b) r32_op(c,3,1,d,a,b)
#define R32_ADDI(d,s,n) rv_i(c,0x13,d,s,n,0)
#define R32_SLTIU(d,s,n) rv_i(c,0x13,d,s,n,3)
#define R32_XORI(d,s,n) rv_i(c,0x13,d,s,n,4)
#define R32_ANDI(d,s,n) rv_i(c,0x13,d,s,n,7)
#define R32_SLLI(d,s,n) rv_i(c,0x13,d,s,n,1)
#define R32_SRLI(d,s,n) rv_i(c,0x13,d,s,n,5)
#define R32_SRAI(d,s,n) rv_i(c,0x13,d,s,0x400|(n),5)
#define R32_LW(d,base,offset) rv_memory(c,false,d,base,offset,2,false)
#define R32_SW(s,base,offset) rv_memory(c,true,s,base,offset,2,false)
/* Local forward branch with its displacement patched later. */
static size_t r32_skip(BackendContext *c, unsigned a, unsigned b, unsigned f3) {
  size_t at = c->text.n; rv_b(c,a,b,f3,0); return at;
}
static void r32_land(BackendContext *c, size_t at) {
  int64_t delta = (int64_t)c->text.n - (int64_t)at;
  if (delta >= 4096 || at + 4 > c->text.n) { c->text.failed = true; return; }
  uint32_t u = (uint32_t)delta, insn;
  memcpy(&insn, c->text.data + at, 4);
  insn |= ((u>>11)&1)<<7 | ((u>>1)&15)<<8 | ((u>>5)&63)<<25 | ((u>>12)&1)<<31;
  patch_word(c, at, insn);
}
static void r32_back(BackendContext *c, size_t destination) {
  rv_b(c,0,0,0,(int)((int64_t)destination - (int64_t)c->text.n));
}
static void r32_pair(BackendContext *c, Reg r, uint64_t value) {
  r32_li(c, r32_lo[r], (uint32_t)value); r32_li(c, r32_hi[r], (uint32_t)(value >> 32));
}
static void r32_compare_regs(BackendContext *c, unsigned alo, unsigned ahi, unsigned blo, unsigned bhi) {
  r32_mv(c,R32_LA,alo); r32_mv(c,R32_HA,ahi); r32_mv(c,R32_LB,blo); r32_mv(c,R32_HB,bhi);
}
/* t1 <- (a < b) over 64 bits. */
static void r32_less(BackendContext *c, unsigned alo, unsigned ahi, unsigned blo, unsigned bhi, bool sign) {
  if (sign) R32_SLT(R32_T1,ahi,bhi); else R32_SLTU(R32_T1,ahi,bhi);
  R32_XOR(R32_T2,ahi,bhi); R32_SLTIU(R32_T2,R32_T2,1);
  R32_SLTU(R32_A7,alo,blo); R32_AND(R32_T2,R32_T2,R32_A7); R32_OR(R32_T1,R32_T1,R32_T2);
}
/* t1 <- whether condition holds for the last comparison or flags. */
static void r32_condition(BackendContext *c, int cond) {
  switch (cond) {
  case CC_E: case CC_NE:
    R32_XOR(R32_T1,R32_LA,R32_LB); R32_XOR(R32_T2,R32_HA,R32_HB); R32_OR(R32_T1,R32_T1,R32_T2);
    if (cond == CC_E) R32_SLTIU(R32_T1,R32_T1,1); else R32_SLTU(R32_T1,0,R32_T1);
    return;
  case CC_B: case CC_AE: r32_less(c,R32_LA,R32_HA,R32_LB,R32_HB,false); break;
  case CC_A: case CC_BE: r32_less(c,R32_LB,R32_HB,R32_LA,R32_HA,false); break;
  case CC_L: case CC_GE: r32_less(c,R32_LA,R32_HA,R32_LB,R32_HB,true); break;
  case CC_G: case CC_LE: r32_less(c,R32_LB,R32_HB,R32_LA,R32_HA,true); break;
  case CC_NO: R32_SLTIU(R32_T1,R32_OVERFLOW,1); return;
  case CC_NO_CARRY: R32_SLTIU(R32_T1,R32_CARRY,1); return;
  default: c->text.failed = true; return;
  }
  if (cond == CC_AE || cond == CC_BE || cond == CC_GE || cond == CC_LE) R32_XORI(R32_T1,R32_T1,1);
}
static size_t r32_branch(BackendContext *c, int cond) {
  if (cond >= 0) { r32_condition(c,cond); rv_b(c,R32_T1,0,0,12); } /* skip the jump when false */
  size_t at = c->text.n; word(c,0x00000317); rv_i(c,0x67,0,6,0,0); return at;
}
/* Stack scratch for moving doubles between integer pairs and FP registers. */
static void r32_pair_to_fp(BackendContext *c, unsigned f, unsigned lo, unsigned hi) {
  if (c->soft_float) { c->text.failed = true; return; } /* Invalid FP ABI class. */
  R32_ADDI(2,2,-16); R32_SW(lo,2,0); R32_SW(hi,2,4); rv_memory(c,false,f,2,0,3,true); R32_ADDI(2,2,16);
}
static void r32_fp_to_pair(BackendContext *c, unsigned lo, unsigned hi, unsigned f) {
  if (c->soft_float) { c->text.failed = true; return; } /* Invalid FP ABI class. */
  R32_ADDI(2,2,-16); rv_memory(c,true,f,2,0,3,true); R32_LW(lo,2,0); R32_LW(hi,2,4); R32_ADDI(2,2,16);
}

static void r32_load(BackendContext *c, Reg r, uint32_t offset) {
  R32_LW(r32_lo[r],8,(int32_t)offset); R32_LW(r32_hi[r],8,(int32_t)offset+4);
}
static void r32_store(BackendContext *c, Reg r, uint32_t offset) {
  R32_SW(r32_lo[r],8,(int32_t)offset); R32_SW(r32_hi[r],8,(int32_t)offset+4);
}
static void r32_lea(BackendContext *c, Reg r, uint32_t offset) {
  rv_address(c,r32_lo[r],8,(int32_t)offset); r32_li(c,r32_hi[r],0);
}
static void r32_immediate(BackendContext *c, Reg r, uint64_t n) { r32_pair(c,r,n); }
static void r32_zero(BackendContext *c, Reg r) { r32_pair(c,r,0); }
static void r32_move(BackendContext *c, Reg to, Reg from) {
  r32_mv(c,r32_lo[to],r32_lo[from]); r32_mv(c,r32_hi[to],r32_hi[from]);
}
static void r32_push(BackendContext *c, Reg r) {
  bare_stack_check(c,16);
  ++c->stack_slots; R32_ADDI(2,2,-16); R32_SW(r32_lo[r],2,0); R32_SW(r32_hi[r],2,4);
}
static void r32_pop(BackendContext *c, Reg r) {
  --c->stack_slots; R32_LW(r32_lo[r],2,0); R32_LW(r32_hi[r],2,4); R32_ADDI(2,2,16);
}
static void r32_peek(BackendContext *c, Reg r, unsigned slot) {
  R32_LW(r32_lo[r],2,(int32_t)slot*16); R32_LW(r32_hi[r],2,(int32_t)slot*16+4);
}
static void r32_drop(BackendContext *c, unsigned count) { c->stack_slots -= count; rv_address(c,2,2,(int64_t)count*16); }
static void r32_test(BackendContext *c, Reg r) { r32_compare_regs(c,r32_lo[r],r32_hi[r],0,0); }
static void r32_compare(BackendContext *c, Reg left, Reg right) {
  r32_compare_regs(c,r32_lo[left],r32_hi[left],r32_lo[right],r32_hi[right]);
}
static void r32_compare_frame(BackendContext *c, uint32_t offset) {
  r32_mv(c,R32_LA,10); r32_mv(c,R32_HA,18);
  R32_LW(R32_LB,8,(int32_t)offset); R32_LW(R32_HB,8,(int32_t)offset+4);
}
static void r32_set(BackendContext *c, Cond cond) { r32_condition(c,cond); r32_mv(c,10,R32_T1); r32_li(c,18,0); }
static void r32_local_address(BackendContext *c, Reg r, unsigned symbol, size_t offset) {
  rv_symbol(c,r32_lo[r],symbol,(int64_t)offset,false); r32_li(c,r32_hi[r],0);
}
static void r32_symbol_address(BackendContext *c, Reg r, unsigned symbol) {
  rv_symbol(c,r32_lo[r],symbol,0,true); r32_li(c,r32_hi[r],0);
}
/* (pointer, length) arguments: runtime_call moves D's high word to a2, since
   the length is a u64 in the runtime's signature. */
static void r32_string_arguments(BackendContext *c, size_t offset, size_t length) {
  rv_symbol(c,10,1,(int64_t)offset,false); r32_li(c,11,(uint32_t)length); r32_li(c,20,0);
}
static void r32_reset_stack(BackendContext *c) { rv_address(c,2,8,-(int64_t)c->frame_bytes-R32_SAVED); }
static void r32_extend(BackendContext *c, unsigned bits, bool sign) {
  if (bits >= 64) return;
  if (bits == 1) { R32_ANDI(10,10,1); r32_li(c,18,0); return; }
  if (bits < 32) { R32_SLLI(10,10,32-bits); if (sign) R32_SRAI(10,10,32-bits); else R32_SRLI(10,10,32-bits); }
  if (sign) R32_SRAI(18,10,31); else r32_li(c,18,0);
}
static void r32_load_value(BackendContext *c, unsigned bits, bool sign) {
  if (bits >= 64) { R32_LW(18,10,4); R32_LW(10,10,0); return; }
  rv_memory(c,false,10,10,0,bits<=8?(sign?0:4):bits==16?(sign?1:5):2,false);
  if (sign) R32_SRAI(18,10,31); else r32_li(c,18,0);
}
static void r32_store_value(BackendContext *c, unsigned bits) {
  rv_memory(c,true,10,16,0,bits<=8?0:bits==16?1:2,false);
  if (bits >= 64) R32_SW(18,16,4);
}
/* R10 <- size bytes at [R11 + offset], zero-extended, one byte at a time. */
static void r32_load_chunk(BackendContext *c, unsigned offset, unsigned size) {
  rv_address(c,R32_T1,16,offset); r32_li(c,15,0); r32_li(c,24,0);
  for (unsigned i = 0; i < size; ++i) {
    unsigned into = i < 4 ? 15 : 24;
    rv_memory(c,false,R32_T2,R32_T1,i,4,false);
    if (i % 4) R32_SLLI(R32_T2,R32_T2,8*(i%4));
    R32_OR(into,into,R32_T2);
  }
}
/* [DI + offset] <- the low bytes of R10 (consumed). */
static void r32_store_chunk(BackendContext *c, unsigned offset, unsigned bytes) {
  rv_address(c,R32_T1,13,offset);
  for (unsigned j = 0; j < bytes; ++j) {
    unsigned from = j < 4 ? 15 : 24;
    rv_memory(c,true,from,R32_T1,j,0,false);
    if (j % 4 != 3 && j + 1 < bytes) R32_SRLI(from,from,8);
  }
}
/* Constant-free helpers for flags and pointers. */
static void r32_test_mask(BackendContext *c, uint32_t mask) {
  r32_li(c,R32_T1,mask); R32_AND(R32_LA,10,R32_T1); r32_li(c,R32_HA,0); r32_li(c,R32_LB,0); r32_li(c,R32_HB,0);
}
static void r32_compare_small(BackendContext *c, Reg r, int value) {
  r32_mv(c,R32_LA,r32_lo[r]); r32_mv(c,R32_HA,r32_hi[r]);
  r32_li(c,R32_LB,(uint32_t)value); r32_li(c,R32_HB,value < 0 ? UINT32_MAX : 0);
}
static bool r32_compare_immediate(BackendContext *c, uint64_t value) {
  r32_mv(c,R32_LA,10); r32_mv(c,R32_HA,18); r32_li(c,R32_LB,(uint32_t)value); r32_li(c,R32_HB,(uint32_t)(value >> 32));
  return true;
}
enum { R32_UDIV, R32_UREM, R32_SDIV, R32_SREM };
static void r32_helper(BackendContext *c, unsigned runtime, uint32_t mode);
static void r32_divide(BackendContext *c, bool sign, bool remainder) {
  if (!sign) {
    /* Both high words zero: one 32-bit instruction. */
    R32_OR(R32_T1,18,19); size_t slow = r32_skip(c,R32_T1,0,1);
    r32_op(c,remainder?7:5,1,10,10,5); r32_li(c,18,0);
    size_t done = c->text.n; rv_b(c,0,0,0,0);
    r32_land(c,slow);
    r32_helper(c,RUNTIME_RV32_DIVIDE,remainder?R32_UREM:R32_UDIV);
    r32_land(c,done);
    return;
  }
  r32_helper(c,RUNTIME_RV32_DIVIDE,remainder?R32_SREM:R32_SDIV);
}
/* reg <- reg shifted by C (0-63). */
static void r32_shift(BackendContext *c, Reg r, int kind) {
  unsigned lo = r32_lo[r], hi = r32_hi[r];
  R32_ANDI(R32_T1,5,32); size_t small = r32_skip(c,R32_T1,0,0);
  if (kind == SHIFT_LEFT) { R32_SLL(hi,lo,5); r32_li(c,lo,0); }
  else if (kind == SHIFT_RIGHT) { R32_SRL(lo,hi,5); r32_li(c,hi,0); }
  else { R32_SRA(lo,hi,5); R32_SRAI(hi,hi,31); }
  size_t done = c->text.n; rv_b(c,0,0,0,0);
  r32_land(c,small);
  size_t zero = r32_skip(c,5,0,0);
  R32_SUB(R32_T1,0,5); /* 32 - count in the low five bits */
  if (kind == SHIFT_LEFT) { R32_SLL(hi,hi,5); R32_SRL(R32_T2,lo,R32_T1); R32_OR(hi,hi,R32_T2); R32_SLL(lo,lo,5); }
  else {
    R32_SRL(lo,lo,5); R32_SLL(R32_T2,hi,R32_T1); R32_OR(lo,lo,R32_T2);
    if (kind == SHIFT_RIGHT) R32_SRL(hi,hi,5); else R32_SRA(hi,hi,5);
  }
  r32_land(c,zero); r32_land(c,done);
}
static void r32_alu(BackendContext *c, int op, Reg to, Reg from) {
  unsigned l1 = r32_lo[to], h1 = r32_hi[to], l2 = r32_lo[from], h2 = r32_hi[from];
  if (op == ALU_AND || op == ALU_OR || op == ALU_XOR) {
    unsigned f3 = op == ALU_AND ? 7 : op == ALU_OR ? 6 : 4;
    r32_op(c,f3,0,l1,l1,l2); r32_op(c,f3,0,h1,h1,h2); return;
  }
  r32_compare_regs(c,l1,h1,l2,h2);
  if (op == ALU_ADD) {
    R32_ADD(l1,l1,l2); R32_SLTU(R32_T1,l1,R32_LB); R32_ADD(h1,h1,R32_HB); R32_ADD(h1,h1,R32_T1);
    R32_XOR(R32_T1,R32_HA,h1); R32_XOR(R32_T2,R32_HB,h1); R32_AND(R32_T1,R32_T1,R32_T2); R32_SRLI(R32_OVERFLOW,R32_T1,31);
    r32_less(c,l1,h1,R32_LA,R32_HA,false); r32_mv(c,R32_CARRY,R32_T1);
  } else {
    R32_SLTU(R32_T1,l1,l2); R32_SUB(l1,l1,l2); R32_SUB(h1,h1,h2); R32_SUB(h1,h1,R32_T1);
    R32_XOR(R32_T1,R32_HA,R32_HB); R32_XOR(R32_T2,R32_HA,h1); R32_AND(R32_T1,R32_T1,R32_T2); R32_SRLI(R32_OVERFLOW,R32_T1,31);
    r32_less(c,R32_LA,R32_HA,R32_LB,R32_HB,false); r32_mv(c,R32_CARRY,R32_T1);
  }
}
static void r32_add_immediate(BackendContext *c, uint32_t n) {
  if (!n) return;
  r32_li(c,R32_T1,n); R32_ADD(10,10,R32_T1); R32_SLTU(R32_T1,10,R32_T1); R32_ADD(18,18,R32_T1);
}
static void r32_scale(BackendContext *c, Reg r, uint32_t n) {
  unsigned lo = r32_lo[r], hi = r32_hi[r];
  r32_li(c,R32_T1,n); R32_MULHU(R32_T2,lo,R32_T1); R32_MUL(lo,lo,R32_T1); R32_MUL(hi,hi,R32_T1); R32_ADD(hi,hi,R32_T2);
}
static void r32_small_immediate(BackendContext *c, Reg r, uint32_t n) { r32_li(c,r32_lo[r],n); r32_li(c,r32_hi[r],0); }
/* Argument register cls <- the stack slot at byte offset. GP classes with bit
   5 set are register pairs; 8-15 are doubles and 16-23 floats. */
static void r32_argument_load(BackendContext *c, int cls, uint32_t offset) {
  if (cls & 32) { unsigned k = (unsigned)cls & 31; R32_LW(10+k,2,(int32_t)offset); R32_LW(10+k+1,2,(int32_t)offset+4); return; }
  if (c->soft_float && cls >= 8) { c->text.failed = true; return; }
  if (cls >= 16) { rv_memory(c,false,10+(unsigned)(cls-16),2,offset,2,true); return; }
  if (cls >= 8 && cls < 16) { rv_memory(c,false,10+(unsigned)(cls-8),2,offset,3,true); return; }
  unsigned k = (unsigned)cls & 31;
  R32_LW(10+k,2,(int32_t)offset);
  if (cls & 32) R32_LW(10+k+1,2,(int32_t)offset+4);
}
static void r32_stack_store(BackendContext *c, uint32_t from, uint32_t to, uint32_t bytes) {
  R32_LW(R32_T1,2,(int32_t)from); R32_SW(R32_T1,2,(int32_t)to);
  if (bytes == 8) { R32_LW(R32_T1,2,(int32_t)from+4); R32_SW(R32_T1,2,(int32_t)to+4); }
}
static void r32_call_stack(BackendContext *c, uint32_t offset) { R32_LW(R32_T1,2,(int32_t)offset); rv_i(c,0x67,1,R32_T1,0,0); }
static void r32_a_to_float(BackendContext *c) {
  if (c->soft_float) { r32_mv(c,11,18); return; }
  r32_pair_to_fp(c,10,10,18);
}
/* Descriptors in memory: slices hold a 32-bit pointer and length, any a
   64-bit type identifier and a 32-bit pointer at offset 8. */
static void r32_load_descriptor(BackendContext *c, bool any) {
  if (any) { R32_LW(11,10,8); R32_LW(18,10,4); R32_LW(10,10,0); }
  else { R32_LW(11,10,4); R32_LW(10,10,0); r32_li(c,18,0); }
  r32_li(c,20,0);
}
static void r32_store_descriptor(BackendContext *c, bool any) {
  R32_SW(10,16,0);
  if (any) { R32_SW(18,16,4); R32_SW(11,16,8); } else R32_SW(11,16,4);
}
static void r32_match_begin(BackendContext *c) { r32_li(c,14,0); r32_li(c,23,0); }
static void r32_match_tag(BackendContext *c, uint64_t tag) {
  r32_li(c,R32_T1,(uint32_t)tag); R32_XOR(R32_T1,10,R32_T1);
  r32_li(c,R32_T2,(uint32_t)(tag >> 32)); R32_XOR(R32_T2,18,R32_T2);
  R32_OR(R32_T1,R32_T1,R32_T2); R32_SLTIU(R32_T1,R32_T1,1); R32_OR(14,14,R32_T1);
}
static void r32_match_test(BackendContext *c) { r32_compare_regs(c,14,0,0,0); }
/* Software helpers use ordinary ILP32, not the private dyn_rv32 ABI.
   Preserve all non-A model registers: their high halves are callee-saved,
   but C's low half (t0) and D..R11 (a1..a6) are caller-saved. The 32-byte
   save area stays aligned and is balanced without changing stack_slots.
   a0:a1 receives/returns 64 bits; a2:a3 is the second 64-bit operand. */
static void r32_soft_helper(BackendContext *c, unsigned runtime, bool input32,
                            bool binary, bool result32) {
  bare_stack_check(c,32);
  R32_ADDI(2,2,-32);
  R32_SW(5,2,0);
  for (unsigned i = 0; i < 6; ++i) R32_SW(11+i,2,4+4*(int32_t)i);
  if (!input32) r32_mv(c,11,18);
  if (binary) {
    r32_mv(c,input32?11:12,5);
    if (!input32) r32_mv(c,13,19);
  }
  runtime_call(c,runtime);
  if (result32) r32_li(c,18,0); else r32_mv(c,18,11);
  R32_LW(5,2,0);
  for (unsigned i = 0; i < 6; ++i) R32_LW(11+i,2,4+4*(int32_t)i);
  R32_ADDI(2,2,32);
}
enum { R32_FLOAT32 = 1, R32_UNSIGNED64 = 2 };
static void r32_int_to_float(BackendContext *c, bool f32, bool unsigned64) {
  if (c->soft_float) {
    unsigned helper = f32 ? (unsigned64 ? RUNTIME_SOFT_U64_TO_F32 : RUNTIME_SOFT_I64_TO_F32)
                          : (unsigned64 ? RUNTIME_SOFT_U64_TO_F64 : RUNTIME_SOFT_I64_TO_F64);
    r32_soft_helper(c,helper,false,false,f32); return;
  }
  r32_helper(c,RUNTIME_RV32_INT_TO_FLOAT,(f32?R32_FLOAT32:0)|(unsigned64?R32_UNSIGNED64:0));
}
static void r32_float_to_int(BackendContext *c, bool f32, bool unsigned64) {
  if (c->soft_float) {
    unsigned helper = f32 ? (unsigned64 ? RUNTIME_SOFT_F32_TO_U64 : RUNTIME_SOFT_F32_TO_I64)
                          : (unsigned64 ? RUNTIME_SOFT_F64_TO_U64 : RUNTIME_SOFT_F64_TO_I64);
    r32_soft_helper(c,helper,f32,false,false); return;
  }
  r32_helper(c,RUNTIME_RV32_FLOAT_TO_INT,(f32?R32_FLOAT32:0)|(unsigned64?R32_UNSIGNED64:0));
}
static void r32_float_convert(BackendContext *c, bool from32) {
  if (c->soft_float) {
    r32_soft_helper(c,from32?RUNTIME_SOFT_F32_TO_F64:RUNTIME_SOFT_F64_TO_F32,from32,false,!from32); return;
  }
  if (from32) { rv_r(c,0x53,0,10,0,0,0x78); rv_r(c,0x53,0,0,0,7,0x21); r32_fp_to_pair(c,10,18,0); return; }
  r32_pair_to_fp(c,0,10,18); rv_r(c,0x53,0,0,1,7,0x20); rv_r(c,0x53,10,0,0,0,0x70); r32_li(c,18,0);
}
static void r32_unary(BackendContext *c, int op) {
  if (op == UNARY_NOT) { R32_XORI(10,10,-1); R32_XORI(18,18,-1); return; }
  if (op == UNARY_BOOL_NOT) { R32_XORI(10,10,1); return; }
  r32_compare_regs(c,0,0,10,18);
  r32_li(c,R32_T1,0x80000000u); R32_XOR(R32_T1,18,R32_T1); R32_OR(R32_T1,R32_T1,10); R32_SLTIU(R32_OVERFLOW,R32_T1,1);
  R32_SLTU(R32_T1,0,10); R32_SUB(10,0,10); R32_SUB(18,0,18); R32_SUB(18,18,R32_T1);
}
static void r32_float_operands(BackendContext *c, bool f32) {
  if (c->soft_float) return; /* Helpers consume and produce raw A/C bits. */
  if (f32) { rv_r(c,0x53,10,10,0,0,0x78); rv_r(c,0x53,11,5,0,0,0x78); return; }
  R32_ADDI(2,2,-16); R32_SW(10,2,0); R32_SW(18,2,4); R32_SW(5,2,8); R32_SW(19,2,12);
  rv_memory(c,false,10,2,0,3,true); rv_memory(c,false,11,2,8,3,true); R32_ADDI(2,2,16);
}
static void r32_float_result(BackendContext *c, bool f32) {
  if (c->soft_float) return; /* Helpers consume and produce raw A/C bits. */
  if (f32) { rv_r(c,0x53,10,10,0,0,0x70); r32_li(c,18,0); return; }
  r32_fp_to_pair(c,10,18,10);
}
static void r32_float_compare(BackendContext *c, bool f32, unsigned op) {
  if (c->soft_float) {
    static const unsigned helpers[2][6] = {
      {RUNTIME_SOFT_F64_EQ,RUNTIME_SOFT_F64_NE,RUNTIME_SOFT_F64_LT,RUNTIME_SOFT_F64_LE,RUNTIME_SOFT_F64_GT,RUNTIME_SOFT_F64_GE},
      {RUNTIME_SOFT_F32_EQ,RUNTIME_SOFT_F32_NE,RUNTIME_SOFT_F32_LT,RUNTIME_SOFT_F32_LE,RUNTIME_SOFT_F32_GT,RUNTIME_SOFT_F32_GE}
    };
    if (op >= 6) { c->text.failed = true; return; }
    r32_soft_helper(c,helpers[f32][op],f32,true,true); return;
  }
  rv_float_compare(c,f32,op); r32_li(c,18,0);
}
/* Soft-only adapter: operands and result are raw A/C model pairs. */
static inline void r32_float_remainder(BackendContext *c, bool f32) {
  if (!c->soft_float) { c->text.failed = true; return; }
  r32_soft_helper(c,f32?RUNTIME_SOFT_F32_REM:RUNTIME_SOFT_F64_REM,f32,true,f32);
}
static void r32_float_arithmetic(BackendContext *c, bool f32, int op) {
  if (c->soft_float) {
    static const unsigned helpers[2][4] = {
      {RUNTIME_SOFT_F64_ADD,RUNTIME_SOFT_F64_SUB,RUNTIME_SOFT_F64_MUL,RUNTIME_SOFT_F64_DIV},
      {RUNTIME_SOFT_F32_ADD,RUNTIME_SOFT_F32_SUB,RUNTIME_SOFT_F32_MUL,RUNTIME_SOFT_F32_DIV}
    };
    if ((unsigned)op >= 4) { c->text.failed = true; return; }
    r32_soft_helper(c,helpers[f32][op],f32,true,f32); return;
  }
  rv_r(c,0x53,10,10,11,7,(unsigned)op*4+(f32?0:1)); r32_float_result(c,f32);
}
static void r32_multiply(BackendContext *c, bool checked, bool sign) {
  if (checked) {
    /* The helper leaves overflow (0 or 1) in t1; success compares equal to zero. */
    r32_helper(c,RUNTIME_RV32_MULTIPLY,sign);
    r32_compare_regs(c,R32_T1,0,0,0);
    return;
  }
  R32_MULHU(R32_T1,10,5); R32_MUL(R32_T2,10,19); R32_ADD(R32_T1,R32_T1,R32_T2);
  R32_MUL(R32_T2,18,5); R32_ADD(18,R32_T1,R32_T2); R32_MUL(10,10,5);
}
static void r32_trace_pop(BackendContext *c, bool descriptor_result) {
  r32_push(c,R_A);
  if (descriptor_result) r32_push(c,R_D);
  runtime_call(c,2);
  if (descriptor_result) r32_pop(c,R_D);
  r32_pop(c,R_A);
}
/* Frame: s0 and ra above FP, then the locals, then s1-s11. */
static void r32_enter(BackendContext *c) {
  R32_ADDI(2,2,-16); R32_SW(8,2,0); R32_SW(1,2,8);
  rv_move(c,8,2); rv_address(c,2,2,-(int64_t)c->frame_bytes-R32_SAVED);
  R32_SW(9,2,0);
  for (unsigned i = 0; i < 10; ++i) R32_SW(18+i,2,4+4*(int32_t)i);
  /* Incoming banks, as on RV64: integers at i*8, doubles at 64+i*8. */
  R32_ADDI(2,2,-128);
  for (unsigned i = 0; i < 8; ++i) { R32_SW(10+i,2,(int32_t)i*8); if (!c->soft_float) rv_memory(c,true,10+i,2,64+(int32_t)i*8,3,true); }
}
static void r32_return(BackendContext *c) {
  rv_address(c,R32_T1,8,-(int64_t)c->frame_bytes-R32_SAVED);
  R32_LW(9,R32_T1,0);
  for (unsigned i = 0; i < 10; ++i) R32_LW(18+i,R32_T1,4+4*(int32_t)i);
  if (c->dwarf && !backend_dwarf_epilogue(c->dwarf,c->text.n)) c->text.failed=true;
  rv_move(c,2,8); R32_LW(8,2,0); R32_LW(1,2,8); R32_ADDI(2,2,16); rv_i(c,0x67,0,1,0,0);
}
static void r32_zero_fill(BackendContext *c, uint32_t size) {
  r32_li(c,R32_A7,size); rv_move(c,12,10);
  size_t loop = c->text.n, done = r32_skip(c,R32_A7,0,0);
  rv_memory(c,true,0,12,0,0,false); R32_ADDI(12,12,1); R32_ADDI(R32_A7,R32_A7,-1); r32_back(c,loop);
  r32_land(c,done);
}
/* memmove of size bytes from A to the popped destination. */
static void r32_copy(BackendContext *c, uint32_t size) {
  rv_move(c,12,10); r32_pop(c,R_DI); r32_li(c,R32_A7,size);
  size_t forward = r32_skip(c,12,13,7); /* destination below the source: forward */
  size_t back = c->text.n, back_done = r32_skip(c,R32_A7,0,0);
  R32_ADDI(R32_A7,R32_A7,-1); R32_ADD(R32_T1,12,R32_A7); rv_memory(c,false,R32_T2,R32_T1,0,4,false);
  R32_ADD(R32_T1,13,R32_A7); rv_memory(c,true,R32_T2,R32_T1,0,0,false); r32_back(c,back);
  r32_land(c,forward);
  size_t next = c->text.n, done = r32_skip(c,R32_A7,0,0);
  rv_memory(c,false,R32_T2,12,0,4,false); rv_memory(c,true,R32_T2,13,0,0,false);
  R32_ADDI(12,12,1); R32_ADDI(13,13,1); R32_ADDI(R32_A7,R32_A7,-1); r32_back(c,next);
  r32_land(c,done); r32_land(c,back_done);
}
static void r32_step(BackendContext *c, int delta) {
  if (delta > 0) { R32_ADDI(10,10,1); R32_SLTIU(R32_T1,10,1); R32_ADD(18,18,R32_T1); }
  else { R32_SLTIU(R32_T1,10,1); R32_ADDI(10,10,-1); R32_SUB(18,18,R32_T1); }
}
static void r32_add_frame(BackendContext *c, uint32_t offset) {
  R32_LW(R32_T1,8,(int32_t)offset); R32_LW(R32_A7,8,(int32_t)offset+4);
  R32_ADD(10,10,R32_T1); R32_SLTU(R32_T1,10,R32_T1); R32_ADD(18,18,R32_A7); R32_ADD(18,18,R32_T1);
}
static void r32_store_result_pointer(BackendContext *c, uint32_t offset) {
  R32_SW(10,8,(int32_t)offset); R32_SW(0,8,(int32_t)offset+4);
}
/* Bank offsets of an incoming argument class: low and high words. */
static void r32_bank(int cls, int32_t *low, int32_t *high) {
  if (cls & 32) { int k = cls & 31; *low = k * 8; *high = (k + 1) * 8; return; }
  if (cls >= 16) { *low = 64 + (cls - 16) * 8; *high = -1; return; }
  if (cls >= 8) { *low = 64 + (cls - 8) * 8; *high = *low + 4; return; }
  int k = cls & 31; *low = k * 8; *high = cls & 32 ? (k + 1) * 8 : -1;
}
static void r32_store_argument(BackendContext *c, int cls, uint32_t offset) {
  int32_t low, high; r32_bank(cls,&low,&high);
  R32_LW(R32_T1,2,low); R32_SW(R32_T1,8,(int32_t)offset);
  if (high >= 0) { R32_LW(R32_T1,2,high); R32_SW(R32_T1,8,(int32_t)offset+4); }
  else R32_SW(0,8,(int32_t)offset+4);
}
static void r32_argument_to_a(BackendContext *c, int cls) {
  int32_t low, high; r32_bank(cls,&low,&high);
  R32_LW(10,2,low);
  if (high >= 0) R32_LW(18,2,high); else r32_li(c,18,0);
}
static size_t r32_once(BackendContext *c) {
  rv_memory(c,false,R32_T1,10,0,4,false); r32_compare_regs(c,R32_T1,0,0,0);
  size_t done = r32_branch(c,CC_NE);
  r32_li(c,R32_T1,1); rv_memory(c,true,R32_T1,10,0,0,false);
  return done;
}
static void r32_test32(BackendContext *c) { r32_mv(c,R32_LA,10); R32_SRAI(R32_HA,10,31); r32_li(c,R32_LB,0); r32_li(c,R32_HB,0); }
static void r32_compare_top(BackendContext *c) {
  r32_mv(c,R32_LA,10); r32_mv(c,R32_HA,18); R32_LW(R32_LB,2,0); R32_LW(R32_HB,2,4);
}
static void r32_helper(BackendContext *c, unsigned runtime, uint32_t mode) { r32_li(c,R32_T1,mode); runtime_call(c,runtime); }
/* Runtime routines that take (pointer, u64): the u64's high word goes in a2. */
static void r32_runtime_arguments(BackendContext *c, unsigned runtime) {
  if (runtime == 0 || runtime == 1 || runtime == RUNTIME_CHECK_FAILED) rv_move(c,12,20);
}
