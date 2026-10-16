/* AArch64 encodings for isa.inc (included by driver.c).

   Model registers map to x0 (A), x9 (C), x1 (D), x14 (SI), x15 (DI), x10 (R8),
   x11 (R10) and x12 (R11). A and D are also the first two AAPCS64 return
   registers, as RAX/RDX are on x86-64. x16/x17 are encoding scratch only.
   x29 is the frame pointer; every push is 16 bytes, so SP stays aligned. */

typedef enum { R_A, R_C, R_D, R_SI, R_DI, R_8, R_10, R_11 } Reg;
/* Branch conditions after a compare (or test against zero). */
typedef enum { CC_E, CC_NE, CC_B, CC_AE, CC_BE, CC_A, CC_L, CC_GE, CC_LE, CC_G,
               CC_NO, /* no signed overflow */
               CC_NO_CARRY /* addition without unsigned carry */ } Cond;

static const unsigned char a64_reg[] = {0, 9, 1, 14, 15, 10, 11, 12};
static const unsigned char a64_cond[] = {0, 1, 3, 2, 9, 8, 11, 10, 13, 12, 7, 3};
enum { A64_LDR, A64_STR, A64_ADD };
enum { A64_SCRATCH = 16, A64_SCRATCH2 = 17, A64_FP = 29, A64_LR = 30, A64_SP = 31 };

static void a64_word(BackendContext *ctx, uint32_t instruction) { word(ctx, instruction); }
static void a64_immediate(BackendContext *ctx, unsigned rd, uint64_t n) {
  bool first = true;
  for (unsigned shift = 0; shift < 64; shift += 16) {
    uint32_t part = (uint32_t)(n >> shift) & 0xffff;
    if (!part && !(first && shift == 48)) continue;
    /* movz for the first emitted chunk, movk afterwards. */
    a64_word(ctx, (first ? 0xd2800000u : 0xf2800000u) | (shift / 16) << 21 | part << 5 | rd);
    first = false;
  }
}
/* rd <- x29 + signed offset (frame offsets are stored as uint32 two's complement). */
static void a64_frame_address(BackendContext *ctx, unsigned rd, int64_t offset) {
  if (offset >= 0 && offset < 4096) { a64_word(ctx, 0x910003a0u | (uint32_t)offset << 10 | rd); return; }
  if (offset < 0 && -offset < 4096) { a64_word(ctx, 0xd10003a0u | (uint32_t)(-offset) << 10 | rd); return; }
  a64_immediate(ctx, A64_SCRATCH, (uint64_t)offset);
  a64_word(ctx, 0x8b1003a0u | rd); /* add rd, x29, x16 */
}
static void a64_frame_raw(BackendContext *ctx, int kind, unsigned rt, uint32_t raw);
static void a64_frame(BackendContext *ctx, int kind, Reg r, uint32_t raw) { a64_frame_raw(ctx, kind, a64_reg[r], raw); }
/* LDR/STR/ADD of a raw register number relative to the frame pointer. */
static void a64_frame_raw(BackendContext *ctx, int kind, unsigned rt, uint32_t raw) {
  int64_t offset = (int32_t)raw;
  if (kind == A64_ADD) { a64_frame_address(ctx, rt, offset); return; }
  if (offset >= -256 && offset < 256) {
    a64_word(ctx, (kind == A64_LDR ? 0xf8400000u : 0xf8000000u) | ((uint32_t)offset & 0x1ff) << 12 | A64_FP << 5 | rt);
    return;
  }
  a64_immediate(ctx, A64_SCRATCH, (uint64_t)offset);
  a64_word(ctx, (kind == A64_LDR ? 0xf8606800u : 0xf8206800u) | A64_SCRATCH << 16 | A64_FP << 5 | rt);
}
static void a64_sp_offset(BackendContext *ctx, int kind, unsigned rt, uint32_t offset) {
  if (offset < 32768) {
    a64_word(ctx, (kind == A64_LDR ? 0xf9400000u : 0xf9000000u) | (offset / 8) << 10 | A64_SP << 5 | rt);
    return;
  }
  a64_immediate(ctx, A64_SCRATCH, offset);
  a64_word(ctx, (kind == A64_LDR ? 0xf8606800u : 0xf8206800u) | A64_SCRATCH << 16 | A64_SP << 5 | rt);
}
static void a64_sp_adjust(BackendContext *ctx, int64_t bytes) {
  if (bytes > 0 && bytes < 4096) { a64_word(ctx, 0x910003ffu | (uint32_t)bytes << 10); return; }
  if (bytes < 0 && -bytes < 4096) { a64_word(ctx, 0xd10003ffu | (uint32_t)(-bytes) << 10); return; }
  a64_immediate(ctx, A64_SCRATCH, (uint64_t)bytes);
  a64_word(ctx, 0x8b3063ffu | A64_SCRATCH << 16); /* add sp, sp, x16 */
}
/* Conditional branches invert over an unconditional b, keeping a +-128 MiB range. */
static size_t a64_branch(BackendContext *ctx, int condition) {
  if (condition >= 0) a64_word(ctx, 0x54000040u | (unsigned)(a64_cond[condition] ^ 1));
  size_t at = ctx->text.n;
  a64_word(ctx, 0);
  return at;
}
static void a64_patch(BackendContext *ctx, size_t at, size_t destination) {
  int64_t delta = ((int64_t)destination - (int64_t)at) / 4;
  if (delta >= (1 << 25) || delta < -(1 << 25)) { ctx->text.failed = true; return; }
  patch_word(ctx, at, 0x14000000u | ((uint32_t)delta & 0x3ffffff));
}
