/* Native x86-64 and AArch64 Linux ELF emitter for checked Dyn IR (debug builds). */
#include "frontend.h"
#include "ir.h"
#include "dyn_location.h"
#include "elf64.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "output.h"
#include "dwarf.h"

/* Per-section and per-object byte bound; buffers grow on demand up to it. */
#define LIMIT (1024u * 1024u * 1024u)
/* Fixed per-object capacities; exceeding one fails emission explicitly. */
#define MAX_SYMBOLS 32768
#define MAX_LOCALS 65536
#define MAX_SCRATCH (1u << 21) /* frame eightbytes: 16 MiB */
#define MAX_AGGREGATE (1u << 24)
#define MAX_LAYOUT (UINT32_MAX - 15u) /* Sparse heap layouts; frame limits remain separate. */
#define MAX_NODES (1u << 22)
/* Recursion bound for expressions, statements and types; matches the syntax depth limit. */
#define MAX_DEPTH 1024
#define MAX_DEFERS 4096
typedef struct { unsigned char *data; size_t n, capacity; bool failed; } Bytes;
/* Ensures capacity for total bytes; failure marks the buffer. */
static bool reserve(Bytes *b, size_t total) {
  if (total <= b->capacity) return true;
  if (b->failed || total > LIMIT) { b->failed = true; return false; }
  size_t capacity = b->capacity ? b->capacity : 65536;
  while (capacity < total) capacity = capacity > LIMIT / 2 ? LIMIT : capacity * 2;
  unsigned char *data = realloc(b->data, capacity);
  if (!data) { b->failed = true; return false; }
  b->data = data; b->capacity = capacity;
  return true;
}
static const char *const runtime_names[] = {"dyn_panic", "dyn_trace_push", "dyn_trace_pop", "dyn_unwind_set", "dyn_unwind_link", "dyn_unwind_unlink", "dyn_unwind_continue", "fmod", "fmodf", "dyn_syscall6", "__chkstk", "dyn_check_failed"};
#define RUNTIME_COUNT 12
enum { RUNTIME_CHKSTK = 10, RUNTIME_CHECK_FAILED = 11 };
/* Check kinds pass to dyn_check_failed by number; runtime/support/support.dyn
   and runtime/reference_support.c name them in this order. */
enum { GUARD_OVERFLOW, GUARD_DIVIDE, GUARD_DIVISION_OVERFLOW, GUARD_SHIFT, GUARD_FUNCTION, GUARD_NONNULL, GUARD_ALIGNED, GUARD_INDEX, GUARD_SLICE_ORDER, GUARD_SLICE_BOUNDS, GUARD_ENUM, GUARD_COUNT };
typedef struct { DynType type; uint32_t offset; } ArrayPart;
/* One register- or stack-passed piece of an argument. cls: GP index, 8 + FP
   index, or -1 for the next eight-byte stack slot. offset/size locate the
   bytes inside an aggregate; leaf is the scalar type of an array leaf. */
typedef struct { uint32_t offset, size; int cls; DynType leaf; uint32_t stack; } AbiPart;
typedef struct {
  Bytes text, rodata, globals_data, constants_data; /* globals_data tracks zero-fill size only. */
  BackendDwarf *dwarf;
  const DynSource *debug_source;
  const DynLocationIndex *debug_locations;
  Elf64_Rela *constant_relocations;
  size_t constant_relocation_count, constant_relocation_capacity;
  bool global_static[MAX_SYMBOLS];
  bool function_live[MAX_SYMBOLS];
  uint32_t constant_offsets[MAX_SYMBOLS];
  Elf64_Rela *relocations;
  size_t relocation_capacity;
  size_t relocation_count, runtime_base, runtime_count;
  unsigned function_symbols[MAX_SYMBOLS], global_symbols[MAX_SYMBOLS];
  unsigned symbol_remap[2 * MAX_SYMBOLS + 16];
  /* Production symbol policy: local bodies named like a foreign link name or exit/_exit get ".dyn". */
  bool function_suffixed[MAX_SYMBOLS];
  unsigned initializer_symbol, initializer_flag_symbol, first_global, dll_entry_symbol;
  bool shared;
  unsigned runtime_index[RUNTIME_COUNT], stack_slots, frame_bytes, local_words;
  uint32_t local_offsets[MAX_LOCALS];
  signed char allocator_registers[MAX_LOCALS];
  unsigned allocator_local_count, allocator_used;
  uint32_t allocator_save[4];
  bool local_alias[MAX_LOCALS];
  struct { uint32_t id; size_t condition, breaks, continues; unsigned defer_base; } loops[MAX_DEPTH];
  unsigned loop_depth;
  const DynIrProgram *active_ir;
  uint32_t defer_ids[MAX_DEFERS], defer_count, unwind_offset, return_offset, call_offset, sret_offset;
  uint32_t captured_offsets[MAX_NODES], statement_scratch[MAX_NODES], temporary_offsets[MAX_NODES];
  /* Struct and array literals whose every field is constant are laid out in
     the constants section once; literal_offsets holds offset + 1 from
     literals_symbol, or 0. */
  uint32_t literal_offsets[MAX_NODES];
  unsigned literals_symbol;
  /* Read-only byte strings already written, by content, so each is stored
     once. Entries past a rolled-back end of rodata are ignored. */
  struct StoredString { size_t offset, length; } *strings;
  size_t string_capacity, string_count;
  bool visited_expr[MAX_NODES];
  uint32_t pack_offsets[MAX_NODES];
  uint32_t copy_offsets[MAX_NODES]; /* AAPCS64 caller copies of large struct arguments */
  /* Ids written while sizing one function; reset touches only these, not the program. */
  uint32_t touched_exprs[2 * MAX_NODES], touched_stmts[MAX_NODES];
  size_t touched_expr_count, touched_stmt_count;
  bool unwinding;
  unsigned cleanup_depth;
  bool debug_mode, relocation_failed;
  bool report; /* false: the caller selects another backend silently */
  ArrayPart call_leaves[512];
  AbiPart call_parts[512];
  /* DWARF lexical scopes: [begin, end) text offsets per local; zero end means
     the variable is visible in the whole function. */
  size_t local_scope_begin[MAX_LOCALS], local_scope_end[MAX_LOCALS];
  uint32_t scope_stack[MAX_LOCALS];
  unsigned scope_count;
  bool vectorize, optimization_remarks;
  bool bmi2; /* Host-selected flag-preserving variable shifts. */
  bool rv64;
  uint32_t rv_anchors[MAX_NODES];
  unsigned rv_anchor_count;
  bool rv_variadic;
  bool a64; /* AArch64 encodings, relocations and ABI instead of x86-64 */
  bool winarm_variadic;
  bool winarm64; /* Windows AArch64 calling convention and COFF objects. */
  bool win64; /* x86-64 Windows: Microsoft x64 calling convention and COFF objects */
  bool darwin; /* macOS: Apple's AAPCS64 variant and Mach-O objects */
  /* Windows unwind data: per function {text start, prologue length, frame bytes}. */
  uint32_t unwind_frames[MAX_SYMBOLS + 2][4]; /* start, prologue bytes, frame bytes, saved home registers */
  unsigned unwind_frame_count;
  uint32_t arm_epilogues[MAX_SYMBOLS * 8][2]; /* frame index, text offset */
  unsigned arm_epilogue_count;
  unsigned *dwarf_types; /* DynType -> DWARF type id + 1 for this object; 1 means unknown */
  size_t message_offsets[GUARD_COUNT], message_lengths[GUARD_COUNT];
  uint32_t check_origin, message_origins[GUARD_COUNT], stub_origins[GUARD_COUNT];
  /* Per function, the failure path of each runtime check without pending
     defers is emitted once; later checks of that kind branch to it. */
  size_t guard_stubs[GUARD_COUNT];
  /* x86-64: R9 holds a binary operator's left value while its call-free
     right operand is evaluated; any call emitted meanwhile is a bug. */
  bool holding;
  /* A comparison that a branch consumes directly leaves its operands
     compared and records the condition instead of producing 0 or 1. */
  const DynIrExpr *flags_for, *flags_from;
  int flags_condition;
  /* The operands of the comparison being lowered are already compared. */
  bool compared;
  /* Shared cleanup ladders: paths that run every pending defer and then end
     the same way emit the cleanup once per defer stack and jump to it. */
  struct { unsigned kind, count, first; size_t at; } ladders[128];
  unsigned ladder_count, ladder_pool_used;
  uint32_t ladder_pool[16384];
} BackendContext;
enum { LADDER_PANIC, LADDER_UNWIND, LADDER_RETURN };
static bool emit_defers(BackendContext *ctx, const DynIrProgram *, const DynIrFunction *, unsigned);
/* Text offset of an earlier ladder for the current defer stack, or SIZE_MAX. */
static size_t ladder_find(BackendContext *ctx, unsigned kind) {
  for (unsigned i = 0; i < ctx->ladder_count; ++i) {
    if (ctx->ladders[i].kind != kind || ctx->ladders[i].count != ctx->defer_count) continue;
    if (!memcmp(ctx->ladder_pool + ctx->ladders[i].first, ctx->defer_ids, ctx->defer_count * sizeof(uint32_t)))
      return ctx->ladders[i].at;
  }
  return SIZE_MAX;
}
static void ladder_remember(BackendContext *ctx, unsigned kind) {
  if (ctx->ladder_count == sizeof(ctx->ladders) / sizeof(ctx->ladders[0]) ||
      ctx->ladder_pool_used + ctx->defer_count > sizeof(ctx->ladder_pool) / sizeof(ctx->ladder_pool[0]))
    return;
  memcpy(ctx->ladder_pool + ctx->ladder_pool_used, ctx->defer_ids, ctx->defer_count * sizeof(uint32_t));
  ctx->ladders[ctx->ladder_count++] = (__typeof__(ctx->ladders[0])){kind, ctx->defer_count, ctx->ladder_pool_used, ctx->text.n};
  ctx->ladder_pool_used += ctx->defer_count;
}
static void isa_jump_back(BackendContext *ctx, size_t destination);
/* Runs the pending defers innermost first. Each level is recorded as a
   ladder entry, so a later path whose defer stack is a prefix enters partway
   in; *jumped says the path joined an existing ladder, tail included. */
static bool ladder_cleanup(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f, unsigned kind,
                           bool *jumped) {
  unsigned saved = ctx->defer_count;
  *jumped = false;
  for (unsigned level = saved; level > 0; --level) {
    ctx->defer_count = level;
    size_t shared = ladder_find(ctx, kind);
    if (shared != SIZE_MAX) {
      isa_jump_back(ctx, shared);
      *jumped = true;
      break;
    }
    ladder_remember(ctx, kind);
    if (!emit_defers(ctx, ir, f, level - 1)) {
      ctx->defer_count = saved;
      return false;
    }
  }
  ctx->defer_count = saved;
  return true;
}
#define backend_report(ctx, ...) do { if ((ctx)->report) fprintf(stderr, __VA_ARGS__); } while (0)
/* Words in the runtime's DynUnwind for this target (runtime/reference_support.c). */
static unsigned unwind_words(const BackendContext *ctx) { return ctx->win64 ? 32 : ctx->rv64 ? 28 : ctx->a64 ? 22 : 16; }
static void byte(BackendContext *ctx, unsigned x) {
  if (ctx->text.n < ctx->text.capacity || reserve(&ctx->text, ctx->text.n + 1))
    ctx->text.data[ctx->text.n++] = (unsigned char)x;
}
static void code(BackendContext *ctx, const unsigned char *p, size_t n) { while (n--) byte(ctx, *p++); }
#define CODE(...) do { const unsigned char p[] = {__VA_ARGS__}; code(ctx, p, sizeof(p)); } while (0)
static void word(BackendContext *ctx, uint32_t n) {
  for (unsigned i = 0; i < 4; ++i) byte(ctx, n >> (8 * i));
}
static void immediate(BackendContext *ctx, uint64_t n) {
  for (unsigned i = 0; i < 8; ++i) byte(ctx, (unsigned)(n >> (8 * i)));
}
static void patch_word(BackendContext *ctx, size_t offset, uint32_t n) {
  if (offset > ctx->text.n || ctx->text.n - offset < 4) { ctx->text.failed = true; return; }
  for (unsigned i = 0; i < 4; ++i) ctx->text.data[offset + i] = (unsigned char)(n >> (8 * i));
}
static uint64_t bytes_hash(const char *s, size_t length) {
  uint64_t hash = UINT64_C(1469598103934665603) ^ length;
  for (size_t i = 0; i < length; ++i) hash = (hash ^ (unsigned char)s[i]) * UINT64_C(1099511628211);
  return hash;
}
static size_t literal_store(BackendContext *ctx, const char *s, size_t length);
static size_t literal(BackendContext *ctx, const char *s, size_t length) {
  if (!length) return 0;
  if (2 * (ctx->string_count + 1) > ctx->string_capacity) {
    size_t capacity = ctx->string_capacity ? 2 * ctx->string_capacity : 1024;
    struct StoredString *grown = calloc(capacity, sizeof(*grown));
    if (!grown) return literal_store(ctx, s, length);
    for (size_t i = 0; i < ctx->string_capacity; ++i) {
      if (!ctx->strings[i].length) continue;
      size_t j = bytes_hash((const char *)ctx->rodata.data + ctx->strings[i].offset, ctx->strings[i].length) & (capacity - 1);
      while (grown[j].length) j = (j + 1) & (capacity - 1);
      grown[j] = ctx->strings[i];
    }
    free(ctx->strings); ctx->strings = grown; ctx->string_capacity = capacity;
  }
  size_t mask = ctx->string_capacity - 1, j = bytes_hash(s, length) & mask;
  for (; ctx->strings[j].length; j = (j + 1) & mask) {
    size_t at = ctx->strings[j].offset;
    if (ctx->strings[j].length == length && at + length <= ctx->rodata.n &&
        !memcmp(ctx->rodata.data + at, s, length)) return at;
  }
  size_t at = literal_store(ctx, s, length);
  if (!ctx->rodata.failed) { ctx->strings[j].offset = at; ctx->strings[j].length = length; ++ctx->string_count; }
  return at;
}
static size_t literal_store(BackendContext *ctx, const char *s, size_t length) {
  size_t offset = ctx->rodata.n;
  if (length > LIMIT - ctx->rodata.n || !reserve(&ctx->rodata, ctx->rodata.n + length)) { ctx->rodata.failed = true; return 0; }
  if (length) memcpy(ctx->rodata.data + ctx->rodata.n, s, length);
  ctx->rodata.n += length;
  return offset;
}
static bool grow_relocations(Elf64_Rela **items, size_t *capacity) {
  size_t next = *capacity ? *capacity * 2 : 4096;
  if (next > LIMIT / sizeof(Elf64_Rela)) return false;
  Elf64_Rela *grown = realloc(*items, next * sizeof(**items));
  if (!grown) return false;
  *items = grown; *capacity = next;
  return true;
}
static void relocate(BackendContext *ctx, unsigned symbol, unsigned type, int64_t addend) {
  if (ctx->relocation_count == ctx->relocation_capacity &&
      !grow_relocations(&ctx->relocations, &ctx->relocation_capacity)) {
    ctx->relocation_failed = true; return;
  }
  ctx->relocations[ctx->relocation_count++] = (Elf64_Rela){.r_offset = ctx->text.n,
      .r_info = ELF64_R_INFO(symbol, type), .r_addend = addend};
}
static void isa_call_symbol(BackendContext *ctx, unsigned symbol);
static void runtime_call(BackendContext *ctx, unsigned runtime) {
  if (!ctx->runtime_index[runtime]) ctx->runtime_index[runtime] = (unsigned)(ctx->runtime_base + ctx->runtime_count++);
  isa_call_symbol(ctx, ctx->runtime_index[runtime]);
}
#include "a64.inc"
#include "rv64.inc"
#include "isa.inc"
#include "coff.inc"
#include "macho.inc"
static bool signed_scalar(DynType type) {
  return (type >= DYN_TYPE_I8 && type <= DYN_TYPE_I64) || type == DYN_TYPE_ISIZE;
}
static bool integer_type(DynType t) {
  return (t >= DYN_TYPE_I8 && t <= DYN_TYPE_USIZE) || t == DYN_TYPE_BOOL;
}
static unsigned integer_bits(DynType t) {
  switch (t) {
  case DYN_TYPE_BOOL: return 1;
  case DYN_TYPE_I8: case DYN_TYPE_U8: return 8;
  case DYN_TYPE_I16: case DYN_TYPE_U16: return 16;
  case DYN_TYPE_I32: case DYN_TYPE_U32: return 32;
  default: return 64;
  }
}
/* Only literal integer trees are folded. Checked overflow remains in the
   emitter, preserving runtime guards and deferred cleanup. */
static bool fold_integer(const DynIrProgram *ir, const DynIrExpr *e,
                         uint64_t *value, unsigned depth) {
  if (depth > MAX_DEPTH || !integer_type(e->type)) return false;
  unsigned bits = integer_bits(e->type);
  uint64_t mask = UINT64_MAX >> (64-bits), sign = UINT64_C(1) << (bits-1);
  uint64_t a, b, result;
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_CHAR || e->kind == DYN_EXPR_BOOL) {
    result = e->kind == DYN_EXPR_BOOL ? e->boolean : e->integer;
  } else {
    if (e->kind != DYN_EXPR_BINARY || e->left >= ir->expression_count ||
        e->right >= ir->expression_count || ir->expressions[e->left].type != e->type ||
        ir->expressions[e->right].type != e->type ||
        !fold_integer(ir, &ir->expressions[e->left], &a, depth+1) ||
        !fold_integer(ir, &ir->expressions[e->right], &b, depth+1)) return false;
    a &= mask; b &= mask;
    bool overflow = false;
    switch (e->op) {
    case DYN_OP_ADD:
      result = (a+b)&mask;
      overflow = signed_scalar(e->type) ? ((~(a^b)&(a^result)&sign) != 0) : b > mask-a;
      break;
    case DYN_OP_SUB:
      result = (a-b)&mask;
      overflow = signed_scalar(e->type) ? (((a^b)&(a^result)&sign) != 0) : a < b;
      break;
    case DYN_OP_MUL: {
      result = (a*b)&mask;
      uint64_t magnitude_a = a, magnitude_b = b, limit = mask;
      if (signed_scalar(e->type)) {
        magnitude_a = (a&sign) ? (0-a)&mask : a;
        magnitude_b = (b&sign) ? (0-b)&mask : b;
        limit = ((a^b)&sign) ? sign : sign-1;
      }
      overflow = magnitude_b && magnitude_a > limit/magnitude_b;
      break;
    }
    case DYN_OP_BIT_AND: result = a&b; break;
    case DYN_OP_BIT_OR: result = a|b; break;
    case DYN_OP_BIT_XOR: result = a^b; break;
    default: return false;
    }
    if (overflow && !e->wrap) return false;
  }
  result &= mask;
  if (signed_scalar(e->type) && (result&sign)) result |= ~mask;
  *value = result;
  return true;
}
static DynType storage_type(const DynIrProgram *ir, DynType t) {
  return dyn_type_is_enum(t) && t-DYN_TYPE_ENUM_BASE<ir->enum_count ? ir->enums[t-DYN_TYPE_ENUM_BASE].tag_type : t;
}
static bool payload_enum(const DynIrProgram *ir,DynType t) {
  return dyn_type_is_enum(t) && t-DYN_TYPE_ENUM_BASE<ir->enum_count && ir->enums[t-DYN_TYPE_ENUM_BASE].has_payload;
}
static bool raw_aggregate(const DynIrProgram *ir,DynType t) { return dyn_type_is_array(t)||payload_enum(ir,t); }
static void normalize(BackendContext *ctx, DynType t) {
  if (payload_enum(ctx->active_ir,t)) return;
  t=storage_type(ctx->active_ir,t);
  isa_extend(ctx, integer_bits(t), signed_scalar(t));
}
static unsigned memory_bits(DynType type) { return type==DYN_TYPE_F32?32:integer_bits(type); }
/* Address in RAX for loads; destination in R11 and value in RAX for stores. */
static void load_memory(BackendContext *ctx, DynType type) {
  type=storage_type(ctx->active_ir,type);
  isa_load_value(ctx, memory_bits(type), signed_scalar(type));
  normalize(ctx, type);
}
static void store_memory(BackendContext *ctx, DynType type) {
  type=storage_type(ctx->active_ir,type);
  isa_store_value(ctx, memory_bits(type));
}
static const char *function_name(const DynIrFunction *f) { return f->foreign ? f->link_name : f->name; }
static void guard(BackendContext *ctx, const DynIrFunction *f, Cond success, unsigned check) {
  if (ctx->message_offsets[check] == SIZE_MAX || ctx->message_origins[check] != ctx->check_origin) {
    ctx->message_origins[check] = ctx->check_origin;
    /* dyn_check_failed builds "runtime check failed (KIND) in NAME" from the
       name and kind << 24 | name length, so each name is stored once. */
    const DynIrFunction *origin = ctx->check_origin && ctx->check_origin <= ctx->active_ir->function_count
        ? &ctx->active_ir->functions[ctx->check_origin - 1] : f;
    const char *name = function_name(origin);
    size_t length = strlen(name);
    if (length > 800) length = 800;
    ctx->message_lengths[check] = (size_t)check << 24 | length;
    ctx->message_offsets[check] = literal(ctx, name, length);
  }
  /* The caller supplies the success condition of the preceding compare.
     Restore the fixed frame before calling the noreturn runtime: nested
     expression pushes may otherwise leave the call stack misaligned. */
  bool plain = ctx->unwinding || !ctx->defer_count;
  if (plain && ctx->guard_stubs[check] != SIZE_MAX && ctx->stub_origins[check] == ctx->check_origin) {
    /* x86-64 branches straight to the shared failure path on the inverse
       condition; elsewhere a success branch skips a jump to it. */
    static const signed char inverse[] = {1, 0, 3, 2, 5, 4, 7, 6, 9, 8, -1, 2};
    int failure = !ctx->a64 && !ctx->rv64 && (unsigned)success < sizeof(inverse) ? inverse[success] : -1;
    if (failure >= 0) isa_patch(ctx, isa_branch(ctx, failure), ctx->guard_stubs[check]);
    else {
      size_t skip = isa_branch(ctx, success);
      isa_jump_back(ctx, ctx->guard_stubs[check]);
      isa_patch(ctx, skip, ctx->text.n);
    }
    return;
  }
  size_t branch = isa_branch(ctx, success);
  if (plain) { ctx->guard_stubs[check] = ctx->text.n; ctx->stub_origins[check] = ctx->check_origin; }
  bool held = ctx->holding; ctx->holding = false; /* the failure path never returns */
  isa_reset_stack(ctx);
  unsigned saved_stack=ctx->stack_slots; ctx->stack_slots=0;
  if (!ctx->unwinding && ctx->defer_count) {
    /* The message waits in the call slot while the shared cleanup runs. */
    isa_rodata_address(ctx, R_A, ctx->message_offsets[check]); isa_store(ctx, R_A, ctx->call_offset);
    isa_small_immediate(ctx, R_A, (uint32_t)ctx->message_lengths[check]); isa_store(ctx, R_A, ctx->call_offset+8);
    bool jumped;
    uint32_t saved_origin = ctx->check_origin; ctx->check_origin = 0;
    bool cleaned = ladder_cleanup(ctx, ctx->active_ir, f, LADDER_PANIC, &jumped);
    ctx->check_origin = saved_origin;
    if (!cleaned) ctx->text.failed=true;
    else if (!jumped) {
      isa_load(ctx, isa_argument(ctx, 0), ctx->call_offset); isa_load(ctx, isa_argument(ctx, 1), ctx->call_offset+8);
      runtime_call(ctx, RUNTIME_CHECK_FAILED); isa_trap(ctx); /* never returns */
    }
  } else {
    isa_string_arguments(ctx, ctx->message_offsets[check], ctx->message_lengths[check]);
    runtime_call(ctx, RUNTIME_CHECK_FAILED); isa_trap(ctx); /* never returns */
  }
  ctx->stack_slots=saved_stack;
  ctx->holding = held;
  isa_patch(ctx, branch, ctx->text.n);
}
static bool scalar(const DynIrProgram *ir, DynType);
static bool float_type(DynType);
static bool descriptor(DynType t) { return dyn_type_is_slice(t) || t==DYN_TYPE_STRING || t==DYN_TYPE_ANY; }
static bool aggregate(const DynIrProgram *ir, DynType t) { return dyn_type_is_struct(t)||raw_aggregate(ir,t); }
static bool value_type(const DynIrProgram *ir, DynType t) { return scalar(ir, t)||descriptor(t); }
static bool layout(const DynIrProgram *ir, DynType type, uint32_t *size, uint32_t *alignment, unsigned depth) {
  if (depth > MAX_DEPTH) return false;
  if (dyn_type_is_enum(type)) {
    if (type-DYN_TYPE_ENUM_BASE>=ir->enum_count) return false;
    const DynIrEnum *e=&ir->enums[type-DYN_TYPE_ENUM_BASE];
    if (!e->alignment || e->alignment>8 || e->size>MAX_LAYOUT) return false;
    *size=(uint32_t)e->size; *alignment=(uint32_t)e->alignment; return true;
  }
  if (descriptor(type)) { *size=16; *alignment=8; return true; }
  if (scalar(ir, type)) { *size=*alignment=(memory_bits(type)+7)/8; return true; }
  if (dyn_type_is_array(type)) {
    size_t index=type-DYN_TYPE_ARRAY_BASE; uint32_t element;
    if (index>=ir->array_count || !layout(ir,ir->arrays[index].element,&element,alignment,depth+1) ||
        ir->arrays[index].length>MAX_LAYOUT || element>MAX_LAYOUT/(ir->arrays[index].length?ir->arrays[index].length:1)) return false;
    *size=element*(uint32_t)ir->arrays[index].length; return true;
  }
  if (dyn_type_is_struct(type)) {
    size_t index=type-DYN_TYPE_STRUCT_BASE;
    if (index>=ir->struct_count || ir->structs[index].size>MAX_LAYOUT || ir->structs[index].alignment>8) return false;
    const DynIrStruct *record=&ir->structs[index];
    if ((uint64_t)record->field_start+record->field_count>ir->field_count) return false;
    for (uint32_t i=0;i<record->field_count;++i) { uint32_t n,a; if (!layout(ir,ir->fields[record->field_start+i].type,&n,&a,depth+1)) return false; }
    *size=(uint32_t)record->size; *alignment=(uint32_t)record->alignment; return *alignment!=0;
  }
  return false;
}
static bool field_offset(const DynIrProgram *ir,DynType type,uint32_t field,uint32_t *offset) {
  if (!dyn_type_is_struct(type) || type-DYN_TYPE_STRUCT_BASE>=ir->struct_count) return false;
  const DynIrStruct *record=&ir->structs[type-DYN_TYPE_STRUCT_BASE];
  if (field>=record->field_count) return false;
  uint32_t at=0;
  for (uint32_t i=0;i<=field;++i) {
    uint32_t size,alignment;
    if (!layout(ir,ir->fields[record->field_start+i].type,&size,&alignment,0)) return false;
    if (!record->packed) at=(at+alignment-1)&~(alignment-1);
    if (i==field) { *offset=at; return true; }
    at+=size;
  }
  return false;
}
/* Classify the bounded <=16-byte SysV struct subset; arrays are storage only. */
static bool abi_classify(const DynIrProgram *ir,DynType type,unsigned offset,unsigned cls[2],unsigned depth) {
  uint32_t size,alignment;
  if (!layout(ir,type,&size,&alignment,depth) || offset+size>16 || offset%alignment) return false;
  if (dyn_type_is_struct(type)) {
    const DynIrStruct *record=&ir->structs[type-DYN_TYPE_STRUCT_BASE];
    for (uint32_t i=0;i<record->field_count;++i) { uint32_t at;
      if (!field_offset(ir,type,i,&at) || !abi_classify(ir,ir->fields[record->field_start+i].type,offset+at,cls,depth+1)) return false;
    }
  } else if (dyn_type_is_array(type)) {
    const DynIrArray *array=&ir->arrays[type-DYN_TYPE_ARRAY_BASE]; uint32_t element,a;
    if (!layout(ir,array->element,&element,&a,depth+1)) return false;
    for (uint64_t i=0;i<array->length;++i) if (!abi_classify(ir,array->element,offset+(unsigned)i*element,cls,depth+1)) return false;
  } else for (unsigned i=offset;i<offset+size;++i) {
    if (!float_type(type)) cls[i/8]=1;
    else if (!cls[i/8]) cls[i/8]=2;
  }
  return true;
}
static bool abi_value(const DynIrProgram *ir,DynType type,unsigned *parts,unsigned cls[2]) {
  cls[0]=cls[1]=1;
  if (scalar(ir, type)) { *parts=1; cls[0]=float_type(type)?2:1; return true; }
  if (descriptor(type)) { *parts=2; return true; }
  uint32_t size,alignment;
  if (!dyn_type_is_struct(type) || !layout(ir,type,&size,&alignment,0) || size>16) return false;
  cls[0]=cls[1]=0; *parts=(size+7)/8;
  return abi_classify(ir,type,0,cls,0);
}
/* LLVM's native array ABI flattens scalar leaves, independently of C struct ABI. */
static bool array_parts(const DynIrProgram *ir,DynType type,uint32_t offset,ArrayPart *out,unsigned *count,unsigned depth) {
  uint32_t size,alignment;
  if (depth > MAX_DEPTH || !layout(ir,type,&size,&alignment,0)) return false;
  if (dyn_type_is_array(type)) {
    const DynIrArray *array=&ir->arrays[type-DYN_TYPE_ARRAY_BASE]; uint32_t element,a;
    if (!layout(ir,array->element,&element,&a,0)) return false;
    for (uint64_t i=0;i<array->length;++i) if (!array_parts(ir,array->element,offset+(uint32_t)i*element,out,count,depth+1)) return false;
  } else if (payload_enum(ir,type)) {
    const DynIrEnum *e=&ir->enums[type-DYN_TYPE_ENUM_BASE];
    uint32_t tag_size=(memory_bits(e->tag_type)+7)/8, a=(uint32_t)e->payload_alignment;
    if (!a || a>8 || *count>=512) return false;
    out[(*count)++]=(ArrayPart){e->tag_type,offset};
    unsigned units=(unsigned)((e->payload_size+a-1)/a);
    DynType unit=a==1?DYN_TYPE_U8:a==2?DYN_TYPE_U16:a==4?DYN_TYPE_U32:DYN_TYPE_U64;
    if (units>512-*count) return false;
    uint32_t base=(tag_size+a-1)&~(a-1);
    for (unsigned i=0;i<units;++i) out[(*count)++]=(ArrayPart){unit,offset+base+i*a};
  } else if (dyn_type_is_struct(type)) {
    const DynIrStruct *record=&ir->structs[type-DYN_TYPE_STRUCT_BASE];
    for (uint32_t i=0;i<record->field_count;++i) { uint32_t at;
      if (!field_offset(ir,type,i,&at) || !array_parts(ir,ir->fields[record->field_start+i].type,offset+at,out,count,depth+1)) return false;
    }
  } else if (descriptor(type)) {
    if (*count>510) return false;
    out[(*count)++]=(ArrayPart){DYN_TYPE_U64,offset};out[(*count)++]=(ArrayPart){DYN_TYPE_U64,offset+8};
  } else {
    if (!scalar(ir, type) || *count==512) return false;
    out[(*count)++]=(ArrayPart){storage_type(ir,type),offset};
  }
  return true;
}
/* AAPCS64 homogeneous floating aggregate: one to four members of one float type. */
static bool a64_hfa(const DynIrProgram *ir,DynType type,DynType *element,unsigned *count,unsigned depth) {
  if (depth>MAX_DEPTH) return false;
  if (float_type(type)) {
    if (*element && *element!=type) return false;
    *element=type; return ++*count<=4;
  }
  if (dyn_type_is_struct(type) && type-DYN_TYPE_STRUCT_BASE<ir->struct_count) {
    const DynIrStruct *record=&ir->structs[type-DYN_TYPE_STRUCT_BASE];
    if (!record->field_count) return false;
    for (uint32_t i=0;i<record->field_count;++i)
      if (!a64_hfa(ir,ir->fields[record->field_start+i].type,element,count,depth+1)) return false;
    return true;
  }
  if (dyn_type_is_array(type) && type-DYN_TYPE_ARRAY_BASE<ir->array_count) {
    const DynIrArray *array=&ir->arrays[type-DYN_TYPE_ARRAY_BASE];
    if (!array->length || array->length>4) return false;
    for (uint64_t i=0;i<array->length;++i) if (!a64_hfa(ir,array->element,element,count,depth+1)) return false;
    return true;
  }
  return false;
}
/* Mirrors codegen_abi.h: an HFA whose size equals its members, else none. */
static bool a64_struct_hfa(const DynIrProgram *ir,DynType type,DynType *element,unsigned *count) {
  uint32_t size,alignment; *element=0; *count=0;
  return dyn_type_is_struct(type) && layout(ir,type,&size,&alignment,0) &&
         a64_hfa(ir,type,element,count,0) && *count && size==*count*(memory_bits(*element)/8);
}
/* Results returned through a hidden pointer. AArch64 Dyn-only raw aggregates
   always use memory; C structs follow AAPCS64. */
