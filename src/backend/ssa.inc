/* SSA code generation for optimized x86-64 System V builds (included by
   driver.c).

   The tree emitter in driver.c evaluates every expression through one
   accumulator and the hardware stack. This path instead converts a function
   into SSA form, optimizes it, allocates registers and then emits machine
   code. The shape follows Go's compiler (cmd/compile/internal/ssa): values in
   basic blocks, phis built while walking the tree (Braun et al., "Simple and
   Efficient Construction of Static Single Assignment Form"), generic
   rewrites, a bounds-check prover, and linear-scan register allocation.

   ssa_function builds the whole function before it writes any byte. When the
   function uses something this path does not handle yet, it returns
   SSA_UNSUPPORTED and the caller uses the tree emitter instead, so coverage
   can grow one construct at a time. Results must match the tree emitter
   exactly: the same runtime checks in the same order, with the same
   messages. */

enum { SSA_UNSUPPORTED, SSA_EMITTED, SSA_FAILED };

/* Register ids: 0-31 general registers, 32-63 floating registers. */
enum { X_RAX = 0, X_RCX = 1, X_RDX = 2, X_RBX = 3, X_RSP = 4, X_RBP = 5, X_RSI = 6, X_RDI = 7,
       X_R8 = 8, X_R9 = 9, X_R10 = 10, X_R11 = 11, X_R12 = 12, X_R13 = 13, X_R14 = 14, X_R15 = 15, X_XMM0 = 32 };
typedef enum {
  SO_CONST,      /* aux: value bits */
  SO_PARAM,      /* aux: incoming location index; see ssa_param */
  SO_PHI,        /* list: one operand per predecessor */
  SO_COPY,       /* a */
  SO_ADD, SO_SUB, SO_MUL, SO_AND, SO_OR, SO_XOR, /* wrapping 64-bit */
  SO_SHL, SO_SHR, SO_SAR,                        /* count below 64 */
  SO_DIV, SO_REM,                                /* aux2: signed; checks done */
  SO_NEG, SO_NOT,
  SO_EXT,        /* a extended from aux bits; aux2: signed */
  SO_CMP,        /* 0 or 1: a cond b */
  SO_FCMP,       /* 0 or 1: float a op b; aux: DYN_OP_EQ.. offset */
  SO_FADD, SO_FSUB, SO_FMUL, SO_FDIV,
  SO_FNEG,
  SO_ITOF,       /* aux: unsigned 64-bit source */
  SO_FTOI,       /* aux: unsigned 64-bit result */
  SO_FCVT,       /* f32 <-> f64 */
  SO_BITS,       /* raw bit move between register files */
  SO_ADDO, SO_SUBO, SO_MULO, /* 64-bit with overflow check; aux2: signed */
  SO_CHECK,      /* panics unless a cond b; aux: check kind */
  SO_CHECK_SHL,  /* left shift a by b (b < 64) loses no bits; aux2: signed */
  SO_LOAD,       /* [a + b*scale + aux]; aux2: memory type */
  SO_STORE,      /* [a + b*scale + aux] <- c */
  SO_FRAME,      /* address FP + aux */
  SO_SYMBOL,     /* address of symbol aux; aux2: SYM_* kind */
  SO_LEA,        /* a + b*scale + aux */
  SO_CALL,       /* list: arguments; aux: callee symbol or -1; c: target */
  SO_RESULT,     /* part aux of call a's result */
  SO_COPYMEM,    /* copy aux bytes from b to a, as memmove */
  SO_ZEROMEM,    /* zero aux bytes at a */
  SO_PANIC,      /* dyn_panic(a, b) */
  SO_VECTOR,     /* SIMD loop over frame arrays a = b op c; aux: elements, aux2: op | bytes << 8 */
  SO_MULH,       /* high 64 bits of a * b; aux2: signed */
  SO_TRAP,       /* unreachable: no case arm matched */
  SO_FAIL,       /* dyn_check_failed for check kind aux, after cleanup */
  SO_CONTINUE,   /* dyn_unwind_continue after cleanup */
  SO_COUNT
} SsaOp;
enum { SC_NONE, SC_INT, SC_F64, SC_F32 };
enum { SYM_GLOBAL, SYM_FUNCTION, SYM_LOCAL };
/* Memory types: bits | signed << 8 | float << 9. */
#define SSA_MEM(bits, sign, fl) ((bits) | (sign) << 8 | (fl) << 9)

typedef struct {
  uint8_t op, cls, cond, scale;
  bool effect, dead, fused;
  int32_t a, b, c;
  int64_t aux, aux2;
  uint32_t block, list, count, uses;
  int32_t reg, slot, hint; /* hint: a value whose register this one prefers */
  uint32_t start, end; /* live interval */
} SsaValue;
typedef struct {
  uint32_t *items; uint32_t count, capacity;
} SsaList;
enum { SB_PLAIN, SB_IF, SB_RETURN, SB_EXIT, SB_CALL /* protected call: succ[0] normal, succ[1] unwinding */,
       SB_SWITCH /* jump table on control: lists[table] = minimum, entries, default, targets... */ };
typedef struct {
  SsaList values, preds;
  uint32_t succ[2];
  uint8_t kind;
  bool sealed, reachable;
  int32_t control;     /* SB_IF: condition; SB_RETURN: value or -1 */
  int32_t control2;    /* SB_RETURN: second word of a descriptor result */
  int32_t control3, control4; /* SB_RETURN: third and fourth result parts (AArch64 HFAs) */
  uint32_t table;      /* SB_SWITCH: index into the value lists */
  uint32_t order, idom, depth, loop_depth;
  size_t at;           /* emitted text offset */
} SsaBlock;
typedef struct { uint64_t key; int32_t value; } SsaDef;
typedef struct { uint32_t block, variable, phi; } SsaPending;
typedef struct { uint32_t id, exit, next; unsigned depth, defer_base; } SsaLoop;
typedef struct { DynExprId expression; uint32_t variable; } SsaCapture;

typedef struct {
  BackendContext *ctx;
  const DynIrProgram *ir;
  const DynIrFunction *f;
  SsaValue *values; uint32_t value_count, value_capacity;
  SsaBlock *blocks; uint32_t block_count, block_capacity;
  uint32_t *lists; uint32_t list_count, list_capacity;
  SsaDef *defs; uint32_t def_capacity, def_count;
  SsaPending *pending; uint32_t pending_count, pending_capacity;
  uint32_t current;
  bool unsupported, failed;
  /* Locals: SSA variables (two per local: data and length words) or frame
     memory at local_offset. */
  bool *memory_local;
  uint32_t *local_offset;
  int32_t *alias;      /* case pointer bindings: the pointer standing for a local, or -1 */
  uint32_t variable_count, hidden_variables;
  uint32_t frame;      /* bytes of frame memory below FP, before spills */
  SsaLoop loops[MAX_DEPTH]; unsigned loop_count, loop_depth;

  uint32_t return_slot; /* sret pointer, saved on entry */
  uint32_t outgoing;   /* bytes reserved at SP for stack arguments */
  unsigned vectorized, reason;
  bool calls;
  /* Pending defers, innermost last; while they run, `unwinding` is set and
     simple deferred calls read the arguments captured at the defer. */
  uint32_t defers[MAX_DEFERS]; unsigned defer_count;
  bool unwinding;
  SsaCapture *captures; uint32_t capture_count, capture_capacity;
  uint32_t unwind_offset, results_offset;
} Ssa;

/* Call argument locations; see ssa_argument. */
enum { SSA_TARGET = 32, SSA_RESULT_POINTER = 33, SSA_STACK = 64 };
/* Records where building stopped, for --opt-remarks. */
#define SSA_GIVE_UP(s) ((s)->unsupported = true, (s)->reason = (s)->reason ? (s)->reason : __LINE__)
static void *ssa_grow(void *items, uint32_t *capacity, uint32_t need, size_t size, bool *failed) {
  if (need <= *capacity) return items;
  uint32_t next = *capacity ? *capacity : 64;
  while (next < need) {
    if (next > UINT32_MAX / 2) { *failed = true; return items; }
    next *= 2;
  }
  void *grown = realloc(items, (size_t)next * size);
  if (!grown) { *failed = true; return items; }
  *capacity = next;
  return grown;
}
static void ssa_push(Ssa *s, SsaList *list, uint32_t item) {
  list->items = ssa_grow(list->items, &list->capacity, list->count + 1, sizeof(uint32_t), &s->failed);
  if (!s->failed) list->items[list->count++] = item;
}
static uint32_t ssa_block(Ssa *s) {
  s->blocks = ssa_grow(s->blocks, &s->block_capacity, s->block_count + 1, sizeof(SsaBlock), &s->failed);
  if (s->failed) return 0;
  SsaBlock *b = &s->blocks[s->block_count];
  memset(b, 0, sizeof(*b));
  b->control = b->control2 = b->control3 = b->control4 = -1;
  b->succ[0] = b->succ[1] = UINT32_MAX;
  b->loop_depth = s->loop_depth;
  return s->block_count++;
}
static int32_t ssa_value(Ssa *s, uint32_t block, SsaOp op, uint8_t cls, int32_t a, int32_t b, int32_t c, int64_t aux, int64_t aux2) {
  s->values = ssa_grow(s->values, &s->value_capacity, s->value_count + 1, sizeof(SsaValue), &s->failed);
  if (s->failed) return 0;
  SsaValue *v = &s->values[s->value_count];
  memset(v, 0, sizeof(*v));
  v->op = (uint8_t)op; v->cls = cls; v->a = a; v->b = b; v->c = c; v->aux = aux; v->aux2 = aux2;
  v->block = block; v->reg = v->slot = -1; v->hint = -1; v->scale = 1;
  v->effect = op == SO_CHECK || op == SO_CHECK_SHL || op == SO_ADDO || op == SO_SUBO || op == SO_MULO ||
              op == SO_LOAD || op == SO_STORE || op == SO_CALL || op == SO_COPYMEM || op == SO_ZEROMEM ||
              op == SO_PANIC || op == SO_DIV || op == SO_REM || op == SO_RESULT || op == SO_PARAM || op == SO_VECTOR || op == SO_TRAP || op == SO_FAIL || op == SO_CONTINUE;
  return (int32_t)s->value_count++;
}
/* Appends a value to the current block. */
static int32_t ssa_emit(Ssa *s, SsaOp op, uint8_t cls, int32_t a, int32_t b, int32_t c, int64_t aux, int64_t aux2) {
  int32_t v = ssa_value(s, s->current, op, cls, a, b, c, aux, aux2);
  if (!s->failed) ssa_push(s, &s->blocks[s->current].values, (uint32_t)v);
  return v;
}
static int32_t ssa_const(Ssa *s, uint64_t bits, uint8_t cls) {
  return ssa_emit(s, SO_CONST, cls, -1, -1, -1, (int64_t)bits, 0);
}
static uint32_t ssa_list(Ssa *s, const int32_t *items, uint32_t count) {
  s->lists = ssa_grow(s->lists, &s->list_capacity, s->list_count + count, sizeof(uint32_t), &s->failed);
  if (s->failed) return 0;
  uint32_t at = s->list_count;
  for (uint32_t i = 0; i < count; ++i) s->lists[at + i] = (uint32_t)items[i];
  s->list_count += count;
  return at;
}
static void ssa_edge(Ssa *s, uint32_t from, uint32_t to) {
  SsaBlock *b = &s->blocks[from];
  if (b->succ[0] == UINT32_MAX) b->succ[0] = to; else b->succ[1] = to;
  ssa_push(s, &s->blocks[to].preds, from);
}
/* Ends the current block with a jump. */
static void ssa_jump(Ssa *s, uint32_t to) {
  if (s->current == UINT32_MAX) return;
  s->blocks[s->current].kind = SB_PLAIN;
  ssa_edge(s, s->current, to);
  s->current = UINT32_MAX;
}
static void ssa_branch(Ssa *s, int32_t condition, uint32_t yes, uint32_t no) {
  if (s->current == UINT32_MAX) return;
  SsaBlock *b = &s->blocks[s->current];
  b->kind = SB_IF; b->control = condition;
  ssa_edge(s, s->current, yes);
  ssa_edge(s, s->current, no);
  s->current = UINT32_MAX;
}

/* Variable definitions: key = variable << 32 | block. */
static uint64_t ssa_hash(uint64_t key) { key ^= key >> 31; key *= UINT64_C(0x9e3779b97f4a7c15); return key ^ key >> 29; }
static void ssa_define(Ssa *s, uint32_t variable, uint32_t block, int32_t value) {
  if (2 * (s->def_count + 1) > s->def_capacity) {
    uint32_t capacity = s->def_capacity ? 2 * s->def_capacity : 1024;
    SsaDef *grown = malloc((size_t)capacity * sizeof(*grown));
    if (!grown) { s->failed = true; return; }
    for (uint32_t i = 0; i < capacity; ++i) grown[i].key = UINT64_MAX;
    for (uint32_t i = 0; i < s->def_capacity; ++i) {
      if (s->defs[i].key == UINT64_MAX) continue;
      uint32_t j = (uint32_t)ssa_hash(s->defs[i].key) & (capacity - 1);
      while (grown[j].key != UINT64_MAX) j = (j + 1) & (capacity - 1);
      grown[j] = s->defs[i];
    }
    free(s->defs); s->defs = grown; s->def_capacity = capacity;
  }
  uint64_t key = (uint64_t)variable << 32 | block;
  uint32_t j = (uint32_t)ssa_hash(key) & (s->def_capacity - 1);
  while (s->defs[j].key != UINT64_MAX && s->defs[j].key != key) j = (j + 1) & (s->def_capacity - 1);
  if (s->defs[j].key == UINT64_MAX) { s->defs[j].key = key; ++s->def_count; }
  s->defs[j].value = value;
}
static bool ssa_defined(Ssa *s, uint32_t variable, uint32_t block, int32_t *value) {
  if (!s->def_capacity) return false;
  uint64_t key = (uint64_t)variable << 32 | block;
  uint32_t j = (uint32_t)ssa_hash(key) & (s->def_capacity - 1);
  while (s->defs[j].key != UINT64_MAX) {
    if (s->defs[j].key == key) { *value = s->defs[j].value; return true; }
    j = (j + 1) & (s->def_capacity - 1);
  }
  return false;
}
/* Follows copies left by removed phis. */
static int32_t ssa_resolve(Ssa *s, int32_t v) {
  while (v >= 0 && s->values[v].op == SO_COPY) v = s->values[v].a;
  return v;
}
static int32_t ssa_read(Ssa *s, uint32_t variable, uint32_t block, uint8_t cls);
static int32_t ssa_new_phi(Ssa *s, uint32_t block, uint8_t cls) {
  int32_t phi = ssa_value(s, block, SO_PHI, cls, -1, -1, -1, 0, 0);
  if (s->failed) return 0;
  /* Phis lead their block. */
  SsaList *list = &s->blocks[block].values;
  ssa_push(s, list, 0);
  if (s->failed) return 0;
  memmove(list->items + 1, list->items, (list->count - 1) * sizeof(uint32_t));
  list->items[0] = (uint32_t)phi;
  return phi;
}
static int32_t ssa_phi_operands(Ssa *s, uint32_t variable, int32_t phi) {
  SsaBlock *b = &s->blocks[s->values[phi].block];
  uint32_t count = b->preds.count;
  int32_t stack[64] = {0}, *items = count <= 64 ? stack : malloc(count * sizeof(int32_t));
  if (!items) { s->failed = true; return phi; }
  for (uint32_t i = 0; i < count; ++i)
    items[i] = ssa_read(s, variable, s->blocks[s->values[phi].block].preds.items[i], s->values[phi].cls);
  s->values[phi].list = ssa_list(s, items, count);
  s->values[phi].count = count;
  if (items != stack) free(items);
  /* A phi whose operands are all one value (or itself) is that value. */
  int32_t same = -1;
  for (uint32_t i = 0; i < count; ++i) {
    int32_t op = ssa_resolve(s, (int32_t)s->lists[s->values[phi].list + i]);
    if (op == phi || op == same) continue;
    if (same >= 0) return phi;
    same = op;
  }
  if (same < 0) { SSA_GIVE_UP(s); return phi; } /* read before any definition */
  s->values[phi].op = SO_COPY; s->values[phi].a = same; s->values[phi].count = 0;
  return same;
}
static int32_t ssa_read(Ssa *s, uint32_t variable, uint32_t block, uint8_t cls) {
  int32_t value;
  if (s->failed) return 0;
  if (ssa_defined(s, variable, block, &value)) return ssa_resolve(s, value);
  SsaBlock *b = &s->blocks[block];
  if (!b->sealed) {
    value = ssa_new_phi(s, block, cls);
    s->pending = ssa_grow(s->pending, &s->pending_capacity, s->pending_count + 1, sizeof(SsaPending), &s->failed);
    if (s->failed) return 0;
    s->pending[s->pending_count++] = (SsaPending){block, variable, (uint32_t)value};
  } else if (b->preds.count == 1) {
    value = ssa_read(s, variable, b->preds.items[0], cls);
  } else if (!b->preds.count) {
    SSA_GIVE_UP(s); return 0;
  } else {
    value = ssa_new_phi(s, block, cls);
    ssa_define(s, variable, block, value);
    value = ssa_phi_operands(s, variable, value);
  }
  ssa_define(s, variable, block, value);
  return value;
}
static void ssa_seal(Ssa *s, uint32_t block) {
  SsaBlock *b = &s->blocks[block];
  if (b->sealed) return;
  b->sealed = true;
  for (uint32_t i = 0; i < s->pending_count; ++i) {
    if (s->pending[i].block != block) continue;
    SsaPending p = s->pending[i];
    s->pending[i--] = s->pending[--s->pending_count];
    ssa_phi_operands(s, p.variable, (int32_t)p.phi);
  }
}
static void ssa_write(Ssa *s, uint32_t variable, int32_t value) {
  if (s->current != UINT32_MAX) ssa_define(s, variable, s->current, value);
}
static void ssa_free(Ssa *s) {
  for (uint32_t i = 0; i < s->block_count; ++i) { free(s->blocks[i].values.items); free(s->blocks[i].preds.items); }
  free(s->values); free(s->blocks); free(s->lists); free(s->defs); free(s->pending);
  free(s->memory_local); free(s->local_offset); free(s->alias); free(s->captures);
}

/* ---- Building ---- */

static uint8_t ssa_class(DynType type) {
  return type == DYN_TYPE_F64 ? SC_F64 : type == DYN_TYPE_F32 ? SC_F32 : SC_INT;
}
static int64_t ssa_memory_type(const DynIrProgram *ir, DynType type) {
  type = storage_type(ir, type);
  unsigned bits = memory_bits(type);
  return SSA_MEM(bits == 1 ? 8 : bits, signed_scalar(type), float_type(type));
}
/* Integer values stay normalized: sign- or zero-extended from their width. */
static int32_t ssa_normalize(Ssa *s, int32_t v, DynType type) {
  if (payload_enum(s->ir, type) || float_type(type)) return v;
  type = storage_type(s->ir, type);
  unsigned bits = integer_bits(type);
  if (bits >= 64) return v;
  return ssa_emit(s, SO_EXT, SC_INT, v, -1, -1, bits, signed_scalar(type));
}
static int32_t ssa_compare(Ssa *s, int32_t a, int32_t b, Cond cond);
static void ssa_run_defers(Ssa *s, unsigned base);
static void ssa_protect(Ssa *s, uint32_t normal);
static int32_t ssa_checked(Ssa *s, SsaOp op, int32_t a, int32_t b, bool sign);
static bool ssa_cleanup(Ssa *s) { return s->defer_count && !s->unwinding; }
/* With defers pending, a failed check runs them before reporting, so the
   check becomes a branch to its own cleanup path. */
