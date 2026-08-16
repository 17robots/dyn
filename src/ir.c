#include "ir.h"
#include <stdlib.h>
#include <string.h>

static bool allocate(void **out, size_t count, size_t size) {
  if (!count) {
    *out = NULL;
    return true;
  }
  *out = calloc(count, size);
  return *out != NULL;
}

static bool valid_expr_id(const DynIrProgram *ir, DynExprId id) {
  return id == DYN_NO_EXPR || id < ir->expression_count;
}

static DynType lower_type(const DynAstFunction *a, DynType t) {
  size_t guard = 0;
  while (dyn_type_is_distinct(t) && guard++ <= a->alias_count) {
    uint32_t id = t - DYN_TYPE_DISTINCT_BASE;
    if (id >= a->alias_count)
      return DYN_TYPE_ERROR;
    t = a->aliases[id].target;
  }
  return t;
}

typedef struct {
  bool valid, exact;
  uint64_t max, value;
} UIntRange;
static bool unsigned_type(DynType t) {
  return t >= DYN_TYPE_U8 && t <= DYN_TYPE_USIZE;
}
static uint64_t unsigned_max(DynType t) {
  if (t == DYN_TYPE_U8)
    return UINT8_MAX;
  if (t == DYN_TYPE_U16)
    return UINT16_MAX;
  if (t == DYN_TYPE_U32)
    return UINT32_MAX;
  return UINT64_MAX;
}
static UIntRange uint_range(const DynIrProgram *ir, DynExprId id,
                            const UIntRange *locals, size_t depth) {
  if (id == DYN_NO_EXPR || id >= ir->expression_count ||
      depth > ir->expression_count)
    return (UIntRange){0};
  const DynIrExpr *e = &ir->expressions[id];
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_CHAR ||
      e->kind == DYN_EXPR_BOOL)
    return (UIntRange){true, true, e->integer, e->integer};
  if (e->kind == DYN_EXPR_NAME && e->integer < ir->local_count)
    return locals[e->integer];
  if (e->kind == DYN_EXPR_CONVERT || e->kind == DYN_EXPR_CAST) {
    if (!unsigned_type(e->type))
      return (UIntRange){0};
    UIntRange source = uint_range(ir, e->left, locals, depth + 1);
    uint64_t limit = unsigned_max(e->type);
    if (!source.valid || source.max > limit)
      return (UIntRange){true, false, limit, 0};
    source.max = source.max < limit ? source.max : limit;
    if (source.exact && source.value > limit)
      source.exact = false;
    return source;
  }
  if (e->kind == DYN_EXPR_INDEX && unsigned_type(e->type))
    return (UIntRange){true, false, unsigned_max(e->type), 0};
  if (e->kind != DYN_EXPR_BINARY)
    return (UIntRange){0};
  UIntRange left = uint_range(ir, e->left, locals, depth + 1),
            right = uint_range(ir, e->right, locals, depth + 1);
  if (!left.valid || !right.valid)
    return (UIntRange){0};
  if (e->op == DYN_OP_BIT_AND) {
    uint64_t max = left.max < right.max ? left.max : right.max;
    if (right.exact && right.value < max)
      max = right.value;
    if (left.exact && left.value < max)
      max = left.value;
    return (UIntRange){true, left.exact && right.exact, max,
                       left.value & right.value};
  }
  if (e->op == DYN_OP_ADD && UINT64_MAX - left.max >= right.max) {
    uint64_t max = left.max + right.max;
    return (UIntRange){true, left.exact && right.exact, max,
                       left.value + right.value};
  }
  if (e->op == DYN_OP_MUL &&
      (left.max == 0 || right.max <= UINT64_MAX / left.max)) {
    uint64_t max = left.max * right.max;
    return (UIntRange){true, left.exact && right.exact, max,
                       left.value * right.value};
  }
  return (UIntRange){0};
}
static bool range_pure(const DynIrProgram *ir, DynExprId id, size_t depth) {
  if (id == DYN_NO_EXPR || id >= ir->expression_count ||
      depth > ir->expression_count)
    return false;
  const DynIrExpr *e = &ir->expressions[id];
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_CHAR ||
      e->kind == DYN_EXPR_BOOL || e->kind == DYN_EXPR_NAME ||
      e->kind == DYN_EXPR_GLOBAL)
    return true;
  if (e->kind == DYN_EXPR_CONVERT || e->kind == DYN_EXPR_CAST)
    return range_pure(ir, e->left, depth + 1);
  if (e->kind == DYN_EXPR_INDEX || e->kind == DYN_EXPR_BINARY)
    return range_pure(ir, e->left, depth + 1) &&
           range_pure(ir, e->right, depth + 1);
  return false;
}
static bool simple_loop_body(const DynIrProgram *ir, const DynIrStmt *loop) {
  for (uint32_t i = 0; i < loop->body_count; ++i) {
    const DynIrStmt *st = &ir->statements[ir->children[loop->body_start + i]];
    if (st->kind == DYN_STMT_LOCAL) {
      if (!range_pure(ir, st->expression, 0))
        return false;
      continue;
    }
    if (st->kind == DYN_STMT_ASSIGN) {
      if (st->target != DYN_NO_EXPR || !range_pure(ir, st->expression, 0))
        return false;
      continue;
    }
    return false;
  }
  return true;
}
static void prove_unsigned_loop(DynIrProgram *ir, DynIrStmt *loop,
                                UIntRange *outer) {
  if (loop->expression == DYN_NO_EXPR || !simple_loop_body(ir, loop))
    return;
  DynIrExpr *condition = &ir->expressions[loop->expression];
  if (condition->kind != DYN_EXPR_BINARY || condition->op != DYN_OP_LT)
    return;
  DynIrExpr *induction = &ir->expressions[condition->left];
  if (induction->kind != DYN_EXPR_NAME ||
      induction->integer >= ir->local_count || !unsigned_type(induction->type))
    return;
  uint32_t induction_id = (uint32_t)induction->integer;
  UIntRange bound = uint_range(ir, condition->right, outer, 0),
            start = outer[induction_id];
  if (!bound.exact || !start.exact || bound.value < start.value)
    return;
  uint64_t iterations = bound.value - start.value;
  bool increment = false;
  for (uint32_t i = 0; i < loop->body_count; ++i) {
    DynIrStmt *st = &ir->statements[ir->children[loop->body_start + i]];
    if (st->kind != DYN_STMT_ASSIGN || st->local_id != induction_id)
      continue;
    DynIrExpr *e = &ir->expressions[st->expression];
    UIntRange one = e->kind == DYN_EXPR_BINARY
                        ? uint_range(ir, e->right, outer, 0)
                        : (UIntRange){0};
    if (e->kind == DYN_EXPR_BINARY && e->op == DYN_OP_ADD &&
        ir->expressions[e->left].kind == DYN_EXPR_NAME &&
        ir->expressions[e->left].integer == induction_id && one.exact &&
        one.value == 1)
      increment = true;
    else
      return;
  }
  if (!increment)
    return;
  UIntRange *inside = calloc(ir->local_count, sizeof(*inside));
  if (!inside)
    return;
  memcpy(inside, outer, ir->local_count * sizeof(*inside));
  inside[induction_id] =
      (UIntRange){true, false, bound.value ? bound.value - 1 : 0, 0};
  for (uint32_t i = 0; i < loop->body_count; ++i) {
    DynIrStmt *st = &ir->statements[ir->children[loop->body_start + i]];
    if (st->kind == DYN_STMT_LOCAL && st->local_id < ir->local_count) {
      inside[st->local_id] = uint_range(ir, st->expression, inside, 0);
      continue;
    }
    if (st->kind != DYN_STMT_ASSIGN || st->local_id >= ir->local_count)
      continue;
    DynIrExpr *e = &ir->expressions[st->expression];
    if (e->kind != DYN_EXPR_BINARY || e->op != DYN_OP_ADD ||
        ir->expressions[e->left].kind != DYN_EXPR_NAME ||
        ir->expressions[e->left].integer != st->local_id)
      continue;
    UIntRange initial = outer[st->local_id],
              step = uint_range(ir, e->right, inside, 0);
    uint64_t limit = unsigned_max(e->type), growth;
    if (!unsigned_type(e->type) || !initial.valid || !step.valid ||
        (iterations != 0 && step.max > UINT64_MAX / iterations))
      continue;
    growth = step.max * iterations;
    if (initial.max <= limit && growth <= limit - initial.max)
      e->boolean = true;
  }
  free(inside);
}
static void prove_unsigned_ranges(DynIrProgram *ir) {
  UIntRange *locals = calloc(ir->local_count, sizeof(*locals));
  if (!locals)
    return;
  for (size_t f = 0; f < ir->function_count; ++f) {
    memset(locals, 0, ir->local_count * sizeof(*locals));
    DynIrFunction *fn = &ir->functions[f];
    for (uint32_t i = 0; i < fn->body_count; ++i) {
      DynIrStmt *st = &ir->statements[ir->children[fn->body_start + i]];
      if (st->kind == DYN_STMT_LOCAL && st->local_id < ir->local_count)
        locals[st->local_id] = uint_range(ir, st->expression, locals, 0);
      else if (st->kind == DYN_STMT_FOR) {
        prove_unsigned_loop(ir, st, locals);
        for (uint32_t j = 0; j < st->body_count; ++j) {
          DynIrStmt *body = &ir->statements[ir->children[st->body_start + j]];
          if (body->kind == DYN_STMT_ASSIGN && body->local_id < ir->local_count)
            locals[body->local_id] = (UIntRange){0};
        }
      } else if (st->kind == DYN_STMT_ASSIGN && st->local_id < ir->local_count)
        locals[st->local_id] = uint_range(ir, st->expression, locals, 0);
    }
  }
  free(locals);
}

