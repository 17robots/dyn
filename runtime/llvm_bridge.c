#include "../src/llvm_shim.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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
    if (!arguments[i] || LLVMTypeOf(arguments[i]) != parameters[i])
      return NULL;
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

int dyn_llvm_emit_object(LLVMModuleRef module, const unsigned char *path,
                         size_t path_length, unsigned release) {
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
  char *triple = LLVMGetDefaultTargetTriple();
  if (!triple) {
    return 1;
  }
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
  LLVMDisposeMessage(triple);
  return failed;
}
