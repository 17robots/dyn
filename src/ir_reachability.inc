typedef struct {
  const DynIrProgram *ir;
  bool *live;
  bool *globals; /* optional: when set, only referenced globals are live */
  unsigned char *expressions, *statements;
  unsigned char *case_arms; /* optional: when set, dead `case any` arms stay 0 */
  uint32_t *queue;
  size_t count;
  DynType any_types[256];
  size_t any_type_count;
  uint32_t any_cases[128];
  size_t any_case_count;
  bool any_all, any_zero;
} Reachability;
static void reachable_any_type(Reachability *p, DynType type) {
  if (!p->case_arms || p->any_all || type == DYN_TYPE_ANY) return;
  for (size_t i = 0; i < p->any_type_count; ++i)
    if (p->any_types[i] == type) return;
  if (p->any_type_count < 256) p->any_types[p->any_type_count++] = type;
  else p->any_all = true;
}
static bool reachable_any_seen(const Reachability *p, DynType type) {
  for (size_t i = 0; i < p->any_type_count; ++i)
    if (p->any_types[i] == type) return true;
  return false;
}
static bool reachable_type_has_any(const DynIrProgram *ir, DynType type, unsigned depth) {
  if (depth > 8) return true;
  if (type == DYN_TYPE_ANY) return true;
  if (dyn_type_is_array(type) && type - DYN_TYPE_ARRAY_BASE < ir->array_count)
    return reachable_type_has_any(ir, ir->arrays[type - DYN_TYPE_ARRAY_BASE].element, depth + 1);
  if (dyn_type_is_struct(type) && type - DYN_TYPE_STRUCT_BASE < ir->struct_count) {
    const DynIrStruct *st = &ir->structs[type - DYN_TYPE_STRUCT_BASE];
    if ((uint64_t)st->field_start + st->field_count > ir->field_count) return true;
    for (uint32_t i = 0; i < st->field_count; ++i)
      if (reachable_type_has_any(ir, ir->fields[st->field_start + i].type, depth + 1)) return true;
  }
  if (dyn_type_is_enum(type) && type - DYN_TYPE_ENUM_BASE < ir->enum_count) {
    const DynIrEnum *en = &ir->enums[type - DYN_TYPE_ENUM_BASE];
    if (en->has_payload) {
      if ((uint64_t)en->variant_start + en->variant_count > ir->variant_count) return true;
      for (uint32_t i = 0; i < en->variant_count; ++i)
        if (ir->variants[en->variant_start + i].payload_type != DYN_TYPE_VOID &&
            reachable_type_has_any(ir, ir->variants[en->variant_start + i].payload_type, depth + 1))
          return true;
    }
  }
  return false;
}
static bool reachable_type_refs_any(const DynIrProgram *ir, DynType type, unsigned depth) {
  if (depth > 8) return true;
  if (reachable_type_has_any(ir, type, depth)) return true;
  if (dyn_type_is_pointer(type) && type - DYN_TYPE_POINTER_BASE < ir->pointer_count)
    return reachable_type_refs_any(ir, ir->pointers[type - DYN_TYPE_POINTER_BASE].pointee, depth + 1);
  if (dyn_type_is_slice(type) && type - DYN_TYPE_SLICE_BASE < ir->slice_count)
    return reachable_type_refs_any(ir, ir->slices[type - DYN_TYPE_SLICE_BASE].element, depth + 1);
  return false;
}
static bool reachable_function(Reachability *p, uint64_t id) {
  if (id >= p->ir->function_count) return false;
  if (!p->live[id] && !p->ir->functions[id].generic) {
    p->live[id] = true;
    p->queue[p->count++] = (uint32_t)id;
    const DynIrFunction *f = &p->ir->functions[id];
    if (p->case_arms && !p->any_all && f->foreign) {
      if (reachable_type_refs_any(p->ir, f->return_type, 0)) p->any_all = true;
      else if ((uint64_t)f->param_start + f->param_count <= p->ir->param_count) {
        for (uint32_t k = 0; k < f->param_count; ++k)
          if (reachable_type_refs_any(p->ir, p->ir->params[f->param_start + k].type, 0)) {
            p->any_all = true;
            break;
          }
      }
    }
  }
  return true;
}
static bool reachable_expression(Reachability *p, DynExprId id, unsigned depth);
static bool reachable_global(Reachability *p, uint64_t id, unsigned depth) {
  if (id >= p->ir->global_count) return false;
  if (!p->globals || p->globals[id]) return true;
  p->globals[id] = true;
  const DynIrGlobal *g = &p->ir->globals[id];
  if (p->case_arms && g->initializer == DYN_NO_EXPR && reachable_type_has_any(p->ir, g->type, 0))
    p->any_zero = true;
  return reachable_expression(p, g->initializer, depth + 1);
}
/* Whether evaluating an initializer may do anything besides produce its
   value: call, panic (division, a shift's count check, an index or a
   dereference) or read memory. Only globals with pure initializers may be
   dropped when nothing names them, as an unused constant is. */