/* Microsoft x64 passes and returns structs of 1, 2, 4 or 8 bytes as integers;
   other sizes go through memory. */
static bool win64_scalar_size(const DynIrProgram *ir,DynType type) {
  uint32_t size,alignment;
  return layout(ir,type,&size,&alignment,0) && (size==1 || size==2 || size==4 || size==8);
}
static bool abi_memory(const BackendContext *ctx,const DynIrProgram *ir,DynType type) {
  if (ctx->rv64) { uint32_t size,alignment; return raw_aggregate(ir,type) || (dyn_type_is_struct(type) && (!layout(ir,type,&size,&alignment,0) || size>16)); }
  if (ctx->win64) return raw_aggregate(ir,type) || (dyn_type_is_struct(type) && !win64_scalar_size(ir,type));
  if (ctx->a64) {
    if (raw_aggregate(ir,type)) return true;
    DynType element; unsigned count; uint32_t size,alignment;
    return dyn_type_is_struct(type) && !a64_struct_hfa(ir,type,&element,&count) &&
           (!layout(ir,type,&size,&alignment,0) || size>16);
  }
  if (raw_aggregate(ir,type)) {
    ArrayPart parts[512]; unsigned count=0,gp=0,fp=0;
    if (!array_parts(ir,type,0,parts,&count,0)) return true;
    for (unsigned i=0;i<count;++i) { if (float_type(parts[i].type)) ++fp; else ++gp; }
    return gp>3 || fp>4;
  }
  unsigned parts,cls[2]; return dyn_type_is_struct(type) && !abi_value(ir,type,&parts,cls);
}
static int abi_gp(bool a64,unsigned *gp) { return *gp<(a64?8u:6u)?(int)(*gp)++:-1; }
static int abi_fp(unsigned *fp) { return *fp<8?(int)(*fp)++ + 8:-1; }
/* Microsoft x64 assigns registers by argument position: the nth of the first
   four uses RCX/RDX/R8/R9 or XMM0-3. *position counts every eight-byte slot. */
static int win64_register(unsigned *position,bool floating) {
  int cls=*position<4?(int)*position+(floating?8:0):-1; ++*position; return cls;
}
/* Struct arguments passed as a pointer to a caller-owned copy. */
static bool abi_copied(const BackendContext *ctx,const DynIrProgram *ir,DynType type) {
  if (!dyn_type_is_struct(type)) return false;
  if (ctx->rv64) {uint32_t size,alignment;return layout(ir,type,&size,&alignment,0)&&size>16;}
  if (ctx->win64) return !win64_scalar_size(ir,type);
  DynType element; unsigned members; uint32_t size,alignment;
  return ctx->a64 && (ctx->winarm64 || !a64_struct_hfa(ir,type,&element,&members)) && layout(ir,type,&size,&alignment,0) && size>16;
}
/* Assign argument registers. *indirect means the single part is a pointer to a
   caller-owned copy (AAPCS64 composites over 16 bytes). */
static bool abi_assign(const BackendContext *ctx,const DynIrProgram *ir,DynType type,unsigned *gp,unsigned *fp,AbiPart *parts,unsigned *count,unsigned capacity,bool *indirect) {
  unsigned cls[2]; uint32_t size=8,alignment;
  bool a64=ctx->a64;
  *indirect=false; *count=0;
  if (ctx->rv64) {
    if (!layout(ir,type,&size,&alignment,0)) return false;
    if (dyn_type_is_struct(type)) {
      ArrayPart leaves[512]; unsigned n=0,ng=0,nf=0;
      bool flat=array_parts(ir,type,0,leaves,&n,0) && n<=2;
      for(unsigned i=0;flat&&i<n;++i) { if(float_type(leaves[i].type))++nf;else ++ng; }
      if (!ctx->rv_variadic && flat && nf && *fp+nf<=8 && *gp+ng<=8) {
        if(n>capacity)return false;
        for(unsigned i=0;i<n;++i) parts[i]=(AbiPart){leaves[i].offset,(memory_bits(leaves[i].type)+7)/8,
          float_type(leaves[i].type)?(int)(*fp)+++(leaves[i].type==DYN_TYPE_F32?16:8):abi_gp(true,gp),leaves[i].type,0};
        *count=n;return true;
      }
      if(size>16) { *indirect=true;parts[0]=(AbiPart){0,8,abi_gp(true,gp),DYN_TYPE_RAWPTR,0};*count=1;return true; }
      *count=(size+7)/8;if(*count>capacity)return false;
      if(ctx->rv_variadic && alignment==16)*gp=(*gp+1)&~1u;
      for(unsigned i=0;i<*count;++i)parts[i]=(AbiPart){i*8,size-i*8>8?8:size-i*8,abi_gp(true,gp),DYN_TYPE_U64,0};
      return true;
    }
    if(raw_aggregate(ir,type)) {
      ArrayPart leaves[512];if(!array_parts(ir,type,0,leaves,count,0)||*count>capacity)return false;
      for(unsigned i=0;i<*count;++i)parts[i]=(AbiPart){leaves[i].offset,(memory_bits(leaves[i].type)+7)/8,
        float_type(leaves[i].type)&&*fp<8?(int)(*fp)+++(leaves[i].type==DYN_TYPE_F32?16:8):abi_gp(true,gp),leaves[i].type,0};
      return true;
    }
    *count=descriptor(type)?2:1;
    for(unsigned i=0;i<*count;++i)parts[i]=(AbiPart){i*8,8,
      float_type(type)&&!ctx->rv_variadic&&*fp<8?(int)(*fp)+++(type==DYN_TYPE_F32?16:8):abi_gp(true,gp),descriptor(type)?DYN_TYPE_U64:type,0};
    return true;
  }
  if (ctx->winarm_variadic) {
    if (!layout(ir,type,&size,&alignment,0)) return false;
    *indirect=dyn_type_is_struct(type) && size>16;
    if (*indirect) { parts[0]=(AbiPart){0,8,abi_gp(true,gp),DYN_TYPE_RAWPTR,0}; *count=1; return true; }
    unsigned chunks=(size+7)/8;
    if (chunks>capacity) return false;
    for(unsigned i=0;i<chunks;++i) parts[i]=(AbiPart){i*8,size-i*8>8?8:size-i*8,abi_gp(true,gp),DYN_TYPE_U64,0};
    *count=chunks; return true;
  }
  if (ctx->win64) {
    if (raw_aggregate(ir,type)) {
      /* Dyn-only fixed arrays: one position per leaf, like LLVM's split aggregate. */
      ArrayPart leaves[512];
      if (!array_parts(ir,type,0,leaves,count,0) || *count>capacity) return false;
      for (unsigned i=0;i<*count;++i)
        parts[i]=(AbiPart){leaves[i].offset,(memory_bits(leaves[i].type)+7)/8,win64_register(gp,float_type(leaves[i].type)),leaves[i].type,0};
      return true;
    }
    if (dyn_type_is_struct(type)) {
      if (!layout(ir,type,&size,&alignment,0)) return false;
      *indirect=!win64_scalar_size(ir,type); *count=1;
      parts[0]=(AbiPart){0,*indirect?8:size,win64_register(gp,false),*indirect?DYN_TYPE_RAWPTR:DYN_TYPE_U64,0};
      return true;
    }
    *count=descriptor(type)?2:1;
    for (unsigned i=0;i<*count;++i)
      parts[i]=(AbiPart){i*8,8,win64_register(gp,float_type(type)),descriptor(type)?DYN_TYPE_U64:type,0};
    return true;
  }
  if (raw_aggregate(ir,type)) {
    ArrayPart leaves[512];
    if (!array_parts(ir,type,0,leaves,count,0) || *count>capacity) return false;
    for (unsigned i=0;i<*count;++i)
      parts[i]=(AbiPart){leaves[i].offset,(memory_bits(leaves[i].type)+7)/8,float_type(leaves[i].type)?abi_fp(fp):abi_gp(a64,gp),leaves[i].type,0};
    return true;
  }
  if (dyn_type_is_struct(type) && !layout(ir,type,&size,&alignment,0)) return false;
  if (a64 && dyn_type_is_struct(type)) {
    DynType element; unsigned members;
    unsigned chunks=(size+7)/8;
    bool hfa=a64_struct_hfa(ir,type,&element,&members);
    if (hfa && *fp+members<=8) {
      if (members>capacity) return false;
      for (unsigned i=0;i<members;++i) parts[i]=(AbiPart){i*(memory_bits(element)/8),memory_bits(element)/8,abi_fp(fp),element,0};
      *count=members; return true;
    }
    if (hfa) *fp=8; /* an HFA that does not fit goes entirely to the stack */
    else if (size>16) { *indirect=true; parts[0]=(AbiPart){0,8,abi_gp(true,gp),DYN_TYPE_RAWPTR,0}; *count=1; return true; }
    bool registers=!hfa && *gp+chunks<=8;
    if (!registers && !hfa) *gp=8;
    if (chunks>capacity) return false;
    for (unsigned i=0;i<chunks;++i)
      parts[i]=(AbiPart){i*8,size-i*8>8?8:size-i*8,registers?abi_gp(true,gp):-1,DYN_TYPE_U64,0};
    *count=chunks; return true;
  }
  if (a64) {
    *count=descriptor(type)?2:1;
    for (unsigned i=0;i<*count;++i)
      parts[i]=(AbiPart){i*8,8,float_type(type)?abi_fp(fp):abi_gp(true,gp),descriptor(type)?DYN_TYPE_U64:type,0};
    return true;
  }
  if (abi_memory(ctx,ir,type)) {
    *count=(size+7)/8; if (*count>capacity) return false;
    for (unsigned i=0;i<*count;++i) parts[i]=(AbiPart){i*8,size-i*8>8?8:size-i*8,-1,DYN_TYPE_U64,0};
    return true;
  }
  if (!abi_value(ir,type,count,cls) || *count>capacity) return false;
  unsigned integers=0,floats=0;
  for (unsigned i=0;i<*count;++i) { if (cls[i]==2) ++floats; else ++integers; }
  bool spill=dyn_type_is_struct(type) && (*gp+integers>6 || *fp+floats>8);
  for (unsigned i=0;i<*count;++i) {
    int assigned;
    if (spill) assigned=-1;
    else if (cls[i]==2) assigned=abi_fp(fp);
    else assigned=abi_gp(false,gp);
    parts[i]=(AbiPart){i*8,size-i*8>8?8:size-i*8,assigned,DYN_TYPE_U64,0};
  }
  return true;
}
static bool abi_supported(const DynIrProgram *ir,DynType type) {
  if (raw_aggregate(ir,type)) { ArrayPart leaves[512]; unsigned n=0; return array_parts(ir,type,0,leaves,&n,0); }
  uint32_t size,alignment; return type==DYN_TYPE_VOID || value_type(ir, type) ||
    (dyn_type_is_struct(type) && layout(ir,type,&size,&alignment,0) && size<=MAX_AGGREGATE);
}
static void load_chunk(BackendContext *ctx, unsigned offset,unsigned size) { isa_load_chunk(ctx, offset, size); }
/* Bytes a stack-passed part occupies: eight, except that Apple AArch64 packs
   scalars narrower than eight bytes at their natural size and alignment. */
static uint32_t stack_width(const BackendContext *ctx, const AbiPart *part) {
  unsigned bits=memory_bits(storage_type(ctx->active_ir,part->leaf));
  return ctx->darwin && ctx->a64 && bits<64 ? (bits+7)/8 : 8;
}
/* Assign the next stack offset to a stack-passed part. */
static uint32_t stack_slot(const BackendContext *ctx, AbiPart *part, uint32_t *cursor) {
  uint32_t width=stack_width(ctx,part);
  *cursor=(*cursor+width-1)/width*width; part->stack=*cursor; *cursor+=width;
  return part->stack;
}
/* A <- an incoming stack-passed part. Arguments sit above the saved FP and
   return address (and, on Windows, the caller's 32-byte register home area). */
static void incoming_stack(BackendContext *ctx, AbiPart *part, uint32_t *cursor) {
  uint32_t at=(ctx->win64?48:16)+stack_slot(ctx,part,cursor);
  if (stack_width(ctx,part)==8) { isa_load(ctx, R_A, at); return; }
  isa_lea(ctx, R_A, at); load_memory(ctx, part->leaf);
}
static void save_struct(BackendContext *ctx, uint32_t offset,DynType type) {
  uint32_t size,alignment; if (!layout(ctx->active_ir,type,&size,&alignment,0)) { ctx->text.failed=true; return; }
  if (size>64) {
    /* Large values copy with a loop instead of one load and store per word. */
    isa_push(ctx, R_A); isa_move(ctx, R_11, R_A); isa_lea(ctx, R_A, offset); isa_push(ctx, R_A);
    isa_move(ctx, R_A, R_11); isa_copy(ctx, size); isa_pop(ctx, R_A);
    return;
  }
  isa_move(ctx, R_11, R_A);
  for (unsigned part=0;part<(size+7)/8;++part) {
    load_chunk(ctx, part*8,size-part*8>8?8:size-part*8);
    isa_store(ctx, R_10, offset+part*8);
  }
}
static void checked_address(BackendContext *ctx, const DynIrFunction *f, DynType pointee) {
  isa_test(ctx, R_A); guard(ctx, f, CC_NE, GUARD_NONNULL);
  uint32_t size,alignment;
  if (!layout(ctx->active_ir,pointee,&size,&alignment,0)) { ctx->text.failed=true; return; }
  if (alignment>1) { isa_test_mask(ctx, alignment-1); guard(ctx, f, CC_E, GUARD_ALIGNED); }
}
static void divide(BackendContext *ctx, const DynIrFunction *f, bool signed_operation, bool remainder, unsigned bits) {
  isa_test(ctx, R_C);
  guard(ctx, f, CC_NE, GUARD_DIVIDE); /* divisor must not be zero */
  if (signed_operation) {
    isa_immediate(ctx, R_D, UINT64_C(0) - (UINT64_C(1) << (bits-1)));
    isa_compare(ctx, R_A, R_D);
    size_t skip = isa_branch(ctx, CC_NE);
    isa_compare_small(ctx, R_C, -1);
    guard(ctx, f, CC_NE, GUARD_DIVISION_OVERFLOW);
    isa_patch(ctx, skip, ctx->text.n);
  }
  isa_divide(ctx, signed_operation, remainder);
}
static void shift(BackendContext *ctx, const DynIrFunction *f, bool signed_operation, bool left, bool wraps, unsigned bits) {
  /* Unsigned comparison also rejects negative signed counts. This dominates
     the redundant narrowed-count check in LLVM's checked_integer lowering. */
  isa_compare_small(ctx, R_C, (int)bits);
  guard(ctx, f, CC_B, GUARD_SHIFT); /* original count is in [0, bits) */
  int restore = signed_operation ? SHIFT_ARITHMETIC : SHIFT_RIGHT;
  if (!left) { isa_shift(ctx, R_A, restore); return; }
  if (!wraps) isa_move(ctx, R_D, R_A); /* preserve the original value */
  isa_shift(ctx, R_A, SHIFT_LEFT);
  if (!wraps) {
    isa_move(ctx, R_8, R_A); isa_shift(ctx, R_8, restore); /* shifting back must restore it */
    isa_compare(ctx, R_8, R_D);
    guard(ctx, f, CC_E, GUARD_OVERFLOW); /* no value/sign bits lost */
  }
}
static bool float_type(DynType t) { return t == DYN_TYPE_F32 || t == DYN_TYPE_F64; }
static bool scalar(const DynIrProgram *ir, DynType t) {
  return (dyn_type_is_enum(t) && t-DYN_TYPE_ENUM_BASE<ir->enum_count && !payload_enum(ir,t)) || integer_type(t) || float_type(t) || dyn_type_is_function(t) || dyn_type_is_pointer(t) || t==DYN_TYPE_RAWPTR;
}
static bool binary_result(BackendContext *ctx, const DynIrProgram *, const DynIrFunction *, const DynIrExpr *);
static bool expression_value(BackendContext *ctx, const DynIrProgram *, const DynIrFunction *, const DynIrExpr *, unsigned);
static bool expression(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                       DynExprId id, unsigned depth) {
  if (depth > MAX_DEPTH || id >= ir->expression_count) return false;
  if (ctx->unwinding && ctx->captured_offsets[id] && aggregate(ir, ir->expressions[id].type)) { isa_lea(ctx, R_A, ctx->captured_offsets[id]); return !ctx->text.failed; }
  if (ctx->unwinding && ctx->captured_offsets[id]) { isa_load(ctx, R_A, ctx->captured_offsets[id]); if (descriptor(ir->expressions[id].type)) isa_load(ctx, R_D, ctx->captured_offsets[id]+8); return !ctx->text.failed; }
  uint32_t saved_origin = ctx->check_origin;
  if (ir->expressions[id].check_origin) ctx->check_origin = ir->expressions[id].check_origin;
  bool ok = expression_value(ctx, ir, f, &ir->expressions[id], depth);
  ctx->check_origin = saved_origin;
  return ok;
}
/* Evaluates a condition and returns the condition code that holds when it is
   false, so the caller branches past the guarded code on that code. Integer
   comparisons branch on their own flags instead of testing a 0 or 1.
   Conditions nest: a runtime check inside this one emits its failure path,
   which runs pending defers and their own conditions, so only flags that this
   expression produced count. */
