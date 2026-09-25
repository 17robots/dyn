#ifndef DYN_CODEGEN_ABI_H
#define DYN_CODEGEN_ABI_H

/* Private target ABI lowering. Declarations, direct/indirect calls, parameters
   and returns use the same plan. Dyn types/layouts never depend on LLVM types.
   Supported C storage: scalars, pointers, structs and nested fixed arrays. */
typedef enum { ABI_DIRECT, ABI_COERCE, ABI_INDIRECT } AbiMode;
typedef struct {
  DynType source;
  AbiMode mode;
  LLVMTypeRef parts[2];
  unsigned count, index, offset[2];
  bool byval, stack_align;
} AbiValue;
struct GenAbi {
  AbiValue result, *params;
  uint32_t count, llvm_count;
  LLVMTypeRef type;
};
static uint64_t abi_size(Gen *g, DynType t) {
  if (dyn_type_is_array(t)) {
    DynIrArray *a = &g->ir->arrays[t - DYN_TYPE_ARRAY_BASE];
    return a->length * abi_size(g, a->element);
  }
  return t == DYN_TYPE_BOOL ? 1 : debug_type_size(g, t);
}
static bool abi_arm(Gen *g) {
  return !strcmp(dyn_context_target(&g->source->context)->arch, "aarch64");
}
static bool abi_windows(Gen *g) {
  return !strcmp(dyn_context_target(&g->source->context)->kernel, "windows");
}
static uint64_t abi_align_up(uint64_t n, uint64_t align) {
  return (n + align - 1) & ~(align - 1);
}
/* SysV eightbyte classes. Integer dominates SSE; unaligned fields use memory.
   Track occupied float bytes so a tail float does not become a double. */
