/* Native x86-64 Linux ELF emitter for checked Dyn IR (debug builds). */
#include "frontend.h"
#include "ir.h"
#include "dyn_location.h"
#include <elf.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "output.h"
#include "dwarf.h"

/* Per-section and per-object byte bound; buffers grow on demand up to it. */
#define LIMIT (1024u * 1024u * 1024u)
/* Fixed per-object capacities; exceeding one fails emission explicitly. */
#define MAX_SYMBOLS 32768
#define MAX_LOCALS 4096
#define MAX_SCRATCH (1u << 21) /* frame eightbytes: 16 MiB */
#define MAX_AGGREGATE (1u << 24)
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
static const char *const runtime_names[] = {"dyn_panic", "dyn_trace_push", "dyn_trace_pop", "dyn_unwind_set", "dyn_unwind_link", "dyn_unwind_unlink", "dyn_unwind_continue", "fmod", "fmodf", "dyn_syscall6"};
#define RUNTIME_COUNT 10
enum { GUARD_OVERFLOW, GUARD_DIVIDE, GUARD_DIVISION_OVERFLOW, GUARD_SHIFT, GUARD_FUNCTION, GUARD_NONNULL, GUARD_ALIGNED, GUARD_INDEX, GUARD_SLICE_ORDER, GUARD_SLICE_BOUNDS, GUARD_ENUM, GUARD_COUNT };
static const char *const guard_names[] = {"overflow.ok", "divide.ok", "division.overflow.ok", "shift.count.ok", "function.nonnull.ok", "pointer.nonnull.ok", "pointer.aligned.ok", "index.ok", "slice.order.ok", "slice.bounds.ok", "enum.cast.ok"};
typedef struct { DynType type; uint32_t offset; } ArrayPart;
typedef struct {
  Bytes text, rodata, globals_data, constants_data;
  BackendDwarf *dwarf;
  const DynSource *debug_source;
  const DynLocationIndex *debug_locations;
  Elf64_Rela *constant_relocations;
  size_t constant_relocation_count, constant_relocation_capacity;
  bool global_static[MAX_SYMBOLS];
  uint32_t constant_offsets[MAX_SYMBOLS];
  Elf64_Rela *relocations;
  size_t relocation_capacity;
  size_t relocation_count, runtime_base, runtime_count;
  unsigned function_symbols[MAX_SYMBOLS], global_symbols[MAX_SYMBOLS];
  unsigned symbol_remap[2 * MAX_SYMBOLS + 16];
  /* Production symbol policy: local bodies named like a foreign link name or exit/_exit get ".dyn". */
  bool function_suffixed[MAX_SYMBOLS];
  unsigned initializer_symbol, initializer_flag_symbol, first_global;
  unsigned runtime_index[RUNTIME_COUNT], stack_slots, frame_bytes, local_words;
  uint32_t local_offsets[MAX_LOCALS];
  bool local_alias[MAX_LOCALS];
  struct { uint32_t id; size_t condition, breaks, continues; unsigned defer_base; } loops[MAX_DEPTH];
  unsigned loop_depth;
  const DynIrProgram *active_ir;
  uint32_t defer_ids[MAX_DEFERS], defer_count, unwind_offset, return_offset, call_offset, sret_offset;
  uint32_t captured_offsets[MAX_NODES], statement_scratch[MAX_NODES], temporary_offsets[MAX_NODES];
  bool visited_expr[MAX_NODES];
  uint32_t pack_offsets[MAX_NODES];
  /* Ids written while sizing one function; reset touches only these, not the program. */
  uint32_t touched_exprs[2 * MAX_NODES], touched_stmts[MAX_NODES];
  size_t touched_expr_count, touched_stmt_count;
  bool unwinding;
  unsigned cleanup_depth;
  bool debug_mode, relocation_failed;
  bool report; /* false: the caller selects another backend silently */
  ArrayPart call_leaves[512];
  /* DWARF lexical scopes: [begin, end) text offsets per local; zero end means
     the variable is visible in the whole function. */
  size_t local_scope_begin[MAX_LOCALS], local_scope_end[MAX_LOCALS];
  uint32_t scope_stack[MAX_LOCALS];
  unsigned scope_count;
  unsigned *dwarf_types; /* DynType -> DWARF type id + 1 for this object; 1 means unknown */
  size_t message_offsets[GUARD_COUNT], message_lengths[GUARD_COUNT];
} BackendContext;
static bool emit_defers(BackendContext *ctx, const DynIrProgram *, const DynIrFunction *, unsigned);
#define backend_report(ctx, ...) do { if ((ctx)->report) fprintf(stderr, __VA_ARGS__); } while (0)
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
static size_t literal(BackendContext *ctx, const char *s, size_t length) {
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
static void runtime_call(BackendContext *ctx, unsigned runtime) {
  if (!ctx->runtime_index[runtime]) ctx->runtime_index[runtime] = (unsigned)(ctx->runtime_base + ctx->runtime_count++);
  byte(ctx, 0xe8); relocate(ctx, ctx->runtime_index[runtime], R_X86_64_PLT32, -4); word(ctx, 0);
}
static void string_arguments(BackendContext *ctx, size_t offset, size_t length) {
  CODE(0x48, 0x8d, 0x3d); /* lea rdi, [rip + string] */
  relocate(ctx, 1, R_X86_64_PC32, (int64_t)offset - 4); word(ctx, 0);
  byte(ctx, 0xbe); word(ctx, (uint32_t)length); /* mov esi, length */
}
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
  unsigned bits=integer_bits(t);
  if (bits == 1) CODE(0x48,0x83,0xe0,1);
  else if (bits == 8) { if (signed_scalar(t)) CODE(0x48,0x0f,0xbe,0xc0); else CODE(0x0f,0xb6,0xc0); }
  else if (bits == 16) { if (signed_scalar(t)) CODE(0x48,0x0f,0xbf,0xc0); else CODE(0x0f,0xb7,0xc0); }
  else if (bits == 32) { if (signed_scalar(t)) CODE(0x48,0x63,0xc0); else CODE(0x89,0xc0); }
}
static unsigned memory_bits(DynType type) { return type==DYN_TYPE_F32?32:integer_bits(type); }
/* Address in RAX for loads; destination in R11 and value in RAX for stores. */
static void load_memory(BackendContext *ctx, DynType type) {
  type=storage_type(ctx->active_ir,type);
  unsigned bits=memory_bits(type);
  if (bits==1 || bits==8) { if (signed_scalar(type)) CODE(0x48,0x0f,0xbe,0x00); else CODE(0x0f,0xb6,0x00); }
  else if (bits==16) { if (signed_scalar(type)) CODE(0x48,0x0f,0xbf,0x00); else CODE(0x0f,0xb7,0x00); }
  else if (bits==32) { if (signed_scalar(type)) CODE(0x48,0x63,0x00); else CODE(0x8b,0x00); }
  else CODE(0x48,0x8b,0x00);
  normalize(ctx, type);
}
static void store_memory(BackendContext *ctx, DynType type) {
  type=storage_type(ctx->active_ir,type);
  unsigned bits=memory_bits(type);
  if (bits==1 || bits==8) CODE(0x41,0x88,0x03);
  else if (bits==16) CODE(0x66,0x41,0x89,0x03);
  else if (bits==32) CODE(0x41,0x89,0x03);
  else CODE(0x49,0x89,0x03);
}
static const char *function_name(const DynIrFunction *f) { return f->foreign ? f->link_name : f->name; }
static void guard(BackendContext *ctx, const DynIrFunction *f, unsigned success, unsigned check) {
  if (ctx->message_offsets[check] == SIZE_MAX) {
    char message[1024];
    const char *name = function_name(f);
    size_t length = strlen(name);
    snprintf(message, sizeof(message), "runtime check failed (%s) in %.*s", guard_names[check],
             (int)(length > 800 ? 800 : length), name);
    ctx->message_lengths[check] = strlen(message);
    ctx->message_offsets[check] = literal(ctx, message, ctx->message_lengths[check]);
  }
  /* The caller supplies a near conditional-jump opcode for success.
     Restore the fixed frame before calling the noreturn runtime: nested
     expression pushes may otherwise leave the call stack misaligned. */
  CODE(0x0f); byte(ctx, success);
  size_t branch = ctx->text.n; word(ctx, 0);
  CODE(0x48, 0x8d, 0xa5); word(ctx, 0u - ctx->frame_bytes); /* restore aligned frame */
  unsigned saved_stack=ctx->stack_slots; ctx->stack_slots=0;
  if (!ctx->unwinding && !emit_defers(ctx, ctx->active_ir,f,0)) ctx->text.failed=true;
  ctx->stack_slots=saved_stack;
  string_arguments(ctx, ctx->message_offsets[check], ctx->message_lengths[check]);
  runtime_call(ctx, 0); CODE(0x0f, 0x0b); /* panic must not return */
  patch_word(ctx, branch, (uint32_t)(ctx->text.n - (branch + 4)));
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
    if (!e->alignment || e->alignment>8 || e->size>MAX_AGGREGATE) return false;
    *size=(uint32_t)e->size; *alignment=(uint32_t)e->alignment; return true;
  }
  if (descriptor(type)) { *size=16; *alignment=8; return true; }
  if (scalar(ir, type)) { *size=*alignment=(memory_bits(type)+7)/8; return true; }
  if (dyn_type_is_array(type)) {
    size_t index=type-DYN_TYPE_ARRAY_BASE; uint32_t element;
    if (index>=ir->array_count || !layout(ir,ir->arrays[index].element,&element,alignment,depth+1) ||
        ir->arrays[index].length>MAX_AGGREGATE || element>MAX_AGGREGATE/(ir->arrays[index].length?ir->arrays[index].length:1)) return false;
    *size=element*(uint32_t)ir->arrays[index].length; return true;
  }
  if (dyn_type_is_struct(type)) {
    size_t index=type-DYN_TYPE_STRUCT_BASE;
    if (index>=ir->struct_count || ir->structs[index].size>MAX_AGGREGATE || ir->structs[index].alignment>8) return false;
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
static bool abi_memory(const DynIrProgram *ir,DynType type) {
  if (raw_aggregate(ir,type)) {
    ArrayPart parts[512]; unsigned count=0,gp=0,fp=0;
    if (!array_parts(ir,type,0,parts,&count,0)) return true;
    for (unsigned i=0;i<count;++i) { if (float_type(parts[i].type)) ++fp; else ++gp; }
    return gp>3 || fp>4;
  }
  unsigned parts,cls[2]; return dyn_type_is_struct(type) && !abi_value(ir,type,&parts,cls);
}
static bool abi_assign(const DynIrProgram *ir,DynType type,unsigned *gp,unsigned *fp,unsigned *parts,int *classes,unsigned capacity) {
  unsigned cls[2];
  if (raw_aggregate(ir,type)) {
    ArrayPart leaves[512]; *parts=0;
    if (!array_parts(ir,type,0,leaves,parts,0) || *parts>capacity) return false;
    for (unsigned i=0;i<*parts;++i) classes[i]=float_type(leaves[i].type)?(*fp<8?(int)(*fp)++ + 8:-1):(*gp<6?(int)(*gp)++:-1);
    return true;
  }
  if (abi_memory(ir,type)) {
    uint32_t size,alignment; if (!layout(ir,type,&size,&alignment,0)) return false;
    *parts=(size+7)/8; if (*parts>capacity) return false;
    for (unsigned i=0;i<*parts;++i) classes[i]=-1;
    return true;
  }
  if (!abi_value(ir,type,parts,cls) || *parts>capacity) return false;
  unsigned integers=0,floats=0;
  for (unsigned i=0;i<*parts;++i) { if (cls[i]==2) ++floats; else ++integers; }
  bool spill=dyn_type_is_struct(type) && (*gp+integers>6 || *fp+floats>8);
  for (unsigned i=0;i<*parts;++i) {
    if (spill) classes[i]=-1;
    else if (cls[i]==2) classes[i]=*fp<8?(int)(*fp)++ + 8:-1;
    else classes[i]=*gp<6?(int)(*gp)++:-1;
  }
  return true;
}
static bool abi_supported(const DynIrProgram *ir,DynType type) {
  if (raw_aggregate(ir,type)) { ArrayPart leaves[512]; unsigned n=0; return array_parts(ir,type,0,leaves,&n,0); }
  uint32_t size,alignment; return type==DYN_TYPE_VOID || value_type(ir, type) ||
    (dyn_type_is_struct(type) && layout(ir,type,&size,&alignment,0));
}
/* Load exactly the occupied bytes from [R11+offset] into R10. Padding must not
   read beyond externally supplied storage at a page boundary. */
static void load_chunk(BackendContext *ctx, unsigned offset,unsigned size) {
  if (size==8) { CODE(0x4d,0x8b,0x93); word(ctx, offset); return; }
  CODE(0x45,0x31,0xd2);
  for (unsigned i=0;i<size;++i) {
    CODE(0x4d,0x0f,0xb6,0x83); word(ctx, offset+i);
    if (i) { CODE(0x49,0xc1,0xe0); byte(ctx, i*8); }
    CODE(0x4d,0x09,0xc2);
  }
}
static void save_struct(BackendContext *ctx, uint32_t offset,DynType type) {
  uint32_t size,alignment; if (!layout(ctx->active_ir,type,&size,&alignment,0)) { ctx->text.failed=true; return; }
  CODE(0x49,0x89,0xc3);
  for (unsigned part=0;part<(size+7)/8;++part) {
    load_chunk(ctx, part*8,size-part*8>8?8:size-part*8);
    CODE(0x4c,0x89,0x95); word(ctx, offset+part*8);
  }
}
static void checked_address(BackendContext *ctx, const DynIrFunction *f, DynType pointee) {
  CODE(0x48,0x85,0xc0); guard(ctx, f,0x85,GUARD_NONNULL);
  uint32_t size,alignment;
  if (!layout(ctx->active_ir,pointee,&size,&alignment,0)) { ctx->text.failed=true; return; }
  if (alignment>1) { CODE(0x48,0xa9); word(ctx, alignment-1); guard(ctx, f,0x84,GUARD_ALIGNED); }
}
static void overflow_guard(BackendContext *ctx, const DynIrFunction *f, bool signed_operation) {
  /* JNO for signed operations; JNC for unsigned carry/borrow and MUL. */
  guard(ctx, f, signed_operation ? 0x81 : 0x83, GUARD_OVERFLOW);
}
static void divide(BackendContext *ctx, const DynIrFunction *f, bool signed_operation, bool remainder, unsigned bits) {
  CODE(0x48, 0x85, 0xc9); /* test rcx, rcx */
  guard(ctx, f, 0x85, GUARD_DIVIDE); /* jne: divisor must not be zero */
  if (signed_operation) {
    CODE(0x48, 0xba); immediate(ctx, UINT64_C(0) - (UINT64_C(1) << (bits-1))); /* movabs rdx, INT64_MIN */
    CODE(0x48, 0x39, 0xd0, 0x0f, 0x85); /* cmp rax, rdx; jne safe */
    size_t skip = ctx->text.n; word(ctx, 0);
    CODE(0x48, 0x83, 0xf9, 0xff); /* cmp rcx, -1 */
    guard(ctx, f, 0x85, GUARD_DIVISION_OVERFLOW);
    patch_word(ctx, skip, (uint32_t)(ctx->text.n - (skip + 4)));
    CODE(0x48, 0x99, 0x48, 0xf7, 0xf9); /* cqo; idiv rcx */
  } else CODE(0x31, 0xd2, 0x48, 0xf7, 0xf1); /* xor edx, edx; div rcx */
  if (remainder) CODE(0x48, 0x89, 0xd0); /* mov rax, rdx */
}
static void shift(BackendContext *ctx, const DynIrFunction *f, bool signed_operation, bool left, bool wraps, unsigned bits) {
  /* Unsigned comparison also rejects negative signed counts. This dominates
     the redundant narrowed-count check in LLVM's checked_integer lowering. */
  CODE(0x48, 0x83, 0xf9); byte(ctx, bits); /* cmp rcx, 64 */
  guard(ctx, f, 0x82, GUARD_SHIFT); /* jb: original count is in [0, 63] */
  if (!left) {
    CODE(0x48, 0xd3); byte(ctx, signed_operation ? 0xf8 : 0xe8); /* sar/shr rax, cl */
    return;
  }
  if (!wraps) CODE(0x48, 0x89, 0xc2); /* preserve original rax in rdx */
  CODE(0x48, 0xd3, 0xe0); /* shl rax, cl */
  if (!wraps) {
    CODE(0x49, 0x89, 0xc0, 0x49, 0xd3); /* copy result to r8, restore by sar/shr */
    byte(ctx, signed_operation ? 0xf8 : 0xe8);
    CODE(0x49, 0x39, 0xd0); /* cmp r8, rdx */
    guard(ctx, f, 0x84, GUARD_OVERFLOW); /* je: no value/sign bits lost */
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
  if (ctx->unwinding && ctx->captured_offsets[id] && aggregate(ir, ir->expressions[id].type)) { CODE(0x48,0x8d,0x85); word(ctx, ctx->captured_offsets[id]); return !ctx->text.failed; }
  if (ctx->unwinding && ctx->captured_offsets[id]) { CODE(0x48,0x8b,0x85); word(ctx, ctx->captured_offsets[id]); if (descriptor(ir->expressions[id].type)) { CODE(0x48,0x8b,0x95); word(ctx, ctx->captured_offsets[id]+8); } return !ctx->text.failed; }
  return expression_value(ctx, ir, f, &ir->expressions[id], depth);
}
static bool index_expression(BackendContext *ctx, const DynIrProgram *ir,const DynIrFunction *f,DynExprId id,unsigned depth) {
  if (!expression(ctx, ir,f,id,depth)) return false;
  unsigned bits=integer_bits(ir->expressions[id].type);
  if (bits<64) { CODE(0x48,0xba); immediate(ctx, (UINT64_C(1)<<bits)-1); CODE(0x48,0x21,0xd0); }
  return !ctx->text.failed;
}
static bool local_slot(BackendContext *ctx, const DynIrFunction *f, uint64_t id, uint32_t *offset) {
  if (id < f->local_start || id - f->local_start >= f->local_count) return false;
  *offset = ctx->local_offsets[id-f->local_start];
  return true;
}
static bool address(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f, DynExprId id, unsigned depth) {
  if (id>=ir->expression_count || depth > MAX_DEPTH) return false;
  const DynIrExpr *e=&ir->expressions[id]; uint32_t offset;
  if (e->kind==DYN_EXPR_NAME) {
    if (!local_slot(ctx, f,e->integer,&offset)) return false;
    CODE(0x48); byte(ctx,ctx->local_alias[e->integer-f->local_start]?0x8b:0x8d); byte(ctx,0x85); word(ctx, offset);
  } else if (e->kind==DYN_EXPR_GLOBAL) {
    if (e->integer>=ir->global_count) return false;
    CODE(0x48,0x8b,0x05); relocate(ctx, ctx->global_symbols[e->integer],R_X86_64_GOTPCREL,-4); word(ctx, 0);
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
    CODE(0x48,0x05); word(ctx, offset);
  } else if (e->kind==DYN_EXPR_INDEX) {
    if (e->left>=ir->expression_count || e->right>=ir->expression_count) return false;
    DynType type=ir->expressions[e->left].type;
    bool array=dyn_type_is_array(type);
    if (!array && !descriptor(type)) return false;
    if (array && type-DYN_TYPE_ARRAY_BASE>=ir->array_count) return false;
    uint32_t size,alignment;
    if (!layout(ir,e->type,&size,&alignment,0) || !expression(ctx, ir,f,e->right,depth+1)) return false;
    unsigned bits=integer_bits(ir->expressions[e->right].type);
    if (bits<64) { CODE(0x48,0xba); immediate(ctx, (UINT64_C(1)<<bits)-1); CODE(0x48,0x21,0xd0); }
    CODE(0x50); ++ctx->stack_slots;
    if (array) {
      if (!address(ctx, ir,f,e->left,depth+1)) return false;
      CODE(0x48,0xba); immediate(ctx, ir->arrays[type-DYN_TYPE_ARRAY_BASE].length);
    } else if (!expression(ctx, ir,f,e->left,depth+1)) return false;
    CODE(0x59); --ctx->stack_slots;
    CODE(0x48,0x39,0xd1); guard(ctx, f,0x82,GUARD_INDEX);
    CODE(0x48,0x69,0xc9); word(ctx, size); CODE(0x48,0x01,0xc8);
  } else if (ctx->temporary_offsets[id]) return expression(ctx, ir,f,id,depth+1);
  else return false;
  return !ctx->text.failed && !ctx->relocation_failed;
}
static bool protect_call(BackendContext *ctx, const DynIrProgram *ir,const DynIrFunction *f) {
  unsigned padding=ctx->stack_slots&1;
  if (padding) CODE(0x48,0x83,0xec,8);
  CODE(0x48,0x8d,0xbd); word(ctx, ctx->unwind_offset); runtime_call(ctx, 3);
  CODE(0x85,0xc0,0x0f,0x84); size_t normal=ctx->text.n; word(ctx, 0);
  CODE(0x48,0x8d,0xa5); word(ctx, 0u-ctx->frame_bytes);
  unsigned saved_stack=ctx->stack_slots; ctx->stack_slots=0;
  if (!emit_defers(ctx, ir,f,0)) return false;
  ctx->stack_slots=saved_stack;
  runtime_call(ctx, 6); CODE(0x0f,0x0b);
  patch_word(ctx, normal,(uint32_t)(ctx->text.n-normal-4));
  CODE(0x48,0x8d,0xbd); word(ctx, ctx->unwind_offset); runtime_call(ctx, 4);
  if (padding) CODE(0x48,0x83,0xc4,8);
  return !ctx->text.failed;
}
static bool initialize(BackendContext *ctx, const DynIrProgram *,const DynIrFunction *,DynType,DynExprId,unsigned);
/* Calls keep their ABI classification arrays out of the recursive expression
   frame, so nested expressions use little stack per level. */
static bool call_with(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                      const DynIrExpr *e, unsigned depth, int *classes) {
  bool indirect=e->kind == DYN_EXPR_INDIRECT_CALL;
  if (e->item_count > 512 || (uint64_t)e->item_start+e->item_count > ir->item_count) return false;
  bool sret=abi_memory(ir,e->type);
  unsigned argument_count=0,gp=sret?1:0,fp=0,outgoing=0;
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
      unsigned parts;
      if (!abi_assign(ir,type,&gp,&fp,&parts,classes+argument_count,512-argument_count)) return false;
      argument_count+=parts;
    }
    if (!expression(ctx, ir,f,e->left,depth+1)) return false;
    CODE(0x48,0x85,0xc0); guard(ctx, f,0x85,GUARD_FUNCTION);
    CODE(0x50); ++ctx->stack_slots;
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
      unsigned parts;
      if (!abi_assign(ir,type,&gp,&fp,&parts,classes+argument_count,512-argument_count)) return false;
      argument_count+=parts;
    }
  }
  /* Keep arguments on the expression stack in source order. Nested calls
     cannot clobber earlier arguments; registers are loaded only afterwards. */
  for (uint32_t i = 0; i < (packed?fixed:e->item_count); ++i) {
    if (!expression(ctx, ir, f, ir->items[e->item_start + i].expression, depth + 1)) return false;
    DynType type=ir->expressions[ir->items[e->item_start+i].expression].type;
    if (raw_aggregate(ir,type)) {
      ArrayPart *leaves=ctx->call_leaves;unsigned count=0;
      if (!array_parts(ir,type,0,leaves,&count,0)) return false;
      CODE(0x49,0x89,0xc3);
      for (unsigned part=0;part<count;++part) { load_chunk(ctx, leaves[part].offset,(memory_bits(leaves[part].type)+7)/8); CODE(0x41,0x52); ++ctx->stack_slots; }
    } else if (dyn_type_is_struct(type)) {
      uint32_t size,alignment; if (!layout(ir,type,&size,&alignment,0)) return false;
      CODE(0x49,0x89,0xc3);
      for (unsigned part=0;part<(size+7)/8;++part) { load_chunk(ctx, part*8,size-part*8>8?8:size-part*8); CODE(0x41,0x52); ++ctx->stack_slots; }
    } else { CODE(0x50); ++ctx->stack_slots; if (descriptor(type)) { CODE(0x52); ++ctx->stack_slots; } }
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
        CODE(0x48,0x8d,0x85); word(ctx,boxed);
        if (!initialize(ctx,ir,f,type,argument,depth+1)) return false;
        CODE(0x48,0xb8); immediate(ctx,type); CODE(0x48,0x89,0x85); word(ctx,offset+i*size);
        CODE(0x48,0x8d,0x85); word(ctx,boxed); CODE(0x48,0x89,0x85); word(ctx,offset+i*size+8);
        boxed+=(value_size?value_size+7:8)/8*8;
      } else {
        CODE(0x48,0x8d,0x85); word(ctx,offset+i*size);
        if (!initialize(ctx,ir,f,pack_type,argument,depth+1)) return false;
      }
    }
    if (count) { CODE(0x48,0x8d,0x85); word(ctx,offset); } else CODE(0x31,0xc0);
    CODE(0x50,0xb8); word(ctx,count); CODE(0x50); ctx->stack_slots+=2;
  }
  bool protected_call=ctx->defer_count && !ctx->unwinding;
  if (protected_call && !protect_call(ctx, ir,f)) return false;
  const unsigned char registers[] = {0xbc, 0xb4, 0x94, 0x8c, 0x84, 0x8c};
  for (uint32_t i=0;i<argument_count;++i) {
    bool floating=classes[i]>=8;
    if (classes[i]<0) { ++outgoing; continue; }
    if (floating) { CODE(0xf3,0x0f,0x7e); byte(ctx, 0x84+8*(unsigned)(classes[i]-8)); byte(ctx, 0x24); }
    else { byte(ctx, classes[i]<4?0x48:0x4c); byte(ctx, 0x8b); byte(ctx, registers[classes[i]]); byte(ctx, 0x24); }
    word(ctx, 8*(argument_count-i-1));
  }
  unsigned padding=(ctx->stack_slots+outgoing)&1, reserved=(outgoing+padding)*8;
  if (reserved) { CODE(0x48,0x81,0xec); word(ctx, reserved); }
  unsigned spilled=0;
  for (uint32_t i=0;i<argument_count;++i) if (classes[i]<0) {
    CODE(0x48,0x8b,0x84,0x24); word(ctx, reserved+8*(argument_count-i-1));
    CODE(0x48,0x89,0x84,0x24); word(ctx, 8*spilled++);
  }
  if (sret) { CODE(0x48,0x8d,0xbd); word(ctx, ctx->temporary_offsets[e-ir->expressions]); }
  if (variadic) { byte(ctx,0xb8); word(ctx,fp); } /* SysV vector register count in AL. */
  if (indirect) {
    CODE(0x4c,0x8b,0x9c,0x24); word(ctx, reserved+argument_count*8);
    CODE(0x41,0xff,0xd3); /* call r11 */
  } else { byte(ctx, 0xe8); relocate(ctx, ctx->function_symbols[e->integer], R_X86_64_PLT32, -4); word(ctx, 0); }
  unsigned cleanup = (argument_count + indirect) * 8 + reserved;
  if (cleanup) { CODE(0x48, 0x81, 0xc4); word(ctx, cleanup); }
  ctx->stack_slots -= argument_count + indirect;
  if (raw_aggregate(ir,e->type)) {
    DynExprId id=(DynExprId)(e-ir->expressions); if (!ctx->temporary_offsets[id]) return false;
    if (!sret) {
      ArrayPart *leaves=ctx->call_leaves; unsigned count=0,gp=0,fp=0;
      if (!array_parts(ir,e->type,0,leaves,&count,0)) return false;
      /* Preserve the three GP/two SSE return registers before scratch loads. */
      CODE(0x50,0x52,0x51,0x66,0x49,0x0f,0x7e,0xc2,0x41,0x52,0x66,0x49,0x0f,0x7e,0xca,0x41,0x52); ctx->stack_slots+=5;
      for (unsigned part=0;part<count;++part) {
        DynType type=leaves[part].type; uint32_t at=ctx->temporary_offsets[id]+leaves[part].offset;
        if (float_type(type) && fp>=2) {
          byte(ctx, type==DYN_TYPE_F32?0xd9:0xdd); byte(ctx, 0x9d); word(ctx, at); ++fp;
        } else {
          unsigned slot=float_type(type)?3+fp++:gp++;
          CODE(0x48,0x8b,0x84,0x24); word(ctx, 8*(4-slot)); normalize(ctx, type);
          CODE(0x4c,0x8d,0x9d); word(ctx, at); store_memory(ctx, type);
        }
      }
      CODE(0x48,0x83,0xc4,40); ctx->stack_slots-=5;
    }
    CODE(0x48,0x8d,0x85); word(ctx, ctx->temporary_offsets[id]);
  } else if (dyn_type_is_struct(e->type)) {
    unsigned parts,cls[2],integers=0,floats=0; DynExprId id=(DynExprId)(e-ir->expressions);
    if (!ctx->temporary_offsets[id]) return false;
    parts=0;
    if (!sret && !abi_value(ir,e->type,&parts,cls)) return false;
    for (unsigned part=0;part<parts;++part) {
      if (cls[part]==2) { CODE(0x66,0x49,0x0f,0x7e); byte(ctx, 0xc2+8*floats++); CODE(0x4c,0x89,0x95); }
      else { CODE(0x48,0x89); byte(ctx, integers++?0x95:0x85); }
      word(ctx, ctx->temporary_offsets[id]+part*8);
    }
    CODE(0x48,0x8d,0x85); word(ctx, ctx->temporary_offsets[id]);
  }
  if (float_type(e->type)) CODE(0x66,0x48,0x0f,0x7e,0xc0); /* xmm0 result to bit carrier */
  normalize(ctx, e->type);
  if (protected_call) {
    CODE(0x48,0x89,0x85); word(ctx, ctx->call_offset);
    if (descriptor(e->type)) { CODE(0x48,0x89,0x95); word(ctx, ctx->call_offset+8); }
    if (ctx->stack_slots&1) CODE(0x48,0x83,0xec,8);
    CODE(0x48,0x8d,0xbd); word(ctx, ctx->unwind_offset); runtime_call(ctx, 5);
    if (ctx->stack_slots&1) CODE(0x48,0x83,0xc4,8);
    CODE(0x48,0x8b,0x85); word(ctx, ctx->call_offset);
    if (descriptor(e->type)) { CODE(0x48,0x8b,0x95); word(ctx, ctx->call_offset+8); }
  }
  return !ctx->text.failed && !ctx->rodata.failed && !ctx->relocation_failed;
}
/* Argument classes live across nested argument evaluation, so each call level
   owns a heap block; array leaves are filled and consumed without recursion. */