static bool condition(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                      DynExprId id, unsigned depth, int *when_false) {
  if (id >= ir->expression_count) return false;
  const DynIrExpr *e = &ir->expressions[id], *outer = ctx->flags_for;
  ctx->flags_for = e->kind == DYN_EXPR_BINARY && e->op >= DYN_OP_EQ && e->op <= DYN_OP_GE ? e : NULL;
  ctx->flags_from = NULL;
  bool ok = expression(ctx, ir, f, id, depth);
  bool flags = ctx->flags_from == e;
  ctx->flags_for = outer;
  ctx->flags_from = NULL;
  if (!ok) return false;
  if (flags) {
    /* Conditions come in complementary pairs: E/NE, B/AE, BE/A, L/GE, LE/G. */
    *when_false = ctx->flags_condition ^ 1;
  } else {
    isa_test(ctx, R_A);
    *when_false = CC_E;
  }
  return !ctx->text.failed;
}
static bool index_expression(BackendContext *ctx, const DynIrProgram *ir,const DynIrFunction *f,DynExprId id,unsigned depth) {
  if (!expression(ctx, ir,f,id,depth)) return false;
  unsigned bits=integer_bits(ir->expressions[id].type);
  if (bits<64) { isa_immediate(ctx, R_D, (UINT64_C(1)<<bits)-1); isa_alu(ctx, ALU_AND, R_A, R_D); }
  return !ctx->text.failed;
}
static bool local_slot(BackendContext *ctx, const DynIrFunction *f, uint64_t id, uint32_t *offset) {
  if (id < f->local_start || id - f->local_start >= f->local_count) return false;
  *offset = ctx->local_offsets[id-f->local_start];
  return true;
}
static bool address_value(BackendContext *, const DynIrProgram *, const DynIrFunction *, DynExprId, unsigned);
static bool address(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f, DynExprId id, unsigned depth) {
  uint32_t saved_origin = ctx->check_origin;
  if (id < ir->expression_count && ir->expressions[id].check_origin) ctx->check_origin = ir->expressions[id].check_origin;
  bool ok = address_value(ctx, ir, f, id, depth);
  ctx->check_origin = saved_origin;
  return ok;
}
static bool address_value(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f, DynExprId id, unsigned depth) {
  if (id>=ir->expression_count || depth > MAX_DEPTH) return false;
  const DynIrExpr *e=&ir->expressions[id]; uint32_t offset;
  if (e->kind==DYN_EXPR_NAME) {
    if (!local_slot(ctx, f,e->integer,&offset)) return false;
    if (ctx->local_alias[e->integer-f->local_start]) isa_load(ctx, R_A, offset); else isa_lea(ctx, R_A, offset);
  } else if (e->kind==DYN_EXPR_GLOBAL) {
    if (e->integer>=ir->global_count) return false;
    isa_symbol_address(ctx, R_A, ctx->global_symbols[e->integer]);
  } else if (e->kind==DYN_EXPR_UNARY && e->op==DYN_OP_DEREF) {
    uint32_t size,alignment;
    if (!layout(ir,e->type,&size,&alignment,0) || dyn_type_is_function(e->type) || !expression(ctx, ir,f,e->left,depth+1)) return false;
    checked_address(ctx, f,e->type);
  } else if (e->kind==DYN_EXPR_FIELD) {
    if (e->left>=ir->expression_count) return false;
    DynType type=ir->expressions[e->left].type;
    if (dyn_type_is_pointer(type)) {
      if (type-DYN_TYPE_POINTER_BASE>=ir->pointer_count || !expression(ctx, ir,f,e->left,depth+1)) return false;
      type=ir->pointers[type-DYN_TYPE_POINTER_BASE].pointee; checked_address(ctx, f,type);
    } else if (!address(ctx, ir,f,e->left,depth+1)) return false;
    uint32_t offset;
    if (!field_offset(ir,type,(uint32_t)e->integer,&offset)) return false;
    isa_add_immediate(ctx, offset);
  } else if (e->kind==DYN_EXPR_INDEX) {
    if (e->left>=ir->expression_count || e->right>=ir->expression_count) return false;
    DynType type=ir->expressions[e->left].type;
    bool array=dyn_type_is_array(type);
    if (!array && !descriptor(type)) return false;
    if (array && type-DYN_TYPE_ARRAY_BASE>=ir->array_count) return false;
    uint32_t size,alignment;
    if (!layout(ir,e->type,&size,&alignment,0) || !expression(ctx, ir,f,e->right,depth+1)) return false;
    unsigned bits=integer_bits(ir->expressions[e->right].type);
    if (bits<64) { isa_immediate(ctx, R_D, (UINT64_C(1)<<bits)-1); isa_alu(ctx, ALU_AND, R_A, R_D); }
    isa_push(ctx, R_A);
    if (array) {
      if (!address(ctx, ir,f,e->left,depth+1)) return false;
      isa_immediate(ctx, R_D, ir->arrays[type-DYN_TYPE_ARRAY_BASE].length);
    } else if (!expression(ctx, ir,f,e->left,depth+1)) return false;
    isa_pop(ctx, R_C);
    isa_compare(ctx, R_C, R_D); guard(ctx, f, CC_B, GUARD_INDEX);
    isa_scale(ctx, R_C, size); isa_alu(ctx, ALU_ADD, R_A, R_C);
  } else if (ctx->temporary_offsets[id]) return expression(ctx, ir,f,id,depth+1);
  else return false;
  return !ctx->text.failed && !ctx->relocation_failed;
}
static bool protect_call(BackendContext *ctx, const DynIrProgram *ir,const DynIrFunction *f) {
  bool padding=isa_align_call(ctx);
  isa_lea(ctx, isa_argument(ctx, 0), ctx->unwind_offset); runtime_call(ctx, 3);
  isa_test32(ctx); size_t normal=isa_branch(ctx, CC_E);
  isa_reset_stack(ctx);
  unsigned saved_stack=ctx->stack_slots; ctx->stack_slots=0;
  bool jumped;
  if (!ladder_cleanup(ctx, ir, f, LADDER_UNWIND, &jumped)) return false;
  if (!jumped) { runtime_call(ctx, 6); isa_trap(ctx); }
  ctx->stack_slots=saved_stack;
  isa_patch(ctx, normal, ctx->text.n);
  isa_lea(ctx, isa_argument(ctx, 0), ctx->unwind_offset); runtime_call(ctx, 4);
  isa_unalign_call(ctx, padding);
  return !ctx->text.failed;
}
static bool initialize(BackendContext *ctx, const DynIrProgram *,const DynIrFunction *,DynType,DynExprId,unsigned);
static bool rv_struct_registers(BackendContext *ctx,const DynIrProgram *ir,DynType type,uint32_t offset,bool returning) {
  AbiPart parts[4];unsigned count=0,gp=0,fp=0;bool indirect;
  if(!abi_assign(ctx,ir,type,&gp,&fp,parts,&count,4,&indirect)||indirect)return false;
  if(returning)rv_move(ctx,16,10);else rv_address(ctx,13,8,(int32_t)offset);
  for(unsigned i=0;i<count;++i) {
    AbiPart *p=&parts[i];unsigned cls=(unsigned)p->cls;
    if(returning) {rv_load_chunk(ctx,p->offset,p->size);if(p->leaf==DYN_TYPE_U32)rv_i(ctx,0x1b,15,15,0,0);if(cls>=8)rv_fp_bits(ctx,true,cls>=16,10+cls%8,15);else rv_move(ctx,10+cls,15);}
    else {if(cls>=8)rv_fp_bits(ctx,false,cls>=16,15,10+cls%8);else rv_move(ctx,15,10+cls);rv_store_chunk(ctx,p->offset,p->size);}
  }
  return !ctx->text.failed;
}
static bool a64_struct_result(BackendContext *ctx, const DynIrProgram *ir, DynType type, uint32_t offset);
static void a64_struct_return(BackendContext *ctx, const DynIrProgram *ir, DynType type);
/* Store a returned struct from its result registers into the temporary at offset. */
static bool isa_struct_result(BackendContext *ctx, const DynIrProgram *ir, DynType type, bool sret, uint32_t offset) {
  unsigned parts=0,cls[2],integers=0,floats=0;
  if (sret) return true;
  if (ctx->rv64) return rv_struct_registers(ctx,ir,type,offset,false);
  if (ctx->a64) return a64_struct_result(ctx, ir, type, offset);
  if (ctx->win64) {
    /* A 1, 2, 4 or 8-byte struct arrives in RAX; store exactly its size. */
    uint32_t size,alignment; if (!layout(ir,type,&size,&alignment,0)) return false;
    isa_move(ctx, R_10, R_A); isa_lea(ctx, R_DI, offset); isa_store_chunk(ctx, 0, size);
    return !ctx->text.failed;
  }
  if (!abi_value(ir,type,&parts,cls)) return false;
  for (unsigned part=0;part<parts;++part) {
    if (cls[part]==2) { CODE(0x66,0x49,0x0f,0x7e); byte(ctx, 0xc2+8*floats++); CODE(0x4c,0x89,0x95); }
    else { CODE(0x48,0x89); byte(ctx, integers++?0x95:0x85); }
    word(ctx, offset+part*8);
  }
  return true;
}
/* Calls keep their ABI classification arrays out of the recursive expression
   frame, so nested expressions use little stack per level. */
typedef struct { AbiPart parts[512]; unsigned first[514]; bool indirect[513]; } CallPlan;
static bool plan_argument(BackendContext *ctx, const DynIrProgram *ir, CallPlan *plan, unsigned index, DynType type,
                          unsigned *gp, unsigned *fp, unsigned *argument_count) {
  unsigned count;
  plan->first[index]=*argument_count;
  if (!abi_assign(ctx,ir,type,gp,fp,plan->parts+*argument_count,&count,512-*argument_count,&plan->indirect[index])) return false;
  *argument_count+=count; plan->first[index+1]=*argument_count;
  return true;
}
/* Whether evaluating a scalar expression emits no call, system call or
   runtime helper other than a check's noreturn failure path. */
static bool call_free(const DynIrProgram *ir, DynExprId id, unsigned depth) {
  if (depth > 12 || id >= ir->expression_count) return false;
  const DynIrExpr *e = &ir->expressions[id];
  if (!scalar(ir, e->type)) return false;
  switch (e->kind) {
  case DYN_EXPR_NAME: case DYN_EXPR_INT: case DYN_EXPR_CHAR: case DYN_EXPR_BOOL: case DYN_EXPR_FLOAT:
  case DYN_EXPR_NIL: case DYN_EXPR_GLOBAL:
    return true;
  case DYN_EXPR_BINARY:
    return call_free(ir, e->left, depth + 1) && call_free(ir, e->right, depth + 1);
  case DYN_EXPR_UNARY: case DYN_EXPR_CAST: case DYN_EXPR_CONVERT: case DYN_EXPR_BITCAST:
    return call_free(ir, e->left, depth + 1);
  default:
    return false;
  }
}
/* Value bits of a compile-time scalar: literals (normalized to their type),
   folded integer trees, and in optimized builds const globals initialized by
   such a value. */
static bool constant_bits(BackendContext *ctx, const DynIrProgram *ir, const DynIrExpr *e, uint64_t *bits,
                          unsigned depth) {
  if (depth > 8) return false;
  if (e->kind == DYN_EXPR_FLOAT) {
    if (e->type == DYN_TYPE_F32) { float value = (float)e->floating; uint32_t raw; memcpy(&raw, &value, 4); *bits = raw; }
    else memcpy(bits, &e->floating, 8);
    return e->type == DYN_TYPE_F32 || e->type == DYN_TYPE_F64;
  }
  if ((e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_CHAR || e->kind == DYN_EXPR_BOOL) && integer_type(e->type)) {
    uint64_t n = e->kind == DYN_EXPR_BOOL ? e->boolean : e->integer;
    unsigned width = integer_bits(e->type);
    if (width == 1) n &= 1;
    else if (width < 64) {
      uint64_t mask = (UINT64_C(1) << width) - 1;
      n &= mask;
      if (signed_scalar(e->type) && (n >> (width - 1)) & 1) n |= ~mask;
    }
    *bits = n;
    return true;
  }
  if (ctx->debug_mode) return false;
  if (e->kind == DYN_EXPR_BINARY) return fold_integer(ir, e, bits, 0);
  if (e->kind == DYN_EXPR_GLOBAL && e->integer < ir->global_count) {
    const DynIrGlobal *g = &ir->globals[e->integer];
    if (!g->is_const || g->foreign || g->type != e->type || g->initializer >= ir->expression_count) return false;
    const DynIrExpr *value = &ir->expressions[g->initializer];
    return value->type == e->type && constant_bits(ctx, ir, value, bits, depth + 1);
  }
  return false;
}
static bool call_with(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                      const DynIrExpr *e, unsigned depth, CallPlan *plan) {
  bool indirect=e->kind == DYN_EXPR_INDIRECT_CALL;
  if (e->item_count > 512 || (uint64_t)e->item_start+e->item_count > ir->item_count) return false;
  bool sret=abi_memory(ctx,ir,e->type);
  unsigned argument_count=0,gp=sret&&!ctx->a64?1:0,fp=0,outgoing=0;
  const DynIrFunction *callee=NULL;
  const DynIrFnType *signature=NULL;
  bool packed=false,variadic=false; unsigned fixed=0; DynType pack_type=DYN_TYPE_VOID;
  if (indirect) {
    if (e->integer >= ir->fn_type_count) return false;
    signature=&ir->fn_types[e->integer];
    if ((!signature->variadic && signature->param_count != e->item_count) || signature->param_count>e->item_count ||
        !abi_supported(ir,signature->return_type)) return false;
    variadic=signature->variadic; fixed=signature->param_count;
    for (uint32_t i=0;i<e->item_count;++i) {
      DynType type=i<fixed?ir->fn_type_params[signature->param_start+i]:ir->expressions[ir->items[e->item_start+i].expression].type;
      ctx->rv_variadic=ctx->rv64 && variadic && i>=fixed;
      ctx->winarm_variadic=ctx->winarm64 && variadic;
      bool planned=plan_argument(ctx,ir,plan,i,type,&gp,&fp,&argument_count);
      ctx->winarm_variadic=false;ctx->rv_variadic=false;
      if (!planned) return false;
      if (ctx->darwin && ctx->a64 && i>=fixed) for (unsigned k=plan->first[i];k<argument_count;++k) { plan->parts[k].cls=-1; plan->parts[k].leaf=DYN_TYPE_U64; }
    }
    if (!expression(ctx, ir,f,e->left,depth+1)) return false;
    isa_test(ctx, R_A); guard(ctx, f, CC_NE, GUARD_FUNCTION);
    isa_push(ctx, R_A);
  } else {
    if (e->integer >= ir->function_count) return false;
    callee=&ir->functions[e->integer];
    if (callee->generic || callee->is_main ||
        (!callee->variadic && callee->param_count != e->item_count) || callee->param_count>e->item_count ||
        !abi_supported(ir,callee->return_type)) return false;
    packed=callee->variadic&&!callee->foreign; variadic=callee->variadic&&!packed; fixed=callee->param_count;
    if (packed) {
      if (!dyn_type_is_slice(callee->variadic_type)) return false;
      pack_type=ir->slices[callee->variadic_type-DYN_TYPE_SLICE_BASE].element;
    }
    for (uint32_t i=0;i<(packed?fixed+1:e->item_count);++i) {
      DynType type=i<fixed?ir->params[callee->param_start+i].type:packed?callee->variadic_type:ir->expressions[ir->items[e->item_start+i].expression].type;
      ctx->rv_variadic=ctx->rv64 && variadic && i>=fixed;
      ctx->winarm_variadic=ctx->winarm64 && variadic;
      bool planned=plan_argument(ctx,ir,plan,i,type,&gp,&fp,&argument_count);
      ctx->winarm_variadic=false;ctx->rv_variadic=false;
      if (!planned) return false;
      /* Apple AArch64 passes every variadic argument on the stack. */
      if (ctx->darwin && ctx->a64 && variadic && i>=fixed) for (unsigned k=plan->first[i];k<argument_count;++k) { plan->parts[k].cls=-1; plan->parts[k].leaf=DYN_TYPE_U64; }
    }
  }
  /* Keep arguments on the expression stack in source order. Nested calls
     cannot clobber earlier arguments; registers are loaded only afterwards.
     On x86-64 the last argument, when it is one integer register value and
     nothing runs between it and the call, moves straight into its register
     instead of being pushed and reloaded. */
  bool protected_call=ctx->defer_count && !ctx->unwinding;
  bool held=false;
  if (!ctx->a64 && !ctx->rv64 && !indirect && !packed && !protected_call && !variadic && e->item_count) {
    uint32_t last=e->item_count-1;
    DynType type=ir->expressions[ir->items[e->item_start+last].expression].type;
    bool registers=true;
    for (uint32_t i=0;i<argument_count;++i) registers=registers && plan->parts[i].cls>=0;
    held=registers && !plan->indirect[last] && !aggregate(ir,type) && !descriptor(type) &&
         plan->first[last]+1==plan->first[last+1] && plan->first[last+1]==argument_count &&
         plan->parts[plan->first[last]].cls<8;
  }
  for (uint32_t i = 0; i < (packed?fixed:e->item_count); ++i) {
    DynExprId argument=ir->items[e->item_start + i].expression;
    if (!expression(ctx, ir, f, argument, depth + 1)) return false;
    DynType type=ir->expressions[argument].type;
    if (plan->indirect[i]) {
      /* AAPCS64: pass a pointer to a caller-owned copy the callee may modify. */
      uint32_t size,alignment,copy=ctx->copy_offsets[argument];
      if (!copy || !layout(ir,type,&size,&alignment,0)) return false;
      isa_push(ctx, R_A); isa_lea(ctx, R_A, copy); isa_pop(ctx, R_C);
      isa_push(ctx, R_A); isa_move(ctx, R_A, R_C); isa_copy(ctx, size);
      isa_lea(ctx, R_A, copy); isa_push(ctx, R_A);
    } else if (aggregate(ir,type)) {
      isa_move(ctx, R_11, R_A);
      for (unsigned part=plan->first[i];part<plan->first[i+1];++part) {
        load_chunk(ctx, plan->parts[part].offset, plan->parts[part].size);
        if(ctx->rv64 && plan->parts[part].leaf==DYN_TYPE_U32)rv_i(ctx,0x1b,15,15,0,0);
        isa_push(ctx, R_10);
      }
    } else if (held && i+1==e->item_count) {
      unsigned target=x86_argument_register(ctx, plan->parts[plan->first[i]].cls);
      byte(ctx, 0x48 | (target >= 8)); byte(ctx, 0x89); byte(ctx, 0xc0 | (target & 7));
    } else { if(ctx->rv64 && type==DYN_TYPE_U32)rv_i(ctx,0x1b,10,10,0,0);isa_push(ctx, R_A); if (descriptor(type)) isa_push(ctx, R_D); }
  }
  if (packed) {
    unsigned count=e->item_count-fixed; uint32_t offset=ctx->pack_offsets[e-ir->expressions],size,alignment;
    if (!layout(ir,pack_type,&size,&alignment,0) || (count && !offset)) return false;
    uint32_t boxed=offset+(size*count+7)/8*8;
    for (unsigned i=0;i<count;++i) {
      DynExprId argument=ir->items[e->item_start+fixed+i].expression;
      DynType type=ir->expressions[argument].type;
      if (pack_type==DYN_TYPE_ANY) {
        uint32_t value_size,a; if (!layout(ir,type,&value_size,&a,0)) return false;
        isa_lea(ctx, R_A, boxed);
        if (!initialize(ctx,ir,f,type,argument,depth+1)) return false;
        isa_immediate(ctx, R_A, type); isa_store(ctx, R_A, offset+i*size);
        isa_lea(ctx, R_A, boxed); isa_store(ctx, R_A, offset+i*size+8);
        boxed+=(value_size?value_size+7:8)/8*8;
      } else {
        isa_lea(ctx, R_A, offset+i*size);
        if (!initialize(ctx,ir,f,pack_type,argument,depth+1)) return false;
      }
    }
    if (count) isa_lea(ctx, R_A, offset); else isa_zero(ctx, R_A);
    isa_push(ctx, R_A); isa_small_immediate(ctx, R_A, count); isa_push(ctx, R_A);
  }
  if (protected_call && !protect_call(ctx, ir,f)) return false;
  unsigned slot=isa_slot(ctx);
  uint32_t outgoing_bytes=0, pushed=argument_count-(held?1u:0u);
  for (uint32_t i=0;i<pushed;++i) {
    if (plan->parts[i].cls<0) { ++outgoing; stack_slot(ctx,&plan->parts[i],&outgoing_bytes); continue; }
    isa_argument_load(ctx, plan->parts[i].cls, slot*(pushed-i-1));
    /* Microsoft x64 variadic callees read floating arguments from the GP register too. */
    if (ctx->win64 && variadic && plan->parts[i].cls>=8) isa_argument_load(ctx, plan->parts[i].cls-8, slot*(pushed-i-1));
  }
  /* Outgoing stack arguments occupy eight-byte slots (Apple packs narrower
     scalars); the area keeps SP 16-byte aligned. */
  unsigned reserved=(ctx->a64||ctx->rv64) ? (outgoing_bytes+15)/16*16 : (outgoing+((ctx->stack_slots+outgoing)&1))*8;
  isa_reserve(ctx, reserved);
  for (uint32_t i=0;i<pushed;++i) if (plan->parts[i].cls<0)
    isa_stack_store(ctx, reserved+slot*(pushed-i-1), plan->parts[i].stack, stack_width(ctx,&plan->parts[i]));
  if (sret) isa_result_pointer(ctx, ctx->temporary_offsets[e-ir->expressions]);
  if (variadic && !ctx->a64 && !ctx->rv64 && !ctx->win64) { byte(ctx,0xb8); word(ctx,fp); } /* SysV vector register count in AL. */
  if (indirect) isa_call_stack(ctx, reserved+argument_count*slot);
  else isa_call_symbol(ctx, ctx->function_symbols[e->integer]);
  isa_release(ctx, (pushed + indirect) * slot + reserved);
  ctx->stack_slots -= pushed + indirect;
  if (raw_aggregate(ir,e->type)) {
    DynExprId id=(DynExprId)(e-ir->expressions); if (!ctx->temporary_offsets[id]) return false;
    if (!sret) {
      if (ctx->a64 || ctx->rv64) return false; /* These targets return raw aggregates through memory. */
      ArrayPart *leaves=ctx->call_leaves; unsigned count=0,gp=0,fp=0;
      if (!array_parts(ir,e->type,0,leaves,&count,0)) return false;
      /* Preserve the three GP/two SSE return registers before scratch loads. */
      CODE(0x50,0x52,0x51,0x66,0x49,0x0f,0x7e,0xc2,0x41,0x52,0x66,0x49,0x0f,0x7e,0xca,0x41,0x52); ctx->stack_slots+=5;
      for (unsigned part=0;part<count;++part) {
        DynType type=leaves[part].type; uint32_t at=ctx->temporary_offsets[id]+leaves[part].offset;
        if (float_type(type) && fp>=2) {
          byte(ctx, type==DYN_TYPE_F32?0xd9:0xdd); byte(ctx, 0x9d); word(ctx, at); ++fp;
        } else {
          unsigned from=float_type(type)?3+fp++:gp++;
          isa_peek(ctx, R_A, 4-from); normalize(ctx, type);
          isa_lea(ctx, R_11, at); store_memory(ctx, type);
        }
      }
      CODE(0x48,0x83,0xc4,40); ctx->stack_slots-=5;
    }
    isa_lea(ctx, R_A, ctx->temporary_offsets[id]);
  } else if (dyn_type_is_struct(e->type)) {
    DynExprId id=(DynExprId)(e-ir->expressions);
    if (!ctx->temporary_offsets[id] || !isa_struct_result(ctx, ir, e->type, sret, ctx->temporary_offsets[id])) return false;
    isa_lea(ctx, R_A, ctx->temporary_offsets[id]);
  }
  if (float_type(e->type)) isa_float_result(ctx, e->type==DYN_TYPE_F32); /* floating result to bit carrier */
  normalize(ctx, e->type);
  if (protected_call) {
    isa_store(ctx, R_A, ctx->call_offset);
    if (descriptor(e->type)) isa_store(ctx, R_D, ctx->call_offset+8);
    bool padding=isa_align_call(ctx);
    isa_lea(ctx, isa_argument(ctx, 0), ctx->unwind_offset); runtime_call(ctx, 5);
    isa_unalign_call(ctx, padding);
    isa_load(ctx, R_A, ctx->call_offset);
    if (descriptor(e->type)) isa_load(ctx, R_D, ctx->call_offset+8);
  }
  return !ctx->text.failed && !ctx->rodata.failed && !ctx->relocation_failed;
}
/* Argument classes live across nested argument evaluation, so each call level
   owns a heap block; array leaves are filled and consumed without recursion. */
