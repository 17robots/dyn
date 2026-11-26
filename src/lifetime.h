#ifndef DYN_LIFETIME_H
#define DYN_LIFETIME_H
/* Intra-function CFG stack-escape dataflow pass. Tracks provenance of
   addresses into a function's own frame across straight-line code, branches
   (if/else, case), loops (fixpoint iteration with break/continue), structs,
   #take, and out-parameters. Knows no library function by name. */
typedef struct { bool stack; uint32_t address; } LifeValue;
typedef struct { uint32_t local, field; LifeValue value; } LifeField;
#define LIFE_INLINE_LOCALS 64
#define LIFE_INLINE_FIELDS 8
typedef struct {
  LifeValue *locals;
  LifeField *fields;
  size_t field_count, field_capacity;
  LifeValue inline_locals[LIFE_INLINE_LOCALS];
  LifeField inline_fields[LIFE_INLINE_FIELDS];
} LifeState;
typedef struct {
  uint32_t loop_id;
  LifeState break_state, cont_state;
  bool has_break, has_cont;
} LifeLoop;
typedef struct {
  Sema *sema; DynAstProgram *a; const DynSource *source; unsigned *errors;
  uint32_t first, count, params;
  LifeValue *locals;
  LifeField *fields; size_t field_count, field_capacity;
  bool *addr_taken;
  bool emit_errors;
  LifeLoop loops[64];
  uint32_t loop_depth;
} Life;

static LifeValue life_join(LifeValue a, LifeValue b) {
  a.stack |= b.stack;
  if (!a.address) a.address = b.address;
  else if (b.address && a.address != b.address) a.address = 0;
  return a;
}
static LifeValue *life_local(Life *l, uint32_t id) {
  return id >= l->first && id - l->first < l->count ? &l->locals[id - l->first] : NULL;
}
static bool life_borrow_type(DynAstProgram *a, DynType t, unsigned depth) {
  if (depth > 64) return false;
  if (dyn_type_is_pointer(t) || dyn_type_is_slice(t) || t == DYN_TYPE_RAWPTR || t == DYN_TYPE_ANY) return true;
  if (dyn_type_is_array(t)) return life_borrow_type(a, a->arrays[t - DYN_TYPE_ARRAY_BASE].element, depth + 1);
  if (dyn_type_is_struct(t)) {
    DynAstStruct *st = &a->structs[t - DYN_TYPE_STRUCT_BASE];
    for (uint32_t i = 0; i < st->field_count; ++i)
      if (life_borrow_type(a, a->fields[st->field_start + i].type, depth + 1)) return true;
  }
  if (dyn_type_is_enum(t)) {
    DynAstEnum *en = &a->enums[t - DYN_TYPE_ENUM_BASE];
    for (uint32_t i = 0; i < en->variant_count; ++i) {
      DynType pt = a->variants[en->variant_start + i].payload_type;
      if (pt != DYN_TYPE_VOID && life_borrow_type(a, pt, depth + 1)) return true;
    }
  }
  return false;
}
static LifeValue life_expr(Life *, DynExprId, unsigned);
static bool life_block(Life *, uint32_t, uint32_t, unsigned);

