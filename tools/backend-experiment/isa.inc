/* Target instruction layer for the native emitter (included by driver.c).

   The IR walker in driver.c is a stack machine over a small register model:
   A is the accumulator and first return register, D carries the second word of
   descriptors, C is the right operand, R10/R11 are scratch value/address
   registers, and SI/DI are copy source/destination. FP addresses the frame;
   pushes and pops use the hardware stack. Each operation below has one
   encoding per target. x86-64 encodings are the original emitter's bytes. */


static const unsigned char x86_jcc[] = {0x84, 0x85, 0x82, 0x83, 0x86, 0x87, 0x8c, 0x8d, 0x8e, 0x8f, 0x81, 0x83};
static const unsigned char x86_setcc[] = {0x94, 0x95, 0x92, 0x93, 0x96, 0x97, 0x9c, 0x9d, 0x9e, 0x9f, 0x91, 0x93};
/* ModRM register field and REX.R/B bit for each model register. */
static const unsigned char x86_code[] = {0, 1, 2, 6, 7, 0, 2, 3};
static const unsigned char x86_extended[] = {0, 0, 0, 0, 0, 1, 1, 1};


/* reg <- [FP + offset], 64-bit. */
static void isa_load(BackendContext *ctx, Reg r, uint32_t offset) {
  if (ctx->a64) { a64_frame(ctx, A64_LDR, r, offset); return; }
  byte(ctx, x86_extended[r] ? 0x4c : 0x48); byte(ctx, 0x8b); byte(ctx, 0x85 | x86_code[r] << 3); word(ctx, offset);
}
/* [FP + offset] <- reg, 64-bit. */
static void isa_store(BackendContext *ctx, Reg r, uint32_t offset) {
  if (ctx->a64) { a64_frame(ctx, A64_STR, r, offset); return; }
  byte(ctx, x86_extended[r] ? 0x4c : 0x48); byte(ctx, 0x89); byte(ctx, 0x85 | x86_code[r] << 3); word(ctx, offset);
}
/* reg <- FP + offset. */
static void isa_lea(BackendContext *ctx, Reg r, uint32_t offset) {
  if (ctx->a64) { a64_frame(ctx, A64_ADD, r, offset); return; }
  byte(ctx, x86_extended[r] ? 0x4c : 0x48); byte(ctx, 0x8d); byte(ctx, 0x85 | x86_code[r] << 3); word(ctx, offset);
}
static void isa_immediate(BackendContext *ctx, Reg r, uint64_t n) {
  if (ctx->a64) { a64_immediate(ctx, a64_reg[r], n); return; }
  byte(ctx, x86_extended[r] ? 0x49 : 0x48); byte(ctx, 0xb8 + x86_code[r]); immediate(ctx, n);
}
static void isa_zero(BackendContext *ctx, Reg r) {
  if (ctx->a64) { a64_immediate(ctx, a64_reg[r], 0); return; }
  byte(ctx, 0x31); byte(ctx, 0xc0 | x86_code[r] << 3 | x86_code[r]);
}
static void isa_move(BackendContext *ctx, Reg to, Reg from) {
  if (ctx->a64) { a64_word(ctx, 0xaa0003e0 | a64_reg[from] << 16 | a64_reg[to]); return; }
  byte(ctx, 0x48 | x86_extended[from] << 2 | x86_extended[to]); byte(ctx, 0x89);
  byte(ctx, 0xc0 | x86_code[from] << 3 | x86_code[to]);
}
static void isa_push(BackendContext *ctx, Reg r) {
  ++ctx->stack_slots;
  if (ctx->a64) { a64_word(ctx, 0xf81f0fe0 | a64_reg[r]); return; } /* str x, [sp, #-16]! */
  if (x86_extended[r]) byte(ctx, 0x41);
  byte(ctx, 0x50 + x86_code[r]);
}
static void isa_pop(BackendContext *ctx, Reg r) {
  --ctx->stack_slots;
  if (ctx->a64) { a64_word(ctx, 0xf84107e0 | a64_reg[r]); return; } /* ldr x, [sp], #16 */
  if (x86_extended[r]) byte(ctx, 0x41);
  byte(ctx, 0x58 + x86_code[r]);
}
/* reg <- the value `slot` pushes below the top, x86-64 short displacement form. */
static void isa_peek_short(BackendContext *ctx, Reg r, unsigned slot) {
  if (ctx->a64) { a64_sp_offset(ctx, A64_LDR, a64_reg[r], slot * 16); return; }
  byte(ctx, x86_extended[r] ? 0x4c : 0x48); byte(ctx, 0x8b);
  if (!slot) { byte(ctx, 0x04 | x86_code[r] << 3); byte(ctx, 0x24); return; }
  byte(ctx, 0x44 | x86_code[r] << 3); byte(ctx, 0x24); byte(ctx, slot * 8);
}
/* reg <- the 64-bit value pushed `slot` pushes before the top (slot 0 is the top). */
static void isa_peek(BackendContext *ctx, Reg r, unsigned slot) {
  if (ctx->a64) { a64_sp_offset(ctx, A64_LDR, a64_reg[r], slot * 16); return; }
  byte(ctx, x86_extended[r] ? 0x4c : 0x48); byte(ctx, 0x8b); byte(ctx, 0x84 | x86_code[r] << 3); byte(ctx, 0x24);
  word(ctx, slot * 8);
}
/* Forget `count` pushed values without loading them. */
static void isa_drop(BackendContext *ctx, unsigned count) {
  ctx->stack_slots -= count;
  if (!count) return;
  if (ctx->a64) { a64_sp_adjust(ctx, (int64_t)count * 16); return; }
  if (count * 8 < 128) { CODE(0x48, 0x83, 0xc4); byte(ctx, count * 8); return; }
  CODE(0x48, 0x81, 0xc4); word(ctx, count * 8);
}
/* Branches: a forward branch slot is patched once its destination is known. */
static size_t isa_branch(BackendContext *ctx, int condition) {
  if (ctx->a64) return a64_branch(ctx, condition);
  if (condition >= 0) { byte(ctx, 0x0f); byte(ctx, x86_jcc[condition]); } else byte(ctx, 0xe9);
  size_t at = ctx->text.n; word(ctx, 0); return at;
}
static void isa_patch(BackendContext *ctx, size_t at, size_t destination) {
  if (ctx->a64) { a64_patch(ctx, at, destination); return; }
  patch_word(ctx, at, (uint32_t)(destination - (at + 4)));
}
static void isa_jump_back(BackendContext *ctx, size_t destination) {
  isa_patch(ctx, isa_branch(ctx, -1), destination);
}
/* Compare A with zero, C, an immediate, or a frame slot; flags feed a branch. */
static void isa_test(BackendContext *ctx, Reg r) {
  if (ctx->a64) { a64_word(ctx, 0xf100001f | a64_reg[r] << 5); return; } /* cmp x, #0 */
  byte(ctx, 0x48 | x86_extended[r] << 2 | x86_extended[r]); byte(ctx, 0x85); byte(ctx, 0xc0 | x86_code[r] << 3 | x86_code[r]);
}
static void isa_compare(BackendContext *ctx, Reg left, Reg right) {
  if (ctx->a64) { a64_word(ctx, 0xeb00001f | a64_reg[right] << 16 | a64_reg[left] << 5); return; }
  byte(ctx, 0x48 | x86_extended[right] << 2 | x86_extended[left]); byte(ctx, 0x39);
  byte(ctx, 0xc0 | x86_code[right] << 3 | x86_code[left]);
}
static void isa_compare_frame(BackendContext *ctx, uint32_t offset) {
  if (ctx->a64) { a64_frame(ctx, A64_LDR, R_C, offset); a64_word(ctx, 0xeb00001f | a64_reg[R_C] << 16 | a64_reg[R_A] << 5); return; }
  CODE(0x48, 0x3b, 0x85); word(ctx, offset);
}
static void isa_set(BackendContext *ctx, Cond condition) {
  if (ctx->a64) { a64_word(ctx, 0x9a9f07e0 | (unsigned)(a64_cond[condition] ^ 1) << 12); return; } /* cset x0 */
  CODE(0x0f); byte(ctx, x86_setcc[condition]); CODE(0xc0, 0x0f, 0xb6, 0xc0);
}
static void isa_trap(BackendContext *ctx) {
  if (ctx->a64) { a64_word(ctx, 0xd4200000); return; } /* brk #0 */
  CODE(0x0f, 0x0b);
}
/* Relocated references. x86-64 uses RIP-relative forms; AArch64 uses adrp pairs. */
static void isa_call_symbol(BackendContext *ctx, unsigned symbol) {
  if (ctx->a64) { relocate(ctx, symbol, R_AARCH64_CALL26, 0); a64_word(ctx, 0x94000000); return; }
  byte(ctx, 0xe8); relocate(ctx, symbol, R_X86_64_PLT32, -4); word(ctx, 0);
}
/* reg <- address of .rodata + offset. */
static void isa_rodata_address(BackendContext *ctx, Reg r, size_t offset) {
  if (ctx->a64) {
    relocate(ctx, 1, R_AARCH64_ADR_PREL_PG_HI21, (int64_t)offset); a64_word(ctx, 0x90000000 | a64_reg[r]);
    relocate(ctx, 1, R_AARCH64_ADD_ABS_LO12_NC, (int64_t)offset); a64_word(ctx, 0x91000000 | a64_reg[r] << 5 | a64_reg[r]);
    return;
  }
  byte(ctx, x86_extended[r] ? 0x4c : 0x48); byte(ctx, 0x8d); byte(ctx, 0x05 | x86_code[r] << 3);
  relocate(ctx, 1, R_X86_64_PC32, (int64_t)offset - 4); word(ctx, 0);
}
/* reg <- address of a symbol through the GOT, so interposed definitions win. */
static void isa_symbol_address(BackendContext *ctx, Reg r, unsigned symbol) {
  if (ctx->a64) {
    relocate(ctx, symbol, R_AARCH64_ADR_GOT_PAGE, 0); a64_word(ctx, 0x90000000 | a64_reg[r]);
    relocate(ctx, symbol, R_AARCH64_LD64_GOT_LO12_NC, 0); a64_word(ctx, 0xf9400000 | a64_reg[r] << 5 | a64_reg[r]);
    return;
  }
  byte(ctx, x86_extended[r] ? 0x4c : 0x48); byte(ctx, 0x8b); byte(ctx, 0x05 | x86_code[r] << 3);
  relocate(ctx, symbol, R_X86_64_GOTPCREL, -4); word(ctx, 0);
}
/* Panic message arguments: pointer and length in the first two argument registers. */
static void isa_string_arguments(BackendContext *ctx, size_t offset, size_t length) {
  if (ctx->a64) { isa_rodata_address(ctx, R_A, offset); a64_immediate(ctx, 1, length); return; }
  CODE(0x48, 0x8d, 0x3d); /* lea rdi, [rip + string] */
  relocate(ctx, 1, R_X86_64_PC32, (int64_t)offset - 4); word(ctx, 0);
  byte(ctx, 0xbe); word(ctx, (uint32_t)length); /* mov esi, length */
}
/* Restore SP to the fixed frame, discarding pushed temporaries. */
static void isa_reset_stack(BackendContext *ctx) {
  if (ctx->a64) {
    a64_immediate(ctx, A64_SCRATCH, ctx->frame_bytes);
    a64_word(ctx, 0xcb3063bf | A64_SCRATCH << 16); /* sub sp, x29, x16 */
    return;
  }
  CODE(0x48, 0x8d, 0xa5); word(ctx, 0u - ctx->frame_bytes); /* lea rsp, [rbp - frame] */
}
/* Sign- or zero-extend A from a narrow integer width (bool keeps bit zero). */
static void isa_extend(BackendContext *ctx, unsigned bits, bool sign) {
  if (ctx->a64) {
    if (bits == 1) a64_word(ctx, 0x92400000);
    else if (bits == 8) a64_word(ctx, sign ? 0x93401c00 : 0x53001c00);
    else if (bits == 16) a64_word(ctx, sign ? 0x93403c00 : 0x53003c00);
    else if (bits == 32) a64_word(ctx, sign ? 0x93407c00 : 0x2a0003e0);
    return;
  }
  if (bits == 1) CODE(0x48,0x83,0xe0,1);
  else if (bits == 8) { if (sign) CODE(0x48,0x0f,0xbe,0xc0); else CODE(0x0f,0xb6,0xc0); }
  else if (bits == 16) { if (sign) CODE(0x48,0x0f,0xbf,0xc0); else CODE(0x0f,0xb7,0xc0); }
  else if (bits == 32) { if (sign) CODE(0x48,0x63,0xc0); else CODE(0x89,0xc0); }
}
/* A <- [A], extended from bits. */
static void isa_load_value(BackendContext *ctx, unsigned bits, bool sign) {
  if (ctx->a64) {
    if (bits == 1 || bits == 8) a64_word(ctx, sign ? 0x39800000 : 0x39400000);
    else if (bits == 16) a64_word(ctx, sign ? 0x79800000 : 0x79400000);
    else if (bits == 32) a64_word(ctx, sign ? 0xb9800000 : 0xb9400000);
    else a64_word(ctx, 0xf9400000);
    return;
  }
  if (bits==1 || bits==8) { if (sign) CODE(0x48,0x0f,0xbe,0x00); else CODE(0x0f,0xb6,0x00); }
  else if (bits==16) { if (sign) CODE(0x48,0x0f,0xbf,0x00); else CODE(0x0f,0xb7,0x00); }
  else if (bits==32) { if (sign) CODE(0x48,0x63,0x00); else CODE(0x8b,0x00); }
  else CODE(0x48,0x8b,0x00);
}
/* [R11] <- low bits of A. */
static void isa_store_value(BackendContext *ctx, unsigned bits) {
  if (ctx->a64) {
    unsigned base = bits <= 8 ? 0x39000000 : bits == 16 ? 0x79000000 : bits == 32 ? 0xb9000000 : 0xf9000000;
    a64_word(ctx, base | a64_reg[R_11] << 5 | a64_reg[R_A]);
    return;
  }
  if (bits==1 || bits==8) CODE(0x41,0x88,0x03);
  else if (bits==16) CODE(0x66,0x41,0x89,0x03);
  else if (bits==32) CODE(0x41,0x89,0x03);
  else CODE(0x49,0x89,0x03);
}
/* R10 <- exactly `size` bytes at [R11 + offset], zero-extended. Never reads past
   the object, even when it ends at a page boundary. */
