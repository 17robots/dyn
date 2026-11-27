/* Lowering pass for Phase 3 error handling (T!E, A | B, try, catch, fail,
   errdefer). Runs at the end of sema_check_function before fn->local_count
   is finalized, rewriting all Phase 3 constructs into standard Dyn AST
   (payload enums, case, if, defer, return, locals) so all backends work
   unchanged. */

typedef struct {
  uint32_t stack[16];
  uint32_t *data;
  uint32_t count, cap;
} ErrStmtBuf;

static void el_buf_init(ErrStmtBuf *b) {
  b->data = b->stack;
  b->count = 0;
  b->cap = 16;
}
static void el_buf_free(ErrStmtBuf *b) {
  if (b->data != b->stack) free(b->data);
}
static bool el_buf_push(ErrStmtBuf *b, uint32_t stmt_id, DynAstProgram *a) {
  if (b->count == b->cap) {
    uint32_t next = b->cap * 2;
    uint32_t *grown = malloc(next * sizeof(*grown));
    if (!grown) { a->allocation_failed = true; return false; }
    memcpy(grown, b->data, b->count * sizeof(*grown));
    if (b->data != b->stack) free(b->data);
    b->data = grown;
    b->cap = next;
  }
  b->data[b->count++] = stmt_id;
  return true;
}

typedef struct {
  DynAstProgram *a;
  uint32_t fn_id;
  DynType fn_ret;
  bool fn_fallible;
  DynType fn_ok;
  DynType fn_err;
  uint32_t failed_local;
  bool instrument_race;
  bool in_addr;
  uint32_t race_read_fn;
  uint32_t race_write_fn;
  bool oom;
} ErrLower;

static bool el_reserve_stmt(DynAstProgram *a) {
  if (a->statement_count < a->statement_capacity) return true;
  size_t c = a->statement_capacity ? a->statement_capacity * 2 : 32;
  void *p = realloc(a->statements, c * sizeof(*a->statements));
  if (!p) { a->allocation_failed = true; return false; }
  a->statements = p;
  a->statement_capacity = c;
  return true;
}
static bool el_reserve_children(DynAstProgram *a, size_t extra) {
  if (a->child_count + extra <= a->child_capacity) return true;
  size_t c = a->child_capacity ? a->child_capacity * 2 : 32;
  while (c < a->child_count + extra) c *= 2;
  void *p = realloc(a->children, c * sizeof(*a->children));
  if (!p) { a->allocation_failed = true; return false; }
  a->children = p;
  a->child_capacity = c;
  return true;
}
static bool el_reserve_arms(DynAstProgram *a, size_t extra) {
  if (a->case_arm_count + extra <= a->case_arm_capacity) return true;
  size_t c = a->case_arm_capacity ? a->case_arm_capacity * 2 : 16;
  while (c < a->case_arm_count + extra) c *= 2;
  void *p = realloc(a->case_arms, c * sizeof(*a->case_arms));
  if (!p) { a->allocation_failed = true; return false; }
  a->case_arms = p;
  a->case_arm_capacity = c;
  return true;
}
static bool el_reserve_patterns(DynAstProgram *a, size_t extra) {
  if (a->pattern_count + extra <= a->pattern_capacity) return true;
  size_t c = a->pattern_capacity ? a->pattern_capacity * 2 : 16;
  while (c < a->pattern_count + extra) c *= 2;
  void *p = realloc(a->patterns, c * sizeof(*a->patterns));
  if (!p) { a->allocation_failed = true; return false; }
  a->patterns = p;
  a->pattern_capacity = c;
  return true;
}
static bool el_reserve_item(DynAstProgram *a) {
  if (a->item_count < a->item_capacity) return true;
  size_t c = a->item_capacity ? a->item_capacity * 2 : 32;
  void *p = realloc(a->items, c * sizeof(*a->items));
  if (!p) { a->allocation_failed = true; return false; }
  a->items = p;
  a->item_capacity = c;
  return true;
}

static uint32_t el_new_local(ErrLower *el, DynType type) {
  DynAstProgram *a = el->a;
  if (!reserve_local(a)) { el->oom = true; return UINT32_MAX; }
  uint32_t id = (uint32_t)a->local_count;
  a->locals[a->local_count++] = (DynAstLocal){
      .type = type, .used = true, .owner_function = el->fn_id};
  return id;
}
static DynExprId el_expr_name(ErrLower *el, uint32_t local_id, DynType type, DynSpan span) {
  DynExprId id = sema_push_expr(el->a, (DynAstExpr){
      .kind = DYN_EXPR_NAME, .type = type, .span = span,
      .left = DYN_NO_EXPR, .right = DYN_NO_EXPR, .integer = local_id});
  if (id == DYN_NO_EXPR) el->oom = true;
  return id;
}
static DynExprId el_expr_bool(ErrLower *el, bool val, DynSpan span) {
  DynExprId id = sema_push_expr(el->a, (DynAstExpr){
      .kind = DYN_EXPR_BOOL, .type = DYN_TYPE_BOOL, .span = span,
      .left = DYN_NO_EXPR, .right = DYN_NO_EXPR, .boolean = val});
  if (id == DYN_NO_EXPR) el->oom = true;
  return id;
}
static DynExprId el_expr_u32(ErrLower *el, uint64_t val, DynSpan span) {
  DynExprId id = sema_push_expr(el->a, (DynAstExpr){
      .kind = DYN_EXPR_INT, .type = DYN_TYPE_U32, .span = span,
      .left = DYN_NO_EXPR, .right = DYN_NO_EXPR, .integer = val});
  if (id == DYN_NO_EXPR) el->oom = true;
  return id;
}
static DynExprId el_expr_enum(ErrLower *el, DynType enum_type, uint32_t variant_id,
                              DynExprId payload, DynSpan span) {
  DynAstProgram *a = el->a;
  uint32_t item_start = 0, item_count = 0;
  if (payload != DYN_NO_EXPR) {
    if (!el_reserve_item(a)) { el->oom = true; return DYN_NO_EXPR; }
    item_start = (uint32_t)a->item_count;
    a->items[a->item_count++] = (DynAstItem){.expression = payload, .field_index = UINT32_MAX};
    item_count = 1;
  }
  DynExprId id = sema_push_expr(a, (DynAstExpr){
      .kind = DYN_EXPR_ENUM, .type = enum_type, .span = span,
      .left = DYN_NO_EXPR, .right = DYN_NO_EXPR, .integer = variant_id,
      .boolean = payload != DYN_NO_EXPR, .item_start = item_start, .item_count = item_count});
  if (id == DYN_NO_EXPR) el->oom = true;
  return id;
}
static uint32_t el_push_stmt(ErrLower *el, DynAstStmt st) {
  DynAstProgram *a = el->a;
  if (!el_reserve_stmt(a)) { el->oom = true; return UINT32_MAX; }
  uint32_t id = (uint32_t)a->statement_count;
  a->statements[a->statement_count++] = st;
  return id;
}
static void el_commit_children(ErrLower *el, const ErrStmtBuf *buf, uint32_t *out_start, uint32_t *out_count) {
  DynAstProgram *a = el->a;
  *out_count = buf->count;
  if (!buf->count) { *out_start = (uint32_t)a->child_count; return; }
  if (!el_reserve_children(a, buf->count)) { el->oom = true; *out_start = 0; *out_count = 0; return; }
  *out_start = (uint32_t)a->child_count;
  memcpy(a->children + a->child_count, buf->data, buf->count * sizeof(uint32_t));
  a->child_count += buf->count;
}
static uint32_t el_stmt_local(ErrLower *el, uint32_t local_id, DynType type, DynExprId init,
                              DynSpan span, uint32_t loop_depth) {
  return el_push_stmt(el, (DynAstStmt){
      .kind = DYN_STMT_LOCAL, .span = span, .declared_type = type,
      .expression = init, .target = DYN_NO_EXPR, .local_id = local_id,
      .loop_depth = loop_depth, .target_loop_id = UINT32_MAX});
}
static uint32_t el_stmt_assign_local(ErrLower *el, uint32_t local_id, DynExprId value,
                                     DynSpan span, uint32_t loop_depth) {
  return el_push_stmt(el, (DynAstStmt){
      .kind = DYN_STMT_ASSIGN, .span = span, .expression = value,
      .target = DYN_NO_EXPR, .assignment_op = DYN_OP_NONE, .local_id = local_id,
      .loop_depth = loop_depth, .target_loop_id = UINT32_MAX});
}
static uint32_t el_stmt_return(ErrLower *el, DynExprId value, DynSpan span, uint32_t loop_depth) {
  return el_push_stmt(el, (DynAstStmt){
      .kind = DYN_STMT_RETURN, .span = span, .expression = value,
      .target = DYN_NO_EXPR, .local_id = UINT32_MAX,
      .loop_depth = loop_depth, .target_loop_id = UINT32_MAX});
}
static DynExprId el_expr_addr_of(ErrLower *el, DynExprId lval, DynType pointee, bool is_const, DynSpan span) {
  DynType pt = sema_intern_pointer(el->a, pointee, is_const);
  DynExprId id = sema_push_expr(el->a, (DynAstExpr){
      .kind = DYN_EXPR_UNARY, .op = DYN_OP_ADDRESS, .type = pt, .span = span,
      .left = lval, .right = DYN_NO_EXPR});
  if (id == DYN_NO_EXPR) el->oom = true;
  return id;
}
static void el_emit_race_call(ErrLower *el, bool is_write, DynExprId ptr_expr, DynSpan span,
                              ErrStmtBuf *pre, uint32_t loop_depth) {
  uint32_t fn = is_write ? el->race_write_fn : el->race_read_fn;
  if (fn == UINT32_MAX || ptr_expr == DYN_NO_EXPR || el->oom) return;
  DynAstProgram *a = el->a;
  DynExprId as_usize = sema_push_expr(a, (DynAstExpr){
      .kind = DYN_EXPR_CAST, .type = DYN_TYPE_USIZE, .span = span,
      .left = ptr_expr, .right = DYN_NO_EXPR});
  DynExprId as_u64 = sema_push_expr(a, (DynAstExpr){
      .kind = DYN_EXPR_CAST, .type = DYN_TYPE_U64, .span = span,
      .left = as_usize, .right = DYN_NO_EXPR});
  DynExprId sz = sema_push_expr(a, (DynAstExpr){
      .kind = DYN_EXPR_INT, .type = DYN_TYPE_U64, .span = span,
      .left = DYN_NO_EXPR, .right = DYN_NO_EXPR, .integer = 8});
  if (as_usize == DYN_NO_EXPR || as_u64 == DYN_NO_EXPR || sz == DYN_NO_EXPR ||
      !el_reserve_item(a)) { el->oom = true; return; }
  uint32_t istart = (uint32_t)a->item_count;
  a->items[a->item_count++] = (DynAstItem){.expression = as_u64, .field_index = UINT32_MAX};
  if (!el_reserve_item(a)) { el->oom = true; return; }
  a->items[a->item_count++] = (DynAstItem){.expression = sz, .field_index = UINT32_MAX};
  DynExprId call = sema_push_expr(a, (DynAstExpr){
      .kind = DYN_EXPR_CALL, .type = DYN_TYPE_VOID, .span = span,
      .left = DYN_NO_EXPR, .right = DYN_NO_EXPR, .integer = fn,
      .item_start = istart, .item_count = 2});
  if (call == DYN_NO_EXPR) { el->oom = true; return; }
  uint32_t st = el_push_stmt(el, (DynAstStmt){
      .kind = DYN_STMT_EXPR, .span = span, .expression = call,
      .target = DYN_NO_EXPR, .local_id = UINT32_MAX,
      .loop_depth = loop_depth, .target_loop_id = UINT32_MAX});
  el_buf_push(pre, st, a);
}
static bool el_field_is_packed(DynAstProgram *a, DynType ptr_type) {
  const DynAstPointer *p = pointer_info(a, ptr_type);
  if (!p || !dyn_type_is_struct(p->pointee)) return false;
  return a->structs[p->pointee - DYN_TYPE_STRUCT_BASE].packed;
}
static bool el_skip_race_span(const DynSource *s, DynSpan span) {
  if (!s) return true;
  if (dyn_reflection_prelude_span(span, s)) return true;
  for (size_t i = 0; i < s->map_count; ++i) {
    if (span.start_byte >= s->maps[i].start && span.start_byte < s->maps[i].end) {
      const char *p = s->maps[i].path;
      if (!p) return false;
      if (strstr(p, "/std/sync/") || strstr(p, "/std/thread/") ||
          strstr(p, "/std/mem/") || strstr(p, "/std/os/") ||
          strstr(p, "/runtime/"))
        return true;
      return false;
    }
  }
  return false;
}