static bool call_value(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                       const DynIrExpr *e, unsigned depth) {
  CallPlan *plan = malloc(sizeof(*plan));
  if (!plan) return false;
  bool ok = call_with(ctx, ir, f, e, depth, plan);
  free(plan);
  return ok;
}
static bool expression_value(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                             const DynIrExpr *e, unsigned depth) {
  if (e->kind==DYN_EXPR_SYSCALL) {
    if (ctx->win64 || ctx->winarm64) return false; /* no Windows system call runtime */
    if (e->item_count>7 || (uint64_t)e->item_start+e->item_count>ir->item_count) return false;
    for (unsigned i=0;i<7;++i) {
      if (i<e->item_count) {
        DynExprId id=ir->items[e->item_start+i].expression;
        if (id>=ir->expression_count || !scalar(ir,ir->expressions[id].type) || !expression(ctx,ir,f,id,depth+1)) return false;
      } else isa_zero(ctx, R_A);
      isa_push(ctx, R_A);
    }
    isa_syscall(ctx);
    return !ctx->text.failed && !ctx->relocation_failed;
  }
  if (e->kind==DYN_EXPR_ENUM) {
    if (!dyn_type_is_enum(e->type) || e->type-DYN_TYPE_ENUM_BASE>=ir->enum_count || e->integer>=ir->variant_count) return false;
    const DynIrEnum *en=&ir->enums[e->type-DYN_TYPE_ENUM_BASE];
    const DynIrVariant *variant=&ir->variants[e->integer];
    if (!en->has_payload) { isa_immediate(ctx, R_A, variant->tag); normalize(ctx,e->type); return true; }
    DynExprId id=(DynExprId)(e-ir->expressions); uint32_t offset=ctx->temporary_offsets[id];
    if (!offset) return false;
    isa_lea(ctx, R_A, offset);
    if (!initialize(ctx,ir,f,e->type,DYN_NO_EXPR,depth+1)) return false;
    isa_lea(ctx, R_11, offset); isa_immediate(ctx, R_A, variant->tag); store_memory(ctx,en->tag_type);
    if (variant->payload_type!=DYN_TYPE_VOID) {
      if (e->item_count!=1 || e->item_start>=ir->item_count) return false;
      uint32_t tag_size=(memory_bits(en->tag_type)+7)/8, a=(uint32_t)en->payload_alignment;
      isa_lea(ctx, R_A, offset+((tag_size+a-1)&~(a-1)));
      if (!initialize(ctx,ir,f,variant->payload_type,ir->items[e->item_start].expression,depth+1)) return false;
    }
    isa_lea(ctx, R_A, offset); return !ctx->text.failed;
  }
  if (e->kind==DYN_EXPR_CONVERT && e->type==DYN_TYPE_ANY) {
    if (e->left>=ir->expression_count) return false;
    uint32_t offset=ctx->temporary_offsets[e-ir->expressions]; if (!offset) return false;
    DynType source=ir->expressions[e->left].type;
    isa_lea(ctx, R_A, offset);
    if (!initialize(ctx,ir,f,source,e->left,depth+1)) return false;
    isa_lea(ctx, R_D, offset); isa_immediate(ctx, R_A, source); return !ctx->text.failed;
  }
  if (e->kind==DYN_EXPR_STRUCT || e->kind==DYN_EXPR_ARRAY) {
    DynExprId id=(DynExprId)(e-ir->expressions);
    if (ctx->literal_offsets[id]) {
      isa_local_address(ctx, R_A, ctx->literals_symbol, ctx->literal_offsets[id]-1);
      return !ctx->text.failed && !ctx->relocation_failed;
    }
    if (!ctx->temporary_offsets[id]) return false;
    isa_lea(ctx, R_A, ctx->temporary_offsets[id]);
    return initialize(ctx, ir,f,e->type,id,depth+1);
  }
  if (descriptor(e->type)) {
    if (e->kind==DYN_EXPR_NIL) { isa_zero(ctx, R_A); isa_zero(ctx, R_D); return true; }
    if (e->kind==DYN_EXPR_STRING) {
      if (e->integer>=ir->string_count) return false;
      const DynIrString *string=&ir->strings[e->integer]; size_t at=literal(ctx, (const char*)string->data,string->length);
      isa_rodata_address(ctx, R_A, at);
      isa_immediate(ctx, R_D, string->length); return !ctx->rodata.failed;
    }
    if (e->kind==DYN_EXPR_CONVERT) {
      return e->left<ir->expression_count && descriptor(ir->expressions[e->left].type) && expression(ctx, ir,f,e->left,depth+1);
    }
    if (e->kind==DYN_EXPR_GLOBAL || e->kind==DYN_EXPR_NAME || e->kind==DYN_EXPR_FIELD || e->kind==DYN_EXPR_INDEX ||
        (e->kind==DYN_EXPR_UNARY && e->op==DYN_OP_DEREF)) {
      if (!address(ctx, ir,f,(DynExprId)(e-ir->expressions),depth+1)) return false;
      isa_load_descriptor(ctx); return !ctx->text.failed;
    }
    if (e->kind==DYN_EXPR_SLICE) {
      if (e->left>=ir->expression_count) return false;
      DynType base=ir->expressions[e->left].type; bool raw=dyn_type_is_pointer(base);
      if (dyn_type_is_array(base)) {
        if (base-DYN_TYPE_ARRAY_BASE>=ir->array_count || !address(ctx, ir,f,e->left,depth+1)) return false;
        isa_immediate(ctx, R_D, ir->arrays[base-DYN_TYPE_ARRAY_BASE].length);
      } else if (raw) {
        if (base-DYN_TYPE_POINTER_BASE>=ir->pointer_count || !expression(ctx, ir,f,e->left,depth+1)) return false;
        checked_address(ctx, f,ir->pointers[base-DYN_TYPE_POINTER_BASE].pointee); isa_zero(ctx, R_D);
      } else if (!descriptor(base) || !expression(ctx, ir,f,e->left,depth+1)) return false;
      isa_push(ctx, R_A); isa_push(ctx, R_D);
      if (e->right==DYN_NO_EXPR) isa_zero(ctx, R_A);
      else if (!index_expression(ctx, ir,f,e->right,depth+1)) return false;
      isa_push(ctx, R_A);
      if (e->integer==DYN_NO_EXPR && !raw) isa_peek_short(ctx, R_A, 1);
      else if (!index_expression(ctx, ir,f,(DynExprId)e->integer,depth+1)) return false;
      isa_pop(ctx, R_C); /* start C, end A */
      isa_compare(ctx, R_C, R_A); guard(ctx, f, CC_BE, GUARD_SLICE_ORDER);
      if (!raw) { isa_compare_top(ctx); guard(ctx, f, CC_BE, GUARD_SLICE_BOUNDS); }
      isa_move(ctx, R_D, R_A); isa_alu(ctx, ALU_SUB, R_D, R_C); isa_drop(ctx, 1); isa_pop(ctx, R_A);
      DynType element=e->type==DYN_TYPE_STRING?DYN_TYPE_U8:ir->slices[e->type-DYN_TYPE_SLICE_BASE].element;
      uint32_t size,alignment; if (!layout(ir,element,&size,&alignment,0)) return false;
      isa_scale(ctx, R_C, size); isa_alu(ctx, ALU_ADD, R_A, R_C); return !ctx->text.failed;
    }
  }
  if (!scalar(ir, e->type) && (e->kind==DYN_EXPR_GLOBAL || e->kind==DYN_EXPR_NAME || e->kind==DYN_EXPR_FIELD || e->kind==DYN_EXPR_INDEX ||
      (e->kind==DYN_EXPR_UNARY && e->op==DYN_OP_DEREF)))
    return address(ctx, ir,f,(DynExprId)(e-ir->expressions),depth+1);
  if (e->kind==DYN_EXPR_FIELD || e->kind==DYN_EXPR_INDEX) {
    if (!scalar(ir, e->type) || !address(ctx, ir,f,(DynExprId)(e-ir->expressions),depth+1)) return false;
    load_memory(ctx, e->type); return !ctx->text.failed;
  }
  if (e->kind==DYN_EXPR_LEN) {
    if (e->left>=ir->expression_count) return false;
    DynType type=ir->expressions[e->left].type;
    if (descriptor(type)) {
      if (!expression(ctx, ir,f,e->left,depth+1)) return false;
      isa_move(ctx, R_A, R_D); return !ctx->text.failed;
    }
    if (!dyn_type_is_array(type) || type-DYN_TYPE_ARRAY_BASE>=ir->array_count) return false;
    isa_immediate(ctx, R_A, ir->arrays[type-DYN_TYPE_ARRAY_BASE].length); return !ctx->text.failed;
  }
  if (!value_type(ir, e->type) && !((e->type==DYN_TYPE_VOID || abi_supported(ir,e->type)) && (e->kind==DYN_EXPR_CALL || e->kind==DYN_EXPR_INDIRECT_CALL))) return false;
  if (e->kind == DYN_EXPR_FLOAT) {
    uint64_t bits=0;
    if (e->type==DYN_TYPE_F32) { float value=(float)e->floating; uint32_t raw; memcpy(&raw,&value,4); bits=raw; }
    else memcpy(&bits,&e->floating,8);
    isa_immediate(ctx, R_A, bits); return !ctx->text.failed;
  }
  uint64_t folded;
  if (!ctx->debug_mode && e->kind == DYN_EXPR_BINARY && fold_integer(ir, e, &folded, 0)) {
    isa_immediate(ctx, R_A, folded);
    return !ctx->text.failed;
  }
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_CHAR || e->kind == DYN_EXPR_BOOL) {
    uint64_t n = e->kind == DYN_EXPR_BOOL ? e->boolean : e->integer;
    isa_immediate(ctx, R_A, n); normalize(ctx, e->type);
    return true;
  }
  if (e->kind == DYN_EXPR_NAME) {
    uint32_t offset;
    if (!local_slot(ctx, f, e->integer, &offset)) return false;
    isa_load(ctx, R_A, offset);
    if (ctx->local_alias[e->integer-f->local_start]) load_memory(ctx,e->type);
    normalize(ctx, e->type);
    return true;
  }
  if (e->kind == DYN_EXPR_GLOBAL) {
    uint64_t bits;
    if (scalar(ir, e->type) && constant_bits(ctx, ir, e, &bits, 0)) { isa_immediate(ctx, R_A, bits); return !ctx->text.failed; }
    if (e->integer >= ir->global_count || !ctx->global_symbols[e->integer]) return false;
    isa_symbol_address(ctx, R_A, ctx->global_symbols[e->integer]);
    load_memory(ctx, e->type); return !ctx->text.failed && !ctx->relocation_failed;
  }
  if (e->kind == DYN_EXPR_FUNCTION) {
    if (e->integer >= ir->function_count || !ctx->function_symbols[e->integer]) return false;
    isa_symbol_address(ctx, R_A, ctx->function_symbols[e->integer]);
    return !ctx->text.failed && !ctx->relocation_failed;
  }
  if (e->kind == DYN_EXPR_NIL && (dyn_type_is_pointer(e->type) || e->type==DYN_TYPE_RAWPTR)) { isa_zero(ctx, R_A); return true; }
  if (e->kind == DYN_EXPR_CALL || e->kind == DYN_EXPR_INDIRECT_CALL) return call_value(ctx, ir, f, e, depth);
  if (e->kind == DYN_EXPR_BITCAST) {
    if (e->left>=ir->expression_count || !scalar(ir, ir->expressions[e->left].type) ||
        !((integer_type(e->type)||float_type(e->type)) &&
          (integer_type(ir->expressions[e->left].type)||float_type(ir->expressions[e->left].type))) ||
        memory_bits(e->type)!=memory_bits(ir->expressions[e->left].type) ||
        !expression(ctx, ir,f,e->left,depth+1)) return false;
    normalize(ctx, e->type); return !ctx->text.failed;
  }
  if (e->kind == DYN_EXPR_CAST || e->kind == DYN_EXPR_CONVERT) {
    if (e->left >= ir->expression_count) return false;
    DynType from=storage_type(ir,ir->expressions[e->left].type);
    if (dyn_type_is_enum(e->type)) {
      if (payload_enum(ir,e->type) || !integer_type(from) || !expression(ctx,ir,f,e->left,depth+1)) return false;
      const DynIrEnum *en=&ir->enums[e->type-DYN_TYPE_ENUM_BASE];
      isa_match_begin(ctx);
      for (unsigned i=0;i<en->variant_count;++i) {
        uint64_t tag=ir->variants[en->variant_start+i].tag; unsigned bits=integer_bits(en->tag_type);
        if (signed_scalar(en->tag_type) && bits<64 && (tag>>(bits-1)&1)) tag|=UINT64_MAX<<bits;
        if (signed_scalar(from)!=signed_scalar(en->tag_type) && (int64_t)tag<0) continue;
        isa_match_tag(ctx, tag);
      }
      isa_match_test(ctx); guard(ctx, f, CC_NE, GUARD_ENUM); normalize(ctx,e->type); return !ctx->text.failed;
    }
    bool from_pointer=dyn_type_is_pointer(from)||from==DYN_TYPE_RAWPTR;
    bool to_pointer=dyn_type_is_pointer(e->type)||e->type==DYN_TYPE_RAWPTR;
    bool pointer_conversion=(from_pointer||to_pointer) &&
      (from_pointer||integer_type(from)) && (to_pointer||integer_type(e->type));
    bool integer_float=integer_type(from)&&float_type(e->type), float_integer=float_type(from)&&integer_type(e->type);
    if (!((integer_type(e->type)&&integer_type(from)) || (float_type(e->type)&&float_type(from)) || pointer_conversion || integer_float || float_integer) ||
        !expression(ctx, ir,f,e->left,depth+1)) return false;
    if (integer_float) {
      isa_int_to_float(ctx, e->type==DYN_TYPE_F32, !signed_scalar(from) && integer_bits(from)==64);
      return !ctx->text.failed;
    }
    if (float_integer) {
      isa_float_to_int(ctx, from==DYN_TYPE_F32, !signed_scalar(e->type) && integer_bits(e->type)==64);
      normalize(ctx, e->type); return !ctx->text.failed;
    }
    /* LLVM inttoptr zero-extends the source bitwidth, even for signed integers. */
    if (to_pointer && integer_type(from) && integer_bits(from)<64) {
      isa_immediate(ctx, R_D, (UINT64_C(1)<<integer_bits(from))-1); isa_alu(ctx, ALU_AND, R_A, R_D);
    }
    if (float_type(e->type) && e->type!=from) isa_float_convert(ctx, from==DYN_TYPE_F32);
    normalize(ctx, e->type); return !ctx->text.failed;
  }
  if (e->kind == DYN_EXPR_UNARY) {
    if (e->op==DYN_OP_ADDRESS) {
      if (e->left<ir->expression_count && ir->expressions[e->left].kind==DYN_EXPR_FUNCTION) return expression(ctx, ir,f,e->left,depth+1);
      return address(ctx, ir,f,e->left,depth+1);
    }
    if (e->op==DYN_OP_DEREF) {
      if (dyn_type_is_function(e->type) || !expression(ctx, ir,f,e->left,depth+1)) return false;
      checked_address(ctx, f,e->type); load_memory(ctx, e->type); return !ctx->text.failed;
    }

    if (float_type(e->type)) {
      if (e->op!=DYN_OP_NEG || !expression(ctx, ir,f,e->left,depth+1)) return false;
      isa_immediate(ctx, R_D, UINT64_C(1)<<(e->type==DYN_TYPE_F32?31:63));
      isa_alu(ctx, ALU_XOR, R_A, R_D); return !ctx->text.failed;
    }
    if (e->op != DYN_OP_BIT_NOT && e->op != DYN_OP_NOT &&
        e->op != DYN_OP_NEG) return false;
    /* The checked frontend marks the signed minimum literal specially: its
       unsigned magnitude is not an independently representable signed value. */
    if (e->op == DYN_OP_NEG && e->boolean) {
      if (e->left >= ir->expression_count || ir->expressions[e->left].kind != DYN_EXPR_INT) return false;
      isa_immediate(ctx, R_A, UINT64_C(0) - ir->expressions[e->left].integer);
      return true;
    }
    if (!expression(ctx, ir, f, e->left, depth + 1)) return false;
    if (e->op == DYN_OP_BIT_NOT) isa_unary(ctx, UNARY_NOT);
    else if (e->op == DYN_OP_NEG) {
      isa_unary(ctx, UNARY_NEGATE);
      /* Negation borrows exactly when the operand is nonzero. */
      if (!e->wrap) guard(ctx, f, signed_scalar(e->type) ? CC_NO : CC_AE, GUARD_OVERFLOW);
    }
    else isa_unary(ctx, UNARY_BOOL_NOT);
    bool check=e->op == DYN_OP_NEG && !e->wrap && integer_bits(e->type)<64;
    if (check) isa_move(ctx, R_10, R_A);
    normalize(ctx, e->type);
    if (check) { isa_compare(ctx, R_A, R_10); guard(ctx, f, CC_E, GUARD_OVERFLOW); }
    return !ctx->text.failed;

  }
  if (e->kind != DYN_EXPR_BINARY) return false;
  if (e->op == DYN_OP_LOGICAL_AND || e->op == DYN_OP_LOGICAL_OR) {
    if (!expression(ctx, ir, f, e->left, depth + 1)) return false;
    isa_test(ctx, R_A);
    size_t skip = isa_branch(ctx, e->op == DYN_OP_LOGICAL_AND ? CC_E : CC_NE);
    if (!expression(ctx, ir, f, e->right, depth + 1)) return false;
    isa_patch(ctx, skip, ctx->text.n);
    return !ctx->text.failed && !ctx->rodata.failed && !ctx->relocation_failed;
  }
  bool comparison = e->op >= DYN_OP_EQ && e->op <= DYN_OP_GE;
  if (e->op != DYN_OP_BIT_AND && e->op != DYN_OP_BIT_OR &&
      e->op != DYN_OP_BIT_XOR &&
      e->op != DYN_OP_ADD && e->op != DYN_OP_SUB && e->op != DYN_OP_MUL &&
      e->op != DYN_OP_DIV && e->op != DYN_OP_REM &&
      e->op != DYN_OP_SHL && e->op != DYN_OP_SHR && !comparison) return false;
  if (!expression(ctx, ir, f, e->left, depth + 1)) return false;
  /* A constant or plain local right operand loads straight into C, with no
     push and pop around it. */
  const DynIrExpr *right=&ir->expressions[e->right];
  uint64_t bits;
  if (constant_bits(ctx, ir, right, &bits, 0)) {
    bool comparison = e->op >= DYN_OP_EQ && e->op <= DYN_OP_GE;
    if (comparison && !float_type(ir->expressions[e->left].type) &&
        isa_compare_immediate(ctx, bits)) {
      ctx->compared = true;
      bool ok = binary_result(ctx, ir, f, e);
      ctx->compared = false;
      return ok;
    }
    isa_immediate(ctx, R_C, bits);
    return binary_result(ctx, ir,f,e);
  }
  uint32_t slot;
  if (right->kind == DYN_EXPR_NAME && local_slot(ctx, f, right->integer, &slot) &&
      !ctx->local_alias[right->integer-f->local_start] &&
      !payload_enum(ir, right->type) && integer_bits(storage_type(ir, right->type)) == 64) {
    isa_load(ctx, R_C, slot);
    return binary_result(ctx, ir,f,e);
  }
  if (!ctx->a64 && !ctx->rv64 && !ctx->holding && call_free(ir, e->right, 0)) {
    CODE(0x49, 0x89, 0xc1); /* mov r9, rax */
    ctx->holding = true;
    bool ok = expression(ctx, ir, f, e->right, depth + 1);
    ctx->holding = false;
    if (!ok) return false;
    isa_move(ctx, R_C, R_A);
    CODE(0x4c, 0x89, 0xc8); /* mov rax, r9 */
    return binary_result(ctx, ir,f,e);
  }
  isa_push(ctx, R_A); /* preserve left while evaluating the right operand */
  if (!expression(ctx, ir, f, e->right, depth + 1)) return false;
  isa_move(ctx, R_C, R_A); isa_pop(ctx, R_A);
  return binary_result(ctx, ir,f,e);
}
static bool binary_result(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f, const DynIrExpr *e) {
  bool comparison=e->op>=DYN_OP_EQ && e->op<=DYN_OP_GE;
  DynType operand_type=ir->expressions[e->left].type;
  if (float_type(operand_type)) {
    bool f32=operand_type==DYN_TYPE_F32;
    isa_float_operands(ctx, f32);
    if (e->op==DYN_OP_REM) {
      bool padding=isa_align_call(ctx);
      runtime_call(ctx, f32?8:7);
      isa_unalign_call(ctx, padding);
      isa_float_result(ctx, f32); return !ctx->text.failed && !ctx->relocation_failed;
    }
    if (comparison) isa_float_compare(ctx, f32, e->op-DYN_OP_EQ);
    else {
      int op=e->op==DYN_OP_ADD?FLOAT_ADD:e->op==DYN_OP_SUB?FLOAT_SUB:e->op==DYN_OP_MUL?FLOAT_MUL:e->op==DYN_OP_DIV?FLOAT_DIV:-1;
      if (op<0) return false;
      isa_float_arithmetic(ctx, f32, op);
    }
    return !ctx->text.failed;
  }
  if (comparison) {
    static const Cond signed_conditions[] = {CC_E, CC_NE, CC_L, CC_LE, CC_G, CC_GE};
    static const Cond unsigned_conditions[] = {CC_E, CC_NE, CC_B, CC_BE, CC_A, CC_AE};
    const Cond *conditions = signed_scalar(storage_type(ir,ir->expressions[e->left].type))
        ? signed_conditions : unsigned_conditions;
    if (!ctx->compared) isa_compare(ctx, R_A, R_C);
    if (ctx->flags_for == e) {
      ctx->flags_for = NULL;
      ctx->flags_from = e;
      ctx->flags_condition = conditions[e->op - DYN_OP_EQ];
    } else isa_set(ctx, conditions[e->op - DYN_OP_EQ]);
    return !ctx->text.failed;
  }
  if (!integer_type(operand_type)) return false;
  bool sign=signed_scalar(e->type);
  switch (e->op) {
  case DYN_OP_ADD: isa_alu(ctx, ALU_ADD, R_A, R_C); break;
  case DYN_OP_SUB: isa_alu(ctx, ALU_SUB, R_A, R_C); break;
  case DYN_OP_MUL: isa_multiply(ctx, !e->wrap, sign); break;
  case DYN_OP_DIV: case DYN_OP_REM:
    divide(ctx, f, sign, e->op == DYN_OP_REM, integer_bits(e->type)); break;
  case DYN_OP_SHL: case DYN_OP_SHR:
    shift(ctx, f, sign, e->op == DYN_OP_SHL, e->wrap, integer_bits(e->type)); break;
  case DYN_OP_BIT_AND: isa_alu(ctx, ALU_AND, R_A, R_C); break;
  case DYN_OP_BIT_OR: isa_alu(ctx, ALU_OR, R_A, R_C); break;
  case DYN_OP_BIT_XOR: isa_alu(ctx, ALU_XOR, R_A, R_C); break;
  default: return false;
  }
  if (!e->wrap && (e->op == DYN_OP_ADD || e->op == DYN_OP_SUB || e->op == DYN_OP_MUL)) {
    int op=e->op==DYN_OP_ADD?ALU_ADD:e->op==DYN_OP_SUB?ALU_SUB:ALU_ADD+16;
    guard(ctx, f, isa_overflow_condition(ctx, op, sign), GUARD_OVERFLOW);
  }
  bool check=!e->wrap && integer_bits(e->type)<64 &&
    (e->op==DYN_OP_ADD || e->op==DYN_OP_SUB || e->op==DYN_OP_MUL || e->op==DYN_OP_SHL);
  if (check) isa_move(ctx, R_10, R_A);
  normalize(ctx, e->type);
  if (check) { isa_compare(ctx, R_A, R_10); guard(ctx, f, CC_E, GUARD_OVERFLOW); }
  return !ctx->text.failed && !ctx->rodata.failed && !ctx->relocation_failed;
}
static void return_value(BackendContext *ctx, DynType type) {
  const DynIrProgram *ir=ctx->active_ir;
  bool sret=abi_memory(ctx,ctx->active_ir,type);
  if (aggregate(ir, type)) { save_struct(ctx, ctx->return_offset,type); isa_lea(ctx, R_A, ctx->return_offset); }
  if (sret) {
    uint32_t size,alignment; if (!layout(ctx->active_ir,type,&size,&alignment,0)) { ctx->text.failed=true; return; }
    isa_move(ctx, R_11, R_A); isa_load(ctx, R_DI, ctx->sret_offset);
    for (unsigned part=0;part<(size+7)/8;++part) {
      unsigned bytes=size-part*8>8?8:size-part*8; load_chunk(ctx, part*8,bytes);
      isa_store_chunk(ctx, part*8, bytes);
    }
    isa_move(ctx, R_A, R_DI);
  }
  if (ctx->debug_mode) {
    if (aggregate(ir, type) && !sret) {
      /* The aggregate snapshot may occupy rbp-8 itself in a zero-local function. */
      runtime_call(ctx, 2); isa_lea(ctx, R_A, ctx->return_offset);
    } else isa_trace_pop(ctx, descriptor(type));
  }
  if (ctx->rv64 && aggregate(ir,type) && !sret) {if(!rv_struct_registers(ctx,ir,type,0,true))ctx->text.failed=true;isa_return(ctx);return;}
  if (ctx->a64 && aggregate(ir, type) && !sret) { a64_struct_return(ctx, ir, type); isa_return(ctx); return; }
  if (ctx->win64 && aggregate(ir, type) && !sret) {
    uint32_t size,alignment; if (!layout(ir,type,&size,&alignment,0)) { ctx->text.failed=true; return; }
    isa_move(ctx, R_11, R_A); load_chunk(ctx, 0, size); isa_move(ctx, R_A, R_10); isa_return(ctx); return;
  }
  if (raw_aggregate(ir,type) && !sret) {
    ArrayPart leaves[512]; unsigned count=0,gp=0,fp=0; uint32_t x87_offset[2]; DynType x87_type[2]; unsigned x87=0;
    if (!array_parts(ctx->active_ir,type,0,leaves,&count,0)) { ctx->text.failed=true; return; }
    CODE(0x49,0x89,0xc3);
    for (unsigned part=0;part<count;++part) {
      DynType leaf=leaves[part].type;
      if (float_type(leaf) && fp>=2) { x87_offset[x87]=ctx->return_offset+leaves[part].offset;x87_type[x87++]=leaf;++fp;continue; }
      load_chunk(ctx, leaves[part].offset,(memory_bits(leaf)+7)/8);
      if (float_type(leaf)) { CODE(0x66,0x49,0x0f,0x6e); byte(ctx, 0xc2+8*fp++); }
      else { CODE(0x4c,0x89); byte(ctx, gp==0?0xd0:gp==1?0xd2:0xd1); ++gp; }
    }
    while (x87) { --x87; byte(ctx, x87_type[x87]==DYN_TYPE_F32?0xd9:0xdd);byte(ctx, 0x85);word(ctx, x87_offset[x87]); }
  }
  if (dyn_type_is_struct(type) && !sret) {
    unsigned parts,cls[2],integers=0,floats=0; uint32_t size,alignment;
    if (!abi_value(ctx->active_ir,type,&parts,cls) || !layout(ctx->active_ir,type,&size,&alignment,0)) { ctx->text.failed=true; return; }
    CODE(0x49,0x89,0xc3);
    for (unsigned part=0;part<parts;++part) {
      load_chunk(ctx, part*8,size-part*8>8?8:size-part*8);
      if (cls[part]==2) { CODE(0x66,0x49,0x0f,0x6e); byte(ctx, 0xc2+8*floats++); }
      else { CODE(0x4c,0x89); byte(ctx, integers++?0xd2:0xd0); }
    }
  }
  if(ctx->rv64 && type==DYN_TYPE_U32)rv_i(ctx,0x1b,10,10,0,0);
  if (float_type(type)) {if(ctx->rv64)rv_fp_bits(ctx,true,type==DYN_TYPE_F32,10,10);else isa_a_to_float(ctx);}
  isa_return(ctx);
}
/* Forward branches form bounded linked lists in their pending displacement words. */
static void pending_jump(BackendContext *ctx, int condition, size_t *head) {
  size_t at = isa_branch(ctx, condition);
  patch_word(ctx, at, (uint32_t)*head); *head = at;
}
static bool resolve_jumps(BackendContext *ctx, size_t head, size_t destination) {
  if (ctx->text.failed) return false;
  while (head != UINT32_MAX) {
    if (head > ctx->text.n || ctx->text.n - head < 4) return false;
    uint32_t next; memcpy(&next, ctx->text.data + head, 4);
    isa_patch(ctx, head, destination); head = next;
  }
  return true;
}
static void reset_scratch(BackendContext *ctx) {
  for (size_t i=0;i<ctx->touched_expr_count;++i) {
    uint32_t id=ctx->touched_exprs[i];
    ctx->captured_offsets[id]=ctx->temporary_offsets[id]=ctx->pack_offsets[id]=ctx->copy_offsets[id]=0; ctx->visited_expr[id]=false;
  }
  for (size_t i=0;i<ctx->touched_stmt_count;++i) ctx->statement_scratch[ctx->touched_stmts[i]]=0;
  ctx->touched_expr_count=ctx->touched_stmt_count=0;
}
static bool frame_layout(const DynIrProgram *ir, DynType type, uint32_t *size, uint32_t *alignment, unsigned depth) {
  return layout(ir, type, size, alignment, depth) && *size <= MAX_AGGREGATE;
}
static bool expression_scratch(BackendContext *ctx, const DynIrProgram *ir,DynExprId id,unsigned depth,unsigned *slots) {
  if (id==DYN_NO_EXPR) return true;
  if (id>=ir->expression_count || depth > MAX_DEPTH) return false;
  if (ctx->visited_expr[id]) return true;
  ctx->visited_expr[id]=true; ctx->touched_exprs[ctx->touched_expr_count++]=id;
  const DynIrExpr *e=&ir->expressions[id];
  if ((e->kind==DYN_EXPR_CALL || e->kind==DYN_EXPR_INDIRECT_CALL || e->kind==DYN_EXPR_STRUCT || e->kind==DYN_EXPR_ARRAY || e->kind==DYN_EXPR_ENUM) &&
      aggregate(ir,e->type)) {
    uint32_t size,alignment; if (!frame_layout(ir,e->type,&size,&alignment,0)) return false;
    *slots+=(size?size+7:8)/8; if (*slots>MAX_SCRATCH) return false;
    ctx->temporary_offsets[id]=0u-8*(ctx->local_words+*slots);
  }
  if (e->kind==DYN_EXPR_CONVERT && e->type==DYN_TYPE_ANY) {
    uint32_t size,a; if (e->left>=ir->expression_count || !frame_layout(ir,ir->expressions[e->left].type,&size,&a,0)) return false;
    *slots+=(size?size+7:8)/8; if (*slots>MAX_SCRATCH) return false;
    ctx->temporary_offsets[id]=0u-8*(ctx->local_words+*slots);
  }
  switch(e->kind) {
  case DYN_EXPR_UNARY: case DYN_EXPR_CONVERT: case DYN_EXPR_CAST: case DYN_EXPR_BITCAST:
  case DYN_EXPR_LEN: case DYN_EXPR_FIELD: case DYN_EXPR_INDIRECT_CALL:
    if (!expression_scratch(ctx, ir,e->left,depth+1,slots)) return false;
    break;
  case DYN_EXPR_SLICE:
    if (!expression_scratch(ctx, ir,(DynExprId)e->integer,depth+1,slots)) return false;
    /* fall through */
  case DYN_EXPR_BINARY: case DYN_EXPR_INDEX:
    if (!expression_scratch(ctx, ir,e->left,depth+1,slots) || !expression_scratch(ctx, ir,e->right,depth+1,slots)) return false;
    break;
  default: break;
  }
  if (e->kind==DYN_EXPR_CALL && e->integer<ir->function_count) {
    const DynIrFunction *callee=&ir->functions[e->integer];
    if (callee->variadic && !callee->foreign) {
      if (!dyn_type_is_slice(callee->variadic_type) || e->item_count<callee->param_count || (uint64_t)e->item_start+e->item_count>ir->item_count) return false;
      DynType element=ir->slices[callee->variadic_type-DYN_TYPE_SLICE_BASE].element;
      uint32_t size,a; if (!frame_layout(ir,element,&size,&a,0)) return false;
      unsigned count=e->item_count-callee->param_count; uint64_t needed=((uint64_t)size*count+7)/8;
      if (element==DYN_TYPE_ANY) for (unsigned i=0;i<count;++i) {
        DynExprId argument=ir->items[e->item_start+callee->param_count+i].expression;
        if (argument>=ir->expression_count || !frame_layout(ir,ir->expressions[argument].type,&size,&a,0)) return false;
        needed+=(size?size+7:8)/8;
      }
      if (needed>MAX_SCRATCH-*slots) return false;
      *slots+=(unsigned)needed; ctx->pack_offsets[id]=0u-8*(ctx->local_words+*slots);
    }
  }
  if (e->kind==DYN_EXPR_SYSCALL || e->kind==DYN_EXPR_ENUM || e->kind==DYN_EXPR_ARRAY || e->kind==DYN_EXPR_STRUCT || e->kind==DYN_EXPR_CALL || e->kind==DYN_EXPR_INDIRECT_CALL) {
    if ((uint64_t)e->item_start+e->item_count>ir->item_count) return false;
    for (uint32_t i=0;i<e->item_count;++i) if (!expression_scratch(ctx, ir,ir->items[e->item_start+i].expression,depth+1,slots)) return false;
    if (e->kind==DYN_EXPR_CALL || e->kind==DYN_EXPR_INDIRECT_CALL)
      for (uint32_t i=0;i<e->item_count;++i) {
        DynExprId argument=ir->items[e->item_start+i].expression; DynType type=ir->expressions[argument].type;
        uint32_t size,alignment;
        if (!abi_copied(ctx,ir,type) || !frame_layout(ir,type,&size,&alignment,0) || ctx->copy_offsets[argument]) continue;
        *slots+=(size+7)/8; if (*slots>MAX_SCRATCH) return false;
        ctx->copy_offsets[argument]=0u-8*(ctx->local_words+*slots); ctx->touched_exprs[ctx->touched_expr_count++]=argument;
      }
    if (e->kind==DYN_EXPR_STRUCT) {
      const DynIrStruct *record=&ir->structs[e->type-DYN_TYPE_STRUCT_BASE];
      for (uint32_t i=0;i<record->field_count;++i) if (!expression_scratch(ctx, ir,ir->fields[record->field_start+i].default_expression,depth+1,slots)) return false;
    }
  }
  return true;
}
static bool count_scratch(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f, uint32_t start, uint32_t count,
                          unsigned depth, unsigned *slots) {
  if (!count) return true;
  if (depth > MAX_DEPTH || (uint64_t)start + count > ir->child_count) return false;
  for (uint32_t i = 0; i < count; ++i) {
    if (ir->children[start+i] >= ir->statement_count) return false;
    const DynIrStmt *s = &ir->statements[ir->children[start+i]];
    if (!expression_scratch(ctx, ir,s->expression,0,slots) || !expression_scratch(ctx, ir,s->target,0,slots)) return false;
    unsigned needed=s->kind == DYN_STMT_CASE ? 2 : s->kind == DYN_STMT_FOR && s->for_range ? 2 : 0;
    if (s->kind==DYN_STMT_CASE && payload_enum(ir,ir->expressions[s->expression].type)) {
      uint32_t size,a; if (!frame_layout(ir,ir->expressions[s->expression].type,&size,&a,0)) return false; needed+=(size+7)/8;
    }
    if (s->kind==DYN_STMT_FOR && !s->for_range && s->target!=DYN_NO_EXPR) {
      if (s->target>=ir->expression_count) return false;
      DynType collection=ir->expressions[s->target].type; needed=3;
      if (dyn_type_is_array(collection) && !s->for_pointer) {
        uint32_t size,alignment; if (!frame_layout(ir,collection,&size,&alignment,0)) return false;
        needed+=(size+7)/8;
      } else if (!dyn_type_is_array(collection) && !descriptor(collection)) return false;
    }
    if (needed) { ctx->touched_stmts[ctx->touched_stmt_count++]=ir->children[start+i]; ctx->statement_scratch[ir->children[start+i]]=0u-8*(ctx->local_words+*slots+(s->kind==DYN_STMT_CASE?needed:1)); *slots+=needed; }
    if (s->kind==DYN_STMT_DEFER) {
      if (!ctx->unwind_offset) { *slots+=unwind_words(ctx); ctx->unwind_offset=0u-8*(ctx->local_words+*slots); if (!ctx->return_offset) { *slots+=2; ctx->return_offset=0u-8*(ctx->local_words+*slots); } *slots+=2; ctx->call_offset=0u-8*(ctx->local_words+*slots); }
      if (!s->defer_block && s->body_count==1) {
        if (s->body_start>=ir->child_count || ir->children[s->body_start]>=ir->statement_count) return false;
        const DynIrStmt *action=&ir->statements[ir->children[s->body_start]];
        if (action->kind==DYN_STMT_EXPR) {
          if (action->expression>=ir->expression_count) return false;
          const DynIrExpr *call=&ir->expressions[action->expression];
          if (call->kind==DYN_EXPR_CALL || call->kind==DYN_EXPR_INDIRECT_CALL) {
            if ((uint64_t)call->item_start+call->item_count>ir->item_count) return false;
            for (uint32_t j=0;j<call->item_count+(call->kind==DYN_EXPR_INDIRECT_CALL);++j) {
              DynExprId id=j<call->item_count?ir->items[call->item_start+j].expression:call->left;
              if (id>=ir->expression_count) return false;
              if (!ctx->captured_offsets[id]) { uint32_t size,alignment; if (!frame_layout(ir,ir->expressions[id].type,&size,&alignment,0)) return false; *slots+=(size?size+7:8)/8; ctx->captured_offsets[id]=0u-8*(ctx->local_words+*slots); ctx->touched_exprs[ctx->touched_expr_count++]=id; }
            }
          }
        }
      }
    }
    if (*slots > MAX_SCRATCH || !count_scratch(ctx, ir,f,s->body_start,s->body_count,depth+1,slots) ||
        !count_scratch(ctx, ir,f,s->else_start,s->else_count,depth+1,slots)) return false;
    if ((uint64_t)s->case_arm_start+s->case_arm_count > ir->case_arm_count) return false;
    for (uint32_t j=0;j<s->case_arm_count;++j) {
      const DynIrCaseArm *a=&ir->case_arms[s->case_arm_start+j];
      if (!count_scratch(ctx, ir,f,a->body_start,a->body_count,depth+1,slots)) return false;
    }
  }
  return true;
}
/* Initialize storage in RAX. Aggregate copies preserve overlap, like LLVM memmove. */
static bool initialize(BackendContext *ctx, const DynIrProgram *ir,const DynIrFunction *f,DynType type,DynExprId id,unsigned depth) {
  uint32_t size,alignment;
  if (depth > MAX_DEPTH || !layout(ir,type,&size,&alignment,0) || (id!=DYN_NO_EXPR && id>=ir->expression_count)) return false;
  isa_push(ctx, R_A);
  const DynIrExpr *value=id==DYN_NO_EXPR?NULL:&ir->expressions[id];
  if (value_type(ir, type)) {
    if (value) { if (!expression(ctx, ir,f,id,0)) return false; } else { isa_zero(ctx, R_A); if (descriptor(type)) isa_zero(ctx, R_D); }
    isa_pop(ctx, R_11);
    if (descriptor(type)) isa_store_descriptor(ctx);
    else store_memory(ctx, type);
    return !ctx->text.failed;
  }
  if (value && ctx->literal_offsets[id]) {
    isa_local_address(ctx, R_A, ctx->literals_symbol, ctx->literal_offsets[id]-1);
    isa_copy_disjoint(ctx, size);
    return !ctx->text.failed && !ctx->relocation_failed;
  }
  if (!value || value->kind==DYN_EXPR_ARRAY || value->kind==DYN_EXPR_STRUCT) {
    isa_zero_fill(ctx, size);
    if (value && value->kind==DYN_EXPR_ARRAY) {
      if (!dyn_type_is_array(type) || (uint64_t)value->item_start+value->item_count>ir->item_count) return false;
      const DynIrArray *array=&ir->arrays[type-DYN_TYPE_ARRAY_BASE]; uint32_t element,a;
      if (value->item_count>array->length || !layout(ir,array->element,&element,&a,0)) return false;
      for (uint32_t i=0;i<value->item_count;++i) {
        isa_peek_short(ctx, R_A, 0); isa_add_immediate(ctx, i*element);
        if (!initialize(ctx, ir,f,array->element,ir->items[value->item_start+i].expression,depth+1)) return false;
      }
    } else if (value) {
      if (!dyn_type_is_struct(type) || (uint64_t)value->item_start+value->item_count>ir->item_count) return false;
      const DynIrStruct *record=&ir->structs[type-DYN_TYPE_STRUCT_BASE];
      for (uint32_t i=0;i<record->field_count+value->item_count;++i) {
        uint32_t field=i<record->field_count?i:ir->items[value->item_start+i-record->field_count].field_index,offset;
        if (!field_offset(ir,type,field,&offset)) return false;
        const DynIrField *definition=&ir->fields[record->field_start+field];
        DynExprId expr=i<record->field_count?definition->default_expression:ir->items[value->item_start+i-record->field_count].expression;
        if (expr==DYN_NO_EXPR) continue;
        isa_peek_short(ctx, R_A, 0); isa_add_immediate(ctx, offset);
        if (!initialize(ctx, ir,f,definition->type,expr,depth+1)) return false;
      }
    }
    isa_pop(ctx, R_A); return !ctx->text.failed;
  }
  if (!expression(ctx, ir,f,id,0)) return false;
  isa_copy(ctx, size); return !ctx->text.failed;
}
static bool assign_value(BackendContext *ctx,const DynIrProgram *ir,const DynIrFunction *f,DynType type,DynExprId value) {
  if (!aggregate(ir,type)) return initialize(ctx,ir,f,type,value,0);
  uint32_t size,alignment; if (!layout(ir,type,&size,&alignment,0)) return false;
  isa_push(ctx, R_A);
  if (!expression(ctx,ir,f,value,0)) return false;
  isa_copy(ctx, size); return !ctx->text.failed;
}
static bool block_statements(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                             uint32_t start, uint32_t count, unsigned depth, bool *falls);
static void scope_open(BackendContext *ctx, const DynIrFunction *f, uint32_t local_id, size_t begin) {
  if (!ctx->dwarf || local_id < f->local_start || local_id - f->local_start >= f->local_count ||
      ctx->scope_count == MAX_LOCALS) return;
  uint32_t index = local_id - f->local_start;
  if (ctx->local_scope_end[index] || ctx->local_scope_begin[index]) return; /* first range wins */
  ctx->local_scope_begin[index] = begin;
  ctx->scope_stack[ctx->scope_count++] = index;
}
/* Locals declared by a block's statements are scoped to the rest of the block. */
static bool block(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                  uint32_t start, uint32_t count, unsigned depth, bool *falls) {
  unsigned base = ctx->scope_count;
  bool ok = block_statements(ctx, ir, f, start, count, depth, falls);
  while (ctx->scope_count > base) ctx->local_scope_end[ctx->scope_stack[--ctx->scope_count]] = ctx->text.n;
  return ok;
}
static void statement_scopes(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                             const DynIrStmt *s, size_t before) {
  if (!ctx->dwarf) return;
  if (s->kind == DYN_STMT_LOCAL) scope_open(ctx, f, s->local_id, ctx->text.n);
  /* Loop and case bindings cover the statement that introduces them. */
  unsigned base = ctx->scope_count;
  if (s->kind == DYN_STMT_FOR) scope_open(ctx, f, s->local_id, before);
  if (s->kind == DYN_STMT_CASE && (uint64_t)s->case_arm_start + s->case_arm_count <= ir->case_arm_count)
    for (uint32_t j = 0; j < s->case_arm_count; ++j)
      scope_open(ctx, f, ir->case_arms[s->case_arm_start + j].local_id, before);
  while (ctx->scope_count > base) ctx->local_scope_end[ctx->scope_stack[--ctx->scope_count]] = ctx->text.n;
}
#include "vector.inc"