static bool initializer_effects(const DynIrProgram *ir, DynExprId id, unsigned depth) {
  if (id == DYN_NO_EXPR) return false;
  if (id >= ir->expression_count || depth > 1024) return true;
  const DynIrExpr *e = &ir->expressions[id];
  switch (e->kind) {
  case DYN_EXPR_INT: case DYN_EXPR_FLOAT: case DYN_EXPR_BOOL: case DYN_EXPR_CHAR: case DYN_EXPR_STRING:
  case DYN_EXPR_NIL: case DYN_EXPR_ENUM: case DYN_EXPR_GLOBAL: case DYN_EXPR_FUNCTION:
  case DYN_EXPR_SIZE: case DYN_EXPR_ALIGN: case DYN_EXPR_LIMIT:
    return false;
  case DYN_EXPR_CONVERT: case DYN_EXPR_CAST: case DYN_EXPR_BITCAST: case DYN_EXPR_FIELD:
    return initializer_effects(ir, e->left, depth + 1);
  case DYN_EXPR_UNARY:
    if (e->op == DYN_OP_DEREF) return true;
    return e->op == DYN_OP_ADDRESS ? false : initializer_effects(ir, e->left, depth + 1);
  case DYN_EXPR_BINARY:
    if (e->op == DYN_OP_DIV || e->op == DYN_OP_REM || e->op == DYN_OP_SHL || e->op == DYN_OP_SHR) return true;
    return initializer_effects(ir, e->left, depth + 1) || initializer_effects(ir, e->right, depth + 1);
  case DYN_EXPR_STRUCT: case DYN_EXPR_ARRAY:
    if ((uint64_t)e->item_start + e->item_count > ir->item_count) return true;
    for (uint32_t i = 0; i < e->item_count; ++i)
      if (initializer_effects(ir, ir->items[e->item_start + i].expression, depth + 1)) return true;
    return false;
  default:
    return true;
  }
}
static bool reachable_expression(Reachability *p, DynExprId id, unsigned depth) {
  if (id == DYN_NO_EXPR) return true;
  if (id >= p->ir->expression_count || depth > 1024) return false;
  if (p->expressions[id]) return true;
  p->expressions[id] = 1;
  const DynIrExpr *e = &p->ir->expressions[id];
  if (e->kind == DYN_EXPR_FUNCTION) return reachable_function(p, e->integer);
  if (e->kind == DYN_EXPR_GLOBAL) return reachable_global(p, e->integer, depth);
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_FLOAT || e->kind == DYN_EXPR_BOOL ||
      e->kind == DYN_EXPR_CHAR || e->kind == DYN_EXPR_STRING || e->kind == DYN_EXPR_NIL ||
      e->kind == DYN_EXPR_NAME) return true;
  if (e->kind == DYN_EXPR_CALL && !reachable_function(p, e->integer)) return false;
  if (p->case_arms && !p->any_all) {
    if (e->kind == DYN_EXPR_CONVERT && e->type == DYN_TYPE_ANY && e->left < p->ir->expression_count)
      reachable_any_type(p, p->ir->expressions[e->left].type);
    else if (e->kind == DYN_EXPR_CALL && e->integer < p->ir->function_count) {
      const DynIrFunction *callee = &p->ir->functions[e->integer];
      if (callee->variadic && !callee->foreign && dyn_type_is_slice(callee->variadic_type) &&
          callee->variadic_type - DYN_TYPE_SLICE_BASE < p->ir->slice_count &&
          p->ir->slices[callee->variadic_type - DYN_TYPE_SLICE_BASE].element == DYN_TYPE_ANY &&
          (uint64_t)e->item_start + e->item_count <= p->ir->item_count) {
        for (uint32_t k = callee->param_count; k < e->item_count; ++k) {
          DynExprId arg = p->ir->items[e->item_start + k].expression;
          if (arg < p->ir->expression_count) reachable_any_type(p, p->ir->expressions[arg].type);
        }
      }
    } else if (e->kind == DYN_EXPR_INDIRECT_CALL && e->integer < p->ir->fn_type_count &&
               p->ir->fn_types[e->integer].variadic) {
      p->any_all = true;
    } else if ((e->kind == DYN_EXPR_CAST || e->kind == DYN_EXPR_BITCAST) &&
               (reachable_type_refs_any(p->ir, e->type, 0) ||
                (e->left < p->ir->expression_count &&
                 reachable_type_refs_any(p->ir, p->ir->expressions[e->left].type, 0)))) {
      p->any_all = true;
    } else if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_DEREF && e->type == DYN_TYPE_ANY) {
      p->any_all = true;
    }
  }
  if (!reachable_expression(p, e->left, depth + 1) ||
      !reachable_expression(p, e->right, depth + 1)) return false;
  if (e->kind == DYN_EXPR_SLICE && !reachable_expression(p, (DynExprId)e->integer, depth + 1)) return false;
  if ((uint64_t)e->item_start + e->item_count > p->ir->item_count) return false;
  for (uint32_t i = 0; i < e->item_count; ++i)
    if (!reachable_expression(p, p->ir->items[e->item_start + i].expression, depth + 1)) return false;
  return true;
}
static bool reachable_block(Reachability *p, uint32_t start, uint32_t count, unsigned depth) {
  if (depth > 1024 || (uint64_t)start + count > p->ir->child_count) return false;
  for (uint32_t i = 0; i < count; ++i) {
    uint32_t id = p->ir->children[start + i];
    if (id >= p->ir->statement_count) return false;
    if (p->statements[id]) continue;
    p->statements[id] = 1;
    const DynIrStmt *s = &p->ir->statements[id];
    if (p->case_arms && s->kind == DYN_STMT_LOCAL && s->expression == DYN_NO_EXPR &&
        s->local_id < p->ir->local_count && reachable_type_has_any(p->ir, p->ir->locals[s->local_id].type, 0))
      p->any_zero = true;
    if (!reachable_expression(p, s->expression, 0) || !reachable_expression(p, s->target, 0) ||
        !reachable_block(p, s->body_start, s->body_count, depth + 1) ||
        !reachable_block(p, s->else_start, s->else_count, depth + 1)) return false;
    if ((uint64_t)s->case_arm_start + s->case_arm_count > p->ir->case_arm_count) return false;
    bool is_any_case = p->case_arms && s->kind == DYN_STMT_CASE && s->expression < p->ir->expression_count &&
                       p->ir->expressions[s->expression].type == DYN_TYPE_ANY;
    if (is_any_case && !p->any_all && p->any_case_count < 128) {
      p->any_cases[p->any_case_count++] = id;
    } else {
      if (is_any_case) p->any_all = true;
      for (uint32_t a = 0; a < s->case_arm_count; ++a) {
        if (p->case_arms) p->case_arms[s->case_arm_start + a] = 1;
        const DynIrCaseArm *arm = &p->ir->case_arms[s->case_arm_start + a];
        if (!reachable_block(p, arm->body_start, arm->body_count, depth + 1)) return false;
      }
    }
  }
  return true;
}
/* Public functions are roots for reusable objects and libraries. Executables
   without external link inputs can instead start at main and initializers. */
