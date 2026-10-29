#include "native_opt.h"
#include "dyn_timing.h"
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
   Calls outside unconditional expression spines and deferred call captures remain calls. */
/* Expressions and statements are rebuilt by appending to the arrays they
   came from, so in reads the original records through view, which follows
   those arrays when they move. Never hold a pointer into them across an
   append. */
typedef struct {
  const DynIrProgram *in;
  DynIrProgram view, out;
  size_t expressions_cap, statements_cap, items_cap, children_cap, locals_cap,
      arms_cap;
  uint32_t loop_stride, next_loop;
  unsigned expansions, budget, resource_budget, reserved_growth, reserved_resources;
  unsigned *costs;
  bool failed, leaf_only, byte_fast;
  bool *active;
  /* Locals whose address is taken anywhere; a call may change them. */
  bool *addressed;
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
  b->view.expressions = b->out.expressions;
  b->view.statements = b->out.statements;
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
/* Saturating estimates include expression/item trees and dispatch records.
   Even an empty case arm costs a copied record and a dispatch alternative. */
static unsigned inline_expression_cost(const DynIrProgram *ir, DynExprId id,
                                       unsigned depth) {
  if (id == DYN_NO_EXPR) return 0;
  if (id >= ir->expression_count || depth > 32) return 257;
  const DynIrExpr *e = &ir->expressions[id];
  unsigned cost = e->kind == DYN_EXPR_CALL ? 8 : 1;
  cost += inline_expression_cost(ir, e->left, depth + 1);
  if (cost > 256) return 257;
  cost += inline_expression_cost(ir, e->right, depth + 1);
  if (e->kind == DYN_EXPR_SLICE)
    cost += inline_expression_cost(ir, (DynExprId)e->integer, depth + 1);
  if ((uint64_t)e->item_start + e->item_count > ir->item_count) return 257;
  for (uint32_t i = 0; i < e->item_count && cost <= 256; ++i)
    cost += 1 + inline_expression_cost(ir, ir->items[e->item_start + i].expression, depth + 1);
  return cost > 256 ? 257 : cost;
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
    cost += 1 + inline_expression_cost(ir, s->expression, 0) +
            inline_expression_cost(ir, s->target, 0) +
            inline_cost(ir, s->body_start, s->body_count, depth + 1) +
            inline_cost(ir, s->else_start, s->else_count, depth + 1);
    if ((uint64_t)s->case_arm_start + s->case_arm_count > ir->case_arm_count)
      return 257;
    for (uint32_t j = 0; j < s->case_arm_count && cost <= 256; ++j) {
      const DynIrCaseArm *arm = &ir->case_arms[s->case_arm_start + j];
      cost += 1 + inline_cost(ir, arm->body_start, arm->body_count, depth + 1);
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
/* A typed dereference must not strengthen a packed-field store's alignment
   requirement. Decline packed ancestry, including arrays nested in a packed
   field. Ordinary indexing relies on the same element-alignment contract as
   the original slice/array access. Bound the ancestry walk independently. */
static bool inline_target_aligned(const DynIrProgram *ir, DynExprId id,
                                   unsigned depth) {
  if (depth > 32 || id >= ir->expression_count) return false;
  const DynIrExpr *e = &ir->expressions[id];
  if (e->kind == DYN_EXPR_FIELD) {
    if (e->left >= ir->expression_count) return false;
    DynType type = ir->expressions[e->left].type;
    if (dyn_type_is_pointer(type)) {
      size_t index = (size_t)(type - DYN_TYPE_POINTER_BASE);
      if (index >= ir->pointer_count) return false;
      type = ir->pointers[index].pointee;
    }
    if (!dyn_type_is_struct(type) ||
        type - DYN_TYPE_STRUCT_BASE >= ir->struct_count ||
        ir->structs[type - DYN_TYPE_STRUCT_BASE].packed) return false;
    return inline_target_aligned(ir, e->left, depth + 1);
  }
  if (e->kind == DYN_EXPR_INDEX)
    return inline_target_aligned(ir, e->left, depth + 1);
  return true;
}
/* Reuse canonical pointer types; optimization never mutates borrowed type
   tables. Large tables retain the call instead of paying an unbounded search. */
static DynType inline_target_pointer(const DynIrProgram *ir, DynExprId id) {
  if (id >= ir->expression_count) return DYN_TYPE_VOID;
  const DynIrExpr *e = &ir->expressions[id];
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_DEREF &&
      e->left < ir->expression_count)
    return ir->expressions[e->left].type;
  if ((e->kind != DYN_EXPR_INDEX && e->kind != DYN_EXPR_FIELD) ||
      ir->pointer_count > 1024 || !inline_target_aligned(ir, id, 0))
    return DYN_TYPE_VOID;
  for (size_t i = 0; i < ir->pointer_count; ++i)
    if (ir->pointers[i].pointee == e->type && !ir->pointers[i].is_const)
      return DYN_TYPE_POINTER_BASE + (DynType)i;
  return DYN_TYPE_VOID;
}
static bool inline_simple_target(const DynIrProgram *ir, DynExprId id) {
  if (id == DYN_NO_EXPR) return true;
  if (id >= ir->expression_count) return false;
  const DynIrExpr *e = &ir->expressions[id];
  return e->kind == DYN_EXPR_NAME || e->kind == DYN_EXPR_GLOBAL ||
         inline_target_pointer(ir, id) != DYN_TYPE_VOID;
}
/* Snapshot the checked assignment address before argument capture. Merely
   requiring read-only arguments would still reorder null/alignment failures
   against checks in the arguments or the inlined body. */
static DynExprId inline_capture_target(Inline *b, const InlineScope *scope,
                                       DynExprId id, InlineList *list) {
  const DynIrExpr original = b->in->expressions[id], *target = &original;
  DynType pointer_type = inline_target_pointer(b->in, id);
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
  DynIrExpr dereference = {.kind = DYN_EXPR_UNARY, .op = DYN_OP_DEREF,
                            .type = target->type, .left = DYN_NO_EXPR,
                            .right = DYN_NO_EXPR, .span = target->span,
                            .check_origin = target->check_origin};
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
                        const DynIrExpr *site, InlineList *list,
                        DynExprId *result, unsigned depth) {
  const DynIrExpr original = *site, *call = &original;
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
  /* Preserve the call for target byte-scan lowering; other targets retain
     their existing scalar inlining decisions. */
  if (b->byte_fast && f->byte_intrinsic != DYN_BYTE_INTRINSIC_NONE)
    return false;
  if (b->leaf_only && (!scope->in_loop || !inline_leaf(b->in, f)))
    return false;
  unsigned cost = b->costs[call->integer];
  /* Copy the entire local table, including unused entries. Each local also
     gets an unstable_locals and local_statements entry in the output. */
  unsigned growth = cost + f->param_count + 2;
  unsigned resources = 4 * cost + 3 * f->local_count +
                       2 * f->param_count + 16;
  bool hot = !b->leaf_only && !scope->returns && scope->in_loop && cost <= 16;
  if (cost > 64 || growth > b->budget || resources > b->resource_budget ||
      (!hot && (growth > b->budget - b->reserved_growth ||
                resources > b->resource_budget - b->reserved_resources)))
    return false;
  if (hot) {
    b->reserved_growth -= growth < b->reserved_growth ? growth : b->reserved_growth;
    b->reserved_resources -= resources < b->reserved_resources ? resources : b->reserved_resources;
  }
  b->budget -= growth;
  b->resource_budget -= resources;
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
/* Expand only an unconditional first-evaluated call spine. A literal left
   sibling permits descent into a binary right operand; logical right operands
   never do. Other siblings retain their position after the expanded call.
   The 32-node cap bounds work and keeps wrapper copying in the ordinary rebuild
   baseline: these nodes replace original nodes, not extra expansion records. */
static bool inline_literal(const DynIrExpr *e) {
  return e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_CHAR ||
         e->kind == DYN_EXPR_FLOAT || e->kind == DYN_EXPR_BOOL ||
         e->kind == DYN_EXPR_NIL;
}
/* Evaluating a call before this operand cannot change the operand's value
   or trap order: a literal, or a local no pointer can reach. */
static bool inline_stable_operand(const DynIrProgram *ir, const bool *addressed, DynExprId id) {
  if (id >= ir->expression_count) return false;
  const DynIrExpr *e = &ir->expressions[id];
  if (inline_literal(e)) return true;
  return addressed && e->kind == DYN_EXPR_NAME && (uint64_t)e->integer < ir->local_count &&
         !addressed[e->integer];
}
static DynExprId inline_spine(const DynIrProgram *ir, const bool *addressed, DynExprId id,
                               DynExprId wrappers[32], bool right[32],
                               unsigned *wrapper_count) {
  unsigned count = 0;
  while (id < ir->expression_count) {
    const DynIrExpr *e = &ir->expressions[id];
    bool conversion = e->kind == DYN_EXPR_CAST || e->kind == DYN_EXPR_CONVERT ||
                      e->kind == DYN_EXPR_BITCAST;
    bool unary = e->kind == DYN_EXPR_UNARY &&
                 (e->op == DYN_OP_NEG || e->op == DYN_OP_NOT || e->op == DYN_OP_BIT_NOT);
    bool binary = e->kind == DYN_EXPR_BINARY;
    if (!conversion && !unary && !binary) break;
    if (count == 32 || e->item_count || (!binary && e->right != DYN_NO_EXPR))
      return DYN_NO_EXPR;
    bool descend_right = binary && inline_stable_operand(ir, addressed, e->left) &&
                         e->op != DYN_OP_LOGICAL_AND && e->op != DYN_OP_LOGICAL_OR;
    wrappers[count] = id;
    right[count++] = descend_right;
    id = descend_right ? e->right : e->left;
  }
  *wrapper_count = count;
  return id;
}
static bool inline_cast_call(Inline *b, const InlineScope *scope,
                             DynExprId id, InlineList *list,
                             DynExprId *result, unsigned depth) {
  DynExprId wrappers[32];
  bool right[32];
  unsigned count = 0;
  id = inline_spine(b->in, b->addressed, id, wrappers, right, &count);
  if (id >= b->in->expression_count ||
      !inline_call(b, scope, &b->in->expressions[id], list, result, depth))
    return false;
  while (count && !b->failed) {
    --count;
    DynIrExpr e = b->in->expressions[wrappers[count]];
    if (!e.check_origin) e.check_origin = scope->check_origin;
    if (right[count]) {
      e.left = inline_expr(b, scope, e.left, 0);
      e.right = *result;
    } else {
      e.left = *result;
      e.right = inline_expr(b, scope, e.right, 0);
    }
    INLINE_APPEND(b, expression, expressions_cap, e, *result);
  }
  return true;
}
/* Reserve at most one quarter of the existing caller allowance for tiny
   call sites actually observed in its original loops. This is admission
   priority, not additional growth. A failed bounded scan reserves nothing. */
static bool inline_reserve_hot(Inline *b, uint32_t start, uint32_t count,
                                bool in_loop, bool expand, unsigned depth,
                                unsigned *remaining) {
  if (depth > 64 || (uint64_t)start + count > b->in->child_count) return false;
  for (uint32_t i = 0; i < count; ++i) {
    if (!*remaining) return false;
    --*remaining;
    uint32_t id = b->in->children[start + i];
    if (id >= b->in->statement_count) return false;
    const DynIrStmt *s = &b->in->statements[id];
    bool eligible = s->kind == DYN_STMT_LOCAL || s->kind == DYN_STMT_RETURN ||
                    s->kind == DYN_STMT_EXPR || s->kind == DYN_STMT_IF ||
                    (s->kind == DYN_STMT_ASSIGN && s->assignment_op == DYN_OP_NONE &&
                     inline_simple_target(b->in, s->target)) ||
                    (s->kind == DYN_STMT_ASSIGN && s->assignment_op != DYN_OP_NONE &&
                     inline_stable_operand(b->in, b->addressed, s->target));
    if (expand && in_loop && eligible && depth <= 16) {
      DynExprId wrappers[32]; bool right[32]; unsigned n = 0;
      DynExprId e = inline_spine(b->in, b->addressed, s->expression, wrappers, right, &n);
      if (e < b->in->expression_count) {
        const DynIrExpr *call = &b->in->expressions[e];
        if (call->kind == DYN_EXPR_CALL && call->integer < b->in->function_count &&
            !b->active[call->integer]) {
          const DynIrFunction *f = &b->in->functions[call->integer];
          unsigned cost = b->costs[call->integer];
          bool byte = b->byte_fast && f->byte_intrinsic != DYN_BYTE_INTRINSIC_NONE;
          if (!f->foreign && !f->generic && !f->variadic && !f->is_main && !byte &&
              f->local_count <= 128 && cost <= 16 && call->item_count == f->param_count &&
              (uint64_t)call->item_start + call->item_count <= b->in->item_count &&
              (uint64_t)f->param_start + f->param_count <= b->in->param_count) {
            unsigned growth = cost + f->param_count + 2;
            unsigned resources = 4 * cost + 3 * f->local_count + 2 * f->param_count + 16;
            if (growth <= 128 - b->reserved_growth && resources <= 1024 - b->reserved_resources) {
              b->reserved_growth += growth;
              b->reserved_resources += resources;
            }
          }
        }
      }
    }
    bool child_expand = expand && s->kind != DYN_STMT_DEFER;
    bool child_loop = in_loop || s->kind == DYN_STMT_FOR;
    if (!inline_reserve_hot(b, s->body_start, s->body_count, child_loop, child_expand, depth + 1, remaining) ||
        !inline_reserve_hot(b, s->else_start, s->else_count, child_loop, child_expand, depth + 1, remaining)) return false;
    if ((uint64_t)s->case_arm_start + s->case_arm_count > b->in->case_arm_count) return false;
    for (uint32_t j = 0; j < s->case_arm_count; ++j) {
      if (!*remaining) return false;
      --*remaining;
      const DynIrCaseArm *arm = &b->in->case_arms[s->case_arm_start + j];
      if (!inline_reserve_hot(b, arm->body_start, arm->body_count, in_loop, expand, depth + 1, remaining)) return false;
    }
  }
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
    /* A compound assignment to a local no pointer reaches reads the same
       value whether the call runs before or after that read. */
    bool eligible =
        s.kind == DYN_STMT_LOCAL || s.kind == DYN_STMT_RETURN ||
        s.kind == DYN_STMT_EXPR || s.kind == DYN_STMT_IF ||
        (s.kind == DYN_STMT_ASSIGN && s.assignment_op == DYN_OP_NONE &&
         inline_simple_target(b->in, s.target)) ||
        (s.kind == DYN_STMT_ASSIGN && s.assignment_op != DYN_OP_NONE &&
         inline_stable_operand(b->in, b->addressed, s.target));
    InlineList expansion = {0};
    bool expanded = eligible && s.expression < b->in->expression_count &&
                    inline_cast_call(b, scope, s.expression, &expansion,
                                     &value, depth);
    bool captured = expanded && s.kind == DYN_STMT_ASSIGN &&
                    s.target < b->in->expression_count &&
                    b->in->expressions[s.target].kind != DYN_EXPR_NAME &&
                    b->in->expressions[s.target].kind != DYN_EXPR_GLOBAL;
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
static int inline_loop_compare(const void *a, const void *b) {
  uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
  return (x > y) - (x < y);
}
/* Expansion reserves disjoint loop-ID ranges, which can become sparse and
   exceed the number of output statements. Consumers index loop tables by ID;
   restore the checked IR invariant with a bounded, identity-preserving map.
   Include retained original prefixes as well as rebuilt executable bodies. */
static bool inline_dense_loops(DynIrProgram *ir) {
  if (ir->statement_count > (1u << 22) ||
      ir->statement_count > SIZE_MAX / sizeof(uint32_t)) return false;
  uint32_t *ids = malloc((ir->statement_count ? ir->statement_count : 1) * sizeof(*ids));
  if (!ids) return false;
  size_t count = 0;
  for (size_t i = 0; i < ir->statement_count; ++i)
    if (ir->statements[i].kind == DYN_STMT_FOR)
      ids[count++] = ir->statements[i].loop_id;
  qsort(ids, count, sizeof(*ids), inline_loop_compare);
  size_t unique = 0;
  for (size_t i = 0; i < count; ++i)
    if (!unique || ids[i] != ids[unique - 1]) ids[unique++] = ids[i];
  for (size_t i = 0; i < ir->statement_count; ++i) {
    DynIrStmt *s = &ir->statements[i];
    uint32_t *id = s->kind == DYN_STMT_FOR ? &s->loop_id :
                   s->kind == DYN_STMT_BREAK || s->kind == DYN_STMT_CONTINUE
                       ? &s->target_loop_id : NULL;
    if (!id) continue;
    size_t low = 0, high = unique;
    while (low < high) {
      size_t mid = low + (high - low) / 2;
      if (ids[mid] < *id) low = mid + 1;
      else high = mid;
    }
    if (low == unique || ids[low] != *id) { free(ids); return false; }
    *id = (uint32_t)low;
  }
  free(ids);
  return true;
}
static bool inline_program(DynNativeOptimization *o, bool leaf_only, bool byte_fast) {
  Inline b = {.view = o->ir, .out = o->ir, .loop_stride = 1,
              .leaf_only = leaf_only, .byte_fast = byte_fast};
  b.in = &b.view;
  b.expressions_cap = o->ir.expression_count;
  b.statements_cap = o->ir.statement_count;
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
  b.costs = calloc(o->ir.function_count ? o->ir.function_count : 1, sizeof(*b.costs));
  if (!b.active || !b.costs) {
    free(b.active); free(b.costs);
    return false;
  }
  for (size_t i = 0; i < b.in->function_count; ++i) {
    const DynIrFunction *f = &b.in->functions[i];
    if (f->foreign || f->generic || (b.in->live.functions && !b.in->live.functions[i])) continue;
    b.costs[i] = inline_cost(b.in, f->body_start, f->body_count, 0);
  }
  /* Reserve the bounded 512-cost-unit O3 allowance (24 at O2) independently
     for each live caller. Nested expansions debit that same reservation.
     A shared pool consumed in declaration order lets unrelated library bodies
     starve later hot loops. Reservations need no redistribution or ordering:
     total expansion charge is at most 512 * live callers. Unreachable bodies
     cannot change any caller's decisions. The callee size, recursion and depth
     limits still apply; no caller can borrow another caller's allowance.

     Physical record bound: relative to rebuilding the original live bodies
     without expansion, added records are <= total resource charge.
     Each caller independently reserves 8 * its ordinary cost allowance.
     Count expressions, items, statements, child IDs, arms, locals and both
     local side tables. Body statements need at most four records after return
     rewriting; expression/item trees and arms are charged individually.
     Parameters add two records each (argument trees replace the original call
     arguments). The 16 fixed records cover loop/exit, result local/name and a
     possible assignment-target capture. Nested copies debit the same budget.
     Borrowed pattern/type/string tables are never cloned.
     Thus additional records <= 4096 * live callers at O3 (192 at O2).
     This bounds expansion, not pre-existing DAG unfolding during rebuilding;
     retained original expression/statement/item prefixes belong to baseline.
     Geometric array capacities are less than twice used size (minimum 16). */
#define INLINE_COPY(field, count, cap)                                         \
  do {                                                                         \
    if (inline_grow(&b, (void **)&b.out.field, &b.cap, b.in->count,            \
                    sizeof(*b.out.field)) &&                                   \
        b.in->count)                                                           \
      memcpy(b.out.field, b.in->field, b.in->count * sizeof(*b.out.field));    \
  } while (0)
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
  b.addressed = calloc(b.in->local_count ? b.in->local_count : 1, sizeof(bool));
  if (!b.addressed) b.failed = true;
  for (size_t i = 0; i < b.in->expression_count && !b.failed; ++i) {
    const DynIrExpr *e = &b.in->expressions[i];
    /* &local, &local.field, &local[i], and slices of local arrays all point
       into the local's storage. */
    bool takes = (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_ADDRESS) || e->kind == DYN_EXPR_SLICE;
    if (!takes) continue;
    DynExprId at = e->left;
    for (unsigned d = 0; d < 64 && at < b.in->expression_count; ++d) {
      const DynIrExpr *x = &b.in->expressions[at];
      if (x->kind == DYN_EXPR_NAME) {
        if ((uint64_t)x->integer < b.in->local_count) b.addressed[x->integer] = true;
        break;
      }
      if (x->kind != DYN_EXPR_FIELD && x->kind != DYN_EXPR_INDEX && x->kind != DYN_EXPR_SLICE) break;
      at = x->left;
    }
  }
  /* Pointer loops bind element addresses of their collection. */
  for (size_t i = 0; i < b.in->statement_count && !b.failed; ++i) {
    const DynIrStmt *st = &b.in->statements[i];
    if (st->kind != DYN_STMT_FOR || !st->for_pointer) continue;
    DynExprId at = st->expression;
    for (unsigned d = 0; d < 64 && at < b.in->expression_count; ++d) {
      const DynIrExpr *x = &b.in->expressions[at];
      if (x->kind == DYN_EXPR_NAME) {
        if ((uint64_t)x->integer < b.in->local_count) b.addressed[x->integer] = true;
        break;
      }
      if (x->kind != DYN_EXPR_FIELD && x->kind != DYN_EXPR_INDEX && x->kind != DYN_EXPR_SLICE) break;
      at = x->left;
    }
  }
  for (size_t i = 0; i < b.in->function_count && !b.failed; ++i) {
    const DynIrFunction *f = &b.in->functions[i];
    if (f->foreign || f->generic || (b.in->live.functions && !b.in->live.functions[i]))
      continue;
    InlineScope scope = {.function = f,
                         .local_base = inline_locals(&b, f),
                         .loop_base = inline_loop_base(&b),
                         .expand = true};
    b.budget = leaf_only ? 24 : 512;
    b.resource_budget = 8 * b.budget;
    b.reserved_growth = b.reserved_resources = 0;
    b.active[i] = true;
    if (!leaf_only) {
      unsigned visits = 4096;
      if (!inline_reserve_hot(&b, f->body_start, f->body_count, false, true, 0, &visits))
        b.reserved_growth = b.reserved_resources = 0;
    }
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
  if (!b.failed && b.expansions && !inline_dense_loops(&b.out)) b.failed = true;
  b.out.unstable_locals = malloc(b.out.local_count ? b.out.local_count : 1);
  b.out.local_statements = calloc(b.out.local_count ? b.out.local_count : 1,
                                  sizeof(*b.out.local_statements));
  if (!b.out.unstable_locals || !b.out.local_statements)
    b.failed = true;
  if (!b.failed)
    memset(b.out.unstable_locals, 1, b.out.local_count);
  free(b.active);
  free(b.costs);
  free(b.addressed);
  /* The original records are still the prefix of the shared arrays. */
  o->ir.expressions = b.out.expressions;
  o->ir.statements = b.out.statements;
  if (b.failed || !b.expansions) {
    b.out.expressions = NULL;
    b.out.statements = NULL;
    inline_free(&b.out);
    return !b.failed;
  }
  o->ir = b.out;
  /* Expansion creates new expression/statement indices; function IDs stay stable. */
  o->ir.live.expressions = NULL;
  o->ir.live.statements = NULL;
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
static bool optimize(const DynSource *source, const DynIrProgram *input, DynIrProgram *owned,
                     unsigned level, bool allow_ssa_intrinsics, DynNativeOptimization *o);
bool dyn_native_optimize_for_emission(const DynSource *source, const DynIrProgram *input,
                         unsigned level, bool allow_ssa_intrinsics, DynNativeOptimization *o) {
  return optimize(source, input, NULL, level, allow_ssa_intrinsics, o);
}
/* Like dyn_native_optimize_for_emission, but frees the input's expressions
   and statements as soon as the optimized copy no longer reads them, so the
   two never stay alive through inlining and emission together. */
bool dyn_native_optimize_owned(const DynSource *source, DynIrProgram *input,
                               unsigned level, bool allow_ssa_intrinsics, DynNativeOptimization *o) {
  return optimize(source, input, input, level, allow_ssa_intrinsics, o);
}
static bool optimize(const DynSource *source, const DynIrProgram *input, DynIrProgram *owned,
                     unsigned level, bool allow_ssa_intrinsics, DynNativeOptimization *o) {
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
  struct timespec optimization_time = dyn_timing_start(&source->context);
  for (size_t i = 0; i < input->expression_count; ++i) {
    if (input->live.expressions && !input->live.expressions[i]) continue;
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
      if (input->live.statements && !input->live.statements[i]) continue;
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
  dyn_timing_phase(&source->context, &optimization_time, "scalar optimization");
  if (owned) {
    /* The copy now holds every expression and statement inlining reads. */
    free(owned->expressions); free(owned->statements);
    owned->expressions = NULL; owned->statements = NULL;
  }
  const char *no_ssa = getenv("DYN_NO_SSA");
  bool byte_fast = allow_ssa_intrinsics && !strcmp(dyn_context_target(&source->context)->arch, "x86_64") &&
                  (!no_ssa || !*no_ssa || !strcmp(no_ssa, "0"));
  if (level >= 2 && !inline_program(o, level == 2, byte_fast)) {
    free(samples);
    dyn_native_optimization_free(o);
    return false;
  }
  dyn_timing_phase(&source->context, &optimization_time, "inlining");
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

bool dyn_native_optimize(const DynSource *source, const DynIrProgram *input,
                         unsigned level, DynNativeOptimization *o) {
  return dyn_native_optimize_for_emission(source, input, level, true, o);
}
