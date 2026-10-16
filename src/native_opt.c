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
void dyn_native_optimization_free(DynNativeOptimization *o) {
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
  if (policy && policy->remarks)
    fprintf(stderr,
            "remark: independent O%u: %zu scalar folds, %zu immutable loads, "
            "%zu constant branches, %zu constant calls\n",
            level, o->folded, o->propagated, o->branches, o->calls);
  if (samples && policy->remarks)
    fprintf(stderr, "remark: samples from profile control constant-call "
                    "budgets (hot 1024, cold 16 nodes)\n");
  free(samples);
  return true;
}
