#include "../src/llvm_shim.h"
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
  unsigned char *data;
  size_t length;
  unsigned char kind;
} DynDirectoryEntry;

static int dyn_directory_entry_compare(const void *left, const void *right) {
  const DynDirectoryEntry *a = left;
  const DynDirectoryEntry *b = right;
  size_t common = a->length < b->length ? a->length : b->length;
  int order = common ? memcmp(a->data, b->data, common) : 0;
  if (order) return order;
  return (a->length > b->length) - (a->length < b->length);
}

__attribute__((weak)) void dyn_sort_directory_entries(void *entries, size_t count) {
  if (entries && count > 1)
    qsort(entries, count, sizeof(DynDirectoryEntry), dyn_directory_entry_compare);
}

typedef struct { uint32_t source_id, start, end; } DynSourceSpan;
typedef struct { const unsigned char *data; size_t length; } DynByteSlice;
typedef struct { DynByteSlice path, text; } DynSourceItem;
typedef struct { DynSourceItem *items; size_t capacity, count; } DynSourceTable;

void dyn_debug_counts(size_t syntax_count, size_t function_count,
                      size_t instruction_count) {
  fprintf(stderr, "[DEBUG-counts] syntax=%zu functions=%zu instructions=%zu\n",
          syntax_count, function_count, instruction_count);
}

void dyn_debug_lower(size_t declaration_count, uint32_t declaration_kind,
                     uint32_t declaration_node) {
  fprintf(stderr, "[DEBUG-lower] declarations=%zu kind=%u node=%u\n",
          declaration_count, declaration_kind, declaration_node);
}

static DynByteSlice dyn_span_bytes(const DynSourceTable *table,
                                   const DynSourceSpan *span) {
  DynByteSlice empty = {0};
  if (!table || !span || span->source_id >= table->count) return empty;
  DynByteSlice text = table->items[span->source_id].text;
  if (span->end < span->start || span->end > text.length) return empty;
  return (DynByteSlice){text.data + span->start, span->end - span->start};
}

static int dyn_bytes_equal(const unsigned char *left,
                           const unsigned char *right, size_t length) {
  for (size_t i = 0; i < length; ++i)
    if (left[i] != right[i]) return 0;
  return 1;
}

int dyn_source_spans_equal(const void *raw_table, const void *raw_left,
                           const void *raw_right) {
  DynByteSlice left = dyn_span_bytes(raw_table, raw_left);
  DynByteSlice right = dyn_span_bytes(raw_table, raw_right);
  return left.length == right.length &&
         dyn_bytes_equal(left.data, right.data, left.length);
}

int dyn_source_path_namespace_equal(const void *raw_table,
                                    const void *raw_path,
                                    const void *raw_name) {
  DynByteSlice path = dyn_span_bytes(raw_table, raw_path);
  DynByteSlice name = dyn_span_bytes(raw_table, raw_name);
  if (path.length < 2) return 0;
  size_t start = 1, end = path.length - 1;
  for (size_t i = 1; i < end; ++i) if (path.data[i] == '/') start = i + 1;
  return end - start == name.length &&
         dyn_bytes_equal(path.data + start, name.data, name.length);
}

typedef struct {
  DynSourceSpan location, namespace_span;
  unsigned char namespace_is_path;
  unsigned char padding[3];
  uint32_t from, target;
} DynImport;
typedef struct {
  void *modules; size_t module_capacity, module_count;
  DynImport *imports; size_t import_capacity, import_count;
  void *source_modules; size_t source_module_count;
  void *states; size_t state_count;
} DynModuleGraph;

uint32_t dyn_imported_module(const void *raw_graph, const void *raw_table,
                             uint32_t from, const void *raw_name) {
  const DynModuleGraph *graph = raw_graph;
  if (!graph || !raw_name) return UINT32_MAX;
  for (size_t i = 0; i < graph->import_count; ++i) {
    const DynImport *edge = &graph->imports[i];
    if (edge->from != from) continue;
    int equal = edge->namespace_is_path
                    ? dyn_source_path_namespace_equal(raw_table,
                                                       &edge->namespace_span,
                                                       raw_name)
                    : dyn_source_spans_equal(raw_table, &edge->namespace_span,
                                             raw_name);
    if (equal) return edge->target;
  }
  return UINT32_MAX;
}

