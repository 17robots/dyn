#include "native_opt.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Conservative scalar evaluation: failure means retain the original runtime
   expression, including its checks and cleanup. No host signed overflow. */
typedef struct {
  const DynIrProgram *ir;
  unsigned level, pointer_bits, remaining;
  const DynIrFunction *function;
  const uint64_t *arguments;
  const uint64_t *samples;
} Eval;
static unsigned width(Eval *c, DynType t) {
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
    return 32;
  case DYN_TYPE_I64:
  case DYN_TYPE_U64:
    return 64;
  case DYN_TYPE_ISIZE:
  case DYN_TYPE_USIZE:
    return c->pointer_bits;
  default:
    return 0;
  }
}
static bool signed_type(DynType t) {
  return (t >= DYN_TYPE_I8 && t <= DYN_TYPE_I64) || t == DYN_TYPE_ISIZE;
}
static uint64_t normalize(uint64_t x, unsigned bits, bool sign) {
  uint64_t mask = UINT64_MAX >> (64 - bits), high = UINT64_C(1) << (bits - 1);
  x &= mask;
  return sign && (x & high) ? x | ~mask : x;
}
static bool value(Eval *c, DynExprId id, uint64_t *out, unsigned depth) {
  if (depth > 64 || !c->remaining || id >= c->ir->expression_count)
    return false;
  --c->remaining;
  const DynIrExpr *e = &c->ir->expressions[id];
  unsigned bits = width(c, e->type);
  if (!bits)
    return false;
  bool sign = signed_type(e->type);
  uint64_t a, b, r = 0, mask = UINT64_MAX >> (64 - bits),
                 high = UINT64_C(1) << (bits - 1);
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_CHAR ||
      e->kind == DYN_EXPR_BOOL) {
    *out = normalize(e->kind == DYN_EXPR_BOOL ? e->boolean : e->integer, bits,
                     sign);
    return true;
  }
  if (e->kind == DYN_EXPR_NAME) {
    if (c->function) {
      for (unsigned i = 0; i < c->function->param_count; ++i)
        if (c->ir->params[c->function->param_start + i].local_id ==
            e->integer) {
          *out = c->arguments[i];
          return true;
        }
      return false;
    }
    if (c->level < 2 || e->integer >= c->ir->local_count ||
        !c->ir->unstable_locals || c->ir->unstable_locals[e->integer] ||
        !c->ir->local_statements)
      return false;
    uint32_t st = c->ir->local_statements[e->integer];
    return st && st <= c->ir->statement_count &&
           value(c, c->ir->statements[st - 1].expression, out, depth + 1);
  }
  if (e->kind == DYN_EXPR_CALL && c->level >= 3 && !c->function &&
      e->integer < c->ir->function_count) {
    const DynIrFunction *f = &c->ir->functions[e->integer];
    if (f->foreign || f->variadic || f->body_count != 1 ||
        f->param_count > 32 || f->param_count != e->item_count ||
        f->body_start >= c->ir->child_count)
      return false;
    const DynIrStmt *s = &c->ir->statements[c->ir->children[f->body_start]];
    if (s->kind != DYN_STMT_RETURN)
      return false;
    uint64_t args[32];
    for (unsigned i = 0; i < f->param_count; ++i)
      if (!value(c, c->ir->items[e->item_start + i].expression, &args[i],
                 depth + 1))
        return false;
    Eval nested = *c;
    nested.function = f;
    nested.arguments = args;
    if (c->samples)
      nested.remaining = c->samples[e->integer] >= 100 ? 1024 : 16;
    bool ok = value(&nested, s->expression, out, depth + 1);
    return ok;
  }
  if (e->kind == DYN_EXPR_UNARY) {
    if (!value(c, e->left, &a, depth + 1))
      return false;
    a &= mask;
    if (e->op == DYN_OP_NOT)
      r = !a;
    else if (e->op == DYN_OP_BIT_NOT)
      r = ~a;
    else if (e->op == DYN_OP_NEG) {
      if (!e->wrap && (sign ? a == high : a != 0))
        return false;
      r = 0 - a;
    } else
      return false;
  } else if (e->kind == DYN_EXPR_BINARY) {
    if (!value(c, e->left, &a, depth + 1))
      return false;
    if (e->op == DYN_OP_LOGICAL_AND && !a) {
      *out = 0;
      return true;
    }
    if (e->op == DYN_OP_LOGICAL_OR && a) {
      *out = 1;
      return true;
    }
    if (!value(c, e->right, &b, depth + 1))
      return false;
    const DynIrExpr *left = &c->ir->expressions[e->left];
    unsigned operand_bits = width(c, left->type);
    if (!operand_bits || left->type != c->ir->expressions[e->right].type)
      return false;
    uint64_t omask = UINT64_MAX >> (64 - operand_bits),
             ohigh = UINT64_C(1) << (operand_bits - 1);
    bool osign = signed_type(left->type), overflow = false;
    a &= omask;
    b &= omask;
    switch (e->op) {
    case DYN_OP_ADD:
      r = (a + b) & mask;
      overflow = sign ? (~(a ^ b) & (a ^ r) & high) != 0 : b > mask - a;
      break;
    case DYN_OP_SUB:
      r = (a - b) & mask;
      overflow = sign ? ((a ^ b) & (a ^ r) & high) != 0 : a < b;
      break;
    case DYN_OP_MUL: {
      r = (a * b) & mask;
      uint64_t aa = sign && (a & high) ? (0 - a) & mask : a,
               bb = sign && (b & high) ? (0 - b) & mask : b;
      uint64_t limit = sign ? ((a ^ b) & high ? high : high - 1) : mask;
      overflow = bb && aa > limit / bb;
      break;
    }
    case DYN_OP_BIT_AND:
      r = a & b;
      break;
    case DYN_OP_BIT_OR:
      r = a | b;
      break;
    case DYN_OP_BIT_XOR:
      r = a ^ b;
      break;
    case DYN_OP_EQ:
      r = a == b;
      break;
    case DYN_OP_NE:
      r = a != b;
      break;
    case DYN_OP_LT:
      r = (osign ? (a ^ ohigh) : a) < (osign ? (b ^ ohigh) : b);
      break;
    case DYN_OP_LE:
      r = (osign ? (a ^ ohigh) : a) <= (osign ? (b ^ ohigh) : b);
      break;
    case DYN_OP_GT:
      r = (osign ? (a ^ ohigh) : a) > (osign ? (b ^ ohigh) : b);
      break;
    case DYN_OP_GE:
      r = (osign ? (a ^ ohigh) : a) >= (osign ? (b ^ ohigh) : b);
      break;
    case DYN_OP_LOGICAL_AND:
      r = a && b;
      break;
    case DYN_OP_LOGICAL_OR:
      r = a || b;
      break;
    default:
      return false;
    }
    if (overflow && !e->wrap)
      return false;
  } else
    return false;
  *out = normalize(r, bits, sign);
  return true;
}
/* LLVM text sample profiles have function:total:head headers and indented
   line[.discriminator]: count records. Binary/extended records are rejected;
   this backend uses function totals to budget constant-call specialization. */
