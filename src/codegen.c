#define _POSIX_C_SOURCE 200809L

#include "dyn.h"
#include "dyn_timing.h"
#include "dyn_location.h"
#include "dyn_ast.h"
#include "frontend.h"
#include "ir.h"
#include "llvm_shim.h"
#include "sema.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct GenAbi GenAbi;
typedef struct {
  uint32_t defer_statement;
  LLVMBasicBlockRef break_target, continue_target;
  size_t break_defer, continue_defer;
} GenControl;
typedef struct {
  LLVMContextRef context;
  LLVMModuleRef module;
  LLVMBuilderRef builder, stack_builder;
  LLVMDIBuilderRef di_builder;
  LLVMMetadataRef di_file, di_unit, di_function_type, di_scope;
  LLVMMetadataRef *di_struct_types, *di_enum_types, *di_array_types;
  LLVMValueRef function, panic_fn, init_fn, syscall_fn, memset_fn,
      trace_push_fn, trace_pop_fn, unwind_set_fn, unwind_link_fn,
      unwind_unlink_fn, unwind_continue_fn, unwind_frame, variadic_data,
      variadic_count;
  LLVMTypeRef panic_type, init_type, syscall_type, memset_type, trace_push_type,
      trace_pop_type, unwind_set_type, unwind_frame_type, unwind_void_type;
  LLVMTypeRef unwind_continue_type;
  LLVMValueRef *locals, *functions, *globals, *captured_values;
  bool *static_globals;
  uint32_t *local_statements;
  DynLocationIndex locations;
  LLVMTypeRef *struct_types, *enum_types, *function_types;
  DynIrProgram *ir;
  GenAbi **abis, **pointer_abis, *current_abi;
  DynType return_type;
  bool is_main, unwinding, tracing, allocation_failed, wasm;
  unsigned pointer_bytes;
  LLVMBasicBlockRef break_target, continue_target;
  GenControl *defer_stack;
  size_t defer_count, break_defer_count, continue_defer_count, string_serial;
  /* Proven facts are reusable only in their current straight-line block.
     LLVM SSA identity makes loads separated by possible aliasing stores differ.
   */
  LLVMBasicBlockRef pointer_fact_block, bounds_fact_block;
  LLVMValueRef pointer_fact, bounds_index, bounds_length;
  DynType pointer_fact_pointee;
  uint64_t statement_epoch, pointer_fact_epoch, bounds_fact_epoch;
  const DynSource *source;
} Gen;

/* Every slot has a compile-time size. Emit it once in the entry block, even
 * when the expression using it appears in a loop. Allocation in the current
 * block grows the stack on every iteration at -O0. Initializers stay in place. */
static LLVMValueRef gen_stack_slot(Gen *g, LLVMTypeRef type, const char *name) {
  LLVMBasicBlockRef entry = LLVMGetEntryBasicBlock(g->function);
  LLVMValueRef first = LLVMGetFirstInstruction(entry);
  if (first)
    LLVMPositionBuilderBefore(g->stack_builder, first);
  else
    LLVMPositionBuilderAtEnd(g->stack_builder, entry);
  return LLVMBuildAlloca(g->stack_builder, type, name);
}

static void debug_location(Gen *g, DynSpan span) {
  if (!g->di_builder || !g->di_scope || !g->source ||
      span.start_byte > g->source->length)
    return;
  const char *path;
  unsigned line, column;
  dyn_location_get(&g->locations, g->source, span.start_byte, &path, &line, &column);
  LLVMSetCurrentDebugLocation2(
      g->builder, LLVMDIBuilderCreateDebugLocation(g->context, line, column,
                                                   g->di_scope, NULL));
}
static unsigned span_line(Gen *g, DynSpan span) {
  if (!g->source)
    return 0;
  const char *path;
  unsigned line, column;
  dyn_location_get(&g->locations, g->source, span.start_byte, &path, &line, &column);
  return line;
}

static LLVMMetadataRef debug_source_file(Gen *g, DynSpan span) {
  const char *path;
  unsigned line, column;
  dyn_location_get(&g->locations, g->source, span.start_byte, &path, &line, &column);
  return path
             ? LLVMDIBuilderCreateFile(g->di_builder, path, strlen(path), "", 0)
             : g->di_file;
}

static int dyn_verify_module(LLVMModuleRef module, int action, char **message) {
  int failed = LLVMVerifyModule(module, action, message);
  if (!failed && message && *message) {
    LLVMDisposeMessage(*message);
    *message = NULL;
  }
  return failed;
}
static bool signed_type(DynType);
static unsigned type_bits(Gen *, DynType);
typedef struct {
  bool ok;
  uint64_t value;
} StaticInt;
static StaticInt static_integer(Gen *g, DynExprId id, size_t depth) {
  if (id == DYN_NO_EXPR || id >= g->ir->expression_count ||
      depth > g->ir->global_count + g->ir->expression_count)
    return (StaticInt){0};
  DynIrExpr *e = &g->ir->expressions[id];
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_CHAR)
    return (StaticInt){true, e->integer};
  if (e->kind == DYN_EXPR_BOOL)
    return (StaticInt){true, e->boolean};
  if (e->kind == DYN_EXPR_GLOBAL) {
    uint32_t q = (uint32_t)e->integer;
    return q < g->ir->global_count && g->ir->globals[q].is_const
               ? static_integer(g, g->ir->globals[q].initializer, depth + 1)
               : (StaticInt){0};
  }
  if (e->kind == DYN_EXPR_CONVERT)
    return static_integer(g, e->left, depth + 1);
  if (e->kind == DYN_EXPR_UNARY) {
    StaticInt x = static_integer(g, e->left, depth + 1);
    if (!x.ok)
      return x;
    if (e->op == DYN_OP_NEG)
      x.value = UINT64_C(0) - x.value;
    else if (e->op == DYN_OP_NOT)
      x.value = !x.value;
    else if (e->op == DYN_OP_BIT_NOT)
      x.value = ~x.value;
    else
      x.ok = false;
    return x;
  }
  if (e->kind != DYN_EXPR_BINARY)
    return (StaticInt){0};
  StaticInt l = static_integer(g, e->left, depth + 1),
            r = static_integer(g, e->right, depth + 1);
  if (!l.ok || !r.ok)
    return (StaticInt){0};
  DynType operand = g->ir->expressions[e->left].type;
  switch (e->op) {
  case DYN_OP_ADD:
    l.value += r.value;
    break;
  case DYN_OP_SUB:
    l.value -= r.value;
    break;
  case DYN_OP_MUL:
    l.value *= r.value;
    break;
  case DYN_OP_DIV:
    l.value = signed_type(operand)
                  ? (uint64_t)((int64_t)l.value / (int64_t)r.value)
                  : l.value / r.value;
    break;
  case DYN_OP_REM:
    l.value = signed_type(operand)
                  ? (uint64_t)((int64_t)l.value % (int64_t)r.value)
                  : l.value % r.value;
    break;
  case DYN_OP_BIT_AND:
  case DYN_OP_LOGICAL_AND:
    l.value &= r.value;
    break;
  case DYN_OP_BIT_OR:
  case DYN_OP_LOGICAL_OR:
    l.value |= r.value;
    break;
  case DYN_OP_BIT_XOR:
    l.value ^= r.value;
    break;
  case DYN_OP_SHL:
    l.value <<= r.value;
    break;
  case DYN_OP_SHR:
    l.value = signed_type(operand) ? (uint64_t)((int64_t)l.value >> r.value)
                                   : l.value >> r.value;
    break;
  case DYN_OP_EQ:
    l.value = l.value == r.value;
    break;
  case DYN_OP_NE:
    l.value = l.value != r.value;
    break;
  case DYN_OP_LT:
    l.value = signed_type(operand) ? (int64_t)l.value < (int64_t)r.value
                                   : l.value < r.value;
    break;
  case DYN_OP_LE:
    l.value = signed_type(operand) ? (int64_t)l.value <= (int64_t)r.value
                                   : l.value <= r.value;
    break;
  case DYN_OP_GT:
    l.value = signed_type(operand) ? (int64_t)l.value > (int64_t)r.value
                                   : l.value > r.value;
    break;
  case DYN_OP_GE:
    l.value = signed_type(operand) ? (int64_t)l.value >= (int64_t)r.value
                                   : l.value >= r.value;
    break;
  default:
    return (StaticInt){0};
  }
  unsigned width = type_bits(g, e->type);
  if (width < 64)
    l.value &= (UINT64_C(1) << width) - 1;
  return l;
}
static bool signed_type(DynType t) {
  return (t >= DYN_TYPE_I8 && t <= DYN_TYPE_I64) || t == DYN_TYPE_ISIZE;
}
static bool int_type(DynType t) {
  return t >= DYN_TYPE_I8 && t <= DYN_TYPE_USIZE;
}
static bool float_type(DynType t) {
  return t == DYN_TYPE_F32 || t == DYN_TYPE_F64;
}
static unsigned type_bits(Gen *g, DynType t) {
  if (t == DYN_TYPE_USIZE || t == DYN_TYPE_ISIZE || t == DYN_TYPE_RAWPTR ||
      dyn_type_is_pointer(t) || dyn_type_is_function(t)) return g->pointer_bytes * 8;
  switch (t) {
  case DYN_TYPE_BOOL:
    return 1;
  case DYN_TYPE_I8:
  case DYN_TYPE_U8:
    return 8;
  case DYN_TYPE_I16:
  case DYN_TYPE_U16:
    return 16;
  case DYN_TYPE_I32:
  case DYN_TYPE_U32:
  case DYN_TYPE_F32:
    return 32;
  default:
    return 64;
  }
}
static uint64_t type_alignment(Gen *, DynType);
static uint64_t debug_type_size(Gen *g, DynType t) {
  if (dyn_type_is_struct(t))
    return g->ir->structs[t - DYN_TYPE_STRUCT_BASE].size;
  if (dyn_type_is_enum(t))
    return g->ir->enums[t - DYN_TYPE_ENUM_BASE].size;
  if (dyn_type_is_array(t)) {
    DynIrArray *a = &g->ir->arrays[t - DYN_TYPE_ARRAY_BASE];
    return debug_type_size(g, a->element) * a->length;
  }
  if (dyn_type_is_slice(t) || t == DYN_TYPE_STRING) return 2 * g->pointer_bytes;
  if (t == DYN_TYPE_ANY) return 16;
  return type_bits(g, t) / 8;
}
static LLVMTypeRef llvm_type(Gen *g, DynType t) {
  if (dyn_type_is_pointer(t) || t == DYN_TYPE_RAWPTR)
    return LLVMPointerTypeInContext(g->context, 0);
  if (t == DYN_TYPE_ANY) {
    LLVMTypeRef fields[] = {LLVMInt64TypeInContext(g->context),
                            LLVMPointerTypeInContext(g->context, 0)};
    return LLVMStructTypeInContext(g->context, fields, 2, 0);
  }
  if (dyn_type_is_struct(t))
    return g->struct_types[t - DYN_TYPE_STRUCT_BASE];
  if (dyn_type_is_enum(t)) {
    DynIrEnum *en = &g->ir->enums[t - DYN_TYPE_ENUM_BASE];
    return en->has_payload ? g->enum_types[t - DYN_TYPE_ENUM_BASE]
                           : llvm_type(g, en->tag_type);
  }
  if (dyn_type_is_array(t)) {
    DynIrArray *a = &g->ir->arrays[t - DYN_TYPE_ARRAY_BASE];
    return LLVMArrayType2(llvm_type(g, a->element), a->length);
  }
  if (dyn_type_is_slice(t) || t == DYN_TYPE_STRING) {
    LLVMTypeRef fields[] = {LLVMPointerTypeInContext(g->context, 0),
                            LLVMIntTypeInContext(g->context, g->pointer_bytes * 8)};
    return LLVMStructTypeInContext(g->context, fields, 2, 0);
  }
  switch (t) {
  case DYN_TYPE_USIZE:
  case DYN_TYPE_ISIZE:
    return LLVMIntTypeInContext(g->context, g->pointer_bytes * 8);
  case DYN_TYPE_BOOL:
    return LLVMInt1TypeInContext(g->context);
  case DYN_TYPE_I8:
  case DYN_TYPE_U8:
    return LLVMInt8TypeInContext(g->context);
  case DYN_TYPE_I16:
  case DYN_TYPE_U16:
    return LLVMInt16TypeInContext(g->context);
  case DYN_TYPE_I32:
  case DYN_TYPE_U32:
    return LLVMInt32TypeInContext(g->context);
  case DYN_TYPE_F32:
    return LLVMFloatTypeInContext(g->context);
  case DYN_TYPE_F64:
    return LLVMDoubleTypeInContext(g->context);
  default:
    return LLVMInt64TypeInContext(g->context);
  }
}

static LLVMMetadataRef debug_type(Gen *g, DynType t) {
  if (!g->di_builder)
    return NULL;
  unsigned pointer_bits = g->pointer_bytes * 8;
  const char *name = dyn_type_name(t);
  unsigned encoding = signed_type(t) ? 5 : int_type(t) ? 7 : 0;
  if (t == DYN_TYPE_BOOL)
    encoding = 2;
  if (float_type(t))
    encoding = 4;
  if (encoding)
    return LLVMDIBuilderCreateBasicType(g->di_builder, name, strlen(name),
                                        type_bits(g, t), encoding, 0);
  if (dyn_type_is_pointer(t) || t == DYN_TYPE_RAWPTR) {
    LLVMMetadataRef pointee = NULL;
    if (dyn_type_is_pointer(t))
      pointee =
          debug_type(g, g->ir->pointers[t - DYN_TYPE_POINTER_BASE].pointee);
    return LLVMDIBuilderCreatePointerType(g->di_builder, pointee, pointer_bits, pointer_bits, 0,
                                          name, strlen(name));
  }
  if (t == DYN_TYPE_ANY) {
    LLVMMetadataRef members[] = {
        LLVMDIBuilderCreateMemberType(g->di_builder, g->di_file, "type", 4,
                                      g->di_file, 0, 64, 64, 0, 0,
                                      debug_type(g, DYN_TYPE_U64)),
        LLVMDIBuilderCreateMemberType(g->di_builder, g->di_file, "data", 4,
                                      g->di_file, 0, pointer_bits, pointer_bits, 64, 0,
                                      debug_type(g, DYN_TYPE_RAWPTR))};
    return LLVMDIBuilderCreateStructType(g->di_builder, g->di_file, "any", 3,
                                         g->di_file, 0, 128, 64, 0, NULL,
                                         members, 2, 0, NULL, "", 0);
  }
  if (dyn_type_is_slice(t) || t == DYN_TYPE_STRING) {
    DynType element = t == DYN_TYPE_STRING
                          ? DYN_TYPE_U8
                          : g->ir->slices[t - DYN_TYPE_SLICE_BASE].element;
    LLVMMetadataRef pointer = LLVMDIBuilderCreatePointerType(
        g->di_builder, debug_type(g, element), pointer_bits, pointer_bits, 0, "", 0);
    LLVMMetadataRef length = debug_type(g, DYN_TYPE_USIZE);
    LLVMMetadataRef members[] = {
        LLVMDIBuilderCreateMemberType(g->di_builder, g->di_file, "data", 4,
                                      g->di_file, 0, pointer_bits, pointer_bits, 0, 0, pointer),
        LLVMDIBuilderCreateMemberType(g->di_builder, g->di_file, "len", 3,
                                      g->di_file, 0, pointer_bits, pointer_bits, pointer_bits, 0, length)};
    return LLVMDIBuilderCreateStructType(g->di_builder, g->di_file, name,
                                         strlen(name), g->di_file, 0, 2 * pointer_bits, pointer_bits,
                                         0, NULL, members, 2, 0, NULL, "", 0);
  }
  if (dyn_type_is_array(t)) {
    size_t id = t - DYN_TYPE_ARRAY_BASE;
    if (g->di_array_types[id])
      return g->di_array_types[id];
    DynIrArray *a = &g->ir->arrays[id];
    LLVMMetadataRef sub =
        LLVMDIBuilderGetOrCreateSubrange(g->di_builder, 0, (int64_t)a->length);
    return g->di_array_types[id] = LLVMDIBuilderCreateArrayType(
               g->di_builder, debug_type_size(g, t) * 8,
               (uint32_t)(type_alignment(g, t) * 8), debug_type(g, a->element),
               &sub, 1);
  }
  if (dyn_type_is_struct(t)) {
    size_t id = t - DYN_TYPE_STRUCT_BASE;
    if (g->di_struct_types[id])
      return g->di_struct_types[id];
    DynIrStruct *st = &g->ir->structs[id];
    LLVMMetadataRef *members = calloc(st->field_count, sizeof(*members));
    if (st->field_count && !members) {
      g->allocation_failed = true;
      return NULL;
    }
    uint64_t offset = 0;
    unsigned line = span_line(g, st->span);
    LLVMMetadataRef file = debug_source_file(g, st->span);
    LLVMMetadataRef forward = LLVMDIBuilderCreateReplaceableCompositeType(
        g->di_builder, 0x13, st->name, strlen(st->name), file, file, line, 0,
        st->size * 8, (uint32_t)(st->alignment * 8), 0, "", 0);
    g->di_struct_types[id] = forward;
    for (uint32_t i = 0; i < st->field_count; ++i) {
      DynIrField *field = &g->ir->fields[st->field_start + i];
      uint64_t alignment = st->packed ? 1 : type_alignment(g, field->type),
               size = debug_type_size(g, field->type);
      offset = (offset + alignment - 1) & ~(alignment - 1);
      members[i] = LLVMDIBuilderCreateMemberType(
          g->di_builder, file, field->name, strlen(field->name), file, line,
          size * 8, (uint32_t)(alignment * 8), offset * 8, 0,
          debug_type(g, field->type));
      offset += size;
    }
    LLVMMetadataRef complete = LLVMDIBuilderCreateStructType(
        g->di_builder, file, st->name, strlen(st->name), file, line,
        st->size * 8, (uint32_t)(st->alignment * 8), 0, NULL, members,
        st->field_count, 0, NULL, "", 0);
    LLVMMetadataReplaceAllUsesWith(forward, complete);
    g->di_struct_types[id] = complete;
    free(members);
    return complete;
  }
  if (dyn_type_is_enum(t)) {
    size_t id = t - DYN_TYPE_ENUM_BASE;
    if (g->di_enum_types[id])
      return g->di_enum_types[id];
    DynIrEnum *en = &g->ir->enums[id];
    unsigned line = span_line(g, en->span);
    LLVMMetadataRef file = debug_source_file(g, en->span);
    LLVMMetadataRef *values = calloc(en->variant_count, sizeof(*values));
    if (en->variant_count && !values) {
      g->allocation_failed = true;
      return NULL;
    }
    for (uint32_t i = 0; i < en->variant_count; ++i) {
      DynIrVariant *v = &g->ir->variants[en->variant_start + i];
      values[i] = LLVMDIBuilderCreateEnumerator(g->di_builder, v->name,
                                                strlen(v->name), v->tag, 1);
    }
    LLVMMetadataRef tag = LLVMDIBuilderCreateEnumerationType(
        g->di_builder, file, en->name, strlen(en->name), file, line,
        debug_type_size(g, en->tag_type) * 8,
        (uint32_t)(type_alignment(g, en->tag_type) * 8), values,
        en->variant_count, debug_type(g, en->tag_type));
    free(values);
    if (!en->has_payload)
      return g->di_enum_types[id] = tag;
    LLVMMetadataRef *variants = calloc(en->variant_count, sizeof(*variants));
    if (en->variant_count && !variants) {
      g->allocation_failed = true;
      return NULL;
    }
    unsigned variant_count = 0;
    for (uint32_t i = 0; i < en->variant_count; ++i) {
      DynIrVariant *v = &g->ir->variants[en->variant_start + i];
      if (v->payload_type == DYN_TYPE_VOID)
        continue;
      variants[variant_count++] = LLVMDIBuilderCreateMemberType(
          g->di_builder, file, v->name, strlen(v->name), file, line,
          debug_type_size(g, v->payload_type) * 8,
          (uint32_t)(type_alignment(g, v->payload_type) * 8), 0, 0,
          debug_type(g, v->payload_type));
    }
    LLVMMetadataRef payload = LLVMDIBuilderCreateUnionType(
        g->di_builder, file, "payload", 7, file, line, en->payload_size * 8,
        (uint32_t)(en->payload_alignment * 8), 0, variants, variant_count, 0,
        "", 0);
    free(variants);
    LLVMMetadataRef members[] = {
        LLVMDIBuilderCreateMemberType(
            g->di_builder, file, "tag", 3, file, line,
            debug_type_size(g, en->tag_type) * 8,
            (uint32_t)(type_alignment(g, en->tag_type) * 8), 0, 0, tag),
        LLVMDIBuilderCreateMemberType(g->di_builder, file, "payload", 7, file,
                                      line, en->payload_size * 8,
                                      (uint32_t)(en->payload_alignment * 8),
                                      en->payload_alignment * 8, 0, payload)};
    return g->di_enum_types[id] = LLVMDIBuilderCreateStructType(
               g->di_builder, file, en->name, strlen(en->name), file, line,
               en->size * 8, (uint32_t)(en->alignment * 8), 0, NULL, members, 2,
               0, NULL, "", 0);
  }
  return NULL;
}