static void isa_load_chunk(BackendContext *ctx, unsigned offset, unsigned size) {
  if (ctx->a64) {
    unsigned base = a64_reg[R_11];
    if (offset) { a64_immediate(ctx, A64_SCRATCH, offset); a64_word(ctx, 0x8b000000 | A64_SCRATCH << 16 | base << 5 | A64_SCRATCH); base = A64_SCRATCH; }
    if (size == 8) { a64_word(ctx, 0xf9400000 | base << 5 | a64_reg[R_10]); return; }
    a64_immediate(ctx, a64_reg[R_10], 0);
    for (unsigned i = 0; i < size; ++i) {
      a64_word(ctx, 0x39400000 | i << 10 | base << 5 | A64_SCRATCH2); /* ldrb w17, [base, #i] */
      a64_word(ctx, 0xaa000000 | A64_SCRATCH2 << 16 | (i * 8) << 10 | a64_reg[R_10] << 5 | a64_reg[R_10]); /* orr x11, x11, x17, lsl #8i */
    }
    return;
  }
  if (size==8) { CODE(0x4d,0x8b,0x93); word(ctx, offset); return; }
  CODE(0x45,0x31,0xd2);
  for (unsigned i=0;i<size;++i) {
    CODE(0x4d,0x0f,0xb6,0x83); word(ctx, offset+i);
    if (i) { CODE(0x49,0xc1,0xe0); byte(ctx, i*8); }
    CODE(0x4d,0x09,0xc2);
  }
}
/* Flags from A & mask, for alignment tests. mask is 2^k - 1. */
static void isa_test_mask(BackendContext *ctx, uint32_t mask) {
  if (ctx->a64) {
    unsigned ones = 0; while (mask >> ones & 1) ++ones;
    a64_word(ctx, 0xf240001f | (ones - 1) << 10 | a64_reg[R_A] << 5); /* tst x0, #mask */
    return;
  }
  CODE(0x48,0xa9); word(ctx, mask);
}
/* Flags from reg compared with a small signed immediate. */
static void isa_compare_small(BackendContext *ctx, Reg r, int value) {
  if (ctx->a64) {
    if (value < 0) a64_word(ctx, 0xb100001f | (unsigned)(-value) << 10 | a64_reg[r] << 5); /* cmn */
    else a64_word(ctx, 0xf100001f | (unsigned)value << 10 | a64_reg[r] << 5);
    return;
  }
  byte(ctx, x86_extended[r] ? 0x49 : 0x48); byte(ctx, 0x83); byte(ctx, 0xf8 | x86_code[r]); byte(ctx, (unsigned)value & 0xff);
}
/* A <- A / C or A % C; the caller has already checked the divisor. */
static void isa_divide(BackendContext *ctx, bool sign, bool remainder) {
  if (ctx->a64) {
    a64_word(ctx, (sign ? 0x9ac00c00 : 0x9ac00800) | a64_reg[R_C] << 16 | a64_reg[R_A] << 5 | A64_SCRATCH);
    if (remainder) a64_word(ctx, 0x9b008000 | a64_reg[R_C] << 16 | a64_reg[R_A] << 10 | A64_SCRATCH << 5 | a64_reg[R_A]);
    else a64_word(ctx, 0xaa0003e0 | A64_SCRATCH << 16 | a64_reg[R_A]);
    return;
  }
  if (sign) CODE(0x48, 0x99, 0x48, 0xf7, 0xf9); /* cqo; idiv rcx */
  else CODE(0x31, 0xd2, 0x48, 0xf7, 0xf1); /* xor edx, edx; div rcx */
  if (remainder) CODE(0x48, 0x89, 0xd0); /* mov rax, rdx */
}
enum { SHIFT_LEFT, SHIFT_RIGHT, SHIFT_ARITHMETIC };
/* reg <- reg shifted by C (count already checked below the width). */
static void isa_shift(BackendContext *ctx, Reg r, int kind) {
  if (ctx->a64) {
    unsigned op = kind == SHIFT_LEFT ? 0x9ac02000 : kind == SHIFT_RIGHT ? 0x9ac02400 : 0x9ac02800;
    a64_word(ctx, op | a64_reg[R_C] << 16 | a64_reg[r] << 5 | a64_reg[r]);
    return;
  }
  byte(ctx, x86_extended[r] ? 0x49 : 0x48); byte(ctx, 0xd3);
  byte(ctx, (kind == SHIFT_LEFT ? 0xe0 : kind == SHIFT_RIGHT ? 0xe8 : 0xf8) | x86_code[r]);
}
enum { ALU_ADD, ALU_SUB, ALU_AND, ALU_OR, ALU_XOR };
/* to <- to op from. Addition and subtraction set overflow and carry flags. */
static void isa_alu(BackendContext *ctx, int op, Reg to, Reg from) {
  if (ctx->a64) {
    static const uint32_t a64_ops[] = {0xab000000, 0xeb000000, 0x8a000000, 0xaa000000, 0xca000000};
    a64_word(ctx, a64_ops[op] | a64_reg[from] << 16 | a64_reg[to] << 5 | a64_reg[to]);
    return;
  }
  static const unsigned char x86_ops[] = {0x01, 0x29, 0x21, 0x09, 0x31};
  byte(ctx, 0x48 | x86_extended[from] << 2 | x86_extended[to]); byte(ctx, x86_ops[op]);
  byte(ctx, 0xc0 | x86_code[from] << 3 | x86_code[to]);
}
/* A <- A + unsigned 32-bit immediate (address offsets). */
static void isa_add_immediate(BackendContext *ctx, uint32_t n) {
  if (ctx->a64) {
    if (n < 4096) { a64_word(ctx, 0x91000000 | n << 10 | a64_reg[R_A] << 5 | a64_reg[R_A]); return; }
    a64_immediate(ctx, A64_SCRATCH, n);
    a64_word(ctx, 0x8b000000 | A64_SCRATCH << 16 | a64_reg[R_A] << 5 | a64_reg[R_A]);
    return;
  }
  CODE(0x48,0x05); word(ctx, n);
}
/* reg <- reg * unsigned 32-bit immediate (element scaling; cannot overflow after bounds checks). */
static void isa_scale(BackendContext *ctx, Reg r, uint32_t n) {
  if (ctx->a64) {
    a64_immediate(ctx, A64_SCRATCH, n);
    a64_word(ctx, 0x9b007c00 | A64_SCRATCH << 16 | a64_reg[r] << 5 | a64_reg[r]);
    return;
  }
  byte(ctx, x86_extended[r] ? 0x4d : 0x48); byte(ctx, 0x69); byte(ctx, 0xc0 | x86_code[r] << 3 | x86_code[r]); word(ctx, n);
}
/* Calls need a 16-byte aligned stack. x86-64 pushes are 8 bytes, so an odd
   push count needs one padding slot; AArch64 pushes keep alignment. */
