/* ---- Function bodies on worker threads ----

   sema_program checks function bodies one after another, and each check
   appends to shared arrays: expressions (conversions, copies of constants),
   items, locals, and new pointer, array, slice and function types. A large
   program instead splits its functions into chunks that workers check at
   once, and commits the chunks in function order on the driver's thread,
   so every id comes out as the serial loop assigns it.

   A function's nodes (expressions, items, statements, case arms, patterns)
   are its own and dense: lowering appended each body in one run, so they
   fill one range of each array, and no other check reads them. A worker
   checks a function in place. What it appends goes to a region reserved
   for its chunk, past the shared count of each array, and its new types go
   to tables private to the chunk that start as copies of the shared ones.
   Before checking it copies the function's ranges; if the check needs what
   only the driver may do (SEMA_SERIAL_ONLY), reports anything, or fills its
   region, the worker copies them back and leaves the function to the
   driver. After a check it lists the fields that name its appended nodes
   or its new types.

   The commit, for each function in order, moves its appended nodes down to
   the shared counts, interns the types it created in the order it created
   them, rewrites the listed fields, and appends its constant expansions. A
   function the worker left is checked again, serially, with its appends
   placed above every region and then moved down the same way. Lifetime
   checks and diagnostics then follow as in the serial loop.
   DYN_SEMA_PARALLEL=0 keeps the serial loop; =1 uses workers for any
   program size, and =N uses N workers, for tests. */
#ifndef _WIN32
/* Below this many functions, starting workers costs more than it saves. */
enum { SEMA_PARALLEL_FUNCTIONS = 2048 };
enum { SEMA_EXPRS, SEMA_ITEMS, SEMA_STMTS, SEMA_ARMS, SEMA_PATTERNS, SEMA_KINDS };
/* What a field holds, for rewriting it at the commit. */
enum { SEMA_EXPR_ID, SEMA_ITEM_ID, SEMA_LOCAL_ID, SEMA_TYPE, SEMA_FN_TYPE_INDEX };
/* A field to rewrite: in array (SEMA_* above, or SEMA_KINDS for locals) at
   index, which counts from the start of the function's appended block when
   block is set; offset bytes into the node, 64 bits wide when wide is set. */
typedef struct { uint32_t index; uint8_t array, offset, holds, flags; } SemaFix;
enum { SEMA_FIX_BLOCK = 1, SEMA_FIX_WIDE = 2 };
typedef struct { uint32_t kind, index; } SemaCreated;
/* One function's result. */
typedef struct {
  bool serial;
  /* The ids its references use; at: where its nodes are now (see sema_room). */
  uint32_t expr_start, expr_end, item_start, item_end, local_start, local_end;
  uint32_t at[3];
  bool moved[3];
  uint32_t fix_start, fix_end;            /* chunk->fixes */
  uint32_t to[3];                         /* where the commit put its blocks */
  uint32_t created_start, created_end;    /* chunk->created */
  uint32_t expansion_start, expansion_end; /* chunk->expansions */
} SemaPart;
/* A run of functions with its own regions and private types. */
typedef struct {
  uint32_t first, last;
  uint32_t expr_region, expr_limit, item_region, item_limit, local_region, local_limit;
  SemaPart *parts;
  SemaFix *fixes; size_t fix_count, fix_capacity;
  SemaCreated *created; size_t created_count, created_capacity;
  struct DynAstExpansion *expansions; size_t expansion_count;
  /* The chunk's private types past the shared counts, kept for the commit. */
  DynAstPointer *pointers; DynAstArray *arrays; DynAstSlice *slices; DynAstFnType *fn_types; DynType *fn_type_params;
  uint32_t pointer_count, array_count, slice_count, fn_type_count, fn_type_param_count;
  DynType *map[4]; /* private type - base -> committed type, 0 until committed */
  bool failed;
} SemaChunk;
typedef struct {
  DynAstProgram *a;
  const DynSource *s;
  Sema *sema;
  SemaChunk *chunks;
  uint32_t chunk_count;
  atomic_uint next;
  /* Shared counts when the workers start. */
  uint32_t base_types[4], base_fn_type_params;
  /* Above every block: where blocks move to make room, and where a
     function the driver checks again appends. Per array: expressions,
     items, locals. */
  size_t free_at[3];
  /* Lowest address a block has moved to; nothing moves below the regions' end. */
  size_t moved_low[3];
  /* An allocation failed on some worker: the program fails as the serial
     loop's would, rather than being checked again serially. */
  atomic_bool out_of_memory;
} SemaPlan;
/* A function's node ranges [low, high) per kind. */
typedef struct { uint32_t low[SEMA_KINDS], high[SEMA_KINDS], count[SEMA_KINDS]; bool failed; } SemaRanges;
struct SemaWork {
  SemaPlan *plan;
  DynAstProgram w;
  Sema sema;
  SemaChunk *chunk;
  DynAstExpr *saved_exprs; size_t saved_expr_capacity;
  DynAstItem *saved_items; size_t saved_item_capacity;
  DynAstStmt *saved_stmts; size_t saved_stmt_capacity;
  DynAstCaseArm *saved_arms; size_t saved_arm_capacity;
  DynAstPattern *saved_patterns; size_t saved_pattern_capacity;
  DynAstParam *saved_params; size_t saved_param_capacity;
  DynDiagnosticCapture capture;
  bool aborted;
};
static void sema_work_abort(void) { sema_work->aborted = true; }
static void sema_out_of_memory(SemaPlan *plan) { atomic_store(&plan->out_of_memory, true); }
/* After an abort, the error type that stands for a step the worker may not
   take reads as memory running out: the function is checked again anyway. */
static void sema_work_out_of_memory(void) {
  if (!sema_work->aborted) sema_out_of_memory(sema_work->plan);
}
static bool sema_grow(void **array, size_t *capacity, size_t need, size_t element) {
  if (need <= *capacity) return true;
  size_t n = *capacity ? *capacity : 64;
  while (n < need) n *= 2;
  void *p = realloc(*array, n * element);
  if (!p) {
    if (sema_work) sema_out_of_memory(sema_work->plan);
    return false;
  }
  *array = p; *capacity = n;
  return true;
}
static void sema_work_created(unsigned kind, uint32_t index) {
  SemaChunk *c = sema_work->chunk;
  if (!sema_grow((void **)&c->created, &c->created_capacity, c->created_count + 1, sizeof(*c->created))) {
    sema_work->aborted = true;
    return;
  }
  c->created[c->created_count++] = (SemaCreated){kind, index};
}

/* ---- A function's ranges ---- */

