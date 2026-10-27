/* Independent checked-IR to WebAssembly object emission.
 * Scalars live in typed Wasm locals; aggregate values use stack-frame storage.
 * Every aggregate call argument is snapshotted when evaluated, before later
 * arguments can mutate its source. Frames and relocation immediates are patched
 * after lowering, so neither temporary counts nor frame sizes require a
 * prepass. The object uses the standard linking v2 and reloc.CODE conventions.
 */
#include "backend/output.h"
#include "ir.h"

#include <setjmp.h>
/* Allocation lifetime is one emission. A local recovery boundary prevents an
 * exhausted compiler heap from publishing a partial object or aborting the
 * process; the registry also releases allocations on the exceptional path. */
typedef struct WAllocation {
  void *pointer;
  struct WAllocation *next;
} WAllocation;
typedef struct WHeap {
  jmp_buf failure;
  WAllocation *allocations;
  struct WHeap *previous;
} WHeap;
static _Thread_local WHeap *wasm_heap;
static void allocation_failure(void) { longjmp(wasm_heap->failure, 1); }
static void *wasm_allocate(size_t n) {
  void *p = malloc(n ? n : 1);
  WAllocation *a = p ? malloc(sizeof(*a)) : NULL;
  if (!a) {
    free(p);
    allocation_failure();
  }
  a->pointer = p;
  a->next = wasm_heap->allocations;
  wasm_heap->allocations = a;
  return p;
}
static void *wasm_calloc(size_t n, size_t size) {
  if (size && n > SIZE_MAX / size)
    allocation_failure();
  size_t bytes = n * size;
  void *p = wasm_allocate(bytes);
  memset(p, 0, bytes);
  return p;
}
static void *wasm_reallocate(void *old, size_t n) {
  if (!old)
    return wasm_allocate(n);
  for (WAllocation *a = wasm_heap->allocations; a; a = a->next)
    if (a->pointer == old) {
      void *p = realloc(old, n ? n : 1);
      if (!p)
        allocation_failure();
      a->pointer = p;
      return p;
    }
  allocation_failure();
  return NULL;
}
static void wasm_free(void *p) {
  if (!p)
    return;
  WAllocation **at = &wasm_heap->allocations;
  while (*at && (*at)->pointer != p)
    at = &(*at)->next;
  if (*at) {
    WAllocation *a = *at;
    *at = a->next;
    free(a->pointer);
    free(a);
  }
}
static char *wasm_strdup(const char *s) {
  size_t n = strlen(s) + 1;
  char *p = wasm_allocate(n);
  memcpy(p, s, n);
  return p;
}
static WHeap *wasm_heap_new(void) { return calloc(1, sizeof(WHeap)); }
static void wasm_heap_destroy(WHeap *h) {
  while (h->allocations) {
    WAllocation *a = h->allocations;
    h->allocations = a->next;
    free(a->pointer);
    free(a);
  }
  free(h);
}
#define malloc wasm_allocate
#define calloc wasm_calloc
#define realloc wasm_reallocate
#define free wasm_free
#define strdup wasm_strdup