static LifeValue life_field(Life *l, uint32_t local, uint32_t field) {
  for (size_t i = l->field_count; i; --i)
    if (l->fields[i - 1].local == local && l->fields[i - 1].field == field) return l->fields[i - 1].value;
  LifeValue *v = life_local(l, local);
  return v ? *v : (LifeValue){0};
}
static void life_set_field(Life *l, uint32_t local, uint32_t field, LifeValue value) {
  for (size_t i = 0; i < l->field_count; ++i)
    if (l->fields[i].local == local && l->fields[i].field == field) { l->fields[i].value = value; return; }
  if (l->field_count >= 512) return;
  if (l->field_count == l->field_capacity) {
    size_t capacity = l->field_capacity ? l->field_capacity * 2 : 16;
    LifeField *fields = realloc(l->fields, capacity * sizeof(*fields));
    if (!fields) { l->a->allocation_failed = true; return; }
    l->fields = fields; l->field_capacity = capacity;
  }
  l->fields[l->field_count++] = (LifeField){local, field, value};
}
static void life_clear_local_fields(Life *l, uint32_t local) {
  for (size_t j = 0; j < l->field_count;) {
    if (l->fields[j].local == local) l->fields[j] = l->fields[--l->field_count];
    else ++j;
  }
}
static void life_forget(Life *l) {
  memset(l->locals, 0, l->count * sizeof(*l->locals));
  l->field_count = 0;
}
static void life_forget_aliased(Life *l) {
  for (uint32_t i = 0; i < l->count; ++i) {
    if (l->addr_taken[i]) l->locals[i] = (LifeValue){0};
  }
  for (size_t j = 0; j < l->field_count;) {
    uint32_t loc = l->fields[j].local;
    if (loc >= l->first && loc - l->first < l->count && l->addr_taken[loc - l->first])
      l->fields[j] = l->fields[--l->field_count];
    else ++j;
  }
}
static void life_state_free(LifeState *s) {
  if (s->locals && s->locals != s->inline_locals) free(s->locals);
  if (s->fields && s->fields != s->inline_fields) free(s->fields);
  s->locals = NULL; s->fields = NULL;
  s->field_count = s->field_capacity = 0;
}
static bool life_state_clone(const Life *l, LifeState *out) {
  if (l->count <= LIFE_INLINE_LOCALS) {
    out->locals = out->inline_locals;
  } else {
    out->locals = malloc(l->count * sizeof(*out->locals));
    if (!out->locals) { l->a->allocation_failed = true; return false; }
  }
  memcpy(out->locals, l->locals, l->count * sizeof(*out->locals));
  out->field_count = l->field_count;
  if (!l->field_count) {
    out->fields = NULL;
    out->field_capacity = 0;
  } else if (l->field_count <= LIFE_INLINE_FIELDS) {
    out->fields = out->inline_fields;
    out->field_capacity = LIFE_INLINE_FIELDS;
    memcpy(out->fields, l->fields, l->field_count * sizeof(*out->fields));
  } else {
    out->fields = malloc(l->field_count * sizeof(*out->fields));
    if (!out->fields) {
      if (out->locals != out->inline_locals) free(out->locals);
      out->locals = NULL; l->a->allocation_failed = true; return false;
    }
    out->field_capacity = l->field_count;
    memcpy(out->fields, l->fields, l->field_count * sizeof(*out->fields));
  }
  return true;
}
static void life_state_restore(Life *l, const LifeState *in) {
  if (!in->locals) return;
  memcpy(l->locals, in->locals, l->count * sizeof(*l->locals));
  if (in->field_count > l->field_capacity) {
    size_t cap = in->field_count < 16 ? 16 : in->field_count;
    LifeField *f = realloc(l->fields, cap * sizeof(*f));
    if (!f) { l->a->allocation_failed = true; l->field_count = 0; return; }
    l->fields = f; l->field_capacity = cap;
  }
  if (in->field_count) memcpy(l->fields, in->fields, in->field_count * sizeof(*l->fields));
  l->field_count = in->field_count;
}
static LifeValue life_state_field_val(const Life *l, const LifeState *s, uint32_t local, uint32_t field) {
  for (size_t i = s->field_count; i; --i)
    if (s->fields[i - 1].local == local && s->fields[i - 1].field == field) return s->fields[i - 1].value;
  return local >= l->first && local - l->first < l->count ? s->locals[local - l->first] : (LifeValue){0};
}
static bool life_state_set_field(const Life *l, LifeState *s, uint32_t local, uint32_t field, LifeValue value) {
  for (size_t i = 0; i < s->field_count; ++i) {
    if (s->fields[i].local == local && s->fields[i].field == field) {
      bool changed = value.stack != s->fields[i].value.stack;
      s->fields[i].value = value;
      return changed;
    }
  }
  if (s->field_count >= 512) return false;
  if (s->field_count == s->field_capacity) {
    if (!s->fields) {
      s->fields = s->inline_fields;
      s->field_capacity = LIFE_INLINE_FIELDS;
    } else {
      size_t cap = s->field_capacity * 2;
      LifeField *f = s->fields == s->inline_fields
                         ? malloc(cap * sizeof(*f))
                         : realloc(s->fields, cap * sizeof(*f));
      if (!f) { l->a->allocation_failed = true; return false; }
      if (s->fields == s->inline_fields) memcpy(f, s->inline_fields, s->field_count * sizeof(*f));
      s->fields = f; s->field_capacity = cap;
    }
  }
  s->fields[s->field_count++] = (LifeField){local, field, value};
  return value.stack;
}
static bool life_state_join(const Life *l, LifeState *dst, bool *dst_valid, const LifeState *src) {
  if (!src->locals) return false;
  if (!*dst_valid) {
    if (l->count <= LIFE_INLINE_LOCALS) {
      dst->locals = dst->inline_locals;
    } else {
      dst->locals = malloc(l->count * sizeof(*dst->locals));
      if (!dst->locals) { l->a->allocation_failed = true; return false; }
    }
    memcpy(dst->locals, src->locals, l->count * sizeof(*dst->locals));
    dst->field_count = src->field_count;
    if (!src->field_count) {
      dst->fields = NULL;
      dst->field_capacity = 0;
    } else if (src->field_count <= LIFE_INLINE_FIELDS) {
      dst->fields = dst->inline_fields;
      dst->field_capacity = LIFE_INLINE_FIELDS;
      memcpy(dst->fields, src->fields, src->field_count * sizeof(*dst->fields));
    } else {
      dst->fields = malloc(src->field_count * sizeof(*dst->fields));
      if (!dst->fields) {
        if (dst->locals != dst->inline_locals) free(dst->locals);
        dst->locals = NULL; l->a->allocation_failed = true; return false;
      }
      dst->field_capacity = src->field_count;
      memcpy(dst->fields, src->fields, src->field_count * sizeof(*dst->fields));
    }
    *dst_valid = true;
    return true;
  }
  bool changed = false;
  /* Snapshot dst's locals before updating so missing fields compare accurately. */
  for (size_t i = 0; i < dst->field_count; ++i) {
    LifeValue sv = life_state_field_val(l, src, dst->fields[i].local, dst->fields[i].field);
    LifeValue joined = life_join(dst->fields[i].value, sv);
    if (joined.stack != dst->fields[i].value.stack) changed = true;
    dst->fields[i].value = joined;
  }
  for (size_t i = 0; i < src->field_count; ++i) {
    uint32_t loc = src->fields[i].local, fld = src->fields[i].field;
    bool exists = false;
    for (size_t j = 0; j < dst->field_count; ++j)
      if (dst->fields[j].local == loc && dst->fields[j].field == fld) { exists = true; break; }
    if (!exists) {
      LifeValue dv = loc >= l->first && loc - l->first < l->count ? dst->locals[loc - l->first] : (LifeValue){0};
      LifeValue joined = life_join(dv, src->fields[i].value);
      if (life_state_set_field(l, dst, loc, fld, joined)) changed = true;
    }
  }
  for (uint32_t i = 0; i < l->count; ++i) {
    bool prev = dst->locals[i].stack;
    dst->locals[i] = life_join(dst->locals[i], src->locals[i]);
    if (dst->locals[i].stack != prev) changed = true;
  }
  return changed;
}
static bool life_state_join_live(const Life *l, LifeState *dst, bool *dst_valid) {
  LifeState cur = {.locals = l->locals, .fields = l->fields, .field_count = l->field_count};
  return life_state_join(l, dst, dst_valid, &cur);
}