static void sema_range_add(SemaRanges *r, unsigned kind, uint32_t id) {
  if (id < r->low[kind]) r->low[kind] = id;
  if (id + 1 > r->high[kind]) r->high[kind] = id + 1;
  ++r->count[kind];
}
static void sema_range_expr(SemaRanges *r, const DynAstProgram *a, DynExprId id, unsigned depth) {
  if (id == DYN_NO_EXPR || r->failed) return;
  if (id >= a->expression_count || depth > 4096) { r->failed = true; return; }
  sema_range_add(r, SEMA_EXPRS, id);
  const DynAstExpr *e = &a->expressions[id];
  sema_range_expr(r, a, e->left, depth + 1);
  sema_range_expr(r, a, e->right, depth + 1);
  if (e->kind == DYN_EXPR_SLICE) sema_range_expr(r, a, (DynExprId)e->integer, depth + 1);
  if (e->kind != DYN_EXPR_OFFSET && e->item_count) {
    if ((uint64_t)e->item_start + e->item_count > a->item_count) { r->failed = true; return; }
    for (uint32_t i = 0; i < e->item_count; ++i) {
      sema_range_add(r, SEMA_ITEMS, e->item_start + i);
      sema_range_expr(r, a, a->items[e->item_start + i].expression, depth + 1);
    }
  }
}
static void sema_range_block(SemaRanges *r, const DynAstProgram *a, uint32_t start, uint32_t count, unsigned depth) {
  if (depth > 4096 || (uint64_t)start + count > a->child_count) { r->failed = true; return; }
  for (uint32_t i = 0; i < count && !r->failed; ++i) {
    uint32_t id = a->children[start + i];
    if (id >= a->statement_count) { r->failed = true; return; }
    sema_range_add(r, SEMA_STMTS, id);
    const DynAstStmt *st = &a->statements[id];
    sema_range_expr(r, a, st->expression, depth + 1);
    sema_range_expr(r, a, st->target, depth + 1);
    sema_range_block(r, a, st->body_start, st->body_count, depth + 1);
    sema_range_block(r, a, st->else_start, st->else_count, depth + 1);
    if ((uint64_t)st->case_arm_start + st->case_arm_count > a->case_arm_count) { r->failed = true; return; }
    for (uint32_t k = 0; k < st->case_arm_count; ++k) {
      const DynAstCaseArm *arm = &a->case_arms[st->case_arm_start + k];
      sema_range_add(r, SEMA_ARMS, st->case_arm_start + k);
      if ((uint64_t)arm->pattern_start + arm->pattern_count > a->pattern_count) { r->failed = true; return; }
      for (uint32_t p = 0; p < arm->pattern_count; ++p) {
        sema_range_add(r, SEMA_PATTERNS, arm->pattern_start + p);
        sema_range_expr(r, a, a->patterns[arm->pattern_start + p].first, depth + 1);
        sema_range_expr(r, a, a->patterns[arm->pattern_start + p].last, depth + 1);
      }
      sema_range_block(r, a, arm->body_start, arm->body_count, depth + 1);
    }
  }
}
/* False when a range is not dense (some node in it is not the function's),
   which the parallel check relies on. */
static bool sema_ranges(SemaRanges *r, const DynAstProgram *a, const DynAstFn *fn) {
  for (unsigned k = 0; k < SEMA_KINDS; ++k) { r->low[k] = UINT32_MAX; r->high[k] = 0; r->count[k] = 0; }
  r->failed = false;
  if (!fn->foreign && !fn->interface_only) sema_range_block(r, a, fn->body_start, fn->body_count, 0);
  for (unsigned k = 0; k < SEMA_KINDS; ++k) {
    if (!r->count[k]) r->low[k] = r->high[k] = 0;
    else if (r->high[k] - r->low[k] != r->count[k]) r->failed = true;
  }
  return !r->failed;
}

/* ---- Rewriting references ---- */

/* How a function's references change at its commit: ids in its appended
   blocks move, and its private types become committed ones. */
typedef struct {
  uint32_t expr_from, expr_count, expr_to;
  uint32_t item_from, item_count, item_to;
  uint32_t local_from, local_count, local_to;
  SemaPlan *plan;
  SemaChunk *chunk; /* NULL: no private types */
} SemaShift;
static uint32_t sema_shift(uint32_t id, uint32_t from, uint32_t count, uint32_t to) {
  return id != UINT32_MAX && id - from < count ? id - from + to : id;
}
static bool sema_private_type(const SemaPlan *plan, DynType t) {
  return (dyn_type_is_pointer(t) && t - DYN_TYPE_POINTER_BASE >= plan->base_types[0]) ||
         (dyn_type_is_array(t) && t - DYN_TYPE_ARRAY_BASE >= plan->base_types[1]) ||
         (dyn_type_is_slice(t) && t - DYN_TYPE_SLICE_BASE >= plan->base_types[2]) ||
         (dyn_type_is_function(t) && t - DYN_TYPE_FN_BASE >= plan->base_types[3]);
}
/* A chunk's private type as the committed type it stands for. */
static DynType sema_commit_type(SemaPlan *plan, SemaChunk *c, DynType t) {
  if (!c || !sema_private_type(plan, t)) return t;
  unsigned kind; uint32_t index;
  if (dyn_type_is_pointer(t)) { kind = 0; index = t - DYN_TYPE_POINTER_BASE; }
  else if (dyn_type_is_array(t)) { kind = 1; index = t - DYN_TYPE_ARRAY_BASE; }
  else if (dyn_type_is_slice(t)) { kind = 2; index = t - DYN_TYPE_SLICE_BASE; }
  else { kind = 3; index = t - DYN_TYPE_FN_BASE; }
  uint32_t rel = index - plan->base_types[kind];
  uint32_t counts[4] = {c->pointer_count, c->array_count, c->slice_count, c->fn_type_count};
  if (rel >= counts[kind] || !c->map[kind]) return DYN_TYPE_ERROR;
  if (c->map[kind][rel]) return c->map[kind][rel];
  DynAstProgram *a = plan->a;
  DynType result = DYN_TYPE_ERROR;
  if (kind == 0) result = sema_intern_pointer(a, sema_commit_type(plan, c, c->pointers[rel].pointee), c->pointers[rel].is_const);
  else if (kind == 1) result = sema_intern_array(a, sema_commit_type(plan, c, c->arrays[rel].element), c->arrays[rel].length);
  else if (kind == 2) result = sema_intern_slice(a, sema_commit_type(plan, c, c->slices[rel].element), c->slices[rel].is_const);
  else {
    const DynAstFnType *fn = &c->fn_types[rel];
    DynType params[256];
    if (fn->param_count > 256) return DYN_TYPE_ERROR;
    for (uint32_t i = 0; i < fn->param_count; ++i) {
      DynType p = fn->param_start >= plan->base_fn_type_params
                      ? c->fn_type_params[fn->param_start - plan->base_fn_type_params + i]
                      : a->fn_type_params[fn->param_start + i];
      params[i] = sema_commit_type(plan, c, p);
    }
    result = sema_intern_fn_type_ex(a, params, fn->param_count, sema_commit_type(plan, c, fn->return_type), fn->variadic);
  }
  c->map[kind][rel] = result;
  return result;
}
static uint32_t sema_rewrite(const SemaShift *m, unsigned holds, uint32_t value) {
  switch (holds) {
  case SEMA_EXPR_ID: return sema_shift(value, m->expr_from, m->expr_count, m->expr_to);
  case SEMA_ITEM_ID: return sema_shift(value, m->item_from, m->item_count, m->item_to);
  case SEMA_LOCAL_ID: return sema_shift(value, m->local_from, m->local_count, m->local_to);
  case SEMA_TYPE: return sema_commit_type(m->plan, m->chunk, value);
  default: return sema_commit_type(m->plan, m->chunk, DYN_TYPE_FN_BASE + value) - DYN_TYPE_FN_BASE;
  }
}
static bool sema_type_operand(const DynAstExpr *e) {
  return e->kind == DYN_EXPR_CAST || e->kind == DYN_EXPR_BITCAST || e->kind == DYN_EXPR_OFFSET ||
         ((e->kind == DYN_EXPR_SIZE || e->kind == DYN_EXPR_ALIGN || e->kind == DYN_EXPR_TYPEOF ||
           e->kind == DYN_EXPR_LIMIT) && e->boolean);
}
/* What integer holds in an expression, or UINT32_MAX when nothing to rewrite. */
static unsigned sema_integer_holds(const DynAstExpr *e) {
  if (e->kind == DYN_EXPR_SLICE) return SEMA_EXPR_ID;
  if (e->kind == DYN_EXPR_NAME) return SEMA_LOCAL_ID;
  if (e->kind == DYN_EXPR_INDIRECT_CALL) return SEMA_FN_TYPE_INDEX;
  if (sema_type_operand(e)) return SEMA_TYPE;
  return UINT32_MAX;
}
/* The fields of a node, by number: a pointer to each and what it holds.
   Returns how many. */