/* Scan whether an expression or statement tree needs error lowering or has errdefer. */
static bool el_expr_scan(const DynAstProgram *a, DynExprId id, bool *has_errdefer, unsigned depth);
static bool el_block_scan(const DynAstProgram *a, uint32_t start, uint32_t count, bool *has_errdefer, unsigned depth) {
  if (depth > 512) return false;
  bool needs = false;
  for (uint32_t i = 0; i < count; ++i) {
    const DynAstStmt *st = &a->statements[a->children[start + i]];
    if (st->kind == DYN_STMT_FAIL) needs = true;
    if (st->kind == DYN_STMT_ERRDEFER) { needs = true; *has_errdefer = true; }
    if (st->kind == DYN_STMT_CASE && st->expression != DYN_NO_EXPR &&
        type_is_error_union(a, a->expressions[st->expression].type))
      needs = true;
    if (el_expr_scan(a, st->expression, has_errdefer, depth + 1)) needs = true;
    if (el_expr_scan(a, st->target, has_errdefer, depth + 1)) needs = true;
    if (st->for_step && el_expr_scan(a, st->step, has_errdefer, depth + 1)) needs = true;
    if (el_block_scan(a, st->body_start, st->body_count, has_errdefer, depth + 1)) needs = true;
    if (el_block_scan(a, st->else_start, st->else_count, has_errdefer, depth + 1)) needs = true;
    if (st->kind == DYN_STMT_CASE) {
      for (uint32_t j = 0; j < st->case_arm_count; ++j) {
        const DynAstCaseArm *arm = &a->case_arms[st->case_arm_start + j];
        if (el_block_scan(a, arm->body_start, arm->body_count, has_errdefer, depth + 1)) needs = true;
      }
    }
  }
  return needs;
}
static bool el_expr_scan(const DynAstProgram *a, DynExprId id, bool *has_errdefer, unsigned depth) {
  if (id == DYN_NO_EXPR || id >= a->expression_count || depth > 512) return false;
  const DynAstExpr *e = &a->expressions[id];
  bool needs = false;
  if (e->kind == DYN_EXPR_TRY || e->kind == DYN_EXPR_CATCH || e->kind == DYN_EXPR_TAKE) needs = true;
  if (e->kind == DYN_EXPR_CONVERT && type_is_error_union(a, e->type)) needs = true;
  if (el_expr_scan(a, e->left, has_errdefer, depth + 1)) needs = true;
  if (el_expr_scan(a, e->right, has_errdefer, depth + 1)) needs = true;
  if (e->kind == DYN_EXPR_SLICE) {
    if (el_expr_scan(a, (DynExprId)e->integer, has_errdefer, depth + 1)) needs = true;
  }
  if (e->kind == DYN_EXPR_CATCH && e->boolean) {
    if (el_block_scan(a, e->item_start, e->item_count, has_errdefer, depth + 1)) needs = true;
  } else if (e->kind != DYN_EXPR_OFFSET) {
    for (uint32_t i = 0; i < e->item_count; ++i)
      if (el_expr_scan(a, a->items[e->item_start + i].expression, has_errdefer, depth + 1)) needs = true;
  }
  return needs;
}

static DynExprId el_lower_expr(ErrLower *el, DynExprId id, ErrStmtBuf *pre, uint32_t loop_depth);
static void el_lower_block(ErrLower *el, uint32_t *start, uint32_t *count, uint32_t loop_depth);

/* Find the variant index in error-union `u_type` holding constituent enum `member`. */
static uint32_t el_union_variant(const DynAstProgram *a, DynType u_type, DynType member) {
  const DynAstEnum *u = &a->enums[u_type - DYN_TYPE_ENUM_BASE];
  for (uint32_t i = 0; i < u->variant_count; ++i)
    if (a->variants[u->variant_start + i].payload_type == member)
      return u->variant_start + i;
  return UINT32_MAX;
}

/* Widen `expr` of type `from` to `to` (where `to` is an error union or equal to `from`). */
static DynExprId el_widen_error(ErrLower *el, DynExprId expr, DynType from, DynType to,
                                DynSpan span, ErrStmtBuf *pre, uint32_t loop_depth) {
  if (from == to || to == DYN_TYPE_VOID || from == DYN_TYPE_ERROR || to == DYN_TYPE_ERROR)
    return expr;
  DynAstProgram *a = el->a;
  if (!type_is_error_union(a, to)) return expr;
  if (!type_is_error_union(a, from)) {
    uint32_t v = el_union_variant(a, to, from);
    if (v == UINT32_MAX) return expr;
    return el_expr_enum(el, to, v, expr, span);
  }
  /* Smaller error union -> larger error union: dispatch per constituent enum. */
  uint32_t tmp = el_new_local(el, to);
  if (tmp == UINT32_MAX) return expr;
  uint32_t decl = el_stmt_local(el, tmp, to, DYN_NO_EXPR, span, loop_depth);
  el_buf_push(pre, decl, a);
  DynAstEnum from_en = a->enums[from - DYN_TYPE_ENUM_BASE];
  uint32_t mcount = from_en.variant_count;
  if (!el_reserve_arms(a, mcount) || !el_reserve_patterns(a, mcount)) { el->oom = true; return expr; }
  uint32_t arm_start = (uint32_t)a->case_arm_count;
  a->case_arm_count += mcount;
  for (uint32_t i = 0; i < mcount; ++i) {
    DynType mem = a->variants[from_en.variant_start + i].payload_type;
    uint32_t bind = el_new_local(el, mem);
    uint32_t dst_v = el_union_variant(a, to, mem);
    DynExprId b_expr = el_expr_name(el, bind, mem, span);
    DynExprId wrapped = el_expr_enum(el, to, dst_v, b_expr, span);
    uint32_t assign = el_stmt_assign_local(el, tmp, wrapped, span, loop_depth);
    ErrStmtBuf body;
    el_buf_init(&body);
    el_buf_push(&body, assign, a);
    uint32_t bstart = 0, bcount = 0;
    el_commit_children(el, &body, &bstart, &bcount);
    el_buf_free(&body);
    uint32_t pstart = (uint32_t)a->pattern_count;
    a->patterns[a->pattern_count++] = (DynAstPattern){
        .span = span, .first = DYN_NO_EXPR, .last = DYN_NO_EXPR,
        .variant = from_en.variant_start + i, .is_enum = true};
    a->case_arms[arm_start + i] = (DynAstCaseArm){
        .span = span, .pattern_start = pstart, .pattern_count = 1,
        .body_start = bstart, .body_count = bcount, .local_id = bind};
  }
  uint32_t cstmt = el_push_stmt(el, (DynAstStmt){
      .kind = DYN_STMT_CASE, .span = span, .expression = expr, .target = DYN_NO_EXPR,
      .local_id = UINT32_MAX, .case_arm_start = arm_start, .case_arm_count = mcount,
      .loop_depth = loop_depth, .target_loop_id = UINT32_MAX});
  el_buf_push(pre, cstmt, a);
  return el_expr_name(el, tmp, to, span);
}