static unsigned local_line(Gen *g, uint32_t local, unsigned fallback) {
  uint32_t entry = g->local_statements ? g->local_statements[local] : 0;
  if (entry) {
    const char *path;
    unsigned line, column;
    dyn_location_get(&g->locations, g->source, g->ir->statements[entry - 1].span.start_byte,
                        &path, &line, &column);
    return line;
  }
  return fallback;
}

static LLVMMetadataRef debug_declare(Gen *g, LLVMValueRef storage,
                                     const char *name, DynType type,
                                     unsigned line, unsigned argument) {
  LLVMMetadataRef ty = debug_type(g, type);
  if (!g->di_builder || !g->di_scope || !ty || !name || !name[0])
    return NULL;
  LLVMMetadataRef variable =
      argument
          ? LLVMDIBuilderCreateParameterVariable(g->di_builder, g->di_scope,
                                                 name, strlen(name), argument,
                                                 g->di_file, line, ty, 1, 0)
          : LLVMDIBuilderCreateAutoVariable(g->di_builder, g->di_scope, name,
                                            strlen(name), g->di_file, line, ty,
                                            1, 0, 0);
  LLVMMetadataRef expression =
      LLVMDIBuilderCreateExpression(g->di_builder, NULL, 0);
  LLVMMetadataRef location =
      LLVMDIBuilderCreateDebugLocation(g->context, line, 1, g->di_scope, NULL);
  LLVMDIBuilderInsertDeclareRecordAtEnd(g->di_builder, storage, variable,
                                        expression, location,
                                        LLVMGetInsertBlock(g->builder));
  return variable;
}

static void debug_value(Gen *g, LLVMValueRef value, LLVMMetadataRef variable,
                        unsigned line) {
  if (!g->di_builder || !variable)
    return;
  LLVMMetadataRef expression =
      LLVMDIBuilderCreateExpression(g->di_builder, NULL, 0);
  LLVMMetadataRef location =
      LLVMDIBuilderCreateDebugLocation(g->context, line, 1, g->di_scope, NULL);
  LLVMDIBuilderInsertDbgValueRecordAtEnd(g->di_builder, value, variable,
                                         expression, location,
                                         LLVMGetInsertBlock(g->builder));
}
static LLVMTypeRef llvm_fn_type(Gen *, uint32_t);
static DynIrPointer *ir_pointer(Gen *g, DynType t) {
  return dyn_type_is_pointer(t) &&
                 t - DYN_TYPE_POINTER_BASE < g->ir->pointer_count
             ? &g->ir->pointers[t - DYN_TYPE_POINTER_BASE]
             : NULL;
}
static DynIrArray *ir_array(Gen *g, DynType t) {
  return dyn_type_is_array(t) ? &g->ir->arrays[t - DYN_TYPE_ARRAY_BASE] : NULL;
}
static DynIrSlice *ir_slice(Gen *g, DynType t) {
  return dyn_type_is_slice(t) ? &g->ir->slices[t - DYN_TYPE_SLICE_BASE] : NULL;
}
static uint64_t type_alignment(Gen *g, DynType t) {
  if (dyn_type_is_pointer(t) || dyn_type_is_slice(t) || dyn_type_is_function(t) ||
      t == DYN_TYPE_RAWPTR || t == DYN_TYPE_USIZE || t == DYN_TYPE_ISIZE ||
      t == DYN_TYPE_STRING) return g->pointer_bytes;
  if (dyn_type_is_array(t))
    return type_alignment(g, ir_array(g, t)->element);
  if (dyn_type_is_struct(t))
    return g->ir->structs[t - DYN_TYPE_STRUCT_BASE].alignment;
  if (dyn_type_is_enum(t))
    return g->ir->enums[t - DYN_TYPE_ENUM_BASE].alignment;
  switch (t) {
  case DYN_TYPE_BOOL:
  case DYN_TYPE_I8:
  case DYN_TYPE_U8:
    return 1;
  case DYN_TYPE_I16:
  case DYN_TYPE_U16:
    return 2;
  case DYN_TYPE_I32:
  case DYN_TYPE_U32:
  case DYN_TYPE_F32:
    return 4;
  default:
    return 8;
  }
}
static void emit_defers(Gen *, size_t);
static void emit_trace_pop(Gen *g) {
  if (!g->tracing)
    return;
  LLVMBuildCall2(g->builder, g->trace_pop_type, g->trace_pop_fn, NULL, 0, "");
}
static void emit_panic(Gen *g, LLVMValueRef message, LLVMValueRef length) {
  if (LLVMTypeOf(length) != llvm_type(g, DYN_TYPE_USIZE))
    length = LLVMBuildTrunc(g->builder, length, llvm_type(g, DYN_TYPE_USIZE), "panic.length");
  LLVMValueRef arguments[2] = {message, length};
  LLVMBuildCall2(g->builder, g->panic_type, g->panic_fn, arguments, 2, "");
}
static void abi_attributes(Gen *, LLVMValueRef, const GenAbi *, bool);
static LLVMValueRef emit_call(Gen *g, LLVMTypeRef type, LLVMValueRef callee,
                              LLVMValueRef *args, unsigned count,
                              const char *name, bool may_panic, const GenAbi *abi) {
  ++g->statement_epoch; /* A call may mutate storage reachable through aliases.
                         */
  if (g->wasm || !may_panic || !g->defer_count || g->unwinding) {
    LLVMValueRef call = LLVMBuildCall2(g->builder, type, callee, args, count, name);
    abi_attributes(g, call, abi, true);
    return call;
  }
  if (!g->unwind_frame)
    g->unwind_frame = gen_stack_slot(g, g->unwind_frame_type, "unwind.frame");
  LLVMValueRef frame = g->unwind_frame;
  LLVMValueRef state =
      LLVMBuildCall2(g->builder, g->unwind_set_type, g->unwind_set_fn, &frame,
                     1, "unwind.state");
  LLVMBasicBlockRef normal =
      LLVMAppendBasicBlockInContext(g->context, g->function, "call.normal");
  LLVMBasicBlockRef unwind =
      LLVMAppendBasicBlockInContext(g->context, g->function, "call.unwind");
  LLVMBasicBlockRef done =
      LLVMAppendBasicBlockInContext(g->context, g->function, "call.done");
  LLVMBuildCondBr(
      g->builder,
      LLVMBuildICmp(g->builder, 32, state,
                    LLVMConstInt(LLVMInt32TypeInContext(g->context), 0, 0),
                    "unwind.normal"),
      normal, unwind);
  LLVMPositionBuilderAtEnd(g->builder, normal);
  LLVMBuildCall2(g->builder, g->unwind_void_type, g->unwind_link_fn, &frame, 1,
                 "");
  LLVMValueRef result =
      LLVMBuildCall2(g->builder, type, callee, args, count, name);
  abi_attributes(g, result, abi, true);
  LLVMBuildCall2(g->builder, g->unwind_void_type, g->unwind_unlink_fn, &frame,
                 1, "");
  LLVMBuildBr(g->builder, done);
  LLVMBasicBlockRef result_block = LLVMGetInsertBlock(g->builder);
  LLVMPositionBuilderAtEnd(g->builder, unwind);
  emit_defers(g, 0);
  LLVMBuildCall2(g->builder, g->unwind_continue_type, g->unwind_continue_fn,
                 NULL, 0, "");
  LLVMBuildUnreachable(g->builder);
  LLVMPositionBuilderAtEnd(g->builder, done);
  if (LLVMGetReturnType(type) == LLVMVoidTypeInContext(g->context))
    return result;
  LLVMValueRef phi = LLVMBuildPhi(g->builder, LLVMGetReturnType(type), name);
  LLVMAddIncoming(phi, &result, &result_block, 1);
  return phi;
}
#include "codegen_abi.h"

static LLVMValueRef guard(Gen *g, LLVMValueRef condition, const char *name) {
  LLVMBasicBlockRef ok = LLVMAppendBasicBlockInContext(g->context, g->function,
                                                       name),
                    bad = LLVMAppendBasicBlockInContext(g->context, g->function,
                                                        "panic");
  LLVMBuildCondBr(g->builder, condition, ok, bad);
  LLVMPositionBuilderAtEnd(g->builder, bad);
  if (!g->unwinding)
    emit_defers(g, 0);
  emit_panic(g, LLVMConstNull(LLVMPointerTypeInContext(g->context, 0)),
             LLVMConstInt(LLVMInt64TypeInContext(g->context), 0, 0));
  LLVMBuildUnreachable(g->builder);
  LLVMPositionBuilderAtEnd(g->builder, ok);
  return condition;
}
/* A fact is reusable iff every path from entry to here crosses its success
   block. Test that directly by searching the CFG with that block removed. */
static bool block_dominates(Gen *g, LLVMBasicBlockRef fact,
                            LLVMBasicBlockRef here) {
  if (!fact || !here)
    return false;
  if (fact == here)
    return true;
  size_t count = 0;
  for (LLVMBasicBlockRef b = LLVMGetFirstBasicBlock(g->function); b;
       b = LLVMGetNextBasicBlock(b))
    ++count;
  if (!count)
    return false;
  LLVMBasicBlockRef *todo = malloc(count * sizeof(*todo));
  LLVMBasicBlockRef *seen = calloc(count, sizeof(*seen));
  if (!todo || !seen) {
    free(todo);
    free(seen);
    return false;
  }
  size_t n = 0;
  LLVMBasicBlockRef entry = LLVMGetFirstBasicBlock(g->function);
  if (entry != fact) {
    todo[n++] = entry;
    seen[0] = entry;
  }
  bool reached = false;
  while (n && !reached) {
    LLVMBasicBlockRef b = todo[--n];
    if (b == here) {
      reached = true;
      break;
    }
    LLVMValueRef term = LLVMGetBasicBlockTerminator(b);
    if (!term)
      continue;
    unsigned successors = LLVMGetNumSuccessors(term);
    for (unsigned i = 0; i < successors; ++i) {
      LLVMBasicBlockRef next = LLVMGetSuccessor(term, i);
      size_t slot = 0;
      for (LLVMBasicBlockRef x = LLVMGetFirstBasicBlock(g->function); x != next;
           x = LLVMGetNextBasicBlock(x))
        ++slot;
      if (next != fact && !seen[slot]) {
        seen[slot] = next;
        todo[n++] = next;
      }
    }
  }
  free(todo);
  free(seen);
  return !reached;
}
static bool same_guard_value(LLVMValueRef a, LLVMValueRef b,
                             bool same_statement) {
  if (a == b)
    return true;
  return same_statement && LLVMIsALoadInst(a) && LLVMIsALoadInst(b) &&
         LLVMGetOperand(a, 0) == LLVMGetOperand(b, 0);
}
static LLVMValueRef checked_pointer(Gen *g, LLVMValueRef pointer,
                                    DynType pointee) {
  if (block_dominates(g, g->pointer_fact_block,
                      LLVMGetInsertBlock(g->builder)) &&
      same_guard_value(g->pointer_fact, pointer,
                       g->pointer_fact_epoch == g->statement_epoch) &&
      g->pointer_fact_pointee == pointee)
    return pointer;
  LLVMTypeRef pt = LLVMPointerTypeInContext(g->context, 0);
  guard(g,
        LLVMBuildICmp(g->builder, 33, pointer, LLVMConstNull(pt),
                      "pointer.nonnull"),
        "pointer.nonnull.ok");
  uint64_t alignment = type_alignment(g, pointee);
  if (alignment > 1) {
    LLVMTypeRef i64 = LLVMInt64TypeInContext(g->context);
    LLVMValueRef address = LLVMBuildPtrToInt(g->builder, pointer, i64,
                                             "pointer.address"),
                 mask = LLVMConstInt(i64, alignment - 1, 0);
    LLVMValueRef aligned =
        LLVMBuildICmp(g->builder, 32,
                      LLVMBuildAnd(g->builder, address, mask, "alignment.bits"),
                      LLVMConstInt(i64, 0, 0), "pointer.aligned");
    guard(g, aligned, "pointer.aligned.ok");
  }
  g->pointer_fact_block = LLVMGetInsertBlock(g->builder);
  g->pointer_fact = pointer;
  g->pointer_fact_pointee = pointee;
  g->pointer_fact_epoch = g->statement_epoch;
  return pointer;
}