typedef struct { void *value; unsigned holds; bool wide; } SemaField;
static uint32_t sema_field_get(const SemaField *f) {
  if (f->wide) { uint64_t v; memcpy(&v, f->value, sizeof(v)); return (uint32_t)v; }
  uint32_t v; memcpy(&v, f->value, sizeof(v)); return v;
}
static void sema_field_set(const SemaField *f, uint32_t value) {
  if (f->wide) { uint64_t v = value; memcpy(f->value, &v, sizeof(v)); }
  else memcpy(f->value, &value, sizeof(value));
}
static unsigned sema_fields(DynAstProgram *a, unsigned array, uint32_t index, SemaField out[5]) {
  switch (array) {
  case SEMA_EXPRS: {
    DynAstExpr *e = &a->expressions[index];
    unsigned n = 0;
    out[n++] = (SemaField){&e->left, SEMA_EXPR_ID, false};
    out[n++] = (SemaField){&e->right, SEMA_EXPR_ID, false};
    out[n++] = (SemaField){e->kind != DYN_EXPR_OFFSET ? &e->item_start : NULL, SEMA_ITEM_ID, false};
    unsigned holds = sema_integer_holds(e);
    /* integer is 64 bits wide; the ids and types it holds fit 32. */
    out[n++] = (SemaField){holds != UINT32_MAX ? &e->integer : NULL, holds, true};
    out[n++] = (SemaField){&e->type, SEMA_TYPE, false};
    return n;
  }
  case SEMA_ITEMS: out[0] = (SemaField){&a->items[index].expression, SEMA_EXPR_ID, false}; return 1;
  case SEMA_STMTS: {
    DynAstStmt *st = &a->statements[index];
    out[0] = (SemaField){&st->expression, SEMA_EXPR_ID, false};
    out[1] = (SemaField){&st->target, SEMA_EXPR_ID, false};
    out[2] = (SemaField){&st->local_id, SEMA_LOCAL_ID, false};
    out[3] = (SemaField){&st->declared_type, SEMA_TYPE, false};
    return 4;
  }
  case SEMA_ARMS: out[0] = (SemaField){&a->case_arms[index].local_id, SEMA_LOCAL_ID, false}; return 1;
  case SEMA_PATTERNS: {
    DynAstPattern *p = &a->patterns[index];
    out[0] = (SemaField){&p->first, SEMA_EXPR_ID, false};
    out[1] = (SemaField){&p->last, SEMA_EXPR_ID, false};
    out[2] = (SemaField){&p->type, SEMA_TYPE, false};
    return 3;
  }
  default: {
    DynAstLocal *local = &a->locals[index];
    out[0] = (SemaField){&local->type, SEMA_TYPE, false};
    out[1] = (SemaField){&local->untyped, SEMA_EXPR_ID, false};
    return 2;
  }
  }
}
_Static_assert(sizeof(DynType) == sizeof(uint32_t) && sizeof(DynExprId) == sizeof(uint32_t), "narrow fields are 32-bit");
/* Whether a field's value changes at the commit. */
static bool sema_needs_rewrite(const SemaShift *m, unsigned holds, uint32_t value) {
  switch (holds) {
  case SEMA_EXPR_ID: return value != UINT32_MAX && value - m->expr_from < m->expr_count;
  case SEMA_ITEM_ID: return value != UINT32_MAX && value - m->item_from < m->item_count;
  case SEMA_LOCAL_ID: return value != UINT32_MAX && value - m->local_from < m->local_count;
  case SEMA_TYPE: return sema_private_type(m->plan, value);
  default: return value >= m->plan->base_types[3];
  }
}
/* The function's record and parameters, which hold local ids. */
static void sema_rewrite_function(DynAstProgram *a, uint32_t f, const SemaShift *m) {
  DynAstFn *fn = &a->functions[f];
  /* The start of the function's locals may be the end of an empty run. */
  fn->local_start = sema_shift(fn->local_start, m->local_from, m->local_count + 1, m->local_to);
  fn->variadic_local_id = sema_shift(fn->variadic_local_id, m->local_from, m->local_count, m->local_to);
  for (uint32_t i = 0; i < fn->param_count; ++i) {
    DynAstParam *p = &a->params[fn->param_start + i];
    p->local_id = sema_shift(p->local_id, m->local_from, m->local_count, m->local_to);
  }
}
/* Rewrites every field of the function's ranges and its moved blocks. */
static void sema_rewrite_all(DynAstProgram *a, const SemaRanges *r, uint32_t f, const SemaShift *m) {
  SemaField fields[5];
  for (unsigned k = 0; k < SEMA_KINDS; ++k)
    for (uint32_t i = r->low[k]; i < r->high[k]; ++i) {
      unsigned n = sema_fields(a, k, i, fields);
      for (unsigned j = 0; j < n; ++j)
        if (fields[j].value) sema_field_set(&fields[j], sema_rewrite(m, fields[j].holds, sema_field_get(&fields[j])));
    }
  uint32_t blocks[3][2] = {{SEMA_EXPRS, m->expr_to}, {SEMA_ITEMS, m->item_to}, {SEMA_KINDS, m->local_to}};
  uint32_t lengths[3] = {m->expr_count, m->item_count, m->local_count};
  for (unsigned b = 0; b < 3; ++b)
    for (uint32_t i = 0; i < lengths[b]; ++i) {
      unsigned n = sema_fields(a, blocks[b][0], blocks[b][1] + i, fields);
      for (unsigned j = 0; j < n; ++j)
        if (fields[j].value) sema_field_set(&fields[j], sema_rewrite(m, fields[j].holds, sema_field_get(&fields[j])));
    }
  sema_rewrite_function(a, f, m);
}