/* Pre-scan which locals ever have their address taken so calls and indirect
   writes only invalidate potentially aliased locals. */
static void life_mark_base_addr_taken(Life *l, DynExprId id, unsigned depth) {
  DynAstProgram *a = l->a;
  while (id != DYN_NO_EXPR && id < a->expression_count && depth < 64) {
    DynAstExpr *e = &a->expressions[id];
    if (e->kind == DYN_EXPR_NAME) {
      if (e->integer >= l->first && e->integer - l->first < l->count)
        l->addr_taken[e->integer - l->first] = true;
      return;
    }
    if (e->kind == DYN_EXPR_FIELD && !e->boolean && !dyn_type_is_pointer(a->expressions[e->left].type)) {
      id = e->left; ++depth; continue;
    }
    if ((e->kind == DYN_EXPR_INDEX || e->kind == DYN_EXPR_SLICE) &&
        e->left != DYN_NO_EXPR && dyn_type_is_array(a->expressions[e->left].type)) {
      id = e->left; ++depth; continue;
    }
    return;
  }
}
static void life_scan_block(Life *l, uint32_t start, uint32_t count, unsigned depth);
static void life_scan_expr(Life *l, DynExprId id, unsigned depth) {
  DynAstProgram *a = l->a;
  if (id == DYN_NO_EXPR || id >= a->expression_count || depth > 256) return;
  DynAstExpr *e = &a->expressions[id];
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_ADDRESS)
    life_mark_base_addr_taken(l, e->left, 0);
  life_scan_expr(l, e->left, depth + 1);
  life_scan_expr(l, e->right, depth + 1);
  if (e->kind == DYN_EXPR_SLICE)
    life_scan_expr(l, (DynExprId)e->integer, depth + 1);
  if (e->kind == DYN_EXPR_CATCH && e->boolean) {
    life_scan_block(l, e->item_start, e->item_count, depth + 1);
  } else if (e->kind != DYN_EXPR_OFFSET) {
    for (uint32_t i = 0; i < e->item_count; ++i)
      life_scan_expr(l, a->items[e->item_start + i].expression, depth + 1);
  }
}
static void life_scan_block(Life *l, uint32_t start, uint32_t count, unsigned depth) {
  DynAstProgram *a = l->a;
  if (depth > 256) return;
  for (uint32_t i = 0; i < count; ++i) {
    DynAstStmt *st = &a->statements[a->children[start + i]];
    life_scan_expr(l, st->expression, depth + 1);
    life_scan_expr(l, st->target, depth + 1);
    if (st->for_step) life_scan_expr(l, st->step, depth + 1);
    if (st->kind == DYN_STMT_FOR && st->for_pointer && st->target != DYN_NO_EXPR)
      life_mark_base_addr_taken(l, st->target, 0);
    life_scan_block(l, st->body_start, st->body_count, depth + 1);
    life_scan_block(l, st->else_start, st->else_count, depth + 1);
    if (st->kind == DYN_STMT_CASE) {
      for (uint32_t j = 0; j < st->case_arm_count; ++j) {
        DynAstCaseArm *arm = &a->case_arms[st->case_arm_start + j];
        if (arm->pointer_binding && st->expression != DYN_NO_EXPR)
          life_mark_base_addr_taken(l, st->expression, 0);
        life_scan_block(l, arm->body_start, arm->body_count, depth + 1);
      }
    }
  }
}