void dyn_symbol_reference_set(void *raw_reference, const void *raw_name,
                              uint32_t node, uint32_t symbol,
                              uint32_t local) {
  uint32_t *reference = raw_reference;
  const uint32_t *name = raw_name;
  reference[0] = name[0];
  reference[1] = name[1];
  reference[2] = name[2];
  reference[3] = node;
  reference[4] = symbol;
  reference[5] = local;
}

LLVMTypeRef dyn_llvm_slice_type(LLVMContextRef context) {
  LLVMTypeRef fields[2] = {LLVMPointerTypeInContext(context, 0),
                           LLVMInt64TypeInContext(context)};
  return LLVMStructTypeInContext(context, fields, 2, 0);
}

LLVMTypeRef dyn_llvm_arena_type(LLVMContextRef context) {
  LLVMTypeRef fields[3] = {dyn_llvm_slice_type(context),
                           LLVMInt64TypeInContext(context),
                           LLVMInt1TypeInContext(context)};
  return LLVMStructTypeInContext(context, fields, 3, 0);
}

LLVMTypeRef dyn_llvm_directory_entry_type(LLVMContextRef context) {
  LLVMTypeRef fields[2] = {dyn_llvm_slice_type(context),
                           LLVMInt8TypeInContext(context)};
  return LLVMStructTypeInContext(context, fields, 2, 0);
}

LLVMTypeRef dyn_llvm_struct_type(LLVMContextRef context, LLVMTypeRef *fields,
                                 unsigned field_count, unsigned packed) {
  if (!fields && field_count)
    return NULL;
  for (unsigned i = 0; i < field_count; ++i)
    if (!fields[i]) {
      fprintf(stderr, "Dyn LLVM struct field %u has no type\n", i);
      return NULL;
    }
  return LLVMStructTypeInContext(context, fields, field_count, packed != 0);
}

LLVMModuleRef dyn_llvm_module_create_probe(LLVMContextRef context) {
  return LLVMModuleCreateWithNameInContext("dyn.selfhost", context);
}

LLVMValueRef dyn_llvm_add_probe(LLVMModuleRef module, LLVMTypeRef type) {
  return LLVMAddFunction(module, "dyn_probe", type);
}

LLVMBasicBlockRef dyn_llvm_append_entry(LLVMContextRef context,
                                        LLVMValueRef function) {
  return LLVMAppendBasicBlockInContext(context, function, "entry");
}

LLVMValueRef dyn_llvm_add_indexed_function(LLVMModuleRef module,
                                           LLVMTypeRef type, unsigned index,
                                           unsigned is_main) {
  char name[32];
  if (is_main) {
    snprintf(name, sizeof(name), "main");
  } else {
    snprintf(name, sizeof(name), "dyn_fn_%u", index);
  }
  return LLVMAddFunction(module, name, type);
}

LLVMValueRef dyn_llvm_add_named_function(LLVMModuleRef module, LLVMTypeRef type,
                                         const unsigned char *name,
                                         size_t name_length) {
  if (!name || name_length == 0 || name_length >= 4096) {
    return NULL;
  }
  char buffer[4096];
  memcpy(buffer, name, name_length);
  buffer[name_length] = '\0';
  return LLVMAddFunction(module, buffer, type);
}

LLVMValueRef dyn_llvm_add_syscall(LLVMModuleRef module, LLVMTypeRef type) {
  return LLVMAddFunction(module, "syscall", type);
}

LLVMValueRef dyn_llvm_add_panic(LLVMModuleRef module, LLVMTypeRef type) {
  return LLVMAddFunction(module, "dyn_selfhost_panic", type);
}

void dyn_selfhost_panic(const unsigned char *message, size_t length) {
  if (message && length)
    fwrite(message, 1, length, stderr);
  fputc('\n', stderr);
  exit(101);
}

LLVMBasicBlockRef dyn_llvm_append_indexed_block(LLVMContextRef context,
                                                LLVMValueRef function,
                                                unsigned index) {
  char name[32];
  snprintf(name, sizeof(name), "block_%u", index);
  return LLVMAppendBasicBlockInContext(context, function, name);
}

