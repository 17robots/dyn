/* Direct compact body lowering. This is deliberately not a Tree-sitter node
   adapter: references identify immutable snapshot nodes and an original-file
   offset; lowering dispatches on the compact grammar's own kinds and flags. */
#include "dyn_compact.h"
typedef struct {
  const ExpSnapshotTree *tree;
  uint32_t id, offset;
  ExpSnapshot *snapshot;
} CompactNode;
static CompactNode compact_none(void) { return (CompactNode){.id = UINT32_MAX}; }
static bool compact_null(CompactNode n) { return !n.tree || n.id == UINT32_MAX; }
static const ExpNode *compact_data(CompactNode n) { return &n.tree->nodes[n.id]; }
static uint16_t compact_kind(CompactNode n) { return compact_null(n) ? UINT16_MAX : compact_data(n)->kind; }
static DynSpan compact_span(CompactNode n) {
  return compact_null(n) ? (DynSpan){0} : (DynSpan){n.offset + compact_data(n)->start, n.offset + compact_data(n)->end};
}
static CompactNode compact_first(CompactNode n) {
  if (!compact_null(n)) n.id = compact_data(n)->first;
  return n;
}
static CompactNode compact_next(CompactNode n) {
  if (!compact_null(n)) n.id = compact_data(n)->next;
  return n;
}
static CompactNode compact_child(CompactNode n, uint32_t at) {
  n = compact_first(n);
  while (at-- && !compact_null(n)) n = compact_next(n);
  return n;
}
static uint32_t compact_count(CompactNode n) {
  uint32_t count = 0;
  for (n = compact_first(n); !compact_null(n); n = compact_next(n)) ++count;
  return count;
}
static CompactNode compact_last(CompactNode n) {
  CompactNode last = compact_none();
  for (n = compact_first(n); !compact_null(n); n = compact_next(n)) last = n;
  return last;
}
static CompactNode compact_unwrap(CompactNode n) {
  while (compact_kind(n) == EXP_GROUP) n = compact_first(n);
  return n;
}
static void compact_diagnostic(CompactNode n, const DynSource *s, unsigned *errors, const char *message) {
  diagnostic_span(compact_span(n), s, errors, message);
}
static DynOperator compact_operator(CompactNode n, const DynSource *s) {
  const ExpNode *node = compact_data(n);
  char op[8];
  if (node->operator_length >= sizeof(op)) return DYN_OP_NONE;
  memcpy(op, s->text + n.offset + node->operator_start, node->operator_length);
  op[node->operator_length] = 0;
  return op_from(op);
}
static bool compact_flag(CompactNode n, unsigned flag) {
  return !compact_null(n) && (compact_data(n)->flags & flag) != 0;
}
static DynType compact_type(CompactNode, const DynSource *, DynAstProgram *);
static DynExprId compact_expr(CompactNode, const DynSource *, DynAstProgram *, unsigned *);
static CompactNode compact_parent(CompactNode n) {
  if (!compact_null(n)) n.id = compact_data(n)->parent;
  return n;
}
static bool compact_same_name(CompactNode n, CompactNode name, const DynSource *s) {
  return compact_kind(n) == EXP_NAME && dyn_span_text_equal(compact_span(n), compact_span(name), s);
}
static bool compact_local_name(CompactNode use, const DynSource *s) {
  CompactNode child = use;
  for (CompactNode scope = compact_parent(child); !compact_null(scope); child = scope, scope = compact_parent(scope)) {
    if (!dyn_work_step(&s->context, 1)) return true;
    uint16_t kind = compact_kind(scope);
    if (kind == SRC_BLOCK) {
      for (CompactNode d = compact_first(scope); !compact_null(d); d = compact_next(d)) {
        if (!dyn_work_step(&s->context, 1)) return true;
        if (compact_span(d).end_byte > compact_span(child).start_byte) break;
        CompactNode v = compact_kind(d) == SRC_CONST ? compact_first(d) : d;
        if (compact_kind(v) == SRC_VARIABLE && compact_same_name(compact_first(v), use, s)) return true;
      }
    } else if (kind == SRC_FN) {
      for (CompactNode p = compact_first(scope); !compact_null(p); p = compact_next(p)) {
        if (!dyn_work_step(&s->context, 1)) return true;
        if (compact_kind(p) != SRC_FN_PARAM && compact_kind(p) != SRC_VARIADIC_PARAM) continue;
        for (CompactNode name = compact_first(p); !compact_null(name); name = compact_next(name))
          if (compact_same_name(name, use, s)) return true;
      }
      break;
    } else if (kind == SRC_FOR && compact_kind(child) == SRC_BLOCK) {
      for (CompactNode c = compact_first(scope); !compact_null(c); c = compact_next(c))
        if (compact_kind(c) == SRC_FOR_CONDITION && compact_flag(c, EXP_ITERATION) && compact_same_name(compact_first(c), use, s)) return true;
    } else if (kind == SRC_CASE_ARM && compact_kind(child) == SRC_BLOCK) {
      for (CompactNode name = compact_first(scope); !compact_null(name); name = compact_next(name)) {
        CompactNode binding = compact_kind(name) == SRC_TYPE_PATTERN ? compact_last(name) : name;
        if (compact_same_name(binding, use, s)) return true;
      }
    }
  }
  return false;
}
static bool compact_integer_constant(CompactNode declaration, const DynSource *s, DynAstProgram *a) {
  CompactNode variable = compact_first(declaration);
  for (CompactNode c = compact_child(variable, 1); !compact_null(c); c = compact_next(c)) {
    uint16_t kind = compact_kind(c);
    if (kind != SRC_QUALIFIER && kind != EXP_TYPE) continue;
    DynType type = compact_type(kind == SRC_QUALIFIER ? compact_first(c) : c, s, a);
    return type >= DYN_TYPE_I8 && type <= DYN_TYPE_USIZE;
  }
  return true;
}
static bool compact_global_extent(CompactNode, const DynSource *, DynAstProgram *, uint64_t *, unsigned, unsigned *);
static bool compact_extent(CompactNode n, const DynSource *s, DynAstProgram *a, uint64_t *value, unsigned depth, unsigned *remaining) {
  if (depth > 64 || !*remaining || !dyn_work_step(&s->context, 1)) return false;
  --*remaining;
  n = compact_unwrap(n);
  if (compact_kind(n) == EXP_NUMBER) {
    DynSpan p = compact_span(n);
    bool hex = p.end_byte - p.start_byte > 2 && s->text[p.start_byte] == '0' && s->text[p.start_byte + 1] == 'x';
    for (uint32_t i = p.start_byte; i < p.end_byte; ++i)
      if (s->text[i] == '.' || (!hex && (s->text[i] == 'e' || s->text[i] == 'E'))) return false;
    bool ok; *value = parse_uint(p, s, &ok); return ok;
  }
  if (compact_kind(n) == EXP_NAME) {
    for (CompactNode scope = compact_parent(n); !compact_null(scope); scope = compact_parent(scope)) {
      if (!dyn_work_step(&s->context, 1)) return false;
      if (compact_kind(scope) != SRC_BLOCK) continue;
      for (CompactNode d = compact_first(scope); !compact_null(d); d = compact_next(d)) {
        if (!dyn_work_step(&s->context, 1)) return false;
        if (compact_span(d).end_byte > compact_span(n).start_byte) break;
        CompactNode v = compact_kind(d) == SRC_CONST ? compact_first(d) : d;
        if (!compact_same_name(compact_first(v), n, s)) continue;
        if (compact_kind(d) != SRC_CONST || !compact_integer_constant(d, s, a)) return false;
        return compact_extent(compact_last(v), s, a, value, depth + 1, remaining);
      }
    }
    if (compact_local_name(n, s)) return false;
    return compact_global_extent(n, s, a, value, depth, remaining);
  }
  if (compact_kind(n) != EXP_BINARY) return false;
  uint64_t left, right;
  if (!compact_extent(compact_child(n, 0), s, a, &left, depth + 1, remaining) ||
      !compact_extent(compact_child(n, 1), s, a, &right, depth + 1, remaining)) return false;
  switch (compact_operator(n, s)) {
  case DYN_OP_ADD: if (left > UINT64_MAX - right) return false; *value = left + right; return true;
  case DYN_OP_SUB: if (left < right) return false; *value = left - right; return true;
  case DYN_OP_MUL: if (right && left > UINT64_MAX / right) return false; *value = left * right; return true;
  case DYN_OP_DIV: if (!right) return false; *value = left / right; return true;
  case DYN_OP_REM: if (!right) return false; *value = left % right; return true;
  case DYN_OP_SHL: if (right >= 64 || left > (UINT64_MAX >> right)) return false; *value = left << right; return true;
  case DYN_OP_SHR: if (right >= 64) return false; *value = left >> right; return true;
  case DYN_OP_BIT_AND: *value = left & right; return true;
  case DYN_OP_BIT_OR: *value = left | right; return true;
  case DYN_OP_BIT_XOR: *value = left ^ right; return true;
  default: return false;
  }
}
static DynType compact_type(CompactNode n, const DynSource *s, DynAstProgram *a) {
  if (!dyn_work_step(&s->context, 1)) return DYN_TYPE_ERROR;
  n = compact_unwrap(n);
  if (compact_kind(n) == EXP_TYPE || compact_kind(n) == EXP_TYPE_ARGUMENT) n = compact_first(n);
  uint16_t kind = compact_kind(n);
  if (kind == EXP_TYPE_PARAMETER) {
    DynSpan name = compact_span(n); ++name.start_byte;
    return scope_type(a, name, s, a->declaring_generic);
  }
  if (kind == EXP_FN_TYPE) {
    uint32_t named = compact_count(n), count = 0;
    DynType *params = calloc(named, sizeof(*params));
    if (named && !params) { a->allocation_failed = true; return DYN_TYPE_ERROR; }
    DynType result = DYN_TYPE_VOID;
    for (CompactNode c = compact_first(n); !compact_null(c); c = compact_next(c)) {
      DynType type = compact_type(c, s, a);
      if (type == DYN_TYPE_ERROR) { free(params); return type; }
      if (compact_data(c)->field == EXP_ROLE_RETURN) result = type;
      else params[count++] = type;
    }
    DynType type = intern_fn_type(a, params, count, result); free(params); return type;
  }
  if (kind == EXP_POINTER_TYPE) {
    DynType child = compact_type(compact_first(n), s, a);
    return child == DYN_TYPE_ERROR ? child : intern_pointer(a, child, compact_flag(n, EXP_CONST));
  }
  if (kind == EXP_ARRAY_TYPE) {
    DynType element = compact_type(compact_last(n), s, a);
    if (element == DYN_TYPE_ERROR) return element;
    if (compact_count(n) > 1) {
      CompactNode extent = compact_first(n); uint64_t length;
      unsigned remaining = 4096;
      if (compact_extent(extent, s, a, &length, 0, &remaining)) return intern_array(a, element, length);
      if (!a->invalid_array_extent.end_byte) a->invalid_array_extent = compact_span(extent);
      return DYN_TYPE_ERROR;
    }
    return intern_slice(a, element, compact_flag(n, EXP_CONST));
  }
  return parse_type_name(compact_span(n), s, a);
}
static DynExprId compact_argument(CompactNode n, const DynSource *s, DynAstProgram *a, unsigned *errors) {
  bool type = compact_kind(n) == EXP_TYPE_ARGUMENT;
  if (!type && a->scope_count) {
    n = compact_unwrap(n);
    type = compact_kind(n) == EXP_NAME && scope_type(a, compact_span(n), s, false) != DYN_TYPE_ERROR;
  }
  if (!type) return compact_expr(n, s, a, errors);
  DynType parsed = compact_type(n, s, a);
  if (parsed == DYN_TYPE_ERROR) { compact_diagnostic(n, s, errors, "unknown type"); return DYN_NO_EXPR; }
  if (!reserve_expr(a)) { compact_diagnostic(n, s, errors, "out of memory"); return DYN_NO_EXPR; }
  a->expressions[a->expression_count] = (DynAstExpr){.kind = DYN_EXPR_TYPE, .type = parsed,
    .span = compact_span(n), .left = DYN_NO_EXPR, .right = DYN_NO_EXPR};
  return (DynExprId)a->expression_count++;
}
static DynExprId compact_expr(CompactNode node, const DynSource *s, DynAstProgram *a,
                            unsigned *errors) {
  if (!dyn_work_step(&s->context, 1)) return DYN_NO_EXPR;
  node = compact_unwrap(node);
  if (!reserve_expr(a)) {
    compact_diagnostic(node, s, errors, "out of memory");
    return DYN_NO_EXPR;
  }
  DynAstExpr e = {0};
  e.span = compact_span(node);
  e.left = e.right = DYN_NO_EXPR;
  uint16_t k = compact_kind(node);
  if (!(k != EXP_NUMBER)) {
    bool fl = false;
    /* e and E are hex digits in 0x literals, not exponents. */
    bool hex = e.span.end_byte - e.span.start_byte > 1 &&
               s->text[e.span.start_byte] == '0' &&
               (s->text[e.span.start_byte + 1] == 'x' ||
                s->text[e.span.start_byte + 1] == 'X');
    for (uint32_t i = e.span.start_byte; i < e.span.end_byte; ++i)
      if (s->text[i] == '.' ||
          (!hex && (s->text[i] == 'e' || s->text[i] == 'E'))) {
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
      e.integer = parse_uint(compact_span(node), s, &ok);
      if (!ok) {
        compact_diagnostic(node, s, errors, "integer literal exceeds u64");
      }
    }
  } else if (!(k != EXP_BOOL)) {
    e.kind = DYN_EXPR_BOOL;
    e.type = DYN_TYPE_BOOL;
    e.boolean = s->text[e.span.start_byte] == 't';
  } else if (!(k != EXP_CHAR)) {
    e.kind = DYN_EXPR_CHAR;
    if (!parse_char(compact_span(node), s, &e.integer)) {
      compact_diagnostic(node, s, errors, "invalid Unicode scalar literal");
      return DYN_NO_EXPR;
    }
    e.type = e.integer <= 255 ? DYN_TYPE_U8 : DYN_TYPE_U32;
  } else if (!(k != EXP_STRING)) {
    e.kind = DYN_EXPR_STRING;
    e.type = DYN_TYPE_STRING;
    e.integer = parse_string(compact_span(node), s, a, errors);
  } else if (!(k != EXP_NIL)) {
    e.kind = DYN_EXPR_NIL;
    e.type = DYN_TYPE_INFER;
  } else if (!(k != EXP_NAME)) {
    e.kind = DYN_EXPR_NAME;
    e.type = DYN_TYPE_INFER;
  } else if (!(k != EXP_FIELD)) {
    e.kind = DYN_EXPR_FIELD;
    e.type = DYN_TYPE_INFER;
    e.left = compact_expr(compact_child(node, 0), s, a, errors);
    e.span = compact_span(compact_child(node, 1));
  } else if (!(k != EXP_CALL)) {
    CompactNode callee = compact_unwrap(compact_child(node, 0));
    if (!(compact_kind(callee) != EXP_FIELD)) {
      e.kind = DYN_EXPR_ENUM;
      e.type = DYN_TYPE_INFER;
      e.boolean = true;
      e.left = compact_expr(compact_child(callee, 0), s, a, errors);
      e.right = compact_expr(callee, s, a, errors);
      e.span = compact_span(compact_child(callee, 1));
    } else if (!(compact_kind(callee) != EXP_NAME)) {
      e.kind = DYN_EXPR_CALL;
      e.type = DYN_TYPE_INFER;
      e.span = compact_span(callee);
    } else {
      e.kind = DYN_EXPR_INDIRECT_CALL;
      e.type = DYN_TYPE_INFER;
      e.left = compact_expr(callee, s, a, errors);
      e.span = compact_span(callee);
    }
    e.item_start = (uint32_t)a->item_count;
    uint32_t operand_count = compact_count(node);
    uint32_t argument_count = operand_count ? operand_count - 1 : 0;
    if (!reserve_items(a, argument_count)) {
      compact_diagnostic(node, s, errors, "out of memory");
      return DYN_NO_EXPR;
    }
    a->item_count += argument_count;
    e.item_count = argument_count;
    uint32_t argument_index = 0;
    bool seen_callee = false;
    for (CompactNode arg = compact_first(node); !compact_null(arg); arg = compact_next(arg)) {
      if (!seen_callee) {
        seen_callee = true;
        continue;
      }
      DynExprId expression = compact_argument(arg, s, a, errors);
      a->items[e.item_start + argument_index++] =
          (DynAstItem){.expression = expression, .field_index = UINT32_MAX};
    }
  } else if (!(k != EXP_STRUCT)) {
    e.kind = DYN_EXPR_STRUCT;
    e.type = DYN_TYPE_INFER;
    uint32_t first = 0, count = compact_count(node);
    while (
        first < count &&
        !(compact_kind(compact_child(node, first)) != EXP_NAME))
      ++first;
    if (first) {
      CompactNode begin = compact_child(node, 0),
             end = compact_child(node, first - 1);
      e.span = (DynSpan){compact_span(begin).start_byte, compact_span(end).end_byte};
    } else {
      e.span = compact_span(node);
      e.boolean = true;
    }
    e.item_start = (uint32_t)a->item_count;
    for (CompactNode m = compact_child(node, first); !compact_null(m); m = compact_next(m)) {
      if ((compact_kind(m) != EXP_MEMBER))
        continue;
      if (!reserve_item(a)) {
        compact_diagnostic(m, s, errors, "out of memory");
        return DYN_NO_EXPR;
      }
      a->items[a->item_count++] = (DynAstItem){.field_index = UINT32_MAX};
      ++e.item_count;
    }
    uint32_t member_index = 0;
    for (CompactNode m = compact_child(node, first); !compact_null(m); m = compact_next(m)) {
      if ((compact_kind(m) != EXP_MEMBER)) {
        continue;
      }
      DynSpan name = compact_span(compact_child(m, 0));
      DynExprId expression = compact_expr(compact_child(m, 1), s, a, errors);
      DynAstItem *item = &a->items[e.item_start + member_index++];
      item->name = name;
      item->expression = expression;
    }
  } else if (!(k != EXP_ARRAY)) {
    e.kind = DYN_EXPR_ARRAY;
    e.type = DYN_TYPE_INFER;
    e.item_start = (uint32_t)a->item_count;
    e.item_count = compact_count(node);
    if (!reserve_items(a, e.item_count)) {
      compact_diagnostic(node, s, errors, "out of memory"); return DYN_NO_EXPR;
    }
    a->item_count += e.item_count;
    uint32_t item_index = 0;
    for (CompactNode child = compact_first(node); !compact_null(child); child = compact_next(child)) {
      DynExprId expression = compact_expr(child, s, a, errors);
      a->items[e.item_start + item_index++] = (DynAstItem){.expression = expression, .field_index = UINT32_MAX};
    }
  } else if (k == EXP_INDEX || k == EXP_SLICE) {
    e.left = compact_expr(compact_first(node), s, a, errors);
    if (k == EXP_INDEX) {
      e.kind = DYN_EXPR_INDEX;
      e.right = compact_expr(compact_child(node, 1), s, a, errors);
    } else {
      e.kind = DYN_EXPR_SLICE;
      e.integer = DYN_NO_EXPR;
      CompactNode low = compact_child(node, 1), high = compact_child(node, 2);
      if (!compact_null(compact_unwrap(low))) e.right = compact_expr(low, s, a, errors);
      if (!compact_null(compact_unwrap(high))) e.integer = compact_expr(high, s, a, errors);
    }
  } else if (!(k != EXP_LEN)) {
    e.kind = DYN_EXPR_LEN;
    e.left = compact_expr(compact_child(node, 0), s, a, errors);
  } else if (!(k != EXP_SIZE) || !(k != EXP_ALIGN) ||
             !(k != EXP_TYPEOF)) {
    e.kind = !(k != EXP_SIZE)    ? DYN_EXPR_SIZE
             : !(k != EXP_ALIGN) ? DYN_EXPR_ALIGN
                                   : DYN_EXPR_TYPEOF;
    CompactNode operand = compact_child(node, 0);
    if (!(compact_kind(operand) != EXP_TYPE)) {
      DynType parsed = compact_type(operand, s, a);
      if (parsed != DYN_TYPE_ERROR) {
        e.boolean = true;
        e.integer = parsed;
      } else {
        while (compact_count(operand) == 1)
          operand = compact_child(operand, 0);
        e.left = compact_expr(operand, s, a, errors);
      }
    } else
      e.left = compact_expr(operand, s, a, errors);
  } else if (!(k != EXP_LOAD)) {
    /* Failures still yield an empty string so one bad path reports once. */
    CompactNode literal = compact_child(node, 0);
    uint32_t begin = compact_span(literal).start_byte + 1, end = compact_span(literal).end_byte - 1;
    const char *source_path = NULL;
    unsigned line = 0, column = 0;
    dyn_source_location(s, e.span.start_byte, &source_path, &line, &column);
    char *path = end > begin && source_path
                     ? dyn_load_path(source_path, s->text + begin, end - begin)
                     : NULL;
    size_t length = 0;
    unsigned char *data = path ? dyn_load_read(path, &length) : NULL;
    if (!path)
      compact_diagnostic(node, s, errors, "#load path must be relative without '..' or '\\'");
    else if (!data)
      compact_diagnostic(node, s, errors, "#load cannot read file");
    free(path);
    if (!data)
      length = 0;
    if (!reserve_string(a) || (!data && !(data = malloc(1)))) {
      free(data);
      compact_diagnostic(node, s, errors, "out of memory");
      return DYN_NO_EXPR;
    }
    e.kind = DYN_EXPR_STRING;
    e.type = DYN_TYPE_STRING;
    e.integer = (uint32_t)a->string_count;
    a->strings[a->string_count++] = (DynAstString){data, length};
  } else if (!(k != EXP_WRAP)) {
    DynExprId inner = compact_expr(compact_child(node, 0), s, a, errors);
    if (inner != DYN_NO_EXPR && !mark_wrap(a, inner, 0))
      compact_diagnostic(node, s, errors, "#wrap needs +, -, * or << inside");
    return inner;
  } else if (!(k != EXP_OFFSET)) {
    CompactNode field = compact_child(node, 1);
    e.kind = DYN_EXPR_OFFSET;
    e.integer = compact_type(compact_child(node, 0), s, a);
    e.item_start = compact_span(field).start_byte;
    e.item_count = compact_span(field).end_byte;
  } else if (!(k != EXP_CAST)) {
    e.kind = compact_flag(node, EXP_BITCAST) ? DYN_EXPR_BITCAST
                                                   : DYN_EXPR_CAST;
    e.integer = compact_type(compact_child(node, 0), s, a);
    e.left = compact_expr(compact_child(node, 1), s, a, errors);
  } else if (!(k != EXP_SYSCALL)) {
    e.kind = DYN_EXPR_SYSCALL;
    e.type = DYN_TYPE_INFER;
    e.item_start = (uint32_t)a->item_count;
    e.item_count = compact_count(node);
    if (!reserve_items(a, e.item_count)) {
      compact_diagnostic(node, s, errors, "out of memory");
      return DYN_NO_EXPR;
    }
    a->item_count += e.item_count;
    uint32_t item_index = 0;
    for (CompactNode arg = compact_first(node); !compact_null(arg); arg = compact_next(arg)) {
      DynExprId expression = compact_expr(arg, s, a, errors);
      a->items[e.item_start + item_index++] =
          (DynAstItem){.expression = expression, .field_index = UINT32_MAX};
    }
  } else if (!(k != EXP_PREFIX)) {
    e.kind = DYN_EXPR_UNARY;
    e.op = compact_operator(node, s);
    if (compact_operator(node, s) == DYN_OP_BIT_AND) {
      e.op = DYN_OP_ADDRESS;
    }
    if (e.op == DYN_OP_SUB) {
      e.op = DYN_OP_NEG;
    }
    e.left = compact_expr(compact_child(node, 0), s, a, errors);
  } else if (!(k != EXP_DEREF)) {
    e.kind = DYN_EXPR_UNARY;
    e.op = DYN_OP_DEREF;
    e.left = compact_expr(compact_child(node, 0), s, a, errors);
  } else if (!(k != EXP_BINARY)) {
    e.kind = DYN_EXPR_BINARY;
    e.op = compact_operator(node, s);
    e.left = compact_expr(compact_child(node, 0), s, a, errors);
    e.right = compact_expr(compact_child(node, 1), s, a, errors);
  } else {
    compact_diagnostic(node, s, errors,
               "expression is not implemented in bootstrap compiler");
    return DYN_NO_EXPR;
  }
  if (!reserve_expr(a)) {
    compact_diagnostic(node, s, errors, "out of memory");
    return DYN_NO_EXPR;
  }
  DynExprId id = (DynExprId)a->expression_count;
  a->expressions[a->expression_count++] = e;
  return id;
}
static bool compact_block(CompactNode, const DynSource *, DynAstProgram *, unsigned *,
                        uint32_t, uint32_t *, uint32_t *);