static bool validate_ir(const DynIrProgram *ir) {
  for (size_t i = 0; i < ir->expression_count; ++i) {
    const DynIrExpr *e = &ir->expressions[i];
    if (e->type == DYN_TYPE_INFER || e->type == DYN_TYPE_ERROR ||
        !valid_expr_id(ir, e->left) || !valid_expr_id(ir, e->right) ||
        (size_t)e->item_start + e->item_count > ir->item_count)
      return false;
    if (e->kind == DYN_EXPR_NAME && e->integer >= ir->local_count)
      return false;
    if (e->kind == DYN_EXPR_GLOBAL && e->integer >= ir->global_count)
      return false;
    if (e->kind == DYN_EXPR_CALL && e->integer >= ir->function_count)
      return false;
    if (e->kind == DYN_EXPR_FUNCTION && e->integer >= ir->function_count)
      return false;
    if (e->kind == DYN_EXPR_INDIRECT_CALL && e->integer >= ir->fn_type_count)
      return false;
    if (e->kind == DYN_EXPR_STRUCT && e->integer >= ir->struct_count)
      return false;
  }
  for (size_t i = 0; i < ir->item_count; ++i)
    if (!valid_expr_id(ir, ir->items[i].expression))
      return false;
  for (size_t i = 0; i < ir->child_count; ++i)
    if (ir->children[i] >= ir->statement_count)
      return false;
  for (size_t i = 0; i < ir->statement_count; ++i) {
    const DynIrStmt *st = &ir->statements[i];
    if (!valid_expr_id(ir, st->expression) || !valid_expr_id(ir, st->target) ||
        st->assignment_op != DYN_OP_NONE ||
        (size_t)st->case_arm_start + st->case_arm_count > ir->case_arm_count)
      return false;
    if ((st->kind == DYN_STMT_BREAK || st->kind == DYN_STMT_CONTINUE) &&
        st->target_loop_id >= ir->statement_count)
      return false;
    if (st->kind == DYN_STMT_FOR && st->loop_id >= ir->statement_count)
      return false;
  }
  for (size_t i = 0; i < ir->case_arm_count; ++i)
    if ((size_t)ir->case_arms[i].pattern_start +
                ir->case_arms[i].pattern_count >
            ir->pattern_count ||
        (size_t)ir->case_arms[i].body_start + ir->case_arms[i].body_count >
            ir->child_count)
      return false;
  return true;
}