/* ---- Worker side ---- */

/* The worker's view: the shared program with the chunk's regions as its
   counts and capacities, private type tables and expansions. */
static bool sema_chunk_open(SemaWork *k, SemaChunk *c) {
  SemaPlan *plan = k->plan;
  DynAstProgram *w = &k->w;
  w->expression_count = c->expr_region; w->expression_capacity = c->expr_limit;
  w->item_count = c->item_region; w->item_capacity = c->item_limit;
  w->local_count = c->local_region; w->local_capacity = c->local_limit;
  w->pointer_count = plan->base_types[0]; w->array_count = plan->base_types[1];
  w->slice_count = plan->base_types[2]; w->fn_type_count = plan->base_types[3];
  w->fn_type_param_count = plan->base_fn_type_params;
  w->expansion_count = 0;
  w->allocation_failed = w->type_capacity_exceeded = false;
  k->chunk = c;
  c->parts = calloc(c->last - c->first + 1, sizeof(*c->parts));
  if (!c->parts) sema_out_of_memory(plan);
  return c->parts != NULL;
}
#define SEMA_SAVE(k, saved, capacity, source, r, kind, back)                                        \
  do {                                                                                              \
    size_t _n = (r)->high[kind] - (r)->low[kind];                                                   \
    if (back) memcpy((source) + (r)->low[kind], (k)->saved, _n * sizeof(*(k)->saved));              \
    else if (_n) memcpy((k)->saved, (source) + (r)->low[kind], _n * sizeof(*(k)->saved));           \
  } while (0)
static bool sema_save(SemaWork *k, const SemaRanges *r, bool back) {
  DynAstProgram *w = &k->w;
  if (!back &&
      (!sema_grow((void **)&k->saved_exprs, &k->saved_expr_capacity, r->high[SEMA_EXPRS] - r->low[SEMA_EXPRS] + 1, sizeof(DynAstExpr)) ||
       !sema_grow((void **)&k->saved_items, &k->saved_item_capacity, r->high[SEMA_ITEMS] - r->low[SEMA_ITEMS] + 1, sizeof(DynAstItem)) ||
       !sema_grow((void **)&k->saved_stmts, &k->saved_stmt_capacity, r->high[SEMA_STMTS] - r->low[SEMA_STMTS] + 1, sizeof(DynAstStmt)) ||
       !sema_grow((void **)&k->saved_arms, &k->saved_arm_capacity, r->high[SEMA_ARMS] - r->low[SEMA_ARMS] + 1, sizeof(DynAstCaseArm)) ||
       !sema_grow((void **)&k->saved_patterns, &k->saved_pattern_capacity, r->high[SEMA_PATTERNS] - r->low[SEMA_PATTERNS] + 1, sizeof(DynAstPattern))))
    return false;
  SEMA_SAVE(k, saved_exprs, saved_expr_capacity, w->expressions, r, SEMA_EXPRS, back);
  SEMA_SAVE(k, saved_items, saved_item_capacity, w->items, r, SEMA_ITEMS, back);
  SEMA_SAVE(k, saved_stmts, saved_stmt_capacity, w->statements, r, SEMA_STMTS, back);
  SEMA_SAVE(k, saved_arms, saved_arm_capacity, w->case_arms, r, SEMA_ARMS, back);
  SEMA_SAVE(k, saved_patterns, saved_pattern_capacity, w->patterns, r, SEMA_PATTERNS, back);
  return true;
}
#undef SEMA_SAVE
static bool sema_fix_add(SemaChunk *c, uint32_t index, unsigned array, const void *node, const void *field,
                         unsigned holds, bool wide, bool block) {
  if (!sema_grow((void **)&c->fixes, &c->fix_capacity, c->fix_count + 1, sizeof(*c->fixes))) return false;
  c->fixes[c->fix_count++] = (SemaFix){index, (uint8_t)array, (uint8_t)((const char *)field - (const char *)node),
                                       (uint8_t)holds, (uint8_t)((block ? SEMA_FIX_BLOCK : 0) | (wide ? SEMA_FIX_WIDE : 0))};
  return true;
}
/* Lists the fields of the function's ranges and appended blocks that
   change at its commit. */