static DynExprId el_lower_expr(ErrLower *el, DynExprId id, ErrStmtBuf *pre, uint32_t loop_depth) {
  if (id == DYN_NO_EXPR || el->oom) return id;
  DynAstProgram *a = el->a;
  DynAstExpr copy = a->expressions[id];
  if (copy.kind == DYN_EXPR_BINARY &&
      (copy.op == DYN_OP_LOGICAL_AND || copy.op == DYN_OP_LOGICAL_OR)) {
    DynExprId lhs = el_lower_expr(el, copy.left, pre, loop_depth);
    a->expressions[id].left = lhs;
    bool dummy = false;
    if (!el_expr_scan(a, copy.right, &dummy, 0)) return id;
    /* Preserve short-circuiting when RHS has try/catch/error-widening. */
    uint32_t res = el_new_local(el, DYN_TYPE_BOOL);
    if (res == UINT32_MAX) return id;
    el_buf_push(pre, el_stmt_local(el, res, DYN_TYPE_BOOL, lhs, copy.span, loop_depth), a);
    ErrStmtBuf rhs_buf;
    el_buf_init(&rhs_buf);
    DynExprId rhs = el_lower_expr(el, copy.right, &rhs_buf, loop_depth);
    el_buf_push(&rhs_buf, el_stmt_assign_local(el, res, rhs, copy.span, loop_depth), a);
    uint32_t bstart = 0, bcount = 0;
    el_commit_children(el, &rhs_buf, &bstart, &bcount);
    el_buf_free(&rhs_buf);
    DynExprId cond = el_expr_name(el, res, DYN_TYPE_BOOL, copy.span);
    if (copy.op == DYN_OP_LOGICAL_OR) {
      cond = sema_push_expr(a, (DynAstExpr){
          .kind = DYN_EXPR_UNARY, .op = DYN_OP_NOT, .type = DYN_TYPE_BOOL,
          .span = copy.span, .left = cond, .right = DYN_NO_EXPR});
    }
    uint32_t if_id = el_push_stmt(el, (DynAstStmt){
        .kind = DYN_STMT_IF, .span = copy.span, .expression = cond, .target = DYN_NO_EXPR,
        .local_id = UINT32_MAX, .body_start = bstart, .body_count = bcount,
        .loop_depth = loop_depth, .target_loop_id = UINT32_MAX});
    el_buf_push(pre, if_id, a);
    return el_expr_name(el, res, DYN_TYPE_BOOL, copy.span);
  }
  if (copy.kind == DYN_EXPR_CONVERT && type_is_error_union(a, copy.type)) {
    DynExprId inner = el_lower_expr(el, copy.left, pre, loop_depth);
    DynType from = a->expressions[inner].type;
    return el_widen_error(el, inner, from, copy.type, copy.span, pre, loop_depth);
  }
  if (copy.kind == DYN_EXPR_TAKE) {
    DynExprId ptr_expr = el_lower_expr(el, copy.left, pre, loop_depth);
    DynType ptr_t = a->expressions[ptr_expr].type;
    DynType pointee = copy.type;
    uint32_t ptr_local = el_new_local(el, ptr_t);
    uint32_t tmp_local = el_new_local(el, pointee);
    if (el->oom) return id;
    el_buf_push(pre, el_stmt_local(el, ptr_local, ptr_t, ptr_expr, copy.span, loop_depth), a);
    DynExprId deref_read = sema_push_expr(a, (DynAstExpr){
        .kind = DYN_EXPR_UNARY, .op = DYN_OP_DEREF, .type = pointee, .span = copy.span,
        .left = el_expr_name(el, ptr_local, ptr_t, copy.span), .right = DYN_NO_EXPR});
    el_buf_push(pre, el_stmt_local(el, tmp_local, pointee, deref_read, copy.span, loop_depth), a);
    DynExprId reset_val = DYN_NO_EXPR;
    if (copy.right != DYN_NO_EXPR) {
      reset_val = el_lower_expr(el, copy.right, pre, loop_depth);
    } else {
      uint32_t zero_local = el_new_local(el, pointee);
      if (el->oom) return id;
      el_buf_push(pre, el_stmt_local(el, zero_local, pointee, DYN_NO_EXPR, copy.span, loop_depth), a);
      reset_val = el_expr_name(el, zero_local, pointee, copy.span);
    }
    DynExprId deref_write = sema_push_expr(a, (DynAstExpr){
        .kind = DYN_EXPR_UNARY, .op = DYN_OP_DEREF, .type = pointee, .span = copy.span,
        .left = el_expr_name(el, ptr_local, ptr_t, copy.span), .right = DYN_NO_EXPR});
    uint32_t write_stmt = el_push_stmt(el, (DynAstStmt){
        .kind = DYN_STMT_ASSIGN, .span = copy.span, .expression = reset_val,
        .target = deref_write, .assignment_op = DYN_OP_NONE, .local_id = UINT32_MAX,
        .loop_depth = loop_depth, .target_loop_id = UINT32_MAX});
    el_buf_push(pre, write_stmt, a);
    return el_expr_name(el, tmp_local, pointee, copy.span);
  }
  if (copy.kind == DYN_EXPR_TRY) {
    DynExprId operand = el_lower_expr(el, copy.left, pre, loop_depth);
    DynType op_t = a->expressions[operand].type;
    if (!type_is_fallible(a, op_t)) return operand;
    DynAstEnum in_en = a->enums[op_t - DYN_TYPE_ENUM_BASE];
    DynAstEnum out_en = a->enums[el->fn_ret - DYN_TYPE_ENUM_BASE];
    uint32_t val_local = UINT32_MAX;
    if (in_en.ok_type != DYN_TYPE_VOID) {
      val_local = el_new_local(el, in_en.ok_type);
      el_buf_push(pre, el_stmt_local(el, val_local, in_en.ok_type, DYN_NO_EXPR, copy.span, loop_depth), a);
    }
    /* Arm 0: Ok */
    ErrStmtBuf ok_buf;
    el_buf_init(&ok_buf);
    uint32_t ok_bind = UINT32_MAX;
    if (in_en.ok_type != DYN_TYPE_VOID) {
      ok_bind = el_new_local(el, in_en.ok_type);
      DynExprId b_ref = el_expr_name(el, ok_bind, in_en.ok_type, copy.span);
      el_buf_push(&ok_buf, el_stmt_assign_local(el, val_local, b_ref, copy.span, loop_depth), a);
    }
    uint32_t ok_start = 0, ok_count = 0;
    el_commit_children(el, &ok_buf, &ok_start, &ok_count);
    el_buf_free(&ok_buf);
    /* Arm 1: Err */
    ErrStmtBuf err_buf;
    el_buf_init(&err_buf);
    uint32_t err_bind = UINT32_MAX;
    if (el->failed_local != UINT32_MAX) {
      DynExprId tval = el_expr_bool(el, true, copy.span);
      el_buf_push(&err_buf, el_stmt_assign_local(el, el->failed_local, tval, copy.span, loop_depth), a);
    }
    DynExprId ret_payload = DYN_NO_EXPR;
    if (out_en.err_type != DYN_TYPE_VOID) {
      err_bind = el_new_local(el, in_en.err_type);
      DynExprId e_ref = el_expr_name(el, err_bind, in_en.err_type, copy.span);
      ret_payload = el_widen_error(el, e_ref, in_en.err_type, out_en.err_type, copy.span, &err_buf, loop_depth);
    }
    DynExprId ret_val = el_expr_enum(el, el->fn_ret, out_en.variant_start + 1, ret_payload, copy.span);
    el_buf_push(&err_buf, el_stmt_return(el, ret_val, copy.span, loop_depth), a);
    uint32_t err_start = 0, err_count = 0;
    el_commit_children(el, &err_buf, &err_start, &err_count);
    el_buf_free(&err_buf);
    if (!el_reserve_arms(a, 2) || !el_reserve_patterns(a, 2)) { el->oom = true; return id; }
    uint32_t p0 = (uint32_t)a->pattern_count;
    a->patterns[a->pattern_count++] = (DynAstPattern){
        .span = copy.span, .first = DYN_NO_EXPR, .last = DYN_NO_EXPR,
        .variant = in_en.variant_start + 0, .is_enum = true};
    uint32_t p1 = (uint32_t)a->pattern_count;
    a->patterns[a->pattern_count++] = (DynAstPattern){
        .span = copy.span, .first = DYN_NO_EXPR, .last = DYN_NO_EXPR,
        .variant = in_en.variant_start + 1, .is_enum = true};
    uint32_t astart = (uint32_t)a->case_arm_count;
    a->case_arms[a->case_arm_count++] = (DynAstCaseArm){
        .span = copy.span, .pattern_start = p0, .pattern_count = 1,
        .body_start = ok_start, .body_count = ok_count, .local_id = ok_bind};
    a->case_arms[a->case_arm_count++] = (DynAstCaseArm){
        .span = copy.span, .pattern_start = p1, .pattern_count = 1,
        .body_start = err_start, .body_count = err_count, .local_id = err_bind};
    uint32_t cstmt = el_push_stmt(el, (DynAstStmt){
        .kind = DYN_STMT_CASE, .span = copy.span, .expression = operand, .target = DYN_NO_EXPR,
        .local_id = UINT32_MAX, .case_arm_start = astart, .case_arm_count = 2,
        .loop_depth = loop_depth, .target_loop_id = UINT32_MAX});
    el_buf_push(pre, cstmt, a);
    return val_local != UINT32_MAX ? el_expr_name(el, val_local, in_en.ok_type, copy.span)
                                   : el_expr_bool(el, true, copy.span);
  }
  if (copy.kind == DYN_EXPR_CATCH) {
    DynExprId operand = el_lower_expr(el, copy.left, pre, loop_depth);
    DynType op_t = a->expressions[operand].type;
    if (!type_is_fallible(a, op_t)) return operand;
    DynAstEnum in_en = a->enums[op_t - DYN_TYPE_ENUM_BASE];
    uint32_t val_local = UINT32_MAX;
    if (in_en.ok_type != DYN_TYPE_VOID) {
      val_local = el_new_local(el, in_en.ok_type);
      el_buf_push(pre, el_stmt_local(el, val_local, in_en.ok_type, DYN_NO_EXPR, copy.span, loop_depth), a);
    }
    /* Arm 0: Ok */
    ErrStmtBuf ok_buf;
    el_buf_init(&ok_buf);
    uint32_t ok_bind = UINT32_MAX;
    if (in_en.ok_type != DYN_TYPE_VOID) {
      ok_bind = el_new_local(el, in_en.ok_type);
      DynExprId b_ref = el_expr_name(el, ok_bind, in_en.ok_type, copy.span);
      el_buf_push(&ok_buf, el_stmt_assign_local(el, val_local, b_ref, copy.span, loop_depth), a);
    }
    uint32_t ok_start = 0, ok_count = 0;
    el_commit_children(el, &ok_buf, &ok_start, &ok_count);
    el_buf_free(&ok_buf);
    /* Arm 1: Err */
    uint32_t err_start = 0, err_count = 0;
    uint32_t err_bind = UINT32_MAX;
    if (copy.boolean) {
      err_bind = copy.catch_local;
      err_start = copy.item_start;
      err_count = copy.item_count;
      el_lower_block(el, &err_start, &err_count, loop_depth);
    } else {
      ErrStmtBuf fb_buf;
      el_buf_init(&fb_buf);
      DynExprId fb = el_lower_expr(el, copy.right, &fb_buf, loop_depth);
      if (val_local != UINT32_MAX)
        el_buf_push(&fb_buf, el_stmt_assign_local(el, val_local, fb, copy.span, loop_depth), a);
      el_commit_children(el, &fb_buf, &err_start, &err_count);
      el_buf_free(&fb_buf);
    }
    if (!el_reserve_arms(a, 2) || !el_reserve_patterns(a, 2)) { el->oom = true; return id; }
    uint32_t p0 = (uint32_t)a->pattern_count;
    a->patterns[a->pattern_count++] = (DynAstPattern){
        .span = copy.span, .first = DYN_NO_EXPR, .last = DYN_NO_EXPR,
        .variant = in_en.variant_start + 0, .is_enum = true};
    uint32_t p1 = (uint32_t)a->pattern_count;
    a->patterns[a->pattern_count++] = (DynAstPattern){
        .span = copy.span, .first = DYN_NO_EXPR, .last = DYN_NO_EXPR,
        .variant = in_en.variant_start + 1, .is_enum = true};
    uint32_t astart = (uint32_t)a->case_arm_count;
    a->case_arms[a->case_arm_count++] = (DynAstCaseArm){
        .span = copy.span, .pattern_start = p0, .pattern_count = 1,
        .body_start = ok_start, .body_count = ok_count, .local_id = ok_bind};
    a->case_arms[a->case_arm_count++] = (DynAstCaseArm){
        .span = copy.span, .pattern_start = p1, .pattern_count = 1,
        .body_start = err_start, .body_count = err_count, .local_id = err_bind};
    uint32_t cstmt = el_push_stmt(el, (DynAstStmt){
        .kind = DYN_STMT_CASE, .span = copy.span, .expression = operand, .target = DYN_NO_EXPR,
        .local_id = UINT32_MAX, .case_arm_start = astart, .case_arm_count = 2,
        .loop_depth = loop_depth, .target_loop_id = UINT32_MAX});
    el_buf_push(pre, cstmt, a);
    return val_local != UINT32_MAX ? el_expr_name(el, val_local, in_en.ok_type, copy.span)
                                   : el_expr_bool(el, true, copy.span);
  }
  /* Ordinary expression: handle address-of and optional --race read hooks. */
  if (copy.kind == DYN_EXPR_UNARY && copy.op == DYN_OP_ADDRESS) {
    bool prev_addr = el->in_addr;
    el->in_addr = true;
    DynExprId l = el_lower_expr(el, copy.left, pre, loop_depth);
    el->in_addr = prev_addr;
    a->expressions[id].left = l;
    return id;
  }
  if (el->instrument_race && !el->in_addr) {
    if (copy.kind == DYN_EXPR_GLOBAL && copy.integer < a->global_count &&
        !a->globals[copy.integer].is_const && copy.type != DYN_TYPE_ERROR) {
      DynExprId g2 = sema_push_expr(a, copy);
      DynExprId addr = el_expr_addr_of(el, g2, copy.type, true, copy.span);
      el_emit_race_call(el, false, addr, copy.span, pre, loop_depth);
      return id;
    }
    if (copy.kind == DYN_EXPR_UNARY && copy.op == DYN_OP_DEREF && copy.left != DYN_NO_EXPR) {
      DynExprId p_expr = el_lower_expr(el, copy.left, pre, loop_depth);
      DynType p_t = a->expressions[p_expr].type;
      uint32_t p_loc = el_new_local(el, p_t);
      if (!el->oom) {
        el_buf_push(pre, el_stmt_local(el, p_loc, p_t, p_expr, copy.span, loop_depth), a);
        el_emit_race_call(el, false, el_expr_name(el, p_loc, p_t, copy.span), copy.span, pre, loop_depth);
        a->expressions[id].left = el_expr_name(el, p_loc, p_t, copy.span);
      }
      return id;
    }
    if (copy.kind == DYN_EXPR_FIELD && copy.left != DYN_NO_EXPR &&
        dyn_type_is_pointer(a->expressions[copy.left].type)) {
      DynExprId p_expr = el_lower_expr(el, copy.left, pre, loop_depth);
      DynType p_t = a->expressions[p_expr].type;
      uint32_t p_loc = el_new_local(el, p_t);
      if (!el->oom) {
        el_buf_push(pre, el_stmt_local(el, p_loc, p_t, p_expr, copy.span, loop_depth), a);
        DynExprId addr;
        if (el_field_is_packed(a, p_t)) {
          addr = el_expr_name(el, p_loc, p_t, copy.span);
        } else {
          DynAstExpr fc = copy;
          fc.left = el_expr_name(el, p_loc, p_t, copy.span);
          DynExprId f2 = sema_push_expr(a, fc);
          addr = el_expr_addr_of(el, f2, copy.type, true, copy.span);
        }
        el_emit_race_call(el, false, addr, copy.span, pre, loop_depth);
        a->expressions[id].left = el_expr_name(el, p_loc, p_t, copy.span);
      }
      return id;
    }
    if (copy.kind == DYN_EXPR_INDEX && copy.left != DYN_NO_EXPR && copy.right != DYN_NO_EXPR &&
        dyn_type_is_slice(a->expressions[copy.left].type)) {
      DynExprId s_expr = el_lower_expr(el, copy.left, pre, loop_depth);
      DynExprId i_expr = el_lower_expr(el, copy.right, pre, loop_depth);
      DynType s_t = a->expressions[s_expr].type, i_t = a->expressions[i_expr].type;
      uint32_t s_loc = el_new_local(el, s_t);
      uint32_t i_loc = el_new_local(el, i_t);
      if (!el->oom) {
        el_buf_push(pre, el_stmt_local(el, s_loc, s_t, s_expr, copy.span, loop_depth), a);
        el_buf_push(pre, el_stmt_local(el, i_loc, i_t, i_expr, copy.span, loop_depth), a);
        DynAstExpr ic = copy;
        ic.left = el_expr_name(el, s_loc, s_t, copy.span);
        ic.right = el_expr_name(el, i_loc, i_t, copy.span);
        DynExprId idx2 = sema_push_expr(a, ic);
        DynExprId addr = el_expr_addr_of(el, idx2, copy.type, true, copy.span);
        el_emit_race_call(el, false, addr, copy.span, pre, loop_depth);
        a->expressions[id].left = el_expr_name(el, s_loc, s_t, copy.span);
        a->expressions[id].right = el_expr_name(el, i_loc, i_t, copy.span);
      }
      return id;
    }
  }
  bool saved_addr = el->in_addr;
  el->in_addr = false;
  if (copy.left != DYN_NO_EXPR) {
    DynExprId l = el_lower_expr(el, copy.left, pre, loop_depth);
    a->expressions[id].left = l;
  }
  if (copy.right != DYN_NO_EXPR) {
    DynExprId r = el_lower_expr(el, copy.right, pre, loop_depth);
    a->expressions[id].right = r;
  }
  if (copy.kind == DYN_EXPR_SLICE && (DynExprId)copy.integer != DYN_NO_EXPR) {
    DynExprId h = el_lower_expr(el, (DynExprId)copy.integer, pre, loop_depth);
    a->expressions[id].integer = h;
  }
  if (copy.kind != DYN_EXPR_OFFSET && copy.item_count) {
    for (uint32_t i = 0; i < copy.item_count; ++i) {
      DynExprId it = el_lower_expr(el, a->items[copy.item_start + i].expression, pre, loop_depth);
      a->items[copy.item_start + i].expression = it;
    }
  }
  el->in_addr = saved_addr;
  return id;
}