bool dyn_ir_lower(const DynAstFunction *a, const DynSource *source,
                  DynIrProgram *ir) {
  memset(ir, 0, sizeof(*ir));
  size_t extra = 0;
  for (size_t i = 0; i < a->statement_count; ++i)
    if (a->statements[i].assignment_op != DYN_OP_NONE)
      extra += a->statements[i].target == DYN_NO_EXPR ? 2 : 1;
  ir->expression_count = a->expression_count;
  ir->expression_capacity = a->expression_count + extra;
  ir->item_count = a->item_count;
  ir->field_count = a->field_count;
  ir->struct_count = a->struct_count;
  ir->enum_count = a->enum_count;
  ir->variant_count = a->variant_count;
  ir->param_count = a->param_count;
  ir->string_count = a->string_count;
  ir->function_count = a->function_count;
  ir->global_count = a->global_count;
  ir->global_init_count = a->global_init_count;
  ir->pointer_count = a->pointer_count;
  ir->array_count = a->array_count;
  ir->slice_count = a->slice_count;
  ir->fn_type_count = a->fn_type_count;
  ir->fn_type_param_count = a->fn_type_param_count;
  ir->statement_count = a->statement_count;
  ir->pattern_count = a->pattern_count;
  ir->case_arm_count = a->case_arm_count;
  ir->child_count = a->child_count;
  ir->local_count = a->local_count;
  if (!allocate((void **)&ir->expressions, ir->expression_capacity,
                sizeof(*ir->expressions)) ||
      !allocate((void **)&ir->items, ir->item_count, sizeof(*ir->items)) ||
      !allocate((void **)&ir->fields, ir->field_count, sizeof(*ir->fields)) ||
      !allocate((void **)&ir->structs, ir->struct_count,
                sizeof(*ir->structs)) ||
      !allocate((void **)&ir->enums, ir->enum_count, sizeof(*ir->enums)) ||
      !allocate((void **)&ir->variants, ir->variant_count,
                sizeof(*ir->variants)) ||
      !allocate((void **)&ir->params, ir->param_count, sizeof(*ir->params)) ||
      !allocate((void **)&ir->functions, ir->function_count,
                sizeof(*ir->functions)) ||
      !allocate((void **)&ir->globals, ir->global_count,
                sizeof(*ir->globals)) ||
      !allocate((void **)&ir->global_init_order, ir->global_init_count,
                sizeof(*ir->global_init_order)) ||
      !allocate((void **)&ir->pointers, ir->pointer_count,
                sizeof(*ir->pointers)) ||
      !allocate((void **)&ir->arrays, ir->array_count, sizeof(*ir->arrays)) ||
      !allocate((void **)&ir->slices, ir->slice_count, sizeof(*ir->slices)) ||
      !allocate((void **)&ir->fn_types, ir->fn_type_count,
                sizeof(*ir->fn_types)) ||
      !allocate((void **)&ir->fn_type_params, ir->fn_type_param_count,
                sizeof(*ir->fn_type_params)) ||
      !allocate((void **)&ir->strings, ir->string_count,
                sizeof(*ir->strings)) ||
      !allocate((void **)&ir->statements, ir->statement_count,
                sizeof(*ir->statements)) ||
      !allocate((void **)&ir->patterns, ir->pattern_count,
                sizeof(*ir->patterns)) ||
      !allocate((void **)&ir->case_arms, ir->case_arm_count,
                sizeof(*ir->case_arms)) ||
      !allocate((void **)&ir->children, ir->child_count,
                sizeof(*ir->children)) ||
      !allocate((void **)&ir->locals, ir->local_count, sizeof(*ir->locals))) {
    dyn_ir_free(ir);
    return false;
  }
  for (size_t i = 0; i < a->expression_count; ++i)
    ir->expressions[i] = (DynIrExpr){
        a->expressions[i].kind,       lower_type(a, a->expressions[i].type),
        a->expressions[i].op,         a->expressions[i].left,
        a->expressions[i].right,      a->expressions[i].integer,
        a->expressions[i].floating,   a->expressions[i].boolean,
        a->expressions[i].item_start, a->expressions[i].item_count};
  for (size_t i = 0; i < ir->expression_count; ++i)
    if (ir->expressions[i].type == DYN_TYPE_INFER) {
      ir->expressions[i].kind = DYN_EXPR_NIL;
      ir->expressions[i].type = DYN_TYPE_VOID;
      ir->expressions[i].left = ir->expressions[i].right = DYN_NO_EXPR;
    }
  for (size_t i = 0; i < a->item_count; ++i)
    ir->items[i] = (DynIrItem){a->items[i].expression, a->items[i].field_index};
  for (size_t i = 0; i < a->field_count; ++i)
    ir->fields[i] = (DynIrField){lower_type(a, a->fields[i].type),
                                 a->fields[i].default_expression};
  for (size_t i = 0; i < a->struct_count; ++i)
    ir->structs[i] = (DynIrStruct){
        a->structs[i].packed, a->structs[i].field_start,
        a->structs[i].field_count, a->structs[i].size, a->structs[i].alignment};
  for (size_t i = 0; i < a->enum_count; ++i)
    ir->enums[i] =
        (DynIrEnum){a->enums[i].tag_type,          a->enums[i].variant_start,
                    a->enums[i].variant_count,     a->enums[i].size,
                    a->enums[i].alignment,         a->enums[i].payload_size,
                    a->enums[i].payload_alignment, a->enums[i].has_payload};
  for (size_t i = 0; i < a->variant_count; ++i)
    ir->variants[i] = (DynIrVariant){lower_type(a, a->variants[i].payload_type),
                                     a->variants[i].tag};
  for (size_t i = 0; i < a->param_count; ++i)
    ir->params[i] =
        (DynIrParam){lower_type(a, a->params[i].type), a->params[i].local_id};
  for (size_t i = 0; i < a->function_count; ++i) {
    size_t n = a->functions[i].name.end_byte - a->functions[i].name.start_byte;
    ir->functions[i].name = malloc(n + 1);
    if (!ir->functions[i].name) {
      dyn_ir_free(ir);
      return false;
    }
    memcpy(ir->functions[i].name,
           source->text + a->functions[i].name.start_byte, n);
    ir->functions[i].name[n] = 0;
    size_t link_length=a->functions[i].link_name.end_byte-a->functions[i].link_name.start_byte;
    ir->functions[i].link_name=malloc(link_length+1);
    if(!ir->functions[i].link_name){dyn_ir_free(ir);return false;}
    memcpy(ir->functions[i].link_name,source->text+a->functions[i].link_name.start_byte,link_length);
    ir->functions[i].link_name[link_length]=0;
    ir->functions[i].return_type = a->functions[i].return_type;
    ir->functions[i].param_start = a->functions[i].param_start;
    ir->functions[i].param_count = a->functions[i].param_count;
    ir->functions[i].body_start = a->functions[i].body_start;
    ir->functions[i].body_count = a->functions[i].body_count;
    ir->functions[i].local_start = a->functions[i].local_start;
    ir->functions[i].local_count = a->functions[i].local_count;
    ir->functions[i].is_main = a->functions[i].is_main;
    ir->functions[i].foreign = a->functions[i].foreign;
  }
  for (size_t i = 0; i < a->global_count; ++i) {
    size_t n = a->globals[i].name.end_byte - a->globals[i].name.start_byte;
    ir->globals[i].name = malloc(n + 1);
    if (!ir->globals[i].name) {
      dyn_ir_free(ir);
      return false;
    }
    memcpy(ir->globals[i].name, source->text + a->globals[i].name.start_byte,
           n);
    ir->globals[i].name[n] = 0;
    ir->globals[i].type = a->globals[i].type;
    ir->globals[i].initializer = a->globals[i].initializer;
    ir->globals[i].is_const = a->globals[i].is_const;
  }
  if (a->global_init_count)
    memcpy(ir->global_init_order, a->global_init_order,
           a->global_init_count * sizeof(*ir->global_init_order));
  for (size_t i = 0; i < a->pointer_count; ++i)
    ir->pointers[i] = (DynIrPointer){lower_type(a, a->pointers[i].pointee),
                                     a->pointers[i].is_const};
  for (size_t i = 0; i < a->array_count; ++i)
    ir->arrays[i] =
        (DynIrArray){lower_type(a, a->arrays[i].element), a->arrays[i].length};
  for (size_t i = 0; i < a->slice_count; ++i)
    ir->slices[i] = (DynIrSlice){lower_type(a, a->slices[i].element),
                                 a->slices[i].is_const};
  for (size_t i = 0; i < a->fn_type_count; ++i)
    ir->fn_types[i] =
        (DynIrFnType){lower_type(a, a->fn_types[i].return_type),
                      a->fn_types[i].param_start, a->fn_types[i].param_count};
  for (size_t i = 0; i < a->fn_type_param_count; ++i)
    ir->fn_type_params[i] = lower_type(a, a->fn_type_params[i]);
  for (size_t i = 0; i < a->string_count; ++i) {
    ir->strings[i].length = a->strings[i].length;
    ir->strings[i].data = malloc(a->strings[i].length);
    if (a->strings[i].length && !ir->strings[i].data) {
      dyn_ir_free(ir);
      return false;
    }
    if (a->strings[i].length)
      memcpy(ir->strings[i].data, a->strings[i].data, a->strings[i].length);
  }
  for (size_t i = 0; i < a->local_count; ++i)
    ir->locals[i] = (DynIrLocal){lower_type(a, a->locals[i].type)};
  for (size_t i = 0; i < a->statement_count; ++i)
    ir->statements[i] = (DynIrStmt){
        a->statements[i].kind,           a->statements[i].expression,
        a->statements[i].target,         a->statements[i].assignment_op,
        a->statements[i].local_id,       a->statements[i].body_start,
        a->statements[i].body_count,     a->statements[i].else_start,
        a->statements[i].else_count,     a->statements[i].loop_id,
        a->statements[i].target_loop_id, a->statements[i].case_arm_start,
        a->statements[i].case_arm_count, a->statements[i].defer_block,
        a->statements[i].for_pointer,    a->statements[i].for_const};
  for (size_t i = 0; i < a->pattern_count; ++i)
    ir->patterns[i] =
        (DynIrPattern){a->patterns[i].first_value, a->patterns[i].last_value,
                       a->patterns[i].variant, a->patterns[i].is_enum,
                       a->patterns[i].is_signed};
  for (size_t i = 0; i < a->case_arm_count; ++i)
    ir->case_arms[i] = (DynIrCaseArm){
        a->case_arms[i].pattern_start,  a->case_arms[i].pattern_count,
        a->case_arms[i].body_start,     a->case_arms[i].body_count,
        a->case_arms[i].local_id,       a->case_arms[i].wildcard,
        a->case_arms[i].pointer_binding};
  for (size_t i = 0; i < ir->statement_count; ++i)
    if (ir->statements[i].kind == DYN_STMT_CASE) {
      DynIrStmt *st = &ir->statements[i];
      for (uint32_t j = 0; j + 1 < st->case_arm_count; ++j) {
        uint32_t at = st->case_arm_start + j;
        if (ir->case_arms[at].wildcard) {
          DynIrCaseArm tmp = ir->case_arms[at];
          ir->case_arms[at] =
              ir->case_arms[st->case_arm_start + st->case_arm_count - 1];
          ir->case_arms[st->case_arm_start + st->case_arm_count - 1] = tmp;
          break;
        }
      }
    }
  for (size_t i = 0; i < ir->statement_count; ++i) {
    DynIrStmt *st = &ir->statements[i];
    if (st->assignment_op == DYN_OP_NONE)
      continue;
    DynExprId left;
    if (st->target != DYN_NO_EXPR)
      left = st->target;
    else {
      left = (DynExprId)ir->expression_count;
      ir->expressions[ir->expression_count++] =
          (DynIrExpr){.kind = DYN_EXPR_NAME,
                      .type = ir->locals[st->local_id].type,
                      .left = DYN_NO_EXPR,
                      .right = DYN_NO_EXPR,
                      .integer = st->local_id};
    }
    DynType type = ir->expressions[left].type;
    DynExprId binary = (DynExprId)ir->expression_count;
    ir->expressions[ir->expression_count++] =
        (DynIrExpr){.kind = DYN_EXPR_BINARY,
                    .type = type,
                    .op = st->assignment_op,
                    .left = left,
                    .right = st->expression};
    st->expression = binary;
    st->assignment_op = DYN_OP_NONE;
  }
  for (size_t i = 0; i < ir->function_count; ++i)
    ir->functions[i].return_type = lower_type(a, ir->functions[i].return_type);
  for (size_t i = 0; i < ir->global_count; ++i)
    ir->globals[i].type = lower_type(a, ir->globals[i].type);
  for (size_t i = 0; i < ir->enum_count; ++i)
    ir->enums[i].tag_type = lower_type(a, ir->enums[i].tag_type);
  if (a->child_count)
    memcpy(ir->children, a->children, a->child_count * sizeof(*ir->children));
  prove_unsigned_ranges(ir);
  for (size_t i = 0; i < ir->function_count; ++i) {
    if ((size_t)ir->functions[i].body_start + ir->functions[i].body_count >
        ir->child_count) {
      dyn_ir_free(ir);
      return false;
    }
  }
  if (!validate_ir(ir)) {
    dyn_ir_free(ir);
    return false;
  }
  return true;
}

void dyn_ir_free(DynIrProgram *ir) {
  for (size_t i = 0; i < ir->string_count; ++i)
    free(ir->strings[i].data);
  for (size_t i = 0; i < ir->function_count; ++i)
    free(ir->functions[i].name);
  for (size_t i = 0; i < ir->function_count; ++i)
    free(ir->functions[i].link_name);
  for (size_t i = 0; i < ir->global_count; ++i)
    free(ir->globals[i].name);
  free(ir->expressions);
  free(ir->items);
  free(ir->fields);
  free(ir->structs);
  free(ir->enums);
  free(ir->variants);
  free(ir->params);
  free(ir->functions);
  free(ir->globals);
  free(ir->global_init_order);
  free(ir->statements);
  free(ir->patterns);
  free(ir->case_arms);
  free(ir->children);
  free(ir->strings);
  free(ir->pointers);
  free(ir->arrays);
  free(ir->slices);
  free(ir->fn_types);
  free(ir->fn_type_params);
  free(ir->locals);
  memset(ir, 0, sizeof(*ir));
}