static bool compact_pointer_pattern(CompactNode pattern, DynAstCaseArm *arm,
                                 CompactNode *value, const DynSource *s) {
  CompactNode p = compact_unwrap(compact_child(pattern, 0));
  if ((compact_kind(p) != EXP_BINARY) || compact_operator(p, s) != DYN_OP_MUL) {
    return false;
  }
  CompactNode right = compact_unwrap(compact_child(p, 1));
  if ((compact_kind(right) != EXP_NAME)) {
    return false;
  }
  arm->binding = compact_span(right);
  arm->pointer_binding = true;
  *value = compact_unwrap(compact_child(p, 0));
  return true;
}
static void compact_case(CompactNode n, const DynSource *s, DynAstProgram *a,
                            unsigned *errors, uint32_t loop_depth,
                            DynAstStmt *st) {
  st->kind = DYN_STMT_CASE;
  st->expression = compact_expr(compact_child(n, 0), s, a, errors);
  st->case_arm_start = (uint32_t)a->case_arm_count;
  uint32_t count = 0;
  for (CompactNode child = compact_child(n, 1); !compact_null(child); child = compact_next(child))
    if (compact_kind(child) == SRC_CASE_ARM) {
      ++count;
    }
  if (!count)
    return;
  CompactNode *blocks = calloc(count, sizeof(*blocks));
  if (!blocks) {
    compact_diagnostic(n, s, errors, "out of memory");
    return;
  }
  uint32_t arm_index = 0;
  for (CompactNode an = compact_child(n, 1); !compact_null(an); an = compact_next(an)) {
    if ((compact_kind(an) != SRC_CASE_ARM)) {
      continue;
    }
    if (!reserve_case_arm(a)) {
      compact_diagnostic(an, s, errors, "out of memory");
      break;
    }
    DynAstCaseArm arm = {.span = compact_span(an),
                         .pattern_start = (uint32_t)a->pattern_count,
                         .local_id = UINT32_MAX};
    arm.wildcard = compact_flag(an, EXP_WILDCARD);
    for (CompactNode c = compact_first(an); !compact_null(c); c = compact_next(c)) {
      if (!(compact_kind(c) != SRC_CASE_PATTERN)) {
        CompactNode p = {0};
        bool pointer = compact_pointer_pattern(c, &arm, &p, s);
        if (!pointer) {
          p = compact_unwrap(compact_child(c, 0));
        }
        if (!reserve_pattern(a)) {
          compact_diagnostic(p, s, errors, "out of memory");
          continue;
        }
        DynAstPattern pat = {
            .span = compact_span(p), .first = DYN_NO_EXPR, .last = DYN_NO_EXPR};
        if (!(compact_kind(p) != SRC_RANGE)) {
          pat.range = true;
          pat.first = compact_expr(compact_child(p, 0), s, a, errors);
          pat.last = compact_expr(compact_child(p, 1), s, a, errors);
          pat.inclusive = compact_flag(p, EXP_INCLUSIVE);
        } else
          pat.first = compact_expr(p, s, a, errors);
        a->patterns[a->pattern_count++] = pat;
        ++arm.pattern_count;
      } else if (!(compact_kind(c) != SRC_TYPE_PATTERN)) {
        if (!reserve_pattern(a)) {
          compact_diagnostic(c, s, errors, "out of memory");
          continue;
        }
        CompactNode tn = {0};
        for (CompactNode x = compact_child(c, 0); !compact_null(x); x = compact_next(x)) {
          if (!(compact_kind(x) != EXP_TYPE))
            tn = x;
          else if (!(compact_kind(x) != EXP_NAME))
            arm.binding = compact_span(x);
        }
        a->patterns[a->pattern_count++] =
            (DynAstPattern){.span = compact_span(c),
                            .first = DYN_NO_EXPR,
                            .last = DYN_NO_EXPR,
                            .type = compact_type(tn, s, a),
                            .is_type = true};
        arm.pattern_count = 1;
      } else if (!(compact_kind(c) != EXP_NAME)) {
        arm.binding = compact_span(c);
      } else if (!(compact_kind(c) != SRC_BLOCK)) {
        blocks[arm_index] = c;
      }
    }
    a->case_arms[a->case_arm_count++] = arm;
    ++arm_index;
  }
  st->case_arm_count = arm_index;
  for (uint32_t i = 0; i < arm_index; ++i)
    if (!compact_null(blocks[i])) {
      uint32_t start = 0, count = 0;
      compact_block(blocks[i], s, a, errors, loop_depth, &start, &count);
      a->case_arms[st->case_arm_start + i].body_start = start;
      a->case_arms[st->case_arm_start + i].body_count = count;
    }
  free(blocks);
}
static uint32_t compact_stmt(CompactNode n, const DynSource *s, DynAstProgram *a,
                           unsigned *errors, uint32_t loop_depth) {
  if (!reserve_stmt(a)) {
    compact_diagnostic(n, s, errors, "out of memory");
    return UINT32_MAX;
  }
  uint32_t id = (uint32_t)a->statement_count++;
  DynAstStmt st = {0};
  st.span = compact_span(n);
  st.expression = st.target = DYN_NO_EXPR;
  st.local_id = UINT32_MAX;
  st.loop_depth = loop_depth;
  uint16_t k = compact_kind(n);
  if (!(k != SRC_CONST)) {
    st.is_const = true;
    n = compact_child(n, 0);
    k = compact_kind(n);
    st.span = compact_span(n);
  }
  st.target_loop_id = UINT32_MAX;
  if (!(k != SRC_RETURN)) {
    st.kind = DYN_STMT_RETURN;
    if (compact_count(n)) {
      st.expression = compact_expr(compact_child(n, 0), s, a, errors);
    }
  } else if (!(k != SRC_VARIABLE)) {
    st.kind = DYN_STMT_LOCAL;
    st.name = compact_span(compact_child(n, 0));
    st.declared_type = DYN_TYPE_INFER;
    for (CompactNode c = compact_child(n, 1); !compact_null(c); c = compact_next(c)) {
      if (!(compact_kind(c) != SRC_QUALIFIER)) {
        st.declared_type = compact_type(compact_child(c, 0), s, a);
      } else if (!(compact_kind(c) != EXP_TYPE)) {
        st.declared_type = compact_type(c, s, a);
      } else {
        st.expression = compact_expr(c, s, a, errors);
      }
    }
    if (st.declared_type == DYN_TYPE_ERROR)
      compact_diagnostic(n, s, errors, "unknown or invalid local type");
    if (st.is_const && st.expression == DYN_NO_EXPR)
      compact_diagnostic(n, s, errors, "local constant requires initializer");
  } else if (!(k != SRC_ASSIGNMENT)) {
    st.kind = DYN_STMT_ASSIGN;
    CompactNode target = compact_unwrap(compact_child(n, 0));
    if (!(compact_kind(target) != EXP_NAME))
      st.name = compact_span(target);
    else if (!(compact_kind(target) != EXP_FIELD) ||
             !(compact_kind(target) != EXP_DEREF) ||
             !(compact_kind(target) != EXP_INDEX) || compact_kind(target) == EXP_SLICE)
      st.target = compact_expr(target, s, a, errors);
    else {
      compact_diagnostic(
          target, s, errors,
          "assignment target must be local, field, dereference, or index");
      a->statements[id] = st;
      return id;
    }
    st.expression = compact_expr(compact_last(n), s, a, errors);
    st.assignment_op = compact_operator(n, s);
  } else if (!(k != SRC_IF)) {
    st.kind = DYN_STMT_IF;
    st.expression = compact_expr(compact_child(n, 0), s, a, errors);
    CompactNode b = compact_child(n, 1);
    compact_block(b, s, a, errors, loop_depth, &st.body_start, &st.body_count);
    if (compact_count(n) > 2) {
      CompactNode e = compact_child(n, 2), branch = compact_child(e, 0);
      if (!(compact_kind(branch) != SRC_BLOCK))
        compact_block(branch, s, a, errors, loop_depth, &st.else_start,
                    &st.else_count);
      else {
        uint32_t nested = compact_stmt(branch, s, a, errors, loop_depth);
        st.else_start = (uint32_t)a->child_count;
        if (reserve_child(a))
          a->children[a->child_count++] = nested;
        st.else_count = 1;
      }
    }
  } else if (!(k != SRC_CASE)) {
    compact_case(n, s, a, errors, loop_depth, &st);
  } else if (!(k != SRC_FOR)) {
    st.kind = DYN_STMT_FOR;
    st.loop_id = a->loop_count++;
    uint32_t count = compact_count(n);
    CompactNode last = compact_last(n);
    for (uint32_t z = 0; z + 1 < count; ++z) {
      CompactNode c = compact_child(n, z);
      if (!(compact_kind(c) != EXP_NAME)) {
        st.label = compact_span(c);
        continue;
      }
      if (!(compact_kind(c) != SRC_FOR_CONDITION)) {
        uint32_t cc = compact_count(c);
        if (cc == 1)
          st.expression = compact_expr(compact_child(c, 0), s, a, errors);
        else {
          CompactNode binder = compact_child(c, 0);
          st.for_pointer = compact_flag(c, EXP_POINTER_BINDING);
          st.for_const = compact_flag(c, EXP_CONST);
          st.name = compact_span(binder);
          CompactNode iterable = compact_last(c);
          if (!(compact_kind(iterable) != SRC_REVERSE)) {
            st.for_reverse = true;
            iterable = compact_child(iterable, 0);
          }
          if (!(compact_kind(iterable) != SRC_RANGE)) {
            st.for_range = true;
            st.for_inclusive = compact_flag(iterable, EXP_INCLUSIVE);
            st.target = compact_expr(compact_child(iterable, 0), s, a, errors);
            st.expression =
                compact_expr(compact_child(iterable, 1), s, a, errors);
          } else
            st.target = compact_expr(iterable, s, a, errors);
        }
      }
    }
    compact_block(last, s, a, errors, loop_depth + 1, &st.body_start,
                &st.body_count);
  } else if (!(k != SRC_BREAK)) {
    st.kind = DYN_STMT_BREAK;
    if (compact_count(n))
      st.control_label = compact_span(compact_child(n, 0));
  } else if (!(k != SRC_CONTINUE)) {
    st.kind = DYN_STMT_CONTINUE;
    if (compact_count(n))
      st.control_label = compact_span(compact_child(n, 0));
  } else if (!(k != SRC_DEFER)) {
    st.kind = DYN_STMT_DEFER;
    CompactNode action = compact_child(n, 0);
    if (!(compact_kind(action) != SRC_BLOCK)) {
      st.defer_block = true;
      compact_block(action, s, a, errors, loop_depth, &st.body_start,
                  &st.body_count);
    } else {
      uint32_t deferred = compact_stmt(action, s, a, errors, loop_depth);
      st.body_start = (uint32_t)a->child_count;
      if (reserve_child(a))
        a->children[a->child_count++] = deferred;
      st.body_count = 1;
    }
  } else if (!(k != SRC_PANIC)) {
    st.kind = DYN_STMT_PANIC;
    if (compact_count(n))
      st.expression = compact_expr(compact_child(n, 0), s, a, errors);
  } else if (!(k != EXP_SYSCALL)) {
    st.kind = DYN_STMT_EXPR;
    st.expression = compact_expr(n, s, a, errors);
  } else if (!(k != EXP_CALL)) {
    st.kind = DYN_STMT_EXPR;
    st.expression = compact_expr(n, s, a, errors);
  } else if (!(k != SRC_ALIAS)) {
    compact_diagnostic(n, s, errors, "local type aliases are not supported; declare the alias at module scope");
  } else {
    compact_diagnostic(
        n, s, errors,
        "unsupported statement");
  }
  a->statements[id] = st;
  return id;
}
static bool compact_block(CompactNode block, const DynSource *s, DynAstProgram *a,
                        unsigned *errors, uint32_t loop_depth, uint32_t *start,
                        uint32_t *count) {
  *count = 0;
  if (compact_null(block)) {
    *start = (uint32_t)a->child_count;
    return true;
  }
  uint32_t n = compact_count(block);
  uint32_t *ids = malloc(n * sizeof(*ids));
  if (n && !ids) {
    a->allocation_failed = true;
    compact_diagnostic(block, s, errors, "out of memory");
    return false;
  }
  for (CompactNode c = compact_first(block); !compact_null(c); c = compact_next(c)) {
    if (!dyn_work_step(&s->context, 1)) { free(ids); *count = 0; return false; }
    uint32_t id = compact_stmt(c, s, a, errors, loop_depth);
    if (id == UINT32_MAX) { free(ids); *count = 0; return false; }
    ids[(*count)++] = id;
  }
  *start = (uint32_t)a->child_count;
  for (uint32_t i = 0; i < *count; ++i) {
    if (!reserve_child(a)) {
      free(ids);
      *count = 0;
      compact_diagnostic(block, s, errors, "out of memory");
      return false;
    }
    a->children[a->child_count++] = ids[i];
  }
  free(ids);
  return true;
}
/* Preserve the old reader's treatment of extras in the few raw-child scans
   whose behavior is observably different from filtered grammar children. */