static bool abi_eightbytes(Gen *g, DynType t, uint64_t offset,
                           unsigned cls[2], unsigned floats[2], unsigned depth) {
  if (depth > 128 || offset + abi_size(g, t) > 16) return false;
  if (dyn_type_is_struct(t)) {
    DynIrStruct *s = &g->ir->structs[t - DYN_TYPE_STRUCT_BASE];
    uint64_t at = 0;
    for (uint32_t i = 0; i < s->field_count; ++i) {
      DynType f = g->ir->fields[s->field_start + i].type;
      uint64_t align = type_alignment(g, f);
      if (!s->packed) at = abi_align_up(at, align);
      if ((offset + at) % align || !abi_eightbytes(g, f, offset + at, cls, floats, depth + 1)) return false;
      at += abi_size(g, f);
    }
    return true;
  }
  if (dyn_type_is_array(t)) {
    DynIrArray *a = &g->ir->arrays[t - DYN_TYPE_ARRAY_BASE];
    for (uint64_t i = 0; i < a->length; ++i)
      if (!abi_eightbytes(g, a->element, offset + i * abi_size(g, a->element), cls, floats, depth + 1)) return false;
    return true;
  }
  uint64_t size = abi_size(g, t);
  for (uint64_t i = offset; i < offset + size; ++i) {
    unsigned slot = (unsigned)(i / 8);
    if (float_type(t)) {
      if (!cls[slot]) cls[slot] = 2;
      floats[slot] |= 1u << (i % 8);
      if (t == DYN_TYPE_F64) floats[slot] |= 256;
    } else cls[slot] = 1;
  }
  return true;
}
static bool abi_hfa(Gen *g, DynType t, DynType *element, unsigned *count, unsigned depth) {
  if (depth > 128) return false;
  if (float_type(t)) {
    if (*element && *element != t) return false;
    *element = t;
    return ++*count <= 4;
  }
  if (dyn_type_is_struct(t)) {
    DynIrStruct *s = &g->ir->structs[t - DYN_TYPE_STRUCT_BASE];
    if (!s->field_count) return false;
    for (uint32_t i = 0; i < s->field_count; ++i)
      if (!abi_hfa(g, g->ir->fields[s->field_start + i].type, element, count, depth + 1)) return false;
    return true;
  }
  if (dyn_type_is_array(t)) {
    DynIrArray *a = &g->ir->arrays[t - DYN_TYPE_ARRAY_BASE];
    if (!a->length || a->length > 4) return false;
    for (uint64_t i = 0; i < a->length; ++i)
      if (!abi_hfa(g, a->element, element, count, depth + 1)) return false;
    return true;
  }
  return false;
}
static AbiValue abi_value(Gen *g, DynType t, bool result) {
  AbiValue v = {.source = t, .count = 1};
  v.parts[0] = t == DYN_TYPE_VOID ? LLVMVoidTypeInContext(g->context) : llvm_type(g, t);
  if (!dyn_type_is_struct(t)) return v;
  uint64_t size = abi_size(g, t);
  v.mode = ABI_COERCE;
  if (g->wasm) {
    /* Basic C ABI: a single scalar field is scalar; other structs indirect. */
    DynType scalar = t;
    while (dyn_type_is_struct(scalar)) {
      DynIrStruct *st = &g->ir->structs[scalar - DYN_TYPE_STRUCT_BASE];
      if (st->field_count != 1) break;
      scalar = g->ir->fields[st->field_start].type;
    }
    if (!dyn_type_is_struct(scalar) && !dyn_type_is_array(scalar) &&
        !dyn_type_is_slice(scalar) && scalar != DYN_TYPE_ANY && scalar != DYN_TYPE_STRING &&
        abi_size(g, scalar) == size)
      v.parts[0] = llvm_type(g, scalar);
    else { v.mode = ABI_INDIRECT; v.byval = !result; }
  } else if (abi_windows(g)) {
    if (size == 1 || size == 2 || size == 4 || size == 8)
      v.parts[0] = LLVMIntTypeInContext(g->context, (unsigned)size * 8);
    else v.mode = ABI_INDIRECT;
  } else if (abi_arm(g)) {
    DynType element = 0;
    unsigned count = 0;
    if (abi_hfa(g, t, &element, &count, 0) && count && size == count * abi_size(g, element)) {
      v.parts[0] = result ? llvm_type(g, t) : LLVMArrayType2(llvm_type(g, element), count);
      v.stack_align = !result && !strcmp(dyn_context_target(&g->source->context)->kernel, "linux");
    } else if (size <= 8)
      v.parts[0] = LLVMIntTypeInContext(g->context, result ? (unsigned)size * 8 : 64);
    else if (size <= 16)
      v.parts[0] = LLVMArrayType2(LLVMInt64TypeInContext(g->context), 2);
    else v.mode = ABI_INDIRECT;
  } else {
    unsigned cls[2] = {0}, floats[2] = {0};
    if (size > 16 || !abi_eightbytes(g, t, 0, cls, floats, 0)) {
      v.mode = ABI_INDIRECT;
      v.byval = !result;
    } else {
      v.count = (unsigned)((size + 7) / 8);
      for (unsigned i = 0; i < v.count; ++i) {
        v.offset[i] = i * 8;
        if (cls[i] == 2) {
          v.parts[i] = floats[i] & 256 ? LLVMDoubleTypeInContext(g->context)
              : floats[i] & 240 ? LLVMVectorType(LLVMFloatTypeInContext(g->context), 2)
                               : LLVMFloatTypeInContext(g->context);
        } else {
          uint64_t bytes = size - i * 8;
          v.parts[i] = LLVMIntTypeInContext(g->context, (unsigned)(bytes > 8 ? 8 : bytes) * 8);
        }
      }
    }
  }
  if (v.mode == ABI_INDIRECT) {
    v.count = 1;
    v.parts[0] = LLVMPointerTypeInContext(g->context, 0);
  }
  return v;
}
static GenAbi *abi_plan(Gen *g, DynType result, const DynType *types, uint32_t count, bool variadic) {
  GenAbi *p = calloc(1, sizeof(*p));
  LLVMTypeRef *llvm_params = calloc((size_t)count * 2 + 1, sizeof(*llvm_params));
  if (!p || !llvm_params) { free(p); free(llvm_params); g->allocation_failed = true; return NULL; }
  p->params = calloc(count ? count : 1, sizeof(*p->params));
  if (!p->params) { free(p); free(llvm_params); g->allocation_failed = true; return NULL; }
  p->count = count;
  p->result = abi_value(g, result, true);
  bool sysv = !g->wasm && !abi_arm(g) && !abi_windows(g);
  unsigned gp = 0, fp = 0;
  LLVMTypeRef returned = p->result.parts[0];
  if (p->result.mode == ABI_INDIRECT) {
    llvm_params[p->llvm_count++] = LLVMPointerTypeInContext(g->context, 0);
    returned = LLVMVoidTypeInContext(g->context);
    if (sysv) ++gp;
  } else if (p->result.count == 2)
    returned = LLVMStructTypeInContext(g->context, p->result.parts, 2, 0);
  for (uint32_t i = 0; i < count; ++i) {
    AbiValue v = abi_value(g, types[i], false);
    if (sysv) {
      unsigned integers = 0, sse = 0;
      if (v.mode != ABI_INDIRECT) {
        for (unsigned k = 0; k < v.count; ++k) {
          int kind = LLVMGetTypeKind(v.parts[k]);
          if (kind == 2 || kind == 3 || kind == 13) ++sse; /* float, double, vector */
          else integers += v.mode == ABI_DIRECT && (dyn_type_is_slice(v.source) || v.source == DYN_TYPE_STRING || v.source == DYN_TYPE_ANY) ? 2 : 1;
        }
        if (v.mode == ABI_COERCE && (gp + integers > 6 || fp + sse > 8)) {
          v.mode = ABI_INDIRECT; v.byval = true; v.count = 1;
          v.parts[0] = LLVMPointerTypeInContext(g->context, 0);
        } else { gp = gp + integers > 6 ? 6 : gp + integers; fp = fp + sse > 8 ? 8 : fp + sse; }
      }
    }
    v.index = p->llvm_count;
    p->params[i] = v;
    for (unsigned k = 0; k < v.count; ++k) llvm_params[p->llvm_count++] = v.parts[k];
  }
  p->type = LLVMFunctionType(returned, llvm_params, p->llvm_count, variadic);
  free(llvm_params);
  return p;
}
static void abi_free(GenAbi *p) { if (p) { free(p->params); free(p); } }
static void abi_attribute(Gen *g, LLVMValueRef value, unsigned index, const char *name,
                          DynType type, uint64_t number, bool call) {
  unsigned kind = LLVMGetEnumAttributeKindForName(name, strlen(name));
  LLVMAttributeRef attribute = type ? LLVMCreateTypeAttribute(g->context, kind, llvm_type(g, type))
                                   : LLVMCreateEnumAttribute(g->context, kind, number);
  if (call) LLVMAddCallSiteAttribute(value, index, attribute);
  else LLVMAddAttributeAtIndex(value, index, attribute);
}
static void abi_attributes(Gen *g, LLVMValueRef value, const GenAbi *p, bool call) {
  if (p->result.mode == ABI_INDIRECT) {
    abi_attribute(g, value, 1, "sret", p->result.source, 0, call);
    abi_attribute(g, value, 1, "align", 0, type_alignment(g, p->result.source), call);
  }
  for (uint32_t i = 0; i <= p->count; ++i) {
    const AbiValue *v = i == p->count ? &p->result : &p->params[i];
    unsigned index = i == p->count ? 0 : v->index + 1;
    if (v->mode == ABI_DIRECT && (v->source == DYN_TYPE_BOOL || v->source == DYN_TYPE_I8 || v->source == DYN_TYPE_U8 || v->source == DYN_TYPE_I16 || v->source == DYN_TYPE_U16))
      abi_attribute(g, value, index, signed_type(v->source) ? "signext" : "zeroext", 0, 0, call);
    if (i == p->count) break;
    if (v->byval) {
      abi_attribute(g, value, index, "byval", v->source, 0, call);
      uint64_t align = type_alignment(g, v->source);
      abi_attribute(g, value, index, "align", 0, g->wasm ? align : align < 8 ? 8 : align, call);
    }
    if (v->stack_align) abi_attribute(g, value, index, "alignstack", 0, 8, call);
  }
}
static LLVMValueRef abi_slot(Gen *g, const AbiValue *v) {
  /* Register coercions can be wider than logical storage (e.g. AArch64 i64
     argument for a 3-byte struct). Never load/store past a source object. */
  LLVMTypeRef type = v->mode == ABI_COERCE
      ? LLVMArrayType2(LLVMInt8TypeInContext(g->context), abi_align_up(abi_size(g, v->source), 8))
      : llvm_type(g, v->source);
  LLVMValueRef slot = gen_stack_slot(g, type, "abi.storage");
  LLVMSetAlignment(slot, 16);
  if (v->mode == ABI_COERCE) LLVMBuildStore(g->builder, LLVMConstNull(type), slot);
  return slot;
}
static LLVMValueRef abi_address(Gen *g, LLVMValueRef slot, unsigned offset) {
  if (!offset) return slot;
  LLVMValueRef index = LLVMConstInt(LLVMInt64TypeInContext(g->context), offset, 0);
  return LLVMBuildGEP2(g->builder, LLVMInt8TypeInContext(g->context), slot, &index, 1, "abi.part");
}
static LLVMValueRef abi_decode(Gen *g, const AbiValue *v, LLVMValueRef *parts) {
  assert(v->count == 1 || v->count == 2);
  if (v->mode == ABI_DIRECT) return parts[0];
  LLVMValueRef slot = parts[0];
  if (v->mode == ABI_COERCE) {
    slot = abi_slot(g, v);
    for (unsigned i = 0; i < v->count; ++i)
      LLVMBuildStore(g->builder, parts[i], abi_address(g, slot, v->offset[i]));
  }
  LLVMValueRef result = LLVMBuildLoad2(g->builder, llvm_type(g, v->source), slot, "abi.value");
  LLVMSetAlignment(result, (unsigned)type_alignment(g, v->source));
  return result;
}
static void abi_encode(Gen *g, const AbiValue *v, LLVMValueRef value, LLVMValueRef *parts) {
  assert(v->count == 1 || v->count == 2);
  if (v->mode == ABI_DIRECT) { parts[0] = value; return; }
  LLVMValueRef slot = abi_slot(g, v);
  LLVMBuildStore(g->builder, value, slot);
  if (v->mode == ABI_INDIRECT) { parts[0] = slot; return; }
  for (unsigned i = 0; i < v->count; ++i)
    parts[i] = LLVMBuildLoad2(g->builder, v->parts[i], abi_address(g, slot, v->offset[i]), "abi.register");
}
static LLVMValueRef abi_call(Gen *g, const GenAbi *p, LLVMValueRef callee,
                             LLVMValueRef *args, unsigned count, const char *name, bool may_panic) {
  assert(count >= p->count);
  unsigned extra = count - p->count;
  LLVMValueRef *values = calloc((size_t)p->llvm_count + extra + 1, sizeof(*values));
  if (!values) { g->allocation_failed = true; return p->result.source == DYN_TYPE_VOID ? NULL : LLVMConstNull(llvm_type(g, p->result.source)); }
  LLVMValueRef result_slot = NULL;
  if (p->result.mode == ABI_INDIRECT) values[0] = result_slot = abi_slot(g, &p->result);
  for (uint32_t i = 0; i < p->count; ++i) abi_encode(g, &p->params[i], args[i], values + p->params[i].index);
  for (unsigned i = 0; i < extra; ++i) values[p->llvm_count + i] = args[p->count + i];
  LLVMValueRef result = emit_call(g, p->type, callee, values, p->llvm_count + extra,
      LLVMGetReturnType(p->type) == LLVMVoidTypeInContext(g->context) ? "" : name, may_panic, p);
  free(values);
  if (p->result.mode == ABI_INDIRECT) return abi_decode(g, &p->result, &result_slot);
  if (p->result.mode == ABI_DIRECT) return result;
  LLVMValueRef parts[2] = {result, NULL};
  if (p->result.count == 2)
    for (unsigned i = 0; i < 2; ++i) parts[i] = LLVMBuildExtractValue(g->builder, result, i, "abi.result.part");
  return abi_decode(g, &p->result, parts);
}
static void abi_return(Gen *g, LLVMValueRef result) {
  const AbiValue *v = &g->current_abi->result;
  if (v->mode == ABI_INDIRECT) {
    LLVMBuildStore(g->builder, result, LLVMGetParam(g->function, 0));
    LLVMBuildRetVoid(g->builder);
  } else if (v->mode == ABI_DIRECT) LLVMBuildRet(g->builder, result);
  else {
    LLVMValueRef parts[2] = {0};
    abi_encode(g, v, result, parts);
    result = parts[0];
    if (v->count == 2) {
      result = LLVMGetUndef(LLVMGetReturnType(g->current_abi->type));
      for (unsigned i = 0; i < 2; ++i) result = LLVMBuildInsertValue(g->builder, result, parts[i], i, "abi.result");
    }
    LLVMBuildRet(g->builder, result);
  }
}
static LLVMTypeRef llvm_fn_type(Gen *g, uint32_t id) {
  if (!g->pointer_abis[id]) {
    DynIrFnType *f = &g->ir->fn_types[id];
    g->pointer_abis[id] = abi_plan(g, f->return_type, g->ir->fn_type_params + f->param_start, f->param_count, f->variadic);
  }
  return g->pointer_abis[id] ? g->pointer_abis[id]->type : NULL;
}
#endif