static bool profile_number(char **cursor, uint64_t *out) {
  char *p = *cursor, *end;
  if (!isdigit((unsigned char)*p))
    return false;
  errno = 0;
  unsigned long long n = strtoull(p, &end, 10);
  if (errno || end == p)
    return false;
  *cursor = end;
  *out = (uint64_t)n;
  return true;
}
static bool profile_read(const char *path, const DynIrProgram *ir,
                         uint64_t *samples) {
  FILE *f = fopen(path, "r");
  if (!f)
    return false;
  char line[4096];
  bool header = false, ok = true;
  size_t records = 0;
  while (fgets(line, sizeof(line), f)) {
    size_t n = strlen(line);
    if (n == sizeof(line) - 1 && line[n - 1] != '\n') {
      ok = false;
      break;
    }
    while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
      line[--n] = 0;
    if (!n)
      continue;
    char *p = line;
    uint64_t a, b;
    if (isspace((unsigned char)*p)) {
      if (!header) {
        ok = false;
        break;
      }
      while (isspace((unsigned char)*p))
        ++p;
      if (!profile_number(&p, &a)) {
        ok = false;
        break;
      }
      if (*p == '.') {
        ++p;
        if (!profile_number(&p, &b)) {
          ok = false;
          break;
        }
      }
      if (*p++ != ':') {
        ok = false;
        break;
      }
      while (isspace((unsigned char)*p))
        ++p;
      if (!profile_number(&p, &a)) {
        ok = false;
        break;
      }
    } else {
      char *colon = strchr(p, ':');
      if (!colon || colon == p) {
        ok = false;
        break;
      }
      *colon = 0;
      p = colon + 1;
      if (!profile_number(&p, &a) || *p++ != ':' || !profile_number(&p, &b)) {
        ok = false;
        break;
      }
      for (size_t i = 0; i < ir->function_count; ++i) {
        const DynIrFunction *fn = &ir->functions[i];
        if (!strcmp(line, fn->link_name ? fn->link_name : fn->name) ||
            !strcmp(line, fn->name))
          samples[i] = a;
      }
      header = true;
      ++records;
    }
    while (isspace((unsigned char)*p))
      ++p;
    if (*p) {
      ok = false;
      break;
    }
  }
  if (ferror(f))
    ok = false;
  fclose(f);
  return ok && records;
}
/* Direct calls in statement positions can be expanded without changing the IR
   contract. A one-shot loop supplies a lexical cleanup boundary and a common
   exit for multiple returns. Arguments are captured before entering that scope.
   Calls inside larger expressions and deferred call captures remain calls. */
