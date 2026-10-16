/* Fixed-bound elementwise integer loops. Local arrays have disjoint storage
   unless they are the same local; matching indices make that overlap safe.
   The scalar tail retains the same wrapping/bitwise operation. */
static bool vector_array(const DynIrProgram *ir, const DynIrFunction *f,
                         DynExprId id, uint32_t index, uint32_t *local, DynType *type,
                         uint64_t *length) {
  if (id >= ir->expression_count) return false;
  const DynIrExpr *e = &ir->expressions[id];
  if (e->kind != DYN_EXPR_INDEX || e->left >= ir->expression_count || e->right >= ir->expression_count) return false;
  const DynIrExpr *base = &ir->expressions[e->left], *at = &ir->expressions[e->right];
  if (base->kind != DYN_EXPR_NAME || !dyn_type_is_array(base->type) ||
      at->kind != DYN_EXPR_NAME || at->integer != index || base->integer < f->local_start ||
      base->integer - f->local_start >= f->local_count ||
      base->type - DYN_TYPE_ARRAY_BASE >= ir->array_count) return false;
  const DynIrArray *a = &ir->arrays[base->type - DYN_TYPE_ARRAY_BASE];
  if (a->element != DYN_TYPE_U32 && a->element != DYN_TYPE_I32 &&
      a->element != DYN_TYPE_U64 && a->element != DYN_TYPE_I64) return false;
  *local = (uint32_t)base->integer; *type = a->element; *length = a->length;
  return true;
}
static bool vector_loop(BackendContext *ctx, const DynIrProgram *ir,
                        const DynIrFunction *f, const DynIrStmt *s) {
  if (!ctx->vectorize || !s->for_range || s->for_reverse || s->for_inclusive ||
      s->for_pointer || s->body_count != 1 || s->body_start >= ir->child_count ||
      s->target >= ir->expression_count || s->expression >= ir->expression_count) return false;
  const DynIrExpr *start = &ir->expressions[s->target], *stop = &ir->expressions[s->expression];
  if (start->kind != DYN_EXPR_INT || start->integer != 0 || stop->kind != DYN_EXPR_INT ||
      stop->integer > UINT32_MAX) return false;
  uint32_t sid = ir->children[s->body_start];
  if (sid >= ir->statement_count) return false;
  const DynIrStmt *assign = &ir->statements[sid];
  if (assign->kind != DYN_STMT_ASSIGN || assign->assignment_op != DYN_OP_NONE ||
      assign->expression >= ir->expression_count) return false;
  const DynIrExpr *op = &ir->expressions[assign->expression];
  if (op->kind != DYN_EXPR_BINARY ||
      !((op->wrap && (op->op == DYN_OP_ADD || op->op == DYN_OP_SUB)) ||
        op->op == DYN_OP_BIT_AND || op->op == DYN_OP_BIT_OR || op->op == DYN_OP_BIT_XOR)) return false;
  uint32_t dest, left, right; DynType type, lt, rt; uint64_t dn, ln, rn;
  if (!vector_array(ir, f, assign->target, s->local_id, &dest, &type, &dn) ||
      !vector_array(ir, f, op->left, s->local_id, &left, &lt, &ln) ||
      !vector_array(ir, f, op->right, s->local_id, &right, &rt, &rn) ||
      type != lt || type != rt || op->type != type ||
      ctx->local_alias[dest-f->local_start] || ctx->local_alias[left-f->local_start] ||
      ctx->local_alias[right-f->local_start]) return false;
  unsigned bytes = type == DYN_TYPE_U64 || type == DYN_TYPE_I64 ? 8 : 4, lanes = 16 / bytes;
  uint64_t n = stop->integer;
  if (n < lanes || n > dn || n > ln || n > rn) return false;
  uint32_t d, l, r;
  if (!local_slot(ctx, f, dest, &d) || !local_slot(ctx, f, left, &l) || !local_slot(ctx, f, right, &r)) return false;
  isa_lea(ctx, R_SI, l); isa_lea(ctx, R_DI, r); isa_lea(ctx, R_11, d);
  isa_immediate(ctx, R_C, n / lanes);
  size_t begin = ctx->text.n;
  if (ctx->a64) {
    a64_word(ctx, 0x3dc00000 | a64_reg[R_SI] << 5); /* ldr q0,[source] */
    a64_word(ctx, 0x3dc00001 | a64_reg[R_DI] << 5); /* ldr q1,[source] */
    uint32_t instruction = op->op == DYN_OP_ADD ? (bytes == 8 ? 0x4ee08400 : 0x4ea08400)
        : op->op == DYN_OP_SUB ? (bytes == 8 ? 0x6ee08400 : 0x6ea08400)
        : op->op == DYN_OP_BIT_AND ? 0x4e201c00
        : op->op == DYN_OP_BIT_OR ? 0x4ea01c00 : 0x6e201c00;
    a64_word(ctx, instruction | 1u << 16);
    a64_word(ctx, 0x3d800000 | a64_reg[R_11] << 5); /* str q0,[destination] */
    const Reg pointers[] = {R_SI, R_DI, R_11};
    for (unsigned i = 0; i < 3; ++i)
      a64_word(ctx, 0x91004000 | a64_reg[pointers[i]] << 5 | a64_reg[pointers[i]]);
    a64_word(ctx, 0xf1000400 | a64_reg[R_C] << 5 | a64_reg[R_C]);
  } else {
    CODE(0xf3,0x0f,0x6f,0x06, 0xf3,0x0f,0x6f,0x0f); /* movdqu xmm0/1,[rsi/rdi] */
    CODE(0x66,0x0f);
    byte(ctx, op->op == DYN_OP_ADD ? (bytes == 8 ? 0xd4 : 0xfe)
        : op->op == DYN_OP_SUB ? (bytes == 8 ? 0xfb : 0xfa)
        : op->op == DYN_OP_BIT_AND ? 0xdb : op->op == DYN_OP_BIT_OR ? 0xeb : 0xef);
    byte(ctx,0xc1);
    CODE(0xf3,0x41,0x0f,0x7f,0x03);
    CODE(0x48,0x83,0xc6,16, 0x48,0x83,0xc7,16, 0x49,0x83,0xc3,16, 0x48,0xff,0xc9);
  }
  size_t again = isa_branch(ctx, CC_NE); isa_patch(ctx, again, begin);
  for (uint64_t i = n / lanes * lanes; i < n; ++i) {
    isa_lea(ctx, R_A, l + (uint32_t)i * bytes); load_memory(ctx, type); isa_push(ctx, R_A);
    isa_lea(ctx, R_A, r + (uint32_t)i * bytes); load_memory(ctx, type);
    isa_move(ctx, R_C, R_A); isa_pop(ctx, R_A);
    if (!binary_result(ctx, ir, f, op)) { ctx->text.failed = true; return true; }
    isa_lea(ctx, R_11, d + (uint32_t)i * bytes); store_memory(ctx, type);
  }
  if (ctx->optimization_remarks)
    fprintf(stderr, "remark: %s: vectorized %llu integer elements (%u lanes, scalar tail %llu)\n",
            f->name, (unsigned long long)n, lanes, (unsigned long long)(n % lanes));
  return true;
}
