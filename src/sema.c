#include "sema.h"
#include <ctype.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
  uint32_t *buckets, *next;
  size_t mask;
} SemaNames;
typedef struct {
  DynAstProgram *program;
  unsigned pointer_bytes;
  SemaNames functions, globals, locals;
  size_t indexed_locals;
  uint32_t current_function;
  DynType current_return_type;
  DynAstStmt **active_loops;
  size_t active_loop_count, active_loop_capacity;
} Sema;

static void error_span(DynSpan span, const DynSource *s, unsigned *e,
                       const char *m) {
  dyn_diagnostic_source("error", s, span.start_byte, span.end_byte, m);
  ++*e;
}
static void note_span(DynSpan span, const DynSource *s, const char *m) {
  dyn_diagnostic_source("note", s, span.start_byte, span.end_byte, m);
}
static void error_types(DynSpan span, const DynSource *s, unsigned *e,
                        const char *m, DynType expected, DynType found) {
  char detail[192];
  snprintf(detail, sizeof(detail), "%s (expected %s, found %s)", m,
           dyn_type_name(expected), dyn_type_name(found));
  error_span(span, s, e, detail);
}

static DynType underlying_type(DynAstProgram *a, DynType t) {
  size_t guard = 0;
  while (a && dyn_type_is_distinct(t) && guard++ <= a->alias_count) {
    uint32_t id = t - DYN_TYPE_DISTINCT_BASE;
    if (id >= a->alias_count)
      return DYN_TYPE_ERROR;
    t = a->aliases[id].target;
  }
  return t;
}
static bool integer(Sema *sema, DynType t) {
  t = underlying_type(sema->program, t);
  return t >= DYN_TYPE_I8 && t <= DYN_TYPE_USIZE;
}
static bool signed_int(Sema *sema, DynType t) {
  t = underlying_type(sema->program, t);
  return (t >= DYN_TYPE_I8 && t <= DYN_TYPE_I64) || t == DYN_TYPE_ISIZE;
}
static bool numeric(Sema *sema, DynType t) {
  t = underlying_type(sema->program, t);
  return integer(sema, t) || t == DYN_TYPE_F32 || t == DYN_TYPE_F64;
}

static bool span_present(DynSpan s) { return s.end_byte > s.start_byte; }
static unsigned name_distance(DynSpan unknown, DynSpan candidate,
                              const DynSource *s) {
  size_t an = 0, bn = candidate.end_byte - candidate.start_byte;
  while (unknown.start_byte + an < unknown.end_byte &&
         (isalnum((unsigned char)s->text[unknown.start_byte + an]) ||
          s->text[unknown.start_byte + an] == '_'))
    ++an;
  if (an > 96 || bn > 96)
    return UINT_MAX;
  unsigned previous[97], current[97];
  for (size_t j = 0; j <= bn; ++j)
    previous[j] = (unsigned)j;
  for (size_t i = 1; i <= an; ++i) {
    current[0] = (unsigned)i;
    for (size_t j = 1; j <= bn; ++j) {
      unsigned cost = s->text[unknown.start_byte + i - 1] ==
                              s->text[candidate.start_byte + j - 1]
                          ? 0u
                          : 1u;
      unsigned insert = current[j - 1] + 1, remove = previous[j] + 1,
               replace = previous[j - 1] + cost;
      current[j] = insert < remove ? insert : remove;
      if (replace < current[j])
        current[j] = replace;
    }
    memcpy(previous, current, (bn + 1) * sizeof(*previous));
  }
  return previous[bn];
}
static bool suggest_name(DynAstProgram *a, DynSpan unknown, const DynSource *s,
                         bool functions, char *message, size_t capacity) {
  DynSpan best = {0};
  unsigned distance = UINT_MAX;
  if (functions) {
    for (size_t i = 0; i < a->function_count; ++i) {
      unsigned d = name_distance(unknown, a->functions[i].name, s);
      if (d < distance) {
        distance = d;
        best = a->functions[i].name;
      }
    }
  } else {
    for (size_t i = 0; i < a->local_count; ++i)
      if (a->locals[i].active) {
        unsigned d = name_distance(unknown, a->locals[i].name, s);
        if (d < distance) {
          distance = d;
          best = a->locals[i].name;
        }
      }
    for (size_t i = 0; i < a->global_count; ++i) {
      unsigned d = name_distance(unknown, a->globals[i].name, s);
      if (d < distance) {
        distance = d;
        best = a->globals[i].name;
      }
    }
  }
  size_t n = best.end_byte - best.start_byte;
  if (!n || distance > 2)
    return false;
  snprintf(message, capacity, "unknown %s; did you mean '%.*s'?",
           functions ? "function" : "name", (int)n, s->text + best.start_byte);
  return true;
}
static bool push_loop(Sema *sema, DynAstStmt *st, const DynSource *s,
                      unsigned *errors) {
  if (span_present(st->label))
    for (size_t i = 0; i < sema->active_loop_count; ++i)
      if (span_present(sema->active_loops[i]->label) &&
          dyn_span_text_equal(st->label, sema->active_loops[i]->label, s)) {
        error_span(st->label, s, errors, "duplicate active loop label");
        note_span(sema->active_loops[i]->label, s,
                  "previous label declared here");
        break;
      }
  if (sema->active_loop_count == sema->active_loop_capacity) {
    size_t c = sema->active_loop_capacity ? sema->active_loop_capacity * 2 : 8;
    void *p = realloc(sema->active_loops, c * sizeof(*sema->active_loops));
    if (!p) {
      error_span(st->span, s, errors, "out of memory");
      return false;
    }
    sema->active_loops = p;
    sema->active_loop_capacity = c;
  }
  sema->active_loops[sema->active_loop_count++] = st;
  return true;
}
static void pop_loop(Sema *sema) {
  if (sema->active_loop_count)
    --sema->active_loop_count;
}
static bool resolve_loop_control(Sema *sema, DynAstStmt *st, const DynSource *s,
                                 unsigned *errors) {
  if (!sema->active_loop_count) {
    error_span(st->span, s, errors,
               st->kind == DYN_STMT_BREAK ? "break requires enclosing loop"
                                          : "continue requires enclosing loop");
    return false;
  }
  if (!span_present(st->control_label)) {
    st->target_loop_id =
        sema->active_loops[sema->active_loop_count - 1]->loop_id;
    return true;
  }
  for (size_t i = sema->active_loop_count; i > 0; --i)
    if (span_present(sema->active_loops[i - 1]->label) &&
        dyn_span_text_equal(st->control_label, sema->active_loops[i - 1]->label,
                            s)) {
      st->target_loop_id = sema->active_loops[i - 1]->loop_id;
      return true;
    }
  error_span(st->control_label, s, errors, "unknown active loop label");
  return false;
}
static bool reserve_local(DynAstProgram *a) {
  if (a->local_count < a->local_capacity)
    return true;
  size_t c = a->local_capacity ? a->local_capacity * 2 : 16;
  void *p = realloc(a->locals, c * sizeof(*a->locals));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }
  a->locals = p;
  a->local_capacity = c;
  return true;
}
static bool sema_reserve_expr(DynAstProgram *a) {
  if (a->expression_count < a->expression_capacity)
    return true;
  size_t c = a->expression_capacity ? a->expression_capacity * 2 : 32;
  void *p = realloc(a->expressions, c * sizeof(*a->expressions));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }
  a->expressions = p;
  a->expression_capacity = c;
  return true;
}
#define reserve_expr sema_reserve_expr
static uint64_t sema_name_hash(DynSpan name, const DynSource *source) {
  uint64_t hash = UINT64_C(14695981039346656037);
  for (size_t i = name.start_byte; i < name.end_byte; ++i)
    hash = (hash ^ (unsigned char)source->text[i]) * UINT64_C(1099511628211);
  return hash;
}
static bool sema_names_build(SemaNames *index, DynAstProgram *a,
                             const DynSource *source, bool functions) {
  size_t count = functions ? a->function_count : a->global_count;
  if (!count)
    return true;
  size_t capacity = 16;
  while (capacity < count * 2)
    capacity *= 2;
  index->buckets = calloc(capacity, sizeof(*index->buckets));
  index->next = calloc(count, sizeof(*index->next));
  if (!index->buckets || !index->next)
    return false;
  index->mask = capacity - 1;
  /* Insert backwards to preserve declaration-order lookup for duplicate errors.
   */
  for (size_t i = count; i-- > 0;) {
    DynSpan name = functions ? a->functions[i].name : a->globals[i].name;
    size_t bucket = sema_name_hash(name, source) & index->mask;
    index->next[i] = index->buckets[bucket];
    index->buckets[bucket] = (uint32_t)i + 1;
  }
  return true;
}
static uint32_t sema_name_lookup(SemaNames *index, DynAstProgram *a,
                                 DynSpan name, const DynSource *source,
                                 bool functions) {
  if (!index->buckets)
    return UINT32_MAX;
  for (uint32_t entry =
           index->buckets[sema_name_hash(name, source) & index->mask];
       entry; entry = index->next[entry - 1]) {
    uint32_t i = entry - 1;
    DynSpan declaration = functions ? a->functions[i].name : a->globals[i].name;
    if (dyn_module_name_equal(name, declaration, source))
      return i;
  }
  return UINT32_MAX;
}
/* Small functions use the allocation-free linear path. Larger functions index
   appended locals lazily; inactive locals remain indexed for no-shadowing checks. */