static LifeValue life_expr(Life *l, DynExprId id, unsigned depth) {
  LifeValue v = {0}; DynAstProgram *a = l->a;
  if (id == DYN_NO_EXPR || id >= a->expression_count || depth > 128 || !dyn_work_step(&l->source->context, 1)) return v;
  DynAstExpr *e = &a->expressions[id];
  if (e->kind == DYN_EXPR_NAME) {
    LifeValue *p = life_local(l, (uint32_t)e->integer);
    if (p) v = *p;
    for (size_t i = 0; i < l->field_count; ++i)
      if (l->fields[i].local == e->integer) v = life_join(v, l->fields[i].value);
  } else if (e->kind == DYN_EXPR_FIELD && a->expressions[e->left].kind == DYN_EXPR_NAME && !e->boolean) {
    v = life_field(l, (uint32_t)a->expressions[e->left].integer, (uint32_t)e->integer);
  } else if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_ADDRESS && a->expressions[e->left].kind == DYN_EXPR_NAME) {
    uint32_t local = (uint32_t)a->expressions[e->left].integer;
    v.stack = life_local(l, local) != NULL; v.address = local + 1;
  } else if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_ADDRESS && a->expressions[e->left].kind == DYN_EXPR_STRUCT) {
    /* &T{...} lives in this function's frame, like a local. */
    v = life_expr(l, e->left, depth + 1); v.stack = true;
  } else if (e->kind == DYN_EXPR_TAKE) {
    DynExprId ptr = e->left;
    if (ptr != DYN_NO_EXPR && a->expressions[ptr].kind == DYN_EXPR_UNARY &&
        a->expressions[ptr].op == DYN_OP_ADDRESS &&
        a->expressions[a->expressions[ptr].left].kind == DYN_EXPR_NAME) {
      uint32_t local = (uint32_t)a->expressions[a->expressions[ptr].left].integer;
      v = life_expr(l, a->expressions[ptr].left, depth + 1);
      LifeValue *p = life_local(l, local);
      if (p) *p = (LifeValue){0};
      life_clear_local_fields(l, local);
    } else {
      (void)life_expr(l, ptr, depth + 1);
    }
  } else if (e->kind == DYN_EXPR_TRY) {
    v = life_expr(l, e->left, depth + 1);
  } else if (e->kind == DYN_EXPR_CATCH) {
    v = life_expr(l, e->left, depth + 1);
    if (e->boolean) {
      LifeState saved = {0};
      if (life_state_clone(l, &saved)) {
        (void)life_block(l, e->item_start, e->item_count, depth + 1);
        life_state_restore(l, &saved);
        life_state_free(&saved);
      }
    } else {
      LifeValue fb = life_expr(l, e->right, depth + 1);
      v = life_join(v, fb);
    }
  } else {
    LifeValue left = life_expr(l, e->left, depth + 1), right = life_expr(l, e->right, depth + 1);
    if (e->kind == DYN_EXPR_SLICE) (void)life_expr(l, (DynExprId)e->integer, depth + 1);
    bool view = e->kind == DYN_EXPR_SLICE || e->kind == DYN_EXPR_CAST || e->kind == DYN_EXPR_CONVERT ||
                e->kind == DYN_EXPR_BITCAST || e->kind == DYN_EXPR_FIELD || e->kind == DYN_EXPR_INDEX ||
                e->kind == DYN_EXPR_UNARY;
    if (view && life_borrow_type(a, e->type, 0)) v = left;
    (void)right;
    if (returns_local_borrow(l->sema, a, id)) v.stack = true;
    if (e->kind != DYN_EXPR_OFFSET) {
      for (uint32_t i = 0; i < e->item_count; ++i) {
        LifeValue item = life_expr(l, a->items[e->item_start + i].expression, depth + 1);
        if (e->kind == DYN_EXPR_STRUCT || e->kind == DYN_EXPR_ARRAY || e->kind == DYN_EXPR_ENUM)
          v = life_join(v, item);
      }
    }
    /* A callee may overwrite any address-exposed local, but cannot mutate
       locals whose address was never taken. */
    if (e->kind == DYN_EXPR_CALL || e->kind == DYN_EXPR_INDIRECT_CALL)
      life_forget_aliased(l);
  }
  if (!life_borrow_type(a, e->type, 0)) { v.stack = false; v.address = 0; }
  return v;
}