static void checked_index(Gen *g, LLVMValueRef index, LLVMValueRef length) {
  if (block_dominates(g, g->bounds_fact_block,
                      LLVMGetInsertBlock(g->builder)) &&
      same_guard_value(g->bounds_index, index,
                       g->bounds_fact_epoch == g->statement_epoch) &&
      same_guard_value(g->bounds_length, length,
                       g->bounds_fact_epoch == g->statement_epoch))
    return;
  guard(g, LLVMBuildICmp(g->builder, 36, index, length, "index.in.bounds"),
        "index.ok");
  g->bounds_fact_block = LLVMGetInsertBlock(g->builder);
  g->bounds_index = index;
  g->bounds_length = length;
  g->bounds_fact_epoch = g->statement_epoch;
}
static LLVMValueRef checked_overflow(Gen *g, DynOperator op, DynType type,
                                     LLVMValueRef l, LLVMValueRef r) {
  const char *operation = op == DYN_OP_ADD   ? "add"
                          : op == DYN_OP_SUB ? "sub"
                                             : "mul";
  char name[64];
  snprintf(name, sizeof(name), "llvm.%c%s.with.overflow.i%u",
           signed_type(type) ? 's' : 'u', operation, type_bits(g, type));
  LLVMTypeRef narrow = llvm_type(g, type), fn_type;
  LLVMValueRef fn = LLVMGetNamedFunction(g->module, name);
  if (fn)
    fn_type = LLVMGlobalGetValueType(fn);
  else {
    LLVMTypeRef fields[] = {narrow, LLVMInt1TypeInContext(g->context)},
                result_type = LLVMStructTypeInContext(g->context, fields, 2, 0),
                params[] = {narrow, narrow};
    fn_type = LLVMFunctionType(result_type, params, 2, 0);
    fn = LLVMAddFunction(g->module, name, fn_type);
  }
  LLVMValueRef args[] = {l, r}, pair = LLVMBuildCall2(g->builder, fn_type, fn,
                                                      args, 2, "checked");
  LLVMValueRef result =
                   LLVMBuildExtractValue(g->builder, pair, 0, "checked.value"),
               overflow = LLVMBuildExtractValue(g->builder, pair, 1,
                                                "checked.overflow");
  guard(g, LLVMBuildNot(g->builder, overflow, "checked.valid"), "overflow.ok");
  return result;
}
static LLVMValueRef proven_integer(Gen *g, DynOperator op, LLVMValueRef l,
                                   LLVMValueRef r) {
  if (op == DYN_OP_ADD)
    return LLVMBuildAdd(g->builder, l, r, "proven.add");
  if (op == DYN_OP_SUB)
    return LLVMBuildSub(g->builder, l, r, "proven.sub");
  return LLVMBuildMul(g->builder, l, r, "proven.mul");
}
static LLVMValueRef checked_integer(Gen *g, DynOperator op, DynType type,
                                    LLVMValueRef l, LLVMValueRef r) {
  unsigned width = type_bits(g, type);
  LLVMTypeRef narrow = llvm_type(g, type);
  if (op == DYN_OP_DIV || op == DYN_OP_REM) {
    LLVMValueRef nz =
        LLVMBuildICmp(g->builder, 33, r, LLVMConstInt(narrow, 0, 0), "nonzero");
    guard(g, nz, "divide.ok");
    if (signed_type(type)) {
      LLVMValueRef minimum =
                       LLVMConstInt(narrow, UINT64_C(1) << (width - 1), 1),
                   negative_one = LLVMConstInt(narrow, UINT64_MAX, 1);
      LLVMValueRef overflow = LLVMBuildAnd(
          g->builder,
          LLVMBuildICmp(g->builder, 32, l, minimum, "division.minimum"),
          LLVMBuildICmp(g->builder, 32, r, negative_one,
                        "division.negative_one"),
          "division.overflow");
      guard(g, LLVMBuildNot(g->builder, overflow, "division.valid"),
            "division.overflow.ok");
      return op == DYN_OP_DIV ? LLVMBuildSDiv(g->builder, l, r, "div")
                              : LLVMBuildSRem(g->builder, l, r, "rem");
    }
    return op == DYN_OP_DIV ? LLVMBuildUDiv(g->builder, l, r, "div")
                            : LLVMBuildURem(g->builder, l, r, "rem");
  }
  LLVMTypeRef wide = LLVMIntTypeInContext(g->context, width * 2);
  LLVMValueRef wl = signed_type(type)
                        ? LLVMBuildSExt(g->builder, l, wide, "lhs.wide")
                        : LLVMBuildZExt(g->builder, l, wide, "lhs.wide");
  LLVMValueRef wr = signed_type(type)
                        ? LLVMBuildSExt(g->builder, r, wide, "rhs.wide")
                        : LLVMBuildZExt(g->builder, r, wide, "rhs.wide");
  LLVMValueRef result = NULL;
  if (op == DYN_OP_SHL || op == DYN_OP_SHR) {
    LLVMValueRef valid = LLVMBuildICmp(
        g->builder, 36, r, LLVMConstInt(llvm_type(g, type), width, 0),
        "shift.valid");
    guard(g, valid, "shift.ok");
    if (op == DYN_OP_SHR)
      return signed_type(type) ? LLVMBuildAShr(g->builder, l, r, "shr")
                               : LLVMBuildLShr(g->builder, l, r, "shr");
    result = LLVMBuildShl(g->builder, wl, wr, "shl.wide");
  } else
    return checked_overflow(g, op, type, l, r);
  LLVMValueRef narrowed = LLVMBuildTrunc(g->builder, result, narrow, "narrow");
  LLVMValueRef restored =
      signed_type(type) ? LLVMBuildSExt(g->builder, narrowed, wide, "restored")
                        : LLVMBuildZExt(g->builder, narrowed, wide, "restored");
  LLVMValueRef fits = LLVMBuildICmp(g->builder, 32, result, restored, "fits");
  guard(g, fits, "overflow.ok");
  return narrowed;
}
static LLVMValueRef static_expr(Gen *g, DynExprId id, size_t depth) {
  if (id == DYN_NO_EXPR || id >= g->ir->expression_count ||
      depth > g->ir->global_count + g->ir->expression_count)
    return NULL;
  DynIrExpr *e = &g->ir->expressions[id];
  LLVMTypeRef type = llvm_type(g, e->type);
  if (e->kind == DYN_EXPR_FUNCTION) {
    return g->functions[e->integer];
  }
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_CHAR)
    return LLVMConstInt(type, e->integer, 0);
  if (e->kind == DYN_EXPR_BOOL)
    return LLVMConstInt(type, e->boolean, 0);
  if (e->kind == DYN_EXPR_FLOAT)
    return LLVMConstReal(type, e->floating);
  if (e->kind == DYN_EXPR_NIL)
    return LLVMConstNull(type);
  if (e->kind == DYN_EXPR_GLOBAL) {
    uint32_t idg = (uint32_t)e->integer;
    return idg < g->ir->global_count && g->ir->globals[idg].is_const
               ? static_expr(g, g->ir->globals[idg].initializer, depth + 1)
               : NULL;
  }
  if (e->kind == DYN_EXPR_CONVERT) {
    DynIrExpr *from = &g->ir->expressions[e->left];
    LLVMValueRef v = static_expr(g, e->left, depth + 1);
    if (!v)
      return NULL;
    /* LLVM has no constant-expression API for these conversions. Returning
       NULL selects the existing runtime initializer path. */
    if ((int_type(from->type) && float_type(e->type)) ||
        (from->type == DYN_TYPE_F32 && e->type == DYN_TYPE_F64))
      return NULL;
    unsigned fb = type_bits(g, from->type), tb = type_bits(g, e->type);
    return fb > tb ? LLVMConstTrunc(v, type) : NULL;
  }
  if (e->kind == DYN_EXPR_UNARY) {
    LLVMValueRef v = static_expr(g, e->left, depth + 1);
    if (!v)
      return NULL;
    if (e->op == DYN_OP_NEG)
      return float_type(e->type) ? NULL : LLVMConstNeg(v);
    if (e->op == DYN_OP_NOT || e->op == DYN_OP_BIT_NOT)
      return LLVMConstNot(v);
    return NULL;
  }
  if (e->kind != DYN_EXPR_BINARY)
    return NULL;
  LLVMValueRef l = static_expr(g, e->left, depth + 1),
               r = static_expr(g, e->right, depth + 1);
  if (!l || !r)
    return NULL;
  if (e->op == DYN_OP_BIT_XOR)
    return LLVMConstXor(l, r);
  if (!float_type(e->type)) {
    if (e->op == DYN_OP_ADD)
      return LLVMConstAdd(l, r);
    if (e->op == DYN_OP_SUB)
      return LLVMConstSub(l, r);
  }
  /* Other operators use the runtime initializer when scalar folding above
     cannot produce a constant. */
  return NULL;
}
static LLVMValueRef static_value(Gen *g, DynExprId id, size_t depth) {
  if (id == DYN_NO_EXPR || id >= g->ir->expression_count ||
      depth > g->ir->global_count + g->ir->expression_count)
    return NULL;
  DynIrExpr *e = &g->ir->expressions[id];
  if (e->kind == DYN_EXPR_STRING) {
    DynIrString *string = &g->ir->strings[e->integer];
    LLVMTypeRef byte = LLVMInt8TypeInContext(g->context),
                array = LLVMArrayType2(byte, string->length);
    LLVMValueRef *bytes = calloc(string->length, sizeof(*bytes));
    if (string->length && !bytes)
      return NULL;
    for (size_t i = 0; i < string->length; ++i)
      bytes[i] = LLVMConstInt(byte, string->data[i], 0);
    LLVMValueRef initializer = LLVMConstArray2(byte, bytes, string->length);
    free(bytes);
    char name[64];
    snprintf(name, sizeof(name), ".dyn.reflect.string.%zu", g->string_serial++);
    LLVMValueRef global = LLVMAddGlobal(g->module, array, name);
    LLVMSetLinkage(global, LLVMPrivateLinkage);
    LLVMSetGlobalConstant(global, 1);
    LLVMSetInitializer(global, initializer);
    LLVMValueRef values[] = {
        global,
        LLVMConstInt(llvm_type(g, DYN_TYPE_USIZE), string->length, 0)};
    return LLVMConstNamedStruct(llvm_type(g, e->type), values, 2);
  }
  if (int_type(e->type) || e->type == DYN_TYPE_BOOL) {
    StaticInt x = static_integer(g, id, depth);
    if (x.ok)
      return LLVMConstInt(llvm_type(g, e->type), x.value, signed_type(e->type));
  }
  if (e->kind == DYN_EXPR_GLOBAL) {
    uint32_t q = (uint32_t)e->integer;
    return q < g->ir->global_count && g->ir->globals[q].is_const
               ? static_value(g, g->ir->globals[q].initializer, depth + 1)
               : NULL;
  }
  if (e->kind == DYN_EXPR_ARRAY) {
    DynIrArray *a = ir_array(g, e->type);
    if (!e->item_count)
      return LLVMConstNull(llvm_type(g, e->type));
    /* Dense tables already have one source item per element. Keeping them
       static avoids generating thousands of stores and making LLVM recover
       the constant initializer. Retain the sparse-array bound: expanding a
       short initializer into a huge zero tail would consume excessive memory. */
    if (a->length > 4096 && a->length != e->item_count)
      return NULL;
    LLVMValueRef *values = calloc(a->length, sizeof(*values));
    if (a->length && !values)
      return NULL;
    for (uint64_t i = 0; i < a->length; ++i)
      values[i] = LLVMConstNull(llvm_type(g, a->element));
    for (uint32_t i = 0; i < e->item_count; ++i) {
      values[i] = static_value(g, g->ir->items[e->item_start + i].expression,
                               depth + 1);
      if (!values[i]) {
        free(values);
        return NULL;
      }
    }
    LLVMValueRef result =
        LLVMConstArray2(llvm_type(g, a->element), values, a->length);
    free(values);
    return result;
  }
  if (e->kind == DYN_EXPR_STRUCT) {
    DynIrStruct *st = &g->ir->structs[e->integer];
    LLVMValueRef *values = calloc(st->field_count, sizeof(*values));
    if (st->field_count && !values)
      return NULL;
    for (uint32_t i = 0; i < st->field_count; ++i) {
      DynIrField *f = &g->ir->fields[st->field_start + i];
      values[i] = f->default_expression == DYN_NO_EXPR
                      ? LLVMConstNull(llvm_type(g, f->type))
                      : static_value(g, f->default_expression, depth + 1);
      if (!values[i]) {
        free(values);
        return NULL;
      }
    }
    for (uint32_t i = 0; i < e->item_count; ++i) {
      DynIrItem *item = &g->ir->items[e->item_start + i];
      values[item->field_index] = static_value(g, item->expression, depth + 1);
      if (!values[item->field_index]) {
        free(values);
        return NULL;
      }
    }
    LLVMValueRef result =
        LLVMConstNamedStruct(llvm_type(g, e->type), values, st->field_count);
    free(values);
    return result;
  }
  return static_expr(g, id, depth);
}
static LLVMValueRef gen_expr(Gen *, DynExprId);
static bool addressable(Gen *g, DynExprId id) {
  DynIrExpr *e = &g->ir->expressions[id];
  if (e->kind == DYN_EXPR_NAME || e->kind == DYN_EXPR_GLOBAL)
    return true;
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_DEREF)
    return true;
  if (e->kind == DYN_EXPR_FIELD)
    return dyn_type_is_pointer(g->ir->expressions[e->left].type) ||
           addressable(g, e->left);
  if (e->kind == DYN_EXPR_INDEX)
    return true;
  return false;
}
static LLVMValueRef as_usize(Gen *g, DynExprId id) {
  LLVMValueRef v = gen_expr(g, id);
  unsigned b = type_bits(g, g->ir->expressions[id].type);
  LLVMTypeRef u = llvm_type(g, DYN_TYPE_USIZE);
  unsigned width = g->pointer_bytes * 8;
  if (b > width)
    guard(g, LLVMBuildICmp(g->builder, 37, v,
      LLVMConstInt(LLVMTypeOf(v), UINT32_MAX, 0), "index.fits"), "index.width.ok");
  return b < width ? LLVMBuildZExt(g->builder, v, u, "usize")
       : b > width ? LLVMBuildTrunc(g->builder, v, u, "usize") : v;
}
static LLVMValueRef lvalue_pointer(Gen *g, DynExprId id) {
  DynIrExpr *e = &g->ir->expressions[id];
  if (e->kind == DYN_EXPR_NAME)
    return g->locals[e->integer];
  if (e->kind == DYN_EXPR_GLOBAL)
    return g->globals[e->integer];
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_DEREF) {
    DynIrPointer *p = ir_pointer(g, g->ir->expressions[e->left].type);
    return checked_pointer(g, gen_expr(g, e->left), p->pointee);
  }
  if (e->kind == DYN_EXPR_FIELD) {
    DynIrExpr *base = &g->ir->expressions[e->left];
    DynType aggregate_type = base->type;
    LLVMValueRef aggregate_pointer;
    if (dyn_type_is_pointer(aggregate_type)) {
      DynIrPointer *p = ir_pointer(g, aggregate_type);
      aggregate_type = p->pointee;
      aggregate_pointer =
          checked_pointer(g, gen_expr(g, e->left), aggregate_type);
    } else
      aggregate_pointer = lvalue_pointer(g, e->left);
    return LLVMBuildStructGEP2(g->builder, llvm_type(g, aggregate_type),
                               aggregate_pointer, (unsigned)e->integer,
                               "field.pointer");
  }
  if (e->kind == DYN_EXPR_INDEX) {
    DynType base = g->ir->expressions[e->left].type;
    LLVMValueRef index = as_usize(g, e->right), length, data;
    if (dyn_type_is_array(base)) {
      DynIrArray *a = ir_array(g, base);
      length = LLVMConstInt(llvm_type(g, DYN_TYPE_USIZE), a->length, 0);
      LLVMValueRef zero =
                       LLVMConstInt(LLVMInt64TypeInContext(g->context), 0, 0),
                   indices[] = {zero, index};
      data = LLVMBuildGEP2(g->builder, llvm_type(g, base),
                           lvalue_pointer(g, e->left), indices, 2,
                           "array.element");
    } else {
      DynIrSlice *sl = ir_slice(g, base);
      LLVMValueRef value = gen_expr(g, e->left);
      data = LLVMBuildExtractValue(g->builder, value, 0, "slice.data");
      length = LLVMBuildExtractValue(g->builder, value, 1, "slice.len");
      (void)sl;
      LLVMValueRef indices[] = {index};
      data = LLVMBuildGEP2(g->builder, llvm_type(g, e->type), data, indices, 1,
                           "slice.element");
    }
    if (!e->boolean)
      checked_index(g, index, length);
    return data;
  }
  return NULL;
}
static LLVMValueRef gen_expr(Gen *g, DynExprId id) {
  DynIrExpr *e = &g->ir->expressions[id];
  debug_location(g, e->span);
  LLVMTypeRef type = llvm_type(g, e->type);
  if (g->captured_values && g->captured_values[id])
    return LLVMBuildLoad2(g->builder, type, g->captured_values[id],
                          "defer.capture");
  if (e->kind == DYN_EXPR_STRING) {
    DynIrString *string = &g->ir->strings[e->integer];
    LLVMTypeRef byte = LLVMInt8TypeInContext(g->context),
                array = LLVMArrayType2(byte, string->length);
    LLVMValueRef *bytes = calloc(string->length, sizeof(*bytes));
    if (string->length && !bytes) {
      g->allocation_failed = true;
      return e->type == DYN_TYPE_VOID ? NULL : LLVMConstNull(type);
    }
    for (size_t i = 0; i < string->length; ++i)
      bytes[i] = LLVMConstInt(byte, string->data[i], 0);
    LLVMValueRef initializer = LLVMConstArray2(byte, bytes, string->length);
    free(bytes);
    char name[64];
    snprintf(name, sizeof(name), ".dyn.string.%zu", g->string_serial++);
    LLVMValueRef global = LLVMAddGlobal(g->module, array, name);
    LLVMSetLinkage(global, LLVMPrivateLinkage);
    LLVMSetInitializer(global, initializer);
    LLVMSetGlobalConstant(global, 1);
    LLVMSetLinkage(global, LLVMPrivateLinkage);
    LLVMValueRef value = LLVMConstNull(type);
    value = LLVMBuildInsertValue(g->builder, value, global, 0, "string.data");
    return LLVMBuildInsertValue(
        g->builder, value,
        LLVMConstInt(llvm_type(g, DYN_TYPE_USIZE), string->length, 0), 1,
        "string.len");
  }
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_CHAR)
    return LLVMConstInt(type, e->integer, 0);
  if (e->kind == DYN_EXPR_BOOL)
    return LLVMConstInt(type, e->boolean, 0);
  if (e->kind == DYN_EXPR_FLOAT)
    return LLVMConstReal(type, e->floating);
  if (e->kind == DYN_EXPR_NIL)
    return LLVMConstNull(type);
  if (e->kind == DYN_EXPR_NAME)
    return LLVMBuildLoad2(g->builder, type, g->locals[e->integer], "load");
  if (e->kind == DYN_EXPR_GLOBAL)
    return LLVMBuildLoad2(g->builder, type, g->globals[e->integer],
                          "global.load");
  if (e->kind == DYN_EXPR_FUNCTION)
    return g->functions[e->integer];
  if (e->kind == DYN_EXPR_ENUM) {
    DynIrEnum *en = &g->ir->enums[e->type - DYN_TYPE_ENUM_BASE];
    DynIrVariant *v = &g->ir->variants[e->integer];
    if (!en->has_payload)
      return LLVMConstInt(llvm_type(g, en->tag_type), v->tag, 0);
    LLVMValueRef storage = gen_stack_slot(g, type, "enum.temporary"),
                 tagp = LLVMBuildStructGEP2(g->builder, type, storage, 0,
                                            "enum.tag.pointer");
    LLVMBuildStore(g->builder,
                   LLVMConstInt(llvm_type(g, en->tag_type), v->tag, 0), tagp);
    if (v->payload_type != DYN_TYPE_VOID) {
      LLVMValueRef payloadp = LLVMBuildStructGEP2(g->builder, type, storage, 1,
                                                  "enum.payload.pointer");
      LLVMBuildStore(g->builder,
                     gen_expr(g, g->ir->items[e->item_start].expression),
                     payloadp);
    }
    return LLVMBuildLoad2(g->builder, type, storage, "enum.value");
  }
  if (e->kind == DYN_EXPR_ARRAY) {
    LLVMValueRef value = LLVMConstNull(type);
    for (uint32_t i = 0; i < e->item_count; ++i)
      value = LLVMBuildInsertValue(
          g->builder, value,
          gen_expr(g, g->ir->items[e->item_start + i].expression), i,
          "array.item");
    return value;
  }
  if (e->kind == DYN_EXPR_INDEX)
    return LLVMBuildLoad2(g->builder, type, lvalue_pointer(g, id), "index");
  if (e->kind == DYN_EXPR_LEN) {
    DynType base = g->ir->expressions[e->left].type;
    if (dyn_type_is_array(base))
      return LLVMConstInt(type, ir_array(g, base)->length, 0);
    return LLVMBuildExtractValue(g->builder, gen_expr(g, e->left), 1,
                                 "slice.len");
  }
  if (e->kind == DYN_EXPR_SLICE) {
    DynType base = g->ir->expressions[e->left].type;
    LLVMTypeRef usize = llvm_type(g, DYN_TYPE_USIZE);
    LLVMValueRef data, length = NULL;
    bool raw = dyn_type_is_pointer(base);
    if (dyn_type_is_array(base)) {
      DynIrArray *a = ir_array(g, base);
      length = LLVMConstInt(usize, a->length, 0);
      LLVMValueRef zero = LLVMConstInt(usize, 0, 0), indices[] = {zero, zero};
      LLVMValueRef pointer = lvalue_pointer(g, e->left);
      if (!pointer) {
        LLVMValueRef constant = static_value(g, e->left, 0);
        if (constant) {
          char name[64];
          snprintf(name, sizeof(name), ".dyn.reflect.members.%zu",
                   g->string_serial++);
          pointer = LLVMAddGlobal(g->module, llvm_type(g, base), name);
          LLVMSetLinkage(pointer, LLVMPrivateLinkage);
          LLVMSetGlobalConstant(pointer, 1);
          LLVMSetInitializer(pointer, constant);
        } else {
          pointer = gen_stack_slot(g, llvm_type(g, base),
                                    "slice.array.temporary");
          LLVMBuildStore(g->builder, gen_expr(g, e->left), pointer);
        }
      }
      data = LLVMBuildGEP2(g->builder, llvm_type(g, base), pointer, indices, 2,
                           "array.data");
    } else if (raw) {
      DynIrPointer *p = ir_pointer(g, base);
      data = checked_pointer(g, gen_expr(g, e->left), p->pointee);
    } else {
      LLVMValueRef source = gen_expr(g, e->left);
      data = LLVMBuildExtractValue(g->builder, source, 0, "slice.data");
      length = LLVMBuildExtractValue(g->builder, source, 1, "slice.len");
    }
    LLVMValueRef start = e->right == DYN_NO_EXPR ? LLVMConstInt(usize, 0, 0)
                                                 : as_usize(g, e->right),
                 end = raw ? as_usize(g, (DynExprId)e->integer)
                       : e->integer == DYN_NO_EXPR
                           ? length
                           : as_usize(g, (DynExprId)e->integer);
    guard(g, LLVMBuildICmp(g->builder, 37, start, end, "slice.ordered"),
          "slice.order.ok");
    if (!raw)
      guard(g, LLVMBuildICmp(g->builder, 37, end, length, "slice.in.bounds"),
            "slice.bounds.ok");
    LLVMValueRef indices[] = {start};
    data =
        LLVMBuildGEP2(g->builder, llvm_type(g, ir_slice(g, e->type)->element),
                      data, indices, 1, "slice.start");
    LLVMValueRef value = LLVMConstNull(type);
    value =
        LLVMBuildInsertValue(g->builder, value, data, 0, "slice.data.value");
    return LLVMBuildInsertValue(
        g->builder, value, LLVMBuildSub(g->builder, end, start, "slice.count"),
        1, "slice.len.value");
  }
  if (e->kind == DYN_EXPR_CALL) {
    DynIrFunction *callee = &g->ir->functions[e->integer];
    bool packed = callee->variadic && !callee->foreign &&
                  dyn_type_is_slice(callee->variadic_type);
    uint32_t extra = packed ? 2 : 0;
    LLVMValueRef *args = calloc(e->item_count + extra, sizeof(*args));
    if ((e->item_count + extra) && !args) {
      g->allocation_failed = true;
      return e->type == DYN_TYPE_VOID ? NULL : LLVMConstNull(type);
    }
    for (uint32_t i = 0; i < (packed ? callee->param_count : e->item_count);
         ++i)
      args[i] = gen_expr(g, g->ir->items[e->item_start + i].expression);
    if (packed) {
      uint32_t n = e->item_count - callee->param_count;
      DynType arg_type = ir_slice(g, callee->variadic_type)->element;
      LLVMTypeRef descriptor = llvm_type(g, arg_type);
      LLVMValueRef data =
          LLVMConstNull(LLVMPointerTypeInContext(g->context, 0));
      if (n) {
        LLVMTypeRef array = LLVMArrayType2(descriptor, n);
        LLVMValueRef storage =
            gen_stack_slot(g, array, "variadic.args");
        LLVMValueRef zero =
            LLVMConstInt(LLVMInt64TypeInContext(g->context), 0, 0);
        for (uint32_t i = 0; i < n; ++i) {
          DynExprId id =
              g->ir->items[e->item_start + callee->param_count + i].expression;
          DynType value_type = g->ir->expressions[id].type;
          LLVMValueRef item;
          if (arg_type == DYN_TYPE_ANY) {
            LLVMValueRef slot = gen_stack_slot(
                g, llvm_type(g, value_type), "variadic.value");
            LLVMBuildStore(g->builder, gen_expr(g, id), slot);
            item = LLVMConstNull(descriptor);
            item = LLVMBuildInsertValue(
                g->builder, item,
                LLVMConstInt(LLVMInt64TypeInContext(g->context), value_type, 0),
                0, "any.type");
            item = LLVMBuildInsertValue(g->builder, item, slot, 1, "any.data");
          } else
            item = gen_expr(g, id);
          LLVMValueRef indexes[] = {
              zero, LLVMConstInt(LLVMInt64TypeInContext(g->context), i, 0)};
          LLVMValueRef destination = LLVMBuildGEP2(g->builder, array, storage,
                                                   indexes, 2, "variadic.item");
          LLVMBuildStore(g->builder, item, destination);
        }
        LLVMValueRef indexes[] = {zero, zero};
        data = LLVMBuildGEP2(g->builder, array, storage, indexes, 2,
                             "variadic.data.pointer");
      }
      args[callee->param_count] = data;
      args[callee->param_count + 1] =
          LLVMConstInt(llvm_type(g, DYN_TYPE_USIZE), n, 0);
    }
    LLVMValueRef result =
        abi_call(g, g->abis[e->integer], g->functions[e->integer],
                  args, packed ? callee->param_count + 2 : e->item_count, "call", true);
    free(args);
    return result;
  }
  if (e->kind == DYN_EXPR_INDIRECT_CALL) {
    LLVMValueRef callee = gen_expr(g, e->left),
                 nonnull = LLVMBuildICmp(
                     g->builder, 33, callee,
                     LLVMConstNull(LLVMPointerTypeInContext(g->context, 0)),
                     "function.nonnull");
    guard(g, nonnull, "function.nonnull.ok");
    LLVMValueRef *args = calloc(e->item_count, sizeof(*args));
    if ((e->item_count) && !args) {
      g->allocation_failed = true;
      return e->type == DYN_TYPE_VOID ? NULL : LLVMConstNull(type);
    }
    for (uint32_t i = 0; i < e->item_count; ++i)
      args[i] = gen_expr(g, g->ir->items[e->item_start + i].expression);
    LLVMTypeRef signature = llvm_fn_type(g, (uint32_t)e->integer);
    if (!signature) {
      free(args);
      return e->type == DYN_TYPE_VOID ? NULL : LLVMConstNull(type);
    }
    LLVMValueRef result =
        abi_call(g, g->pointer_abis[e->integer], callee, args, e->item_count, "indirect.call", true);
    free(args);
    return result;
  }
  if (e->kind == DYN_EXPR_FIELD)
    return addressable(g, id)
               ? LLVMBuildLoad2(g->builder, type, lvalue_pointer(g, id),
                                "field")
               : LLVMBuildExtractValue(g->builder, gen_expr(g, e->left),
                                       (unsigned)e->integer, "field");
  if (e->kind == DYN_EXPR_STRUCT) {
    uint32_t sid = (uint32_t)e->integer;
    DynIrStruct *st = &g->ir->structs[sid];
    LLVMValueRef value = LLVMConstNull(type);
    for (uint32_t i = 0; i < st->field_count; ++i) {
      DynIrField *f = &g->ir->fields[st->field_start + i];
      if (f->default_expression != DYN_NO_EXPR)
        value = LLVMBuildInsertValue(g->builder, value,
                                     gen_expr(g, f->default_expression), i,
                                     "default.field");
    }
    for (uint32_t i = 0; i < e->item_count; ++i) {
      DynIrItem *item = &g->ir->items[e->item_start + i];
      value =
          LLVMBuildInsertValue(g->builder, value, gen_expr(g, item->expression),
                               item->field_index, "literal.field");
    }
    return value;
  }
  if (e->kind == DYN_EXPR_CAST) {
    DynIrExpr *source = &g->ir->expressions[e->left];
    LLVMValueRef value = gen_expr(g, e->left);
    bool source_ptr =
        dyn_type_is_pointer(source->type) || source->type == DYN_TYPE_RAWPTR;
    bool target_ptr =
        dyn_type_is_pointer(e->type) || e->type == DYN_TYPE_RAWPTR;
    if (source->type == e->type || (source_ptr && target_ptr))
      return value;
    if (source_ptr && int_type(e->type))
      return LLVMBuildPtrToInt(g->builder, value, type,
                               "cast.pointer.to.integer");
    if (int_type(source->type) && target_ptr)
      return LLVMBuildIntToPtr(g->builder, value, type,
                               "cast.integer.to.pointer");
    if (int_type(source->type) && int_type(e->type)) {
      unsigned from = type_bits(g, source->type), to = type_bits(g, e->type);
      if (from == to)
        return value;
      if (from > to)
        return LLVMBuildTrunc(g->builder, value, type, "cast.trunc");
      return signed_type(source->type)
                 ? LLVMBuildSExt(g->builder, value, type, "cast.sext")
                 : LLVMBuildZExt(g->builder, value, type, "cast.zext");
    }
    if (int_type(source->type) && float_type(e->type))
      return signed_type(source->type)
                 ? LLVMBuildSIToFP(g->builder, value, type, "cast.sitofp")
                 : LLVMBuildUIToFP(g->builder, value, type, "cast.uitofp");
    if (float_type(source->type) && int_type(e->type))
      return signed_type(e->type)
                 ? LLVMBuildFPToSI(g->builder, value, type, "cast.fptosi")
                 : LLVMBuildFPToUI(g->builder, value, type, "cast.fptoui");
    return source->type == DYN_TYPE_F64
               ? LLVMBuildFPTrunc(g->builder, value, type, "cast.fptrunc")
               : LLVMBuildFPExt(g->builder, value, type, "cast.fpext");
  }
  if (e->kind == DYN_EXPR_BITCAST)
    return LLVMBuildBitCast(g->builder, gen_expr(g, e->left), type, "bitcast");
  if (e->kind == DYN_EXPR_SYSCALL) {
    LLVMTypeRef i64 = LLVMInt64TypeInContext(g->context);
    LLVMValueRef args[7];
    for (uint32_t i = 0; i < 7; ++i)
      args[i] = LLVMConstInt(i64, 0, 0);
    for (uint32_t i = 0; i < e->item_count && i < 7; ++i) {
      DynExprId arg = g->ir->items[e->item_start + i].expression;
      DynType at = g->ir->expressions[arg].type;
      LLVMValueRef value = gen_expr(g, arg);
      if (dyn_type_is_pointer(at))
        value = LLVMBuildPtrToInt(g->builder, value, i64, "syscall.pointer");
      else {
        unsigned width = type_bits(g, at);
        if (width < 64)
          value = signed_type(at)
                      ? LLVMBuildSExt(g->builder, value, i64, "syscall.sext")
                      : LLVMBuildZExt(g->builder, value, i64, "syscall.zext");
        else if (width > 64)
          value = LLVMBuildTrunc(g->builder, value, i64, "syscall.trunc");
      }
      args[i] = value;
    }
    ++g->statement_epoch;
    return LLVMBuildCall2(g->builder, g->syscall_type, g->syscall_fn, args, 7,
                          "syscall");
  }
  if (e->kind == DYN_EXPR_CONVERT) {
    DynIrExpr *source = &g->ir->expressions[e->left];
    LLVMValueRef value = gen_expr(g, e->left);
    if (e->type == DYN_TYPE_ANY) {
      LLVMValueRef slot =
          gen_stack_slot(g, llvm_type(g, source->type), "any.value");
      LLVMBuildStore(g->builder, value, slot);
      LLVMValueRef boxed = LLVMConstNull(type);
      boxed = LLVMBuildInsertValue(
          g->builder, boxed,
          LLVMConstInt(LLVMInt64TypeInContext(g->context), source->type, 0), 0,
          "any.type");
      return LLVMBuildInsertValue(g->builder, boxed, slot, 1, "any.data");
    }
    if ((dyn_type_is_pointer(source->type) && dyn_type_is_pointer(e->type)) ||
        (dyn_type_is_slice(source->type) && dyn_type_is_slice(e->type)))
      return value;
    if (int_type(source->type) && float_type(e->type))
      return signed_type(source->type)
                 ? LLVMBuildSIToFP(g->builder, value, type, "sitofp")
                 : LLVMBuildUIToFP(g->builder, value, type, "uitofp");
    if (source->type == DYN_TYPE_F32 && e->type == DYN_TYPE_F64)
      return LLVMBuildFPExt(g->builder, value, type, "fpext");
    return signed_type(source->type)
               ? LLVMBuildSExt(g->builder, value, type, "sext")
               : LLVMBuildZExt(g->builder, value, type, "zext");
  }
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_ADDRESS)
    return lvalue_pointer(g, e->left);
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_DEREF)
    return LLVMBuildLoad2(g->builder, type, lvalue_pointer(g, id),
                          "dereference");
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_NEG && e->boolean) {
    uint64_t magnitude = g->ir->expressions[e->left].integer;
    return LLVMConstInt(type, UINT64_C(0) - magnitude, 1);
  }
  LLVMValueRef l = gen_expr(g, e->left);
  if (e->kind == DYN_EXPR_UNARY) {
    if (e->op == DYN_OP_NOT || e->op == DYN_OP_BIT_NOT)
      return LLVMBuildNot(g->builder, l, "not");
    if (float_type(e->type))
      return LLVMBuildFNeg(g->builder, l, "neg");
    LLVMValueRef zero = LLVMConstInt(type, 0, 0);
    return checked_integer(g, DYN_OP_SUB, e->type, zero, l);
  }
  if (e->op == DYN_OP_LOGICAL_AND || e->op == DYN_OP_LOGICAL_OR) {
    LLVMValueRef short_value =
        LLVMConstInt(type, e->op == DYN_OP_LOGICAL_OR, 0);
    LLVMBasicBlockRef left_block = LLVMGetInsertBlock(g->builder);
    LLVMBasicBlockRef rhs = LLVMAppendBasicBlockInContext(
                          g->context, g->function, "logical.rhs"),
                      done = LLVMAppendBasicBlockInContext(
                          g->context, g->function, "logical.done");
    if (e->op == DYN_OP_LOGICAL_AND)
      LLVMBuildCondBr(g->builder, l, rhs, done);
    else
      LLVMBuildCondBr(g->builder, l, done, rhs);
    LLVMPositionBuilderAtEnd(g->builder, rhs);
    LLVMValueRef right_value = gen_expr(g, e->right);
    LLVMBasicBlockRef right_block = LLVMGetInsertBlock(g->builder);
    LLVMBuildBr(g->builder, done);
    LLVMPositionBuilderAtEnd(g->builder, done);
    LLVMValueRef value = LLVMBuildPhi(g->builder, type, "logical.value");
    LLVMValueRef incoming[] = {short_value, right_value};
    LLVMBasicBlockRef blocks[] = {left_block, right_block};
    LLVMAddIncoming(value, incoming, blocks, 2);
    return value;
  }
  LLVMValueRef r = gen_expr(g, e->right);
  if (e->op >= DYN_OP_EQ && e->op <= DYN_OP_GE) {
    int predicates_signed[] = {32, 33, 40, 41, 38, 39},
        predicates_unsigned[] = {32, 33, 36, 37, 34, 35},
        predicates_float[] = {1, 6, 4, 5, 2, 3};
    unsigned index = (unsigned)e->op - (unsigned)DYN_OP_EQ;
    if (float_type(g->ir->expressions[e->left].type))
      return LLVMBuildFCmp(g->builder, predicates_float[index], l, r, "fcmp");
    return LLVMBuildICmp(g->builder,
                         signed_type(g->ir->expressions[e->left].type)
                             ? predicates_signed[index]
                             : predicates_unsigned[index],
                         l, r, "icmp");
  }
  if (e->op == DYN_OP_BIT_AND)
    return LLVMBuildAnd(g->builder, l, r, "and");
  if (e->op == DYN_OP_BIT_OR)
    return LLVMBuildOr(g->builder, l, r, "or");
  if (e->op == DYN_OP_BIT_XOR)
    return LLVMBuildXor(g->builder, l, r, "xor");
  if (e->op == DYN_OP_SHL || e->op == DYN_OP_SHR) {
    DynType right_type = g->ir->expressions[e->right].type;
    LLVMTypeRef right_llvm = llvm_type(g, right_type);
    LLVMValueRef valid = LLVMBuildICmp(
        g->builder, 36, r, LLVMConstInt(right_llvm, type_bits(g, e->type), 0),
        "shift.count.valid");
    guard(g, valid, "shift.count.ok");
    unsigned rb = type_bits(g, right_type), lb = type_bits(g, e->type);
    if (rb > lb)
      r = LLVMBuildTrunc(g->builder, r, type, "shift.count");
    else if (rb < lb)
      r = LLVMBuildZExt(g->builder, r, type, "shift.count");
    return checked_integer(g, e->op, e->type, l, r);
  }
  if (int_type(e->type))
    return e->boolean ? proven_integer(g, e->op, l, r)
                      : checked_integer(g, e->op, e->type, l, r);
  if (e->op == DYN_OP_ADD)
    return LLVMBuildFAdd(g->builder, l, r, "fadd");
  if (e->op == DYN_OP_SUB)
    return LLVMBuildFSub(g->builder, l, r, "fsub");
  if (e->op == DYN_OP_MUL)
    return LLVMBuildFMul(g->builder, l, r, "fmul");
  if (e->op == DYN_OP_DIV)
    return LLVMBuildFDiv(g->builder, l, r, "fdiv");
  return LLVMBuildFRem(g->builder, l, r, "frem");
}
static bool gen_block(Gen *, uint32_t, uint32_t);
static void capture_defer_expr(Gen *g, DynExprId id) {
  if (id == DYN_NO_EXPR || g->captured_values[id])
    return;
  LLVMTypeRef type = llvm_type(g, g->ir->expressions[id].type);
  LLVMValueRef value = gen_expr(g, id),
               slot = gen_stack_slot(g, type, "defer.capture.slot");
  LLVMBuildStore(g->builder, value, slot);
  g->captured_values[id] = slot;
}
static void capture_defer(Gen *g, DynIrStmt *st) {
  if (st->defer_block || st->body_count != 1)
    return;
  DynIrStmt *action = &g->ir->statements[g->ir->children[st->body_start]];
  if (action->kind != DYN_STMT_EXPR)
    return;
  DynIrExpr *call = &g->ir->expressions[action->expression];
  if (call->kind != DYN_EXPR_CALL && call->kind != DYN_EXPR_INDIRECT_CALL)
    return;
  if (call->kind == DYN_EXPR_INDIRECT_CALL)
    capture_defer_expr(g, call->left);
  for (uint32_t i = 0; i < call->item_count; ++i)
    capture_defer_expr(g, g->ir->items[call->item_start + i].expression);
}
/* Initialize aggregates in their destination. Materializing a large struct as
   one SSA value expands every array element in LLVM's instruction selector. */
