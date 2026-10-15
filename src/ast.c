#include "dyn_load.h"
#include "dyn_ast.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>


bool dyn_span_text_equal(DynSpan a, DynSpan b, const DynSource *s) {
  return a.end_byte - a.start_byte == b.end_byte - b.start_byte &&
         !memcmp(s->text + a.start_byte, s->text + b.start_byte,
                 a.end_byte - a.start_byte);
}
static const char *module_source_path(const DynSource *source, size_t offset) {
  size_t first = 0, end = source->map_count;
  while (first < end) {
    size_t middle = first + (end - first) / 2;
    const DynSourceMap *map = &source->maps[middle];
    if (offset < map->start)
      end = middle;
    else if (offset > map->end)
      first = middle + 1;
    else
      return map->path;
  }
  return source->path;
}
/* Rewritten imported names are explicit module-qualified bindings. Unqualified
   names may only see declarations in their own source directory. */
bool dyn_module_name_equal(DynSpan use, DynSpan declaration,
                           const DynSource *source) {
  if (!dyn_span_text_equal(use, declaration, source))
    return false;
  /* Compiler-generated reflection declarations precede every source map. */
  if (source->map_count && declaration.start_byte < source->maps[0].start)
    return true;
  if (use.end_byte - use.start_byte >= 5 &&
      !memcmp(source->text + use.start_byte, "dyn_m", 5))
    return true;
  const char *a = module_source_path(source, use.start_byte);
  const char *b = module_source_path(source, declaration.start_byte);
  if (a == b || !a || !b)
    return true;
  const char *ae = strrchr(a, '/'), *be = strrchr(b, '/');
  size_t an = ae ? (size_t)(ae - a) : 0;
  size_t bn = be ? (size_t)(be - b) : 0;
  return an == bn && !memcmp(a, b, an);
}
static uint64_t ast_name_hash(DynSpan name, const DynSource *s) {
  uint64_t hash = UINT64_C(14695981039346656037);
  for (size_t i = name.start_byte; i < name.end_byte; ++i)
    hash = (hash ^ (unsigned char)s->text[i]) * UINT64_C(1099511628211);
  return hash;
}
static DynSpan ast_index_span(const void *names, size_t stride, size_t i) {
  DynSpan name;
  memcpy(&name, (const unsigned char *)names + stride * i, sizeof(name));
  return name;
}
uint32_t dyn_name_index_find(DynNameIndex *index, const void *names, size_t stride,
                             size_t count, DynSpan name, const DynSource *s,
                             bool module, bool *failed) {
  if (count >= 32 && !*failed) {
    if (count > index->capacity / 2) {
      size_t capacity = 64;
      while (capacity / 2 < count && capacity <= SIZE_MAX / 2) capacity *= 2;
      if (capacity / 2 < count || capacity > SIZE_MAX / sizeof(uint32_t)) {
        *failed = true;
      } else {
        uint32_t *buckets = calloc(capacity, sizeof(*buckets));
        uint32_t *next = malloc(capacity / 2 * sizeof(*next));
        if (!buckets || !next) { free(buckets); free(next); *failed = true; }
        else {
          free(index->buckets); free(index->next);
          *index = (DynNameIndex){buckets, next, 0, capacity};
        }
      }
    }
    if (!*failed) {
      for (size_t i = index->count; i < count; ++i) {
        size_t bucket = ast_name_hash(ast_index_span(names, stride, i), s) & (index->capacity - 1);
        index->next[i] = index->buckets[bucket];
        index->buckets[bucket] = (uint32_t)i + 1;
      }
      index->count = count;
      uint32_t found = UINT32_MAX;
      for (uint32_t entry = index->buckets[ast_name_hash(name, s) & (index->capacity - 1)];
           entry; entry = index->next[entry - 1]) {
        DynSpan declaration = ast_index_span(names, stride, entry - 1);
        if ((module ? dyn_module_name_equal(name, declaration, s)
                    : dyn_span_text_equal(name, declaration, s)) && entry - 1 < found)
          found = entry - 1;
      }
      return found;
    }
  }
  for (uint32_t i = 0; i < count; ++i) {
    DynSpan declaration = ast_index_span(names, stride, i);
    if (module ? dyn_module_name_equal(name, declaration, s)
               : dyn_span_text_equal(name, declaration, s)) return i;
  }
  return UINT32_MAX;
}
static void ast_name_index_free(DynNameIndex *index) {
  free(index->buckets); free(index->next);
}
const char *dyn_type_name(DynType t) {
  static const char *names[] = {
      "<infer>", "<error>", "void",       "bool",   "i8",  "i16",   "i32",
      "i64",     "u8",      "u16",        "u32",    "u64", "isize", "usize",
      "f32",     "f64",     "[]const u8", "rawptr", "any"};
  return t < DYN_TYPE_STRUCT_BASE ? names[t]
         : dyn_type_is_enum(t)    ? "enum"
         : dyn_type_is_pointer(t) ? "pointer"
         : dyn_type_is_array(t)   ? "array"
         : dyn_type_is_slice(t)   ? "slice"
                                  : "struct";
}
bool dyn_type_is_struct(DynType t) {
  return t >= DYN_TYPE_STRUCT_BASE && t < DYN_TYPE_ENUM_BASE;
}
bool dyn_type_is_enum(DynType t) {
  return t >= DYN_TYPE_ENUM_BASE && t < DYN_TYPE_POINTER_BASE;
}
bool dyn_type_is_pointer(DynType t) {
  return t >= DYN_TYPE_POINTER_BASE && t < DYN_TYPE_ARRAY_BASE;
}
bool dyn_type_is_array(DynType t) {
  return t >= DYN_TYPE_ARRAY_BASE && t < DYN_TYPE_SLICE_BASE;
}
bool dyn_type_is_slice(DynType t) {
  return t >= DYN_TYPE_SLICE_BASE && t < DYN_TYPE_FN_BASE;
}
bool dyn_type_is_function(DynType t) {
  return t >= DYN_TYPE_FN_BASE && t < DYN_TYPE_DISTINCT_BASE;
}
bool dyn_type_is_distinct(DynType t) { return t >= DYN_TYPE_DISTINCT_BASE && t < DYN_TYPE_PARAM_BASE; }
static void diagnostic_span(DynSpan p, const DynSource *s, unsigned *errors,
                            const char *message) {
  dyn_diagnostic_source("error", s, p.start_byte, p.end_byte, message);
  ++*errors;
}
#define diagnostic(n, s, e, m) diagnostic_span((n), (s), (e), (m))
static bool reserve_expr(DynAstProgram *a) {
  if (a->expression_count < a->expression_capacity) {
    return true;
  }
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
static bool reserve_stmt(DynAstProgram *a) {
  if (a->statement_count < a->statement_capacity) {
    return true;
  }
  size_t c = a->statement_capacity ? a->statement_capacity * 2 : 16;
  void *p = realloc(a->statements, c * sizeof(*a->statements));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->statements = p;
  a->statement_capacity = c;
  return true;
}
static bool reserve_pattern(DynAstProgram *a) {
  if (a->pattern_count < a->pattern_capacity) {
    return true;
  }
  size_t c = a->pattern_capacity ? a->pattern_capacity * 2 : 16;
  void *p = realloc(a->patterns, c * sizeof(*a->patterns));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->patterns = p;
  a->pattern_capacity = c;
  return true;
}
static bool reserve_case_arm(DynAstProgram *a) {
  if (a->case_arm_count < a->case_arm_capacity) {
    return true;
  }
  size_t c = a->case_arm_capacity ? a->case_arm_capacity * 2 : 8;
  void *p = realloc(a->case_arms, c * sizeof(*a->case_arms));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->case_arms = p;
  a->case_arm_capacity = c;
  return true;
}
static bool reserve_child(DynAstProgram *a) {
  if (a->child_count < a->child_capacity) {
    return true;
  }
  size_t c = a->child_capacity ? a->child_capacity * 2 : 32;
  void *p = realloc(a->children, c * sizeof(*a->children));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->children = p;
  a->child_capacity = c;
  return true;
}
static bool reserve_item(DynAstProgram *a) {
  if (a->item_count < a->item_capacity) {
    return true;
  }
  size_t c = a->item_capacity ? a->item_capacity * 2 : 32;
  void *p = realloc(a->items, c * sizeof(*a->items));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->items = p;
  a->item_capacity = c;
  return true;
}
static bool reserve_items(DynAstProgram *a, size_t count) {
  while (a->item_count + count > a->item_capacity) {
    size_t c = a->item_capacity ? a->item_capacity * 2 : 32;
    if (c < a->item_count + count)
      c = a->item_count + count;
    void *p = realloc(a->items, c * sizeof(*a->items));
    if (!p) {
      a->allocation_failed = true;
      return false;
    }
    a->items = p;
    a->item_capacity = c;
  }
  return true;
}
static bool reserve_field(DynAstProgram *a) {
  if (a->field_count < a->field_capacity) {
    return true;
  }
  size_t c = a->field_capacity ? a->field_capacity * 2 : 32;
  void *p = realloc(a->fields, c * sizeof(*a->fields));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->fields = p;
  a->field_capacity = c;
  return true;
}
static bool reserve_struct(DynAstProgram *a) {
  if (a->struct_count < a->struct_capacity) {
    return true;
  }
  size_t c = a->struct_capacity ? a->struct_capacity * 2 : 8;
  void *p = realloc(a->structs, c * sizeof(*a->structs));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->structs = p;
  a->struct_capacity = c;
  return true;
}
static bool reserve_enum(DynAstProgram *a) {
  if (a->enum_count < a->enum_capacity) {
    return true;
  }
  size_t c = a->enum_capacity ? a->enum_capacity * 2 : 8;
  void *p = realloc(a->enums, c * sizeof(*a->enums));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->enums = p;
  a->enum_capacity = c;
  return true;
}
static bool reserve_variant(DynAstProgram *a) {
  if (a->variant_count < a->variant_capacity) {
    return true;
  }
  size_t c = a->variant_capacity ? a->variant_capacity * 2 : 16;
  void *p = realloc(a->variants, c * sizeof(*a->variants));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->variants = p;
  a->variant_capacity = c;
  return true;
}
static bool reserve_param(DynAstProgram *a) {
  if (a->param_count < a->param_capacity) {
    return true;
  }
  size_t c = a->param_capacity ? a->param_capacity * 2 : 16;
  void *p = realloc(a->params, c * sizeof(*a->params));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->params = p;
  a->param_capacity = c;
  return true;
}
static bool reserve_function(DynAstProgram *a) {
  if (a->function_count < a->function_capacity) {
    return true;
  }
  size_t c = a->function_capacity ? a->function_capacity * 2 : 8;
  void *p = realloc(a->functions, c * sizeof(*a->functions));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->functions = p;
  a->function_capacity = c;
  return true;
}
static bool reserve_global(DynAstProgram *a) {
  if (a->global_count < a->global_capacity) {
    return true;
  }
  size_t c = a->global_capacity ? a->global_capacity * 2 : 8;
  void *p = realloc(a->globals, c * sizeof(*a->globals));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->globals = p;
  a->global_capacity = c;
  return true;
}
static bool reserve_pointer(DynAstProgram *a) {
  if (a->pointer_count < a->pointer_capacity) {
    return true;
  }
  size_t c = a->pointer_capacity ? a->pointer_capacity * 2 : 8;
  void *p = realloc(a->pointers, c * sizeof(*a->pointers));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->pointers = p;
  a->pointer_capacity = c;
  return true;
}
static bool reserve_array(DynAstProgram *a) {
  if (a->array_count < a->array_capacity) {
    return true;
  }
  size_t c = a->array_capacity ? a->array_capacity * 2 : 8;
  void *p = realloc(a->arrays, c * sizeof(*a->arrays));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->arrays = p;
  a->array_capacity = c;
  return true;
}
static bool reserve_slice(DynAstProgram *a) {
  if (a->slice_count < a->slice_capacity) {
    return true;
  }
  size_t c = a->slice_capacity ? a->slice_capacity * 2 : 8;
  void *p = realloc(a->slices, c * sizeof(*a->slices));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->slices = p;
  a->slice_capacity = c;
  return true;
}
static bool reserve_string(DynAstProgram *a) {
  if (a->string_count < a->string_capacity) {
    return true;
  }
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
static bool reserve_fn_type(DynAstProgram *a) {
  if (a->fn_type_count < a->fn_type_capacity) {
    return true;
  }
  size_t c = a->fn_type_capacity ? a->fn_type_capacity * 2 : 8;
  void *p = realloc(a->fn_types, c * sizeof(*a->fn_types));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->fn_types = p;
  a->fn_type_capacity = c;
  return true;
}
static bool reserve_fn_type_params(DynAstProgram *a, size_t extra) {
  if (a->fn_type_param_count + extra <= a->fn_type_param_capacity) {
    return true;
  }
  size_t c = a->fn_type_param_capacity ? a->fn_type_param_capacity * 2 : 16;
  while (c < a->fn_type_param_count + extra)
    c *= 2;
  void *p = realloc(a->fn_type_params, c * sizeof(*a->fn_type_params));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->fn_type_params = p;
  a->fn_type_param_capacity = c;
  return true;
}
static bool reserve_alias(DynAstProgram *a) {
  if (a->alias_count < a->alias_capacity) {
    return true;
  }
  size_t c = a->alias_capacity ? a->alias_capacity * 2 : 8;
  void *p = realloc(a->aliases, c * sizeof(*a->aliases));
  if (!p) {
    a->allocation_failed = true;
    return false;
  }

  a->aliases = p;
  a->alias_capacity = c;
  return true;
}
static DynType intern_pointer(DynAstProgram *a, DynType pointee,
                              bool is_const) {
  for (uint32_t i = 0; i < a->pointer_count; ++i)
    if (a->pointers[i].pointee == pointee &&
        a->pointers[i].is_const == is_const) {
      return DYN_TYPE_POINTER_BASE + i;
    }
  if (a->pointer_count >= DYN_TYPE_ARRAY_BASE - DYN_TYPE_POINTER_BASE) {
    a->type_capacity_exceeded = true;
    return DYN_TYPE_ERROR;
  }
  if (!reserve_pointer(a)) {
    return DYN_TYPE_ERROR;
  }
  a->pointers[a->pointer_count] = (DynAstPointer){pointee, is_const};
  return DYN_TYPE_POINTER_BASE + a->pointer_count++;
}
static DynType intern_array(DynAstProgram *a, DynType element,
                            uint64_t length) {
  for (uint32_t i = 0; i < a->array_count; ++i)
    if (a->arrays[i].element == element && a->arrays[i].length == length) {
      return DYN_TYPE_ARRAY_BASE + i;
    }
  if (a->array_count >= DYN_TYPE_SLICE_BASE - DYN_TYPE_ARRAY_BASE) {
    a->type_capacity_exceeded = true;
    return DYN_TYPE_ERROR;
  }
  if (!reserve_array(a)) {
    return DYN_TYPE_ERROR;
  }
  a->arrays[a->array_count] = (DynAstArray){element, length};
  return DYN_TYPE_ARRAY_BASE + a->array_count++;
}
static DynType intern_slice(DynAstProgram *a, DynType element, bool is_const) {
  for (uint32_t i = 0; i < a->slice_count; ++i)
    if (a->slices[i].element == element && a->slices[i].is_const == is_const) {
      return DYN_TYPE_SLICE_BASE + i;
    }
  if (a->slice_count >= DYN_TYPE_FN_BASE - DYN_TYPE_SLICE_BASE) {
    a->type_capacity_exceeded = true;
    return DYN_TYPE_ERROR;
  }
  if (!reserve_slice(a)) {
    return DYN_TYPE_ERROR;
  }
  a->slices[a->slice_count] = (DynAstSlice){element, is_const};
  return DYN_TYPE_SLICE_BASE + a->slice_count++;
}
static DynType intern_fn_type(DynAstProgram *a, const DynType *params,
                              uint32_t count, DynType result) {
  for (uint32_t i = 0; i < a->fn_type_count; ++i) {
    DynAstFnType *f = &a->fn_types[i];
    if (f->return_type != result || f->param_count != count || f->variadic) {
      continue;
    }
    bool same = true;
    for (uint32_t j = 0; j < count; ++j)
      if (a->fn_type_params[f->param_start + j] != params[j]) {
        same = false;
      }
    if (same) {
      return DYN_TYPE_FN_BASE + i;
    }
  }
  if (a->fn_type_count >= DYN_TYPE_DISTINCT_BASE - DYN_TYPE_FN_BASE) {
    a->type_capacity_exceeded = true;
    return DYN_TYPE_ERROR;
  }
  if (!reserve_fn_type(a) || !reserve_fn_type_params(a, count)) {
    return DYN_TYPE_ERROR;
  }
  uint32_t start = (uint32_t)a->fn_type_param_count;
  for (uint32_t i = 0; i < count; ++i)
    a->fn_type_params[a->fn_type_param_count++] = params[i];
  a->fn_types[a->fn_type_count] = (DynAstFnType){result, start, count, false};
  return DYN_TYPE_FN_BASE + a->fn_type_count++;
}
static DynSpan unqualified_span(DynSpan name, const DynSource *s) {
  for (uint32_t i = name.start_byte; i < name.end_byte; ++i)
    if (s->text[i] == '.') {
      name.start_byte = i + 1;
    }
  return name;
}
static uint32_t find_struct(DynAstProgram *a, DynSpan name,
                            const DynSource *s) {
  name = unqualified_span(name, s);
  uint32_t id = dyn_name_index_find(&a->struct_names,
      a->struct_count ? &a->structs[0].name : NULL, sizeof(*a->structs), a->struct_count,
      name, s, true, &a->allocation_failed);
  if (id != UINT32_MAX) return id;
  id = dyn_name_index_find(&a->enum_names,
      a->enum_count ? &a->enums[0].name : NULL, sizeof(*a->enums), a->enum_count,
      name, s, true, &a->allocation_failed);
  return id == UINT32_MAX ? id : DYN_TYPE_ENUM_BASE - DYN_TYPE_STRUCT_BASE + id;
}
static uint32_t find_enum(DynAstProgram *a, DynSpan name, const DynSource *s) {
  return dyn_name_index_find(&a->enum_names,
      a->enum_count ? &a->enums[0].name : NULL, sizeof(*a->enums), a->enum_count,
      unqualified_span(name, s), s, true, &a->allocation_failed);
}
static uint32_t find_alias(DynAstProgram *a, DynSpan name, const DynSource *s) {
  return dyn_name_index_find(&a->alias_names,
      a->alias_count ? &a->aliases[0].name : NULL, sizeof(*a->aliases), a->alias_count,
      unqualified_span(name, s), s, true, &a->allocation_failed);
}
static DynOperator op_from(const char *s) {
  struct {
    const char *s;
    DynOperator op;
  } m[] = {{"-", DYN_OP_SUB},          {"-=", DYN_OP_SUB},
           {"!", DYN_OP_NOT},          {"~", DYN_OP_BIT_NOT},
           {"+", DYN_OP_ADD},          {"+=", DYN_OP_ADD},
           {"*", DYN_OP_MUL},          {"*=", DYN_OP_MUL},
           {"/", DYN_OP_DIV},          {"/=", DYN_OP_DIV},
           {"%", DYN_OP_REM},          {"%=", DYN_OP_REM},
           {"==", DYN_OP_EQ},          {"!=", DYN_OP_NE},
           {"<", DYN_OP_LT},           {"<=", DYN_OP_LE},
           {">", DYN_OP_GT},           {">=", DYN_OP_GE},
           {"&&", DYN_OP_LOGICAL_AND}, {"||", DYN_OP_LOGICAL_OR},
           {"&", DYN_OP_BIT_AND},      {"&=", DYN_OP_BIT_AND},
           {"|", DYN_OP_BIT_OR},       {"|=", DYN_OP_BIT_OR},
           {"^", DYN_OP_BIT_XOR},      {"^=", DYN_OP_BIT_XOR},
           {"<<", DYN_OP_SHL},         {"<<=", DYN_OP_SHL},
           {">>", DYN_OP_SHR},         {">>=", DYN_OP_SHR}};
  for (size_t i = 0; i < sizeof(m) / sizeof(m[0]); ++i)
    if (!strcmp(s, m[i].s)) {
      return m[i].op;
    }
  return DYN_OP_NONE;
}
static DynType compact_alias_type(DynAstCompactRef, const DynSource *, DynAstProgram *);
static DynType resolve_alias(DynAstProgram *a, uint32_t id,
                             const DynSource *s) {
  DynAstAlias *x = &a->aliases[id];
  if (x->state == 2) {
    return x->distinct ? DYN_TYPE_DISTINCT_BASE + id : x->target;
  }
  if (x->state == 1) {
    return DYN_TYPE_ERROR;
  }
  x->state = 1;
  x->target = compact_alias_type(x->compact_type, s, a);
  DynType representation = x->target;
  size_t guard = 0;
  while (dyn_type_is_distinct(representation) && guard++ <= a->alias_count) {
    uint32_t inner = representation - DYN_TYPE_DISTINCT_BASE;
    if (inner >= a->alias_count) {
      representation = DYN_TYPE_ERROR;
      break;
    }
    representation = a->aliases[inner].target;
  }
  bool numeric =
      (representation >= DYN_TYPE_I8 && representation <= DYN_TYPE_USIZE) ||
      representation == DYN_TYPE_F32 || representation == DYN_TYPE_F64;
  if (x->target == DYN_TYPE_ERROR || x->target == DYN_TYPE_VOID ||
      x->target == DYN_TYPE_INFER || (x->distinct && !numeric)) {
    x->state = 3;
    return DYN_TYPE_ERROR;
  }
  x->state = 2;
  return x->distinct ? DYN_TYPE_DISTINCT_BASE + id : x->target;
}
static uint64_t parse_uint(DynSpan n, const DynSource *s, bool *ok) {
  uint32_t i = n.start_byte, e = n.end_byte;
  unsigned base = 10;
  uint64_t v = 0;
  *ok = true;
  if (e - i > 2 && s->text[i] == '0') {
    char p = s->text[i + 1];
    if (p == 'x') {
      base = 16;
      i += 2;
    } else if (p == 'b') {
      base = 2;
      i += 2;
    } else if (p == 'o') {
      base = 8;
      i += 2;
    }
  }
  for (; i < e; ++i) {
    char c = s->text[i];
    if (c == '_') {
      continue;
    }
    unsigned d = isdigit((unsigned char)c)
                     ? (unsigned)(c - '0')
                     : (unsigned)(tolower((unsigned char)c) - 'a' + 10);
    if (v > (UINT64_MAX - d) / base) {
      *ok = false;
      return 0;
    }
    v = v * base + d;
  }
  return v;
}
static bool parse_char(DynSpan n, const DynSource *s, uint64_t *value) {
  uint32_t i = n.start_byte + 1, e = n.end_byte - 1;
  if (i >= e) {
    return false;
  }
  const unsigned char *p = (const unsigned char *)s->text + i;
  if (*p == '\\') {
    if (i + 1 >= e) {
      return false;
    }
    char c = s->text[++i];
    if (c == 'n') {
      *value = '\n';
    } else if (c == 'r') {
      *value = '\r';
    } else if (c == 't') {
      *value = '\t';
    } else if (c == '0') {
      *value = 0;
    } else if (c == '\\' || c == '\'' || c == '"') {
      *value = (unsigned char)c;
    } else if (c == 'x' && i + 2 < e) {
      unsigned v = 0;
      for (unsigned j = 0; j < 2; ++j) {
        char h = s->text[++i];
        v = v * 16 + (unsigned)(isdigit((unsigned char)h)
                                    ? h - '0'
                                    : tolower((unsigned char)h) - 'a' + 10);
      }
      *value = v;
    } else if (c == 'u' && i + 1 < e && s->text[i + 1] == '{') {
      i += 2;
      uint64_t v = 0;
      while (i < e && s->text[i] != '}') {
        char h = s->text[i++];
        v = v * 16 + (uint64_t)(isdigit((unsigned char)h)
                                    ? h - '0'
                                    : tolower((unsigned char)h) - 'a' + 10);
      }
      if (i >= e || v > 0x10ffff || (v >= 0xd800 && v <= 0xdfff)) {
        return false;
      }
      *value = v;
    } else {
      return false;
    }
    return true;
  }
  unsigned char c = p[0];
  if (c < 0x80) {
    *value = c;
    return i + 1 == e;
  }
  unsigned count = c >= 0xf0 ? 4 : c >= 0xe0 ? 3 : c >= 0xc0 ? 2 : 0;
  if (!count || i + count != e) {
    return false;
  }
  uint64_t v = c & ((1u << (7 - count)) - 1u);
  for (unsigned j = 1; j < count; ++j) {
    if ((p[j] & 0xc0) != 0x80) {
      return false;
    }
    v = (v << 6) | (p[j] & 0x3f);
  }
  if (v > 0x10ffff || (v >= 0xd800 && v <= 0xdfff)) {
    return false;
  }
  *value = v;
  return true;
}
static uint32_t parse_string(DynSpan n, const DynSource *s, DynAstProgram *a,
                             unsigned *errors) {
  uint32_t begin = n.start_byte + 1, end = n.end_byte - 1;
  unsigned char *out = malloc(end - begin + 1);
  size_t count = 0;
  if (!out || !reserve_string(a)) {
    free(out);
    diagnostic(n, s, errors, "out of memory");
    return UINT32_MAX;
  }
  for (uint32_t i = begin; i < end; ++i) {
    unsigned char c = (unsigned char)s->text[i];
    if (c != '\\') {
      out[count++] = c;
      continue;
    }
    if (++i >= end) {
      free(out);
      diagnostic(n, s, errors, "invalid string escape");
      return UINT32_MAX;
    }
    c = (unsigned char)s->text[i];
    if (c == 'n') {
      out[count++] = '\n';
    } else if (c == 'r') {
      out[count++] = '\r';
    } else if (c == 't') {
      out[count++] = '\t';
    } else if (c == '0') {
      out[count++] = 0;
    } else if (c == '\\' || c == '\'' || c == '"') {
      out[count++] = c;
    } else if (c == 'x' && i + 2 < end) {
      unsigned value = 0;
      for (uint32_t j = 0; j < 2; ++j) {
        char h = s->text[++i];
        value =
            value * 16 + (unsigned)(isdigit((unsigned char)h)
                                        ? h - '0'
                                        : tolower((unsigned char)h) - 'a' + 10);
      }
      out[count++] = (unsigned char)value;
    } else {
      free(out);
      diagnostic(n, s, errors, "unsupported string escape");
      return UINT32_MAX;
    }
  }
  uint32_t id = (uint32_t)a->string_count;
  a->strings[a->string_count++] = (DynAstString){out, count};
  return id;
}
static DynType scope_type(DynAstProgram *, DynSpan, const DynSource *, bool);
static bool negative_literal(const DynAstProgram *a, const DynAstExpr *e) {
  if (e->kind != DYN_EXPR_UNARY || e->op != DYN_OP_NEG || e->left == DYN_NO_EXPR)
    return false;
  DynExprKind k = a->expressions[e->left].kind;
  return k == DYN_EXPR_INT || k == DYN_EXPR_FLOAT || k == DYN_EXPR_CHAR;
}
/* Marks the integer operators written inside #wrap(...) as wrapping. Called
   functions are untouched; their arguments are written here, so they are marked. */
static unsigned mark_wrap(DynAstProgram *a, DynExprId id, unsigned depth) {
  if (id == DYN_NO_EXPR || id >= a->expression_count || depth > 4096)
    return 0;
  DynAstExpr *e = &a->expressions[id];
  unsigned marked = 0;
  if ((e->kind == DYN_EXPR_BINARY &&
       (e->op == DYN_OP_ADD || e->op == DYN_OP_SUB || e->op == DYN_OP_MUL ||
        e->op == DYN_OP_SHL)) ||
      (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_NEG &&
       !negative_literal(a, e))) {
    e->wrap = true;
    marked = 1;
  }
  if (e->kind == DYN_EXPR_SIZE || e->kind == DYN_EXPR_ALIGN ||
      e->kind == DYN_EXPR_TYPEOF || e->kind == DYN_EXPR_LEN)
    return marked;
  marked += mark_wrap(a, e->left, depth + 1);
  marked += mark_wrap(a, e->right, depth + 1);
  if (e->kind == DYN_EXPR_SLICE)
    marked += mark_wrap(a, (DynExprId)e->integer, depth + 1);
  if (e->kind == DYN_EXPR_CALL || e->kind == DYN_EXPR_STRUCT ||
      e->kind == DYN_EXPR_ARRAY || e->kind == DYN_EXPR_SYSCALL)
    for (uint32_t i = 0; i < e->item_count; ++i)
      marked += mark_wrap(a, a->items[e->item_start + i].expression, depth + 1);
  return marked;
}


static DynType parse_type_name(DynSpan p, const DynSource *s, DynAstProgram *a) {
  struct {
    const char *n;
    DynType t;
  } m[] = {{"bool", DYN_TYPE_BOOL},   {"i8", DYN_TYPE_I8},
           {"i16", DYN_TYPE_I16},     {"i32", DYN_TYPE_I32},
           {"i64", DYN_TYPE_I64},     {"u8", DYN_TYPE_U8},
           {"u16", DYN_TYPE_U16},     {"u32", DYN_TYPE_U32},
           {"u64", DYN_TYPE_U64},     {"isize", DYN_TYPE_ISIZE},
           {"usize", DYN_TYPE_USIZE}, {"f32", DYN_TYPE_F32},
           {"f64", DYN_TYPE_F64},     {"rawptr", DYN_TYPE_RAWPTR},
           {"any", DYN_TYPE_ANY}};
  for (size_t i = 0; i < sizeof(m) / sizeof(m[0]); ++i)
    if (p.end_byte - p.start_byte == strlen(m[i].n) &&
        !memcmp(s->text + p.start_byte, m[i].n, strlen(m[i].n))) {
      return m[i].t;
    }
  DynType bound = scope_type(a, p, s, false);
  if (bound != DYN_TYPE_ERROR)
    return bound;
  uint32_t alias = find_alias(a, p, s);
  if (alias != UINT32_MAX) {
    return resolve_alias(a, alias, s);
  }
  uint32_t id = find_struct(a, p, s);
  return id == UINT32_MAX ? DYN_TYPE_ERROR : DYN_TYPE_STRUCT_BASE + id;
}

/* A name in the generic scope. While declaring a signature, `$T` introduces
   T as type parameter k; while lowering an instance, T is a concrete type. */
static DynType scope_type(DynAstProgram *a, DynSpan name, const DynSource *s,
                          bool introduce) {
  for (uint32_t i = 0; i < a->scope_count; ++i)
    if (dyn_span_text_equal(a->scope_names[i], name, s))
      return introduce ? DYN_TYPE_ERROR : a->scope_types[i];
  if (!introduce || a->scope_count == DYN_MAX_TYPE_PARAMS)
    return DYN_TYPE_ERROR;
  a->scope_names[a->scope_count] = name;
  a->scope_types[a->scope_count] = DYN_TYPE_PARAM_BASE + a->scope_count;
  return a->scope_types[a->scope_count++];
}

#include "ast_compact.inc"

void dyn_ast_program_free(DynAstProgram *a) {
  for (size_t i = 0; i < a->compact_body_count; ++i)
    exp_snapshot_release(a->compact_bodies[i].snapshot);
  free(a->compact_bodies);
  for (size_t i = 0; i < a->compact_declaration_count; ++i)
    exp_snapshot_release(a->compact_declarations[i].ref.snapshot);
  free(a->compact_declarations);
  ast_name_index_free(&a->struct_names);
  ast_name_index_free(&a->enum_names);
  ast_name_index_free(&a->alias_names);
  for (size_t i = 0; i < a->struct_count; ++i) ast_name_index_free(&a->structs[i].field_names);
  for (size_t i = 0; i < a->enum_count; ++i) ast_name_index_free(&a->enums[i].variant_names);
  for (size_t i = 0; i < a->string_count; ++i)
    free(a->strings[i].data);
  free(a->strings);
  free(a->expressions);
  free(a->items);
  free(a->fields);
  free(a->structs);
  free(a->enums);
  free(a->variants);
  free(a->params);
  free(a->functions);
  free(a->globals);
  free(a->asserts);
  free(a->global_init_order);
  free(a->pointers);
  free(a->arrays);
  free(a->slices);
  free(a->fn_types);
  free(a->fn_type_params);
  free(a->aliases);
  free(a->statements);
  free(a->patterns);
  free(a->case_arms);
  free(a->children);
  free(a->locals);
  free(a->generics);
  free(a->generic_params);
  free(a->instances);
  memset(a, 0, sizeof(*a));
}
DynType dyn_ast_named_type(DynAstProgram *a, DynSpan name, const DynSource *s) {
  uint32_t alias = find_alias(a, name, s);
  if (alias != UINT32_MAX)
    return resolve_alias(a, alias, s);
  uint32_t id = find_struct(a, name, s);
  return id == UINT32_MAX ? DYN_TYPE_ERROR : DYN_TYPE_STRUCT_BASE + id;
}
DynType dyn_ast_substitute(DynAstProgram *a, DynType t, const DynType *args) {
  if (dyn_type_is_param(t))
    return args[t - DYN_TYPE_PARAM_BASE];
  if (dyn_type_is_pointer(t)) {
    DynAstPointer p = a->pointers[t - DYN_TYPE_POINTER_BASE];
    DynType pointee = dyn_ast_substitute(a, p.pointee, args);
    return pointee == p.pointee ? t : intern_pointer(a, pointee, p.is_const);
  }
  if (dyn_type_is_slice(t)) {
    DynAstSlice p = a->slices[t - DYN_TYPE_SLICE_BASE];
    DynType element = dyn_ast_substitute(a, p.element, args);
    return element == p.element ? t : intern_slice(a, element, p.is_const);
  }
  if (dyn_type_is_array(t)) {
    DynAstArray p = a->arrays[t - DYN_TYPE_ARRAY_BASE];
    DynType element = dyn_ast_substitute(a, p.element, args);
    return element == p.element ? t : intern_array(a, element, p.length);
  }
  if (dyn_type_is_function(t)) {
    DynAstFnType f = a->fn_types[t - DYN_TYPE_FN_BASE];
    DynType params[64];
    if (f.param_count > 64 || f.variadic)
      return t;
    bool changed = false;
    for (uint32_t i = 0; i < f.param_count; ++i) {
      params[i] = dyn_ast_substitute(a, a->fn_type_params[f.param_start + i], args);
      changed |= params[i] != a->fn_type_params[f.param_start + i];
    }
    DynType result = dyn_ast_substitute(a, f.return_type, args);
    if (!changed && result == f.return_type)
      return t;
    return intern_fn_type(a, params, f.param_count, result);
  }
  return t;
}
uint32_t dyn_ast_instantiate(DynAstProgram *a, const DynSource *s, uint32_t generic,
                             const DynType *args, uint32_t depth, DynSpan call,
                             uint64_t hash) {
  (void)s;
  DynAstGeneric g = a->generics[generic];
  if (a->instance_count == a->instance_capacity) {
    size_t c = a->instance_capacity ? a->instance_capacity * 2 : 16;
    void *p = realloc(a->instances, c * sizeof(*a->instances));
    if (!p) { a->allocation_failed = true; return UINT32_MAX; }
    a->instances = p;
    a->instance_capacity = c;
  }
  if (!reserve_function(a))
    return UINT32_MAX;
  DynAstFn fn = a->functions[g.function];
  fn.is_generic = false;
  fn.interface_only = false;
  fn.is_instance = true;
  fn.body_pending = true;
  fn.instance = (uint32_t)a->instance_count;
  fn.param_start = (uint32_t)a->param_count;
  fn.param_count = 0;
  fn.return_type = dyn_ast_substitute(a, g.return_pattern, args);
  for (uint32_t i = 0; i < g.param_count; ++i) {
    DynAstGenericParam p = a->generic_params[g.param_start + i];
    if (p.is_type)
      continue;
    if (!reserve_param(a))
      return UINT32_MAX;
    a->params[a->param_count++] = (DynAstParam){
        .name = p.name, .type = dyn_ast_substitute(a, p.pattern, args),
        .local_id = UINT32_MAX};
    ++fn.param_count;
  }
  DynAstInstance instance = {.generic = generic, .function = (uint32_t)a->function_count,
                             .depth = depth, .call = call, .hash = hash};
  memcpy(instance.args, args, g.type_param_count * sizeof(*args));
  a->instances[a->instance_count++] = instance;
  a->functions[a->function_count] = fn;
  return (uint32_t)a->function_count++;
}
bool dyn_ast_lower_instance(DynAstProgram *a, const DynSource *s, uint32_t function,
                            unsigned *errors) {
  DynAstFn *fn = &a->functions[function];
  fn->body_pending = false;
  DynAstInstance instance = a->instances[fn->instance];
  DynAstGeneric g = a->generics[instance.generic];
  CompactNode prepared = compact_none();
  for (CompactNode c = compact_first(compact_node(g.compact_node)); !compact_null(c); c = compact_next(c))
    if (compact_kind(c) == SRC_BLOCK) prepared = c;
  memcpy(a->scope_names, g.type_names, sizeof(a->scope_names));
  memcpy(a->scope_types, instance.args, sizeof(a->scope_types));
  a->scope_count = g.type_param_count;
  uint32_t start = 0, count = 0;
  bool ok = !compact_null(prepared) &&
      compact_block(prepared, s, a, errors, 0, &start, &count);
  a->scope_count = 0;
  fn = &a->functions[function];
  fn->body_start = start;
  fn->body_count = count;
  return ok;
}
static uint64_t declaration_owner(DynSpan name, const DynSource *s) {
  if (name.end_byte - name.start_byte < 22 ||
      memcmp(s->text + name.start_byte, "dyn_m", 5) ||
      s->text[name.start_byte + 21] != '_')
    return 0;
  uint64_t value = 0;
  for (uint32_t i = 5; i < 21; ++i) {
    unsigned char c = (unsigned char)s->text[name.start_byte + i];
    uint64_t digit = c >= '0' && c <= '9'   ? c - '0'
                     : c >= 'a' && c <= 'f' ? c - 'a' + 10
                     : c >= 'A' && c <= 'F' ? c - 'A' + 10
                                            : 16;
    if (digit == 16)
      return 0;
    value = value * 16 + digit;
  }
  return value;
}
static bool tag_fits(DynType t, uint64_t bits, bool negative) {
  unsigned width = t == DYN_TYPE_I8 || t == DYN_TYPE_U8     ? 8
                   : t == DYN_TYPE_I16 || t == DYN_TYPE_U16 ? 16
                   : t == DYN_TYPE_I32 || t == DYN_TYPE_U32 ? 32
                                                            : 64;
  bool sign = t == DYN_TYPE_I8 || t == DYN_TYPE_I16 || t == DYN_TYPE_I32 ||
              t == DYN_TYPE_I64 || t == DYN_TYPE_ISIZE;
  if (!sign)
    return !negative && (width == 64 || bits < UINT64_C(1) << width);
  int64_t value = (int64_t)bits;
  if (negative != (value < 0))
    return false;
  return width == 64 || (value >= -(INT64_C(1) << (width - 1)) &&
                         value < INT64_C(1) << (width - 1));
}
static uint64_t type_layout(DynType t, bool alignment, DynAstProgram *a,
                            unsigned char *state, const DynSource *s,
                            unsigned *errors);
static bool layout_enum(uint32_t id, DynAstProgram *a, unsigned char *state,
                        const DynSource *s, unsigned *errors);
static bool layout_struct(uint32_t id, DynAstProgram *a, unsigned char *state,
                          const DynSource *s, unsigned *errors) {
  if (state[id] == 2)
    return true;
  if (state[id] == 1) {
    diagnostic_span(a->structs[id].span, s, errors,
                    "struct contains itself by value");
    return false;
  }
  state[id] = 1;
  DynAstStruct *st = &a->structs[id];
  if (!st->field_count) {
    /* Empty values occupy one byte. This keeps array elements and distinct
       addresses representable without special zero-sized pointer rules. */
    st->size = st->alignment = 1;
    state[id] = 2;
    return true;
  }
  uint64_t size = 0, max_align = 1;
  uint64_t limit = dyn_target_pointer_bytes(dyn_context_target(&s->context)) == 4 ? UINT32_MAX : UINT64_MAX;
  for (uint32_t i = 0; i < st->field_count; ++i) {
    DynAstField *f = &a->fields[st->field_start + i];
    uint64_t align = st->packed
                         ? 1
                         : type_layout(f->type, true, a, state, s, errors),
             field_size = type_layout(f->type, false, a, state, s, errors);
    if (!align || !field_size)
      return false;
    if (align > max_align)
      max_align = align;
    if (size > limit - (align - 1)) goto oversized_struct;
    size = (size + align - 1) / align * align;
    f->offset = size;
    if (field_size > limit - size) goto oversized_struct;
    size += field_size;
  }
  if (size > limit - (max_align - 1)) goto oversized_struct;
  size = (size + max_align - 1) / max_align * max_align;
  st->size = size;
  st->alignment = max_align;
  state[id] = 2;
  return true;
oversized_struct:
  diagnostic_span(st->span, s, errors, "struct layout exceeds target address space");
  return false;
}
static uint64_t type_layout(DynType t, bool alignment, DynAstProgram *a,
                            unsigned char *state, const DynSource *s,
                            unsigned *errors) {
  if (dyn_type_is_distinct(t)) {
    uint32_t id = t - DYN_TYPE_DISTINCT_BASE;
    if (id >= a->alias_count)
      return 0;
    return type_layout(a->aliases[id].target, alignment, a, state, s, errors);
  }
  if (dyn_type_is_struct(t)) {
    uint32_t id = t - DYN_TYPE_STRUCT_BASE;
    if (id >= a->struct_count || !layout_struct(id, a, state, s, errors))
      return 0;
    return alignment ? a->structs[id].alignment : a->structs[id].size;
  }
  if (dyn_type_is_enum(t)) {
    uint32_t id = t - DYN_TYPE_ENUM_BASE;
    if (id >= a->enum_count || !layout_enum(id, a, state, s, errors)) return 0;
    DynAstEnum *en = &a->enums[id];
    return alignment ? en->alignment : en->size;
  }
  if (dyn_type_is_array(t)) {
    DynAstArray *x = &a->arrays[t - DYN_TYPE_ARRAY_BASE];
    uint64_t unit = type_layout(x->element, alignment, a, state, s, errors);
    uint64_t limit = dyn_target_pointer_bytes(dyn_context_target(&s->context)) == 4 ? UINT32_MAX : UINT64_MAX;
    if (!alignment && unit && x->length > limit / unit) {
      diagnostic_span((DynSpan){0}, s, errors, "array layout exceeds target address space");
      return 0;
    }
    return alignment ? unit : unit * x->length;
  }
  unsigned pointer = dyn_target_pointer_bytes(dyn_context_target(&s->context));
  if (dyn_type_is_slice(t) || t == DYN_TYPE_STRING)
    return alignment ? pointer : 2 * pointer;
  if (t == DYN_TYPE_ANY) return alignment ? 8 : 16;
  if (dyn_type_is_pointer(t) || dyn_type_is_function(t) || t == DYN_TYPE_RAWPTR ||
      t == DYN_TYPE_USIZE || t == DYN_TYPE_ISIZE) return pointer;
  uint64_t size = t == DYN_TYPE_BOOL || t == DYN_TYPE_I8 || t == DYN_TYPE_U8 ? 1
                  : t == DYN_TYPE_I16 || t == DYN_TYPE_U16                   ? 2
                  : t == DYN_TYPE_I32 || t == DYN_TYPE_U32 || t == DYN_TYPE_F32
                      ? 4
                      : 8;
  return size;
}
static bool layout_enum(uint32_t id, DynAstProgram *a, unsigned char *state,
                        const DynSource *s, unsigned *errors) {
  size_t slot = a->struct_count + id;
  if (state[slot] == 2) return true;
  if (state[slot] == 1) {
    diagnostic_span(a->enums[id].name, s, errors,
                    "enum contains itself by value");
    return false;
  }
  state[slot] = 1;
  DynAstEnum *en = &a->enums[id];
  uint64_t tag_size = type_layout(en->tag_type, false, a, state, s, errors),
           tag_align = type_layout(en->tag_type, true, a, state, s, errors);
  en->payload_alignment = 1;
  en->payload_size = 0;
  for (uint32_t j = 0; j < en->variant_count; ++j) {
    DynType p = a->variants[en->variant_start + j].payload_type;
    if (p == DYN_TYPE_VOID)
      continue;
    if (dyn_type_is_enum(p)) {
      diagnostic_span(a->variants[en->variant_start + j].name, s, errors,
                      "enum payload cannot contain enum directly");
      continue;
    }
    uint64_t pa = type_layout(p, true, a, state, s, errors),
             ps = type_layout(p, false, a, state, s, errors);
    if (!pa || !ps) {
      diagnostic_span(a->variants[en->variant_start + j].name, s, errors,
                      "recursive or incomplete enum payload layout");
      continue;
    }
    if (pa > en->payload_alignment)
      en->payload_alignment = pa;
    if (ps > en->payload_size)
      en->payload_size = ps;
  }
  en->alignment =
      tag_align > en->payload_alignment ? tag_align : en->payload_alignment;
  uint64_t offset = (tag_size + en->payload_alignment - 1) /
                    en->payload_alignment * en->payload_alignment;
  uint64_t limit = dyn_target_pointer_bytes(dyn_context_target(&s->context)) == 4 ? UINT32_MAX : UINT64_MAX;
  if (en->payload_size > limit - offset ||
      offset + en->payload_size > limit - (en->alignment - 1)) {
    diagnostic_span(en->name, s, errors, "enum layout exceeds target address space");
    return false;
  }
  en->size = (offset + en->payload_size + en->alignment - 1) / en->alignment *
             en->alignment;
  state[slot] = 2;
  return true;
}
static bool compute_layouts_v2(DynAstProgram *a, const DynSource *s,
                               unsigned *errors) {
  size_t count = a->struct_count + a->enum_count;
  unsigned char *state = calloc(count, 1);
  if (count && !state) {
    a->allocation_failed = true;
    return false;
  }
  for (uint32_t i = 0; i < a->enum_count; ++i)
    layout_enum(i, a, state, s, errors);
  for (uint32_t i = 0; i < a->struct_count; ++i)
    layout_struct(i, a, state, s, errors);
  free(state);
  return true;
}
static uint32_t find_function(DynNameIndex *index, DynAstProgram *a, DynSpan name,
                              const DynSource *s) {
  return dyn_name_index_find(index, a->function_count ? &a->functions[0].name : NULL,
                             sizeof(*a->functions), a->function_count, name, s,
                             true, &a->allocation_failed);
}
static uint32_t find_global(DynNameIndex *index, DynAstProgram *a, DynSpan name,
                            const DynSource *s) {
  return dyn_name_index_find(index, a->global_count ? &a->globals[0].name : NULL,
                             sizeof(*a->globals), a->global_count, name, s,
                             true, &a->allocation_failed);
}
static bool reserve_generic(DynAstProgram *a, size_t params) {
  if (a->generic_count == a->generic_capacity) {
    size_t c = a->generic_capacity ? a->generic_capacity * 2 : 8;
    void *p = realloc(a->generics, c * sizeof(*a->generics));
    if (!p) { a->allocation_failed = true; return false; }
    a->generics = p;
    a->generic_capacity = c;
  }
  if (a->generic_param_count + params > a->generic_param_capacity) {
    size_t c = a->generic_param_capacity ? a->generic_param_capacity * 2 : 16;
    while (c < a->generic_param_count + params) c *= 2;
    void *p = realloc(a->generic_params, c * sizeof(*a->generic_params));
    if (!p) { a->allocation_failed = true; return false; }
    a->generic_params = p;
    a->generic_param_capacity = c;
  }
  return true;
}
static uint64_t owner_key_value(const char *owner_key) {
  if (!owner_key || !strcmp(owner_key, "root"))
    return 0;
  if (strncmp(owner_key, "dyn_m", 5) || strlen(owner_key) != 21)
    return UINT64_MAX;
  uint64_t value = 0;
  for (unsigned i = 5; i < 21; ++i) {
    unsigned char c = (unsigned char)owner_key[i];
    unsigned digit = c >= '0' && c <= '9'   ? c - '0'
                     : c >= 'a' && c <= 'f' ? c - 'a' + 10
                     : c >= 'A' && c <= 'F' ? c - 'A' + 10
                                            : 16;
    if (digit == 16)
      return UINT64_MAX;
    value = value * 16 + digit;
  }
  return value;
}
#include "ast_compact_declarations.inc"

static bool lower_declarations(DynSpan root, const DynSource *s, DynAstProgram *a,
                               unsigned *errors, const char *owner_key) {
  unsigned before = *errors;
  DynNameIndex functions = {0}, globals = {0};
  bool declarations_ok = compact_add_enum_names(s, a, errors) &&
      compact_add_struct_names(s, a, errors) && compact_add_alias_names(s, a, errors) &&
      compact_add_struct_fields(s, a, errors) && compact_add_enum_variants(s, a, errors) &&
      compute_layouts_v2(a, s, errors) && compact_add_globals(s, a, errors, &globals) &&
      compact_add_asserts(s, a, errors) && compact_add_function_signatures(s, a, errors, &functions, &globals);
  if (!declarations_ok) {
    ast_name_index_free(&functions);
    ast_name_index_free(&globals);
    if (a->invalid_array_extent.end_byte)
      diagnostic(a->invalid_array_extent, s, errors,
          "array length requires nonnegative integer constant arithmetic (no runtime values, cycles, overflow, or division by zero)");
    if (*errors == before)
      diagnostic(root, s, errors, "out of memory");
    return false;
  }
  compact_lower_function_bodies(s, a, errors, owner_key, &functions);
  if (a->invalid_array_extent.end_byte)
    diagnostic(a->invalid_array_extent, s, errors,
        "array length requires nonnegative integer constant arithmetic (no runtime values, cycles, overflow, or division by zero)");
  ast_name_index_free(&functions);
  ast_name_index_free(&globals);
  if (a->type_capacity_exceeded)
    diagnostic(root, s, errors, "interned type capacity exceeded");
  bool found = false;
  for (uint32_t i = 0; i < a->function_count; ++i)
    if (a->functions[i].is_main)
      found = true;
  return found;
}
bool dyn_ast_lower_compact(const DynSource *s, DynAstProgram *a,
                           unsigned *errors, const char *owner_key) {
  memset(a,0,sizeof(*a));
  DynSpan root={s->compact_root_start,s->compact_root_end};
  size_t count=s->syntax_part_count ? s->syntax_part_count : 1;
  for (size_t i=0;i<count;++i) {
    const ExpSnapshotTree *tree=exp_snapshot_tree(s->syntax_part_count ? s->compact_parts[i] : s->compact);
    if (!tree) { diagnostic(root,s,errors,"missing validated compact source"); return false; }
    for (uint32_t child=tree->nodes[tree->root].first;child!=UINT32_MAX;child=tree->nodes[child].next) {
      if (a->decl_count==UINT32_MAX) { diagnostic(root,s,errors,"too many declarations"); return false; }
      ++a->decl_count;
    }
  }
  if (!compact_prepare_bodies(a,s)) {
    a->decl_count=0;
    if (a->allocation_failed) diagnostic(root,s,errors,"out of memory");
    return false;
  }
  a->decl_count=0;
  return lower_declarations(root,s,a,errors,owner_key);
}

#undef diagnostic