static bool block_statements_value(BackendContext *, const DynIrProgram *, const DynIrFunction *, uint32_t, uint32_t, unsigned, bool *);
static bool block_statements(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                             uint32_t start, uint32_t count, unsigned depth, bool *falls) {
  uint32_t saved_origin = ctx->check_origin;
  bool ok = block_statements_value(ctx, ir, f, start, count, depth, falls);
  ctx->check_origin = saved_origin;
  return ok;
}
static bool block_statements_value(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                             uint32_t start, uint32_t count, unsigned depth, bool *falls) {
  uint32_t enclosing_origin = ctx->check_origin;
  if (depth > MAX_DEPTH || (uint64_t)start + count > ir->child_count) return false;
  unsigned defer_base=ctx->defer_count;
  bool reachable = true;
  /* Scopes close when the next statement begins; several paths below continue early. */
  const DynIrStmt *previous = NULL;
  size_t previous_start = 0;
  for (uint32_t i = 0; i < count; ++i) {
    uint32_t id = ir->children[start + i];
    if (id >= ir->statement_count) return false;
    const DynIrStmt *s = &ir->statements[id];
    ctx->check_origin = s->check_origin ? s->check_origin : enclosing_origin;
    if (previous) statement_scopes(ctx, ir, f, previous, previous_start);
    previous = s; previous_start = ctx->text.n;
    if (ctx->dwarf) {
      const char *path; unsigned line,column;
      dyn_location_get(ctx->debug_locations,ctx->debug_source,s->span.start_byte,&path,&line,&column);
      if (!backend_dwarf_line(ctx->dwarf,ctx->text.n,path,line,column,false)) return false;
    }
    if (s->kind==DYN_STMT_PANIC) {
      if (s->expression>=ir->expression_count || !descriptor(ir->expressions[s->expression].type) ||
          !expression(ctx, ir,f,s->expression,0)) return false;
      isa_push(ctx, R_A); isa_push(ctx, R_D);
      if (ctx->defer_count && !ctx->unwinding && !protect_call(ctx, ir,f)) return false;
      isa_pop(ctx, isa_argument(ctx, 1)); isa_pop(ctx, isa_argument(ctx, 0));
      runtime_call(ctx, 0); isa_trap(ctx); reachable=false;
    } else if (s->kind==DYN_STMT_DEFER) {
      if (ctx->defer_count==MAX_DEFERS || ctx->unwinding) return false;
      if (!s->defer_block && s->body_count==1) {
        const DynIrStmt *action=&ir->statements[ir->children[s->body_start]];
        if (action->kind==DYN_STMT_EXPR) {
          const DynIrExpr *call=&ir->expressions[action->expression];
          if (call->kind==DYN_EXPR_CALL || call->kind==DYN_EXPR_INDIRECT_CALL) {
            if (call->kind==DYN_EXPR_INDIRECT_CALL) {
              if (!expression(ctx, ir,f,call->left,0)) return false;
              isa_store(ctx, R_A, ctx->captured_offsets[call->left]);
            }
            for (uint32_t j=0;j<call->item_count;++j) {
              DynExprId value=ir->items[call->item_start+j].expression;
              if (!expression(ctx, ir,f,value,0)) return false;
              if (aggregate(ir, ir->expressions[value].type)) save_struct(ctx, ctx->captured_offsets[value],ir->expressions[value].type);
              else isa_store(ctx, R_A, ctx->captured_offsets[value]);
              if (descriptor(ir->expressions[value].type)) isa_store(ctx, R_D, ctx->captured_offsets[value]+8);
            }
          }
        }
      }
      ctx->defer_ids[ctx->defer_count++]=id;
    } else if (s->kind == DYN_STMT_RETURN) {
      if (s->expression != DYN_NO_EXPR) {
        if (!expression(ctx, ir, f, s->expression, 0)) return false;
      } else if (f->return_type != DYN_TYPE_VOID) return false;
      bool jumped=false;
      if (ctx->defer_count) {
        if (aggregate(ir, f->return_type)) save_struct(ctx, ctx->return_offset,f->return_type);
        else isa_store(ctx, R_A, ctx->return_offset);
        if (descriptor(f->return_type)) isa_store(ctx, R_D, ctx->return_offset+8);
        /* Returns with the same pending defers share one cleanup and epilogue. */
        if (!ctx->stack_slots && !ctx->unwinding) {
          if (!ladder_cleanup(ctx, ir, f, LADDER_RETURN, &jumped)) return false;
        } else if (!emit_defers(ctx, ir,f,0)) return false;
        if (!jumped) {
          if (aggregate(ir, f->return_type)) isa_lea(ctx, R_A, ctx->return_offset);
          else isa_load(ctx, R_A, ctx->return_offset);
          if (descriptor(f->return_type)) isa_load(ctx, R_D, ctx->return_offset+8);
        }
      }
      if (!jumped) {
        if (f->is_main) isa_zero(ctx, R_A);
        return_value(ctx,f->is_main?DYN_TYPE_I32:f->return_type);
      }
      reachable = false;
    } else if (s->kind == DYN_STMT_IF) {
      if (!ctx->debug_mode && s->expression < ir->expression_count &&
          ir->expressions[s->expression].kind == DYN_EXPR_BOOL) {
        bool chosen = ir->expressions[s->expression].boolean, falls;
        if (!block(ctx, ir, f, chosen ? s->body_start : s->else_start,
                   chosen ? s->body_count : s->else_count, depth + 1, &falls)) return false;
        reachable = reachable && falls;
        continue;
      }
      int when_false;
      if (!condition(ctx, ir, f, s->expression, 0, &when_false)) return false;
      size_t otherwise = isa_branch(ctx, when_false);
      bool then_falls, else_falls;
      if (!block(ctx, ir, f, s->body_start, s->body_count, depth + 1, &then_falls)) return false;
      size_t done = isa_branch(ctx, -1); /* join */
      isa_patch(ctx, otherwise, ctx->text.n);
      if (!block(ctx, ir, f, s->else_start, s->else_count, depth + 1, &else_falls)) return false;
      isa_patch(ctx, done, ctx->text.n);
      reachable = reachable && (then_falls || else_falls);
    } else if (s->kind == DYN_STMT_LOCAL || s->kind == DYN_STMT_ASSIGN) {
      if (s->kind == DYN_STMT_ASSIGN && s->local_id == UINT32_MAX && s->target == DYN_NO_EXPR) {
        if (!expression(ctx, ir, f, s->expression, 0)) return false;
        continue;
      }
      if ((s->kind==DYN_STMT_LOCAL || (s->kind==DYN_STMT_ASSIGN && s->target==DYN_NO_EXPR)) &&
          s->local_id<ir->local_count && !scalar(ir, ir->locals[s->local_id].type)) {
        if (s->assignment_op!=DYN_OP_NONE) return false;
        uint32_t offset; if (!local_slot(ctx, f,s->local_id,&offset)) return false;
        if (ctx->local_alias[s->local_id-f->local_start]) isa_load(ctx, R_A, offset); else isa_lea(ctx, R_A, offset);
        if (s->kind==DYN_STMT_ASSIGN) { if (!assign_value(ctx,ir,f,ir->locals[s->local_id].type,s->expression)) return false; }
        else if (!initialize(ctx,ir,f,ir->locals[s->local_id].type,s->expression,0)) return false;
        continue;
      }
      if (s->kind==DYN_STMT_ASSIGN && s->target<ir->expression_count && !scalar(ir, ir->expressions[s->target].type)) {
        if (s->assignment_op!=DYN_OP_NONE || !address(ctx, ir,f,s->target,0) ||
            !assign_value(ctx,ir,f,ir->expressions[s->target].type,s->expression)) return false;
        continue;
      }
      if (s->kind==DYN_STMT_ASSIGN && s->target<ir->expression_count &&
          ((ir->expressions[s->target].kind==DYN_EXPR_NAME && ir->expressions[s->target].integer>=f->local_start && ir->expressions[s->target].integer-f->local_start<f->local_count && ctx->local_alias[ir->expressions[s->target].integer-f->local_start]) || ir->expressions[s->target].kind==DYN_EXPR_INDEX || ir->expressions[s->target].kind==DYN_EXPR_FIELD ||
          (ir->expressions[s->target].kind==DYN_EXPR_UNARY && ir->expressions[s->target].op==DYN_OP_DEREF))) {
        DynType type=ir->expressions[s->target].type;
        if (!scalar(ir, type) || !address(ctx, ir,f,s->target,0)) return false;
        isa_push(ctx, R_A);
        if (s->assignment_op!=DYN_OP_NONE) {
          load_memory(ctx, type); isa_push(ctx, R_A);
          if (!expression(ctx, ir,f,s->expression,0)) return false;
          isa_move(ctx, R_C, R_A); isa_pop(ctx, R_A);
          DynIrExpr op={.type=type,.op=s->assignment_op,.left=s->target,.right=s->expression};
          if (!binary_result(ctx, ir,f,&op)) return false;
        } else if (!expression(ctx, ir,f,s->expression,0)) return false;
        isa_pop(ctx, R_11); store_memory(ctx, type); continue;
      }
      uint64_t id = s->local_id; bool global=false;
      if (s->kind == DYN_STMT_ASSIGN && s->target != DYN_NO_EXPR) {
        if (s->target >= ir->expression_count) return false;
        const DynIrExpr *target=&ir->expressions[s->target];
        if (target->kind != DYN_EXPR_NAME && target->kind != DYN_EXPR_GLOBAL) return false;
        global=target->kind == DYN_EXPR_GLOBAL; id=target->integer;
      }
      uint32_t offset=0; DynType type;
      if (global) {
        if (id>=ir->global_count || ir->globals[id].is_const) return false;
        type=ir->globals[id].type;
      } else {
        if (!local_slot(ctx, f,id,&offset)) return false;
        type=ir->locals[id].type;
      }
      if (!scalar(ir, type)) return false;
      if (s->assignment_op != DYN_OP_NONE) {
        if (s->target == DYN_NO_EXPR) return false;
        DynIrExpr operation = {.kind=DYN_EXPR_BINARY, .type=type,
          .op=s->assignment_op, .left=s->target, .right=s->expression};
        if (!expression_value(ctx, ir, f, &operation, 0)) return false;
      } else if (s->expression == DYN_NO_EXPR && s->kind == DYN_STMT_LOCAL) {
        isa_zero(ctx, R_A);
      } else if (!expression(ctx, ir, f, s->expression, 0)) return false;
      if (global) {
        isa_symbol_address(ctx, R_11, ctx->global_symbols[id]);
        store_memory(ctx, type);
      } else if (ctx->local_alias[id-f->local_start]) { isa_load(ctx, R_11, offset); store_memory(ctx,type); }
      else isa_store(ctx, R_A, offset);
    } else if (s->kind == DYN_STMT_EXPR) {
      if (!expression(ctx, ir, f, s->expression, 0)) return false;
    } else if (s->kind == DYN_STMT_CASE) {
      DynType type=ir->expressions[s->expression].type;
      bool payload=payload_enum(ir,type), any=type==DYN_TYPE_ANY, reference=false;
      for (unsigned i=0;i<s->case_arm_count;++i) if (ir->case_arms[s->case_arm_start+i].pointer_binding) reference=true;
      uint32_t subject=ctx->statement_scratch[id], payload_offset=0;
      if (payload) {
        const DynIrEnum *en=&ir->enums[type-DYN_TYPE_ENUM_BASE];
        uint32_t tag_size=(memory_bits(en->tag_type)+7)/8,a=(uint32_t)en->payload_alignment;
        payload_offset=(tag_size+a-1)&~(a-1);
      }
      if (reference) { if (!payload || !address(ctx,ir,f,s->expression,0)) return false; }
      else if (!expression(ctx,ir,f,s->expression,0)) return false;
      if (payload) {
        if (!reference) { save_struct(ctx,subject+16,type); isa_lea(ctx, R_A, subject+16); }
        isa_store(ctx, R_A, subject+8); load_memory(ctx,storage_type(ir,type));
      } else if (any) isa_store(ctx, R_D, subject+8);
      isa_store(ctx, R_A, subject);
      bool all_terminate = true;
      size_t done=UINT32_MAX;
      bool sign=signed_scalar(storage_type(ir,type));
      for (uint32_t i=0;i<s->case_arm_count;++i) {
        const DynIrCaseArm *a=&ir->case_arms[s->case_arm_start+i];
        if ((uint64_t)a->pattern_start+a->pattern_count > ir->pattern_count) return false;
        size_t matches=UINT32_MAX, next=UINT32_MAX;
        for (uint32_t j=0;j<a->pattern_count;++j) {
          const DynIrPattern *p=&ir->patterns[a->pattern_start+j];
          uint64_t first=p->first,last=p->last;
          if (p->is_enum) {
            if (!dyn_type_is_enum(type) || p->variant>=ir->variant_count) return false;
            first=last=ir->variants[p->variant].tag;
            unsigned bits=integer_bits(storage_type(ir,type));
            if (sign && bits<64 && (first>>(bits-1)&1)) first=last=first|(UINT64_MAX<<bits);
          } else if (p->is_type) { if (!any) return false; first=last=p->type; }
          isa_load(ctx, R_A, subject);
          isa_immediate(ctx, R_C, first); isa_compare(ctx, R_A, R_C);
          size_t lower=UINT32_MAX; pending_jump(ctx,sign?CC_L:CC_B,&lower);
          isa_immediate(ctx, R_C, last); isa_compare(ctx, R_A, R_C);
          pending_jump(ctx,sign?CC_LE:CC_BE,&matches);
          if (!resolve_jumps(ctx,lower,ctx->text.n)) return false;
        }
        if (!a->wildcard) pending_jump(ctx,-1,&next);
        if (!resolve_jumps(ctx,matches,ctx->text.n)) return false;
        bool old_alias=false;
        if (a->local_id!=UINT32_MAX) {
          uint32_t offset; if (!a->pattern_count || !local_slot(ctx,f,a->local_id,&offset)) return false;
          const DynIrPattern *pattern=&ir->patterns[a->pattern_start];
          DynType binding=ir->locals[a->local_id].type;
          if (!pattern->is_type && !pattern->is_enum) return false;
          isa_load(ctx, R_A, subject+8);
          if (payload) isa_add_immediate(ctx, payload_offset);
          old_alias=ctx->local_alias[a->local_id-f->local_start];
          ctx->local_alias[a->local_id-f->local_start]=a->pointer_binding;
          if (a->pointer_binding) isa_store(ctx, R_A, offset);
          else save_struct(ctx,offset,binding);
        }
        bool arm_falls;
        if (!block(ctx,ir,f,a->body_start,a->body_count,depth+1,&arm_falls)) return false;
        if (a->local_id!=UINT32_MAX) ctx->local_alias[a->local_id-f->local_start]=old_alias;
        all_terminate &= !arm_falls; pending_jump(ctx,-1,&done);
        if (!resolve_jumps(ctx,next,ctx->text.n)) return false;
      }
      isa_trap(ctx);
      if (!resolve_jumps(ctx,done,ctx->text.n)) return false;
      reachable &= !all_terminate;
    } else if (s->kind==DYN_STMT_FOR && !s->for_range && s->target!=DYN_NO_EXPR) {
      if (s->target>=ir->expression_count || ctx->loop_depth==MAX_DEPTH) return false;
      DynType collection=ir->expressions[s->target].type,element;
      bool array=dyn_type_is_array(collection); uint32_t element_size,alignment,binding;
      if (array) element=ir->arrays[collection-DYN_TYPE_ARRAY_BASE].element;
      else if (dyn_type_is_slice(collection)) element=ir->slices[collection-DYN_TYPE_SLICE_BASE].element;
      else if (collection==DYN_TYPE_STRING) element=DYN_TYPE_U8;
      else return false;
      if (!layout(ir,element,&element_size,&alignment,0) || !local_slot(ctx, f,s->local_id,&binding) ||
          !(array && s->for_pointer ? address(ctx, ir,f,s->target,0) : expression(ctx, ir,f,s->target,0))) return false;
      uint32_t counter=ctx->statement_scratch[id],length=counter-8,data=counter-16;
      if (array) {
        const DynIrArray *definition=&ir->arrays[collection-DYN_TYPE_ARRAY_BASE];
        if (!s->for_pointer) {
          uint32_t bytes,a; if (!layout(ir,collection,&bytes,&a,0)) return false;
          uint32_t snapshot=counter-8*(2+(bytes+7)/8);
          save_struct(ctx, snapshot,collection); isa_lea(ctx, R_A, snapshot);
        }
        isa_immediate(ctx, R_D, definition->length);
      }
      isa_store(ctx, R_A, data); isa_store(ctx, R_D, length);
      if (s->for_reverse) isa_move(ctx, R_A, R_D); else isa_zero(ctx, R_A);
      isa_store(ctx, R_A, counter);
      unsigned loop=ctx->loop_depth++; ctx->loops[loop].id=s->loop_id; ctx->loops[loop].defer_base=ctx->defer_count;
      ctx->loops[loop].breaks=ctx->loops[loop].continues=UINT32_MAX; ctx->loops[loop].condition=ctx->text.n;
      isa_load(ctx, R_A, counter);
      if (s->for_reverse) { isa_test(ctx, R_A); pending_jump(ctx, CC_E,&ctx->loops[loop].breaks); isa_step(ctx, -1); }
      else { isa_compare_frame(ctx, length); pending_jump(ctx, CC_AE,&ctx->loops[loop].breaks); }
      isa_scale(ctx, R_A, element_size); isa_add_frame(ctx, data);
      if (s->for_pointer) isa_store(ctx, R_A, binding);
      else if (scalar(ir, element)) { load_memory(ctx, element); isa_store(ctx, R_A, binding); }
      else save_struct(ctx, binding,element);
      bool body_falls;
      if (!block(ctx, ir,f,s->body_start,s->body_count,depth+1,&body_falls) || !resolve_jumps(ctx, ctx->loops[loop].continues,ctx->text.n)) return false;
      isa_load(ctx, R_A, counter); isa_step(ctx, s->for_reverse ? -1 : 1);
      isa_store(ctx, R_A, counter);
      isa_jump_back(ctx, ctx->loops[loop].condition);
      if (!resolve_jumps(ctx, ctx->loops[loop].breaks,ctx->text.n)) return false;
      --ctx->loop_depth;
    } else if (s->kind == DYN_STMT_FOR) {
      if (vector_loop(ctx, ir, f, s)) continue;
      if ((!s->for_range && s->target != DYN_NO_EXPR) || ctx->loop_depth == MAX_DEPTH) return false;
      unsigned loop = ctx->loop_depth++;
      ctx->loops[loop].id = s->loop_id; ctx->loops[loop].defer_base=ctx->defer_count;
      ctx->loops[loop].breaks = ctx->loops[loop].continues = UINT32_MAX;
      uint32_t counter=0, stop=0, binding=0;
      if (s->for_range) {
        if (s->for_pointer || !local_slot(ctx, f,s->local_id,&binding) ||
            !expression(ctx, ir,f,s->target,0)) return false;
        counter=ctx->statement_scratch[id]; stop=counter-8;
        isa_store(ctx, R_A, s->for_reverse?stop:counter);
        if (!expression(ctx, ir,f,s->expression,0)) return false;
        isa_store(ctx, R_A, s->for_reverse?counter:stop);
      }
      ctx->loops[loop].condition = ctx->text.n;
      if (s->for_range) {
        isa_load(ctx, R_A, counter);
        isa_compare_frame(ctx, stop);
        bool sign=signed_scalar(ir->expressions[s->target].type);
        Cond exit = s->for_reverse ? (s->for_inclusive ? (sign?CC_L:CC_B) : (sign?CC_LE:CC_BE))
          : (s->for_inclusive ? (sign?CC_G:CC_A) : (sign?CC_GE:CC_AE));
        pending_jump(ctx, exit,&ctx->loops[loop].breaks);
        if (s->for_reverse && !s->for_inclusive) isa_step(ctx, -1);
        isa_store(ctx, R_A, binding);
      } else if (s->expression != DYN_NO_EXPR) {
        int when_false;
        if (!condition(ctx, ir, f, s->expression, 0, &when_false)) return false;
        pending_jump(ctx, when_false, &ctx->loops[loop].breaks);
      }
      bool body_falls;
      if (!block(ctx, ir, f, s->body_start, s->body_count, depth + 1, &body_falls)) return false;
      if (!resolve_jumps(ctx, ctx->loops[loop].continues,ctx->text.n)) return false;
      if (s->for_range) {
        isa_load(ctx, R_A, counter);
        if (s->for_inclusive) {
          isa_compare_frame(ctx, stop); pending_jump(ctx, CC_E,&ctx->loops[loop].breaks);
        }
        isa_step(ctx, s->for_reverse ? -1 : 1);
        isa_store(ctx, R_A, counter);
      }
      isa_jump_back(ctx, ctx->loops[loop].condition);
      if (!resolve_jumps(ctx, ctx->loops[loop].breaks,ctx->text.n)) return false;
      --ctx->loop_depth;
    } else if (s->kind == DYN_STMT_BREAK || s->kind == DYN_STMT_CONTINUE) {
      unsigned loop = ctx->loop_depth;
      while (loop && ctx->loops[loop - 1].id != s->target_loop_id) --loop;
      if (!loop) return false;
      --loop;
      if (!emit_defers(ctx, ir,f,ctx->loops[loop].defer_base)) return false;
      pending_jump(ctx, -1,s->kind == DYN_STMT_CONTINUE ? &ctx->loops[loop].continues : &ctx->loops[loop].breaks);
      reachable = false;
    } else return false;
    /* Validate even unreachable statements: unsupported IR never gets hidden
       by constant conditions or an earlier return. Output is still buffered. */
  }
  if (previous) statement_scopes(ctx, ir, f, previous, previous_start);
  if (reachable && !emit_defers(ctx, ir,f,defer_base)) return false;
  ctx->defer_count=defer_base;
  *falls = reachable;
  return !ctx->text.failed && !ctx->rodata.failed && !ctx->relocation_failed;
}
static bool emit_defers(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f, unsigned base) {
  if (ctx->cleanup_depth++>=MAX_DEPTH) { --ctx->cleanup_depth; return false; }
  bool old=ctx->unwinding; ctx->unwinding=true;
  unsigned saved=ctx->defer_count;
  for (unsigned i=saved;i>base;--i) {
    const DynIrStmt *s=&ir->statements[ctx->defer_ids[i-1]]; bool falls;
    if (!block(ctx, ir,f,s->body_start,s->body_count,0,&falls)) { ctx->unwinding=old; --ctx->cleanup_depth; return false; }
  }
  ctx->unwinding=old; ctx->defer_count=saved; --ctx->cleanup_depth; return true;
}
#include "allocation.inc"
#include "ssa.inc"