static bool sema_list_fixes(SemaChunk *c, DynAstProgram *w, const SemaRanges *r, const SemaShift *m) {
  const SemaPlan *plan = m->plan;
#define SEMA_IN(v, from, count) ((v) != UINT32_MAX && (uint32_t)(v) - (from) < (count))
#define SEMA_FIX(node, field, holds, wide)                                                                  \
  do {                                                                                                      \
    if (!sema_fix_add(c, block ? i - low : i, array, node, &(node)->field, holds, wide, block)) return false; \
  } while (0)
  for (unsigned pass = 0; pass < 2; ++pass) {
    bool block = pass == 1;
    /* Expressions: the function's range, then its appended block. */
    unsigned array = SEMA_EXPRS;
    uint32_t low = block ? m->expr_from : r->low[SEMA_EXPRS], high = block ? low + m->expr_count : r->high[SEMA_EXPRS];
    for (uint32_t i = low; i < high; ++i) {
      DynAstExpr *e = &w->expressions[i];
      if (SEMA_IN(e->left, m->expr_from, m->expr_count)) SEMA_FIX(e, left, SEMA_EXPR_ID, false);
      if (SEMA_IN(e->right, m->expr_from, m->expr_count)) SEMA_FIX(e, right, SEMA_EXPR_ID, false);
      if (e->kind != DYN_EXPR_OFFSET && SEMA_IN(e->item_start, m->item_from, m->item_count))
        SEMA_FIX(e, item_start, SEMA_ITEM_ID, false);
      unsigned holds = sema_integer_holds(e);
      if (holds != UINT32_MAX && sema_needs_rewrite(m, holds, (uint32_t)e->integer)) SEMA_FIX(e, integer, holds, true);
      if (sema_private_type(plan, e->type)) SEMA_FIX(e, type, SEMA_TYPE, false);
    }
    array = SEMA_ITEMS;
    low = block ? m->item_from : r->low[SEMA_ITEMS]; high = block ? low + m->item_count : r->high[SEMA_ITEMS];
    for (uint32_t i = low; i < high; ++i) {
      DynAstItem *item = &w->items[i];
      if (SEMA_IN(item->expression, m->expr_from, m->expr_count)) SEMA_FIX(item, expression, SEMA_EXPR_ID, false);
    }
    if (block) {
      array = SEMA_KINDS;
      low = m->local_from; high = low + m->local_count;
      for (uint32_t i = low; i < high; ++i) {
        DynAstLocal *local = &w->locals[i];
        if (sema_private_type(plan, local->type)) SEMA_FIX(local, type, SEMA_TYPE, false);
        if (SEMA_IN(local->untyped, m->expr_from, m->expr_count)) SEMA_FIX(local, untyped, SEMA_EXPR_ID, false);
      }
      continue;
    }
    array = SEMA_STMTS;
    for (uint32_t i = low = r->low[SEMA_STMTS]; i < r->high[SEMA_STMTS]; ++i) {
      DynAstStmt *st = &w->statements[i];
      if (SEMA_IN(st->expression, m->expr_from, m->expr_count)) SEMA_FIX(st, expression, SEMA_EXPR_ID, false);
      if (SEMA_IN(st->target, m->expr_from, m->expr_count)) SEMA_FIX(st, target, SEMA_EXPR_ID, false);
      if (SEMA_IN(st->local_id, m->local_from, m->local_count)) SEMA_FIX(st, local_id, SEMA_LOCAL_ID, false);
      if (sema_private_type(plan, st->declared_type)) SEMA_FIX(st, declared_type, SEMA_TYPE, false);
    }
    array = SEMA_ARMS;
    for (uint32_t i = low = r->low[SEMA_ARMS]; i < r->high[SEMA_ARMS]; ++i) {
      DynAstCaseArm *arm = &w->case_arms[i];
      if (SEMA_IN(arm->local_id, m->local_from, m->local_count)) SEMA_FIX(arm, local_id, SEMA_LOCAL_ID, false);
    }
    array = SEMA_PATTERNS;
    for (uint32_t i = low = r->low[SEMA_PATTERNS]; i < r->high[SEMA_PATTERNS]; ++i) {
      DynAstPattern *p = &w->patterns[i];
      if (SEMA_IN(p->first, m->expr_from, m->expr_count)) SEMA_FIX(p, first, SEMA_EXPR_ID, false);
      if (SEMA_IN(p->last, m->expr_from, m->expr_count)) SEMA_FIX(p, last, SEMA_EXPR_ID, false);
      if (sema_private_type(plan, p->type)) SEMA_FIX(p, type, SEMA_TYPE, false);
    }
  }
#undef SEMA_FIX
#undef SEMA_IN
  return true;
}
static void sema_check_part(SemaWork *k, uint32_t f) {
  SemaChunk *c = k->chunk;
  DynAstProgram *w = &k->w;
  SemaPart *part = &c->parts[f - c->first];
  DynAstFn *fn = &w->functions[f];
  SemaRanges r;
  part->serial = true;
  if (fn->body_pending || !sema_ranges(&r, w, fn) || !sema_save(k, &r, false) ||
      !sema_grow((void **)&k->saved_params, &k->saved_param_capacity, fn->param_count + 1, sizeof(*k->saved_params)))
    return;
  DynAstFn saved_fn = *fn;
  memcpy(k->saved_params, w->params + fn->param_start, fn->param_count * sizeof(*k->saved_params));
  uint32_t expressions = (uint32_t)w->expression_count, items = (uint32_t)w->item_count, locals = (uint32_t)w->local_count;
  uint32_t types[5] = {(uint32_t)w->pointer_count, (uint32_t)w->array_count, (uint32_t)w->slice_count,
                       (uint32_t)w->fn_type_count, (uint32_t)w->fn_type_param_count};
  size_t created = c->created_count, expansions = w->expansion_count, fixes = c->fix_count;
  k->aborted = false;
  dyn_diagnostic_capture = &k->capture;
  unsigned errors = 0;
  sema_check_function(&k->sema, w, k->plan->s, &errors, f, NULL);
  dyn_diagnostic_capture = NULL;
  if (w->allocation_failed && !k->aborted) sema_out_of_memory(k->plan);
  SemaShift m = {expressions, (uint32_t)w->expression_count - expressions, 0, items, (uint32_t)w->item_count - items, 0,
                 locals, (uint32_t)w->local_count - locals, 0, k->plan, c};
  if (!k->aborted && !errors && !k->capture.count && !w->allocation_failed && !w->type_capacity_exceeded &&
      sema_list_fixes(c, w, &r, &m)) {
    *part = (SemaPart){.expr_start = expressions, .expr_end = (uint32_t)w->expression_count,
                       .item_start = items, .item_end = (uint32_t)w->item_count,
                       .local_start = locals, .local_end = (uint32_t)w->local_count, .at = {expressions, items, locals},
                       .fix_start = (uint32_t)fixes, .fix_end = (uint32_t)c->fix_count,
                       .created_start = (uint32_t)created, .created_end = (uint32_t)c->created_count,
                       .expansion_start = (uint32_t)expansions, .expansion_end = (uint32_t)w->expansion_count};
    return;
  }
  (void)sema_save(k, &r, true);
  w->functions[f] = saved_fn;
  memcpy(w->params + saved_fn.param_start, k->saved_params, saved_fn.param_count * sizeof(*k->saved_params));
  w->expression_count = expressions; w->item_count = items; w->local_count = locals;
  w->pointer_count = types[0]; w->array_count = types[1]; w->slice_count = types[2];
  w->fn_type_count = types[3]; w->fn_type_param_count = types[4];
  w->allocation_failed = w->type_capacity_exceeded = false;
  c->created_count = created; w->expansion_count = expansions; c->fix_count = fixes;
  dyn_diagnostic_capture_free(&k->capture);
}
/* Keeps the chunk's private types and expansions for the commit. */
static bool sema_chunk_close(SemaWork *k, SemaChunk *c) {
  SemaPlan *plan = k->plan;
  DynAstProgram *w = &k->w;
#define SEMA_KEEP(field, count, base)                                                     \
  do {                                                                                    \
    c->count = (uint32_t)(w->count - (base));                                             \
    if (c->count) {                                                                       \
      c->field = malloc(c->count * sizeof(*c->field));                                    \
      if (!c->field) { sema_out_of_memory(plan); return false; }                          \
      memcpy(c->field, w->field + (base), c->count * sizeof(*c->field));                  \
    }                                                                                     \
  } while (0)
  SEMA_KEEP(pointers, pointer_count, plan->base_types[0]);
  SEMA_KEEP(arrays, array_count, plan->base_types[1]);
  SEMA_KEEP(slices, slice_count, plan->base_types[2]);
  SEMA_KEEP(fn_types, fn_type_count, plan->base_types[3]);
  SEMA_KEEP(fn_type_params, fn_type_param_count, plan->base_fn_type_params);
#undef SEMA_KEEP
  c->expansion_count = w->expansion_count;
  if (c->expansion_count) {
    c->expansions = malloc(c->expansion_count * sizeof(*c->expansions));
    if (!c->expansions) { sema_out_of_memory(plan); return false; }
    memcpy(c->expansions, w->expansions, c->expansion_count * sizeof(*c->expansions));
  }
  return true;
}
static void *sema_worker(void *argument) {
  SemaPlan *plan = argument;
  DynAstProgram *a = plan->a;
  SemaWork k = {.plan = plan, .w = *a, .sema = *plan->sema};
  /* Private tables: the shared types, then the chunk's own. */
  bool ok = true;
#define SEMA_PRIVATE(field, count, capacity)                                         \
  do {                                                                               \
    k.w.field = NULL; k.w.capacity = 0;                                              \
    if (ok && !sema_grow((void **)&k.w.field, &k.w.capacity, a->count + 64, sizeof(*a->field))) ok = false; \
    else if (ok && a->count) memcpy(k.w.field, a->field, a->count * sizeof(*a->field)); \
  } while (0)
  SEMA_PRIVATE(pointers, pointer_count, pointer_capacity);
  SEMA_PRIVATE(arrays, array_count, array_capacity);
  SEMA_PRIVATE(slices, slice_count, slice_capacity);
  SEMA_PRIVATE(fn_types, fn_type_count, fn_type_capacity);
  SEMA_PRIVATE(fn_type_params, fn_type_param_count, fn_type_param_capacity);
#undef SEMA_PRIVATE
  if (!ok) sema_out_of_memory(plan);
  k.w.expansions = NULL; k.w.expansion_capacity = 0;
  k.sema.program = &k.w;
  k.sema.locals = (SemaNames){0}; k.sema.indexed_locals = 0;
  k.sema.active_loops = NULL; k.sema.active_loop_count = k.sema.active_loop_capacity = 0;
  k.sema.mem_kinds = NULL; k.sema.mem_kind_count = 0; k.sema.late_vet = NULL;
  memset(&sema_report, 0, sizeof(sema_report));
  sema_work = &k;
  for (;;) {
    unsigned index = atomic_fetch_add(&plan->next, 1);
    if (index >= plan->chunk_count) break;
    SemaChunk *c = &plan->chunks[index];
    if (!ok || !sema_chunk_open(&k, c)) { c->failed = true; continue; }
    for (uint32_t f = c->first; f < c->last; ++f) sema_check_part(&k, f);
    if (!sema_chunk_close(&k, c)) c->failed = true;
  }
  sema_work = NULL;
  free(k.w.pointers); free(k.w.arrays); free(k.w.slices); free(k.w.fn_types); free(k.w.fn_type_params);
  free(k.w.expansions); free(k.saved_exprs); free(k.saved_items); free(k.saved_stmts); free(k.saved_arms);
  free(k.saved_patterns); free(k.saved_params); free(k.sema.active_loops);
  free(k.sema.locals.buckets); free(k.sema.locals.next);
  dyn_diagnostic_capture_free(&k.capture);
  return NULL;
}