int dyn_llvm_verify_module(LLVMModuleRef module) {
  char *message = NULL;
  int failed = LLVMVerifyModule(module, 2, &message);
  if (failed && message) {
    fputs(message, stderr);
  }
  if (message) {
    LLVMDisposeMessage(message);
  }
  return failed;
}

LLVMValueRef dyn_llvm_build_add(LLVMBuilderRef builder, LLVMValueRef left,
                                LLVMValueRef right) {
  return LLVMBuildAdd(builder, left, right, "add");
}

LLVMValueRef dyn_llvm_build_sub(LLVMBuilderRef builder, LLVMValueRef left,
                                LLVMValueRef right) {
  return LLVMBuildSub(builder, left, right, "sub");
}

LLVMValueRef dyn_llvm_build_mul(LLVMBuilderRef builder, LLVMValueRef left,
                                LLVMValueRef right) {
  return LLVMBuildMul(builder, left, right, "mul");
}

LLVMValueRef dyn_llvm_build_sdiv(LLVMBuilderRef builder, LLVMValueRef left,
                                 LLVMValueRef right) {
  return LLVMBuildSDiv(builder, left, right, "div");
}

LLVMValueRef dyn_llvm_build_udiv(LLVMBuilderRef builder, LLVMValueRef left,
                                 LLVMValueRef right) {
  return LLVMBuildUDiv(builder, left, right, "udiv");
}

LLVMValueRef dyn_llvm_build_neg(LLVMBuilderRef builder, LLVMValueRef value) {
  return LLVMBuildNeg(builder, value, "neg");
}

LLVMValueRef dyn_llvm_build_not(LLVMBuilderRef builder, LLVMValueRef value) {
  return LLVMBuildNot(builder, value, "not");
}

LLVMValueRef dyn_llvm_build_srem(LLVMBuilderRef builder, LLVMValueRef left,
                                 LLVMValueRef right) {
  return LLVMBuildSRem(builder, left, right, "rem");
}

LLVMValueRef dyn_llvm_build_urem(LLVMBuilderRef builder, LLVMValueRef left,
                                 LLVMValueRef right) {
  return LLVMBuildURem(builder, left, right, "urem");
}

LLVMValueRef dyn_llvm_build_and(LLVMBuilderRef builder, LLVMValueRef left,
                                LLVMValueRef right) {
  return LLVMBuildAnd(builder, left, right, "and");
}

LLVMValueRef dyn_llvm_build_or(LLVMBuilderRef builder, LLVMValueRef left,
                               LLVMValueRef right) {
  return LLVMBuildOr(builder, left, right, "or");
}

LLVMValueRef dyn_llvm_build_alloca(LLVMBuilderRef builder, LLVMTypeRef type) {
  return LLVMBuildAlloca(builder, type, "local");
}

LLVMValueRef dyn_llvm_build_store(LLVMBuilderRef builder, LLVMValueRef value,
                                  LLVMValueRef pointer) {
  return LLVMBuildStore(builder, value, pointer);
}

LLVMValueRef dyn_llvm_build_load(LLVMBuilderRef builder, LLVMTypeRef type,
                                 LLVMValueRef pointer) {
  if (!builder || !type || !pointer)
    return NULL;
  return LLVMBuildLoad2(builder, type, pointer, "load");
}

LLVMValueRef dyn_llvm_build_struct_gep(LLVMBuilderRef builder,
                                       LLVMTypeRef type,
                                       LLVMValueRef pointer,
                                       unsigned field) {
  return LLVMBuildStructGEP2(builder, type, pointer, field, "field");
}

LLVMValueRef dyn_llvm_build_insert_value(LLVMBuilderRef builder,
                                          LLVMValueRef aggregate,
                                          LLVMValueRef value,
                                          unsigned index) {
  if (!builder || !aggregate || !value) return aggregate;
  LLVMTypeRef aggregate_type = LLVMTypeOf(aggregate);
  if (LLVMGetTypeKind(aggregate_type) != 10 ||
      index >= LLVMCountStructElementTypes(aggregate_type))
    return aggregate;
  LLVMTypeRef expected = LLVMStructGetTypeAtIndex(aggregate_type, index);
  if (LLVMTypeOf(value) != expected) return aggregate;
  return LLVMBuildInsertValue(builder, aggregate, value, index, "insert");
}