/* Whether a pointer comes from outside this call: a parameter, a global, or
   a pointer read through one of them. */
static bool life_outside_pointer(Life *l, DynExprId id, unsigned depth) {
  DynAstProgram *a = l->a;
  if (id == DYN_NO_EXPR || id >= a->expression_count || depth > 64) return false;
  DynAstExpr *e = &a->expressions[id];
  if (e->kind == DYN_EXPR_NAME) return e->integer >= l->first && e->integer < (uint64_t)l->first + l->params;
  if (e->kind == DYN_EXPR_GLOBAL) return true;
  if (e->kind == DYN_EXPR_FIELD || e->kind == DYN_EXPR_INDEX || e->kind == DYN_EXPR_CONVERT || e->kind == DYN_EXPR_CAST ||
      (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_DEREF))
    return life_outside_pointer(l, e->left, depth + 1);
  return false;
}
/* Whether a write to target lands where the caller or a global can see it. */
static bool life_target_escapes(Life *l, DynExprId id, unsigned depth) {
  DynAstProgram *a = l->a;
  if (id == DYN_NO_EXPR || id >= a->expression_count || depth > 64) return false;
  DynAstExpr *e = &a->expressions[id];
  if (e->kind == DYN_EXPR_GLOBAL) return true;
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_DEREF) return life_outside_pointer(l, e->left, depth + 1);
  if (e->kind == DYN_EXPR_FIELD) {
    if (dyn_type_is_pointer(a->expressions[e->left].type)) return life_outside_pointer(l, e->left, depth + 1);
    return life_target_escapes(l, e->left, depth + 1);
  }
  if (e->kind == DYN_EXPR_INDEX) {
    if (dyn_type_is_array(a->expressions[e->left].type)) return life_target_escapes(l, e->left, depth + 1);
    return life_outside_pointer(l, e->left, depth + 1);
  }
  return false;
}