static void gen_initialize(Gen *g, DynType type, DynExprId expression,
                           LLVMValueRef destination) {
  DynIrExpr *value = expression == DYN_NO_EXPR ? NULL : &g->ir->expressions[expression];
  LLVMTypeRef llvm = llvm_type(g, type);
  if ((!value && (dyn_type_is_struct(type) || dyn_type_is_array(type))) ||
      (value && (value->kind == DYN_EXPR_ARRAY || value->kind == DYN_EXPR_STRUCT))) {
    LLVMValueRef arguments[] = {
        destination, LLVMConstInt(LLVMInt8TypeInContext(g->context), 0, 0),
        LLVMSizeOf(llvm), LLVMConstInt(LLVMInt1TypeInContext(g->context), 0, 0)};
    LLVMBuildCall2(g->builder, g->memset_type, g->memset_fn, arguments, 4, "");
    if (!value) return;
    if (value->kind == DYN_EXPR_ARRAY) {
      DynType element_type = ir_array(g, type)->element;
      for (uint32_t i = 0; i < value->item_count; ++i) {
        LLVMValueRef indices[] = {
            LLVMConstInt(LLVMInt64TypeInContext(g->context), 0, 0),
            LLVMConstInt(LLVMInt64TypeInContext(g->context), i, 0)};
        LLVMValueRef element = LLVMBuildGEP2(g->builder, llvm, destination,
                                            indices, 2, "array.initializer.element");
        gen_initialize(g, element_type,
                       g->ir->items[value->item_start + i].expression, element);
      }
    } else {
      DynIrStruct *record = &g->ir->structs[value->integer];
      for (uint32_t i = 0; i < record->field_count; ++i) {
        DynIrField *field = &g->ir->fields[record->field_start + i];
        if (field->default_expression == DYN_NO_EXPR) continue;
        LLVMValueRef address = LLVMBuildStructGEP2(g->builder, llvm, destination,
                                                    i, "default.field.address");
        gen_initialize(g, field->type, field->default_expression, address);
      }
      for (uint32_t i = 0; i < value->item_count; ++i) {
        DynIrItem *item = &g->ir->items[value->item_start + i];
        DynIrField *field = &g->ir->fields[record->field_start + item->field_index];
        LLVMValueRef address = LLVMBuildStructGEP2(g->builder, llvm, destination,
                                                    item->field_index, "literal.field.address");
        gen_initialize(g, field->type, item->expression, address);
      }
    }
    return;
  }
  LLVMBuildStore(g->builder, value ? gen_expr(g, expression) : LLVMConstNull(llvm),
                 destination);
}
static bool gen_stmt(Gen *g, DynIrStmt *st) {
  ++g->statement_epoch;
  debug_location(g, st->span);
  if (st->kind == DYN_STMT_DEFER) {
    capture_defer(g, st);
    g->defer_stack[g->defer_count++].defer_statement =
        (uint32_t)(st - g->ir->statements);
    return false;
  }
  if (st->kind == DYN_STMT_PANIC) {
    emit_defers(g, 0);
    LLVMValueRef message = gen_expr(g, st->expression);
    emit_panic(g, LLVMBuildExtractValue(g->builder, message, 0, "panic.data"),
               LLVMBuildExtractValue(g->builder, message, 1, "panic.len"));
    LLVMBuildUnreachable(g->builder);
    return true;
  }
  if (st->kind == DYN_STMT_RETURN) {
    LLVMValueRef result = NULL;
    if (!g->is_main && g->return_type != DYN_TYPE_VOID)
      result = gen_expr(g, st->expression);
    emit_defers(g, 0);
    emit_trace_pop(g);
    if (g->is_main)
      LLVMBuildRet(g->builder,
                   LLVMConstInt(LLVMInt32TypeInContext(g->context), 0, 0));
    else if (g->return_type == DYN_TYPE_VOID)
      LLVMBuildRetVoid(g->builder);
    else
      abi_return(g, result);
    return true;
  }
  if (st->kind == DYN_STMT_BREAK) {
    emit_defers(g, g->defer_stack[st->target_loop_id].break_defer);
    LLVMBuildBr(g->builder, g->defer_stack[st->target_loop_id].break_target);
    return true;
  }
  if (st->kind == DYN_STMT_CONTINUE) {
    emit_defers(g, g->defer_stack[st->target_loop_id].continue_defer);
    LLVMBuildBr(g->builder, g->defer_stack[st->target_loop_id].continue_target);
    return true;
  }
  if (st->kind == DYN_STMT_IF) {
    LLVMBasicBlockRef yes = LLVMAppendBasicBlockInContext(
                          g->context, g->function, "if.then"),
                      no = LLVMAppendBasicBlockInContext(
                          g->context, g->function, "if.else"),
                      done = LLVMAppendBasicBlockInContext(
                          g->context, g->function, "if.done");
    LLVMBuildCondBr(g->builder, gen_expr(g, st->expression), yes,
                    st->else_count ? no : done);
    LLVMPositionBuilderAtEnd(g->builder, yes);
    bool yes_term = gen_block(g, st->body_start, st->body_count);
    if (!yes_term)
      LLVMBuildBr(g->builder, done);
    bool no_term = false;
    if (st->else_count) {
      LLVMPositionBuilderAtEnd(g->builder, no);
      no_term = gen_block(g, st->else_start, st->else_count);
      if (!no_term)
        LLVMBuildBr(g->builder, done);
    } else {
      LLVMPositionBuilderAtEnd(g->builder, no);
      LLVMBuildUnreachable(g->builder);
    }
    LLVMPositionBuilderAtEnd(g->builder, done);
    if (st->else_count && yes_term && no_term) {
      LLVMBuildUnreachable(g->builder);
      return true;
    }
    return false;
  }
  if (st->kind == DYN_STMT_CASE) {
    DynType subject_type = g->ir->expressions[st->expression].type;
    bool enum_case = dyn_type_is_enum(subject_type),
         any_case = subject_type == DYN_TYPE_ANY, reference_subject = false;
    DynIrEnum *en =
        enum_case ? &g->ir->enums[subject_type - DYN_TYPE_ENUM_BASE] : NULL;
    for (uint32_t i = 0; i < st->case_arm_count; ++i)
      if (g->ir->case_arms[st->case_arm_start + i].pointer_binding)
        reference_subject = true;
    LLVMValueRef subject_storage = NULL, subject = NULL;
    if (reference_subject) {
      subject_storage = lvalue_pointer(g, st->expression);
      subject = LLVMBuildLoad2(g->builder, llvm_type(g, subject_type),
                               subject_storage, "case.subject.value");
    } else
      subject = gen_expr(g, st->expression);
    LLVMValueRef test_value = subject;
    if (any_case)
      test_value = LLVMBuildExtractValue(g->builder, subject, 0, "any.type");
    if (enum_case && en->has_payload) {
      if (!subject_storage) {
        subject_storage = gen_stack_slot(
            g, llvm_type(g, subject_type), "case.subject");
        LLVMBuildStore(g->builder, subject, subject_storage);
      }
      test_value = LLVMBuildExtractValue(g->builder, subject, 0, "case.tag");
    }
    LLVMTypeRef test_type = enum_case  ? llvm_type(g, en->tag_type)
                            : any_case ? LLVMInt64TypeInContext(g->context)
                                       : llvm_type(g, subject_type);
    LLVMBasicBlockRef done = LLVMAppendBasicBlockInContext(
                          g->context, g->function, "case.done"),
                      next = NULL;
    bool all_terminate = true;
    for (uint32_t i = 0; i < st->case_arm_count; ++i) {
      DynIrCaseArm *arm = &g->ir->case_arms[st->case_arm_start + i];
      LLVMBasicBlockRef body =
          LLVMAppendBasicBlockInContext(g->context, g->function, "case.arm");
      next =
          LLVMAppendBasicBlockInContext(g->context, g->function, "case.next");
      if (arm->wildcard)
        LLVMBuildBr(g->builder, body);
      else {
        LLVMValueRef condition =
            LLVMConstInt(LLVMInt1TypeInContext(g->context), 0, 0);
        for (uint32_t j = 0; j < arm->pattern_count; ++j) {
          DynIrPattern *p = &g->ir->patterns[arm->pattern_start + j];
          LLVMValueRef match;
          if (p->is_type) {
            match =
                LLVMBuildICmp(g->builder, 32, test_value,
                              LLVMConstInt(test_type, p->type, 0), "case.type");
          } else if (p->is_enum) {
            DynIrVariant *v = &g->ir->variants[p->variant];
            match = LLVMBuildICmp(g->builder, 32, test_value,
                                  LLVMConstInt(test_type, v->tag, 0),
                                  "case.variant");
          } else {
            LLVMValueRef lo = LLVMConstInt(test_type, (uint64_t)p->first, 1),
                         hi = LLVMConstInt(test_type, (uint64_t)p->last, 1);
            unsigned ge = signed_type(subject_type) ? 39 : 35,
                     le = signed_type(subject_type) ? 41 : 37;
            LLVMValueRef lower = LLVMBuildICmp(g->builder, ge, test_value, lo,
                                               "case.lower"),
                         upper = LLVMBuildICmp(g->builder, le, test_value, hi,
                                               "case.upper");
            match = LLVMBuildAnd(g->builder, lower, upper, "case.range");
          }
          condition = LLVMBuildOr(g->builder, condition, match, "case.match");
        }
        LLVMBuildCondBr(g->builder, condition, body, next);
      }
      LLVMPositionBuilderAtEnd(g->builder, body);
      if (arm->local_id != UINT32_MAX) {
        DynIrPattern *p = &g->ir->patterns[arm->pattern_start];
        if (p->is_type) {
          LLVMValueRef data =
              LLVMBuildExtractValue(g->builder, subject, 1, "any.data");
          LLVMBuildStore(g->builder,
                         LLVMBuildLoad2(g->builder, llvm_type(g, p->type), data,
                                        "case.binding"),
                         g->locals[arm->local_id]);
        } else {
          DynIrVariant *v = &g->ir->variants[p->variant];
          LLVMValueRef payload =
              LLVMBuildStructGEP2(g->builder, llvm_type(g, subject_type),
                                  subject_storage, 1, "case.payload");
          if (arm->pointer_binding)
            g->locals[arm->local_id] = payload;
          else
            LLVMBuildStore(g->builder,
                           LLVMBuildLoad2(g->builder,
                                          llvm_type(g, v->payload_type),
                                          payload, "case.binding"),
                           g->locals[arm->local_id]);
        }
      }
      bool terminated = gen_block(g, arm->body_start, arm->body_count);
      all_terminate = all_terminate && terminated;
      if (!terminated) {
        LLVMBuildBr(g->builder, done);
      }
      LLVMPositionBuilderAtEnd(g->builder, next);
    }
    LLVMBuildUnreachable(g->builder);
    LLVMPositionBuilderAtEnd(g->builder, done);
    if (all_terminate) {
      LLVMBuildUnreachable(g->builder);
      return true;
    }
    return false;
  }
  if (st->kind == DYN_STMT_FOR && st->target != DYN_NO_EXPR) {
    DynType collection = g->ir->expressions[st->target].type;
    bool array = dyn_type_is_array(collection);
    LLVMTypeRef usize = llvm_type(g, DYN_TYPE_USIZE),
                ct = llvm_type(g, collection);
    LLVMValueRef source = NULL, storage = NULL,
                 counter = gen_stack_slot(g, usize, "for.index");
    if (array) {
      if (st->for_pointer)
        storage = lvalue_pointer(g, st->target);
      else {
        source = gen_expr(g, st->target);
        storage = gen_stack_slot(g, ct, "for.collection");
        LLVMBuildStore(g->builder, source, storage);
      }
    } else
      source = gen_expr(g, st->target);
    LLVMBuildStore(g->builder, LLVMConstInt(usize, 0, 0), counter);
    LLVMValueRef length =
        array ? LLVMConstInt(usize, ir_array(g, collection)->length, 0)
              : LLVMBuildExtractValue(g->builder, source, 1, "for.len");
    LLVMBasicBlockRef condition = LLVMAppendBasicBlockInContext(
                          g->context, g->function, "for.condition"),
                      body = LLVMAppendBasicBlockInContext(
                          g->context, g->function, "for.body"),
                      increment = LLVMAppendBasicBlockInContext(
                          g->context, g->function, "for.increment"),
                      done = LLVMAppendBasicBlockInContext(
                          g->context, g->function, "for.done");
    LLVMBuildBr(g->builder, condition);
    LLVMPositionBuilderAtEnd(g->builder, condition);
    LLVMValueRef index =
        LLVMBuildLoad2(g->builder, usize, counter, "for.index.value");
    LLVMBuildCondBr(g->builder,
                    LLVMBuildICmp(g->builder, 36, index, length, "for.more"),
                    body, done);
    LLVMPositionBuilderAtEnd(g->builder, body);
    DynType element = array ? ir_array(g, collection)->element
                            : ir_slice(g, collection)->element;
    LLVMValueRef pointer;
    if (array) {
      LLVMValueRef zero = LLVMConstInt(usize, 0, 0), indices[] = {zero, index};
      pointer =
          LLVMBuildGEP2(g->builder, ct, storage, indices, 2, "for.element");
    } else {
      LLVMValueRef data =
                       LLVMBuildExtractValue(g->builder, source, 0, "for.data"),
                   indices[] = {index};
      pointer = LLVMBuildGEP2(g->builder, llvm_type(g, element), data, indices,
                              1, "for.element");
    }
    LLVMBuildStore(g->builder,
                   st->for_pointer
                       ? pointer
                       : LLVMBuildLoad2(g->builder, llvm_type(g, element),
                                        pointer, "for.value"),
                   g->locals[st->local_id]);
    LLVMBasicBlockRef old_break = g->break_target,
                      old_continue = g->continue_target;
    size_t old_break_defer = g->break_defer_count,
           old_continue_defer = g->continue_defer_count;
    g->break_target = done;
    g->continue_target = increment;
    g->break_defer_count = g->continue_defer_count = g->defer_count;
    g->defer_stack[st->loop_id].break_target = done;
    g->defer_stack[st->loop_id].continue_target = increment;
    g->defer_stack[st->loop_id].break_defer = g->defer_count;
    g->defer_stack[st->loop_id].continue_defer = g->defer_count;
    bool terminated = gen_block(g, st->body_start, st->body_count);
    g->break_target = old_break;
    g->continue_target = old_continue;
    g->break_defer_count = old_break_defer;
    g->continue_defer_count = old_continue_defer;
    if (!terminated)
      LLVMBuildBr(g->builder, increment);
    LLVMPositionBuilderAtEnd(g->builder, increment);
    index = LLVMBuildLoad2(g->builder, usize, counter, "for.index.next");
    LLVMBuildStore(g->builder,
                   LLVMBuildAdd(g->builder, index, LLVMConstInt(usize, 1, 0),
                                "for.index.increment"),
                   counter);
    LLVMBuildBr(g->builder, condition);
    LLVMPositionBuilderAtEnd(g->builder, done);
    return false;
  }
  if (st->kind == DYN_STMT_FOR) {
    LLVMBasicBlockRef condition = LLVMAppendBasicBlockInContext(
                          g->context, g->function, "for.condition"),
                      body = LLVMAppendBasicBlockInContext(
                          g->context, g->function, "for.body"),
                      done = LLVMAppendBasicBlockInContext(
                          g->context, g->function, "for.done");
    LLVMBuildBr(g->builder, condition);
    LLVMPositionBuilderAtEnd(g->builder, condition);
    LLVMValueRef test =
        st->expression == DYN_NO_EXPR
            ? LLVMConstInt(LLVMInt1TypeInContext(g->context), 1, 0)
            : gen_expr(g, st->expression);
    LLVMBuildCondBr(g->builder, test, body, done);
    LLVMPositionBuilderAtEnd(g->builder, body);
    LLVMBasicBlockRef old_break = g->break_target,
                      old_continue = g->continue_target;
    size_t old_break_defer = g->break_defer_count,
           old_continue_defer = g->continue_defer_count;
    g->break_target = done;
    g->continue_target = condition;
    g->break_defer_count = g->continue_defer_count = g->defer_count;
    g->defer_stack[st->loop_id].break_target = done;
    g->defer_stack[st->loop_id].continue_target = condition;
    g->defer_stack[st->loop_id].break_defer = g->defer_count;
    g->defer_stack[st->loop_id].continue_defer = g->defer_count;
    bool terminated = gen_block(g, st->body_start, st->body_count);
    g->break_target = old_break;
    g->continue_target = old_continue;
    g->break_defer_count = old_break_defer;
    g->continue_defer_count = old_continue_defer;
    if (!terminated)
      LLVMBuildBr(g->builder, condition);
    LLVMPositionBuilderAtEnd(g->builder, done);
    return false;
  }
  if (st->kind == DYN_STMT_EXPR) {
    (void)gen_expr(g, st->expression);
    return false;
  }
  if (st->kind == DYN_STMT_LOCAL) {
    DynType local_type = g->ir->locals[st->local_id].type;
    gen_initialize(g, local_type, st->expression, g->locals[st->local_id]);
    return false;
  }
  if (st->target != DYN_NO_EXPR) {
    LLVMBuildStore(g->builder, gen_expr(g, st->expression),
                   lvalue_pointer(g, st->target));
    return false;
  }
  if (st->local_id == UINT32_MAX) {
    (void)gen_expr(g, st->expression);
    return false;
  }
  LLVMBuildStore(g->builder, gen_expr(g, st->expression),
                 g->locals[st->local_id]);
  return false;
}
static void emit_defers(Gen *g, size_t base) {
  size_t saved = g->defer_count;
  bool old_unwinding = g->unwinding;
  g->unwinding = true;
  for (size_t i = saved; i > base; --i) {
    DynIrStmt *defer =
        &g->ir->statements[g->defer_stack[i - 1].defer_statement];
    (void)gen_block(g, defer->body_start, defer->body_count);
  }
  g->unwinding = old_unwinding;
  g->defer_count = saved;
}
static bool gen_block(Gen *g, uint32_t start, uint32_t count) {
  size_t base = g->defer_count;
  bool terminated = false;
  for (uint32_t i = 0; i < count; ++i)
    if (gen_stmt(g, &g->ir->statements[g->ir->children[start + i]])) {
      terminated = true;
      break;
    }
  if (!terminated)
    emit_defers(g, base);
  g->defer_count = base;
  return terminated;
}
static int write_text(const char *p, const char *t) {
  FILE *f = fopen(p, "wb");
  if (!f)
    return 1;
  fputs(t, f);
  return fclose(f) != 0;
}
static void global_module_key(const char *name, char *out, size_t capacity) {
  if (!strncmp(name, "dyn_m", 5) && strlen(name) > 21 && name[21] == '_')
    snprintf(out, capacity, "%.21s", name);
  else
    snprintf(out, capacity, "root");
}
static bool module_owns(const char *owner_key, const char *name) {
  if (!owner_key)
    return true;
  char key[32];
  global_module_key(name, key, sizeof(key));
  return !strcmp(owner_key, key);
}
static pthread_once_t llvm_targets_once = PTHREAD_ONCE_INIT;
static void initialize_llvm_targets(void) {
  LLVMInitializeWebAssemblyTargetInfo();
  LLVMInitializeWebAssemblyTarget();
  LLVMInitializeWebAssemblyTargetMC();
  LLVMInitializeWebAssemblyAsmPrinter();
  LLVMInitializeX86TargetInfo();
  LLVMInitializeX86Target();
  LLVMInitializeX86TargetMC();
  LLVMInitializeX86AsmPrinter();
  LLVMInitializeAArch64TargetInfo();
  LLVMInitializeAArch64Target();
  LLVMInitializeAArch64TargetMC();
  LLVMInitializeAArch64AsmPrinter();
}
int dyn_codegen_module(const DynSource *source, const char *object_path,
                       const char *ir_path, const char *asm_path, bool release,
                       bool debug_info, bool shared, const char *owner_key) {
  DynAstProgram ast = {0};
  if (!source)
    return 1;
  DynAnalysisResult analysis = dyn_analyze(
      source, &ast,
      (DynAnalysisOptions){.owner_key = owner_key,
                           .main_path = !owner_key || !strcmp(owner_key, "root")
                                            ? source->path
                                            : NULL,
                           .require_main = !shared});
  if (!analysis.checked) {
    dyn_ast_program_free(&ast);
    return 1;
  }
  struct timespec phase = dyn_timing_start(&source->context);
  DynIrProgram ir;
  if (!dyn_ir_lower(&ast, source, &ir)) {
    fprintf(stderr, "error: failed to lower typed Dyn IR\n");
    dyn_ast_program_free(&ast);
    return 2;
  }
  dyn_ast_program_free(&ast);
  if (!strcmp(dyn_context_target(&source->context)->arch, "wasm32")) {
    for (size_t i = 0; i < ir.function_count; ++i) {
      DynIrFunction *fn = &ir.functions[i];
      if ((fn->foreign && fn->variadic) || !strcmp(fn->name, "dyn_initialize")) {
        fprintf(stderr, "error: browser modules reserve dyn_initialize and do not support C variadic functions\n");
        dyn_ir_free(&ir); return 1;
      }
    }
  }
  dyn_timing_phase(&source->context, &phase, "ir");
  pthread_once(&llvm_targets_once, initialize_llvm_targets);
  Gen g = {0};
  int failed = 0;
  char *error = NULL;
  bool pass_message = false;
  LLVMTargetMachineRef tm = NULL;
  LLVMValueRef *init_functions = NULL;
  size_t object_length = strlen(object_path);
  bool thin_bitcode = release && object_length >= 3 &&
                      !strcmp(object_path + object_length - 3, ".bc");
  g.source = source;
  g.wasm = !strcmp(dyn_context_target(&source->context)->arch, "wasm32");
  g.pointer_bytes = dyn_target_pointer_bytes(dyn_context_target(&source->context));
  g.tracing = !release && !g.wasm;
  g.context = LLVMContextCreate();
  g.module = LLVMModuleCreateWithNameInContext("dyn_module", g.context);
  if (debug_info) {
    char directory[4096];
    if (!getcwd(directory, sizeof(directory)))
      strcpy(directory, ".");
    g.di_builder = LLVMCreateDIBuilder(g.module);
    g.di_file = LLVMDIBuilderCreateFile(g.di_builder, source->path,
                                        strlen(source->path), directory,
                                        strlen(directory));
    g.di_unit = LLVMDIBuilderCreateCompileUnit(g.di_builder, 0x8000, g.di_file,
                                               "dyn", 3, release, "", 0, 0, "",
                                               0, 1, 0, 0, 0, "", 0, "", 0);
    g.di_function_type =
        LLVMDIBuilderCreateSubroutineType(g.di_builder, g.di_file, NULL, 0, 0);
    LLVMTypeRef i32_type = LLVMInt32TypeInContext(g.context);
    LLVMAddModuleFlag(g.module, 1, "Debug Info Version", 18,
                      LLVMValueAsMetadata(LLVMConstInt(
                          i32_type, LLVMDebugMetadataVersion(), 0)));
    LLVMAddModuleFlag(g.module, 1, "Dwarf Version", 13,
                      LLVMValueAsMetadata(LLVMConstInt(i32_type, 5, 0)));
  }
  g.ir = &ir;
  if (g.di_builder) {
    g.di_struct_types = calloc(ir.struct_count, sizeof(*g.di_struct_types));
    g.di_enum_types = calloc(ir.enum_count, sizeof(*g.di_enum_types));
    g.di_array_types = calloc(ir.array_count, sizeof(*g.di_array_types));
    if ((ir.struct_count && !g.di_struct_types) ||
        (ir.enum_count && !g.di_enum_types) ||
        (ir.array_count && !g.di_array_types)) {
      goto allocation_failure;
    }
  }
  g.struct_types = calloc(ir.struct_count, sizeof(*g.struct_types));
  if (ir.struct_count && !g.struct_types)
    goto allocation_failure;
  for (uint32_t i = 0; i < ir.struct_count; ++i) {
    char name[64];
    snprintf(name, sizeof(name), "dyn.struct.%u", i);
    g.struct_types[i] = LLVMStructCreateNamed(g.context, name);
  }
  g.enum_types = calloc(ir.enum_count, sizeof(*g.enum_types));
  if (ir.enum_count && !g.enum_types)
    goto allocation_failure;
  for (uint32_t i = 0; i < ir.enum_count; ++i)
    if (ir.enums[i].has_payload) {
      char name[64];
      snprintf(name, sizeof(name), "dyn.enum.%u", i);
      g.enum_types[i] = LLVMStructCreateNamed(g.context, name);
    }
  for (uint32_t i = 0; i < ir.struct_count; ++i) {
    DynIrStruct *st = &ir.structs[i];
    uint32_t llvm_field_count = st->field_count ? st->field_count : 1;
    LLVMTypeRef *fields = calloc(llvm_field_count, sizeof(*fields));
    if (!fields)
      goto allocation_failure;
    if (!st->field_count)
      fields[0] = LLVMInt8TypeInContext(g.context);
    for (uint32_t j = 0; j < st->field_count; ++j)
      fields[j] = llvm_type(&g, ir.fields[st->field_start + j].type);
    LLVMStructSetBody(g.struct_types[i], fields, llvm_field_count, st->packed);
    free(fields);
  }
  for (uint32_t i = 0; i < ir.enum_count; ++i)
    if (ir.enums[i].has_payload) {
      DynIrEnum *en = &ir.enums[i];
      LLVMTypeRef unit = LLVMIntTypeInContext(
                      g.context, (unsigned)(en->payload_alignment * 8)),
                  fields[] = {llvm_type(&g, en->tag_type),
                              LLVMArrayType2(unit, (en->payload_size +
                                                    en->payload_alignment - 1) /
                                                       en->payload_alignment)};
      LLVMStructSetBody(g.enum_types[i], fields, 2, 0);
    }
  LLVMTypeRef i32 = LLVMInt32TypeInContext(g.context);
  g.functions = calloc(ir.function_count, sizeof(*g.functions));
  g.function_types = calloc(ir.function_count, sizeof(*g.function_types));
  g.abis = calloc(ir.function_count ? ir.function_count : 1, sizeof(*g.abis));
  g.pointer_abis = calloc(ir.fn_type_count ? ir.fn_type_count : 1, sizeof(*g.pointer_abis));
  if (!g.abis || !g.pointer_abis) goto allocation_failure;
  if (ir.function_count && (!g.functions || !g.function_types))
    goto allocation_failure;
  for (uint32_t i = 0; i < ir.function_count; ++i) {
    DynIrFunction *fn = &ir.functions[i];
    bool packed =
        fn->variadic && !fn->foreign && dyn_type_is_slice(fn->variadic_type);
    uint32_t llvm_param_count = fn->param_count + (packed ? 2 : 0);
    DynType *params = calloc(llvm_param_count ? llvm_param_count : 1, sizeof(*params));
    if (!params) goto allocation_failure;
    for (uint32_t j = 0; j < fn->param_count; ++j)
      params[j] = ir.params[fn->param_start + j].type;
    if (packed) { params[fn->param_count] = DYN_TYPE_RAWPTR; params[fn->param_count + 1] = DYN_TYPE_USIZE; }
    g.abis[i] = abi_plan(&g, fn->is_main ? DYN_TYPE_I32 : fn->return_type, params, llvm_param_count, fn->foreign && fn->variadic);
    free(params);
    if (!g.abis[i]) goto allocation_failure;
    g.function_types[i] = g.abis[i]->type;
    g.functions[i] = LLVMAddFunction(g.module,
                                     fn->foreign   ? fn->link_name
                                     : fn->is_main ? "main"
                                                   : fn->name,
                                     g.function_types[i]);
    abi_attributes(&g, g.functions[i], g.abis[i], false);
    if (g.wasm && fn->is_public && !fn->foreign && module_owns("root", fn->name))
      LLVMAddAttributeAtIndex(g.functions[i], ~0u,
        LLVMCreateStringAttribute(g.context, "wasm-export-name", 16, fn->name, (unsigned)strlen(fn->name)));
    if (g.wasm && fn->foreign)
      LLVMAddAttributeAtIndex(g.functions[i], ~0u,
        LLVMCreateStringAttribute(g.context, "wasm-import-module", 18, "env", 3));
    if (release && debug_info && !fn->foreign)
      LLVMAddAttributeAtIndex(
          g.functions[i], ~0u,
          LLVMCreateEnumAttribute(
              g.context, LLVMGetEnumAttributeKindForName("noinline", 8), 0));
    if (!owner_key && !fn->is_main && !fn->foreign &&
        ((release && !shared) || (shared && !fn->is_public)))
      LLVMSetLinkage(g.functions[i], LLVMInternalLinkage);
  }
  LLVMTypeRef panic_params[2] = {LLVMPointerTypeInContext(g.context, 0),
                                 llvm_type(&g, DYN_TYPE_USIZE)};
  g.panic_type =
      LLVMFunctionType(LLVMVoidTypeInContext(g.context), panic_params, 2, 0);
  g.panic_fn = LLVMAddFunction(g.module, "dyn_panic", g.panic_type);
  LLVMAddAttributeAtIndex(
      g.panic_fn, ~0u,
      LLVMCreateEnumAttribute(
          g.context, LLVMGetEnumAttributeKindForName("noreturn", 8), 0));
  g.trace_push_type =
      LLVMFunctionType(LLVMVoidTypeInContext(g.context), panic_params, 2, 0);
  g.trace_push_fn =
      LLVMAddFunction(g.module, "dyn_trace_push", g.trace_push_type);
  g.trace_pop_type =
      LLVMFunctionType(LLVMVoidTypeInContext(g.context), NULL, 0, 0);
  g.trace_pop_fn = LLVMAddFunction(g.module, "dyn_trace_pop", g.trace_pop_type);
  g.unwind_frame_type = LLVMArrayType2(LLVMInt64TypeInContext(g.context), 16);
  LLVMTypeRef unwind_pointer[] = {LLVMPointerTypeInContext(g.context, 0)};
  g.unwind_set_type = LLVMFunctionType(i32, unwind_pointer, 1, 0);
  g.unwind_set_fn =
      LLVMAddFunction(g.module, "dyn_unwind_set", g.unwind_set_type);
  LLVMAddAttributeAtIndex(
      g.unwind_set_fn, ~0u,
      LLVMCreateEnumAttribute(
          g.context, LLVMGetEnumAttributeKindForName("returns_twice", 13), 0));
  g.unwind_void_type =
      LLVMFunctionType(LLVMVoidTypeInContext(g.context), unwind_pointer, 1, 0);
  g.unwind_link_fn =
      LLVMAddFunction(g.module, "dyn_unwind_link", g.unwind_void_type);
  g.unwind_unlink_fn =
      LLVMAddFunction(g.module, "dyn_unwind_unlink", g.unwind_void_type);
  g.unwind_continue_type =
      LLVMFunctionType(LLVMVoidTypeInContext(g.context), NULL, 0, 0);
  g.unwind_continue_fn =
      LLVMAddFunction(g.module, "dyn_unwind_continue", g.unwind_continue_type);
  LLVMAddAttributeAtIndex(
      g.unwind_continue_fn, ~0u,
      LLVMCreateEnumAttribute(
          g.context, LLVMGetEnumAttributeKindForName("noreturn", 8), 0));
  LLVMTypeRef syscall_params[7];
  for (uint32_t i = 0; i < 7; ++i)
    syscall_params[i] = LLVMInt64TypeInContext(g.context);
  g.syscall_type =
      LLVMFunctionType(LLVMInt64TypeInContext(g.context), syscall_params, 7, 0);
  g.syscall_fn = LLVMAddFunction(g.module, "dyn_syscall6", g.syscall_type);
  LLVMTypeRef memset_params[] = {
      LLVMPointerTypeInContext(g.context, 0), LLVMInt8TypeInContext(g.context),
      LLVMInt64TypeInContext(g.context), LLVMInt1TypeInContext(g.context)};
  g.memset_type =
      LLVMFunctionType(LLVMVoidTypeInContext(g.context), memset_params, 4, 0);
  g.memset_fn = LLVMAddFunction(g.module, "llvm.memset.p0.i64", g.memset_type);
  g.builder = LLVMCreateBuilderInContext(g.context);
  g.stack_builder = LLVMCreateBuilderInContext(g.context);
  if ((g.di_builder || g.tracing) && !dyn_location_build(&g.locations, source))
    goto allocation_failure;
  g.locals = calloc(ir.local_count, sizeof(*g.locals));
  if (g.di_builder && ir.local_count) {
    g.local_statements = calloc(ir.local_count, sizeof(*g.local_statements));
    if (!g.local_statements) goto allocation_failure;
    for (size_t i = 0; i < ir.statement_count; ++i) {
      const DynIrStmt *st = &ir.statements[i];
      if (st->kind == DYN_STMT_LOCAL && !g.local_statements[st->local_id])
        g.local_statements[st->local_id] = (uint32_t)i + 1;
    }
  }
  g.captured_values = calloc(ir.expression_count, sizeof(*g.captured_values));
  g.defer_stack = calloc(ir.statement_count, sizeof(*g.defer_stack));
  g.globals = calloc(ir.global_count, sizeof(*g.globals));
  g.static_globals = calloc(ir.global_count, sizeof(*g.static_globals));
  if ((ir.local_count && !g.locals) ||
      (ir.expression_count && !g.captured_values) ||
      (ir.statement_count && !g.defer_stack) ||
      (ir.global_count && (!g.globals || !g.static_globals)))
    goto allocation_failure;
  for (uint32_t i = 0; i < ir.global_count; ++i) {
    g.globals[i] = LLVMAddGlobal(g.module, llvm_type(&g, ir.globals[i].type),
                                 ir.globals[i].foreign ? ir.globals[i].link_name
                                                       : ir.globals[i].name);
    bool owned =
        !ir.globals[i].foreign && module_owns(owner_key, ir.globals[i].name);
    if (owned)
      LLVMSetInitializer(g.globals[i],
                         LLVMConstNull(llvm_type(&g, ir.globals[i].type)));
    if (!owner_key && owned &&
        ((release && !shared) || (shared && !ir.globals[i].is_public)))
      LLVMSetLinkage(g.globals[i], LLVMInternalLinkage);
    if (g.di_builder && owned) {
      DynIrGlobal *global = &ir.globals[i];
      unsigned line = span_line(&g, global->span);
      LLVMMetadataRef type = debug_type(&g, global->type),
                      expression =
                          LLVMDIBuilderCreateExpression(g.di_builder, NULL, 0);
      if (type) {
        LLVMMetadataRef metadata = LLVMDIBuilderCreateGlobalVariableExpression(
            g.di_builder, g.di_unit, global->name, strlen(global->name),
            global->name, strlen(global->name),
            debug_source_file(&g, global->span), line, type, !global->is_public,
            expression, NULL, (uint32_t)(type_alignment(&g, global->type) * 8));
        LLVMGlobalSetMetadata(g.globals[i],
                              LLVMGetMDKindIDInContext(g.context, "dbg", 3),
                              metadata);
      }
    }
  }
  for (uint32_t i = 0; i < ir.global_count; ++i)
    if (ir.globals[i].is_const) {
      DynIrExpr *initializer = &ir.expressions[ir.globals[i].initializer];
      LLVMValueRef value = initializer->kind == DYN_EXPR_FUNCTION
                               ? g.functions[initializer->integer]
                               : static_value(&g, ir.globals[i].initializer, 0);
      if (value) {
        if (module_owns(owner_key, ir.globals[i].name)) {
          LLVMSetInitializer(g.globals[i], value);
          LLVMSetGlobalConstant(g.globals[i], 1);
        }
        g.static_globals[i] = true;
      }
    }
  g.init_type = LLVMFunctionType(LLVMVoidTypeInContext(g.context), NULL, 0, 0);
  init_functions = calloc(ir.global_count, sizeof(*init_functions));
  if (ir.global_count && !init_functions)
    goto allocation_failure;
  size_t init_function_count = 0;
  for (uint32_t at = 0; at < ir.global_init_count;) {
    while (at < ir.global_init_count &&
           g.static_globals[ir.global_init_order[at]])
      ++at;
    if (at >= ir.global_init_count)
      break;
    uint32_t first = ir.global_init_order[at];
    char key[32], function_name[64];
    global_module_key(ir.globals[first].name, key, sizeof(key));
    snprintf(function_name, sizeof(function_name), "__dyn_init_%s", key);
    bool owns_init = !owner_key || !strcmp(owner_key, key);
    LLVMValueRef init = LLVMAddFunction(g.module, function_name, g.init_type);
    if (release && !owner_key)
      LLVMSetLinkage(init, LLVMInternalLinkage);
    init_functions[init_function_count++] = init;
    if (!owns_init) {
      for (; at < ir.global_init_count; ++at) {
        uint32_t id = ir.global_init_order[at];
        if (g.static_globals[id])
          continue;
        char next[32];
        global_module_key(ir.globals[id].name, next, sizeof(next));
        if (strcmp(key, next))
          break;
      }
      continue;
    }
    g.function = init;
    g.return_type = DYN_TYPE_VOID;
    g.is_main = false;
    LLVMPositionBuilderAtEnd(
        g.builder, LLVMAppendBasicBlockInContext(g.context, init, "entry"));
    for (; at < ir.global_init_count; ++at) {
      uint32_t id = ir.global_init_order[at];
      if (g.static_globals[id])
        continue;
      char next[32];
      global_module_key(ir.globals[id].name, next, sizeof(next));
      if (strcmp(key, next))
        break;
      DynIrExpr *initializer = &ir.expressions[ir.globals[id].initializer];
      if (initializer->kind == DYN_EXPR_ARRAY) {
        LLVMTypeRef array_type = llvm_type(&g, initializer->type);
        for (uint32_t item = 0; item < initializer->item_count; ++item) {
          LLVMValueRef indices[] = {
              LLVMConstInt(LLVMInt64TypeInContext(g.context), 0, 0),
              LLVMConstInt(LLVMInt64TypeInContext(g.context), item, 0)};
          LLVMBuildStore(
              g.builder,
              gen_expr(&g, ir.items[initializer->item_start + item].expression),
              LLVMBuildGEP2(g.builder, array_type, g.globals[id], indices, 2,
                            "global.array.initializer.element"));
        }
      } else {
        LLVMBuildStore(g.builder, gen_expr(&g, ir.globals[id].initializer),
                       g.globals[id]);
      }
    }
    LLVMBuildRetVoid(g.builder);
  }
  if (g.wasm) {
    LLVMValueRef initialize = LLVMAddFunction(g.module, "dyn_initialize", g.init_type);
    g.init_fn = initialize;
    LLVMAddAttributeAtIndex(initialize, ~0u, LLVMCreateStringAttribute(
      g.context, "wasm-export-name", 16, "dyn_initialize", 14));
    g.function = initialize;
    LLVMPositionBuilderAtEnd(g.builder, LLVMAppendBasicBlockInContext(g.context, initialize, "entry"));
    LLVMValueRef initialized = LLVMAddGlobal(g.module, LLVMInt1TypeInContext(g.context), "__dyn_initialized");
    LLVMSetLinkage(initialized, LLVMInternalLinkage);
    LLVMSetInitializer(initialized, LLVMConstInt(LLVMInt1TypeInContext(g.context), 0, 0));
    LLVMBasicBlockRef run_init = LLVMAppendBasicBlockInContext(g.context, initialize, "initialize"),
                     done_init = LLVMAppendBasicBlockInContext(g.context, initialize, "done");
    LLVMBuildCondBr(g.builder, LLVMBuildLoad2(g.builder, LLVMInt1TypeInContext(g.context), initialized, "initialized"), done_init, run_init);
    LLVMPositionBuilderAtEnd(g.builder, run_init);
    LLVMBuildStore(g.builder, LLVMConstInt(LLVMInt1TypeInContext(g.context), 1, 0), initialized);
    for (size_t q = 0; q < init_function_count; ++q)
      LLVMBuildCall2(g.builder, g.init_type, init_functions[q], NULL, 0, "");
    LLVMBuildBr(g.builder, done_init);
    LLVMPositionBuilderAtEnd(g.builder, done_init);
    LLVMBuildRetVoid(g.builder);
  }
  bool has_init = init_function_count != 0;
  for (uint32_t i = 0; i < ir.function_count; ++i) {
    DynIrFunction *fn = &ir.functions[i];
    if (fn->foreign || !module_owns(owner_key, fn->name))
      continue;
    g.function = g.functions[i];
    g.return_type = fn->return_type;
    g.current_abi = g.abis[i];
    g.is_main = fn->is_main;
    g.variadic_data = g.variadic_count = NULL;
    g.break_target = NULL;
    g.continue_target = NULL;
    LLVMPositionBuilderAtEnd(g.builder, LLVMAppendBasicBlockInContext(
                                            g.context, g.function, "entry"));
    LLVMSetCurrentDebugLocation2(g.builder, NULL);
    if (g.di_builder)
      LLVMSetCurrentDebugLocation2(g.builder, NULL);
    /* Allocate an entry-block frame lazily, only for protected calls. Calls
       cannot overlap, and loop iterations must reuse the same stack slot. */
    g.unwind_frame = NULL;
    if (g.di_builder) {
      const char *debug_path;
      unsigned debug_line, debug_column;
      dyn_location_get(&g.locations, source, fn->source_offset, &debug_path, &debug_line,
                          &debug_column);
      g.di_file = LLVMDIBuilderCreateFile(g.di_builder, debug_path,
                                          strlen(debug_path), "", 0);
      LLVMMetadataRef subprogram = LLVMDIBuilderCreateFunction(
          g.di_builder, g.di_file, fn->name, strlen(fn->name), fn->name,
          strlen(fn->name), g.di_file, fn->source_line, g.di_function_type,
          owner_key != NULL, 1, fn->source_line, 0, release);
      LLVMSetSubprogram(g.function, subprogram);
      g.di_scope = subprogram;
      LLVMSetCurrentDebugLocation2(
          g.builder, LLVMDIBuilderCreateDebugLocation(
                         g.context, fn->source_line, 1, subprogram, NULL));
    }
    if (g.tracing) {
      char label[4096];
      const char *trace_path;
      unsigned trace_line, trace_column;
      dyn_location_get(&g.locations, source, fn->source_offset, &trace_path, &trace_line,
                          &trace_column);
      snprintf(label, sizeof(label), "%s (%s:%u)", fn->name, trace_path,
               trace_line);
      LLVMValueRef trace_name =
          LLVMBuildGlobalStringPtr(g.builder, label, ".dyn.trace.name");
      LLVMValueRef trace_arguments[2] = {
          trace_name,
          LLVMConstInt(LLVMInt64TypeInContext(g.context), strlen(label), 0)};
      LLVMBuildCall2(g.builder, g.trace_push_type, g.trace_push_fn,
                     trace_arguments, 2, "");
    }
    if (fn->is_main && g.wasm)
      LLVMBuildCall2(g.builder, g.init_type, g.init_fn, NULL, 0, "");
    else if (fn->is_main && has_init)
      for (size_t q = 0; q < init_function_count; ++q)
        LLVMBuildCall2(g.builder, g.init_type, init_functions[q], NULL, 0, "");
    for (uint32_t j = 0; j < fn->local_count; ++j) {
      uint32_t local = fn->local_start + j;
      g.locals[local] = gen_stack_slot(
          &g, llvm_type(&g, ir.locals[local].type), "local");
    }
    for (uint32_t j = 0; j < fn->param_count; ++j) {
      DynIrParam *p = &ir.params[fn->param_start + j];
      LLVMMetadataRef variable = debug_declare(
          &g, g.locals[p->local_id], p->name, p->type, fn->source_line, j + 1);
      const AbiValue *parameter = &g.current_abi->params[j];
      LLVMValueRef parts[2] = {0};
      for (unsigned k = 0; k < parameter->count; ++k) parts[k] = LLVMGetParam(g.function, parameter->index + k);
      LLVMValueRef value = abi_decode(&g, parameter, parts);
      debug_value(&g, value, variable, fn->source_line);
      LLVMBuildStore(g.builder, value, g.locals[p->local_id]);
    }
    for (uint32_t j = 0; g.di_builder && j < fn->local_count; ++j) {
      uint32_t local = fn->local_start + j;
      bool parameter = false;
      for (uint32_t q = 0; q < fn->param_count; ++q)
        if (ir.params[fn->param_start + q].local_id == local)
          parameter = true;
      if (!parameter && (!fn->variadic || local != fn->variadic_local_id))
        debug_declare(&g, g.locals[local], ir.locals[local].name,
                      ir.locals[local].type,
                      local_line(&g, local, fn->source_line), 0);
    }
    if (fn->variadic && !fn->foreign && dyn_type_is_slice(fn->variadic_type)) {
      g.variadic_data = LLVMGetParam(g.function, g.current_abi->params[fn->param_count].index);
      g.variadic_count = LLVMGetParam(g.function, g.current_abi->params[fn->param_count + 1].index);
      LLVMValueRef pack = LLVMConstNull(llvm_type(&g, fn->variadic_type));
      pack = LLVMBuildInsertValue(g.builder, pack, g.variadic_data, 0,
                                  "variadic.data");
      pack = LLVMBuildInsertValue(g.builder, pack, g.variadic_count, 1,
                                  "variadic.count");
      LLVMBuildStore(g.builder, pack, g.locals[fn->variadic_local_id]);
    }
    bool terminated = gen_block(&g, fn->body_start, fn->body_count);
    if (!terminated) {
      emit_trace_pop(&g);
      if (fn->is_main)
        LLVMBuildRet(g.builder, LLVMConstInt(i32, 0, 0));
      else
        LLVMBuildRetVoid(g.builder);
    }
  }
  const char *triple = dyn_context_target(&source->context)->triple;
  if (g.di_builder)
    LLVMDIBuilderFinalize(g.di_builder);
  LLVMSetTarget(g.module, triple);
  if (g.allocation_failed)
    goto allocation_failure;
  if (dyn_verify_module(g.module, 2, &error)) {
    fprintf(stderr, "error: invalid LLVM module: %s\n", error ? error : "");
    failed = 1;
    if (error) {
      LLVMDisposeMessage(error);
      error = NULL;
    }
  }
  LLVMTargetRef target = NULL;
  if (!failed && LLVMGetTargetFromTriple(triple, &target, &error))
    failed = 1;
  if (!failed)
    tm = LLVMCreateTargetMachine(target, triple, "generic", "", release ? 2 : 0,
                                 shared && !g.wasm ? 2 : 0, 0);
  if (!failed && !tm)
    failed = 1;
  if (!failed) {
    LLVMTargetDataRef layout = LLVMCreateTargetDataLayout(tm);
    char *layout_text = LLVMCopyStringRepOfTargetData(layout);
    LLVMSetDataLayout(g.module, layout_text);
    LLVMDisposeMessage(layout_text);
    LLVMDisposeTargetData(layout);
  }
  dyn_timing_phase(&source->context, &phase, "llvm");
  if (!failed && release) {
    LLVMPassBuilderOptionsRef options = LLVMCreatePassBuilderOptions();
    LLVMErrorRef pass_error = LLVMRunPasses(
        g.module, thin_bitcode ? "thinlto-pre-link<O2>" : "default<O2>", tm,
        options);
    LLVMDisposePassBuilderOptions(options);
    if (pass_error) {
      error = LLVMGetErrorMessage(pass_error);
      pass_message = true;
      failed = 1;
    }
  }
  dyn_timing_phase(&source->context, &phase, "optimize");
  if (!failed && dyn_verify_module(g.module, 2, &error)) {
    fprintf(stderr, "error: optimized LLVM module is invalid: %s\n",
            error ? error : "");
    failed = 1;
  }
  if (!failed && ir_path) {
    char *llvm_ir = LLVMPrintModuleToString(g.module);
    failed = write_text(ir_path, llvm_ir);
    LLVMDisposeMessage(llvm_ir);
  }
  if (!failed && asm_path)
    failed =
        LLVMTargetMachineEmitToFile(tm, g.module, (char *)asm_path, 0, &error);
  if (!failed)
    failed = thin_bitcode ? LLVMWriteBitcodeToFile(g.module, object_path)
                          : LLVMTargetMachineEmitToFile(
                                tm, g.module, (char *)object_path, 1, &error);
  if (!failed && g.wasm) {
    const char *wasi_imports = !strcmp(dyn_context_target(&source->context)->kernel, "wasi")
      ? "wasi_proc_exit\nwasi_fd_write\nwasi_fd_read\nwasi_fd_close\nwasi_args_sizes_get\nwasi_args_get\nwasi_path_open\nwasi_random_get\nwasi_clock_time_get\n" : "";
    size_t capacity = strlen(wasi_imports) + 1;
    for (size_t i = 0; i < ir.function_count; ++i)
      if (ir.functions[i].foreign) capacity += strlen(ir.functions[i].link_name) + 1;
    char *imports = calloc(capacity, 1), *path = malloc(strlen(object_path) + 9);
    if (!imports || !path) { free(imports); free(path); goto allocation_failure; }
    strcpy(imports, wasi_imports);
    size_t at = strlen(wasi_imports);
    for (size_t i = 0; i < ir.function_count; ++i)
      if (ir.functions[i].foreign) at += (size_t)sprintf(imports + at, "%s\n", ir.functions[i].link_name);
    sprintf(path, "%s.imports", object_path);
    failed = write_text(path, imports);
    free(imports); free(path);
  }
  dyn_timing_phase(&source->context, &phase, "emit");
  if (failed)
    fprintf(stderr, "error: LLVM emission failed%s%s\n", error ? ": " : "",
            error ? error : "");
  if (error) {
    if (pass_message)
      LLVMDisposeErrorMessage(error);
    else
      LLVMDisposeMessage(error);
  }
  if (tm)
    LLVMDisposeTargetMachine(tm);
  goto cleanup;
allocation_failure:
  dyn_diagnostic_source("error", source, 0, 0, "out of memory generating code");
  failed = 2;
cleanup:
  free(init_functions);
  free(g.locals);
  free(g.local_statements);
  dyn_location_free(&g.locations);
  free(g.captured_values);
  free(g.defer_stack);
  free(g.globals);
  free(g.static_globals);
  free(g.functions);
  free(g.function_types);
  if (g.abis) for (size_t i = 0; i < ir.function_count; ++i) abi_free(g.abis[i]);
  if (g.pointer_abis) for (size_t i = 0; i < ir.fn_type_count; ++i) abi_free(g.pointer_abis[i]);
  free(g.abis); free(g.pointer_abis);
  free(g.struct_types);
  free(g.enum_types);
  free(g.di_struct_types);
  free(g.di_enum_types);
  free(g.di_array_types);

  if (g.di_builder)
    LLVMDisposeDIBuilder(g.di_builder);
  if (g.builder)
    LLVMDisposeBuilder(g.builder);
  if (g.stack_builder)
    LLVMDisposeBuilder(g.stack_builder);
  LLVMDisposeModule(g.module);
  LLVMContextDispose(g.context);
  dyn_ir_free(&ir);
  return failed;
}
int dyn_codegen_main(const DynSource *source, const char *object_path,
                     const char *ir_path, const char *asm_path, bool release,
                     bool debug_info, bool shared) {
  return dyn_codegen_module(source, object_path, ir_path, asm_path, release,
                            debug_info, shared, NULL);
}
static int link_wasm(const DynContext *, const char *, const char *,
                     const char *const *, size_t, bool);