typedef struct {
  const DynIrProgram *in;
  DynIrProgram out;
  size_t expressions_cap, statements_cap, items_cap, children_cap, locals_cap,
      arms_cap;
  uint32_t loop_stride, next_loop;
  unsigned expansions, budget;
  bool failed, leaf_only;
  bool *active;
} Inline;
typedef struct {
  const DynIrFunction *function;
  uint32_t local_base, loop_base, exit_loop, result_local, check_origin;
  bool returns, expand, in_loop;
} InlineScope;
typedef struct {
  uint32_t *ids;
  size_t count, capacity;
} InlineList;
static bool inline_grow(Inline *b, void **array, size_t *capacity, size_t need,
                        size_t element) {
  if (b->failed)
    return false;
  if (need <= *capacity)
    return true;
  if (need > (1u << 22) || element > SIZE_MAX / need) {
    b->failed = true;
    return false;
  }
  size_t n = *capacity ? *capacity : 16;
  while (n < need)
    n *= 2;
  void *p = realloc(*array, n * element);
  if (!p) {
    b->failed = true;
    return false;
  }
  *array = p;
  *capacity = n;
  return true;
}
#define INLINE_APPEND(b, field, cap, value, result)                            \
  do {                                                                         \
    (result) = (uint32_t)(b)->out.field##_count;                               \
    if (inline_grow((b), (void **)&(b)->out.field##s, &(b)->cap,               \
                    (b)->out.field##_count + 1, sizeof(*(b)->out.field##s)))   \
      (b)->out.field##s[(b)->out.field##_count++] = (value);                   \
  } while (0)
static void inline_list(Inline *b, InlineList *list, uint32_t id) {
  if (inline_grow(b, (void **)&list->ids, &list->capacity, list->count + 1,
                  sizeof(*list->ids)))
    list->ids[list->count++] = id;
}
static uint32_t inline_children(Inline *b, InlineList *list) {
  uint32_t start = (uint32_t)b->out.child_count;
  if (inline_grow(b, (void **)&b->out.children, &b->children_cap,
                  b->out.child_count + list->count, sizeof(*b->out.children))) {
    if (list->count)
      memcpy(b->out.children + start, list->ids,
             list->count * sizeof(*list->ids));
    b->out.child_count += list->count;
  }
  free(list->ids);
  list->ids = NULL;
  return start;
}
static uint32_t inline_local(Inline *b, const InlineScope *s, uint32_t id) {
  if (id == UINT32_MAX)
    return id;
  if (id < s->function->local_start ||
      id - s->function->local_start >= s->function->local_count) {
    b->failed = true;
    return UINT32_MAX;
  }
  return s->local_base + id - s->function->local_start;
}
static uint32_t inline_locals(Inline *b, const DynIrFunction *f) {
  uint32_t start = (uint32_t)b->out.local_count;
  if ((uint64_t)f->local_start + f->local_count > b->in->local_count) {
    b->failed = true;
    return start;
  }
  if (inline_grow(b, (void **)&b->out.locals, &b->locals_cap,
                  b->out.local_count + f->local_count,
                  sizeof(*b->out.locals))) {
    if (f->local_count)
      memcpy(b->out.locals + start, b->in->locals + f->local_start,
             f->local_count * sizeof(*b->out.locals));
    b->out.local_count += f->local_count;
  }
  return start;
}
static uint32_t inline_loop_base(Inline *b) {
  uint32_t base = b->next_loop;
  if (b->next_loop > UINT32_MAX - b->loop_stride)
    b->failed = true;
  else
    b->next_loop += b->loop_stride;
  return base;
}
/* Keep constant subtrees shared. Cloning their IR identities would duplicate
   the backend's literal pool even when the enclosing function is unchanged. */
static bool inline_shared_expr(const DynIrProgram *ir, DynExprId id,
                               unsigned depth, unsigned *remaining,
                               bool needs_origin) {
  if (id == DYN_NO_EXPR)
    return true;
  if (depth > 32 || id >= ir->expression_count || !*remaining)
    return false;
  --*remaining;
  const DynIrExpr *e = &ir->expressions[id];
  switch (e->kind) {
  case DYN_EXPR_INT: case DYN_EXPR_FLOAT: case DYN_EXPR_BOOL:
  case DYN_EXPR_CHAR: case DYN_EXPR_STRING: case DYN_EXPR_NIL:
  case DYN_EXPR_GLOBAL: case DYN_EXPR_FUNCTION:
    return true;
  case DYN_EXPR_STRUCT:
    /* Defaults run even when explicit fields subsequently replace them. */
    if (needs_origin) {
      if (!dyn_type_is_struct(e->type) ||
          e->type - DYN_TYPE_STRUCT_BASE >= ir->struct_count)
        return false;
      const DynIrStruct *record = &ir->structs[e->type - DYN_TYPE_STRUCT_BASE];
      for (uint32_t i = 0; i < record->field_count; ++i)
        if (ir->fields[record->field_start + i].default_expression != DYN_NO_EXPR)
          return false;
    }
    break;
  case DYN_EXPR_ARRAY:
    break;
  case DYN_EXPR_UNARY: case DYN_EXPR_BINARY: case DYN_EXPR_CONVERT:
  case DYN_EXPR_FIELD: case DYN_EXPR_CAST: case DYN_EXPR_BITCAST:
  case DYN_EXPR_ENUM:
    /* The regular folder has already replaced evaluable scalar constants.
       Clone the remaining operations so any failure retains its callee. */
    if (needs_origin)
      return false;
    break;
  default:
    return false;
  }
  if (!inline_shared_expr(ir, e->left, depth + 1, remaining, needs_origin) ||
      !inline_shared_expr(ir, e->right, depth + 1, remaining, needs_origin) ||
      (uint64_t)e->item_start + e->item_count > ir->item_count)
    return false;
  for (uint32_t i = 0; i < e->item_count; ++i)
    if (!inline_shared_expr(ir, ir->items[e->item_start + i].expression,
                            depth + 1, remaining, needs_origin))
      return false;
  return true;
}
static DynExprId inline_expr(Inline *b, const InlineScope *scope, DynExprId id,
                             unsigned depth) {
  if (id == DYN_NO_EXPR || b->failed)
    return id;
  if (id >= b->in->expression_count || depth > 1024) {
    b->failed = true;
    return DYN_NO_EXPR;
  }
  unsigned shared_budget = 1024;
  if (inline_shared_expr(b->in, id, 0, &shared_budget,
                         scope->check_origin != 0))
    return id;
  DynIrExpr e = b->in->expressions[id];
  if (!e.check_origin)
    e.check_origin = scope->check_origin;
  if (e.kind == DYN_EXPR_NAME)
    e.integer = inline_local(b, scope, (uint32_t)e.integer);
  if (e.kind == DYN_EXPR_SLICE)
    e.integer = inline_expr(b, scope, (DynExprId)e.integer, depth + 1);
  e.left = inline_expr(b, scope, e.left, depth + 1);
  e.right = inline_expr(b, scope, e.right, depth + 1);
  if ((uint64_t)e.item_start + e.item_count > b->in->item_count) {
    b->failed = true;
    return DYN_NO_EXPR;
  }
  /* Reserve each contiguous item range before recursively cloning values. */
  uint32_t start = (uint32_t)b->out.item_count;
  if (!inline_grow(b, (void **)&b->out.items, &b->items_cap,
                   b->out.item_count + e.item_count, sizeof(*b->out.items)))
    return DYN_NO_EXPR;
  b->out.item_count += e.item_count;
  for (uint32_t i = 0; i < e.item_count; ++i) {
    DynIrItem item = b->in->items[e.item_start + i];
    item.expression = inline_expr(b, scope, item.expression, depth + 1);
    b->out.items[start + i] = item;
  }
  e.item_start = start;
  uint32_t result;
  INLINE_APPEND(b, expression, expressions_cap, e, result);
  return result;
}
static DynExprId inline_name(Inline *b, uint32_t local, DynSpan span) {
  DynIrExpr e = {.kind = DYN_EXPR_NAME,
                 .type = b->out.locals[local].type,
                 .integer = local,
                 .left = DYN_NO_EXPR,
                 .right = DYN_NO_EXPR,
                 .span = span};
  uint32_t id;
  INLINE_APPEND(b, expression, expressions_cap, e, id);
  return id;
}
static void inline_statement(Inline *b, InlineList *list, DynIrStmt s) {
  uint32_t id;
  INLINE_APPEND(b, statement, statements_cap, s, id);
  inline_list(b, list, id);
}
static DynIrStmt inline_empty(DynStmtKind kind, DynSpan span) {
  return (DynIrStmt){.kind = kind,
                     .expression = DYN_NO_EXPR,
                     .target = DYN_NO_EXPR,
                     .local_id = UINT32_MAX,
                     .span = span};
}
static unsigned inline_cost(const DynIrProgram *ir, uint32_t start,
                            uint32_t count, unsigned depth) {
  if (depth > 32 || (uint64_t)start + count > ir->child_count)
    return 257;
  unsigned cost = 0;
  for (uint32_t i = 0; i < count && cost <= 256; ++i) {
    uint32_t id = ir->children[start + i];
    if (id >= ir->statement_count)
      return 257;
    const DynIrStmt *s = &ir->statements[id];
    cost += 1 + inline_cost(ir, s->body_start, s->body_count, depth + 1) +
            inline_cost(ir, s->else_start, s->else_count, depth + 1);
    if ((uint64_t)s->case_arm_start + s->case_arm_count > ir->case_arm_count)
      return 257;
    for (uint32_t j = 0; j < s->case_arm_count && cost <= 256; ++j) {
      const DynIrCaseArm *arm = &ir->case_arms[s->case_arm_start + j];
      cost += inline_cost(ir, arm->body_start, arm->body_count, depth + 1);
    }
  }
  return cost;
}
/* Default optimization expands only small, straight-line leaves in loops.
   Count expressions, not statements: a single return can contain a large tree.
   Capturing parameters still preserves argument order, aliasing and checks. */
static bool inline_leaf_expr(const DynIrProgram *ir, DynExprId id,
                             unsigned *remaining) {
  if (id == DYN_NO_EXPR)
    return true;
  if (id >= ir->expression_count || !*remaining)
    return false;
  --*remaining;
  const DynIrExpr *e = &ir->expressions[id];
  switch (e->kind) {
  case DYN_EXPR_INT: case DYN_EXPR_FLOAT: case DYN_EXPR_BOOL:
  case DYN_EXPR_CHAR: case DYN_EXPR_NIL: case DYN_EXPR_NAME:
    return true;
  case DYN_EXPR_UNARY:
    if (e->op == DYN_OP_ADDRESS || e->op == DYN_OP_DEREF)
      return false;
    break;
  case DYN_EXPR_BINARY: case DYN_EXPR_CONVERT: case DYN_EXPR_STRUCT:
  case DYN_EXPR_FIELD: case DYN_EXPR_CAST: case DYN_EXPR_BITCAST:
    break;
  default:
    return false;
  }
  if (!inline_leaf_expr(ir, e->left, remaining) ||
      !inline_leaf_expr(ir, e->right, remaining) ||
      (uint64_t)e->item_start + e->item_count > ir->item_count)
    return false;
  for (uint32_t i = 0; i < e->item_count; ++i)
    if (!inline_leaf_expr(ir, ir->items[e->item_start + i].expression,
                          remaining))
      return false;
  return true;
}
static bool inline_small_type(const DynIrProgram *ir, DynType type) {
  if (type < DYN_TYPE_STRUCT_BASE)
    return true;
  if (type < DYN_TYPE_POINTER_BASE) {
    size_t index = type - DYN_TYPE_STRUCT_BASE;
    return index < ir->struct_count && ir->structs[index].size <= 32;
  }
  return type < DYN_TYPE_ARRAY_BASE;
}
static bool inline_leaf(const DynIrProgram *ir, const DynIrFunction *f) {
  if (f->body_count != 1 || f->param_count > 4 ||
      f->local_count != f->param_count ||
      f->body_start >= ir->child_count ||
      !inline_small_type(ir, f->return_type))
    return false;
  for (uint32_t i = 0; i < f->param_count; ++i)
    if (!inline_small_type(ir, ir->params[f->param_start + i].type))
      return false;
  uint32_t id = ir->children[f->body_start];
  if (id >= ir->statement_count || ir->statements[id].kind != DYN_STMT_RETURN)
    return false;
  unsigned remaining = 24;
  return inline_leaf_expr(ir, ir->statements[id].expression, &remaining);
}
static bool inline_simple_target(const DynIrProgram *ir, DynExprId id) {
  if (id == DYN_NO_EXPR)
    return true;
  if (id >= ir->expression_count)
    return false;
  const DynIrExpr *e = &ir->expressions[id];
  if (e->kind == DYN_EXPR_NAME || e->kind == DYN_EXPR_GLOBAL)
    return true;
  return e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_DEREF &&
         e->left < ir->expression_count &&
         ir->expressions[e->left].kind == DYN_EXPR_NAME;
}
/* Snapshot the checked assignment address before argument capture. Merely
   requiring read-only arguments would still reorder null/alignment failures
   against checks in the arguments or the inlined body. */
static DynExprId inline_capture_target(Inline *b, const InlineScope *scope,
                                       DynExprId id, InlineList *list) {
  const DynIrExpr *target = &b->in->expressions[id];
  DynType pointer_type = b->in->expressions[target->left].type;
  DynIrLocal local = {.name = "__inline_target", .type = pointer_type};
  uint32_t local_id;
  INLINE_APPEND(b, local, locals_cap, local, local_id);
  if (b->failed)
    return DYN_NO_EXPR;
  DynIrExpr address = {.kind = DYN_EXPR_UNARY, .type = pointer_type,
                        .op = DYN_OP_ADDRESS,
                        .left = inline_expr(b, scope, id, 0),
                        .right = DYN_NO_EXPR, .span = target->span,
                        .check_origin = target->check_origin ? target->check_origin :
                                        scope->check_origin};
  uint32_t address_id;
  INLINE_APPEND(b, expression, expressions_cap, address, address_id);
  DynIrStmt capture = inline_empty(DYN_STMT_LOCAL, target->span);
  capture.local_id = local_id;
  capture.expression = address_id;
  inline_statement(b, list, capture);
  DynIrExpr dereference = *target;
  if (!dereference.check_origin)
    dereference.check_origin = scope->check_origin;
  dereference.left = inline_name(b, local_id, target->span);
  uint32_t result;
  INLINE_APPEND(b, expression, expressions_cap, dereference, result);
  return result;
}
static void inline_block(Inline *, const InlineScope *, uint32_t, uint32_t,
                         InlineList *, unsigned);
static bool inline_call(Inline *b, const InlineScope *scope,
                        const DynIrExpr *call, InlineList *list,
                        DynExprId *result, unsigned depth) {
  if (!scope->expand || call->kind != DYN_EXPR_CALL ||
      call->integer >= b->in->function_count || depth > 16 ||
      b->active[call->integer])
    return false;
  const DynIrFunction *f = &b->in->functions[call->integer];
  if (f->foreign || f->generic || f->variadic || f->is_main ||
      f->local_count > 128 || call->item_count != f->param_count ||
      (uint64_t)call->item_start + call->item_count > b->in->item_count ||
      (uint64_t)f->param_start + f->param_count > b->in->param_count)
    return false;
  if (b->leaf_only && (!scope->in_loop || !inline_leaf(b->in, f)))
    return false;
  unsigned cost = inline_cost(b->in, f->body_start, f->body_count, 0);
  if (cost > 64 || cost + f->param_count + 2 > b->budget)
    return false;
  b->budget -= cost + f->param_count + 2;
  InlineScope nested = {.function = f,
                        .local_base = inline_locals(b, f),
                        .loop_base = inline_loop_base(b),
                        .returns = true,
                        .check_origin = (uint32_t)call->integer + 1,
                        .expand = true,
                        .result_local = UINT32_MAX};
  nested.exit_loop = inline_loop_base(b);
  if (f->return_type != DYN_TYPE_VOID) {
    DynIrLocal local = {.name = "__inline_result", .type = f->return_type};
    INLINE_APPEND(b, local, locals_cap, local, nested.result_local);
  }
  if (b->failed)
    return true;
  for (uint32_t i = 0; i < f->param_count; ++i) {
    DynIrStmt s = inline_empty(DYN_STMT_LOCAL, call->span);
    s.local_id =
        inline_local(b, &nested, b->in->params[f->param_start + i].local_id);
    s.expression =
        inline_expr(b, scope, b->in->items[call->item_start + i].expression, 0);
    inline_statement(b, list, s);
  }
  InlineList body = {0};
  b->active[call->integer] = true;
  inline_block(b, &nested, f->body_start, f->body_count, &body, depth + 1);
  b->active[call->integer] = false;
  DynIrStmt exit = inline_empty(DYN_STMT_BREAK, call->span);
  exit.target_loop_id = nested.exit_loop;
  inline_statement(b, &body, exit);
  DynIrStmt loop = inline_empty(DYN_STMT_FOR, call->span);
  loop.loop_id = nested.exit_loop;
  loop.body_count = (uint32_t)body.count;
  loop.body_start = inline_children(b, &body);
  inline_statement(b, list, loop);
  *result = nested.result_local == UINT32_MAX
                ? DYN_NO_EXPR
                : inline_name(b, nested.result_local, call->span);
  ++b->expansions;
  return true;
}
static void inline_block(Inline *b, const InlineScope *scope, uint32_t start,
                         uint32_t count, InlineList *list, unsigned depth) {
  if (b->failed)
    return;
  if (depth > 1024 || (uint64_t)start + count > b->in->child_count) {
    b->failed = true;
    return;
  }
  for (uint32_t i = 0; i < count && !b->failed; ++i) {
    uint32_t id = b->in->children[start + i];
    if (id >= b->in->statement_count) {
      b->failed = true;
      break;
    }
    DynIrStmt s = b->in->statements[id];
    if (!s.check_origin) s.check_origin = scope->check_origin;
    DynExprId value = DYN_NO_EXPR;
    bool eligible =
        s.kind == DYN_STMT_LOCAL || s.kind == DYN_STMT_RETURN ||
        s.kind == DYN_STMT_EXPR || s.kind == DYN_STMT_IF ||
        (s.kind == DYN_STMT_ASSIGN && s.assignment_op == DYN_OP_NONE &&
         inline_simple_target(b->in, s.target));
    InlineList expansion = {0};
    bool expanded = eligible && s.expression < b->in->expression_count &&
                    inline_call(b, scope, &b->in->expressions[s.expression],
                                &expansion, &value, depth);
    bool captured = expanded && s.kind == DYN_STMT_ASSIGN &&
                    s.target < b->in->expression_count &&
                    b->in->expressions[s.target].kind == DYN_EXPR_UNARY;
    if (captured)
      s.target = inline_capture_target(b, scope, s.target, list);
    for (size_t j = 0; j < expansion.count; ++j)
      inline_list(b, list, expansion.ids[j]);
    free(expansion.ids);
    if (b->failed)
      return;
    if (expanded && s.kind == DYN_STMT_EXPR && value == DYN_NO_EXPR)
      continue;
    s.expression = expanded ? value : inline_expr(b, scope, s.expression, 0);
    if (!captured)
      s.target = inline_expr(b, scope, s.target, 0);
    if (s.kind == DYN_STMT_LOCAL || s.kind == DYN_STMT_ASSIGN ||
        s.kind == DYN_STMT_FOR) {
      /* Non-binding loops use a sentinel local id. */
      if (s.kind != DYN_STMT_FOR || s.for_range || s.target != DYN_NO_EXPR)
        s.local_id = inline_local(b, scope, s.local_id);
    }
    if (s.kind == DYN_STMT_FOR)
      s.loop_id += scope->loop_base;
    if (s.kind == DYN_STMT_BREAK || s.kind == DYN_STMT_CONTINUE)
      s.target_loop_id += scope->loop_base;
    InlineScope child = *scope;
    if (s.kind == DYN_STMT_FOR)
      child.in_loop = true;
    if (s.kind == DYN_STMT_DEFER)
      child.expand = false;
    InlineList body = {0}, otherwise = {0};
    inline_block(b, &child, s.body_start, s.body_count, &body, depth + 1);
    inline_block(b, &child, s.else_start, s.else_count, &otherwise, depth + 1);
    s.body_count = (uint32_t)body.count;
    s.body_start = inline_children(b, &body);
    s.else_count = (uint32_t)otherwise.count;
    s.else_start = inline_children(b, &otherwise);
    if ((uint64_t)s.case_arm_start + s.case_arm_count > b->in->case_arm_count) {
      b->failed = true;
      break;
    }
    uint32_t arm_start = (uint32_t)b->out.case_arm_count;
    if (!inline_grow(b, (void **)&b->out.case_arms, &b->arms_cap,
                     b->out.case_arm_count + s.case_arm_count,
                     sizeof(*b->out.case_arms)))
      break;
    b->out.case_arm_count += s.case_arm_count;
    for (uint32_t j = 0; j < s.case_arm_count; ++j) {
      DynIrCaseArm arm = b->in->case_arms[s.case_arm_start + j];
      arm.local_id = inline_local(b, scope, arm.local_id);
      InlineList arm_body = {0};
      inline_block(b, scope, arm.body_start, arm.body_count, &arm_body,
                   depth + 1);
      arm.body_count = (uint32_t)arm_body.count;
      arm.body_start = inline_children(b, &arm_body);
      b->out.case_arms[arm_start + j] = arm;
    }
    s.case_arm_start = arm_start;
    if (s.kind == DYN_STMT_RETURN && scope->returns) {
      if (scope->result_local != UINT32_MAX) {
        DynIrStmt assign = inline_empty(DYN_STMT_ASSIGN, s.span);
        assign.local_id = scope->result_local;
        assign.expression = s.expression;
        inline_statement(b, list, assign);
      }
      DynIrStmt exit = inline_empty(DYN_STMT_BREAK, s.span);
      exit.target_loop_id = scope->exit_loop;
      inline_statement(b, list, exit);
    } else
      inline_statement(b, list, s);
  }
}
static void inline_free(DynIrProgram *ir) {
  free(ir->expressions);
  free(ir->statements);
  free(ir->items);
  free(ir->children);
  free(ir->locals);
  free(ir->params);
  free(ir->functions);
  free(ir->case_arms);
  free(ir->unstable_locals);
  free(ir->local_statements);
}
static bool inline_program(DynNativeOptimization *o, bool leaf_only) {
  Inline b = {.in = &o->ir, .out = o->ir, .loop_stride = 1,
              .leaf_only = leaf_only};
  b.out.expressions = NULL;
  b.out.statements = NULL;
  b.out.items = NULL;
  b.out.children = NULL;
  b.out.locals = NULL;
  b.out.params = NULL;
  b.out.functions = NULL;
  b.out.case_arms = NULL;
  b.out.unstable_locals = NULL;
  b.out.local_statements = NULL;
  b.out.local_count = 0;
  b.out.child_count = 0;
  b.out.case_arm_count = 0;
  b.active = calloc(o->ir.function_count ? o->ir.function_count : 1,
                    sizeof(*b.active));
  if (!b.active)
    return false;
#define INLINE_COPY(field, count, cap)                                         \
  do {                                                                         \
    if (inline_grow(&b, (void **)&b.out.field, &b.cap, b.in->count,            \
                    sizeof(*b.out.field)) &&                                   \
        b.in->count)                                                           \
      memcpy(b.out.field, b.in->field, b.in->count * sizeof(*b.out.field));    \
  } while (0)
  INLINE_COPY(expressions, expression_count, expressions_cap);
  INLINE_COPY(statements, statement_count, statements_cap);
  INLINE_COPY(items, item_count, items_cap);
  size_t bytes = (b.in->function_count ? b.in->function_count : 1) *
                 sizeof(*b.out.functions);
  b.out.functions = malloc(bytes);
  if (b.out.functions && b.in->function_count)
    memcpy(b.out.functions, b.in->functions, bytes);
  bytes = (b.in->param_count ? b.in->param_count : 1) * sizeof(*b.out.params);
  b.out.params = malloc(bytes);
  if (b.out.params && b.in->param_count)
    memcpy(b.out.params, b.in->params, bytes);
  if (!b.out.functions || !b.out.params)
    b.failed = true;
  for (size_t i = 0; i < b.in->statement_count; ++i) {
    const DynIrStmt *s = &b.in->statements[i];
    if (s->kind == DYN_STMT_FOR && s->loop_id >= b.loop_stride) {
      if (s->loop_id == UINT32_MAX)
        b.failed = true;
      else
        b.loop_stride = s->loop_id + 1;
    }
  }
  for (size_t i = 0; i < b.in->function_count && !b.failed; ++i) {
    const DynIrFunction *f = &b.in->functions[i];
    if (f->foreign || f->generic)
      continue;
    InlineScope scope = {.function = f,
                         .local_base = inline_locals(&b, f),
                         .loop_base = inline_loop_base(&b),
                         .expand = true};
    b.budget = leaf_only ? 24 : 256;
    b.active[i] = true;
    InlineList body = {0};
    inline_block(&b, &scope, f->body_start, f->body_count, &body, 0);
    b.active[i] = false;
    DynIrFunction *dest = &b.out.functions[i];
    dest->body_count = (uint32_t)body.count;
    dest->body_start = inline_children(&b, &body);
    dest->local_start = scope.local_base;
    dest->local_count = (uint32_t)b.out.local_count - scope.local_base;
    if (f->variadic)
      dest->variadic_local_id = inline_local(&b, &scope, f->variadic_local_id);
    for (uint32_t j = 0; j < f->param_count; ++j)
      b.out.params[f->param_start + j].local_id =
          inline_local(&b, &scope, b.in->params[f->param_start + j].local_id);
  }
  b.out.unstable_locals = malloc(b.out.local_count ? b.out.local_count : 1);
  b.out.local_statements = calloc(b.out.local_count ? b.out.local_count : 1,
                                  sizeof(*b.out.local_statements));
  if (!b.out.unstable_locals || !b.out.local_statements)
    b.failed = true;
  if (!b.failed)
    memset(b.out.unstable_locals, 1, b.out.local_count);
  free(b.active);
  if (!b.failed && !b.expansions) {
    inline_free(&b.out);
    return true;
  }
  if (b.failed) {
    inline_free(&b.out);
    return false;
  }
  free(o->ir.expressions);
  free(o->ir.statements);
  o->ir = b.out;
  o->inlined = b.expansions;
  o->owns_expansion = true;
  return true;
#undef INLINE_COPY
}
#undef INLINE_APPEND

void dyn_native_optimization_free(DynNativeOptimization *o) {
  if (o->owns_expansion) {
    inline_free(&o->ir);
    memset(o, 0, sizeof(*o));
    return;
  }
  free(o->ir.expressions);
  free(o->ir.statements);
  memset(o, 0, sizeof(*o));
}
bool dyn_native_optimize(const DynSource *source, const DynIrProgram *input,
                         unsigned level, DynNativeOptimization *o) {
  memset(o, 0, sizeof(*o));
  o->ir = *input;
  o->ir.expressions = NULL;
  o->ir.statements = NULL;
  if (level < 1 || level > 3)
    return false;
  o->ir.expressions =
      malloc((input->expression_count ? input->expression_count : 1) *
             sizeof(*input->expressions));
  o->ir.statements =
      malloc((input->statement_count ? input->statement_count : 1) *
             sizeof(*input->statements));
  if (!o->ir.expressions || !o->ir.statements) {
    dyn_native_optimization_free(o);
    return false;
  }
  if (input->expression_count)
    memcpy(o->ir.expressions, input->expressions,
           input->expression_count * sizeof(*input->expressions));
  if (input->statement_count)
    memcpy(o->ir.statements, input->statements,
           input->statement_count * sizeof(*input->statements));
  Eval c = {.ir = input,
            .level = level,
            .pointer_bits = 8 * dyn_target_pointer_bytes(
                                    dyn_context_target(&source->context))};
  uint64_t *samples = NULL;
  const DynOptimization *policy = source->context.optimization;
  if (policy && policy->sample_profile) {
    samples = calloc(input->function_count ? input->function_count : 1,
                     sizeof(*samples));
    if (!samples || !profile_read(policy->sample_profile, input, samples)) {
      fprintf(stderr,
              "error: independent sample profile requires nonempty "
              "function:total:head text records and numeric line samples\n");
      free(samples);
      dyn_native_optimization_free(o);
      return false;
    }
    c.samples = samples;
    c.level = 3;
  }
  for (size_t i = 0; i < input->expression_count; ++i) {
    const DynIrExpr *e = &input->expressions[i];
    if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_BOOL ||
        e->kind == DYN_EXPR_CHAR)
      continue;
    uint64_t result;
    c.remaining = 256;
    if (!value(&c, (DynExprId)i, &result, 0))
      continue;
    DynIrExpr *dest = &o->ir.expressions[i];
    dest->kind = e->type == DYN_TYPE_BOOL ? DYN_EXPR_BOOL : DYN_EXPR_INT;
    dest->integer = result;
    dest->boolean = result != 0;
    if (e->kind == DYN_EXPR_NAME)
      ++o->propagated;
    else if (e->kind == DYN_EXPR_CALL)
      ++o->calls;
    else
      ++o->folded;
  }
  if (level >= 2)
    for (size_t i = 0; i < input->statement_count; ++i) {
      DynIrStmt *s = &o->ir.statements[i];
      if (s->kind != DYN_STMT_IF || s->expression >= input->expression_count)
        continue;
      const DynIrExpr *e = &o->ir.expressions[s->expression];
      if (e->kind != DYN_EXPR_BOOL)
        continue;
      /* Preserve the chosen block's lexical scope and deferred actions. */
      if (e->boolean)
        s->else_count = 0;
      else
        s->body_count = 0;
      ++o->branches;
    }
  if (level >= 2 && !inline_program(o, level == 2)) {
    free(samples);
    dyn_native_optimization_free(o);
    return false;
  }
  if (policy && policy->remarks)
    fprintf(stderr,
            "remark: independent O%u: %zu scalar folds, %zu immutable loads, "
            "%zu constant branches, %zu constant calls\n",
            level, o->folded, o->propagated, o->branches, o->calls);
  if (samples && policy->remarks)
    fprintf(stderr, "remark: samples from profile control constant-call "
                    "budgets (hot 1024, cold 16 nodes)\n");
  if (policy && policy->remarks && level >= 2)
    fprintf(stderr,
            "remark: %zu direct calls inlined with argument capture and "
            "lexical cleanup\n",
            o->inlined);
  free(samples);
  return true;
}