/* ---- Commit ---- */

/* Copies count nodes of array k (0 expressions, 1 items, 2 locals) from
   from to to, growing the array to hold them. */
static bool sema_block_copy(DynAstProgram *a, unsigned k, size_t to, size_t from, size_t count) {
  if (!count || to == from) return true;
  if (k == 0) {
    if (!sema_grow((void **)&a->expressions, &a->expression_capacity, to + count, sizeof(*a->expressions))) return false;
    memmove(&a->expressions[to], &a->expressions[from], count * sizeof(*a->expressions));
  } else if (k == 1) {
    if (!sema_grow((void **)&a->items, &a->item_capacity, to + count, sizeof(*a->items))) return false;
    memmove(&a->items[to], &a->items[from], count * sizeof(*a->items));
  } else {
    if (!sema_grow((void **)&a->locals, &a->local_capacity, to + count, sizeof(*a->locals))) return false;
    memmove(&a->locals[to], &a->locals[from], count * sizeof(*a->locals));
  }
  return true;
}
static size_t *sema_count(DynAstProgram *a, unsigned k) {
  return k == 0 ? &a->expression_count : k == 1 ? &a->item_count : &a->local_count;
}
static uint32_t sema_part_length(const SemaPart *p, unsigned k) {
  return k == 0 ? p->expr_end - p->expr_start : k == 1 ? p->item_end - p->item_start : p->local_end - p->local_start;
}
/* Makes [start, end) of array k free of blocks not yet committed, those
   after function f of chunk ci, by moving them above everything. Blocks
   that never moved lie in function order, and moved ones lie at or above
   moved_low, so below that the first unmoved block past end ends the
   search. */
static bool sema_room(SemaPlan *plan, uint32_t ci, uint32_t f, unsigned k, size_t start, size_t end) {
  if (start == end) return true;
  for (uint32_t i = ci; i < plan->chunk_count; ++i) {
    SemaChunk *c = &plan->chunks[i];
    if (c->failed || !c->parts) continue;
    for (uint32_t g = i == ci ? f + 1 : c->first; g < c->last; ++g) {
      SemaPart *p = &c->parts[g - c->first];
      if (p->serial) continue;
      size_t at = p->at[k], length = sema_part_length(p, k);
      if (!p->moved[k] && at >= end && end <= plan->moved_low[k]) return true;
      if (!length || at >= end || at + length <= start) continue;
      size_t to = plan->free_at[k];
      if (!sema_block_copy(plan->a, k, to, at, length)) return false;
      p->at[k] = (uint32_t)to; p->moved[k] = true;
      plan->free_at[k] = to + length;
      if (to < plan->moved_low[k]) plan->moved_low[k] = to;
    }
  }
  return true;
}
static void sema_apply_fixes(SemaPlan *plan, SemaChunk *c, const SemaPart *part);
/* Function f, which a worker left, checked here with its appends above
   every block, then moved down like a worker's. */
