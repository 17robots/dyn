#include "sema.h"
#include <ctype.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define dyn_sema_function dyn_sema_base_impl

static void error_span(DynSpan span, const DynSource *s, unsigned *e,
                       const char *m) {
  unsigned line = 1, col = 1;
  for (uint32_t i = 0; i < span.start_byte && i < s->length; ++i) {
    if (s->text[i] == '\n') {
      ++line;
      col = 1;
    } else
      ++col;
  }
  fprintf(stderr, "%s:%u:%u: error: %s\n", s->path, line, col, m);
  ++*e;
}
static DynAstFunction *type_context;
static DynType underlying_type(DynType t) {
  size_t guard = 0;
  while (type_context && dyn_type_is_distinct(t) &&
         guard++ <= type_context->alias_count) {
    uint32_t id = t - DYN_TYPE_DISTINCT_BASE;
    if (id >= type_context->alias_count)
      return DYN_TYPE_ERROR;
    t = type_context->aliases[id].target;
  }
  return t;
}
static bool integer(DynType t) {
  t = underlying_type(t);
  return t >= DYN_TYPE_I8 && t <= DYN_TYPE_USIZE;
}
static bool signed_int(DynType t) {
  t = underlying_type(t);
  return (t >= DYN_TYPE_I8 && t <= DYN_TYPE_I64) || t == DYN_TYPE_ISIZE;
}
static bool numeric(DynType t) {
  t = underlying_type(t);
  return integer(t) || t == DYN_TYPE_F32 || t == DYN_TYPE_F64;
}
static uint32_t current_function = UINT32_MAX;
static DynType current_return_type = DYN_TYPE_VOID;
static DynAstStmt **active_loops;
static size_t active_loop_count, active_loop_capacity;
static bool span_present(DynSpan s) { return s.end_byte > s.start_byte; }
static bool push_loop(DynAstStmt *st, const DynSource *s, unsigned *errors) {
  if (span_present(st->label))
    for (size_t i = 0; i < active_loop_count; ++i)
      if (span_present(active_loops[i]->label) &&
          dyn_span_text_equal(st->label, active_loops[i]->label, s)) {
        error_span(st->label, s, errors, "duplicate active loop label");
        break;
      }
  if (active_loop_count == active_loop_capacity) {
    size_t c = active_loop_capacity ? active_loop_capacity * 2 : 8;
    void *p = realloc(active_loops, c * sizeof(*active_loops));
    if (!p) {
      error_span(st->span, s, errors, "out of memory");
      return false;
    }
    active_loops = p;
    active_loop_capacity = c;
  }
  active_loops[active_loop_count++] = st;
  return true;
}
static void pop_loop(void) {
  if (active_loop_count)
    --active_loop_count;
}
static bool resolve_loop_control(DynAstStmt *st, const DynSource *s,
                                 unsigned *errors) {
  if (!active_loop_count) {
    error_span(st->span, s, errors,
               st->kind == DYN_STMT_BREAK ? "break requires enclosing loop"
                                          : "continue requires enclosing loop");
    return false;
  }
  if (!span_present(st->control_label)) {
    st->target_loop_id = active_loops[active_loop_count - 1]->loop_id;
    return true;
  }
  for (size_t i = active_loop_count; i > 0; --i)
    if (span_present(active_loops[i - 1]->label) &&
        dyn_span_text_equal(st->control_label, active_loops[i - 1]->label, s)) {
      st->target_loop_id = active_loops[i - 1]->loop_id;
      return true;
    }
  error_span(st->control_label, s, errors, "unknown active loop label");
  return false;
}
static bool reserve_local(DynAstFunction *a) {
  if (a->local_count < a->local_capacity)
    return true;
  size_t c = a->local_capacity ? a->local_capacity * 2 : 16;
  void *p = realloc(a->locals, c * sizeof(*a->locals));
  if (!p)
    return false;
  a->locals = p;
  a->local_capacity = c;
  return true;
}
static bool sema_reserve_expr(DynAstFunction *a) {
  if (a->expression_count < a->expression_capacity)
    return true;
  size_t c = a->expression_capacity ? a->expression_capacity * 2 : 32;
  void *p = realloc(a->expressions, c * sizeof(*a->expressions));
  if (!p)
    return false;
  a->expressions = p;
  a->expression_capacity = c;
  return true;
}
#define reserve_expr sema_reserve_expr
static uint32_t find_local(DynAstFunction *a, DynSpan name,
                           const DynSource *s) {
  for (uint32_t i = 0; i < a->local_count; ++i)
    if (a->locals[i].active && dyn_span_text_equal(name, a->locals[i].name, s))
      return i;
  return UINT32_MAX;
}
static uint32_t find_any_local(DynAstFunction *a, DynSpan name,
                               const DynSource *s) {
  for (uint32_t i = 0; i < a->local_count; ++i)
    if (a->locals[i].owner_function == current_function &&
        dyn_span_text_equal(name, a->locals[i].name, s))
      return i;
  return UINT32_MAX;
}
#define find_global sema_find_global_name
static uint32_t sema_find_global_name(DynAstFunction *a, DynSpan name,
                                      const DynSource *s) {
  for (uint32_t i = 0; i < a->global_count; ++i)
    if (dyn_span_text_equal(name, a->globals[i].name, s))
      return i;
  return UINT32_MAX;
}
static uint32_t sema_find_function(DynAstFunction *a, DynSpan name,
                                   const DynSource *s) {
  for (uint32_t i = 0; i < a->function_count; ++i)
    if (dyn_span_text_equal(name, a->functions[i].name, s))
      return i;
  return UINT32_MAX;
}
static DynSpan sema_unqualified_span(DynSpan name, const DynSource *s) {
  for (uint32_t i = name.start_byte; i < name.end_byte; ++i)
    if (s->text[i] == '.')
      name.start_byte = i + 1;
  return name;
}
static uint32_t sema_find_struct(DynAstFunction *a, DynSpan name,
                                 const DynSource *s) {
  name = sema_unqualified_span(name, s);
  for (uint32_t i = 0; i < a->struct_count; ++i)
    if (dyn_span_text_equal(name, a->structs[i].name, s))
      return i;
  return UINT32_MAX;
}
static uint32_t sema_find_enum(DynAstFunction *a, DynSpan name,
                               const DynSource *s) {
  name = sema_unqualified_span(name, s);
  for (uint32_t i = 0; i < a->enum_count; ++i)
    if (dyn_span_text_equal(name, a->enums[i].name, s))
      return i;
  return UINT32_MAX;
}
static uint32_t sema_expr_enum(DynAstFunction *a, DynExprId id,
                               const DynSource *s) {
  if (id == DYN_NO_EXPR)
    return UINT32_MAX;
  DynAstExpr *e = &a->expressions[id];
  return e->kind == DYN_EXPR_NAME || e->kind == DYN_EXPR_FIELD
             ? sema_find_enum(a, e->span, s)
             : UINT32_MAX;
}
static uint32_t sema_find_variant(DynAstFunction *a, uint32_t eid, DynSpan name,
                                  const DynSource *s) {
  DynAstEnum *en = &a->enums[eid];
  for (uint32_t i = 0; i < en->variant_count; ++i)
    if (dyn_span_text_equal(name, a->variants[en->variant_start + i].name, s))
      return en->variant_start + i;
  return UINT32_MAX;
}
static uint32_t sema_find_field(DynAstFunction *a, uint32_t sid, DynSpan name,
                                const DynSource *s) {
  DynAstStruct *st = &a->structs[sid];
  for (uint32_t i = 0; i < st->field_count; ++i)
    if (dyn_span_text_equal(name, a->fields[st->field_start + i].name, s))
      return i;
  return UINT32_MAX;
}
static bool discard_name(DynSpan n, const DynSource *s) {
  return n.end_byte - n.start_byte == 1 && s->text[n.start_byte] == '_';
}
static unsigned bits(DynType t) {
  t = underlying_type(t);
  switch (t) {
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
#define sema_type_layout sema_type_layout_base
static uint64_t sema_type_layout(DynAstFunction *a, DynType t, bool alignment) {
  t = underlying_type(t);
  if (t == DYN_TYPE_BOOL || t == DYN_TYPE_I8 || t == DYN_TYPE_U8)
    return 1;
  if (t == DYN_TYPE_I16 || t == DYN_TYPE_U16)
    return 2;
  if (t == DYN_TYPE_I32 || t == DYN_TYPE_U32 || t == DYN_TYPE_F32)
    return 4;
  if (t == DYN_TYPE_I64 || t == DYN_TYPE_U64 || t == DYN_TYPE_ISIZE ||
      t == DYN_TYPE_USIZE || t == DYN_TYPE_F64 || t == DYN_TYPE_RAWPTR ||
      dyn_type_is_pointer(t))
    return 8;
  if (dyn_type_is_struct(t)) {
    DynAstStruct *st = &a->structs[t - DYN_TYPE_STRUCT_BASE];
    return alignment ? st->alignment : st->size;
  }
  if (dyn_type_is_enum(t)) {
    DynAstEnum *en = &a->enums[t - DYN_TYPE_ENUM_BASE];
    return alignment ? en->alignment : en->size;
  }
  if (dyn_type_is_array(t)) {
    DynAstArray *ar = &a->arrays[t - DYN_TYPE_ARRAY_BASE];
    uint64_t element = sema_type_layout(a, ar->element, alignment);
    return alignment ? element : element * ar->length;
  }
  if (dyn_type_is_slice(t))
    return alignment ? 8 : 16;
  return 0;
}
#undef sema_type_layout
static uint64_t sema_type_layout(DynAstFunction *a, DynType t, bool alignment) {
  return sema_type_layout_base(a, t, alignment);
}
static bool literal_fits(uint64_t v, DynType t) {
  unsigned b = bits(t);
  if (signed_int(t))
    return b == 64 ? v <= INT64_MAX : v <= (UINT64_C(1) << (b - 1)) - 1;
  return integer(t) && (b == 64 || v <= (UINT64_C(1) << b) - 1);
}
static bool lossless(DynType from, DynType to) {
  if (from == to)
    return true;
  if (dyn_type_is_distinct(from) || dyn_type_is_distinct(to))
    return false;
  if (integer(from) && integer(to)) {
    unsigned f = bits(from), t = bits(to);
    if (signed_int(from) == signed_int(to))
      return t > f;
    if (!signed_int(from) && signed_int(to))
      return t > f;
    return false;
  }
  if (from == DYN_TYPE_F32 && to == DYN_TYPE_F64)
    return true;
  if (integer(from) && (to == DYN_TYPE_F32 || to == DYN_TYPE_F64)) {
    unsigned precision = to == DYN_TYPE_F32 ? 24 : 53;
    unsigned needed = bits(from) - (signed_int(from) ? 1u : 0u);
    return needed <= precision;
  }
  return false;
}
static DynAstPointer *pointer_info(DynAstFunction *a, DynType t) {
  return dyn_type_is_pointer(t) && t - DYN_TYPE_POINTER_BASE < a->pointer_count
             ? &a->pointers[t - DYN_TYPE_POINTER_BASE]
             : NULL;
}
static DynAstArray *array_info(DynAstFunction *a, DynType t) {
  return dyn_type_is_array(t) && t - DYN_TYPE_ARRAY_BASE < a->array_count
             ? &a->arrays[t - DYN_TYPE_ARRAY_BASE]
             : NULL;
}
static DynAstSlice *slice_info(DynAstFunction *a, DynType t) {
  return dyn_type_is_slice(t) && t - DYN_TYPE_SLICE_BASE < a->slice_count
             ? &a->slices[t - DYN_TYPE_SLICE_BASE]
             : NULL;
}
static DynAstFnType *fn_type_info(DynAstFunction *a, DynType t) {
  return dyn_type_is_function(t) && t - DYN_TYPE_FN_BASE < a->fn_type_count
             ? &a->fn_types[t - DYN_TYPE_FN_BASE]
             : NULL;
}
static DynType sema_intern_pointer(DynAstFunction *a, DynType pointee,
                                   bool is_const) {
  for (uint32_t i = 0; i < a->pointer_count; ++i)
    if (a->pointers[i].pointee == pointee &&
        a->pointers[i].is_const == is_const)
      return DYN_TYPE_POINTER_BASE + i;
  if (a->pointer_count == a->pointer_capacity) {
    size_t c = a->pointer_capacity ? a->pointer_capacity * 2 : 8;
    void *p = realloc(a->pointers, c * sizeof(*a->pointers));
    if (!p)
      return DYN_TYPE_ERROR;
    a->pointers = p;
    a->pointer_capacity = c;
  }
  a->pointers[a->pointer_count] = (DynAstPointer){pointee, is_const};
  return DYN_TYPE_POINTER_BASE + a->pointer_count++;
}
static DynType sema_intern_array(DynAstFunction *a, DynType element,
                                 uint64_t length) {
  for (uint32_t i = 0; i < a->array_count; ++i)
    if (a->arrays[i].element == element && a->arrays[i].length == length)
      return DYN_TYPE_ARRAY_BASE + i;
  if (a->array_count == a->array_capacity) {
    size_t c = a->array_capacity ? a->array_capacity * 2 : 8;
    void *p = realloc(a->arrays, c * sizeof(*a->arrays));
    if (!p)
      return DYN_TYPE_ERROR;
    a->arrays = p;
    a->array_capacity = c;
  }
  a->arrays[a->array_count] = (DynAstArray){element, length};
  return DYN_TYPE_ARRAY_BASE + a->array_count++;
}
static DynType sema_intern_slice(DynAstFunction *a, DynType element,
                                 bool is_const) {
  for (uint32_t i = 0; i < a->slice_count; ++i)
    if (a->slices[i].element == element && a->slices[i].is_const == is_const)
      return DYN_TYPE_SLICE_BASE + i;
  if (a->slice_count == a->slice_capacity) {
    size_t c = a->slice_capacity ? a->slice_capacity * 2 : 8;
    void *p = realloc(a->slices, c * sizeof(*a->slices));
    if (!p)
      return DYN_TYPE_ERROR;
    a->slices = p;
    a->slice_capacity = c;
  }
  a->slices[a->slice_count] = (DynAstSlice){element, is_const};
  return DYN_TYPE_SLICE_BASE + a->slice_count++;
}
static DynType sema_intern_fn_type(DynAstFunction *a, const DynType *params,
                                   uint32_t count, DynType result) {
  for (uint32_t i = 0; i < a->fn_type_count; ++i) {
    DynAstFnType *f = &a->fn_types[i];
    if (f->return_type != result || f->param_count != count)
      continue;
    bool same = true;
    for (uint32_t j = 0; j < count; ++j)
      if (a->fn_type_params[f->param_start + j] != params[j])
        same = false;
    if (same)
      return DYN_TYPE_FN_BASE + i;
  }
  if (a->fn_type_count == a->fn_type_capacity) {
    size_t c = a->fn_type_capacity ? a->fn_type_capacity * 2 : 8;
    void *p = realloc(a->fn_types, c * sizeof(*a->fn_types));
    if (!p)
      return DYN_TYPE_ERROR;
    a->fn_types = p;
    a->fn_type_capacity = c;
  }
  if (a->fn_type_param_count + count > a->fn_type_param_capacity) {
    size_t c = a->fn_type_param_capacity ? a->fn_type_param_capacity * 2 : 16;
    while (c < a->fn_type_param_count + count)
      c *= 2;
    void *p = realloc(a->fn_type_params, c * sizeof(*a->fn_type_params));
    if (!p)
      return DYN_TYPE_ERROR;
    a->fn_type_params = p;
    a->fn_type_param_capacity = c;
  }
  uint32_t start = (uint32_t)a->fn_type_param_count;
  for (uint32_t i = 0; i < count; ++i)
    a->fn_type_params[a->fn_type_param_count++] = params[i];
  a->fn_types[a->fn_type_count] = (DynAstFnType){result, start, count};
  return DYN_TYPE_FN_BASE + a->fn_type_count++;
}
static DynType function_pointer_type(DynAstFunction *a, uint32_t id) {
  DynAstFn *f = &a->functions[id];
  DynType *params = calloc(f->param_count, sizeof(*params));
  if (f->param_count && !params)
    return DYN_TYPE_ERROR;
  for (uint32_t i = 0; i < f->param_count; ++i)
    params[i] = a->params[f->param_start + i].type;
  DynType signature =
      sema_intern_fn_type(a, params, f->param_count, f->return_type);
  free(params);
  return signature == DYN_TYPE_ERROR ? signature
                                     : sema_intern_pointer(a, signature, false);
}
static DynType function_signature_type(DynAstFunction *a, uint32_t id) {
  DynAstFn *f = &a->functions[id];
  DynType *params = calloc(f->param_count, sizeof(*params));
  if (f->param_count && !params)
    return DYN_TYPE_ERROR;
  for (uint32_t i = 0; i < f->param_count; ++i)
    params[i] = a->params[f->param_start + i].type;
  DynType result =
      sema_intern_fn_type(a, params, f->param_count, f->return_type);
  free(params);
  return result;
}
static bool can_convert(DynAstFunction *a, DynType from, DynType to) {
  if (to == DYN_TYPE_ANY && from != DYN_TYPE_VOID && from != DYN_TYPE_ERROR)
    return true;
  if (lossless(from, to))
    return true;
  DynAstPointer *f = pointer_info(a, from), *t = pointer_info(a, to);
  if (f && t)
    return f->pointee == t->pointee && !f->is_const && t->is_const;
  DynAstSlice *fs = slice_info(a, from), *ts = slice_info(a, to);
  return fs && ts && fs->element == ts->element && !fs->is_const &&
         ts->is_const;
}
static DynExprId convert_expr(DynAstFunction *a, DynExprId source,
                              DynType target) {
  if (a->expression_count == a->expression_capacity) {
    size_t c = a->expression_capacity ? a->expression_capacity * 2 : 32;
    void *p = realloc(a->expressions, c * sizeof(*a->expressions));
    if (!p)
      return DYN_NO_EXPR;
    a->expressions = p;
    a->expression_capacity = c;
  }
  DynExprId id = (DynExprId)a->expression_count;
  a->expressions[a->expression_count++] = (DynAstExpr){.kind = DYN_EXPR_CONVERT,
                                                       .type = target,
                                                       .left = source,
                                                       .right = DYN_NO_EXPR};
  return id;
}
typedef struct {
  bool valid, overflow;
  int64_t value;
} ConstantInt;
typedef struct {
  bool valid, overflow;
  uint64_t value;
} ConstantUInt;
static ConstantInt constant_int(DynAstFunction *a, DynExprId id) {
  if (id == DYN_NO_EXPR)
    return (ConstantInt){0};
  DynAstExpr *e = &a->expressions[id];
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_CHAR) {
    if (e->integer > INT64_MAX)
      return (ConstantInt){.overflow = true};
    return (ConstantInt){.valid = true, .value = (int64_t)e->integer};
  }
  if (e->kind == DYN_EXPR_UNARY) {
    if (e->op == DYN_OP_NEG && e->boolean &&
        a->expressions[e->left].kind == DYN_EXPR_INT) {
      uint64_t magnitude = a->expressions[e->left].integer;
      return (ConstantInt){.valid = true,
                           .value = magnitude == UINT64_C(1) << 63
                                        ? INT64_MIN
                                        : -(int64_t)magnitude};
    }
    ConstantInt x = constant_int(a, e->left);
    if (!x.valid)
      return x;
    if (e->op == DYN_OP_NEG) {
      if (x.value == INT64_MIN)
        return (ConstantInt){.overflow = true};
      x.value = -x.value;
    } else if (e->op == DYN_OP_BIT_NOT)
      x.value = ~x.value;
    else
      x.valid = false;
    return x;
  }
  if (e->kind != DYN_EXPR_BINARY)
    return (ConstantInt){0};
  ConstantInt l = constant_int(a, e->left), r = constant_int(a, e->right);
  if (!l.valid || !r.valid)
    return (ConstantInt){.overflow = l.overflow || r.overflow};
  int64_t v = 0;
  bool overflow = false;
  switch (e->op) {
  case DYN_OP_ADD:
    overflow = (r.value > 0 && l.value > INT64_MAX - r.value) ||
               (r.value < 0 && l.value < INT64_MIN - r.value);
    if (!overflow)
      v = l.value + r.value;
    break;
  case DYN_OP_SUB:
    overflow = (r.value < 0 && l.value > INT64_MAX + r.value) ||
               (r.value > 0 && l.value < INT64_MIN + r.value);
    if (!overflow)
      v = l.value - r.value;
    break;
  case DYN_OP_MUL:
    if (l.value == 0 || r.value == 0)
      v = 0;
    else if ((l.value > 0 && r.value > 0 && l.value > INT64_MAX / r.value) ||
             (l.value > 0 && r.value < 0 && r.value < INT64_MIN / l.value) ||
             (l.value < 0 && r.value > 0 && l.value < INT64_MIN / r.value) ||
             (l.value < 0 && r.value < 0 && l.value < INT64_MAX / r.value))
      overflow = true;
    else
      v = l.value * r.value;
    break;
  case DYN_OP_DIV:
  case DYN_OP_REM:
    if (r.value == 0)
      return (ConstantInt){0};
    if (l.value == INT64_MIN && r.value == -1)
      overflow = true;
    else
      v = e->op == DYN_OP_DIV ? l.value / r.value : l.value % r.value;
    break;
  case DYN_OP_SHL:
    if (r.value < 0 || r.value >= 64)
      overflow = true;
    else if (l.value < 0 || l.value > (INT64_MAX >> r.value))
      overflow = true;
    else
      v = l.value << r.value;
    break;
  case DYN_OP_SHR:
    if (r.value < 0 || r.value >= 64)
      overflow = true;
    else
      v = l.value >> r.value;
    break;
  default:
    return (ConstantInt){0};
  }
  return (ConstantInt){.valid = !overflow, .overflow = overflow, .value = v};
}
static ConstantUInt constant_uint(DynAstFunction *a, DynExprId id) {
  if (id == DYN_NO_EXPR)
    return (ConstantUInt){0};
  DynAstExpr *e = &a->expressions[id];
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_CHAR)
    return (ConstantUInt){.valid = true, .value = e->integer};
  if (e->kind == DYN_EXPR_UNARY) {
    ConstantUInt x = constant_uint(a, e->left);
    if (!x.valid)
      return x;
    if (e->op == DYN_OP_BIT_NOT)
      x.value = ~x.value;
    else if (e->op == DYN_OP_NEG) {
      if (x.value)
        x.overflow = true;
      else
        x.value = 0;
    } else
      x.valid = false;
    return x;
  }
  if (e->kind != DYN_EXPR_BINARY)
    return (ConstantUInt){0};
  ConstantUInt l = constant_uint(a, e->left), r = constant_uint(a, e->right);
  if (!l.valid || !r.valid)
    return (ConstantUInt){.overflow = l.overflow || r.overflow};
  uint64_t v = 0;
  bool overflow = false;
  switch (e->op) {
  case DYN_OP_ADD:
    overflow = l.value > UINT64_MAX - r.value;
    if (!overflow)
      v = l.value + r.value;
    break;
  case DYN_OP_SUB:
    overflow = l.value < r.value;
    if (!overflow)
      v = l.value - r.value;
    break;
  case DYN_OP_MUL:
    overflow = l.value && r.value > UINT64_MAX / l.value;
    if (!overflow)
      v = l.value * r.value;
    break;
  case DYN_OP_DIV:
  case DYN_OP_REM:
    if (!r.value)
      return (ConstantUInt){0};
    v = e->op == DYN_OP_DIV ? l.value / r.value : l.value % r.value;
    break;
  case DYN_OP_SHL:
    overflow = r.value >= 64 || l.value > (UINT64_MAX >> r.value);
    if (!overflow)
      v = l.value << r.value;
    break;
  case DYN_OP_SHR:
    overflow = r.value >= 64;
    if (!overflow)
      v = l.value >> r.value;
    break;
  default:
    return (ConstantUInt){0};
  }
  return (ConstantUInt){.valid = !overflow, .overflow = overflow, .value = v};
}
static bool constant_fits_type(int64_t v, DynType t) {
  unsigned b = bits(t);
  if (signed_int(t)) {
    if (b == 64)
      return true;
    int64_t min = -(INT64_C(1) << (b - 1)), max = (INT64_C(1) << (b - 1)) - 1;
    return v >= min && v <= max;
  }
  if (!integer(t) || v < 0)
    return false;
  return b == 64 || ((uint64_t)v <= (UINT64_C(1) << b) - 1);
}
static bool lvalue_const(DynAstFunction *, DynExprId);
static bool span_is(DynSpan p, const DynSource *s, const char *name) {
  size_t n = strlen(name);
  return p.end_byte - p.start_byte == n &&
         !memcmp(s->text + p.start_byte, name, n);
}
static bool reserve_reflection_items(DynAstFunction *a, size_t extra) {
  if (a->item_count + extra <= a->item_capacity)
    return true;
  size_t c = a->item_capacity ? a->item_capacity * 2 : 16;
  while (c < a->item_count + extra)
    c *= 2;
  void *p = realloc(a->items, c * sizeof(*a->items));
  if (!p)
    return false;
  a->items = p;
  a->item_capacity = c;
  return true;
}
static bool reserve_reflection_string(DynAstFunction *a) {
  if (a->string_count < a->string_capacity)
    return true;
  size_t c = a->string_capacity ? a->string_capacity * 2 : 8;
  void *p = realloc(a->strings, c * sizeof(*a->strings));
  if (!p)
    return false;
  a->strings = p;
  a->string_capacity = c;
  return true;
}
static void type_name_into(DynAstFunction *a, DynType t, const DynSource *s,
                           char *out, size_t cap) {
  if (!cap)
    return;
  out[0] = 0;
  const char *basic = dyn_type_name(t);
  if (t < DYN_TYPE_STRUCT_BASE && basic && strcmp(basic, "unknown")) {
    snprintf(out, cap, "%s", basic);
    return;
  }
  if (dyn_type_is_struct(t) || dyn_type_is_enum(t)) {
    DynSpan p = dyn_type_is_struct(t)
                    ? a->structs[t - DYN_TYPE_STRUCT_BASE].name
                    : a->enums[t - DYN_TYPE_ENUM_BASE].name;
    size_t begin = p.start_byte, length = p.end_byte - p.start_byte;
    if (length > 22 && !memcmp(s->text + begin, "dyn_m", 5) &&
        s->text[begin + 21] == '_')
      begin += 22;
    size_t n = p.end_byte - begin;
    if (n >= cap)
      n = cap - 1;
    memcpy(out, s->text + begin, n);
    out[n] = 0;
    return;
  }
  char inner[384];
  if (dyn_type_is_pointer(t)) {
    DynAstPointer *p = pointer_info(a, t);
    type_name_into(a, p->pointee, s, inner, sizeof(inner));
    snprintf(out, cap, "*%s%s", p->is_const ? "const " : "", inner);
    return;
  }
  if (dyn_type_is_array(t)) {
    DynAstArray *ar = array_info(a, t);
    type_name_into(a, ar->element, s, inner, sizeof(inner));
    snprintf(out, cap, "[%llu]%s", (unsigned long long)ar->length, inner);
    return;
  }
  if (dyn_type_is_slice(t)) {
    DynAstSlice *sl = slice_info(a, t);
    type_name_into(a, sl->element, s, inner, sizeof(inner));
    snprintf(out, cap, "[]%s%s", sl->is_const ? "const " : "", inner);
    return;
  }
  if (dyn_type_is_function(t)) {
    DynAstFnType *fn = fn_type_info(a, t);
    size_t at = (size_t)snprintf(out, cap, "fn(");
    for (uint32_t i = 0; i < fn->param_count && at < cap; ++i) {
      type_name_into(a, a->fn_type_params[fn->param_start + i], s, inner,
                     sizeof(inner));
      at += (size_t)snprintf(out + at, cap - at, "%s%s", i ? ", " : "", inner);
    }
    if (at < cap) {
      type_name_into(a, fn->return_type, s, inner, sizeof(inner));
      snprintf(out + at, cap - at, ") %s", inner);
    }
    return;
  }
  snprintf(out, cap, "unknown");
}
static uint64_t reflection_id(const char *name) {
  uint64_t h = UINT64_C(1469598103934665603);
  for (const unsigned char *p = (const unsigned char *)name; *p; ++p) {
    h ^= *p;
    h *= UINT64_C(1099511628211);
  }
  return h;
}
static unsigned reflection_kind(DynType t) {
  if (t == DYN_TYPE_VOID)
    return 1;
  if (t == DYN_TYPE_BOOL)
    return 2;
  if (integer(t))
    return 3;
  if (t == DYN_TYPE_F32 || t == DYN_TYPE_F64)
    return 4;
  if (dyn_type_is_pointer(t))
    return 5;
  if (dyn_type_is_array(t))
    return 6;
  if (dyn_type_is_slice(t))
    return 7;
  if (dyn_type_is_struct(t))
    return 8;
  if (dyn_type_is_enum(t))
    return 9;
  if (dyn_type_is_function(t))
    return 10;
  return 0;
}
static void display_type_name(DynAstFunction *a, DynType t, const DynSource *s,
                              char *out, size_t cap) {
  if (!dyn_type_is_distinct(t)) {
    type_name_into(a, t, s, out, cap);
    return;
  }
  uint32_t id = t - DYN_TYPE_DISTINCT_BASE;
  if (id >= a->alias_count || !cap) {
    if (cap)
      out[0] = 0;
    return;
  }
  DynSpan p = a->aliases[id].name;
  size_t n = p.end_byte - p.start_byte;
  if (n >= cap)
    n = cap - 1;
  memcpy(out, s->text + p.start_byte, n);
  out[n] = 0;
}
#define type_name_into display_type_name
static DynExprId reflection_expr(DynAstFunction *a, DynExprKind kind,
                                 DynType type, uint64_t integer) {
  if (!reserve_expr(a))
    return DYN_NO_EXPR;
  DynExprId id = (DynExprId)a->expression_count;
  a->expressions[a->expression_count++] = (DynAstExpr){.kind = kind,
                                                       .type = type,
                                                       .left = DYN_NO_EXPR,
                                                       .right = DYN_NO_EXPR,
                                                       .integer = integer};
  return id;
}
static DynType check_expr(DynAstFunction *a, DynExprId id, const DynSource *s,
                          unsigned *errors, DynType expected) {
  if (id == DYN_NO_EXPR)
    return DYN_TYPE_VOID;
  DynAstExpr *e = &a->expressions[id];
  uint32_t qualified_enum = sema_expr_enum(a, e->left, s);
  if (e->kind == DYN_EXPR_ENUM && qualified_enum == UINT32_MAX) {
    e->kind = DYN_EXPR_INDIRECT_CALL;
    e->left = e->right;
    e->right = DYN_NO_EXPR;
  }
  if (e->kind == DYN_EXPR_ENUM ||
      (e->kind == DYN_EXPR_FIELD && qualified_enum != UINT32_MAX)) {
    uint32_t eid = qualified_enum,
             variant = sema_find_variant(a, eid, e->span, s);
    e->left = DYN_NO_EXPR;
    if (variant == UINT32_MAX) {
      error_span(e->span, s, errors, "unknown enum variant");
      return e->type = DYN_TYPE_ERROR;
    }
    DynAstVariant *v = &a->variants[variant];
    bool constructor = e->kind == DYN_EXPR_ENUM;
    e->kind = DYN_EXPR_ENUM;
    e->integer = variant;
    e->type = DYN_TYPE_ENUM_BASE + eid;
    if (v->payload_type == DYN_TYPE_VOID) {
      if (constructor || e->item_count)
        error_span(e->span, s, errors,
                   "payloadless enum variant is not callable");
    } else if (!constructor) {
      if (expected != e->type)
        error_span(e->span, s, errors,
                   "payload enum variant requires exactly one argument");
    } else if (e->item_count != 1)
      error_span(e->span, s, errors,
                 "payload enum variant requires exactly one argument");
    else {
      uint32_t item_start = e->item_start;
      DynSpan enum_span = e->span;
      DynAstItem *arg = &a->items[item_start];
      DynType value =
          check_expr(a, arg->expression, s, errors, v->payload_type);
      if (value != v->payload_type && value != DYN_TYPE_ERROR) {
        if (can_convert(a, value, v->payload_type))
          arg->expression = convert_expr(a, arg->expression, v->payload_type);
        else
          error_span(enum_span, s, errors, "enum payload type mismatch");
      }
    }
    return a->expressions[id].type;
  }
  if (e->kind == DYN_EXPR_CALL) {
    uint32_t fn = sema_find_function(a, e->span, s);
    if (fn == UINT32_MAX) {
      if (find_local(a, e->span, s) == UINT32_MAX &&
          find_global(a, e->span, s) == UINT32_MAX) {
        error_span(e->span, s, errors, "unknown function");
        return e->type = DYN_TYPE_ERROR;
      }
      DynSpan call_span = e->span;
      if (!reserve_expr(a)) {
        error_span(call_span, s, errors, "out of memory");
        return DYN_TYPE_ERROR;
      }
      DynExprId target = (DynExprId)a->expression_count;
      a->expressions[a->expression_count++] =
          (DynAstExpr){.kind = DYN_EXPR_NAME,
                       .type = DYN_TYPE_INFER,
                       .span = call_span,
                       .left = DYN_NO_EXPR,
                       .right = DYN_NO_EXPR};
      e = &a->expressions[id];
      e->left = target;
      e->kind = DYN_EXPR_INDIRECT_CALL;
    } else {
      e->left = DYN_NO_EXPR;
      e->integer = fn;
      DynAstFn *callee = &a->functions[fn];
      if ((!callee->variadic && e->item_count != callee->param_count) ||
          (callee->variadic && e->item_count < callee->param_count))
        error_span(e->span, s, errors, "function argument count mismatch");
      uint32_t count = e->item_count < callee->param_count
                           ? e->item_count
                           : callee->param_count;
      uint32_t item_start = e->item_start;
      DynType return_type = callee->return_type;
      for (uint32_t i = 0; i < count; ++i) {
        DynAstItem *arg = &a->items[item_start + i];
        DynType target = a->params[callee->param_start + i].type,
                value = check_expr(a, arg->expression, s, errors, target);
        if (value != target && value != DYN_TYPE_ERROR) {
          if (can_convert(a, value, target))
            arg->expression = convert_expr(a, arg->expression, target);
          else
            error_span(a->expressions[arg->expression].span, s, errors,
                       "function argument type mismatch");
        }
      }
      if (callee->variadic && callee->foreign)
        for (uint32_t i = callee->param_count; i < e->item_count; ++i) {
          DynAstItem *arg = &a->items[item_start + i];
          DynType value =
              check_expr(a, arg->expression, s, errors, DYN_TYPE_INFER);
          DynType promoted = value;
          if (value == DYN_TYPE_F32)
            promoted = DYN_TYPE_F64;
          else if (value == DYN_TYPE_I8 || value == DYN_TYPE_I16 ||
                   value == DYN_TYPE_U8 || value == DYN_TYPE_U16)
            promoted = DYN_TYPE_I32;
          if (promoted != value && value != DYN_TYPE_ERROR)
            arg->expression = convert_expr(a, arg->expression, promoted);
          else if (value != DYN_TYPE_I32 && value != DYN_TYPE_U32 &&
                   value != DYN_TYPE_I64 && value != DYN_TYPE_U64 &&
                   value != DYN_TYPE_ISIZE && value != DYN_TYPE_USIZE &&
                   value != DYN_TYPE_F64 && !dyn_type_is_pointer(value) &&
                   value != DYN_TYPE_ERROR)
            error_span(a->expressions[arg->expression].span, s, errors,
                       "C variadic argument requires integer, float, or pointer");
        }
      else if (callee->variadic)
        for (uint32_t i = callee->param_count; i < e->item_count; ++i) {
          DynAstItem *arg = &a->items[item_start + i];
          DynType element = slice_info(a, callee->variadic_type)->element;
          DynType value = check_expr(a, arg->expression, s, errors,
                                     element == DYN_TYPE_ANY ? DYN_TYPE_INFER : element);
          if (element != DYN_TYPE_ANY && value != element && value != DYN_TYPE_ERROR) {
            if (can_convert(a, value, element)) arg->expression = convert_expr(a, arg->expression, element);
            else error_span(a->expressions[arg->expression].span, s, errors,
                            "variadic argument type mismatch");
          }
        }
      return a->expressions[id].type = return_type;
    }
  }
  if (e->kind == DYN_EXPR_INDIRECT_CALL) {
    DynExprId target_expr = e->left;
    uint32_t item_start = e->item_start, item_count = e->item_count;
    DynSpan call_span = e->span;
    DynType target = check_expr(a, target_expr, s, errors, DYN_TYPE_INFER);
    DynAstPointer *p = pointer_info(a, target);
    DynAstFnType *signature = p ? fn_type_info(a, p->pointee) : NULL;
    if (!signature) {
      error_span(call_span, s, errors, "call target must be function pointer");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    if (item_count != signature->param_count)
      error_span(call_span, s, errors,
                 "function pointer argument count mismatch");
    uint32_t count = item_count < signature->param_count
                         ? item_count
                         : signature->param_count;
    for (uint32_t i = 0; i < count; ++i) {
      DynAstItem *arg = &a->items[item_start + i];
      DynType want = a->fn_type_params[signature->param_start + i],
              value = check_expr(a, arg->expression, s, errors, want);
      if (value != want && value != DYN_TYPE_ERROR) {
        if (can_convert(a, value, want))
          arg->expression = convert_expr(a, arg->expression, want);
        else
          error_span(a->expressions[arg->expression].span, s, errors,
                     "function pointer argument type mismatch");
      }
    }
    a->expressions[id].integer = p->pointee - DYN_TYPE_FN_BASE;
    return a->expressions[id].type = signature->return_type;
  }
  if (e->kind == DYN_EXPR_FUNCTION)
    return e->type;
  if (e->kind == DYN_EXPR_NAME) {
    uint32_t l = find_local(a, e->span, s);
    if (l != UINT32_MAX) {
      e->integer = l;
      return e->type = a->locals[l].type;
    }
    uint32_t global = find_global(a, e->span, s);
    if (global != UINT32_MAX) {
      e->kind = DYN_EXPR_GLOBAL;
      e->integer = global;
      return e->type = a->globals[global].type;
    }
    error_span(e->span, s, errors, "unknown name");
    return e->type = DYN_TYPE_ERROR;
  }
  if (e->kind == DYN_EXPR_ARRAY) {
    DynAstArray *want = array_info(a, expected);
    if (!e->item_count && !want) {
      error_span(e->span, s, errors,
                 "empty array literal requires expected fixed-array type");
      return e->type = DYN_TYPE_ERROR;
    }
    if (want && e->item_count > want->length) {
      error_span(e->span, s, errors, "array literal has too many elements");
      return e->type = DYN_TYPE_ERROR;
    }
    DynType element = want ? want->element : DYN_TYPE_INFER;
    for (uint32_t i = 0; i < e->item_count; ++i) {
      DynAstItem *item = &a->items[e->item_start + i];
      DynType value = check_expr(a, item->expression, s, errors, element);
      if (element == DYN_TYPE_INFER)
        element = value;
      else if (value != element && value != DYN_TYPE_ERROR) {
        if (can_convert(a, value, element))
          item->expression = convert_expr(a, item->expression, element);
        else
          error_span(a->expressions[item->expression].span, s, errors,
                     "array element type mismatch");
      }
    }
    return e->type =
               want ? expected : sema_intern_array(a, element, e->item_count);
  }
  if (e->kind == DYN_EXPR_INDEX) {
    DynType base = check_expr(a, e->left, s, errors, DYN_TYPE_INFER),
            index = check_expr(a, e->right, s, errors, DYN_TYPE_USIZE);
    if (!integer(index) || signed_int(index))
      error_span(e->span, s, errors, "array index requires unsigned integer");
    DynAstArray *ar = array_info(a, base);
    DynAstSlice *sl = slice_info(a, base);
    if (!ar && !sl) {
      error_span(e->span, s, errors, "indexing requires array or slice");
      return e->type = DYN_TYPE_ERROR;
    }
    return e->type = ar ? ar->element : sl->element;
  }
  if (e->kind == DYN_EXPR_SLICE) {
    DynType base = check_expr(a, e->left, s, errors, DYN_TYPE_INFER);
    DynAstArray *ar = array_info(a, base);
    DynAstSlice *sl = slice_info(a, base);
    DynAstPointer *pointer = pointer_info(a, base);
    if (!ar && !sl && !pointer) {
      error_span(e->span, s, errors,
                 "slicing requires array, slice, or pointer range");
      return e->type = DYN_TYPE_ERROR;
    }
    if (pointer && e->integer == DYN_NO_EXPR) {
      error_span(e->span, s, errors,
                 "pointer slicing requires explicit end bound");
      return e->type = DYN_TYPE_ERROR;
    }
    if (pointer && !sema_type_layout(a, pointer->pointee, false)) {
      error_span(e->span, s, errors, "cannot slice pointer to unsized type");
      return e->type = DYN_TYPE_ERROR;
    }
    if (e->right != DYN_NO_EXPR) {
      DynType t = check_expr(a, e->right, s, errors, DYN_TYPE_USIZE);
      if (!integer(t) || signed_int(t))
        error_span(e->span, s, errors, "slice bound requires unsigned integer");
    }
    if (e->integer != DYN_NO_EXPR) {
      DynType t =
          check_expr(a, (DynExprId)e->integer, s, errors, DYN_TYPE_USIZE);
      if (!integer(t) || signed_int(t))
        error_span(e->span, s, errors, "slice bound requires unsigned integer");
    }
    DynType element = ar ? ar->element : sl ? sl->element : pointer->pointee;
    return e->type = sema_intern_slice(
               a, element, sl ? sl->is_const : pointer && pointer->is_const);
  }
  if (e->kind == DYN_EXPR_LEN) {
    DynType base = check_expr(a, e->left, s, errors, DYN_TYPE_INFER);
    if (!dyn_type_is_array(base) && !dyn_type_is_slice(base)) {
      error_span(e->span, s, errors, "#len requires array or slice");
      return e->type = DYN_TYPE_ERROR;
    }
    return e->type = DYN_TYPE_USIZE;
  }
  if (e->kind == DYN_EXPR_VARIADIC) {
    if (current_function == UINT32_MAX ||
        !a->functions[current_function].variadic ||
        a->functions[current_function].foreign) {
      error_span(e->span, s, errors,
                 "#variadic is only valid inside a native variadic function");
      return e->type = DYN_TYPE_ERROR;
    }
    uint32_t arg = UINT32_MAX, kind = UINT32_MAX;
    for (uint32_t i = 0; i < a->struct_count; ++i)
      if (span_is(a->structs[i].name, s, "VariadicArg")) arg = i;
    for (uint32_t i = 0; i < a->enum_count; ++i)
      if (span_is(a->enums[i].name, s, "VariadicKind")) kind = i;
    if (arg == UINT32_MAX || kind == UINT32_MAX ||
        a->structs[arg].field_count != 2 ||
        a->fields[a->structs[arg].field_start].type != DYN_TYPE_ENUM_BASE + kind ||
        !dyn_type_is_pointer(a->fields[a->structs[arg].field_start + 1].type)) {
      error_span(e->span, s, errors, "compiler variadic ABI mismatch");
      return e->type = DYN_TYPE_ERROR;
    }
    e->type = sema_intern_slice(a, DYN_TYPE_STRUCT_BASE + arg, true);
    for (uint32_t i = 0; i < a->function_count; ++i)
      if (a->functions[i].variadic && !a->functions[i].foreign)
        a->functions[i].variadic_type = e->type;
    return e->type;
  }
  if (e->kind == DYN_EXPR_TYPEOF) {
    DynType operand;
    if (e->boolean)
      operand = (DynType)e->integer;
    else {
      DynAstExpr *source = &a->expressions[e->left];
      uint32_t fn = source->kind == DYN_EXPR_NAME
                        ? sema_find_function(a, source->span, s)
                        : UINT32_MAX;
      operand = fn == UINT32_MAX
                    ? check_expr(a, e->left, s, errors, DYN_TYPE_INFER)
                    : function_signature_type(a, fn);
    }
    uint32_t info = UINT32_MAX, kind_enum = UINT32_MAX;
    for (uint32_t i = 0; i < a->struct_count; ++i)
      if (span_is(a->structs[i].name, s, "TypeInfo"))
        info = i;
    for (uint32_t i = 0; i < a->enum_count; ++i)
      if (span_is(a->enums[i].name, s, "TypeKind"))
        kind_enum = i;
    if (info == UINT32_MAX || kind_enum == UINT32_MAX) {
      error_span(e->span, s, errors, "compiler reflection ABI is unavailable");
      return e->type = DYN_TYPE_ERROR;
    }
    DynAstStruct *st = &a->structs[info];
    DynAstEnum *en = &a->enums[kind_enum];
    bool abi =
        st->field_count == 5 && en->variant_count >= 11 &&
        a->fields[st->field_start].type == DYN_TYPE_U64 &&
        a->fields[st->field_start + 1].type == DYN_TYPE_ENUM_BASE + kind_enum &&
        a->fields[st->field_start + 3].type == DYN_TYPE_USIZE &&
        a->fields[st->field_start + 4].type == DYN_TYPE_USIZE;
    if (!abi) {
      error_span(e->span, s, errors, "compiler TypeInfo ABI mismatch");
      return e->type = DYN_TYPE_ERROR;
    }
    char name[512];
    type_name_into(a, operand, s, name, sizeof(name));
    size_t length = strlen(name);
    if (!reserve_reflection_string(a) || !reserve_reflection_items(a, 5)) {
      error_span(e->span, s, errors, "out of memory");
      return e->type = DYN_TYPE_ERROR;
    }
    unsigned char *bytes = malloc(length);
    if (length && !bytes) {
      error_span(e->span, s, errors, "out of memory");
      return e->type = DYN_TYPE_ERROR;
    }
    if (length)
      memcpy(bytes, name, length);
    uint32_t string = (uint32_t)a->string_count;
    a->strings[a->string_count++] = (DynAstString){bytes, length};
    uint32_t start = (uint32_t)a->item_count;
    DynExprId values[5];
    values[0] =
        reflection_expr(a, DYN_EXPR_INT, DYN_TYPE_U64, reflection_id(name));
    unsigned k = reflection_kind(operand);
    values[1] =
        reflection_expr(a, DYN_EXPR_ENUM, DYN_TYPE_ENUM_BASE + kind_enum,
                        en->variant_start + k);
    values[2] = reflection_expr(a, DYN_EXPR_STRING,
                                a->fields[st->field_start + 2].type, string);
    uint64_t size = operand == DYN_TYPE_VOID || dyn_type_is_function(operand)
                        ? 0
                        : sema_type_layout(a, operand, false),
             alignment =
                 operand == DYN_TYPE_VOID || dyn_type_is_function(operand)
                     ? 1
                     : sema_type_layout(a, operand, true);
    values[3] = reflection_expr(a, DYN_EXPR_INT, DYN_TYPE_USIZE, size);
    values[4] = reflection_expr(a, DYN_EXPR_INT, DYN_TYPE_USIZE, alignment);
    for (uint32_t i = 0; i < 5; ++i)
      a->items[a->item_count++] =
          (DynAstItem){.expression = values[i], .field_index = i};
    e = &a->expressions[id];
    e->kind = DYN_EXPR_STRUCT;
    e->type = DYN_TYPE_STRUCT_BASE + info;
    e->integer = info;
    e->left = e->right = DYN_NO_EXPR;
    e->item_start = start;
    e->item_count = 5;
    return e->type;
  }
  if (e->kind == DYN_EXPR_SIZE || e->kind == DYN_EXPR_ALIGN) {
    DynType operand = e->boolean
                          ? (DynType)e->integer
                          : check_expr(a, e->left, s, errors, DYN_TYPE_INFER);
    uint64_t value = sema_type_layout(a, operand, e->kind == DYN_EXPR_ALIGN);
    if (!value) {
      error_span(e->span, s, errors,
                 e->kind == DYN_EXPR_ALIGN
                     ? "#alignof requires sized value or type"
                     : "#sizeof requires sized value or type");
      return e->type = DYN_TYPE_ERROR;
    }
    e->kind = DYN_EXPR_INT;
    e->integer = value;
    return e->type = DYN_TYPE_USIZE;
  }
  if (e->kind == DYN_EXPR_CAST) {
    DynType source = check_expr(a, e->left, s, errors, DYN_TYPE_INFER),
            target = (DynType)e->integer;
    bool source_ptr = dyn_type_is_pointer(source) || source == DYN_TYPE_RAWPTR;
    bool target_ptr = dyn_type_is_pointer(target) || target == DYN_TYPE_RAWPTR;
    bool valid = (numeric(source) && numeric(target)) ||
                 (source_ptr && target_ptr) || (source_ptr && integer(target)) ||
                 (integer(source) && target_ptr) ||
                 source == target;
    if (!valid) {
      error_span(e->span, s, errors, "invalid explicit cast");
      return e->type = DYN_TYPE_ERROR;
    }
    return e->type = target;
  }
  if (e->kind == DYN_EXPR_BITCAST) {
    DynType source = check_expr(a, e->left, s, errors, DYN_TYPE_INFER),
            target = (DynType)e->integer;
    bool scalar = (numeric(source) || dyn_type_is_pointer(source)) &&
                  (numeric(target) || dyn_type_is_pointer(target));
    uint64_t from = sema_type_layout(a, source, false),
             to = sema_type_layout(a, target, false);
    if (!scalar || !from || from != to ||
        (dyn_type_is_pointer(source) != dyn_type_is_pointer(target))) {
      error_span(e->span, s, errors,
                 "#bitcast requires compatible scalar representation sizes");
      return e->type = DYN_TYPE_ERROR;
    }
    return e->type = target;
  }
  if (e->kind == DYN_EXPR_SYSCALL) {
    if (e->item_count < 1 || e->item_count > 7)
      error_span(e->span, s, errors,
                 "#syscall requires syscall number and at most six arguments");
    for (uint32_t i = 0; i < e->item_count; ++i) {
      DynType t = check_expr(a, a->items[e->item_start + i].expression, s,
                             errors, DYN_TYPE_INFER);
      if (!integer(t) && !dyn_type_is_pointer(t))
        error_span(a->expressions[a->items[e->item_start + i].expression].span,
                   s, errors, "#syscall arguments require integer or pointer");
    }
    return e->type = DYN_TYPE_ISIZE;
  }
  if (e->kind == DYN_EXPR_CONVERT)
    return e->type;
  if (e->kind == DYN_EXPR_NIL) {
    if (!dyn_type_is_pointer(expected) && expected != DYN_TYPE_RAWPTR) {
      error_span(e->span, s, errors, "nil requires expected pointer type");
      return e->type = DYN_TYPE_ERROR;
    }
    return e->type = expected;
  }
  if (e->kind == DYN_EXPR_STRUCT) {
    uint32_t sid = e->boolean && dyn_type_is_struct(expected)
                       ? expected - DYN_TYPE_STRUCT_BASE
                       : sema_find_struct(a, e->span, s);
    if (sid == UINT32_MAX || sid >= a->struct_count) {
      error_span(e->span, s, errors,
                 e->boolean
                     ? "inferred struct literal requires expected struct type"
                     : "unknown struct type");
      return e->type = DYN_TYPE_ERROR;
    }
    e->integer = sid;
    e->type = DYN_TYPE_STRUCT_BASE + sid;
    DynAstStruct *st = &a->structs[sid];
    for (uint32_t i = 0; i < e->item_count; ++i) {
      DynAstItem *item = &a->items[e->item_start + i];
      uint32_t field = sema_find_field(a, sid, item->name, s);
      if (field == UINT32_MAX) {
        error_span(item->name, s, errors, "unknown struct field");
        continue;
      }
      item->field_index = field;
      for (uint32_t j = 0; j < i; ++j)
        if (dyn_span_text_equal(item->name, a->items[e->item_start + j].name,
                                s))
          error_span(item->name, s, errors, "duplicate struct literal field");
      DynType target = a->fields[st->field_start + field].type;
      DynType value = check_expr(a, item->expression, s, errors, target);
      if (value != target && value != DYN_TYPE_ERROR) {
        if (can_convert(a, value, target))
          item->expression = convert_expr(a, item->expression, target);
        else
          error_span(item->name, s, errors,
                     "struct field initializer type mismatch");
      }
    }
    return e->type;
  }
  if (e->kind == DYN_EXPR_FIELD) {
    DynType base = check_expr(a, e->left, s, errors, DYN_TYPE_INFER);
    if (dyn_type_is_pointer(base)) {
      DynAstPointer *p = pointer_info(a, base);
      base = p ? p->pointee : DYN_TYPE_ERROR;
      e->boolean = true;
    }
    if (!dyn_type_is_struct(base)) {
      error_span(e->span, s, errors,
                 "field access requires struct or struct pointer");
      return e->type = DYN_TYPE_ERROR;
    }
    uint32_t sid = base - DYN_TYPE_STRUCT_BASE,
             field = sema_find_field(a, sid, e->span, s);
    if (field == UINT32_MAX) {
      error_span(e->span, s, errors, "unknown struct field");
      return e->type = DYN_TYPE_ERROR;
    }
    e->integer = field;
    return e->type = a->fields[a->structs[sid].field_start + field].type;
  }
  if (e->kind == DYN_EXPR_INT) {
    if (expected != DYN_TYPE_INFER && !dyn_type_is_distinct(expected) &&
        integer(expected)) {
      if (!literal_fits(e->integer, expected)) {
        error_span(e->span, s, errors,
                   "integer literal is not representable in expected type");
        return e->type = DYN_TYPE_ERROR;
      }
      return e->type = expected;
    }
    if (e->integer > INT32_MAX) {
      error_span(e->span, s, errors,
                 "integer literal does not fit default i32");
      return e->type = DYN_TYPE_ERROR;
    }
    return e->type = DYN_TYPE_I32;
  }
  if (e->kind == DYN_EXPR_FLOAT) {
    return e->type = expected == DYN_TYPE_F64 ? DYN_TYPE_F64 : DYN_TYPE_F32;
  }
  if (e->kind == DYN_EXPR_CHAR) {
    DynType t = expected == DYN_TYPE_U8 || expected == DYN_TYPE_U16 ||
                        expected == DYN_TYPE_U32
                    ? expected
                    : (e->integer <= 255 ? DYN_TYPE_U8 : DYN_TYPE_U32);
    if (!literal_fits(e->integer, t)) {
      error_span(e->span, s, errors,
                 "character literal is not representable in expected type");
      return e->type = DYN_TYPE_ERROR;
    }
    return e->type = t;
  }
  if (e->kind == DYN_EXPR_STRING) {
    if (expected == DYN_TYPE_INFER)
      return e->type = sema_intern_slice(a, DYN_TYPE_U8, true);
    DynAstSlice *target = slice_info(a, expected);
    if (!target || target->element != DYN_TYPE_U8 || !target->is_const) {
      error_span(e->span, s, errors,
                 "string literal requires expected []const u8 type");
      return e->type = DYN_TYPE_ERROR;
    }
    return e->type = expected;
  }
  if (e->kind == DYN_EXPR_BOOL)
    return e->type;
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_NEG &&
      !dyn_type_is_distinct(expected) && signed_int(expected) &&
      a->expressions[e->left].kind == DYN_EXPR_INT) {
    DynAstExpr *operand = &a->expressions[e->left];
    unsigned width = bits(expected);
    uint64_t limit =
        width == 64 ? (UINT64_C(1) << 63) : (UINT64_C(1) << (width - 1));
    if (operand->integer > limit) {
      error_span(e->span, s, errors,
                 "negative literal is not representable in expected type");
      return e->type = DYN_TYPE_ERROR;
    }
    operand->type = expected;
    e->boolean = true;
    return e->type = expected;
  }
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_ADDRESS) {
    DynAstExpr *operand = &a->expressions[e->left];
    if (operand->kind == DYN_EXPR_NAME) {
      uint32_t fn = sema_find_function(a, operand->span, s);
      if (fn != UINT32_MAX) {
        if (a->functions[fn].variadic) {
          error_span(e->span, s, errors,
                     "variadic function pointers are not implemented");
          return e->type = DYN_TYPE_ERROR;
        }
        e->kind = DYN_EXPR_FUNCTION;
        e->op = DYN_OP_NONE;
        e->integer = fn;
        e->left = DYN_NO_EXPR;
        return e->type = function_pointer_type(a, fn);
      }
    }
    DynType value = check_expr(a, e->left, s, errors, DYN_TYPE_INFER);
    DynExprKind kind = a->expressions[e->left].kind;
    if (kind != DYN_EXPR_NAME && kind != DYN_EXPR_GLOBAL &&
        kind != DYN_EXPR_FIELD && kind != DYN_EXPR_INDEX &&
        !(kind == DYN_EXPR_UNARY &&
          a->expressions[e->left].op == DYN_OP_DEREF)) {
      error_span(e->span, s, errors,
                 "address operand must be assignable storage or function");
      return e->type = DYN_TYPE_ERROR;
    }
    return e->type = sema_intern_pointer(a, value, lvalue_const(a, e->left));
  }
  DynType left =
      a->expressions[e->left].kind == DYN_EXPR_NIL && e->kind == DYN_EXPR_BINARY
          ? check_expr(a, e->left, s, errors,
                       check_expr(a, e->right, s, errors, DYN_TYPE_INFER))
          : check_expr(a, e->left, s, errors, expected);
  if (e->kind == DYN_EXPR_UNARY) {
    if (e->op == DYN_OP_DEREF) {
      DynAstPointer *p = pointer_info(a, left);
      if (!p) {
        error_span(e->span, s, errors, "dereference requires pointer");
        return e->type = DYN_TYPE_ERROR;
      }
      if (p->pointee == DYN_TYPE_VOID) {
        error_span(e->span, s, errors,
                   "raw *void pointer cannot be dereferenced");
        return e->type = DYN_TYPE_ERROR;
      }
      return e->type = p->pointee;
    }
    if (e->op == DYN_OP_NOT && left != DYN_TYPE_BOOL)
      error_span(e->span, s, errors, "! requires bool");
    else if (e->op == DYN_OP_BIT_NOT && !integer(left))
      error_span(e->span, s, errors, "~ requires integer");
    else if (e->op == DYN_OP_NEG && !numeric(left))
      error_span(e->span, s, errors, "unary - requires numeric type");
    return e->type = left;
  }
  if (e->op == DYN_OP_SHL || e->op == DYN_OP_SHR) {
    DynType right = check_expr(a, e->right, s, errors, DYN_TYPE_USIZE);
    if (!integer(left) || !integer(right) || signed_int(right)) {
      error_span(e->span, s, errors, "shift count requires unsigned integer");
      return e->type = DYN_TYPE_ERROR;
    }
    ConstantUInt rhs = constant_uint(a, e->right);
    if (rhs.valid && rhs.value >= bits(left)) {
      error_span(e->span, s, errors, "invalid constant shift count");
      return e->type = DYN_TYPE_ERROR;
    }
    return e->type = left;
  }
  DynType right = check_expr(a, e->right, s, errors, left);
  if (left == DYN_TYPE_ERROR || right == DYN_TYPE_ERROR)
    return e->type = DYN_TYPE_ERROR;
  if (left != right && dyn_type_is_pointer(left) &&
      dyn_type_is_pointer(right) &&
      (e->op == DYN_OP_EQ || e->op == DYN_OP_NE)) {
    if (can_convert(a, left, right)) {
      e->left = convert_expr(a, e->left, right);
      left = right;
    } else if (can_convert(a, right, left)) {
      e->right = convert_expr(a, e->right, left);
      right = left;
    }
  }
  if (left != right) {
    error_span(e->span, s, errors, "mixed operand types require explicit cast");
    return e->type = DYN_TYPE_ERROR;
  }
  if (e->op == DYN_OP_LOGICAL_AND || e->op == DYN_OP_LOGICAL_OR) {
    if (left != DYN_TYPE_BOOL)
      error_span(e->span, s, errors, "logical operators require bool");
    return e->type = DYN_TYPE_BOOL;
  }
  if (e->op >= DYN_OP_EQ && e->op <= DYN_OP_GE) {
    if (left == DYN_TYPE_STRING || dyn_type_is_struct(left) ||
        dyn_type_is_array(left) || dyn_type_is_slice(left) ||
        (dyn_type_is_enum(left) &&
         a->enums[left - DYN_TYPE_ENUM_BASE].has_payload)) {
      error_span(e->span, s, errors, "aggregate values are not comparable");
      return e->type = DYN_TYPE_ERROR;
    }
    if ((dyn_type_is_pointer(left) || dyn_type_is_enum(left)) &&
        e->op != DYN_OP_EQ && e->op != DYN_OP_NE) {
      error_span(e->span, s, errors,
                 dyn_type_is_enum(left) ? "enums support equality only"
                                        : "pointers support equality only");
      return e->type = DYN_TYPE_ERROR;
    }
    return e->type = DYN_TYPE_BOOL;
  }
  if (e->op == DYN_OP_BIT_AND || e->op == DYN_OP_BIT_OR ||
      e->op == DYN_OP_BIT_XOR) {
    if (!integer(left) && left != DYN_TYPE_BOOL)
      error_span(e->span, s, errors,
                 "bitwise operators require integer or bool");
    return e->type = left;
  }
  if (!numeric(left))
    error_span(e->span, s, errors, "arithmetic requires numeric operands");
  if (integer(left)) {
    ConstantUInt rhs = constant_uint(a, e->right);
    if ((e->op == DYN_OP_DIV || e->op == DYN_OP_REM) && rhs.valid &&
        rhs.value == 0) {
      error_span(e->span, s, errors, "invalid constant division by zero");
      return e->type = DYN_TYPE_ERROR;
    }
    if (signed_int(left)) {
      ConstantInt all = constant_int(a, id);
      if (all.overflow || (all.valid && !constant_fits_type(all.value, left))) {
        error_span(e->span, s, errors,
                   "constant arithmetic overflows result type");
        return e->type = DYN_TYPE_ERROR;
      }
    } else {
      ConstantUInt all = constant_uint(a, id);
      unsigned width = bits(left);
      if (all.overflow || (all.valid && width < 64 &&
                           all.value > ((UINT64_C(1) << width) - 1))) {
        error_span(e->span, s, errors,
                   "constant arithmetic overflows result type");
        return e->type = DYN_TYPE_ERROR;
      }
    }
  }
  return e->type = left;
}
static bool lvalue_const(DynAstFunction *a, DynExprId id) {
  if (id == DYN_NO_EXPR)
    return false;
  DynAstExpr *e = &a->expressions[id];
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_DEREF) {
    DynAstPointer *p = pointer_info(a, a->expressions[e->left].type);
    return p && p->is_const;
  }
  if (e->kind == DYN_EXPR_FIELD) {
    DynType base = a->expressions[e->left].type;
    if (dyn_type_is_pointer(base)) {
      DynAstPointer *p = pointer_info(a, base);
      return p && p->is_const;
    }
    return lvalue_const(a, e->left);
  }
  if (e->kind == DYN_EXPR_INDEX) {
    DynAstSlice *sl = slice_info(a, a->expressions[e->left].type);
    return sl ? sl->is_const : lvalue_const(a, e->left);
  }
  return false;
}
static bool sema_block(DynAstFunction *, uint32_t, uint32_t, const DynSource *,
                       unsigned *, bool);