static bool isa_align_call(BackendContext *ctx) {
  if (ctx->a64 || !(ctx->stack_slots & 1)) return false;
  CODE(0x48,0x83,0xec,8);
  return true;
}
static void isa_unalign_call(BackendContext *ctx, bool padded) {
  if (padded) CODE(0x48,0x83,0xc4,8);
}
/* The nth integer argument register (n < 2), for runtime calls. */
static Reg isa_argument(BackendContext *ctx, unsigned n) {
  return ctx->a64 ? (n ? R_D : R_A) : (n ? R_SI : R_DI);
}
/* Flags from the 32-bit integer result in A. */
static void isa_test32(BackendContext *ctx) {
  if (ctx->a64) { a64_word(ctx, 0x7100001f); return; } /* cmp w0, #0 */
  CODE(0x85,0xc0);
}
/* Bytes per pushed expression-stack slot. */
static unsigned isa_slot(BackendContext *ctx) { return ctx->a64 ? 16 : 8; }
/* A <- small unsigned immediate (x86-64 uses the 32-bit form). */
static void isa_small_immediate(BackendContext *ctx, Reg r, uint32_t n) {
  if (ctx->a64) { a64_immediate(ctx, a64_reg[r], n); return; }
  byte(ctx, 0xb8 + x86_code[r]); word(ctx, n);
}
/* Argument register `cls` (GP index, or 8 + FP index) <- stack slot at byte offset. */
static void isa_argument_load(BackendContext *ctx, int cls, uint32_t offset) {
  if (ctx->a64) {
    if (cls >= 8) { a64_word(ctx, 0xfd400000 | (offset / 8) << 10 | A64_SP << 5 | (unsigned)(cls - 8)); return; }
    a64_sp_offset(ctx, A64_LDR, (unsigned)cls, offset);
    return;
  }
  static const unsigned char registers[] = {0xbc, 0xb4, 0x94, 0x8c, 0x84, 0x8c};
  if (cls >= 8) { CODE(0xf3,0x0f,0x7e); byte(ctx, 0x84+8*(unsigned)(cls-8)); byte(ctx, 0x24); }
  else { byte(ctx, cls<4?0x48:0x4c); byte(ctx, 0x8b); byte(ctx, registers[cls]); byte(ctx, 0x24); }
  word(ctx, offset);
}
/* Reserve bytes below SP for outgoing stack arguments (a multiple of 16 on AArch64). */
static void isa_reserve(BackendContext *ctx, uint32_t bytes) {
  if (!bytes) return;
  if (ctx->a64) { a64_sp_adjust(ctx, -(int64_t)bytes); return; }
  CODE(0x48,0x81,0xec); word(ctx, bytes);
}
static void isa_release(BackendContext *ctx, uint32_t bytes) {
  if (!bytes) return;
  if (ctx->a64) { a64_sp_adjust(ctx, bytes); return; }
  CODE(0x48, 0x81, 0xc4); word(ctx, bytes);
}
/* [SP + to] <- [SP + from], 64-bit, through A. */
static void isa_stack_copy(BackendContext *ctx, uint32_t from, uint32_t to) {
  if (ctx->a64) { a64_sp_offset(ctx, A64_LDR, A64_SCRATCH, from); a64_sp_offset(ctx, A64_STR, A64_SCRATCH, to); return; }
  CODE(0x48,0x8b,0x84,0x24); word(ctx, from);
  CODE(0x48,0x89,0x84,0x24); word(ctx, to);
}
/* Hidden result pointer argument: RDI on x86-64, X8 on AArch64. */
static void isa_result_pointer(BackendContext *ctx, uint32_t offset) {
  if (ctx->a64) { a64_frame_address(ctx, 8, (int32_t)offset); return; }
  CODE(0x48,0x8d,0xbd); word(ctx, offset);
}
/* Call the address stored at [SP + offset]. */
static void isa_call_stack(BackendContext *ctx, uint32_t offset) {
  if (ctx->a64) { a64_sp_offset(ctx, A64_LDR, A64_SCRATCH, offset); a64_word(ctx, 0xd63f0000 | A64_SCRATCH << 5); return; }
  CODE(0x4c,0x8b,0x9c,0x24); word(ctx, offset);
  CODE(0x41,0xff,0xd3); /* call r11 */
}
/* First floating argument/result register <- raw bits in A. */
static void isa_a_to_float(BackendContext *ctx) {
  if (ctx->a64) { a64_word(ctx, 0x9e670000); return; } /* fmov d0, x0 */
  CODE(0x66,0x48,0x0f,0x6e,0xc0);
}
/* Flags from A compared with the top of the expression stack. */
static void isa_compare_top(BackendContext *ctx) {
  if (ctx->a64) { a64_word(ctx, 0xf94003f0); a64_word(ctx, 0xeb10001f); return; } /* ldr x16, [sp]; cmp x0, x16 */
  CODE(0x48,0x3b,0x04,0x24);
}
/* D <- [A + 8]; A <- [A]: load a two-word descriptor. */
static void isa_load_descriptor(BackendContext *ctx) {
  if (ctx->a64) { a64_word(ctx, 0xa9400400); return; } /* ldp x0, x1, [x0] */
  CODE(0x48,0x8b,0x50,8,0x48,0x8b,0x00);
}
/* [R11] <- A, [R11 + 8] <- D. */
static void isa_store_descriptor(BackendContext *ctx) {
  if (ctx->a64) { a64_word(ctx, 0xa9000400 | a64_reg[R_11] << 5); return; } /* stp x0, x1, [x12] */
  CODE(0x49,0x89,0x03,0x49,0x89,0x53,8);
}
/* dyn_syscall6(a, b, c, d, e, f, number): seven pushed values, first pushed first. */
static void isa_syscall(BackendContext *ctx) {
  if (ctx->a64) {
    for (unsigned i = 0; i < 7; ++i) a64_sp_offset(ctx, A64_LDR, i, 16 * (6 - i));
    runtime_call(ctx, 9); isa_drop(ctx, 7);
    return;
  }
  const unsigned char regs[]={0xbc,0xb4,0x94,0x8c,0x84,0x8c};
  for (unsigned i=0;i<6;++i) { byte(ctx,i<4?0x48:0x4c); CODE(0x8b); byte(ctx,regs[i]); byte(ctx,0x24); word(ctx,8*(6-i)); }
  unsigned reserved=(1+((ctx->stack_slots+1)&1))*8;
  CODE(0x48,0x8b,0x04,0x24,0x48,0x81,0xec); word(ctx,reserved); CODE(0x48,0x89,0x04,0x24);
  runtime_call(ctx,9); CODE(0x48,0x81,0xc4); word(ctx,reserved+56); ctx->stack_slots-=7;
}
/* Enum cast validation: R8 accumulates whether A equals any declared tag. */
static void isa_match_begin(BackendContext *ctx) {
  if (ctx->a64) { a64_immediate(ctx, a64_reg[R_8], 0); return; }
  CODE(0x45,0x31,0xc0);
}
static void isa_match_tag(BackendContext *ctx, uint64_t tag) {
  isa_immediate(ctx, R_C, tag);
  if (ctx->a64) {
    a64_word(ctx, 0xeb00001f | a64_reg[R_C] << 16 | a64_reg[R_A] << 5); /* cmp x0, x9 */
    a64_word(ctx, 0x9a9f17e0 | A64_SCRATCH); /* cset x16, eq */
    a64_word(ctx, 0xaa000000 | A64_SCRATCH << 16 | a64_reg[R_8] << 5 | a64_reg[R_8]);
    return;
  }
  CODE(0x48,0x39,0xc8,0x0f,0x94,0xc1,0x41,0x08,0xc8);
}
static void isa_match_test(BackendContext *ctx) {
  if (ctx->a64) { a64_word(ctx, 0xf100001f | a64_reg[R_8] << 5); return; }
  CODE(0x45,0x84,0xc0);
}
/* Integer bits in A -> floating bits in A (f32 bits zero-extended). */
static void isa_int_to_float(BackendContext *ctx, bool f32, bool unsigned64) {
  if (ctx->a64) {
    a64_word(ctx, (f32 ? 0x9e220000 : 0x9e620000) | (unsigned64 ? 0x10000 : 0)); /* scvtf/ucvtf */
    a64_word(ctx, f32 ? 0x1e260000 : 0x9e660000); /* fmov w0, s0 / x0, d0 */
    return;
  }
  unsigned prefix=f32?0xf3:0xf2;
  CODE(0x0f,0x57,0xc0); /* clear upper carrier bits for scalar f32 conversion */
  if (unsigned64) {
    CODE(0x48,0x85,0xc0,0x0f,0x89); size_t ordinary=ctx->text.n; word(ctx, 0);
    /* Sticky low bit preserves exact rounding when halving an unsigned i64. */
    CODE(0x48,0x89,0xc1,0x83,0xe1,1,0x48,0xd1,0xe8,0x48,0x09,0xc8);
    byte(ctx, prefix); CODE(0x48,0x0f,0x2a,0xc0);
    byte(ctx, prefix); CODE(0x0f,0x58,0xc0,0xe9); size_t done=ctx->text.n; word(ctx, 0);
    patch_word(ctx, ordinary,(uint32_t)(ctx->text.n-ordinary-4));
    byte(ctx, prefix); CODE(0x48,0x0f,0x2a,0xc0);
    patch_word(ctx, done,(uint32_t)(ctx->text.n-done-4));
  } else { byte(ctx, prefix); CODE(0x48,0x0f,0x2a,0xc0); }
  CODE(0x66,0x48,0x0f,0x7e,0xc0);
}
/* Floating bits in A -> integer in A, truncating toward zero. */
static void isa_float_to_int(BackendContext *ctx, bool f32, bool unsigned64) {
  if (ctx->a64) {
    a64_word(ctx, f32 ? 0x1e270000 : 0x9e670000); /* fmov s0, w0 / d0, x0 */
    a64_word(ctx, (f32 ? 0x9e380000 : 0x9e780000) | (unsigned64 ? 0x10000 : 0)); /* fcvtzs/fcvtzu x0 */
    return;
  }
  unsigned prefix=f32?0xf3:0xf2;
  CODE(0x66,0x48,0x0f,0x6e,0xc0);
  if (unsigned64) {
    CODE(0x48,0xb9); immediate(ctx, f32?UINT64_C(0x5f000000):UINT64_C(0x43e0000000000000));
    CODE(0x66,0x48,0x0f,0x6e,0xc9);
    if (!f32) byte(ctx, 0x66);
    CODE(0x0f,0x2e,0xc1,0x0f,0x82); size_t ordinary=ctx->text.n; word(ctx, 0);
    byte(ctx, prefix); CODE(0x0f,0x5c,0xc1);
    byte(ctx, prefix); CODE(0x48,0x0f,0x2c,0xc0);
    CODE(0x48,0xb9); immediate(ctx, UINT64_C(1)<<63); CODE(0x48,0x31,0xc8,0xe9); size_t done=ctx->text.n; word(ctx, 0);
    patch_word(ctx, ordinary,(uint32_t)(ctx->text.n-ordinary-4));
    byte(ctx, prefix); CODE(0x48,0x0f,0x2c,0xc0);
    patch_word(ctx, done,(uint32_t)(ctx->text.n-done-4));
  } else { byte(ctx, prefix); CODE(0x48,0x0f,0x2c,0xc0); }
}
/* f32 <-> f64 conversion of the floating bits in A. */
static void isa_float_convert(BackendContext *ctx, bool from32) {
  if (ctx->a64) {
    if (from32) { a64_word(ctx, 0x1e270000); a64_word(ctx, 0x1e22c000); a64_word(ctx, 0x9e660000); }
    else { a64_word(ctx, 0x9e670000); a64_word(ctx, 0x1e624000); a64_word(ctx, 0x1e260000); }
    return;
  }
  CODE(0x66,0x48,0x0f,0x6e,0xc0); byte(ctx, from32?0xf3:0xf2);
  CODE(0x0f,0x5a,0xc0,0x66,0x48,0x0f,0x7e,0xc0);
}
enum { UNARY_NOT, UNARY_NEGATE, UNARY_BOOL_NOT };
/* A <- ~A, -A (setting overflow/borrow flags), or A ^ 1. */
static void isa_unary(BackendContext *ctx, int op) {
  if (ctx->a64) {
    a64_word(ctx, op == UNARY_NOT ? 0xaa2003e0 : op == UNARY_NEGATE ? 0xeb0003e0 : 0xd2400000);
    return;
  }
  if (op == UNARY_NOT) CODE(0x48, 0xf7, 0xd0);
  else if (op == UNARY_NEGATE) CODE(0x48, 0xf7, 0xd8);
  else CODE(0x48, 0x83, 0xf0, 1);
}
/* Floating operands: left bits in A, right bits in C, moved to the first two FP registers. */
static void isa_float_operands(BackendContext *ctx, bool f32) {
  if (ctx->a64) {
    a64_word(ctx, (f32 ? 0x1e270000 : 0x9e670000) | a64_reg[R_A] << 5);
    a64_word(ctx, (f32 ? 0x1e270000 : 0x9e670000) | a64_reg[R_C] << 5 | 1);
    return;
  }
  CODE(0x66,0x48,0x0f,0x6e,0xc0,0x66,0x48,0x0f,0x6e,0xc9); /* xmm0=left,xmm1=right */
}
/* A <- floating result bits from the first FP register. */
static void isa_float_result(BackendContext *ctx, bool f32) {
  if (ctx->a64) { a64_word(ctx, f32 ? 0x1e260000 : 0x9e660000); return; }
  CODE(0x66,0x48,0x0f,0x7e,0xc0);
}
/* A <- 0/1 for an IEEE comparison; any NaN is unordered (only != holds). */
static void isa_float_compare(BackendContext *ctx, bool f32, unsigned op) {
  if (ctx->a64) {
    static const unsigned char conditions[] = {0, 1, 4, 9, 12, 10}; /* eq ne mi ls gt ge */
    a64_word(ctx, (f32 ? 0x1e202000 : 0x1e602000) | 1 << 16);
    a64_word(ctx, 0x9a9f07e0 | (unsigned)(conditions[op] ^ 1) << 12);
    return;
  }
  if (!f32) byte(ctx, 0x66);
  CODE(0x0f,0x2e,0xc1); /* unordered compare sets parity for NaN */
  const unsigned char predicates[]={0x94,0x95,0x92,0x96,0x97,0x93};
  byte(ctx, 0x0f); byte(ctx, predicates[op]); byte(ctx, 0xc0);
  CODE(0x0f); byte(ctx, op==1?0x9a:0x9b); byte(ctx, 0xc2);
  byte(ctx, op==1?0x08:0x20); byte(ctx, 0xd0); CODE(0x0f,0xb6,0xc0);
}
enum { FLOAT_ADD, FLOAT_SUB, FLOAT_MUL, FLOAT_DIV };
static void isa_float_arithmetic(BackendContext *ctx, bool f32, int op) {
  if (ctx->a64) {
    static const uint32_t ops[] = {0x1e602800, 0x1e603800, 0x1e600800, 0x1e601800};
    a64_word(ctx, (ops[op] & ~(f32 ? 0x400000u : 0)) | 1 << 16);
    isa_float_result(ctx, f32);
    return;
  }
  static const unsigned char opcodes[] = {0x58, 0x5c, 0x59, 0x5e};
  byte(ctx, f32?0xf3:0xf2); byte(ctx, 0x0f); byte(ctx, opcodes[op]); byte(ctx, 0xc1);
  CODE(0x66,0x48,0x0f,0x7e,0xc0);
}
/* A <- A * C. Checked forms leave flags for isa_overflow_condition. */
static void isa_multiply(BackendContext *ctx, bool checked, bool sign) {
  if (ctx->a64) {
    if (checked) a64_word(ctx, (sign ? 0x9b407c00 : 0x9bc07c00) | a64_reg[R_C] << 16 | a64_reg[R_A] << 5 | A64_SCRATCH);
    a64_word(ctx, 0x9b007c00 | a64_reg[R_C] << 16 | a64_reg[R_A] << 5 | a64_reg[R_A]);
    if (checked && sign) a64_word(ctx, 0xeb80fc1f | a64_reg[R_A] << 16 | A64_SCRATCH << 5); /* cmp x16, x0, asr #63 */
    else if (checked) a64_word(ctx, 0xf100001f | A64_SCRATCH << 5); /* cmp x16, #0 */
    return;
  }
  if (checked && !sign) CODE(0x48, 0xf7, 0xe1); /* mul rcx: rdx:rax */
  else CODE(0x48, 0x0f, 0xaf, 0xc1); /* imul rax, rcx */
}
/* Success condition after a checked add, subtract or multiply. */
static Cond isa_overflow_condition(BackendContext *ctx, int op, bool sign) {
  if (op == ALU_ADD + 16) return ctx->a64 ? CC_E : sign ? CC_NO : CC_AE; /* multiply */
  if (sign) return CC_NO;
  return op == ALU_ADD ? CC_NO_CARRY : CC_AE; /* subtraction succeeds without a borrow */
}
/* [DI + offset] <- the low `bytes` bytes of R10, without touching later bytes. */
static void isa_store_chunk(BackendContext *ctx, unsigned offset, unsigned bytes) {
  if (ctx->a64) {
    unsigned base = a64_reg[R_DI];
    if (offset) { a64_immediate(ctx, A64_SCRATCH, offset); a64_word(ctx, 0x8b000000 | A64_SCRATCH << 16 | base << 5 | A64_SCRATCH); base = A64_SCRATCH; }
    if (bytes == 8) { a64_word(ctx, 0xf9000000 | base << 5 | a64_reg[R_10]); return; }
    for (unsigned j = 0; j < bytes; ++j) {
      a64_word(ctx, 0x39000000 | j << 10 | base << 5 | a64_reg[R_10]); /* strb w11, [base, #j] */
      if (j + 1 < bytes) a64_word(ctx, 0xd348fc00 | a64_reg[R_10] << 5 | a64_reg[R_10]); /* lsr x11, x11, #8 */
    }
    return;
  }
  if (bytes==8) { CODE(0x4c,0x89,0x97); word(ctx, offset); return; }
  for (unsigned j=0;j<bytes;++j) {
    CODE(0x44,0x88,0x97); word(ctx, offset+j);
    if (j+1<bytes) CODE(0x49,0xc1,0xea,8);
  }
}
/* Call dyn_trace_pop while preserving the A (and D) result registers. */
static void isa_trace_pop(BackendContext *ctx, bool descriptor_result) {
  if (ctx->a64) {
    a64_word(ctx, 0xa9bf07e0); /* stp x0, x1, [sp, #-16]! */
    runtime_call(ctx, 2);
    a64_word(ctx, 0xa8c107e0); /* ldp x0, x1, [sp], #16 */
    return;
  }
  CODE(0x48,0x89,0x45,0xf8);
  if (descriptor_result) CODE(0x48,0x89,0x55,0xf0);
  runtime_call(ctx, 2); CODE(0x48,0x8b,0x45,0xf8);
  if (descriptor_result) CODE(0x48,0x8b,0x55,0xf0);
}
/* Function epilogue: restore the caller frame and return. */
static void isa_return(BackendContext *ctx) {
  if (ctx->dwarf && !backend_dwarf_epilogue(ctx->dwarf,ctx->text.n)) ctx->text.failed=true;
  if (ctx->a64) {
    a64_word(ctx, 0x910003bf); /* mov sp, x29 */
    a64_word(ctx, 0xa8c17bfd); /* ldp x29, x30, [sp], #16 */
    a64_word(ctx, 0xd65f03c0); /* ret */
    return;
  }
  CODE(0xc9, 0xc3); /* leave; ret */
}
/* Function prologue with a frame of ctx->frame_bytes below FP. */
static void isa_enter(BackendContext *ctx) {
  if (ctx->a64) {
    a64_word(ctx, 0xa9bf7bfd); /* stp x29, x30, [sp, #-16]! */
    a64_word(ctx, 0x910003fd); /* mov x29, sp */
    a64_sp_adjust(ctx, -(int64_t)ctx->frame_bytes);
    return;
  }
  CODE(0x55, 0x48, 0x89, 0xe5, 0x48, 0x81, 0xec); word(ctx, ctx->frame_bytes);
}
/* [A, A + size) <- 0. */
static void isa_zero_fill(BackendContext *ctx, uint32_t size) {
  if (ctx->a64) {
    a64_immediate(ctx, A64_SCRATCH, size);
    a64_word(ctx, 0xaa0003f1); /* mov x17, x0 */
    a64_word(ctx, 0xb4000090); /* loop: cbz x16, done */
    a64_word(ctx, 0x3800163f); /* strb wzr, [x17], #1 */
    a64_word(ctx, 0xd1000610); /* sub x16, x16, #1 */
    a64_word(ctx, 0x17fffffd); /* b loop */
    return;
  }
  CODE(0x48,0x89,0xc7,0x31,0xc0,0xb9); word(ctx, size); CODE(0xfc,0xf3,0xaa);
}
/* Copy size bytes from A to the popped destination, preserving overlap like memmove. */
static void isa_copy(BackendContext *ctx, uint32_t size) {
  isa_move(ctx, R_SI, R_A); isa_pop(ctx, R_DI);
  if (ctx->a64) {
    unsigned s = a64_reg[R_SI], d = a64_reg[R_DI];
    a64_immediate(ctx, A64_SCRATCH, size);
    a64_word(ctx, 0xeb00001f | s << 16 | d << 5); /* cmp dst, src */
    a64_word(ctx, 0x540000c9); /* b.ls forward */
    a64_word(ctx, 0xb4000150); /* backward: cbz x16, done */
    a64_word(ctx, 0xd1000610); /* sub x16, x16, #1 */
    a64_word(ctx, 0x38706800 | s << 5 | A64_SCRATCH2); /* ldrb w17, [src, x16] */
    a64_word(ctx, 0x38306800 | d << 5 | A64_SCRATCH2); /* strb w17, [dst, x16] */
    a64_word(ctx, 0x17fffffc); /* b backward */
    a64_word(ctx, 0xb40000b0); /* forward: cbz x16, done */
    a64_word(ctx, 0x38401400 | s << 5 | A64_SCRATCH2); /* ldrb w17, [src], #1 */
    a64_word(ctx, 0x38001400 | d << 5 | A64_SCRATCH2); /* strb w17, [dst], #1 */
    a64_word(ctx, 0xd1000610); /* sub x16, x16, #1 */
    a64_word(ctx, 0x17fffffc); /* b forward */
    return;
  }
  CODE(0xb9); word(ctx, size);
  CODE(0x48,0x39,0xf7,0x0f,0x86); size_t forward=ctx->text.n; word(ctx, 0);
  if (size) { CODE(0x48,0x81,0xc6); word(ctx, size-1); CODE(0x48,0x81,0xc7); word(ctx, size-1); }
  CODE(0xfd,0xf3,0xa4,0xfc,0xe9); size_t done=ctx->text.n; word(ctx, 0);
  patch_word(ctx, forward,(uint32_t)(ctx->text.n-forward-4)); CODE(0xfc,0xf3,0xa4);
  patch_word(ctx, done,(uint32_t)(ctx->text.n-done-4));
}
/* A <- A + delta (delta is 1 or -1); loop counters never overflow here. */
static void isa_step(BackendContext *ctx, int delta) {
  if (ctx->a64) { a64_word(ctx, (delta > 0 ? 0x91000400 : 0xd1000400)); return; }
  CODE(0x48,0xff); byte(ctx, delta > 0 ? 0xc0 : 0xc8);
}
/* A <- A + [FP + offset]. */
static void isa_add_frame(BackendContext *ctx, uint32_t offset) {
  if (ctx->a64) { a64_frame_raw(ctx, A64_LDR, A64_SCRATCH, offset); a64_word(ctx, 0x8b100000); return; }
  CODE(0x48,0x03,0x85); word(ctx, offset);
}
/* Save the hidden result pointer register on entry. */
static void isa_store_result_pointer(BackendContext *ctx, uint32_t offset) {
  if (ctx->a64) { a64_frame_raw(ctx, A64_STR, 8, offset); return; }
  CODE(0x48,0x89,0xbd); word(ctx, offset);
}
/* [FP + offset] <- incoming argument register cls (GP index or 8 + FP index). */
static void isa_store_argument(BackendContext *ctx, int cls, uint32_t offset) {
  if (ctx->a64) {
    if (cls >= 8) { a64_word(ctx, 0x9e660000 | (unsigned)(cls - 8) << 5 | A64_SCRATCH); a64_frame_raw(ctx, A64_STR, A64_SCRATCH, offset); }
    else a64_frame_raw(ctx, A64_STR, (unsigned)cls, offset);
    return;
  }
  static const unsigned char regs[] = {0xbd,0xb5,0x95,0x8d,0x85,0x8d};
  if (cls>=8) { CODE(0x66,0x48,0x0f,0x7e); byte(ctx, 0xc0+8*(unsigned)(cls-8)); CODE(0x48,0x89,0x85); }
  else { byte(ctx, cls<4?0x48:0x4c); byte(ctx, 0x89); byte(ctx, regs[cls]); }
  word(ctx, offset);
}
/* A <- incoming argument register cls. */
static void isa_argument_to_a(BackendContext *ctx, int cls) {
  if (ctx->a64) {
    if (cls >= 8) a64_word(ctx, 0x9e660000 | (unsigned)(cls - 8) << 5);
    else a64_word(ctx, 0xaa0003e0 | (unsigned)cls << 16);
    return;
  }
  static const unsigned char gp_to_rax[]={0xf8,0xf0,0xd0,0xc8,0xc0,0xc8};
  if (cls>=8) { CODE(0x66,0x48,0x0f,0x7e);byte(ctx, 0xc0+8*(unsigned)(cls-8)); }
  else { byte(ctx, cls<4?0x48:0x4c);byte(ctx, 0x89);byte(ctx, gp_to_rax[cls]); }
}
/* Run-once flag at [A]: branch (returned slot) when already set, else set it. */
static size_t isa_once(BackendContext *ctx) {
  if (ctx->a64) {
    a64_word(ctx, 0x39400010); /* ldrb w16, [x0] */
    a64_word(ctx, 0x7100021f); /* cmp w16, #0 */
    size_t done = a64_branch(ctx, CC_NE);
    a64_word(ctx, 0x52800030); /* mov w16, #1 */
    a64_word(ctx, 0x39000010); /* strb w16, [x0] */
    return done;
  }
  CODE(0x80,0x38,0,0x0f,0x85); size_t done=ctx->text.n; word(ctx,0); CODE(0xc6,0x00,1);
  return done;
}