static bool sema_commit_serial(SemaPlan *plan, uint32_t ci, unsigned *errors, uint32_t f, SemaLate *late) {
  DynAstProgram *a = plan->a;
  SemaRanges r;
  bool dense = sema_ranges(&r, a, &a->functions[f]);
  size_t at[3], base[3], length[3];
  for (unsigned k = 0; k < 3; ++k) {
    at[k] = *sema_count(a, k);
    base[k] = plan->free_at[k];
  }
  if (!dense ||
      !sema_grow((void **)&a->expressions, &a->expression_capacity, base[0] + 1024, sizeof(*a->expressions)) ||
      !sema_grow((void **)&a->items, &a->item_capacity, base[1] + 256, sizeof(*a->items)) ||
      !sema_grow((void **)&a->locals, &a->local_capacity, base[2] + 256, sizeof(*a->locals)))
    return false;
  for (unsigned k = 0; k < 3; ++k) *sema_count(a, k) = base[k];
  size_t expansions = a->expansion_count;
  sema_check_function(plan->sema, a, plan->s, errors, f, late);
  bool ok = !a->allocation_failed;
  for (unsigned k = 0; k < 3; ++k) {
    length[k] = *sema_count(a, k) - base[k];
    plan->free_at[k] = base[k] + length[k];
    *sema_count(a, k) = at[k];
  }
  for (unsigned k = 0; ok && k < 3; ++k) {
    ok = sema_room(plan, ci, f, k, at[k], at[k] + length[k]) && sema_block_copy(a, k, at[k], base[k], length[k]);
    *sema_count(a, k) = at[k] + length[k];
  }
  SemaShift m = {(uint32_t)base[0], (uint32_t)length[0], (uint32_t)at[0], (uint32_t)base[1], (uint32_t)length[1],
                 (uint32_t)at[1], (uint32_t)base[2], (uint32_t)length[2], (uint32_t)at[2], plan, NULL};
  if (ok) sema_rewrite_all(a, &r, f, &m);
  for (size_t i = expansions; ok && i < a->expansion_count; ++i) {
    struct DynAstExpansion *x = &a->expansions[i];
    x->expression = sema_shift(x->expression, m.expr_from, m.expr_count, m.expr_to);
    if (!x->global) x->target = sema_shift(x->target, m.local_from, m.local_count, m.local_to);
  }
  return ok;
}
static bool sema_commit_part(SemaPlan *plan, uint32_t ci, unsigned *errors, uint32_t f, SemaLate *late) {
  DynAstProgram *a = plan->a;
  SemaChunk *c = &plan->chunks[ci];
  SemaPart *part = &c->parts[f - c->first];
  for (uint32_t i = part->created_start; i < part->created_end; ++i) {
    static const DynType bases[4] = {DYN_TYPE_POINTER_BASE, DYN_TYPE_ARRAY_BASE, DYN_TYPE_SLICE_BASE, DYN_TYPE_FN_BASE};
    (void)sema_commit_type(plan, c, bases[c->created[i].kind] + c->created[i].index);
  }
  size_t to[3];
  for (unsigned k = 0; k < 3; ++k) {
    to[k] = *sema_count(a, k);
    uint32_t length = sema_part_length(part, k);
    if (!sema_room(plan, ci, f, k, to[k], to[k] + length) || !sema_block_copy(a, k, to[k], part->at[k], length))
      return false;
    *sema_count(a, k) = to[k] + length;
  }
  SemaShift m = {part->expr_start, part->expr_end - part->expr_start, (uint32_t)to[0],
                 part->item_start, part->item_end - part->item_start, (uint32_t)to[1],
                 part->local_start, part->local_end - part->local_start, (uint32_t)to[2], plan, c};
  for (unsigned k = 0; k < 3; ++k) part->to[k] = (uint32_t)to[k];
  sema_rewrite_function(a, f, &m);
  for (uint32_t i = part->expansion_start; i < part->expansion_end; ++i) {
    if (!sema_grow((void **)&a->expansions, &a->expansion_capacity, a->expansion_count + 1, sizeof(*a->expansions)))
      return false;
    struct DynAstExpansion x = c->expansions[i];
    x.expression = sema_shift(x.expression, m.expr_from, m.expr_count, m.expr_to);
    if (!x.global) x.target = sema_shift(x.target, m.local_from, m.local_count, m.local_to);
    a->expansions[a->expansion_count++] = x;
  }
  /* A lifetime check now reads the body, so its fixes go in first; one
     queued on late runs after the fixers. */
  DynAstFn *fn = &a->functions[f];
  if (fn->foreign || fn->interface_only) return !a->allocation_failed;
  if (!late || *errors || !fn->local_count || !sema_late_add(late, f)) {
    sema_apply_fixes(plan, c, part);
    part->fix_end = part->fix_start;
    if (!late || (!*errors && fn->local_count)) {
      plan->sema->current_function = f;
      life_check_function(plan->sema, a, plan->s, errors, fn);
      plan->sema->current_function = UINT32_MAX;
    }
  }
  return !a->allocation_failed;
}
/* Rewrites the fields a function's worker listed, once the commit has
   placed its blocks and committed its chunk's types. Functions touch
   different fields, so workers do this in parallel. */
static void sema_apply_fixes(SemaPlan *plan, SemaChunk *c, const SemaPart *part) {
  DynAstProgram *a = plan->a;
  SemaShift m = {part->expr_start, part->expr_end - part->expr_start, part->to[0],
                 part->item_start, part->item_end - part->item_start, part->to[1],
                 part->local_start, part->local_end - part->local_start, part->to[2], plan, c};
  for (uint32_t i = part->fix_start; i < part->fix_end; ++i) {
    const SemaFix *x = &c->fixes[i];
    bool block = x->flags & SEMA_FIX_BLOCK;
    char *node;
    if (x->array == SEMA_EXPRS) node = (char *)&a->expressions[x->index + (block ? m.expr_to : 0)];
    else if (x->array == SEMA_ITEMS) node = (char *)&a->items[x->index + (block ? m.item_to : 0)];
    else if (x->array == SEMA_STMTS) node = (char *)&a->statements[x->index];
    else if (x->array == SEMA_ARMS) node = (char *)&a->case_arms[x->index];
    else if (x->array == SEMA_PATTERNS) node = (char *)&a->patterns[x->index];
    else node = (char *)&a->locals[x->index + m.local_to];
    SemaField field = {node + x->offset, x->holds, x->flags & SEMA_FIX_WIDE};
    sema_field_set(&field, sema_rewrite(&m, x->holds, sema_field_get(&field)));
  }
}
static void *sema_fixer(void *argument) {
  SemaPlan *plan = argument;
  for (;;) {
    unsigned index = atomic_fetch_add(&plan->next, 1);
    if (index >= plan->chunk_count) break;
    SemaChunk *c = &plan->chunks[index];
    if (c->failed || !c->parts) continue;
    for (uint32_t f = c->first; f < c->last; ++f)
      if (!c->parts[f - c->first].serial) sema_apply_fixes(plan, c, &c->parts[f - c->first]);
  }
  return NULL;
}
static void sema_plan_free(SemaPlan *plan) {
  for (uint32_t i = 0; i < plan->chunk_count; ++i) {
    SemaChunk *c = &plan->chunks[i];
    free(c->parts); free(c->fixes); free(c->created); free(c->expansions);
    free(c->pointers); free(c->arrays); free(c->slices); free(c->fn_types); free(c->fn_type_params);
    for (unsigned k = 0; k < 4; ++k) free(c->map[k]);
  }
  free(plan->chunks);
}
/* How many workers check this program's bodies; 0 keeps the serial loop. */
static unsigned sema_parallel_workers(const DynAstProgram *a, const DynSource *s) {
  const char *setting = getenv("DYN_SEMA_PARALLEL");
  if (setting && *setting == '0') return 0;
  bool forced = setting && *setting >= '1' && *setting <= '9';
  /* vet records findings in lists the whole run shares. */
  if (s->context.work || s->context.vet || (!forced && a->function_count < SEMA_PARALLEL_FUNCTIONS)) return 0;
  long online = sysconf(_SC_NPROCESSORS_ONLN);
  if (forced && atoi(setting) > 1) return (unsigned)(atoi(setting) > 16 ? 16 : atoi(setting));
  if (online < 2) return forced ? 2 : 0;
  /* A worker per 1024 functions, at most 8: past that the commit dominates. */
  long workers = (long)(a->function_count / 1024) + 1;
  if (workers > online) workers = online;
  if (workers > 8) workers = 8;
  return workers < 2 ? 2 : (unsigned)workers;
}
/* Checks the functions there are now, [0, n), as the serial loop would,
   and returns n; 0 when it could not start, with nothing changed. The
   instances their checks create come after n. */