/* Lower `case err { ... }` where `err` is a closed enum union `A | B`. */
static void el_lower_union_case(ErrLower *el, uint32_t stmt_id, ErrStmtBuf *out, uint32_t loop_depth) {
  DynAstProgram *a = el->a;
  DynAstStmt orig = a->statements[stmt_id];
  DynExprId subj = el_lower_expr(el, orig.expression, out, loop_depth);
  DynType u_type = a->expressions[subj].type;
  DynAstEnum u = a->enums[u_type - DYN_TYPE_ENUM_BASE];
  uint32_t mcount = u.variant_count;
  uint32_t acount = orig.case_arm_count;

  /* First lower every original arm's body once (never duplicated). */
  uint32_t *arm_bstart = malloc((acount + 1) * sizeof(uint32_t));
  uint32_t *arm_bcount = malloc((acount + 1) * sizeof(uint32_t));
  bool *arm_shared = calloc(acount + 1, sizeof(bool));
  if (!arm_bstart || !arm_bcount || !arm_shared) {
    free(arm_bstart); free(arm_bcount); free(arm_shared);
    el->oom = true; a->allocation_failed = true; return;
  }
  for (uint32_t ai = 0; ai < acount; ++ai) {
    DynAstCaseArm arm = a->case_arms[orig.case_arm_start + ai];
    arm_bstart[ai] = arm.body_start;
    arm_bcount[ai] = arm.body_count;
    el_lower_block(el, &arm_bstart[ai], &arm_bcount[ai], loop_depth);
    if (arm.wildcard) {
      arm_shared[ai] = true;
    } else if (arm.pattern_count > 1) {
      /* Check if patterns span more than one constituent enum. */
      DynType first_mem = DYN_TYPE_ERROR;
      for (uint32_t pi = 0; pi < arm.pattern_count; ++pi) {
        DynAstPattern p = a->patterns[arm.pattern_start + pi];
        DynType mem = p.type;
        if (first_mem == DYN_TYPE_ERROR) first_mem = mem;
        else if (mem != first_mem) { arm_shared[ai] = true; break; }
      }
    }
  }
  bool needs_dispatch = false;
  for (uint32_t ai = 0; ai < acount; ++ai) needs_dispatch |= arm_shared[ai];

  uint32_t which_local = UINT32_MAX;
  if (needs_dispatch) {
    which_local = el_new_local(el, DYN_TYPE_U32);
    el_buf_push(out, el_stmt_local(el, which_local, DYN_TYPE_U32, DYN_NO_EXPR, orig.span, loop_depth), a);
  }

  /* Build outer case with one arm per constituent enum E_mi. */
  if (!el_reserve_arms(a, mcount) || !el_reserve_patterns(a, mcount)) {
    free(arm_bstart); free(arm_bcount); free(arm_shared);
    el->oom = true; return;
  }
  uint32_t outer_arm_start = (uint32_t)a->case_arm_count;
  a->case_arm_count += mcount;
  uint32_t outer_pat_start = (uint32_t)a->pattern_count;
  a->pattern_count += mcount;

  for (uint32_t mi = 0; mi < mcount; ++mi) {
    DynType mem = a->variants[u.variant_start + mi].payload_type;
    a->patterns[outer_pat_start + mi] = (DynAstPattern){
        .span = orig.span, .first = DYN_NO_EXPR, .last = DYN_NO_EXPR,
        .variant = u.variant_start + mi, .is_enum = true};

    /* Check if a single whole-enum arm covers E_mi directly. */
    uint32_t whole_arm = UINT32_MAX;
    bool any_ptr = false;
    uint32_t wildcard_arm = UINT32_MAX;
    for (uint32_t ai = 0; ai < acount; ++ai) {
      DynAstCaseArm arm = a->case_arms[orig.case_arm_start + ai];
      if (arm.wildcard) { wildcard_arm = ai; continue; }
      for (uint32_t pi = 0; pi < arm.pattern_count; ++pi) {
        DynAstPattern p = a->patterns[arm.pattern_start + pi];
        if (p.type != mem) continue;
        if (arm.pointer_binding) any_ptr = true;
        if (p.is_type) whole_arm = ai;
      }
    }
    if (whole_arm != UINT32_MAX) {
      DynAstCaseArm warm = a->case_arms[orig.case_arm_start + whole_arm];
      if (!arm_shared[whole_arm]) {
        /* Direct 1-level outer arm! */
        a->case_arms[outer_arm_start + mi] = (DynAstCaseArm){
            .span = warm.span, .pattern_start = outer_pat_start + mi, .pattern_count = 1,
            .body_start = arm_bstart[whole_arm], .body_count = arm_bcount[whole_arm],
            .local_id = warm.local_id, .pointer_binding = warm.pointer_binding};
      } else {
        /* Whole-enum pattern in a multi-enum grouped arm: set which = whole_arm + 1. */
        ErrStmtBuf b;
        el_buf_init(&b);
        el_buf_push(&b, el_stmt_assign_local(el, which_local, el_expr_u32(el, whole_arm + 1, warm.span), warm.span, loop_depth), a);
        uint32_t bs = 0, bc = 0;
        el_commit_children(el, &b, &bs, &bc);
        el_buf_free(&b);
        a->case_arms[outer_arm_start + mi] = (DynAstCaseArm){
            .span = warm.span, .pattern_start = outer_pat_start + mi, .pattern_count = 1,
            .body_start = bs, .body_count = bc, .local_id = UINT32_MAX};
      }
      continue;
    }

    /* Count how many original arms have specific variant patterns for E_mi. */
    uint32_t inner_arm_count = 0;
    for (uint32_t ai = 0; ai < acount; ++ai) {
      DynAstCaseArm arm = a->case_arms[orig.case_arm_start + ai];
      if (arm.wildcard) continue;
      bool matches = false;
      for (uint32_t pi = 0; pi < arm.pattern_count; ++pi)
        if (a->patterns[arm.pattern_start + pi].type == mem) { matches = true; break; }
      if (matches) ++inner_arm_count;
    }
    if (!inner_arm_count && wildcard_arm != UINT32_MAX) {
      /* Entire E_mi falls into wildcard _. */
      ErrStmtBuf b;
      el_buf_init(&b);
      el_buf_push(&b, el_stmt_assign_local(el, which_local, el_expr_u32(el, wildcard_arm + 1, orig.span), orig.span, loop_depth), a);
      uint32_t bs = 0, bc = 0;
      el_commit_children(el, &b, &bs, &bc);
      el_buf_free(&b);
      a->case_arms[outer_arm_start + mi] = (DynAstCaseArm){
          .span = orig.span, .pattern_start = outer_pat_start + mi, .pattern_count = 1,
          .body_start = bs, .body_count = bc, .local_id = UINT32_MAX};
      continue;
    }

    /* Inner dispatch on sub_local (of type E_mi, or *E_mi if any_ptr). */
    DynType sub_type = any_ptr ? sema_intern_pointer(a, mem, false) : mem;
    uint32_t sub_local = el_new_local(el, sub_type);
    DynExprId sub_subj = el_expr_name(el, sub_local, sub_type, orig.span);
    if (any_ptr) {
      sub_subj = sema_push_expr(a, (DynAstExpr){
          .kind = DYN_EXPR_UNARY, .op = DYN_OP_DEREF, .type = mem,
          .span = orig.span, .left = sub_subj, .right = DYN_NO_EXPR});
    }
    bool has_wc = wildcard_arm != UINT32_MAX;
    uint32_t total_inner = inner_arm_count + (has_wc ? 1 : 0);
    if (!el_reserve_arms(a, total_inner)) { el->oom = true; break; }
    uint32_t i_arm_start = (uint32_t)a->case_arm_count;
    a->case_arm_count += total_inner;
    uint32_t idx = 0;
    for (uint32_t ai = 0; ai < acount; ++ai) {
      DynAstCaseArm arm = a->case_arms[orig.case_arm_start + ai];
      if (arm.wildcard) continue;
      uint32_t pcnt = 0;
      for (uint32_t pi = 0; pi < arm.pattern_count; ++pi)
        if (a->patterns[arm.pattern_start + pi].type == mem) ++pcnt;
      if (!pcnt) continue;
      if (!el_reserve_patterns(a, pcnt)) { el->oom = true; break; }
      uint32_t ipstart = (uint32_t)a->pattern_count;
      for (uint32_t pi = 0; pi < arm.pattern_count; ++pi) {
        DynAstPattern p = a->patterns[arm.pattern_start + pi];
        if (p.type != mem) continue;
        a->patterns[a->pattern_count++] = (DynAstPattern){
            .span = p.span, .first = DYN_NO_EXPR, .last = DYN_NO_EXPR,
            .variant = p.variant, .is_enum = true};
      }
      if (!arm_shared[ai]) {
        a->case_arms[i_arm_start + idx++] = (DynAstCaseArm){
            .span = arm.span, .pattern_start = ipstart, .pattern_count = pcnt,
            .body_start = arm_bstart[ai], .body_count = arm_bcount[ai],
            .local_id = arm.local_id, .pointer_binding = arm.pointer_binding};
      } else {
        ErrStmtBuf b;
        el_buf_init(&b);
        el_buf_push(&b, el_stmt_assign_local(el, which_local, el_expr_u32(el, ai + 1, arm.span), arm.span, loop_depth), a);
        uint32_t bs = 0, bc = 0;
        el_commit_children(el, &b, &bs, &bc);
        el_buf_free(&b);
        a->case_arms[i_arm_start + idx++] = (DynAstCaseArm){
            .span = arm.span, .pattern_start = ipstart, .pattern_count = pcnt,
            .body_start = bs, .body_count = bc, .local_id = UINT32_MAX};
      }
    }
    if (has_wc) {
      ErrStmtBuf b;
      el_buf_init(&b);
      el_buf_push(&b, el_stmt_assign_local(el, which_local, el_expr_u32(el, wildcard_arm + 1, orig.span), orig.span, loop_depth), a);
      uint32_t bs = 0, bc = 0;
      el_commit_children(el, &b, &bs, &bc);
      el_buf_free(&b);
      a->case_arms[i_arm_start + idx++] = (DynAstCaseArm){
          .span = orig.span, .pattern_start = (uint32_t)a->pattern_count, .pattern_count = 0,
          .body_start = bs, .body_count = bc, .local_id = UINT32_MAX, .wildcard = true};
    }
    uint32_t inner_case = el_push_stmt(el, (DynAstStmt){
        .kind = DYN_STMT_CASE, .span = orig.span, .expression = sub_subj, .target = DYN_NO_EXPR,
        .local_id = UINT32_MAX, .case_arm_start = i_arm_start, .case_arm_count = idx,
        .loop_depth = loop_depth, .target_loop_id = UINT32_MAX});
    ErrStmtBuf ob;
    el_buf_init(&ob);
    el_buf_push(&ob, inner_case, a);
    uint32_t obs = 0, obc = 0;
    el_commit_children(el, &ob, &obs, &obc);
    el_buf_free(&ob);
    a->case_arms[outer_arm_start + mi] = (DynAstCaseArm){
        .span = orig.span, .pattern_start = outer_pat_start + mi, .pattern_count = 1,
        .body_start = obs, .body_count = obc, .local_id = sub_local, .pointer_binding = any_ptr};
  }

  /* Rewrite the original statement to be the outer case. */
  a->statements[stmt_id] = (DynAstStmt){
      .kind = DYN_STMT_CASE, .span = orig.span, .expression = subj, .target = DYN_NO_EXPR,
      .local_id = UINT32_MAX, .case_arm_start = outer_arm_start, .case_arm_count = mcount,
      .loop_depth = loop_depth, .target_loop_id = UINT32_MAX};
  el_buf_push(out, stmt_id, a);

  /* If any shared/wildcard arm was used, emit the single dispatch case on which_local. */
  if (needs_dispatch) {
    bool non_shared_terminates = true;
    for (uint32_t ai = 0; ai < acount; ++ai) {
      if (arm_shared[ai]) continue;
      bool term = false;
      for (uint32_t k = 0; k < arm_bcount[ai]; ++k) {
        DynStmtKind sk = a->statements[a->children[arm_bstart[ai] + k]].kind;
        if (sk == DYN_STMT_RETURN || sk == DYN_STMT_PANIC || sk == DYN_STMT_BREAK || sk == DYN_STMT_CONTINUE)
          term = true;
        else if (sk == DYN_STMT_CASE) {
          /* Nested exhaustive case where every arm ends in return/panic/break/continue. */
          DynAstStmt *cs = &a->statements[a->children[arm_bstart[ai] + k]];
          bool all_t = cs->case_arm_count > 0;
          for (uint32_t ci = 0; ci < cs->case_arm_count && all_t; ++ci) {
            DynAstCaseArm *ca = &a->case_arms[cs->case_arm_start + ci];
            bool ct = false;
            for (uint32_t ck = 0; ck < ca->body_count; ++ck) {
              DynStmtKind csk = a->statements[a->children[ca->body_start + ck]].kind;
              if (csk == DYN_STMT_RETURN || csk == DYN_STMT_PANIC || csk == DYN_STMT_BREAK || csk == DYN_STMT_CONTINUE)
                ct = true;
            }
            all_t = ct;
          }
          if (all_t) term = true;
        }
      }
      if (!term) { non_shared_terminates = false; break; }
    }
    uint32_t scount = 0;
    for (uint32_t ai = 0; ai < acount; ++ai) if (arm_shared[ai]) ++scount;
    if (el_reserve_arms(a, scount + 1) && el_reserve_patterns(a, scount)) {
      uint32_t d_arm_start = (uint32_t)a->case_arm_count;
      for (uint32_t ai = 0; ai < acount; ++ai) {
        if (!arm_shared[ai]) continue;
        uint32_t ps = (uint32_t)a->pattern_count;
        a->patterns[a->pattern_count++] = (DynAstPattern){
            .span = orig.span, .first = DYN_NO_EXPR, .last = DYN_NO_EXPR,
            .first_value = ai + 1, .last_value = ai + 1};
        a->case_arms[a->case_arm_count++] = (DynAstCaseArm){
            .span = orig.span, .pattern_start = ps, .pattern_count = 1,
            .body_start = arm_bstart[ai], .body_count = arm_bcount[ai], .local_id = UINT32_MAX};
      }
      uint32_t wc_start = (uint32_t)a->child_count, wc_count = 0;
      if (non_shared_terminates) {
        /* Unreachable: every outer non-shared arm exited, so which is always nonzero. */
        if (a->string_count == a->string_capacity) {
          size_t cap = a->string_capacity ? a->string_capacity * 2 : 8;
          void *mem = realloc(a->strings, cap * sizeof(*a->strings));
          if (mem) { a->strings = mem; a->string_capacity = cap; }
        }
        unsigned char *empty = malloc(1);
        if (empty && a->string_count < a->string_capacity) {
          empty[0] = 0;
          uint32_t sid = (uint32_t)a->string_count;
          a->strings[a->string_count++] = (DynAstString){empty, 0};
          DynType str_t = sema_intern_slice(a, DYN_TYPE_U8, true);
          DynExprId msg = sema_push_expr(a, (DynAstExpr){
              .kind = DYN_EXPR_STRING, .type = str_t, .span = orig.span,
              .left = DYN_NO_EXPR, .right = DYN_NO_EXPR, .integer = sid});
          uint32_t p_id = el_push_stmt(el, (DynAstStmt){
              .kind = DYN_STMT_PANIC, .span = orig.span, .expression = msg,
              .target = DYN_NO_EXPR, .local_id = UINT32_MAX,
              .loop_depth = loop_depth, .target_loop_id = UINT32_MAX});
          ErrStmtBuf wb;
          el_buf_init(&wb);
          el_buf_push(&wb, p_id, a);
          el_commit_children(el, &wb, &wc_start, &wc_count);
          el_buf_free(&wb);
        } else {
          free(empty);
        }
      }
      a->case_arms[a->case_arm_count++] = (DynAstCaseArm){
          .span = orig.span, .pattern_start = (uint32_t)a->pattern_count, .pattern_count = 0,
          .body_start = wc_start, .body_count = wc_count, .local_id = UINT32_MAX, .wildcard = true};
      uint32_t dstmt = el_push_stmt(el, (DynAstStmt){
          .kind = DYN_STMT_CASE, .span = orig.span,
          .expression = el_expr_name(el, which_local, DYN_TYPE_U32, orig.span),
          .target = DYN_NO_EXPR, .local_id = UINT32_MAX,
          .case_arm_start = d_arm_start, .case_arm_count = scount + 1,
          .loop_depth = loop_depth, .target_loop_id = UINT32_MAX});
      el_buf_push(out, dstmt, a);
    } else {
      el->oom = true;
    }
  }
  free(arm_bstart);
  free(arm_bcount);
  free(arm_shared);
}