typedef struct {
  unsigned char *p;
  size_t n, cap;
} WB;
static void wb(WB *b, unsigned v) {
  if (b->n == b->cap) {
    if (b->cap > SIZE_MAX / 2)
      allocation_failure();
    b->cap = b->cap ? b->cap * 2 : 128;
    b->p = realloc(b->p, b->cap);
    if (!b->p)
      allocation_failure();
  }
  b->p[b->n++] = (unsigned char)v;
}
static void wu(WB *b, uint64_t v) {
  do {
    unsigned c = v & 127;
    v >>= 7;
    wb(b, c | (v ? 128 : 0));
  } while (v);
}
static void ws(WB *b, int64_t v) {
  bool more;
  do {
    unsigned c = v & 127;
    v >>= 7;
    more = !((v == 0 && !(c & 64)) || (v == -1 && (c & 64)));
    wb(b, c | (more ? 128 : 0));
  } while (more);
}
static void wn(WB *b, const void *p, size_t n) {
  const unsigned char *s = p;
  for (size_t i = 0; i < n; i++)
    wb(b, s[i]);
}
static void wstr(WB *b, const char *s) {
  wu(b, strlen(s));
  wn(b, s, strlen(s));
}
static void wp(WB *b, uint32_t v) {
  for (int i = 0; i < 4; i++) {
    wb(b, (v & 127) | 128);
    v >>= 7;
  }
  wb(b, v & 15);
}
static void wsec(WB *b, unsigned id, WB *s) {
  wb(b, id);
  wu(b, s->n);
  wn(b, s->p, s->n);
  free(s->p);
  *s = (WB){0};
}
typedef struct {
  uint32_t type, offset, symbol;
  int32_t addend;
} WR;
typedef struct {
  WR *p;
  size_t n, cap;
} WRs;
static void wradd(WRs *r, WR x) {
  if (r->n == r->cap) {
    if (r->cap > SIZE_MAX / (2 * sizeof(*r->p)))
      allocation_failure();
    r->cap = r->cap ? r->cap * 2 : 64;
    r->p = realloc(r->p, r->cap * sizeof(*r->p));
    if (!r->p)
      allocation_failure();
  }
  r->p[r->n++] = x;
}
typedef struct {
  char *name;
  unsigned kind, flags, index, offset, size;
} WSym;
typedef struct {
  unsigned break_depth, continue_depth;
  size_t defer_count;
} WLoop;
typedef struct {
  const DynIrProgram *ir;
  const DynSource *source;
  bool failed, unwinding;
  WB code, data, types, imports, exports;
  unsigned type_count, import_count, export_count;
  WSym *symbols;
  size_t ns, cs;
  unsigned *fn_symbol, *fn_index, *fn_type, *global_symbol, *string_symbol;
  unsigned stack_symbol, stack_low_symbol, init_symbol, guard_symbol,
      init_index;
  WB body, localtypes;
  size_t temp_cursor;
  WRs relocs, bodyrelocs;
  unsigned param_count, base, frame, depth;
  unsigned *localoffset, *localalias, *captured;
  uint32_t *defers;
  size_t ndefer;
  WLoop *loops;
  const DynIrFunction *function;
  unsigned return_ptr;
  size_t frame_patch;
} WG;
static unsigned wal(unsigned n, unsigned a) { return (n + a - 1) & ~(a - 1); }
static bool wen(DynType t) {
  return t >= DYN_TYPE_ENUM_BASE && t < DYN_TYPE_POINTER_BASE;
}
static bool wst(DynType t) {
  return t >= DYN_TYPE_STRUCT_BASE && t < DYN_TYPE_ENUM_BASE;
}
static bool war(DynType t) {
  return t >= DYN_TYPE_ARRAY_BASE && t < DYN_TYPE_SLICE_BASE;
}
static bool wsl(DynType t) {
  return t == DYN_TYPE_STRING ||
         (t >= DYN_TYPE_SLICE_BASE && t < DYN_TYPE_FN_BASE);
}
static bool wptr(DynType t) {
  return t >= DYN_TYPE_POINTER_BASE && t < DYN_TYPE_ARRAY_BASE;
}
static DynType wtag(WG *g, DynType t) {
  return wen(t) ? g->ir->enums[t - DYN_TYPE_ENUM_BASE].tag_type : t;
}
static bool wsign(DynType t) {
  return t == DYN_TYPE_I8 || t == DYN_TYPE_I16 || t == DYN_TYPE_I32 ||
         t == DYN_TYPE_I64 || t == DYN_TYPE_ISIZE;
}
static unsigned wsize(WG *, DynType);
static unsigned wa(WG *, DynType);
static unsigned wfield(WG *g, DynType t, unsigned f) {
  if (wsl(t))
    return f * 4;
  if (t == DYN_TYPE_ANY)
    return f ? 8 : 0;
  DynIrStruct *s = &g->ir->structs[t - DYN_TYPE_STRUCT_BASE];
  unsigned n = 0;
  for (unsigned i = 0; i <= f; i++) {
    DynType ft = g->ir->fields[s->field_start + i].type;
    n = wal(n, s->packed ? 1 : wa(g, ft));
    if (i == f)
      return n;
    n += wsize(g, ft);
  }
  return n;
}
static unsigned wa(WG *g, DynType t) {
  if (wst(t)) {
    DynIrStruct *s = &g->ir->structs[t - DYN_TYPE_STRUCT_BASE];
    unsigned a = 1;
    for (unsigned i = 0; i < s->field_count; i++) {
      unsigned x = wa(g, g->ir->fields[s->field_start + i].type);
      if (x > a)
        a = x;
    }
    return s->packed ? 1 : a;
  }
  if (wen(t)) {
    DynIrEnum *e = &g->ir->enums[t - DYN_TYPE_ENUM_BASE];
    unsigned a = wa(g, e->tag_type);
    for (unsigned i = 0; i < e->variant_count; i++) {
      unsigned x = wa(g, g->ir->variants[e->variant_start + i].payload_type);
      if (x > a)
        a = x;
    }
    return a;
  }
  if (war(t))
    return wa(g, g->ir->arrays[t - DYN_TYPE_ARRAY_BASE].element);
  if (t == DYN_TYPE_I64 || t == DYN_TYPE_U64 || t == DYN_TYPE_F64 ||
      t == DYN_TYPE_ANY)
    return 8;
  if (t == DYN_TYPE_BOOL || t == DYN_TYPE_I8 || t == DYN_TYPE_U8 ||
      t == DYN_TYPE_VOID)
    return 1;
  if (t == DYN_TYPE_I16 || t == DYN_TYPE_U16)
    return 2;
  return 4;
}
static unsigned wpayload(WG *g, DynType t) {
  DynIrEnum *e = &g->ir->enums[t - DYN_TYPE_ENUM_BASE];
  unsigned a = 1;
  for (unsigned i = 0; i < e->variant_count; i++) {
    unsigned x = wa(g, g->ir->variants[e->variant_start + i].payload_type);
    if (x > a)
      a = x;
  }
  return wal(wsize(g, e->tag_type), a);
}
static unsigned wsize(WG *g, DynType t) {
  if (t == DYN_TYPE_VOID)
    return 0;
  if (wst(t)) {
    DynIrStruct *s = &g->ir->structs[t - DYN_TYPE_STRUCT_BASE];
    if (!s->field_count)
      return 0;
    unsigned i = s->field_count - 1;
    return wal(wfield(g, t, i) +
                   wsize(g, g->ir->fields[s->field_start + i].type),
               wa(g, t));
  }
  if (wen(t)) {
    DynIrEnum *e = &g->ir->enums[t - DYN_TYPE_ENUM_BASE];
    if (!e->has_payload)
      return wsize(g, e->tag_type);
    unsigned n = 0;
    for (unsigned i = 0; i < e->variant_count; i++) {
      unsigned x = wsize(g, g->ir->variants[e->variant_start + i].payload_type);
      if (x > n)
        n = x;
    }
    return wal(wpayload(g, t) + n, wa(g, t));
  }
  if (war(t)) {
    DynIrArray *a = &g->ir->arrays[t - DYN_TYPE_ARRAY_BASE];
    uint64_t n = (uint64_t)wsize(g, a->element) * a->length;
    if (n > UINT32_MAX) {
      g->failed = true;
      return 0;
    }
    return (unsigned)n;
  }
  if (wsl(t))
    return 8;
  if (t == DYN_TYPE_ANY)
    return 16;
  return wa(g, t);
}
static bool wagg(WG *g, DynType t) {
  return wst(t) || war(t) || wsl(t) || t == DYN_TYPE_ANY ||
         (wen(t) && g->ir->enums[t - DYN_TYPE_ENUM_BASE].has_payload);
}
static unsigned wvt(WG *g, DynType t) {
  t = wtag(g, t);
  return t == DYN_TYPE_I64 || t == DYN_TYPE_U64 ? 0x7e
         : t == DYN_TYPE_F32                    ? 0x7d
         : t == DYN_TYPE_F64                    ? 0x7c
                                                : 0x7f;
}
static DynType wflat(WG *g, DynType t) {
  if (wst(t)) {
    DynIrStruct *s = &g->ir->structs[t - DYN_TYPE_STRUCT_BASE];
    if (s->field_count == 1)
      return wflat(g, g->ir->fields[s->field_start].type);
  }
  if (war(t) && g->ir->arrays[t - DYN_TYPE_ARRAY_BASE].length == 1)
    return wflat(g, g->ir->arrays[t - DYN_TYPE_ARRAY_BASE].element);
  return wagg(g, t) ? DYN_TYPE_VOID : t;
}
static void op(WG *g, unsigned c) { wb(&g->body, c); }
static void get(WG *g, unsigned n) {
  op(g, 0x20);
  wu(&g->body, n);
}
static void set(WG *g, unsigned n) {
  op(g, 0x21);
  wu(&g->body, n);
}
static unsigned tmp(WG *g, unsigned vt) {
  /* Aggregate initializer scopes can release completed element temporaries.
     Keep the physical declarations at their high-water mark and reuse only a
     matching value type above the current live prefix. Outer expression values
     stay below the cursor; stack-slot backing is never rewound here. */
  size_t at = g->temp_cursor;
  while (at < g->localtypes.n && g->localtypes.p[at] != vt)
    ++at;
  if (at == g->localtypes.n)
    wb(&g->localtypes, vt);
  g->temp_cursor = at + 1;
  return g->param_count + (unsigned)at;
}
static unsigned save(WG *g, unsigned vt) {
  unsigned n = tmp(g, vt);
  set(g, n);
  return n;
}
static void icon(WG *g, uint64_t v, unsigned vt) {
  op(g, vt == 0x7e ? 0x42 : 0x41);
  ws(&g->body, vt == 0x7e ? (int64_t)v : (int32_t)(uint32_t)v);
}
static unsigned constant(WG *g, uint64_t v, unsigned vt) {
  icon(g, v, vt);
  return save(g, vt);
}
static void reloc(WG *g, unsigned kind, unsigned sym, int add) {
  wradd(&g->bodyrelocs, (WR){kind, (uint32_t)g->body.n, sym, add});
  wp(&g->body, 0);
}
static unsigned symaddr(WG *g, unsigned s) {
  op(g, 0x41);
  reloc(g, 4, s, 0);
  return save(g, 0x7f);
}
static unsigned offset(WG *g, unsigned p, unsigned n) {
  if (!n)
    return p;
  get(g, p);
  icon(g, n, 0x7f);
  op(g, 0x6a);
  return save(g, 0x7f);
}
static unsigned frame_reserve(WG *g, unsigned n, unsigned a) {
  uint64_t off = ((uint64_t)g->frame + a - 1) & ~((uint64_t)a - 1);
  if (off + n > INT32_MAX - 16) {
    if (!g->failed)
      fprintf(stderr, "error: Wasm stack frame exceeds addressable size\n");
    g->failed = true;
    return 0;
  }
  g->frame = (unsigned)(off + n);
  return (unsigned)off;
}
static unsigned slot(WG *g, unsigned n, unsigned a) {
  return offset(g, g->base, frame_reserve(g, n, a));
}
static void loadop(WG *g, DynType t) {
  t = wtag(g, t);
  unsigned c = t == DYN_TYPE_I8                           ? 0x2c
               : (t == DYN_TYPE_U8 || t == DYN_TYPE_BOOL) ? 0x2d
               : t == DYN_TYPE_I16                        ? 0x2e
               : t == DYN_TYPE_U16                        ? 0x2f
               : t == DYN_TYPE_F32                        ? 0x2a
               : t == DYN_TYPE_F64                        ? 0x2b
               : wvt(g, t) == 0x7e                        ? 0x29
                                                          : 0x28;
  op(g, c);
  wu(&g->body, 0);
  wu(&g->body, 0);
}
static unsigned load(WG *g, unsigned p, DynType t) {
  if (wagg(g, t))
    return p;
  get(g, p);
  loadop(g, t);
  return save(g, wvt(g, t));
}
static void store(WG *g, unsigned p, unsigned v, DynType t) {
  get(g, p);
  get(g, v);
  if (wagg(g, t)) {
    icon(g, wsize(g, t), 0x7f);
    op(g, 0xfc);
    wu(&g->body, 10);
    op(g, 0);
    op(g, 0);
    return;
  }
  t = wtag(g, t);
  unsigned c = t == DYN_TYPE_I8 || t == DYN_TYPE_U8 || t == DYN_TYPE_BOOL ? 0x3a
               : t == DYN_TYPE_I16 || t == DYN_TYPE_U16                   ? 0x3b
               : t == DYN_TYPE_F32                                        ? 0x38
               : t == DYN_TYPE_F64                                        ? 0x39
               : wvt(g, t) == 0x7e ? 0x37
                                   : 0x36;
  op(g, c);
  wu(&g->body, 0);
  wu(&g->body, 0);
}
static void zero(WG *g, unsigned p, unsigned n) {
  get(g, p);
  icon(g, 0, 0x7f);
  icon(g, n, 0x7f);
  op(g, 0xfc);
  wu(&g->body, 11);
  op(g, 0);
}
static void begin(WG *g, unsigned c, unsigned type) {
  op(g, c);
  op(g, type);
  g->depth++;
}
static void end(WG *g) {
  op(g, 0x0b);
  g->depth--;
}
static void defers(WG *, size_t);
static void guard(WG *g) {
  op(g, 0x45);
  begin(g, 4, 0x40);
  if (!g->unwinding) {
    g->unwinding = true;
    defers(g, 0);
    g->unwinding = false;
  }
  op(g, 0);
  end(g);
}
static void branch(WG *g, unsigned depth, bool cond) {
  if (depth >= g->depth) {
    fprintf(stderr, "error: invalid Wasm branch in %s: target %u at depth %u\n", g->function ? g->function->name : "initializer", depth, g->depth);
    g->failed = true;
    return;
  }
  op(g, cond ? 0x0d : 0x0c);
  wu(&g->body, g->depth - depth - 1);
}
static unsigned expr(WG *, DynExprId);
static unsigned address(WG *, DynExprId);
static void block(WG *, unsigned, unsigned);
static unsigned usize(WG *g, DynExprId id) {
  unsigned v = expr(g, id);
  if (wvt(g, g->ir->expressions[id].type) == 0x7e) {
    get(g, v);
    icon(g, UINT32_MAX, 0x7e);
    op(g, 0x58);
    guard(g);
    get(g, v);
    op(g, 0xa7);
    return save(g, 0x7f);
  }
  return v;
}
static void pointer_check(WG *g, unsigned p, DynType t) {
  get(g, p);
  guard(g);
  unsigned a = wa(g, t);
  if (a > 1) {
    get(g, p);
    icon(g, a - 1, 0x7f);
    op(g, 0x71);
    op(g, 0x45);
    guard(g);
  }
}
static unsigned address(WG *g, DynExprId id) {
  const DynIrExpr *e = &g->ir->expressions[id];
  if (e->kind == DYN_EXPR_NAME)
    return g->localalias[e->integer] != UINT32_MAX
               ? g->localalias[e->integer]
               : offset(g, g->base, g->localoffset[e->integer]);
  if (e->kind == DYN_EXPR_GLOBAL)
    return symaddr(g, g->global_symbol[e->integer]);
  if (e->kind == DYN_EXPR_UNARY && e->op == DYN_OP_DEREF) {
    unsigned p = expr(g, e->left);
    pointer_check(g, p, e->type);
    return p;
  }
  if (e->kind == DYN_EXPR_FIELD) {
    DynType t = g->ir->expressions[e->left].type;
    unsigned p = expr(g, e->left);
    if (wptr(t)) {
      t = g->ir->pointers[t - DYN_TYPE_POINTER_BASE].pointee;
      pointer_check(g, p, t);
    }
    return offset(g, p, wfield(g, t, (unsigned)e->integer));
  }
  if (e->kind == DYN_EXPR_INDEX) {
    unsigned ix = usize(g, e->right), p = expr(g, e->left), n;
    DynType t = g->ir->expressions[e->left].type;
    if (war(t))
      n = constant(g, g->ir->arrays[t - DYN_TYPE_ARRAY_BASE].length, 0x7f);
    else {
      n = load(g, offset(g, p, 4), DYN_TYPE_U32);
      p = load(g, p, DYN_TYPE_RAWPTR);
    }
    if (!e->boolean) {
      get(g, ix);
      get(g, n);
      op(g, 0x49);
      guard(g);
    }
    get(g, ix);
    icon(g, wsize(g, e->type), 0x7f);
    op(g, 0x6c);
    get(g, p);
    op(g, 0x6a);
    return save(g, 0x7f);
  }
  g->failed = true;
  return constant(g, 0, 0x7f);
}
static unsigned normalize(WG *g, unsigned v, DynType t) {
  t = wtag(g, t);
  unsigned bits = wsize(g, t) * 8;
  if (bits < 32) {
    get(g, v);
    if (wsign(t)) {
      icon(g, 32 - bits, 0x7f);
      op(g, 0x74);
      icon(g, 32 - bits, 0x7f);
      op(g, 0x75);
    } else {
      icon(g, (1u << bits) - 1, 0x7f);
      op(g, 0x71);
    }
    return save(g, 0x7f);
  }
  return v;
}
/* Exact fmod reduction: multiplying/dividing the divisor by powers of two
 * preserves its significand. Each subtraction is between nearby values and
 * exact (Sterbenz's lemma), including subnormal operands. */