static bool function(BackendContext *ctx, const DynSource *source, const DynIrProgram *ir, const DynIrFunction *f, const DynLocationIndex *locations) {
  if (f->generic ||
      !abi_supported(ir,f->return_type) || f->param_count > 512)
    return false;
  const char *symbol = function_name(f);
  if (!strcmp(symbol,"__dyn_backend_initialize") || !strcmp(symbol,"__dyn_backend_initialized")) return false;
  for (unsigned i = 0; i < RUNTIME_COUNT; ++i)
    if (!source->context.runtime_support && !strcmp(symbol, runtime_names[i])) return false;
  for (uint32_t i = 0; i < f->param_count; ++i)
    if (!abi_supported(ir,ir->params[f->param_start + i].type)) return false;
  if (f->foreign) return true;
  if (f->variadic && (!dyn_type_is_slice(f->variadic_type) || !abi_supported(ir,f->variadic_type))) return false;
  if (f->local_count > MAX_LOCALS || (uint64_t)f->local_start + f->local_count > ir->local_count) return false;
  ctx->active_ir=ir;
  int ssa=ssa_function(ctx, source, ir, f);
  if (ssa==SSA_EMITTED) return true;
  if (ssa==SSA_FAILED) return false;
  ctx->local_words=0;
  if (f->local_count <= MAX_LOCALS) memset(ctx->local_alias,0,f->local_count*sizeof(*ctx->local_alias));
  if (f->local_count <= MAX_LOCALS) {
    memset(ctx->local_scope_begin,0,f->local_count*sizeof(*ctx->local_scope_begin));
    memset(ctx->local_scope_end,0,f->local_count*sizeof(*ctx->local_scope_end));
  }
  ctx->scope_count=0;
  for (uint32_t i=0;i<f->local_count;++i) {
    uint32_t size,alignment;
    if (!frame_layout(ir,ir->locals[f->local_start+i].type,&size,&alignment,0)) return false;
    ctx->local_words+=(size+7)/8;
    if (!size) ++ctx->local_words;
    if (ctx->local_words>MAX_SCRATCH) return false;
    ctx->local_offsets[i]=0u-8*ctx->local_words;
  }
  if (ir->expression_count>MAX_NODES || ir->statement_count>MAX_NODES) return false;
  reset_scratch(ctx);
  ctx->active_ir=ir; ctx->sret_offset=ctx->return_offset=ctx->defer_count=ctx->unwind_offset=ctx->cleanup_depth=0; ctx->unwinding=false;
  ctx->ladder_count=ctx->ladder_pool_used=0; ctx->holding=false;
  if (!allocation_plan(ctx, source, ir, f)) return false;
  unsigned scratch=0;
  if (aggregate(ir, f->return_type)) {
    uint32_t size,alignment; if (!layout(ir,f->return_type,&size,&alignment,0)) return false;
    if (size>MAX_AGGREGATE) return false;
    scratch=(size?size+7:8)/8; ctx->return_offset=0u-8*(ctx->local_words+scratch);
    if (abi_memory(ctx,ir,f->return_type)) { ++scratch; ctx->sret_offset=0u-8*(ctx->local_words+scratch); }
    if (scratch>MAX_SCRATCH) return false;
  }
  if (!count_scratch(ctx, ir,f,f->body_start,f->body_count,0,&scratch)) return false;
  for (unsigned r = 0; r < 4; ++r)
    if (ctx->allocator_used & (1u << r)) ctx->allocator_save[r] = 0u - 8 * (ctx->local_words + ++scratch);
  ctx->frame_bytes = (((ctx->local_words+scratch) * 8 + 15) / 16) * 16;
  if (!ctx->frame_bytes) ctx->frame_bytes = 16;
  ctx->stack_slots = ctx->loop_depth = 0;
  for (unsigned i = 0; i < GUARD_COUNT; ++i) ctx->message_offsets[i] = ctx->guard_stubs[i] = SIZE_MAX;
  isa_enter(ctx);
  /* GP and FP register banks exhaust independently; stack slots retain source order. */
  unsigned gp=ctx->sret_offset && !ctx->a64?1:0,fp=0; uint32_t spilled=0;
  if (ctx->sret_offset) isa_store_result_pointer(ctx, ctx->sret_offset);
  for (uint32_t i=0;i<f->param_count+(unsigned)f->variadic;++i) {
    DynIrParam packed={.type=f->variadic_type,.local_id=f->variadic_local_id};
    const DynIrParam *p=i<f->param_count?&ir->params[f->param_start+i]:&packed; uint32_t offset;
    if (!local_slot(ctx, f,p->local_id,&offset)) return false;
    unsigned parts; bool indirect; AbiPart *assigned=ctx->call_parts;
    bool array=raw_aggregate(ir,p->type);
    if (!abi_assign(ctx,ir,p->type,&gp,&fp,assigned,&parts,512,&indirect)) return false;
    for (unsigned part=0;part<parts;++part) {
      int cls=assigned[part].cls;
      if (array || indirect || ((ctx->a64 || ctx->rv64) && aggregate(ir,p->type))) {
        if (cls>=0) isa_argument_to_a(ctx, cls);
        else incoming_stack(ctx, &assigned[part], &spilled);
        if (indirect) { save_struct(ctx, offset, p->type); continue; } /* copy the caller's memory */
        if (array) { normalize(ctx, assigned[part].leaf); isa_lea(ctx, R_11, offset+assigned[part].offset); store_memory(ctx, assigned[part].leaf); continue; }
        /* AArch64 struct pieces (HFA members or eightbytes) keep their exact size. */
        isa_move(ctx, R_10, R_A); isa_lea(ctx, R_DI, offset+assigned[part].offset); isa_store_chunk(ctx, 0, assigned[part].size);
        continue;
      }
      if (cls>=0) isa_store_argument(ctx, cls, offset+part*8);
      else { incoming_stack(ctx, &assigned[part], &spilled); isa_store(ctx, R_A, offset+part*8); }
    }
  }
  if (ctx->rv64) rv_i(ctx,0x13,2,2,128,0);
  if (ctx->debug_mode) {
    char label[4096]; const char *path; unsigned line, column;
    dyn_location_get(locations, source, f->source_offset, &path, &line, &column);
    snprintf(label, sizeof(label), "%s (%s:%u)", f->debug_name ? f->debug_name : f->name, path, line);
    size_t length = strlen(label), offset = literal(ctx, label, length);
    isa_string_arguments(ctx, offset, length); runtime_call(ctx, 1);
  }
  if (ctx->dwarf) {
    const char *path; unsigned line,column;
    dyn_location_get(locations,source,f->source_offset,&path,&line,&column);
    if (!backend_dwarf_line(ctx->dwarf,ctx->text.n,path,line,column,true)) return false;
  }
  if (f->is_main && ctx->initializer_symbol) isa_call_symbol(ctx, ctx->initializer_symbol);
  bool falls;
  if (!block(ctx, ir, f, f->body_start, f->body_count, 0, &falls) || ctx->stack_slots) return false;
  if (falls) { if (f->return_type != DYN_TYPE_VOID) return false; if (f->is_main) isa_zero(ctx, R_A); return_value(ctx,f->is_main?DYN_TYPE_I32:f->return_type); }
  return !ctx->text.failed && !ctx->rodata.failed && !ctx->relocation_failed;
}
/* AArch64 struct results: HFA members arrive in v0-v3, other structs up to
   16 bytes in x0/x1 (AAPCS64); larger structs used the hidden pointer. */
static bool a64_struct_result(BackendContext *ctx, const DynIrProgram *ir, DynType type, uint32_t offset) {
  DynType element; unsigned members; uint32_t size,alignment;
  if (!layout(ir,type,&size,&alignment,0)) return false;
  if (a64_struct_hfa(ir,type,&element,&members)) {
    unsigned bytes=memory_bits(element)/8;
    for (unsigned i=0;i<members;++i) {
      a64_frame_address(ctx, A64_SCRATCH, (int32_t)(offset+i*bytes));
      a64_word(ctx, (bytes==4?0xbd000000u:0xfd000000u) | A64_SCRATCH << 5 | i); /* str s/d i, [x16] */
    }
    return !ctx->text.failed;
  }
  /* Spill x1 before A/D are reused as scratch. */
  isa_store(ctx, R_A, offset);
  if (size>8) isa_store(ctx, R_D, offset+8);
  return !ctx->text.failed;
}
static void a64_struct_return(BackendContext *ctx, const DynIrProgram *ir, DynType type) {
  DynType element; unsigned members; uint32_t size,alignment;
  if (!layout(ir,type,&size,&alignment,0)) { ctx->text.failed=true; return; }
  isa_move(ctx, R_11, R_A);
  if (a64_struct_hfa(ir,type,&element,&members)) {
    unsigned bytes=memory_bits(element)/8;
    for (unsigned i=0;i<members;++i) {
      a64_immediate(ctx, A64_SCRATCH, i*bytes);
      a64_word(ctx, 0x8b100000 | a64_reg[R_11] << 5 | A64_SCRATCH); /* add x16, x12, x16 */
      a64_word(ctx, (bytes==4?0xbd400000u:0xfd400000u) | A64_SCRATCH << 5 | i); /* ldr s/d i, [x16] */
    }
    return;
  }
  /* Exact-size loads: the struct may end at a page boundary. */
  if (size>8) { load_chunk(ctx, 8, size-8); isa_move(ctx, R_D, R_10); }
  load_chunk(ctx, 0, size>8?8:size); isa_move(ctx, R_A, R_10);
}
static size_t align8(size_t n) { return (n + 7) & ~(size_t)7; }
/* Static scalar initializers only. Runtime initialization is a separate contract. */
static bool static_scalar(const DynIrProgram *ir, DynExprId id, uint64_t *value, unsigned depth) {
  *value=0;
  if (id==DYN_NO_EXPR) return true;
  if (id>=ir->expression_count || depth > MAX_DEPTH) return false;
  const DynIrExpr *e=&ir->expressions[id];
  if (!scalar(ir, e->type)) return false;
  if (e->kind==DYN_EXPR_ENUM && e->integer<ir->variant_count && !payload_enum(ir,e->type)) *value=ir->variants[e->integer].tag;
  else if (e->kind==DYN_EXPR_INT) *value=e->integer;
  else if (e->kind==DYN_EXPR_BOOL) *value=e->boolean;
  else if (e->kind==DYN_EXPR_NIL && (dyn_type_is_pointer(e->type)||e->type==DYN_TYPE_RAWPTR)) *value=0;
  else if (e->kind==DYN_EXPR_FLOAT) {
    if (e->type==DYN_TYPE_F32) { float v=(float)e->floating; uint32_t raw; memcpy(&raw,&v,4); *value=raw; }
    else memcpy(value,&e->floating,8);
  } else if (e->kind==DYN_EXPR_GLOBAL) {
    if (e->integer>=ir->global_count || !ir->globals[e->integer].is_const ||
        !static_scalar(ir,ir->globals[e->integer].initializer,value,depth+1)) return false;
  } else if ((e->kind==DYN_EXPR_CAST || e->kind==DYN_EXPR_CONVERT) && integer_type(e->type)) {
    if (e->left>=ir->expression_count || !integer_type(ir->expressions[e->left].type) ||
        !static_scalar(ir,e->left,value,depth+1)) return false;
  } else if (e->kind==DYN_EXPR_UNARY && e->op==DYN_OP_NEG) {
    if (!static_scalar(ir,e->left,value,depth+1)) return false;
    if (float_type(e->type)) *value^=UINT64_C(1)<<(e->type==DYN_TYPE_F32?31:63);
    else {
      if (!e->wrap && !e->boolean && ((!signed_scalar(e->type) && *value) ||
          (signed_scalar(e->type) && *value==(UINT64_C(0)-(UINT64_C(1)<<(integer_bits(e->type)-1)))))) return false;
      *value=0-*value;
    }
  } else return false;
  unsigned bits=integer_bits(e->type);
  if (integer_type(e->type) && bits<64) {
    uint64_t mask=(UINT64_C(1)<<bits)-1; *value&=mask;
    if (signed_scalar(e->type) && (*value&(UINT64_C(1)<<(bits-1)))) *value|=~mask;
  }
  return true;
}
/* Static values with addresses use .data.rel.ro: relocated by the loader,
   then protected by the linker's RELRO segment. */