static uint32_t sema_parallel(Sema *sema, DynAstProgram *a, const DynSource *s, unsigned *errors, SemaLate *late) {
  unsigned workers = sema_parallel_workers(a, s);
  if (!workers) return 0;
  uint32_t n = (uint32_t)a->function_count;
  if (!n) return 0;
  /* Indexes the checks only read, built now so no worker builds them. */
  (void)sema_find_struct(a, (DynSpan){0}, s);
  (void)sema_find_enum(a, (DynSpan){0}, s);
  (void)dyn_ast_named_type(a, (DynSpan){0}, s);
  for (uint32_t i = 0; i < a->struct_count; ++i) (void)sema_find_field(a, i, (DynSpan){0}, s);
  for (uint32_t i = 0; i < a->enum_count; ++i) (void)sema_find_variant(a, i, (DynSpan){0}, s);
  if (a->allocation_failed) return 0;
  SemaPlan plan = {.a = a, .s = s, .sema = sema};
  plan.chunk_count = n < 4u * workers ? n : 4u * workers;
  plan.chunks = calloc(plan.chunk_count, sizeof(*plan.chunks));
  if (!plan.chunks) {
    a->allocation_failed = true;
    return n;
  }
  /* Regions: an even share of each array's current size plus slack, past the shared counts. */
  size_t expressions = a->expression_count, items = a->item_count, locals = a->local_count;
  size_t expr_share = expressions / plan.chunk_count + 1024, item_share = items / plan.chunk_count + 256;
  size_t local_share = (a->statement_count + a->param_count) / plan.chunk_count + 256;
  size_t top[3] = {expressions + expr_share * plan.chunk_count, items + item_share * plan.chunk_count,
                   locals + local_share * plan.chunk_count};
  if (top[0] > UINT32_MAX / 2 || top[1] > UINT32_MAX / 2 || top[2] > UINT32_MAX / 2) {
    free(plan.chunks);
    return 0;
  }
  if (!sema_grow((void **)&a->expressions, &a->expression_capacity, top[0] + 1024, sizeof(*a->expressions)) ||
      !sema_grow((void **)&a->items, &a->item_capacity, top[1] + 256, sizeof(*a->items)) ||
      !sema_grow((void **)&a->locals, &a->local_capacity, top[2] + 256, sizeof(*a->locals))) {
    free(plan.chunks);
    a->allocation_failed = true;
    return n;
  }
  for (uint32_t i = 0; i < plan.chunk_count; ++i) {
    SemaChunk *c = &plan.chunks[i];
    c->first = (uint32_t)((uint64_t)n * i / plan.chunk_count);
    c->last = (uint32_t)((uint64_t)n * (i + 1) / plan.chunk_count);
    c->expr_region = (uint32_t)(expressions + expr_share * i); c->expr_limit = (uint32_t)(c->expr_region + expr_share);
    c->item_region = (uint32_t)(items + item_share * i); c->item_limit = (uint32_t)(c->item_region + item_share);
    c->local_region = (uint32_t)(locals + local_share * i); c->local_limit = (uint32_t)(c->local_region + local_share);
  }
  plan.base_types[0] = (uint32_t)a->pointer_count; plan.base_types[1] = (uint32_t)a->array_count;
  plan.base_types[2] = (uint32_t)a->slice_count; plan.base_types[3] = (uint32_t)a->fn_type_count;
  plan.base_fn_type_params = (uint32_t)a->fn_type_param_count;
  for (unsigned k = 0; k < 3; ++k) { plan.free_at[k] = top[k]; plan.moved_low[k] = SIZE_MAX; }
  atomic_init(&plan.next, 0);
  atomic_init(&plan.out_of_memory, false);
  /* This thread works too: its report state and body capture come back after. */
  DynDiagnosticCapture *kept = dyn_diagnostic_capture;
  dyn_diagnostic_capture = NULL;
  SemaReport report = sema_report;
  pthread_t threads[16];
  unsigned started = 0;
  for (; started + 1 < workers; ++started)
    if (pthread_create(&threads[started], NULL, sema_worker, &plan)) break;
  sema_worker(&plan);
  for (unsigned i = 0; i < started; ++i) pthread_join(threads[i], NULL);
  sema_report = report;
  dyn_diagnostic_capture = kept;
  /* Commit in order. */
  bool ok = !atomic_load(&plan.out_of_memory);
  for (uint32_t i = 0; ok && i < plan.chunk_count; ++i) {
    SemaChunk *c = &plan.chunks[i];
    uint32_t counts[4] = {c->pointer_count, c->array_count, c->slice_count, c->fn_type_count};
    for (unsigned k = 0; k < 4 && ok; ++k)
      if (counts[k] && !(c->map[k] = calloc(counts[k], sizeof(DynType)))) ok = false;
    for (uint32_t f = c->first; ok && f < c->last; ++f) {
      bool serial = c->failed || !c->parts || c->parts[f - c->first].serial;
      ok = serial ? sema_commit_serial(&plan, i, errors, f, late) : sema_commit_part(&plan, i, errors, f, late);
    }
  }
  /* Every private type a fix can name was created by a committed function
     of its chunk; map any other now, in order, so the fixers only read. */
  for (uint32_t i = 0; ok && i < plan.chunk_count; ++i) {
    SemaChunk *c = &plan.chunks[i];
    static const DynType bases[4] = {DYN_TYPE_POINTER_BASE, DYN_TYPE_ARRAY_BASE, DYN_TYPE_SLICE_BASE, DYN_TYPE_FN_BASE};
    uint32_t counts[4] = {c->pointer_count, c->array_count, c->slice_count, c->fn_type_count};
    for (unsigned k = 0; k < 4; ++k)
      for (uint32_t t = 0; t < counts[k]; ++t)
        (void)sema_commit_type(&plan, c, bases[k] + plan.base_types[k] + t);
  }
  if (ok) {
    atomic_store(&plan.next, 0);
    started = 0;
    for (; started + 1 < workers; ++started)
      if (pthread_create(&threads[started], NULL, sema_fixer, &plan)) break;
    sema_fixer(&plan);
    for (unsigned i = 0; i < started; ++i) pthread_join(threads[i], NULL);
  }
  sema_plan_free(&plan);
  if (!ok) a->allocation_failed = true;
  return n;
}
#else
static void sema_work_abort(void) {}
static void sema_work_created(unsigned kind, uint32_t index) { (void)kind; (void)index; }
static void sema_work_out_of_memory(void) {}
#endif