static unsigned float_constant(WG *g, double value, unsigned vt) {
  op(g, vt == 0x7d ? 0x43 : 0x44);
  if (vt == 0x7d) {
    float f = (float)value;
    uint32_t b;
    memcpy(&b, &f, 4);
    for (unsigned i = 0; i < 4; i++)
      op(g, b >> (i * 8));
  } else {
    uint64_t b;
    memcpy(&b, &value, 8);
    for (unsigned i = 0; i < 8; i++)
      op(g, b >> (i * 8));
  }
  return save(g, vt);
}
static unsigned float_remainder(WG *g, unsigned l, unsigned r, unsigned vt) {
  unsigned d = vt == 0x7c ? 14 : 0, cmp = vt == 0x7c ? 6 : 0;
  get(g, l);
  op(g, 0x8b + d);
  unsigned x = save(g, vt);
  get(g, r);
  op(g, 0x8b + d);
  unsigned y = save(g, vt);
  unsigned z = float_constant(g, 0, vt), two = float_constant(g, 2, vt),
           half = float_constant(g, 0.5, vt);
  unsigned result = tmp(g, vt);
  /* x-x is NaN precisely for infinity/NaN; y!=y catches a NaN divisor. */
  get(g, x);
  get(g, x);
  op(g, 0x93 + d);
  get(g, z);
  op(g, 0x5c + cmp);
  get(g, y);
  get(g, y);
  op(g, 0x5c + cmp);
  op(g, 0x72);
  get(g, y);
  get(g, z);
  op(g, 0x5b + cmp);
  op(g, 0x72);
  begin(g, 4, 0x40);
  get(g, z);
  get(g, z);
  op(g, 0x95 + d);
  set(g, result);
  op(g, 5);
  get(g, y);
  unsigned scale = save(g, vt);
  unsigned outer = g->depth;
  begin(g, 2, 0x40);
  unsigned loop = g->depth;
  begin(g, 3, 0x40);
  get(g, scale);
  get(g, x);
  get(g, half);
  op(g, 0x94 + d);
  op(g, 0x5e + cmp);
  branch(g, outer, true);
  get(g, scale);
  get(g, two);
  op(g, 0x94 + d);
  set(g, scale);
  branch(g, loop, false);
  end(g);
  end(g);
  outer = g->depth;
  begin(g, 2, 0x40);
  loop = g->depth;
  begin(g, 3, 0x40);
  get(g, x);
  get(g, scale);
  op(g, 0x60 + cmp);
  begin(g, 4, 0x40);
  get(g, x);
  get(g, scale);
  op(g, 0x93 + d);
  set(g, x);
  end(g);
  get(g, scale);
  get(g, y);
  op(g, 0x5f + cmp);
  branch(g, outer, true);
  get(g, scale);
  get(g, half);
  op(g, 0x94 + d);
  set(g, scale);
  branch(g, loop, false);
  end(g);
  end(g);
  get(g, x);
  get(g, l);
  op(g, 0x98 + d);
  set(g, result);
  end(g);
  return result;
}
static unsigned binary(WG *g, DynOperator o, DynType t, DynType rt, unsigned l,
                       unsigned r, bool wrap, bool proven) {
  t = wtag(g, t);
  unsigned vt = wvt(g, t);
  bool wide = vt == 0x7e, sign = wsign(t), flt = vt == 0x7c || vt == 0x7d;
  unsigned c = 0;
  if (o >= DYN_OP_EQ && o <= DYN_OP_GE) {
    unsigned s[] = {0x46, 0x47, 0x48, 0x4c, 0x4a, 0x4e},
             u[] = {0x46, 0x47, 0x49, 0x4d, 0x4b, 0x4f},
             f[] = {0x5b, 0x5c, 0x5d, 0x5f, 0x5e, 0x60};
    c = flt ? f[o - DYN_OP_EQ] + (vt == 0x7c ? 6 : 0)
            : (sign ? s : u)[o - DYN_OP_EQ] + (wide ? 11 : 0);
    get(g, l);
    get(g, r);
    op(g, c);
    return save(g, 0x7f);
  }
  if (flt) {
    if (o == DYN_OP_REM)
      return float_remainder(g, l, r, vt);
    c = o == DYN_OP_ADD   ? 0x92
        : o == DYN_OP_SUB ? 0x93
        : o == DYN_OP_MUL ? 0x94
        : o == DYN_OP_DIV ? 0x95
                          : 0;
    if (!c) {
      g->failed = true;
      return l;
    }
    get(g, l);
    get(g, r);
    op(g, c + (vt == 0x7c ? 14 : 0));
    return save(g, vt);
  }
  if (o == DYN_OP_DIV || o == DYN_OP_REM) {
    get(g, r);
    icon(g, 0, vt);
    op(g, wide ? 0x52 : 0x47);
    guard(g);
  }
  if (sign && (o == DYN_OP_DIV || o == DYN_OP_REM)) {
    unsigned bits = wsize(g, t) * 8;
    get(g, l);
    icon(g,
         bits == 64 ? UINT64_C(0x8000000000000000)
                    : (uint64_t)(-(INT64_C(1) << (bits - 1))),
         vt);
    op(g, wide ? 0x51 : 0x46);
    get(g, r);
    icon(g, UINT64_MAX, vt);
    op(g, wide ? 0x51 : 0x46);
    op(g, 0x71);
    op(g, 0x45);
    guard(g);
  }
  if (o == DYN_OP_SHL || o == DYN_OP_SHR) {
    get(g, r);
    icon(g, wsize(g, t) * 8, wvt(g, rt));
    op(g, wvt(g, rt) == 0x7e ? 0x54 : 0x49);
    guard(g);
    if (wvt(g, rt) != vt) {
      get(g, r);
      op(g, wide ? 0xad : 0xa7);
      r = save(g, vt);
    }
  }
  c = o == DYN_OP_ADD       ? 0x6a
      : o == DYN_OP_SUB     ? 0x6b
      : o == DYN_OP_MUL     ? 0x6c
      : o == DYN_OP_DIV     ? (sign ? 0x6d : 0x6e)
      : o == DYN_OP_REM     ? (sign ? 0x6f : 0x70)
      : o == DYN_OP_BIT_AND ? 0x71
      : o == DYN_OP_BIT_OR  ? 0x72
      : o == DYN_OP_BIT_XOR ? 0x73
      : o == DYN_OP_SHL     ? 0x74
      : o == DYN_OP_SHR     ? (sign ? 0x75 : 0x76)
                            : 0;
  if (!c) {
    g->failed = true;
    return l;
  }
  /* Compute narrow arithmetic in i64, then prove the result representable. */
  bool checked = !wrap && !proven &&
                 (o == DYN_OP_ADD || o == DYN_OP_SUB || o == DYN_OP_MUL ||
                  o == DYN_OP_SHL);
  if (checked && !wide) {
    get(g, l);
    op(g, sign ? 0xac : 0xad);
    get(g, r);
    op(g, sign ? 0xac : 0xad);
    op(g, c + 0x12);
    unsigned v = save(g, 0x7e);
    unsigned bits = wsize(g, t) * 8;
    get(g, v);
    icon(g, sign ? (UINT64_C(1) << (bits - 1)) - 1 : (UINT64_C(1) << bits) - 1,
         0x7e);
    op(g, sign ? 0x57 : 0x58);
    guard(g);
    if (sign) {
      get(g, v);
      icon(g, (uint64_t)(-(INT64_C(1) << (bits - 1))), 0x7e);
      op(g, 0x59);
      guard(g);
    }
    get(g, v);
    op(g, 0xa7);
    return save(g, 0x7f);
  }
  get(g, l);
  get(g, r);
  op(g, c + (wide ? 0x12 : 0));
  unsigned v = save(g, vt);
  if (checked && wide) {
    if (o == DYN_OP_ADD || o == DYN_OP_SUB) {
      if (sign) {
        get(g, l);
        get(g, v);
        op(g, 0x85);
        get(g, o == DYN_OP_ADD ? r : l);
        get(g, o == DYN_OP_ADD ? v : r);
        op(g, 0x85);
        op(g, 0x83);
        icon(g, 0, vt);
        op(g, 0x59);
        guard(g);
      } else {
        get(g, o == DYN_OP_ADD ? v : l);
        get(g, o == DYN_OP_ADD ? l : r);
        op(g, 0x5a);
        guard(g);
      }
    } else if (o == DYN_OP_SHL) {
      get(g, v);
      get(g, r);
      op(g, sign ? 0x87 : 0x88);
      get(g, l);
      op(g, 0x51);
      guard(g);
    } else if (o == DYN_OP_MUL) { /* Division check must avoid MIN / -1. */
      get(g, r);
      op(g, 0x50);
      begin(g, 4, 0x40);
      op(g, 5);
      if (sign) {
        get(g, l);
        icon(g, INT64_MIN, vt);
        op(g, 0x51);
        get(g, r);
        icon(g, UINT64_MAX, vt);
        op(g, 0x51);
        op(g, 0x71);
        op(g, 0x45);
        guard(g);
        get(g, r);
        icon(g, INT64_MIN, vt);
        op(g, 0x51);
        get(g, l);
        icon(g, UINT64_MAX, vt);
        op(g, 0x51);
        op(g, 0x71);
        op(g, 0x45);
        guard(g);
      }
      get(g, v);
      get(g, r);
      op(g, sign ? 0x7f : 0x80);
      get(g, l);
      op(g, 0x51);
      guard(g);
      end(g);
    }
  }
  return normalize(g, v, t);
}
static unsigned convert(WG *g, unsigned v, DynType from, DynType to,
                        bool bitcast) {
  unsigned a = wvt(g, from), b = wvt(g, to);
  if (a == b)
    return normalize(g, v, to);
  get(g, v);
  unsigned c = 0;
  if (bitcast)
    c = a == 0x7f && b == 0x7d   ? 0xbe
        : a == 0x7d && b == 0x7f ? 0xbc
        : a == 0x7e && b == 0x7c ? 0xbf
        : a == 0x7c && b == 0x7e ? 0xbd
                                 : 0;
  else if (a == 0x7f)
    c = b == 0x7e   ? (wsign(from) ? 0xac : 0xad)
        : b == 0x7d ? (wsign(from) ? 0xb2 : 0xb3)
                    : (wsign(from) ? 0xb7 : 0xb8);
  else if (a == 0x7e)
    c = b == 0x7f   ? 0xa7
        : b == 0x7d ? (wsign(from) ? 0xb4 : 0xb5)
                    : (wsign(from) ? 0xb9 : 0xba);
  else if (a == 0x7d)
    c = b == 0x7c   ? 0xbb
        : b == 0x7f ? (wsign(to) ? 0xa8 : 0xa9)
                    : (wsign(to) ? 0xae : 0xaf);
  else
    c = b == 0x7d   ? 0xb6
        : b == 0x7f ? (wsign(to) ? 0xaa : 0xab)
                    : (wsign(to) ? 0xb0 : 0xb1);
  if (!c)
    g->failed = true;
  else
    op(g, c);
  return normalize(g, save(g, b), to);
}
static unsigned signature(WG *g, DynType ret, const DynType *args, unsigned n) {
  WB b = {0};
  wb(&b, 0x60);
  bool sr = wagg(g, ret) && wflat(g, ret) == DYN_TYPE_VOID;
  wu(&b, n + sr);
  if (sr)
    wb(&b, 0x7f);
  for (unsigned i = 0; i < n; i++) {
    DynType t = wflat(g, args[i]);
    wb(&b, t == DYN_TYPE_VOID ? 0x7f : wvt(g, t));
  }
  wu(&b, ret != DYN_TYPE_VOID && !sr);
  if (ret != DYN_TYPE_VOID && !sr)
    wb(&b, wvt(g, wflat(g, ret)));
  wn(&g->types, b.p, b.n);
  free(b.p);
  return g->type_count++;
}
static unsigned call(WG *g, const DynIrExpr *e) {
  bool indirect = e->kind == DYN_EXPR_INDIRECT_CALL;
  const DynIrFunction *f = indirect ? NULL : &g->ir->functions[e->integer];
  DynIrFnType *ft = indirect ? &g->ir->fn_types[e->integer] : NULL;
  unsigned n = indirect ? ft->param_count : f->param_count;
  bool packed = f && f->variadic && !f->foreign;
  unsigned *args = calloc(e->item_count + 3, sizeof(*args));
  if (!args)
    allocation_failure();
  unsigned callee = indirect ? expr(g, e->left) : 0;
  if (indirect) {
    get(g, callee);
    guard(g);
  }
  for (unsigned i = 0; i < e->item_count; i++) {
    unsigned id = g->ir->items[e->item_start + i].expression;
    args[i] = expr(g, id);
    DynType t = g->ir->expressions[id].type;
    if (wagg(g, t)) {
      unsigned copy = slot(g, wsize(g, t), wa(g, t));
      store(g, copy, args[i], t);
      args[i] = copy;
    }
  }
  /* Only trusted SDK leaves carry this identity. Keep ordinary bodies and
     address-taken calls available; unsupported operations retain their calls. */
  if (f && f->return_type == DYN_TYPE_F64 && e->type == DYN_TYPE_F64 &&
      !f->foreign && !f->variadic && n == e->item_count) {
    unsigned opcode = 0, count = 1;
    switch (f->math_intrinsic) {
    case DYN_MATH_INTRINSIC_SQRT: opcode = 0x9f; break;
    case DYN_MATH_INTRINSIC_FLOOR: opcode = 0x9c; break;
    case DYN_MATH_INTRINSIC_CEIL: opcode = 0x9b; break;
    case DYN_MATH_INTRINSIC_TRUNC: opcode = 0x9d; break;
    case DYN_MATH_INTRINSIC_COPYSIGN: opcode = 0xa6; count = 2; break;
    default: break; /* nearest is not ties-away round; Wasm has no fused FMA. */
    }
    if (opcode && n == count) {
      for (unsigned i = 0; i < count; ++i) get(g, args[i]);
      op(g, opcode);
      free(args);
      return save(g, 0x7c);
    }
  }
  if (f && f->variadic && f->foreign) {
    fprintf(stderr,
            "error: independent Wasm C variadic calls are unsupported\n");
    g->failed = true;
  }
  unsigned result = 0;
  DynType flat = wflat(g, e->type);
  bool sr = wagg(g, e->type) && flat == DYN_TYPE_VOID;
  if (wagg(g, e->type))
    result = slot(g, wsize(g, e->type), wa(g, e->type));
  if (packed) {
    unsigned count = e->item_count - n;
    DynType et = g->ir->slices[f->variadic_type - DYN_TYPE_SLICE_BASE].element;
    unsigned p = slot(g, wsize(g, et) * count, wa(g, et));
    for (unsigned i = 0; i < count; i++) {
      unsigned v = args[n + i];
      DynType at =
          g->ir->expressions[g->ir->items[e->item_start + n + i].expression]
              .type;
      if (et == DYN_TYPE_ANY) {
        unsigned item = offset(g, p, i * wsize(g, et)),
                 box = slot(g, wsize(g, at), wa(g, at));
        store(g, box, v, at);
        store(g, item, constant(g, at, 0x7e), DYN_TYPE_U64);
        store(g, offset(g, item, 8), box, DYN_TYPE_RAWPTR);
      } else
        store(g, offset(g, p, i * wsize(g, et)), v, et);
    }
    args[n] = p;
    args[n + 1] = constant(g, count, 0x7f);
  }
  if (sr) {
    get(g, result);
  }
  for (unsigned i = 0; i < n; i++) {
    DynType t = indirect ? g->ir->fn_type_params[ft->param_start + i]
                         : g->ir->params[f->param_start + i].type;
    unsigned v = args[i];
    if (wagg(g, t) && wflat(g, t) != DYN_TYPE_VOID)
      v = load(g, v, wflat(g, t));
    get(g, v);
  }
  if (packed) {
    get(g, args[n]);
    get(g, args[n + 1]);
  }
  if (indirect) {
    get(g, callee);
    DynType *ats = calloc(n, sizeof(*ats));
    for (unsigned i = 0; i < n; i++)
      ats[i] = g->ir->fn_type_params[ft->param_start + i];
    unsigned sig = signature(g, e->type, ats, n);
    free(ats);
    op(g, 0x11);
    reloc(g, 6, sig, 0);
    op(g, 0);
  } else {
    op(g, 0x10);
    reloc(g, 0, g->fn_symbol[e->integer], 0);
  }
  if (e->type != DYN_TYPE_VOID && !sr) {
    unsigned v = save(g, wvt(g, flat));
    if (wagg(g, e->type))
      store(g, result, v, flat);
    else
      result = v;
  }
  free(args);
  return result;
}
static unsigned expr(WG *g, DynExprId id) {
  if (id == DYN_NO_EXPR)
    return constant(g, 0, 0x7f);
  if (g->captured && g->captured[id] != UINT32_MAX)
    return g->captured[id];
  const DynIrExpr *e = &g->ir->expressions[id];
  unsigned vt = wvt(g, e->type), p, v;
  switch (e->kind) {
  case DYN_EXPR_INT:
  case DYN_EXPR_CHAR:
    return constant(g, e->integer, vt);
  case DYN_EXPR_BOOL:
    return constant(g, e->boolean, 0x7f);
  case DYN_EXPR_NIL:
    return constant(g, 0, vt);
  case DYN_EXPR_FLOAT:
    op(g, vt == 0x7d ? 0x43 : 0x44);
    if (vt == 0x7d) {
      float f = (float)e->floating;
      uint32_t x;
      memcpy(&x, &f, 4);
      for (int i = 0; i < 4; i++)
        wb(&g->body, x >> (i * 8));
    } else {
      uint64_t x;
      memcpy(&x, &e->floating, 8);
      for (int i = 0; i < 8; i++)
        wb(&g->body, x >> (i * 8));
    }
    return save(g, vt);
  case DYN_EXPR_NAME:
  case DYN_EXPR_GLOBAL:
  case DYN_EXPR_FIELD:
  case DYN_EXPR_INDEX:
    return load(g, address(g, id), e->type);
  case DYN_EXPR_STRING:
    p = slot(g, 8, 4);
    store(g, p, symaddr(g, g->string_symbol[e->integer]), DYN_TYPE_RAWPTR);
    store(g, offset(g, p, 4),
          constant(g, g->ir->strings[e->integer].length, 0x7f), DYN_TYPE_U32);
    return p;
  case DYN_EXPR_CALL:
  case DYN_EXPR_INDIRECT_CALL:
    return call(g, e);
  case DYN_EXPR_FUNCTION:
    op(g, 0x41);
    reloc(g, 1, g->fn_symbol[e->integer], 0);
    return save(g, 0x7f);
  case DYN_EXPR_STRUCT:
  case DYN_EXPR_ARRAY: {
    p = slot(g, wsize(g, e->type), wa(g, e->type));
    zero(g, p, wsize(g, e->type));
    size_t element_temps = g->temp_cursor;
    if (e->kind == DYN_EXPR_STRUCT) {
      DynIrStruct *s = &g->ir->structs[e->integer];
      for (unsigned i = 0; i < s->field_count; i++) {
        DynIrField *f = &g->ir->fields[s->field_start + i];
        if (f->default_expression != DYN_NO_EXPR) {
          store(g, offset(g, p, wfield(g, e->type, i)),
                expr(g, f->default_expression), f->type);
          g->temp_cursor = element_temps;
        }
      }
    }
    for (unsigned i = 0; i < e->item_count; i++) {
      DynIrItem *it = &g->ir->items[e->item_start + i];
      DynType t = g->ir->expressions[it->expression].type;
      unsigned off = e->kind == DYN_EXPR_STRUCT
                         ? wfield(g, e->type, it->field_index)
                         : i * wsize(g, t);
      v = expr(g, it->expression);
      store(g, offset(g, p, off), v, t);
      g->temp_cursor = element_temps;
    }
    return p;
  }
  case DYN_EXPR_ENUM: {
    DynIrVariant *x = &g->ir->variants[e->integer];
    DynIrEnum *en = &g->ir->enums[e->type - DYN_TYPE_ENUM_BASE];
    if (!en->has_payload)
      return constant(g, x->tag, wvt(g, en->tag_type));
    p = slot(g, wsize(g, e->type), wa(g, e->type));
    zero(g, p, wsize(g, e->type));
    store(g, p, constant(g, x->tag, wvt(g, en->tag_type)), en->tag_type);
    if (x->payload_type != DYN_TYPE_VOID)
      store(g, offset(g, p, wpayload(g, e->type)),
            expr(g, g->ir->items[e->item_start].expression), x->payload_type);
    return p;
  }
  case DYN_EXPR_LEN: {
    DynType t = g->ir->expressions[e->left].type;
    if (war(t))
      return constant(g, g->ir->arrays[t - DYN_TYPE_ARRAY_BASE].length, 0x7f);
    return load(g, offset(g, expr(g, e->left), 4), DYN_TYPE_U32);
  }
  case DYN_EXPR_SLICE: {
    DynType t = g->ir->expressions[e->left].type;
    unsigned data = expr(g, e->left), length = 0;
    if (war(t))
      length = constant(g, g->ir->arrays[t - DYN_TYPE_ARRAY_BASE].length, 0x7f);
    else if (!wptr(t)) {
      length = load(g, offset(g, data, 4), DYN_TYPE_U32);
      data = load(g, data, DYN_TYPE_RAWPTR);
    } else {
      pointer_check(g, data,
                    g->ir->pointers[t - DYN_TYPE_POINTER_BASE].pointee);
    }
    unsigned start = e->right == DYN_NO_EXPR ? constant(g, 0, 0x7f)
                                             : usize(g, e->right),
             stop = e->integer == DYN_NO_EXPR ? length
                                              : usize(g, (DynExprId)e->integer);
    get(g, start);
    get(g, stop);
    op(g, 0x4d);
    guard(g);
    if (!wptr(t)) {
      get(g, stop);
      get(g, length);
      op(g, 0x4d);
      guard(g);
    }
    get(g, start);
    DynType et = e->type == DYN_TYPE_STRING
                     ? DYN_TYPE_U8
                     : g->ir->slices[e->type - DYN_TYPE_SLICE_BASE].element;
    icon(g, wsize(g, et), 0x7f);
    op(g, 0x6c);
    get(g, data);
    op(g, 0x6a);
    data = save(g, 0x7f);
    get(g, stop);
    get(g, start);
    op(g, 0x6b);
    length = save(g, 0x7f);
    p = slot(g, 8, 4);
    store(g, p, data, DYN_TYPE_RAWPTR);
    store(g, offset(g, p, 4), length, DYN_TYPE_U32);
    return p;
  }
  case DYN_EXPR_CONVERT:
  case DYN_EXPR_CAST:
  case DYN_EXPR_BITCAST: {
    DynType from = g->ir->expressions[e->left].type;
    v = expr(g, e->left);
    if (e->type == DYN_TYPE_ANY && from != DYN_TYPE_ANY) {
      unsigned box = slot(g, wsize(g, from), wa(g, from));
      store(g, box, v, from);
      p = slot(g, 16, 8);
      store(g, p, constant(g, from, 0x7e), DYN_TYPE_U64);
      store(g, offset(g, p, 8), box, DYN_TYPE_RAWPTR);
      return p;
    }
    if (e->kind == DYN_EXPR_BITCAST && (wagg(g, from) || wagg(g, e->type))) {
      unsigned box = slot(g, wsize(g, from), wa(g, from));
      store(g, box, v, from);
      return load(g, box, e->type);
    }
    if (wagg(g, e->type))
      return v;
    if (wen(e->type) && !wen(from)) {
      DynIrEnum *en = &g->ir->enums[e->type - DYN_TYPE_ENUM_BASE];
      unsigned ok = constant(g, 0, 0x7f),
               wide = convert(g, v, from, DYN_TYPE_I64, false);
      unsigned bits = wsize(g, en->tag_type) * 8;
      bool sign = wsign(en->tag_type);
      for (unsigned i = 0; i < en->variant_count; i++) {
        uint64_t tag = g->ir->variants[en->variant_start + i].tag;
        if (sign && bits < 64 && (tag & (UINT64_C(1) << (bits - 1))))
          tag |= UINT64_MAX << bits;
        if (wsign(from) != sign && (int64_t)tag < 0)
          continue;
        get(g, wide);
        icon(g, tag, 0x7e);
        op(g, 0x51);
        get(g, ok);
        op(g, 0x72);
        set(g, ok);
      }
      get(g, ok);
      guard(g);
    }
    return convert(g, v, wtag(g, from), wtag(g, e->type),
                   e->kind == DYN_EXPR_BITCAST);
  }
  case DYN_EXPR_UNARY:
    if (e->op == DYN_OP_ADDRESS)
      return address(g, e->left);
    if (e->op == DYN_OP_DEREF)
      return load(g, address(g, id), e->type);
    if (e->op == DYN_OP_NEG && e->boolean)
      return constant(g, 0 - g->ir->expressions[e->left].integer, vt);
    v = expr(g, e->left);
    if (e->op == DYN_OP_NOT) {
      get(g, v);
      op(g, vt == 0x7e ? 0x50 : 0x45);
      return save(g, 0x7f);
    }
    if (e->op == DYN_OP_BIT_NOT) {
      get(g, v);
      icon(g, UINT64_MAX, vt);
      op(g, vt == 0x7e ? 0x85 : 0x73);
      return normalize(g, save(g, vt), e->type);
    }
    if (vt == 0x7d || vt == 0x7c) {
      get(g, v);
      op(g, vt == 0x7d ? 0x8c : 0x9a);
      return save(g, vt);
    }
    return binary(g, DYN_OP_SUB, e->type, e->type, constant(g, 0, vt), v,
                  e->wrap, false);
  case DYN_EXPR_BINARY: {
    unsigned l = expr(g, e->left);
    if (e->op == DYN_OP_LOGICAL_AND || e->op == DYN_OP_LOGICAL_OR) {
      unsigned result = tmp(g, 0x7f);
      get(g, l);
      begin(g, 4, 0x40);
      if (e->op == DYN_OP_LOGICAL_AND) {
        v = expr(g, e->right);
        get(g, v);
      } else
        icon(g, 1, 0x7f);
      set(g, result);
      op(g, 5);
      if (e->op == DYN_OP_LOGICAL_OR) {
        v = expr(g, e->right);
        get(g, v);
      } else
        icon(g, 0, 0x7f);
      set(g, result);
      end(g);
      return result;
    }
    unsigned r = expr(g, e->right);
    return binary(g, e->op, g->ir->expressions[e->left].type,
                  g->ir->expressions[e->right].type, l, r, e->wrap, e->boolean);
  }
  default:
    fprintf(stderr, "error: independent Wasm expression %u is unsupported\n",
            (unsigned)e->kind);
    g->failed = true;
    return constant(g, 0, vt);
  }
}
static void defers(WG *g, size_t to) {
  size_t n = g->ndefer;
  while (g->ndefer > to) {
    unsigned i = g->defers[--g->ndefer];
    const DynIrStmt *s = &g->ir->statements[i];
    block(g, s->body_start, s->body_count);
  }
  g->ndefer = n;
}
static void restore(WG *g) {
  get(g, g->base);
  icon(g, 0, 0x7f); /* patched at function completion */
  size_t at = g->body.n - 1;
  g->body.n = at;
  wradd(&g->bodyrelocs, (WR){UINT32_MAX, (unsigned)at, 0, 0});
  wp(&g->body, 0);
  op(g, 0x6a);
  op(g, 0x24);
  reloc(g, 7, g->stack_symbol, 0);
}
static void statement(WG *g, const DynIrStmt *s) {
  unsigned p, v;
  switch (s->kind) {
  case DYN_STMT_LOCAL:
    p = offset(g, g->base, g->localoffset[s->local_id]);
    if (s->expression == DYN_NO_EXPR)
      zero(g, p, wsize(g, g->ir->locals[s->local_id].type));
    else {
      v = expr(g, s->expression);
      store(g, p, v, g->ir->locals[s->local_id].type);
    }
    break;
  case DYN_STMT_ASSIGN: {
    if (s->target == DYN_NO_EXPR) {
      v = expr(g, s->expression);
      if (s->local_id != UINT32_MAX)
        store(g,
              g->localalias[s->local_id] != UINT32_MAX
                  ? g->localalias[s->local_id]
                  : offset(g, g->base, g->localoffset[s->local_id]),
              v, g->ir->locals[s->local_id].type);
      break;
    }
    DynType t = g->ir->expressions[s->target].type;
    if (s->assignment_op) {
      p = address(g, s->target);
      v = load(g, p, t);
      unsigned r = expr(g, s->expression);
      v = binary(g, s->assignment_op, t, g->ir->expressions[s->expression].type,
                 v, r, false, false);
    } else {
      v = expr(g, s->expression);
      if (wagg(g, t)) {
        unsigned copy = slot(g, wsize(g, t), wa(g, t));
        store(g, copy, v, t);
        v = copy;
      }
      p = address(g, s->target);
    }
    store(g, p, v, t);
    break;
  }
  case DYN_STMT_EXPR:
    (void)expr(g, s->expression);
    break;
  case DYN_STMT_RETURN: {
    DynType t = g->function ? g->function->return_type : DYN_TYPE_VOID;
    v = t == DYN_TYPE_VOID ? 0 : expr(g, s->expression);
    if (wagg(g, t)) {
      unsigned copy = slot(g, wsize(g, t), wa(g, t));
      store(g, copy, v, t);
      v = copy;
    }
    defers(g, 0);
    if (wagg(g, t) && wflat(g, t) == DYN_TYPE_VOID)
      store(g, g->return_ptr, v, t);
    else if (wagg(g, t))
      v = load(g, v, wflat(g, t));
    restore(g);
    if (g->function && g->function->is_main)
      icon(g, 0, 0x7f);
    else if (t != DYN_TYPE_VOID &&
             !(wagg(g, t) && wflat(g, t) == DYN_TYPE_VOID))
      get(g, v);
    op(g, 0x0f);
    break;
  }
  case DYN_STMT_PANIC:
    (void)expr(g, s->expression);
    defers(g, 0);
    op(g, 0);
    break;
  case DYN_STMT_IF:
    if (s->expression < g->ir->expression_count &&
        g->ir->expressions[s->expression].kind == DYN_EXPR_BOOL) {
      bool chosen = g->ir->expressions[s->expression].boolean;
      block(g, chosen ? s->body_start : s->else_start,
            chosen ? s->body_count : s->else_count);
      break;
    }
    v = expr(g, s->expression);
    get(g, v);
    begin(g, 4, 0x40);
    block(g, s->body_start, s->body_count);
    if (s->else_count) {
      op(g, 5);
      block(g, s->else_start, s->else_count);
    }
    end(g);
    break;
  case DYN_STMT_BREAK:
  case DYN_STMT_CONTINUE: {
    WLoop *l = &g->loops[s->target_loop_id];
    defers(g, l->defer_count);
    branch(g, s->kind == DYN_STMT_BREAK ? l->break_depth : l->continue_depth,
           false);
    break;
  }
  case DYN_STMT_DEFER: {
    if (!s->defer_block && s->body_count) {
      const DynIrStmt *a = &g->ir->statements[g->ir->children[s->body_start]];
      if (a->kind == DYN_STMT_EXPR) {
        const DynIrExpr *e = &g->ir->expressions[a->expression];
        if (e->kind == DYN_EXPR_INDIRECT_CALL)
          g->captured[e->left] = expr(g, e->left);
        for (unsigned i = 0; i < e->item_count; i++) {
          unsigned id = g->ir->items[e->item_start + i].expression;
          unsigned val = expr(g, id);
          DynType t = g->ir->expressions[id].type;
          if (wagg(g, t)) {
            unsigned copy = slot(g, wsize(g, t), wa(g, t));
            store(g, copy, val, t);
            val = copy;
          }
          g->captured[id] = val;
        }
      }
    }
    g->defers[g->ndefer++] = (uint32_t)(s - g->ir->statements);
    break;
  }
  case DYN_STMT_FOR: {
    bool range = s->for_range, collection = !range && s->target != DYN_NO_EXPR;
    DynType t = range ? g->ir->expressions[s->target].type : DYN_TYPE_USIZE;
    unsigned vt = wvt(g, t), counter = 0, stop = 0, data = 0;
    DynType element = DYN_TYPE_VOID;
    if (range) {
      unsigned first = expr(g, s->target), last = expr(g, s->expression);
      counter = tmp(g, vt);
      get(g, s->for_reverse ? last : first);
      set(g, counter);
      stop = s->for_reverse ? first : last;
    } else if (collection) {
      DynType ct = g->ir->expressions[s->target].type;
      data = expr(g, s->target);
      if (war(ct)) {
        element = g->ir->arrays[ct - DYN_TYPE_ARRAY_BASE].element;
        stop =
            constant(g, g->ir->arrays[ct - DYN_TYPE_ARRAY_BASE].length, 0x7f);
        if (!s->for_pointer) {
          unsigned copy = slot(g, wsize(g, ct), wa(g, ct));
          store(g, copy, data, ct);
          data = copy;
        }
      } else {
        element = ct == DYN_TYPE_STRING
                      ? DYN_TYPE_U8
                      : g->ir->slices[ct - DYN_TYPE_SLICE_BASE].element;
        stop = load(g, offset(g, data, 4), DYN_TYPE_U32);
        data = load(g, data, DYN_TYPE_RAWPTR);
      }
      counter = tmp(g, vt);
      if (s->for_reverse)
        get(g, stop);
      else
        icon(g, 0, vt);
      set(g, counter);
    }
    unsigned bd = g->depth;
    begin(g, 2, 0x40);
    unsigned ld = g->depth;
    begin(g, 3, 0x40);
    if (range) {
      DynOperator cmp = s->for_reverse
                            ? (s->for_inclusive ? DYN_OP_GE : DYN_OP_GT)
                            : (s->for_inclusive ? DYN_OP_LE : DYN_OP_LT);
      v = binary(g, cmp, t, t, counter, stop, true, true);
      get(g, v);
    } else if (collection) {
      get(g, counter);
      if (s->for_reverse) {
        icon(g, 0, vt);
        op(g, 0x4b);
      } else {
        get(g, stop);
        op(g, 0x49);
      }
    } else if (s->expression != DYN_NO_EXPR) {
      v = expr(g, s->expression);
      get(g, v);
    } else
      icon(g, 1, 0x7f);
    op(g, 0x45);
    branch(g, bd, true);
    if (range || collection) {
      get(g, counter);
      if (s->for_reverse && (!range || !s->for_inclusive)) {
        icon(g, 1, vt);
        op(g, vt == 0x7e ? 0x7d : 0x6b);
      }
      v = save(g, vt);
      if (collection) {
        get(g, v);
        icon(g, wsize(g, element), 0x7f);
        op(g, 0x6c);
        get(g, data);
        op(g, 0x6a);
        v = save(g, 0x7f);
        if (!s->for_pointer)
          v = load(g, v, element);
      }
      p = offset(g, g->base, g->localoffset[s->local_id]);
      store(g, p, v, g->ir->locals[s->local_id].type);
    }
    unsigned cd = g->depth;
    begin(g, 2, 0x40);
    g->loops[s->loop_id] = (WLoop){bd, cd, g->ndefer};
    block(g, s->body_start, s->body_count);
    end(g);
    if (range && s->for_inclusive) {
      get(g, counter);
      get(g, stop);
      op(g, vt == 0x7e ? 0x51 : 0x46);
      branch(g, bd, true);
    }
    if (range || collection) {
      get(g, counter);
      icon(g, 1, vt);
      op(g, (s->for_reverse ? 0x6b : 0x6a) + (vt == 0x7e ? 0x12 : 0));
      set(g, counter);
    }
    branch(g, ld, false);
    end(g);
    end(g);
    break;
  }
  case DYN_STMT_CASE: {
    DynType t = g->ir->expressions[s->expression].type;
    unsigned subject = expr(g, s->expression), test = subject;
    DynType tt = t;
    if (t == DYN_TYPE_ANY) {
      tt = DYN_TYPE_U64;
      test = load(g, subject, tt);
    } else if (wen(t)) {
      tt = wtag(g, t);
      if (wagg(g, t))
        test = load(g, subject, tt);
    }
    unsigned done = g->depth;
    begin(g, 2, 0x40);
    for (unsigned i = 0; i < s->case_arm_count; i++) {
      DynIrCaseArm *a = &g->ir->case_arms[s->case_arm_start + i];
      unsigned ok = constant(g, a->wildcard, 0x7f);
      for (unsigned j = 0; j < a->pattern_count; j++) {
        DynIrPattern *x = &g->ir->patterns[a->pattern_start + j];
        unsigned match;
        if (x->is_type || x->is_enum) {
          uint64_t k = x->is_type ? x->type : g->ir->variants[x->variant].tag;
          match = binary(g, DYN_OP_EQ, tt, tt, test, constant(g, k, wvt(g, tt)),
                         true, true);
        } else {
          unsigned lo = binary(g, DYN_OP_GE, tt, tt, test,
                               constant(g, x->first, wvt(g, tt)), true, true),
                   hi = binary(g, DYN_OP_LE, tt, tt, test,
                               constant(g, x->last, wvt(g, tt)), true, true);
          get(g, lo);
          get(g, hi);
          op(g, 0x71);
          match = save(g, 0x7f);
        }
        get(g, ok);
        get(g, match);
        op(g, 0x72);
        set(g, ok);
      }
      get(g, ok);
      begin(g, 4, 0x40);
      if (a->local_id != UINT32_MAX) {
        DynIrPattern *x = &g->ir->patterns[a->pattern_start];
        DynType bt = g->ir->locals[a->local_id].type;
        p = x->is_type ? load(g, offset(g, subject, 8), DYN_TYPE_RAWPTR)
                       : offset(g, subject, wpayload(g, t));
        if (a->pointer_binding)
          g->localalias[a->local_id] = p;
        else {
          v = load(g, p, bt);
          store(g, offset(g, g->base, g->localoffset[a->local_id]), v, bt);
        }
      }
      block(g, a->body_start, a->body_count);
      branch(g, done, false);
      end(g);
    }
    op(g, 0);
    end(g);
    break;
  }
  default:
    g->failed = true;
    fprintf(stderr, "error: independent Wasm statement %u unsupported\n",
            s->kind);
    break;
  }
}
static void block(WG *g, unsigned start, unsigned n) {
  size_t nd = g->ndefer;
  for (unsigned i = 0; i < n; i++)
    statement(g, &g->ir->statements[g->ir->children[start + i]]);
  defers(g, nd);
  g->ndefer = nd;
}
static unsigned symbol(WG *g, const char *name, unsigned kind, unsigned flags,
                       unsigned index, unsigned offset_, unsigned size) {
  if (g->ns == g->cs) {
    if (g->cs > SIZE_MAX / (2 * sizeof(*g->symbols)))
      allocation_failure();
    g->cs = g->cs ? g->cs * 2 : 128;
    g->symbols = realloc(g->symbols, g->cs * sizeof(*g->symbols));
    if (!g->symbols)
      allocation_failure();
  }
  unsigned n = (unsigned)g->ns++;
  g->symbols[n] = (WSym){strdup(name), kind, flags, index, offset_, size};
  return n;
}
static unsigned datasym(WG *g, const char *name, unsigned size, unsigned align,
                        const void *bytes, unsigned flags) {
  unsigned off = wal((unsigned)g->data.n, align);
  while (g->data.n < off)
    wb(&g->data, 0);
  if (bytes)
    wn(&g->data, bytes, size);
  else
    for (unsigned i = 0; i < size; i++)
      wb(&g->data, 0);
  return symbol(g, name, 1, flags, 0, off, size);
}
static void exportfn(WG *g, const char *name, unsigned index) {
  wstr(&g->exports, name);
  wb(&g->exports, 0);
  wu(&g->exports, index);
  g->export_count++;
}
static void startbody(WG *g, const DynIrFunction *f, unsigned params) {
  g->function = f;
  g->param_count = params;
  g->temp_cursor = 0;
  g->frame = 0;
  g->depth = 0;
  g->ndefer = 0;
  for (size_t i = 0; i < g->ir->local_count; i++)
    g->localalias[i] = UINT32_MAX;
  g->base = tmp(g, 0x7f);
  for (size_t i = 0; i < g->ir->expression_count; i++)
    g->captured[i] = UINT32_MAX;
  op(g, 0x23);
  reloc(g, 7, g->stack_symbol, 0);
  unsigned old = save(g, 0x7f);
  get(g, old);
  op(g, 0x41);
  wradd(&g->bodyrelocs, (WR){UINT32_MAX, (unsigned)g->body.n, 0, 0});
  wp(&g->body, 0);
  op(g, 0x4f);
  guard(g);
  get(g, old);
  op(g, 0x41);
  g->frame_patch = g->body.n;
  wp(&g->body, 0);
  op(g, 0x6b);
  set(g, g->base);
  unsigned low = symaddr(g, g->stack_low_symbol);
  get(g, g->base);
  get(g, low);
  op(g, 0x4f);
  guard(g);
  get(g, g->base);
  op(g, 0x24);
  reloc(g, 7, g->stack_symbol, 0);
}
static void patch5(WB *b, size_t at, unsigned v) {
  for (int j = 0; j < 4; j++) {
    b->p[at++] = (v & 127) | 128;
    v >>= 7;
  }
  b->p[at] = v & 15;
}
static void finishbody(WG *g) {
  unsigned frame = wal(g->frame, 16);
  patch5(&g->body, g->frame_patch, frame);
  WB body = {0};
  wu(&body, g->localtypes.n);
  for (size_t i = 0; i < g->localtypes.n; i++) {
    wu(&body, 1);
    wb(&body, g->localtypes.p[i]);
  }
  unsigned prefix = (unsigned)body.n;
  wn(&body, g->body.p, g->body.n);
  wb(&body, 0x0b);
  wu(&g->code, body.n);
  unsigned base = (unsigned)g->code.n + prefix;
  for (size_t i = 0; i < g->bodyrelocs.n; i++) {
    WR r = g->bodyrelocs.p[i];
    if (r.type == UINT32_MAX) {
      patch5(&body, prefix + r.offset, frame);
      continue;
    }
    r.offset += base;
    wradd(&g->relocs, r);
  }
  wn(&g->code, body.p, body.n);
  free(body.p);
  free(g->body.p);
  g->body = (WB){0};
  g->localtypes.n = 0;
  g->bodyrelocs.n = 0;
}
#include "codegen_wasm_asm.inc"