static LifeLoop *life_find_loop(Life *l, uint32_t target_loop_id) {
  if (!l->loop_depth) return NULL;
  if (target_loop_id == UINT32_MAX) return &l->loops[l->loop_depth - 1];
  for (uint32_t i = l->loop_depth; i; --i)
    if (l->loops[i - 1].loop_id == target_loop_id) return &l->loops[i - 1];
  return &l->loops[l->loop_depth - 1];
}

static bool life_block(Life *l, uint32_t start, uint32_t count, unsigned depth) {
  if (depth > 128) { life_forget(l); return false; }
  for (uint32_t i = 0; i < count && dyn_work_step(&l->source->context, 1); ++i) {
    DynAstStmt *st = &l->a->statements[l->a->children[start + i]];
    if (st->kind == DYN_STMT_DEFER || st->kind == DYN_STMT_ERRDEFER) {
      /* Defers execute later; never simulate their invalidations inline. */
      continue;
    }
    if (st->kind == DYN_STMT_BREAK) {
      LifeLoop *lp = life_find_loop(l, st->target_loop_id);
      if (lp) life_state_join_live(l, &lp->break_state, &lp->has_break);
      return true;
    }
    if (st->kind == DYN_STMT_CONTINUE) {
      LifeLoop *lp = life_find_loop(l, st->target_loop_id);
      if (lp) life_state_join_live(l, &lp->cont_state, &lp->has_cont);
      return true;
    }
    if (st->kind == DYN_STMT_PANIC) {
      (void)life_expr(l, st->expression, 0);
      return true;
    }
    if (st->kind == DYN_STMT_IF) {
      if (st->bare_block) {
        if (life_block(l, st->body_start, st->body_count, depth + 1)) return true;
        continue;
      }
      (void)life_expr(l, st->expression, 0);
      LifeState entry = {0}, then_out = {0};
      if (!life_state_clone(l, &entry)) { life_forget(l); continue; }
      bool then_term = life_block(l, st->body_start, st->body_count, depth + 1);
      bool have_then = !then_term && life_state_clone(l, &then_out);
      life_state_restore(l, &entry);
      bool else_term = st->else_count ? life_block(l, st->else_start, st->else_count, depth + 1) : false;
      life_state_free(&entry);
      if (then_term && else_term) {
        life_state_free(&then_out);
        return true;
      }
      if (!then_term && else_term) {
        if (have_then) life_state_restore(l, &then_out);
      } else if (!then_term && !else_term && have_then) {
        LifeState merged = {0};
        bool mv = false;
        life_state_join(l, &merged, &mv, &then_out);
        life_state_join_live(l, &merged, &mv);
        life_state_restore(l, &merged);
        life_state_free(&merged);
      }
      life_state_free(&then_out);
      continue;
    }
    if (st->kind == DYN_STMT_CASE) {
      LifeValue subj = life_expr(l, st->expression, 0);
      bool subj_is_local_lval = st->expression != DYN_NO_EXPR &&
                                l->a->expressions[st->expression].kind == DYN_EXPR_NAME &&
                                life_local(l, (uint32_t)l->a->expressions[st->expression].integer) != NULL;
      LifeState entry = {0}, merged = {0};
      bool has_merged = false;
      if (!life_state_clone(l, &entry)) { life_forget(l); continue; }
      for (uint32_t j = 0; j < st->case_arm_count; ++j) {
        DynAstCaseArm *arm = &l->a->case_arms[st->case_arm_start + j];
        life_state_restore(l, &entry);
        if (arm->local_id != UINT32_MAX) {
          LifeValue *bp = life_local(l, arm->local_id);
          if (bp) {
            if (arm->pointer_binding)
              *bp = (LifeValue){.stack = subj_is_local_lval || subj.stack, .address = 0};
            else
              *bp = subj;
          }
        }
        bool arm_term = life_block(l, arm->body_start, arm->body_count, depth + 1);
        if (!arm_term) life_state_join_live(l, &merged, &has_merged);
      }
      life_state_free(&entry);
      if (!has_merged) {
        life_state_free(&merged);
        return true;
      }
      life_state_restore(l, &merged);
      life_state_free(&merged);
      continue;
    }
    if (st->kind == DYN_STMT_FOR) {
      LifeValue target_val = life_expr(l, st->target, 0);
      (void)life_expr(l, st->expression, 0);
      if (st->for_step) (void)life_expr(l, st->step, 0);
      if (st->for_pointer && st->local_id != UINT32_MAX) {
        LifeValue *lp = life_local(l, st->local_id);
        bool arr_local = st->target != DYN_NO_EXPR &&
                         l->a->expressions[st->target].kind == DYN_EXPR_NAME &&
                         dyn_type_is_array(l->a->expressions[st->target].type) &&
                         life_local(l, (uint32_t)l->a->expressions[st->target].integer) != NULL;
        if (lp) *lp = (LifeValue){.stack = arr_local || target_val.stack, .address = 0};
      }
      if (l->loop_depth >= 64) { life_forget(l); continue; }
      LifeLoop *loop = &l->loops[l->loop_depth++];
      *loop = (LifeLoop){.loop_id = st->loop_id};
      LifeState header = {0};
      if (!life_state_clone(l, &header)) { --l->loop_depth; life_forget(l); continue; }
      bool prev_emit = l->emit_errors;
      l->emit_errors = false;
      for (unsigned iter = 0; iter < 16; ++iter) {
        life_state_free(&loop->cont_state);
        loop->has_cont = false;
        life_state_restore(l, &header);
        bool body_term = life_block(l, st->body_start, st->body_count, depth + 1);
        bool hv = true, changed = false;
        if (!body_term) changed |= life_state_join_live(l, &header, &hv);
        if (loop->has_cont) changed |= life_state_join(l, &header, &hv, &loop->cont_state);
        if (!changed) break;
      }
      /* Final pass on converged loop header state with diagnostics enabled. */
      life_state_free(&loop->break_state); loop->has_break = false;
      life_state_free(&loop->cont_state); loop->has_cont = false;
      l->emit_errors = prev_emit;
      life_state_restore(l, &header);
      (void)life_block(l, st->body_start, st->body_count, depth + 1);
      bool endless = !st->for_range && st->target == DYN_NO_EXPR && st->expression == DYN_NO_EXPR;
      if (endless) {
        if (!loop->has_break) {
          life_state_free(&header);
          life_state_free(&loop->break_state);
          life_state_free(&loop->cont_state);
          --l->loop_depth;
          return true;
        }
        life_state_restore(l, &loop->break_state);
      } else {
        if (loop->has_break) {
          bool hv = true;
          life_state_join(l, &header, &hv, &loop->break_state);
        }
        life_state_restore(l, &header);
      }
      life_state_free(&header);
      life_state_free(&loop->break_state);
      life_state_free(&loop->cont_state);
      --l->loop_depth;
      continue;
    }
    LifeValue value = life_expr(l, st->expression, 0);
    if (st->kind == DYN_STMT_RETURN || st->kind == DYN_STMT_FAIL) {
      if (l->emit_errors && value.stack && !returns_local_borrow(l->sema, l->a, st->expression))
        error_span(st->span, l->source, l->errors, "returned value borrows function-local storage through an alias");
      return true;
    }
    if (st->kind == DYN_STMT_LOCAL || (st->kind == DYN_STMT_ASSIGN && st->target == DYN_NO_EXPR && st->assignment_op == DYN_OP_NONE && !discard_name(st->name, l->source))) {
      LifeValue *p = life_local(l, st->local_id);
      if (!p) continue;
      life_clear_local_fields(l, st->local_id);
      *p = value;
      if (st->expression != DYN_NO_EXPR) {
        DynAstExpr *source = &l->a->expressions[st->expression];
        if (source->kind == DYN_EXPR_NAME && dyn_type_is_struct(source->type) && source->integer != st->local_id) {
          LifeValue *original = life_local(l, (uint32_t)source->integer);
          *p = original ? *original : (LifeValue){0};
          size_t fields = l->field_count;
          for (size_t j = 0; j < fields; ++j) if (l->fields[j].local == source->integer) {
            LifeField field = l->fields[j];
            life_set_field(l, st->local_id, field.field, field.value);
          }
        }
      }
      if (st->expression != DYN_NO_EXPR) {
        DynAstExpr *e = &l->a->expressions[st->expression];
        if (e->kind == DYN_EXPR_STRUCT) {
          *p = (LifeValue){0};
          for (uint32_t j = 0; j < e->item_count; ++j) {
            DynAstItem *item = &l->a->items[e->item_start + j];
            life_set_field(l, st->local_id, item->field_index, life_expr(l, item->expression, 0));
          }
        }
      }
    } else if (st->kind == DYN_STMT_ASSIGN && st->target != DYN_NO_EXPR) {
      DynAstExpr *target = &l->a->expressions[st->target];
      (void)life_expr(l, st->target, 0);
      bool direct_field = target->kind == DYN_EXPR_FIELD && !target->boolean && l->a->expressions[target->left].kind == DYN_EXPR_NAME;
      if (direct_field) life_set_field(l, (uint32_t)l->a->expressions[target->left].integer, (uint32_t)target->integer, value);
      else {
        if (l->emit_errors && value.stack && life_target_escapes(l, st->target, 0))
          error_span(st->span, l->source, l->errors, "stores the address of function-local storage where it outlives the function");
        life_forget_aliased(l);
      }
    }
  }
  return false;
}

