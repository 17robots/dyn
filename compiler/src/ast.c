#include "dyn_ast.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "dyn_syntax.h"

static DynSpan span(TSNode n) {
  return (DynSpan){ts_node_start_byte(n), ts_node_end_byte(n)};
}
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
bool dyn_type_is_distinct(DynType t) { return t >= DYN_TYPE_DISTINCT_BASE; }
static void diagnostic_node(TSNode n, const DynSource *s, unsigned *errors,
                            const char *message) {
  dyn_syntax_diagnostic(n, s, "error", message);
  ++*errors;
}
static void diagnostic_span(DynSpan p, const DynSource *s, unsigned *errors,
                            const char *message) {
  dyn_diagnostic_source("error", s, p.start_byte, p.end_byte, message);
  ++*errors;
}
#define diagnostic(n, s, e, m)                                                 \
  _Generic((n), TSNode: diagnostic_node, DynSpan: diagnostic_span)((n), (s),   \
                                                                   (e), (m))
static TSNode unwrap(TSNode n) {
  for (;;) {
    const char *kind = ts_node_type(n);
    if (strcmp(kind, "expression") && strcmp(kind, "primary") &&
        strcmp(kind, "literal") && strcmp(kind, "group"))
      return n;
    if (ts_node_named_child_count(n) == 1) {
      TSNode child = ts_node_named_child(n, 0);
      if (ts_node_is_extra(child)) return n;
      n = child;
    } else {
      if (dyn_syntax_child_count(n) != 1) return n;
      n = dyn_syntax_child(n, 0);
    }
  }
}
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
static const char *anonymous_operator(TSNode n) {
  for (uint32_t i = 0; i < ts_node_child_count(n); ++i) {
    TSNode c = ts_node_child(n, i);
    if (!ts_node_is_named(c)) {
      return ts_node_type(c);
    }
  }
  return "";
}
static DynType parse_type(TSNode, const DynSource *, DynAstProgram *);
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
  x->target = parse_type(x->type_node, s, a);
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
static uint64_t parse_uint(TSNode n, const DynSource *s, bool *ok) {
  uint32_t i = ts_node_start_byte(n), e = ts_node_end_byte(n);
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
static bool parse_char(TSNode n, const DynSource *s, uint64_t *value) {
  uint32_t i = ts_node_start_byte(n) + 1, e = ts_node_end_byte(n) - 1;
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
static uint32_t parse_string(TSNode n, const DynSource *s, DynAstProgram *a,
                             unsigned *errors) {
  uint32_t begin = ts_node_start_byte(n) + 1, end = ts_node_end_byte(n) - 1;
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
static DynExprId lower_expr(TSNode node, const DynSource *s, DynAstProgram *a,
                            unsigned *errors) {
  if (!dyn_work_step(&s->context, 1)) return DYN_NO_EXPR;
  node = unwrap(node);
  if (!reserve_expr(a)) {
    diagnostic(node, s, errors, "out of memory");
    return DYN_NO_EXPR;
  }
  DynAstExpr e = {0};
  e.span = span(node);
  e.left = e.right = DYN_NO_EXPR;
  const char *k = ts_node_type(node);
  if (!strcmp(k, "number_")) {
    bool fl = false;
    for (uint32_t i = e.span.start_byte; i < e.span.end_byte; ++i)
      if (s->text[i] == '.' || s->text[i] == 'e' || s->text[i] == 'E') {
        fl = true;
      }
    if (fl) {
      e.kind = DYN_EXPR_FLOAT;
      e.type = DYN_TYPE_F32;
      char buf[128];
      size_t out = 0;
      for (uint32_t i = e.span.start_byte;
           i < e.span.end_byte && out + 1 < sizeof(buf); ++i)
        if (s->text[i] != '_') {
          buf[out++] = s->text[i];
        }
      buf[out] = 0;
      e.floating = strtod(buf, NULL);
    } else {
      bool ok;
      e.kind = DYN_EXPR_INT;
      e.type = DYN_TYPE_I32;
      e.integer = parse_uint(node, s, &ok);
      if (!ok) {
        diagnostic(node, s, errors, "integer literal exceeds u64");
      }
    }
  } else if (!strcmp(k, "bool_")) {
    e.kind = DYN_EXPR_BOOL;
    e.type = DYN_TYPE_BOOL;
    e.boolean = s->text[e.span.start_byte] == 't';
  } else if (!strcmp(k, "char_")) {
    e.kind = DYN_EXPR_CHAR;
    if (!parse_char(node, s, &e.integer)) {
      diagnostic(node, s, errors, "invalid Unicode scalar literal");
      return DYN_NO_EXPR;
    }
    e.type = e.integer <= 255 ? DYN_TYPE_U8 : DYN_TYPE_U32;
  } else if (!strcmp(k, "string_")) {
    e.kind = DYN_EXPR_STRING;
    e.type = DYN_TYPE_STRING;
    e.integer = parse_string(node, s, a, errors);
  } else if (!strcmp(k, "null_")) {
    e.kind = DYN_EXPR_NIL;
    e.type = DYN_TYPE_INFER;
  } else if (!strcmp(k, "identifier")) {
    e.kind = DYN_EXPR_NAME;
    e.type = DYN_TYPE_INFER;
  } else if (!strcmp(k, "field_access")) {
    e.kind = DYN_EXPR_FIELD;
    e.type = DYN_TYPE_INFER;
    e.left = lower_expr(dyn_syntax_child(node, 0), s, a, errors);
    e.span = span(dyn_syntax_child(node, 1));
  } else if (!strcmp(k, "call")) {
    TSNode callee = unwrap(dyn_syntax_child(node, 0));
    if (!strcmp(ts_node_type(callee), "field_access")) {
      e.kind = DYN_EXPR_ENUM;
      e.type = DYN_TYPE_INFER;
      e.boolean = true;
      e.left = lower_expr(dyn_syntax_child(callee, 0), s, a, errors);
      e.right = lower_expr(callee, s, a, errors);
      e.span = span(dyn_syntax_child(callee, 1));
    } else if (!strcmp(ts_node_type(callee), "identifier")) {
      e.kind = DYN_EXPR_CALL;
      e.type = DYN_TYPE_INFER;
      e.span = span(callee);
    } else {
      e.kind = DYN_EXPR_INDIRECT_CALL;
      e.type = DYN_TYPE_INFER;
      e.left = lower_expr(callee, s, a, errors);
      e.span = span(callee);
    }
    e.item_start = (uint32_t)a->item_count;
    uint32_t operand_count = dyn_syntax_child_count(node);
    uint32_t argument_count = operand_count ? operand_count - 1 : 0;
    if (!reserve_items(a, argument_count)) {
      diagnostic(node, s, errors, "out of memory");
      return DYN_NO_EXPR;
    }
    a->item_count += argument_count;
    e.item_count = argument_count;
    uint32_t argument_index = 0;
    bool seen_callee = false;
    for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i) {
      TSNode arg = ts_node_named_child(node, i);
      if (ts_node_is_extra(arg))
        continue;
      if (!seen_callee) {
        seen_callee = true;
        continue;
      }
      DynExprId expression = lower_expr(arg, s, a, errors);
      a->items[e.item_start + argument_index++] =
          (DynAstItem){.expression = expression, .field_index = UINT32_MAX};
    }
  } else if (!strcmp(k, "struct_literal")) {
    e.kind = DYN_EXPR_STRUCT;
    e.type = DYN_TYPE_INFER;
    uint32_t first = 0, count = ts_node_named_child_count(node);
    while (
        first < count &&
        !strcmp(ts_node_type(ts_node_named_child(node, first)), "identifier"))
      ++first;
    if (first) {
      TSNode begin = dyn_syntax_child(node, 0),
             end = ts_node_named_child(node, first - 1);
      e.span = (DynSpan){ts_node_start_byte(begin), ts_node_end_byte(end)};
    } else {
      e.span = span(node);
      e.boolean = true;
    }
    e.item_start = (uint32_t)a->item_count;
    for (uint32_t i = first; i < count; ++i) {
      TSNode m = ts_node_named_child(node, i);
      if (strcmp(ts_node_type(m), "struct_literal_member"))
        continue;
      if (!reserve_item(a)) {
        diagnostic(m, s, errors, "out of memory");
        return DYN_NO_EXPR;
      }
      a->items[a->item_count++] = (DynAstItem){.field_index = UINT32_MAX};
      ++e.item_count;
    }
    uint32_t member_index = 0;
    for (uint32_t i = first; i < count; ++i) {
      TSNode m = ts_node_named_child(node, i);
      if (strcmp(ts_node_type(m), "struct_literal_member")) {
        continue;
      }
      DynSpan name = span(dyn_syntax_child(m, 0));
      DynExprId expression = lower_expr(dyn_syntax_child(m, 1), s, a, errors);
      DynAstItem *item = &a->items[e.item_start + member_index++];
      item->name = name;
      item->expression = expression;
    }
  } else if (!strcmp(k, "array_literal")) {
    e.kind = DYN_EXPR_ARRAY;
    e.type = DYN_TYPE_INFER;
    e.item_start = (uint32_t)a->item_count;
    /* Walk wide array nodes with a cursor. Indexed child lookups repeatedly
       descend Tree-sitter's internal sequence tree for large literal tables. */
    TSTreeCursor cursor = ts_tree_cursor_new(node);
    if (ts_tree_cursor_goto_first_child(&cursor)) do {
      TSNode child = ts_tree_cursor_current_node(&cursor);
      if (ts_node_is_named(child) && !ts_node_is_extra(child)) ++e.item_count;
    } while (ts_tree_cursor_goto_next_sibling(&cursor));
    if (!reserve_items(a, e.item_count)) {
      ts_tree_cursor_delete(&cursor);
      diagnostic(node, s, errors, "out of memory");
      return DYN_NO_EXPR;
    }
    a->item_count += e.item_count;
    uint32_t item_index = 0;
    ts_tree_cursor_reset(&cursor, node);
    if (ts_tree_cursor_goto_first_child(&cursor)) do {
      TSNode child = ts_tree_cursor_current_node(&cursor);
      if (!ts_node_is_named(child) || ts_node_is_extra(child)) continue;
      DynExprId expression = lower_expr(child, s, a, errors);
      a->items[e.item_start + item_index++] =
          (DynAstItem){.expression = expression, .field_index = UINT32_MAX};
    } while (ts_tree_cursor_goto_next_sibling(&cursor));
    ts_tree_cursor_delete(&cursor);
  } else if (!strcmp(k, "index")) {
    uint32_t count = dyn_syntax_child_count(node);
    e.left = lower_expr(dyn_syntax_child(node, 0), s, a, errors);
    bool range = false;
    uint32_t dots = 0;
    for (uint32_t i = 0; i < ts_node_child_count(node); ++i) {
      TSNode child = ts_node_child(node, i);
      if (!strcmp(ts_node_type(child), "..")) {
        range = true;
        dots = ts_node_start_byte(child);
        break;
      }
    }
    if (!range) {
      e.kind = DYN_EXPR_INDEX;
      e.right = lower_expr(dyn_syntax_child(node, 1), s, a, errors);
    } else {
      e.kind = DYN_EXPR_SLICE;
      e.right = DYN_NO_EXPR;
      e.integer = DYN_NO_EXPR;
      if (count > 1) {
        TSNode first = dyn_syntax_child(node, 1);
        if (ts_node_end_byte(first) <= dots) {
          e.right = lower_expr(first, s, a, errors);
        } else {
          e.integer = lower_expr(first, s, a, errors);
        }
      }
      if (count > 2) {
        e.integer = lower_expr(dyn_syntax_child(node, 2), s, a, errors);
      }
    }
  } else if (!strcmp(k, "len")) {
    e.kind = DYN_EXPR_LEN;
    e.left = lower_expr(dyn_syntax_child(node, 0), s, a, errors);
  } else if (!strcmp(k, "size") || !strcmp(k, "align") ||
             !strcmp(k, "typeof")) {
    e.kind = !strcmp(k, "size")    ? DYN_EXPR_SIZE
             : !strcmp(k, "align") ? DYN_EXPR_ALIGN
                                   : DYN_EXPR_TYPEOF;
    TSNode operand = dyn_syntax_child(node, 0);
    if (!strcmp(ts_node_type(operand), "type")) {
      DynType parsed = parse_type(operand, s, a);
      if (parsed != DYN_TYPE_ERROR) {
        e.boolean = true;
        e.integer = parsed;
      } else {
        while (dyn_syntax_child_count(operand) == 1)
          operand = dyn_syntax_child(operand, 0);
        e.left = lower_expr(operand, s, a, errors);
      }
    } else
      e.left = lower_expr(operand, s, a, errors);
  } else if (!strcmp(k, "cast")) {
    e.kind = s->text[e.span.start_byte + 1] == 'b' ? DYN_EXPR_BITCAST
                                                   : DYN_EXPR_CAST;
    e.integer = parse_type(dyn_syntax_child(node, 0), s, a);
    e.left = lower_expr(dyn_syntax_child(node, 1), s, a, errors);
  } else if (!strcmp(k, "syscall")) {
    e.kind = DYN_EXPR_SYSCALL;
    e.type = DYN_TYPE_INFER;
    e.item_start = (uint32_t)a->item_count;
    e.item_count = dyn_syntax_child_count(node);
    if (!reserve_items(a, e.item_count)) {
      diagnostic(node, s, errors, "out of memory");
      return DYN_NO_EXPR;
    }
    a->item_count += e.item_count;
    uint32_t item_index = 0;
    for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i) {
      TSNode arg = ts_node_named_child(node, i);
      if (ts_node_is_extra(arg))
        continue;
      DynExprId expression = lower_expr(arg, s, a, errors);
      a->items[e.item_start + item_index++] =
          (DynAstItem){.expression = expression, .field_index = UINT32_MAX};
    }
  } else if (!strcmp(k, "unary_prefix")) {
    e.kind = DYN_EXPR_UNARY;
    e.op = op_from(anonymous_operator(node));
    if (!strcmp(anonymous_operator(node), "&")) {
      e.op = DYN_OP_ADDRESS;
    }
    if (e.op == DYN_OP_SUB) {
      e.op = DYN_OP_NEG;
    }
    e.left = lower_expr(dyn_syntax_child(node, 0), s, a, errors);
  } else if (!strcmp(k, "unary_postfix")) {
    e.kind = DYN_EXPR_UNARY;
    e.op = DYN_OP_DEREF;
    e.left = lower_expr(dyn_syntax_child(node, 0), s, a, errors);
  } else if (!strcmp(k, "binary")) {
    e.kind = DYN_EXPR_BINARY;
    e.op = op_from(anonymous_operator(node));
    e.left = lower_expr(dyn_syntax_child(node, 0), s, a, errors);
    e.right = lower_expr(dyn_syntax_child(node, 1), s, a, errors);
  } else {
    diagnostic(node, s, errors,
               "expression is not implemented in bootstrap compiler");
    return DYN_NO_EXPR;
  }
  if (!reserve_expr(a)) {
    diagnostic(node, s, errors, "out of memory");
    return DYN_NO_EXPR;
  }
  DynExprId id = (DynExprId)a->expression_count;
  a->expressions[a->expression_count++] = e;
  return id;
}
static DynType parse_type(TSNode n, const DynSource *s, DynAstProgram *a) {
  n = unwrap(n);
  if (!strcmp(ts_node_type(n), "type") && dyn_syntax_child_count(n) == 1) {
    n = dyn_syntax_child(n, 0);
  }
  if (!strcmp(ts_node_type(n), "fn_type")) {
    uint32_t close = ts_node_start_byte(n);
    for (uint32_t i = 0; i < ts_node_child_count(n); ++i) {
      TSNode child = ts_node_child(n, i);
      if (!strcmp(ts_node_type(child), ")"))
        close = ts_node_start_byte(child);
    }
    uint32_t named = ts_node_named_child_count(n), count = 0;
    DynType *params = calloc(named, sizeof(*params));
    if (named && !params)
      return DYN_TYPE_ERROR;
    DynType result = DYN_TYPE_VOID;
    for (uint32_t i = 0; i < named; ++i) {
      TSNode c = ts_node_named_child(n, i);
      if (ts_node_is_extra(c))
        continue;
      DynType t = parse_type(c, s, a);
      if (t == DYN_TYPE_ERROR) {
        free(params);
        return DYN_TYPE_ERROR;
      }
      if (ts_node_start_byte(c) > close) {
        result = t;
      } else {
        params[count++] = t;
      }
    }
    DynType type = intern_fn_type(a, params, count, result);
    free(params);
    return type;
  }
  if (!strcmp(ts_node_type(n), "pointer_type")) {
    TSNode child = dyn_syntax_child(n, 0);
    bool is_const = dyn_syntax_has_token(n, "const");
    DynType pointee = parse_type(child, s, a);
    return pointee == DYN_TYPE_ERROR ? DYN_TYPE_ERROR
                                     : intern_pointer(a, pointee, is_const);
  }
  if (!strcmp(ts_node_type(n), "array_type")) {
    TSNode last = dyn_syntax_last_child(n);
    DynType element = parse_type(last, s, a);
    if (element == DYN_TYPE_ERROR)
      return DYN_TYPE_ERROR;
    TSNode first = dyn_syntax_child(n, 0);
    if (!strcmp(ts_node_type(first), "number_")) {
      bool ok;
      uint64_t length = parse_uint(first, s, &ok);
      return ok ? intern_array(a, element, length) : DYN_TYPE_ERROR;
    }
    bool is_const = dyn_syntax_has_token(n, "const");
    return intern_slice(a, element, is_const);
  }
  DynSpan p = span(n);
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
  uint32_t alias = find_alias(a, p, s);
  if (alias != UINT32_MAX) {
    return resolve_alias(a, alias, s);
  }
  uint32_t id = find_struct(a, p, s);
  return id == UINT32_MAX ? DYN_TYPE_ERROR : DYN_TYPE_STRUCT_BASE + id;
}
static bool lower_block(TSNode, const DynSource *, DynAstProgram *, unsigned *,
                        uint32_t, uint32_t *, uint32_t *);

static bool pointer_case_pattern(TSNode pattern, DynAstCaseArm *arm,
                                 TSNode *value) {
  TSNode p = unwrap(dyn_syntax_child(pattern, 0));
  if (strcmp(ts_node_type(p), "binary") || strcmp(anonymous_operator(p), "*")) {
    return false;
  }
  TSNode right = unwrap(dyn_syntax_child(p, 1));
  if (strcmp(ts_node_type(right), "identifier")) {
    return false;
  }
  arm->binding = span(right);
  arm->pointer_binding = true;
  *value = unwrap(dyn_syntax_child(p, 0));
  return true;
}
static void lower_case_stmt(TSNode n, const DynSource *s, DynAstProgram *a,
                            unsigned *errors, uint32_t loop_depth,
                            DynAstStmt *st) {
  st->kind = DYN_STMT_CASE;
  st->expression = lower_expr(dyn_syntax_child(n, 0), s, a, errors);
  st->case_arm_start = (uint32_t)a->case_arm_count;
  uint32_t count = 0;
  for (uint32_t i = 1; i < ts_node_named_child_count(n); ++i)
    if (!strcmp(ts_node_type(ts_node_named_child(n, i)), "case_arm")) {
      ++count;
    }
  if (!count)
    return;
  TSNode *blocks = calloc(count, sizeof(*blocks));
  if (!blocks) {
    diagnostic(n, s, errors, "out of memory");
    return;
  }
  uint32_t arm_index = 0;
  for (uint32_t i = 1; i < ts_node_named_child_count(n); ++i) {
    TSNode an = ts_node_named_child(n, i);
    if (strcmp(ts_node_type(an), "case_arm")) {
      continue;
    }
    if (!reserve_case_arm(a)) {
      diagnostic(an, s, errors, "out of memory");
      break;
    }
    DynAstCaseArm arm = {.span = span(an),
                         .pattern_start = (uint32_t)a->pattern_count,
                         .local_id = UINT32_MAX};
    uint32_t pos = ts_node_start_byte(an);
    while (pos < ts_node_end_byte(an) && isspace((unsigned char)s->text[pos]))
      ++pos;
    arm.wildcard = s->text[pos] == '_';
    for (uint32_t j = 0; j < ts_node_named_child_count(an); ++j) {
      TSNode c = ts_node_named_child(an, j);
      if (!strcmp(ts_node_type(c), "case_pattern")) {
        TSNode p = {0};
        bool pointer = pointer_case_pattern(c, &arm, &p);
        if (!pointer) {
          p = unwrap(dyn_syntax_child(c, 0));
        }
        if (!reserve_pattern(a)) {
          diagnostic(p, s, errors, "out of memory");
          continue;
        }
        DynAstPattern pat = {
            .span = span(p), .first = DYN_NO_EXPR, .last = DYN_NO_EXPR};
        if (!strcmp(ts_node_type(p), "range")) {
          pat.range = true;
          pat.first = lower_expr(dyn_syntax_child(p, 0), s, a, errors);
          pat.last = lower_expr(dyn_syntax_child(p, 1), s, a, errors);
          for (uint32_t q = ts_node_start_byte(p); q < ts_node_end_byte(p); ++q)
            if (s->text[q] == '=') {
              pat.inclusive = true;
            }
        } else
          pat.first = lower_expr(p, s, a, errors);
        a->patterns[a->pattern_count++] = pat;
        ++arm.pattern_count;
      } else if (!strcmp(ts_node_type(c), "type_pattern")) {
        if (!reserve_pattern(a)) {
          diagnostic(c, s, errors, "out of memory");
          continue;
        }
        TSNode tn = {0};
        for (uint32_t q = 0; q < ts_node_named_child_count(c); ++q) {
          TSNode x = ts_node_named_child(c, q);
          if (!strcmp(ts_node_type(x), "type"))
            tn = x;
          else if (!strcmp(ts_node_type(x), "identifier"))
            arm.binding = span(x);
        }
        a->patterns[a->pattern_count++] =
            (DynAstPattern){.span = span(c),
                            .first = DYN_NO_EXPR,
                            .last = DYN_NO_EXPR,
                            .type = parse_type(tn, s, a),
                            .is_type = true};
        arm.pattern_count = 1;
      } else if (!strcmp(ts_node_type(c), "identifier")) {
        arm.binding = span(c);
      } else if (!strcmp(ts_node_type(c), "block")) {
        blocks[arm_index] = c;
      }
    }
    a->case_arms[a->case_arm_count++] = arm;
    ++arm_index;
  }
  st->case_arm_count = arm_index;
  for (uint32_t i = 0; i < arm_index; ++i)
    if (!ts_node_is_null(blocks[i])) {
      lower_block(blocks[i], s, a, errors, loop_depth,
                  &a->case_arms[st->case_arm_start + i].body_start,
                  &a->case_arms[st->case_arm_start + i].body_count);
    }
  free(blocks);
}
static uint32_t lower_stmt(TSNode n, const DynSource *s, DynAstProgram *a,
                           unsigned *errors, uint32_t loop_depth) {
  if (!strcmp(ts_node_type(n), "statement")) {
    n = dyn_syntax_child(n, 0);
  }
  if (!reserve_stmt(a)) {
    diagnostic(n, s, errors, "out of memory");
    return UINT32_MAX;
  }
  uint32_t id = (uint32_t)a->statement_count++;
  DynAstStmt st = {0};
  st.span = span(n);
  st.expression = st.target = DYN_NO_EXPR;
  st.local_id = UINT32_MAX;
  st.loop_depth = loop_depth;
  const char *k = ts_node_type(n);
  if (!strcmp(k, "const_variable")) {
    st.is_const = true;
    n = dyn_syntax_child(n, 0);
    k = ts_node_type(n);
    st.span = span(n);
  }
  st.target_loop_id = UINT32_MAX;
  if (!strcmp(k, "return_")) {
    st.kind = DYN_STMT_RETURN;
    if (dyn_syntax_child_count(n)) {
      st.expression = lower_expr(dyn_syntax_child(n, 0), s, a, errors);
    }
  } else if (!strcmp(k, "variable")) {
    st.kind = DYN_STMT_LOCAL;
    st.name = span(dyn_syntax_child(n, 0));
    st.declared_type = DYN_TYPE_INFER;
    for (uint32_t j = 1; j < ts_node_named_child_count(n); ++j) {
      TSNode c = ts_node_named_child(n, j);
      if (ts_node_is_extra(c))
        continue;
      if (!strcmp(ts_node_type(c), "type_qualifier")) {
        st.declared_type = parse_type(dyn_syntax_child(c, 0), s, a);
      } else if (!strcmp(ts_node_type(c), "type")) {
        st.declared_type = parse_type(c, s, a);
      } else {
        st.expression = lower_expr(c, s, a, errors);
      }
    }
    if (st.declared_type == DYN_TYPE_ERROR)
      diagnostic(n, s, errors, "unknown or invalid local type");
    if (st.is_const && st.expression == DYN_NO_EXPR)
      diagnostic(n, s, errors, "local constant requires initializer");
  } else if (!strcmp(k, "assignment")) {
    st.kind = DYN_STMT_ASSIGN;
    TSNode target = unwrap(dyn_syntax_child(n, 0));
    if (!strcmp(ts_node_type(target), "identifier"))
      st.name = span(target);
    else if (!strcmp(ts_node_type(target), "field_access") ||
             !strcmp(ts_node_type(target), "unary_postfix") ||
             !strcmp(ts_node_type(target), "index"))
      st.target = lower_expr(target, s, a, errors);
    else {
      diagnostic(
          target, s, errors,
          "assignment target must be local, field, dereference, or index");
      return id;
    }
    st.expression = lower_expr(dyn_syntax_last_child(n), s, a, errors);
    st.assignment_op = op_from(anonymous_operator(n));
  } else if (!strcmp(k, "if_")) {
    st.kind = DYN_STMT_IF;
    st.expression = lower_expr(dyn_syntax_child(n, 0), s, a, errors);
    TSNode b = dyn_syntax_child(n, 1);
    lower_block(b, s, a, errors, loop_depth, &st.body_start, &st.body_count);
    if (dyn_syntax_child_count(n) > 2) {
      TSNode e = dyn_syntax_child(n, 2), branch = dyn_syntax_child(e, 0);
      if (!strcmp(ts_node_type(branch), "block"))
        lower_block(branch, s, a, errors, loop_depth, &st.else_start,
                    &st.else_count);
      else {
        uint32_t nested = lower_stmt(branch, s, a, errors, loop_depth);
        st.else_start = (uint32_t)a->child_count;
        if (reserve_child(a))
          a->children[a->child_count++] = nested;
        st.else_count = 1;
      }
    }
  } else if (!strcmp(k, "case_")) {
    lower_case_stmt(n, s, a, errors, loop_depth, &st);
  } else if (!strcmp(k, "for_")) {
    st.kind = DYN_STMT_FOR;
    st.loop_id = a->loop_count++;
    uint32_t count = ts_node_named_child_count(n);
    TSNode last = dyn_syntax_last_child(n);
    for (uint32_t z = 0; z + 1 < count; ++z) {
      TSNode c = ts_node_named_child(n, z);
      if (!strcmp(ts_node_type(c), "identifier")) {
        st.label = span(c);
        continue;
      }
      if (!strcmp(ts_node_type(c), "for_condition")) {
        uint32_t cc = dyn_syntax_child_count(c);
        if (cc == 1)
          st.expression = lower_expr(dyn_syntax_child(c, 0), s, a, errors);
        else {
          TSNode binder = dyn_syntax_child(c, 0);
          st.for_pointer = dyn_syntax_has_token(c, "*");
          st.for_const = dyn_syntax_has_token(c, "const");
          st.name = span(binder);
          st.target = lower_expr(dyn_syntax_last_child(c), s, a, errors);
        }
      }
    }
    lower_block(last, s, a, errors, loop_depth + 1, &st.body_start,
                &st.body_count);
  } else if (!strcmp(k, "break_")) {
    st.kind = DYN_STMT_BREAK;
    if (dyn_syntax_child_count(n))
      st.control_label = span(dyn_syntax_child(n, 0));
  } else if (!strcmp(k, "continue_")) {
    st.kind = DYN_STMT_CONTINUE;
    if (dyn_syntax_child_count(n))
      st.control_label = span(dyn_syntax_child(n, 0));
  } else if (!strcmp(k, "defer")) {
    st.kind = DYN_STMT_DEFER;
    TSNode action = dyn_syntax_child(n, 0);
    if (!strcmp(ts_node_type(action), "block")) {
      st.defer_block = true;
      lower_block(action, s, a, errors, loop_depth, &st.body_start,
                  &st.body_count);
    } else {
      uint32_t deferred = lower_stmt(action, s, a, errors, loop_depth);
      st.body_start = (uint32_t)a->child_count;
      if (reserve_child(a))
        a->children[a->child_count++] = deferred;
      st.body_count = 1;
    }
  } else if (!strcmp(k, "panic")) {
    st.kind = DYN_STMT_PANIC;
    if (dyn_syntax_child_count(n))
      st.expression = lower_expr(dyn_syntax_child(n, 0), s, a, errors);
  } else if (!strcmp(k, "syscall")) {
    st.kind = DYN_STMT_EXPR;
    st.expression = lower_expr(n, s, a, errors);
  } else if (!strcmp(k, "call")) {
    st.kind = DYN_STMT_EXPR;
    st.expression = lower_expr(n, s, a, errors);
  } else if (!strcmp(k, "type_alias")) {
    diagnostic(n, s, errors, "local type aliases are not supported; declare the alias at module scope");
  } else {
    diagnostic(
        n, s, errors,
        "unsupported statement");
  }
  a->statements[id] = st;
  return id;
}
static bool lower_block(TSNode block, const DynSource *s, DynAstProgram *a,
                        unsigned *errors, uint32_t loop_depth, uint32_t *start,
                        uint32_t *count) {
  *count = 0;
  if (ts_node_is_null(block)) {
    *start = (uint32_t)a->child_count;
    return true;
  }
  uint32_t n = ts_node_named_child_count(block);
  uint32_t *ids = malloc(n * sizeof(*ids));
  if (n && !ids) {
    a->allocation_failed = true;
    diagnostic(block, s, errors, "out of memory");
    return false;
  }
  TSTreeCursor cursor = ts_tree_cursor_new(block);
  if (ts_tree_cursor_goto_first_child(&cursor)) do {
    TSNode c = ts_tree_cursor_current_node(&cursor);
    if (!ts_node_is_named(c) || !strcmp(ts_node_type(c), "comment"))
      continue;
    uint32_t id = lower_stmt(c, s, a, errors, loop_depth);
    if (id == UINT32_MAX) {
      ts_tree_cursor_delete(&cursor);
      free(ids);
      *count = 0;
      return false;
    }
    ids[(*count)++] = id;
  } while (ts_tree_cursor_goto_next_sibling(&cursor));
  ts_tree_cursor_delete(&cursor);
  *start = (uint32_t)a->child_count;
  for (uint32_t i = 0; i < *count; ++i) {
    if (!reserve_child(a)) {
      free(ids);
      *count = 0;
      diagnostic(block, s, errors, "out of memory");
      return false;
    }
    a->children[a->child_count++] = ids[i];
  }
  free(ids);
  return true;
}
bool dyn_ast_lower_main(TSNode fn, const DynSource *s, DynAstProgram *a,
                        unsigned *errors) {
  a->span = span(fn);
  TSNode name = ts_node_child_by_field_name(fn, "name", 4);
  a->name = span(name);
  TSNode block = {0};
  for (uint32_t i = 0; i < ts_node_named_child_count(fn); ++i) {
    TSNode c = ts_node_named_child(fn, i);
    if (!strcmp(ts_node_type(c), "fn_param"))
      ++a->parameter_count;
    else if (!strcmp(ts_node_type(c), "block"))
      block = c;
    else if (strcmp(ts_node_type(c), "identifier") &&
             strcmp(ts_node_type(c), "comment"))
      a->has_return_type = true;
  }
  if (!ts_node_is_null(block))
    lower_block(block, s, a, errors, 0, &a->body_start, &a->body_count);
  return *errors == 0;
}
void dyn_ast_program_free(DynAstProgram *a) {
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
  memset(a, 0, sizeof(*a));
}
extern const TSLanguage *tree_sitter_dyn(void);
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
static bool add_enum_names(TSNode root, const DynSource *s, DynAstProgram *a,
                           unsigned *errors) {
  for (uint32_t i = 0; i < ts_node_named_child_count(root) && dyn_work_step(&s->context, 1); ++i) {
    TSNode wrapper = ts_node_named_child(root, i);
    bool is_public = dyn_syntax_public(wrapper);
    TSNode d = dyn_syntax_declaration_node(wrapper);
    if (strcmp(ts_node_type(d), "enum"))
      continue;
    TSNode name = {0};
    for (uint32_t j = 0; j < ts_node_named_child_count(d); ++j) {
      TSNode c = ts_node_named_child(d, j);
      if (!strcmp(ts_node_type(c), "identifier")) {
        name = c;
        break;
      }
    }
    DynSpan ns = span(name);
    if (find_enum(a, ns, s) != UINT32_MAX) {
      diagnostic(name, s, errors, "duplicate enum declaration");
      continue;
    }
    if (!reserve_enum(a)) {
      diagnostic(d, s, errors, "out of memory");
      return false;
    }
    a->enums[a->enum_count++] =
        (DynAstEnum){.span = span(d),
                     .name = ns,
                     .tag_type = DYN_TYPE_U32,
                     .alignment = 1,
                     .is_public = is_public,
                     .module_owner = declaration_owner(ns, s)};
  }
  return true;
}
static bool add_struct_names(TSNode root, const DynSource *s, DynAstProgram *a,
                             unsigned *errors) {
  for (uint32_t i = 0; i < ts_node_named_child_count(root) && dyn_work_step(&s->context, 1); ++i) {
    TSNode wrapper = ts_node_named_child(root, i);
    bool is_public = dyn_syntax_public(wrapper);
    TSNode d = dyn_syntax_declaration_node(wrapper);
    if (strcmp(ts_node_type(d), "struct"))
      continue;
    TSNode name = dyn_syntax_child(d, 0);
    DynSpan ns = span(name);
    if (find_struct(a, ns, s) != UINT32_MAX) {
      diagnostic(name, s, errors, "duplicate struct declaration");
      continue;
    }
    if (!reserve_struct(a)) {
      diagnostic(d, s, errors, "out of memory");
      return false;
    }
    bool packed = dyn_syntax_has_token(d, "packed");
    a->structs[a->struct_count++] =
        (DynAstStruct){.span = span(d),
                       .name = ns,
                       .packed = packed,
                       .alignment = 0,
                       .is_public = is_public,
                       .module_owner = declaration_owner(ns, s)};
  }
  return true;
}
static bool add_alias_names(TSNode root, const DynSource *s, DynAstProgram *a,
                            unsigned *errors) {
  for (uint32_t i = 0; i < ts_node_named_child_count(root) && dyn_work_step(&s->context, 1); ++i) {
    TSNode wrapper = ts_node_named_child(root, i);
    bool is_public = dyn_syntax_public(wrapper);
    TSNode d = dyn_syntax_declaration_node(wrapper);
    if (strcmp(ts_node_type(d), "type_alias"))
      continue;
    TSNode name = dyn_syntax_child(d, 0), type = dyn_syntax_child(d, 1);
    DynSpan ns = span(name);
    if (find_alias(a, ns, s) != UINT32_MAX ||
        find_struct(a, ns, s) != UINT32_MAX) {
      diagnostic(name, s, errors, "duplicate type declaration");
      continue;
    }
    if (!reserve_alias(a)) {
      diagnostic(d, s, errors, "out of memory");
      return false;
    }
    bool distinct = dyn_syntax_has_token(d, "distinct");
    a->aliases[a->alias_count++] =
        (DynAstAlias){.name = ns,
                      .target = DYN_TYPE_ERROR,
                      .type_node = type,
                      .distinct = distinct,
                      .is_public = is_public,
                      .module_owner = declaration_owner(ns, s)};
  }
  for (uint32_t i = 0; i < a->alias_count; ++i)
    if (resolve_alias(a, i, s) == DYN_TYPE_ERROR)
      diagnostic(a->aliases[i].name, s, errors, "invalid or cyclic type alias");
  return true;
}
static bool add_struct_fields(TSNode root, const DynSource *s, DynAstProgram *a,
                              unsigned *errors) {
  uint32_t si = 0;
  for (uint32_t i = 0; i < ts_node_named_child_count(root) && dyn_work_step(&s->context, 1); ++i) {
    TSNode d = dyn_syntax_declaration_node(ts_node_named_child(root, i));
    if (strcmp(ts_node_type(d), "struct"))
      continue;
    if (si >= a->struct_count)
      break;
    DynAstStruct *st = &a->structs[si++];
    st->field_start = (uint32_t)a->field_count;
    for (uint32_t j = 1; j < ts_node_named_child_count(d); ++j) {
      TSNode m = ts_node_named_child(d, j);
      if (strcmp(ts_node_type(m), "struct_member"))
        continue;
      TSNode tq = {0}, init = {0};
      for (uint32_t k = 0; k < ts_node_named_child_count(m); ++k) {
        TSNode c = ts_node_named_child(m, k);
        if (!strcmp(ts_node_type(c), "type_qualifier"))
          tq = c;
        else if (!strcmp(ts_node_type(c), "expression"))
          init = c;
      }
      DynType type = ts_node_is_null(tq)
                         ? DYN_TYPE_ERROR
                         : parse_type(dyn_syntax_child(tq, 0), s, a);
      if (type == DYN_TYPE_ERROR)
        diagnostic(tq, s, errors, "unknown or unsupported struct field type");
      for (uint32_t k = 0; k < ts_node_named_child_count(m); ++k) {
        TSNode c = ts_node_named_child(m, k);
        if (strcmp(ts_node_type(c), "identifier"))
          continue;
        DynSpan name = span(c);
        bool duplicate = false;
        for (uint32_t q = 0; q < st->field_count; ++q)
          if (dyn_span_text_equal(name, a->fields[st->field_start + q].name, s))
            duplicate = true;
        if (duplicate) {
          diagnostic(c, s, errors, "duplicate struct field");
          continue;
        }
        if (!reserve_field(a)) {
          diagnostic(c, s, errors, "out of memory");
          return false;
        }
        DynExprId def = ts_node_is_null(init) ? DYN_NO_EXPR
                                              : lower_expr(init, s, a, errors);
        a->fields[a->field_count++] = (DynAstField){name, type, def};
        ++st->field_count;
      }
    }
  }
  return true;
}
static bool add_enum_variants(TSNode root, const DynSource *s, DynAstProgram *a,
                              unsigned *errors) {
  uint32_t ei = 0;
  for (uint32_t i = 0; i < ts_node_named_child_count(root) && dyn_work_step(&s->context, 1); ++i) {
    TSNode d = dyn_syntax_declaration_node(ts_node_named_child(root, i));
    if (strcmp(ts_node_type(d), "enum"))
      continue;
    DynAstEnum *en = &a->enums[ei++];
    en->variant_start = (uint32_t)a->variant_count;
    bool saw_name = false;
    for (uint32_t j = 0; j < ts_node_named_child_count(d); ++j) {
      TSNode c = ts_node_named_child(d, j);
      const char *k = ts_node_type(c);
      if (!saw_name && !strcmp(k, "primitive")) {
        en->tag_type = parse_type(c, s, a);
        continue;
      }
      if (!saw_name && !strcmp(k, "identifier")) {
        saw_name = true;
        continue;
      }
      if (strcmp(k, "enum_member"))
        continue;
      TSNode name = dyn_syntax_child(c, 0);
      bool duplicate = false;
      for (uint32_t q = 0; q < en->variant_count; ++q)
        if (dyn_span_text_equal(span(name),
                                a->variants[en->variant_start + q].name, s))
          duplicate = true;
      if (duplicate) {
        diagnostic(name, s, errors, "duplicate enum variant");
        continue;
      }
      DynType payload = DYN_TYPE_VOID;
      for (uint32_t q = 1; q < ts_node_named_child_count(c); ++q) {
        TSNode part = ts_node_named_child(c, q);
        if (!strcmp(ts_node_type(part), "type_qualifier"))
          payload = parse_type(dyn_syntax_child(part, 0), s, a);
        else {
          diagnostic(part, s, errors,
                     "explicit enum discriminants are not supported");
        }
      }
      if (!reserve_variant(a)) {
        diagnostic(c, s, errors, "out of memory");
        return false;
      }
      a->variants[a->variant_count++] =
          (DynAstVariant){span(name), payload, en->variant_count};
      ++en->variant_count;
      if (payload != DYN_TYPE_VOID)
        en->has_payload = true;
    }
    if (!en->variant_count)
      diagnostic(d, s, errors, "enum requires at least one variant");
    unsigned width =
        en->tag_type == DYN_TYPE_I8 || en->tag_type == DYN_TYPE_U8     ? 8
        : en->tag_type == DYN_TYPE_I16 || en->tag_type == DYN_TYPE_U16 ? 16
        : en->tag_type == DYN_TYPE_I32 || en->tag_type == DYN_TYPE_U32 ? 32
                                                                       : 64;
    if (en->tag_type < DYN_TYPE_I8 || en->tag_type > DYN_TYPE_USIZE)
      diagnostic(en->name, s, errors, "enum tag type must be integer");
    else if (width < 64 && en->variant_count > (UINT64_C(1) << width))
      diagnostic(en->name, s, errors,
                 "enum has too many variants for tag type");
  }
  return true;
}
static uint64_t type_layout(DynType t, bool alignment, DynAstProgram *a,
                            unsigned char *state, const DynSource *s,
                            unsigned *errors);
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
    DynAstEnum *en = &a->enums[t - DYN_TYPE_ENUM_BASE];
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
static bool compute_layouts_v2(DynAstProgram *a, const DynSource *s,
                               unsigned *errors) {
  unsigned char *state = calloc(a->struct_count, 1);
  if (a->struct_count && !state) {
    a->allocation_failed = true;
    return false;
  }
  for (uint32_t i = 0; i < a->enum_count; ++i) {
    DynAstEnum *en = &a->enums[i];
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
      continue;
    }
    en->size = (offset + en->payload_size + en->alignment - 1) / en->alignment *
               en->alignment;
  }
  for (uint32_t i = 0; i < a->struct_count; ++i)
    layout_struct(i, a, state, s, errors);
  free(state);
  return true;
}
static uint32_t find_function(DynAstProgram *a, DynSpan name,
                              const DynSource *s) {
  for (uint32_t i = 0; i < a->function_count; ++i)
    if (dyn_module_name_equal(name, a->functions[i].name, s))
      return i;
  return UINT32_MAX;
}
static uint32_t find_global(DynAstProgram *a, DynSpan name,
                            const DynSource *s) {
  for (uint32_t i = 0; i < a->global_count; ++i)
    if (dyn_module_name_equal(name, a->globals[i].name, s))
      return i;
  return UINT32_MAX;
}
static bool add_globals(TSNode root, const DynSource *s, DynAstProgram *a,
                        unsigned *errors) {
  for (uint32_t i = 0; i < ts_node_named_child_count(root) && dyn_work_step(&s->context, 1); ++i) {
    TSNode wrapper = ts_node_named_child(root, i);
    bool is_public = dyn_syntax_public(wrapper);
    TSNode d = dyn_syntax_declaration_node(wrapper);
    bool foreign = !strcmp(ts_node_type(d), "extern_variable");
    bool is_const = !strcmp(ts_node_type(d), "const_variable");
    TSNode v = is_const ? dyn_syntax_child(d, 0) : d;
    if (strcmp(ts_node_type(v), "variable") && !foreign)
      continue;
    TSNode name = foreign ? ts_node_child_by_field_name(v, "name", 4)
                          : dyn_syntax_child(v, 0),
           tq = {0}, init = {0};
    DynSpan ns = span(name);
    if (find_global(a, ns, s) != UINT32_MAX ||
        find_struct(a, ns, s) != UINT32_MAX) {
      diagnostic(name, s, errors, "duplicate declaration name");
      continue;
    }
    for (uint32_t j = 1; j < ts_node_named_child_count(v); ++j) {
      TSNode c = ts_node_named_child(v, j);
      if (!strcmp(ts_node_type(c), "type_qualifier") ||
          !strcmp(ts_node_type(c), "type"))
        tq = c;
      else if (!strcmp(ts_node_type(c), "expression"))
        init = c;
    }
    DynType type = ts_node_is_null(tq)
                       ? DYN_TYPE_INFER
                       : parse_type(!strcmp(ts_node_type(tq), "type_qualifier")
                                        ? dyn_syntax_child(tq, 0)
                                        : tq,
                                    s, a);
    if (type == DYN_TYPE_ERROR)
      diagnostic(tq, s, errors, "unknown type in global declaration");
    if (!reserve_global(a)) {
      diagnostic(v, s, errors, "out of memory");
      return false;
    }
    TSNode link_name =
        foreign ? ts_node_child_by_field_name(v, "link_name", 9) : (TSNode){0};
    DynSpan link = ts_node_is_null(link_name)
                       ? ns
                       : (DynSpan){ts_node_start_byte(link_name) + 1,
                                   ts_node_end_byte(link_name) - 1};
    a->globals[a->global_count++] = (DynAstGlobal){
        .name = ns,
        .link_name = link,
        .type = type,
        .initializer = ts_node_is_null(init) ? DYN_NO_EXPR
                                             : lower_expr(init, s, a, errors),
        .is_const = is_const,
        .foreign = foreign,
        .is_public = is_public,
        .module_owner = declaration_owner(ns, s)};
  }
  return true;
}
static bool add_function_signatures(TSNode root, const DynSource *s,
                                    DynAstProgram *a, unsigned *errors) {
  for (uint32_t i = 0; i < ts_node_named_child_count(root) && dyn_work_step(&s->context, 1); ++i) {
    TSNode wrapper = ts_node_named_child(root, i);
    bool is_public = dyn_syntax_public(wrapper);
    TSNode d = dyn_syntax_declaration_node(wrapper);
    bool foreign = !strcmp(ts_node_type(d), "extern_fn");
    if (strcmp(ts_node_type(d), "fn") && !foreign)
      continue;
    TSNode name = ts_node_child_by_field_name(d, "name", 4);
    DynSpan ns = span(name);
    if (find_function(a, ns, s) != UINT32_MAX ||
        find_struct(a, ns, s) != UINT32_MAX ||
        find_global(a, ns, s) != UINT32_MAX) {
      diagnostic(name, s, errors, "duplicate declaration name");
      continue;
    }
    if (!reserve_function(a)) {
      diagnostic(d, s, errors, "out of memory");
      return false;
    }
    DynAstFn fn = {.span = span(d),
                   .name = ns,
                   .return_type = DYN_TYPE_VOID,
                   .param_start = (uint32_t)a->param_count,
                   .foreign = foreign,
                   .is_public = is_public,
                   .module_owner = declaration_owner(ns, s)};
    TSNode link_name = ts_node_child_by_field_name(d, "link_name", 9);
    fn.link_name = ts_node_is_null(link_name)
                       ? ns
                       : (DynSpan){ts_node_start_byte(link_name) + 1,
                                   ts_node_end_byte(link_name) - 1};
    fn.is_main = !foreign && ns.end_byte - ns.start_byte == 4 &&
                 !memcmp(s->text + ns.start_byte, "main", 4);
    for (uint32_t j = 0; j < ts_node_named_child_count(d); ++j) {
      TSNode c = ts_node_named_child(d, j);
      if (!strcmp(ts_node_type(c), "fn_param")) {
        TSNode tq = {0};
        for (uint32_t k = 0; k < ts_node_named_child_count(c); ++k) {
          TSNode q = ts_node_named_child(c, k);
          if (!strcmp(ts_node_type(q), "type_qualifier"))
            tq = q;
        }
        DynType type = ts_node_is_null(tq)
                           ? DYN_TYPE_ERROR
                           : parse_type(dyn_syntax_child(tq, 0), s, a);
        if (type == DYN_TYPE_ERROR)
          diagnostic(ts_node_is_null(tq) ? c : tq, s, errors,
                     "unknown type in parameter");
        else if (type == DYN_TYPE_VOID)
          diagnostic(tq, s, errors, "parameter requires a non-void type");
        for (uint32_t k = 0; k < ts_node_named_child_count(c); ++k) {
          TSNode q = ts_node_named_child(c, k);
          if (strcmp(ts_node_type(q), "identifier"))
            continue;
          if (!reserve_param(a)) {
            diagnostic(q, s, errors, "out of memory");
            return false;
          }
          a->params[a->param_count++] = (DynAstParam){
              .name = span(q), .type = type, .local_id = UINT32_MAX};
          ++fn.param_count;
        }
      } else if (!strcmp(ts_node_type(c), "variadic_param")) {
        fn.variadic = true;
        fn.variadic_name = span(ts_node_child_by_field_name(c, "name", 4));
        fn.variadic_type = intern_slice(
            a, parse_type(ts_node_child_by_field_name(c, "type", 4), s, a),
            true);
      } else if (!strcmp(ts_node_type(c), "variadic"))
        fn.variadic = true;
      else if (!strcmp(ts_node_type(c), "type")) {
        fn.return_type = parse_type(c, s, a);
        if (fn.return_type == DYN_TYPE_ERROR)
          diagnostic(c, s, errors, "unknown type in return signature");
      }
    }
    a->functions[a->function_count++] = fn;
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
static void lower_function_bodies(TSNode root, const DynSource *s,
                                  DynAstProgram *a, unsigned *errors,
                                  const char *owner_key) {
  uint64_t wanted = owner_key_value(owner_key);
  for (uint32_t i = 0; i < ts_node_named_child_count(root) && dyn_work_step(&s->context, 1); ++i) {
    TSNode d = dyn_syntax_declaration_node(ts_node_named_child(root, i));
    if (strcmp(ts_node_type(d), "fn") && strcmp(ts_node_type(d), "extern_fn"))
      continue;
    TSNode name = ts_node_child_by_field_name(d, "name", 4);
    uint32_t id = find_function(a, span(name), s);
    if (id == UINT32_MAX)
      continue;
    if (a->functions[id].foreign)
      continue;
    if (owner_key && a->functions[id].module_owner != wanted) {
      a->functions[id].interface_only = true;
      continue;
    }
    TSNode block = {0};
    for (uint32_t j = 0; j < ts_node_named_child_count(d); ++j) {
      TSNode c = ts_node_named_child(d, j);
      if (!strcmp(ts_node_type(c), "block")) {
        block = c;
        break;
      }
    }
    lower_block(block, s, a, errors, 0, &a->functions[id].body_start,
                &a->functions[id].body_count);
    if (a->functions[id].is_main) {
      a->span = a->functions[id].span;
      a->name = a->functions[id].name;
      a->parameter_count = a->functions[id].param_count;
      a->has_return_type = a->functions[id].return_type != DYN_TYPE_VOID;
      a->body_start = a->functions[id].body_start;
      a->body_count = a->functions[id].body_count;
    }
  }
}
bool dyn_ast_lower_source(TSNode root, const DynSource *s, DynAstProgram *a,
                          unsigned *errors, const char *owner_key) {
  memset(a, 0, sizeof(*a));
  unsigned before = *errors;
  if (!add_enum_names(root, s, a, errors) ||
      !add_struct_names(root, s, a, errors) ||
      !add_alias_names(root, s, a, errors) ||
      !add_struct_fields(root, s, a, errors) ||
      !add_enum_variants(root, s, a, errors) ||
      !compute_layouts_v2(a, s, errors) || !add_globals(root, s, a, errors) ||
      !add_function_signatures(root, s, a, errors)) {
    if (*errors == before)
      diagnostic_node(root, s, errors, "out of memory");
    return false;
  }
  lower_function_bodies(root, s, a, errors, owner_key);
  bool found = false;
  for (uint32_t i = 0; i < a->function_count; ++i)
    if (a->functions[i].is_main)
      found = true;
  return found;
}
bool dyn_ast_parse_source_owner(const DynSource *s, DynAstProgram *a,
                                unsigned *errors, const char *owner_key,
                                bool allow_no_main) {
  memset(a, 0, sizeof(*a));
  TSParser *p = dyn_syntax_parser();
  if (!p) {
    return false;
  }
  TSTree *t = ts_parser_parse_string(p, NULL, s->text, (uint32_t)s->length);
  if (!t) {
    ts_parser_delete(p);
    return false;
  }
  TSNode root = ts_tree_root_node(t);
  bool found = dyn_ast_lower_source(root, s, a, errors, owner_key);
  ts_tree_delete(t);
  ts_parser_delete(p);
  return allow_no_main || (owner_key && strcmp(owner_key, "root")) || found;
}
bool dyn_ast_parse_main_source(const DynSource *s, DynAstProgram *a,
                               unsigned *errors) {
  return dyn_ast_parse_source_owner(s, a, errors, NULL, false);
}

#undef diagnostic