static bool sema_locals_sync(Sema *sema, DynAstProgram *a, const DynSource *s,
                             size_t first, size_t count) {
  SemaNames *index = &sema->locals;
  if (!index->buckets || count > (index->mask + 1) / 2) {
    size_t capacity = 64;
    while (count > capacity / 2) {
      if (capacity > SIZE_MAX / 2) return false;
      capacity *= 2;
    }
    if (capacity > SIZE_MAX / sizeof(*index->buckets)) return false;
    uint32_t *buckets = calloc(capacity, sizeof(*buckets));
    uint32_t *next = malloc((capacity / 2) * sizeof(*next));
    if (!buckets || !next) { free(buckets); free(next); return false; }
    free(index->buckets); free(index->next);
    *index = (SemaNames){buckets, next, capacity - 1};
    sema->indexed_locals = 0;
  }
  while (sema->indexed_locals < count) {
    size_t local = sema->indexed_locals++;
    size_t bucket = sema_name_hash(a->locals[first + local].name, s) & index->mask;
    index->next[local] = index->buckets[bucket];
    index->buckets[bucket] = (uint32_t)local + 1;
  }
  return true;
}
static uint32_t sema_local_lookup(Sema *sema, DynAstProgram *a, DynSpan name,
                                   const DynSource *s, bool active_only) {
  if (sema->current_function == UINT32_MAX) return UINT32_MAX;
  size_t first = a->functions[sema->current_function].local_start,
         count = a->local_count - first;
  if (count >= 32 && sema_locals_sync(sema, a, s, first, count)) {
    SemaNames *index = &sema->locals;
    uint32_t found = UINT32_MAX;
    for (uint32_t entry = index->buckets[sema_name_hash(name, s) & index->mask];
         entry; entry = index->next[entry - 1]) {
      uint32_t id = (uint32_t)first + entry - 1;
      if (id < found && (!active_only || a->locals[id].active) &&
          dyn_span_text_equal(name, a->locals[id].name, s)) found = id;
    }
    return found;
  }
  if (count >= 32) a->allocation_failed = true;
  for (size_t i = first; i < a->local_count; ++i)
    if ((!active_only || a->locals[i].active) &&
        dyn_span_text_equal(name, a->locals[i].name, s)) return (uint32_t)i;
  return UINT32_MAX;
}
static uint32_t find_local(Sema *sema, DynAstProgram *a, DynSpan name,
                           const DynSource *s) {
  return sema_local_lookup(sema, a, name, s, true);
}
static uint32_t find_any_local(Sema *sema, DynAstProgram *a, DynSpan name,
                               const DynSource *s) {
  return sema_local_lookup(sema, a, name, s, false);
}
static uint32_t sema_find_global_name(Sema *sema, DynAstProgram *a,
                                      DynSpan name, const DynSource *s) {
  return sema_name_lookup(&sema->globals, a, name, s, false);
}
static uint32_t sema_find_function(Sema *sema, DynAstProgram *a, DynSpan name,
                                   const DynSource *s) {
  if (find_local(sema, a, name, s) != UINT32_MAX ||
      sema_find_global_name(sema, a, name, s) != UINT32_MAX)
    return UINT32_MAX;
  return sema_name_lookup(&sema->functions, a, name, s, true);
}
static DynSpan sema_unqualified_span(DynSpan name, const DynSource *s) {
  for (uint32_t i = name.start_byte; i < name.end_byte; ++i)
    if (s->text[i] == '.')
      name.start_byte = i + 1;
  return name;
}
static uint32_t sema_find_struct(DynAstProgram *a, DynSpan name,
                                 const DynSource *s) {
  name = sema_unqualified_span(name, s);
  uint32_t found = dyn_name_index_find(&a->struct_names,
      a->struct_count ? &a->structs[0].name : NULL, sizeof(*a->structs), a->struct_count,
      name, s, true, &a->allocation_failed);
  if (found != UINT32_MAX) return found;
  for (uint32_t i = 0; i < a->alias_count; ++i) {
    const DynAstAlias *alias = &a->aliases[i];
    if (!alias->distinct && dyn_type_is_struct(alias->target) &&
        dyn_module_name_equal(name, alias->name, s))
      return alias->target - DYN_TYPE_STRUCT_BASE;
  }
  return UINT32_MAX;
}
static uint32_t sema_find_enum(DynAstProgram *a, DynSpan name,
                               const DynSource *s) {
  name = sema_unqualified_span(name, s);
  uint32_t found = dyn_name_index_find(&a->enum_names,
      a->enum_count ? &a->enums[0].name : NULL, sizeof(*a->enums), a->enum_count,
      name, s, true, &a->allocation_failed);
  if (found != UINT32_MAX) return found;
  for (uint32_t i = 0; i < a->alias_count; ++i) {
    const DynAstAlias *alias = &a->aliases[i];
    if (!alias->distinct && dyn_type_is_enum(alias->target) &&
        dyn_module_name_equal(name, alias->name, s))
      return alias->target - DYN_TYPE_ENUM_BASE;
  }
  return UINT32_MAX;
}
static uint32_t sema_expr_enum(DynAstProgram *a, DynExprId id,
                               const DynSource *s) {
  if (id == DYN_NO_EXPR)
    return UINT32_MAX;
  DynAstExpr *e = &a->expressions[id];
  return e->kind == DYN_EXPR_NAME || e->kind == DYN_EXPR_FIELD
             ? sema_find_enum(a, e->span, s)
             : UINT32_MAX;
}
static uint32_t sema_find_variant(DynAstProgram *a, uint32_t eid, DynSpan name,
                                  const DynSource *s) {
  DynAstEnum *en = &a->enums[eid];
  uint32_t id = dyn_name_index_find(&en->variant_names,
      en->variant_count ? &a->variants[en->variant_start].name : NULL,
      sizeof(*a->variants), en->variant_count, name, s, false, &a->allocation_failed);
  return id == UINT32_MAX ? id : en->variant_start + id;
}
static uint32_t sema_find_field(DynAstProgram *a, uint32_t sid, DynSpan name,
                                const DynSource *s) {
  DynAstStruct *st = &a->structs[sid];
  return dyn_name_index_find(&st->field_names,
      st->field_count ? &a->fields[st->field_start].name : NULL,
      sizeof(*a->fields), st->field_count, name, s, false, &a->allocation_failed);
}
static bool discard_name(DynSpan n, const DynSource *s) {
  return n.end_byte - n.start_byte == 1 && s->text[n.start_byte] == '_';
}
static unsigned bits(Sema *sema, DynType t) {
  t = underlying_type(sema->program, t);
  if (t == DYN_TYPE_USIZE || t == DYN_TYPE_ISIZE) return sema->pointer_bytes * 8;
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
static uint64_t sema_type_layout(Sema *sema, DynAstProgram *a, DynType t, bool alignment) {
  t = underlying_type(a, t);
  if (t == DYN_TYPE_BOOL || t == DYN_TYPE_I8 || t == DYN_TYPE_U8)
    return 1;
  if (t == DYN_TYPE_I16 || t == DYN_TYPE_U16)
    return 2;
  if (t == DYN_TYPE_I32 || t == DYN_TYPE_U32 || t == DYN_TYPE_F32)
    return 4;
  if (t == DYN_TYPE_ISIZE || t == DYN_TYPE_USIZE || t == DYN_TYPE_RAWPTR ||
      dyn_type_is_pointer(t) || dyn_type_is_function(t)) return sema->pointer_bytes;
  if (t == DYN_TYPE_I64 || t == DYN_TYPE_U64 || t == DYN_TYPE_F64) return 8;
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
    uint64_t element = sema_type_layout(sema, a, ar->element, alignment);
    uint64_t limit = sema->pointer_bytes == 4 ? UINT32_MAX : UINT64_MAX;
    if (!alignment && element && ar->length > limit / element) return 0;
    return alignment ? element : element * ar->length;
  }
  if (dyn_type_is_slice(t) || t == DYN_TYPE_STRING)
    return alignment ? sema->pointer_bytes : 2 * sema->pointer_bytes;
  if (t == DYN_TYPE_ANY) return alignment ? 8 : 16;
  return 0;
}
static bool literal_fits(Sema *sema, uint64_t v, DynType t) {
  unsigned b = bits(sema, t);
  if (signed_int(sema, t))
    return b == 64 ? v <= INT64_MAX : v <= (UINT64_C(1) << (b - 1)) - 1;
  return integer(sema, t) && (b == 64 || v <= (UINT64_C(1) << b) - 1);
}
static bool lossless(Sema *sema, DynType from, DynType to) {
  if (from == to)
    return true;
  if (dyn_type_is_distinct(from) || dyn_type_is_distinct(to))
    return false;
  if (integer(sema, from) && integer(sema, to)) {
    unsigned f = bits(sema, from), t = bits(sema, to);
    if (signed_int(sema, from) == signed_int(sema, to))
      return t > f;
    if (!signed_int(sema, from) && signed_int(sema, to))
      return t > f;
    return false;
  }
  if (from == DYN_TYPE_F32 && to == DYN_TYPE_F64)
    return true;
  if (integer(sema, from) && (to == DYN_TYPE_F32 || to == DYN_TYPE_F64)) {
    unsigned precision = to == DYN_TYPE_F32 ? 24 : 53;
    unsigned needed = bits(sema, from) - (signed_int(sema, from) ? 1u : 0u);
    return needed <= precision;
  }
  return false;
}
static DynAstPointer *pointer_info(DynAstProgram *a, DynType t) {
  return dyn_type_is_pointer(t) && t - DYN_TYPE_POINTER_BASE < a->pointer_count
             ? &a->pointers[t - DYN_TYPE_POINTER_BASE]
             : NULL;
}
static DynAstArray *array_info(DynAstProgram *a, DynType t) {
  return dyn_type_is_array(t) && t - DYN_TYPE_ARRAY_BASE < a->array_count
             ? &a->arrays[t - DYN_TYPE_ARRAY_BASE]
             : NULL;
}
static DynAstSlice *slice_info(DynAstProgram *a, DynType t) {
  return dyn_type_is_slice(t) && t - DYN_TYPE_SLICE_BASE < a->slice_count
             ? &a->slices[t - DYN_TYPE_SLICE_BASE]
             : NULL;
}
static DynAstFnType *fn_type_info(DynAstProgram *a, DynType t) {
  return dyn_type_is_function(t) && t - DYN_TYPE_FN_BASE < a->fn_type_count
             ? &a->fn_types[t - DYN_TYPE_FN_BASE]
             : NULL;
}
/* C ABI storage is explicit. Structs may contain C scalars/pointers and fixed
   arrays, but never Dyn slice/any descriptors or payload enums. */