static bool compact_comments(const DynSource *s, DynSpan span) {
  for (uint32_t i = span.start_byte; i < span.end_byte; ++i) {
    if (!(i % 1024) && !dyn_work_step(&s->context, 1)) return true;
    unsigned char c = (unsigned char)s->text[i];
    if (c == '\'' || c == '"') {
      unsigned char quote = c;
      while (++i < span.end_byte) {
        if (!(i % 1024) && !dyn_work_step(&s->context, 1)) return true;
        if (s->text[i] == '\\' && i + 1 < span.end_byte) ++i;
        else if ((unsigned char)s->text[i] == quote) break;
      }
    } else if (c == '/' && i + 1 < span.end_byte &&
               (s->text[i + 1] == '/' || s->text[i + 1] == '*')) return true;
  }
  return false;
}
static bool compact_compatible_node(CompactNode n, const DynSource *s) {
  /* Batch commands have no legacy reader to defer to. */
  if (s->context.strict_syntax) return true;
  if (compact_kind(n) == SRC_ENUM_MEMBER && compact_comments(s, compact_span(n))) return false;
  if (compact_kind(n) == EXP_STRUCT) {
    CompactNode first = compact_first(n), last = first;
    for (CompactNode name = first; compact_kind(name) == EXP_NAME; name = compact_next(name)) last = name;
    if (compact_kind(first) == EXP_NAME && last.id != first.id &&
        compact_comments(s, (DynSpan){compact_span(first).start_byte, compact_span(last).end_byte})) return false;
  }
  if (compact_kind(n) == SRC_RANGE && compact_comments(s, compact_span(n))) return false;
  return true;
}
static bool compact_shape_supported(CompactNode n, const DynSource *s) {
  if (!dyn_work_step(&s->context, 1) || !compact_compatible_node(n, s)) return false;
  for (CompactNode c = compact_first(n); !compact_null(c); c = compact_next(c))
    if (!compact_shape_supported(c, s)) return false;
  return true;
}
/* Eligibility is decided before any AST mutation. Named array extents still
   require the existing declaration-order and local-shadowing resolver. */