/* Inlining rebuilds only live bodies and their local/child tables. Dead
   function metadata still refers to the original tables and must not be emitted. */
static bool wasm_function_live(const DynIrProgram *ir, size_t i) {
  return (!ir->live.functions || ir->live.functions[i]) &&
         !(ir->functions[i].generic && !ir->functions[i].instance);
}

static int wasm_object_impl(const DynSource *source, const DynIrProgram *ir,
                            const char *path, bool report, bool assembly) {
  WG g = {.ir = ir, .source = source};
  size_t nf = ir->function_count;
  g.fn_symbol = calloc(nf, sizeof(unsigned));
  g.fn_index = calloc(nf, sizeof(unsigned));
  g.fn_type = calloc(nf, sizeof(unsigned));
  g.global_symbol = calloc(ir->global_count, sizeof(unsigned));
  g.string_symbol = calloc(ir->string_count, sizeof(unsigned));
  g.localoffset = calloc(ir->local_count, sizeof(unsigned));
  g.localalias = calloc(ir->local_count, sizeof(unsigned));
  g.captured = calloc(ir->expression_count, sizeof(unsigned));
  g.defers = calloc(ir->statement_count + 1, sizeof(uint32_t));
  g.loops = calloc(ir->statement_count + 1, sizeof(WLoop));
  if (!g.fn_symbol || !g.fn_index || !g.fn_type || !g.captured || !g.defers ||
      !g.loops)
    allocation_failure();
  unsigned imported = 0, defined = 0;
  for (size_t i = 0; i < nf; i++) {
    const DynIrFunction *f = &ir->functions[i];
    if (!wasm_function_live(ir, i))
      continue;
    if (f->foreign)
      g.fn_index[i] = imported++;
    else
      defined++;
  }
  unsigned next = imported;
  for (size_t i = 0; i < nf; i++) {
    const DynIrFunction *f = &ir->functions[i];
    if (!wasm_function_live(ir, i))
      continue;
    if (!f->foreign)
      g.fn_index[i] = next++;
  }
  g.init_index = next;
  for (size_t i = 0; i < nf; i++) {
    const DynIrFunction *f = &ir->functions[i];
    if (!wasm_function_live(ir, i))
      continue;
    unsigned n = f->param_count + (f->variadic && !f->foreign ? 2 : 0);
    DynType *args = calloc(n + 1, sizeof(*args));
    for (unsigned j = 0; j < f->param_count; j++)
      args[j] = ir->params[f->param_start + j].type;
    if (n > f->param_count) {
      args[n - 2] = DYN_TYPE_RAWPTR;
      args[n - 1] = DYN_TYPE_USIZE;
    }
    g.fn_type[i] =
        signature(&g, f->is_main ? DYN_TYPE_I32 : f->return_type, args, n);
    free(args);
    const char *name =
        f->is_main     ? "__original_main"
        : f->foreign && f->link_name ? f->link_name
                       : f->name; /* Root functions retain unmangled names. */
    bool exp = f->is_public && !f->foreign && strncmp(f->name, "dyn_m", 5) != 0;
    g.fn_symbol[i] = symbol(&g, name, 0,
                            f->foreign ? 0x10
                            : exp      ? 0x20
                                       : 0,
                            g.fn_index[i], 0, 0);
    if (f->foreign) {
      wstr(&g.imports, "env");
      wstr(&g.imports, name);
      wb(&g.imports, 0);
      wu(&g.imports, g.fn_type[i]);
      g.import_count++;
    }
    if (exp)
      exportfn(&g, f->name, g.fn_index[i]);
  }
  unsigned init_type = signature(&g, DYN_TYPE_VOID, NULL, 0);
  g.init_symbol = symbol(&g, "dyn_initialize", 0, 0x20, g.init_index, 0, 0);
  exportfn(&g, "dyn_initialize", g.init_index);
  wstr(&g.imports, "env");
  wstr(&g.imports, "__linear_memory");
  wb(&g.imports, 2);
  wb(&g.imports, 0);
  wu(&g.imports, 0);
  g.import_count++;
  wstr(&g.imports, "env");
  wstr(&g.imports, "__indirect_function_table");
  wb(&g.imports, 1);
  wb(&g.imports, 0x70);
  wb(&g.imports, 0);
  wu(&g.imports, 0);
  g.import_count++;
  wstr(&g.imports, "env");
  wstr(&g.imports, "__stack_pointer");
  wb(&g.imports, 3);
  wb(&g.imports, 0x7f);
  wb(&g.imports, 1);
  g.import_count++;
  g.stack_symbol = symbol(&g, "__stack_pointer", 2, 0x10, 0, 0, 0);
  g.stack_low_symbol = symbol(&g, "__stack_low", 1, 0x10, 0, 0, 0);
  g.guard_symbol = datasym(&g, ".dyn.initialized", 4, 4, NULL, 2);
  for (size_t i = 0; i < ir->global_count; i++) {
    DynIrGlobal *x = &ir->globals[i];
    const char *name = x->link_name ? x->link_name : x->name;
    g.global_symbol[i] =
        x->foreign ? symbol(&g, name, 1, 0x10, 0, 0, 0)
                   : datasym(&g, name, wsize(&g, x->type), wa(&g, x->type),
                             NULL, x->is_public ? 0 : 2);
  }
  for (size_t i = 0; i < ir->string_count; i++) {
    char name[64];
    snprintf(name, sizeof(name), ".dyn.string.%zu", i);
    g.string_symbol[i] = datasym(&g, name, (unsigned)ir->strings[i].length, 1,
                                 ir->strings[i].data, 2);
  }
  wu(&g.code, defined + 1);
  for (size_t i = 0; i < nf; i++) {
    const DynIrFunction *f = &ir->functions[i];
    if (f->foreign || !wasm_function_live(ir, i))
      continue;
    bool sr =
        wagg(&g, f->return_type) && wflat(&g, f->return_type) == DYN_TYPE_VOID;
    unsigned params = f->param_count + sr + (f->variadic ? 2 : 0);
    startbody(&g, f, params);
    g.return_ptr = 0;
    for (unsigned j = 0; j < f->local_count; j++) {
      unsigned id = f->local_start + j;
      g.localoffset[id] = frame_reserve(&g, wsize(&g, ir->locals[id].type),
                                        wa(&g, ir->locals[id].type));
    }
    for (unsigned j = 0; j < f->param_count; j++) {
      DynIrParam *a = &ir->params[f->param_start + j];
      unsigned p = offset(&g, g.base, g.localoffset[a->local_id]);
      if (wagg(&g, a->type) && wflat(&g, a->type) != DYN_TYPE_VOID)
        store(&g, p, j + sr, wflat(&g, a->type));
      else
        store(&g, p, j + sr, a->type);
    }
    if (f->variadic) {
      unsigned p = offset(&g, g.base, g.localoffset[f->variadic_local_id]);
      store(&g, p, f->param_count + sr, DYN_TYPE_RAWPTR);
      store(&g, offset(&g, p, 4), f->param_count + sr + 1, DYN_TYPE_USIZE);
    }
    if (f->is_main) {
      op(&g, 0x10);
      reloc(&g, 0, g.init_symbol, 0);
    }
    block(&g, f->body_start, f->body_count);
    restore(&g);
    if (f->is_main)
      icon(&g, 0, 0x7f);
    else if (f->return_type != DYN_TYPE_VOID)
      op(&g, 0);
    finishbody(&g);
  }
  startbody(&g, NULL, 0);
  unsigned guardp = symaddr(&g, g.guard_symbol);
  unsigned initialized = load(&g, guardp, DYN_TYPE_U32);
  get(&g, initialized);
  op(&g, 0x45);
  begin(&g, 4, 0x40);
  store(&g, guardp, constant(&g, 1, 0x7f), DYN_TYPE_U32);
  for (size_t j = 0; j < ir->global_init_count; j++) {
    unsigned i = ir->global_init_order[j];
    DynIrGlobal *x = &ir->globals[i];
    if (!x->foreign && x->initializer != DYN_NO_EXPR) {
      unsigned v = expr(&g, x->initializer);
      store(&g, symaddr(&g, g.global_symbol[i]), v, x->type);
    }
  }
  end(&g);
  restore(&g);
  finishbody(&g);
  WB out = {0}, s = {0};
  wn(&out, "\0asm\1\0\0\0", 8);
  wu(&s, g.type_count);
  wn(&s, g.types.p, g.types.n);
  wsec(&out, 1, &s);
  wu(&s, g.import_count);
  wn(&s, g.imports.p, g.imports.n);
  wsec(&out, 2, &s);
  wu(&s, defined + 1);
  for (size_t i = 0; i < nf; i++)
    if (!ir->functions[i].foreign && wasm_function_live(ir, i))
      wu(&s, g.fn_type[i]);
  wu(&s, init_type);
  wsec(&out, 3, &s);
  wu(&s, g.export_count);
  wn(&s, g.exports.p, g.exports.n);
  wsec(&out, 7, &s);
  unsigned code_section = 4;
  wn(&s, g.code.p, g.code.n);
  wsec(&out, 10, &s);
  wu(&s, 1);
  wu(&s, 0);
  wb(&s, 0x41);
  ws(&s, 0);
  wb(&s, 0x0b);
  wu(&s, g.data.n);
  wn(&s, g.data.p, g.data.n);
  wsec(&out, 11, &s);
  wstr(&s, "linking");
  wu(&s, 2);
  WB sub = {0};
  wu(&sub, 1);
  wstr(&sub, ".data");
  wu(&sub, 4);
  wu(&sub, 0);
  wb(&s, 5);
  wu(&s, sub.n);
  wn(&s, sub.p, sub.n);
  free(sub.p);
  sub = (WB){0};
  wu(&sub, g.ns);
  for (size_t i = 0; i < g.ns; i++) {
    WSym *x = &g.symbols[i];
    wb(&sub, x->kind);
    wu(&sub, x->flags);
    if (x->kind == 1) {
      wstr(&sub, x->name);
      if (!(x->flags & 0x10)) {
        wu(&sub, 0);
        wu(&sub, x->offset);
        wu(&sub, x->size);
      }
    } else {
      wu(&sub, x->index);
      if (!(x->flags & 0x10))
        wstr(&sub, x->name);
    }
  }
  wb(&s, 8);
  wu(&s, sub.n);
  wn(&s, sub.p, sub.n);
  free(sub.p);
  wsec(&out, 0, &s);
  wstr(&s, "reloc.CODE");
  wu(&s, code_section);
  wu(&s, g.relocs.n);
  for (size_t i = 0; i < g.relocs.n; i++) {
    WR *r = &g.relocs.p[i];
    wu(&s, r->type);
    wu(&s, r->offset);
    wu(&s, r->symbol);
    if (r->type == 4)
      ws(&s, r->addend);
  }
  wsec(&out, 0, &s);
  size_t len = strlen(path);
  char *imports = malloc(len + 9);
  memcpy(imports, path, len);
  memcpy(imports + len, ".imports", 9);
  WB allowed = {0};
  if (!strcmp(dyn_context_target(&source->context)->kernel, "wasi")) {
    const char *wasi = "wasi_proc_exit\nwasi_fd_write\nwasi_fd_read\nwasi_fd_"
                       "close\nwasi_args_sizes_get\nwasi_args_get\nwasi_path_"
                       "open\nwasi_random_get\nwasi_clock_time_get\n";
    wn(&allowed, wasi, strlen(wasi));
  }
  for (size_t i = 0; i < nf; i++)
    if (ir->functions[i].foreign) {
      const char *name = ir->functions[i].link_name ? ir->functions[i].link_name
                                                    : ir->functions[i].name;
      wn(&allowed, name, strlen(name));
      wb(&allowed, '\n');
    }
  bool ok = !g.failed && (assembly ? wasm_assembly_write(&g, path, init_type)
            : backend_write_object(imports, allowed.p, allowed.n) &&
              backend_write_object(path, out.p, out.n));
  free(imports);
  free(allowed.p);
  if (!ok && report)
    fprintf(stderr, "error: independent Wasm object emission failed\n");
  for (size_t i = 0; i < g.ns; i++)
    free(g.symbols[i].name);
  free(g.symbols);
  free(g.fn_symbol);
  free(g.fn_index);
  free(g.fn_type);
  free(g.global_symbol);
  free(g.string_symbol);
  free(g.localoffset);
  free(g.localalias);
  free(g.captured);
  free(g.defers);
  free(g.loops);
  free(g.types.p);
  free(g.imports.p);
  free(g.exports.p);
  free(g.code.p);
  free(g.data.p);
  free(g.localtypes.p);
  free(g.relocs.p);
  free(g.bodyrelocs.p);
  free(out.p);
  return ok ? 0 : 2;
}

static int wasm_emit(const DynSource *source, const DynIrProgram *ir,
                     const char *path, bool report, bool assembly) {
  WHeap *heap = wasm_heap_new();
  if (!heap) {
    if (report)
      fprintf(stderr, "error: Wasm compiler allocation failed\n");
    return 2;
  }
  heap->previous = wasm_heap;
  wasm_heap = heap;
  int result;
  if (setjmp(heap->failure)) {
    if (report)
      fprintf(stderr, "error: Wasm compiler allocation failed\n");
    result = 2;
  } else
    result = wasm_object_impl(source, ir, path, report, assembly);
  wasm_heap = heap->previous;
  wasm_heap_destroy(heap);
  return result;
}

int dyn_wasm_object(const DynSource *source, const DynIrProgram *ir, const char *path, bool report) {
  return wasm_emit(source, ir, path, report, false);
}

int dyn_wasm_assembly(const DynSource *source, const DynIrProgram *ir, const char *path, bool report) {
  return wasm_emit(source, ir, path, report, true);
}