static bool sema_c_abi_type(DynAstProgram *a, DynType type, unsigned depth) {
  type = underlying_type(a, type);
  if (depth > 128) return false;
  if (type == DYN_TYPE_STRING || type == DYN_TYPE_ANY || dyn_type_is_slice(type)) return false;
  if (dyn_type_is_struct(type)) {
    DynAstStruct *st = &a->structs[type - DYN_TYPE_STRUCT_BASE];
    if (!st->field_count) return false;
    for (uint32_t i = 0; i < st->field_count; ++i)
      if (!sema_c_abi_type(a, a->fields[st->field_start + i].type, depth + 1)) return false;
  }
  if (dyn_type_is_array(type)) {
    DynAstArray *array = &a->arrays[type - DYN_TYPE_ARRAY_BASE];
    return array->length && sema_c_abi_type(a, array->element, depth + 1);
  }
  if (dyn_type_is_enum(type)) return !a->enums[type - DYN_TYPE_ENUM_BASE].has_payload;
  if (dyn_type_is_pointer(type)) {
    DynType pointee = underlying_type(a, a->pointers[type - DYN_TYPE_POINTER_BASE].pointee);
    return !dyn_type_is_function(pointee) || sema_c_abi_type(a, pointee, depth + 1);
  }
  if (dyn_type_is_function(type)) {
    DynAstFnType *fn = &a->fn_types[type - DYN_TYPE_FN_BASE];
    if (dyn_type_is_array(underlying_type(a, fn->return_type)) || !sema_c_abi_type(a, fn->return_type, depth + 1)) return false;
    for (uint32_t i = 0; i < fn->param_count; ++i) {
      DynType parameter = a->fn_type_params[fn->param_start + i];
      if (dyn_type_is_array(underlying_type(a, parameter)) || !sema_c_abi_type(a, parameter, depth + 1)) return false;
    }
  }
  return true;
}
static bool sema_c_abi_function(DynAstProgram *a, const DynAstFn *fn) {
  if (!fn->foreign) return true;
  if (dyn_type_is_array(underlying_type(a, fn->return_type)) || !sema_c_abi_type(a, fn->return_type, 0)) return false;
  for (uint32_t i = 0; i < fn->param_count; ++i)
    if (dyn_type_is_array(underlying_type(a, a->params[fn->param_start + i].type)) || !sema_c_abi_type(a, a->params[fn->param_start + i].type, 0)) return false;
  return true;
}
static DynType sema_intern_pointer(DynAstProgram *a, DynType pointee,
                                   bool is_const) {
  for (uint32_t i = 0; i < a->pointer_count; ++i)
    if (a->pointers[i].pointee == pointee &&
        a->pointers[i].is_const == is_const)
      return DYN_TYPE_POINTER_BASE + i;
  if (a->pointer_count == a->pointer_capacity) {
    size_t c = a->pointer_capacity ? a->pointer_capacity * 2 : 8;
    void *p = realloc(a->pointers, c * sizeof(*a->pointers));
    if (!p) {
      a->allocation_failed = true;
      return DYN_TYPE_ERROR;
    }
    a->pointers = p;
    a->pointer_capacity = c;
  }
  a->pointers[a->pointer_count] = (DynAstPointer){pointee, is_const};
  return DYN_TYPE_POINTER_BASE + a->pointer_count++;
}
static DynType sema_intern_array(DynAstProgram *a, DynType element,
                                 uint64_t length) {
  for (uint32_t i = 0; i < a->array_count; ++i)
    if (a->arrays[i].element == element && a->arrays[i].length == length)
      return DYN_TYPE_ARRAY_BASE + i;
  if (a->array_count == a->array_capacity) {
    size_t c = a->array_capacity ? a->array_capacity * 2 : 8;
    void *p = realloc(a->arrays, c * sizeof(*a->arrays));
    if (!p) {
      a->allocation_failed = true;
      return DYN_TYPE_ERROR;
    }
    a->arrays = p;
    a->array_capacity = c;
  }
  a->arrays[a->array_count] = (DynAstArray){element, length};
  return DYN_TYPE_ARRAY_BASE + a->array_count++;
}
static DynType sema_intern_slice(DynAstProgram *a, DynType element,
                                 bool is_const) {
  for (uint32_t i = 0; i < a->slice_count; ++i)
    if (a->slices[i].element == element && a->slices[i].is_const == is_const)
      return DYN_TYPE_SLICE_BASE + i;
  if (a->slice_count == a->slice_capacity) {
    size_t c = a->slice_capacity ? a->slice_capacity * 2 : 8;
    void *p = realloc(a->slices, c * sizeof(*a->slices));
    if (!p) {
      a->allocation_failed = true;
      return DYN_TYPE_ERROR;
    }
    a->slices = p;
    a->slice_capacity = c;
  }
  a->slices[a->slice_count] = (DynAstSlice){element, is_const};
  return DYN_TYPE_SLICE_BASE + a->slice_count++;
}
static DynType sema_intern_fn_type_ex(DynAstProgram *a, const DynType *params,
                                      uint32_t count, DynType result,
                                      bool variadic) {
  for (uint32_t i = 0; i < a->fn_type_count; ++i) {
    DynAstFnType *f = &a->fn_types[i];
    if (f->return_type != result || f->param_count != count ||
        f->variadic != variadic)
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
    if (!p) {
      a->allocation_failed = true;
      return DYN_TYPE_ERROR;
    }
    a->fn_types = p;
    a->fn_type_capacity = c;
  }
  if (a->fn_type_param_count + count > a->fn_type_param_capacity) {
    size_t c = a->fn_type_param_capacity ? a->fn_type_param_capacity * 2 : 16;
    while (c < a->fn_type_param_count + count)
      c *= 2;
    void *p = realloc(a->fn_type_params, c * sizeof(*a->fn_type_params));
    if (!p) {
      a->allocation_failed = true;
      return DYN_TYPE_ERROR;
    }
    a->fn_type_params = p;
    a->fn_type_param_capacity = c;
  }
  uint32_t start = (uint32_t)a->fn_type_param_count;
  for (uint32_t i = 0; i < count; ++i)
    a->fn_type_params[a->fn_type_param_count++] = params[i];
  a->fn_types[a->fn_type_count] =
      (DynAstFnType){result, start, count, variadic};
  return DYN_TYPE_FN_BASE + a->fn_type_count++;
}
static DynType sema_intern_fn_type(DynAstProgram *a, const DynType *params,
                                   uint32_t count, DynType result) {
  return sema_intern_fn_type_ex(a, params, count, result, false);
}
static DynType function_pointer_type(DynAstProgram *a, uint32_t id) {
  DynAstFn *f = &a->functions[id];
  DynType *params = calloc(f->param_count, sizeof(*params));
  if (f->param_count && !params)
    return DYN_TYPE_ERROR;
  for (uint32_t i = 0; i < f->param_count; ++i)
    params[i] = a->params[f->param_start + i].type;
  DynType signature = sema_intern_fn_type_ex(
      a, params, f->param_count, f->return_type, f->foreign && f->variadic);
  free(params);
  return signature == DYN_TYPE_ERROR ? signature
                                     : sema_intern_pointer(a, signature, false);
}
static DynType function_signature_type(DynAstProgram *a, uint32_t id) {
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
static bool can_convert(Sema *sema, DynAstProgram *a, DynType from,
                        DynType to) {
  if (to == DYN_TYPE_ANY && from != DYN_TYPE_VOID && from != DYN_TYPE_ERROR)
    return true;
  if (lossless(sema, from, to))
    return true;
  DynAstPointer *f = pointer_info(a, from), *t = pointer_info(a, to);
  if (f && t)
    return f->pointee == t->pointee && !f->is_const && t->is_const;
  DynAstSlice *fs = slice_info(a, from), *ts = slice_info(a, to);
  return fs && ts && fs->element == ts->element && !fs->is_const &&
         ts->is_const;
}
static DynExprId convert_expr(DynAstProgram *a, DynExprId source,
                              DynType target) {
  if (a->expression_count == a->expression_capacity) {
    size_t c = a->expression_capacity ? a->expression_capacity * 2 : 32;
    void *p = realloc(a->expressions, c * sizeof(*a->expressions));
    if (!p) {
      a->allocation_failed = true;
      return DYN_NO_EXPR;
    }
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
static ConstantInt constant_int(DynAstProgram *a, DynExprId id) {
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
static ConstantUInt constant_uint(DynAstProgram *a, DynExprId id) {
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
static bool constant_fits_type(Sema *sema, int64_t v, DynType t) {
  unsigned b = bits(sema, t);
  if (signed_int(sema, t)) {
    if (b == 64)
      return true;
    int64_t min = -(INT64_C(1) << (b - 1)), max = (INT64_C(1) << (b - 1)) - 1;
    return v >= min && v <= max;
  }
  if (!integer(sema, t) || v < 0)
    return false;
  return b == 64 || ((uint64_t)v <= (UINT64_C(1) << b) - 1);
}
static bool lvalue_const(DynAstProgram *, DynExprId);
static bool span_is(DynSpan p, const DynSource *s, const char *name) {
  size_t n = strlen(name);
  return p.end_byte - p.start_byte == n &&
         !memcmp(s->text + p.start_byte, name, n);
}
static bool reserve_reflection_items(DynAstProgram *a, size_t extra) {
  if (a->item_count + extra <= a->item_capacity)
    return true;
  size_t c = a->item_capacity ? a->item_capacity * 2 : 16;
  while (c < a->item_count + extra)
    c *= 2;
  void *p = realloc(a->items, c * sizeof(*a->items));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }
  a->items = p;
  a->item_capacity = c;
  return true;
}
static bool reserve_reflection_string(DynAstProgram *a) {
  if (a->string_count < a->string_capacity)
    return true;
  size_t c = a->string_capacity ? a->string_capacity * 2 : 8;
  void *p = realloc(a->strings, c * sizeof(*a->strings));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }
  a->strings = p;
  a->string_capacity = c;
  return true;
}
static void type_name_into(DynAstProgram *a, DynType t, const DynSource *s,
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
static unsigned reflection_kind(Sema *sema, DynType t) {
  if (t == DYN_TYPE_VOID)
    return 1;
  if (t == DYN_TYPE_BOOL)
    return 2;
  if (integer(sema, t))
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
static void display_type_name(DynAstProgram *a, DynType t, const DynSource *s,
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
void dyn_type_format(DynAstProgram *a, DynType t, const DynSource *s, char *out,
                     size_t capacity) {
  display_type_name(a, t, s, out, capacity);
}
#define type_name_into display_type_name
static DynExprId reflection_expr(DynAstProgram *a, DynExprKind kind,
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
static DynExprId reflection_string(DynAstProgram *a, DynType type,
                                   const char *bytes, size_t length) {
  if (!reserve_reflection_string(a))
    return DYN_NO_EXPR;
  unsigned char *copy = malloc(length);
  if (length && !copy)
    return DYN_NO_EXPR;
  if (length)
    memcpy(copy, bytes, length);
  uint32_t string = (uint32_t)a->string_count;
  a->strings[a->string_count++] = (DynAstString){copy, length};
  return reflection_expr(a, DYN_EXPR_STRING, type, string);
}
static DynExprId reflection_members(DynAstProgram *a, const DynSource *s,
                                    DynType member_type, DynType slice_type,
                                    const DynSpan *names, const DynType *types,
                                    uint32_t count) {
  if (!count)
    return reflection_expr(a, DYN_EXPR_NIL, slice_type, 0);
  if (!reserve_reflection_items(a, (size_t)count * 3))
    return DYN_NO_EXPR;
  uint32_t array_start = (uint32_t)a->item_count;
  a->item_count += count;
  DynType name_type =
      a->fields[a->structs[member_type - DYN_TYPE_STRUCT_BASE].field_start]
          .type;
  for (uint32_t i = 0; i < count; ++i) {
    size_t n = names ? names[i].end_byte - names[i].start_byte : 0;
    const char *sname = names ? s->text + names[i].start_byte : "";
    DynExprId name = reflection_string(a, name_type, sname, n);
    char type_name[512];
    type_name_into(a, types[i], s, type_name, sizeof(type_name));
    DynExprId type_id = reflection_expr(
        a, DYN_EXPR_INT, DYN_TYPE_U64,
        types[i] == DYN_TYPE_VOID ? 0 : reflection_id(type_name));
    if (name == DYN_NO_EXPR || type_id == DYN_NO_EXPR)
      return DYN_NO_EXPR;
    uint32_t fields = (uint32_t)a->item_count;
    a->items[a->item_count++] =
        (DynAstItem){.expression = name, .field_index = 0};
    a->items[a->item_count++] =
        (DynAstItem){.expression = type_id, .field_index = 1};
    DynExprId member = reflection_expr(a, DYN_EXPR_STRUCT, member_type,
                                       member_type - DYN_TYPE_STRUCT_BASE);
    if (member == DYN_NO_EXPR)
      return DYN_NO_EXPR;
    a->expressions[member].item_start = fields;
    a->expressions[member].item_count = 2;
    a->items[array_start + i] = (DynAstItem){.expression = member};
  }
  DynType array_type = sema_intern_array(a, member_type, count);
  DynExprId array = reflection_expr(a, DYN_EXPR_ARRAY, array_type, 0);
  DynExprId slice = reflection_expr(a, DYN_EXPR_SLICE, slice_type, DYN_NO_EXPR);
  if (array == DYN_NO_EXPR || slice == DYN_NO_EXPR)
    return DYN_NO_EXPR;
  a->expressions[array].item_start = array_start;
  a->expressions[array].item_count = count;
  a->expressions[slice].left = array;
  a->expressions[slice].right = DYN_NO_EXPR;
  return slice;
}
static DynType check_expr(Sema *sema, DynAstProgram *a, DynExprId id,
                          const DynSource *s, unsigned *errors,
                          DynType expected) {
  if (!dyn_work_step(&s->context, 1)) return DYN_TYPE_ERROR;
  if (id == DYN_NO_EXPR)
    return DYN_TYPE_VOID;
  /* Recursive checks may grow expression, item and interned-type tables.
     Keep IDs/scalar copies across calls, never table-entry pointers. */
  uint32_t qualified_enum = sema_expr_enum(a, a->expressions[id].left, s);
  if (a->expressions[id].kind == DYN_EXPR_ENUM && qualified_enum == UINT32_MAX) {
    a->expressions[id].kind = DYN_EXPR_INDIRECT_CALL;
    a->expressions[id].left = a->expressions[id].right;
    a->expressions[id].right = DYN_NO_EXPR;
  }
  if (a->expressions[id].kind == DYN_EXPR_ENUM ||
      (a->expressions[id].kind == DYN_EXPR_FIELD && qualified_enum != UINT32_MAX)) {
    uint32_t eid = qualified_enum,
             variant = sema_find_variant(a, eid, a->expressions[id].span, s);
    a->expressions[id].left = DYN_NO_EXPR;
    if (variant == UINT32_MAX) {
      error_span(a->expressions[id].span, s, errors, "unknown enum variant");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    DynAstVariant *v = &a->variants[variant];
    bool constructor = a->expressions[id].kind == DYN_EXPR_ENUM;
    a->expressions[id].kind = DYN_EXPR_ENUM;
    a->expressions[id].integer = variant;
    a->expressions[id].type = DYN_TYPE_ENUM_BASE + eid;
    if (v->payload_type == DYN_TYPE_VOID) {
      if (constructor || a->expressions[id].item_count)
        error_span(a->expressions[id].span, s, errors,
                   "payloadless enum variant is not callable");
    } else if (!constructor) {
      if (expected != a->expressions[id].type)
        error_span(a->expressions[id].span, s, errors,
                   "payload enum variant requires exactly one argument");
    } else if (a->expressions[id].item_count != 1)
      error_span(a->expressions[id].span, s, errors,
                 "payload enum variant requires exactly one argument");
    else {
      uint32_t item_start = a->expressions[id].item_start;
      DynSpan enum_span = a->expressions[id].span;
      uint32_t arg_index = item_start;
      DynType value =
          check_expr(sema, a, a->items[arg_index].expression, s, errors, v->payload_type);
      if (value != v->payload_type && value != DYN_TYPE_ERROR) {
        if (can_convert(sema, a, value, v->payload_type))
          a->items[arg_index].expression = convert_expr(a, a->items[arg_index].expression, v->payload_type);
        else
          error_span(enum_span, s, errors, "enum payload type mismatch");
      }
    }
    return a->expressions[id].type;
  }
  if (a->expressions[id].kind == DYN_EXPR_CALL) {
    uint32_t fn = sema_find_function(sema, a, a->expressions[id].span, s);
    if (fn == UINT32_MAX) {
      if (find_local(sema, a, a->expressions[id].span, s) == UINT32_MAX &&
          sema_find_global_name(sema, a, a->expressions[id].span, s) == UINT32_MAX) {
        char message[256];
        error_span(a->expressions[id].span, s, errors,
                   suggest_name(a, a->expressions[id].span, s, true, message, sizeof(message))
                       ? message
                       : "unknown function");
        for (uint32_t i = 0; i < a->expressions[id].item_count; ++i)
          (void)check_expr(sema, a, a->items[a->expressions[id].item_start + i].expression, s,
                           errors, DYN_TYPE_INFER);
        return a->expressions[id].type = DYN_TYPE_ERROR;
      }
      DynSpan call_span = a->expressions[id].span;
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
      a->expressions[id].left = target;
      a->expressions[id].kind = DYN_EXPR_INDIRECT_CALL;
    } else {
      a->expressions[id].left = DYN_NO_EXPR;
      a->expressions[id].integer = fn;
      DynAstFn *callee = &a->functions[fn];
      if (!sema_c_abi_function(a, callee))
        error_span(a->expressions[id].span, s, errors,
                   "type has no supported C ABI; use C-compatible storage or a pointer adapter");
      if ((!callee->variadic && a->expressions[id].item_count != callee->param_count) ||
          (callee->variadic && a->expressions[id].item_count < callee->param_count))
        error_span(a->expressions[id].span, s, errors, "function argument count mismatch");
      uint32_t count = a->expressions[id].item_count < callee->param_count
                           ? a->expressions[id].item_count
                           : callee->param_count;
      uint32_t item_start = a->expressions[id].item_start;
      DynType return_type = callee->return_type;
      for (uint32_t i = 0; i < count; ++i) {
        uint32_t arg_index = item_start + i;
        DynType target = a->params[callee->param_start + i].type,
                value = check_expr(sema, a, a->items[arg_index].expression, s, errors, target);
        if (value != target && value != DYN_TYPE_ERROR &&
            target != DYN_TYPE_ERROR) {
          if (can_convert(sema, a, value, target))
            a->items[arg_index].expression = convert_expr(a, a->items[arg_index].expression, target);
          else
            error_types(a->expressions[a->items[arg_index].expression].span, s, errors,
                        "function argument type mismatch", target, value);
        }
      }
      if (callee->variadic && callee->foreign)
        for (uint32_t i = callee->param_count; i < a->expressions[id].item_count; ++i) {
          uint32_t arg_index = item_start + i;
          DynType value =
              check_expr(sema, a, a->items[arg_index].expression, s, errors, DYN_TYPE_INFER);
          DynType promoted = value;
          if (value == DYN_TYPE_F32)
            promoted = DYN_TYPE_F64;
          else if (value == DYN_TYPE_I8 || value == DYN_TYPE_I16 ||
                   value == DYN_TYPE_U8 || value == DYN_TYPE_U16)
            promoted = DYN_TYPE_I32;
          if (promoted != value && value != DYN_TYPE_ERROR)
            a->items[arg_index].expression = convert_expr(a, a->items[arg_index].expression, promoted);
          else if (value != DYN_TYPE_I32 && value != DYN_TYPE_U32 &&
                   value != DYN_TYPE_I64 && value != DYN_TYPE_U64 &&
                   value != DYN_TYPE_ISIZE && value != DYN_TYPE_USIZE &&
                   value != DYN_TYPE_F64 && !dyn_type_is_pointer(value) &&
                   value != DYN_TYPE_ERROR)
            error_span(
                a->expressions[a->items[arg_index].expression].span, s, errors,
                "C variadic argument requires integer, float, or pointer");
        }
      else if (callee->variadic)
        for (uint32_t i = callee->param_count; i < a->expressions[id].item_count; ++i) {
          uint32_t arg_index = item_start + i;
          DynType element = slice_info(a, callee->variadic_type)->element;
          DynType value =
              check_expr(sema, a, a->items[arg_index].expression, s, errors,
                         element == DYN_TYPE_ANY ? DYN_TYPE_INFER : element);
          if (element != DYN_TYPE_ANY && value != element &&
              value != DYN_TYPE_ERROR) {
            if (can_convert(sema, a, value, element))
              a->items[arg_index].expression = convert_expr(a, a->items[arg_index].expression, element);
            else
              error_span(a->expressions[a->items[arg_index].expression].span, s, errors,
                         "variadic argument type mismatch");
          }
        }
      return a->expressions[id].type = return_type;
    }
  }
  if (a->expressions[id].kind == DYN_EXPR_INDIRECT_CALL) {
    DynExprId target_expr = a->expressions[id].left;
    uint32_t item_start = a->expressions[id].item_start, item_count = a->expressions[id].item_count;
    DynSpan call_span = a->expressions[id].span;
    DynType target =
        check_expr(sema, a, target_expr, s, errors, DYN_TYPE_INFER);
    DynAstPointer *p = pointer_info(a, target);
    DynAstFnType *signature = p ? fn_type_info(a, p->pointee) : NULL;
    if (!signature) {
      if (target != DYN_TYPE_ERROR)
        error_span(call_span, s, errors,
                   "call target must be function pointer");
      for (uint32_t i = 0; i < item_count; ++i)
        (void)check_expr(sema, a, a->items[item_start + i].expression, s,
                         errors, DYN_TYPE_INFER);
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    DynAstFnType signature_value = *signature;
    DynType function_type = p->pointee;
    signature = &signature_value;
    if ((!signature->variadic && item_count != signature->param_count) ||
        (signature->variadic && item_count < signature->param_count))
      error_span(call_span, s, errors,
                 "function pointer argument count mismatch");
    uint32_t count = item_count < signature->param_count
                         ? item_count
                         : signature->param_count;
    for (uint32_t i = 0; i < count; ++i) {
      uint32_t arg_index = item_start + i;
      DynType want = a->fn_type_params[signature->param_start + i],
              value = check_expr(sema, a, a->items[arg_index].expression, s, errors, want);
      if (value != want && value != DYN_TYPE_ERROR) {
        if (can_convert(sema, a, value, want))
          a->items[arg_index].expression = convert_expr(a, a->items[arg_index].expression, want);
        else
          error_types(a->expressions[a->items[arg_index].expression].span, s, errors,
                      "function pointer argument type mismatch", want, value);
      }
    }
    if (signature->variadic)
      for (uint32_t i = signature->param_count; i < item_count; ++i) {
        uint32_t arg_index = item_start + i;
        DynType value =
            check_expr(sema, a, a->items[arg_index].expression, s, errors, DYN_TYPE_INFER);
        DynType promoted = value;
        if (value == DYN_TYPE_F32)
          promoted = DYN_TYPE_F64;
        else if (value == DYN_TYPE_I8 || value == DYN_TYPE_I16 ||
                 value == DYN_TYPE_U8 || value == DYN_TYPE_U16)
          promoted = DYN_TYPE_I32;
        if (promoted != value && value != DYN_TYPE_ERROR)
          a->items[arg_index].expression = convert_expr(a, a->items[arg_index].expression, promoted);
        else if (value != DYN_TYPE_I32 && value != DYN_TYPE_U32 &&
                 value != DYN_TYPE_I64 && value != DYN_TYPE_U64 &&
                 value != DYN_TYPE_ISIZE && value != DYN_TYPE_USIZE &&
                 value != DYN_TYPE_F64 && !dyn_type_is_pointer(value) &&
                 value != DYN_TYPE_ERROR)
          error_span(a->expressions[a->items[arg_index].expression].span, s, errors,
                     "C variadic argument requires integer, float, or pointer");
      }
    a->expressions[id].integer = function_type - DYN_TYPE_FN_BASE;
    return a->expressions[id].type = signature->return_type;
  }
  if (a->expressions[id].kind == DYN_EXPR_FUNCTION)
    return a->expressions[id].type;
  if (a->expressions[id].kind == DYN_EXPR_NAME) {
    uint32_t l = find_local(sema, a, a->expressions[id].span, s);
    if (l != UINT32_MAX) {
      a->expressions[id].integer = l;
      return a->expressions[id].type = a->locals[l].type;
    }
    uint32_t global = sema_find_global_name(sema, a, a->expressions[id].span, s);
    if (global != UINT32_MAX) {
      a->expressions[id].kind = DYN_EXPR_GLOBAL;
      a->expressions[id].integer = global;
      return a->expressions[id].type = a->globals[global].type;
    }
    char message[256];
    error_span(a->expressions[id].span, s, errors,
               suggest_name(a, a->expressions[id].span, s, false, message, sizeof(message))
                   ? message
                   : "unknown name");
    return a->expressions[id].type = DYN_TYPE_ERROR;
  }
  if (a->expressions[id].kind == DYN_EXPR_ARRAY) {
    DynAstArray *want = array_info(a, expected);
    if (!a->expressions[id].item_count && !want) {
      error_span(a->expressions[id].span, s, errors,
                 "empty array literal requires expected fixed-array type");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    if (want && a->expressions[id].item_count > want->length) {
      error_span(a->expressions[id].span, s, errors, "array literal has too many elements");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    DynType element = want ? want->element : DYN_TYPE_INFER;
    for (uint32_t i = 0; i < a->expressions[id].item_count; ++i) {
      uint32_t item_index = a->expressions[id].item_start + i;
      DynType value = check_expr(sema, a, a->items[item_index].expression, s, errors, element);
      if (element == DYN_TYPE_INFER)
        element = value;
      else if (value != element && value != DYN_TYPE_ERROR) {
        if (can_convert(sema, a, value, element))
          a->items[item_index].expression = convert_expr(a, a->items[item_index].expression, element);
        else
          error_span(a->expressions[a->items[item_index].expression].span, s, errors,
                     "array element type mismatch");
      }
    }
    return a->expressions[id].type =
               want ? expected : sema_intern_array(a, element, a->expressions[id].item_count);
  }
  if (a->expressions[id].kind == DYN_EXPR_INDEX) {
    DynType base = check_expr(sema, a, a->expressions[id].left, s, errors, DYN_TYPE_INFER),
            index = check_expr(sema, a, a->expressions[id].right, s, errors, DYN_TYPE_USIZE);
    if (!integer(sema, index) || signed_int(sema, index))
      error_span(a->expressions[id].span, s, errors, "array index requires unsigned integer");
    DynAstArray *ar = array_info(a, base);
    DynAstSlice *sl = slice_info(a, base);
    if (!ar && !sl) {
      error_span(a->expressions[id].span, s, errors, "indexing requires array or slice");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    return a->expressions[id].type = ar ? ar->element : sl->element;
  }
  if (a->expressions[id].kind == DYN_EXPR_SLICE) {
    DynType base = check_expr(sema, a, a->expressions[id].left, s, errors, DYN_TYPE_INFER);
    DynAstArray *ar = array_info(a, base);
    DynAstSlice *sl = slice_info(a, base);
    DynAstPointer *pointer = pointer_info(a, base);
    if (!ar && !sl && !pointer) {
      error_span(a->expressions[id].span, s, errors,
                 "slicing requires array, slice, or pointer range");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    if (pointer && a->expressions[id].integer == DYN_NO_EXPR) {
      error_span(a->expressions[id].span, s, errors,
                 "pointer slicing requires explicit end bound");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    if (pointer && !sema_type_layout(sema, a, pointer->pointee, false)) {
      error_span(a->expressions[id].span, s, errors, "cannot slice pointer to unsized type");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    DynType element = ar ? ar->element : sl ? sl->element : pointer->pointee;
    bool element_const = sl ? sl->is_const : pointer && pointer->is_const;
    if (a->expressions[id].right != DYN_NO_EXPR) {
      DynType t = check_expr(sema, a, a->expressions[id].right, s, errors, DYN_TYPE_USIZE);
      if (!integer(sema, t) || signed_int(sema, t))
        error_span(a->expressions[id].span, s, errors, "slice bound requires unsigned integer");
    }
    if (a->expressions[id].integer != DYN_NO_EXPR) {
      DynType t =
          check_expr(sema, a, (DynExprId)a->expressions[id].integer, s, errors, DYN_TYPE_USIZE);
      if (!integer(sema, t) || signed_int(sema, t))
        error_span(a->expressions[id].span, s, errors, "slice bound requires unsigned integer");
    }
    return a->expressions[id].type = sema_intern_slice(a, element, element_const);
  }
  if (a->expressions[id].kind == DYN_EXPR_LEN) {
    DynType base = check_expr(sema, a, a->expressions[id].left, s, errors, DYN_TYPE_INFER);
    if (!dyn_type_is_array(base) && !dyn_type_is_slice(base)) {
      error_span(a->expressions[id].span, s, errors, "#len requires array or slice");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    return a->expressions[id].type = DYN_TYPE_USIZE;
  }
  if (a->expressions[id].kind == DYN_EXPR_TYPEOF) {
    DynType operand;
    uint32_t reflected_fn = UINT32_MAX;
    if (a->expressions[id].boolean)
      operand = (DynType)a->expressions[id].integer;
    else {
      DynAstExpr *source = &a->expressions[a->expressions[id].left];
      reflected_fn = source->kind == DYN_EXPR_NAME
                         ? sema_find_function(sema, a, source->span, s)
                         : UINT32_MAX;
      operand = reflected_fn == UINT32_MAX
                    ? check_expr(sema, a, a->expressions[id].left, s, errors, DYN_TYPE_INFER)
                    : function_signature_type(a, reflected_fn);
    }
    uint32_t info = UINT32_MAX, member = UINT32_MAX, kind_enum = UINT32_MAX;
    for (uint32_t i = 0; i < a->struct_count; ++i)
      if (span_is(a->structs[i].name, s, "TypeInfo"))
        info = i;
      else if (span_is(a->structs[i].name, s, "TypeMember"))
        member = i;
    for (uint32_t i = 0; i < a->enum_count; ++i)
      if (span_is(a->enums[i].name, s, "TypeKind"))
        kind_enum = i;
    if (info == UINT32_MAX || member == UINT32_MAX || kind_enum == UINT32_MAX) {
      error_span(a->expressions[id].span, s, errors, "compiler reflection ABI is unavailable");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    DynAstStruct *st = &a->structs[info];
    DynAstEnum *en = &a->enums[kind_enum];
    bool abi =
        st->field_count == 13 && a->structs[member].field_count == 2 &&
        en->variant_count >= 11 &&
        a->fields[st->field_start].type == DYN_TYPE_U64 &&
        a->fields[st->field_start + 1].type == DYN_TYPE_ENUM_BASE + kind_enum &&
        a->fields[st->field_start + 3].type == DYN_TYPE_USIZE &&
        a->fields[st->field_start + 4].type == DYN_TYPE_USIZE &&
        a->fields[st->field_start + 5].type == DYN_TYPE_U64 &&
        a->fields[st->field_start + 6].type == DYN_TYPE_USIZE &&
        a->fields[st->field_start + 7].type == DYN_TYPE_USIZE &&
        a->fields[st->field_start + 8].type == DYN_TYPE_USIZE &&
        a->fields[st->field_start + 9].type == DYN_TYPE_U64;
    if (!abi) {
      error_span(a->expressions[id].span, s, errors, "compiler TypeInfo ABI mismatch");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    char name[512];
    type_name_into(a, operand, s, name, sizeof(name));
    size_t length = strlen(name);
    if (!reserve_reflection_string(a) || !reserve_reflection_items(a, 13)) {
      error_span(a->expressions[id].span, s, errors, "out of memory");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    unsigned char *bytes = malloc(length);
    if (length && !bytes) {
      error_span(a->expressions[id].span, s, errors, "out of memory");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    if (length)
      memcpy(bytes, name, length);
    uint32_t string = (uint32_t)a->string_count;
    a->strings[a->string_count++] = (DynAstString){bytes, length};
    uint32_t start = (uint32_t)a->item_count;
    a->item_count += 13;
    DynExprId values[13];
    values[0] =
        reflection_expr(a, DYN_EXPR_INT, DYN_TYPE_U64, reflection_id(name));
    unsigned k = reflection_kind(sema, operand);
    values[1] =
        reflection_expr(a, DYN_EXPR_ENUM, DYN_TYPE_ENUM_BASE + kind_enum,
                        en->variant_start + k);
    values[2] = reflection_expr(a, DYN_EXPR_STRING,
                                a->fields[st->field_start + 2].type, string);
    uint64_t size = operand == DYN_TYPE_VOID || dyn_type_is_function(operand)
                        ? 0
                        : sema_type_layout(sema, a, operand, false),
             alignment =
                 operand == DYN_TYPE_VOID || dyn_type_is_function(operand)
                     ? 1
                     : sema_type_layout(sema, a, operand, true);
    values[3] = reflection_expr(a, DYN_EXPR_INT, DYN_TYPE_USIZE, size);
    values[4] = reflection_expr(a, DYN_EXPR_INT, DYN_TYPE_USIZE, alignment);
    DynType element = DYN_TYPE_VOID, result = DYN_TYPE_VOID;
    uint64_t array_length = 0, members = 0, parameters = 0;
    if (dyn_type_is_pointer(operand))
      element = pointer_info(a, operand)->pointee;
    else if (dyn_type_is_array(operand)) {
      element = array_info(a, operand)->element;
      array_length = array_info(a, operand)->length;
    } else if (dyn_type_is_slice(operand))
      element = slice_info(a, operand)->element;
    else if (dyn_type_is_struct(operand))
      members = a->structs[operand - DYN_TYPE_STRUCT_BASE].field_count;
    else if (dyn_type_is_enum(operand))
      members = a->enums[operand - DYN_TYPE_ENUM_BASE].variant_count;
    else if (dyn_type_is_function(operand)) {
      DynAstFnType *fn = fn_type_info(a, operand);
      parameters = fn->param_count;
      result = fn->return_type;
    }
    char related_name[512];
    uint64_t element_id = 0, result_id = 0;
    if (element != DYN_TYPE_VOID) {
      type_name_into(a, element, s, related_name, sizeof(related_name));
      element_id = reflection_id(related_name);
    }
    if (result != DYN_TYPE_VOID) {
      type_name_into(a, result, s, related_name, sizeof(related_name));
      result_id = reflection_id(related_name);
    }
    values[5] = reflection_expr(a, DYN_EXPR_INT, DYN_TYPE_U64, element_id);
    values[6] = reflection_expr(a, DYN_EXPR_INT, DYN_TYPE_USIZE, array_length);
    values[7] = reflection_expr(a, DYN_EXPR_INT, DYN_TYPE_USIZE, members);
    values[8] = reflection_expr(a, DYN_EXPR_INT, DYN_TYPE_USIZE, parameters);
    values[9] = reflection_expr(a, DYN_EXPR_INT, DYN_TYPE_U64, result_id);
    DynType member_type = DYN_TYPE_STRUCT_BASE + member;
    DynType member_slice = sema_intern_slice(a, member_type, true);
    values[10] = reflection_expr(a, DYN_EXPR_NIL, member_slice, 0);
    values[11] = reflection_expr(a, DYN_EXPR_NIL, member_slice, 0);
    values[12] = reflection_expr(a, DYN_EXPR_NIL, member_slice, 0);
    if (dyn_type_is_struct(operand)) {
      DynAstStruct *subject = &a->structs[operand - DYN_TYPE_STRUCT_BASE];
      DynSpan *names = calloc(subject->field_count, sizeof(*names));
      DynType *types = calloc(subject->field_count, sizeof(*types));
      if (subject->field_count && (!names || !types))
        values[10] = DYN_NO_EXPR;
      for (uint32_t i = 0; i < subject->field_count && names && types; ++i) {
        names[i] = a->fields[subject->field_start + i].name;
        types[i] = a->fields[subject->field_start + i].type;
      }
      if (names && types)
        values[10] = reflection_members(a, s, member_type, member_slice, names,
                                        types, subject->field_count);
      free(names);
      free(types);
    } else if (dyn_type_is_enum(operand)) {
      DynAstEnum *subject = &a->enums[operand - DYN_TYPE_ENUM_BASE];
      DynSpan *names = calloc(subject->variant_count, sizeof(*names));
      DynType *types = calloc(subject->variant_count, sizeof(*types));
      if (subject->variant_count && (!names || !types))
        values[11] = DYN_NO_EXPR;
      for (uint32_t i = 0; i < subject->variant_count && names && types; ++i) {
        names[i] = a->variants[subject->variant_start + i].name;
        types[i] = a->variants[subject->variant_start + i].payload_type;
      }
      if (names && types)
        values[11] = reflection_members(a, s, member_type, member_slice, names,
                                        types, subject->variant_count);
      free(names);
      free(types);
    } else if (dyn_type_is_function(operand)) {
      DynAstFnType *signature = fn_type_info(a, operand);
      DynSpan *names = calloc(signature->param_count, sizeof(*names));
      DynType *types = calloc(signature->param_count, sizeof(*types));
      if (signature->param_count && (!names || !types))
        values[12] = DYN_NO_EXPR;
      for (uint32_t i = 0; i < signature->param_count && names && types; ++i) {
        types[i] = a->fn_type_params[signature->param_start + i];
        if (reflected_fn != UINT32_MAX)
          names[i] = a->params[a->functions[reflected_fn].param_start + i].name;
      }
      if (names && types)
        values[12] = reflection_members(a, s, member_type, member_slice, names,
                                        types, signature->param_count);
      free(names);
      free(types);
    }
    for (uint32_t i = 0; i < 13; ++i) {
      if (values[i] == DYN_NO_EXPR) {
        error_span(a->expressions[id].span, s, errors, "out of memory");
        return a->expressions[id].type = DYN_TYPE_ERROR;
      }
      a->items[start + i] =
          (DynAstItem){.expression = values[i], .field_index = i};
    }
    a->expressions[id].kind = DYN_EXPR_STRUCT;
    a->expressions[id].type = DYN_TYPE_STRUCT_BASE + info;
    a->expressions[id].integer = info;
    a->expressions[id].left = a->expressions[id].right = DYN_NO_EXPR;
    a->expressions[id].item_start = start;
    a->expressions[id].item_count = 13;
    return a->expressions[id].type;
  }
  if (a->expressions[id].kind == DYN_EXPR_SIZE || a->expressions[id].kind == DYN_EXPR_ALIGN) {
    DynType operand =
        a->expressions[id].boolean ? (DynType)a->expressions[id].integer
                   : check_expr(sema, a, a->expressions[id].left, s, errors, DYN_TYPE_INFER);
    uint64_t value = sema_type_layout(sema, a, operand, a->expressions[id].kind == DYN_EXPR_ALIGN);
    if (!value) {
      error_span(a->expressions[id].span, s, errors,
                 a->expressions[id].kind == DYN_EXPR_ALIGN
                     ? "#alignof requires sized value or type"
                     : "#sizeof requires sized value or type");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    a->expressions[id].kind = DYN_EXPR_INT;
    a->expressions[id].integer = value;
    return a->expressions[id].type = DYN_TYPE_USIZE;
  }
  if (a->expressions[id].kind == DYN_EXPR_CAST) {
    DynType source = check_expr(sema, a, a->expressions[id].left, s, errors, DYN_TYPE_INFER),
            target = (DynType)a->expressions[id].integer;
    if (source == DYN_TYPE_ERROR)
      return a->expressions[id].type = DYN_TYPE_ERROR;
    bool source_ptr = dyn_type_is_pointer(source) || source == DYN_TYPE_RAWPTR;
    bool target_ptr = dyn_type_is_pointer(target) || target == DYN_TYPE_RAWPTR;
    bool valid = (numeric(sema, source) && numeric(sema, target)) ||
                 (source_ptr && target_ptr) ||
                 (source_ptr && integer(sema, target)) ||
                 (integer(sema, source) && target_ptr) || source == target;
    if (!valid) {
      char from[128], to[128], message[320];
      type_name_into(a, source, s, from, sizeof(from));
      type_name_into(a, target, s, to, sizeof(to));
      snprintf(message, sizeof(message), "cannot cast %s to %s", from, to);
      error_span(a->expressions[id].span, s, errors, message);
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    return a->expressions[id].type = target;
  }
  if (a->expressions[id].kind == DYN_EXPR_BITCAST) {
    DynType source = check_expr(sema, a, a->expressions[id].left, s, errors, DYN_TYPE_INFER),
            target = (DynType)a->expressions[id].integer;
    bool scalar = (numeric(sema, source) || dyn_type_is_pointer(source)) &&
                  (numeric(sema, target) || dyn_type_is_pointer(target));
    uint64_t from = sema_type_layout(sema, a, source, false),
             to = sema_type_layout(sema, a, target, false);
    if (!scalar || !from || from != to ||
        (dyn_type_is_pointer(source) != dyn_type_is_pointer(target))) {
      error_span(a->expressions[id].span, s, errors,
                 "#bitcast requires compatible scalar representation sizes");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    return a->expressions[id].type = target;
  }
  if (a->expressions[id].kind == DYN_EXPR_SYSCALL) {
    if (a->expressions[id].item_count < 1 || a->expressions[id].item_count > 7)
      error_span(a->expressions[id].span, s, errors,
                 "#syscall requires syscall number and at most six arguments");
    for (uint32_t i = 0; i < a->expressions[id].item_count; ++i) {
      DynType t = check_expr(sema, a, a->items[a->expressions[id].item_start + i].expression, s,
                             errors, DYN_TYPE_INFER);
      if (!integer(sema, t) && !dyn_type_is_pointer(t))
        error_span(a->expressions[a->items[a->expressions[id].item_start + i].expression].span,
                   s, errors, "#syscall arguments require integer or pointer");
    }
    if (a->expressions[id].item_count &&
        !strcmp(dyn_context_target(&s->context)->kernel, "linux") &&
        !strcmp(dyn_context_target(&s->context)->arch, "aarch64")) {
      DynAstExpr *number = &a->expressions[a->items[a->expressions[id].item_start].expression];
      uint64_t native = 0;
      if (number->kind != DYN_EXPR_INT)
        error_span(number->span, s, errors,
                   "AArch64 #syscall number must be a constant portable Linux "
                   "syscall ID");
      else if (!dyn_target_syscall_number(dyn_context_target(&s->context),
                                          number->integer, &native))
        error_span(number->span, s, errors,
                   "syscall has no AArch64 Linux mapping");
      else
        number->integer = native;
    }
    return a->expressions[id].type = DYN_TYPE_ISIZE;
  }
  if (a->expressions[id].kind == DYN_EXPR_CONVERT)
    return a->expressions[id].type;
  if (a->expressions[id].kind == DYN_EXPR_NIL) {
    if (!dyn_type_is_pointer(expected) && expected != DYN_TYPE_RAWPTR) {
      error_span(a->expressions[id].span, s, errors, "nil requires expected pointer type");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    return a->expressions[id].type = expected;
  }
  if (a->expressions[id].kind == DYN_EXPR_STRUCT) {
    uint32_t sid = a->expressions[id].boolean && dyn_type_is_struct(expected)
                       ? expected - DYN_TYPE_STRUCT_BASE
                       : sema_find_struct(a, a->expressions[id].span, s);
    if (sid == UINT32_MAX || sid >= a->struct_count) {
      error_span(a->expressions[id].span, s, errors,
                 a->expressions[id].boolean
                     ? "inferred struct literal requires expected struct type"
                     : "unknown struct type");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    a->expressions[id].integer = sid;
    a->expressions[id].type = DYN_TYPE_STRUCT_BASE + sid;
    DynAstStruct *st = &a->structs[sid];
    for (uint32_t i = 0; i < a->expressions[id].item_count; ++i) {
      uint32_t item_index = a->expressions[id].item_start + i;
      uint32_t field = sema_find_field(a, sid, a->items[item_index].name, s);
      if (field == UINT32_MAX) {
        error_span(a->items[item_index].name, s, errors, "unknown struct field");
        continue;
      }
      a->items[item_index].field_index = field;
      for (uint32_t j = 0; j < i; ++j)
        if (dyn_span_text_equal(a->items[item_index].name, a->items[a->expressions[id].item_start + j].name,
                                s))
          error_span(a->items[item_index].name, s, errors, "duplicate struct literal field");
      DynType target = a->fields[st->field_start + field].type;
      DynType value = check_expr(sema, a, a->items[item_index].expression, s, errors, target);
      if (value != target && value != DYN_TYPE_ERROR &&
          target != DYN_TYPE_ERROR) {
        if (can_convert(sema, a, value, target))
          a->items[item_index].expression = convert_expr(a, a->items[item_index].expression, target);
        else
          error_span(a->items[item_index].name, s, errors,
                     "struct field initializer type mismatch");
      }
    }
    return a->expressions[id].type;
  }
  if (a->expressions[id].kind == DYN_EXPR_FIELD) {
    DynType base = check_expr(sema, a, a->expressions[id].left, s, errors, DYN_TYPE_INFER);
    if (dyn_type_is_pointer(base)) {
      DynAstPointer *p = pointer_info(a, base);
      base = p ? p->pointee : DYN_TYPE_ERROR;
      a->expressions[id].boolean = true;
    }
    if (!dyn_type_is_struct(base)) {
      if (base != DYN_TYPE_ERROR)
        error_span(a->expressions[id].span, s, errors,
                   "field access requires struct or struct pointer");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    uint32_t sid = base - DYN_TYPE_STRUCT_BASE,
             field = sema_find_field(a, sid, a->expressions[id].span, s);
    if (field == UINT32_MAX) {
      error_span(a->expressions[id].span, s, errors, "unknown struct field");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    a->expressions[id].integer = field;
    return a->expressions[id].type = a->fields[a->structs[sid].field_start + field].type;
  }
  if (a->expressions[id].kind == DYN_EXPR_INT) {
    if (expected != DYN_TYPE_INFER && !dyn_type_is_distinct(expected) &&
        integer(sema, expected)) {
      if (!literal_fits(sema, a->expressions[id].integer, expected)) {
        error_span(a->expressions[id].span, s, errors,
                   "integer literal is not representable in expected type");
        return a->expressions[id].type = DYN_TYPE_ERROR;
      }
      return a->expressions[id].type = expected;
    }
    if (a->expressions[id].integer > INT32_MAX) {
      error_span(a->expressions[id].span, s, errors,
                 "integer literal does not fit default i32");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    return a->expressions[id].type = DYN_TYPE_I32;
  }
  if (a->expressions[id].kind == DYN_EXPR_FLOAT) {
    return a->expressions[id].type = expected == DYN_TYPE_F64 ? DYN_TYPE_F64 : DYN_TYPE_F32;
  }
  if (a->expressions[id].kind == DYN_EXPR_CHAR) {
    DynType t = expected == DYN_TYPE_U8 || expected == DYN_TYPE_U16 ||
                        expected == DYN_TYPE_U32
                    ? expected
                    : (a->expressions[id].integer <= 255 ? DYN_TYPE_U8 : DYN_TYPE_U32);
    if (!literal_fits(sema, a->expressions[id].integer, t)) {
      error_span(a->expressions[id].span, s, errors,
                 "character literal is not representable in expected type");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    return a->expressions[id].type = t;
  }
  if (a->expressions[id].kind == DYN_EXPR_STRING) {
    if (expected == DYN_TYPE_INFER)
      return a->expressions[id].type = sema_intern_slice(a, DYN_TYPE_U8, true);
    DynAstSlice *target = slice_info(a, expected);
    if (!target || target->element != DYN_TYPE_U8 || !target->is_const) {
      error_span(a->expressions[id].span, s, errors,
                 "string literal requires expected []const u8 type");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    return a->expressions[id].type = expected;
  }
  if (a->expressions[id].kind == DYN_EXPR_BOOL)
    return a->expressions[id].type;
  if (a->expressions[id].kind == DYN_EXPR_UNARY && a->expressions[id].op == DYN_OP_NEG &&
      !dyn_type_is_distinct(expected) && signed_int(sema, expected) &&
      a->expressions[a->expressions[id].left].kind == DYN_EXPR_INT) {
    DynAstExpr *operand = &a->expressions[a->expressions[id].left];
    unsigned width = bits(sema, expected);
    uint64_t limit =
        width == 64 ? (UINT64_C(1) << 63) : (UINT64_C(1) << (width - 1));
    if (operand->integer > limit) {
      error_span(a->expressions[id].span, s, errors,
                 "negative literal is not representable in expected type");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    operand->type = expected;
    a->expressions[id].boolean = true;
    return a->expressions[id].type = expected;
  }
  if (a->expressions[id].kind == DYN_EXPR_UNARY && a->expressions[id].op == DYN_OP_ADDRESS) {
    DynAstExpr *operand = &a->expressions[a->expressions[id].left];
    if (operand->kind == DYN_EXPR_NAME) {
      uint32_t fn = sema_find_function(sema, a, operand->span, s);
      if (fn != UINT32_MAX) {
        if (a->functions[fn].variadic && !a->functions[fn].foreign) {
          error_span(a->expressions[id].span, s, errors,
                     "native variadic function pointers are not supported");
          return a->expressions[id].type = DYN_TYPE_ERROR;
        }
        if (!sema_c_abi_function(a, &a->functions[fn])) {
          error_span(a->expressions[id].span, s, errors,
                     "type has no supported C ABI; use C-compatible storage or a pointer adapter");
          return a->expressions[id].type = DYN_TYPE_ERROR;
        }
        a->expressions[id].kind = DYN_EXPR_FUNCTION;
        a->expressions[id].op = DYN_OP_NONE;
        a->expressions[id].integer = fn;
        a->expressions[id].left = DYN_NO_EXPR;
        return a->expressions[id].type = function_pointer_type(a, fn);
      }
    }
    DynType value = check_expr(sema, a, a->expressions[id].left, s, errors, DYN_TYPE_INFER);
    DynExprKind kind = a->expressions[a->expressions[id].left].kind;
    if (kind != DYN_EXPR_NAME && kind != DYN_EXPR_GLOBAL &&
        kind != DYN_EXPR_FIELD && kind != DYN_EXPR_INDEX &&
        !(kind == DYN_EXPR_UNARY &&
          a->expressions[a->expressions[id].left].op == DYN_OP_DEREF)) {
      error_span(a->expressions[id].span, s, errors,
                 "address operand must be assignable storage or function");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    return a->expressions[id].type = sema_intern_pointer(a, value, lvalue_const(a, a->expressions[id].left));
  }
  DynType left =
      a->expressions[a->expressions[id].left].kind == DYN_EXPR_NIL && a->expressions[id].kind == DYN_EXPR_BINARY
          ? check_expr(sema, a, a->expressions[id].left, s, errors,
                       check_expr(sema, a, a->expressions[id].right, s, errors, DYN_TYPE_INFER))
          : check_expr(sema, a, a->expressions[id].left, s, errors, expected);
  if (a->expressions[id].kind == DYN_EXPR_UNARY) {
    if (a->expressions[id].op == DYN_OP_DEREF) {
      DynAstPointer *p = pointer_info(a, left);
      if (!p) {
        error_span(a->expressions[id].span, s, errors, "dereference requires pointer");
        return a->expressions[id].type = DYN_TYPE_ERROR;
      }
      if (p->pointee == DYN_TYPE_VOID) {
        error_span(a->expressions[id].span, s, errors,
                   "raw *void pointer cannot be dereferenced");
        return a->expressions[id].type = DYN_TYPE_ERROR;
      }
      return a->expressions[id].type = p->pointee;
    }
    if (a->expressions[id].op == DYN_OP_NOT && left != DYN_TYPE_BOOL)
      error_span(a->expressions[id].span, s, errors, "! requires bool");
    else if (a->expressions[id].op == DYN_OP_BIT_NOT && !integer(sema, left))
      error_span(a->expressions[id].span, s, errors, "~ requires integer");
    else if (a->expressions[id].op == DYN_OP_NEG && !numeric(sema, left))
      error_span(a->expressions[id].span, s, errors, "unary - requires numeric type");
    return a->expressions[id].type = left;
  }
  if (a->expressions[id].op == DYN_OP_SHL || a->expressions[id].op == DYN_OP_SHR) {
    DynType right = check_expr(sema, a, a->expressions[id].right, s, errors, DYN_TYPE_USIZE);
    if (!integer(sema, left) || !integer(sema, right) ||
        signed_int(sema, right)) {
      error_span(a->expressions[id].span, s, errors, "shift count requires unsigned integer");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    ConstantUInt rhs = constant_uint(a, a->expressions[id].right);
    if (rhs.valid && rhs.value >= bits(sema, left)) {
      error_span(a->expressions[id].span, s, errors, "invalid constant shift count");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    return a->expressions[id].type = left;
  }
  DynType right = check_expr(sema, a, a->expressions[id].right, s, errors, left);
  if (left == DYN_TYPE_ERROR || right == DYN_TYPE_ERROR)
    return a->expressions[id].type = DYN_TYPE_ERROR;
  if (left != right && dyn_type_is_pointer(left) &&
      dyn_type_is_pointer(right) &&
      (a->expressions[id].op == DYN_OP_EQ || a->expressions[id].op == DYN_OP_NE)) {
    if (can_convert(sema, a, left, right)) {
      DynExprId converted = convert_expr(a, a->expressions[id].left, right);
      a->expressions[id].left = converted;
      left = right;
    } else if (can_convert(sema, a, right, left)) {
      DynExprId converted = convert_expr(a, a->expressions[id].right, left);
      a->expressions[id].right = converted;
      right = left;
    }
  }
  if (left != right) {
    char lhs[128], rhs[128], message[384];
    type_name_into(a, left, s, lhs, sizeof(lhs));
    type_name_into(a, right, s, rhs, sizeof(rhs));
    snprintf(message, sizeof(message),
             "operator has mismatched types %s and %s; cast one operand", lhs,
             rhs);
    error_span(a->expressions[id].span, s, errors, message);
    return a->expressions[id].type = DYN_TYPE_ERROR;
  }
  if (a->expressions[id].op == DYN_OP_LOGICAL_AND || a->expressions[id].op == DYN_OP_LOGICAL_OR) {
    if (left != DYN_TYPE_BOOL)
      error_span(a->expressions[id].span, s, errors, "logical operators require bool");
    return a->expressions[id].type = DYN_TYPE_BOOL;
  }
  if (a->expressions[id].op >= DYN_OP_EQ && a->expressions[id].op <= DYN_OP_GE) {
    if (left == DYN_TYPE_STRING || dyn_type_is_struct(left) ||
        dyn_type_is_array(left) || dyn_type_is_slice(left) ||
        (dyn_type_is_enum(left) &&
         a->enums[left - DYN_TYPE_ENUM_BASE].has_payload)) {
      error_span(a->expressions[id].span, s, errors, "aggregate values are not comparable");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    if ((dyn_type_is_pointer(left) || dyn_type_is_enum(left)) &&
        a->expressions[id].op != DYN_OP_EQ && a->expressions[id].op != DYN_OP_NE) {
      error_span(a->expressions[id].span, s, errors,
                 dyn_type_is_enum(left) ? "enums support equality only"
                                        : "pointers support equality only");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    return a->expressions[id].type = DYN_TYPE_BOOL;
  }
  if (a->expressions[id].op == DYN_OP_BIT_AND || a->expressions[id].op == DYN_OP_BIT_OR ||
      a->expressions[id].op == DYN_OP_BIT_XOR) {
    if (!integer(sema, left) && left != DYN_TYPE_BOOL)
      error_span(a->expressions[id].span, s, errors,
                 "bitwise operators require integer or bool");
    return a->expressions[id].type = left;
  }
  if (!numeric(sema, left))
    error_span(a->expressions[id].span, s, errors, "arithmetic requires numeric operands");
  if (integer(sema, left)) {
    ConstantUInt rhs = constant_uint(a, a->expressions[id].right);
    if ((a->expressions[id].op == DYN_OP_DIV || a->expressions[id].op == DYN_OP_REM) && rhs.valid &&
        rhs.value == 0) {
      error_span(a->expressions[id].span, s, errors, "invalid constant division by zero");
      return a->expressions[id].type = DYN_TYPE_ERROR;
    }
    if (signed_int(sema, left)) {
      ConstantInt all = constant_int(a, id);
      if (all.overflow ||
          (all.valid && !constant_fits_type(sema, all.value, left))) {
        error_span(a->expressions[id].span, s, errors,
                   "constant arithmetic overflows result type");
        return a->expressions[id].type = DYN_TYPE_ERROR;
      }
    } else {
      ConstantUInt all = constant_uint(a, id);
      unsigned width = bits(sema, left);
      if (all.overflow || (all.valid && width < 64 &&
                           all.value > ((UINT64_C(1) << width) - 1))) {
        error_span(a->expressions[id].span, s, errors,
                   "constant arithmetic overflows result type");
        return a->expressions[id].type = DYN_TYPE_ERROR;
      }
    }
  }
  return a->expressions[id].type = left;
}
static bool lvalue_const(DynAstProgram *a, DynExprId id) {
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
static bool sema_block(Sema *sema, DynAstProgram *, uint32_t, uint32_t,
                       const DynSource *, unsigned *, bool);
static bool mutable_case_subject(DynAstProgram *a, DynExprId id) {
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
static void validate_pointer_case_bindings(DynAstProgram *a, DynAstStmt *st,
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
static bool valid_defer_stmt(DynAstProgram *a, uint32_t id, const DynSource *s,
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
typedef struct { DynExprId id; bool leave_global; } ConstantFrame;
/* Iterate dependency graphs: expression depth is unrelated to global count,
   and constant cycles must not consume the C stack. Common literals need no
   heap scratch. Each referenced global is visited once within this query. */
static bool compile_time_expr(DynAstProgram *a, DynExprId id, const DynSource *s) {
  ConstantFrame local[64], *stack = local;
  size_t count = 1, capacity = 64;
  unsigned char *globals = NULL;
  bool ok = false;
  local[0] = (ConstantFrame){id, false};
  while (count) {
    if (!dyn_work_step(&s->context, 1)) goto done;
    ConstantFrame frame = stack[--count];
    if (frame.leave_global) { globals[frame.id] = 2; continue; }
    if (frame.id == DYN_NO_EXPR || frame.id >= a->expression_count) goto done;
    DynAstExpr *e = &a->expressions[frame.id];
    size_t required = count + (size_t)e->item_count + 3;
    if (required > capacity) {
      size_t next_capacity = capacity * 2;
      if (next_capacity < required) next_capacity = required;
      if (next_capacity > SIZE_MAX / sizeof(*stack)) goto allocation_failed;
      ConstantFrame *next = malloc(next_capacity * sizeof(*next));
      if (!next) goto allocation_failed;
      memcpy(next, stack, count * sizeof(*next));
      if (stack != local) free(stack);
      stack = next; capacity = next_capacity;
    }
    if (e->kind == DYN_EXPR_FUNCTION || e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_FLOAT ||
        e->kind == DYN_EXPR_BOOL || e->kind == DYN_EXPR_CHAR || e->kind == DYN_EXPR_STRING || e->kind == DYN_EXPR_NIL) continue;
    if (e->kind == DYN_EXPR_GLOBAL) {
      uint32_t g = (uint32_t)e->integer;
      if (g >= a->global_count || !a->globals[g].is_const) goto done;
      if (!globals) {
        globals = calloc(a->global_count, 1);
        if (!globals) goto allocation_failed;
      }
      if (globals[g] == 1) goto done;
      if (globals[g] == 2) continue;
      globals[g] = 1;
      stack[count++] = (ConstantFrame){g, true};
      stack[count++] = (ConstantFrame){a->globals[g].initializer, false};
      continue;
    }
    if (e->kind == DYN_EXPR_CONVERT || (e->kind == DYN_EXPR_UNARY && e->op != DYN_OP_ADDRESS && e->op != DYN_OP_DEREF)) {
      stack[count++] = (ConstantFrame){e->left, false}; continue;
    }
    if (e->kind == DYN_EXPR_CAST) {
      DynType target = underlying_type(a, e->type);
      DynType source = underlying_type(a, a->expressions[e->left].type);
      if (target < DYN_TYPE_I8 || target > DYN_TYPE_F64 || source < DYN_TYPE_I8 || source > DYN_TYPE_F64) goto done;
      stack[count++] = (ConstantFrame){e->left, false}; continue;
    }
    if (e->kind == DYN_EXPR_BINARY) {
      stack[count++] = (ConstantFrame){e->right, false};
      stack[count++] = (ConstantFrame){e->left, false}; continue;
    }
    if (e->kind == DYN_EXPR_STRUCT || e->kind == DYN_EXPR_ARRAY) {
      for (uint32_t i = 0; i < e->item_count; ++i)
        stack[count++] = (ConstantFrame){a->items[e->item_start + i].expression, false};
      continue;
    }
    goto done;
  }
  ok = true;
  goto done;
allocation_failed:
  a->allocation_failed = true;
done:
  if (stack != local) free(stack);
  free(globals);
  return ok;
}
static bool interval_overlap(const DynAstPattern *a, const DynAstPattern *b) {
  if (a->is_signed) {
    int64_t af = (int64_t)a->first_value, al = (int64_t)a->last_value,
            bf = (int64_t)b->first_value, bl = (int64_t)b->last_value;
    return af <= bl && bf <= al;
  }
  return a->first_value <= b->last_value && b->first_value <= a->last_value;
}
static bool integer_case_complete(Sema *sema, DynAstProgram *a, DynAstStmt *st,
                                  DynType type) {
  bool sign = signed_int(sema, type);
  unsigned width = bits(sema, type);
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
static bool sema_case_v2(Sema *sema, DynAstProgram *a, DynAstStmt *st,
                         const DynSource *s, unsigned *errors) {
  DynType subject =
      check_expr(sema, a, st->expression, s, errors, DYN_TYPE_INFER);
  bool enum_case = dyn_type_is_enum(subject),
       integer_case = integer(sema, subject);
  if (subject == DYN_TYPE_ANY) {
    bool wildcard = false, all_terminate = true;
    for (uint32_t i = 0; i < st->case_arm_count; ++i) {
      DynAstCaseArm *arm = &a->case_arms[st->case_arm_start + i];
      if (arm->wildcard) {
        if (wildcard)
          error_span(arm->span, s, errors, "duplicate _ case arm");
        wildcard = true;
      } else if (arm->pattern_count != 1 ||
                 !a->patterns[arm->pattern_start].is_type)
        error_span(arm->span, s, errors,
                   "any case arm requires an is type pattern");
      else {
        DynAstPattern *p = &a->patterns[arm->pattern_start];
        for (uint32_t q = 0; q < i; ++q) {
          DynAstCaseArm *old = &a->case_arms[st->case_arm_start + q];
          if (!old->wildcard && old->pattern_count &&
              a->patterns[old->pattern_start].is_type &&
              a->patterns[old->pattern_start].type == p->type)
            error_span(p->span, s, errors, "duplicate any type pattern");
        }
        if (arm->binding.end_byte > arm->binding.start_byte &&
            reserve_local(a)) {
          arm->local_id = (uint32_t)a->local_count;
          a->locals[a->local_count++] =
              (DynAstLocal){.name = arm->binding,
                            .type = p->type,
                            .active = true,
                            .owner_function = sema->current_function};
        }
      }
      all_terminate = sema_block(sema, a, arm->body_start, arm->body_count, s,
                                 errors, true) &&
                      all_terminate;
      if (arm->local_id != UINT32_MAX)
        a->locals[arm->local_id].active = false;
    }
    if (!wildcard)
      error_span(st->span, s, errors, "any case requires _ arm");
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
        DynType t = check_expr(sema, a, p->first, s, errors, subject);
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
        p->is_signed = signed_int(sema, subject);
        DynType t = check_expr(sema, a, p->first, s, errors, subject);
        bool valid = t == subject;
        if (p->is_signed) {
          ConstantInt lo = constant_int(a, p->first);
          valid = valid && lo.valid;
          p->first_value = (uint64_t)lo.value;
          p->last_value = p->first_value;
          if (p->range) {
            DynType ht = check_expr(sema, a, p->last, s, errors, subject);
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
            DynType ht = check_expr(sema, a, p->last, s, errors, subject);
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
        else if (find_any_local(sema, a, arm->binding, s) != UINT32_MAX)
          error_span(arm->binding, s, errors,
                     "shadowing or duplicate local is forbidden");
        else if (reserve_local(a)) {
          arm->local_id = (uint32_t)a->local_count;
          a->locals[a->local_count++] =
              (DynAstLocal){.name = arm->binding,
                            .type = v->payload_type,
                            .active = true,
                            .owner_function = sema->current_function};
        }
      }
    }
    all_terminate = sema_block(sema, a, arm->body_start, arm->body_count, s,
                               errors, true) &&
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
    complete = integer_case_complete(sema, a, st, subject);
  if (wildcard && complete)
    error_span(st->span, s, errors,
               "_ case arm is unreachable because all cases are covered");
  else if (!wildcard && !complete)
    error_span(st->span, s, errors, "case is not exhaustive");
  return all_terminate;
}
/* Diagnose syntactically proven escapes only. Borrowed pointer/slice parameters
 * are safe here; their referents are not the parameter's own stack slot. */
static bool function_storage(Sema *sema, DynAstProgram *a, DynExprId id) {
  if (id == DYN_NO_EXPR || id >= a->expression_count)
    return false;
  DynAstExpr *e = &a->expressions[id];
  if (e->type == DYN_TYPE_ERROR)
    return false;
  if (e->kind == DYN_EXPR_NAME)
    return e->integer < a->local_count &&
           a->locals[e->integer].owner_function == sema->current_function;
  /* Literal storage may be promoted to a static constant by codegen. */
  if (e->kind == DYN_EXPR_FIELD)
    return !dyn_type_is_pointer(
               underlying_type(a, a->expressions[e->left].type)) &&
           function_storage(sema, a, e->left);
  if (e->kind == DYN_EXPR_INDEX)
    return dyn_type_is_array(
               underlying_type(a, a->expressions[e->left].type)) &&
           function_storage(sema, a, e->left);
  return false;
}

static bool returns_local_borrow(Sema *sema, DynAstProgram *a, DynExprId id) {
  if (id == DYN_NO_EXPR || id >= a->expression_count)
    return false;
  DynAstExpr *e = &a->expressions[id];
  if (e->type == DYN_TYPE_ERROR)
    return false;
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_ADDRESS)
    return function_storage(sema, a, e->left);
  if (e->kind == DYN_EXPR_SLICE) {
    DynType base = underlying_type(a, a->expressions[e->left].type);
    return (dyn_type_is_array(base) && function_storage(sema, a, e->left)) ||
           returns_local_borrow(sema, a, e->left);
  }
  if (e->kind == DYN_EXPR_CONVERT || e->kind == DYN_EXPR_CAST ||
      e->kind == DYN_EXPR_BITCAST) {
    DynType type = underlying_type(a, e->type);
    if (dyn_type_is_pointer(type) || dyn_type_is_slice(type) ||
        type == DYN_TYPE_RAWPTR)
      return returns_local_borrow(sema, a, e->left);
  }
  if (e->kind == DYN_EXPR_STRUCT || e->kind == DYN_EXPR_ARRAY)
    for (uint32_t i = 0; i < e->item_count; ++i)
      if (returns_local_borrow(sema, a, a->items[e->item_start + i].expression))
        return true;
  return false;
}


#include "lifetime.h"

static bool sema_stmt(Sema *sema, DynAstProgram *a, DynAstStmt *st,
                      const DynSource *s, unsigned *errors) {
  if (st->kind == DYN_STMT_INVALID)
    return false;
  if (st->kind == DYN_STMT_DEFER) {
    bool valid = true;
    for (uint32_t i = 0; i < st->body_count; ++i)
      valid = valid_defer_stmt(a, a->children[st->body_start + i], s, errors) &&
              valid;
    if (valid)
      (void)sema_block(sema, a, st->body_start, st->body_count, s, errors,
                       true);
    return false;
  }
  if (st->kind == DYN_STMT_PANIC) {
    DynType message_type = sema_intern_slice(a, DYN_TYPE_U8, true);
    DynType value =
        check_expr(sema, a, st->expression, s, errors, message_type);
    if (value != message_type && value != DYN_TYPE_ERROR) {
      if (can_convert(sema, a, value, message_type))
        st->expression = convert_expr(a, st->expression, message_type);
      else
        error_span(st->span, s, errors, "#panic message requires []const u8");
    }
    return true;
  }
  if (st->kind == DYN_STMT_CASE) {
    validate_pointer_case_bindings(a, st, s, errors);
    return sema_case_v2(sema, a, st, s, errors);
  }
  if (st->kind == DYN_STMT_RETURN) {
    if (sema->current_return_type == DYN_TYPE_VOID) {
      if (st->expression != DYN_NO_EXPR)
        error_span(st->span, s, errors, "void function cannot return a value");
    } else if (st->expression == DYN_NO_EXPR)
      error_span(st->span, s, errors, "non-void function must return a value");
    else {
      DynType value = check_expr(sema, a, st->expression, s, errors,
                                 sema->current_return_type);
      if (returns_local_borrow(sema, a, st->expression))
        error_span(st->span, s, errors,
                   "returned value borrows function-local storage");
      if (value != sema->current_return_type && value != DYN_TYPE_ERROR) {
        if (can_convert(sema, a, value, sema->current_return_type))
          st->expression =
              convert_expr(a, st->expression, sema->current_return_type);
        else
          error_types(st->span, s, errors, "return type mismatch",
                      sema->current_return_type, value);
      }
    }
    return true;
  }
  if (st->kind == DYN_STMT_EXPR) {
    DynExprKind original = a->expressions[st->expression].kind;
    DynType value =
        check_expr(sema, a, st->expression, s, errors, DYN_TYPE_INFER);
    if (original != DYN_EXPR_SYSCALL && value != DYN_TYPE_VOID &&
        value != DYN_TYPE_ERROR)
      error_span(st->span, s, errors,
                 "discard non-void call result with '_ = call()'");
    return false;
  }
  if (st->kind == DYN_STMT_BREAK || st->kind == DYN_STMT_CONTINUE) {
    (void)resolve_loop_control(sema, st, s, errors);
    return true;
  }
  if (st->kind == DYN_STMT_CASE) {
    DynType subject =
        check_expr(sema, a, st->expression, s, errors, DYN_TYPE_INFER);
    bool enum_case = dyn_type_is_enum(subject),
         integer_case = integer(sema, subject);
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
          DynType t = check_expr(sema, a, p->first, s, errors, subject);
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
          DynType t = check_expr(sema, a, p->first, s, errors, subject);
          ConstantInt lo = constant_int(a, p->first);
          if (t != subject || !lo.valid) {
            error_span(p->span, s, errors,
                       "case pattern must be a compile-time integer constant");
            continue;
          }
          p->first_value = lo.value;
          p->last_value = lo.value;
          if (p->range) {
            t = check_expr(sema, a, p->last, s, errors, subject);
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
          else if (find_any_local(sema, a, arm->binding, s) != UINT32_MAX)
            error_span(arm->binding, s, errors,
                       "shadowing or duplicate local is forbidden");
          else if (reserve_local(a)) {
            arm->local_id = (uint32_t)a->local_count;
            a->locals[a->local_count++] =
                (DynAstLocal){.name = arm->binding,
                              .type = v->payload_type,
                              .active = true,
                              .owner_function = sema->current_function};
          }
        }
      }
      bool term = sema_block(sema, a, arm->body_start, arm->body_count, s,
                             errors, true);
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
      DynType collection =
          check_expr(sema, a, st->target, s, errors, DYN_TYPE_INFER);
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
      if (find_any_local(sema, a, st->name, s) != UINT32_MAX) {
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
      a->locals[a->local_count++] =
          (DynAstLocal){.name = st->name,
                        .type = binding,
                        .active = true,
                        .owner_function = sema->current_function};
      bool pushed = push_loop(sema, st, s, errors);
      (void)sema_block(sema, a, st->body_start, st->body_count, s, errors,
                       true);
      if (pushed)
        pop_loop(sema);
      a->locals[st->local_id].active = false;
      return false;
    }
    DynType condition =
        st->expression == DYN_NO_EXPR
            ? DYN_TYPE_BOOL
            : check_expr(sema, a, st->expression, s, errors, DYN_TYPE_BOOL);
    if (condition != DYN_TYPE_BOOL && condition != DYN_TYPE_ERROR)
      error_span(st->span, s, errors, "control-flow condition requires bool");
    bool pushed = st->kind == DYN_STMT_FOR && push_loop(sema, st, s, errors);
    bool body =
        sema_block(sema, a, st->body_start, st->body_count, s, errors, true);
    if (pushed)
      pop_loop(sema);
    if (st->kind == DYN_STMT_FOR)
      return false;
    bool other = st->else_count && sema_block(sema, a, st->else_start,
                                              st->else_count, s, errors, true);
    return st->else_count && body && other;
  }
  if (st->kind == DYN_STMT_LOCAL) {
    if (find_any_local(sema, a, st->name, s) != UINT32_MAX ||
        sema_find_global_name(sema, a, st->name, s) != UINT32_MAX) {
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
      DynType value = check_expr(sema, a, st->expression, s, errors, type);
      if (type == DYN_TYPE_INFER)
        type = value;
      else if (value != type && value != DYN_TYPE_ERROR) {
        if (can_convert(sema, a, value, type))
          st->expression = convert_expr(a, st->expression, type);
        else
          error_types(st->span, s, errors, "initializer type mismatch", type,
                      value);
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
    a->locals[a->local_count++] =
        (DynAstLocal){.name = st->name,
                      .type = type,
                      .active = true,
                      .is_const = st->is_const,
                      .owner_function = sema->current_function};
    return false;
  }
  if (st->target != DYN_NO_EXPR) {
    DynType target = check_expr(sema, a, st->target, s, errors, DYN_TYPE_INFER),
            value = check_expr(sema, a, st->expression, s, errors, target);
    if (lvalue_const(a, st->target))
      error_span(st->span, s, errors, "assignment through *const pointer");
    if (value != target && value != DYN_TYPE_ERROR &&
        target != DYN_TYPE_ERROR) {
      if (can_convert(sema, a, value, target) &&
          st->assignment_op == DYN_OP_NONE)
        st->expression = convert_expr(a, st->expression, target);
      else
        error_types(st->span, s, errors, "field assignment type mismatch",
                    target, value);
    }
    if (st->assignment_op != DYN_OP_NONE) {
      bool valid = numeric(sema, target) && (st->assignment_op >= DYN_OP_ADD &&
                                             st->assignment_op <= DYN_OP_REM);
      valid = valid ||
              (integer(sema, target) && (st->assignment_op == DYN_OP_BIT_AND ||
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
    (void)check_expr(sema, a, st->expression, s, errors, DYN_TYPE_INFER);
    return false;
  }
  uint32_t local = find_local(sema, a, st->name, s),
           global = sema_find_global_name(sema, a, st->name, s);
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
  DynType value = check_expr(sema, a, st->expression, s, errors,
                             shift ? DYN_TYPE_USIZE : target);
  if (shift) {
    if (!integer(sema, value) || signed_int(sema, value))
      error_span(st->span, s, errors, "shift count requires unsigned integer");
  } else if (value != target && value != DYN_TYPE_ERROR &&
             target != DYN_TYPE_ERROR) {
    if (can_convert(sema, a, value, target) && st->assignment_op == DYN_OP_NONE)
      st->expression = convert_expr(a, st->expression, target);
    else
      error_types(st->span, s, errors, "assignment type mismatch", target,
                  value);
  }
  if (st->assignment_op != DYN_OP_NONE) {
    bool valid = numeric(sema, target) && (st->assignment_op >= DYN_OP_ADD &&
                                           st->assignment_op <= DYN_OP_REM);
    valid = valid || (integer(sema, target) &&
                      (st->assignment_op == DYN_OP_BIT_AND ||
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
static bool sema_block(Sema *sema, DynAstProgram *a, uint32_t start,
                       uint32_t count, const DynSource *s, unsigned *errors,
                       bool scoped) {
  size_t base = a->local_count;
  bool terminated = false;
  for (uint32_t i = 0; i < count; ++i) {
    DynAstStmt *st = &a->statements[a->children[start + i]];
    if (terminated) {
      error_span(st->span, s, errors, "unreachable statement");
      continue;
    }
    terminated = sema_stmt(sema, a, st, s, errors);
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
static bool sema_program(Sema *sema, DynAstProgram *a, const DynSource *s,
                         unsigned *errors) {
  /* Reserve common conversion growth up front as an optimization. Reflection
     may exceed this estimate; recursive checking must remain relocation-safe. */
  size_t semantic_capacity = a->expression_count * 2 + 32;
  if (semantic_capacity > a->expression_capacity) {
    void *expressions =
        realloc(a->expressions, semantic_capacity * sizeof(*a->expressions));
    if (!expressions) {
      ++*errors;
      return false;
    }
    a->expressions = expressions;
    a->expression_capacity = semantic_capacity;
  }
  for (uint32_t i = 0; i < a->field_count; ++i)
    if (a->fields[i].default_expression != DYN_NO_EXPR) {
      DynType value = check_expr(sema, a, a->fields[i].default_expression, s,
                                 errors, a->fields[i].type);
      if (value != a->fields[i].type && value != DYN_TYPE_ERROR) {
        if (can_convert(sema, a, value, a->fields[i].type))
          a->fields[i].default_expression = convert_expr(
              a, a->fields[i].default_expression, a->fields[i].type);
        else
          error_span(a->fields[i].name, s, errors,
                     "struct field default type mismatch");
      }
    }
  sema->current_function = UINT32_MAX;
  for (uint32_t i = 0; i < a->global_count; ++i) {
    DynAstGlobal *g = &a->globals[i];
    if (g->foreign) {
      if (!foreign_symbol_valid(g->link_name, s))
        error_span(g->link_name, s, errors,
                   "foreign link name must be a non-empty linker symbol");
      if (g->type == DYN_TYPE_INFER || g->type == DYN_TYPE_ERROR ||
          g->type == DYN_TYPE_VOID || g->type == DYN_TYPE_ANY)
        error_span(g->name, s, errors,
                   "foreign global requires a concrete non-void type");
      continue;
    }
    if (g->type == DYN_TYPE_ANY)
      error_span(g->name, s, errors,
                 "global any would escape borrowed storage");
    if (g->initializer == DYN_NO_EXPR) {
      if (g->is_const)
        error_span(g->name, s, errors, "constant requires initializer");
      if (g->type == DYN_TYPE_INFER)
        error_span(g->name, s, errors, "inferred global requires initializer");
      continue;
    }
    DynType value = check_expr(sema, a, g->initializer, s, errors, g->type);
    if (g->type == DYN_TYPE_INFER)
      g->type = value;
    else if (value != g->type && value != DYN_TYPE_ERROR) {
      if (can_convert(sema, a, value, g->type))
        g->initializer = convert_expr(a, g->initializer, g->type);
      else
        error_span(g->name, s, errors, "global initializer type mismatch");
    }
  }
  /* Resolve all global expressions before following constant dependencies;
     forward references otherwise still contain unresolved name expressions. */
  for (uint32_t i = 0; i < a->global_count && dyn_work_step(&s->context, 1); ++i) {
    DynAstGlobal *g = &a->globals[i];
    if (g->is_const && g->initializer != DYN_NO_EXPR &&
        !compile_time_expr(a, g->initializer, s))
      error_span(g->name, s, errors,
                 "constant initializer must be compile-time expression");
  }
  for (uint32_t i = 0; i < a->field_count && dyn_work_step(&s->context, 1); ++i)
    if (a->fields[i].default_expression != DYN_NO_EXPR &&
        !compile_time_expr(a, a->fields[i].default_expression, s))
      error_span(a->fields[i].name, s, errors,
                 "struct field default must be compile-time expression");
  for (uint32_t f = 0; f < a->function_count && dyn_work_step(&s->context, 1); ++f) {
    DynAstFn *fn = &a->functions[f];
    if (fn->return_type == DYN_TYPE_ANY)
      error_span(fn->name, s, errors,
                 "returning any would escape borrowed storage");
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
    /* A cached/imported interface deliberately has no implementation body.
       Its signature was checked while loading declarations; its owner checks
       the body in a separate frontend job. */
    if (fn->interface_only) {
      for (uint32_t i = 0; i < fn->param_count; ++i) {
        DynAstParam *p = &a->params[fn->param_start + i];
        for (uint32_t j = 0; j < i; ++j)
          if (dyn_span_text_equal(p->name, a->params[fn->param_start + j].name,
                                  s))
            error_span(p->name, s, errors, "duplicate parameter name");
      }
      continue;
    }
    sema->current_function = f;
    sema->current_return_type = fn->return_type;
    fn->local_start = (uint32_t)a->local_count;
    for (uint32_t i = 0; i < fn->param_count; ++i) {
      DynAstParam *p = &a->params[fn->param_start + i];
      if (find_any_local(sema, a, p->name, s) != UINT32_MAX ||
          sema_find_global_name(sema, a, p->name, s) != UINT32_MAX) {
        error_span(p->name, s, errors, "duplicate parameter name");
        continue;
      }
      if (!reserve_local(a)) {
        error_span(p->name, s, errors, "out of memory");
        continue;
      }
      p->local_id = (uint32_t)a->local_count;
      a->locals[a->local_count++] = (DynAstLocal){.name = p->name,
                                                  .type = p->type,
                                                  .active = true,
                                                  .owner_function = f};
    }
    if (fn->variadic &&
        fn->variadic_name.end_byte > fn->variadic_name.start_byte) {
      if (!reserve_local(a))
        error_span(fn->variadic_name, s, errors, "out of memory");
      else {
        fn->variadic_local_id = (uint32_t)a->local_count;
        a->locals[a->local_count++] = (DynAstLocal){.name = fn->variadic_name,
                                                    .type = fn->variadic_type,
                                                    .active = true,
                                                    .owner_function = f};
      }
    }
    bool terminated =
        sema_block(sema, a, fn->body_start, fn->body_count, s, errors, false);
    fn->local_count = (uint32_t)a->local_count - fn->local_start;
    life_check_function(sema,a,s,errors,fn);
    if (fn->return_type != DYN_TYPE_VOID && !terminated)
      error_span(fn->name, s, errors,
                 "non-void function may exit without return");
    for (uint32_t i = fn->local_start; i < a->local_count; ++i)
      a->locals[i].active = false;
    free(sema->locals.buckets); free(sema->locals.next);
    sema->locals = (SemaNames){0}; sema->indexed_locals = 0;
  }
  sema->current_function = UINT32_MAX;
  return *errors == 0;
}
bool dyn_sema_base(DynAstProgram *a, const DynSource *s, unsigned *errors) {
  Sema sema = {.program = a,
               .pointer_bytes = dyn_target_pointer_bytes(dyn_context_target(&s->context)),
               .current_function = UINT32_MAX,
               .current_return_type = DYN_TYPE_VOID};
  for (size_t i = 0; i < a->array_count; ++i) {
    if (a->arrays[i].length && !sema_type_layout(&sema, a, DYN_TYPE_ARRAY_BASE + (DynType)i, false))
      error_span((DynSpan){0}, s, errors, "array layout exceeds target address space or has an unsized element");
  }
  bool ready = sema_names_build(&sema.functions, a, s, true) &&
               sema_names_build(&sema.globals, a, s, false);
  if (!ready) {
    a->allocation_failed = true;
    error_span((DynSpan){0}, s, errors, "out of memory indexing symbols");
  }
  bool ok = ready && sema_program(&sema, a, s, errors);
  free(sema.functions.buckets);
  free(sema.functions.next);
  free(sema.globals.buckets);
  free(sema.globals.next);
  free(sema.locals.buckets);
  free(sema.locals.next);
  free(sema.active_loops);
  return ok;
}