static void ssa_check(Ssa *s, int32_t a, int32_t b, Cond holds, unsigned kind) {
  if (ssa_cleanup(s)) {
    uint32_t ok = ssa_block(s), fail = ssa_block(s);
    if (s->failed) return;
    ssa_branch(s, ssa_compare(s, a, b, holds), ok, fail);
    ssa_seal(s, fail);
    s->current = fail;
    ssa_run_defers(s, 0);
    if (s->current != UINT32_MAX) {
      ssa_emit(s, SO_FAIL, SC_NONE, -1, -1, -1, kind, 0);
      s->blocks[s->current].kind = SB_EXIT;
    }
    ssa_seal(s, ok);
    s->current = ok;
    return;
  }
  int32_t v = ssa_emit(s, SO_CHECK, SC_NONE, a, b, -1, kind, 0);
  if (!s->failed) s->values[v].cond = (uint8_t)holds;
}
static int32_t ssa_compare(Ssa *s, int32_t a, int32_t b, Cond cond) {
  int32_t v = ssa_emit(s, SO_CMP, SC_INT, a, b, -1, 0, 0);
  if (!s->failed) s->values[v].cond = (uint8_t)cond;
  return v;
}
static int32_t ssa_load(Ssa *s, int32_t base, int32_t index, unsigned scale, int64_t offset, int64_t type) {
  uint8_t cls = type >> 9 & 1 ? ((type & 0xff) == 32 ? SC_F32 : SC_F64) : SC_INT;
  int32_t v = ssa_emit(s, SO_LOAD, cls, base, index, -1, offset, type);
  if (!s->failed) s->values[v].scale = (uint8_t)scale;
  return v;
}
static void ssa_store(Ssa *s, int32_t base, int32_t index, unsigned scale, int64_t offset, int64_t type, int32_t value) {
  int32_t v = ssa_emit(s, SO_STORE, SC_NONE, base, index, value, offset, type);
  if (!s->failed) s->values[v].scale = (uint8_t)scale;
}
static int32_t ssa_add_offset(Ssa *s, int32_t base, int64_t offset) {
  if (!offset) return base;
  return ssa_emit(s, SO_LEA, SC_INT, base, -1, -1, offset, 0);
}
/* Fresh frame memory below FP. */
static uint32_t ssa_reserve(Ssa *s, uint32_t size, uint32_t alignment) {
  if (alignment < 8) alignment = 8;
  if (size > MAX_AGGREGATE || s->frame > MAX_AGGREGATE) { SSA_GIVE_UP(s); return 0; }
  s->frame = (s->frame + size + alignment - 1) / alignment * alignment;
  return 0u - s->frame;
}
static int32_t ssa_frame(Ssa *s, uint32_t offset) {
  return ssa_emit(s, SO_FRAME, SC_INT, -1, -1, -1, (int32_t)offset, 0);
}
static int32_t ssa_symbol(Ssa *s, unsigned symbol, int kind, int64_t offset) {
  return ssa_emit(s, SO_SYMBOL, SC_INT, -1, -1, (int32_t)offset, symbol, kind);
}
static bool ssa_local_index(Ssa *s, uint64_t id, uint32_t *local) {
  if (id < s->f->local_start || id - s->f->local_start >= s->f->local_count) { SSA_GIVE_UP(s); return false; }
  *local = (uint32_t)(id - s->f->local_start);
  return true;
}
/* Pointer checks of checked_address: non-nil, then aligned for the pointee. */
static void ssa_checked_address(Ssa *s, int32_t pointer, DynType pointee) {
  uint32_t size, alignment;
  if (!layout(s->ir, pointee, &size, &alignment, 0)) { SSA_GIVE_UP(s); return; }
  ssa_check(s, pointer, ssa_const(s, 0, SC_INT), CC_NE, GUARD_NONNULL);
  if (alignment > 1) {
    int32_t low = ssa_emit(s, SO_AND, SC_INT, pointer, ssa_const(s, alignment - 1, SC_INT), -1, 0, 0);
    ssa_check(s, low, ssa_const(s, 0, SC_INT), CC_E, GUARD_ALIGNED);
  }
}
static int32_t ssa_expr(Ssa *s, DynExprId id, int32_t *second, unsigned depth);
static int32_t ssa_address(Ssa *s, DynExprId id, unsigned depth);
static void ssa_initialize(Ssa *s, int32_t destination, DynType type, DynExprId value, unsigned depth);
/* An index masked to its width, as index_expression does. */
static int32_t ssa_index(Ssa *s, DynExprId id, unsigned depth) {
  int32_t v = ssa_expr(s, id, NULL, depth);
  unsigned bits = integer_bits(s->ir->expressions[id].type);
  if (bits < 64) v = ssa_emit(s, SO_EXT, SC_INT, v, -1, -1, bits, 0);
  return v;
}
/* base + index * size, with x86 scaling when size allows it. */
static int32_t ssa_element(Ssa *s, int32_t base, int32_t index, uint32_t size) {
  if (size == 1 || size == 2 || size == 4 || size == 8) {
    int32_t v = ssa_emit(s, SO_LEA, SC_INT, base, index, -1, 0, 0);
    if (!s->failed) s->values[v].scale = (uint8_t)size;
    return v;
  }
  int32_t scaled = ssa_emit(s, SO_MUL, SC_INT, index, ssa_const(s, size, SC_INT), -1, 0, 0);
  return ssa_emit(s, SO_LEA, SC_INT, base, scaled, -1, 0, 0);
}
/* Address of a local kept in memory or reached through a pointer binding. */
static bool ssa_in_memory(Ssa *s, uint32_t local) { return s->alias[local] >= 0 || s->memory_local[local]; }
static int32_t ssa_local_address(Ssa *s, uint32_t local) {
  return s->alias[local] >= 0 ? s->alias[local] : ssa_frame(s, s->local_offset[local]);
}
static int32_t ssa_address(Ssa *s, DynExprId id, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  if (s->unsupported || s->failed || id >= ir->expression_count || depth > MAX_DEPTH) { SSA_GIVE_UP(s); return 0; }
  const DynIrExpr *e = &ir->expressions[id];
  if (e->kind == DYN_EXPR_NAME) {
    uint32_t local;
    if (!ssa_local_index(s, e->integer, &local)) return 0;
    if (!ssa_in_memory(s, local)) { SSA_GIVE_UP(s); return 0; }
    return ssa_local_address(s, local);
  }
  if (e->kind == DYN_EXPR_GLOBAL) {
    if (e->integer >= ir->global_count || !s->ctx->global_symbols[e->integer]) { SSA_GIVE_UP(s); return 0; }
    return ssa_symbol(s, s->ctx->global_symbols[e->integer], SYM_GLOBAL, 0);
  }
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_DEREF) {
    if (dyn_type_is_function(e->type)) { SSA_GIVE_UP(s); return 0; }
    int32_t pointer = ssa_expr(s, e->left, NULL, depth + 1);
    ssa_checked_address(s, pointer, e->type);
    return pointer;
  }
  if (e->kind == DYN_EXPR_FIELD) {
    if (e->left >= ir->expression_count) { SSA_GIVE_UP(s); return 0; }
    DynType type = ir->expressions[e->left].type;
    int32_t base;
    if (dyn_type_is_pointer(type)) {
      if (type - DYN_TYPE_POINTER_BASE >= ir->pointer_count) { SSA_GIVE_UP(s); return 0; }
      base = ssa_expr(s, e->left, NULL, depth + 1);
      type = ir->pointers[type - DYN_TYPE_POINTER_BASE].pointee;
      ssa_checked_address(s, base, type);
    } else base = ssa_address(s, e->left, depth + 1);
    uint32_t offset;
    if (!field_offset(ir, type, (uint32_t)e->integer, &offset)) { SSA_GIVE_UP(s); return 0; }
    return ssa_add_offset(s, base, offset);
  }
  if (e->kind == DYN_EXPR_INDEX) {
    if (e->left >= ir->expression_count || e->right >= ir->expression_count) { SSA_GIVE_UP(s); return 0; }
    DynType type = ir->expressions[e->left].type;
    bool array = dyn_type_is_array(type);
    uint32_t size, alignment;
    if ((!array && !descriptor(type)) || (array && type - DYN_TYPE_ARRAY_BASE >= ir->array_count) ||
        type == DYN_TYPE_ANY || !layout(ir, e->type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return 0; }
    int32_t index = ssa_index(s, e->right, depth + 1), base, length;
    if (array) {
      base = ssa_address(s, e->left, depth + 1);
      length = ssa_const(s, ir->arrays[type - DYN_TYPE_ARRAY_BASE].length, SC_INT);
    } else base = ssa_expr(s, e->left, &length, depth + 1);
    ssa_check(s, index, length, CC_B, GUARD_INDEX);
    return ssa_element(s, base, index, size);
  }
  /* Aggregate rvalues (calls, literals) already evaluate to an address. */
  if (aggregate(ir, e->type)) return ssa_expr(s, id, NULL, depth + 1);
  SSA_GIVE_UP(s);
  return 0;
}
/* A temporary holding an aggregate value; returns its address. */
static int32_t ssa_temporary(Ssa *s, DynType type) {
  uint32_t size, alignment;
  if (!layout(s->ir, type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return 0; }
  return ssa_frame(s, ssa_reserve(s, size ? size : 1, alignment));
}
static int32_t ssa_binary(Ssa *s, const DynIrExpr *e, int32_t left, int32_t right);
static int32_t ssa_call(Ssa *s, const DynIrExpr *e, int32_t *second, unsigned depth);
/* Value of a scalar local, global, field or element in memory. */
static int32_t ssa_load_value(Ssa *s, int32_t address, DynType type, int32_t *second) {
  if (descriptor(type)) {
    int32_t data = ssa_load(s, address, -1, 1, 0, SSA_MEM(64, 0, 0));
    int32_t length = ssa_load(s, address, -1, 1, 8, SSA_MEM(64, 0, 0));
    if (second) *second = length;
    return data;
  }
  if (aggregate(s->ir, type)) return address;
  if (!scalar(s->ir, type)) { SSA_GIVE_UP(s); return 0; }
  int32_t v = ssa_load(s, address, -1, 1, 0, ssa_memory_type(s->ir, type));
  if (storage_type(s->ir, type) == DYN_TYPE_BOOL) v = ssa_normalize(s, v, DYN_TYPE_BOOL);
  return v;
}
static void ssa_store_value(Ssa *s, int32_t address, DynType type, int32_t value, int32_t second) {
  if (descriptor(type)) {
    ssa_store(s, address, -1, 1, 0, SSA_MEM(64, 0, 0), value);
    ssa_store(s, address, -1, 1, 8, SSA_MEM(64, 0, 0), second);
    return;
  }
  if (aggregate(s->ir, type)) {
    uint32_t size, alignment;
    if (!layout(s->ir, type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return; }
    ssa_emit(s, SO_COPYMEM, SC_NONE, address, value, -1, size, 0);
    return;
  }
  ssa_store(s, address, -1, 1, 0, ssa_memory_type(s->ir, type), value);
}
static int32_t ssa_cast(Ssa *s, const DynIrExpr *e, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  if (e->left >= ir->expression_count) { SSA_GIVE_UP(s); return 0; }
  DynType from = storage_type(ir, ir->expressions[e->left].type);
  if (dyn_type_is_enum(e->type)) {
    if (payload_enum(ir, e->type) || !integer_type(from)) { SSA_GIVE_UP(s); return 0; }
    int32_t v = ssa_expr(s, e->left, NULL, depth + 1), any = -1;
    const DynIrEnum *en = &ir->enums[e->type - DYN_TYPE_ENUM_BASE];
    for (unsigned i = 0; i < en->variant_count; ++i) {
      uint64_t tag = ir->variants[en->variant_start + i].tag; unsigned bits = integer_bits(en->tag_type);
      if (signed_scalar(en->tag_type) && bits < 64 && (tag >> (bits - 1) & 1)) tag |= UINT64_MAX << bits;
      if (signed_scalar(from) != signed_scalar(en->tag_type) && (int64_t)tag < 0) continue;
      int32_t match = ssa_compare(s, v, ssa_const(s, tag, SC_INT), CC_E);
      any = any < 0 ? match : ssa_emit(s, SO_OR, SC_INT, any, match, -1, 0, 0);
    }
    ssa_check(s, any < 0 ? ssa_const(s, 0, SC_INT) : any, ssa_const(s, 0, SC_INT), CC_NE, GUARD_ENUM);
    return ssa_normalize(s, v, e->type);
  }
  bool from_pointer = dyn_type_is_pointer(from) || from == DYN_TYPE_RAWPTR;
  bool to_pointer = dyn_type_is_pointer(e->type) || e->type == DYN_TYPE_RAWPTR;
  bool pointer_conversion = (from_pointer || to_pointer) &&
    (from_pointer || integer_type(from)) && (to_pointer || integer_type(e->type));
  bool integer_float = integer_type(from) && float_type(e->type), float_integer = float_type(from) && integer_type(e->type);
  if (!((integer_type(e->type) && integer_type(from)) || (float_type(e->type) && float_type(from)) ||
        pointer_conversion || integer_float || float_integer)) { SSA_GIVE_UP(s); return 0; }
  int32_t v = ssa_expr(s, e->left, NULL, depth + 1);
  if (integer_float)
    return ssa_emit(s, SO_ITOF, ssa_class(e->type), v, -1, -1, !signed_scalar(from) && integer_bits(from) == 64, 0);
  if (float_integer) {
    v = ssa_emit(s, SO_FTOI, SC_INT, v, -1, -1, !signed_scalar(e->type) && integer_bits(e->type) == 64, 0);
    return ssa_normalize(s, v, e->type);
  }
  if (to_pointer && integer_type(from) && integer_bits(from) < 64)
    v = ssa_emit(s, SO_EXT, SC_INT, v, -1, -1, integer_bits(from), 0);
  if (float_type(e->type)) return e->type != from ? ssa_emit(s, SO_FCVT, ssa_class(e->type), v, -1, -1, 0, 0) : v;
  return ssa_normalize(s, v, e->type);
}
static int32_t ssa_unary(Ssa *s, const DynIrExpr *e, int32_t *second, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  if (e->op == DYN_OP_ADDRESS) {
    if (e->left < ir->expression_count && ir->expressions[e->left].kind == DYN_EXPR_FUNCTION)
      return ssa_expr(s, e->left, NULL, depth + 1);
    return ssa_address(s, e->left, depth + 1);
  }
  if (e->op == DYN_OP_DEREF) {
    if (dyn_type_is_function(e->type)) { SSA_GIVE_UP(s); return 0; }
    int32_t pointer = ssa_expr(s, e->left, NULL, depth + 1);
    ssa_checked_address(s, pointer, e->type);
    return ssa_load_value(s, pointer, e->type, second);
  }
  if (float_type(e->type)) {
    if (e->op != DYN_OP_NEG) { SSA_GIVE_UP(s); return 0; }
    return ssa_emit(s, SO_FNEG, ssa_class(e->type), ssa_expr(s, e->left, NULL, depth + 1), -1, -1, 0, 0);
  }
  if (e->op == DYN_OP_NEG && e->boolean) {
    if (e->left >= ir->expression_count || ir->expressions[e->left].kind != DYN_EXPR_INT) { SSA_GIVE_UP(s); return 0; }
    return ssa_const(s, UINT64_C(0) - ir->expressions[e->left].integer, SC_INT);
  }
  if (e->op != DYN_OP_BIT_NOT && e->op != DYN_OP_NOT && e->op != DYN_OP_NEG) { SSA_GIVE_UP(s); return 0; }
  int32_t v = ssa_expr(s, e->left, NULL, depth + 1);
  if (e->op == DYN_OP_NOT) return ssa_emit(s, SO_XOR, SC_INT, v, ssa_const(s, 1, SC_INT), -1, 0, 0);
  if (e->op == DYN_OP_BIT_NOT) return ssa_normalize(s, ssa_emit(s, SO_NOT, SC_INT, v, -1, -1, 0, 0), e->type);
  bool sign = signed_scalar(e->type);
  unsigned bits = integer_bits(storage_type(ir, e->type));
  if (e->wrap) return ssa_normalize(s, ssa_emit(s, SO_NEG, SC_INT, v, -1, -1, 0, 0), e->type);
  if (!sign) {
    /* Negation borrows exactly when the operand is nonzero. */
    ssa_check(s, v, ssa_const(s, 0, SC_INT), CC_E, GUARD_OVERFLOW);
    return ssa_const(s, 0, SC_INT);
  }
  if (bits == 64) return ssa_checked(s, SO_SUBO, ssa_const(s, 0, SC_INT), v, true);
  int32_t t = ssa_emit(s, SO_NEG, SC_INT, v, -1, -1, 0, 0), n = ssa_normalize(s, t, e->type);
  ssa_check(s, n, t, CC_E, GUARD_OVERFLOW);
  return n;
}
/* A descriptor slice of an array, pointer or descriptor. */
static int32_t ssa_slice(Ssa *s, const DynIrExpr *e, int32_t *second, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  if (e->left >= ir->expression_count) { SSA_GIVE_UP(s); return 0; }
  DynType base = ir->expressions[e->left].type;
  bool raw = dyn_type_is_pointer(base);
  int32_t data, length = -1;
  if (dyn_type_is_array(base)) {
    if (base - DYN_TYPE_ARRAY_BASE >= ir->array_count) { SSA_GIVE_UP(s); return 0; }
    data = ssa_address(s, e->left, depth + 1);
    length = ssa_const(s, ir->arrays[base - DYN_TYPE_ARRAY_BASE].length, SC_INT);
  } else if (raw) {
    if (base - DYN_TYPE_POINTER_BASE >= ir->pointer_count) { SSA_GIVE_UP(s); return 0; }
    data = ssa_expr(s, e->left, NULL, depth + 1);
    ssa_checked_address(s, data, ir->pointers[base - DYN_TYPE_POINTER_BASE].pointee);
  } else if (descriptor(base) && base != DYN_TYPE_ANY) data = ssa_expr(s, e->left, &length, depth + 1);
  else { SSA_GIVE_UP(s); return 0; }
  int32_t start = e->right == DYN_NO_EXPR ? ssa_const(s, 0, SC_INT) : ssa_index(s, e->right, depth + 1);
  int32_t end;
  if (e->integer == DYN_NO_EXPR && !raw) end = length;
  else if (e->integer == DYN_NO_EXPR) { SSA_GIVE_UP(s); return 0; }
  else end = ssa_index(s, (DynExprId)e->integer, depth + 1);
  ssa_check(s, start, end, CC_BE, GUARD_SLICE_ORDER);
  if (!raw) ssa_check(s, end, length, CC_BE, GUARD_SLICE_BOUNDS);
  DynType element = e->type == DYN_TYPE_STRING ? DYN_TYPE_U8 : ir->slices[e->type - DYN_TYPE_SLICE_BASE].element;
  uint32_t size, alignment;
  if (!layout(ir, element, &size, &alignment, 0)) { SSA_GIVE_UP(s); return 0; }
  if (second) *second = ssa_emit(s, SO_SUB, SC_INT, end, start, -1, 0, 0);
  return ssa_element(s, data, start, size);
}
static int32_t ssa_constant_scalar(Ssa *s, const DynIrExpr *e, bool *found) {
  uint64_t bits;
  *found = scalar(s->ir, e->type) && constant_bits(s->ctx, s->ir, e, &bits, 0);
  return *found ? ssa_const(s, bits, ssa_class(e->type)) : 0;
}
static int32_t ssa_expr(Ssa *s, DynExprId id, int32_t *second, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  if (s->unsupported || s->failed || depth > MAX_DEPTH || id >= ir->expression_count || s->current == UINT32_MAX) {
    SSA_GIVE_UP(s); return 0;
  }
  const DynIrExpr *e = &ir->expressions[id];
  if (s->unwinding)
    for (uint32_t i = s->capture_count; i-- > 0;)
      if (s->captures[i].expression == id) {
        if (descriptor(e->type) && second) *second = ssa_read(s, s->captures[i].variable + 1, s->current, SC_INT);
        return ssa_read(s, s->captures[i].variable, s->current, ssa_class(e->type));
      }
  bool found;
  int32_t constant = ssa_constant_scalar(s, e, &found);
  if (found) return constant;
  switch (e->kind) {
  case DYN_EXPR_INT: case DYN_EXPR_CHAR: case DYN_EXPR_BOOL: case DYN_EXPR_FLOAT:
    SSA_GIVE_UP(s); return 0; /* constant_bits handles every valid literal */
  case DYN_EXPR_NIL:
    if (descriptor(e->type)) { if (second) *second = ssa_const(s, 0, SC_INT); return ssa_const(s, 0, SC_INT); }
    if (dyn_type_is_pointer(e->type) || e->type == DYN_TYPE_RAWPTR || dyn_type_is_function(e->type)) return ssa_const(s, 0, SC_INT);
    break;
  case DYN_EXPR_STRING: {
    if (e->integer >= ir->string_count || !descriptor(e->type)) break;
    const DynIrString *string = &ir->strings[e->integer];
    size_t at = literal(s->ctx, (const char *)string->data, string->length);
    if (s->ctx->rodata.failed) { s->failed = true; return 0; }
    if (second) *second = ssa_const(s, string->length, SC_INT);
    return ssa_symbol(s, 1, SYM_LOCAL, (int64_t)at);
  }
  case DYN_EXPR_NAME: {
    uint32_t local;
    if (!ssa_local_index(s, e->integer, &local)) return 0;
    DynType type = ir->locals[e->integer].type;
    if (ssa_in_memory(s, local)) return ssa_load_value(s, ssa_local_address(s, local), type, second);
    if (descriptor(type) && second) *second = ssa_read(s, 2 * local + 1, s->current, SC_INT);
    return ssa_read(s, 2 * local, s->current, ssa_class(type));
  }
  case DYN_EXPR_GLOBAL: {
    if (e->integer >= ir->global_count || !s->ctx->global_symbols[e->integer]) break;
    int32_t address = ssa_symbol(s, s->ctx->global_symbols[e->integer], SYM_GLOBAL, 0);
    return ssa_load_value(s, address, e->type, second);
  }
  case DYN_EXPR_FUNCTION:
    if (e->integer >= ir->function_count || !s->ctx->function_symbols[e->integer]) break;
    return ssa_symbol(s, s->ctx->function_symbols[e->integer], SYM_FUNCTION, 0);
  case DYN_EXPR_FIELD: case DYN_EXPR_INDEX:
    if (aggregate(ir, e->type)) return ssa_address(s, id, depth + 1);
    return ssa_load_value(s, ssa_address(s, id, depth + 1), e->type, second);
  case DYN_EXPR_LEN: {
    if (e->left >= ir->expression_count) break;
    DynType type = ir->expressions[e->left].type;
    if (descriptor(type) && type != DYN_TYPE_ANY) {
      int32_t length = 0;
      ssa_expr(s, e->left, &length, depth + 1);
      return length;
    }
    if (!dyn_type_is_array(type) || type - DYN_TYPE_ARRAY_BASE >= ir->array_count) break;
    return ssa_const(s, ir->arrays[type - DYN_TYPE_ARRAY_BASE].length, SC_INT);
  }
  case DYN_EXPR_SLICE:
    return ssa_slice(s, e, second, depth);
  case DYN_EXPR_CONVERT:
    if (descriptor(e->type) && e->type != DYN_TYPE_ANY) {
      if (e->left >= ir->expression_count || !descriptor(ir->expressions[e->left].type)) break;
      return ssa_expr(s, e->left, second, depth + 1);
    }
    if (e->type == DYN_TYPE_ANY) {
      /* any is {type id, pointer to a boxed copy}. */
      if (e->left >= ir->expression_count) break;
      DynType source = ir->expressions[e->left].type;
      int32_t box = ssa_temporary(s, source);
      ssa_initialize(s, box, source, e->left, depth + 1);
      if (second) *second = box;
      return ssa_const(s, source, SC_INT);
    }
    /* fall through */
  case DYN_EXPR_CAST:
    if (!scalar(ir, e->type)) break;
    return ssa_cast(s, e, depth);
  case DYN_EXPR_BITCAST: {
    if (e->left >= ir->expression_count) break;
    DynType from = ir->expressions[e->left].type;
    if (!scalar(ir, from) || !(integer_type(e->type) || float_type(e->type)) ||
        !(integer_type(from) || float_type(from)) || memory_bits(e->type) != memory_bits(from)) break;
    int32_t v = ssa_expr(s, e->left, NULL, depth + 1);
    if (float_type(e->type) != float_type(from)) v = ssa_emit(s, SO_BITS, ssa_class(e->type), v, -1, -1, 0, 0);
    return ssa_normalize(s, v, e->type);
  }
  case DYN_EXPR_UNARY:
    return ssa_unary(s, e, second, depth);
  case DYN_EXPR_BINARY: {
    if (e->op == DYN_OP_LOGICAL_AND || e->op == DYN_OP_LOGICAL_OR) {
      /* left && right is left ? right : 0; left || right is left ? 1 : right. */
      int32_t left = ssa_expr(s, e->left, NULL, depth + 1);
      uint32_t right_block = ssa_block(s), join = ssa_block(s), from = s->current;
      if (s->failed) return 0;
      uint32_t variable = s->variable_count + s->hidden_variables++;
      ssa_write(s, variable, left);
      if (e->op == DYN_OP_LOGICAL_AND) ssa_branch(s, left, right_block, join);
      else ssa_branch(s, left, join, right_block);
      ssa_seal(s, right_block);
      s->current = right_block;
      int32_t right = ssa_expr(s, e->right, NULL, depth + 1);
      ssa_write(s, variable, right);
      ssa_jump(s, join);
      ssa_seal(s, join);
      s->current = join;
      (void)from;
      return ssa_read(s, variable, join, SC_INT);
    }
    int32_t left = ssa_expr(s, e->left, NULL, depth + 1);
    int32_t right = ssa_expr(s, e->right, NULL, depth + 1);
    return ssa_binary(s, e, left, right);
  }
  case DYN_EXPR_CALL: case DYN_EXPR_INDIRECT_CALL:
    return ssa_call(s, e, second, depth);
  case DYN_EXPR_SYSCALL: {
    /* dyn_syscall6: six register arguments and the seventh on the stack. */
    if (e->item_count > 7 || (uint64_t)e->item_start + e->item_count > ir->item_count) break;
    int32_t items[21];
    for (unsigned i = 0; i < 7; ++i) {
      int32_t v;
      if (i < e->item_count) {
        DynExprId argument = ir->items[e->item_start + i].expression;
        if (argument >= ir->expression_count || !scalar(ir, ir->expressions[argument].type)) { SSA_GIVE_UP(s); return 0; }
        v = ssa_expr(s, argument, NULL, depth + 1);
      } else v = ssa_const(s, 0, SC_INT);
      items[3 * i] = v; items[3 * i + 1] = i < 6 || s->ctx->a64 ? (int32_t)i : SSA_STACK; items[3 * i + 2] = 0;
    }
    int32_t call = ssa_emit(s, SO_CALL, SC_NONE, -1, -1, -1, 9, 1);
    if (s->failed) return 0;
    s->values[call].list = ssa_list(s, items, 21); s->values[call].count = 7;
    if (s->outgoing < 8 && !s->ctx->a64) s->outgoing = 8;
    s->calls = true;
    return ssa_emit(s, SO_RESULT, SC_INT, call, -1, -1, 0, 0);
  }
  case DYN_EXPR_STRUCT: case DYN_EXPR_ARRAY: {
    if (s->ctx->literal_offsets[id])
      return ssa_symbol(s, s->ctx->literals_symbol, SYM_LOCAL, s->ctx->literal_offsets[id] - 1);
    int32_t address = ssa_temporary(s, e->type);
    ssa_initialize(s, address, e->type, id, depth + 1);
    return address;
  }
  case DYN_EXPR_ENUM: {
    if (!dyn_type_is_enum(e->type) || e->type - DYN_TYPE_ENUM_BASE >= ir->enum_count || e->integer >= ir->variant_count) break;
    const DynIrEnum *en = &ir->enums[e->type - DYN_TYPE_ENUM_BASE];
    const DynIrVariant *variant = &ir->variants[e->integer];
    if (!en->has_payload) {
      uint64_t tag = variant->tag;
      unsigned bits = integer_bits(en->tag_type);
      if (bits < 64) {
        tag &= (UINT64_C(1) << bits) - 1;
        if (signed_scalar(en->tag_type) && (tag >> (bits - 1) & 1)) tag |= UINT64_MAX << bits;
      }
      return ssa_const(s, tag, SC_INT);
    }
    int32_t address = ssa_temporary(s, e->type);
    uint32_t size, alignment;
    if (!layout(ir, e->type, &size, &alignment, 0)) break;
    ssa_emit(s, SO_ZEROMEM, SC_NONE, address, -1, -1, size, 0);
    ssa_store(s, address, -1, 1, 0, ssa_memory_type(ir, en->tag_type), ssa_const(s, variant->tag, SC_INT));
    if (variant->payload_type != DYN_TYPE_VOID) {
      if (e->item_count != 1 || e->item_start >= ir->item_count) break;
      uint32_t tag_size = (memory_bits(en->tag_type) + 7) / 8, a = (uint32_t)en->payload_alignment;
      int32_t payload = ssa_add_offset(s, address, (tag_size + a - 1) & ~(a - 1));
      ssa_initialize(s, payload, variant->payload_type, ir->items[e->item_start].expression, depth + 1);
    }
    return address;
  }
  default:
    break;
  }
  SSA_GIVE_UP(s);
  return 0;
}
/* 64-bit add, subtract or multiply that panics on overflow. With defers
   pending the overflow test is explicit, since its failure path needs a
   block of its own. */
static int32_t ssa_checked(Ssa *s, SsaOp op, int32_t a, int32_t b, bool sign) {
  if (!ssa_cleanup(s)) return ssa_emit(s, op, SC_INT, a, b, -1, 0, sign);
  SsaOp plain = op == SO_ADDO ? SO_ADD : op == SO_SUBO ? SO_SUB : SO_MUL;
  int32_t r = ssa_emit(s, plain, SC_INT, a, b, -1, 0, 0), zero = ssa_const(s, 0, SC_INT);
  if (op == SO_MULO) {
    int32_t high = ssa_emit(s, SO_MULH, SC_INT, a, b, -1, 0, sign);
    int32_t expected = sign ? ssa_emit(s, SO_SAR, SC_INT, r, ssa_const(s, 63, SC_INT), -1, 0, 0) : zero;
    ssa_check(s, high, expected, CC_E, GUARD_OVERFLOW);
  } else if (!sign) ssa_check(s, op == SO_ADDO ? r : a, op == SO_ADDO ? a : b, CC_AE, GUARD_OVERFLOW);
  else {
    /* Signed overflow: the result's sign differs from what the operands allow. */
    int32_t x = op == SO_ADDO ? ssa_emit(s, SO_XOR, SC_INT, a, r, -1, 0, 0) : ssa_emit(s, SO_XOR, SC_INT, a, b, -1, 0, 0);
    int32_t y = op == SO_ADDO ? ssa_emit(s, SO_XOR, SC_INT, b, r, -1, 0, 0) : ssa_emit(s, SO_XOR, SC_INT, a, r, -1, 0, 0);
    ssa_check(s, ssa_emit(s, SO_AND, SC_INT, x, y, -1, 0, 0), zero, CC_GE, GUARD_OVERFLOW);
  }
  return r;
}
static int32_t ssa_binary(Ssa *s, const DynIrExpr *e, int32_t left, int32_t right) {
  const DynIrProgram *ir = s->ir;
  DynType operand = ir->expressions[e->left].type;
  bool comparison = e->op >= DYN_OP_EQ && e->op <= DYN_OP_GE;
  if (float_type(operand)) {
    uint8_t cls = ssa_class(operand);
    if (comparison) {
      int32_t v = ssa_emit(s, SO_FCMP, SC_INT, left, right, -1, e->op - DYN_OP_EQ, 0);
      return v;
    }
    if (e->op == DYN_OP_REM) {
      int32_t items[6] = {left, 8, 0, right, 9, 0};
      int32_t call = ssa_emit(s, SO_CALL, SC_NONE, -1, -1, -1, operand == DYN_TYPE_F32 ? 8 : 7, 1);
      if (s->failed) return 0;
      s->values[call].list = ssa_list(s, items, 6); s->values[call].count = 2;
      s->calls = true;
      return ssa_emit(s, SO_RESULT, cls, call, -1, -1, X_XMM0, 0);
    }
    SsaOp op = e->op == DYN_OP_ADD ? SO_FADD : e->op == DYN_OP_SUB ? SO_FSUB : e->op == DYN_OP_MUL ? SO_FMUL :
               e->op == DYN_OP_DIV ? SO_FDIV : SO_COUNT;
    if (op == SO_COUNT) { SSA_GIVE_UP(s); return 0; }
    return ssa_emit(s, op, cls, left, right, -1, 0, 0);
  }
  if (comparison) {
    static const Cond signed_conditions[] = {CC_E, CC_NE, CC_L, CC_LE, CC_G, CC_GE};
    static const Cond unsigned_conditions[] = {CC_E, CC_NE, CC_B, CC_BE, CC_A, CC_AE};
    bool sign = signed_scalar(storage_type(ir, operand));
    return ssa_compare(s, left, right, (sign ? signed_conditions : unsigned_conditions)[e->op - DYN_OP_EQ]);
  }
  if (!integer_type(operand)) { SSA_GIVE_UP(s); return 0; }
  DynType type = e->type;
  bool sign = signed_scalar(type);
  unsigned bits = integer_bits(storage_type(ir, type));
  int32_t result;
  switch (e->op) {
  case DYN_OP_ADD: case DYN_OP_SUB: case DYN_OP_MUL: {
    SsaOp plain = e->op == DYN_OP_ADD ? SO_ADD : e->op == DYN_OP_SUB ? SO_SUB : SO_MUL;
    SsaOp checked = e->op == DYN_OP_ADD ? SO_ADDO : e->op == DYN_OP_SUB ? SO_SUBO : SO_MULO;
    if (e->wrap) return ssa_normalize(s, ssa_emit(s, plain, SC_INT, left, right, -1, 0, 0), type);
    if (bits == 64) return ssa_checked(s, checked, left, right, sign);
    /* Normalized narrow operands cannot overflow 64 bits; the narrowed result
       must equal the full one. */
    int32_t full = ssa_emit(s, plain, SC_INT, left, right, -1, 0, 0);
    result = ssa_normalize(s, full, type);
    ssa_check(s, result, full, CC_E, GUARD_OVERFLOW);
    return result;
  }
  case DYN_OP_DIV: case DYN_OP_REM: {
    ssa_check(s, right, ssa_const(s, 0, SC_INT), CC_NE, GUARD_DIVIDE);
    if (sign) {
      int32_t minimum = ssa_compare(s, left, ssa_const(s, UINT64_C(0) - (UINT64_C(1) << (bits - 1)), SC_INT), CC_E);
      int32_t negative_one = ssa_compare(s, right, ssa_const(s, UINT64_MAX, SC_INT), CC_E);
      int32_t both = ssa_emit(s, SO_AND, SC_INT, minimum, negative_one, -1, 0, 0);
      ssa_check(s, both, ssa_const(s, 0, SC_INT), CC_E, GUARD_DIVISION_OVERFLOW);
    }
    return ssa_emit(s, e->op == DYN_OP_DIV ? SO_DIV : SO_REM, SC_INT, left, right, -1, 0, sign);
  }
  case DYN_OP_SHL: case DYN_OP_SHR: {
    ssa_check(s, right, ssa_const(s, bits, SC_INT), CC_B, GUARD_SHIFT);
    SsaOp back = sign ? SO_SAR : SO_SHR;
    if (e->op == DYN_OP_SHR) return ssa_emit(s, back, SC_INT, left, right, -1, 0, 0);
    int32_t shifted = ssa_emit(s, SO_SHL, SC_INT, left, right, -1, 0, 0);
    if (e->wrap) return ssa_normalize(s, shifted, type);
    int32_t restored = ssa_emit(s, back, SC_INT, shifted, right, -1, 0, 0);
    ssa_check(s, restored, left, CC_E, GUARD_OVERFLOW);
    if (bits == 64) return shifted;
    result = ssa_normalize(s, shifted, type);
    ssa_check(s, result, shifted, CC_E, GUARD_OVERFLOW);
    return result;
  }
  case DYN_OP_BIT_AND: return ssa_emit(s, SO_AND, SC_INT, left, right, -1, 0, 0);
  case DYN_OP_BIT_OR: return ssa_emit(s, SO_OR, SC_INT, left, right, -1, 0, 0);
  case DYN_OP_BIT_XOR: return ssa_emit(s, SO_XOR, SC_INT, left, right, -1, 0, 0);
  default:
    SSA_GIVE_UP(s);
    return 0;
  }
}
/* Exactly `size` bytes at address + offset, zero-extended, never reading past them. */
static int32_t ssa_load_bytes(Ssa *s, int32_t address, uint32_t offset, uint32_t size) {
  int32_t result = -1;
  uint32_t done = 0;
  while (done < size) {
    uint32_t width = size - done >= 8 ? 8 : size - done >= 4 ? 4 : size - done >= 2 ? 2 : 1;
    int32_t piece = ssa_load(s, address, -1, 1, offset + done, SSA_MEM(width * 8, 0, 0));
    if (done) piece = ssa_emit(s, SO_SHL, SC_INT, piece, ssa_const(s, done * 8, SC_INT), -1, 0, 0);
    result = result < 0 ? piece : ssa_emit(s, SO_OR, SC_INT, result, piece, -1, 0, 0);
    done += width;
  }
  return result < 0 ? ssa_const(s, 0, SC_INT) : result;
}
static void ssa_store_bytes(Ssa *s, int32_t address, uint32_t offset, uint32_t size, int32_t value) {
  uint32_t done = 0;
  while (done < size) {
    uint32_t width = size - done >= 8 ? 8 : size - done >= 4 ? 4 : size - done >= 2 ? 2 : 1;
    int32_t piece = done ? ssa_emit(s, SO_SHR, SC_INT, value, ssa_const(s, done * 8, SC_INT), -1, 0, 0) : value;
    ssa_store(s, address, -1, 1, offset + done, SSA_MEM(width * 8, 0, 0), piece);
    done += width;
  }
}
/* Call arguments are triples in the value's list: value, location, bytes.
   Locations: 0-5 GP argument registers, 8-15 XMM registers, 32 the indirect
   target (RAX), 64 + offset an outgoing stack slot. bytes > 0 copies that many
   bytes from the address in value to the stack slot. */
typedef struct { int32_t *items; uint32_t count, capacity; } SsaArguments;
static void ssa_argument(Ssa *s, SsaArguments *list, int32_t value, int32_t location, int32_t bytes) {
  list->items = ssa_grow(list->items, &list->capacity, list->count + 3, sizeof(int32_t), &s->failed);
  if (s->failed) return;
  list->items[list->count++] = value; list->items[list->count++] = location; list->items[list->count++] = bytes;
}
static void ssa_pass(Ssa *s, SsaArguments *list, DynType type, int32_t value, int32_t second,
                     AbiPart *parts, unsigned count, uint32_t *stack) {
  const DynIrProgram *ir = s->ir;
  if (s->ctx->a64) {
    /* AAPCS64 stack parts take their own slots: eight bytes on Linux, natural
       size on Apple. bytes = -width marks a stack store of that width. */
    for (unsigned i = 0; i < count; ++i) {
      bool floating = float_type(storage_type(ir, parts[i].leaf)) || parts[i].cls >= 8;
      int32_t part;
      if (aggregate(ir, type))
        part = floating ? ssa_load(s, value, -1, 1, parts[i].offset, SSA_MEM(parts[i].size == 4 ? 32 : 64, 0, 1))
                        : ssa_load_bytes(s, value, parts[i].offset, parts[i].size);
      else part = i ? second : value;
      if (parts[i].cls >= 0) { ssa_argument(s, list, part, parts[i].cls, 0); continue; }
      uint32_t at = stack_slot(s->ctx, &parts[i], stack);
      ssa_argument(s, list, part, SSA_STACK + (int32_t)at, -(int32_t)stack_width(s->ctx, &parts[i]));
    }
    return;
  }
  if (aggregate(ir, type)) {
    uint32_t size, alignment;
    if (!layout(ir, type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return; }
    if (count && parts[0].cls < 0) {
      /* Memory class: a snapshot now, copied to the outgoing area at the call. */
      int32_t copy = ssa_temporary(s, type);
      ssa_emit(s, SO_COPYMEM, SC_NONE, copy, value, -1, size, 0);
      ssa_argument(s, list, copy, SSA_STACK + (int32_t)*stack, (int32_t)size);
      *stack += (size + 7) / 8 * 8;
      return;
    }
    for (unsigned i = 0; i < count; ++i) {
      int32_t part;
      if (parts[i].cls >= 8)
        part = ssa_load(s, value, -1, 1, parts[i].offset, SSA_MEM(parts[i].size == 4 ? 32 : 64, 0, 1));
      else part = ssa_load_bytes(s, value, parts[i].offset, parts[i].size);
      ssa_argument(s, list, part, parts[i].cls, 0);
    }
    return;
  }
  for (unsigned i = 0; i < count; ++i) {
    int32_t part = i ? second : value;
    if (parts[i].cls >= 0) ssa_argument(s, list, part, parts[i].cls, 0);
    else { ssa_argument(s, list, part, SSA_STACK + (int32_t)*stack, 0); *stack += 8; }
  }
}
/* Register parts of a struct result: System V eightbytes, or on AArch64 the
   members of a homogeneous float aggregate or up to two words. aux: result
   slot (0 and 1 integer, X_XMM0 + n floating). False: returned in memory. */
typedef struct { uint32_t offset, size; int aux; bool floating; } SsaPart;
static bool ssa_struct_parts(Ssa *s, DynType type, SsaPart *parts, unsigned *count) {
  const DynIrProgram *ir = s->ir;
  uint32_t size, alignment;
  if (!layout(ir, type, &size, &alignment, 0) || abi_memory(s->ctx, ir, type)) return false;
  if (s->ctx->a64) {
    DynType element; unsigned members;
    if (a64_struct_hfa(ir, type, &element, &members)) {
      unsigned bytes = memory_bits(element) / 8;
      for (unsigned i = 0; i < members; ++i) parts[i] = (SsaPart){i * bytes, bytes, X_XMM0 + (int)i, true};
      *count = members;
      return true;
    }
    *count = (size + 7) / 8;
    for (unsigned i = 0; i < *count; ++i) parts[i] = (SsaPart){i * 8, size - i * 8 > 8 ? 8 : size - i * 8, (int)i, false};
    return true;
  }
  unsigned cls[2], integers = 0, floats = 0;
  if (!abi_value(ir, type, count, cls)) return false;
  for (unsigned i = 0; i < *count; ++i) {
    bool fl = cls[i] == 2;
    parts[i] = (SsaPart){i * 8, size - i * 8 > 8 ? 8 : size - i * 8, fl ? X_XMM0 + (int)floats++ : (int)integers++, fl};
  }
  return true;
}
static int32_t ssa_call(Ssa *s, const DynIrExpr *e, int32_t *second, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  BackendContext *ctx = s->ctx;
  bool indirect = e->kind == DYN_EXPR_INDIRECT_CALL;
  if (e->item_count > 512 || (uint64_t)e->item_start + e->item_count > ir->item_count) { SSA_GIVE_UP(s); return 0; }
  DynType result = e->type;
  if (raw_aggregate(ir, result) || !abi_supported(ir, result)) { SSA_GIVE_UP(s); return 0; }
  bool sret = abi_memory(ctx, ir, result);
  const DynIrFunction *callee = NULL;
  unsigned fixed;
  bool packed = false;
  DynType pack_type = DYN_TYPE_VOID;
  int32_t target = -1;
  if (indirect) {
    if (e->integer >= ir->fn_type_count) { SSA_GIVE_UP(s); return 0; }
    const DynIrFnType *signature = &ir->fn_types[e->integer];
    if (signature->variadic || signature->param_count != e->item_count) { SSA_GIVE_UP(s); return 0; }
    fixed = signature->param_count;
    target = ssa_expr(s, e->left, NULL, depth + 1);
    ssa_check(s, target, ssa_const(s, 0, SC_INT), CC_NE, GUARD_FUNCTION);
  } else {
    if (e->integer >= ir->function_count) { SSA_GIVE_UP(s); return 0; }
    callee = &ir->functions[e->integer];
    if (callee->generic || callee->is_main || !ctx->function_symbols[e->integer] ||
        (!callee->variadic && callee->param_count != e->item_count) || callee->param_count > e->item_count ||
        (callee->variadic && callee->foreign)) { SSA_GIVE_UP(s); return 0; }
    fixed = callee->param_count;
    packed = callee->variadic;
    if (packed) {
      if (!dyn_type_is_slice(callee->variadic_type)) { SSA_GIVE_UP(s); return 0; }
      pack_type = ir->slices[callee->variadic_type - DYN_TYPE_SLICE_BASE].element;
    }
  }
  SsaArguments list = {0};
  unsigned gp = sret && !ctx->a64 ? 1 : 0, fp = 0;
  uint32_t stack = 0;
  int32_t result_address = -1;
  if (sret) {
    result_address = ssa_temporary(s, result);
    ssa_argument(s, &list, result_address, ctx->a64 ? SSA_RESULT_POINTER : 0, 0);
  }
  AbiPart parts[512];
  for (uint32_t i = 0; i < fixed + (packed ? 1u : 0u) && !s->unsupported && !s->failed; ++i) {
    DynType type = i < fixed ? (indirect ? ir->fn_type_params[ir->fn_types[e->integer].param_start + i]
                                         : ir->params[callee->param_start + i].type)
                             : callee->variadic_type;
    unsigned count; bool by_pointer;
    if (raw_aggregate(ir, type) || !abi_assign(ctx, ir, type, &gp, &fp, parts, &count, 512, &by_pointer)) {
      SSA_GIVE_UP(s); break;
    }
    /* AArch64 stack arguments differ by platform; they stay with the tree emitter. */
    int32_t value, length = -1;
    if (i < fixed) {
      DynExprId argument = ir->items[e->item_start + i].expression;
      value = ssa_expr(s, argument, &length, depth + 1);
    } else {
      /* The packed variadic slice: elements in a frame array; with `any`,
         each value boxed beside it. */
      unsigned extra = e->item_count - fixed;
      uint32_t element, a;
      if (!layout(ir, pack_type, &element, &a, 0)) { SSA_GIVE_UP(s); break; }
      int32_t array = extra ? ssa_frame(s, ssa_reserve(s, element * extra, a)) : ssa_const(s, 0, SC_INT);
      for (unsigned k = 0; k < extra && !s->unsupported; ++k) {
        DynExprId argument = ir->items[e->item_start + fixed + k].expression;
        DynType argument_type = ir->expressions[argument].type;
        if (pack_type == DYN_TYPE_ANY) {
          uint32_t size, alignment;
          if (!layout(ir, argument_type, &size, &alignment, 0)) { SSA_GIVE_UP(s); break; }
          int32_t box = ssa_frame(s, ssa_reserve(s, size ? size : 1, alignment));
          ssa_initialize(s, box, argument_type, argument, depth + 1);
          int32_t slot = ssa_add_offset(s, array, (int64_t)k * element);
          ssa_store(s, slot, -1, 1, 0, SSA_MEM(64, 0, 0), ssa_const(s, argument_type, SC_INT));
          ssa_store(s, slot, -1, 1, 8, SSA_MEM(64, 0, 0), box);
        } else ssa_initialize(s, ssa_add_offset(s, array, (int64_t)k * element), pack_type, argument, depth + 1);
      }
      value = array; length = ssa_const(s, extra, SC_INT);
    }
    if (by_pointer) {
      /* AAPCS64 composites over 16 bytes: a pointer to a caller-owned copy. */
      uint32_t size, alignment;
      if (!layout(ir, type, &size, &alignment, 0)) { SSA_GIVE_UP(s); break; }
      int32_t copy = ssa_temporary(s, type);
      ssa_emit(s, SO_COPYMEM, SC_NONE, copy, value, -1, size, 0);
      if (parts[0].cls >= 0) ssa_argument(s, &list, copy, parts[0].cls, 0);
      else ssa_argument(s, &list, copy, SSA_STACK + (int32_t)stack_slot(ctx, &parts[0], &stack), -8);
      continue;
    }
    ssa_pass(s, &list, type, value, length, parts, count, &stack);
  }
  if (s->unsupported || s->failed) { free(list.items); return 0; }
  if (indirect) ssa_argument(s, &list, target, SSA_TARGET, 0);
  int32_t call = ssa_emit(s, SO_CALL, SC_NONE, -1, -1, -1, indirect ? 0 : ctx->function_symbols[e->integer], indirect ? 2 : 0);
  if (!s->failed) {
    s->values[call].list = ssa_list(s, list.items, list.count);
    s->values[call].count = list.count / 3;
  }
  free(list.items);
  if (stack > s->outgoing) s->outgoing = stack;
  s->calls = true;
  if (ssa_cleanup(s) && !s->failed) {
    s->values[call].cond = 1;
    uint32_t normal = ssa_block(s);
    ssa_protect(s, normal);
  }
  if (result == DYN_TYPE_VOID) return 0;
  if (sret) return result_address;
  if (descriptor(result)) {
    int32_t data = ssa_emit(s, SO_RESULT, SC_INT, call, -1, -1, 0, 0);
    int32_t length = ssa_emit(s, SO_RESULT, SC_INT, call, -1, -1, 1, 0);
    if (second) *second = length;
    return data;
  }
  if (dyn_type_is_struct(result)) {
    SsaPart parts[4]; unsigned count;
    if (!ssa_struct_parts(s, result, parts, &count)) { SSA_GIVE_UP(s); return 0; }
    int32_t values[4];
    for (unsigned i = 0; i < count; ++i)
      values[i] = ssa_emit(s, SO_RESULT, parts[i].floating ? (parts[i].size == 4 ? SC_F32 : SC_F64) : SC_INT, call, -1, -1, parts[i].aux, 0);
    int32_t address = ssa_temporary(s, result);
    for (unsigned i = 0; i < count; ++i) {
      if (parts[i].floating) ssa_store(s, address, -1, 1, parts[i].offset, SSA_MEM(parts[i].size == 4 ? 32 : 64, 0, 1), values[i]);
      else ssa_store_bytes(s, address, parts[i].offset, parts[i].size, values[i]);
    }
    return address;
  }
  int32_t v = ssa_emit(s, SO_RESULT, ssa_class(result), call, -1, -1, float_type(result) ? X_XMM0 : 0, 0);
  return ssa_normalize(s, v, result);
}
static void ssa_initialize(Ssa *s, int32_t destination, DynType type, DynExprId id, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  if (s->unsupported || s->failed || depth > MAX_DEPTH) { SSA_GIVE_UP(s); return; }
  const DynIrExpr *value = id == DYN_NO_EXPR ? NULL : &ir->expressions[id];
  if (value_type(ir, type)) {
    int32_t v, second = -1;
    if (value) v = ssa_expr(s, id, &second, depth + 1);
    else { v = ssa_const(s, 0, ssa_class(type)); second = ssa_const(s, 0, SC_INT); }
    ssa_store_value(s, destination, type, v, second);
    return;
  }
  uint32_t size, alignment;
  if (!layout(ir, type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return; }
  if (value && s->ctx->literal_offsets[id]) {
    int32_t source = ssa_symbol(s, s->ctx->literals_symbol, SYM_LOCAL, s->ctx->literal_offsets[id] - 1);
    ssa_emit(s, SO_COPYMEM, SC_NONE, destination, source, -1, size, 1);
    return;
  }
  if (!value || value->kind == DYN_EXPR_ARRAY || value->kind == DYN_EXPR_STRUCT) {
    ssa_emit(s, SO_ZEROMEM, SC_NONE, destination, -1, -1, size, 0);
    if (value && value->kind == DYN_EXPR_ARRAY) {
      if (!dyn_type_is_array(type) || (uint64_t)value->item_start + value->item_count > ir->item_count) { SSA_GIVE_UP(s); return; }
      const DynIrArray *array = &ir->arrays[type - DYN_TYPE_ARRAY_BASE];
      uint32_t element, a;
      if (value->item_count > array->length || !layout(ir, array->element, &element, &a, 0)) { SSA_GIVE_UP(s); return; }
      for (uint32_t i = 0; i < value->item_count; ++i)
        ssa_initialize(s, ssa_add_offset(s, destination, (int64_t)i * element), array->element,
                       ir->items[value->item_start + i].expression, depth + 1);
    } else if (value) {
      if (!dyn_type_is_struct(type) || (uint64_t)value->item_start + value->item_count > ir->item_count) { SSA_GIVE_UP(s); return; }
      const DynIrStruct *record = &ir->structs[type - DYN_TYPE_STRUCT_BASE];
      for (uint32_t i = 0; i < record->field_count + value->item_count; ++i) {
        uint32_t field = i < record->field_count ? i : ir->items[value->item_start + i - record->field_count].field_index, offset;
        if (!field_offset(ir, type, field, &offset)) { SSA_GIVE_UP(s); return; }
        const DynIrField *definition = &ir->fields[record->field_start + field];
        DynExprId expr = i < record->field_count ? definition->default_expression
                                                 : ir->items[value->item_start + i - record->field_count].expression;
        if (expr == DYN_NO_EXPR) continue;
        ssa_initialize(s, ssa_add_offset(s, destination, offset), definition->type, expr, depth + 1);
      }
    }
    return;
  }
  int32_t source = ssa_expr(s, id, NULL, depth + 1);
  ssa_emit(s, SO_COPYMEM, SC_NONE, destination, source, -1, size, 0);
}

/* ---- Statements ---- */

static void ssa_statements(Ssa *s, uint32_t start, uint32_t count, unsigned depth);
static void ssa_return(Ssa *s, int32_t value, int32_t second) {
  if (s->current == UINT32_MAX) return;
  SsaBlock *b = &s->blocks[s->current];
  b->kind = SB_RETURN; b->control = value; b->control2 = second;
  s->current = UINT32_MAX;
}
/* Ends the block with a return of the function's result: registers per the
   System V classification, or a copy through the caller's result pointer. */
static void ssa_return_value(Ssa *s, int32_t value, int32_t second) {
  const DynIrProgram *ir = s->ir;
  DynType type = s->f->return_type;
  if (s->current == UINT32_MAX) return;
  if (s->f->is_main) { ssa_return(s, ssa_const(s, 0, SC_INT), -1); return; }
  if (type == DYN_TYPE_VOID || value_type(ir, type)) { ssa_return(s, value, second); return; }
  uint32_t size, alignment;
  if (!dyn_type_is_struct(type) || !layout(ir, type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return; }
  if (s->return_slot != UINT32_MAX) {
    int32_t pointer = ssa_load(s, ssa_frame(s, s->return_slot), -1, 1, 0, SSA_MEM(64, 0, 0));
    ssa_emit(s, SO_COPYMEM, SC_NONE, pointer, value, -1, size, 0);
    ssa_return(s, pointer, -1);
    return;
  }
  SsaPart layout_parts[4]; unsigned count;
  if (!ssa_struct_parts(s, type, layout_parts, &count)) { SSA_GIVE_UP(s); return; }
  int32_t parts[4] = {-1, -1, -1, -1};
  for (unsigned i = 0; i < count; ++i)
    parts[i] = layout_parts[i].floating
               ? ssa_load(s, value, -1, 1, layout_parts[i].offset, SSA_MEM(layout_parts[i].size == 4 ? 32 : 64, 0, 1))
               : ssa_load_bytes(s, value, layout_parts[i].offset, layout_parts[i].size);
  uint32_t block = s->current;
  ssa_return(s, parts[0], parts[1]);
  s->blocks[block].control3 = parts[2]; s->blocks[block].control4 = parts[3];
}
/* Evaluates a condition into a branch. */
static void ssa_condition(Ssa *s, DynExprId id, uint32_t yes, uint32_t no, unsigned depth) {
  const DynIrExpr *e = &s->ir->expressions[id];
  if (e->kind == DYN_EXPR_BINARY && (e->op == DYN_OP_LOGICAL_AND || e->op == DYN_OP_LOGICAL_OR)) {
    uint32_t middle = ssa_block(s);
    if (s->failed) return;
    if (e->op == DYN_OP_LOGICAL_AND) ssa_condition(s, e->left, middle, no, depth + 1);
    else ssa_condition(s, e->left, yes, middle, depth + 1);
    ssa_seal(s, middle);
    s->current = middle;
    ssa_condition(s, e->right, yes, no, depth + 1);
    return;
  }
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_NOT) { ssa_condition(s, e->left, no, yes, depth + 1); return; }
  int32_t v = ssa_expr(s, id, NULL, depth + 1);
  ssa_branch(s, v, yes, no);
}
static SsaLoop *ssa_target_loop(Ssa *s, uint32_t id) {
  for (unsigned i = s->loop_count; i > 0; --i) if (s->loops[i - 1].id == id) return &s->loops[i - 1];
  SSA_GIVE_UP(s);
  return NULL;
}
/* Assigns a scalar or descriptor value to a local, in a register or memory. */
static void ssa_set_local(Ssa *s, uint32_t local, int32_t value, int32_t second) {
  DynType type = s->ir->locals[s->f->local_start + local].type;
  if (ssa_in_memory(s, local)) { ssa_store_value(s, ssa_local_address(s, local), type, value, second); return; }
  ssa_write(s, 2 * local, value);
  if (descriptor(type)) ssa_write(s, 2 * local + 1, second);
}
static void ssa_assign(Ssa *s, const DynIrStmt *st) {
  const DynIrProgram *ir = s->ir;
  if (st->kind == DYN_STMT_ASSIGN && st->local_id == UINT32_MAX && st->target == DYN_NO_EXPR) {
    ssa_expr(s, st->expression, NULL, 0);
    return;
  }
  /* Locals declared or assigned whole. */
  if (st->kind == DYN_STMT_LOCAL || (st->kind == DYN_STMT_ASSIGN && st->target == DYN_NO_EXPR) ||
      (st->target < ir->expression_count && ir->expressions[st->target].kind == DYN_EXPR_NAME)) {
    uint64_t id = st->target != DYN_NO_EXPR && st->kind == DYN_STMT_ASSIGN ? ir->expressions[st->target].integer : st->local_id;
    uint32_t local;
    if (!ssa_local_index(s, id, &local)) return;
    DynType type = ir->locals[id].type;
    if (!value_type(ir, type)) {
      if (st->assignment_op != DYN_OP_NONE || !ssa_in_memory(s, local)) { SSA_GIVE_UP(s); return; }
      int32_t address = ssa_local_address(s, local);
      if (st->kind == DYN_STMT_ASSIGN) {
        uint32_t size, alignment;
        if (!layout(ir, type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return; }
        int32_t source = ssa_expr(s, st->expression, NULL, 0);
        ssa_emit(s, SO_COPYMEM, SC_NONE, address, source, -1, size, 0);
      } else ssa_initialize(s, address, type, st->expression, 0);
      return;
    }
    int32_t value, second = -1;
    if (st->assignment_op != DYN_OP_NONE) {
      if (st->target == DYN_NO_EXPR || descriptor(type)) { SSA_GIVE_UP(s); return; }
      DynIrExpr operation = {.kind = DYN_EXPR_BINARY, .type = type, .op = st->assignment_op,
                             .left = st->target, .right = st->expression, .wrap = false};
      int32_t left = ssa_expr(s, st->target, NULL, 0);
      int32_t right = ssa_expr(s, st->expression, NULL, 0);
      value = ssa_binary(s, &operation, left, right);
    } else if (st->expression == DYN_NO_EXPR && st->kind == DYN_STMT_LOCAL) {
      value = ssa_const(s, 0, ssa_class(type)); second = ssa_const(s, 0, SC_INT);
    } else value = ssa_expr(s, st->expression, &second, 0);
    ssa_set_local(s, local, value, second);
    return;
  }
  if (st->target >= ir->expression_count) { SSA_GIVE_UP(s); return; }
  const DynIrExpr *target = &ir->expressions[st->target];
  DynType type = target->type;
  if (!value_type(ir, type)) {
    if (st->assignment_op != DYN_OP_NONE) { SSA_GIVE_UP(s); return; }
    uint32_t size, alignment;
    if (!layout(ir, type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return; }
    int32_t address = ssa_address(s, st->target, 0);
    int32_t source = ssa_expr(s, st->expression, NULL, 0);
    ssa_emit(s, SO_COPYMEM, SC_NONE, address, source, -1, size, 0);
    return;
  }
  if (target->kind == DYN_EXPR_GLOBAL && (target->integer >= ir->global_count || ir->globals[target->integer].is_const)) {
    SSA_GIVE_UP(s); return;
  }
  /* Memory targets: the address first, then (compound) its old value, then
     the right side. Globals evaluate the right side before their address. */
  if (target->kind == DYN_EXPR_GLOBAL) {
    int32_t value, second = -1;
    if (st->assignment_op != DYN_OP_NONE) {
      if (descriptor(type)) { SSA_GIVE_UP(s); return; }
      DynIrExpr operation = {.kind = DYN_EXPR_BINARY, .type = type, .op = st->assignment_op,
                             .left = st->target, .right = st->expression};
      int32_t left = ssa_expr(s, st->target, NULL, 0);
      int32_t right = ssa_expr(s, st->expression, NULL, 0);
      value = ssa_binary(s, &operation, left, right);
    } else value = ssa_expr(s, st->expression, &second, 0);
    int32_t address = ssa_symbol(s, s->ctx->global_symbols[target->integer], SYM_GLOBAL, 0);
    ssa_store_value(s, address, type, value, second);
    return;
  }
  if (target->kind != DYN_EXPR_INDEX && target->kind != DYN_EXPR_FIELD &&
      !(target->kind == DYN_EXPR_UNARY && target->op == DYN_OP_DEREF)) { SSA_GIVE_UP(s); return; }
  if (!scalar(ir, type) && st->assignment_op != DYN_OP_NONE) { SSA_GIVE_UP(s); return; }
  int32_t address = ssa_address(s, st->target, 0), value, second = -1;
  if (st->assignment_op != DYN_OP_NONE) {
    int32_t old = ssa_load_value(s, address, type, NULL);
    int32_t right = ssa_expr(s, st->expression, NULL, 0);
    DynIrExpr operation = {.kind = DYN_EXPR_BINARY, .type = type, .op = st->assignment_op,
                           .left = st->target, .right = st->expression};
    value = ssa_binary(s, &operation, old, right);
  } else value = ssa_expr(s, st->expression, &second, 0);
  ssa_store_value(s, address, type, value, second);
}
/* Whether statements may write memory a by-value loop snapshot would
   protect: any call, or an assignment to anything but a register local. */
static bool ssa_expression_calls(const DynIrProgram *ir, DynExprId id, unsigned depth) {
  if (id == DYN_NO_EXPR || id >= ir->expression_count || depth > MAX_DEPTH) return id != DYN_NO_EXPR;
  const DynIrExpr *e = &ir->expressions[id];
  if (e->kind == DYN_EXPR_CALL || e->kind == DYN_EXPR_INDIRECT_CALL || e->kind == DYN_EXPR_SYSCALL) return true;
  if (e->kind == DYN_EXPR_INT || e->kind == DYN_EXPR_BOOL || e->kind == DYN_EXPR_CHAR || e->kind == DYN_EXPR_FLOAT ||
      e->kind == DYN_EXPR_NAME || e->kind == DYN_EXPR_GLOBAL || e->kind == DYN_EXPR_STRING || e->kind == DYN_EXPR_NIL ||
      e->kind == DYN_EXPR_FUNCTION) return false;
  if (ssa_expression_calls(ir, e->left, depth + 1) || ssa_expression_calls(ir, e->right, depth + 1)) return true;
  if (e->kind == DYN_EXPR_SLICE && ssa_expression_calls(ir, (DynExprId)e->integer, depth + 1)) return true;
  if ((uint64_t)e->item_start + e->item_count > ir->item_count) return true;
  for (uint32_t i = 0; i < e->item_count; ++i)
    if (ssa_expression_calls(ir, ir->items[e->item_start + i].expression, depth + 1)) return true;
  return false;
}
static bool ssa_writes_memory(Ssa *s, uint32_t start, uint32_t count, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  if (depth > MAX_DEPTH || (uint64_t)start + count > ir->child_count) return true;
  for (uint32_t i = 0; i < count; ++i) {
    const DynIrStmt *st = &ir->statements[ir->children[start + i]];
    if (ssa_expression_calls(ir, st->expression, 0) || ssa_expression_calls(ir, st->target, 0)) return true;
    if (st->kind == DYN_STMT_ASSIGN || st->kind == DYN_STMT_LOCAL) {
      uint64_t id = st->local_id;
      if (st->kind == DYN_STMT_ASSIGN && st->target != DYN_NO_EXPR) {
        const DynIrExpr *target = &ir->expressions[st->target];
        if (target->kind != DYN_EXPR_NAME) return true;
        id = target->integer;
      }
      uint32_t local;
      if (id != UINT32_MAX && (!ssa_local_index(s, id, &local) || ssa_in_memory(s, local))) {
        if (st->kind == DYN_STMT_ASSIGN) return true;
      }
    }
    if (st->kind == DYN_STMT_DEFER || st->kind == DYN_STMT_CASE) return true;
    if (ssa_writes_memory(s, st->body_start, st->body_count, depth + 1) ||
        ssa_writes_memory(s, st->else_start, st->else_count, depth + 1)) return true;
  }
  return false;
}
/* The O3 elementwise loop of vector.inc: `for i in 0..N { d[i] = l[i] op r[i] }`
   over local arrays of 32- or 64-bit integers, with a wrapping or bitwise
   operation. Whole 16-byte lanes run as SIMD; the tail stays scalar. */
static bool ssa_vector_array(Ssa *s, DynExprId id, uint32_t index, uint32_t *local, DynType *type, uint64_t *length) {
  const DynIrProgram *ir = s->ir;
  if (id >= ir->expression_count) return false;
  const DynIrExpr *e = &ir->expressions[id];
  if (e->kind != DYN_EXPR_INDEX || e->left >= ir->expression_count || e->right >= ir->expression_count) return false;
  const DynIrExpr *base = &ir->expressions[e->left], *at = &ir->expressions[e->right];
  if (base->kind != DYN_EXPR_NAME || !dyn_type_is_array(base->type) || at->kind != DYN_EXPR_NAME || at->integer != index ||
      base->integer < s->f->local_start || base->integer - s->f->local_start >= s->f->local_count ||
      base->type - DYN_TYPE_ARRAY_BASE >= ir->array_count) return false;
  const DynIrArray *a = &ir->arrays[base->type - DYN_TYPE_ARRAY_BASE];
  if (a->element != DYN_TYPE_U32 && a->element != DYN_TYPE_I32 && a->element != DYN_TYPE_U64 && a->element != DYN_TYPE_I64) return false;
  *local = (uint32_t)(base->integer - s->f->local_start); *type = a->element; *length = a->length;
  return s->memory_local[*local] && s->alias[*local] < 0;
}
static bool ssa_vector(Ssa *s, const DynIrStmt *st) {
  const DynIrProgram *ir = s->ir;
  if (!s->ctx->vectorize || !st->for_range || st->for_reverse || st->for_inclusive || st->for_pointer ||
      st->body_count != 1 || st->body_start >= ir->child_count || st->target >= ir->expression_count ||
      st->expression >= ir->expression_count) return false;
  const DynIrExpr *start = &ir->expressions[st->target], *stop = &ir->expressions[st->expression];
  if (start->kind != DYN_EXPR_INT || start->integer != 0 || stop->kind != DYN_EXPR_INT || stop->integer > UINT32_MAX) return false;
  uint32_t sid = ir->children[st->body_start];
  if (sid >= ir->statement_count) return false;
  const DynIrStmt *assign = &ir->statements[sid];
  if (assign->kind != DYN_STMT_ASSIGN || assign->assignment_op != DYN_OP_NONE || assign->expression >= ir->expression_count) return false;
  const DynIrExpr *op = &ir->expressions[assign->expression];
  if (op->kind != DYN_EXPR_BINARY ||
      !((op->wrap && (op->op == DYN_OP_ADD || op->op == DYN_OP_SUB)) ||
        op->op == DYN_OP_BIT_AND || op->op == DYN_OP_BIT_OR || op->op == DYN_OP_BIT_XOR)) return false;
  uint32_t dest, left, right; DynType type, lt, rt; uint64_t dn, ln, rn;
  if (!ssa_vector_array(s, assign->target, st->local_id, &dest, &type, &dn) ||
      !ssa_vector_array(s, op->left, st->local_id, &left, &lt, &ln) ||
      !ssa_vector_array(s, op->right, st->local_id, &right, &rt, &rn) ||
      type != lt || type != rt || op->type != type) return false;
  unsigned bytes = type == DYN_TYPE_U64 || type == DYN_TYPE_I64 ? 8 : 4, lanes = 16 / bytes;
  uint64_t n = stop->integer;
  if (n < lanes || n > dn || n > ln || n > rn) return false;
  ssa_emit(s, SO_VECTOR, SC_NONE, ssa_frame(s, s->local_offset[dest]), ssa_frame(s, s->local_offset[left]),
           ssa_frame(s, s->local_offset[right]), (int64_t)(n / lanes * lanes), op->op | bytes << 8);
  for (uint64_t i = n / lanes * lanes; i < n; ++i) {
    int64_t memory = ssa_memory_type(ir, type);
    int32_t a = ssa_load(s, ssa_frame(s, s->local_offset[left]), -1, 1, (int64_t)i * bytes, memory);
    int32_t b = ssa_load(s, ssa_frame(s, s->local_offset[right]), -1, 1, (int64_t)i * bytes, memory);
    ssa_store(s, ssa_frame(s, s->local_offset[dest]), -1, 1, (int64_t)i * bytes, memory, ssa_binary(s, op, a, b));
  }
  ++s->vectorized;
  if (s->ctx->optimization_remarks)
    fprintf(stderr, "remark: %s: vectorized %llu integer elements (%u lanes, scalar tail %llu)\n",
            s->f->name, (unsigned long long)n, lanes, (unsigned long long)(n % lanes));
  return true;
}
/* The value a case pattern matches, as the subject compares it. */
static bool ssa_pattern_range(Ssa *s, const DynIrPattern *p, DynType type, bool any, uint64_t *first, uint64_t *last) {
  const DynIrProgram *ir = s->ir;
  *first = p->first; *last = p->last;
  if (p->is_enum) {
    if (!dyn_type_is_enum(type) || p->variant >= ir->variant_count) return false;
    *first = *last = ir->variants[p->variant].tag;
    unsigned bits = integer_bits(storage_type(ir, type));
    if (signed_scalar(storage_type(ir, type)) && bits < 64 && (*first >> (bits - 1) & 1)) *first = *last = *first | (UINT64_MAX << bits);
  } else if (p->is_type) { if (!any) return false; *first = *last = p->type; }
  return true;
}
/* An arm's binding and statements, then the jump past the case. */
static void ssa_case_body(Ssa *s, const DynIrCaseArm *arm, int32_t pointer, uint32_t done, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  if (arm->local_id != UINT32_MAX) {
    uint32_t binding;
    if (!arm->pattern_count || !ssa_local_index(s, arm->local_id, &binding)) { SSA_GIVE_UP(s); return; }
    const DynIrPattern *pattern = &ir->patterns[arm->pattern_start];
    if (!pattern->is_type && !pattern->is_enum) { SSA_GIVE_UP(s); return; }
    DynType bound = ir->locals[arm->local_id].type;
    if (arm->pointer_binding) s->alias[binding] = pointer;
    else if (value_type(ir, bound)) {
      int32_t second = -1, value = ssa_load_value(s, pointer, bound, &second);
      ssa_set_local(s, binding, value, second);
    } else {
      if (!ssa_in_memory(s, binding)) { SSA_GIVE_UP(s); return; }
      ssa_store_value(s, ssa_local_address(s, binding), bound, pointer, -1);
    }
  }
  ssa_statements(s, arm->body_start, arm->body_count, depth + 1);
  if (arm->local_id != UINT32_MAX && arm->pointer_binding) s->alias[arm->local_id - s->f->local_start] = -1;
  ssa_jump(s, done);
}
/* Dense single-value cases dispatch through a jump table: at least four
   values spanning at most four slots per value. Earlier arms win, as in the
   compare chain. Returns false when the case does not qualify. */
static bool ssa_case_table(Ssa *s, const DynIrStmt *st, DynType type, bool any, int32_t subject, int32_t pointer,
                           uint32_t done, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  uint32_t values = 0, wildcard = UINT32_MAX;
  int64_t minimum = INT64_MAX, maximum = INT64_MIN;
  for (uint32_t i = 0; i < st->case_arm_count && wildcard == UINT32_MAX; ++i) {
    const DynIrCaseArm *arm = &ir->case_arms[st->case_arm_start + i];
    if (arm->wildcard) { if (arm->pattern_count) return false; wildcard = i; break; }
    for (uint32_t j = 0; j < arm->pattern_count; ++j) {
      uint64_t first, last;
      if (!ssa_pattern_range(s, &ir->patterns[arm->pattern_start + j], type, any, &first, &last) || first != last) return false;
      if ((int64_t)first < minimum) minimum = (int64_t)first;
      if ((int64_t)first > maximum) maximum = (int64_t)first;
      ++values;
    }
  }
  if (values < 4 || (uint64_t)maximum - (uint64_t)minimum >= 4096 || (uint64_t)maximum - (uint64_t)minimum + 1 > 4 * (uint64_t)values) return false;
  uint32_t entries = (uint32_t)((uint64_t)maximum - (uint64_t)minimum + 1);
  uint32_t *bodies = malloc((st->case_arm_count + 1) * sizeof(uint32_t)), *targets = malloc(entries * sizeof(uint32_t));
  if (!bodies || !targets) { free(bodies); free(targets); s->failed = true; return true; }
  for (uint32_t i = 0; i < st->case_arm_count; ++i) bodies[i] = ssa_block(s);
  uint32_t fallback = wildcard != UINT32_MAX ? bodies[wildcard] : ssa_block(s);
  for (uint32_t k = 0; k < entries; ++k) targets[k] = fallback;
  uint32_t last_arm = wildcard != UINT32_MAX ? wildcard : st->case_arm_count;
  for (uint32_t i = last_arm; i-- > 0;) {
    const DynIrCaseArm *arm = &ir->case_arms[st->case_arm_start + i];
    for (uint32_t j = arm->pattern_count; j-- > 0;) {
      uint64_t first, last;
      ssa_pattern_range(s, &ir->patterns[arm->pattern_start + j], type, any, &first, &last);
      targets[first - (uint64_t)minimum] = bodies[i];
    }
  }
  int32_t *items = malloc((3 + entries) * sizeof(int32_t));
  if (!items) { free(bodies); free(targets); s->failed = true; return true; }
  items[0] = (int32_t)(uint32_t)(uint64_t)minimum; items[1] = (int32_t)entries; items[2] = (int32_t)fallback;
  for (uint32_t k = 0; k < entries; ++k) items[3 + k] = (int32_t)targets[k];
  uint32_t from = s->current;
  SsaBlock *b = &s->blocks[from];
  b->kind = SB_SWITCH; b->control = subject;
  b->table = ssa_list(s, items, 3 + entries) ;
  /* lists[table]: low half of the minimum, then [table+1] entries; keep the
     full 64-bit minimum in aux of a constant control offset. */
  b->control2 = ssa_value(s, from, SO_CONST, SC_INT, -1, -1, -1, minimum, 0);
  free(items);
  /* One predecessor edge per distinct target. */
  for (uint32_t i = 0; i <= st->case_arm_count; ++i) {
    uint32_t target = i < st->case_arm_count ? bodies[i] : fallback;
    if (i == st->case_arm_count && wildcard != UINT32_MAX) break;
    bool used = target == fallback;
    for (uint32_t k = 0; k < entries && !used; ++k) used = targets[k] == target;
    if (used) ssa_push(s, &s->blocks[target].preds, from);
  }
  s->current = UINT32_MAX;
  for (uint32_t i = 0; i < st->case_arm_count && !s->unsupported; ++i) {
    ssa_seal(s, bodies[i]);
    if (!s->blocks[bodies[i]].preds.count) continue;
    s->current = bodies[i];
    ssa_case_body(s, &ir->case_arms[st->case_arm_start + i], pointer, done, depth);
  }
  if (wildcard == UINT32_MAX) {
    ssa_seal(s, fallback);
    s->current = fallback;
    ssa_emit(s, SO_TRAP, SC_NONE, -1, -1, -1, 0, 0);
    s->blocks[fallback].kind = SB_EXIT;
  }
  s->current = UINT32_MAX;
  free(bodies); free(targets);
  ssa_seal(s, done);
  s->current = s->blocks[done].preds.count ? done : UINT32_MAX;
  return true;
}
/* case: arms test their patterns in order; each pattern is a value or an
   inclusive range, compared signed or unsigned like the subject. Payload
   enums match on a snapshot of the value unless an arm binds a pointer. */
static void ssa_case(Ssa *s, const DynIrStmt *st, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  if (st->expression >= ir->expression_count) { SSA_GIVE_UP(s); return; }
  DynType type = ir->expressions[st->expression].type;
  bool payload = payload_enum(ir, type), any = type == DYN_TYPE_ANY, reference = false;
  if (!payload && !any && !scalar(ir, type)) { SSA_GIVE_UP(s); return; }
  if ((uint64_t)st->case_arm_start + st->case_arm_count > ir->case_arm_count) { SSA_GIVE_UP(s); return; }
  for (uint32_t i = 0; i < st->case_arm_count; ++i) if (ir->case_arms[st->case_arm_start + i].pointer_binding) reference = true;
  if (reference && !payload) { SSA_GIVE_UP(s); return; }
  uint32_t payload_offset = 0;
  int32_t subject, data = -1;
  if (payload) {
    const DynIrEnum *en = &ir->enums[type - DYN_TYPE_ENUM_BASE];
    uint32_t tag_size = (memory_bits(en->tag_type) + 7) / 8, a = (uint32_t)en->payload_alignment;
    payload_offset = (tag_size + a - 1) & ~(a - 1);
    if (reference) data = ssa_address(s, st->expression, 0);
    else {
      uint32_t size, alignment;
      if (!layout(ir, type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return; }
      int32_t value = ssa_expr(s, st->expression, NULL, 0);
      data = ssa_temporary(s, type);
      ssa_emit(s, SO_COPYMEM, SC_NONE, data, value, -1, size, 0);
    }
    subject = ssa_normalize(s, ssa_load(s, data, -1, 1, 0, ssa_memory_type(ir, type)), storage_type(ir, type));
  } else subject = ssa_expr(s, st->expression, any ? &data : NULL, 0);
  bool sign = signed_scalar(storage_type(ir, type));
  uint32_t done = ssa_block(s);
  if (s->failed) return;
  if (ssa_case_table(s, st, type, any, subject, payload ? ssa_add_offset(s, data, payload_offset) : data, done, depth)) return;
  for (uint32_t i = 0; i < st->case_arm_count && !s->unsupported && s->current != UINT32_MAX; ++i) {
    const DynIrCaseArm *arm = &ir->case_arms[st->case_arm_start + i];
    if ((uint64_t)arm->pattern_start + arm->pattern_count > ir->pattern_count) { SSA_GIVE_UP(s); return; }
    uint32_t body = ssa_block(s), next = ssa_block(s);
    if (s->failed) return;
    for (uint32_t j = 0; j < arm->pattern_count; ++j) {
      uint64_t first, last;
      if (!ssa_pattern_range(s, &ir->patterns[arm->pattern_start + j], type, any, &first, &last)) { SSA_GIVE_UP(s); return; }
      uint32_t miss = ssa_block(s);
      if (s->failed) return;
      if (first == last) ssa_branch(s, ssa_compare(s, subject, ssa_const(s, first, SC_INT), CC_E), body, miss);
      else {
        uint32_t upper = ssa_block(s);
        if (s->failed) return;
        ssa_branch(s, ssa_compare(s, subject, ssa_const(s, first, SC_INT), sign ? CC_L : CC_B), miss, upper);
        ssa_seal(s, upper);
        s->current = upper;
        ssa_branch(s, ssa_compare(s, subject, ssa_const(s, last, SC_INT), sign ? CC_LE : CC_BE), body, miss);
      }
      ssa_seal(s, miss);
      s->current = miss;
    }
    ssa_jump(s, arm->wildcard ? body : next);
    ssa_seal(s, body);
    s->current = body;
    ssa_case_body(s, arm, payload ? ssa_add_offset(s, data, payload_offset) : data, done, depth);
    ssa_seal(s, next);
    s->current = s->blocks[next].preds.count ? next : UINT32_MAX;
  }
  if (s->current != UINT32_MAX) {
    ssa_emit(s, SO_TRAP, SC_NONE, -1, -1, -1, 0, 0);
    s->blocks[s->current].kind = SB_EXIT;
    s->current = UINT32_MAX;
  }
  ssa_seal(s, done);
  s->current = s->blocks[done].preds.count ? done : UINT32_MAX;
}
/* Runs pending defers innermost first, down to `base`, as cleanup code.
   The defer stack itself stays as it was. */
static void ssa_run_defers(Ssa *s, unsigned base) {
  const DynIrProgram *ir = s->ir;
  bool unwinding = s->unwinding;
  unsigned saved = s->defer_count;
  s->unwinding = true;
  for (unsigned i = saved; i > base && s->current != UINT32_MAX && !s->unsupported; --i) {
    const DynIrStmt *st = &ir->statements[s->defers[i - 1]];
    s->defer_count = i - 1;
    ssa_statements(s, st->body_start, st->body_count, 1);
  }
  s->defer_count = saved;
  s->unwinding = unwinding;
}
static void ssa_capture(Ssa *s, DynExprId id, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  DynType type = ir->expressions[id].type;
  int32_t second = -1, value = ssa_expr(s, id, &second, depth);
  if (aggregate(ir, type)) {
    uint32_t size, alignment;
    if (!layout(ir, type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return; }
    int32_t copy = ssa_temporary(s, type);
    ssa_emit(s, SO_COPYMEM, SC_NONE, copy, value, -1, size, 0);
    value = copy;
  }
  s->captures = ssa_grow(s->captures, &s->capture_capacity, s->capture_count + 1, sizeof(SsaCapture), &s->failed);
  if (s->failed) return;
  uint32_t variable = s->variable_count + s->hidden_variables;
  s->hidden_variables += 2;
  s->captures[s->capture_count++] = (SsaCapture){id, variable};
  ssa_write(s, variable, value);
  if (descriptor(type)) ssa_write(s, variable + 1, second);
}
/* A deferred single call evaluates its callee and arguments now. */
static void ssa_defer(Ssa *s, const DynIrStmt *st, uint32_t id) {
  const DynIrProgram *ir = s->ir;
  if (s->unwinding || s->defer_count == MAX_DEFERS) { SSA_GIVE_UP(s); return; }
  if (!st->defer_block && st->body_count == 1) {
    const DynIrStmt *action = &ir->statements[ir->children[st->body_start]];
    if (action->kind == DYN_STMT_EXPR && action->expression < ir->expression_count) {
      const DynIrExpr *call = &ir->expressions[action->expression];
      if (call->kind == DYN_EXPR_CALL || call->kind == DYN_EXPR_INDIRECT_CALL) {
        if (call->kind == DYN_EXPR_INDIRECT_CALL) ssa_capture(s, call->left, 0);
        if ((uint64_t)call->item_start + call->item_count > ir->item_count) { SSA_GIVE_UP(s); return; }
        for (uint32_t j = 0; j < call->item_count; ++j) ssa_capture(s, ir->items[call->item_start + j].expression, 0);
      }
    }
  }
  s->defers[s->defer_count++] = id;
}
/* Ends the block at a protected call: the normal path continues in a new
   block; an unwinding panic lands in a block that runs the defers and keeps
   unwinding. */
static void ssa_protect(Ssa *s, uint32_t normal) {
  if (s->current == UINT32_MAX) return;
  uint32_t landing = ssa_block(s);
  if (s->failed) return;
  if (!s->unwind_offset) {
    s->unwind_offset = ssa_reserve(s, unwind_words(s->ctx) * 8, 16);
    s->results_offset = ssa_reserve(s, 64, 16); /* result registers kept across dyn_unwind_unlink */
  }
  SsaBlock *b = &s->blocks[s->current];
  b->kind = SB_CALL;
  ssa_edge(s, s->current, normal);
  ssa_edge(s, s->current, landing);
  ssa_seal(s, normal); ssa_seal(s, landing);
  s->current = landing;
  ssa_run_defers(s, 0);
  if (s->current != UINT32_MAX) {
    ssa_emit(s, SO_CONTINUE, SC_NONE, -1, -1, -1, 0, 0);
    s->blocks[s->current].kind = SB_EXIT;
  }
  s->current = normal;
}
static void ssa_loop_body(Ssa *s, const DynIrStmt *st, uint32_t latch, uint32_t exit, unsigned depth) {
  if (s->loop_count == MAX_DEPTH) { SSA_GIVE_UP(s); return; }
  s->loops[s->loop_count++] = (SsaLoop){st->loop_id, exit, latch, depth, s->defer_count};
  ssa_statements(s, st->body_start, st->body_count, depth + 1);
  --s->loop_count;
  ssa_jump(s, latch);
}
static void ssa_statement(Ssa *s, const DynIrStmt *st, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  switch (st->kind) {
  case DYN_STMT_LOCAL: case DYN_STMT_ASSIGN:
    ssa_assign(s, st);
    return;
  case DYN_STMT_EXPR:
    ssa_expr(s, st->expression, NULL, 0);
    return;
  case DYN_STMT_RETURN: {
    int32_t value = -1, second = -1;
    if (st->expression != DYN_NO_EXPR) value = ssa_expr(s, st->expression, &second, 0);
    else if (s->f->return_type != DYN_TYPE_VOID) { SSA_GIVE_UP(s); return; }
    if (s->defer_count) {
      /* Defers may change what an aggregate result refers to; return a copy. */
      if (value >= 0 && aggregate(ir, s->f->return_type) && !s->f->is_main) {
        uint32_t size, alignment;
        if (!layout(ir, s->f->return_type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return; }
        int32_t copy = ssa_temporary(s, s->f->return_type);
        ssa_emit(s, SO_COPYMEM, SC_NONE, copy, value, -1, size, 0);
        value = copy;
      }
      ssa_run_defers(s, 0);
    }
    ssa_return_value(s, value, second);
    return;
  }
  case DYN_STMT_PANIC: {
    if (st->expression >= ir->expression_count || !descriptor(ir->expressions[st->expression].type)) break;
    int32_t length = -1, data = ssa_expr(s, st->expression, &length, 0);
    int32_t panic = ssa_emit(s, SO_PANIC, SC_NONE, data, length, -1, 0, 0);
    s->calls = true;
    if (ssa_cleanup(s)) {
      /* The panic unwinds into this frame, which runs its defers. */
      s->values[panic].cond = 1;
      uint32_t never = ssa_block(s);
      ssa_protect(s, never);
      if (s->current != UINT32_MAX) { ssa_emit(s, SO_TRAP, SC_NONE, -1, -1, -1, 0, 0); s->blocks[s->current].kind = SB_EXIT; }
      s->current = UINT32_MAX;
      return;
    }
    if (s->current != UINT32_MAX) s->blocks[s->current].kind = SB_EXIT;
    s->current = UINT32_MAX;
    return;
  }
  case DYN_STMT_IF: {
    if (st->expression < ir->expression_count && ir->expressions[st->expression].kind == DYN_EXPR_BOOL) {
      bool chosen = ir->expressions[st->expression].boolean;
      ssa_statements(s, chosen ? st->body_start : st->else_start, chosen ? st->body_count : st->else_count, depth + 1);
      return;
    }
    uint32_t yes = ssa_block(s), no = ssa_block(s), join = ssa_block(s);
    if (s->failed) return;
    ssa_condition(s, st->expression, yes, no, 0);
    ssa_seal(s, yes); ssa_seal(s, no);
    s->current = yes;
    ssa_statements(s, st->body_start, st->body_count, depth + 1);
    ssa_jump(s, join);
    s->current = no;
    ssa_statements(s, st->else_start, st->else_count, depth + 1);
    ssa_jump(s, join);
    ssa_seal(s, join);
    s->current = s->blocks[join].preds.count ? join : UINT32_MAX;
    return;
  }
  case DYN_STMT_FOR: {
    if (ssa_vector(s, st)) return;
    uint32_t counter = s->variable_count + s->hidden_variables++;
    ++s->loop_depth;
    uint32_t header = ssa_block(s), body = ssa_block(s), latch = ssa_block(s), exit = ssa_block(s);
    --s->loop_depth;
    if (s->failed) return;
    s->blocks[exit].loop_depth = s->loop_depth;
    if (st->for_range) {
      if (st->for_pointer) break;
      uint32_t binding;
      if (!ssa_local_index(s, st->local_id, &binding)) return;
      DynType type = ir->expressions[st->target].type;
      bool sign = signed_scalar(storage_type(ir, type));
      int32_t first = ssa_expr(s, st->target, NULL, 0);
      int32_t last = ssa_expr(s, st->expression, NULL, 0);
      int32_t stop = st->for_reverse ? first : last;
      ssa_write(s, counter, st->for_reverse ? last : first);
      ssa_jump(s, header);
      ++s->loop_depth;
      s->current = header;
      int32_t at = ssa_read(s, counter, header, SC_INT);
      Cond exit_when = st->for_reverse ? (st->for_inclusive ? (sign ? CC_L : CC_B) : (sign ? CC_LE : CC_BE))
                                       : (st->for_inclusive ? (sign ? CC_G : CC_A) : (sign ? CC_GE : CC_AE));
      ssa_branch(s, ssa_compare(s, at, stop, exit_when), exit, body);
      ssa_seal(s, body);
      s->current = body;
      int32_t value = at;
      if (st->for_reverse && !st->for_inclusive) value = ssa_emit(s, SO_ADD, SC_INT, at, ssa_const(s, UINT64_MAX, SC_INT), -1, 0, 0);
      ssa_set_local(s, binding, value, -1);
      ssa_loop_body(s, st, latch, exit, depth);
      ssa_seal(s, latch);
      s->current = s->blocks[latch].preds.count ? latch : UINT32_MAX;
      if (s->current != UINT32_MAX) {
        int32_t now = ssa_read(s, counter, latch, SC_INT);
        if (st->for_inclusive) {
          uint32_t step = ssa_block(s);
          ssa_branch(s, ssa_compare(s, now, stop, CC_E), exit, step);
          ssa_seal(s, step);
          s->current = step;
        }
        /* aux2 marks a counter step that cannot wrap: 1 signed, 2 unsigned. */
        ssa_write(s, counter, ssa_emit(s, SO_ADD, SC_INT, now, ssa_const(s, st->for_reverse ? UINT64_MAX : 1, SC_INT), -1, 0,
                                       st->for_reverse ? 0 : sign ? 1 : 2));
        ssa_jump(s, header);
      }
    } else if (st->target != DYN_NO_EXPR) {
      DynType collection = ir->expressions[st->target].type, element;
      bool array = dyn_type_is_array(collection);
      if (array) element = ir->arrays[collection - DYN_TYPE_ARRAY_BASE].element;
      else if (dyn_type_is_slice(collection)) element = ir->slices[collection - DYN_TYPE_SLICE_BASE].element;
      else if (collection == DYN_TYPE_STRING) element = DYN_TYPE_U8;
      else break;
      uint32_t size, alignment, binding;
      if (!layout(ir, element, &size, &alignment, 0) || !ssa_local_index(s, st->local_id, &binding)) return;
      int32_t data, length = -1;
      if (array) {
        const DynExprKind kind = ir->expressions[st->target].kind;
        bool lvalue = kind == DYN_EXPR_NAME || kind == DYN_EXPR_GLOBAL || kind == DYN_EXPR_FIELD ||
                      kind == DYN_EXPR_INDEX || (kind == DYN_EXPR_UNARY && ir->expressions[st->target].op == DYN_OP_DEREF);
        data = st->for_pointer ? ssa_address(s, st->target, 0) : ssa_expr(s, st->target, NULL, 0);
        if (!st->for_pointer && lvalue && ssa_writes_memory(s, st->body_start, st->body_count, 0)) {
          /* The loop iterates a copy taken before the body runs. */
          uint32_t bytes, a;
          if (!layout(ir, collection, &bytes, &a, 0)) { SSA_GIVE_UP(s); return; }
          int32_t copy = ssa_temporary(s, collection);
          ssa_emit(s, SO_COPYMEM, SC_NONE, copy, data, -1, bytes, 0);
          data = copy;
        }
        length = ssa_const(s, ir->arrays[collection - DYN_TYPE_ARRAY_BASE].length, SC_INT);
      } else data = ssa_expr(s, st->target, &length, 0);
      ssa_write(s, counter, st->for_reverse ? length : ssa_const(s, 0, SC_INT));
      ssa_jump(s, header);
      ++s->loop_depth;
      s->current = header;
      int32_t at = ssa_read(s, counter, header, SC_INT);
      if (st->for_reverse) ssa_branch(s, ssa_compare(s, at, ssa_const(s, 0, SC_INT), CC_E), exit, body);
      else ssa_branch(s, ssa_compare(s, at, length, CC_AE), exit, body);
      ssa_seal(s, body);
      s->current = body;
      int32_t index = st->for_reverse ? ssa_emit(s, SO_ADD, SC_INT, at, ssa_const(s, UINT64_MAX, SC_INT), -1, 0, 0) : at;
      int32_t address = ssa_element(s, data, index, size);
      if (st->for_pointer) ssa_set_local(s, binding, address, -1);
      else if (scalar(ir, element)) ssa_set_local(s, binding, ssa_load_value(s, address, element, NULL), -1);
      else if (descriptor(element)) {
        int32_t second = -1, first = ssa_load_value(s, address, element, &second);
        ssa_set_local(s, binding, first, second);
      } else {
        if (!s->memory_local[binding]) { SSA_GIVE_UP(s); return; }
        ssa_store_value(s, ssa_frame(s, s->local_offset[binding]), element, address, -1);
      }
      ssa_loop_body(s, st, latch, exit, depth);
      ssa_seal(s, latch);
      s->current = s->blocks[latch].preds.count ? latch : UINT32_MAX;
      if (s->current != UINT32_MAX) {
        int32_t now = ssa_read(s, counter, latch, SC_INT);
        ssa_write(s, counter, ssa_emit(s, SO_ADD, SC_INT, now, ssa_const(s, st->for_reverse ? UINT64_MAX : 1, SC_INT), -1, 0,
                                       st->for_reverse ? 0 : 2));
        ssa_jump(s, header);
      }
    } else {
      ssa_jump(s, header);
      ++s->loop_depth;
      s->current = header;
      if (st->expression != DYN_NO_EXPR) ssa_condition(s, st->expression, body, exit, 0);
      else ssa_jump(s, body);
      ssa_seal(s, body);
      s->current = body;
      ssa_loop_body(s, st, latch, exit, depth);
      ssa_seal(s, latch);
      s->current = s->blocks[latch].preds.count ? latch : UINT32_MAX;
      ssa_jump(s, header);
    }
    --s->loop_depth;
    ssa_seal(s, header);
    ssa_seal(s, exit);
    s->current = s->blocks[exit].preds.count ? exit : UINT32_MAX;
    return;
  }
  case DYN_STMT_CASE:
    ssa_case(s, st, depth);
    return;
  case DYN_STMT_BREAK: case DYN_STMT_CONTINUE: {
    SsaLoop *loop = ssa_target_loop(s, st->target_loop_id);
    if (!loop) return;
    uint32_t target = st->kind == DYN_STMT_BREAK ? loop->exit : loop->next;
    if (s->defer_count > loop->defer_base) {
      unsigned saved = s->defer_count;
      ssa_run_defers(s, loop->defer_base);
      s->defer_count = saved;
    }
    ssa_jump(s, target);
    return;
  }
  case DYN_STMT_DEFER:
    ssa_defer(s, st, (uint32_t)(st - ir->statements));
    return;
  default:
    break;
  }
  SSA_GIVE_UP(s);
}
static void ssa_statements(Ssa *s, uint32_t start, uint32_t count, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  if (depth > MAX_DEPTH || (uint64_t)start + count > ir->child_count) { SSA_GIVE_UP(s); return; }
  unsigned base = s->defer_count;
  for (uint32_t i = 0; i < count && !s->unsupported && !s->failed; ++i) {
    if (s->current == UINT32_MAX) break; /* unreachable code */
    uint32_t id = ir->children[start + i];
    if (id >= ir->statement_count) { SSA_GIVE_UP(s); return; }
    ssa_statement(s, &ir->statements[id], depth);
  }
  /* Defers of this block run when it falls through to its end. */
  if (s->current != UINT32_MAX && s->defer_count > base) ssa_run_defers(s, base);
  s->defer_count = base;
}
/* Marks locals whose address is taken; they live in frame memory. */
static void ssa_find_addresses(Ssa *s, DynExprId id, bool address, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  if (id == DYN_NO_EXPR) return;
  if (id >= ir->expression_count || depth > MAX_DEPTH) { SSA_GIVE_UP(s); return; }
  const DynIrExpr *e = &ir->expressions[id];
  if (e->kind == DYN_EXPR_NAME) {
    uint32_t local;
    if (address && ssa_local_index(s, e->integer, &local)) s->memory_local[local] = true;
    return;
  }
  bool through = (e->kind == DYN_EXPR_FIELD && e->left < ir->expression_count && !dyn_type_is_pointer(ir->expressions[e->left].type)) ||
                 (e->kind == DYN_EXPR_INDEX && e->left < ir->expression_count && dyn_type_is_array(ir->expressions[e->left].type)) ||
                 (e->kind == DYN_EXPR_SLICE && e->left < ir->expression_count && dyn_type_is_array(ir->expressions[e->left].type));
  ssa_find_addresses(s, e->left, (address && through) || (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_ADDRESS) ||
                                 (e->kind == DYN_EXPR_SLICE && through), depth + 1);
  ssa_find_addresses(s, e->right, false, depth + 1);
  if (e->kind == DYN_EXPR_SLICE) ssa_find_addresses(s, (DynExprId)e->integer, false, depth + 1);
  if ((uint64_t)e->item_start + e->item_count > ir->item_count) { SSA_GIVE_UP(s); return; }
  if (e->kind == DYN_EXPR_OFFSET) return;
  for (uint32_t i = 0; i < e->item_count; ++i) ssa_find_addresses(s, ir->items[e->item_start + i].expression, false, depth + 1);
}
static void ssa_scan(Ssa *s, uint32_t start, uint32_t count, unsigned depth) {
  const DynIrProgram *ir = s->ir;
  if (depth > MAX_DEPTH || (uint64_t)start + count > ir->child_count) { SSA_GIVE_UP(s); return; }
  for (uint32_t i = 0; i < count && !s->unsupported; ++i) {
    uint32_t id = ir->children[start + i];
    if (id >= ir->statement_count) { SSA_GIVE_UP(s); return; }
    const DynIrStmt *st = &ir->statements[id];
    bool pointer_loop = st->kind == DYN_STMT_FOR && st->for_pointer;
    ssa_find_addresses(s, st->expression, false, 0);
    ssa_find_addresses(s, st->target, pointer_loop, 0);
    ssa_scan(s, st->body_start, st->body_count, depth + 1);
    ssa_scan(s, st->else_start, st->else_count, depth + 1);
  }
}
/* Builds the function. Parameters arrive first, as SO_PARAM values that the
   emitter moves out of the argument registers together. */
static void ssa_build(Ssa *s) {
  const DynIrProgram *ir = s->ir;
  const DynIrFunction *f = s->f;
  uint32_t locals = f->local_count ? f->local_count : 1;
  s->memory_local = calloc(locals, sizeof(bool));
  s->local_offset = calloc(locals, sizeof(uint32_t));
  s->alias = malloc(locals * sizeof(int32_t));
  if (!s->memory_local || !s->local_offset || !s->alias) { s->failed = true; return; }
  for (uint32_t i = 0; i < locals; ++i) s->alias[i] = -1;
  s->variable_count = 2 * f->local_count;
  s->return_slot = UINT32_MAX;
  for (uint32_t i = 0; i < f->local_count; ++i) {
    DynType type = ir->locals[f->local_start + i].type;
    if (!value_type(ir, type)) s->memory_local[i] = true;
    if (type == DYN_TYPE_VOID) { SSA_GIVE_UP(s); return; }
  }
  ssa_scan(s, f->body_start, f->body_count, 0);
  if (s->unsupported) return;
  for (uint32_t i = 0; i < f->local_count; ++i) {
    if (!s->memory_local[i]) continue;
    uint32_t size, alignment;
    if (!frame_layout(ir, ir->locals[f->local_start + i].type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return; }
    s->local_offset[i] = ssa_reserve(s, size ? size : 1, alignment);
  }
  uint32_t entry = ssa_block(s);
  s->blocks[entry].sealed = true;
  s->current = entry;
  BackendContext *ctx = s->ctx;
  bool sret = abi_memory(ctx, ir, f->return_type);
  if (raw_aggregate(ir, f->return_type)) { SSA_GIVE_UP(s); return; }
  unsigned gp = sret && !ctx->a64 ? 1 : 0, fp = 0;
  uint32_t stack = 0;
  /* Pass 1: every register parameter as an SO_PARAM value. */
  typedef struct { int32_t value; AbiPart part; } Incoming;
  Incoming incoming[512]; unsigned count = 0, firsts[514];
  int32_t result_pointer = sret ? ssa_emit(s, SO_PARAM, SC_INT, -1, -1, -1, ctx->a64 ? SSA_RESULT_POINTER : 0, 0) : -1;
  for (uint32_t i = 0; i < f->param_count + (unsigned)f->variadic && !s->unsupported; ++i) {
    DynType type = i < f->param_count ? ir->params[f->param_start + i].type : f->variadic_type;
    AbiPart parts[512]; unsigned n; bool by_pointer;
    if (raw_aggregate(ir, type) || !abi_assign(ctx, ir, type, &gp, &fp, parts, &n, 512, &by_pointer) ||
        count + n > 512 || i >= 512) { SSA_GIVE_UP(s); return; }
    if (by_pointer) parts[0].leaf = DYN_TYPE_RAWPTR; /* marks the copy-from pointer */
    firsts[i] = count;
    for (unsigned k = 0; k < n; ++k) {
      AbiPart part = parts[k];
      int32_t v = -1;
      if (part.cls >= 0) {
        uint8_t cls = part.cls >= 8 ? (part.leaf == DYN_TYPE_F32 || (aggregate(ir, type) && part.size == 4) ? SC_F32 : SC_F64) : SC_INT;
        if (part.cls >= 8 && !aggregate(ir, type)) cls = ssa_class(type);
        v = ssa_emit(s, SO_PARAM, cls, -1, -1, -1, part.cls, 0);
      } else if (ctx->a64) stack_slot(ctx, &part, &stack);
      else { part.stack = stack; stack += 8; }
      incoming[count++] = (Incoming){v, part};
    }
  }
  if (s->unsupported || s->failed) return;
  firsts[f->param_count + (unsigned)f->variadic] = count;
  if (sret) {
    s->return_slot = ssa_reserve(s, 8, 8);
    ssa_store(s, ssa_frame(s, s->return_slot), -1, 1, 0, SSA_MEM(64, 0, 0), result_pointer);
  }
  /* Pass 2: values into variables or frame memory. */
  unsigned next = 0;
  for (uint32_t i = 0; i < f->param_count + (unsigned)f->variadic && !s->unsupported; ++i) {
    DynIrParam packed = {.type = f->variadic_type, .local_id = f->variadic_local_id};
    const DynIrParam *p = i < f->param_count ? &ir->params[f->param_start + i] : &packed;
    uint32_t local;
    if (!ssa_local_index(s, p->local_id, &local)) return;
    unsigned n = descriptor(p->type) ? 2 : 1;
    if (aggregate(ir, p->type)) {
      uint32_t size, alignment;
      if (!layout(ir, p->type, &size, &alignment, 0)) { SSA_GIVE_UP(s); return; }
      n = firsts[i + 1] - firsts[i];
      int32_t address = ssa_frame(s, s->local_offset[local]);
      if (n == 1 && incoming[next].part.leaf == DYN_TYPE_RAWPTR) {
        /* Passed as a pointer to the caller's copy. */
        int32_t pointer = incoming[next].part.cls >= 0 ? incoming[next].value
                          : ssa_load(s, ssa_frame(s, 16 + incoming[next].part.stack), -1, 1, 0, SSA_MEM(64, 0, 0));
        ssa_emit(s, SO_COPYMEM, SC_NONE, address, pointer, -1, size, 1);
        next += 1;
        continue;
      }
      for (unsigned k = 0; k < n; ++k) {
        Incoming *in = &incoming[next + k];
        int32_t v = in->value;
        if (in->part.cls < 0) v = ssa_load(s, ssa_frame(s, 16 + in->part.stack), -1, 1, 0, SSA_MEM(64, 0, 0));
        if (in->part.cls >= 8) ssa_store(s, address, -1, 1, in->part.offset, SSA_MEM(in->part.size == 4 ? 32 : 64, 0, 1), v);
        else ssa_store_bytes(s, address, in->part.offset, in->part.size, v);
      }
      next += n;
      continue;
    }
    int32_t values[2] = {-1, -1};
    for (unsigned k = 0; k < n; ++k) {
      Incoming *in = &incoming[next + k];
      values[k] = in->part.cls >= 0 ? in->value
                  : ssa_load(s, ssa_frame(s, 16 + in->part.stack), -1, 1, 0,
                             descriptor(p->type) ? SSA_MEM(64, 0, 0) : ssa_memory_type(ir, p->type));
    }
    next += n;
    if (scalar(ir, p->type)) values[0] = ssa_normalize(s, values[0], p->type);
    ssa_set_local(s, local, values[0], values[1]);
  }
  if (next != count) { SSA_GIVE_UP(s); return; }
  if (f->is_main && ctx->initializer_symbol) {
    int32_t call = ssa_emit(s, SO_CALL, SC_NONE, -1, -1, -1, ctx->initializer_symbol, 0);
    (void)call;
    s->calls = true;
  }
  ssa_statements(s, f->body_start, f->body_count, 0);
  if (s->current != UINT32_MAX) {
    if (f->return_type != DYN_TYPE_VOID && !f->is_main) { SSA_GIVE_UP(s); return; }
    ssa_return_value(s, -1, -1);
  }
}

/* ---- Passes ---- */

/* Operand slots of a value, including phi and call list entries. */
static uint32_t ssa_operands(Ssa *s, uint32_t id, int32_t **slots, uint32_t capacity) {
  SsaValue *v = &s->values[id];
  uint32_t n = 0;
  if (v->op == SO_CONST || v->op == SO_PARAM || v->op == SO_FRAME || v->op == SO_SYMBOL) return 0;
  if (v->op == SO_PHI) {
    for (uint32_t i = 0; i < v->count && n < capacity; ++i) slots[n++] = (int32_t *)&s->lists[v->list + i];
    return n;
  }
  if (v->op == SO_CALL) {
    for (uint32_t i = 0; i < v->count && n < capacity; ++i) slots[n++] = (int32_t *)&s->lists[v->list + 3 * i];
    return n;
  }
  if (v->a >= 0) slots[n++] = &v->a;
  if (v->b >= 0) slots[n++] = &v->b;
  if (v->c >= 0) slots[n++] = &v->c;
  return n;
}
#define SSA_MAX_OPERANDS 1600
static _Thread_local int32_t *ssa_slots[SSA_MAX_OPERANDS];
static void ssa_resolve_all(Ssa *s) {
  for (uint32_t b = 0; b < s->block_count; ++b) {
    SsaBlock *block = &s->blocks[b];
    uint32_t kept = 0;
    for (uint32_t i = 0; i < block->values.count; ++i) {
      uint32_t id = block->values.items[i];
      SsaValue *v = &s->values[id];
      if (v->op == SO_COPY) { v->dead = true; continue; }
      uint32_t n = ssa_operands(s, id, ssa_slots, SSA_MAX_OPERANDS);
      for (uint32_t k = 0; k < n; ++k) *ssa_slots[k] = ssa_resolve(s, *ssa_slots[k]);
      block->values.items[kept++] = id;
    }
    block->values.count = kept;
    block->control = ssa_resolve(s, block->control);
    block->control2 = ssa_resolve(s, block->control2);
    block->control3 = ssa_resolve(s, block->control3);
    block->control4 = ssa_resolve(s, block->control4);
  }
}
/* Reverse postorder of reachable blocks; drops unreachable predecessors. */
static uint32_t ssa_successors(const Ssa *s, const SsaBlock *b) {
  switch (b->kind) {
  case SB_PLAIN: return 1;
  case SB_IF: case SB_CALL: return 2;
  case SB_SWITCH: return 1 + s->lists[b->table + 1];
  default: return 0;
  }
}
static uint32_t ssa_successor(const Ssa *s, const SsaBlock *b, uint32_t i) {
  if (b->kind == SB_SWITCH) return s->lists[b->table + 2 + i];
  return b->succ[i];
}
static uint32_t *ssa_order(Ssa *s, uint32_t *count) {
  uint32_t *order = malloc((s->block_count + 1) * sizeof(uint32_t));
  uint32_t *stack = malloc((s->block_count + 1) * 2 * sizeof(uint32_t));
  if (!order || !stack) { free(order); free(stack); s->failed = true; return NULL; }
  for (uint32_t i = 0; i < s->block_count; ++i) { s->blocks[i].reachable = false; s->blocks[i].order = UINT32_MAX; }
  uint32_t top = 0, n = 0;
  stack[top++] = 0; stack[top++] = 0;
  s->blocks[0].reachable = true;
  uint32_t *post = malloc((s->block_count + 1) * sizeof(uint32_t)), posts = 0;
  if (!post) { free(order); free(stack); s->failed = true; return NULL; }
  while (top) {
    uint32_t b = stack[top - 2], next = stack[top - 1];
    SsaBlock *block = &s->blocks[b];
    if (next < ssa_successors(s, block)) {
      stack[top - 1] = next + 1;
      uint32_t succ = ssa_successor(s, block, next);
      if (succ != UINT32_MAX && !s->blocks[succ].reachable) { s->blocks[succ].reachable = true; stack[top++] = succ; stack[top++] = 0; }
      continue;
    }
    post[posts++] = b;
    top -= 2;
  }
  for (uint32_t i = 0; i < posts; ++i) { order[n] = post[posts - 1 - i]; s->blocks[order[n]].order = n; ++n; }
  free(post); free(stack);
  /* Remove unreachable predecessors together with their phi operands. */
  for (uint32_t i = 0; i < n; ++i) {
    SsaBlock *block = &s->blocks[order[i]];
    uint32_t kept = 0;
    for (uint32_t p = 0; p < block->preds.count; ++p) {
      if (!s->blocks[block->preds.items[p]].reachable) continue;
      for (uint32_t k = 0; k < block->values.count; ++k) {
        SsaValue *v = &s->values[block->values.items[k]];
        if (v->op != SO_PHI) break;
        s->lists[v->list + kept] = s->lists[v->list + p];
      }
      block->preds.items[kept++] = block->preds.items[p];
    }
    for (uint32_t k = 0; k < block->values.count; ++k) {
      SsaValue *v = &s->values[block->values.items[k]];
      if (v->op != SO_PHI) break;
      v->count = kept;
    }
    block->preds.count = kept;
  }
  *count = n;
  return order;
}
/* Splits edges from a branch into a block with several predecessors, so phi
   moves have a block of their own. */
static void ssa_split_edges(Ssa *s) {
  uint32_t blocks = s->block_count;
  for (uint32_t b = 0; b < blocks; ++b) {
    if (!s->blocks[b].reachable || s->blocks[b].kind != SB_IF) continue;
    for (unsigned k = 0; k < 2; ++k) {
      uint32_t to = s->blocks[b].succ[k];
      if (s->blocks[to].preds.count < 2) continue;
      uint32_t middle = ssa_block(s);
      if (s->failed) return;
      SsaBlock *m = &s->blocks[middle];
      m->reachable = m->sealed = true;
      m->loop_depth = s->blocks[to].loop_depth < s->blocks[b].loop_depth ? s->blocks[to].loop_depth : s->blocks[b].loop_depth;
      m->succ[0] = to; m->kind = SB_PLAIN;
      ssa_push(s, &m->preds, b);
      s->blocks[b].succ[k] = middle;
      SsaBlock *t = &s->blocks[to];
      for (uint32_t p = 0; p < t->preds.count; ++p) if (t->preds.items[p] == b) { t->preds.items[p] = middle; break; }
    }
  }
}
/* Cooper, Harvey and Kennedy's iterative dominators over the RPO. */
static void ssa_dominators(Ssa *s, const uint32_t *order, uint32_t n) {
  for (uint32_t i = 0; i < n; ++i) s->blocks[order[i]].idom = UINT32_MAX;
  s->blocks[order[0]].idom = order[0];
  for (bool changed = true; changed;) {
    changed = false;
    for (uint32_t i = 1; i < n; ++i) {
      SsaBlock *block = &s->blocks[order[i]];
      uint32_t idom = UINT32_MAX;
      for (uint32_t p = 0; p < block->preds.count; ++p) {
        uint32_t pred = block->preds.items[p];
        if (s->blocks[pred].idom == UINT32_MAX) continue;
        if (idom == UINT32_MAX) { idom = pred; continue; }
        uint32_t x = pred, y = idom;
        while (x != y) {
          while (s->blocks[x].order > s->blocks[y].order) x = s->blocks[x].idom;
          while (s->blocks[y].order > s->blocks[x].order) y = s->blocks[y].idom;
        }
        idom = x;
      }
      if (idom != block->idom) { block->idom = idom; changed = true; }
    }
  }
  for (uint32_t i = 0; i < n; ++i) {
    uint32_t b = order[i];
    s->blocks[b].depth = i ? s->blocks[s->blocks[b].idom].depth + 1 : 0;
  }
}
static bool ssa_dominates(Ssa *s, uint32_t a, uint32_t b) {
  while (s->blocks[b].depth > s->blocks[a].depth) b = s->blocks[b].idom;
  return a == b;
}
static void ssa_replace(Ssa *s, uint32_t id, int32_t with) {
  SsaValue *v = &s->values[id];
  v->op = SO_COPY; v->a = with; v->b = v->c = -1; v->effect = false; v->count = 0;
}
static bool ssa_is_const(Ssa *s, int32_t id, uint64_t *value) {
  if (id < 0 || s->values[id].op != SO_CONST || s->values[id].cls != SC_INT) return false;
  *value = (uint64_t)s->values[id].aux;
  return true;
}
static uint64_t ssa_extend(uint64_t x, unsigned bits, bool sign) {
  if (bits >= 64) return x;
  uint64_t mask = (UINT64_C(1) << bits) - 1;
  x &= mask;
  if (sign && (x >> (bits - 1) & 1)) x |= ~mask;
  return x;
}
static bool ssa_condition_holds(Cond cond, uint64_t a, uint64_t b) {
  switch (cond) {
  case CC_E: return a == b;
  case CC_NE: return a != b;
  case CC_B: return a < b;
  case CC_BE: return a <= b;
  case CC_A: return a > b;
  case CC_AE: return a >= b;
  case CC_L: return (int64_t)a < (int64_t)b;
  case CC_LE: return (int64_t)a <= (int64_t)b;
  case CC_G: return (int64_t)a > (int64_t)b;
  case CC_GE: return (int64_t)a >= (int64_t)b;
  default: return false;
  }
}
/* Replaces values computable now. Returns whether anything changed. */
static bool ssa_fold(Ssa *s, const uint32_t *order, uint32_t n) {
  bool changed = false;
  for (uint32_t i = 0; i < n; ++i) {
    SsaBlock *block = &s->blocks[order[i]];
    for (uint32_t k = 0; k < block->values.count; ++k) {
      uint32_t id = block->values.items[k];
      SsaValue *v = &s->values[id];
      uint64_t x, y, r;
      bool ca = ssa_is_const(s, v->a, &x), cb = ssa_is_const(s, v->b, &y);
      int32_t replacement = -1;
      bool constant = false;
      switch (v->op) {
      case SO_ADD: if (ca && cb) { r = x + y; constant = true; } else if (cb && !y) replacement = v->a; else if (ca && !x) replacement = v->b; break;
      case SO_SUB: if (ca && cb) { r = x - y; constant = true; } else if (cb && !y) replacement = v->a; break;
      case SO_MUL:
        if (ca && cb) { r = x * y; constant = true; }
        else if (cb && y == 1) replacement = v->a;
        else if (cb && y && !(y & (y - 1))) {
          unsigned shift = 0; while (!(y >> shift & 1)) ++shift;
          int32_t amount = ssa_value(s, order[i], SO_CONST, SC_INT, -1, -1, -1, shift, 0);
          if (s->failed) return false;
          v = &s->values[id];
          v->op = SO_SHL; v->b = amount;
          ssa_push(s, &block->values, 0);
          memmove(block->values.items + k + 1, block->values.items + k, (block->values.count - k - 1) * sizeof(uint32_t));
          block->values.items[k] = (uint32_t)v->b; ++k;
          changed = true;
        }
        break;
      case SO_AND: if (ca && cb) { r = x & y; constant = true; } else if (cb && y == UINT64_MAX) replacement = v->a; else if (v->a == v->b) replacement = v->a; break;
      case SO_OR: if (ca && cb) { r = x | y; constant = true; } else if (cb && !y) replacement = v->a; else if (v->a == v->b) replacement = v->a; break;
      case SO_XOR: if (ca && cb) { r = x ^ y; constant = true; } else if (cb && !y) replacement = v->a; break;
      case SO_SHL: if (ca && cb && y < 64) { r = x << y; constant = true; } else if (cb && !y) replacement = v->a; break;
      case SO_SHR: if (ca && cb && y < 64) { r = x >> y; constant = true; } else if (cb && !y) replacement = v->a; break;
      case SO_SAR: if (ca && cb && y < 64) { r = (uint64_t)((int64_t)x >> y); constant = true; } else if (cb && !y) replacement = v->a; break;
      case SO_NEG: if (ca) { r = 0 - x; constant = true; } break;
      case SO_NOT: if (ca) { r = ~x; constant = true; } break;
      case SO_EXT: {
        if (ca) { r = ssa_extend(x, (unsigned)v->aux, v->aux2 != 0); constant = true; break; }
        SsaValue *inner = &s->values[v->a];
        /* Values already normalized to a range the outer extension keeps. */
        if (inner->op == SO_EXT && ((inner->aux2 == v->aux2 && inner->aux <= v->aux) || (!inner->aux2 && v->aux2 && inner->aux < v->aux)))
          replacement = v->a;
        else if ((inner->op == SO_CMP || inner->op == SO_FCMP) && v->aux >= 1) replacement = v->a;
        else if (inner->op == SO_LOAD && !(inner->aux2 >> 9 & 1) && v->aux != 1) {
          int64_t bits = inner->aux2 & 0xff, sign = inner->aux2 >> 8 & 1;
          if ((sign == v->aux2 && bits <= v->aux) || (!sign && v->aux2 && bits < v->aux)) replacement = v->a;
        }
        break;
      }
      case SO_CMP: if (ca && cb) { r = ssa_condition_holds(v->cond, x, y); constant = true; } break;
      case SO_ADDO: case SO_SUBO: case SO_MULO:
        if (ca && cb) {
          bool overflow;
          if (v->op == SO_ADDO) {
            r = x + y;
            overflow = v->aux2 ? ((~(x ^ y) & (x ^ r)) >> 63) != 0 : r < x;
          } else if (v->op == SO_SUBO) {
            r = x - y;
            overflow = v->aux2 ? (((x ^ y) & (x ^ r)) >> 63) != 0 : x < y;
          } else {
            if (v->aux2) { int64_t product; overflow = __builtin_mul_overflow((int64_t)x, (int64_t)y, &product); r = (uint64_t)product; }
            else overflow = __builtin_mul_overflow(x, y, &r);
          }
          if (!overflow) constant = true;
        } else if (cb && !y && v->op != SO_MULO) replacement = v->a;
        else if (cb && y == 1 && v->op == SO_MULO) replacement = v->a;
        break;
      case SO_CHECK:
        if (ca && cb && ssa_condition_holds(v->cond, x, y)) { v->dead = true; changed = true; }
        else if (v->a == v->b && (v->cond == CC_E || v->cond == CC_BE || v->cond == CC_AE || v->cond == CC_LE || v->cond == CC_GE)) {
          v->dead = true; changed = true;
        }
        break;
      default: break;
      }
      if (constant) {
        v = &s->values[id];
        v->op = SO_CONST; v->aux = (int64_t)r; v->a = v->b = v->c = -1; v->effect = false; v->cls = SC_INT;
        changed = true;
      } else if (replacement >= 0) { ssa_replace(s, id, replacement); changed = true; }
    }
    /* Remove dead checks from the block. */
    uint32_t kept = 0;
    for (uint32_t k = 0; k < block->values.count; ++k)
      if (!s->values[block->values.items[k]].dead) block->values.items[kept++] = block->values.items[k];
    block->values.count = kept;
    /* Branches on constants become jumps. */
    uint64_t c;
    if (block->kind == SB_IF && ssa_is_const(s, block->control, &c)) {
      uint32_t keep = block->succ[c ? 0 : 1], drop = block->succ[c ? 1 : 0];
      block->kind = SB_PLAIN; block->succ[0] = keep; block->succ[1] = UINT32_MAX;
      if (drop != keep) {
        SsaBlock *t = &s->blocks[drop];
        for (uint32_t p = 0; p < t->preds.count; ++p) {
          if (t->preds.items[p] != order[i]) continue;
          for (uint32_t q = 0; q < t->values.count; ++q) {
            SsaValue *phi = &s->values[t->values.items[q]];
            if (phi->op != SO_PHI) break;
            memmove(&s->lists[phi->list + p], &s->lists[phi->list + p + 1], (phi->count - p - 1) * sizeof(uint32_t));
            --phi->count;
          }
          memmove(&t->preds.items[p], &t->preds.items[p + 1], (t->preds.count - p - 1) * sizeof(uint32_t));
          --t->preds.count;
          break;
        }
      } else {
        /* Both edges reached the same block: drop the duplicate predecessor. */
        SsaBlock *t = &s->blocks[keep];
        for (uint32_t p = t->preds.count; p-- > 0;) {
          if (t->preds.items[p] != order[i]) continue;
          for (uint32_t q = 0; q < t->values.count; ++q) {
            SsaValue *phi = &s->values[t->values.items[q]];
            if (phi->op != SO_PHI) break;
            memmove(&s->lists[phi->list + p], &s->lists[phi->list + p + 1], (phi->count - p - 1) * sizeof(uint32_t));
            --phi->count;
          }
          memmove(&t->preds.items[p], &t->preds.items[p + 1], (t->preds.count - p - 1) * sizeof(uint32_t));
          --t->preds.count;
          break;
        }
      }
      changed = true;
    }
  }
  /* Phis whose operands agree are that operand. */
  for (uint32_t i = 0; i < n; ++i) {
    SsaBlock *block = &s->blocks[order[i]];
    for (uint32_t k = 0; k < block->values.count; ++k) {
      uint32_t id = block->values.items[k];
      SsaValue *v = &s->values[id];
      if (v->op != SO_PHI) break;
      int32_t same = -1; bool unique = true;
      for (uint32_t p = 0; p < v->count; ++p) {
        int32_t op = ssa_resolve(s, (int32_t)s->lists[v->list + p]);
        if (op == (int32_t)id || op == same) continue;
        if (same >= 0) { unique = false; break; }
        same = op;
      }
      if (unique && same >= 0) { ssa_replace(s, id, same); changed = true; }
    }
  }
  return changed;
}
/* Values without side effects, or whose effect (a check) repeats harmlessly. */
static bool ssa_pure(const SsaValue *v) {
  switch (v->op) {
  case SO_CONST: case SO_ADD: case SO_SUB: case SO_MUL: case SO_AND: case SO_OR: case SO_XOR:
  case SO_SHL: case SO_SHR: case SO_SAR: case SO_NEG: case SO_NOT: case SO_EXT: case SO_CMP: case SO_FCMP:
  case SO_FADD: case SO_FSUB: case SO_FMUL: case SO_FDIV: case SO_FNEG: case SO_ITOF: case SO_FTOI:
  case SO_FCVT: case SO_BITS: case SO_FRAME: case SO_SYMBOL: case SO_LEA: case SO_MULH:
    return true;
  default:
    return false;
  }
}
static uint64_t ssa_key(const SsaValue *v) {
  uint64_t h = v->op * UINT64_C(0x100000001b3) ^ v->cls;
  h = (h ^ (uint64_t)(uint32_t)v->a) * UINT64_C(0x100000001b3);
  h = (h ^ (uint64_t)(uint32_t)v->b) * UINT64_C(0x100000001b3);
  h = (h ^ (uint64_t)(uint32_t)v->c) * UINT64_C(0x100000001b3);
  h = (h ^ (uint64_t)v->aux) * UINT64_C(0x100000001b3);
  h = (h ^ (uint64_t)v->aux2 ^ (uint64_t)v->cond << 40 ^ (uint64_t)v->scale << 48) * UINT64_C(0x100000001b3);
  return h;
}
static bool ssa_same(const SsaValue *x, const SsaValue *y) {
  return x->op == y->op && x->cls == y->cls && x->a == y->a && x->b == y->b && x->c == y->c &&
         x->aux == y->aux && x->aux2 == y->aux2 && x->cond == y->cond && x->scale == y->scale;
}
/* Common subexpressions: a later value equal to a dominating one reuses it.
   Checks and overflow-checked arithmetic qualify too: once a check passed,
   an identical one cannot fail. */
static bool ssa_cse(Ssa *s, const uint32_t *order, uint32_t n) {
  uint32_t capacity = 64;
  while (capacity < 2 * s->value_count) capacity *= 2;
  int32_t *table = malloc(capacity * sizeof(int32_t));
  if (!table) { s->failed = true; return false; }
  for (uint32_t i = 0; i < capacity; ++i) table[i] = -1;
  bool changed = false;
  for (uint32_t i = 0; i < n; ++i) {
    uint32_t b = order[i];
    SsaBlock *block = &s->blocks[b];
    uint32_t kept = 0;
    for (uint32_t k = 0; k < block->values.count; ++k) {
      uint32_t id = block->values.items[k];
      SsaValue *v = &s->values[id];
      bool candidate = ssa_pure(v) || v->op == SO_CHECK || v->op == SO_ADDO || v->op == SO_SUBO ||
                       v->op == SO_MULO || v->op == SO_DIV || v->op == SO_REM;
      if (candidate) {
        uint32_t slot = (uint32_t)ssa_key(v) & (capacity - 1);
        int32_t found = -1;
        while (table[slot] >= 0) {
          SsaValue *other = &s->values[table[slot]];
          if (ssa_same(other, v) && !other->dead && other->op != SO_COPY && ssa_dominates(s, other->block, b)) { found = table[slot]; break; }
          slot = (slot + 1) & (capacity - 1);
        }
        if (found >= 0) {
          if (v->op == SO_CHECK) v->dead = true;
          else { ssa_replace(s, id, found); v->dead = true; }
          changed = true;
          continue;
        }
        table[slot] = (int32_t)id;
      }
      block->values.items[kept++] = id;
    }
    block->values.count = kept;
  }
  free(table);
  return changed;
}
/* Unsigned bounds of a value where `block` executes: arithmetic over
   constants, induction variables and the branch conditions that dominate
   the block, in the spirit of Go's prove pass. */
static bool ssa_nonnegative(Ssa *s, int32_t id, unsigned depth);
static void ssa_range(Ssa *s, int32_t id, uint32_t block, uint64_t *lo, uint64_t *hi, unsigned depth);
static bool ssa_nonnegative(Ssa *s, int32_t id, unsigned depth) {
  if (id < 0 || depth > 6) return false;
  SsaValue *v = &s->values[id];
  uint64_t c;
  switch (v->op) {
  case SO_CONST: return v->cls == SC_INT && (int64_t)v->aux >= 0;
  case SO_EXT: return !v->aux2 && v->aux < 64;
  case SO_CMP: case SO_FCMP: return true;
  case SO_AND: return ssa_nonnegative(s, v->a, depth + 1) || ssa_nonnegative(s, v->b, depth + 1);
  case SO_SHR: return ssa_is_const(s, v->b, &c) && c > 0;
  case SO_LOAD: return !(v->aux2 >> 9 & 1) && !(v->aux2 >> 8 & 1) && (v->aux2 & 0xff) < 64;
  case SO_ADDO: case SO_MULO:
    /* Checked signed arithmetic of non-negative values stays non-negative. */
    return v->aux2 && ssa_nonnegative(s, v->a, depth + 1) && ssa_nonnegative(s, v->b, depth + 1);
  case SO_PHI: {
    /* An induction variable: every operand non-negative or the phi plus a
       non-negative step through checked addition. */
    for (uint32_t i = 0; i < v->count; ++i) {
      int32_t op = (int32_t)s->lists[v->list + i];
      SsaValue *o = &s->values[op];
      if (o->op == SO_ADDO && o->aux2 && o->a == id && ssa_nonnegative(s, o->b, depth + 1)) continue;
      /* Steps of signed loop counters stay below their exit bound. */
      if (o->op == SO_ADD && o->a == id && o->aux2 == 1) continue;
      if (!ssa_nonnegative(s, op, depth + 1)) return false;
    }
    return true;
  }
  default: return false;
  }
}
static bool ssa_fact(Ssa *s, uint32_t block, int32_t *compare, bool *holds, uint32_t *next) {
  /* The condition a single-predecessor block is reached under. */
  SsaBlock *b = &s->blocks[block];
  *next = b->idom;
  if (b->preds.count != 1) return false;
  SsaBlock *p = &s->blocks[b->preds.items[0]];
  if (p->kind != SB_IF || p->control < 0 || s->values[p->control].op != SO_CMP) return false;
  *compare = p->control;
  *holds = p->succ[0] == block;
  return p->succ[0] != p->succ[1];
}
static Cond ssa_negate(Cond c) { return (Cond)(c ^ 1); }
static Cond ssa_swap(Cond c) {
  switch (c) {
  case CC_B: return CC_A; case CC_A: return CC_B; case CC_BE: return CC_AE; case CC_AE: return CC_BE;
  case CC_L: return CC_G; case CC_G: return CC_L; case CC_LE: return CC_GE; case CC_GE: return CC_LE;
  default: return c;
  }
}
static void ssa_range(Ssa *s, int32_t id, uint32_t block, uint64_t *lo, uint64_t *hi, unsigned depth) {
  *lo = 0; *hi = UINT64_MAX;
  if (id < 0 || depth > 8) return;
  SsaValue *v = &s->values[id];
  uint64_t alo, ahi, blo, bhi, c;
  switch (v->op) {
  case SO_CONST: if (v->cls == SC_INT) *lo = *hi = (uint64_t)v->aux; return;
  case SO_EXT:
    if (!v->aux2 && v->aux < 64) { ssa_range(s, v->a, block, &alo, &ahi, depth + 1);
      uint64_t mask = (UINT64_C(1) << v->aux) - 1;
      if (ahi <= mask) { *lo = alo; *hi = ahi; } else *hi = mask; }
    break;
  case SO_AND:
    if (ssa_is_const(s, v->b, &c)) *hi = c;
    else if (ssa_is_const(s, v->a, &c)) *hi = c;
    break;
  case SO_CMP: case SO_FCMP: *hi = 1; return;
  case SO_LOAD:
    if (!(v->aux2 >> 9 & 1) && !(v->aux2 >> 8 & 1) && (v->aux2 & 0xff) < 64) *hi = (UINT64_C(1) << (v->aux2 & 0xff)) - 1;
    break;
  case SO_ADD: case SO_ADDO:
    if (v->op == SO_ADD && v->a >= 0 && s->values[v->a].op == SO_PHI) break; /* wrapping counter step */
    ssa_range(s, v->a, block, &alo, &ahi, depth + 1); ssa_range(s, v->b, block, &blo, &bhi, depth + 1);
    if (ahi <= UINT64_MAX - bhi) { *lo = alo + blo; *hi = ahi + bhi; }
    break;
  case SO_MUL: case SO_MULO:
    ssa_range(s, v->a, block, &alo, &ahi, depth + 1); ssa_range(s, v->b, block, &blo, &bhi, depth + 1);
    if (!bhi || ahi <= UINT64_MAX / bhi) { *lo = alo * blo; *hi = ahi * bhi; }
    break;
  case SO_SHL:
    if (ssa_is_const(s, v->b, &c) && c < 64) {
      ssa_range(s, v->a, block, &alo, &ahi, depth + 1);
      if (ahi <= UINT64_MAX >> c) { *lo = alo << c; *hi = ahi << c; }
    }
    break;
  case SO_SHR:
    if (ssa_is_const(s, v->b, &c) && c < 64) { ssa_range(s, v->a, block, &alo, &ahi, depth + 1); *lo = alo >> c; *hi = ahi >> c; }
    break;
  case SO_REM:
    if (!v->aux2 && ssa_is_const(s, v->b, &c) && c) *hi = c - 1;
    else if (v->aux2 && ssa_is_const(s, v->b, &c) && (int64_t)c > 0 && ssa_nonnegative(s, v->a, 0)) *hi = c - 1;
    break;
  case SO_DIV:
    if (!v->aux2 && ssa_is_const(s, v->b, &c) && c) { ssa_range(s, v->a, block, &alo, &ahi, depth + 1); *lo = alo / c; *hi = ahi / c; }
    break;
  case SO_PHI:
    if (ssa_nonnegative(s, id, 0)) *hi = UINT64_C(0x7fffffffffffffff);
    break;
  default: break;
  }
  if (*lo > *hi) { *lo = 0; *hi = UINT64_MAX; }
  /* Dominating conditions on this value. */
  bool nonnegative = *hi <= UINT64_C(0x7fffffffffffffff);
  uint32_t at = block;
  for (unsigned steps = 0; steps < 64 && at != UINT32_MAX; ++steps) {
    int32_t compare; bool holds; uint32_t next;
    if (ssa_fact(s, at, &compare, &holds, &next)) {
      SsaValue *cmp = &s->values[compare];
      Cond cond = holds ? (Cond)cmp->cond : ssa_negate((Cond)cmp->cond);
      int32_t other = -1;
      if (cmp->a == id) other = cmp->b;
      else if (cmp->b == id) { other = cmp->a; cond = ssa_swap(cond); }
      if (other >= 0) {
        bool sign = cond == CC_L || cond == CC_LE || cond == CC_G || cond == CC_GE;
        uint64_t olo, ohi;
        ssa_range(s, other, block, &olo, &ohi, depth + 1);
        bool usable = !sign || (nonnegative && ohi <= UINT64_C(0x7fffffffffffffff));
        if (usable) {
          if ((cond == CC_B || cond == CC_L) && ohi && ohi - 1 < *hi) *hi = ohi - 1;
          if ((cond == CC_BE || cond == CC_LE) && ohi < *hi) *hi = ohi;
          if ((cond == CC_A || cond == CC_G) && olo < UINT64_MAX && olo + 1 > *lo) *lo = olo + 1;
          if ((cond == CC_AE || cond == CC_GE) && olo > *lo) *lo = olo;
          if (cond == CC_E) { if (olo > *lo) *lo = olo; if (ohi < *hi) *hi = ohi; }
        }
      }
    }
    if (at == s->blocks[at].idom || !s->blocks[at].depth) break;
    at = next;
  }
  if (*lo > *hi) { *lo = 0; *hi = UINT64_MAX; }
}
/* Removes checks and overflow tests the ranges prove. */
static bool ssa_prove(Ssa *s, const uint32_t *order, uint32_t n) {
  bool changed = false;
  for (uint32_t i = 0; i < n; ++i) {
    uint32_t b = order[i];
    SsaBlock *block = &s->blocks[b];
    uint32_t kept = 0;
    for (uint32_t k = 0; k < block->values.count; ++k) {
      uint32_t id = block->values.items[k];
      SsaValue *v = &s->values[id];
      uint64_t alo, ahi, blo, bhi;
      if (v->op == SO_CHECK) {
        ssa_range(s, v->a, b, &alo, &ahi, 0);
        ssa_range(s, v->b, b, &blo, &bhi, 0);
        bool proven = false;
        switch (v->cond) {
        case CC_B: proven = ahi < blo; break;
        case CC_BE: proven = ahi <= blo; break;
        case CC_NE: proven = (blo == 0 && bhi == 0 && alo > 0) || (alo == 0 && ahi == 0 && blo > 0) || ahi < blo || bhi < alo; break;
        case CC_E: {
          /* Narrowing checks: EXT(t) == t holds when t fits the width. */
          SsaValue *x = &s->values[v->a];
          if (x->op == SO_EXT && x->a == v->b && x->aux < 64) {
            uint64_t limit = x->aux2 ? (UINT64_C(1) << (x->aux - 1)) - 1 : (UINT64_C(1) << x->aux) - 1;
            proven = blo <= limit && bhi <= limit;
          } else proven = alo == ahi && blo == bhi && alo == blo;
          break;
        }
        default: break;
        }
        if (proven) { changed = true; continue; }
      } else if (v->op == SO_ITOF && v->aux) {
        ssa_range(s, v->a, b, &alo, &ahi, 0);
        if (ahi <= UINT64_C(0x7fffffffffffffff)) { v->aux = 0; changed = true; }
      } else if (v->op == SO_ADDO || v->op == SO_MULO || v->op == SO_SUBO) {
        ssa_range(s, v->a, b, &alo, &ahi, 0);
        ssa_range(s, v->b, b, &blo, &bhi, 0);
        uint64_t limit = v->aux2 ? UINT64_C(0x7fffffffffffffff) : UINT64_MAX;
        bool fits = false;
        if (v->op == SO_ADDO) fits = ahi <= limit && bhi <= limit - ahi;
        else if (v->op == SO_MULO) fits = ahi <= limit && bhi <= limit && (!bhi || ahi <= limit / bhi);
        else fits = !v->aux2 ? alo >= bhi : (ahi <= limit && bhi <= limit);
        if (fits) {
          v->op = v->op == SO_ADDO ? SO_ADD : v->op == SO_MULO ? SO_MUL : SO_SUB;
          v->effect = false; v->aux2 = 0;
          changed = true;
        }
      }
      block->values.items[kept++] = id;
    }
    block->values.count = kept;
  }
  return changed;
}
/* (high:0) / d for d > high, by shift and subtract; *remainder gets the rest. */
static uint64_t ssa_divide_wide(uint64_t high, uint64_t d, uint64_t *remainder) {
  uint64_t quotient = 0, r = high;
  for (int bit = 63; bit >= 0; --bit) {
    bool carry = r >> 63;
    r <<= 1;
    quotient <<= 1;
    if (carry || r >= d) { r -= d; quotient |= 1; }
  }
  *remainder = r;
  return quotient;
}
static int32_t ssa_insert(Ssa *s, uint32_t b, uint32_t *k, SsaOp op, int32_t a, int32_t c, int64_t aux, int64_t aux2) {
  int32_t v = ssa_value(s, b, op, SC_INT, a, c, -1, aux, aux2);
  if (s->failed) return 0;
  SsaList *list = &s->blocks[b].values;
  ssa_push(s, list, 0);
  if (s->failed) return 0;
  memmove(list->items + *k + 1, list->items + *k, (list->count - *k - 1) * sizeof(uint32_t));
  list->items[(*k)++] = (uint32_t)v;
  return v;
}
/* Division by a constant becomes shifts or a multiply by its reciprocal
   (Granlund and Montgomery, as libdivide computes it). The checks before it
   already ran; the result is bit-identical to the hardware division. */
static void ssa_divisions(Ssa *s, const uint32_t *order, uint32_t n) {
  for (uint32_t i = 0; i < n; ++i) {
    uint32_t b = order[i];
    for (uint32_t k = 0; k < s->blocks[b].values.count; ++k) {
      uint32_t id = s->blocks[b].values.items[k];
      SsaValue *v = &s->values[id];
      uint64_t d;
      if ((v->op != SO_DIV && v->op != SO_REM) || !ssa_is_const(s, v->b, &d) || d == 0) continue;
      bool sign = v->aux2 != 0, rem = v->op == SO_REM;
      int32_t x = v->a, q;
      if (sign && (int64_t)d <= 1) continue; /* negative divisors keep IDIV */
      if (!sign && d == 1) { ssa_replace(s, id, rem ? ssa_insert(s, b, &k, SO_CONST, -1, -1, 0, 0) : x); continue; }
      unsigned log = 63 - (unsigned)__builtin_clzll(d);
      if (!(d & (d - 1))) {
        if (!sign) {
          q = rem ? ssa_insert(s, b, &k, SO_AND, x, ssa_insert(s, b, &k, SO_CONST, -1, -1, (int64_t)(d - 1), 0), 0, 0)
                  : ssa_insert(s, b, &k, SO_SHR, x, ssa_insert(s, b, &k, SO_CONST, -1, -1, log, 0), 0, 0);
          ssa_replace(s, id, q);
          continue;
        }
        /* Signed: bias negative values by d - 1 so the shift truncates toward zero. */
        int32_t sh63 = ssa_insert(s, b, &k, SO_SAR, x, ssa_insert(s, b, &k, SO_CONST, -1, -1, 63, 0), 0, 0);
        int32_t bias = ssa_insert(s, b, &k, SO_SHR, sh63, ssa_insert(s, b, &k, SO_CONST, -1, -1, 64 - log, 0), 0, 0);
        int32_t biased = ssa_insert(s, b, &k, SO_ADD, x, bias, 0, 0);
        q = ssa_insert(s, b, &k, SO_SAR, biased, ssa_insert(s, b, &k, SO_CONST, -1, -1, log, 0), 0, 0);
      } else if (!sign) {
        uint64_t r, m = ssa_divide_wide(UINT64_C(1) << log, d, &r), e = d - r;
        bool add = e >= (UINT64_C(1) << log);
        if (add) { uint64_t twice = r + r; m += m; if (twice >= d || twice < r) m += 1; }
        int32_t t = ssa_insert(s, b, &k, SO_MULH, x, ssa_insert(s, b, &k, SO_CONST, -1, -1, (int64_t)(m + 1), 0), 0, 0);
        if (add) {
          int32_t diff = ssa_insert(s, b, &k, SO_SUB, x, t, 0, 0);
          int32_t half = ssa_insert(s, b, &k, SO_SHR, diff, ssa_insert(s, b, &k, SO_CONST, -1, -1, 1, 0), 0, 0);
          int32_t sum = ssa_insert(s, b, &k, SO_ADD, half, t, 0, 0);
          q = ssa_insert(s, b, &k, SO_SHR, sum, ssa_insert(s, b, &k, SO_CONST, -1, -1, log, 0), 0, 0);
        } else q = log ? ssa_insert(s, b, &k, SO_SHR, t, ssa_insert(s, b, &k, SO_CONST, -1, -1, log, 0), 0, 0) : t;
      } else {
        uint64_t r, m = ssa_divide_wide(UINT64_C(1) << (log - 1), d, &r), e = d - r;
        bool add = e >= (UINT64_C(1) << log);
        unsigned shift = log - 1;
        if (add) { uint64_t twice = r + r; m += m; if (twice >= d || twice < r) m += 1; shift = log; }
        int32_t t = ssa_insert(s, b, &k, SO_MULH, x, ssa_insert(s, b, &k, SO_CONST, -1, -1, (int64_t)(m + 1), 0), 0, 1);
        if (add) t = ssa_insert(s, b, &k, SO_ADD, t, x, 0, 0);
        int32_t shifted = shift ? ssa_insert(s, b, &k, SO_SAR, t, ssa_insert(s, b, &k, SO_CONST, -1, -1, shift, 0), 0, 0) : t;
        int32_t negative = ssa_insert(s, b, &k, SO_SHR, shifted, ssa_insert(s, b, &k, SO_CONST, -1, -1, 63, 0), 0, 0);
        q = ssa_insert(s, b, &k, SO_ADD, shifted, negative, 0, 0);
      }
      if (rem) {
        int32_t product = ssa_insert(s, b, &k, SO_MUL, q, ssa_insert(s, b, &k, SO_CONST, -1, -1, (int64_t)d, 0), 0, 0);
        q = ssa_insert(s, b, &k, SO_SUB, x, product, 0, 0);
      }
      ssa_replace(s, id, q);
    }
  }
}
/* Loop-invariant code motion: pure values whose operands come from outside
   a loop move to the block that enters the loop. Checks, loads and calls stay
   where they are, so panics and memory effects keep their order. */
static bool ssa_hoist(Ssa *s, const uint32_t *order, uint32_t n) {
  uint32_t *stamp = calloc(s->block_count, sizeof(uint32_t)), *work = malloc((s->block_count + 1) * sizeof(uint32_t));
  if (!stamp || !work) { free(stamp); free(work); s->failed = true; return false; }
  bool changed = false;
  uint32_t mark = 0;
  for (uint32_t i = n; i-- > 0;) {
    uint32_t header = order[i];
    SsaBlock *h = &s->blocks[header];
    /* A header has one predecessor before it in the order and back edges. */
    uint32_t entry = UINT32_MAX, entries = 0, latches = 0;
    for (uint32_t p = 0; p < h->preds.count; ++p) {
      uint32_t pred = h->preds.items[p];
      if (s->blocks[pred].order >= h->order) ++latches;
      else { entry = pred; ++entries; }
    }
    if (!latches || entries != 1 || s->blocks[entry].kind != SB_PLAIN) continue;
    /* The loop: blocks reaching a latch without passing the header. */
    ++mark;
    uint32_t top = 0;
    stamp[header] = mark;
    for (uint32_t p = 0; p < h->preds.count; ++p) {
      uint32_t pred = h->preds.items[p];
      if (s->blocks[pred].order >= h->order && stamp[pred] != mark) { stamp[pred] = mark; work[top++] = pred; }
    }
    while (top) {
      SsaBlock *x = &s->blocks[work[--top]];
      for (uint32_t p = 0; p < x->preds.count; ++p) {
        uint32_t pred = x->preds.items[p];
        if (stamp[pred] != mark) { stamp[pred] = mark; work[top++] = pred; }
      }
    }
    SsaBlock *pre = &s->blocks[entry];
    for (uint32_t j = i; j < n; ++j) {
      uint32_t b = order[j];
      if (stamp[b] != mark) continue;
      SsaBlock *block = &s->blocks[b];
      uint32_t kept = 0;
      for (uint32_t k = 0; k < block->values.count; ++k) {
        uint32_t id = block->values.items[k];
        SsaValue *v = &s->values[id];
        bool invariant = ssa_pure(v) && !(v->op == SO_CONST && v->cls == SC_INT) && v->op != SO_FRAME;
        if (invariant) {
          uint32_t count = ssa_operands(s, id, ssa_slots, SSA_MAX_OPERANDS);
          for (uint32_t o = 0; o < count && invariant; ++o) {
            int32_t op = *ssa_slots[o];
            if (op >= 0 && stamp[s->values[op].block] == mark) invariant = false;
          }
        }
        if (!invariant) { block->values.items[kept++] = id; continue; }
        v->block = entry;
        ssa_push(s, &pre->values, id);
        pre = &s->blocks[entry]; block = &s->blocks[b];
        changed = true;
      }
      block->values.count = kept;
    }
  }
  free(stamp); free(work);
  return changed;
}
/* Removes values nothing needs; counts the uses of the rest. */
static void ssa_dce(Ssa *s, const uint32_t *order, uint32_t n) {
  uint32_t *work = malloc((s->value_count + 1) * sizeof(uint32_t)), top = 0;
  if (!work) { s->failed = true; return; }
  for (uint32_t i = 0; i < s->value_count; ++i) { s->values[i].uses = 0; s->values[i].dead = true; }
  for (uint32_t i = 0; i < n; ++i) {
    SsaBlock *block = &s->blocks[order[i]];
    for (uint32_t k = 0; k < block->values.count; ++k) {
      uint32_t id = block->values.items[k];
      SsaValue *v = &s->values[id];
      v->block = order[i];
      if ((v->effect && v->op != SO_RESULT && v->op != SO_PARAM && v->op != SO_DIV && v->op != SO_REM &&
           v->op != SO_LOAD) && v->dead) { v->dead = false; work[top++] = id; }
    }
    int32_t controls[4] = {block->control, block->control2, block->control3, block->control4};
    for (unsigned c = 0; c < 4; ++c) {
      if (controls[c] < 0 || (block->kind != SB_IF && block->kind != SB_RETURN && block->kind != SB_SWITCH)) continue;
      ++s->values[controls[c]].uses;
      if (s->values[controls[c]].dead) { s->values[controls[c]].dead = false; work[top++] = (uint32_t)controls[c]; }
    }
  }
  while (top) {
    uint32_t id = work[--top];
    uint32_t count = ssa_operands(s, id, ssa_slots, SSA_MAX_OPERANDS);
    for (uint32_t k = 0; k < count; ++k) {
      int32_t op = *ssa_slots[k];
      if (op < 0) continue;
      ++s->values[op].uses;
      if (s->values[op].dead) { s->values[op].dead = false; work[top++] = (uint32_t)op; }
    }
  }
  free(work);
  for (uint32_t i = 0; i < n; ++i) {
    SsaBlock *block = &s->blocks[order[i]];
    uint32_t kept = 0;
    for (uint32_t k = 0; k < block->values.count; ++k) {
      uint32_t id = block->values.items[k];
      /* A call stays for its effect; results and parameters follow it. */
      SsaValue *v = &s->values[id];
      if (v->dead && (v->op == SO_CALL || v->op == SO_PARAM || v->op == SO_RESULT)) v->dead = v->op != SO_CALL;
      if (!v->dead || v->op == SO_PARAM) block->values.items[kept++] = id;
    }
    block->values.count = kept;
  }
}
/* Folds address arithmetic into loads and stores. */
static void ssa_addressing(Ssa *s, const uint32_t *order, uint32_t n) {
  for (uint32_t i = 0; i < n; ++i) {
    SsaBlock *block = &s->blocks[order[i]];
    for (uint32_t k = 0; k < block->values.count; ++k) {
      SsaValue *v = &s->values[block->values.items[k]];
      if (v->op != SO_LOAD && v->op != SO_STORE && v->op != SO_LEA) continue;
      for (unsigned rounds = 0; rounds < 4 && v->a >= 0; ++rounds) {
        SsaValue *base = &s->values[v->a];
        if (base->op != SO_LEA) break;
        int64_t disp = v->aux + base->aux;
        if (disp != (int32_t)disp) break;
        if (base->b >= 0 && v->b >= 0) break;
        if (base->b >= 0) { v->b = base->b; v->scale = base->scale; }
        v->a = base->a; v->aux = disp;
      }
      /* LEA with no index and no displacement is its base. */
    }
  }
}

/* ---- Register allocation ---- */

/* Hardware registers 0-15 are RAX..R15, 16-31 XMM0..XMM15. R10, R11, XMM14
   and XMM15 stay free for the emitter; RSP and RBP hold the frame. */
static const unsigned char ssa_gp_order[] = {X_RAX, X_RCX, X_RDX, X_RSI, X_RDI, X_R8, X_R9,
                                             X_RBX, X_R12, X_R13, X_R14, X_R15};
static const unsigned char ssa_arguments[] = {X_RDI, X_RSI, X_RDX, X_RCX, X_R8, X_R9};
/* AArch64: x14-x17 are emitter scratch, x18 is the platform register, x29 and
   x30 hold the frame; v30 and v31 are floating scratch, and v8-v15 (callee
   saved) are not allocated. */
static const unsigned char a64_gp_order[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
                                             19, 20, 21, 22, 23, 24, 25, 26, 27, 28};
static const unsigned char a64_fp_order[] = {0, 1, 2, 3, 4, 5, 6, 7, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29};
#define A64_CALLER_SAVED (UINT64_C(0x7ffff) | UINT64_C(0xff) << X_XMM0 | UINT64_C(0xffff0000) << X_XMM0)
#define A64_CALLEE_SAVED (UINT64_C(0x1ff80000))
/* Register an argument location names on this target. */
static int ssa_location_register(const BackendContext *ctx, int location) {
  if (location == SSA_RESULT_POINTER) return 8;
  if (location == SSA_TARGET) return ctx->a64 ? 9 : X_RAX;
  if (location >= 8) return X_XMM0 + location - 8;
  return ctx->a64 ? location : ssa_arguments[location];
}
#define SSA_CALLER_SAVED ((UINT64_C(1) << X_RAX) | (UINT64_C(1) << X_RCX) | (UINT64_C(1) << X_RDX) | (UINT64_C(1) << X_RSI) | \
                          (UINT64_C(1) << X_RDI) | (UINT64_C(1) << X_R8) | (UINT64_C(1) << X_R9) | (UINT64_C(1) << X_R10) | \
                          (UINT64_C(1) << X_R11) | UINT64_C(0xffff) << X_XMM0)
typedef struct { uint32_t position; uint64_t mask; } SsaClobber;

/* Hardware register of result part aux: 0 and 1 the integer result
   registers, X_XMM0 + n floating result register n. */
static int ssa_result_register(const BackendContext *ctx, int64_t aux) {
  if (aux >= X_XMM0 || ctx->a64) return (int)aux;
  return aux ? X_RDX : X_RAX;
}
/* Whether a value occupies a register or slot (constants and frame
   addresses are rematerialized at each use). */
static bool ssa_located(const SsaValue *v) {
  bool constant = v->op == SO_CONST && v->cls == SC_INT;
  return !v->dead && v->cls != SC_NONE && !constant && v->op != SO_FRAME && !v->fused;
}
static uint64_t ssa_clobbers(Ssa *s, const SsaValue *v) {
  if (s->ctx->a64 && v->op != SO_CALL && v->op != SO_PANIC) return 0;
  switch (v->op) {
  case SO_CALL: case SO_PANIC: return s->ctx->a64 ? A64_CALLER_SAVED : SSA_CALLER_SAVED;
  case SO_DIV: case SO_REM: case SO_MULH: return UINT64_C(1) << X_RAX | UINT64_C(1) << X_RDX;
  case SO_MULO: return v->aux2 ? 0 : UINT64_C(1) << X_RAX | UINT64_C(1) << X_RDX;
  case SO_SHL: case SO_SHR: case SO_SAR: {
    uint64_t c;
    return ssa_is_const(s, v->b, &c) || s->ctx->bmi2 ? 0 : UINT64_C(1) << X_RCX;
  }
  case SO_COPYMEM: return v->aux > 64 ? (UINT64_C(1) << X_RCX | UINT64_C(1) << X_RSI | UINT64_C(1) << X_RDI) : UINT64_C(1) << X_RCX;
  case SO_ZEROMEM: return v->aux > 64 ? (UINT64_C(1) << X_RAX | UINT64_C(1) << X_RCX | UINT64_C(1) << X_RDI) : 0;
  default: return 0;
  }
}
typedef struct {
  Ssa *s;
  const uint32_t *order; uint32_t n;
  uint32_t *block_start, *block_end;
  SsaClobber *clobbers; uint32_t clobber_count;
  uint64_t used_callee;   /* callee-saved registers to preserve */
  uint32_t spill_slots;
} SsaAlloc;
static bool ssa_clobbered(SsaAlloc *a, unsigned reg, uint32_t start, uint32_t end) {
  /* Any clobber of reg strictly inside (start, end)? Clobbers are sorted. */
  uint32_t low = 0, high = a->clobber_count;
  while (low < high) { uint32_t mid = (low + high) / 2; if (a->clobbers[mid].position <= start) low = mid + 1; else high = mid; }
  for (uint32_t i = low; i < a->clobber_count && a->clobbers[i].position < end; ++i)
    if (a->clobbers[i].mask >> reg & 1) return true;
  return false;
}
/* Live intervals: each value's definition through its last use, widened to
   the end of every block it is live out of. */
static bool ssa_intervals(SsaAlloc *a) {
  Ssa *s = a->s;
  uint32_t position = 0;
  a->block_start = malloc(s->block_count * sizeof(uint32_t));
  a->block_end = malloc(s->block_count * sizeof(uint32_t));
  uint32_t *stamp = calloc(s->block_count, sizeof(uint32_t));
  uint32_t *work = malloc((s->block_count + 1) * sizeof(uint32_t));
  if (!a->block_start || !a->block_end || !stamp || !work) { free(stamp); free(work); return false; }
  uint32_t clobber_capacity = 0;
  for (uint32_t i = 0; i < a->n; ++i) {
    uint32_t b = a->order[i];
    SsaBlock *block = &s->blocks[b];
    a->block_start[b] = position;
    position += 2;
    for (uint32_t k = 0; k < block->values.count; ++k) {
      SsaValue *v = &s->values[block->values.items[k]];
      if (v->op == SO_PHI) { v->start = v->end = a->block_start[b]; continue; }
      v->start = v->end = position;
      uint64_t mask = ssa_clobbers(s, v);
      if (mask) {
        a->clobbers = ssa_grow(a->clobbers, &clobber_capacity, a->clobber_count + 1, sizeof(SsaClobber), &s->failed);
        if (s->failed) { free(stamp); free(work); return false; }
        a->clobbers[a->clobber_count++] = (SsaClobber){position, mask};
      }
      position += 2;
    }
    a->block_end[b] = position;
    position += 2;
  }
  uint32_t visit = 0;
  /* Each use extends the interval of its operand. */
  for (uint32_t i = 0; i < a->n; ++i) {
    uint32_t b = a->order[i];
    SsaBlock *block = &s->blocks[b];
    for (uint32_t k = 0; k <= block->values.count; ++k) {
      int32_t operands[SSA_MAX_OPERANDS]; uint32_t count = 0, at;
      int32_t phi = -1;
      if (k < block->values.count) {
        uint32_t id = block->values.items[k];
        SsaValue *v = &s->values[id];
        uint32_t c = ssa_operands(s, id, ssa_slots, SSA_MAX_OPERANDS);
        for (uint32_t j = 0; j < c; ++j) operands[count++] = *ssa_slots[j];
        at = v->start;
        if (v->op == SO_PHI) phi = (int32_t)id;
        /* A protected call runs dyn_unwind_set and dyn_unwind_link before its
           argument moves, so its operands must survive those calls. */
        if ((v->op == SO_CALL || v->op == SO_PANIC) && v->cond) at = v->start + 1;
        if (v->fused) at = a->block_end[b];
      } else {
        if (block->kind == SB_IF || block->kind == SB_RETURN || block->kind == SB_SWITCH) {
          if (block->control >= 0) operands[count++] = block->control;
          if (block->control2 >= 0) operands[count++] = block->control2;
          if (block->control3 >= 0) operands[count++] = block->control3;
          if (block->control4 >= 0) operands[count++] = block->control4;
        }
        at = a->block_end[b];
      }
      for (uint32_t j = 0; j < count; ++j) {
        int32_t op = operands[j];
        if (op < 0) continue;
        SsaValue *o = &s->values[op];
        /* Where the use happens: phi operands at the end of their predecessor. */
        uint32_t use_block = phi >= 0 ? block->preds.items[j] : b;
        uint32_t use_at = phi >= 0 ? a->block_end[use_block] : at;
        if (use_at > o->end) o->end = use_at;
        if (use_block == o->block) continue;
        /* Live into use_block: walk predecessors back to the definition. */
        ++visit;
        uint32_t top = 0;
        if (phi >= 0) {
          /* Live out of the predecessor itself. */
          if (a->block_end[use_block] > o->end) o->end = a->block_end[use_block];
        }
        stamp[use_block] = visit; work[top++] = use_block;
        while (top) {
          uint32_t x = work[--top];
          if (x == o->block) continue;
          SsaBlock *xb = &s->blocks[x];
          for (uint32_t p = 0; p < xb->preds.count; ++p) {
            uint32_t pred = xb->preds.items[p];
            if (a->block_end[pred] > o->end) o->end = a->block_end[pred];
            if (stamp[pred] != visit) { stamp[pred] = visit; work[top++] = pred; }
          }
        }
      }
    }
  }
  free(stamp); free(work);
  return true;
}
/* Register preferences that remove moves: phis and their operands share a
   register, two-address results reuse their first operand's, and values
   headed to or from fixed registers prefer them. */
static void ssa_hints(SsaAlloc *a) {
  Ssa *s = a->s;
  for (uint32_t i = 0; i < a->n; ++i) {
    SsaBlock *block = &s->blocks[a->order[i]];
    for (uint32_t k = 0; k < block->values.count; ++k) {
      uint32_t id = block->values.items[k];
      SsaValue *v = &s->values[id];
      if (v->dead) continue;
      switch (v->op) {
      case SO_PHI:
        for (uint32_t p = 0; p < v->count; ++p) {
          int32_t op = (int32_t)s->lists[v->list + p];
          SsaValue *o = &s->values[op];
          if (o->op == SO_CONST || o->op == SO_FRAME) continue;
          if (o->start < v->start) { if (v->hint == -1) v->hint = op; }
          else if (o->hint == -1) o->hint = (int32_t)id;
        }
        break;
      case SO_ADD: case SO_SUB: case SO_MUL: case SO_AND: case SO_OR: case SO_XOR: case SO_SHL: case SO_SHR:
      case SO_SAR: case SO_NEG: case SO_NOT: case SO_EXT: case SO_ADDO: case SO_SUBO: case SO_FADD: case SO_FSUB:
      case SO_FMUL: case SO_FDIV: case SO_FNEG: case SO_LEA:
        if (v->hint == -1 && v->a >= 0 && s->values[v->a].op != SO_CONST && s->values[v->a].op != SO_FRAME &&
            s->values[v->a].end == v->start)
          v->hint = v->a;
        break;
      case SO_PARAM:
        v->hint = -2 - ssa_location_register(s->ctx, (int)v->aux);
        break;
      case SO_RESULT: v->hint = -2 - ssa_result_register(s->ctx, v->aux); break;
      case SO_DIV: v->hint = -2 - X_RAX; break;
      case SO_MULH: v->hint = -2 - X_RDX; break;
      case SO_REM: v->hint = -2 - X_RDX; break;
      case SO_CALL:
        for (uint32_t p = 0; p < v->count; ++p) {
          int32_t op = (int32_t)s->lists[v->list + 3 * p], location = (int32_t)s->lists[v->list + 3 * p + 1];
          SsaValue *o = &s->values[op];
          if (o->hint != -1 || o->end != v->start || location >= SSA_STACK) continue;
          o->hint = -2 - ssa_location_register(s->ctx, location);
        }
        break;
      default: break;
      }
    }
    if (block->kind == SB_RETURN && block->control >= 0) {
      SsaValue *r = &s->values[block->control];
      if (r->hint == -1) r->hint = -2 - (r->cls == SC_F64 || r->cls == SC_F32 ? X_XMM0 : X_RAX);
    }
  }
}
/* qsort has no context argument in C11; emission is single-threaded per context. */
static _Thread_local SsaValue *ssa_sort_values;
static int ssa_sort_start(const void *x, const void *y) {
  const SsaValue *v = ssa_sort_values;
  uint32_t a = *(const uint32_t *)x, b = *(const uint32_t *)y;
  if (v[a].start != v[b].start) return v[a].start < v[b].start ? -1 : 1;
  return a < b ? -1 : a > b;
}
static bool ssa_allocate(SsaAlloc *a) {
  Ssa *s = a->s;
  uint32_t *list = malloc((s->value_count + 1) * sizeof(uint32_t)), count = 0;
  uint32_t *active = malloc((s->value_count + 1) * sizeof(uint32_t)), actives = 0;
  if (!list || !active) { free(list); free(active); return false; }
  for (uint32_t i = 0; i < a->n; ++i) {
    SsaBlock *block = &s->blocks[a->order[i]];
    for (uint32_t k = 0; k < block->values.count; ++k) {
      uint32_t id = block->values.items[k];
      SsaValue *v = &s->values[id];
      v->reg = v->slot = -1;
      if (ssa_located(v)) list[count++] = id;
    }
  }
  ssa_sort_values = s->values;
  qsort(list, count, sizeof(uint32_t), ssa_sort_start);
  uint32_t owner[64];
  for (unsigned r = 0; r < 64; ++r) owner[r] = UINT32_MAX;
  for (uint32_t i = 0; i < count; ++i) {
    uint32_t id = list[i];
    SsaValue *v = &s->values[id];
    /* Expire intervals that ended before this one starts. */
    uint32_t kept = 0;
    for (uint32_t j = 0; j < actives; ++j) {
      SsaValue *w = &s->values[active[j]];
      if (w->end < v->start || (w->end == v->start && v->op != SO_PHI)) { if (w->reg >= 0) owner[w->reg] = UINT32_MAX; }
      else active[kept++] = active[j];
    }
    actives = kept;
    bool floating = v->cls == SC_F64 || v->cls == SC_F32;
    int chosen = -1;
    /* Hints: >= 0 another value's register, <= -2 register -2 - hint. */
    int want = v->hint >= 0 ? s->values[v->hint].reg : v->hint <= -2 ? -2 - v->hint : -1;
    if (want >= 0 && (want >= X_XMM0) == floating && owner[want] == UINT32_MAX &&
        !ssa_clobbered(a, (unsigned)want, v->start, v->end))
      chosen = want;
    if (chosen >= 0) {}
    else if (floating) {
      unsigned count = s->ctx->a64 ? sizeof(a64_fp_order) : 14;
      for (unsigned j = 0; j < count && chosen < 0; ++j) {
        unsigned r = X_XMM0 + (s->ctx->a64 ? a64_fp_order[j] : j);
        if (owner[r] == UINT32_MAX && !ssa_clobbered(a, r, v->start, v->end)) chosen = (int)r;
      }
    } else {
      const unsigned char *gp = s->ctx->a64 ? a64_gp_order : ssa_gp_order;
      unsigned count = s->ctx->a64 ? sizeof(a64_gp_order) : sizeof(ssa_gp_order);
      for (unsigned j = 0; j < count && chosen < 0; ++j) {
        unsigned r = gp[j];
        if (owner[r] == UINT32_MAX && !ssa_clobbered(a, r, v->start, v->end)) chosen = (int)r;
      }
    }
    if (chosen < 0) {
      /* Evict the active interval of this class that ends last, if it
         outlives this one and its register suits this interval. */
      int victim = -1;
      for (uint32_t j = 0; j < actives; ++j) {
        SsaValue *w = &s->values[active[j]];
        if (w->reg < 0 || (w->reg >= X_XMM0) != floating || ssa_clobbered(a, (unsigned)w->reg, v->start, v->end)) continue;
        if (victim < 0 || w->end > s->values[active[victim]].end) victim = (int)j;
      }
      if (victim >= 0 && s->values[active[victim]].end > v->end) {
        SsaValue *w = &s->values[active[victim]];
        chosen = w->reg;
        w->reg = -1;
        active[victim] = active[--actives];
      }
    }
    if (chosen >= 0) {
      v->reg = chosen;
      owner[chosen] = id;
      active[actives++] = id;
    }
  }
  /* Spill slots and callee-saved registers. */
  for (uint32_t i = 0; i < count; ++i) {
    SsaValue *v = &s->values[list[i]];
    if (v->reg < 0) v->slot = (int32_t)a->spill_slots++;
    else if (s->ctx->a64 ? (A64_CALLEE_SAVED >> v->reg & 1) : (v->reg == X_RBX || (v->reg >= X_R12 && v->reg <= X_R15)))
      a->used_callee |= UINT64_C(1) << v->reg;
  }
  free(list); free(active);
  return true;
}

/* ---- x86-64 emission ---- */

typedef struct { int base, index; unsigned scale; int32_t disp; } SsaMemory;
typedef struct {
  SsaAlloc *alloc;
  Ssa *s;
  BackendContext *ctx;
  uint32_t frame_bytes, spill_base, save_base;
  size_t stubs[GUARD_COUNT];
  struct { size_t at; unsigned kind; } *stub_uses; uint32_t stub_use_count, stub_use_capacity;
  struct { size_t at; uint32_t block; bool short_branch; } *jumps; uint32_t jump_count, jump_capacity;
  /* From a first emission: block and jump offsets from the function start,
     so the final emission can pick short branches. */
  size_t start, *measured_blocks, *measured_jumps; uint32_t measured_jump_count;
  struct { size_t at; uint32_t block; } *tables; uint32_t table_count, table_capacity;
} SsaEmit;

static void x86_rex(BackendContext *ctx, bool w, unsigned reg, unsigned index, unsigned base, bool byte_reg) {
  unsigned rex = 0x40 | (w ? 8 : 0) | (reg >> 3 & 1) << 2 | (index >> 3 & 1) << 1 | (base >> 3 & 1);
  if (rex != 0x40 || byte_reg) byte(ctx, rex);
}
/* ModRM, SIB and displacement for a memory operand. RIP-relative operands
   are written by their callers. */
static void x86_memory_operand(BackendContext *ctx, unsigned reg, SsaMemory m) {
  unsigned base = (unsigned)m.base & 7;
  int32_t disp = m.disp;
  unsigned mode = disp == 0 && base != 5 ? 0 : disp >= -128 && disp <= 127 ? 1 : 2;
  if (m.index >= 0) {
    unsigned scale = m.scale == 8 ? 3 : m.scale == 4 ? 2 : m.scale == 2 ? 1 : 0;
    byte(ctx, mode << 6 | (reg & 7) << 3 | 4);
    byte(ctx, scale << 6 | ((unsigned)m.index & 7) << 3 | base);
  } else {
    byte(ctx, mode << 6 | (reg & 7) << 3 | base);
    if (base == 4) byte(ctx, 0x24);
  }
  if (mode == 1) byte(ctx, (uint8_t)disp);
  else if (mode == 2) word(ctx, (uint32_t)disp);
}
/* Opcodes of one or two bytes, packed with their length: OP1(0x8b), OP2(0x0f, 0xb6). */
#define OP1(a) ((uint32_t)(a) | 1u << 24)
#define OP2(a, b) ((uint32_t)(a) | (uint32_t)(b) << 8 | 2u << 24)
static void x86_opcode(BackendContext *ctx, uint32_t opcode) {
  byte(ctx, opcode & 0xff);
  if (opcode >> 24 == 2) byte(ctx, opcode >> 8 & 0xff);
}
/* [prefix] REX opcode modrm(mem) */
static void x86_mem_op(BackendContext *ctx, int prefix, bool w, uint32_t opcode, unsigned reg, SsaMemory m, bool byte_reg) {
  if (prefix >= 0) byte(ctx, (unsigned)prefix);
  x86_rex(ctx, w, reg, m.index >= 0 ? (unsigned)m.index : 0, (unsigned)m.base, byte_reg && reg >= 4 && reg < 8);
  x86_opcode(ctx, opcode);
  x86_memory_operand(ctx, reg, m);
}
static void x86_reg_op(BackendContext *ctx, int prefix, bool w, uint32_t opcode, unsigned reg, unsigned rm, bool byte_reg) {
  if (prefix >= 0) byte(ctx, (unsigned)prefix);
  x86_rex(ctx, w, reg, 0, rm, byte_reg && ((reg >= 4 && reg < 8) || (rm >= 4 && rm < 8)));
  x86_opcode(ctx, opcode);
  byte(ctx, 0xc0 | (reg & 7) << 3 | (rm & 7));
}
static void x86_mov(BackendContext *ctx, unsigned to, unsigned from) {
  if (to == from) return;
  if (to >= X_XMM0 && from >= X_XMM0) x86_reg_op(ctx, -1, false, OP2(0x0f, 0x28), to - X_XMM0, from - X_XMM0, false); /* movaps */
  else if (to >= X_XMM0) x86_reg_op(ctx, 0x66, true, OP2(0x0f, 0x6e), to - X_XMM0, from, false); /* movq xmm, r64 */
  else if (from >= X_XMM0) x86_reg_op(ctx, 0x66, true, OP2(0x0f, 0x7e), from - X_XMM0, to, false); /* movq r64, xmm */
  else x86_reg_op(ctx, -1, true, OP1(0x89), from, to, false);
}
static void x86_move_immediate(BackendContext *ctx, unsigned reg, uint64_t n) {
  if (reg >= X_XMM0) {
    if (!n) { x86_reg_op(ctx, -1, false, OP2(0x0f, 0x57), reg - X_XMM0, reg - X_XMM0, false); return; } /* xorps */
    x86_move_immediate(ctx, X_R10, n);
    x86_mov(ctx, reg, X_R10);
    return;
  }
  if (!n) { x86_reg_op(ctx, -1, false, OP1(0x31), reg, reg, false); return; } /* xor r32, r32 */
  if (n <= UINT32_MAX) { if (reg >= 8) byte(ctx, 0x41); byte(ctx, 0xb8 + (reg & 7)); word(ctx, (uint32_t)n); return; }
  if ((int64_t)n >= INT32_MIN && (int64_t)n <= INT32_MAX) {
    x86_reg_op(ctx, -1, true, OP1(0xc7), 0, reg, false); word(ctx, (uint32_t)n); return;
  }
  byte(ctx, 0x48 | (reg >> 3 & 1)); byte(ctx, 0xb8 + (reg & 7)); immediate(ctx, n);
}
static bool ssa_imm32(Ssa *s, int32_t id, int32_t *out) {
  uint64_t c;
  if (!ssa_is_const(s, id, &c) || (int64_t)c < INT32_MIN || (int64_t)c > INT32_MAX) return false;
  *out = (int32_t)c;
  return true;
}
static SsaMemory ssa_slot_memory(SsaEmit *e, const SsaValue *v) {
  return (SsaMemory){X_RBP, -1, 1, (int32_t)(e->spill_base - 8 * (uint32_t)v->slot)};
}
/* A register holding the value: its own, or `scratch` after a reload. */
static unsigned ssa_get(SsaEmit *e, int32_t id, unsigned scratch) {
  Ssa *s = e->s; BackendContext *ctx = e->ctx;
  SsaValue *v = &s->values[id];
  if (v->op == SO_CONST && !ssa_located(v)) {
    bool fl = v->cls == SC_F64 || v->cls == SC_F32;
    if (fl && scratch < X_XMM0) scratch = X_XMM0 + 15;
    x86_move_immediate(ctx, scratch, (uint64_t)v->aux);
    return scratch;
  }
  if (v->op == SO_FRAME) {
    x86_mem_op(ctx, -1, true, OP1(0x8d), scratch, (SsaMemory){X_RBP, -1, 1, (int32_t)v->aux}, false);
    return scratch;
  }
  if (v->reg >= 0) return (unsigned)v->reg;
  if (v->slot < 0) { e->ctx->text.failed = true; return scratch; }
  SsaMemory m = ssa_slot_memory(e, v);
  if (v->cls == SC_F64 || v->cls == SC_F32) {
    if (scratch < X_XMM0) scratch = X_XMM0 + 15;
    x86_mem_op(ctx, 0xf2, false, OP2(0x0f, 0x10), scratch - X_XMM0, m, false); /* movsd */
  } else x86_mem_op(ctx, -1, true, OP1(0x8b), scratch, m, false);
  return scratch;
}
/* Destination register; ssa_put stores it when the value is spilled. */
static unsigned ssa_target(SsaEmit *e, const SsaValue *v) {
  (void)e;
  if (v->reg >= 0) return (unsigned)v->reg;
  return v->cls == SC_F64 || v->cls == SC_F32 ? X_XMM0 + 15 : X_R11;
}
static void ssa_put(SsaEmit *e, const SsaValue *v, unsigned reg) {
  if (v->reg >= 0) { x86_mov(e->ctx, (unsigned)v->reg, reg); return; }
  if (v->slot < 0) return;
  SsaMemory m = ssa_slot_memory(e, v);
  if (reg >= X_XMM0) x86_mem_op(e->ctx, 0xf2, false, OP2(0x0f, 0x11), reg - X_XMM0, m, false);
  else x86_mem_op(e->ctx, -1, true, OP1(0x89), reg, m, false);
}
/* Memory operand for a value's address: frame addresses fold into RBP. */
static SsaMemory ssa_address_of(SsaEmit *e, int32_t base, int32_t index, unsigned scale, int64_t disp, unsigned base_scratch,
                                unsigned index_scratch) {
  Ssa *s = e->s;
  SsaMemory m = {X_RBP, -1, 1, 0};
  int64_t total = disp;
  if (base >= 0 && s->values[base].op == SO_FRAME) { total += s->values[base].aux; m.base = X_RBP; }
  else if (base >= 0) m.base = (int)ssa_get(e, base, base_scratch);
  uint64_t c;
  if (index >= 0 && ssa_is_const(s, index, &c) && (int64_t)(total + (int64_t)c * scale) == (int32_t)(total + (int64_t)c * scale)) {
    total += (int64_t)c * scale;
    index = -1;
  }
  if (index >= 0) { m.index = (int)ssa_get(e, index, index_scratch); m.scale = scale; }
  if (total != (int32_t)total) { e->ctx->text.failed = true; total = 0; }
  m.disp = (int32_t)total;
  if (m.index == X_RSP) e->ctx->text.failed = true;
  return m;
}
/* Parallel moves between registers, frame slots, outgoing stack slots and
   constants, resolving cycles through R11 or XMM15. */
enum { L_REG, L_SLOT, L_OUT, L_CONST, L_FRAME };
typedef struct { uint8_t dst_kind, src_kind, cls; int64_t dst, src; } SsaMove;
static SsaMove ssa_source(SsaEmit *e, int32_t id) {
  SsaValue *v = &e->s->values[id];
  SsaMove m = {0};
  m.cls = v->cls;
  if (v->op == SO_CONST && !ssa_located(v)) { m.src_kind = L_CONST; m.src = v->aux; }
  else if (v->op == SO_FRAME) { m.src_kind = L_FRAME; m.src = v->aux; }
  else if (v->reg >= 0) { m.src_kind = L_REG; m.src = v->reg; }
  else { m.src_kind = L_SLOT; m.src = ssa_slot_memory(e, v).disp; }
  return m;
}
static void ssa_destination(SsaEmit *e, SsaMove *m, int32_t id) {
  SsaValue *v = &e->s->values[id];
  if (v->reg >= 0) { m->dst_kind = L_REG; m->dst = v->reg; }
  else { m->dst_kind = L_SLOT; m->dst = ssa_slot_memory(e, v).disp; }
}
static bool ssa_float_class(uint8_t cls) { return cls == SC_F64 || cls == SC_F32; }
/* Moves one value between any two locations, with `via` as the scratch for
   memory-to-memory transfers. */
static void a64s_transfer(SsaEmit *e, uint8_t dst_kind, int64_t dst, uint8_t src_kind, int64_t src, uint8_t cls);
static void ssa_transfer(SsaEmit *e, uint8_t dst_kind, int64_t dst, uint8_t src_kind, int64_t src, uint8_t cls, unsigned via) {
  BackendContext *ctx = e->ctx;
  if (ctx->a64) { a64s_transfer(e, dst_kind, dst, src_kind, src, cls); return; }
  bool fl = ssa_float_class(cls);
  if (fl && via < X_XMM0) via = X_XMM0 + 14;
  unsigned reg;
  if (dst_kind == L_REG) reg = (unsigned)dst;
  else reg = via;
  if (src_kind == L_REG) { if (dst_kind == L_REG) { x86_mov(ctx, reg, (unsigned)src); return; } reg = (unsigned)src; }
  else if (src_kind == L_CONST) {
    int64_t value = src;
    if (dst_kind != L_REG && !fl && value == (int32_t)value) {
      SsaMemory m = {dst_kind == L_SLOT ? X_RBP : X_RSP, -1, 1, (int32_t)dst};
      x86_mem_op(ctx, -1, true, OP1(0xc7), 0, m, false); word(ctx, (uint32_t)value);
      return;
    }
    x86_move_immediate(ctx, reg, (uint64_t)value);
  } else if (src_kind == L_FRAME) {
    if (fl) { ctx->text.failed = true; return; }
    x86_mem_op(ctx, -1, true, OP1(0x8d), reg, (SsaMemory){X_RBP, -1, 1, (int32_t)src}, false);
  } else {
    SsaMemory m = {src_kind == L_SLOT ? X_RBP : X_RSP, -1, 1, (int32_t)src};
    if (fl) x86_mem_op(ctx, 0xf2, false, OP2(0x0f, 0x10), reg - X_XMM0, m, false);
    else x86_mem_op(ctx, -1, true, OP1(0x8b), reg, m, false);
  }
  if (dst_kind == L_REG) return;
  SsaMemory m = {dst_kind == L_SLOT ? X_RBP : X_RSP, -1, 1, (int32_t)dst};
  if (reg >= X_XMM0) x86_mem_op(ctx, 0xf2, false, OP2(0x0f, 0x11), reg - X_XMM0, m, false);
  else x86_mem_op(ctx, -1, true, OP1(0x89), reg, m, false);
}
static bool ssa_reads(const SsaMove *m, uint8_t kind, int64_t location) {
  return (m->src_kind == L_REG || m->src_kind == L_SLOT || m->src_kind == L_OUT) && m->src_kind == kind && m->src == location;
}
static void ssa_parallel(SsaEmit *e, SsaMove *moves, uint32_t count) {
  /* Drop moves onto themselves. */
  uint32_t n = 0;
  for (uint32_t i = 0; i < count; ++i)
    if (!(moves[i].dst_kind == moves[i].src_kind && moves[i].dst == moves[i].src)) moves[n++] = moves[i];
  while (n) {
    bool progress = false;
    for (uint32_t i = 0; i < n; ++i) {
      bool blocked = false;
      for (uint32_t j = 0; j < n && !blocked; ++j)
        if (j != i && ssa_reads(&moves[j], moves[i].dst_kind, moves[i].dst)) blocked = true;
      if (blocked) continue;
      ssa_transfer(e, moves[i].dst_kind, moves[i].dst, moves[i].src_kind, moves[i].src, moves[i].cls, X_R10);
      moves[i] = moves[--n];
      progress = true;
      break;
    }
    if (progress) continue;
    /* Every remaining move is in a cycle: park one destination's value. */
    SsaMove *m = &moves[0];
    bool fl = ssa_float_class(m->cls);
    unsigned temp = e->ctx->a64 ? (fl ? X_XMM0 + 31 : 16) : fl ? X_XMM0 + 15 : X_R11;
    ssa_transfer(e, L_REG, temp, m->dst_kind, m->dst, m->cls, X_R10);
    for (uint32_t j = 0; j < n; ++j)
      if (ssa_reads(&moves[j], m->dst_kind, m->dst)) { moves[j].src_kind = L_REG; moves[j].src = temp; }
  }
}
/* Branches to blocks: short forms when the first emission measured the
   target within reach. Code between a branch and its target only shrinks
   in the final emission, so a measured distance stays an upper bound. */
static void ssa_jump_to(SsaEmit *e, int condition, uint32_t block) {
  BackendContext *ctx = e->ctx;
  bool short_branch = false;
  if (e->measured_blocks && e->jump_count < e->measured_jump_count) {
    int64_t distance = (int64_t)e->measured_blocks[block] - (int64_t)e->measured_jumps[e->jump_count];
    short_branch = ctx->a64 ? condition >= 0 && distance > -(1 << 20) && distance < (1 << 20) : distance > -100 && distance < 100;
  }
  size_t at;
  if (short_branch && ctx->a64) { at = ctx->text.n; a64_word(ctx, 0x54000000u | a64_cond[condition]); }
  else if (short_branch) {
    byte(ctx, condition >= 0 ? 0x70 | (x86_jcc[condition] & 0x0f) : 0xeb);
    at = ctx->text.n; byte(ctx, 0);
  } else at = isa_branch(ctx, condition);
  e->jumps = ssa_grow(e->jumps, &e->jump_capacity, e->jump_count + 1, sizeof(*e->jumps), &e->s->failed);
  if (!e->s->failed) {
    e->jumps[e->jump_count].at = at; e->jumps[e->jump_count].block = block; e->jumps[e->jump_count++].short_branch = short_branch;
  }
}
/* Branch to the shared failure path of a check kind when `failure` holds. */
static void ssa_fail_when(SsaEmit *e, int failure, unsigned kind) {
  size_t at = isa_branch(e->ctx, failure);
  e->stub_uses = ssa_grow(e->stub_uses, &e->stub_use_capacity, e->stub_use_count + 1, sizeof(*e->stub_uses), &e->s->failed);
  if (!e->s->failed) { e->stub_uses[e->stub_use_count].at = at; e->stub_uses[e->stub_use_count++].kind = kind; }
}
/* Sets flags for a against b; returns the condition to use (swapped when
   the constant had to move to the right). */
static Cond ssa_compare_values(SsaEmit *e, int32_t a, int32_t b, Cond cond) {
  Ssa *s = e->s; BackendContext *ctx = e->ctx;
  int32_t imm;
  if (ssa_imm32(s, a, &imm) && !ssa_imm32(s, b, &imm)) { int32_t t = a; a = b; b = t; cond = ssa_swap(cond); }
  unsigned ra = ssa_get(e, a, X_R11);
  if (ssa_imm32(s, b, &imm)) {
    if (!imm) x86_reg_op(ctx, -1, true, OP1(0x85), ra, ra, false); /* test */
    else if (imm >= -128 && imm <= 127) { x86_reg_op(ctx, -1, true, OP1(0x83), 7, ra, false); byte(ctx, (uint8_t)imm); }
    else { x86_reg_op(ctx, -1, true, OP1(0x81), 7, ra, false); word(ctx, (uint32_t)imm); }
    return cond;
  }
  SsaValue *vb = &s->values[b];
  if (vb->reg < 0 && vb->slot >= 0) { x86_mem_op(ctx, -1, true, OP1(0x3b), ra, ssa_slot_memory(e, vb), false); return cond; }
  unsigned rb = ssa_get(e, b, X_R10);
  x86_reg_op(ctx, -1, true, OP1(0x39), rb, ra, false);
  return cond;
}
/* d = a op b for two-address integer instructions. */
static void ssa_alu(SsaEmit *e, SsaValue *v, unsigned extension, unsigned char opcode, bool commutative) {
  Ssa *s = e->s; BackendContext *ctx = e->ctx;
  int32_t a = v->a, b = v->b, imm;
  unsigned d = ssa_target(e, v);
  if (commutative && ssa_imm32(s, a, &imm) && !ssa_imm32(s, b, &imm)) { int32_t t = a; a = b; b = t; }
  if (ssa_imm32(s, b, &imm)) {
    x86_mov(ctx, d, ssa_get(e, a, d));
    if (imm >= -128 && imm <= 127) { x86_reg_op(ctx, -1, true, OP1(0x83), extension, d, false); byte(ctx, (uint8_t)imm); }
    else { x86_reg_op(ctx, -1, true, OP1(0x81), extension, d, false); word(ctx, (uint32_t)imm); }
    return;
  }
  SsaValue *vb = &s->values[b];
  if (vb->reg >= 0 && (unsigned)vb->reg == d && a != b) {
    if (commutative) { int32_t t = a; a = b; b = t; vb = &s->values[b]; }
    else { x86_mov(ctx, X_R10, d); x86_mov(ctx, d, ssa_get(e, a, d)); x86_reg_op(ctx, -1, true, OP1(opcode), d, X_R10, false); return; }
  }
  x86_mov(ctx, d, ssa_get(e, a, d));
  if (vb->op != SO_CONST && vb->op != SO_FRAME && vb->reg < 0) x86_mem_op(ctx, -1, true, OP1(opcode), d, ssa_slot_memory(e, vb), false);
  else x86_reg_op(ctx, -1, true, OP1(opcode), d, ssa_get(e, b, X_R10), false);
}
static void ssa_float_op(SsaEmit *e, SsaValue *v, unsigned char opcode, bool commutative) {
  Ssa *s = e->s; BackendContext *ctx = e->ctx;
  int prefix = v->cls == SC_F32 ? 0xf3 : 0xf2;
  int32_t a = v->a, b = v->b;
  unsigned d = ssa_target(e, v);
  SsaValue *vb = &s->values[b];
  if (vb->reg >= 0 && (unsigned)vb->reg == d && a != b) {
    if (commutative) { int32_t t = a; a = b; b = t; vb = &s->values[b]; }
    else { x86_mov(ctx, X_XMM0 + 14, d); x86_mov(ctx, d, ssa_get(e, a, d)); x86_reg_op(ctx, prefix, false, OP2(0x0f, opcode), d - X_XMM0, 14, false); return; }
  }
  x86_mov(ctx, d, ssa_get(e, a, d));
  if (vb->op != SO_CONST && vb->reg < 0) x86_mem_op(ctx, prefix, false, OP2(0x0f, opcode), d - X_XMM0, ssa_slot_memory(e, vb), false);
  else x86_reg_op(ctx, prefix, false, OP2(0x0f, opcode), d - X_XMM0, ssa_get(e, b, X_XMM0 + 14) - X_XMM0, false);
}
static void ssa_extend_register(BackendContext *ctx, unsigned d, unsigned source, unsigned bits, bool sign) {
  if (bits == 1) { x86_mov(ctx, d, source); x86_reg_op(ctx, -1, false, OP1(0x83), 4, d, false); byte(ctx, 1); }
  else if (bits == 8) x86_reg_op(ctx, -1, sign, sign ? OP2(0x0f, 0xbe) : OP2(0x0f, 0xb6), d, source, true);
  else if (bits == 16) x86_reg_op(ctx, -1, sign, sign ? OP2(0x0f, 0xbf) : OP2(0x0f, 0xb7), d, source, false);
  else if (bits == 32) { if (sign) x86_reg_op(ctx, -1, true, OP1(0x63), d, source, false); else x86_reg_op(ctx, -1, false, OP1(0x89), source, d, false); }
  else x86_mov(ctx, d, source);
}
static void ssa_setcc(BackendContext *ctx, unsigned d, int cond) {
  x86_reg_op(ctx, -1, false, OP2(0x0f, x86_setcc[cond]), 0, d, true);
}
static void ssa_fail_raw(SsaEmit *e, unsigned char jcc, unsigned kind) {
  BackendContext *ctx = e->ctx;
  CODE(0x0f, jcc);
  size_t at = ctx->text.n; word(ctx, 0);
  e->stub_uses = ssa_grow(e->stub_uses, &e->stub_use_capacity, e->stub_use_count + 1, sizeof(*e->stub_uses), &e->s->failed);
  if (!e->s->failed) { e->stub_uses[e->stub_use_count].at = at; e->stub_uses[e->stub_use_count++].kind = kind; }
}
enum { JCC_O = 0x80, JCC_B = 0x82 };
/* Copies size bytes from [r11] to [r10] through RCX, forwards or backwards. */
static void ssa_copy_words(BackendContext *ctx, uint32_t size, bool backward) {
  uint32_t at = backward ? size : 0, remaining = size;
  while (remaining) {
    unsigned width = remaining >= 8 ? 8 : remaining >= 4 ? 4 : remaining >= 2 ? 2 : 1;
    if (backward) at -= width;
    SsaMemory from = {X_R11, -1, 1, (int32_t)at}, to = {X_R10, -1, 1, (int32_t)at};
    int prefix = width == 2 ? 0x66 : -1;
    x86_mem_op(ctx, prefix, width == 8, width == 1 ? OP1(0x8a) : OP1(0x8b), X_RCX, from, false);
    x86_mem_op(ctx, prefix, width == 8, width == 1 ? OP1(0x88) : OP1(0x89), X_RCX, to, false);
    if (!backward) at += width;
    remaining -= width;
  }
}
static void ssa_copy_memory(SsaEmit *e, SsaValue *v) {
  BackendContext *ctx = e->ctx;
  uint32_t size = (uint32_t)v->aux;
  if (!size) return;
  if (size <= 64) {
    /* Destination in R10, source in R11; RCX carries the data. */
    SsaMove moves[2] = {ssa_source(e, v->a), ssa_source(e, v->b)};
    moves[0].dst_kind = moves[1].dst_kind = L_REG; moves[0].dst = X_R10; moves[1].dst = X_R11;
    moves[0].cls = moves[1].cls = SC_INT;
    if (moves[0].src_kind == L_REG && moves[0].src == X_R11 && moves[1].src_kind == L_REG && moves[1].src == X_R10) {
      x86_mov(ctx, X_RCX, X_R10); x86_mov(ctx, X_R10, X_R11); x86_mov(ctx, X_R11, X_RCX);
    } else if (moves[1].src_kind == L_REG && moves[1].src == X_R10) {
      ssa_transfer(e, L_REG, X_R11, moves[1].src_kind, moves[1].src, SC_INT, X_RCX);
      ssa_transfer(e, L_REG, X_R10, moves[0].src_kind, moves[0].src, SC_INT, X_RCX);
    } else {
      ssa_transfer(e, L_REG, X_R10, moves[0].src_kind, moves[0].src, SC_INT, X_RCX);
      ssa_transfer(e, L_REG, X_R11, moves[1].src_kind, moves[1].src, SC_INT, X_RCX);
    }
    if (v->aux2) { ssa_copy_words(ctx, size, false); return; }
    CODE(0x4d, 0x39, 0xda, 0x0f, 0x86); size_t forward = ctx->text.n; word(ctx, 0); /* cmp r10, r11; jbe */
    ssa_copy_words(ctx, size, true);
    byte(ctx, 0xe9); size_t done = ctx->text.n; word(ctx, 0);
    patch_word(ctx, forward, (uint32_t)(ctx->text.n - forward - 4));
    ssa_copy_words(ctx, size, false);
    patch_word(ctx, done, (uint32_t)(ctx->text.n - done - 4));
    return;
  }
  SsaMove moves[2] = {ssa_source(e, v->a), ssa_source(e, v->b)};
  moves[0].dst_kind = moves[1].dst_kind = L_REG; moves[0].dst = X_RDI; moves[1].dst = X_RSI;
  moves[0].cls = moves[1].cls = SC_INT;
  ssa_parallel(e, moves, 2);
  /* The tree emitter's memmove: backwards only when the ranges overlap with
     the destination above the source. */
  CODE(0xb9); word(ctx, size);
  CODE(0x48, 0x39, 0xf7, 0x0f, 0x86); size_t forward = ctx->text.n; word(ctx, 0);
  CODE(0x48, 0x8d, 0x8e); word(ctx, size);
  CODE(0x48, 0x39, 0xcf, 0xb9); word(ctx, size);
  CODE(0x0f, 0x83); size_t disjoint = ctx->text.n; word(ctx, 0);
  CODE(0x48, 0x81, 0xc6); word(ctx, size - 1); CODE(0x48, 0x81, 0xc7); word(ctx, size - 1);
  CODE(0xfd, 0xf3, 0xa4, 0xfc, 0xe9); size_t done = ctx->text.n; word(ctx, 0);
  patch_word(ctx, forward, (uint32_t)(ctx->text.n - forward - 4));
  patch_word(ctx, disjoint, (uint32_t)(ctx->text.n - disjoint - 4));
  CODE(0xfc, 0xf3, 0xa4);
  patch_word(ctx, done, (uint32_t)(ctx->text.n - done - 4));
}
static void ssa_zero_memory(SsaEmit *e, SsaValue *v) {
  BackendContext *ctx = e->ctx;
  uint32_t size = (uint32_t)v->aux;
  if (!size) return;
  if (size <= 64) {
    SsaMemory m = ssa_address_of(e, v->a, -1, 1, 0, X_R10, X_R11);
    uint32_t at = 0;
    while (at < size) {
      unsigned width = size - at >= 8 ? 8 : size - at >= 4 ? 4 : size - at >= 2 ? 2 : 1;
      SsaMemory slot = m; slot.disp += (int32_t)at;
      if (width == 1) { x86_mem_op(ctx, -1, false, OP1(0xc6), 0, slot, false); byte(ctx, 0); }
      else if (width == 2) { x86_mem_op(ctx, 0x66, false, OP1(0xc7), 0, slot, false); byte(ctx, 0); byte(ctx, 0); }
      else { x86_mem_op(ctx, -1, width == 8, OP1(0xc7), 0, slot, false); word(ctx, 0); }
      at += width;
    }
    return;
  }
  SsaMove move = ssa_source(e, v->a);
  ssa_transfer(e, L_REG, X_RDI, move.src_kind, move.src, SC_INT, X_R10);
  CODE(0x31, 0xc0, 0xb9); word(ctx, size); CODE(0xfc, 0xf3, 0xaa);
}
static void a64s_store_outgoing(SsaEmit *e, int32_t value, uint32_t offset, unsigned width);
static void ssa_call_emit(SsaEmit *e, SsaBlock *block, uint32_t *k) {
  Ssa *s = e->s; BackendContext *ctx = e->ctx;
  uint32_t id = block->values.items[*k];
  SsaValue *v = &s->values[id];
  SsaMove moves[1100]; uint32_t count = 0;
  if (v->count > 1000) { ctx->text.failed = true; return; }
  /* Memory-class arguments copy into the outgoing area first; registers
     still hold every other argument. */
  for (uint32_t i = 0; i < v->count; ++i) {
    int32_t value = (int32_t)s->lists[v->list + 3 * i], location = (int32_t)s->lists[v->list + 3 * i + 1];
    int32_t bytes = (int32_t)s->lists[v->list + 3 * i + 2];
    if (bytes <= 0) continue;
    SsaMove from = ssa_source(e, value);
    ssa_transfer(e, L_REG, X_R10, from.src_kind, from.src, SC_INT, X_R11);
    for (int32_t at = 0; at < bytes;) {
      unsigned width = bytes - at >= 8 ? 8 : bytes - at >= 4 ? 4 : bytes - at >= 2 ? 2 : 1;
      int prefix = width == 2 ? 0x66 : -1;
      x86_mem_op(ctx, prefix, width == 8, width == 1 ? OP1(0x8a) : OP1(0x8b), X_R11, (SsaMemory){X_R10, -1, 1, at}, true);
      x86_mem_op(ctx, prefix, width == 8, width == 1 ? OP1(0x88) : OP1(0x89), X_R11,
                 (SsaMemory){X_RSP, -1, 1, location - SSA_STACK + at}, true);
      at += (int32_t)width;
    }
  }
  for (uint32_t i = 0; i < v->count && ctx->a64; ++i) {
    int32_t value = (int32_t)s->lists[v->list + 3 * i], location = (int32_t)s->lists[v->list + 3 * i + 1];
    int32_t bytes = (int32_t)s->lists[v->list + 3 * i + 2];
    if (location < SSA_STACK || bytes > 0) continue;
    a64s_store_outgoing(e, value, (uint32_t)(location - SSA_STACK), bytes ? (unsigned)-bytes : 8);
  }
  for (uint32_t i = 0; i < v->count; ++i) {
    int32_t value = (int32_t)s->lists[v->list + 3 * i], location = (int32_t)s->lists[v->list + 3 * i + 1];
    int32_t bytes = (int32_t)s->lists[v->list + 3 * i + 2];
    if (bytes > 0 || (ctx->a64 && location >= SSA_STACK)) continue;
    SsaMove m = ssa_source(e, value);
    if (location >= SSA_STACK) { m.dst_kind = L_OUT; m.dst = location - SSA_STACK; }
    else if (location == SSA_TARGET || location == SSA_RESULT_POINTER) { m.dst_kind = L_REG; m.dst = ssa_location_register(ctx, location); }
    else if (location >= 8) { m.dst_kind = L_REG; m.dst = X_XMM0 + (location - 8); }
    else { m.dst_kind = L_REG; m.dst = ssa_location_register(ctx, location); }
    moves[count++] = m;
  }
  ssa_parallel(e, moves, count);
  if (v->aux2 == 2 && ctx->a64) a64_word(ctx, 0xd63f0120u); /* blr x9 */
  else if (v->aux2 == 2) CODE(0xff, 0xd0); /* call rax */
  else if (v->aux2 == 1) runtime_call(ctx, (unsigned)v->aux);
  else isa_call_symbol(ctx, (unsigned)v->aux);
  /* Results follow their call directly. */
  count = 0;
  while (*k + 1 < block->values.count && s->values[block->values.items[*k + 1]].op == SO_RESULT &&
         s->values[block->values.items[*k + 1]].a == (int32_t)id) {
    ++*k;
    SsaValue *r = &s->values[block->values.items[*k]];
    if (r->dead || (r->reg < 0 && r->slot < 0)) continue;
    SsaMove m = {.src_kind = L_REG, .src = ssa_result_register(ctx, r->aux), .cls = r->cls};
    ssa_destination(e, &m, (int32_t)block->values.items[*k]);
    moves[count++] = m;
  }
  ssa_parallel(e, moves, count);
}
static void ssa_frame_argument(SsaEmit *e, uint32_t offset) {
  x86_mem_op(e->ctx, -1, true, OP1(0x8d), X_RDI, (SsaMemory){X_RBP, -1, 1, (int32_t)offset}, false);
}
/* dyn_unwind_set, branching to the landing block when it returns again
   during unwinding, then dyn_unwind_link. */
static void ssa_protect_begin(SsaEmit *e, SsaBlock *block) {
  BackendContext *ctx = e->ctx;
  ssa_frame_argument(e, e->s->unwind_offset); runtime_call(ctx, 3);
  CODE(0x85, 0xc0);
  ssa_jump_to(e, CC_NE, block->succ[1]);
  ssa_frame_argument(e, e->s->unwind_offset); runtime_call(ctx, 4);
}
/* dyn_unwind_unlink, keeping the result registers. */
static void ssa_protect_end(SsaEmit *e) {
  BackendContext *ctx = e->ctx;
  int32_t at = (int32_t)e->s->results_offset;
  x86_mem_op(ctx, -1, true, OP1(0x89), X_RAX, (SsaMemory){X_RBP, -1, 1, at}, false);
  x86_mem_op(ctx, -1, true, OP1(0x89), X_RDX, (SsaMemory){X_RBP, -1, 1, at + 8}, false);
  x86_mem_op(ctx, 0xf2, false, OP2(0x0f, 0x11), 0, (SsaMemory){X_RBP, -1, 1, at + 16}, false);
  x86_mem_op(ctx, 0xf2, false, OP2(0x0f, 0x11), 1, (SsaMemory){X_RBP, -1, 1, at + 24}, false);
  ssa_frame_argument(e, e->s->unwind_offset); runtime_call(ctx, 5);
  x86_mem_op(ctx, -1, true, OP1(0x8b), X_RAX, (SsaMemory){X_RBP, -1, 1, at}, false);
  x86_mem_op(ctx, -1, true, OP1(0x8b), X_RDX, (SsaMemory){X_RBP, -1, 1, at + 8}, false);
  x86_mem_op(ctx, 0xf2, false, OP2(0x0f, 0x10), 0, (SsaMemory){X_RBP, -1, 1, at + 16}, false);
  x86_mem_op(ctx, 0xf2, false, OP2(0x0f, 0x10), 1, (SsaMemory){X_RBP, -1, 1, at + 24}, false);
}
static void ssa_emit_value(SsaEmit *e, SsaBlock *block, uint32_t *k) {
  Ssa *s = e->s; BackendContext *ctx = e->ctx;
  uint32_t id = block->values.items[*k];
  SsaValue *v = &s->values[id];
  if (v->dead && v->op != SO_CALL) return;
  unsigned d;
  int32_t imm, imm32_scratch = 0;
  switch (v->op) {
  case SO_CONST:
    if (ssa_located(v)) { d = ssa_target(e, v); x86_move_immediate(ctx, d, (uint64_t)v->aux); ssa_put(e, v, d); }
    return;
  case SO_RESULT:
    /* After a protected call, results arrive in the next block. */
    if (s->values[v->a].block != v->block && (v->reg >= 0 || v->slot >= 0)) {
      SsaMove m = {.src_kind = L_REG, .src = ssa_result_register(ctx, v->aux), .cls = v->cls};
      ssa_destination(e, &m, (int32_t)id);
      uint32_t count = 1;
      while (*k + count < block->values.count && s->values[block->values.items[*k + count]].op == SO_RESULT) ++count;
      SsaMove moves[4]; uint32_t n = 0;
      for (uint32_t j = 0; j < count && j < 4; ++j) {
        SsaValue *r = &s->values[block->values.items[*k + j]];
        if (r->dead || (r->reg < 0 && r->slot < 0)) continue;
        SsaMove move = {.src_kind = L_REG, .src = ssa_result_register(ctx, r->aux), .cls = r->cls};
        ssa_destination(e, &move, (int32_t)block->values.items[*k + j]);
        moves[n++] = move;
      }
      (void)m;
      ssa_parallel(e, moves, n);
      *k += count - 1;
    }
    return;
  case SO_FRAME: case SO_PHI: case SO_PARAM: case SO_COPY:
    return;
  case SO_ADD: {
    /* Three-address addition through LEA when the result has its own register. */
    SsaValue *x = &s->values[v->a], *y = &s->values[v->b];
    d = ssa_target(e, v);
    bool imm = ssa_imm32(s, v->b, &imm32_scratch);
    if (x->reg >= 0 && (unsigned)x->reg != d && (imm || (y->reg >= 0 && (unsigned)y->reg != d))) {
      SsaMemory m = imm ? (SsaMemory){x->reg, -1, 1, imm32_scratch} : (SsaMemory){x->reg, y->reg, 1, 0};
      if (m.index == X_RSP) { m.index = m.base; m.base = X_RSP; }
      x86_mem_op(ctx, -1, true, OP1(0x8d), d, m, false);
    } else ssa_alu(e, v, 0, 0x03, true);
    ssa_put(e, v, d);
    return;
  }
  case SO_SUB: ssa_alu(e, v, 5, 0x2b, false); ssa_put(e, v, ssa_target(e, v)); return;
  case SO_AND: ssa_alu(e, v, 4, 0x23, true); ssa_put(e, v, ssa_target(e, v)); return;
  case SO_OR: ssa_alu(e, v, 1, 0x0b, true); ssa_put(e, v, ssa_target(e, v)); return;
  case SO_XOR: ssa_alu(e, v, 6, 0x33, true); ssa_put(e, v, ssa_target(e, v)); return;
  case SO_ADDO: case SO_SUBO:
    ssa_alu(e, v, v->op == SO_ADDO ? 0 : 5, v->op == SO_ADDO ? 0x03 : 0x2b, v->op == SO_ADDO);
    ssa_fail_raw(e, v->aux2 ? JCC_O : JCC_B, GUARD_OVERFLOW);
    ssa_put(e, v, ssa_target(e, v));
    return;
  case SO_MUL: case SO_MULO: {
    if (v->op == SO_MULO && !v->aux2) {
      /* Unsigned checked multiply: MUL sets CF and OF on a high half. */
      unsigned rb = ssa_get(e, v->b, X_R11);
      if (rb != X_R11) x86_mov(ctx, X_R11, rb);
      x86_mov(ctx, X_RAX, ssa_get(e, v->a, X_RAX));
      CODE(0x49, 0xf7, 0xe3); /* mul r11 */
      ssa_fail_raw(e, JCC_O, GUARD_OVERFLOW);
      ssa_put(e, v, X_RAX);
      return;
    }
    d = ssa_target(e, v);
    int32_t a = v->a, b = v->b;
    if (ssa_imm32(s, a, &imm) && !ssa_imm32(s, b, &imm)) { int32_t t = a; a = b; b = t; }
    if (ssa_imm32(s, b, &imm)) {
      unsigned ra = ssa_get(e, a, d);
      x86_reg_op(ctx, -1, true, OP1(0x69), d, ra, false); word(ctx, (uint32_t)imm);
    } else {
      SsaValue *vb = &s->values[b];
      if (vb->reg >= 0 && (unsigned)vb->reg == d && a != b) { int32_t t = a; a = b; b = t; vb = &s->values[b]; }
      x86_mov(ctx, d, ssa_get(e, a, d));
      if (vb->op != SO_CONST && vb->reg < 0) x86_mem_op(ctx, -1, true, OP2(0x0f, 0xaf), d, ssa_slot_memory(e, vb), false);
      else x86_reg_op(ctx, -1, true, OP2(0x0f, 0xaf), d, ssa_get(e, b, X_R10), false);
    }
    if (v->op == SO_MULO) ssa_fail_raw(e, JCC_O, GUARD_OVERFLOW);
    ssa_put(e, v, d);
    return;
  }
  case SO_SHL: case SO_SHR: case SO_SAR: {
    unsigned extension = v->op == SO_SHL ? 4 : v->op == SO_SHR ? 5 : 7;
    d = ssa_target(e, v);
    uint64_t c;
    if (ssa_is_const(s, v->b, &c)) {
      x86_mov(ctx, d, ssa_get(e, v->a, d));
      x86_reg_op(ctx, -1, true, OP1(0xc1), extension, d, false); byte(ctx, (uint8_t)(c & 63));
    } else if (ctx->bmi2) {
      unsigned ra = ssa_get(e, v->a, X_R11), rc = ssa_get(e, v->b, X_R10);
      byte(ctx, 0xc4);
      byte(ctx, (~(d >> 3) & 1) << 7 | 1 << 6 | (~(ra >> 3) & 1) << 5 | 0x02);
      byte(ctx, 0x80 | (~rc & 15) << 3 | (v->op == SO_SHL ? 1 : v->op == SO_SHR ? 3 : 2));
      byte(ctx, 0xf7);
      byte(ctx, 0xc0 | (d & 7) << 3 | (ra & 7));
    } else {
      x86_mov(ctx, X_R11, ssa_get(e, v->a, X_R11));
      x86_mov(ctx, X_RCX, ssa_get(e, v->b, X_RCX));
      x86_reg_op(ctx, -1, true, OP1(0xd3), extension, X_R11, false);
      x86_mov(ctx, d, X_R11);
    }
    ssa_put(e, v, d);
    return;
  }
  case SO_DIV: case SO_REM: {
    unsigned rb = ssa_get(e, v->b, X_R11);
    if (rb != X_R11) x86_mov(ctx, X_R11, rb);
    x86_mov(ctx, X_RAX, ssa_get(e, v->a, X_RAX));
    if (v->aux2) CODE(0x48, 0x99, 0x49, 0xf7, 0xfb); /* cqo; idiv r11 */
    else CODE(0x31, 0xd2, 0x49, 0xf7, 0xf3); /* xor edx, edx; div r11 */
    ssa_put(e, v, v->op == SO_DIV ? X_RAX : X_RDX);
    return;
  }
  case SO_MULH: {
    unsigned rb = ssa_get(e, v->b, X_R11);
    if (rb != X_R11) x86_mov(ctx, X_R11, rb);
    x86_mov(ctx, X_RAX, ssa_get(e, v->a, X_RAX));
    if (v->aux2) CODE(0x49, 0xf7, 0xeb); /* imul r11: rdx:rax */
    else CODE(0x49, 0xf7, 0xe3); /* mul r11 */
    ssa_put(e, v, X_RDX);
    return;
  }
  case SO_NEG: case SO_NOT:
    d = ssa_target(e, v);
    x86_mov(ctx, d, ssa_get(e, v->a, d));
    x86_reg_op(ctx, -1, true, OP1(0xf7), v->op == SO_NEG ? 3 : 2, d, false);
    ssa_put(e, v, d);
    return;
  case SO_EXT:
    d = ssa_target(e, v);
    ssa_extend_register(ctx, d, ssa_get(e, v->a, d), (unsigned)v->aux, v->aux2 != 0);
    ssa_put(e, v, d);
    return;
  case SO_CMP: {
    if (v->fused) return;
    Cond cond = ssa_compare_values(e, v->a, v->b, (Cond)v->cond);
    d = ssa_target(e, v);
    ssa_setcc(ctx, d, cond);
    ssa_extend_register(ctx, d, d, 8, false);
    ssa_put(e, v, d);
    return;
  }
  case SO_FCMP: {
    bool f32 = s->values[v->a].cls == SC_F32;
    unsigned ra = ssa_get(e, v->a, X_XMM0 + 15), rb = ssa_get(e, v->b, X_XMM0 + 14);
    x86_reg_op(ctx, f32 ? -1 : 0x66, false, OP2(0x0f, 0x2e), ra - X_XMM0, rb - X_XMM0, false);
    static const unsigned char predicates[] = {0x94, 0x95, 0x92, 0x96, 0x97, 0x93};
    d = ssa_target(e, v);
    unsigned op = (unsigned)v->aux;
    x86_reg_op(ctx, -1, false, OP2(0x0f, predicates[op]), 0, d, true);
    x86_reg_op(ctx, -1, false, OP2(0x0f, op == 1 ? 0x9a : 0x9b), 0, X_R10, true);
    x86_reg_op(ctx, -1, false, OP1(op == 1 ? 0x08 : 0x20), X_R10, d, true);
    ssa_extend_register(ctx, d, d, 8, false);
    ssa_put(e, v, d);
    return;
  }
  case SO_FADD: ssa_float_op(e, v, 0x58, true); ssa_put(e, v, ssa_target(e, v)); return;
  case SO_FSUB: ssa_float_op(e, v, 0x5c, false); ssa_put(e, v, ssa_target(e, v)); return;
  case SO_FMUL: ssa_float_op(e, v, 0x59, true); ssa_put(e, v, ssa_target(e, v)); return;
  case SO_FDIV: ssa_float_op(e, v, 0x5e, false); ssa_put(e, v, ssa_target(e, v)); return;
  case SO_FNEG:
    d = ssa_target(e, v);
    x86_mov(ctx, d, ssa_get(e, v->a, d));
    x86_move_immediate(ctx, X_R11, v->cls == SC_F32 ? UINT64_C(0x80000000) : UINT64_C(1) << 63);
    x86_mov(ctx, X_XMM0 + 14, X_R11);
    x86_reg_op(ctx, -1, false, OP2(0x0f, 0x57), d - X_XMM0, 14, false);
    ssa_put(e, v, d);
    return;
  case SO_ITOF: {
    bool f32 = v->cls == SC_F32;
    int prefix = f32 ? 0xf3 : 0xf2;
    d = ssa_target(e, v);
    unsigned ra = ssa_get(e, v->a, X_R11);
    x86_reg_op(ctx, -1, false, OP2(0x0f, 0x57), d - X_XMM0, d - X_XMM0, false);
    if (v->aux) {
      /* Unsigned 64-bit: halve values with the top bit set, keeping a sticky
         low bit, convert, then double. */
      x86_mov(ctx, X_R11, ra);
      CODE(0x4d, 0x85, 0xdb, 0x0f, 0x89); size_t ordinary = ctx->text.n; word(ctx, 0); /* test r11, r11; jns */
      CODE(0x4d, 0x89, 0xda, 0x41, 0x83, 0xe2, 0x01, 0x49, 0xd1, 0xeb, 0x4d, 0x09, 0xd3); /* r10=r11&1; r11>>=1; r11|=r10 */
      x86_reg_op(ctx, prefix, true, OP2(0x0f, 0x2a), d - X_XMM0, X_R11, false);
      x86_reg_op(ctx, prefix, false, OP2(0x0f, 0x58), d - X_XMM0, d - X_XMM0, false);
      byte(ctx, 0xe9); size_t done = ctx->text.n; word(ctx, 0);
      patch_word(ctx, ordinary, (uint32_t)(ctx->text.n - ordinary - 4));
      x86_reg_op(ctx, prefix, true, OP2(0x0f, 0x2a), d - X_XMM0, X_R11, false);
      patch_word(ctx, done, (uint32_t)(ctx->text.n - done - 4));
    } else x86_reg_op(ctx, prefix, true, OP2(0x0f, 0x2a), d - X_XMM0, ra, false);
    ssa_put(e, v, d);
    return;
  }
  case SO_FTOI: {
    bool f32 = s->values[v->a].cls == SC_F32;
    int prefix = f32 ? 0xf3 : 0xf2;
    d = ssa_target(e, v);
    unsigned ra = ssa_get(e, v->a, X_XMM0 + 15);
    if (v->aux) {
      x86_mov(ctx, X_XMM0 + 15, ra);
      x86_move_immediate(ctx, X_R11, f32 ? UINT64_C(0x5f000000) : UINT64_C(0x43e0000000000000));
      x86_mov(ctx, X_XMM0 + 14, X_R11);
      x86_reg_op(ctx, f32 ? -1 : 0x66, false, OP2(0x0f, 0x2e), 15, 14, false);
      CODE(0x0f, 0x82); size_t ordinary = ctx->text.n; word(ctx, 0);
      x86_reg_op(ctx, prefix, false, OP2(0x0f, 0x5c), 15, 14, false);
      x86_reg_op(ctx, prefix, true, OP2(0x0f, 0x2c), X_R11, 15, false);
      x86_move_immediate(ctx, X_R10, UINT64_C(1) << 63);
      x86_reg_op(ctx, -1, true, OP1(0x31), X_R10, X_R11, false);
      byte(ctx, 0xe9); size_t done = ctx->text.n; word(ctx, 0);
      patch_word(ctx, ordinary, (uint32_t)(ctx->text.n - ordinary - 4));
      x86_reg_op(ctx, prefix, true, OP2(0x0f, 0x2c), X_R11, 15, false);
      patch_word(ctx, done, (uint32_t)(ctx->text.n - done - 4));
      x86_mov(ctx, d, X_R11);
    } else x86_reg_op(ctx, prefix, true, OP2(0x0f, 0x2c), d, ra - X_XMM0, false);
    ssa_put(e, v, d);
    return;
  }
  case SO_FCVT: {
    d = ssa_target(e, v);
    bool to32 = v->cls == SC_F32;
    x86_reg_op(ctx, to32 ? 0xf2 : 0xf3, false, OP2(0x0f, 0x5a), d - X_XMM0, ssa_get(e, v->a, X_XMM0 + 15) - X_XMM0, false);
    ssa_put(e, v, d);
    return;
  }
  case SO_BITS: {
    d = ssa_target(e, v);
    unsigned ra = ssa_get(e, v->a, d >= X_XMM0 ? X_R11 : X_XMM0 + 15);
    bool wide = v->cls == SC_F64 || s->values[v->a].cls == SC_F64;
    if (d >= X_XMM0) x86_reg_op(ctx, 0x66, wide, OP2(0x0f, 0x6e), d - X_XMM0, ra, false);
    else x86_reg_op(ctx, 0x66, wide, OP2(0x0f, 0x7e), ra - X_XMM0, d, false);
    ssa_put(e, v, d);
    return;
  }
  case SO_LOAD: {
    d = ssa_target(e, v);
    SsaMemory m = ssa_address_of(e, v->a, v->b, v->scale, v->aux, X_R10, X_R11);
    unsigned bits = v->aux2 & 0xff;
    bool sign = v->aux2 >> 8 & 1, fl = v->aux2 >> 9 & 1;
    if (fl) x86_mem_op(ctx, bits == 32 ? 0xf3 : 0xf2, false, OP2(0x0f, 0x10), d - X_XMM0, m, false);
    else if (bits == 8) x86_mem_op(ctx, -1, sign, sign ? OP2(0x0f, 0xbe) : OP2(0x0f, 0xb6), d, m, false);
    else if (bits == 16) x86_mem_op(ctx, -1, sign, sign ? OP2(0x0f, 0xbf) : OP2(0x0f, 0xb7), d, m, false);
    else if (bits == 32) x86_mem_op(ctx, -1, sign, sign ? OP1(0x63) : OP1(0x8b), d, m, false);
    else x86_mem_op(ctx, -1, true, OP1(0x8b), d, m, false);
    ssa_put(e, v, d);
    return;
  }
  case SO_STORE: {
    unsigned bits = v->aux2 & 0xff;
    bool fl = v->aux2 >> 9 & 1;
    SsaValue *value = &s->values[v->c];
    int32_t constant;
    bool immediate_store = !fl && ssa_imm32(s, v->c, &constant);
    unsigned rv = 0;
    bool base_scratch = v->a >= 0 && s->values[v->a].op != SO_FRAME && s->values[v->a].reg < 0;
    uint64_t c;
    bool index_scratch = v->b >= 0 && !ssa_is_const(s, v->b, &c) && s->values[v->b].reg < 0;
    bool value_scratch = !immediate_store && !fl && value->reg < 0;
    SsaMemory m;
    if (base_scratch && index_scratch && value_scratch) {
      unsigned base = ssa_get(e, v->a, X_R10), index = ssa_get(e, v->b, X_R11);
      x86_mem_op(ctx, -1, true, OP1(0x8d), X_R10, (SsaMemory){(int)base, (int)index, v->scale, 0}, false);
      m = (SsaMemory){X_R10, -1, 1, (int32_t)v->aux};
      rv = ssa_get(e, v->c, X_R11);
    } else {
      if (!immediate_store) rv = ssa_get(e, v->c, fl ? X_XMM0 + 15 : (base_scratch ? X_R11 : X_R10));
      m = ssa_address_of(e, v->a, v->b, v->scale, v->aux, value_scratch && rv == X_R10 ? X_R11 : X_R10,
                         value_scratch && rv == X_R11 ? X_R10 : X_R11);
    }
    if (fl) x86_mem_op(ctx, bits == 32 ? 0xf3 : 0xf2, false, OP2(0x0f, 0x11), rv - X_XMM0, m, false);
    else if (immediate_store) {
      if (bits == 8) { x86_mem_op(ctx, -1, false, OP1(0xc6), 0, m, false); byte(ctx, (uint8_t)constant); }
      else if (bits == 16) { x86_mem_op(ctx, 0x66, false, OP1(0xc7), 0, m, false); byte(ctx, (uint8_t)constant); byte(ctx, (uint8_t)(constant >> 8)); }
      else { x86_mem_op(ctx, -1, bits == 64, OP1(0xc7), 0, m, false); word(ctx, (uint32_t)constant); }
    } else if (bits == 8) x86_mem_op(ctx, -1, false, OP1(0x88), rv, m, true);
    else if (bits == 16) x86_mem_op(ctx, 0x66, false, OP1(0x89), rv, m, false);
    else x86_mem_op(ctx, -1, bits == 64, OP1(0x89), rv, m, false);
    return;
  }
  case SO_LEA: {
    d = ssa_target(e, v);
    SsaMemory m = ssa_address_of(e, v->a, v->b, v->scale, v->aux, X_R10, X_R11);
    if (m.index < 0 && !m.disp) x86_mov(ctx, d, (unsigned)m.base);
    else x86_mem_op(ctx, -1, true, OP1(0x8d), d, m, false);
    ssa_put(e, v, d);
    return;
  }
  case SO_SYMBOL: {
    d = ssa_target(e, v);
    bool got = v->aux2 != SYM_LOCAL;
    x86_rex(ctx, true, d, 0, 0, false);
    byte(ctx, got ? 0x8b : 0x8d); byte(ctx, 0x05 | (d & 7) << 3);
    relocate(ctx, (unsigned)v->aux, got ? R_X86_64_GOTPCREL : R_X86_64_PC32, got ? -4 : (int64_t)v->c - 4);
    word(ctx, 0);
    ssa_put(e, v, d);
    return;
  }
  case SO_CHECK: {
    Cond cond = ssa_compare_values(e, v->a, v->b, (Cond)v->cond);
    ssa_fail_when(e, cond ^ 1, (unsigned)v->aux);
    return;
  }
  case SO_VECTOR: {
    /* R11 walks the three frame arrays by byte offset; XMM14/15 carry lanes. */
    int32_t destination = (int32_t)s->values[v->a].aux, left = (int32_t)s->values[v->b].aux, right = (int32_t)s->values[v->c].aux;
    unsigned bytes = (unsigned)(v->aux2 >> 8), op = (unsigned)(v->aux2 & 0xff);
    uint32_t limit = (uint32_t)v->aux * bytes;
    x86_move_immediate(ctx, X_R11, 0);
    size_t begin = ctx->text.n;
    x86_mem_op(ctx, 0xf3, false, OP2(0x0f, 0x6f), 14, (SsaMemory){X_RBP, X_R11, 1, left}, false);
    x86_mem_op(ctx, 0xf3, false, OP2(0x0f, 0x6f), 15, (SsaMemory){X_RBP, X_R11, 1, right}, false);
    unsigned char opcode = op == DYN_OP_ADD ? (bytes == 8 ? 0xd4 : 0xfe) : op == DYN_OP_SUB ? (bytes == 8 ? 0xfb : 0xfa)
                         : op == DYN_OP_BIT_AND ? 0xdb : op == DYN_OP_BIT_OR ? 0xeb : 0xef;
    x86_reg_op(ctx, 0x66, false, OP2(0x0f, opcode), 14, 15, false);
    x86_mem_op(ctx, 0xf3, false, OP2(0x0f, 0x7f), 14, (SsaMemory){X_RBP, X_R11, 1, destination}, false);
    x86_reg_op(ctx, -1, true, OP1(0x83), 0, X_R11, false); byte(ctx, 16);
    x86_reg_op(ctx, -1, true, OP1(0x81), 7, X_R11, false); word(ctx, limit);
    isa_patch(ctx, isa_branch(ctx, CC_NE), begin);
    return;
  }
  case SO_TRAP: isa_trap(ctx); return;
  case SO_COPYMEM: ssa_copy_memory(e, v); return;
  case SO_ZEROMEM: ssa_zero_memory(e, v); return;
  case SO_CALL:
    if (v->cond) { ssa_protect_begin(e, block); ssa_call_emit(e, block, k); ssa_protect_end(e); }
    else ssa_call_emit(e, block, k);
    return;
  case SO_FAIL: {
    const char *name = function_name(s->f);
    size_t length = strlen(name);
    if (length > 800) length = 800;
    isa_string_arguments(ctx, literal(ctx, name, length), (size_t)v->aux << 24 | length);
    runtime_call(ctx, RUNTIME_CHECK_FAILED);
    isa_trap(ctx);
    return;
  }
  case SO_CONTINUE: runtime_call(ctx, 6); isa_trap(ctx); return;
  case SO_PANIC: {
    SsaMove moves[2] = {ssa_source(e, v->a), ssa_source(e, v->b)};
    moves[0].dst_kind = moves[1].dst_kind = L_REG; moves[0].dst = X_RDI; moves[1].dst = X_RSI;
    moves[0].cls = moves[1].cls = SC_INT;
    if (v->cond) ssa_protect_begin(e, block);
    ssa_parallel(e, moves, 2);
    runtime_call(ctx, 0);
    isa_trap(ctx);
    return;
  }
  default:
    ctx->text.failed = true;
    return;
  }
}
#include "ssa_a64.inc"
/* A comparison used only by its block's branch is emitted at the branch. */
static void ssa_fuse(Ssa *s, const uint32_t *order, uint32_t n) {
  for (uint32_t i = 0; i < n; ++i) {
    SsaBlock *block = &s->blocks[order[i]];
    if (block->kind != SB_IF || block->control < 0) continue;
    SsaValue *v = &s->values[block->control];
    if (v->op != SO_CMP || v->uses != 1 || v->block != order[i]) continue;
    v->fused = true;
    /* Keep it last so its operands stay live to the branch. */
    for (uint32_t k = 0; k < block->values.count; ++k) {
      if (block->values.items[k] != (uint32_t)block->control) continue;
      memmove(&block->values.items[k], &block->values.items[k + 1], (block->values.count - k - 1) * sizeof(uint32_t));
      block->values.items[block->values.count - 1] = (uint32_t)block->control;
      break;
    }
  }
}
static void ssa_phi_moves(SsaEmit *e, uint32_t from, uint32_t to) {
  Ssa *s = e->s;
  SsaBlock *target = &s->blocks[to];
  uint32_t index = UINT32_MAX;
  for (uint32_t p = 0; p < target->preds.count; ++p) if (target->preds.items[p] == from) { index = p; break; }
  if (index == UINT32_MAX) return;
  SsaMove stack_moves[64], *moves = stack_moves;
  uint32_t count = 0, capacity = 64;
  for (uint32_t k = 0; k < target->values.count; ++k) {
    uint32_t id = target->values.items[k];
    SsaValue *phi = &s->values[id];
    if (phi->op != SO_PHI) break;
    if (phi->dead || (phi->reg < 0 && phi->slot < 0)) continue;
    if (count == capacity) {
      SsaMove *grown = malloc(2 * capacity * sizeof(SsaMove));
      if (!grown) { s->failed = true; return; }
      memcpy(grown, moves, count * sizeof(SsaMove));
      if (moves != stack_moves) free(moves);
      moves = grown; capacity *= 2;
    }
    SsaMove m = ssa_source(e, (int32_t)s->lists[phi->list + index]);
    m.cls = phi->cls;
    ssa_destination(e, &m, (int32_t)id);
    moves[count++] = m;
  }
  ssa_parallel(e, moves, count);
  if (moves != stack_moves) free(moves);
}
static void ssa_epilogue(SsaEmit *e) {
  BackendContext *ctx = e->ctx;
  unsigned k = 0;
  if (ctx->a64) {
    for (unsigned r = 0; r < 32; ++r)
      if (e->alloc->used_callee >> r & 1)
        a64s_slot_access(ctx, false, r, (SsaMemory){A64_FP, -1, 1, (int32_t)(e->save_base - 8 * k++)});
    a64_word(ctx, 0x910003bfu); /* mov sp, x29 */
    a64_word(ctx, 0xa8c17bfdu); /* ldp x29, x30, [sp], #16 */
    a64_word(ctx, 0xd65f03c0u); /* ret */
    return;
  }
  for (unsigned r = 0; r < 16; ++r) {
    if (!(e->alloc->used_callee >> r & 1)) continue;
    x86_mem_op(ctx, -1, true, OP1(0x8b), r, (SsaMemory){X_RBP, -1, 1, (int32_t)(e->save_base - 8 * k++)}, false);
  }
  CODE(0xc9, 0xc3); /* leave; ret */
}
static bool ssa_emit_function(SsaEmit *e, const uint32_t *order, uint32_t n) {
  Ssa *s = e->s; BackendContext *ctx = e->ctx;
  SsaAlloc *a = e->alloc;
  unsigned saves = 0;
  for (unsigned r = 0; r < 32; ++r) saves += a->used_callee >> r & 1;
  uint32_t frame = (s->frame + 7) / 8 * 8;
  e->save_base = 0u - frame - 8;
  e->spill_base = 0u - frame - 8 * saves - 8;
  uint64_t total = (uint64_t)frame + 8 * saves + 8 * (uint64_t)a->spill_slots + s->outgoing;
  total = (total + 15) / 16 * 16;
  if (total > MAX_AGGREGATE + (1u << 20)) return false;
  e->frame_bytes = (uint32_t)total;
  for (unsigned i = 0; i < GUARD_COUNT; ++i) e->stubs[i] = SIZE_MAX;
  unsigned k = 0;
  if (ctx->a64) {
    a64_word(ctx, 0xa9bf7bfdu); /* stp x29, x30, [sp, #-16]! */
    a64_word(ctx, 0x910003fdu); /* mov x29, sp */
    if (total) a64_sp_adjust(ctx, -(int64_t)total);
    for (unsigned r = 0; r < 32; ++r)
      if (a->used_callee >> r & 1)
        a64s_slot_access(ctx, true, r, (SsaMemory){A64_FP, -1, 1, (int32_t)(e->save_base - 8 * k++)});
  } else {
    CODE(0x55, 0x48, 0x89, 0xe5); /* push rbp; mov rbp, rsp */
    x86_stack_adjust(ctx, -(int64_t)total);
    for (unsigned r = 0; r < 16; ++r) {
      if (!(a->used_callee >> r & 1)) continue;
      x86_mem_op(ctx, -1, true, OP1(0x89), r, (SsaMemory){X_RBP, -1, 1, (int32_t)(e->save_base - 8 * k++)}, false);
    }
  }
  /* Parameters leave the argument registers together. */
  SsaBlock *entry = &s->blocks[order[0]];
  SsaMove moves[600]; uint32_t count = 0;
  for (uint32_t i = 0; i < entry->values.count && count < 600; ++i) {
    SsaValue *v = &s->values[entry->values.items[i]];
    if (v->op != SO_PARAM) continue;
    if (v->dead || (v->reg < 0 && v->slot < 0)) continue;
    SsaMove m = {.src_kind = L_REG, .cls = v->cls};
    m.src = ssa_location_register(ctx, (int)v->aux);
    ssa_destination(e, &m, (int32_t)entry->values.items[i]);
    moves[count++] = m;
  }
  ssa_parallel(e, moves, count);
  for (uint32_t i = 0; i < n && !ctx->text.failed && !s->failed; ++i) {
    uint32_t b = order[i];
    SsaBlock *block = &s->blocks[b];
    /* Loop headers start on a 16-byte boundary, so short loops do not
       straddle fetch lines; the padding is one multi-byte NOP run. */
    if (!ctx->a64) {
      bool header = false;
      for (uint32_t p = 0; p < block->preds.count && !header; ++p) header = s->blocks[block->preds.items[p]].order >= block->order;
      if (header) {
        static const unsigned char nops[][9] = {{0x90}, {0x66, 0x90}, {0x0f, 0x1f, 0x00}, {0x0f, 0x1f, 0x40, 0x00},
          {0x0f, 0x1f, 0x44, 0x00, 0x00}, {0x66, 0x0f, 0x1f, 0x44, 0x00, 0x00}, {0x0f, 0x1f, 0x80, 0x00, 0x00, 0x00, 0x00},
          {0x0f, 0x1f, 0x84, 0x00, 0x00, 0x00, 0x00, 0x00}, {0x66, 0x0f, 0x1f, 0x84, 0x00, 0x00, 0x00, 0x00, 0x00}};
        unsigned pad = (unsigned)(-ctx->text.n & 15);
        while (pad) { unsigned n = pad > 9 ? 9 : pad; code(ctx, nops[n - 1], n); pad -= n; }
      }
    }
    block->at = ctx->text.n;
    for (uint32_t k = 0; k < block->values.count; ++k) {
      if (ctx->a64) a64s_emit_value(e, block, &k);
      else ssa_emit_value(e, block, &k);
    }
    uint32_t next = i + 1 < n ? order[i + 1] : UINT32_MAX;
    if (block->kind == SB_PLAIN) {
      ssa_phi_moves(e, b, block->succ[0]);
      SsaBlock *target = &s->blocks[block->succ[0]];
      /* A back edge to a header that only compares and branches repeats the
         comparison here, saving a jump per iteration (loop rotation). */
      bool rotate = block->succ[0] != next && target->order < block->order && target->kind == SB_IF &&
                    s->values[target->control].fused;
      for (uint32_t k = 0; rotate && k < target->values.count; ++k) {
        SsaValue *v = &s->values[target->values.items[k]];
        rotate = v->op == SO_PHI || (int32_t)target->values.items[k] == target->control;
      }
      if (rotate) {
        SsaValue *c = &s->values[target->control];
        int cond = ctx->a64 ? a64s_compare(e, c->a, c->b, (Cond)c->cond) : ssa_compare_values(e, c->a, c->b, (Cond)c->cond);
        if (target->succ[1] == next) ssa_jump_to(e, cond, target->succ[0]);
        else if (target->succ[0] == next) ssa_jump_to(e, cond ^ 1, target->succ[1]);
        else { ssa_jump_to(e, cond, target->succ[0]); ssa_jump_to(e, -1, target->succ[1]); }
      } else if (block->succ[0] != next) ssa_jump_to(e, -1, block->succ[0]);
    } else if (block->kind == SB_IF) {
      SsaValue *c = &s->values[block->control];
      int cond;
      if (c->fused) cond = ctx->a64 ? a64s_compare(e, c->a, c->b, (Cond)c->cond) : ssa_compare_values(e, c->a, c->b, (Cond)c->cond);
      else if (ctx->a64) {
        a64_word(ctx, 0xf100001fu | a64s_get(e, block->control, A_S1) << 5);
        cond = CC_NE;
      } else {
        unsigned r = ssa_get(e, block->control, X_R11);
        x86_reg_op(ctx, -1, true, OP1(0x85), r, r, false);
        cond = CC_NE;
      }
      if (block->succ[1] == next) ssa_jump_to(e, cond, block->succ[0]);
      else if (block->succ[0] == next) ssa_jump_to(e, cond ^ 1, block->succ[1]);
      else { ssa_jump_to(e, cond, block->succ[0]); ssa_jump_to(e, -1, block->succ[1]); }
    } else if (block->kind == SB_CALL) {
      if (block->succ[0] != next) ssa_jump_to(e, -1, block->succ[0]);
    } else if (block->kind == SB_SWITCH) {
      /* index = control - minimum; out of range goes to the default target. */
      uint32_t entries = s->lists[block->table + 1], fallback = s->lists[block->table + 2];
      int64_t minimum = s->values[block->control2].aux;
      size_t at;
      if (ctx->a64) {
        a64s_mov(ctx, A_S1, a64s_get(e, block->control, A_S1));
        a64s_add_immediate(ctx, A_S1, A_S1, -minimum);
        a64_word(ctx, 0xf100001fu | (entries - 1) << 10 | A_S1 << 5);
        ssa_jump_to(e, CC_A, fallback);
        at = ctx->text.n;
        a64_word(ctx, 0x10000000u | A_S2);              /* adr x17, table */
        a64_word(ctx, 0xb8a07800u | A_S1 << 16 | A_S2 << 5 | A_S1); /* ldrsw x16, [x17, x16, lsl #2] */
        a64_word(ctx, 0x8b000000u | A_S1 << 16 | A_S2 << 5 | A_S1); /* add x16, x17, x16 */
        a64_word(ctx, 0xd61f0000u | A_S1 << 5);         /* br x16 */
      } else {
        x86_mov(ctx, X_R11, ssa_get(e, block->control, X_R11));
        if (minimum == (int32_t)minimum) { if (minimum) { x86_reg_op(ctx, -1, true, OP1(0x81), 5, X_R11, false); word(ctx, (uint32_t)minimum); } }
        else { x86_move_immediate(ctx, X_R10, (uint64_t)minimum); x86_reg_op(ctx, -1, true, OP1(0x29), X_R10, X_R11, false); }
        x86_reg_op(ctx, -1, true, OP1(0x81), 7, X_R11, false); word(ctx, entries - 1);
        ssa_jump_to(e, CC_A, fallback);
        CODE(0x4c, 0x8d, 0x15); at = ctx->text.n; word(ctx, 0); /* lea r10, [rip + table] */
        CODE(0x4f, 0x63, 0x1c, 0x9a);                    /* movsxd r11, [r10 + r11*4] */
        CODE(0x4d, 0x01, 0xd3, 0x41, 0xff, 0xe3);        /* add r11, r10; jmp r11 */
      }
      e->tables = ssa_grow(e->tables, &e->table_capacity, e->table_count + 1, sizeof(*e->tables), &s->failed);
      if (!s->failed) { e->tables[e->table_count].at = at; e->tables[e->table_count++].block = b; }
    } else if (block->kind == SB_RETURN) {
      SsaMove results[4]; uint32_t parts = 0;
      unsigned integers = 0, floats = 0;
      int32_t values[4] = {block->control, block->control2, block->control3, block->control4};
      for (unsigned p = 0; p < 4; ++p) {
        if (values[p] < 0) continue;
        SsaMove m = ssa_source(e, values[p]);
        m.dst_kind = L_REG;
        m.dst = ssa_float_class(m.cls) ? (int64_t)(X_XMM0 + floats++) : ssa_result_register(ctx, integers++);
        results[parts++] = m;
      }
      ssa_parallel(e, results, parts);
      ssa_epilogue(e);
    }
  }
  /* Shared failure paths, one per check kind. */
  for (uint32_t i = 0; i < e->stub_use_count; ++i) {
    unsigned kind = e->stub_uses[i].kind;
    if (e->stubs[kind] == SIZE_MAX) {
      e->stubs[kind] = ctx->text.n;
      const char *name = function_name(s->f);
      size_t length = strlen(name);
      if (length > 800) length = 800;
      size_t at = literal(ctx, name, length);
      isa_string_arguments(ctx, at, (size_t)kind << 24 | length);
      runtime_call(ctx, RUNTIME_CHECK_FAILED);
      isa_trap(ctx);
    }
    isa_patch(ctx, e->stub_uses[i].at, e->stubs[kind]);
  }
  /* Jump tables: 32-bit offsets of each target from the table start. */
  for (uint32_t i = 0; i < e->table_count && !s->failed; ++i) {
    while (ctx->text.n & 3) byte(ctx, ctx->a64 ? 0 : 0xcc);
    size_t table = ctx->text.n, at = e->tables[i].at;
    SsaBlock *block = &s->blocks[e->tables[i].block];
    uint32_t entries = s->lists[block->table + 1];
    for (uint32_t k = 0; k < entries; ++k) word(ctx, (uint32_t)(s->blocks[s->lists[block->table + 3 + k]].at - table));
    if (ctx->a64) {
      uint32_t delta = (uint32_t)(table - at);
      patch_word(ctx, at, 0x10000000u | (delta & 3) << 29 | (delta >> 2 & 0x7ffff) << 5 | A_S2);
    } else patch_word(ctx, at, (uint32_t)(table - (at + 4)));
  }
  for (uint32_t i = 0; i < e->jump_count; ++i) {
    size_t at = e->jumps[i].at, target = s->blocks[e->jumps[i].block].at;
    if (e->jumps[i].short_branch && ctx->a64) {
      int64_t delta = ((int64_t)target - (int64_t)at) / 4;
      if (delta >= (1 << 18) || delta < -(1 << 18)) { ctx->text.failed = true; continue; }
      patch_word(ctx, at, (uint32_t)ctx->text.data[at] | (uint32_t)ctx->text.data[at + 1] << 8 |
                          (uint32_t)ctx->text.data[at + 2] << 16 | (uint32_t)ctx->text.data[at + 3] << 24 |
                          ((uint32_t)delta & 0x7ffff) << 5);
      continue;
    }
    if (e->jumps[i].short_branch) {
      int64_t delta = (int64_t)target - (int64_t)(at + 1);
      if (delta < -128 || delta > 127) { ctx->text.failed = true; continue; }
      ctx->text.data[at] = (unsigned char)(int8_t)delta;
      continue;
    }
    isa_patch(ctx, at, target);
  }
  return !ctx->text.failed && !ctx->rodata.failed && !ctx->relocation_failed && !s->failed;
}

/* ---- Entry point ---- */

static bool ssa_enabled(BackendContext *ctx, const DynSource *source) {
  const DynOptimization *policy = source->context.optimization;
  if (ctx->debug_mode || ctx->dwarf || ctx->rv64 || ctx->win64 || ctx->winarm64) return false;
  if (policy && policy->level == 1) return false;
  const char *disabled = getenv("DYN_NO_SSA");
  return !disabled || !*disabled || !strcmp(disabled, "0");
}
static int ssa_function(BackendContext *ctx, const DynSource *source, const DynIrProgram *ir, const DynIrFunction *f) {
  if (!ssa_enabled(ctx, source)) return SSA_UNSUPPORTED;
  Ssa s = {.ctx = ctx, .ir = ir, .f = f, .current = UINT32_MAX};
  SsaAlloc alloc = {.s = &s};
  SsaEmit emit = {.alloc = &alloc, .s = &s, .ctx = ctx};
  uint32_t *order = NULL, n = 0;
  int result = SSA_UNSUPPORTED;
  size_t text = ctx->text.n, relocations = ctx->relocation_count, rodata = ctx->rodata.n;
  ssa_build(&s);
  if (s.unsupported && ctx->optimization_remarks)
    fprintf(stderr, "remark: %s: tree emitter (SSA stopped at ssa.inc:%u)\n", f->name, s.reason);
  if (s.unsupported || s.failed) goto done;
  ssa_resolve_all(&s);
  for (unsigned round = 0; round < 6 && !s.failed; ++round) {
    free(order);
    order = ssa_order(&s, &n);
    if (!order) goto done;
    ssa_dominators(&s, order, n);
    bool changed = ssa_fold(&s, order, n);
    ssa_resolve_all(&s);
    changed |= ssa_cse(&s, order, n);
    ssa_resolve_all(&s);
    changed |= ssa_prove(&s, order, n);
    if (!changed) break;
  }
  free(order);
  order = ssa_order(&s, &n);
  if (!order || s.failed) goto done;
  for (unsigned i = 0; i < n; ++i) {
    SsaBlock *block = &s.blocks[order[i]];
    for (uint32_t k = 0; k < block->values.count; ++k) s.values[block->values.items[k]].block = order[i];
  }
  ssa_divisions(&s, order, n);
  ssa_resolve_all(&s);
  if (ssa_hoist(&s, order, n)) {
    /* Hoisted copies of one computation meet in the same preheader. */
    ssa_dominators(&s, order, n);
    ssa_cse(&s, order, n);
    ssa_resolve_all(&s);
  }
  ssa_split_edges(&s);
  free(order);
  order = ssa_order(&s, &n);
  if (!order || s.failed) goto done;
  ssa_addressing(&s, order, n);
  ssa_dce(&s, order, n);
  ssa_fuse(&s, order, n);
  alloc.order = order; alloc.n = n;
  if (!ssa_intervals(&alloc) || s.failed) goto done;
  ssa_hints(&alloc);
  if (!ssa_allocate(&alloc) || s.failed) goto done;
  /* Measure, then emit again with short branches. */
  emit.start = ctx->text.n;
  size_t built_rodata = ctx->rodata.n;
  bool measured = ssa_emit_function(&emit, order, n);
  if (measured) {
    emit.measured_blocks = malloc(s.block_count * sizeof(size_t));
    emit.measured_jumps = malloc((emit.jump_count + 1) * sizeof(size_t));
    if (emit.measured_blocks && emit.measured_jumps) {
      for (uint32_t i = 0; i < n; ++i) emit.measured_blocks[order[i]] = s.blocks[order[i]].at;
      for (uint32_t i = 0; i < emit.jump_count; ++i) emit.measured_jumps[i] = emit.jumps[i].at;
      emit.measured_jump_count = emit.jump_count;
      ctx->text.n = text; ctx->relocation_count = relocations; ctx->rodata.n = built_rodata;
      emit.jump_count = emit.stub_use_count = emit.table_count = 0;
      measured = ssa_emit_function(&emit, order, n);
    }
  }
  if (measured) result = SSA_EMITTED;
  else {
    /* Roll back; the tree emitter takes the function instead. */
    ctx->text.n = text; ctx->relocation_count = relocations; ctx->rodata.n = rodata;
    ctx->text.failed = ctx->rodata.failed = ctx->relocation_failed = false;
  }
  if (result == SSA_EMITTED && source->context.optimization && source->context.optimization->remarks)
    fprintf(stderr, "remark: %s: SSA code generation, %u spill slots\n", f->name, alloc.spill_slots);
done:
  free(order);
  free(alloc.block_start); free(alloc.block_end); free(alloc.clobbers);
  free(emit.stub_uses); free(emit.jumps); free(emit.tables); free(emit.measured_blocks); free(emit.measured_jumps);
  ssa_free(&s);
  return result;
}