static bool call_value(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                       const DynIrExpr *e, unsigned depth) {
  int *classes = malloc(512 * sizeof(*classes));
  if (!classes) return false;
  bool ok = call_with(ctx, ir, f, e, depth, classes);
  free(classes);
  return ok;
}
static bool expression_value(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                             const DynIrExpr *e, unsigned depth) {
  if (e->kind==DYN_EXPR_SYSCALL) {
    if (e->item_count>7 || (uint64_t)e->item_start+e->item_count>ir->item_count) return false;
    for (unsigned i=0;i<7;++i) {
      if (i<e->item_count) {
        DynExprId id=ir->items[e->item_start+i].expression;
        if (id>=ir->expression_count || !scalar(ir,ir->expressions[id].type) || !expression(ctx,ir,f,id,depth+1)) return false;
      } else CODE(0x31,0xc0);
      CODE(0x50); ++ctx->stack_slots;
    }
    const unsigned char regs[]={0xbc,0xb4,0x94,0x8c,0x84,0x8c};
    for (unsigned i=0;i<6;++i) { byte(ctx,i<4?0x48:0x4c); CODE(0x8b); byte(ctx,regs[i]); byte(ctx,0x24); word(ctx,8*(6-i)); }
    unsigned reserved=(1+((ctx->stack_slots+1)&1))*8;
    CODE(0x48,0x8b,0x04,0x24,0x48,0x81,0xec); word(ctx,reserved); CODE(0x48,0x89,0x04,0x24);
    runtime_call(ctx,9); CODE(0x48,0x81,0xc4); word(ctx,reserved+56); ctx->stack_slots-=7;
    return !ctx->text.failed && !ctx->relocation_failed;
  }
  if (e->kind==DYN_EXPR_ENUM) {
    if (!dyn_type_is_enum(e->type) || e->type-DYN_TYPE_ENUM_BASE>=ir->enum_count || e->integer>=ir->variant_count) return false;
    const DynIrEnum *en=&ir->enums[e->type-DYN_TYPE_ENUM_BASE];
    const DynIrVariant *variant=&ir->variants[e->integer];
    if (!en->has_payload) { CODE(0x48,0xb8); immediate(ctx,variant->tag); normalize(ctx,e->type); return true; }
    DynExprId id=(DynExprId)(e-ir->expressions); uint32_t offset=ctx->temporary_offsets[id];
    if (!offset) return false;
    CODE(0x48,0x8d,0x85); word(ctx,offset);
    if (!initialize(ctx,ir,f,e->type,DYN_NO_EXPR,depth+1)) return false;
    CODE(0x4c,0x8d,0x9d); word(ctx,offset); CODE(0x48,0xb8); immediate(ctx,variant->tag); store_memory(ctx,en->tag_type);
    if (variant->payload_type!=DYN_TYPE_VOID) {
      if (e->item_count!=1 || e->item_start>=ir->item_count) return false;
      uint32_t tag_size=(memory_bits(en->tag_type)+7)/8, a=(uint32_t)en->payload_alignment;
      CODE(0x48,0x8d,0x85); word(ctx,offset+((tag_size+a-1)&~(a-1)));
      if (!initialize(ctx,ir,f,variant->payload_type,ir->items[e->item_start].expression,depth+1)) return false;
    }
    CODE(0x48,0x8d,0x85); word(ctx,offset); return !ctx->text.failed;
  }
  if (e->kind==DYN_EXPR_CONVERT && e->type==DYN_TYPE_ANY) {
    if (e->left>=ir->expression_count) return false;
    uint32_t offset=ctx->temporary_offsets[e-ir->expressions]; if (!offset) return false;
    DynType source=ir->expressions[e->left].type;
    CODE(0x48,0x8d,0x85); word(ctx,offset);
    if (!initialize(ctx,ir,f,source,e->left,depth+1)) return false;
    CODE(0x48,0x8d,0x95); word(ctx,offset); CODE(0x48,0xb8); immediate(ctx,source); return !ctx->text.failed;
  }
  if (e->kind==DYN_EXPR_STRUCT || e->kind==DYN_EXPR_ARRAY) {
    DynExprId id=(DynExprId)(e-ir->expressions);
    if (!ctx->temporary_offsets[id]) return false;
    CODE(0x48,0x8d,0x85); word(ctx, ctx->temporary_offsets[id]);
    return initialize(ctx, ir,f,e->type,id,depth+1);
  }
  if (descriptor(e->type)) {
    if (e->kind==DYN_EXPR_NIL) { CODE(0x31,0xc0,0x31,0xd2); return true; }
    if (e->kind==DYN_EXPR_STRING) {
      if (e->integer>=ir->string_count) return false;
      const DynIrString *string=&ir->strings[e->integer]; size_t at=literal(ctx, (const char*)string->data,string->length);
      CODE(0x48,0x8d,0x05); relocate(ctx, 1,R_X86_64_PC32,(int64_t)at-4); word(ctx, 0);
      CODE(0x48,0xba); immediate(ctx, string->length); return !ctx->rodata.failed;
    }
    if (e->kind==DYN_EXPR_CONVERT) {
      return e->left<ir->expression_count && descriptor(ir->expressions[e->left].type) && expression(ctx, ir,f,e->left,depth+1);
    }
    if (e->kind==DYN_EXPR_GLOBAL || e->kind==DYN_EXPR_NAME || e->kind==DYN_EXPR_FIELD || e->kind==DYN_EXPR_INDEX ||
        (e->kind==DYN_EXPR_UNARY && e->op==DYN_OP_DEREF)) {
      if (!address(ctx, ir,f,(DynExprId)(e-ir->expressions),depth+1)) return false;
      CODE(0x48,0x8b,0x50,8,0x48,0x8b,0x00); return !ctx->text.failed;
    }
    if (e->kind==DYN_EXPR_SLICE) {
      if (e->left>=ir->expression_count) return false;
      DynType base=ir->expressions[e->left].type; bool raw=dyn_type_is_pointer(base);
      if (dyn_type_is_array(base)) {
        if (base-DYN_TYPE_ARRAY_BASE>=ir->array_count || !address(ctx, ir,f,e->left,depth+1)) return false;
        CODE(0x48,0xba); immediate(ctx, ir->arrays[base-DYN_TYPE_ARRAY_BASE].length);
      } else if (raw) {
        if (base-DYN_TYPE_POINTER_BASE>=ir->pointer_count || !expression(ctx, ir,f,e->left,depth+1)) return false;
        checked_address(ctx, f,ir->pointers[base-DYN_TYPE_POINTER_BASE].pointee); CODE(0x31,0xd2);
      } else if (!descriptor(base) || !expression(ctx, ir,f,e->left,depth+1)) return false;
      CODE(0x50,0x52); ctx->stack_slots+=2;
      if (e->right==DYN_NO_EXPR) CODE(0x31,0xc0);
      else if (!index_expression(ctx, ir,f,e->right,depth+1)) return false;
      CODE(0x50); ++ctx->stack_slots;
      if (e->integer==DYN_NO_EXPR && !raw) CODE(0x48,0x8b,0x44,0x24,8);
      else if (!index_expression(ctx, ir,f,(DynExprId)e->integer,depth+1)) return false;
      CODE(0x59); --ctx->stack_slots; /* start RCX, end RAX */
      CODE(0x48,0x39,0xc1); guard(ctx, f,0x86,GUARD_SLICE_ORDER);
      if (!raw) { CODE(0x48,0x3b,0x04,0x24); guard(ctx, f,0x86,GUARD_SLICE_BOUNDS); }
      CODE(0x48,0x89,0xc2,0x48,0x29,0xca,0x48,0x83,0xc4,8,0x58); ctx->stack_slots-=2;
      DynType element=e->type==DYN_TYPE_STRING?DYN_TYPE_U8:ir->slices[e->type-DYN_TYPE_SLICE_BASE].element;
      uint32_t size,alignment; if (!layout(ir,element,&size,&alignment,0)) return false;
      CODE(0x48,0x69,0xc9); word(ctx, size); CODE(0x48,0x01,0xc8); return !ctx->text.failed;
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
      CODE(0x48,0x89,0xd0); return !ctx->text.failed;
    }
    if (!dyn_type_is_array(type) || type-DYN_TYPE_ARRAY_BASE>=ir->array_count) return false;
    CODE(0x48,0xb8); immediate(ctx, ir->arrays[type-DYN_TYPE_ARRAY_BASE].length); return !ctx->text.failed;
  }
  if (!value_type(ir, e->type) && !((e->type==DYN_TYPE_VOID || abi_supported(ir,e->type)) && (e->kind==DYN_EXPR_CALL || e->kind==DYN_EXPR_INDIRECT_CALL))) return false;
  if (e->kind == DYN_EXPR_FLOAT) {
    uint64_t bits=0;
    if (e->type==DYN_TYPE_F32) { float value=(float)e->floating; uint32_t raw; memcpy(&raw,&value,4); bits=raw; }
    else memcpy(&bits,&e->floating,8);
    CODE(0x48,0xb8); immediate(ctx, bits); return !ctx->text.failed;
  }
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_CHAR || e->kind == DYN_EXPR_BOOL) {
    uint64_t n = e->kind == DYN_EXPR_BOOL ? e->boolean : e->integer;
    CODE(0x48, 0xb8); /* movabs rax, immediate */
    immediate(ctx, n); normalize(ctx, e->type);
    return true;
  }
  if (e->kind == DYN_EXPR_NAME) {
    uint32_t offset;
    if (!local_slot(ctx, f, e->integer, &offset)) return false;
    CODE(0x48, 0x8b, 0x85); word(ctx, offset);
    if (ctx->local_alias[e->integer-f->local_start]) load_memory(ctx,e->type);
    normalize(ctx, e->type);
    return true;
  }
  if (e->kind == DYN_EXPR_GLOBAL) {
    if (e->integer >= ir->global_count || !ctx->global_symbols[e->integer]) return false;
    CODE(0x48,0x8b,0x05); relocate(ctx, ctx->global_symbols[e->integer],R_X86_64_GOTPCREL,-4); word(ctx, 0);
    load_memory(ctx, e->type); return !ctx->text.failed && !ctx->relocation_failed;
  }
  if (e->kind == DYN_EXPR_FUNCTION) {
    if (e->integer >= ir->function_count || !ctx->function_symbols[e->integer]) return false;
    CODE(0x48,0x8b,0x05); relocate(ctx, ctx->function_symbols[e->integer],R_X86_64_GOTPCREL,-4); word(ctx, 0);
    return !ctx->text.failed && !ctx->relocation_failed;
  }
  if (e->kind == DYN_EXPR_NIL && (dyn_type_is_pointer(e->type) || e->type==DYN_TYPE_RAWPTR)) { CODE(0x31,0xc0); return true; }
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
      CODE(0x45,0x31,0xc0);
      for (unsigned i=0;i<en->variant_count;++i) {
        uint64_t tag=ir->variants[en->variant_start+i].tag; unsigned bits=integer_bits(en->tag_type);
        if (signed_scalar(en->tag_type) && bits<64 && (tag>>(bits-1)&1)) tag|=UINT64_MAX<<bits;
        if (signed_scalar(from)!=signed_scalar(en->tag_type) && (int64_t)tag<0) continue;
        CODE(0x48,0xb9); immediate(ctx,tag); CODE(0x48,0x39,0xc8,0x0f,0x94,0xc1,0x41,0x08,0xc8);
      }
      CODE(0x45,0x84,0xc0); guard(ctx,f,0x85,GUARD_ENUM); normalize(ctx,e->type); return !ctx->text.failed;
    }
    bool from_pointer=dyn_type_is_pointer(from)||from==DYN_TYPE_RAWPTR;
    bool to_pointer=dyn_type_is_pointer(e->type)||e->type==DYN_TYPE_RAWPTR;
    bool pointer_conversion=(from_pointer||to_pointer) &&
      (from_pointer||integer_type(from)) && (to_pointer||integer_type(e->type));
    bool integer_float=integer_type(from)&&float_type(e->type), float_integer=float_type(from)&&integer_type(e->type);
    if (!((integer_type(e->type)&&integer_type(from)) || (float_type(e->type)&&float_type(from)) || pointer_conversion || integer_float || float_integer) ||
        !expression(ctx, ir,f,e->left,depth+1)) return false;
    if (integer_float) {
      unsigned prefix=e->type==DYN_TYPE_F32?0xf3:0xf2;
      CODE(0x0f,0x57,0xc0); /* clear upper carrier bits for scalar f32 conversion */
      if (!signed_scalar(from) && integer_bits(from)==64) {
        CODE(0x48,0x85,0xc0,0x0f,0x89); size_t ordinary=ctx->text.n; word(ctx, 0);
        /* Sticky low bit preserves exact rounding when halving an unsigned i64. */
        CODE(0x48,0x89,0xc1,0x83,0xe1,1,0x48,0xd1,0xe8,0x48,0x09,0xc8);
        byte(ctx, prefix); CODE(0x48,0x0f,0x2a,0xc0);
        byte(ctx, prefix); CODE(0x0f,0x58,0xc0,0xe9); size_t done=ctx->text.n; word(ctx, 0);
        patch_word(ctx, ordinary,(uint32_t)(ctx->text.n-ordinary-4));
        byte(ctx, prefix); CODE(0x48,0x0f,0x2a,0xc0);
        patch_word(ctx, done,(uint32_t)(ctx->text.n-done-4));
      } else { byte(ctx, prefix); CODE(0x48,0x0f,0x2a,0xc0); }
      CODE(0x66,0x48,0x0f,0x7e,0xc0); return !ctx->text.failed;
    }
    if (float_integer) {
      unsigned prefix=from==DYN_TYPE_F32?0xf3:0xf2;
      CODE(0x66,0x48,0x0f,0x6e,0xc0);
      if (!signed_scalar(e->type) && integer_bits(e->type)==64) {
        CODE(0x48,0xb9); immediate(ctx, from==DYN_TYPE_F32?UINT64_C(0x5f000000):UINT64_C(0x43e0000000000000));
        CODE(0x66,0x48,0x0f,0x6e,0xc9);
        if (from==DYN_TYPE_F64) byte(ctx, 0x66);
        CODE(0x0f,0x2e,0xc1,0x0f,0x82); size_t ordinary=ctx->text.n; word(ctx, 0);
        byte(ctx, prefix); CODE(0x0f,0x5c,0xc1);
        byte(ctx, prefix); CODE(0x48,0x0f,0x2c,0xc0);
        CODE(0x48,0xb9); immediate(ctx, UINT64_C(1)<<63); CODE(0x48,0x31,0xc8,0xe9); size_t done=ctx->text.n; word(ctx, 0);
        patch_word(ctx, ordinary,(uint32_t)(ctx->text.n-ordinary-4));
        byte(ctx, prefix); CODE(0x48,0x0f,0x2c,0xc0);
        patch_word(ctx, done,(uint32_t)(ctx->text.n-done-4));
      } else { byte(ctx, prefix); CODE(0x48,0x0f,0x2c,0xc0); }
      normalize(ctx, e->type); return !ctx->text.failed;
    }
    /* LLVM inttoptr zero-extends the source bitwidth, even for signed integers. */
    if (to_pointer && integer_type(from) && integer_bits(from)<64) {
      CODE(0x48,0xba); immediate(ctx, (UINT64_C(1)<<integer_bits(from))-1); CODE(0x48,0x21,0xd0);
    }
    if (float_type(e->type) && e->type!=from) {
      CODE(0x66,0x48,0x0f,0x6e,0xc0); byte(ctx, from==DYN_TYPE_F32?0xf3:0xf2);
      CODE(0x0f,0x5a,0xc0,0x66,0x48,0x0f,0x7e,0xc0);
    }
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
      CODE(0x48,0xba); immediate(ctx, UINT64_C(1)<<(e->type==DYN_TYPE_F32?31:63));
      CODE(0x48,0x31,0xd0); return !ctx->text.failed;
    }
    if (e->op != DYN_OP_BIT_NOT && e->op != DYN_OP_NOT &&
        e->op != DYN_OP_NEG) return false;
    /* The checked frontend marks the signed minimum literal specially: its
       unsigned magnitude is not an independently representable signed value. */
    if (e->op == DYN_OP_NEG && e->boolean) {
      if (e->left >= ir->expression_count || ir->expressions[e->left].kind != DYN_EXPR_INT) return false;
      CODE(0x48, 0xb8); immediate(ctx, UINT64_C(0) - ir->expressions[e->left].integer);
      return true;
    }
    if (!expression(ctx, ir, f, e->left, depth + 1)) return false;
    if (e->op == DYN_OP_BIT_NOT) CODE(0x48, 0xf7, 0xd0);
    else if (e->op == DYN_OP_NEG) {
      CODE(0x48, 0xf7, 0xd8);
      if (!e->wrap) overflow_guard(ctx, f, signed_scalar(e->type));
    }
    else CODE(0x48, 0x83, 0xf0, 1);
    bool check=e->op == DYN_OP_NEG && !e->wrap && integer_bits(e->type)<64;
    if (check) CODE(0x49,0x89,0xc2);
    normalize(ctx, e->type);
    if (check) { CODE(0x4c,0x39,0xd0); guard(ctx, f,0x84,GUARD_OVERFLOW); }
    return !ctx->text.failed;

  }
  if (e->kind != DYN_EXPR_BINARY) return false;
  if (e->op == DYN_OP_LOGICAL_AND || e->op == DYN_OP_LOGICAL_OR) {
    if (!expression(ctx, ir, f, e->left, depth + 1)) return false;
    CODE(0x48, 0x85, 0xc0, 0x0f); /* test rax, rax; je/jne done */
    byte(ctx, e->op == DYN_OP_LOGICAL_AND ? 0x84 : 0x85);
    size_t skip = ctx->text.n; word(ctx, 0);
    if (!expression(ctx, ir, f, e->right, depth + 1)) return false;
    patch_word(ctx, skip, (uint32_t)(ctx->text.n - (skip + 4)));
    return !ctx->text.failed && !ctx->rodata.failed && !ctx->relocation_failed;
  }
  bool comparison = e->op >= DYN_OP_EQ && e->op <= DYN_OP_GE;
  if (e->op != DYN_OP_BIT_AND && e->op != DYN_OP_BIT_OR &&
      e->op != DYN_OP_BIT_XOR &&
      e->op != DYN_OP_ADD && e->op != DYN_OP_SUB && e->op != DYN_OP_MUL &&
      e->op != DYN_OP_DIV && e->op != DYN_OP_REM &&
      e->op != DYN_OP_SHL && e->op != DYN_OP_SHR && !comparison) return false;
  if (!expression(ctx, ir, f, e->left, depth + 1)) return false;
  CODE(0x50); ++ctx->stack_slots; /* preserve left while evaluating the right operand */
  if (!expression(ctx, ir, f, e->right, depth + 1)) return false;
  CODE(0x48, 0x89, 0xc1, 0x58); --ctx->stack_slots; /* mov rcx, rax; pop rax */
  return binary_result(ctx, ir,f,e);
}
static bool binary_result(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f, const DynIrExpr *e) {
  bool comparison=e->op>=DYN_OP_EQ && e->op<=DYN_OP_GE;
  DynType operand_type=ir->expressions[e->left].type;
  if (float_type(operand_type)) {
    CODE(0x66,0x48,0x0f,0x6e,0xc0,0x66,0x48,0x0f,0x6e,0xc9); /* xmm0=left,xmm1=right */
    if (e->op==DYN_OP_REM) {
      if (ctx->stack_slots&1) CODE(0x48,0x83,0xec,8);
      runtime_call(ctx, operand_type==DYN_TYPE_F32?8:7);
      if (ctx->stack_slots&1) CODE(0x48,0x83,0xc4,8);
      CODE(0x66,0x48,0x0f,0x7e,0xc0); return !ctx->text.failed && !ctx->relocation_failed;
    }
    if (comparison) {
      if (operand_type==DYN_TYPE_F64) byte(ctx, 0x66);
      CODE(0x0f,0x2e,0xc1); /* unordered compare sets parity for NaN */
      const unsigned char predicates[]={0x94,0x95,0x92,0x96,0x97,0x93};
      byte(ctx, 0x0f); byte(ctx, predicates[e->op-DYN_OP_EQ]); byte(ctx, 0xc0);
      CODE(0x0f); byte(ctx, e->op==DYN_OP_NE?0x9a:0x9b); byte(ctx, 0xc2);
      byte(ctx, e->op==DYN_OP_NE?0x08:0x20); byte(ctx, 0xd0); CODE(0x0f,0xb6,0xc0);
    } else {
      unsigned opcode=e->op==DYN_OP_ADD?0x58:e->op==DYN_OP_SUB?0x5c:e->op==DYN_OP_MUL?0x59:e->op==DYN_OP_DIV?0x5e:0;
      if (!opcode) return false;
      byte(ctx, operand_type==DYN_TYPE_F32?0xf3:0xf2); byte(ctx, 0x0f); byte(ctx, opcode); byte(ctx, 0xc1);
      CODE(0x66,0x48,0x0f,0x7e,0xc0);
    }
    return !ctx->text.failed;
  }
  if (comparison) {
    static const unsigned char signed_conditions[] = {0x94, 0x95, 0x9c, 0x9e, 0x9f, 0x9d};
    static const unsigned char unsigned_conditions[] = {0x94, 0x95, 0x92, 0x96, 0x97, 0x93};
    const unsigned char *conditions = signed_scalar(storage_type(ir,ir->expressions[e->left].type))
        ? signed_conditions : unsigned_conditions;
    CODE(0x48, 0x39, 0xc8, 0x0f); byte(ctx, conditions[e->op - DYN_OP_EQ]);
    CODE(0xc0, 0x0f, 0xb6, 0xc0); /* setcc al; movzx eax, al */
    return !ctx->text.failed;
  }
  if (!integer_type(operand_type)) return false;
  switch (e->op) {
  case DYN_OP_ADD: CODE(0x48, 0x01, 0xc8); break;
  case DYN_OP_SUB: CODE(0x48, 0x29, 0xc8); break;
  case DYN_OP_MUL:
    if (!e->wrap && !signed_scalar(e->type)) CODE(0x48, 0xf7, 0xe1); /* mul rcx: rdx:rax */
    else CODE(0x48, 0x0f, 0xaf, 0xc1); /* imul rax, rcx */
    break;
  case DYN_OP_DIV: case DYN_OP_REM:
    divide(ctx, f, signed_scalar(e->type), e->op == DYN_OP_REM, integer_bits(e->type)); break;
  case DYN_OP_SHL: case DYN_OP_SHR:
    shift(ctx, f, signed_scalar(e->type), e->op == DYN_OP_SHL, e->wrap, integer_bits(e->type)); break;
  case DYN_OP_BIT_AND: CODE(0x48, 0x21, 0xc8); break;
  case DYN_OP_BIT_OR: CODE(0x48, 0x09, 0xc8); break;
  case DYN_OP_BIT_XOR: CODE(0x48, 0x31, 0xc8); break;
  default: return false;
  }
  if (!e->wrap && (e->op == DYN_OP_ADD || e->op == DYN_OP_SUB || e->op == DYN_OP_MUL))
    overflow_guard(ctx, f, signed_scalar(e->type));
  bool check=!e->wrap && integer_bits(e->type)<64 &&
    (e->op==DYN_OP_ADD || e->op==DYN_OP_SUB || e->op==DYN_OP_MUL || e->op==DYN_OP_SHL);
  if (check) CODE(0x49,0x89,0xc2);
  normalize(ctx, e->type);
  if (check) { CODE(0x4c,0x39,0xd0); guard(ctx, f,0x84,GUARD_OVERFLOW); }
  return !ctx->text.failed && !ctx->rodata.failed && !ctx->relocation_failed;
}
static void return_value(BackendContext *ctx, DynType type) {
  const DynIrProgram *ir=ctx->active_ir;
  bool sret=abi_memory(ctx->active_ir,type);
  if (aggregate(ir, type)) { save_struct(ctx, ctx->return_offset,type); CODE(0x48,0x8d,0x85); word(ctx, ctx->return_offset); }
  if (sret) {
    uint32_t size,alignment; if (!layout(ctx->active_ir,type,&size,&alignment,0)) { ctx->text.failed=true; return; }
    CODE(0x49,0x89,0xc3,0x48,0x8b,0xbd); word(ctx, ctx->sret_offset);
    for (unsigned part=0;part<(size+7)/8;++part) {
      unsigned bytes=size-part*8>8?8:size-part*8; load_chunk(ctx, part*8,bytes);
      if (bytes==8) { CODE(0x4c,0x89,0x97); word(ctx, part*8); }
      else for (unsigned j=0;j<bytes;++j) {
        CODE(0x44,0x88,0x97); word(ctx, part*8+j);
        if (j+1<bytes) CODE(0x49,0xc1,0xea,8);
      }
    }
    CODE(0x48,0x89,0xf8);
  }
  if (ctx->debug_mode) {
    if (aggregate(ir, type) && !sret) {
      /* The aggregate snapshot may occupy rbp-8 itself in a zero-local function. */
      runtime_call(ctx, 2); CODE(0x48,0x8d,0x85); word(ctx, ctx->return_offset);
    } else {
      CODE(0x48,0x89,0x45,0xf8);
      if (descriptor(type)) CODE(0x48,0x89,0x55,0xf0);
      runtime_call(ctx, 2); CODE(0x48,0x8b,0x45,0xf8);
      if (descriptor(type)) CODE(0x48,0x8b,0x55,0xf0);
    }
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
  if (float_type(type)) CODE(0x66,0x48,0x0f,0x6e,0xc0);
  if (ctx->dwarf && !backend_dwarf_epilogue(ctx->dwarf,ctx->text.n)) ctx->text.failed=true;
  CODE(0xc9, 0xc3); /* leave; ret */
}
/* Forward branches form bounded linked lists in their pending displacement words. */
static void pending_jump(BackendContext *ctx, unsigned condition, size_t *head) {
  if (condition) { byte(ctx, 0x0f); byte(ctx, condition); } else byte(ctx, 0xe9);
  size_t at = ctx->text.n; word(ctx, (uint32_t)*head); *head = at;
}
static bool resolve_jumps(BackendContext *ctx, size_t head, size_t destination) {
  if (ctx->text.failed) return false;
  while (head != UINT32_MAX) {
    if (head > ctx->text.n || ctx->text.n - head < 4) return false;
    uint32_t next; memcpy(&next, ctx->text.data + head, 4);
    patch_word(ctx, head, (uint32_t)(destination - head - 4)); head = next;
  }
  return true;
}
static void reset_scratch(BackendContext *ctx) {
  for (size_t i=0;i<ctx->touched_expr_count;++i) {
    uint32_t id=ctx->touched_exprs[i];
    ctx->captured_offsets[id]=ctx->temporary_offsets[id]=ctx->pack_offsets[id]=0; ctx->visited_expr[id]=false;
  }
  for (size_t i=0;i<ctx->touched_stmt_count;++i) ctx->statement_scratch[ctx->touched_stmts[i]]=0;
  ctx->touched_expr_count=ctx->touched_stmt_count=0;
}
static bool expression_scratch(BackendContext *ctx, const DynIrProgram *ir,DynExprId id,unsigned depth,unsigned *slots) {
  if (id==DYN_NO_EXPR) return true;
  if (id>=ir->expression_count || depth > MAX_DEPTH) return false;
  if (ctx->visited_expr[id]) return true;
  ctx->visited_expr[id]=true; ctx->touched_exprs[ctx->touched_expr_count++]=id;
  const DynIrExpr *e=&ir->expressions[id];
  if ((e->kind==DYN_EXPR_CALL || e->kind==DYN_EXPR_INDIRECT_CALL || e->kind==DYN_EXPR_STRUCT || e->kind==DYN_EXPR_ARRAY || e->kind==DYN_EXPR_ENUM) &&
      aggregate(ir,e->type)) {
    uint32_t size,alignment; if (!layout(ir,e->type,&size,&alignment,0)) return false;
    *slots+=(size?size+7:8)/8; if (*slots>MAX_SCRATCH) return false;
    ctx->temporary_offsets[id]=0u-8*(ctx->local_words+*slots);
  }
  if (e->kind==DYN_EXPR_CONVERT && e->type==DYN_TYPE_ANY) {
    uint32_t size,a; if (e->left>=ir->expression_count || !layout(ir,ir->expressions[e->left].type,&size,&a,0)) return false;
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
      uint32_t size,a; if (!layout(ir,element,&size,&a,0)) return false;
      unsigned count=e->item_count-callee->param_count; uint64_t needed=((uint64_t)size*count+7)/8;
      if (element==DYN_TYPE_ANY) for (unsigned i=0;i<count;++i) {
        DynExprId argument=ir->items[e->item_start+callee->param_count+i].expression;
        if (argument>=ir->expression_count || !layout(ir,ir->expressions[argument].type,&size,&a,0)) return false;
        needed+=(size?size+7:8)/8;
      }
      if (needed>MAX_SCRATCH-*slots) return false;
      *slots+=(unsigned)needed; ctx->pack_offsets[id]=0u-8*(ctx->local_words+*slots);
    }
  }
  if (e->kind==DYN_EXPR_SYSCALL || e->kind==DYN_EXPR_ENUM || e->kind==DYN_EXPR_ARRAY || e->kind==DYN_EXPR_STRUCT || e->kind==DYN_EXPR_CALL || e->kind==DYN_EXPR_INDIRECT_CALL) {
    if ((uint64_t)e->item_start+e->item_count>ir->item_count) return false;
    for (uint32_t i=0;i<e->item_count;++i) if (!expression_scratch(ctx, ir,ir->items[e->item_start+i].expression,depth+1,slots)) return false;
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
      uint32_t size,a; if (!layout(ir,ir->expressions[s->expression].type,&size,&a,0)) return false; needed+=(size+7)/8;
    }
    if (s->kind==DYN_STMT_FOR && !s->for_range && s->target!=DYN_NO_EXPR) {
      if (s->target>=ir->expression_count) return false;
      DynType collection=ir->expressions[s->target].type; needed=3;
      if (dyn_type_is_array(collection) && !s->for_pointer) {
        uint32_t size,alignment; if (!layout(ir,collection,&size,&alignment,0)) return false;
        needed+=(size+7)/8;
      } else if (!dyn_type_is_array(collection) && !descriptor(collection)) return false;
    }
    if (needed) { ctx->touched_stmts[ctx->touched_stmt_count++]=ir->children[start+i]; ctx->statement_scratch[ir->children[start+i]]=0u-8*(ctx->local_words+*slots+(s->kind==DYN_STMT_CASE?needed:1)); *slots+=needed; }
    if (s->kind==DYN_STMT_DEFER) {
      if (!ctx->unwind_offset) { *slots+=16; ctx->unwind_offset=0u-8*(ctx->local_words+*slots); if (!ctx->return_offset) { *slots+=2; ctx->return_offset=0u-8*(ctx->local_words+*slots); } *slots+=2; ctx->call_offset=0u-8*(ctx->local_words+*slots); }
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
              if (!ctx->captured_offsets[id]) { uint32_t size,alignment; if (!layout(ir,ir->expressions[id].type,&size,&alignment,0)) return false; *slots+=(size?size+7:8)/8; ctx->captured_offsets[id]=0u-8*(ctx->local_words+*slots); ctx->touched_exprs[ctx->touched_expr_count++]=id; }
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
  CODE(0x50); ++ctx->stack_slots;
  const DynIrExpr *value=id==DYN_NO_EXPR?NULL:&ir->expressions[id];
  if (value_type(ir, type)) {
    if (value) { if (!expression(ctx, ir,f,id,0)) return false; } else { CODE(0x31,0xc0); if (descriptor(type)) CODE(0x31,0xd2); }
    CODE(0x41,0x5b); --ctx->stack_slots;
    if (descriptor(type)) { CODE(0x49,0x89,0x03,0x49,0x89,0x53,8); }
    else store_memory(ctx, type);
    return !ctx->text.failed;
  }
  if (!value || value->kind==DYN_EXPR_ARRAY || value->kind==DYN_EXPR_STRUCT) {
    CODE(0x48,0x89,0xc7,0x31,0xc0,0xb9); word(ctx, size); CODE(0xfc,0xf3,0xaa);
    if (value && value->kind==DYN_EXPR_ARRAY) {
      if (!dyn_type_is_array(type) || (uint64_t)value->item_start+value->item_count>ir->item_count) return false;
      const DynIrArray *array=&ir->arrays[type-DYN_TYPE_ARRAY_BASE]; uint32_t element,a;
      if (value->item_count>array->length || !layout(ir,array->element,&element,&a,0)) return false;
      for (uint32_t i=0;i<value->item_count;++i) {
        CODE(0x48,0x8b,0x04,0x24,0x48,0x05); word(ctx, i*element);
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
        CODE(0x48,0x8b,0x04,0x24,0x48,0x05); word(ctx, offset);
        if (!initialize(ctx, ir,f,definition->type,expr,depth+1)) return false;
      }
    }
    CODE(0x58); --ctx->stack_slots; return !ctx->text.failed;
  }
  if (!expression(ctx, ir,f,id,0)) return false;
  CODE(0x48,0x89,0xc6,0x5f); --ctx->stack_slots; /* source RSI, destination RDI */
  CODE(0xb9); word(ctx, size);
  CODE(0x48,0x39,0xf7,0x0f,0x86); size_t forward=ctx->text.n; word(ctx, 0);
  if (size) { CODE(0x48,0x81,0xc6); word(ctx, size-1); CODE(0x48,0x81,0xc7); word(ctx, size-1); }
  CODE(0xfd,0xf3,0xa4,0xfc,0xe9); size_t done=ctx->text.n; word(ctx, 0);
  patch_word(ctx, forward,(uint32_t)(ctx->text.n-forward-4)); CODE(0xfc,0xf3,0xa4);
  patch_word(ctx, done,(uint32_t)(ctx->text.n-done-4)); return !ctx->text.failed;
}
static bool assign_value(BackendContext *ctx,const DynIrProgram *ir,const DynIrFunction *f,DynType type,DynExprId value) {
  if (!aggregate(ir,type)) return initialize(ctx,ir,f,type,value,0);
  uint32_t size,alignment; if (!layout(ir,type,&size,&alignment,0)) return false;
  CODE(0x50); ++ctx->stack_slots;
  if (!expression(ctx,ir,f,value,0)) return false;
  CODE(0x48,0x89,0xc6,0x5f); --ctx->stack_slots; /* source RSI, destination RDI */
  CODE(0xb9); word(ctx, size);
  CODE(0x48,0x39,0xf7,0x0f,0x86); size_t forward=ctx->text.n; word(ctx, 0);
  if (size) { CODE(0x48,0x81,0xc6); word(ctx, size-1); CODE(0x48,0x81,0xc7); word(ctx, size-1); }
  CODE(0xfd,0xf3,0xa4,0xfc,0xe9); size_t done=ctx->text.n; word(ctx, 0);
  patch_word(ctx, forward,(uint32_t)(ctx->text.n-forward-4)); CODE(0xfc,0xf3,0xa4);
  patch_word(ctx, done,(uint32_t)(ctx->text.n-done-4)); return !ctx->text.failed;
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
static bool block_statements(BackendContext *ctx, const DynIrProgram *ir, const DynIrFunction *f,
                             uint32_t start, uint32_t count, unsigned depth, bool *falls) {
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
      CODE(0x50,0x52); ctx->stack_slots+=2;
      if (ctx->defer_count && !ctx->unwinding && !protect_call(ctx, ir,f)) return false;
      CODE(0x5e,0x5f); ctx->stack_slots-=2;
      runtime_call(ctx, 0); CODE(0x0f,0x0b); reachable=false;
    } else if (s->kind==DYN_STMT_DEFER) {
      if (ctx->defer_count==MAX_DEFERS || ctx->unwinding) return false;
      if (!s->defer_block && s->body_count==1) {
        const DynIrStmt *action=&ir->statements[ir->children[s->body_start]];
        if (action->kind==DYN_STMT_EXPR) {
          const DynIrExpr *call=&ir->expressions[action->expression];
          if (call->kind==DYN_EXPR_CALL || call->kind==DYN_EXPR_INDIRECT_CALL) {
            if (call->kind==DYN_EXPR_INDIRECT_CALL) {
              if (!expression(ctx, ir,f,call->left,0)) return false;
              CODE(0x48,0x89,0x85); word(ctx, ctx->captured_offsets[call->left]);
            }
            for (uint32_t j=0;j<call->item_count;++j) {
              DynExprId value=ir->items[call->item_start+j].expression;
              if (!expression(ctx, ir,f,value,0)) return false;
              if (aggregate(ir, ir->expressions[value].type)) save_struct(ctx, ctx->captured_offsets[value],ir->expressions[value].type);
              else { CODE(0x48,0x89,0x85); word(ctx, ctx->captured_offsets[value]); }
              if (descriptor(ir->expressions[value].type)) { CODE(0x48,0x89,0x95); word(ctx, ctx->captured_offsets[value]+8); }
            }
          }
        }
      }
      ctx->defer_ids[ctx->defer_count++]=id;
    } else if (s->kind == DYN_STMT_RETURN) {
      if (s->expression != DYN_NO_EXPR) {
        if (!expression(ctx, ir, f, s->expression, 0)) return false;
      } else if (f->return_type != DYN_TYPE_VOID) return false;
      if (ctx->defer_count) {
        if (aggregate(ir, f->return_type)) save_struct(ctx, ctx->return_offset,f->return_type);
        else { CODE(0x48,0x89,0x85); word(ctx, ctx->return_offset); }
        if (descriptor(f->return_type)) { CODE(0x48,0x89,0x95); word(ctx, ctx->return_offset+8); }
        if (!emit_defers(ctx, ir,f,0)) return false;
        if (aggregate(ir, f->return_type)) CODE(0x48,0x8d,0x85);
        else CODE(0x48,0x8b,0x85);
        word(ctx, ctx->return_offset);
        if (descriptor(f->return_type)) { CODE(0x48,0x8b,0x95); word(ctx, ctx->return_offset+8); }
      }
      if (f->is_main) CODE(0x31,0xc0);
      return_value(ctx,f->is_main?DYN_TYPE_I32:f->return_type); reachable = false;
    } else if (s->kind == DYN_STMT_IF) {
      if (!expression(ctx, ir, f, s->expression, 0)) return false;
      CODE(0x48, 0x85, 0xc0, 0x0f, 0x84); /* test rax, rax; je else */
      size_t otherwise = ctx->text.n; word(ctx, 0);
      bool then_falls, else_falls;
      if (!block(ctx, ir, f, s->body_start, s->body_count, depth + 1, &then_falls)) return false;
      byte(ctx, 0xe9); size_t done = ctx->text.n; word(ctx, 0); /* jmp join */
      patch_word(ctx, otherwise, (uint32_t)(ctx->text.n - (otherwise + 4)));
      if (!block(ctx, ir, f, s->else_start, s->else_count, depth + 1, &else_falls)) return false;
      patch_word(ctx, done, (uint32_t)(ctx->text.n - (done + 4)));
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
        CODE(0x48); byte(ctx,ctx->local_alias[s->local_id-f->local_start]?0x8b:0x8d); byte(ctx,0x85); word(ctx,offset);
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
        CODE(0x50); ++ctx->stack_slots;
        if (s->assignment_op!=DYN_OP_NONE) {
          load_memory(ctx, type); CODE(0x50); ++ctx->stack_slots;
          if (!expression(ctx, ir,f,s->expression,0)) return false;
          CODE(0x48,0x89,0xc1,0x58); --ctx->stack_slots;
          DynIrExpr op={.type=type,.op=s->assignment_op,.left=s->target,.right=s->expression};
          if (!binary_result(ctx, ir,f,&op)) return false;
        } else if (!expression(ctx, ir,f,s->expression,0)) return false;
        CODE(0x41,0x5b); --ctx->stack_slots; store_memory(ctx, type); continue;
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
        CODE(0x31, 0xc0);
      } else if (!expression(ctx, ir, f, s->expression, 0)) return false;
      if (global) {
        CODE(0x4c,0x8b,0x1d); relocate(ctx, ctx->global_symbols[id],R_X86_64_GOTPCREL,-4); word(ctx, 0);
        store_memory(ctx, type);
      } else if (ctx->local_alias[id-f->local_start]) { CODE(0x4c,0x8b,0x9d); word(ctx,offset); store_memory(ctx,type); }
      else { CODE(0x48, 0x89, 0x85); word(ctx, offset); }
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
        if (!reference) { save_struct(ctx,subject+16,type); CODE(0x48,0x8d,0x85); word(ctx,subject+16); }
        CODE(0x48,0x89,0x85); word(ctx,subject+8); load_memory(ctx,storage_type(ir,type));
      } else if (any) { CODE(0x48,0x89,0x95); word(ctx,subject+8); }
      CODE(0x48,0x89,0x85); word(ctx,subject);
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
          CODE(0x48,0x8b,0x85); word(ctx,subject);
          CODE(0x48,0xb9); immediate(ctx,first); CODE(0x48,0x39,0xc8);
          size_t lower=UINT32_MAX; pending_jump(ctx,sign?0x8c:0x82,&lower);
          CODE(0x48,0xb9); immediate(ctx,last); CODE(0x48,0x39,0xc8);
          pending_jump(ctx,sign?0x8e:0x86,&matches);
          if (!resolve_jumps(ctx,lower,ctx->text.n)) return false;
        }
        if (!a->wildcard) pending_jump(ctx,0,&next);
        if (!resolve_jumps(ctx,matches,ctx->text.n)) return false;
        bool old_alias=false;
        if (a->local_id!=UINT32_MAX) {
          uint32_t offset; if (!a->pattern_count || !local_slot(ctx,f,a->local_id,&offset)) return false;
          const DynIrPattern *pattern=&ir->patterns[a->pattern_start];
          DynType binding=ir->locals[a->local_id].type;
          if (!pattern->is_type && !pattern->is_enum) return false;
          CODE(0x48,0x8b,0x85); word(ctx,subject+8);
          if (payload) { CODE(0x48,0x05); word(ctx,payload_offset); }
          old_alias=ctx->local_alias[a->local_id-f->local_start];
          ctx->local_alias[a->local_id-f->local_start]=a->pointer_binding;
          if (a->pointer_binding) { CODE(0x48,0x89,0x85); word(ctx,offset); }
          else save_struct(ctx,offset,binding);
        }
        bool arm_falls;
        if (!block(ctx,ir,f,a->body_start,a->body_count,depth+1,&arm_falls)) return false;
        if (a->local_id!=UINT32_MAX) ctx->local_alias[a->local_id-f->local_start]=old_alias;
        all_terminate &= !arm_falls; pending_jump(ctx,0,&done);
        if (!resolve_jumps(ctx,next,ctx->text.n)) return false;
      }
      CODE(0x0f,0x0b);
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
          save_struct(ctx, snapshot,collection); CODE(0x48,0x8d,0x85); word(ctx, snapshot);
        }
        CODE(0x48,0xba); immediate(ctx, definition->length);
      }
      CODE(0x48,0x89,0x85); word(ctx, data); CODE(0x48,0x89,0x95); word(ctx, length);
      if (s->for_reverse) CODE(0x48,0x89,0xd0); else CODE(0x31,0xc0);
      CODE(0x48,0x89,0x85); word(ctx, counter);
      unsigned loop=ctx->loop_depth++; ctx->loops[loop].id=s->loop_id; ctx->loops[loop].defer_base=ctx->defer_count;
      ctx->loops[loop].breaks=ctx->loops[loop].continues=UINT32_MAX; ctx->loops[loop].condition=ctx->text.n;
      CODE(0x48,0x8b,0x85); word(ctx, counter);
      if (s->for_reverse) { CODE(0x48,0x85,0xc0); pending_jump(ctx, 0x84,&ctx->loops[loop].breaks); CODE(0x48,0xff,0xc8); }
      else { CODE(0x48,0x3b,0x85); word(ctx, length); pending_jump(ctx, 0x83,&ctx->loops[loop].breaks); }
      CODE(0x48,0x69,0xc0); word(ctx, element_size); CODE(0x48,0x03,0x85); word(ctx, data);
      if (s->for_pointer) { CODE(0x48,0x89,0x85); word(ctx, binding); }
      else if (scalar(ir, element)) { load_memory(ctx, element); CODE(0x48,0x89,0x85); word(ctx, binding); }
      else save_struct(ctx, binding,element);
      bool body_falls;
      if (!block(ctx, ir,f,s->body_start,s->body_count,depth+1,&body_falls) || !resolve_jumps(ctx, ctx->loops[loop].continues,ctx->text.n)) return false;
      CODE(0x48,0x8b,0x85); word(ctx, counter); CODE(0x48,0xff); byte(ctx, s->for_reverse?0xc8:0xc0);
      CODE(0x48,0x89,0x85); word(ctx, counter);
      byte(ctx, 0xe9); word(ctx, (uint32_t)(ctx->loops[loop].condition-ctx->text.n-4));
      if (!resolve_jumps(ctx, ctx->loops[loop].breaks,ctx->text.n)) return false;
      --ctx->loop_depth;
    } else if (s->kind == DYN_STMT_FOR) {
      if ((!s->for_range && s->target != DYN_NO_EXPR) || ctx->loop_depth == MAX_DEPTH) return false;
      unsigned loop = ctx->loop_depth++;
      ctx->loops[loop].id = s->loop_id; ctx->loops[loop].defer_base=ctx->defer_count;
      ctx->loops[loop].breaks = ctx->loops[loop].continues = UINT32_MAX;
      uint32_t counter=0, stop=0, binding=0;
      if (s->for_range) {
        if (s->for_pointer || !local_slot(ctx, f,s->local_id,&binding) ||
            !expression(ctx, ir,f,s->target,0)) return false;
        counter=ctx->statement_scratch[id]; stop=counter-8;
        CODE(0x48,0x89,0x85); word(ctx, s->for_reverse?stop:counter);
        if (!expression(ctx, ir,f,s->expression,0)) return false;
        CODE(0x48,0x89,0x85); word(ctx, s->for_reverse?counter:stop);
      }
      ctx->loops[loop].condition = ctx->text.n;
      if (s->for_range) {
        CODE(0x48,0x8b,0x85); word(ctx, counter);
        CODE(0x48,0x3b,0x85); word(ctx, stop);
        bool sign=signed_scalar(ir->expressions[s->target].type);
        unsigned exit = s->for_reverse ? (s->for_inclusive ? (sign?0x8c:0x82) : (sign?0x8e:0x86))
          : (s->for_inclusive ? (sign?0x8f:0x87) : (sign?0x8d:0x83));
        pending_jump(ctx, exit,&ctx->loops[loop].breaks);
        if (s->for_reverse && !s->for_inclusive) CODE(0x48,0xff,0xc8);
        CODE(0x48,0x89,0x85); word(ctx, binding);
      } else if (s->expression != DYN_NO_EXPR) {
        if (!expression(ctx, ir, f, s->expression, 0)) return false;
        CODE(0x48, 0x85, 0xc0); pending_jump(ctx, 0x84,&ctx->loops[loop].breaks);
      }
      bool body_falls;
      if (!block(ctx, ir, f, s->body_start, s->body_count, depth + 1, &body_falls)) return false;
      if (!resolve_jumps(ctx, ctx->loops[loop].continues,ctx->text.n)) return false;
      if (s->for_range) {
        CODE(0x48,0x8b,0x85); word(ctx, counter);
        if (s->for_inclusive) {
          CODE(0x48,0x3b,0x85); word(ctx, stop); pending_jump(ctx, 0x84,&ctx->loops[loop].breaks);
        }
        CODE(0x48,0xff); byte(ctx, s->for_reverse?0xc8:0xc0);
        CODE(0x48,0x89,0x85); word(ctx, counter);
      }
      byte(ctx, 0xe9); word(ctx, (uint32_t)(ctx->loops[loop].condition - (ctx->text.n + 4)));
      if (!resolve_jumps(ctx, ctx->loops[loop].breaks,ctx->text.n)) return false;
      --ctx->loop_depth;
    } else if (s->kind == DYN_STMT_BREAK || s->kind == DYN_STMT_CONTINUE) {
      unsigned loop = ctx->loop_depth;
      while (loop && ctx->loops[loop - 1].id != s->target_loop_id) --loop;
      if (!loop) return false;
      --loop;
      if (!emit_defers(ctx, ir,f,ctx->loops[loop].defer_base)) return false;
      pending_jump(ctx, 0,s->kind == DYN_STMT_CONTINUE ? &ctx->loops[loop].continues : &ctx->loops[loop].breaks);
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
static bool function(BackendContext *ctx, const DynSource *source, const DynIrProgram *ir, const DynIrFunction *f, const DynLocationIndex *locations) {
  if (f->generic ||
      !abi_supported(ir,f->return_type) || f->param_count > 512)
    return false;
  const char *symbol = function_name(f);
  if (!strcmp(symbol,"__dyn_backend_initialize") || !strcmp(symbol,"__dyn_backend_initialized")) return false;
  for (unsigned i = 0; i < RUNTIME_COUNT; ++i)
    if (!strcmp(symbol, runtime_names[i])) return false;
  for (uint32_t i = 0; i < f->param_count; ++i)
    if (!abi_supported(ir,ir->params[f->param_start + i].type)) return false;
  if (f->foreign) return true;
  if (f->variadic && (!dyn_type_is_slice(f->variadic_type) || !abi_supported(ir,f->variadic_type))) return false;
  if (f->local_count > MAX_LOCALS || (uint64_t)f->local_start + f->local_count > ir->local_count) return false;
  ctx->local_words=0; memset(ctx->local_alias,0,sizeof(ctx->local_alias));
  if (f->local_count <= MAX_LOCALS) {
    memset(ctx->local_scope_begin,0,f->local_count*sizeof(*ctx->local_scope_begin));
    memset(ctx->local_scope_end,0,f->local_count*sizeof(*ctx->local_scope_end));
  }
  ctx->scope_count=0;
  for (uint32_t i=0;i<f->local_count;++i) {
    uint32_t size,alignment;
    if (!layout(ir,ir->locals[f->local_start+i].type,&size,&alignment,0)) return false;
    ctx->local_words+=(size+7)/8;
    if (!size) ++ctx->local_words;
    if (ctx->local_words>MAX_SCRATCH) return false;
    ctx->local_offsets[i]=0u-8*ctx->local_words;
  }
  if (ir->expression_count>MAX_NODES || ir->statement_count>MAX_NODES) return false;
  reset_scratch(ctx);
  ctx->active_ir=ir; ctx->sret_offset=ctx->return_offset=ctx->defer_count=ctx->unwind_offset=ctx->cleanup_depth=0; ctx->unwinding=false;
  unsigned scratch=0;
  if (aggregate(ir, f->return_type)) {
    uint32_t size,alignment; if (!layout(ir,f->return_type,&size,&alignment,0)) return false;
    scratch=(size?size+7:8)/8; ctx->return_offset=0u-8*(ctx->local_words+scratch);
    if (abi_memory(ir,f->return_type)) { ++scratch; ctx->sret_offset=0u-8*(ctx->local_words+scratch); }
    if (scratch>MAX_SCRATCH) return false;
  }
  if (!count_scratch(ctx, ir,f,f->body_start,f->body_count,0,&scratch)) return false;
  ctx->frame_bytes = (((ctx->local_words+scratch) * 8 + 15) / 16) * 16;
  if (!ctx->frame_bytes) ctx->frame_bytes = 16;
  ctx->stack_slots = ctx->loop_depth = 0;
  for (unsigned i = 0; i < GUARD_COUNT; ++i) ctx->message_offsets[i] = SIZE_MAX;
  CODE(0x55, 0x48, 0x89, 0xe5, 0x48, 0x81, 0xec); word(ctx, ctx->frame_bytes);
  /* GP and SSE register banks exhaust independently; stack slots retain source order. */
  const unsigned char regs[] = {0xbd,0xb5,0x95,0x8d,0x85,0x8d};
  unsigned gp=ctx->sret_offset?1:0,fp=0,spilled=0;
  if (ctx->sret_offset) { CODE(0x48,0x89,0xbd); word(ctx, ctx->sret_offset); }
  for (uint32_t i=0;i<f->param_count+(unsigned)f->variadic;++i) {
    DynIrParam packed={.type=f->variadic_type,.local_id=f->variadic_local_id};
    const DynIrParam *p=i<f->param_count?&ir->params[f->param_start+i]:&packed; uint32_t offset;
    if (!local_slot(ctx, f,p->local_id,&offset)) return false;
    unsigned parts; int classes[512]; ArrayPart leaves[512]; unsigned leaf_count=0;
    bool array=raw_aggregate(ir,p->type);
    if (!abi_assign(ir,p->type,&gp,&fp,&parts,classes,512) ||
        (array && !array_parts(ir,p->type,0,leaves,&leaf_count,0))) return false;
    for (unsigned part=0;part<parts;++part) {
      int cls=classes[part];
      if (array) {
        if (cls>=8) { CODE(0x66,0x48,0x0f,0x7e);byte(ctx, 0xc0+8*(unsigned)(cls-8)); }
        else if (cls>=0) {
          static const unsigned char gp_to_rax[]={0xf8,0xf0,0xd0,0xc8,0xc0,0xc8};
          byte(ctx, cls<4?0x48:0x4c);byte(ctx, 0x89);byte(ctx, gp_to_rax[cls]);
        } else { CODE(0x48,0x8b,0x85);word(ctx, 16+8*spilled++); }
        normalize(ctx, leaves[part].type); CODE(0x4c,0x8d,0x9d); word(ctx, offset+leaves[part].offset); store_memory(ctx, leaves[part].type); continue;
      }
      if (cls>=8) {
        CODE(0x66,0x48,0x0f,0x7e); byte(ctx, 0xc0+8*(unsigned)(cls-8)); CODE(0x48,0x89,0x85);
      } else if (cls>=0) {
        byte(ctx, cls<4?0x48:0x4c); byte(ctx, 0x89); byte(ctx, regs[cls]);
      } else {
        CODE(0x48,0x8b,0x85); word(ctx, 16+8*spilled++); CODE(0x48,0x89,0x85);
      }
      word(ctx, offset+part*8);
    }
  }
  if (ctx->debug_mode) {
    char label[4096]; const char *path; unsigned line, column;
    dyn_location_get(locations, source, f->source_offset, &path, &line, &column);
    snprintf(label, sizeof(label), "%s (%s:%u)", f->debug_name ? f->debug_name : f->name, path, line);
    size_t length = strlen(label), offset = literal(ctx, label, length);
    string_arguments(ctx, offset, length); runtime_call(ctx, 1);
  }
  if (ctx->dwarf) {
    const char *path; unsigned line,column;
    dyn_location_get(locations,source,f->source_offset,&path,&line,&column);
    if (!backend_dwarf_line(ctx->dwarf,ctx->text.n,path,line,column,true)) return false;
  }
  if (f->is_main && ctx->initializer_symbol) { byte(ctx,0xe8); relocate(ctx,ctx->initializer_symbol,R_X86_64_PLT32,-4); word(ctx,0); }
  bool falls;
  if (!block(ctx, ir, f, f->body_start, f->body_count, 0, &falls) || ctx->stack_slots) return false;
  if (falls) { if (f->return_type != DYN_TYPE_VOID) return false; if (f->is_main) CODE(0x31,0xc0); return_value(ctx,f->is_main?DYN_TYPE_I32:f->return_type); }
  return !ctx->text.failed && !ctx->rodata.failed && !ctx->relocation_failed;
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
  ctx->constant_relocations[ctx->constant_relocation_count++]=(Elf64_Rela){.r_offset=at,.r_info=ELF64_R_INFO(symbol,R_X86_64_64),.r_addend=addend};
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
static bool global_initializer(BackendContext *ctx,const DynIrProgram *ir) {
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
  CODE(0x55,0x48,0x89,0xe5,0x48,0x81,0xec); word(ctx,ctx->frame_bytes);
  CODE(0x48,0x8b,0x05); relocate(ctx,ctx->initializer_flag_symbol,R_X86_64_GOTPCREL,-4); word(ctx,0);
  CODE(0x80,0x38,0,0x0f,0x85); size_t done=ctx->text.n; word(ctx,0); CODE(0xc6,0x00,1);
  for (size_t i=0;i<ir->global_init_count;++i) {
    uint32_t id=ir->global_init_order[i]; const DynIrGlobal *g=&ir->globals[id];
    if (g->foreign || ctx->global_static[id] || g->initializer==DYN_NO_EXPR) continue;
    char name[64];
    if (!strncmp(g->name,"dyn_m",5) && strlen(g->name)>21 && g->name[21]=='_') snprintf(name,sizeof(name),"__dyn_init_%.21s",g->name);
    else snprintf(name,sizeof(name),"__dyn_init_root");
    f.name=name;
    for (unsigned j=0;j<GUARD_COUNT;++j) ctx->message_offsets[j]=SIZE_MAX;
    CODE(0x48,0x8b,0x05); relocate(ctx,ctx->global_symbols[id],R_X86_64_GOTPCREL,-4); word(ctx,0);
    if (dyn_type_is_array(g->type) && ir->expressions[g->initializer].kind==DYN_EXPR_ARRAY) {
      if (!initialize(ctx,ir,&f,g->type,g->initializer,0)) return false;
    } else if (!assign_value(ctx,ir,&f,g->type,g->initializer)) return false;
  }
  patch_word(ctx,done,(uint32_t)(ctx->text.n-done-4));
  if (ctx->dwarf && !backend_dwarf_epilogue(ctx->dwarf,ctx->text.n)) return false;
  CODE(0xc9,0xc3);
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
static bool emit_object(BackendContext *ctx, const DynSource *source, const DynIrProgram *ir, const char *path) {
  ctx->active_ir=ir;
  if (!ir->function_count || ir->function_count > MAX_SYMBOLS || ir->global_count > MAX_SYMBOLS) {
    backend_report(ctx, "unsupported by native backend: global/function count\n");
    return false;
  }
  DynLocationIndex locations = {0};
  if ((ctx->debug_mode || ctx->dwarf) && !dyn_location_build(&locations, source)) return false;
  ctx->debug_source=source; ctx->debug_locations=&locations;
  if (!suffix_functions(ctx, ir)) { dyn_location_free(&locations); return false; }
  unsigned section_symbols=ctx->dwarf?7:2;
  ctx->runtime_base=section_symbols;
  for (size_t i=0;i<ir->function_count;++i)
    ctx->function_symbols[i]=ir->functions[i].generic?0:(unsigned)ctx->runtime_base++;

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
  for (size_t i=0;i<ir->global_count;++i) if (!ir->globals[i].foreign && !ctx->global_static[i] && ir->globals[i].initializer!=DYN_NO_EXPR) {
    ctx->initializer_symbol=(unsigned)ctx->runtime_base++;
    ctx->initializer_flag_symbol=(unsigned)ctx->runtime_base++; break;
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
      if (f->generic || (unsigned)(f->foreign||f->is_public||f->is_main)!=pass) continue;
      unsigned old=ctx->function_symbols[i]; ctx->function_symbols[i]=next; remap[old]=next++;
    }
    for (size_t i=0;i<ir->global_count;++i) {
      const DynIrGlobal *g=&ir->globals[i];
      if ((unsigned)(g->foreign||g->is_public)!=pass) continue;
      unsigned old=ctx->global_symbols[i]; ctx->global_symbols[i]=next; remap[old]=next++;
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
      at=align8(ctx->globals_data.n); if (at>LIMIT || size>LIMIT-at || !reserve(&ctx->globals_data,at+size)) goto done;
      memset(ctx->globals_data.data+ctx->globals_data.n,0,at+size-ctx->globals_data.n); ctx->globals_data.n=at+size;
    }
    symbols[ctx->global_symbols[i]]=(Elf64_Sym){.st_name=(Elf64_Word)names,
      .st_info=ELF64_ST_INFO(g->foreign||g->is_public?STB_GLOBAL:STB_LOCAL,STT_OBJECT),.st_shndx=g->foreign?SHN_UNDEF:ctx->global_static[i]?11:8,.st_value=at,.st_size=size};
    memcpy(strings+names,name,length); names+=length;
  }
  if (ctx->initializer_symbol) {
    const char *flag="__dyn_backend_initialized"; size_t length=strlen(flag)+1,at=align8(ctx->globals_data.n);
    if (at>LIMIT-8 || length>string_limit-names || !reserve(&ctx->globals_data,at+8)) goto done;
    memset(ctx->globals_data.data+ctx->globals_data.n,0,at+8-ctx->globals_data.n); ctx->globals_data.n=at+8;
    symbols[ctx->initializer_flag_symbol]=(Elf64_Sym){.st_name=(Elf64_Word)names,.st_info=ELF64_ST_INFO(STB_LOCAL,STT_OBJECT),.st_shndx=8,.st_value=at,.st_size=1};
    memcpy(strings+names,flag,length); names+=length;
  }
  for (size_t i = 0; i < ir->function_count; ++i) {
    const DynIrFunction *f = &ir->functions[i];
    if (f->generic) continue; /* only checked concrete instances have machine code */
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
  for (unsigned i = 0; i < RUNTIME_COUNT; ++i) if (ctx->runtime_index[i]) {
    size_t length = strlen(runtime_names[i]) + 1;
    if (length > string_limit - names) goto done;
    symbols[ctx->runtime_index[i]] = (Elf64_Sym){.st_name = (Elf64_Word)names,
      .st_info = ELF64_ST_INFO(STB_GLOBAL, STT_FUNC), .st_shndx = SHN_UNDEF};
    memcpy(strings + names, runtime_names[i], length); names += length;
  }
  if (ctx->dwarf && !backend_dwarf_finish(ctx->dwarf,&debug)) goto done;
  size_t debug_name=sizeof("\0.text\0.rodata\0.rela.text\0.symtab\0.strtab\0.shstrtab\0.note.GNU-stack\0.data\0.init_array\0.rela.init_array\0.data.rel.ro\0.rela.data.rel.ro\0")-1;
  const char section_names[] = "\0.text\0.rodata\0.rela.text\0.symtab\0.strtab\0.shstrtab\0.note.GNU-stack\0.data\0.init_array\0.rela.init_array\0.data.rel.ro\0.rela.data.rel.ro\0" ".debug_info\0.rela.debug_info\0.debug_abbrev\0.rela.debug_abbrev\0.debug_line\0.rela.debug_line\0.debug_frame\0.rela.debug_frame\0";
  Elf64_Ehdr h = {.e_ident = {0x7f,'E','L','F',ELFCLASS64,ELFDATA2LSB,EV_CURRENT},
    .e_type = ET_REL, .e_machine = EM_X86_64, .e_version = EV_CURRENT,
    .e_ehsize = sizeof(h), .e_shentsize = sizeof(Elf64_Shdr), .e_shnum = ctx->dwarf?21:13,
    .e_shstrndx = 6};
  Elf64_Shdr sh[21] = {0};
  size_t symbytes = (ctx->runtime_base + ctx->runtime_count) * sizeof(*symbols);
  size_t relbytes = ctx->relocation_count * sizeof(*ctx->relocations);
  sh[1] = (Elf64_Shdr){.sh_name=1, .sh_type=SHT_PROGBITS,
    .sh_flags=SHF_ALLOC|SHF_EXECINSTR, .sh_offset=sizeof(h), .sh_size=ctx->text.n, .sh_addralign=1};
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
  sh[8]=(Elf64_Shdr){.sh_name=68,.sh_type=SHT_PROGBITS,.sh_flags=SHF_ALLOC|SHF_WRITE,
    .sh_offset=align8(sh[6].sh_offset+sizeof(section_names)),.sh_size=ctx->globals_data.n,.sh_addralign=8};
  sh[9]=(Elf64_Shdr){.sh_name=74,.sh_type=SHT_INIT_ARRAY,.sh_flags=SHF_ALLOC|SHF_WRITE,
    .sh_offset=align8(sh[8].sh_offset+ctx->globals_data.n),.sh_size=ctx->initializer_symbol?8:0,.sh_addralign=8,.sh_entsize=8};
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
  memcpy(data, &h, sizeof(h)); memcpy(data+sh[1].sh_offset, ctx->text.data, ctx->text.n);
  memcpy(data+sh[2].sh_offset, ctx->rodata.data, ctx->rodata.n);
  memcpy(data+sh[3].sh_offset, ctx->relocations, relbytes);
  memcpy(data+sh[4].sh_offset, symbols, symbytes); memcpy(data+sh[5].sh_offset, strings, names);
  memcpy(data+sh[6].sh_offset, section_names, sizeof(section_names));
  memcpy(data+sh[8].sh_offset,ctx->globals_data.data,ctx->globals_data.n);
  if (ctx->initializer_symbol) {
    Elf64_Rela init={.r_info=ELF64_R_INFO(ctx->initializer_symbol,R_X86_64_64)};
    memcpy(data+sh[10].sh_offset,&init,sizeof(init));
  }
  memcpy(data+sh[11].sh_offset,ctx->constants_data.data,ctx->constants_data.n);
  memcpy(data+sh[12].sh_offset,ctx->constant_relocations,sh[12].sh_size);
  for (unsigned i=0;ctx->dwarf && i<4;++i) {
    unsigned section=13+2*i; size_t count=0;
    if (debug.sections[i].size) memcpy(data+sh[section].sh_offset,debug.sections[i].data,debug.sections[i].size);
    for (size_t j=0;j<debug.relocation_count;++j) {
      const BackendDwarfRelocation *r=&debug.relocations[j]; if (r->section!=i) continue;
      unsigned symbol=r->target==BACKEND_DWARF_TEXT?2:3+r->target;
      Elf64_Rela relocation={.r_offset=r->offset,.r_info=ELF64_R_INFO(symbol,r->type),.r_addend=r->addend};
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
static bool object_report(const DynSource *source, const DynIrProgram *ir,
                          const char *path, bool debug, bool debug_info, bool report) {
  BackendContext *ctx = calloc(1, sizeof(*ctx));
  if (!ctx) return false;
  ctx->debug_mode = debug; ctx->report = report;
  if (debug_info && (!(ctx->dwarf=backend_dwarf_create()) ||
                     !(ctx->dwarf_types=calloc(DYN_TYPE_PARAM_BASE, sizeof(*ctx->dwarf_types))))) {
    backend_dwarf_free(ctx->dwarf); free(ctx); return false;
  }
  bool ok = emit_object(ctx, source, ir, path);
  backend_dwarf_free(ctx->dwarf);
  free(ctx->dwarf_types);
  free(ctx->text.data); free(ctx->rodata.data); free(ctx->globals_data.data); free(ctx->constants_data.data);
  free(ctx->relocations); free(ctx->constant_relocations);
  free(ctx);
  return ok;
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
  /* ELF structs are deliberately host-native only in this isolated experiment. */
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