int dyn_link_executable_objects(const DynContext *context,
                                const char *const *object_paths,
                                size_t object_count, const char *output_path,
                                const char *const *link_inputs,
                                size_t link_input_count, bool release,
                                bool verbose) {
  char temporary[4096], runtime[4096], support[4096], executable[4096];
  bool dynamic = false;
  for (size_t i = 0; i < link_input_count; ++i) {
    const char *extension = strstr(link_inputs[i], ".so");
    if (extension && (extension[3] == 0 || extension[3] == '.'))
      dynamic = true;
  }
  if (snprintf(temporary, sizeof(temporary), "%s.tmp", output_path) >=
      (int)sizeof(temporary))
    return 2;
  ssize_t n = dyn_host_executable(executable, sizeof(executable) - 1);
  if (n < 0) {
    perror("error: locate compiler");
    return 2;
  }
  executable[n] = 0;
  char *slash = strrchr(executable, '/');
  if (!slash)
    return 2;
  *slash = 0;
  const char *runtime_name =
      !strcmp(dyn_context_target(context)->kernel, "windows")
          ? "dynrt_windows_start.o"
      : !strcmp(dyn_context_target(context)->kernel, "darwin")
          ? "dynrt_macos_start.o"
      : !strcmp(dyn_context_target(context)->arch, "aarch64")
          ? (release ? "dynrt_aarch64_release.o" : "dynrt_aarch64_start.o")
          : (release ? "dynrt_release.o" : "dynrt_start.o");
  if (snprintf(runtime, sizeof(runtime), "%s/%s", executable, runtime_name) >=
      (int)sizeof(runtime))
    return 2;
  if (access(runtime, R_OK) &&
      snprintf(runtime, sizeof(runtime), "%s/../lib/dyn/%s", executable,
               runtime_name) >= (int)sizeof(runtime))
    return 2;
  const char *support_name =
      !strcmp(dyn_context_target(context)->kernel, "windows")
          ? "dynrt_windows_support.o"
      : !strcmp(dyn_context_target(context)->kernel, "darwin")
          ? "dynrt_macos_support.o"
      : !strcmp(dyn_context_target(context)->arch, "aarch64")
          ? "dynrt_aarch64_support.o"
          : "dynrt_support.o";
  if (snprintf(support, sizeof(support), "%s/%s", executable, support_name) >=
      (int)sizeof(support))
    return 2;
  if (access(support, R_OK) &&
      snprintf(support, sizeof(support), "%s/../lib/dyn/%s", executable,
               support_name) >= (int)sizeof(support))
    return 2;
  bool windows = !strcmp(dyn_context_target(context)->kernel, "windows");
  bool darwin = !strcmp(dyn_context_target(context)->kernel, "darwin");
  bool thin = release && object_count && strstr(object_paths[0], ".bc");
  const char *linker = darwin ? DYN_DARWIN_LINKER : windows ? DYN_WINDOWS_LINKER : "ld.lld";
  if (verbose) {
    fprintf(
        stderr, "+ %s %s -o %s %s %s", linker,
        darwin ?
#ifdef __APPLE__
          "-arch arm64 -platform_version macos 15.0 15.0 -e _dyn_start"
#else
          "cc --target=aarch64-macos-none -nostdlib -Wl,-e,_dyn_start"
#endif
        : windows
            ? "-mi386pep --gc-sections --entry=dyn_start --subsystem console"
            : "--gc-sections",
        temporary, runtime, support);
    for (size_t i = 0; i < object_count; ++i)
      fprintf(stderr, " %s", object_paths[i]);
    if (dynamic && !darwin && !windows)
      fprintf(stderr, " --dynamic-linker %s",
              dyn_context_target(context)->dynamic_linker);
    for (size_t i = 0; i < link_input_count; ++i)
      fprintf(stderr, " %s", link_inputs[i]);
    fputc('\n', stderr);
  }
  char **arguments =
      calloc(object_count + link_input_count + 18, sizeof(*arguments));
  if (!arguments)
    return 2;
  size_t argument_count = 0;
  arguments[argument_count++] = (char *)linker;
  if (darwin) {
#ifdef __APPLE__
    arguments[argument_count++] = "-arch"; arguments[argument_count++] = "arm64";
    arguments[argument_count++] = "-platform_version";
    arguments[argument_count++] = "macos";
    arguments[argument_count++] = "15.0"; arguments[argument_count++] = "15.0";
    arguments[argument_count++] = "-e"; arguments[argument_count++] = "_dyn_start";
#else
    arguments[argument_count++] = "cc";
    arguments[argument_count++] = "--target=aarch64-macos-none";
    arguments[argument_count++] = "-nostdlib";
    arguments[argument_count++] = "-Wl,-e,_dyn_start";
#endif
  } else if (windows) {
    arguments[argument_count++] = "-mi386pep";
    arguments[argument_count++] = "--gc-sections";
    arguments[argument_count++] = "--entry=dyn_start";
    arguments[argument_count++] = "--subsystem";
    arguments[argument_count++] = "console";
  } else {
    arguments[argument_count++] = "--gc-sections";
    if (thin)
      arguments[argument_count++] = "--lto-O2";
  }
  arguments[argument_count++] = "-o";
  arguments[argument_count++] = temporary;
  arguments[argument_count++] = runtime;
  arguments[argument_count++] = support;
  for (size_t i = 0; i < object_count; ++i)
    arguments[argument_count++] = (char *)object_paths[i];
  if (dynamic && !darwin && !windows) {
    arguments[argument_count++] = "--dynamic-linker";
    arguments[argument_count++] =
        (char *)dyn_context_target(context)->dynamic_linker;
  }
  for (size_t i = 0; i < link_input_count; ++i)
    arguments[argument_count++] = (char *)link_inputs[i];
  int status;
  status = dyn_host_spawn(arguments);
  if (status == 127 && thin) {
    for (size_t i = argument_count; i > 0; --i)
      arguments[i + 1] = arguments[i];
    arguments[0] = "zig";
    arguments[1] = "ld.lld";
    status = dyn_host_spawn(arguments);
  }
  if (status == 127 && !strcmp(dyn_context_target(context)->name, "aarch64-linux")) {
    for (size_t i = argument_count; i > 0; --i)
      arguments[i + 1] = arguments[i];
    arguments[0] = "zig";
    arguments[1] = "ld.lld";
    status = dyn_host_spawn(arguments);
  }
  if (status == 127 && !strcmp(dyn_context_target(context)->name, "x86_64-linux")) {
    arguments[0] = "ld";
    status = dyn_host_spawn(arguments);
  }
  free(arguments);
  if (status != 0) {
    if (status == 127)
      fprintf(stderr, "error: target '%s' requires %s in PATH\n",
              dyn_context_target(context)->name, linker);
    else
      fprintf(stderr, "error: linker failed\n");
    return 2;
  }
  if (rename(temporary, output_path)) {
    perror("error: rename output");
    return 2;
  }
  return 0;
}
int dyn_link_executable(const DynContext *context, const char *object_path,
                        const char *output_path, const char *const *link_inputs,
                        size_t link_input_count, bool release, bool verbose) {
  if (!strcmp(dyn_context_target(context)->arch, "wasm32"))
    return link_wasm(context, object_path, output_path, link_inputs, link_input_count, verbose);

  return dyn_link_executable_objects(context, &object_path, 1, output_path,
                                     link_inputs, link_input_count, release,
                                     verbose);
}
/* Browser modules use a static Wasm link, not a native dynamic library. */
static int link_wasm(const DynContext *context, const char *object_path, const char *output_path,
                        const char *const *inputs, size_t count, bool verbose) {
  char executable[4096], support[4096], temporary[4096], imports[8192];
  char wasi_support[4096], wasi_start[4096];
  bool wasi = !strcmp(dyn_context_target(context)->kernel, "wasi");
  if (snprintf(imports, sizeof(imports), "--allow-undefined-file=%s.imports", object_path) >= (int)sizeof(imports)) return 2;
  ssize_t n = dyn_host_executable(executable, sizeof(executable) - 1);
  if (n < 0 || (size_t)n >= sizeof(executable) - 1) return 2;
  executable[n] = 0;
  char *slash = strrchr(executable, '/');
  if (!slash) return 2;
  *slash = 0;
  if (snprintf(support, sizeof(support), "%s/dynrt_wasm.o", executable) >= (int)sizeof(support)) return 2;
  if (access(support, R_OK) && snprintf(support, sizeof(support), "%s/../lib/dyn/dynrt_wasm.o", executable) >= (int)sizeof(support)) return 2;
  if (wasi) {
    char *end = strrchr(support, '/');
    if (!end) return 2;
    size_t length = (size_t)(end - support);
    if (snprintf(wasi_support, sizeof(wasi_support), "%.*s/dynrt_wasi_support.o", (int)length, support) >= (int)sizeof(wasi_support) ||
        snprintf(wasi_start, sizeof(wasi_start), "%.*s/dynrt_wasi_start.o", (int)length, support) >= (int)sizeof(wasi_start)) return 2;
  }
  if (snprintf(temporary, sizeof(temporary), "%s.tmp", output_path) >= (int)sizeof(temporary)) return 2;
  if (verbose) fprintf(stderr, "+ wasm-ld --no-entry --export-memory -o %s %s %s\n", temporary, support, object_path);
  char **args = calloc(count + 16, sizeof(*args));
  if (!args) return 2;
  size_t at = 0;
  args[at++] = "wasm-ld";
  args[at++] = "--no-entry";
  args[at++] = imports;
  args[at++] = "--export-memory";
  args[at++] = "-z"; args[at++] = "stack-size=1048576";
  args[at++] = "-o"; args[at++] = temporary;
  args[at++] = support; args[at++] = (char *)object_path;
  if (wasi) { args[at++] = wasi_support; args[at++] = wasi_start; }
  for (size_t i = 0; i < count; ++i) args[at++] = (char *)inputs[i];
  int status;
  status = dyn_host_spawn(args);
  free(args);
  if (status != 0) {
    fprintf(stderr, "error: Wasm link failed (wasm-ld required in PATH)\n");
    remove(temporary); return 2;
  }
  if (rename(temporary, output_path)) { remove(temporary); return 2; }
  return 0;
}
int dyn_link_shared(const DynContext *context, const char *object_path,
                    const char *output_path, const char *const *link_inputs,
                    size_t link_input_count, bool verbose) {
  if (!strcmp(dyn_context_target(context)->arch, "wasm32"))
    return link_wasm(context, object_path, output_path, link_inputs, link_input_count, verbose);
  char temporary[4096], support[4096], assembly[4096], executable[4096];
  char import_temporary[4096] = {0}, import_output[4096] = {0};
  if (snprintf(temporary, sizeof(temporary), "%s.tmp", output_path) >=
      (int)sizeof(temporary))
    return 2;
  ssize_t n = dyn_host_executable(executable, sizeof(executable) - 1);
  if (n < 0) {
    perror("error: locate compiler");
    return 2;
  }
  executable[n] = 0;
  char *slash = strrchr(executable, '/');
  if (!slash)
    return 2;
  *slash = 0;
  bool windows = !strcmp(dyn_context_target(context)->kernel, "windows");
  bool darwin = !strcmp(dyn_context_target(context)->kernel, "darwin");
  const char *link_output = windows ? output_path : temporary;
  if (windows && (snprintf(import_output, sizeof(import_output), "%s.a",
                           output_path) >= (int)sizeof(import_output) ||
                  snprintf(import_temporary, sizeof(import_temporary), "%s.tmp",
                           import_output) >= (int)sizeof(import_temporary)))
    return 2;
  const char *name = windows  ? "dynrt_windows_support.o"
                     : darwin ? "dynrt_macos_support.o"
                     : !strcmp(dyn_context_target(context)->arch, "aarch64")
                         ? "dynrt_aarch64_support_pic.o"
                         : "dynrt_support_pic.o";
  if (snprintf(support, sizeof(support), "%s/%s", executable, name) >=
      (int)sizeof(support))
    return 2;
  if (access(support, R_OK) &&
      snprintf(support, sizeof(support), "%s/../lib/dyn/%s", executable,
               name) >= (int)sizeof(support))
    return 2;
  const char *assembly_name =
      windows  ? "dynrt_windows_shared.o"
      : darwin ? "dynrt_macos_shared.o"
      : !strcmp(dyn_context_target(context)->arch, "aarch64")
          ? "dynrt_aarch64_shared.o"
          : "dynrt_shared.o";
  if (snprintf(assembly, sizeof(assembly), "%s/%s", executable,
               assembly_name) >= (int)sizeof(assembly))
    return 2;
  if (access(assembly, R_OK) &&
      snprintf(assembly, sizeof(assembly), "%s/../lib/dyn/%s", executable,
               assembly_name) >= (int)sizeof(assembly))
    return 2;
  if (verbose) {
    fprintf(stderr, "+ %s -o %s %s %s %s",
            darwin ?
#ifdef __APPLE__
                "ld64.lld -arch arm64 -platform_version macos 15.0 15.0 -dylib"
#else
                "zig cc --target=aarch64-macos-none -dynamiclib -nostdlib"
#endif
            : windows ? DYN_WINDOWS_LINKER " -mi386pep -shared"
                      : "ld.lld -shared",
            temporary, assembly, support, object_path);
    for (size_t i = 0; i < link_input_count; ++i)
      fprintf(stderr, " %s", link_inputs[i]);
    fputc('\n', stderr);
  }
  char **arguments = calloc(link_input_count + 18, sizeof(*arguments));
  if (!arguments)
    return 2;
  size_t count = 0;
  arguments[count++] = darwin ? DYN_DARWIN_LINKER : windows ? DYN_WINDOWS_LINKER : "ld.lld";
  if (darwin) {
#ifdef __APPLE__
    arguments[count++] = "-arch"; arguments[count++] = "arm64";
    arguments[count++] = "-platform_version"; arguments[count++] = "macos";
    arguments[count++] = "15.0"; arguments[count++] = "15.0";
    arguments[count++] = "-dylib";
#else
    arguments[count++] = "cc";
    arguments[count++] = "--target=aarch64-macos-none";
    arguments[count++] = "-dynamiclib";
    arguments[count++] = "-nostdlib";
#endif
  } else {
    if (windows)
      arguments[count++] = "-mi386pep";
    arguments[count++] = "-shared";
    arguments[count++] = "--gc-sections";
    if (windows) {
      arguments[count++] = "--export-all-symbols";
      arguments[count++] = "--out-implib";
      arguments[count++] = import_temporary;
    }
  }
  arguments[count++] = "-o";
  arguments[count++] = (char *)link_output;
  arguments[count++] = assembly;
  arguments[count++] = support;
  arguments[count++] = (char *)object_path;
  for (size_t i = 0; i < link_input_count; ++i)
    arguments[count++] = (char *)link_inputs[i];
  int status;
  status = dyn_host_spawn(arguments);
  if (status == 127 && !windows && !darwin &&
      !strcmp(dyn_context_target(context)->name, "aarch64-linux")) {
    for (size_t i = count; i > 0; --i)
      arguments[i + 1] = arguments[i];
    arguments[0] = "zig";
    arguments[1] = "ld.lld";
    status = dyn_host_spawn(arguments);
  }
  if (status == 127 && !windows && !darwin &&
      !strcmp(dyn_context_target(context)->name, "x86_64-linux")) {
    arguments[0] = "ld";
    status = dyn_host_spawn(arguments);
  }
  free(arguments);
  if (status != 0) {
    if (status == 127)
      fprintf(stderr, "error: target '%s' requires %s in PATH\n",
              dyn_context_target(context)->name,
              darwin    ? DYN_DARWIN_LINKER
              : windows ? DYN_WINDOWS_LINKER
                        : "ld.lld");
    else
      fprintf(stderr, "error: linker failed\n");
    remove(link_output);
    return 2;
  }
  if (!windows && rename(temporary, output_path)) {
    perror("error: rename output");
    remove(temporary);
    return 2;
  }
  if (windows && rename(import_temporary, import_output)) {
    perror("error: rename import library");
    return 2;
  }
  return 0;
}