static bool mutable_case_subject(DynAstFunction *a, DynExprId id) {
  if (id == DYN_NO_EXPR)
    return false;
  DynAstExpr *e = &a->expressions[id];
  if (e->kind == DYN_EXPR_NAME)
    return true;
  if (e->kind == DYN_EXPR_GLOBAL)
    return e->integer < a->global_count && !a->globals[e->integer].is_const;
  if (e->kind == DYN_EXPR_FIELD) {
    DynAstPointer *p = pointer_info(a, a->expressions[e->left].type);
    return p ? !p->is_const : mutable_case_subject(a, e->left);
  }
  if (e->kind == DYN_EXPR_INDEX) {
    DynAstSlice *sl = slice_info(a, a->expressions[e->left].type);
    return sl ? !sl->is_const : mutable_case_subject(a, e->left);
  }
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_DEREF) {
    DynAstPointer *p = pointer_info(a, a->expressions[e->left].type);
    return p && !p->is_const;
  }
  return false;
}
static void validate_pointer_case_bindings(DynAstFunction *a, DynAstStmt *st,
                                           const DynSource *s,
                                           unsigned *errors) {
  for (uint32_t i = 0; i < st->case_arm_count; ++i) {
    DynAstCaseArm *arm = &a->case_arms[st->case_arm_start + i];
    if (arm->pointer_binding && !mutable_case_subject(a, st->expression))
      error_span(
          arm->binding, s, errors,
          "pointer payload binding requires mutable assignable case subject");
  }
}
static bool valid_defer_stmt(DynAstFunction *a, uint32_t id, const DynSource *s,
                             unsigned *errors) {
  DynAstStmt *st = &a->statements[id];
  if (st->kind == DYN_STMT_RETURN || st->kind == DYN_STMT_BREAK ||
      st->kind == DYN_STMT_CONTINUE || st->kind == DYN_STMT_LOCAL ||
      st->kind == DYN_STMT_DEFER) {
    error_span(st->span, s, errors,
               "deferred block cannot contain control transfer, declaration, "
               "or nested defer");
    return false;
  }
  bool ok = true;
  for (uint32_t i = 0; i < st->body_count; ++i)
    ok = valid_defer_stmt(a, a->children[st->body_start + i], s, errors) && ok;
  for (uint32_t i = 0; i < st->else_count; ++i)
    ok = valid_defer_stmt(a, a->children[st->else_start + i], s, errors) && ok;
  if (st->kind == DYN_STMT_CASE)
    for (uint32_t i = 0; i < st->case_arm_count; ++i) {
      DynAstCaseArm *arm = &a->case_arms[st->case_arm_start + i];
      for (uint32_t j = 0; j < arm->body_count; ++j)
        ok = valid_defer_stmt(a, a->children[arm->body_start + j], s, errors) &&
             ok;
    }
  return ok;
}
static bool compile_time_expr_depth(DynAstFunction *a, DynExprId id,
                                    size_t depth) {
  if (id == DYN_NO_EXPR || depth > a->global_count + 1)
    return false;
  DynAstExpr *e = &a->expressions[id];
  if (e->kind == DYN_EXPR_FUNCTION || e->kind == DYN_EXPR_INT ||
      e->kind == DYN_EXPR_FLOAT || e->kind == DYN_EXPR_BOOL ||
      e->kind == DYN_EXPR_CHAR || e->kind == DYN_EXPR_STRING ||
      e->kind == DYN_EXPR_NIL)
    return true;
  if (e->kind == DYN_EXPR_GLOBAL) {
    uint32_t g = (uint32_t)e->integer;
    return g < a->global_count && a->globals[g].is_const &&
           compile_time_expr_depth(a, a->globals[g].initializer, depth + 1);
  }
  if (e->kind == DYN_EXPR_CONVERT)
    return compile_time_expr_depth(a, e->left, depth + 1);
  if (e->kind == DYN_EXPR_UNARY && e->op != DYN_OP_ADDRESS &&
      e->op != DYN_OP_DEREF)
    return compile_time_expr_depth(a, e->left, depth + 1);
  if (e->kind == DYN_EXPR_BINARY)
    return compile_time_expr_depth(a, e->left, depth + 1) &&
           compile_time_expr_depth(a, e->right, depth + 1);
  if (e->kind == DYN_EXPR_STRUCT || e->kind == DYN_EXPR_ARRAY) {
    for (uint32_t i = 0; i < e->item_count; ++i)
      if (!compile_time_expr_depth(a, a->items[e->item_start + i].expression,
                                   depth + 1))
        return false;
    return true;
  }
  return false;
}
static bool compile_time_expr(DynAstFunction *a, DynExprId id) {
  return id != DYN_NO_EXPR && a->expressions[id].kind == DYN_EXPR_FUNCTION
             ? true
             : compile_time_expr_depth(a, id, 0);
}
static bool interval_overlap(const DynAstPattern *a, const DynAstPattern *b) {
  if (a->is_signed) {
    int64_t af = (int64_t)a->first_value, al = (int64_t)a->last_value,
            bf = (int64_t)b->first_value, bl = (int64_t)b->last_value;
    return af <= bl && bf <= al;
  }
  return a->first_value <= b->last_value && b->first_value <= a->last_value;
}
static bool integer_case_complete(DynAstFunction *a, DynAstStmt *st,
                                  DynType type) {
  bool sign = signed_int(type);
  unsigned width = bits(type);
  uint64_t cursor = sign
                        ? (uint64_t)(width == 64 ? INT64_MIN
                                                 : -(INT64_C(1) << (width - 1)))
                        : 0,
           max = sign
                     ? (uint64_t)(width == 64 ? INT64_MAX
                                              : (INT64_C(1) << (width - 1)) - 1)
                     : (width == 64 ? UINT64_MAX : (UINT64_C(1) << width) - 1);
  for (;;) {
    DynAstPattern *found = NULL;
    for (uint32_t i = 0; i < st->case_arm_count && !found; ++i) {
      DynAstCaseArm *arm = &a->case_arms[st->case_arm_start + i];
      for (uint32_t j = 0; j < arm->pattern_count; ++j) {
        DynAstPattern *p = &a->patterns[arm->pattern_start + j];
        if (p->first_value == cursor) {
          found = p;
          break;
        }
      }
    }
    if (!found)
      return false;
    if (found->last_value == max)
      return true;
    if (sign && (int64_t)found->last_value == INT64_MAX)
      return false;
    if (!sign && found->last_value == UINT64_MAX)
      return false;
    cursor = found->last_value + 1;
  }
}
static bool sema_case_v2(DynAstFunction *a, DynAstStmt *st, const DynSource *s,
                         unsigned *errors) {
  DynType subject = check_expr(a, st->expression, s, errors, DYN_TYPE_INFER);
  bool enum_case = dyn_type_is_enum(subject), integer_case = integer(subject);
  if (subject == DYN_TYPE_ANY) {
    bool wildcard = false, all_terminate = true;
    for (uint32_t i = 0; i < st->case_arm_count; ++i) {
      DynAstCaseArm *arm = &a->case_arms[st->case_arm_start + i];
      if (arm->wildcard) { if (wildcard) error_span(arm->span, s, errors, "duplicate _ case arm"); wildcard = true; }
      else if (arm->pattern_count != 1 || !a->patterns[arm->pattern_start].is_type)
        error_span(arm->span, s, errors, "any case arm requires an is type pattern");
      else {
        DynAstPattern *p = &a->patterns[arm->pattern_start];
        for (uint32_t q = 0; q < i; ++q) {
          DynAstCaseArm *old = &a->case_arms[st->case_arm_start + q];
          if (!old->wildcard && old->pattern_count && a->patterns[old->pattern_start].is_type &&
              a->patterns[old->pattern_start].type == p->type)
            error_span(p->span, s, errors, "duplicate any type pattern");
        }
        if (arm->binding.end_byte > arm->binding.start_byte && reserve_local(a)) {
          arm->local_id = (uint32_t)a->local_count;
          a->locals[a->local_count++] = (DynAstLocal){.name = arm->binding,
            .type = p->type, .active = true, .owner_function = current_function};
        }
      }
      all_terminate = sema_block(a, arm->body_start, arm->body_count, s, errors, true) && all_terminate;
      if (arm->local_id != UINT32_MAX) a->locals[arm->local_id].active = false;
    }
    if (!wildcard) error_span(st->span, s, errors, "any case requires _ arm");
    return all_terminate;
  }
  if (!enum_case && !integer_case) {
    error_span(st->span, s, errors, "case requires integer or enum value");
    return false;
  }
  bool wildcard = false, all_terminate = true;
  DynAstEnum *en = enum_case ? &a->enums[subject - DYN_TYPE_ENUM_BASE] : NULL;
  bool *seen = enum_case ? calloc(en->variant_count, 1) : NULL;
  for (uint32_t i = 0; i < st->case_arm_count; ++i) {
    DynAstCaseArm *arm = &a->case_arms[st->case_arm_start + i];
    if (arm->wildcard) {
      if (wildcard)
        error_span(arm->span, s, errors, "duplicate _ case arm");
      wildcard = true;
    }
    for (uint32_t j = 0; j < arm->pattern_count; ++j) {
      DynAstPattern *p = &a->patterns[arm->pattern_start + j];
      if (enum_case) {
        if (p->range) {
          error_span(p->span, s, errors, "enum case pattern cannot be a range");
          continue;
        }
        DynType t = check_expr(a, p->first, s, errors, subject);
        DynAstExpr *pe = &a->expressions[p->first];
        if (t != subject || pe->kind != DYN_EXPR_ENUM) {
          error_span(p->span, s, errors, "case enum pattern type mismatch");
          continue;
        }
        p->is_enum = true;
        p->variant = (uint32_t)pe->integer;
        uint32_t relative = p->variant - en->variant_start;
        if (seen[relative])
          error_span(p->span, s, errors,
                     "duplicate or overlapping case pattern");
        seen[relative] = true;
      } else {
        p->is_signed = signed_int(subject);
        DynType t = check_expr(a, p->first, s, errors, subject);
        bool valid = t == subject;
        if (p->is_signed) {
          ConstantInt lo = constant_int(a, p->first);
          valid = valid && lo.valid;
          p->first_value = (uint64_t)lo.value;
          p->last_value = p->first_value;
          if (p->range) {
            DynType ht = check_expr(a, p->last, s, errors, subject);
            ConstantInt hi = constant_int(a, p->last);
            valid = valid && ht == subject && hi.valid;
            if (valid && (!p->inclusive && hi.value == INT64_MIN))
              valid = false;
            else if (valid)
              p->last_value = (uint64_t)(hi.value - (p->inclusive ? 0 : 1));
          }
        } else {
          ConstantUInt lo = constant_uint(a, p->first);
          valid = valid && lo.valid;
          p->first_value = lo.value;
          p->last_value = lo.value;
          if (p->range) {
            DynType ht = check_expr(a, p->last, s, errors, subject);
            ConstantUInt hi = constant_uint(a, p->last);
            valid = valid && ht == subject && hi.valid;
            if (valid && !p->inclusive && hi.value == 0)
              valid = false;
            else if (valid)
              p->last_value = hi.value - (p->inclusive ? 0 : 1);
          }
        }
        if (!valid) {
          error_span(p->span, s, errors,
                     "case pattern must be compile-time integer constant");
          continue;
        }
        if ((p->is_signed &&
             (int64_t)p->last_value < (int64_t)p->first_value) ||
            (!p->is_signed && p->last_value < p->first_value)) {
          error_span(p->span, s, errors, "case range is empty or reversed");
          continue;
        }
        for (uint32_t ai = 0; ai <= i; ++ai) {
          DynAstCaseArm *old = &a->case_arms[st->case_arm_start + ai];
          uint32_t limit = ai == i ? j : old->pattern_count;
          for (uint32_t q = 0; q < limit; ++q) {
            DynAstPattern *other = &a->patterns[old->pattern_start + q];
            if (interval_overlap(p, other))
              error_span(p->span, s, errors,
                         "duplicate or overlapping case pattern");
          }
        }
      }
    }
    bool binding = arm->binding.end_byte > arm->binding.start_byte;
    if (binding) {
      if (!enum_case || arm->wildcard || arm->pattern_count != 1 ||
          !a->patterns[arm->pattern_start].is_enum)
        error_span(arm->binding, s, errors,
                   "payload binding requires one enum variant pattern");
      else {
        DynAstVariant *v =
            &a->variants[a->patterns[arm->pattern_start].variant];
        if (v->payload_type == DYN_TYPE_VOID)
          error_span(arm->binding, s, errors,
                     "payloadless variant cannot bind payload");
        else if (find_any_local(a, arm->binding, s) != UINT32_MAX)
          error_span(arm->binding, s, errors,
                     "shadowing or duplicate local is forbidden");
        else if (reserve_local(a)) {
          arm->local_id = (uint32_t)a->local_count;
          a->locals[a->local_count++] = (DynAstLocal){
              .name = arm->binding, .type = v->payload_type, .active = true,
              .owner_function = current_function};
        }
      }
    }
    all_terminate =
        sema_block(a, arm->body_start, arm->body_count, s, errors, true) &&
        all_terminate;
    if (arm->local_id != UINT32_MAX)
      a->locals[arm->local_id].active = false;
  }
  bool complete;
  if (enum_case) {
    complete = true;
    for (uint32_t i = 0; i < en->variant_count; ++i)
      complete = complete && seen[i];
    free(seen);
  } else
    complete = integer_case_complete(a, st, subject);
  if (wildcard && complete)
    error_span(st->span, s, errors,
               "_ case arm is unreachable because all cases are covered");
  else if (!wildcard && !complete)
    error_span(st->span, s, errors, "case is not exhaustive");
  return all_terminate;
}
static bool sema_stmt(DynAstFunction *a, DynAstStmt *st, const DynSource *s,
                      unsigned *errors) {
  if (st->kind == DYN_STMT_INVALID)
    return false;
  if (st->kind == DYN_STMT_DEFER) {
    bool valid = true;
    for (uint32_t i = 0; i < st->body_count; ++i)
      valid = valid_defer_stmt(a, a->children[st->body_start + i], s, errors) &&
              valid;
    if (valid)
      (void)sema_block(a, st->body_start, st->body_count, s, errors, true);
    return false;
  }
  if (st->kind == DYN_STMT_PANIC) {
    DynType message_type = sema_intern_slice(a, DYN_TYPE_U8, true);
    DynType value =
        check_expr(a, st->expression, s, errors, message_type);
    if (value != message_type && value != DYN_TYPE_ERROR) {
      if (can_convert(a, value, message_type))
        st->expression = convert_expr(a, st->expression, message_type);
      else
        error_span(st->span, s, errors,
                   "#panic message requires []const u8");
    }
    return true;
  }
  if (st->kind == DYN_STMT_CASE) {
    validate_pointer_case_bindings(a, st, s, errors);
    return sema_case_v2(a, st, s, errors);
  }
  if (st->kind == DYN_STMT_RETURN) {
    if (current_return_type == DYN_TYPE_VOID) {
      if (st->expression != DYN_NO_EXPR)
        error_span(st->span, s, errors, "void function cannot return a value");
    } else if (st->expression == DYN_NO_EXPR)
      error_span(st->span, s, errors, "non-void function must return a value");
    else {
      DynType value =
          check_expr(a, st->expression, s, errors, current_return_type);
      if (value != current_return_type && value != DYN_TYPE_ERROR) {
        if (can_convert(a, value, current_return_type))
          st->expression = convert_expr(a, st->expression, current_return_type);
        else
          error_span(st->span, s, errors, "return type mismatch");
      }
    }
    return true;
  }
  if (st->kind == DYN_STMT_EXPR) {
    DynExprKind original = a->expressions[st->expression].kind;
    DynType value = check_expr(a, st->expression, s, errors, DYN_TYPE_INFER);
    if (original != DYN_EXPR_SYSCALL && value != DYN_TYPE_VOID &&
        value != DYN_TYPE_ERROR)
      error_span(st->span, s, errors,
                 "discard non-void call result with '_ = call()'");
    return false;
  }
  if (st->kind == DYN_STMT_BREAK || st->kind == DYN_STMT_CONTINUE) {
    (void)resolve_loop_control(st, s, errors);
    return true;
  }
  if (st->kind == DYN_STMT_CASE) {
    DynType subject = check_expr(a, st->expression, s, errors, DYN_TYPE_INFER);
    bool enum_case = dyn_type_is_enum(subject), integer_case = integer(subject);
    if (!enum_case && !integer_case) {
      error_span(st->span, s, errors, "case requires integer or enum value");
      return false;
    }
    bool wildcard = false, all_terminate = true;
    uint32_t total_patterns = 0;
    bool *variants =
        enum_case
            ? calloc(a->enums[subject - DYN_TYPE_ENUM_BASE].variant_count, 1)
            : NULL;
    for (uint32_t i = 0; i < st->case_arm_count; ++i) {
      DynAstCaseArm *arm = &a->case_arms[st->case_arm_start + i];
      if (arm->wildcard) {
        if (wildcard)
          error_span(arm->span, s, errors, "duplicate _ case arm");
        wildcard = true;
        if (arm->pattern_count)
          error_span(arm->span, s, errors, "_ case arm cannot have patterns");
      }
      for (uint32_t j = 0; j < arm->pattern_count; ++j) {
        DynAstPattern *p = &a->patterns[arm->pattern_start + j];
        ++total_patterns;
        if (enum_case) {
          if (p->range) {
            error_span(p->span, s, errors,
                       "enum case pattern cannot be a range");
            continue;
          }
          DynType t = check_expr(a, p->first, s, errors, subject);
          if (t != subject) {
            error_span(p->span, s, errors, "case enum pattern type mismatch");
            continue;
          }
          DynAstExpr *pe = &a->expressions[p->first];
          if (pe->kind != DYN_EXPR_ENUM) {
            error_span(p->span, s, errors,
                       "enum case pattern must be a variant");
            continue;
          }
          p->is_enum = true;
          p->variant = (uint32_t)pe->integer;
          uint32_t relative =
              p->variant - a->enums[subject - DYN_TYPE_ENUM_BASE].variant_start;
          if (variants[relative])
            error_span(p->span, s, errors,
                       "duplicate or overlapping case pattern");
          variants[relative] = true;
        } else {
          DynType t = check_expr(a, p->first, s, errors, subject);
          ConstantInt lo = constant_int(a, p->first);
          if (t != subject || !lo.valid) {
            error_span(p->span, s, errors,
                       "case pattern must be a compile-time integer constant");
            continue;
          }
          p->first_value = lo.value;
          p->last_value = lo.value;
          if (p->range) {
            t = check_expr(a, p->last, s, errors, subject);
            ConstantInt hi = constant_int(a, p->last);
            if (t != subject || !hi.valid) {
              error_span(
                  p->span, s, errors,
                  "case range bound must be a compile-time integer constant");
              continue;
            }
            p->last_value = hi.value - (p->inclusive ? 0 : 1);
            if (p->last_value < p->first_value)
              error_span(p->span, s, errors, "case range is empty or reversed");
          }
          for (uint32_t q = 0; q < p->span.start_byte && q < total_patterns - 1;
               ++q) {
            (void)q;
          }
          for (uint32_t ai = 0; ai < i; ++ai) {
            DynAstCaseArm *old = &a->case_arms[st->case_arm_start + ai];
            for (uint32_t pj = 0; pj < old->pattern_count; ++pj) {
              DynAstPattern *o = &a->patterns[old->pattern_start + pj];
              if (!o->is_enum && p->first_value <= o->last_value &&
                  o->first_value <= p->last_value)
                error_span(p->span, s, errors,
                           "duplicate or overlapping case pattern");
            }
          }
          for (uint32_t pj = 0; pj < j; ++pj) {
            DynAstPattern *o = &a->patterns[arm->pattern_start + pj];
            if (p->first_value <= o->last_value &&
                o->first_value <= p->last_value)
              error_span(p->span, s, errors,
                         "duplicate or overlapping case pattern");
          }
        }
      }
      bool has_binding = arm->binding.end_byte > arm->binding.start_byte;
      if (has_binding) {
        if (!enum_case || arm->wildcard || arm->pattern_count != 1 ||
            !a->patterns[arm->pattern_start].is_enum) {
          error_span(arm->binding, s, errors,
                     "payload binding requires one enum variant pattern");
        } else {
          DynAstVariant *v =
              &a->variants[a->patterns[arm->pattern_start].variant];
          if (v->payload_type == DYN_TYPE_VOID)
            error_span(arm->binding, s, errors,
                       "payloadless variant cannot bind payload");
          else if (find_any_local(a, arm->binding, s) != UINT32_MAX)
            error_span(arm->binding, s, errors,
                       "shadowing or duplicate local is forbidden");
          else if (reserve_local(a)) {
            arm->local_id = (uint32_t)a->local_count;
            a->locals[a->local_count++] = (DynAstLocal){
                .name = arm->binding, .type = v->payload_type, .active = true,
                .owner_function = current_function};
          }
        }
      }
      bool term =
          sema_block(a, arm->body_start, arm->body_count, s, errors, true);
      all_terminate = all_terminate && term;
      if (arm->local_id != UINT32_MAX)
        a->locals[arm->local_id].active = false;
    }
    if (enum_case) {
      DynAstEnum *en = &a->enums[subject - DYN_TYPE_ENUM_BASE];
      bool complete = true;
      for (uint32_t i = 0; i < en->variant_count; ++i)
        complete = complete && variants[i];
      if (wildcard && complete)
        error_span(
            st->span, s, errors,
            "_ case arm is unreachable because all variants are covered");
      else if (!wildcard && !complete)
        error_span(st->span, s, errors, "enum case is not exhaustive");
      free(variants);
    } else if (!wildcard)
      error_span(st->span, s, errors,
                 "integer case requires exhaustive ranges or _");
    return all_terminate;
  }
  if (st->kind == DYN_STMT_IF || st->kind == DYN_STMT_FOR) {
    if (st->kind == DYN_STMT_FOR && st->target != DYN_NO_EXPR) {
      DynType collection = check_expr(a, st->target, s, errors, DYN_TYPE_INFER);
      DynAstArray *ar = array_info(a, collection);
      DynAstSlice *sl = slice_info(a, collection);
      if (!ar && !sl) {
        error_span(st->span, s, errors, "for-in requires array or slice");
        return false;
      }
      if (st->for_pointer && ar) {
        DynExprKind k = a->expressions[st->target].kind;
        if (k != DYN_EXPR_NAME && k != DYN_EXPR_GLOBAL && k != DYN_EXPR_FIELD &&
            k != DYN_EXPR_INDEX && k != DYN_EXPR_UNARY) {
          error_span(
              st->span, s, errors,
              "pointer for-in over array requires assignable collection");
          return false;
        }
      }
      if (st->for_pointer && !st->for_const && sl && sl->is_const) {
        error_span(st->span, s, errors,
                   "mutable pointer for-in requires mutable collection");
        return false;
      }
      if (find_any_local(a, st->name, s) != UINT32_MAX) {
        error_span(st->name, s, errors,
                   "shadowing or duplicate local is forbidden");
        return false;
      }
      if (!reserve_local(a)) {
        error_span(st->span, s, errors, "out of memory");
        return false;
      }
      DynType element = ar ? ar->element : sl->element,
              binding =
                  st->for_pointer
                      ? sema_intern_pointer(
                            a, element, st->for_const || (sl && sl->is_const))
                      : element;
      if (binding == DYN_TYPE_ERROR) {
        error_span(st->span, s, errors, "out of memory");
        return false;
      }
      st->local_id = (uint32_t)a->local_count;
      a->locals[a->local_count++] = (DynAstLocal){
          .name = st->name, .type = binding, .active = true,
          .owner_function = current_function};
      bool pushed = push_loop(st, s, errors);
      (void)sema_block(a, st->body_start, st->body_count, s, errors, true);
      if (pushed)
        pop_loop();
      a->locals[st->local_id].active = false;
      return false;
    }
    DynType condition =
        st->expression == DYN_NO_EXPR
            ? DYN_TYPE_BOOL
            : check_expr(a, st->expression, s, errors, DYN_TYPE_BOOL);
    if (condition != DYN_TYPE_BOOL && condition != DYN_TYPE_ERROR)
      error_span(st->span, s, errors, "control-flow condition requires bool");
    bool pushed = st->kind == DYN_STMT_FOR && push_loop(st, s, errors);
    bool body = sema_block(a, st->body_start, st->body_count, s, errors, true);
    if (pushed)
      pop_loop();
    if (st->kind == DYN_STMT_FOR)
      return false;
    bool other = st->else_count &&
                 sema_block(a, st->else_start, st->else_count, s, errors, true);
    return st->else_count && body && other;
  }
  if (st->kind == DYN_STMT_LOCAL) {
    if (find_any_local(a, st->name, s) != UINT32_MAX ||
        find_global(a, st->name, s) != UINT32_MAX) {
      error_span(st->name, s, errors,
                 "shadowing or duplicate local is forbidden");
      return false;
    }
    DynType type = st->declared_type;
    if (type == DYN_TYPE_INFER && st->expression == DYN_NO_EXPR) {
      error_span(st->span, s, errors, "inferred local requires initializer");
      return false;
    }
    if (st->expression != DYN_NO_EXPR) {
      DynType value = check_expr(a, st->expression, s, errors, type);
      if (type == DYN_TYPE_INFER)
        type = value;
      else if (value != type && value != DYN_TYPE_ERROR) {
        if (can_convert(a, value, type))
          st->expression = convert_expr(a, st->expression, type);
        else
          error_span(st->span, s, errors, "initializer type mismatch");
      }
    }
    if (type == DYN_TYPE_ERROR || type == DYN_TYPE_STRING ||
        type == DYN_TYPE_VOID) {
      if (type == DYN_TYPE_STRING)
        error_span(st->span, s, errors,
                   "string locals are deferred until slice lowering");
      else if (type == DYN_TYPE_VOID)
        error_span(st->span, s, errors, "local cannot have void type");
      return false;
    }
    if (!reserve_local(a)) {
      error_span(st->span, s, errors, "out of memory");
      return false;
    }
    st->local_id = (uint32_t)a->local_count;
    a->locals[a->local_count++] = (DynAstLocal){
        .name = st->name, .type = type, .active = true,
        .is_const = st->is_const, .owner_function = current_function};
    return false;
  }
  if (st->target != DYN_NO_EXPR) {
    DynType target = check_expr(a, st->target, s, errors, DYN_TYPE_INFER),
            value = check_expr(a, st->expression, s, errors, target);
    if (lvalue_const(a, st->target))
      error_span(st->span, s, errors, "assignment through *const pointer");
    if (value != target && value != DYN_TYPE_ERROR) {
      if (can_convert(a, value, target) && st->assignment_op == DYN_OP_NONE)
        st->expression = convert_expr(a, st->expression, target);
      else
        error_span(st->span, s, errors, "field assignment type mismatch");
    }
    if (st->assignment_op != DYN_OP_NONE) {
      bool valid = numeric(target) && (st->assignment_op >= DYN_OP_ADD &&
                                       st->assignment_op <= DYN_OP_REM);
      valid =
          valid || (integer(target) && (st->assignment_op == DYN_OP_BIT_AND ||
                                        st->assignment_op == DYN_OP_BIT_OR ||
                                        st->assignment_op == DYN_OP_BIT_XOR ||
                                        st->assignment_op == DYN_OP_SHL ||
                                        st->assignment_op == DYN_OP_SHR));
      valid = valid || (target == DYN_TYPE_BOOL &&
                        (st->assignment_op == DYN_OP_BIT_AND ||
                         st->assignment_op == DYN_OP_BIT_OR ||
                         st->assignment_op == DYN_OP_BIT_XOR));
      if (!valid)
        error_span(st->span, s, errors,
                   "compound operator is invalid for field type");
    }
    return false;
  }
  if (discard_name(st->name, s)) {
    (void)check_expr(a, st->expression, s, errors, DYN_TYPE_INFER);
    return false;
  }
  uint32_t local = find_local(a, st->name, s),
           global = find_global(a, st->name, s);
  DynType target;
  if (local != UINT32_MAX) {
    st->local_id = local;
    target = a->locals[local].type;
    if (a->locals[local].is_const)
      error_span(st->name, s, errors, "cannot assign to constant");
  } else if (global != UINT32_MAX) {
    if (a->globals[global].is_const)
      error_span(st->name, s, errors, "cannot assign to constant");
    if (!reserve_expr(a)) {
      error_span(st->span, s, errors, "out of memory");
      return false;
    }
    st->target = (DynExprId)a->expression_count;
    a->expressions[a->expression_count++] =
        (DynAstExpr){.kind = DYN_EXPR_GLOBAL,
                     .type = a->globals[global].type,
                     .left = DYN_NO_EXPR,
                     .right = DYN_NO_EXPR,
                     .integer = global};
    st->local_id = UINT32_MAX;
    target = a->globals[global].type;
  } else {
    error_span(st->name, s, errors, "assignment target is not declared");
    return false;
  }
  bool shift =
      st->assignment_op == DYN_OP_SHL || st->assignment_op == DYN_OP_SHR;
  DynType value =
      check_expr(a, st->expression, s, errors, shift ? DYN_TYPE_USIZE : target);
  if (shift) {
    if (!integer(value) || signed_int(value))
      error_span(st->span, s, errors, "shift count requires unsigned integer");
  } else if (value != target && value != DYN_TYPE_ERROR) {
    if (can_convert(a, value, target) && st->assignment_op == DYN_OP_NONE)
      st->expression = convert_expr(a, st->expression, target);
    else
      error_span(st->span, s, errors, "assignment type mismatch");
  }
  if (st->assignment_op != DYN_OP_NONE) {
    bool valid = numeric(target) && (st->assignment_op >= DYN_OP_ADD &&
                                     st->assignment_op <= DYN_OP_REM);
    valid = valid ||
            (integer(target) && (st->assignment_op == DYN_OP_BIT_AND ||
                                 st->assignment_op == DYN_OP_BIT_OR ||
                                 st->assignment_op == DYN_OP_BIT_XOR || shift));
    valid = valid ||
            (target == DYN_TYPE_BOOL && (st->assignment_op == DYN_OP_BIT_AND ||
                                         st->assignment_op == DYN_OP_BIT_OR ||
                                         st->assignment_op == DYN_OP_BIT_XOR));
    if (!valid)
      error_span(st->span, s, errors,
                 "compound operator is invalid for variable type");
  }
  return false;
}
static bool sema_block(DynAstFunction *a, uint32_t start, uint32_t count,
                       const DynSource *s, unsigned *errors, bool scoped) {
  size_t base = a->local_count;
  bool terminated = false;
  for (uint32_t i = 0; i < count; ++i) {
    DynAstStmt *st = &a->statements[a->children[start + i]];
    if (terminated) {
      error_span(st->span, s, errors, "unreachable statement");
      continue;
    }
    terminated = sema_stmt(a, st, s, errors);
  }
  if (scoped)
    for (size_t i = base; i < a->local_count; ++i)
      a->locals[i].active = false;
  return terminated;
}
static bool foreign_symbol_valid(DynSpan name, const DynSource *s) {
  if (name.end_byte <= name.start_byte)
    return false;
  for (uint32_t i = name.start_byte; i < name.end_byte; ++i) {
    unsigned char c = (unsigned char)s->text[i];
    if (!(isalnum(c) || c == '_' || c == '.' || c == '$' || c == '@'))
      return false;
  }
  return true;
}
bool dyn_sema_function(DynAstFunction *a, const DynSource *s,
                       unsigned *errors) {
  /* check_expr keeps short-lived pointers into this table while recursively
     checking children. Reserve all conversion nodes up front so convert_expr
     cannot invalidate those pointers. At most one implicit conversion is
     introduced per parsed expression edge. */
  size_t semantic_capacity = a->expression_count * 2 + 32;
  if (semantic_capacity > a->expression_capacity) {
    void *expressions = realloc(a->expressions,
                                semantic_capacity * sizeof(*a->expressions));
    if (!expressions) {
      ++*errors;
      return false;
    }
    a->expressions = expressions;
    a->expression_capacity = semantic_capacity;
  }
  for (uint32_t i = 0; i < a->field_count; ++i)
    if (a->fields[i].default_expression != DYN_NO_EXPR) {
      DynType value = check_expr(a, a->fields[i].default_expression, s, errors,
                                 a->fields[i].type);
      if (!compile_time_expr(a, a->fields[i].default_expression))
        error_span(a->fields[i].name, s, errors,
                   "struct field default must be compile-time expression");
      if (value != a->fields[i].type && value != DYN_TYPE_ERROR) {
        if (can_convert(a, value, a->fields[i].type))
          a->fields[i].default_expression = convert_expr(
              a, a->fields[i].default_expression, a->fields[i].type);
        else
          error_span(a->fields[i].name, s, errors,
                     "struct field default type mismatch");
      }
    }
  current_function = UINT32_MAX;
  for (uint32_t i = 0; i < a->global_count; ++i) {
    DynAstGlobal *g = &a->globals[i];
    if (g->type == DYN_TYPE_ANY)
      error_span(g->name, s, errors, "global any would escape borrowed storage");
    if (g->initializer == DYN_NO_EXPR) {
      if (g->is_const)
        error_span(g->name, s, errors, "constant requires initializer");
      if (g->type == DYN_TYPE_INFER)
        error_span(g->name, s, errors, "inferred global requires initializer");
      continue;
    }
    DynType value = check_expr(a, g->initializer, s, errors, g->type);
    if (g->type == DYN_TYPE_INFER)
      g->type = value;
    else if (value != g->type && value != DYN_TYPE_ERROR) {
      if (can_convert(a, value, g->type))
        g->initializer = convert_expr(a, g->initializer, g->type);
      else
        error_span(g->name, s, errors, "global initializer type mismatch");
    }
    if (g->is_const && !compile_time_expr(a, g->initializer))
      error_span(g->name, s, errors,
                 "constant initializer must be compile-time expression");
  }
  for (uint32_t f = 0; f < a->function_count; ++f) {
    DynAstFn *fn = &a->functions[f];
    if (fn->return_type == DYN_TYPE_ANY)
      error_span(fn->name, s, errors, "returning any would escape borrowed storage");
    if (fn->foreign) {
      if (fn->variadic && fn->param_count == 0)
        error_span(fn->name, s, errors,
                   "C variadic function requires a fixed parameter");
      if (!foreign_symbol_valid(fn->link_name, s))
        error_span(fn->link_name, s, errors,
                   "foreign link name must be a non-empty linker symbol");
      for (uint32_t prior = 0; prior < f; ++prior)
        if (a->functions[prior].foreign &&
            dyn_span_text_equal(fn->link_name, a->functions[prior].link_name,
                                s))
          error_span(fn->link_name, s, errors, "duplicate foreign link symbol");
      if (fn->return_type == DYN_TYPE_ERROR ||
          fn->return_type == DYN_TYPE_INFER)
        error_span(fn->name, s, errors,
                   "foreign function has invalid return type");
      for (uint32_t i = 0; i < fn->param_count; ++i) {
        DynAstParam *p = &a->params[fn->param_start + i];
        if (p->type == DYN_TYPE_ERROR || p->type == DYN_TYPE_INFER ||
            p->type == DYN_TYPE_VOID)
          error_span(p->name, s, errors,
                     "foreign parameter requires a concrete non-void type");
        for (uint32_t j = 0; j < i; ++j)
          if (dyn_span_text_equal(p->name, a->params[fn->param_start + j].name,
                                  s))
            error_span(p->name, s, errors, "duplicate parameter name");
      }
      continue;
    }
    current_function = f;
    current_return_type = fn->return_type;
    fn->local_start = (uint32_t)a->local_count;
    for (uint32_t i = 0; i < fn->param_count; ++i) {
      DynAstParam *p = &a->params[fn->param_start + i];
      if (find_any_local(a, p->name, s) != UINT32_MAX ||
          find_global(a, p->name, s) != UINT32_MAX) {
        error_span(p->name, s, errors, "duplicate parameter name");
        continue;
      }
      if (!reserve_local(a)) {
        error_span(p->name, s, errors, "out of memory");
        continue;
      }
      p->local_id = (uint32_t)a->local_count;
      a->locals[a->local_count++] = (DynAstLocal){
          .name = p->name, .type = p->type, .active = true,
          .owner_function = f};
    }
    if (fn->variadic && fn->variadic_name.end_byte > fn->variadic_name.start_byte) {
      if (!reserve_local(a)) error_span(fn->variadic_name, s, errors, "out of memory");
      else {
        fn->variadic_local_id = (uint32_t)a->local_count;
        a->locals[a->local_count++] = (DynAstLocal){.name = fn->variadic_name,
          .type = fn->variadic_type, .active = true, .owner_function = f};
      }
    }
    bool terminated =
        sema_block(a, fn->body_start, fn->body_count, s, errors, false);
    fn->local_count = (uint32_t)a->local_count - fn->local_start;
    if (fn->return_type != DYN_TYPE_VOID && !terminated)
      error_span(fn->name, s, errors,
                 "non-void function may exit without return");
    for (uint32_t i = fn->local_start; i < a->local_count; ++i)
      a->locals[i].active = false;
  }
  current_function = UINT32_MAX;
  return *errors == 0;
}
#undef dyn_sema_function
bool dyn_sema_base(DynAstFunction *a, const DynSource *s, unsigned *errors) {
  type_context = a;
  return dyn_sema_base_impl(a, s, errors);
}