static bool constant_relocation(BackendContext *ctx,uint32_t at,unsigned symbol,int64_t addend) {
  if (!symbol || (ctx->constant_relocation_count==ctx->constant_relocation_capacity &&
                  !grow_relocations(&ctx->constant_relocations,&ctx->constant_relocation_capacity))) return false;
  ctx->constant_relocations[ctx->constant_relocation_count++]=(Elf64_Rela){.r_offset=at,.r_info=ELF64_R_INFO(symbol,ctx->rv64?2:ctx->a64?R_AARCH64_ABS64:R_X86_64_64),.r_addend=addend};
  return true;
}
static bool constant_value(BackendContext *ctx,const DynIrProgram *ir,DynType type,DynExprId id,uint32_t offset,unsigned depth) {
  uint32_t size,alignment;
  if (depth > MAX_DEPTH || !layout(ir,type,&size,&alignment,0) || offset>ctx->constants_data.n || size>ctx->constants_data.n-offset) return false;
  if (id==DYN_NO_EXPR) return true;
  if (id>=ir->expression_count) return false;
  const DynIrExpr *e=&ir->expressions[id]; uint64_t value;
  if (scalar(ir,type) && static_scalar(ir,id,&value,0)) {
    if (size>8) return false;
    for (unsigned i=0;i<size;++i) ctx->constants_data.data[offset+i]=(unsigned char)(value>>(8*i));
    return true;
  }
  if (e->kind==DYN_EXPR_NIL) return true;
  if (e->kind==DYN_EXPR_GLOBAL) {
    return e->integer<ir->global_count && ir->globals[e->integer].is_const &&
      constant_value(ctx,ir,type,ir->globals[e->integer].initializer,offset,depth+1);
  }
  if (e->kind==DYN_EXPR_FUNCTION)
    return size==8 && e->integer<ir->function_count && constant_relocation(ctx,offset,ctx->function_symbols[e->integer],0);
  if (e->kind==DYN_EXPR_UNARY && e->op==DYN_OP_ADDRESS && e->left<ir->expression_count) {
    const DynIrExpr *target=&ir->expressions[e->left];
    if (target->kind==DYN_EXPR_GLOBAL && target->integer<ir->global_count)
      return size==8 && constant_relocation(ctx,offset,ctx->global_symbols[target->integer],0);
    if (target->kind==DYN_EXPR_FUNCTION && target->integer<ir->function_count)
      return size==8 && constant_relocation(ctx,offset,ctx->function_symbols[target->integer],0);
  }
  if (e->kind==DYN_EXPR_STRING && descriptor(type) && e->integer<ir->string_count) {
    const DynIrString *string=&ir->strings[e->integer]; size_t at=literal(ctx,(const char*)string->data,string->length);
    if (!constant_relocation(ctx,offset,1,(int64_t)at)) return false;
    for (unsigned i=0;i<8;++i) ctx->constants_data.data[offset+8+i]=(unsigned char)(string->length>>(8*i));
    return !ctx->rodata.failed;
  }
  if (e->kind==DYN_EXPR_ENUM && payload_enum(ir,type) && e->integer<ir->variant_count) {
    const DynIrEnum *en=&ir->enums[type-DYN_TYPE_ENUM_BASE]; const DynIrVariant *variant=&ir->variants[e->integer];
    unsigned tag_size=(memory_bits(en->tag_type)+7)/8;
    for (unsigned i=0;i<tag_size;++i) ctx->constants_data.data[offset+i]=(unsigned char)(variant->tag>>(8*i));
    if (variant->payload_type==DYN_TYPE_VOID) return true;
    unsigned a=(unsigned)en->payload_alignment;
    return e->item_count==1 && e->item_start<ir->item_count && constant_value(ctx,ir,variant->payload_type,
      ir->items[e->item_start].expression,offset+((tag_size+a-1)&~(a-1)),depth+1);
  }
  if (e->kind==DYN_EXPR_ARRAY && dyn_type_is_array(type)) {
    const DynIrArray *array=&ir->arrays[type-DYN_TYPE_ARRAY_BASE]; uint32_t element,a;
    if (e->item_count>array->length || (uint64_t)e->item_start+e->item_count>ir->item_count || !layout(ir,array->element,&element,&a,0)) return false;
    for (unsigned i=0;i<e->item_count;++i) if (!constant_value(ctx,ir,array->element,ir->items[e->item_start+i].expression,offset+i*element,depth+1)) return false;
    return true;
  }
  if (e->kind==DYN_EXPR_STRUCT && dyn_type_is_struct(type)) {
    const DynIrStruct *record=&ir->structs[type-DYN_TYPE_STRUCT_BASE];
    if ((uint64_t)e->item_start+e->item_count>ir->item_count) return false;
    for (unsigned i=0;i<record->field_count+e->item_count;++i) {
      unsigned field=i<record->field_count?i:ir->items[e->item_start+i-record->field_count].field_index; uint32_t at,n,a;
      if (!field_offset(ir,type,field,&at)) return false;
      const DynIrField *definition=&ir->fields[record->field_start+field];
      DynExprId value=i<record->field_count?definition->default_expression:ir->items[e->item_start+i-record->field_count].expression;
      if (value==DYN_NO_EXPR) continue;
      if (!layout(ir,definition->type,&n,&a,0)) return false;
      if (i>=record->field_count) {
        memset(ctx->constants_data.data+offset+at,0,n);
        for (size_t j=0;j<ctx->constant_relocation_count;) {
          uint64_t pos=ctx->constant_relocations[j].r_offset;
          if (pos>=offset+at && pos<offset+at+n) {
            memmove(&ctx->constant_relocations[j],&ctx->constant_relocations[j+1],(--ctx->constant_relocation_count-j)*sizeof(*ctx->constant_relocations));
          } else ++j;
        }
      }
      if (!constant_value(ctx,ir,definition->type,value,offset+at,depth+1)) return false;
    }
    return true;
  }
  return false;
}
/* Lays out every outermost struct or array literal of 16 to 512 bytes whose
   fields are all constant and mostly nonzero, so code copies or reads it
   instead of building it field by field. */
static bool constant_literals(BackendContext *ctx, const DynIrProgram *ir) {
  if (!ir->expression_count) return true;
  bool *nested = calloc(ir->expression_count, 1);
  if (!nested) return false;
  for (size_t id = 0; id < ir->expression_count; ++id) {
    const DynIrExpr *e = &ir->expressions[id];
    if ((e->kind != DYN_EXPR_STRUCT && e->kind != DYN_EXPR_ARRAY) ||
        (uint64_t)e->item_start + e->item_count > ir->item_count) continue;
    for (uint32_t i = 0; i < e->item_count; ++i) {
      DynExprId item = ir->items[e->item_start + i].expression;
      if (item < ir->expression_count) nested[item] = true;
    }
  }
  bool any = false;
  for (size_t id = 0; id < ir->expression_count; ++id) {
    const DynIrExpr *e = &ir->expressions[id];
    uint32_t size, alignment;
    if ((e->kind != DYN_EXPR_STRUCT && e->kind != DYN_EXPR_ARRAY) || nested[id] || !aggregate(ir, e->type) ||
        !layout(ir, e->type, &size, &alignment, 0) || size < 16 || size > 512 || alignment > 8) continue;
    size_t previous = ctx->constants_data.n, at = align8(previous), rodata = ctx->rodata.n;
    size_t relocations = ctx->constant_relocation_count;
    if (at > LIMIT || size > LIMIT - at || !reserve(&ctx->constants_data, at + size)) { free(nested); return false; }
    memset(ctx->constants_data.data + previous, 0, at + size - previous);
    ctx->constants_data.n = at + size;
    bool dense = false;
    if (constant_value(ctx, ir, e->type, (DynExprId)id, (uint32_t)at, 0)) {
      /* Building a literal costs a zero fill plus a store per nonzero word;
         the image costs every byte. Keep images that are mostly nonzero. */
      uint32_t words = (size + 7) / 8, used = 0;
      for (uint32_t w = 0; w < words; ++w) {
        bool nonzero = false;
        for (uint32_t i = w * 8; !nonzero && i < size && i < w * 8 + 8; ++i) nonzero = ctx->constants_data.data[at + i] != 0;
        for (size_t r = relocations; !nonzero && r < ctx->constant_relocation_count; ++r)
          nonzero = ctx->constant_relocations[r].r_offset / 8 == (at / 8) + w;
        used += nonzero;
      }
      dense = 2 * used >= words;
      if (dense) { ctx->literal_offsets[id] = (uint32_t)at + 1; any = true; }
    }
    if (!dense) {
      ctx->constants_data.n = previous; ctx->rodata.n = rodata; ctx->constant_relocation_count = relocations;
    }
  }
  free(nested);
  if (any) ctx->literals_symbol = (unsigned)ctx->runtime_base++;
  return true;
}
static bool global_initializer(BackendContext *ctx,const DynIrProgram *ir) {
  ctx->allocator_used = ctx->allocator_local_count = 0;
  DynIrFunction f={.name="__dyn_init_root",.return_type=DYN_TYPE_VOID};
  if (ir->expression_count>MAX_NODES) return false;
  ctx->local_words=ctx->stack_slots=ctx->defer_count=ctx->loop_depth=0; ctx->unwinding=false;
  reset_scratch(ctx);
  unsigned slots=0;
  for (size_t i=0;i<ir->global_init_count;++i) {
    uint32_t id=ir->global_init_order[i]; if (id>=ir->global_count) return false;
    const DynIrGlobal *g=&ir->globals[id];
    if (!g->foreign && !ctx->global_static[id] && !expression_scratch(ctx,ir,g->initializer,0,&slots)) return false;
  }
  ctx->frame_bytes=((slots*8+15)/16)*16; if (!ctx->frame_bytes) ctx->frame_bytes=16;
  isa_enter(ctx);
  isa_symbol_address(ctx, R_A, ctx->initializer_flag_symbol);
  size_t done=isa_once(ctx);
  for (size_t i=0;i<ir->global_init_count;++i) {
    uint32_t id=ir->global_init_order[i]; const DynIrGlobal *g=&ir->globals[id];
    if (g->foreign || ctx->global_static[id] || g->initializer==DYN_NO_EXPR) continue;
    char name[64];
    if (!strncmp(g->name,"dyn_m",5) && strlen(g->name)>21 && g->name[21]=='_') snprintf(name,sizeof(name),"__dyn_init_%.21s",g->name);
    else snprintf(name,sizeof(name),"__dyn_init_root");
    f.name=name;
    for (unsigned j=0;j<GUARD_COUNT;++j) ctx->message_offsets[j]=ctx->guard_stubs[j]=SIZE_MAX;
    isa_symbol_address(ctx, R_A, ctx->global_symbols[id]);
    if (dyn_type_is_array(g->type) && ir->expressions[g->initializer].kind==DYN_EXPR_ARRAY) {
      if (!initialize(ctx,ir,&f,g->type,g->initializer,0)) return false;
    } else if (!assign_value(ctx,ir,&f,g->type,g->initializer)) return false;
  }
  isa_patch(ctx, done, ctx->text.n);
  isa_return(ctx);
  return !ctx->stack_slots && !ctx->text.failed && !ctx->relocation_failed;
}
/* Mirrors codegen.c debug_type. Unknown types yield zero and omit the variable. */
static unsigned dwarf_type(BackendContext *ctx, const DynIrProgram *ir, DynType t, unsigned depth) {
  if (t >= DYN_TYPE_PARAM_BASE || depth > 64) return 0;
  if (ctx->dwarf_types[t]) return ctx->dwarf_types[t] - 1;
  BackendDwarf *d = ctx->dwarf;
  unsigned id = 0;
  const char *name = dyn_type_name(t);
  if (integer_type(t) || float_type(t)) {
    unsigned encoding = t == DYN_TYPE_BOOL ? 2 : float_type(t) ? 4 : signed_scalar(t) ? 5 : 7;
    id = backend_dwarf_base_type(d, name, encoding, (memory_bits(t) + 7) / 8);
  } else if (t == DYN_TYPE_RAWPTR || dyn_type_is_function(t)) {
    id = backend_dwarf_pointer_type(d, 0);
  } else if (dyn_type_is_pointer(t)) {
    ctx->dwarf_types[t] = 1 + (id = backend_dwarf_pointer_type(d, 0));
    unsigned target = dwarf_type(ctx, ir, ir->pointers[t - DYN_TYPE_POINTER_BASE].pointee, depth + 1);
    if (target) id = backend_dwarf_pointer_type(d, target);
  } else if (t == DYN_TYPE_ANY) {
    id = backend_dwarf_struct_type(d, "any", 16, 2);
    if (id) {
      backend_dwarf_member(d, id, 0, "type", dwarf_type(ctx, ir, DYN_TYPE_U64, depth + 1), 0);
      backend_dwarf_member(d, id, 1, "data", dwarf_type(ctx, ir, DYN_TYPE_RAWPTR, depth + 1), 8);
    }
  } else if (dyn_type_is_slice(t) || t == DYN_TYPE_STRING) {
    DynType element = t == DYN_TYPE_STRING ? DYN_TYPE_U8 : ir->slices[t - DYN_TYPE_SLICE_BASE].element;
    id = backend_dwarf_struct_type(d, name, 16, 2);
    if (id) {
      ctx->dwarf_types[t] = id + 1;
      unsigned data = dwarf_type(ctx, ir, element, depth + 1);
      backend_dwarf_member(d, id, 0, "data", data ? backend_dwarf_pointer_type(d, data) : dwarf_type(ctx, ir, DYN_TYPE_RAWPTR, depth + 1), 0);
      backend_dwarf_member(d, id, 1, "len", dwarf_type(ctx, ir, DYN_TYPE_USIZE, depth + 1), 8);
    }
  } else if (dyn_type_is_array(t) && t - DYN_TYPE_ARRAY_BASE < ir->array_count) {
    const DynIrArray *array = &ir->arrays[t - DYN_TYPE_ARRAY_BASE];
    id = backend_dwarf_array_type(d, dwarf_type(ctx, ir, array->element, depth + 1), array->length);
  } else if (dyn_type_is_struct(t) && t - DYN_TYPE_STRUCT_BASE < ir->struct_count) {
    const DynIrStruct *record = &ir->structs[t - DYN_TYPE_STRUCT_BASE];
    id = backend_dwarf_struct_type(d, record->name, record->size, record->field_count);
    if (id) {
      ctx->dwarf_types[t] = id + 1;
      for (uint32_t i = 0; i < record->field_count; ++i) {
        const DynIrField *field = &ir->fields[record->field_start + i];
        uint32_t offset;
        if (field_offset(ir, t, i, &offset))
          backend_dwarf_member(d, id, i, field->name, dwarf_type(ctx, ir, field->type, depth + 1), offset);
      }
    }
  } else if (dyn_type_is_enum(t) && t - DYN_TYPE_ENUM_BASE < ir->enum_count) {
    const DynIrEnum *e = &ir->enums[t - DYN_TYPE_ENUM_BASE];
    unsigned tag = backend_dwarf_enum_type(d, e->name, dwarf_type(ctx, ir, e->tag_type, depth + 1),
                                           (memory_bits(e->tag_type) + 7) / 8, e->variant_count);
    for (uint32_t i = 0; tag && i < e->variant_count; ++i) {
      const DynIrVariant *v = &ir->variants[e->variant_start + i];
      backend_dwarf_enumerator(d, tag, i, v->name, (int64_t)v->tag);
    }
    id = tag;
    if (tag && e->has_payload) {
      /* Mirrors codegen.c: tag at zero, payload union at the payload alignment. */
      id = backend_dwarf_struct_type(d, e->name, e->size, 2);
      unsigned payload = backend_dwarf_union_type(d, "payload", e->payload_size, e->variant_count);
      for (uint32_t i = 0; payload && i < e->variant_count; ++i) {
        const DynIrVariant *v = &ir->variants[e->variant_start + i];
        if (v->payload_type != DYN_TYPE_VOID)
          backend_dwarf_member(d, payload, i, v->name, dwarf_type(ctx, ir, v->payload_type, depth + 1), 0);
      }
      if (id) {
        backend_dwarf_member(d, id, 0, "tag", tag, 0);
        if (payload) backend_dwarf_member(d, id, 1, "payload", payload, e->payload_alignment);
      }
    }
  }
  ctx->dwarf_types[t] = id + 1;
  return id;
}
static bool dwarf_variables(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f) {
  for (uint32_t i = 0; i < f->local_count; ++i) {
    const DynIrLocal *local = &ir->locals[f->local_start + i];
    bool parameter = false;
    for (uint32_t j = 0; j < f->param_count; ++j)
      parameter |= ir->params[f->param_start + j].local_id == f->local_start + i;
    unsigned type = dwarf_type(ctx, ir, local->type, 0);
    size_t begin = parameter ? 0 : ctx->local_scope_begin[i], end = parameter ? 0 : ctx->local_scope_end[i];
    if (!backend_dwarf_variable(ctx->dwarf, local->name, type,
                                (int32_t)ctx->local_offsets[i], parameter, begin, end)) return false;
  }
  return true;
}
static int compare_names(const void *a, const void *b) {
  return strcmp(*(const char *const *)a, *(const char *const *)b);
}
/* Mirrors codegen.c function_symbol: sorted foreign names keep this linear-logarithmic. */
static bool suffix_functions(BackendContext *ctx, const DynIrProgram *ir) {
  size_t count=0;
  const char **foreign=malloc((ir->function_count?ir->function_count:1)*sizeof(*foreign));
  if (!foreign) return false;
  for (size_t i=0;i<ir->function_count;++i)
    if (ir->functions[i].foreign) foreign[count++]=ir->functions[i].link_name;
  qsort(foreign,count,sizeof(*foreign),compare_names);
  for (size_t i=0;i<ir->function_count;++i) {
    const DynIrFunction *f=&ir->functions[i];
    const char *name=f->name;
    ctx->function_suffixed[i]=!f->foreign && !f->is_main && name &&
      (!strcmp(name,"exit") || !strcmp(name,"_exit") ||
       bsearch(&name,foreign,count,sizeof(*foreign),compare_names));
  }
  free(foreign);
  return true;
}
#include "reachability.inc"

