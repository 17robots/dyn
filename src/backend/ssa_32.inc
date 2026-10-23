/* RV32/Thumb foundation: SSA values are 64-bit pairs in eight-byte frame
   slots, not native registers. The existing ISA owns pair arithmetic, target
   frames, incoming banks and guard-aware prologues. Unsupported functions
   are rejected as a whole before emitting any instructions. */
static bool ssa32_scalar(Ssa *s, DynType type) {
  return scalar(s->ir, type);
}
static bool ssa32_signature(Ssa *s) {
  const DynIrFunction *f = s->f;
  if (f->param_count > 512 || (uint64_t)f->param_start + f->param_count > s->ir->param_count ||
      (uint64_t)f->local_start + f->local_count > s->ir->local_count || !abi_supported(s->ir, f->return_type)) return false;
  if (f->variadic && (!ssa_packed_type(s->ir, f) ||
      f->variadic_local_id < f->local_start ||
      f->variadic_local_id - f->local_start >= f->local_count ||
      s->ir->locals[f->variadic_local_id].type != f->variadic_type)) return false;
  for (uint32_t i = 0; i < f->param_count; ++i)
    if (!abi_supported(s->ir, s->ir->params[f->param_start + i].type)) return false;
  for (uint32_t i = 0; i < f->local_count; ++i) {
    DynType type = s->ir->locals[f->local_start + i].type;
    uint32_t size, alignment;
    if ((!ssa32_scalar(s, type) && !descriptor(type) && !aggregate(s->ir, type)) ||
        !layout(s->ir, type, &size, &alignment, 0) || size > MAX_AGGREGATE ||
        !alignment || (alignment & (alignment - 1))) return false;
  }
  return true;
}
/* Flatten identities only after assigning each original parameter type. */
static bool ssa32_incoming(Ssa *s, AbiPart *parts, unsigned *total) {
  bool sret = abi_memory(s->ctx, s->ir, s->f->return_type);
  unsigned gp = sret ? 1 : 0, fp = 0;
  *total = sret ? 1 : 0;
  if (sret) parts[0] = (AbiPart){0, 4, 0, DYN_TYPE_RAWPTR, 0};
  for (uint32_t i = 0; i < s->f->param_count + (unsigned)s->f->variadic; ++i) {
    DynType type = i < s->f->param_count ? s->ir->params[s->f->param_start + i].type : s->f->variadic_type;
    unsigned count; bool indirect;
    if (!abi_supported(s->ir, type) ||
        !abi_assign(s->ctx, s->ir, type, &gp, &fp, parts + *total, &count, 512 - *total, &indirect)) return false;
    *total += count;
  }
  return true;
}
/* All flattened incoming parts are captured before local reconstruction. */
static void ssa32_parameters(Ssa *s) {
  AbiPart parts[512]; unsigned total;
  if (!ssa32_incoming(s, parts, &total)) { SSA_GIVE_UP(s); return; }
  int32_t values[512];
  for (unsigned i = 0; i < total; ++i)
    values[i] = ssa_emit(s, SO_PARAM, ssa_class(parts[i].leaf), -1, -1, -1, i, parts[i].leaf);
  bool sret = abi_memory(s->ctx, s->ir, s->f->return_type);
  unsigned at = sret ? 1 : 0, gp = at, fp = 0;
  if (sret) {
    s->return_slot = ssa_reserve(s, 4, 4);
    ssa_store(s, ssa_frame(s, s->return_slot), -1, 1, 0, SSA_MEM(32, 0, 0), values[0]);
  }
  for (uint32_t i = 0; i < s->f->param_count + (unsigned)s->f->variadic; ++i) {
    DynIrParam packed = {.type = s->f->variadic_type, .local_id = s->f->variadic_local_id};
    const DynIrParam *p = i < s->f->param_count ? &s->ir->params[s->f->param_start + i] : &packed;
    uint32_t local; AbiPart assigned[512]; unsigned count; bool indirect;
    if (!ssa_local_index(s, p->local_id, &local) ||
        !abi_assign(s->ctx, s->ir, p->type, &gp, &fp, assigned, &count, 512, &indirect)) { SSA_GIVE_UP(s); return; }
    if (aggregate(s->ir, p->type)) {
      int32_t address = ssa_frame(s, s->local_offset[local]);
      if (indirect) {
        uint32_t size, alignment;
        if (!layout(s->ir, p->type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return; }
        ssa_emit(s, SO_COPYMEM, SC_NONE, address, values[at], -1, size, 1);
      } else for (unsigned j = 0; j < count; ++j) {
        AbiPart *part = &parts[at + j];
        if (float_type(part->leaf))
          ssa_store(s, address, -1, 1, part->offset, SSA_MEM(part->size * 8, 0, 1), values[at + j]);
        else ssa_store_bytes(s, address, part->offset, part->size, values[at + j]);
      }
    } else {
      int32_t first = ssa_normalize(s, values[at], parts[at].leaf);
      int32_t second = count == 2 ? ssa_normalize(s, values[at + 1], parts[at + 1].leaf) : -1;
      ssa_set_local(s, local, first, second);
    }
    at += count;
  }
}
static const DynIrExpr *ssa32_call_expression(Ssa *s, SsaValue *v) {
  if (!v->abi_expr || v->abi_expr > s->ir->expression_count) return NULL;
  const DynIrExpr *e = &s->ir->expressions[v->abi_expr - 1];
  if (e->kind != (v->aux2 == 2 ? DYN_EXPR_INDIRECT_CALL : DYN_EXPR_CALL)) return NULL;
  return e;
}
/* Original type/group boundaries are part of the plan, not inferred from
   flattened leaves (which lose aggregate alignment). Reassign and compare. */
static bool ssa32_call_parts(Ssa *s, SsaValue *v, AbiPart *parts, uint32_t *bytes) {
  if (v->cls != SC_NONE || v->cond > 1 || (v->aux2 != 0 && v->aux2 != 2) ||
      v->a != -1 || v->b != -1 || v->c != -1 ||
      v->count < (v->aux2 == 2) || v->count > 512u + (v->aux2 == 2) ||
      (uint64_t)v->list + 3u * v->count > s->list_count ||
      v->abi_group_count > 512 || (uint64_t)v->abi_groups + 3u * v->abi_group_count > s->list_count) return false;
  const DynIrExpr *e = ssa32_call_expression(s, v);
  if (!e || !abi_supported(s->ir, e->type)) return false;
  SsaCallPlan plan;
  if (!ssa_call_plan(s,e,&plan) || plan.groups != v->abi_group_count ||
      (v->aux2 == 2 ? v->aux != 0 : v->aux != s->ctx->function_symbols[e->integer])) return false;
  bool sret = plan.sret;
  unsigned gp = sret ? 1 : 0, fp = 0, at = gp;
  uint32_t argc = v->count - (v->aux2 == 2);
  *bytes = 0;
  if (sret) {
    const uint32_t *arg = &s->lists[v->list];
    if (!argc || arg[0] >= s->value_count || s->values[arg[0]].cls != SC_INT ||
        arg[1] != SSA_ILP32_PART || arg[2] != DYN_TYPE_RAWPTR) return false;
    parts[0] = (AbiPart){0, 4, 0, DYN_TYPE_RAWPTR, 0};
  }
  for (uint32_t i = 0; i < plan.groups; ++i) {
    const uint32_t *group = &s->lists[v->abi_groups + 3 * i];
    DynType type = ssa_call_type(s,e,&plan,i);
    unsigned n; bool indirect;
    if (group[0] != type || group[1] != at || !abi_supported(s->ir, type) ||
        !ssa_call_parts(s, type, plan.variadic && (s->ctx->t32 || i>=plan.fixed), &gp, &fp, parts + at, &n, 512 - at, &indirect) ||
        n != group[2] || at + n > argc) return false;
    for (unsigned j = 0; j < n; ++j, ++at) {
      const uint32_t *arg = &s->lists[v->list + 3 * at];
      if (arg[0] >= s->value_count || s->values[arg[0]].cls != ssa_class(parts[at].leaf) ||
          arg[2] != parts[at].leaf || arg[1] != (uint32_t)(SSA_ILP32_PART + parts[at].cls)) return false;
      if (parts[at].cls < 0 || (s->ctx->rv32 && parts[at].cls == RV32_SPLIT)) stack_slot(s->ctx, &parts[at], bytes);
    }
  }
  if (at != argc) return false;
  if (v->aux2 == 2) {
    const uint32_t *target = &s->lists[v->list + 3 * argc];
    if (target[0] >= s->value_count || s->values[target[0]].cls != SC_INT || target[1] != SSA_TARGET || target[2]) return false;
  }
  return true;
}
static bool ssa32_float(unsigned cls) { return cls == SC_F32 || cls == SC_F64; }
static bool ssa32_operand(Ssa *s, int32_t id, unsigned cls) {
  return id >= 0 && (uint32_t)id < s->value_count && s->values[id].cls == cls;
}
/* Only the builder's two-operand fmod runtime form is admitted. */
static bool ssa32_remainder(Ssa *s, SsaValue *v) {
  if (v->op != SO_CALL || v->cls != SC_NONE || v->cond || v->aux2 != 1 ||
      (v->aux != 7 && v->aux != 8) || v->a != -1 || v->b != -1 || v->c != -1 ||
      v->abi_expr || v->abi_groups || v->abi_group_count ||
      v->count != 2 || (uint64_t)v->list + 6 > s->list_count) return false;
  const uint32_t *a = &s->lists[v->list];
  unsigned cls = v->aux == 8 ? SC_F32 : SC_F64;
  return a[1] == 8 && !a[2] && a[4] == 9 && !a[5] &&
         ssa32_operand(s, a[0], cls) && ssa32_operand(s, a[3], cls);
}
/* A protected call owns the initial capture group of its normal successor. */
static int32_t ssa32_preceding_call(Ssa *s, uint32_t block, bool live) {
  SsaBlock *b = &s->blocks[block];
  if (b->preds.count != 1 || b->preds.items[0] >= s->block_count) return -1;
  SsaBlock *p = &s->blocks[b->preds.items[0]];
  if (p->kind != SB_CALL || p->succ[0] != block) return -1;
  for (uint32_t k = p->values.count; k; --k) {
    uint32_t id = p->values.items[k - 1];
    if (id >= s->value_count) return -1;
    SsaValue *v = &s->values[id];
    if (live && v->dead) continue;
    return v->op == SO_CALL && v->cond == 1 ? (int32_t)id : -1;
  }
  return -1;
}
/* Check both constructed and live graphs before any instruction is emitted. */
static bool ssa32_boundary(Ssa *s, bool live) {
  if (!ssa32_signature(s) || s->frame > MAX_AGGREGATE) return false;
  int64_t end = 0;
  for (uint32_t i = 0; i < s->region_count; ++i) {
    SsaRegion *r = &s->regions[i];
    int64_t start = (int32_t)r->offset;
    if (!r->size || start >= 0 || start < -(int64_t)s->frame || start + r->size > end) return false;
    end = start;
  }
  if (!!s->unwind_offset != !!s->results_offset) return false;
  if (s->unwind_offset) {
    uint32_t offsets[2] = {s->unwind_offset, s->results_offset}, sizes[2] = {224, 64};
    for (unsigned j = 0; j < 2; ++j) {
      int32_t r = ssa_region(s, (int32_t)offsets[j]);
      if ((offsets[j] & 15) || r < 0 || s->regions[r].offset != offsets[j] || s->regions[r].size != sizes[j]) return false;
    }
  }
  AbiPart incoming[512]; unsigned incoming_count;
  if (!ssa32_incoming(s, incoming, &incoming_count)) return false;
  for (uint32_t i = 0; i < s->block_count; ++i) {
    SsaBlock *b = &s->blocks[i];
    if (live && !b->reachable) continue;
    if (b->kind != SB_PLAIN && b->kind != SB_IF && b->kind != SB_RETURN && b->kind != SB_EXIT && b->kind != SB_CALL) return false;
    /* All-return case arms leave an unused, empty join in the constructed graph. */
    if (!live && i && b->kind == SB_PLAIN && !b->preds.count && !b->values.count &&
        b->succ[0] == UINT32_MAX && b->succ[1] == UINT32_MAX) continue;
    unsigned edges = b->kind == SB_IF || b->kind == SB_CALL ? 2 : b->kind == SB_PLAIN ? 1 : 0;
    for (unsigned j = 0; j < edges; ++j) {
      if (b->succ[j] >= s->block_count) return false;
      SsaBlock *to = &s->blocks[b->succ[j]];
      unsigned matches = 0;
      for (uint32_t p = 0; p < to->preds.count; ++p) matches += to->preds.items[p] == i;
      if (matches != 1 || (live && !to->reachable)) return false;
    }
    if (b->kind == SB_IF && !ssa32_operand(s, b->control, SC_INT)) return false;
    if (b->kind == SB_CALL && (!s->unwind_offset || b->succ[0] == b->succ[1] ||
        b->control != -1 || b->control2 != -1 || b->control3 != -1 || b->control4 != -1)) return false;
    if (b->kind == SB_RETURN && aggregate(s->ir, s->f->return_type) &&
        !abi_memory(s->ctx, s->ir, s->f->return_type)) {
      SsaPart parts[4]; unsigned count;
      int32_t controls[4] = {b->control, b->control2, b->control3, b->control4};
      if (!ssa_struct_parts(s, s->f->return_type, parts, &count)) return false;
      for (unsigned j = 0; j < 4; ++j)
        if (j < count ? !ssa32_operand(s, controls[j], parts[j].floating ? (parts[j].size == 4 ? SC_F32 : SC_F64) : SC_INT) : controls[j] >= 0) return false;
    } else {
      if (b->control >= 0 && !ssa32_operand(s, b->control,
          b->kind == SB_RETURN ? ssa_class(s->f->return_type) : SC_INT)) return false;
      if (b->control3 >= 0 || b->control4 >= 0) return false;
      if (b->kind == SB_RETURN && descriptor(s->f->return_type)) {
        if (!ssa32_operand(s, b->control, SC_INT) || !ssa32_operand(s, b->control2, SC_INT)) return false;
      } else if (b->control2 >= 0) return false;
    }
  }
  /* Captures form one contiguous group after their call. Dead omissions
     are permitted, but repeated locations and stale call identities are not. */
  for (uint32_t i = 0; i < s->block_count; ++i) {
    SsaBlock *b = &s->blocks[i];
    if (live && !b->reachable) continue;
    int32_t call = ssa32_preceding_call(s, i, live); unsigned seen = 0;
    bool protected_call = false;
    bool terminal = false;
    for (uint32_t k = 0; k < b->values.count; ++k) {
      uint32_t id = b->values.items[k];
      if (id >= s->value_count || s->values[id].block != i) return false;
      SsaValue *v = &s->values[id];
      if (live && v->dead) continue;
      if (terminal || protected_call) return false;
      if (v->op == SO_PHI && seen) return false;
      if (v->op == SO_PHI && call >= 0 && s->values[call].block == i) call = -1;
      if ((v->op == SO_CALL || v->op == SO_PANIC) && v->cond) {
        if (v->cond != 1 || !v->effect || b->kind != SB_CALL) return false;
        protected_call = true;
      }
      if (v->op == SO_TRAP || v->op == SO_FAIL || v->op == SO_CONTINUE ||
          (v->op == SO_PANIC && !v->cond)) terminal = true;
      if (v->op == SO_RESULT) {
        if (v->a != call || call < 0) return false;
        unsigned bit = v->aux == 0 ? 1 : v->aux == 1 ? 2 : v->aux >= X_XMM0 && v->aux < X_XMM0 + 4 ? 4u << (v->aux - X_XMM0) : 0;
        if (!bit || (seen & bit)) return false;
        seen |= bit;
      } else if (v->op != SO_PHI) { call = v->op == SO_CALL ? (int32_t)id : -1; seen = 0; }
    }
    /* Terminal effects end exits; protected effects end two-edge call blocks. */
    if (terminal != (b->kind == SB_EXIT) || protected_call != (b->kind == SB_CALL)) return false;
    if (terminal && (b->control != -1 || b->control2 != -1 ||
                     b->control3 != -1 || b->control4 != -1 ||
                     b->succ[0] != UINT32_MAX || b->succ[1] != UINT32_MAX)) return false;
  }
  for (uint32_t i = 0; i < s->value_count; ++i) {
    SsaValue *v = &s->values[i];
    if (v->block >= s->block_count) return false;
    if (live && (v->dead || !s->blocks[v->block].reachable)) continue;
    if (v->cls != SC_NONE && v->cls != SC_INT && !ssa32_float(v->cls)) return false;
    switch (v->op) {
    case SO_ADD: case SO_SUB: case SO_MUL: case SO_AND: case SO_OR: case SO_XOR:
    case SO_SHL: case SO_SHR: case SO_SAR: case SO_ADDO: case SO_SUBO: case SO_MULO:
    case SO_DIV: case SO_REM: case SO_CMP: case SO_CHECK: case SO_MULOK32:
      if (v->cls != (v->op == SO_CHECK ? SC_NONE : SC_INT) ||
          !ssa32_operand(s, v->a, SC_INT) || !ssa32_operand(s, v->b, SC_INT) || v->c != -1) return false;
      break;
    case SO_EXT: case SO_NEG: case SO_NOT:
      if (v->cls != SC_INT || !ssa32_operand(s, v->a, SC_INT) || v->b != -1 || v->c != -1) return false;
      break;
    case SO_FRAME: case SO_SYMBOL:
      if (v->cls != SC_INT) return false;
      break;
    case SO_LEA:
      if (v->cls != SC_INT || !ssa32_operand(s, v->a, SC_INT) ||
          (v->b != -1 && !ssa32_operand(s, v->b, SC_INT)) || v->c != -1) return false;
      break;
    default: break;
    }
    switch (v->op) {
    case SO_CALL: {
      AbiPart parts[512]; uint32_t bytes;
      if (v->aux2 == 1 ? !ssa32_remainder(s, v) : !ssa32_call_parts(s, v, parts, &bytes)) return false;
      if (v->aux2 == 1) {
        SsaBlock *block = &s->blocks[v->block];
        uint32_t k = 0;
        while (k < block->values.count && block->values.items[k] != i) ++k;
        if (k == block->values.count) return false;
        do { ++k; } while (live && k < block->values.count &&
                           block->values.items[k] < s->value_count && s->values[block->values.items[k]].dead);
        if (k == block->values.count || block->values.items[k] >= s->value_count) return false;
        SsaValue *result = &s->values[block->values.items[k]];
        if (result->op != SO_RESULT || result->a != (int32_t)i || result->block != v->block ||
            result->cls != (v->aux == 8 ? SC_F32 : SC_F64) || result->aux != X_XMM0 || result->aux2) return false;
      }
      break;
    }
    case SO_RESULT: {
      if (v->cond || v->b != -1 || v->c != -1 ||
          v->a < 0 || (uint32_t)v->a >= s->value_count || s->values[v->a].op != SO_CALL ||
          (s->values[v->a].cond ? ssa32_preceding_call(s, v->block, live) != v->a :
                                s->values[v->a].block != v->block)) return false;
      SsaValue *call = &s->values[v->a];
      if (call->aux2 == 1) {
        if (!ssa32_remainder(s, call) || v->aux2 || v->aux != X_XMM0 ||
            v->cls != (call->aux == 8 ? SC_F32 : SC_F64)) return false;
      } else {
        const DynIrExpr *e = ssa32_call_expression(s, call);
        SsaCallPlan plan;
        if (!e || !ssa_call_plan(s,e,&plan) || v->aux2 != e->type) return false;
        if (aggregate(s->ir, e->type)) {
          SsaPart parts[4]; unsigned count; bool found = false;
          if (!ssa_call_result_parts(s, e->type, s->ctx->t32 && plan.variadic, parts, &count)) return false;
          for (unsigned j = 0; j < count; ++j)
            if (v->aux == parts[j].aux && v->cls == (parts[j].floating ? (parts[j].size == 4 ? SC_F32 : SC_F64) : SC_INT)) found = true;
          if (!found) return false;
          break;
        }
        if (v->cls != ssa_class(e->type)) return false;
        if (descriptor(e->type)) { if (v->aux != 0 && v->aux != 1) return false; }
        else if (!ssa32_scalar(s, e->type) || v->aux != (ssa32_float(v->cls) ? X_XMM0 : 0)) return false;
      }
      break;
    }
    case SO_PHI:
      if (v->cls == SC_NONE || v->count > 512 || (uint64_t)v->list + v->count > s->list_count) return false;
      for (uint32_t j = 0; j < v->count; ++j)
        if (!ssa32_operand(s, s->lists[v->list + j], v->cls)) return false;
      break;
    case SO_CONST:
      if (v->cls == SC_NONE) return false;
      break;
    case SO_PARAM:
      if (v->aux < 0 || (uint64_t)v->aux >= incoming_count || v->aux2 != incoming[v->aux].leaf ||
          v->cls != ssa_class(incoming[v->aux].leaf) || v->a != -1 || v->b != -1 || v->c != -1) return false;
      break;
    case SO_COPY:
      if (v->cls == SC_NONE || !ssa32_operand(s, v->a, v->cls) || v->b != -1 || v->c != -1) return false;
      break;
    case SO_FADD: case SO_FSUB: case SO_FMUL: case SO_FDIV:
      if (!ssa32_float(v->cls) || !ssa32_operand(s, v->a, v->cls) ||
          !ssa32_operand(s, v->b, v->cls) || v->c != -1 || v->aux || v->aux2 || v->cond) return false;
      break;
    case SO_FCMP:
      if (v->cls != SC_INT || v->a < 0 || (uint32_t)v->a >= s->value_count ||
          !ssa32_float(s->values[v->a].cls) || !ssa32_operand(s, v->b, s->values[v->a].cls) ||
          v->c != -1 || v->aux < 0 || v->aux >= 6 || v->aux2 || v->cond) return false;
      break;
    case SO_FNEG: case SO_ITOF: case SO_FTOI: case SO_FCVT: case SO_BITS: {
      if (v->a < 0 || (uint32_t)v->a >= s->value_count || v->b != -1 || v->c != -1 || v->aux2 || v->cond) return false;
      unsigned src = s->values[v->a].cls;
      if (v->op == SO_ITOF || v->op == SO_FTOI) {
        if (v->aux != 0 && v->aux != 1) return false;
        if (v->op == SO_ITOF ? (src != SC_INT || !ssa32_float(v->cls)) :
                              (!ssa32_float(src) || v->cls != SC_INT)) return false;
      } else {
        if (v->aux) return false;
        if (v->op == SO_FNEG && (!ssa32_float(src) || src != v->cls)) return false;
        if (v->op == SO_FCVT && (!ssa32_float(src) || !ssa32_float(v->cls) || src == v->cls)) return false;
        if (v->op == SO_BITS && !((src == SC_INT && ssa32_float(v->cls)) || (ssa32_float(src) && v->cls == SC_INT))) return false;
      }
      break;
    }
    case SO_ADD: case SO_SUB: case SO_MUL: case SO_AND: case SO_OR: case SO_XOR:
    case SO_SHL: case SO_SHR: case SO_SAR: case SO_NEG: case SO_NOT:
    case SO_SYMBOL: case SO_LEA: break;
    case SO_FRAME:
      if (v->aux != (int32_t)v->aux || ssa_region(s, v->aux) < 0 ||
          v->a != -1 || v->b != -1 || v->c != -1 || v->aux2 || v->cond) return false;
      break;
    case SO_EXT:
      if (v->aux != 1 && v->aux != 8 && v->aux != 16 && v->aux != 32 && v->aux != 64) return false;
      break;
    case SO_CMP:
      if (v->cond > CC_G) return false;
      break;
    case SO_LOAD: case SO_STORE: {
      unsigned bits = v->aux2 & 255;
      bool floating = (v->aux2 & 512) != 0;
      unsigned cls = floating ? (bits == 32 ? SC_F32 : SC_F64) : SC_INT;
      if ((v->aux2 & ~1023) || (bits != 8 && bits != 16 && bits != 32 && bits != 64) ||
          (floating && (bits != 32 && bits != 64)) || (floating && (v->aux2 & 256)) ||
          !ssa32_operand(s, v->a, SC_INT) || (v->b != -1 && !ssa32_operand(s, v->b, SC_INT)) ||
          (v->op == SO_LOAD ? (v->cls != cls || v->c != -1) :
                             (v->cls != SC_NONE || !ssa32_operand(s, v->c, cls)))) return false;
      break;
    }
    case SO_COPYMEM: case SO_ZEROMEM:
      if (v->cls != SC_NONE || !ssa32_operand(s, v->a, SC_INT) ||
          (v->op == SO_COPYMEM ? !ssa32_operand(s, v->b, SC_INT) : v->b != -1) ||
          v->c != -1 || v->cond || v->aux < 0 || v->aux > MAX_AGGREGATE ||
          (v->op == SO_COPYMEM ? (v->aux2 != 0 && v->aux2 != 1) : v->aux2 != 0)) return false;
      break;
    case SO_MULOK32:
      if (v->aux || v->aux2 > 1 || v->cond) return false;
      break;
    case SO_ADDO: case SO_SUBO: case SO_MULO: case SO_DIV: case SO_REM: break;
    case SO_FAIL: case SO_CONTINUE:
      if (s->blocks[v->block].kind != SB_EXIT || !v->effect || v->cls != SC_NONE ||
          v->a != -1 || v->b != -1 || v->c != -1 || v->aux2 || v->cond || v->count || v->list ||
          v->abi_expr || v->abi_groups || v->abi_group_count ||
          (v->op == SO_CONTINUE ? v->aux != 0 : (v->aux < 0 || v->aux >= GUARD_COUNT))) return false;
      break;
    case SO_PANIC:
      if (s->blocks[v->block].kind != (v->cond ? SB_CALL : SB_EXIT) || !v->effect ||
          v->cls != SC_NONE || !ssa32_operand(s, v->a, SC_INT) ||
          !ssa32_operand(s, v->b, SC_INT) || v->c != -1 || v->scale != 1 ||
          v->aux || v->aux2 || v->cond > 1 || v->count || v->list ||
          v->abi_expr || v->abi_groups || v->abi_group_count) return false;
      break;
    case SO_TRAP:
      if (s->blocks[v->block].kind != SB_EXIT || !v->effect ||
          v->cls != SC_NONE || v->a != -1 || v->b != -1 || v->c != -1 ||
          v->aux || v->aux2 || v->cond || v->count || v->list ||
          v->abi_expr || v->abi_groups || v->abi_group_count) return false;
      break;
    case SO_CHECK:
      if (v->cond > CC_G || v->aux2) return false;
      if (v->aux == GUARD_ENUM_TAG) {
        if (v->cond != CC_NE) return false;
        break;
      }
      if (v->aux == GUARD_NONNULL || v->aux == GUARD_ALIGNED || v->aux == GUARD_INDEX ||
          v->aux == GUARD_SLICE_ORDER || v->aux == GUARD_SLICE_BOUNDS) {
        unsigned condition = v->aux == GUARD_NONNULL ? CC_NE : v->aux == GUARD_ALIGNED ? CC_E :
                             v->aux == GUARD_INDEX ? CC_B : CC_BE;
        if (v->cond != condition) return false;
        break;
      }
      if (v->aux != GUARD_OVERFLOW && v->aux != GUARD_DIVIDE &&
          v->aux != GUARD_DIVISION_OVERFLOW && v->aux != GUARD_SHIFT && v->aux != GUARD_FUNCTION) {
        if (live) return false;
      }
      break;
    default: return false;
    }
  }
  return true;
}
static uint32_t ssa32_slot(Ssa *s, int32_t id) {
  return 0u - ((s->frame + 7) / 8 * 8 + 8 * ((uint32_t)s->values[id].slot + 1));
}
static void ssa32_get(Ssa *s, int32_t id, Reg reg) { isa_load(s->ctx, reg, ssa32_slot(s, id)); }
/* Decode the whole physical result bank once, before frame address/FP
   scratch can destroy another component. SO_RESULT only names saved slots. */
static void ssa32_capture(Ssa *s, SsaValue *call) {
  BackendContext *ctx = s->ctx;
  const DynIrExpr *e = call->aux2 == 1 ? NULL : ssa32_call_expression(s, call);
  DynType type = e ? e->type : call->aux == 8 ? DYN_TYPE_F32 : DYN_TYPE_F64;
  SsaCallPlan plan = {0};
  if (e && !ssa_call_plan(s,e,&plan)) { ctx->text.failed = true; return; }
  bool base = ctx->t32 && plan.variadic;
  if (type == DYN_TYPE_VOID || ssa_call_memory(s,type,base)) return;
  if (aggregate(s->ir, type)) {
    SsaPart parts[4]; unsigned count;
    if (!ssa_call_result_parts(s, type, base, parts, &count)) { ctx->text.failed = true; return; }
    /* Save the complete physical bank using only SP-relative stores. In
       particular, reading fa0/s0 into A must not overwrite an integer result. */
    unsigned bank = 4 * isa_slot(ctx);
    isa_reserve(ctx, bank);
    for (unsigned j = 0; j < count; ++j) {
      SsaPart *p = &parts[j];
      unsigned reg = p->floating ? (unsigned)(p->aux - X_XMM0) : (unsigned)p->aux;
      if (ctx->rv32) rv_memory(ctx, true, 10 + reg, 2, isa_slot(ctx) * j,
                              p->floating && p->size == 8 ? 3 : 2, p->floating);
      else if (p->floating) t32_vmem(ctx, false, p->size == 8, reg, T32_SP, isa_slot(ctx) * j);
      else t32_mem(ctx, T32_STR, reg, T32_SP, isa_slot(ctx) * j);
    }
    SsaBlock *b = &s->blocks[call->cond ? s->blocks[call->block].succ[0] : call->block];
    for (uint32_t k = 0; k < b->values.count; ++k) {
      uint32_t id = b->values.items[k]; SsaValue *v = &s->values[id];
      if (v->dead || v->op != SO_RESULT || v->a != (int32_t)(call - s->values)) continue;
      for (unsigned j = 0; j < count; ++j) if (v->aux == parts[j].aux) {
        isa_peek(ctx, R_A, j);
        if (parts[j].size <= 4) isa_extend(ctx, 32, false);
        isa_store(ctx, R_A, ssa32_slot(s, (int32_t)id));
      }
    }
    isa_release(ctx, bank);
    return;
  }
  if (call->aux2 != 1) {
    if (ctx->rv32) rv32_call_result(ctx, type);
    else if (base && float_type(type)) {
      /* Variadic Thumb results use core registers even in a hard-float image. */
      if (type == DYN_TYPE_F64) t32_mv(ctx,4,1); else t32_li(ctx,4,0);
    } else t32_call_result(ctx, type, descriptor(type), wide_scalar(ctx, type));
  }
  if (float_type(type) && !base) isa_float_result(ctx, type == DYN_TYPE_F32);
  SsaBlock *b = &s->blocks[call->cond ? s->blocks[call->block].succ[0] : call->block];
  int32_t call_id = (int32_t)(call - s->values);
  for (uint32_t k = 0; k < b->values.count; ++k) {
    uint32_t id = b->values.items[k]; SsaValue *v = &s->values[id];
    if (!v->dead && v->op == SO_RESULT && v->a == call_id)
      isa_store(ctx, descriptor(type) && v->aux == 1 ? R_D : R_A, ssa32_slot(s, (int32_t)id));
  }
}
static void ssa32_call(Ssa *s, SsaValue *v) {
  BackendContext *ctx = s->ctx;
  if (v->aux2 == 1) {
    ssa32_get(s, s->lists[v->list], R_A); ssa32_get(s, s->lists[v->list + 3], R_C);
    isa_float_operands(ctx, v->aux == 8);
    bool padded = isa_align_call(ctx);
    if (ctx->soft_float) {
      /* Soft helpers consume and return raw model pairs; capture must not
         reimport an ordinary ABI result over the helper's A pair. */
      if (ctx->rv32) r32_float_remainder(ctx, v->aux == 8);
      else t32_float_remainder(ctx, v->aux == 8);
    } else runtime_call(ctx, (unsigned)v->aux);
    ssa32_capture(s, v);
    isa_unalign_call(ctx, padded);
    return;
  }
  AbiPart parts[512]; uint32_t bytes;
  /* The same decoder was checked before emission. */
  if (!ssa32_call_parts(s, v, parts, &bytes)) { ctx->text.failed = true; return; }
  bool indirect = v->aux2 == 2;
  uint32_t argc = v->count - indirect, slot = isa_slot(ctx), saved = ctx->stack_slots;
  if (indirect) { ssa32_get(s, s->lists[v->list + 3 * argc], R_A); isa_push(ctx, R_A); }
  for (uint32_t i = 0; i < argc; ++i) {
    ssa32_get(s, s->lists[v->list + 3 * i], R_A); isa_push(ctx, R_A);
  }
  for (uint32_t i = 0; i < argc; ++i) {
    if (parts[i].cls < 0) continue;
    bool split = ctx->rv32 && parts[i].cls == RV32_SPLIT;
    isa_argument_load(ctx, split ? 7 : parts[i].cls, slot * (argc - i - 1));
  }
  uint32_t reserved = (bytes + 15) / 16 * 16;
  isa_reserve(ctx, reserved);
  for (uint32_t i = 0; i < argc; ++i) {
    bool split = ctx->rv32 && parts[i].cls == RV32_SPLIT;
    if (parts[i].cls < 0 || split)
      isa_stack_store(ctx, reserved + slot * (argc - i - 1) + (split ? 4 : 0),
                      parts[i].stack, stack_width(ctx, &parts[i]));
  }
  if (indirect) isa_call_stack(ctx, reserved + argc * slot);
  else isa_call_symbol(ctx, (unsigned)v->aux);
  ssa32_capture(s, v);
  isa_release(ctx, reserved + (argc + indirect) * slot);
  ctx->stack_slots = saved;
}
/* Address arithmetic uses pairs too, then canonicalizes the pointer to XLEN.
   Load C before A: scaling C may use scratch registers but never a live A. */
static void ssa32_address(Ssa *s, SsaValue *v) {
  BackendContext *ctx = s->ctx;
  if (v->b >= 0) { ssa32_get(s, v->b, R_C); isa_scale(ctx, R_C, v->scale); }
  ssa32_get(s, v->a, R_A);
  if (v->b >= 0) isa_alu(ctx, ALU_ADD, R_A, R_C);
  if (v->aux) { isa_immediate(ctx, R_C, (uint64_t)v->aux); isa_alu(ctx, ALU_ADD, R_A, R_C); }
  isa_extend(ctx, 32, false);
}
static void ssa32_value(Ssa *s, uint32_t id) {
  BackendContext *ctx = s->ctx; SsaValue *v = &s->values[id];
  switch (v->op) {
  case SO_CALL: ssa32_call(s, v); return;
  case SO_RESULT: return; /* captured atomically at the call */
  case SO_PARAM: case SO_PHI: return; /* entry capture / incoming edge */
  case SO_CONST: isa_immediate(ctx, R_A, (uint64_t)v->aux); break;
  case SO_COPY: case SO_BITS:
    ssa32_get(s, v->a, R_A);
    if (v->cls == SC_F32 || s->values[v->a].cls == SC_F32) isa_extend(ctx, 32, false);
    break;
  case SO_FNEG:
    ssa32_get(s, v->a, R_A);
    isa_immediate(ctx, R_C, UINT64_C(1) << (v->cls == SC_F32 ? 31 : 63));
    isa_alu(ctx, ALU_XOR, R_A, R_C); break;
  case SO_FADD: case SO_FSUB: case SO_FMUL: case SO_FDIV: case SO_FCMP: {
    bool f32 = s->values[v->a].cls == SC_F32;
    ssa32_get(s, v->a, R_A); ssa32_get(s, v->b, R_C);
    isa_float_operands(ctx, f32);
    if (v->op == SO_FCMP) isa_float_compare(ctx, f32, (unsigned)v->aux);
    else isa_float_arithmetic(ctx, f32, v->op - SO_FADD);
    break;
  }
  case SO_ITOF:
    ssa32_get(s, v->a, R_A); isa_int_to_float(ctx, v->cls == SC_F32, v->aux != 0); break;
  case SO_FTOI:
    ssa32_get(s, v->a, R_A); isa_float_to_int(ctx, s->values[v->a].cls == SC_F32, v->aux != 0); break;
  case SO_FCVT:
    ssa32_get(s, v->a, R_A); isa_float_convert(ctx, s->values[v->a].cls == SC_F32); break;
  case SO_EXT: ssa32_get(s, v->a, R_A); isa_extend(ctx, (unsigned)v->aux, v->aux2 != 0); break;
  case SO_NEG: case SO_NOT:
    ssa32_get(s, v->a, R_A); isa_unary(ctx, v->op == SO_NEG ? UNARY_NEGATE : UNARY_NOT); break;
  case SO_ADD: case SO_SUB: case SO_AND: case SO_OR: case SO_XOR:
    ssa32_get(s, v->a, R_A); ssa32_get(s, v->b, R_C);
    isa_alu(ctx, v->op == SO_ADD ? ALU_ADD : v->op == SO_SUB ? ALU_SUB :
                 v->op == SO_AND ? ALU_AND : v->op == SO_OR ? ALU_OR : ALU_XOR, R_A, R_C); break;
  case SO_ADDO: case SO_SUBO: case SO_MULO: {
    ssa32_get(s, v->a, R_A); ssa32_get(s, v->b, R_C);
    int op = v->op == SO_ADDO ? ALU_ADD : v->op == SO_SUBO ? ALU_SUB : ALU_ADD + 16;
    if (v->op == SO_MULO) isa_multiply(ctx, true, v->aux2 != 0);
    else isa_alu(ctx, op, R_A, R_C);
    guard(ctx, s->f, isa_overflow_condition(ctx, op, v->aux2 != 0), GUARD_OVERFLOW);
    break;
  }
  case SO_PANIC:
    /* Keep the full length pair in logical argument 1. The runtime adapter
       owns RV32's a1:a2 and Thumb's aligned r2:r3 ABI placement. */
    ssa32_get(s, v->b, isa_argument(ctx, 1));
    ssa32_get(s, v->a, isa_argument(ctx, 0));
    runtime_call(ctx, 0);
    isa_trap(ctx); return;
  case SO_FAIL: {
    const char *name = function_name(s->f);
    size_t length = strlen(name);
    if (length > 800) length = 800;
    isa_string_arguments(ctx, literal(ctx, name, length), (size_t)v->aux << 24 | length);
    runtime_call(ctx, RUNTIME_CHECK_FAILED); isa_trap(ctx); return;
  }
  case SO_CONTINUE: runtime_call(ctx, 6); isa_trap(ctx); return;
  case SO_TRAP: isa_trap(ctx); return;
  case SO_MULOK32:
    ssa32_get(s, v->a, R_A); ssa32_get(s, v->b, R_C);
    isa_multiply(ctx, true, v->aux2 != 0);
    isa_set(ctx, isa_overflow_condition(ctx, ALU_ADD + 16, v->aux2 != 0));
    break;
  case SO_CHECK:
    ssa32_get(s, v->a, R_A); ssa32_get(s, v->b, R_C);
    isa_compare(ctx, R_A, R_C); guard(ctx, s->f, (Cond)v->cond, (unsigned)v->aux); return;
  case SO_DIV: case SO_REM:
    /* The ordered SO_CHECK effects already checked zero and MIN/-1. Every
       live value resides in its frame slot across the hidden runtime call. */
    ssa32_get(s, v->a, R_A); ssa32_get(s, v->b, R_C);
    isa_divide(ctx, v->aux2 != 0, v->op == SO_REM); break;
  case SO_MUL:
    ssa32_get(s, v->a, R_A); ssa32_get(s, v->b, R_C); isa_multiply(ctx, false, false); break;
  case SO_SHL: case SO_SHR: case SO_SAR:
    ssa32_get(s, v->a, R_A); ssa32_get(s, v->b, R_C);
    isa_shift(ctx, R_A, v->op == SO_SHL ? SHIFT_LEFT : v->op == SO_SHR ? SHIFT_RIGHT : SHIFT_ARITHMETIC); break;
  case SO_CMP:
    ssa32_get(s, v->a, R_A); ssa32_get(s, v->b, R_C);
    isa_compare(ctx, R_A, R_C); isa_set(ctx, (Cond)v->cond); break;
  case SO_FRAME: isa_lea(ctx, R_A, (uint32_t)v->aux); break;
  case SO_SYMBOL:
    if (v->aux2 == SYM_LOCAL) isa_local_address(ctx, R_A, (unsigned)v->aux, (size_t)v->c);
    else {
      isa_symbol_address(ctx, R_A, (unsigned)v->aux);
      if (v->c) { isa_immediate(ctx, R_C, (uint64_t)(int64_t)v->c); isa_alu(ctx, ALU_ADD, R_A, R_C); }
    }
    isa_extend(ctx, 32, false); break;
  case SO_LEA: ssa32_address(s, v); break;
  case SO_LOAD:
    ssa32_address(s, v); isa_load_value(ctx, v->aux2 & 255, (v->aux2 & 256) != 0); break;
  case SO_COPYMEM:
    ssa32_get(s, v->a, R_A); isa_push(ctx, R_A);
    ssa32_get(s, v->b, R_A); isa_copy(ctx, (uint32_t)v->aux); return;
  case SO_ZEROMEM:
    ssa32_get(s, v->a, R_A); isa_zero_fill(ctx, (uint32_t)v->aux); return;
  case SO_STORE:
    ssa32_address(s, v); isa_move(ctx, R_11, R_A); ssa32_get(s, v->c, R_A);
    isa_store_value(ctx, v->aux2 & 255); return;
  default: ctx->text.failed = true; return; /* preflight makes this unreachable */
  }
  isa_store(ctx, R_A, ssa32_slot(s, (int32_t)id));
}
/* Snapshot ALL incoming values before assigning ANY destination. This is a
   parallel copy, even for swaps, longer cycles and self-loop edges. */
static void ssa32_edge(Ssa *s, uint32_t from, uint32_t to, uint32_t temporary) {
  SsaBlock *b = &s->blocks[to]; uint32_t pred = 0, count = 0;
  while (pred < b->preds.count && b->preds.items[pred] != from) ++pred;
  for (uint32_t k = 0; k < b->values.count; ++k) {
    SsaValue *v = &s->values[b->values.items[k]];
    if (v->dead || v->op != SO_PHI) continue;
    ssa32_get(s, (int32_t)s->lists[v->list + pred], R_A);
    isa_store(s->ctx, R_A, temporary - 8 * count++);
  }
  count = 0;
  for (uint32_t k = 0; k < b->values.count; ++k) {
    uint32_t id = b->values.items[k]; SsaValue *v = &s->values[id];
    if (v->dead || v->op != SO_PHI) continue;
    isa_load(s->ctx, R_A, temporary - 8 * count++); isa_store(s->ctx, R_A, ssa32_slot(s, (int32_t)id));
  }
}
static int ssa32_function(Ssa *s, const uint32_t *order, uint32_t n) {
  BackendContext *ctx = s->ctx;
  if (!n || n > s->block_count || n > (UINT32_MAX - 1) / 2 ||
      !ssa32_boundary(s, true)) return SSA_UNSUPPORTED;
  uint32_t slots = 0, phis = 0;
  for (uint32_t i = 0; i < s->value_count; ++i) s->values[i].slot = -1;
  for (uint32_t i = 0; i < n; ++i) {
    if (order[i] >= s->block_count || !s->blocks[order[i]].reachable) return SSA_UNSUPPORTED;
    for (uint32_t j = 0; j < i; ++j) if (order[j] == order[i]) return SSA_UNSUPPORTED;
    SsaBlock *b = &s->blocks[order[i]]; uint32_t count = 0;
    for (uint32_t k = 0; k < b->values.count; ++k) {
      if (b->values.items[k] >= s->value_count) return SSA_UNSUPPORTED;
      SsaValue *v = &s->values[b->values.items[k]];
      if (v->dead) continue;
      if (v->cls != SC_NONE) v->slot = (int32_t)slots++;
      if (v->op == SO_PHI) {
        if (v->count != b->preds.count || v->count > 512) return SSA_UNSUPPORTED;
        ++count;
      }
    }
    if (count > phis) phis = count;
  }
  for (uint32_t i = 0; i < s->block_count; ++i) {
    if (!s->blocks[i].reachable) continue;
    uint32_t j = 0;
    while (j < n && order[j] != i) ++j;
    if (j == n) return SSA_UNSUPPORTED;
  }
  uint64_t base = ((uint64_t)s->frame + 7) / 8 * 8 + 8 * (uint64_t)slots;
  uint64_t total = (base + 8 * phis + 15) / 16 * 16;
  if (total > MAX_AGGREGATE + (1u << 20)) return SSA_UNSUPPORTED;
  /* Verify every operand and edge before the first instruction, and allocate
     all branch fixup storage up front. No fallback after partial emission. */
  for (uint32_t i = 0; i < n; ++i) {
    SsaBlock *b = &s->blocks[order[i]];
    if ((b->kind == SB_IF || b->kind == SB_RETURN) && b->control >= 0 && ((uint32_t)b->control >= s->value_count || s->values[b->control].slot < 0)) return SSA_UNSUPPORTED;
    if (b->control2 >= 0 && ((uint32_t)b->control2 >= s->value_count || s->values[b->control2].slot < 0)) return SSA_UNSUPPORTED;
    if (b->control3 >= 0 && ((uint32_t)b->control3 >= s->value_count || s->values[b->control3].slot < 0)) return SSA_UNSUPPORTED;
    if (b->control4 >= 0 && ((uint32_t)b->control4 >= s->value_count || s->values[b->control4].slot < 0)) return SSA_UNSUPPORTED;
    unsigned edges = b->kind == SB_IF || b->kind == SB_CALL ? 2 : b->kind == SB_PLAIN ? 1 : 0;
    for (unsigned j = 0; j < edges; ++j) {
      if (b->succ[j] >= s->block_count) return SSA_UNSUPPORTED;
      SsaBlock *to = &s->blocks[b->succ[j]]; unsigned p = 0;
      while (p < to->preds.count && to->preds.items[p] != order[i]) ++p;
      if (p == to->preds.count || !to->reachable) return SSA_UNSUPPORTED;
    }
    int32_t previous = ssa32_preceding_call(s, order[i], true);
    for (uint32_t k = 0; k < b->values.count; ++k) {
      uint32_t id = b->values.items[k]; SsaValue *v = &s->values[id];
      if (v->dead) continue;
      if (v->op == SO_RESULT) {
        /* Its dependency is an effect, deliberately without a value slot.
           The contiguous result group shares this one live call. */
        if (v->a != previous || s->values[v->a].dead || s->values[v->a].cls != SC_NONE)
          return SSA_UNSUPPORTED;
        continue;
      }
      if (v->op != SO_PHI) previous = (int32_t)id;
      int32_t *operands[513]; uint32_t count = ssa_operands(s, id, operands, 513);
      for (uint32_t j = 0; j < count; ++j)
        if (*operands[j] < 0 || (uint32_t)*operands[j] >= s->value_count || s->values[*operands[j]].slot < 0)
          return SSA_UNSUPPORTED;
    }
  }
  AbiPart incoming[512]; unsigned incoming_count;
  if (!ssa32_incoming(s, incoming, &incoming_count)) return SSA_UNSUPPORTED;
  typedef struct { size_t at; uint32_t to; } Jump;
  Jump *jumps = calloc((size_t)n * 2 + 1, sizeof(*jumps));
  if (!jumps) return SSA_FAILED;
  uint32_t jump_count = 0, temporary = 0u - (uint32_t)base - 8;
  ctx->frame_bytes = (uint32_t)total;
  ctx->stack_slots = ctx->loop_depth = 0;
  ctx->allocator_used = ctx->allocator_local_count = 0;
  /* Guard state belongs to this function, never the preceding tree/SSA one. */
  ctx->defer_count = ctx->cleanup_depth = ctx->unwind_offset = 0;
  ctx->unwinding = ctx->holding = false;
  for (unsigned i = 0; i < GUARD_COUNT; ++i)
    ctx->message_offsets[i] = ctx->guard_stubs[i] = SIZE_MAX;
  isa_enter(ctx);
  uint32_t cursor = 0;
  for (uint32_t i = 0; i < incoming_count; ++i) {
    incoming_part(ctx, &incoming[i], &cursor);
    for (uint32_t k = 0; k < s->value_count; ++k) {
      SsaValue *v = &s->values[k];
      if (v->op == SO_PARAM && v->aux == i && v->slot >= 0) isa_store(ctx, R_A, ssa32_slot(s, (int32_t)k));
    }
  }
  if (ctx->rv32) rv_i(ctx, 0x13, 2, 2, 128, 0);
  else t32_release_bank(ctx);
  for (uint32_t i = 0; i < n; ++i) {
    uint32_t id = order[i]; SsaBlock *b = &s->blocks[id]; b->at = ctx->text.n;
    size_t landing = SIZE_MAX;
    for (uint32_t k = 0; k < b->values.count; ++k) {
      SsaValue *v = &s->values[b->values.items[k]];
      if (v->dead) continue;
      if ((v->op == SO_CALL || v->op == SO_PANIC) && v->cond) {
        /* Set/link at the fixed baseline, before any outgoing staging. */
        isa_lea(ctx, isa_argument(ctx, 0), s->unwind_offset); runtime_call(ctx, 3);
        isa_test32(ctx); landing = isa_branch(ctx, CC_NE);
        isa_lea(ctx, isa_argument(ctx, 0), s->unwind_offset); runtime_call(ctx, 4);
      }
      ssa32_value(s, b->values.items[k]);
    }
    if (b->kind == SB_RETURN) {
      if (aggregate(s->ir, s->f->return_type) && !abi_memory(ctx, s->ir, s->f->return_type)) {
        SsaPart parts[4]; unsigned count;
        int32_t values[4] = {b->control, b->control2, b->control3, b->control4};
        if (!ssa_struct_parts(s, s->f->return_type, parts, &count)) { ctx->text.failed = true; break; }
        for (unsigned j = 0; j < count; ++j) { ssa32_get(s, values[j], R_A); isa_push(ctx, R_A); }
        for (unsigned j = 0; j < count; ++j) {
          int cls = parts[j].floating ? parts[j].aux - X_XMM0 + (parts[j].size == 4 ? 16 : 8) : parts[j].aux;
          isa_argument_load(ctx, cls, isa_slot(ctx) * (count - j - 1));
        }
        isa_drop(ctx, count);
        isa_return(ctx);
        continue;
      }
      if (b->control2 >= 0) ssa32_get(s, b->control2, R_D);
      if (b->control >= 0) ssa32_get(s, b->control, R_A);
      else isa_zero(ctx, R_A);
      if (ctx->rv32) rv32_return_registers(ctx, s->f->return_type);
      else t32_return_registers(ctx, s->f->return_type, wide_scalar(ctx, s->f->return_type));
      isa_return(ctx);
    } else if (b->kind == SB_CALL) {
      /* Results are already in successor slots and staging is released. */
      isa_lea(ctx, isa_argument(ctx, 0), s->unwind_offset); runtime_call(ctx, 5);
      ssa32_edge(s, id, b->succ[0], temporary);
      jumps[jump_count++] = (Jump){isa_branch(ctx, -1), b->succ[0]};
      isa_patch(ctx, landing, ctx->text.n);
      isa_reset_stack(ctx); ctx->stack_slots = 0;
      /* unwind_begin already popped this record. */
      ssa32_edge(s, id, b->succ[1], temporary);
      jumps[jump_count++] = (Jump){isa_branch(ctx, -1), b->succ[1]};
    } else if (b->kind == SB_IF) {
      ssa32_get(s, b->control, R_A); isa_test(ctx, R_A);
      size_t otherwise = isa_branch(ctx, CC_E);
      ssa32_edge(s, id, b->succ[0], temporary);
      jumps[jump_count++] = (Jump){isa_branch(ctx, -1), b->succ[0]};
      isa_patch(ctx, otherwise, ctx->text.n);
      ssa32_edge(s, id, b->succ[1], temporary);
      jumps[jump_count++] = (Jump){isa_branch(ctx, -1), b->succ[1]};
    } else if (b->kind == SB_PLAIN) {
      ssa32_edge(s, id, b->succ[0], temporary);
      jumps[jump_count++] = (Jump){isa_branch(ctx, -1), b->succ[0]};
    }
  }
  for (uint32_t i = 0; i < jump_count; ++i) isa_patch(ctx, jumps[i].at, s->blocks[jumps[i].to].at);
  free(jumps);
  if (ctx->text.failed || ctx->rodata.failed || ctx->relocation_failed) return SSA_FAILED;
  if (ctx->optimization_remarks)
    fprintf(stderr, "remark: %s: SSA code generation, %u paired frame slots, %u phi temporaries\n", s->f->name, slots, phis);
  return SSA_EMITTED;
}