static void el_lower_stmt(ErrLower *el, uint32_t stmt_id, ErrStmtBuf *out, uint32_t loop_depth) {
  if (el->oom) return;
  DynAstProgram *a = el->a;
  DynAstStmt st = a->statements[stmt_id];
  if (st.kind == DYN_STMT_FAIL) {
    DynExprId err_e = st.expression != DYN_NO_EXPR ? el_lower_expr(el, st.expression, out, loop_depth) : DYN_NO_EXPR;
    if (el->failed_local != UINT32_MAX) {
      el_buf_push(out, el_stmt_assign_local(el, el->failed_local, el_expr_bool(el, true, st.span), st.span, loop_depth), a);
    }
    DynAstEnum fn_en = a->enums[el->fn_ret - DYN_TYPE_ENUM_BASE];
    DynExprId ret_val = el_expr_enum(el, el->fn_ret, fn_en.variant_start + 1, err_e, st.span);
    a->statements[stmt_id].kind = DYN_STMT_RETURN;
    a->statements[stmt_id].expression = ret_val;
    el_buf_push(out, stmt_id, a);
    return;
  }
  if (st.kind == DYN_STMT_RETURN) {
    DynExprId val = st.expression != DYN_NO_EXPR ? el_lower_expr(el, st.expression, out, loop_depth) : DYN_NO_EXPR;
    if (el->fn_fallible) {
      DynAstEnum fn_en = a->enums[el->fn_ret - DYN_TYPE_ENUM_BASE];
      val = el_expr_enum(el, el->fn_ret, fn_en.variant_start + 0, val, st.span);
    }
    a->statements[stmt_id].expression = val;
    el_buf_push(out, stmt_id, a);
    return;
  }
  if (st.kind == DYN_STMT_ERRDEFER) {
    uint32_t bs = st.body_start, bc = st.body_count;
    el_lower_block(el, &bs, &bc, loop_depth);
    DynExprId cond = el_expr_name(el, el->failed_local, DYN_TYPE_BOOL, st.span);
    uint32_t if_id = el_push_stmt(el, (DynAstStmt){
        .kind = DYN_STMT_IF, .span = st.span, .expression = cond, .target = DYN_NO_EXPR,
        .local_id = UINT32_MAX, .body_start = bs, .body_count = bc,
        .loop_depth = loop_depth, .target_loop_id = UINT32_MAX});
    ErrStmtBuf dbuf;
    el_buf_init(&dbuf);
    el_buf_push(&dbuf, if_id, a);
    uint32_t dstart = 0, dcount = 0;
    el_commit_children(el, &dbuf, &dstart, &dcount);
    el_buf_free(&dbuf);
    a->statements[stmt_id].kind = DYN_STMT_DEFER;
    a->statements[stmt_id].defer_block = true;
    a->statements[stmt_id].body_start = dstart;
    a->statements[stmt_id].body_count = dcount;
    el_buf_push(out, stmt_id, a);
    return;
  }
  if (st.kind == DYN_STMT_DEFER) {
    uint32_t bs = st.body_start, bc = st.body_count;
    el_lower_block(el, &bs, &bc, loop_depth);
    a->statements[stmt_id].body_start = bs;
    a->statements[stmt_id].body_count = bc;
    el_buf_push(out, stmt_id, a);
    return;
  }
  if (st.kind == DYN_STMT_CASE && st.expression != DYN_NO_EXPR &&
      type_is_error_union(a, a->expressions[st.expression].type)) {
    el_lower_union_case(el, stmt_id, out, loop_depth);
    return;
  }
  if (st.kind == DYN_STMT_CASE) {
    DynExprId subj = el_lower_expr(el, st.expression, out, loop_depth);
    a->statements[stmt_id].expression = subj;
    for (uint32_t i = 0; i < st.case_arm_count; ++i) {
      uint32_t ai = st.case_arm_start + i;
      uint32_t bs = a->case_arms[ai].body_start, bc = a->case_arms[ai].body_count;
      el_lower_block(el, &bs, &bc, loop_depth);
      a->case_arms[ai].body_start = bs;
      a->case_arms[ai].body_count = bc;
    }
    el_buf_push(out, stmt_id, a);
    return;
  }
  if (st.kind == DYN_STMT_IF) {
    DynExprId cond = el_lower_expr(el, st.expression, out, loop_depth);
    a->statements[stmt_id].expression = cond;
    uint32_t bs = st.body_start, bc = st.body_count;
    uint32_t es = st.else_start, ec = st.else_count;
    el_lower_block(el, &bs, &bc, loop_depth);
    el_lower_block(el, &es, &ec, loop_depth);
    a->statements[stmt_id].body_start = bs;
    a->statements[stmt_id].body_count = bc;
    a->statements[stmt_id].else_start = es;
    a->statements[stmt_id].else_count = ec;
    el_buf_push(out, stmt_id, a);
    return;
  }
  if (st.kind == DYN_STMT_FOR) {
    bool dummy = false;
    bool cond_needs = !st.for_range && st.target == DYN_NO_EXPR &&
                      st.expression != DYN_NO_EXPR && el_expr_scan(a, st.expression, &dummy, 0);
    if (!cond_needs) {
      if (st.target != DYN_NO_EXPR) {
        DynExprId t = el_lower_expr(el, st.target, out, loop_depth);
        a->statements[stmt_id].target = t;
      }
      if (st.expression != DYN_NO_EXPR) {
        DynExprId e = el_lower_expr(el, st.expression, out, loop_depth);
        a->statements[stmt_id].expression = e;
      }
      if (st.for_step && st.step != DYN_NO_EXPR) {
        DynExprId s = el_lower_expr(el, st.step, out, loop_depth);
        a->statements[stmt_id].step = s;
      }
      uint32_t bs = st.body_start, bc = st.body_count;
      el_lower_block(el, &bs, &bc, loop_depth + 1);
      a->statements[stmt_id].body_start = bs;
      a->statements[stmt_id].body_count = bc;
    } else {
      /* Rewrite `for cond { body }` into `for { <cond_pre>; if !cond { break }; <body...> }`. */
      ErrStmtBuf body;
      el_buf_init(&body);
      DynExprId cond = el_lower_expr(el, st.expression, &body, loop_depth + 1);
      DynExprId ncond = sema_push_expr(a, (DynAstExpr){
          .kind = DYN_EXPR_UNARY, .op = DYN_OP_NOT, .type = DYN_TYPE_BOOL,
          .span = st.span, .left = cond, .right = DYN_NO_EXPR});
      uint32_t brk = el_push_stmt(el, (DynAstStmt){
          .kind = DYN_STMT_BREAK, .span = st.span, .expression = DYN_NO_EXPR,
          .target = DYN_NO_EXPR, .local_id = UINT32_MAX,
          .loop_depth = loop_depth + 1, .target_loop_id = st.loop_id});
      ErrStmtBuf bblk;
      el_buf_init(&bblk);
      el_buf_push(&bblk, brk, a);
      uint32_t bbs = 0, bbc = 0;
      el_commit_children(el, &bblk, &bbs, &bbc);
      el_buf_free(&bblk);
      uint32_t if_brk = el_push_stmt(el, (DynAstStmt){
          .kind = DYN_STMT_IF, .span = st.span, .expression = ncond, .target = DYN_NO_EXPR,
          .local_id = UINT32_MAX, .body_start = bbs, .body_count = bbc,
          .loop_depth = loop_depth + 1, .target_loop_id = UINT32_MAX});
      el_buf_push(&body, if_brk, a);
      uint32_t obs = st.body_start, obc = st.body_count;
      el_lower_block(el, &obs, &obc, loop_depth + 1);
      for (uint32_t k = 0; k < obc; ++k) el_buf_push(&body, a->children[obs + k], a);
      uint32_t nbs = 0, nbc = 0;
      el_commit_children(el, &body, &nbs, &nbc);
      el_buf_free(&body);
      a->statements[stmt_id].expression = DYN_NO_EXPR;
      a->statements[stmt_id].for_broken = true;
      a->statements[stmt_id].body_start = nbs;
      a->statements[stmt_id].body_count = nbc;
    }
    el_buf_push(out, stmt_id, a);
    return;
  }
  if (st.kind == DYN_STMT_EXPR && st.expression != DYN_NO_EXPR) {
    DynExprKind ek = a->expressions[st.expression].kind;
    DynType et = a->expressions[st.expression].type;
    DynExprId lowered = el_lower_expr(el, st.expression, out, loop_depth);
    if ((ek == DYN_EXPR_TRY || ek == DYN_EXPR_CATCH) && et == DYN_TYPE_VOID)
      return; /* Lowered case statement already emitted into `out`. */
    a->statements[stmt_id].expression = lowered;
    el_buf_push(out, stmt_id, a);
    return;
  }
  if (st.target != DYN_NO_EXPR) {
    if (el->instrument_race && st.kind == DYN_STMT_ASSIGN) {
      DynAstExpr tcopy = a->expressions[st.target];
      if (tcopy.kind == DYN_EXPR_GLOBAL && tcopy.integer < a->global_count &&
          !a->globals[tcopy.integer].is_const) {
        DynExprId g2 = sema_push_expr(a, tcopy);
        el_emit_race_call(el, true, el_expr_addr_of(el, g2, tcopy.type, true, st.span), st.span, out, loop_depth);
      } else if (tcopy.kind == DYN_EXPR_UNARY && tcopy.op == DYN_OP_DEREF && tcopy.left != DYN_NO_EXPR) {
        DynExprId p_expr = el_lower_expr(el, tcopy.left, out, loop_depth);
        DynType p_t = a->expressions[p_expr].type;
        uint32_t p_loc = el_new_local(el, p_t);
        if (!el->oom) {
          el_buf_push(out, el_stmt_local(el, p_loc, p_t, p_expr, st.span, loop_depth), a);
          el_emit_race_call(el, true, el_expr_name(el, p_loc, p_t, st.span), st.span, out, loop_depth);
          a->expressions[st.target].left = el_expr_name(el, p_loc, p_t, st.span);
        }
      } else if (tcopy.kind == DYN_EXPR_FIELD && tcopy.left != DYN_NO_EXPR &&
                 dyn_type_is_pointer(a->expressions[tcopy.left].type)) {
        DynExprId p_expr = el_lower_expr(el, tcopy.left, out, loop_depth);
        DynType p_t = a->expressions[p_expr].type;
        uint32_t p_loc = el_new_local(el, p_t);
        if (!el->oom) {
          el_buf_push(out, el_stmt_local(el, p_loc, p_t, p_expr, st.span, loop_depth), a);
          DynExprId addr;
          if (el_field_is_packed(a, p_t)) {
            addr = el_expr_name(el, p_loc, p_t, st.span);
          } else {
            DynAstExpr fc = tcopy;
            fc.left = el_expr_name(el, p_loc, p_t, st.span);
            DynExprId f2 = sema_push_expr(a, fc);
            addr = el_expr_addr_of(el, f2, tcopy.type, true, st.span);
          }
          el_emit_race_call(el, true, addr, st.span, out, loop_depth);
          a->expressions[st.target].left = el_expr_name(el, p_loc, p_t, st.span);
        }
      } else if (tcopy.kind == DYN_EXPR_INDEX && tcopy.left != DYN_NO_EXPR && tcopy.right != DYN_NO_EXPR &&
                 dyn_type_is_slice(a->expressions[tcopy.left].type)) {
        DynExprId s_expr = el_lower_expr(el, tcopy.left, out, loop_depth);
        DynExprId i_expr = el_lower_expr(el, tcopy.right, out, loop_depth);
        DynType s_t = a->expressions[s_expr].type, i_t = a->expressions[i_expr].type;
        uint32_t s_loc = el_new_local(el, s_t);
        uint32_t i_loc = el_new_local(el, i_t);
        if (!el->oom) {
          el_buf_push(out, el_stmt_local(el, s_loc, s_t, s_expr, st.span, loop_depth), a);
          el_buf_push(out, el_stmt_local(el, i_loc, i_t, i_expr, st.span, loop_depth), a);
          DynAstExpr ic = tcopy;
          ic.left = el_expr_name(el, s_loc, s_t, st.span);
          ic.right = el_expr_name(el, i_loc, i_t, st.span);
          DynExprId idx2 = sema_push_expr(a, ic);
          el_emit_race_call(el, true, el_expr_addr_of(el, idx2, tcopy.type, true, st.span), st.span, out, loop_depth);
          a->expressions[st.target].left = el_expr_name(el, s_loc, s_t, st.span);
          a->expressions[st.target].right = el_expr_name(el, i_loc, i_t, st.span);
        }
      } else {
        bool prev_addr = el->in_addr;
        el->in_addr = true;
        DynExprId t = el_lower_expr(el, st.target, out, loop_depth);
        el->in_addr = prev_addr;
        a->statements[stmt_id].target = t;
      }
    } else {
      DynExprId t = el_lower_expr(el, st.target, out, loop_depth);
      a->statements[stmt_id].target = t;
    }
  }
  if (st.expression != DYN_NO_EXPR) {
    DynExprId e = el_lower_expr(el, st.expression, out, loop_depth);
    a->statements[stmt_id].expression = e;
  }
  el_buf_push(out, stmt_id, a);
}