static void life_check_function(Sema *sema, DynAstProgram *a, const DynSource *s, unsigned *errors, DynAstFn *fn) {
  if (*errors || !fn->local_count) return;
  LifeValue stack_locals[LIFE_INLINE_LOCALS];
  bool stack_addr[LIFE_INLINE_LOCALS];
  Life l = {.sema = sema, .a = a, .source = s, .errors = errors,
            .first = fn->local_start, .count = fn->local_count,
            .params = fn->param_count, .emit_errors = true};
  if (l.count <= LIFE_INLINE_LOCALS) {
    memset(stack_locals, 0, l.count * sizeof(*stack_locals));
    memset(stack_addr, 0, l.count * sizeof(*stack_addr));
    l.locals = stack_locals;
    l.addr_taken = stack_addr;
  } else {
    l.locals = calloc(l.count, sizeof(*l.locals));
    l.addr_taken = calloc(l.count, sizeof(*l.addr_taken));
    if (!l.locals || !l.addr_taken) {
      free(l.locals); free(l.addr_taken);
      a->allocation_failed = true;
      return;
    }
  }
  life_scan_block(&l, fn->body_start, fn->body_count, 0);
  (void)life_block(&l, fn->body_start, fn->body_count, 0);
  if (l.locals != stack_locals) free(l.locals);
  if (l.addr_taken != stack_addr) free(l.addr_taken);
  free(l.fields);
}
#endif