static bool compact_extent_supported(CompactNode n, const DynSource *s) {
  if (!dyn_work_step(&s->context, 1)) return false;
  if (compact_kind(n) == EXP_NAME) return false;
  for (CompactNode c = compact_first(n); !compact_null(c); c = compact_next(c))
    if (!compact_extent_supported(c, s)) return false;
  return true;
}
static bool compact_body_supported(CompactNode n, const DynSource *s) {
  if (!dyn_work_step(&s->context, 1) || !compact_compatible_node(n, s)) return false;
  if (compact_kind(n) == EXP_ARRAY_TYPE && compact_count(n) > 1 &&
      !compact_extent_supported(compact_first(n), s)) return false;
  for (CompactNode c = compact_first(n); !compact_null(c); c = compact_next(c))
    if (!compact_body_supported(c, s)) return false;
  return true;
}
static DynAstCompactRef compact_reference(CompactNode n) {
  return (DynAstCompactRef){n.snapshot, n.id, n.offset};
}
static CompactNode compact_node(DynAstCompactRef ref) {
  return ref.snapshot ? (CompactNode){exp_snapshot_tree(ref.snapshot), ref.node, ref.offset, ref.snapshot} : compact_none();
}
static DynType compact_alias_type(DynAstCompactRef ref, const DynSource *s, DynAstProgram *a) {
  return compact_type(compact_node(ref), s, a);
}
struct DynCompactDeclaration {
  DynAstCompactRef ref;
};
static CompactNode compact_declaration(const DynAstProgram *a, size_t index) {
  return compact_node(a->compact_declarations[index].ref);
}
static bool compact_global_extent(CompactNode n, const DynSource *s, DynAstProgram *a, uint64_t *value, unsigned depth, unsigned *remaining) {
  for (size_t i = 0; i < a->compact_declaration_count; ++i) {
    if (!dyn_work_step(&s->context, 1)) return false;
    CompactNode wrapper = compact_declaration(a, i), name = wrapper;
    name.id = dyn_compact_name(wrapper.tree, wrapper.id);
    if (compact_null(name) || !dyn_module_name_equal(compact_span(n), compact_span(name), s)) continue;
    CompactNode declaration = compact_first(wrapper);
    CompactNode v = compact_kind(declaration) == SRC_CONST ? compact_first(declaration) : declaration;
    if (compact_kind(declaration) != SRC_CONST || !compact_integer_constant(declaration, s, a)) return false;
    return compact_extent(compact_last(v), s, a, value, depth + 1, remaining);
  }
  return false;
}
static CompactNode compact_field(CompactNode n, ExpField field) {
  for (CompactNode c = compact_first(n); !compact_null(c); c = compact_next(c))
    if (compact_data(c)->field == field) return c;
  return compact_none();
}
struct DynCompactBody {
  ExpSnapshot *snapshot;
  uint32_t node, offset, function_start;
};
/* Shape checks only read the trees, so batch builds run them on workers. */
typedef struct {
  CompactNode declaration;
  bool shape;
  uint32_t block;  /* first body block of a function, or UINT32_MAX */
  bool block_supported;
} CompactShape;
typedef struct {
  CompactShape *items;
  size_t count;
  const DynSource *source;
  atomic_size_t next;
} CompactShapes;
static void *compact_shape_worker(void *raw) {
  CompactShapes *shapes = raw;
  for (size_t i; (i = atomic_fetch_add(&shapes->next, 64)) < shapes->count;)
    for (size_t j = i; j < i + 64 && j < shapes->count; ++j) {
      CompactShape *item = &shapes->items[j];
      item->shape = compact_shape_supported(item->declaration, shapes->source);
      item->block = UINT32_MAX;
      CompactNode fn = compact_first(item->declaration);
      if (compact_kind(fn) != SRC_FN) continue;
      for (CompactNode body = compact_first(fn); !compact_null(body); body = compact_next(body))
        if (compact_kind(body) == SRC_BLOCK) {
          item->block = body.id;
          item->block_supported = compact_body_supported(body, shapes->source);
          break;
        }
    }
  return NULL;
}
static CompactShape *compact_shapes(DynAstProgram *a, const DynSource *s, size_t partitions) {
#ifdef _WIN32
  (void)a; (void)s; (void)partitions;
  return NULL;
#else
  long online = sysconf(_SC_NPROCESSORS_ONLN);
  if (s->context.work || online < 2 || a->decl_count < 256) return NULL;
  CompactShapes shapes = {.items = calloc(a->decl_count, sizeof(CompactShape)), .source = s};
  if (!shapes.items) return NULL;
  for (size_t i = 0; i < partitions; ++i) {
    ExpSnapshot *snapshot = s->syntax_part_count ? s->compact_parts[i] : s->compact;
    const ExpSnapshotTree *tree = exp_snapshot_tree(snapshot);
    if (!tree) continue;
    size_t prelude = s->syntax_part_count ? partitions - s->map_count : 0;
    uint32_t offset = s->syntax_part_count && i >= prelude ? (uint32_t)s->maps[i - prelude].start : 0;
    CompactNode root = {tree, tree->root, offset, snapshot};
    for (CompactNode d = compact_first(root); !compact_null(d) && shapes.count < a->decl_count; d = compact_next(d))
      shapes.items[shapes.count++].declaration = d;
  }
  atomic_init(&shapes.next, 0);
  unsigned workers = online > 4 ? 4 : (unsigned)online, started = 0;
  pthread_t threads[4];
  for (; started + 1 < workers; ++started)
    if (pthread_create(&threads[started], NULL, compact_shape_worker, &shapes)) break;
  compact_shape_worker(&shapes);
  for (unsigned i = 0; i < started; ++i) pthread_join(threads[i], NULL);
  return shapes.items;
#endif
}
static bool compact_prepare_bodies(DynAstProgram *a, const DynSource *s) {
  if (!s->compact && !s->compact_parts) return true;
  size_t partitions = s->syntax_part_count ? s->syntax_part_count : 1;
  if (s->syntax_part_count && (!s->compact_parts || !s->map_count ||
      partitions < s->map_count || partitions > s->map_count + 1)) return true;
  a->compact_bodies = calloc(a->decl_count ? a->decl_count : 1, sizeof(*a->compact_bodies));
  a->compact_declarations = calloc(a->decl_count ? a->decl_count : 1, sizeof(*a->compact_declarations));
  if (!a->compact_bodies || !a->compact_declarations) { a->allocation_failed = true; return false; }
  a->compact_complete = true;
  CompactShape *shapes = compact_shapes(a, s, partitions);
  size_t index = 0;
  for (size_t i = 0; i < partitions; ++i) {
    ExpSnapshot *snapshot = s->syntax_part_count ? s->compact_parts[i] : s->compact;
    const ExpSnapshotTree *tree = exp_snapshot_tree(snapshot);
    if (!tree) { a->compact_complete = false; continue; }
    size_t prelude = s->syntax_part_count ? partitions - s->map_count : 0;
    uint32_t offset = s->syntax_part_count && i >= prelude ? (uint32_t)s->maps[i - prelude].start : 0;
    CompactNode root = {tree, tree->root, offset, snapshot};
    for (CompactNode declaration = compact_first(root); !compact_null(declaration); declaration = compact_next(declaration)) {
      if (!dyn_work_step(&s->context, 1)) { free(shapes); return false; }
      const CompactShape *shape = shapes ? &shapes[index++] : NULL;
      if (!(shape ? shape->shape : compact_shape_supported(declaration, s))) a->compact_complete = false;
      if (!exp_snapshot_retain(snapshot)) { a->allocation_failed = true; free(shapes); return false; }
      a->compact_declarations[a->compact_declaration_count++].ref = compact_reference(declaration);
      CompactNode fn = compact_first(declaration);
      if (compact_kind(fn) != SRC_FN) continue;
      for (CompactNode body = compact_first(fn); !compact_null(body); body = compact_next(body)) {
        if (compact_kind(body) != SRC_BLOCK) continue;
        bool supported = shape && shape->block == body.id ? shape->block_supported : compact_body_supported(body, s);
        if (!supported) continue;
        if (!exp_snapshot_retain(snapshot)) { a->allocation_failed = true; free(shapes); return false; }
        a->compact_bodies[a->compact_body_count++] = (struct DynCompactBody){snapshot, body.id, offset, compact_span(fn).start_byte};
      }
    }
  }
  free(shapes);
  return dyn_work_step(&s->context, 0);
}