static bool reachable_collect(Reachability *p, bool public_roots, bool all_roots) {
  bool ok = p->expressions && p->statements && p->queue;
  const DynIrProgram *ir = p->ir;
  if (public_roots || all_roots) p->any_all = true;
  for (size_t i = 0; ok && i < ir->function_count; ++i) {
    const DynIrFunction *f = &ir->functions[i];
    if (f->is_main || (public_roots && f->is_public) || f->foreign || all_roots)
      ok = reachable_function(p, i);
  }
  /* Without a globals map every initializer is a root. With one, roots are
     public globals of libraries and initializers that may have effects;
     the rest stay only when live code names them. */
  for (size_t i = 0; ok && i < ir->global_count; ++i) {
    const DynIrGlobal *g = &ir->globals[i];
    if (!p->globals) ok = reachable_expression(p, g->initializer, 0);
    else if (all_roots || (public_roots && g->is_public) || g->foreign || initializer_effects(ir, g->initializer, 0))
      ok = reachable_global(p, i, 0);
  }
  size_t at = 0;
  for (bool progress = true; ok && progress;) {
    bool was_all = p->any_all;
    progress = false;
    for (; ok && at < p->count; ++at) {
      const DynIrFunction *f = &ir->functions[p->queue[at]];
      if (!f->foreign) ok = reachable_block(p, f->body_start, f->body_count, 0);
    }
    if (!ok || !p->case_arms) break;
    for (size_t c = 0; ok && c < p->any_case_count; ++c) {
      const DynIrStmt *s = &ir->statements[p->any_cases[c]];
      for (uint32_t a = 0; ok && a < s->case_arm_count; ++a) {
        uint32_t arm_idx = s->case_arm_start + a;
        if (p->case_arms[arm_idx]) continue;
        const DynIrCaseArm *arm = &ir->case_arms[arm_idx];
        bool match = p->any_all;
        if (!match && !arm->wildcard) {
          if ((uint64_t)arm->pattern_start + arm->pattern_count > ir->pattern_count) { ok = false; break; }
          for (uint32_t j = 0; j < arm->pattern_count && !match; ++j) {
            const DynIrPattern *pat = &ir->patterns[arm->pattern_start + j];
            if (!pat->is_type || reachable_any_seen(p, pat->type)) match = true;
          }
        } else if (!match && arm->wildcard) {
          if (p->any_zero) match = true;
          for (size_t ti = 0; ti < p->any_type_count && !match; ++ti) {
            DynType t = p->any_types[ti];
            bool covered = false;
            for (uint32_t prev = 0; prev < a && !covered; ++prev) {
              const DynIrCaseArm *pa = &ir->case_arms[s->case_arm_start + prev];
              for (uint32_t j = 0; j < pa->pattern_count; ++j)
                if (ir->patterns[pa->pattern_start + j].is_type && ir->patterns[pa->pattern_start + j].type == t) {
                  covered = true; break;
                }
            }
            if (!covered) match = true;
          }
        }
        if (match) {
          p->case_arms[arm_idx] = 1;
          progress = true;
          ok = reachable_block(p, arm->body_start, arm->body_count, 0);
        }
      }
    }
    if (at < p->count || (p->any_all && !was_all)) progress = true;
  }
  return ok;
}