static bool emit_object(BackendContext *ctx, const DynSource *source, const DynIrProgram *ir, const char *path) {
  ctx->active_ir=ir;
  if ((!ir->function_count && !ctx->shared) || ir->function_count > MAX_SYMBOLS || ir->global_count > MAX_SYMBOLS) {
    backend_report(ctx, "unsupported by native backend: global/function count\n");
    return false;
  }
  DynLocationIndex locations = {0};
  if ((ctx->debug_mode || ctx->dwarf) && !dyn_location_build(&locations, source)) return false;
  ctx->debug_source=source; ctx->debug_locations=&locations;
  if (!suffix_functions(ctx, ir)) { dyn_location_free(&locations); return false; }
  if (!reachable_functions(ctx, source, ir)) { dyn_location_free(&locations); return false; }
  unsigned section_symbols=ctx->dwarf?7:2;
  ctx->runtime_base=section_symbols;
  for (size_t i=0;i<ir->function_count;++i)
    ctx->function_symbols[i]=ctx->function_live[i]?(unsigned)ctx->runtime_base++:0;

  for (size_t i=0;i<ir->global_count;++i) ctx->global_symbols[i]=(unsigned)ctx->runtime_base++;
  for (size_t i=0;i<ir->global_count;++i) {
    const DynIrGlobal *g=&ir->globals[i]; if (!g->is_const || g->foreign) continue;
    uint32_t size,a; if (!layout(ir,g->type,&size,&a,0)) { dyn_location_free(&locations); return false; }
    size_t previous=ctx->constants_data.n, at=align8(previous), rodata=ctx->rodata.n, relocations=ctx->constant_relocation_count;
    if (at>LIMIT || size>LIMIT-at || !reserve(&ctx->constants_data,at+size)) { dyn_location_free(&locations); return false; }
    memset(ctx->constants_data.data+previous,0,at+size-previous); ctx->constants_data.n=at+size;
    if (constant_value(ctx,ir,g->type,g->initializer,(uint32_t)at,0)) {
      ctx->global_static[i]=true; ctx->constant_offsets[i]=(uint32_t)at;
    } else {
      ctx->constants_data.n=previous; ctx->rodata.n=rodata; ctx->constant_relocation_count=relocations;
    }
  }
  if (!constant_literals(ctx, ir)) { dyn_location_free(&locations); return false; }
  for (size_t i=0;i<ir->global_count;++i) if (!ir->globals[i].foreign && !ctx->global_static[i] && ir->globals[i].initializer!=DYN_NO_EXPR) {
    ctx->initializer_symbol=(unsigned)ctx->runtime_base++;
    ctx->initializer_flag_symbol=(unsigned)ctx->runtime_base++; break;
  }
  if (ctx->shared && (ctx->win64 || ctx->winarm64) && !source->context.runtime_support) {
    for (size_t i=0;i<ir->function_count;++i) {
      if (!strcmp(function_name(&ir->functions[i]), "DllMainCRTStartup")) {
        backend_report(ctx, "error: shared Windows modules reserve DllMainCRTStartup\n");
        dyn_location_free(&locations); return false;
      }
    }
    ctx->dll_entry_symbol=(unsigned)ctx->runtime_base++;
  }
  /* ELF requires every local before sh_info. Reindex once before code emission,
     including address relocations already recorded for constant initializers. */
  unsigned *remap=ctx->symbol_remap, next=section_symbols;
  memset(ctx->symbol_remap,0,sizeof(ctx->symbol_remap));
  for (unsigned i=1;i<section_symbols;++i) remap[i]=i;
  if (ctx->runtime_base>sizeof(ctx->symbol_remap)/sizeof(*ctx->symbol_remap)) { dyn_location_free(&locations); return false; }
  for (unsigned pass=0;pass<2;++pass) {
    if (pass) ctx->first_global=next;
    for (size_t i=0;i<ir->function_count;++i) {
      const DynIrFunction *f=&ir->functions[i];
      if (!ctx->function_live[i] || (unsigned)(f->foreign||f->is_public||f->is_main)!=pass) continue;
      unsigned old=ctx->function_symbols[i]; ctx->function_symbols[i]=next; remap[old]=next++;
    }
    for (size_t i=0;i<ir->global_count;++i) {
      const DynIrGlobal *g=&ir->globals[i];
      if ((unsigned)(g->foreign||g->is_public)!=pass) continue;
      unsigned old=ctx->global_symbols[i]; ctx->global_symbols[i]=next; remap[old]=next++;
    }
    if (pass && ctx->dll_entry_symbol) {
      remap[ctx->dll_entry_symbol]=next; ctx->dll_entry_symbol=next++;
    }
    if (!pass && ctx->literals_symbol) {
      remap[ctx->literals_symbol]=next; ctx->literals_symbol=next++;
    }
    if (!pass && ctx->initializer_symbol) {
      remap[ctx->initializer_symbol]=next; ctx->initializer_symbol=next++;
      remap[ctx->initializer_flag_symbol]=next; ctx->initializer_flag_symbol=next++;
    }
  }
  if (next!=ctx->runtime_base) { dyn_location_free(&locations); return false; }
  for (size_t i=0;i<ctx->constant_relocation_count;++i) {
    Elf64_Rela *r=&ctx->constant_relocations[i]; unsigned symbol=(unsigned)ELF64_R_SYM(r->r_info);
    if (symbol>=next || !remap[symbol]) { dyn_location_free(&locations); return false; }
    r->r_info=ELF64_R_INFO(remap[symbol],ELF64_R_TYPE(r->r_info));
  }
  Elf64_Sym *symbols = calloc(ctx->runtime_base + RUNTIME_COUNT, sizeof(*symbols));
  /* Every symbol name plus a ".dyn" suffix, initializer names and the null entry. */
  size_t string_limit = 4096;
  for (size_t i = 0; i < ir->function_count; ++i) string_limit += strlen(function_name(&ir->functions[i])) + 5;
  for (size_t i = 0; i < ir->global_count; ++i)
    string_limit += strlen(ir->globals[i].foreign ? ir->globals[i].link_name : ir->globals[i].name) + 1;
  for (unsigned i = 0; i < RUNTIME_COUNT; ++i) string_limit += strlen(runtime_names[i]) + 1;
  if (string_limit > LIMIT) string_limit = LIMIT;
  char *strings = calloc(string_limit, 1);
  if (!symbols || !strings) { free(symbols); free(strings); dyn_location_free(&locations); return false; }
  /* Local section symbol precedes every global symbol. All string references
     use this symbol plus an addend, so linked code stays position independent. */
  symbols[1] = (Elf64_Sym){.st_info = ELF64_ST_INFO(STB_LOCAL, STT_SECTION), .st_shndx = 2};
  if (ctx->dwarf) {
    symbols[2]=(Elf64_Sym){.st_info=ELF64_ST_INFO(STB_LOCAL,STT_SECTION),.st_shndx=1};
    for (unsigned i=0;i<4;++i) symbols[3+i]=(Elf64_Sym){.st_info=ELF64_ST_INFO(STB_LOCAL,STT_SECTION),.st_shndx=(Elf64_Half)(13+2*i)};
  }
  BackendDwarfOutput debug={0};
  size_t names = 1;
  bool ok = false;
  for (size_t i=0;i<ir->global_count;++i) {
    const DynIrGlobal *g=&ir->globals[i]; const char *name=g->foreign?g->link_name:g->name;
    uint32_t size,alignment;
    if (!layout(ir,g->type,&size,&alignment,0)) {
      backend_report(ctx,"unsupported by native backend global initializer: %s\n",name); goto done;
    }
    for (size_t j=0;j<ir->function_count;++j) if (!ctx->function_suffixed[j] && !strcmp(name,function_name(&ir->functions[j]))) {
      backend_report(ctx,"unsupported by native backend: global/function symbol collision\n"); goto done;
    }
    if (!strcmp(name,"__dyn_backend_initialize") || !strcmp(name,"__dyn_backend_initialized")) goto done;
    for (unsigned j=0;j<RUNTIME_COUNT;++j) if (!strcmp(name,runtime_names[j])) {
      backend_report(ctx,"unsupported by native backend: reserved global symbol\n"); goto done;
    }
    size_t length=strlen(name)+1; if (length>string_limit-names) goto done;
    size_t at=0;
    if (ctx->global_static[i]) at=ctx->constant_offsets[i];
    else if (!g->foreign) {
      at=align8(ctx->globals_data.n); if (at>LIMIT || size>LIMIT-at) goto done;
      /* Mutable globals begin zeroed; initializer code supplies their values. */
      ctx->globals_data.n=at+size;
    }
    symbols[ctx->global_symbols[i]]=(Elf64_Sym){.st_name=(Elf64_Word)names,
      .st_info=ELF64_ST_INFO(g->foreign||g->is_public?STB_GLOBAL:STB_LOCAL,STT_OBJECT),.st_shndx=g->foreign?SHN_UNDEF:ctx->global_static[i]?11:8,.st_value=at,.st_size=size};
    memcpy(strings+names,name,length); names+=length;
  }
  if (ctx->literals_symbol) {
    const char *label="__dyn_backend_literals"; size_t length=strlen(label)+1;
    if (length>string_limit-names) goto done;
    symbols[ctx->literals_symbol]=(Elf64_Sym){.st_name=(Elf64_Word)names,.st_info=ELF64_ST_INFO(STB_LOCAL,STT_OBJECT),.st_shndx=11};
    memcpy(strings+names,label,length); names+=length;
  }
  if (ctx->initializer_symbol) {
    const char *flag="__dyn_backend_initialized"; size_t length=strlen(flag)+1,at=align8(ctx->globals_data.n);
    if (at>LIMIT-8 || length>string_limit-names) goto done;
    ctx->globals_data.n=at+8;
    symbols[ctx->initializer_flag_symbol]=(Elf64_Sym){.st_name=(Elf64_Word)names,.st_info=ELF64_ST_INFO(STB_LOCAL,STT_OBJECT),.st_shndx=8,.st_value=at,.st_size=1};
    memcpy(strings+names,flag,length); names+=length;
  }
  for (size_t i = 0; i < ir->function_count; ++i) {
    const DynIrFunction *f = &ir->functions[i];
    if (!ctx->function_live[i]) continue; /* checked, reachable concrete functions only */
    const char *name = function_name(f);
    size_t length = strlen(name) + 1 + (ctx->function_suffixed[i] ? 4 : 0), begin = ctx->text.n;
    if (ctx->dwarf && !f->foreign) {
      const char *file; unsigned line,column;
      dyn_location_get(&locations,source,f->source_offset,&file,&line,&column);
      if (!backend_dwarf_begin(ctx->dwarf,begin,name,file,line,column)) goto done;
    }
    if (length > string_limit - names || !function(ctx, source, ir, f, &locations)) {
      backend_report(ctx, "unsupported by native backend function or emission limit: %s\n", name);
      goto done;
    }
    if (ctx->dwarf && !f->foreign &&
        (!dwarf_variables(ctx, ir, f) || !backend_dwarf_end(ctx->dwarf,ctx->text.n))) goto done;
    symbols[ctx->function_symbols[i]] = (Elf64_Sym){.st_name = (Elf64_Word)names,
      .st_info = ELF64_ST_INFO(f->foreign||f->is_public||f->is_main?STB_GLOBAL:STB_LOCAL, STT_FUNC), .st_shndx = f->foreign ? SHN_UNDEF : 1,
      .st_value = f->foreign ? 0 : begin, .st_size = ctx->text.n - begin};
    if (source->context.runtime_support && !f->foreign)
      symbols[ctx->function_symbols[i]].st_other = 2; /* STV_HIDDEN */
    memcpy(strings + names, name, strlen(name));
    if (ctx->function_suffixed[i]) memcpy(strings + names + strlen(name), ".dyn", 4);
    strings[names + length - 1] = 0; names += length;
  }
  if (ctx->initializer_symbol) {
    const char *name="__dyn_backend_initialize"; size_t length=strlen(name)+1,begin=ctx->text.n;
    if (ctx->dwarf) {
      const char *file; unsigned line,column; dyn_location_get(&locations,source,0,&file,&line,&column);
      if (!backend_dwarf_begin(ctx->dwarf,begin,name,file,line,column)) goto done;
    }
    if (length>string_limit-names || !global_initializer(ctx,ir)) { backend_report(ctx,"unsupported by native backend global initialization\n"); goto done; }
    if (ctx->dwarf && !backend_dwarf_end(ctx->dwarf,ctx->text.n)) goto done;
    symbols[ctx->initializer_symbol]=(Elf64_Sym){.st_name=(Elf64_Word)names,.st_info=ELF64_ST_INFO(STB_LOCAL,STT_FUNC),.st_shndx=1,.st_value=begin,.st_size=ctx->text.n-begin};
    memcpy(strings+names,name,length); names+=length;
  }
  if (ctx->dll_entry_symbol) {
    const char *name="DllMainCRTStartup"; size_t length=strlen(name)+1, begin=ctx->text.n;
    if (length>string_limit-names) goto done;
    BackendDwarf *dwarf=ctx->dwarf; ctx->dwarf=NULL;
    ctx->frame_bytes=0; ctx->stack_slots=0;
    ctx->allocator_used = ctx->allocator_local_count = 0;
    isa_enter(ctx);
    if (ctx->initializer_symbol) {
      if (ctx->a64) a64_word(ctx,0xf100043f); /* cmp x1, DLL_PROCESS_ATTACH */
      else CODE(0x83,0xfa,1); /* cmp edx, DLL_PROCESS_ATTACH */
      size_t done_attach=isa_branch(ctx,CC_NE);
      isa_call_symbol(ctx,ctx->initializer_symbol);
      isa_patch(ctx,done_attach,ctx->text.n);
    }
    isa_immediate(ctx,R_A,1); isa_return(ctx);
    ctx->dwarf=dwarf;
    if (ctx->text.failed || ctx->relocation_failed) goto done;
    symbols[ctx->dll_entry_symbol]=(Elf64_Sym){.st_name=(Elf64_Word)names,
      .st_info=ELF64_ST_INFO(STB_GLOBAL,STT_FUNC),.st_shndx=1,.st_value=begin,.st_size=ctx->text.n-begin};
    memcpy(strings+names,name,length); names+=length;
  }
  for (unsigned i = 0; i < RUNTIME_COUNT; ++i) if (ctx->runtime_index[i]) {
    size_t length = strlen(runtime_names[i]) + 1;
    if (length > string_limit - names) goto done;
    symbols[ctx->runtime_index[i]] = (Elf64_Sym){.st_name = (Elf64_Word)names,
      .st_info = ELF64_ST_INFO(STB_GLOBAL, STT_FUNC), .st_shndx = SHN_UNDEF};
    memcpy(strings + names, runtime_names[i], length); names += length;
  }
  if (ctx->dwarf && !backend_dwarf_finish(ctx->dwarf,&debug)) goto done;
  if (ctx->rv64 && ctx->rv_anchor_count) {
    unsigned count=(unsigned)(ctx->runtime_base+ctx->runtime_count),n=ctx->rv_anchor_count,first=ctx->first_global;
    Elf64_Sym *grown=calloc(count+n,sizeof(*grown));if(!grown)goto done;
    memcpy(grown,symbols,first*sizeof(*symbols));
    for(unsigned i=0;i<n;++i)grown[first+i]=(Elf64_Sym){.st_info=ELF64_ST_INFO(STB_LOCAL,STT_NOTYPE),.st_shndx=1,.st_value=ctx->rv_anchors[i]};
    memcpy(grown+first+n,symbols+first,(count-first)*sizeof(*symbols));free(symbols);symbols=grown;
    for(unsigned group=0;group<2;++group) {
      Elf64_Rela *items=group?ctx->constant_relocations:ctx->relocations;
      size_t total=group?ctx->constant_relocation_count:ctx->relocation_count;
      for(size_t i=0;i<total;++i) {unsigned symbol=(unsigned)ELF64_R_SYM(items[i].r_info);
        symbol=symbol&0x80000000u?first+(symbol&0x7fffffffu):symbol>=first?symbol+n:symbol;
        items[i].r_info=ELF64_R_INFO(symbol,ELF64_R_TYPE(items[i].r_info));
      }
    }
    if(ctx->initializer_symbol>=first)ctx->initializer_symbol+=n;
    ctx->runtime_base+=n;ctx->first_global+=n;
  }

  if (ctx->win64 || ctx->winarm64 || ctx->darwin) {
    unsigned symbol_count=(unsigned)(ctx->runtime_base+ctx->runtime_count);
    ok = (ctx->win64 || ctx->winarm64) ? write_coff(ctx,path,symbols,symbol_count,strings,&debug)
                    : write_macho(ctx,path,symbols,symbol_count,strings,&debug);
    if (!ok) backend_report(ctx, "native backend: failed to write object\n");
    goto done;
  }
  /* Keep the extra terminator after .bss so later section-name offsets stay fixed. */
  size_t debug_name=sizeof("\0.text\0.rodata\0.rela.text\0.symtab\0.strtab\0.shstrtab\0.note.GNU-stack\0.bss\0\0.init_array\0.rela.init_array\0.data.rel.ro\0.rela.data.rel.ro\0")-1;
  const char section_names[] = "\0.text\0.rodata\0.rela.text\0.symtab\0.strtab\0.shstrtab\0.note.GNU-stack\0.bss\0\0.init_array\0.rela.init_array\0.data.rel.ro\0.rela.data.rel.ro\0" ".debug_info\0.rela.debug_info\0.debug_abbrev\0.rela.debug_abbrev\0.debug_line\0.rela.debug_line\0.debug_frame\0.rela.debug_frame\0";
  Elf64_Ehdr h = {.e_ident = {0x7f,'E','L','F',ELFCLASS64,ELFDATA2LSB,EV_CURRENT},
    .e_type = ET_REL, .e_machine = ctx->rv64 ? 243 : ctx->a64 ? EM_AARCH64 : EM_X86_64, .e_flags=ctx->rv64?4:0, .e_version = EV_CURRENT,
    .e_ehsize = sizeof(h), .e_shentsize = sizeof(Elf64_Shdr), .e_shnum = ctx->dwarf?21:13,
    .e_shstrndx = 6};
  Elf64_Shdr sh[21] = {0};
  size_t symbytes = (ctx->runtime_base + ctx->runtime_count) * sizeof(*symbols);
  size_t relbytes = ctx->relocation_count * sizeof(*ctx->relocations);
  sh[1] = (Elf64_Shdr){.sh_name=1, .sh_type=SHT_PROGBITS,
    .sh_flags=SHF_ALLOC|SHF_EXECINSTR, .sh_offset=sizeof(h), .sh_size=ctx->text.n, .sh_addralign=(ctx->a64||ctx->rv64)?4:1};
  sh[2] = (Elf64_Shdr){.sh_name=7, .sh_type=SHT_PROGBITS, .sh_flags=SHF_ALLOC,
    .sh_offset=align8(sizeof(h)+ctx->text.n), .sh_size=ctx->rodata.n, .sh_addralign=8};
  sh[3] = (Elf64_Shdr){.sh_name=15, .sh_type=SHT_RELA,
    .sh_offset=align8(sh[2].sh_offset+ctx->rodata.n), .sh_size=relbytes,
    .sh_link=4, .sh_info=1, .sh_addralign=8, .sh_entsize=sizeof(*ctx->relocations)};
  sh[4] = (Elf64_Shdr){.sh_name=26, .sh_type=SHT_SYMTAB,
    .sh_offset=sh[3].sh_offset+relbytes, .sh_size=symbytes,
    .sh_link=5, .sh_info=ctx->first_global, .sh_addralign=8, .sh_entsize=sizeof(*symbols)};
  sh[5] = (Elf64_Shdr){.sh_name=34, .sh_type=SHT_STRTAB,
    .sh_offset=sh[4].sh_offset+symbytes, .sh_size=names, .sh_addralign=1};
  sh[6] = (Elf64_Shdr){.sh_name=42, .sh_type=SHT_STRTAB,
    .sh_offset=sh[5].sh_offset+names, .sh_size=sizeof(section_names), .sh_addralign=1};
  sh[7] = (Elf64_Shdr){.sh_name=52, .sh_type=SHT_PROGBITS, .sh_addralign=1};
  sh[8]=(Elf64_Shdr){.sh_name=68,.sh_type=SHT_NOBITS,.sh_flags=SHF_ALLOC|SHF_WRITE,
    .sh_offset=align8(sh[6].sh_offset+sizeof(section_names)),.sh_size=ctx->globals_data.n,.sh_addralign=8};
  sh[9]=(Elf64_Shdr){.sh_name=74,.sh_type=SHT_INIT_ARRAY,.sh_flags=SHF_ALLOC|SHF_WRITE,
    .sh_offset=sh[8].sh_offset,.sh_size=ctx->initializer_symbol?8:0,.sh_addralign=8,.sh_entsize=8};
  sh[10]=(Elf64_Shdr){.sh_name=86,.sh_type=SHT_RELA,.sh_offset=sh[9].sh_offset+sh[9].sh_size,
    .sh_size=ctx->initializer_symbol?sizeof(Elf64_Rela):0,.sh_link=4,.sh_info=9,.sh_addralign=8,.sh_entsize=sizeof(Elf64_Rela)};
  sh[11]=(Elf64_Shdr){.sh_name=103,.sh_type=SHT_PROGBITS,.sh_flags=SHF_ALLOC|SHF_WRITE,
    .sh_offset=align8(sh[10].sh_offset+sh[10].sh_size),.sh_size=ctx->constants_data.n,.sh_addralign=8};
  sh[12]=(Elf64_Shdr){.sh_name=116,.sh_type=SHT_RELA,.sh_offset=align8(sh[11].sh_offset+sh[11].sh_size),
    .sh_size=ctx->constant_relocation_count*sizeof(*ctx->constant_relocations),.sh_link=4,.sh_info=11,.sh_addralign=8,.sh_entsize=sizeof(Elf64_Rela)};
  size_t cursor=align8(sh[12].sh_offset+sh[12].sh_size);
  for (unsigned i=0;ctx->dwarf && i<4;++i) {
    unsigned section=13+2*i; size_t count=0;
    for (size_t j=0;j<debug.relocation_count;++j) count+=debug.relocations[j].section==i;
    sh[section]=(Elf64_Shdr){.sh_name=(Elf64_Word)debug_name,.sh_type=SHT_PROGBITS,
      .sh_offset=cursor,.sh_size=debug.sections[i].size,.sh_addralign=i==BACKEND_DWARF_FRAME?8:1};
    debug_name+=strlen(section_names+debug_name)+1; cursor=align8(cursor+sh[section].sh_size);
    sh[section+1]=(Elf64_Shdr){.sh_name=(Elf64_Word)debug_name,.sh_type=SHT_RELA,
      .sh_offset=cursor,.sh_size=count*sizeof(Elf64_Rela),.sh_link=4,.sh_info=section,.sh_addralign=8,.sh_entsize=sizeof(Elf64_Rela)};
    debug_name+=strlen(section_names+debug_name)+1; cursor+=sh[section+1].sh_size;
  }
  h.e_shoff=align8(cursor);
  size_t shbytes=h.e_shnum*sizeof(*sh),total=h.e_shoff+shbytes;
  unsigned char *data = calloc(total, 1);
  if (!data) goto done;
  memcpy(data, &h, sizeof(h));
  if (ctx->text.n) memcpy(data+sh[1].sh_offset, ctx->text.data, ctx->text.n);
  if (ctx->rodata.n) memcpy(data+sh[2].sh_offset, ctx->rodata.data, ctx->rodata.n);
  if (relbytes) memcpy(data+sh[3].sh_offset, ctx->relocations, relbytes);
  memcpy(data+sh[4].sh_offset, symbols, symbytes); memcpy(data+sh[5].sh_offset, strings, names);
  memcpy(data+sh[6].sh_offset, section_names, sizeof(section_names));
  if (ctx->initializer_symbol) {
    Elf64_Rela init={.r_info=ELF64_R_INFO(ctx->initializer_symbol,ctx->rv64?2:ctx->a64?R_AARCH64_ABS64:R_X86_64_64)};
    memcpy(data+sh[10].sh_offset,&init,sizeof(init));
  }
  if (ctx->constants_data.n) memcpy(data+sh[11].sh_offset,ctx->constants_data.data,ctx->constants_data.n);
  if (sh[12].sh_size) memcpy(data+sh[12].sh_offset,ctx->constant_relocations,sh[12].sh_size);
  for (unsigned i=0;ctx->dwarf && i<4;++i) {
    unsigned section=13+2*i; size_t count=0;
    if (debug.sections[i].size) memcpy(data+sh[section].sh_offset,debug.sections[i].data,debug.sections[i].size);
    for (size_t j=0;j<debug.relocation_count;++j) {
      const BackendDwarfRelocation *r=&debug.relocations[j]; if (r->section!=i) continue;
      unsigned symbol=r->target==BACKEND_DWARF_TEXT?2:3+r->target;
      unsigned type=ctx->rv64?(r->type==R_X86_64_64?2:1):!ctx->a64?r->type:r->type==R_X86_64_64?R_AARCH64_ABS64:R_AARCH64_ABS32;
      Elf64_Rela relocation={.r_offset=r->offset,.r_info=ELF64_R_INFO(symbol,type),.r_addend=r->addend};
      memcpy(data+sh[section+1].sh_offset+count++*sizeof(relocation),&relocation,sizeof(relocation));
    }
  }
  memcpy(data+h.e_shoff, sh, shbytes);
  /* No output is opened until every function has passed the whitelist. */
  ok = backend_write_object(path,data,total);
  if (!ok) backend_report(ctx, "native backend: failed to write object\n");
  free(data);
done:
  backend_dwarf_output_free(&debug);
  dyn_location_free(&locations);
  free(symbols); free(strings); return ok;
}
typedef enum { TARGET_X64_ELF, TARGET_A64_ELF, TARGET_X64_COFF, TARGET_A64_MACHO, TARGET_X64_MACHO, TARGET_A64_COFF, TARGET_RV64_ELF } ObjectTarget;
static bool object_target_mode(const DynSource *source, const DynIrProgram *ir,
                          const char *path, bool debug, bool debug_info, bool report, ObjectTarget target, bool shared) {
  BackendContext *ctx = calloc(1, sizeof(*ctx));
  if (!ctx) return false;
  bool a64 = target == TARGET_A64_ELF || target == TARGET_A64_MACHO || target == TARGET_A64_COFF;
  ctx->rv64=target==TARGET_RV64_ELF;
  ctx->debug_mode = debug; ctx->report = report; ctx->a64 = a64; ctx->shared = shared;
  ctx->bmi2 = !a64 && !ctx->rv64 && source->context.optimization && source->context.optimization->features &&
              !strcmp(source->context.optimization->features, "+bmi2");
  if (source->context.optimization && source->context.optimization->remarks &&
      source->context.optimization->native_cpu)
    fprintf(stderr, "remark: independent CPU selection: %s\n", ctx->bmi2 ? "+bmi2 variable shifts" : "baseline ISA (no additional implemented host features)");
  ctx->vectorize = !ctx->rv64 && !debug && !debug_info && source->context.optimization && source->context.optimization->level >= 3;
  ctx->optimization_remarks = source->context.optimization && source->context.optimization->remarks;
  ctx->winarm64 = target == TARGET_A64_COFF;
  ctx->win64 = target == TARGET_X64_COFF; ctx->darwin = target == TARGET_A64_MACHO || target == TARGET_X64_MACHO;
  if (debug_info && (!(ctx->dwarf=ctx->rv64?backend_dwarf_create_rv64():a64?backend_dwarf_create_a64():backend_dwarf_create()) ||
                     !(ctx->dwarf_types=calloc(DYN_TYPE_PARAM_BASE, sizeof(*ctx->dwarf_types))))) {
    backend_dwarf_free(ctx->dwarf); free(ctx); return false;
  }
  bool ok = emit_object(ctx, source, ir, path);
  backend_dwarf_free(ctx->dwarf);
  free(ctx->dwarf_types);
  free(ctx->text.data); free(ctx->rodata.data); free(ctx->globals_data.data); free(ctx->constants_data.data);
  free(ctx->strings);
  free(ctx->relocations); free(ctx->constant_relocations);
  free(ctx);
  return ok;
}
static bool object_target(const DynSource *source, const DynIrProgram *ir,
                          const char *path, bool debug, bool debug_info, bool report, ObjectTarget target) {
  return object_target_mode(source, ir, path, debug, debug_info, report, target, false);
}
static bool object_report(const DynSource *source, const DynIrProgram *ir,
                          const char *path, bool debug, bool debug_info, bool report) {
  return object_target(source, ir, path, debug, debug_info, report, TARGET_X64_ELF);
}
static bool object_options(const DynSource *source, const DynIrProgram *ir,
                           const char *path, bool debug, bool debug_info) {
  return object_report(source, ir, path, debug, debug_info, true);
}
static bool object_mode(const DynSource *source,const DynIrProgram *ir,const char *path,bool debug) {
  return object_options(source,ir,path,debug,false);
}
#ifndef DYN_BACKEND_EMBEDDED
/* Retain the benchmark's release-mode entry point. */
static bool object(const DynSource *source, const DynIrProgram *ir, const char *path) {
  return object_mode(source, ir, path, false);
}
int main(int argc, char **argv) {
  bool debug_mode=false,debug_info=false;
  while (argc>3 && (!strcmp(argv[1],"--debug") || !strcmp(argv[1],"--debug-info"))) {
    if (!strcmp(argv[1],"--debug")) debug_mode=true; else debug_info=true;
    --argc; ++argv;
  }
  if (argc != 3) { fprintf(stderr, "usage: scalar-backend [--debug] [--debug-info] input.dyn output.o\n"); return 2; }
  /* This standalone command only writes x86-64 Linux ELF objects. */
#if !defined(__x86_64__) || !defined(__linux__)
  fprintf(stderr, "native backend requires x86-64 Linux host\n"); return 2;
#endif
  DynSource source = {.path = strdup(argv[1])};
  if (!source.path) return 2;
  source.context.target = dyn_target_find("x86_64-linux");
  if (!source.context.target) { fprintf(stderr, "missing x86_64-linux target\n"); return 2; }
  FILE *in = fopen(argv[1], "rb");
  if (!in) { perror(argv[1]); dyn_source_free(&source); return 2; }
  const size_t source_limit = 16u * 1024u * 1024u;
  source.text = calloc(source_limit + 1, 1);
  if (!source.text) { fclose(in); dyn_source_free(&source); return 2; }
  source.length = fread(source.text, 1, source_limit + 1, in);
  bool input_ok = !ferror(in) && source.length <= source_limit;
  fclose(in);
  if (!input_ok) fprintf(stderr, "native backend: unreadable source or source exceeds 16 MiB\n");
  DynAstProgram ast = {0}; DynIrProgram ir = {0}; DynSource merged={0};
  DynSources inputs={.items=&source,.count=1};
  bool ok = input_ok && dyn_sources_merge(&inputs,source.path,&merged)==0;
  if (ok) ok=dyn_analyze(&merged,&ast,(DynAnalysisOptions){0}).checked;
  if (ok) ok = dyn_ir_lower(&ast, &merged, &ir);
  if (ok) ok = debug_info ? object_options(&merged, &ir, argv[2], debug_mode, true)
               : debug_mode ? object_mode(&merged, &ir, argv[2], true) : object(&merged, &ir, argv[2]);
  dyn_ir_free(&ir); dyn_ast_program_free(&ast); dyn_source_free(&merged); dyn_source_free(&source);
  return ok ? 0 : 1;
}

#endif /* DYN_BACKEND_EMBEDDED */