static void el_lower_block(ErrLower *el, uint32_t *start, uint32_t *count, uint32_t loop_depth) {
  if (!*count || el->oom) return;
  uint32_t orig_start = *start, orig_count = *count;
  uint32_t local_ids[32];
  uint32_t *ids = orig_count <= 32 ? local_ids : malloc(orig_count * sizeof(uint32_t));
  if (!ids) { el->oom = true; el->a->allocation_failed = true; return; }
  memcpy(ids, el->a->children + orig_start, orig_count * sizeof(uint32_t));
  ErrStmtBuf out;
  el_buf_init(&out);
  for (uint32_t i = 0; i < orig_count && !el->oom; ++i)
    el_lower_stmt(el, ids[i], &out, loop_depth);
  if (ids != local_ids) free(ids);
  el_commit_children(el, &out, start, count);
  el_buf_free(&out);
}

static bool sema_fn_needs_error_lowering(const DynAstProgram *a, const DynAstFn *fn, bool *has_errdefer) {
  *has_errdefer = false;
  bool needs = type_is_fallible(a, fn->return_type);
  if (el_block_scan(a, fn->body_start, fn->body_count, has_errdefer, 0)) needs = true;
  return needs;
}

static void sema_lower_errors_function(DynAstProgram *a, uint32_t fn_id, bool has_errdefer,
                                       bool instrument_race, uint32_t race_read_fn,
                                       uint32_t race_write_fn, uint32_t set_lifetimes_fn) {
  DynAstFn *fn = &a->functions[fn_id];
  bool is_fall = type_is_fallible(a, fn->return_type);
  ErrLower el = {
      .a = a, .fn_id = fn_id, .fn_ret = fn->return_type, .fn_fallible = is_fall,
      .fn_ok = is_fall ? a->enums[fn->return_type - DYN_TYPE_ENUM_BASE].ok_type : DYN_TYPE_VOID,
      .fn_err = is_fall ? a->enums[fn->return_type - DYN_TYPE_ENUM_BASE].err_type : DYN_TYPE_VOID,
      .failed_local = UINT32_MAX,
      .instrument_race = instrument_race,
      .race_read_fn = race_read_fn,
      .race_write_fn = race_write_fn};
  if (has_errdefer) {
    el.failed_local = el_new_local(&el, DYN_TYPE_BOOL);
    if (el.oom) return;
  }
  uint32_t bs = fn->body_start, bc = fn->body_count;
  el_lower_block(&el, &bs, &bc, 0);
  if (el.oom) return;
  bool prepend_failed = el.failed_local != UINT32_MAX;
  bool prepend_lifetimes = fn->is_main && set_lifetimes_fn != UINT32_MAX;
  bool append_ok = is_fall && el.fn_ok == DYN_TYPE_VOID;
  if (prepend_failed || prepend_lifetimes || append_ok) {
    ErrStmtBuf full;
    el_buf_init(&full);
    DynSpan fspan = a->functions[fn_id].span;
    if (prepend_lifetimes) {
      DynExprId one = sema_push_expr(a, (DynAstExpr){
          .kind = DYN_EXPR_INT, .type = DYN_TYPE_U64, .span = fspan,
          .left = DYN_NO_EXPR, .right = DYN_NO_EXPR, .integer = 1});
      if (one != DYN_NO_EXPR && el_reserve_item(a)) {
        uint32_t istart = (uint32_t)a->item_count;
        a->items[a->item_count++] = (DynAstItem){.expression = one, .field_index = UINT32_MAX};
        DynExprId call = sema_push_expr(a, (DynAstExpr){
            .kind = DYN_EXPR_CALL, .type = DYN_TYPE_VOID, .span = fspan,
            .left = DYN_NO_EXPR, .right = DYN_NO_EXPR, .integer = set_lifetimes_fn,
            .item_start = istart, .item_count = 1});
        if (call != DYN_NO_EXPR)
          el_buf_push(&full, el_push_stmt(&el, (DynAstStmt){
              .kind = DYN_STMT_EXPR, .span = fspan, .expression = call,
              .target = DYN_NO_EXPR, .local_id = UINT32_MAX,
              .loop_depth = 0, .target_loop_id = UINT32_MAX}), a);
      }
    }
    if (prepend_failed)
      el_buf_push(&full, el_stmt_local(&el, el.failed_local, DYN_TYPE_BOOL, DYN_NO_EXPR, fspan, 0), a);
    for (uint32_t i = 0; i < bc; ++i)
      el_buf_push(&full, a->children[bs + i], a);
    if (append_ok) {
      DynAstEnum fn_en = a->enums[el.fn_ret - DYN_TYPE_ENUM_BASE];
      DynExprId ok_val = el_expr_enum(&el, el.fn_ret, fn_en.variant_start + 0, DYN_NO_EXPR, fspan);
      el_buf_push(&full, el_stmt_return(&el, ok_val, fspan, 0), a);
    }
    el_commit_children(&el, &full, &bs, &bc);
    el_buf_free(&full);
  }
  a->functions[fn_id].body_start = bs;
  a->functions[fn_id].body_count = bc;
}