LLVMValueRef dyn_llvm_build_extract_value(LLVMBuilderRef builder,
                                           LLVMValueRef aggregate,
                                           unsigned index) {
  return LLVMBuildExtractValue(builder, aggregate, index, "extract");
}

LLVMValueRef dyn_llvm_build_array_gep(LLVMBuilderRef builder,
                                      LLVMTypeRef array_type,
                                      LLVMValueRef pointer,
                                      LLVMValueRef index) {
  LLVMValueRef indices[2] = {LLVMConstInt(LLVMTypeOf(index), 0, 0), index};
  return LLVMBuildGEP2(builder, array_type, pointer, indices, 2, "index");
}

LLVMValueRef dyn_llvm_build_element_gep(LLVMBuilderRef builder,
                                        LLVMTypeRef element_type,
                                        LLVMValueRef pointer,
                                        LLVMValueRef index) {
  return LLVMBuildGEP2(builder, element_type, pointer, &index, 1, "index");
}

LLVMValueRef dyn_llvm_build_ptr_to_int(LLVMBuilderRef builder,
                                       LLVMValueRef value, LLVMTypeRef type) {
  return LLVMBuildPtrToInt(builder, value, type, "ptrtoint");
}

LLVMValueRef dyn_llvm_build_int_to_ptr(LLVMBuilderRef builder,
                                       LLVMValueRef value, LLVMTypeRef type) {
  return LLVMBuildIntToPtr(builder, value, type, "inttoptr");
}

LLVMValueRef dyn_llvm_build_string(LLVMBuilderRef builder,
                                   const unsigned char *text,
                                   size_t text_length) {
  if (!text || text_length < 2 || text_length >= 4096)
    return NULL;
  char buffer[4096];
  size_t length = text_length - 2;
  memcpy(buffer, text + 1, length);
  buffer[length] = '\0';
  return LLVMBuildGlobalStringPtr(builder, buffer, "str");
}

LLVMValueRef dyn_llvm_build_br(LLVMBuilderRef builder,
                               LLVMBasicBlockRef target) {
  return LLVMBuildBr(builder, target);
}

LLVMValueRef dyn_llvm_build_icmp(LLVMBuilderRef builder, unsigned predicate,
                                 LLVMValueRef left, LLVMValueRef right) {
  return LLVMBuildICmp(builder, predicate, left, right, "compare");
}

LLVMValueRef dyn_llvm_build_cond_br(LLVMBuilderRef builder,
                                    LLVMValueRef condition,
                                    LLVMBasicBlockRef true_block,
                                    LLVMBasicBlockRef false_block) {
  return LLVMBuildCondBr(builder, condition, true_block, false_block);
}

LLVMValueRef dyn_llvm_build_call(LLVMBuilderRef builder, LLVMTypeRef type,
                                 LLVMValueRef function, LLVMValueRef *arguments,
                                 unsigned argument_count) {
  unsigned fixed_count = LLVMCountParamTypes(type);
  if (fixed_count > argument_count || fixed_count > 256)
    return NULL;
  LLVMTypeRef parameters[256];
  LLVMGetParamTypes(type, parameters);
  for (unsigned i = 0; i < fixed_count; ++i)
    if (!arguments[i] || LLVMTypeOf(arguments[i]) != parameters[i]) {
      return NULL;
    }
  LLVMTypeRef result = LLVMGetReturnType(type);
  const char *name = LLVMGetTypeKind(result) == 0 ? "" : "call";
  return LLVMBuildCall2(builder, type, function, arguments, argument_count,
                        name);
}

LLVMValueRef dyn_llvm_build_sext(LLVMBuilderRef builder, LLVMValueRef value,
                                 LLVMTypeRef type) {
  return LLVMBuildSExt(builder, value, type, "sext");
}

LLVMValueRef dyn_llvm_build_zext(LLVMBuilderRef builder, LLVMValueRef value,
                                 LLVMTypeRef type) {
  return LLVMBuildZExt(builder, value, type, "zext");
}

LLVMValueRef dyn_llvm_build_trunc(LLVMBuilderRef builder, LLVMValueRef value,
                                  LLVMTypeRef type) {
  return LLVMBuildTrunc(builder, value, type, "trunc");
}