static void el_shift_expr_locals(DynAstProgram *a, DynExprId id, uint32_t old_start, uint32_t old_count, uint32_t new_start, unsigned depth);
static void el_shift_block_locals(DynAstProgram *a, uint32_t start, uint32_t count, uint32_t old_start, uint32_t old_count, uint32_t new_start, unsigned depth) {
  if (depth > 512) return;
  for (uint32_t i = 0; i < count; ++i) {
    DynAstStmt *st = &a->statements[a->children[start + i]];
    if (st->local_id != UINT32_MAX && st->local_id >= old_start && st->local_id - old_start < old_count)
      st->local_id = st->local_id - old_start + new_start;
    el_shift_expr_locals(a, st->expression, old_start, old_count, new_start, depth + 1);
    el_shift_expr_locals(a, st->target, old_start, old_count, new_start, depth + 1);
    if (st->for_step)
      el_shift_expr_locals(a, st->step, old_start, old_count, new_start, depth + 1);
    el_shift_block_locals(a, st->body_start, st->body_count, old_start, old_count, new_start, depth + 1);
    el_shift_block_locals(a, st->else_start, st->else_count, old_start, old_count, new_start, depth + 1);
    if (st->kind == DYN_STMT_CASE) {
      for (uint32_t j = 0; j < st->case_arm_count; ++j) {
        DynAstCaseArm *arm = &a->case_arms[st->case_arm_start + j];
        if (arm->local_id != UINT32_MAX && arm->local_id >= old_start && arm->local_id - old_start < old_count)
          arm->local_id = arm->local_id - old_start + new_start;
        el_shift_block_locals(a, arm->body_start, arm->body_count, old_start, old_count, new_start, depth + 1);
      }
    }
  }
}
static void el_shift_expr_locals(DynAstProgram *a, DynExprId id, uint32_t old_start, uint32_t old_count, uint32_t new_start, unsigned depth) {
  if (id == DYN_NO_EXPR || id >= a->expression_count || depth > 512) return;
  DynAstExpr *e = &a->expressions[id];
  if (e->kind == DYN_EXPR_NAME && e->integer >= old_start && e->integer - old_start < old_count)
    e->integer = e->integer - old_start + new_start;
  if (e->kind == DYN_EXPR_CATCH && e->boolean &&
      e->catch_local != UINT32_MAX && e->catch_local >= old_start && e->catch_local - old_start < old_count)
    e->catch_local = e->catch_local - old_start + new_start;
  el_shift_expr_locals(a, e->left, old_start, old_count, new_start, depth + 1);
  el_shift_expr_locals(a, e->right, old_start, old_count, new_start, depth + 1);
  if (e->kind == DYN_EXPR_SLICE)
    el_shift_expr_locals(a, (DynExprId)e->integer, old_start, old_count, new_start, depth + 1);
  if (e->kind == DYN_EXPR_CATCH && e->boolean) {
    el_shift_block_locals(a, e->item_start, e->item_count, old_start, old_count, new_start, depth + 1);
  } else if (e->kind != DYN_EXPR_OFFSET) {
    for (uint32_t i = 0; i < e->item_count; ++i)
      el_shift_expr_locals(a, a->items[e->item_start + i].expression, old_start, old_count, new_start, depth + 1);
  }
}
static bool el_relocate_fn_locals(DynAstProgram *a, uint32_t fn_id) {
  DynAstFn *fn = &a->functions[fn_id];
  if (fn->local_start + fn->local_count == a->local_count) return true;
  uint32_t old_start = fn->local_start, old_count = fn->local_count;
  uint32_t new_start = (uint32_t)a->local_count;
  for (uint32_t i = 0; i < old_count; ++i) {
    if (!reserve_local(a)) return false;
    a->locals[a->local_count++] = a->locals[old_start + i];
    a->locals[old_start + i] = (DynAstLocal){0};
  }
  fn->local_start = new_start;
  if (old_count) {
    for (uint32_t i = 0; i < fn->param_count; ++i) {
      DynAstParam *p = &a->params[fn->param_start + i];
      if (p->local_id != UINT32_MAX && p->local_id >= old_start && p->local_id - old_start < old_count)
        p->local_id = p->local_id - old_start + new_start;
    }
    if (fn->variadic && fn->variadic_local_id != UINT32_MAX &&
        fn->variadic_local_id >= old_start && fn->variadic_local_id - old_start < old_count)
      fn->variadic_local_id = fn->variadic_local_id - old_start + new_start;
    for (size_t i = 0; i < a->expansion_count; ++i) {
      if (!a->expansions[i].global && a->expansions[i].target >= old_start &&
          a->expansions[i].target - old_start < old_count)
        a->expansions[i].target = a->expansions[i].target - old_start + new_start;
    }
    el_shift_block_locals(a, fn->body_start, fn->body_count, old_start, old_count, new_start, 0);
  }
  return true;
}