LLVMValueRef dyn_llvm_coerce_integer(LLVMBuilderRef builder, LLVMValueRef value,
                                     LLVMTypeRef type, unsigned is_signed) {
  if (!value || !type) return value;
  LLVMTypeRef source = LLVMTypeOf(value);
  if (source == type) return value;
  if (LLVMGetTypeKind(source) != 8 || LLVMGetTypeKind(type) != 8)
    return value;
  unsigned source_width = LLVMGetIntTypeWidth(source);
  unsigned target_width = LLVMGetIntTypeWidth(type);
  if (source_width > target_width)
    return LLVMBuildTrunc(builder, value, type, "int.cast");
  if (is_signed)
    return LLVMBuildSExt(builder, value, type, "int.cast");
  return LLVMBuildZExt(builder, value, type, "int.cast");
}

static int dyn_llvm_emit_object_for_target(LLVMModuleRef module,
    const unsigned char *path, size_t path_length, unsigned release,
    const char *triple) {
  if (!path || path_length == 0 || path_length >= 4096) {
    return 1;
  }
  char output[4096];
  memcpy(output, path, path_length);
  output[path_length] = '\0';
  LLVMInitializeX86TargetInfo();
  LLVMInitializeX86Target();
  LLVMInitializeX86TargetMC();
  LLVMInitializeX86AsmPrinter();
  LLVMInitializeAArch64TargetInfo();
  LLVMInitializeAArch64Target();
  LLVMInitializeAArch64TargetMC();
  LLVMInitializeAArch64AsmPrinter();
  if (!triple) return 1;
  LLVMSetTarget(module, triple);
  LLVMTargetRef target = NULL;
  char *error = NULL;
  int failed = LLVMGetTargetFromTriple(triple, &target, &error);
  LLVMTargetMachineRef machine = NULL;
  if (!failed) {
    machine = LLVMCreateTargetMachine(target, triple, "generic", "",
                                      release ? 2 : 0, 2, 0);
  }
  if (!failed && !machine) {
    failed = 1;
  }
  if (!failed && release) {
    LLVMPassBuilderOptionsRef options = LLVMCreatePassBuilderOptions();
    LLVMErrorRef pass_error = LLVMRunPasses(module, "default<O2>", machine, options);
    LLVMDisposePassBuilderOptions(options);
    if (pass_error) {
      error = LLVMGetErrorMessage(pass_error);
      failed = 1;
    }
  }
  if (!failed) {
    failed = LLVMTargetMachineEmitToFile(machine, module, output, 1, &error);
  }
  if (failed && error) {
    fputs(error, stderr);
  }
  if (error) {
    LLVMDisposeMessage(error);
  }
  if (machine) {
    LLVMDisposeTargetMachine(machine);
  }
  return failed;
}

int dyn_llvm_emit_object(LLVMModuleRef module, const unsigned char *path,
                         size_t path_length, unsigned release) {
  char *triple = LLVMGetDefaultTargetTriple();
  if (!triple) return 1;
  int result = dyn_llvm_emit_object_for_target(module, path, path_length,
                                               release, triple);
  LLVMDisposeMessage(triple);
  return result;
}

/* Self-host IR ABI. Keep this adapter mechanical: policy and IR construction
   remain in Dyn; C only translates stable POD records into LLVM calls. */
typedef struct { const unsigned char *data; size_t length; } DynIrSlice;
typedef struct {
  DynIrSlice name;
  DynIrSlice source_name;
  uint32_t type_id, first_block, block_count, first_value, value_count;
  uint32_t declaration;
  uint8_t foreign;
} DynIrFunction;
typedef struct { uint32_t first, count; } DynIrBlock;
typedef struct {
  uint32_t op, type_id, result, left, right;
  uint32_t padding;
  uint64_t immediate;
  uint32_t target, alternate;
} DynIrInstruction;
typedef struct {
  DynIrFunction *functions; size_t function_capacity, function_count;
  DynIrBlock *blocks; size_t block_capacity, block_count;
  DynIrInstruction *instructions; size_t instruction_capacity, instruction_count;
} DynIrProgram;
typedef struct {
  uint32_t kind, element, result, declaration, parameter_start, parameter_count;
  uint64_t length;
  uint32_t bits;
  uint8_t is_signed, constant, variadic;
  uint8_t padding;
  uint64_t size, alignment;
  uint32_t metadata;
} DynIrType;
typedef struct {
  DynIrType *items; size_t item_capacity, count;
  uint32_t *parameters; size_t parameter_capacity, parameter_count;
} DynIrTypes;