static void sema_lower_errors_all(DynAstProgram *a, const DynSource *s) {
  const DynOptimization *opt = s ? s->context.optimization : NULL;
  bool check_lifetimes = opt && opt->check_lifetimes && !s->context.runtime_support;
  bool race = opt && opt->race && !s->context.runtime_support;
  uint32_t set_lifetimes_fn = check_lifetimes ? prelude_function(a, s, "dyn_set_lifetime_checks") : UINT32_MAX;
  uint32_t race_read_fn = race ? prelude_function(a, s, "dyn_race_read") : UINT32_MAX;
  uint32_t race_write_fn = race ? prelude_function(a, s, "dyn_race_write") : UINT32_MAX;
  for (uint32_t f = 0; f < a->function_count && !a->allocation_failed; ++f) {
    DynAstFn *fn = &a->functions[f];
    if (fn->foreign || fn->interface_only || fn->is_generic) continue;
    bool has_errdefer = false;
    bool fn_race = race && race_read_fn != UINT32_MAX && race_write_fn != UINT32_MAX &&
                   !el_skip_race_span(s, fn->span);
    bool fn_lifetimes = fn->is_main && set_lifetimes_fn != UINT32_MAX;
    if (!sema_fn_needs_error_lowering(a, fn, &has_errdefer) && !fn_race && !fn_lifetimes) continue;
    if (!el_relocate_fn_locals(a, f)) return;
    sema_lower_errors_function(a, f, has_errdefer, fn_race, race_read_fn, race_write_fn,
                               fn_lifetimes ? set_lifetimes_fn : UINT32_MAX);
    fn = &a->functions[f];
    fn->local_count = (uint32_t)a->local_count - fn->local_start;
    if (fn->is_main) {
      a->body_start = fn->body_start;
      a->body_count = fn->body_count;
    }
  }
}