static LLVMTypeRef dyn_selfhost_type(LLVMContextRef context,
                                     const DynIrTypes *types, uint32_t id) {
  if (!types || id >= types->count) return NULL;
  const DynIrType *type = &types->items[id];
  switch (type->kind) {
    case 2: return LLVMVoidTypeInContext(context);
    case 3: return LLVMInt1TypeInContext(context);
    case 4: {
      unsigned bits = type->bits ? type->bits : (unsigned)(type->size * 8);
      return LLVMIntTypeInContext(context, bits);
    }
    case 5: return type->bits == 32 ? LLVMFloatTypeInContext(context)
                                    : LLVMDoubleTypeInContext(context);
    case 6: case 9: return LLVMPointerTypeInContext(context, 0);
    default: return NULL;
  }
}

static int dyn_selfhost_signed(const DynIrTypes *types, uint32_t id) {
  return types && id < types->count && types->items[id].is_signed;
}

int dyn_llvm_emit_program(const void *raw_program, const void *raw_types,
                          const unsigned char *path, size_t path_length,
                          unsigned release, const unsigned char *raw_triple,
                          size_t triple_length, void *raw_values,
                          void *raw_functions, void *raw_function_types) {
  const DynIrProgram *program = raw_program;
  const DynIrTypes *types = raw_types;
  if (!program || !types || !program->function_count || !raw_triple ||
      !triple_length || triple_length >= 256) return 1;
  char triple[256];
  memcpy(triple, raw_triple, triple_length);
  triple[triple_length] = 0;
  int failed = 1;
  LLVMContextRef context = LLVMContextCreate();
  LLVMModuleRef module = dyn_llvm_module_create_probe(context);
  LLVMBuilderRef builder = LLVMCreateBuilderInContext(context);
  LLVMValueRef *values = raw_values;
  LLVMValueRef *functions = raw_functions;
  LLVMTypeRef *function_types = raw_function_types;
  if (!context || !module || !builder || !values || !functions ||
      !function_types) goto done;
  for (size_t f = 0; f < program->function_count; ++f) {
    const DynIrFunction *fn = &program->functions[f];
    if (fn->type_id >= types->count) goto done;
    const DynIrType *signature = &types->items[fn->type_id];
    if (signature->kind != 12 || signature->parameter_count > 256) goto done;
    LLVMTypeRef parameters[256];
    for (uint32_t p = 0; p < signature->parameter_count; ++p) {
      size_t at = (size_t)signature->parameter_start + p;
      if (at >= types->parameter_count) goto done;
      parameters[p] = dyn_selfhost_type(context, types, types->parameters[at]);
      if (!parameters[p]) goto done;
    }
    LLVMTypeRef result = dyn_selfhost_type(context, types, signature->result);
    if (!result) goto done;
    function_types[f] = LLVMFunctionType(result, parameters,
      signature->parameter_count, signature->variadic != 0);
    functions[f] = dyn_llvm_add_named_function(module, function_types[f],
      fn->name.data, fn->name.length);
    if (!functions[f]) goto done;
  }
  for (size_t f = 0; f < program->function_count; ++f) {
    const DynIrFunction *fn = &program->functions[f];
    if (fn->foreign) continue;
    LLVMBasicBlockRef blocks[256];
    if (!fn->block_count || fn->block_count > 256 ||
        (size_t)fn->first_block + fn->block_count > program->block_count)
      goto done;
    for (uint32_t b = 0; b < fn->block_count; ++b)
      blocks[b] = dyn_llvm_append_indexed_block(context, functions[f], b);
    for (uint32_t b = 0; b < fn->block_count; ++b) {
      const DynIrBlock *block = &program->blocks[fn->first_block + b];
      if ((size_t)block->first + block->count > program->instruction_count)
        goto done;
      LLVMPositionBuilderAtEnd(builder, blocks[b]);
      for (uint32_t n = block->first; n < block->first + block->count; ++n) {
        const DynIrInstruction *in = &program->instructions[n];
        LLVMTypeRef type = dyn_selfhost_type(context, types, in->type_id);
        switch (in->op) {
          case 1: values[n] = LLVMGetParam(functions[f], in->immediate); break;
          case 2: values[n] = type ? LLVMConstInt(type, in->immediate, 0) : NULL; break;
          case 3: values[n] = dyn_llvm_build_add(builder, values[in->left], values[in->right]); break;
          case 4: values[n] = dyn_llvm_build_sub(builder, values[in->left], values[in->right]); break;
          case 5: values[n] = dyn_llvm_build_mul(builder, values[in->left], values[in->right]); break;
          case 6: values[n] = dyn_llvm_build_sdiv(builder, values[in->left], values[in->right]); break;
          case 7: values[n] = dyn_llvm_build_udiv(builder, values[in->left], values[in->right]); break;
          case 8: values[n] = dyn_selfhost_signed(types, in->type_id)
              ? dyn_llvm_build_srem(builder, values[in->left], values[in->right])
              : dyn_llvm_build_urem(builder, values[in->left], values[in->right]); break;
          case 9: values[n] = dyn_llvm_build_and(builder, values[in->left], values[in->right]); break;
          case 10: values[n] = dyn_llvm_build_or(builder, values[in->left], values[in->right]); break;
          case 11: values[n] = LLVMBuildXor(builder, values[in->left], values[in->right], "xor"); break;
          case 12: values[n] = LLVMBuildShl(builder, values[in->left], values[in->right], "shl"); break;
          case 13: values[n] = dyn_selfhost_signed(types,
              program->instructions[in->left].type_id)
              ? LLVMBuildAShr(builder, values[in->left], values[in->right], "shr")
              : LLVMBuildLShr(builder, values[in->left], values[in->right], "shr"); break;
          case 14: case 15: case 16: case 17: case 18: case 19: {
            int is_signed = dyn_selfhost_signed(types,
              program->instructions[in->left].type_id);
            unsigned predicate = in->op == 14 ? 32 : in->op == 15 ? 33 :
              in->op == 16 ? (is_signed ? 40 : 36) :
              in->op == 17 ? (is_signed ? 41 : 37) :
              in->op == 18 ? (is_signed ? 38 : 34) : (is_signed ? 39 : 35);
            values[n] = dyn_llvm_build_icmp(builder, predicate,
              values[in->left], values[in->right]); break;
          }
          case 20: values[n] = dyn_llvm_coerce_integer(builder, values[in->left], type,
                                                       dyn_selfhost_signed(types, in->type_id)); break;
          case 21: values[n] = dyn_llvm_build_alloca(builder, type); break;
          case 22: values[n] = dyn_llvm_build_load(builder, type, values[in->left]); break;
          case 23: values[n] = dyn_llvm_build_store(builder, values[in->left], values[in->right]); break;
          case 24: {
            if (in->target >= program->function_count || in->immediate > 2) goto done;
            LLVMValueRef arguments[2] = {values[in->left], values[in->right]};
            values[n] = dyn_llvm_build_call(builder, function_types[in->target],
              functions[in->target], arguments, (unsigned)in->immediate); break;
          }
          case 25:
            if (in->target < fn->first_block ||
                in->target >= fn->first_block + fn->block_count) goto done;
            values[n] = dyn_llvm_build_br(builder,
              blocks[in->target - fn->first_block]); break;
          case 26:
            if (in->target < fn->first_block || in->alternate < fn->first_block ||
                in->target >= fn->first_block + fn->block_count ||
                in->alternate >= fn->first_block + fn->block_count) goto done;
            values[n] = dyn_llvm_build_cond_br(builder, values[in->left],
              blocks[in->target - fn->first_block],
              blocks[in->alternate - fn->first_block]); break;
          case 27: values[n] = LLVMBuildRet(builder, values[in->left]); break;
          case 28: values[n] = LLVMBuildRetVoid(builder); break;
          default: goto done;
        }
        if (!values[n]) goto done;
      }
    }
  }
  if (dyn_llvm_verify_module(module)) goto done;
  failed = dyn_llvm_emit_object_for_target(module, path, path_length, release,
                                            triple);
done:
  if (builder) LLVMDisposeBuilder(builder);
  if (module) LLVMDisposeModule(module);
  if (context) LLVMContextDispose(context);
  return failed;
}
