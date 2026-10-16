/* LLVM syntax writer, independent of LLVM libraries and executables. */
#include "llvm_text.h"
#include <ctype.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct Allocation {
  struct Allocation *next;
} Allocation;
typedef struct TextAllocation {
  struct TextAllocation *next;
  char *data;
} TextAllocation;
struct LLVMOpaqueContext {
  Allocation *allocations;
  TextAllocation *texts;
  LLVMTypeRef types;
  unsigned serial;
  LLVMMetadataRef metadata;
  const char *error;
  jmp_buf failure;
};
struct LLVMOpaqueType {
  LLVMContextRef c;
  LLVMTypeRef next, result, element;
  LLVMTypeRef *members;
  unsigned count, bits;
  uint64_t length;
  int kind;
  bool packed, variadic;
  const char *name;
};
struct LLVMOpaqueAttributeRef {
  const char *name, *value;
  LLVMTypeRef type;
  unsigned long long number;
};
typedef struct Attr {
  struct Attr *next;
  unsigned index;
  LLVMAttributeRef value;
} Attr;
struct LLVMOpaqueValue {
  LLVMContextRef c;
  LLVMTypeRef type, declared;
  const char *name, *raw_name, *text, *section;
  LLVMValueRef next, initializer, operand;
  LLVMModuleRef module;
  LLVMBasicBlockRef block, first, last, successors[2];
  LLVMValueRef *params;
  Attr *attrs;
  unsigned linkage, visibility, alignment, successor_count;
  uint64_t integer;
  LLVMMetadataRef debug;
  bool constant_int, constant, load, terminator, function, global, phi;
};
struct LLVMOpaqueBasicBlock {
  LLVMValueRef function, first, last;
  LLVMBasicBlockRef next;
  const char *name;
};
struct LLVMOpaqueBuilder {
  LLVMContextRef c;
  LLVMBasicBlockRef block;
  LLVMValueRef before;
  LLVMMetadataRef location;
};
struct LLVMOpaqueModule {
  LLVMContextRef c;
  LLVMValueRef first, last;
  const char *triple, *layout;
  LLVMMetadataRef unit;
  const char *flags;
};
struct LLVMOpaqueMetadata {
  LLVMContextRef c;
  LLVMMetadataRef next;
  const char *ref, *text;
};
struct LLVMOpaqueDIBuilder {
  LLVMModuleRef module;
};
typedef struct {
  LLVMContextRef c;
  TextAllocation *owner;
  char *data;
  size_t n, cap;
  bool failed;
} Text;
static void *arena(LLVMContextRef, size_t);
static void add(Text *s, const char *fmt, ...) {
  if (s->failed)
    return;
  va_list ap, copy;
  va_start(ap, fmt);
  va_copy(copy, ap);
  int n = vsnprintf(NULL, 0, fmt, copy);
  va_end(copy);
  if (n < 0 || s->n > SIZE_MAX - (size_t)n - 1) {
    s->failed = true;
    va_end(ap);
    return;
  }
  if (!s->owner) {
    s->owner = arena(s->c, sizeof(*s->owner));
    s->owner->next = s->c->texts;
    s->c->texts = s->owner;
  }
  size_t need = s->n + (size_t)n + 1;
  if (need > s->cap) {
    size_t cap = need <= SIZE_MAX / 2 ? need * 2 : need;
    char *p = realloc(s->data, cap);
    if (!p) {
      s->failed = true;
      va_end(ap);
      return;
    }
    s->owner->data = s->data = p;
    s->cap = cap;
  }
  vsnprintf(s->data + s->n, s->cap - s->n, fmt, ap);
  s->n += (size_t)n;
  va_end(ap);
}
static void *arena(LLVMContextRef c, size_t n) {
  if (n > SIZE_MAX - sizeof(Allocation))
    longjmp(c->failure, 1);
  Allocation *a = calloc(1, sizeof(*a) + n);
  if (!a) {
    longjmp(c->failure, 1);
  }
  a->next = c->allocations;
  c->allocations = a;
  return a + 1;
}
static char *str(LLVMContextRef c, const char *s) {
  size_t n = strlen(s) + 1;
  char *p = arena(c, n);
  memcpy(p, s, n);
  return p;
}
static const char *finish(LLVMContextRef c, Text *s) {
  if (s->failed) {
    free(s->data);
    if (s->owner)
      s->owner->data = NULL;
    c->error = "out of memory writing LLVM IR";
    return "";
  }
  char *p = str(c, s->data ? s->data : "");
  free(s->data);
  if (s->owner)
    s->owner->data = NULL;
  return p;
}
static const char *fmt(LLVMContextRef c, const char *f, ...) {
  if (!f) {
    c->error = "missing LLVM IR format string";
    return "";
  }
  va_list a, b;
  va_start(a, f);
  va_copy(b, a);
  int n = vsnprintf(NULL, 0, f, b);
  va_end(b);
  if (n < 0) {
    va_end(a);
    c->error = "formatting LLVM IR failed";
    return "";
  }
  char *p = arena(c, (size_t)n + 1);
  vsnprintf(p, (size_t)n + 1, f, a);
  va_end(a);
  return p;
}
static const char *quote(LLVMContextRef c, const char *s) {
  Text t = {.c = c};
  add(&t, "\"");
  for (const unsigned char *p = (const unsigned char *)s; *p; ++p) {
    if (*p < ' ' || *p > 126 || *p == '"' || *p == '\\')
      add(&t, "\\%02X", *p);
    else
      add(&t, "%c", *p);
  }
  add(&t, "\"");
  return finish(c, &t);
}
static const char *identifier(LLVMContextRef c, const char *s) {
  if (!*s || isdigit((unsigned char)*s))
    return quote(c, s);
  for (const unsigned char *p = (const unsigned char *)s; *p; p++)
    if (!isalnum(*p) && !strchr("-$._", *p))
      return quote(c, s);
  return s;
}
static LLVMTypeRef type(LLVMContextRef c, int kind) {
  LLVMTypeRef t = arena(c, sizeof(*t));
  t->c = c;
  t->kind = kind;
  t->next = c->types;
  c->types = t;
  return t;
}
jmp_buf *dyn_text_jump(LLVMContextRef c) { return &c->failure; }
LLVMContextRef LLVMContextCreate(void) {
  return calloc(1, sizeof(struct LLVMOpaqueContext));
}
void LLVMContextDispose(LLVMContextRef c) {
  if (!c)
    return;
  for (TextAllocation *t = c->texts; t; t = t->next)
    free(t->data);
  Allocation *a = c->allocations;
  while (a) {
    Allocation *n = a->next;
    free(a);
    a = n;
  }
  free(c);
}
LLVMTypeRef LLVMIntTypeInContext(LLVMContextRef c, unsigned bits) {
  for (LLVMTypeRef t = c->types; t; t = t->next)
    if (t->kind == 8 && t->bits == bits)
      return t;
  LLVMTypeRef t = type(c, 8);
  t->bits = bits;
  return t;
}
#define INT(N)                                                                 \
  LLVMTypeRef LLVMInt##N##TypeInContext(LLVMContextRef c) {                    \
    return LLVMIntTypeInContext(c, N);                                         \
  }
INT(1)
INT(8)
INT(16) INT(32) INT(64) static LLVMTypeRef simple(LLVMContextRef c, int k) {
  for (LLVMTypeRef t = c->types; t; t = t->next)
    if (t->kind == k)
      return t;
  return type(c, k);
}
LLVMTypeRef LLVMVoidTypeInContext(LLVMContextRef c) { return simple(c, 0); }
LLVMTypeRef LLVMFloatTypeInContext(LLVMContextRef c) { return simple(c, 2); }
LLVMTypeRef LLVMDoubleTypeInContext(LLVMContextRef c) { return simple(c, 3); }
LLVMTypeRef LLVMPointerTypeInContext(LLVMContextRef c, unsigned space) {
  if (space)
    c->error = "nonzero LLVM address spaces unsupported";
  return simple(c, 12);
}
LLVMTypeRef LLVMArrayType2(LLVMTypeRef e, unsigned long long n) {
  LLVMTypeRef t = type(e->c, 11);
  t->element = e;
  t->length = n;
  return t;
}
LLVMTypeRef LLVMVectorType(LLVMTypeRef e, unsigned n) {
  LLVMTypeRef t = type(e->c, 13);
  t->element = e;
  t->length = n;
  return t;
}
static void members(LLVMTypeRef t, LLVMTypeRef *m, unsigned n) {
  t->members = arena(t->c, (n ? n : 1) * sizeof(*m));
  if (n)
    memcpy(t->members, m, n * sizeof(*m));
  t->count = n;
}
LLVMTypeRef LLVMStructCreateNamed(LLVMContextRef c, const char *name) {
  LLVMTypeRef t = type(c, 10);
  t->name = str(c, name);
  return t;
}
void LLVMStructSetBody(LLVMTypeRef t, LLVMTypeRef *m, unsigned n, int packed) {
  members(t, m, n);
  t->packed = packed;
}
LLVMTypeRef LLVMStructTypeInContext(LLVMContextRef c, LLVMTypeRef *m,
                                    unsigned n, int packed) {
  LLVMTypeRef t = type(c, 10);
  LLVMStructSetBody(t, m, n, packed);
  return t;
}
LLVMTypeRef LLVMFunctionType(LLVMTypeRef r, LLVMTypeRef *m, unsigned n,
                             int var) {
  LLVMTypeRef t = type(r->c, 9);
  t->result = r;
  members(t, m, n);
  t->variadic = var;
  return t;
}
int LLVMGetTypeKind(LLVMTypeRef t) { return t->kind; }
unsigned LLVMGetIntTypeWidth(LLVMTypeRef t) { return t->bits; }
unsigned LLVMCountStructElementTypes(LLVMTypeRef t) { return t->count; }
LLVMTypeRef LLVMStructGetTypeAtIndex(LLVMTypeRef t, unsigned i) {
  return t->members[i];
}
LLVMTypeRef LLVMGetReturnType(LLVMTypeRef t) { return t->result; }
unsigned LLVMCountParamTypes(LLVMTypeRef t) { return t->count; }
void LLVMGetParamTypes(LLVMTypeRef t, LLVMTypeRef *out) {
  memcpy(out, t->members, t->count * sizeof(*out));
}
static void print_type(Text *s, LLVMTypeRef t, bool body) {
  switch (t->kind) {
  case 0:
    add(s, "void");
    break;
  case 2:
    add(s, "float");
    break;
  case 3:
    add(s, "double");
    break;
  case 8:
    add(s, "i%u", t->bits);
    break;
  case 12:
    add(s, "ptr");
    break;
  case 14:
    add(s, "metadata");
    break;
  case 11:
  case 13:
    add(s, t->kind == 11 ? "[%" PRIu64 " x " : "<%" PRIu64 " x ", t->length);
    print_type(s, t->element, false);
    add(s, t->kind == 11 ? "]" : ">");
    break;
  case 10:
    if (t->name && !body) {
      add(s, "%%%s", identifier(t->c, t->name));
      break;
    }
    add(s, t->packed ? "<{ " : "{ ");
    for (unsigned i = 0; i < t->count; i++) {
      if (i)
        add(s, ", ");
      print_type(s, t->members[i], false);
    }
    add(s, t->packed ? " }>" : " }");
    break;
  case 9:
    print_type(s, t->result, false);
    add(s, " (");
    for (unsigned i = 0; i < t->count; i++) {
      if (i)
        add(s, ", ");
      print_type(s, t->members[i], false);
    }
    if (t->variadic)
      add(s, t->count ? ", ..." : "...");
    add(s, ")");
    break;
  default:
    t->c->error = "unknown LLVM textual type";
    add(s, "void");
  }
}
static const char *ts(LLVMTypeRef t) {
  Text s = {.c = t->c};
  print_type(&s, t, false);
  return finish(t->c, &s);
}
static LLVMValueRef val(LLVMTypeRef t, const char *name) {
  LLVMValueRef v = arena(t->c, sizeof(*v));
  v->c = t->c;
  v->type = t;
  v->name = name;
  return v;
}
LLVMTypeRef LLVMTypeOf(LLVMValueRef v) { return v->type; }
LLVMTypeRef LLVMGlobalGetValueType(LLVMValueRef v) { return v->declared; }
LLVMModuleRef LLVMModuleCreateWithNameInContext(const char *name,
                                                LLVMContextRef c) {
  (void)name;
  LLVMModuleRef m = arena(c, sizeof(*m));
  m->c = c;
  return m;
}
void LLVMDisposeModule(LLVMModuleRef m) { (void)m; }
void LLVMSetTarget(LLVMModuleRef m, const char *triple) {
  m->triple = str(m->c, triple);
}
void LLVMSetDataLayout(LLVMModuleRef m, const char *layout) {
  m->layout = str(m->c, layout);
}
static LLVMValueRef global(LLVMModuleRef m, const char *n, LLVMTypeRef t,
                           bool fn) {
  LLVMValueRef v = val(LLVMPointerTypeInContext(m->c, 0),
                       fmt(m->c, "@%s", identifier(m->c, n)));
  v->raw_name = str(m->c, n);
  v->declared = t;
  v->module = m;
  v->function = fn;
  v->global = !fn;
  if (m->last)
    m->last->next = v;
  else
    m->first = v;
  m->last = v;
  return v;
}
LLVMValueRef LLVMGetNamedFunction(LLVMModuleRef m, const char *name) {
  const char *n = fmt(m->c, "@%s", identifier(m->c, name));
  for (LLVMValueRef v = m->first; v; v = v->next)
    if (v->function && !strcmp(v->name, n))
      return v;
  return NULL;
}
LLVMValueRef LLVMAddFunction(LLVMModuleRef m, const char *name, LLVMTypeRef t) {
  LLVMValueRef existing = LLVMGetNamedFunction(m, name);
  if (existing)
    return existing;
  LLVMValueRef v = global(m, name, t, true);
  v->params = arena(m->c, (t->count ? t->count : 1) * sizeof(*v->params));
  for (unsigned i = 0; i < t->count; i++)
    v->params[i] = val(t->members[i], fmt(m->c, "%%p%u", i));
  return v;
}
LLVMValueRef LLVMAddGlobal(LLVMModuleRef m, LLVMTypeRef t, const char *name) {
  return global(m, name, t, false);
}
LLVMValueRef LLVMGetParam(LLVMValueRef v, unsigned i) { return v->params[i]; }
void LLVMSetInitializer(LLVMValueRef v, LLVMValueRef init) {
  v->initializer = init;
}
void LLVMSetGlobalConstant(LLVMValueRef v, int yes) { v->constant = yes; }
void LLVMSetLinkage(LLVMValueRef v, int l) { v->linkage = l; }
void LLVMSetVisibility(LLVMValueRef v, int l) { v->visibility = l; }
void LLVMSetAlignment(LLVMValueRef v, unsigned a) { v->alignment = a; }
void LLVMSetSection(LLVMValueRef v, const char *s) {
  v->section = str(v->c, s);
}
const char *LLVMGetValueName2(LLVMValueRef v, size_t *len) {
  *len = strlen(v->raw_name ? v->raw_name : v->name);
  return v->raw_name ? v->raw_name : v->name;
}
LLVMValueRef LLVMConstInt(LLVMTypeRef t, unsigned long long x, int sign) {
  LLVMValueRef v = val(t, NULL);
  if (t->bits < 64)
    x &= (UINT64_C(1) << t->bits) - 1;
  v->integer = x;
  v->constant_int = true;
  v->name = t->bits > 64 && sign && (x >> 63) ? fmt(t->c, "-%llu", (~x) + 1)
                                              : fmt(t->c, "%llu", x);
  return v;
}
LLVMValueRef LLVMConstReal(LLVMTypeRef t, double d) {
  if (t->kind == 2)
    d = (double)(float)d;
  uint64_t bits;
  memcpy(&bits, &d, 8);
  return val(t, fmt(t->c, "0x%016" PRIX64, bits));
}
LLVMValueRef LLVMConstNull(LLVMTypeRef t) {
  if (t->kind == 8)
    return LLVMConstInt(t, 0, 0);
  return val(t, t->kind == 12 ? "null" : "zeroinitializer");
}
LLVMValueRef LLVMGetUndef(LLVMTypeRef t) { return val(t, "undef"); }
LLVMValueRef LLVMConstStringInContext(LLVMContextRef c, const char *p,
                                      unsigned n, int nonul) {
  Text s = {.c = c};
  add(&s, "c\"");
  for (unsigned i = 0; i < n; i++)
    add(&s, "\\%02X", (unsigned char)p[i]);
  if (!nonul)
    add(&s, "\\00");
  add(&s, "\"");
  return val(LLVMArrayType2(LLVMInt8TypeInContext(c), n + !nonul),
             finish(c, &s));
}
static LLVMValueRef aggregate(LLVMTypeRef t, LLVMValueRef *v,
                              unsigned long long n, bool array) {
  Text s = {.c = t->c};
  add(&s, array ? "[" : t->packed ? "<{" : "{");
  for (unsigned long long i = 0; i < n; i++) {
    if (i)
      add(&s, ", ");
    add(&s, "%s %s", ts(v[i]->type), v[i]->name);
  }
  add(&s, array ? "]" : t->packed ? "}>" : "}");
  return val(t, finish(t->c, &s));
}
LLVMValueRef LLVMConstArray2(LLVMTypeRef e, LLVMValueRef *v,
                             unsigned long long n) {
  return aggregate(LLVMArrayType2(e, n), v, n, true);
}
LLVMValueRef LLVMConstNamedStruct(LLVMTypeRef t, LLVMValueRef *v, unsigned n) {
  return aggregate(t, v, n, false);
}
LLVMValueRef LLVMSizeOf(LLVMTypeRef t) {
  return val(LLVMInt64TypeInContext(t->c),
             fmt(t->c,
                 "ptrtoint (ptr getelementptr (%s, ptr null, i32 1) to i64)",
                 ts(t)));
}
LLVMValueRef LLVMIsAConstantInt(LLVMValueRef v) {
  return v && v->constant_int ? v : NULL;
}
unsigned long long LLVMConstIntGetZExtValue(LLVMValueRef v) {
  return v->integer;
}
LLVMValueRef LLVMIsALoadInst(LLVMValueRef v) { return v && v->load ? v : NULL; }
LLVMValueRef LLVMGetOperand(LLVMValueRef v, unsigned i) {
  if (i)
    v->c->error = "unsupported LLVM operand query";
  return v->operand;
}
LLVMBuilderRef LLVMCreateBuilderInContext(LLVMContextRef c) {
  LLVMBuilderRef b = arena(c, sizeof(*b));
  b->c = c;
  return b;
}
void LLVMDisposeBuilder(LLVMBuilderRef b) { (void)b; }
LLVMBasicBlockRef LLVMAppendBasicBlockInContext(LLVMContextRef c,
                                                LLVMValueRef f,
                                                const char *name) {
  LLVMBasicBlockRef b = arena(c, sizeof(*b));
  b->function = f;
  b->name = fmt(c, "b%u.%s", c->serial++, name);
  if (f->last)
    f->last->next = b;
  else
    f->first = b;
  f->last = b;
  return b;
}
void LLVMPositionBuilderAtEnd(LLVMBuilderRef b, LLVMBasicBlockRef block) {
  b->block = block;
  b->before = NULL;
}
void LLVMPositionBuilderBefore(LLVMBuilderRef b, LLVMValueRef v) {
  b->block = v->block;
  b->before = v;
}
LLVMBasicBlockRef LLVMGetInsertBlock(LLVMBuilderRef b) { return b->block; }
LLVMBasicBlockRef LLVMGetEntryBasicBlock(LLVMValueRef v) { return v->first; }
LLVMBasicBlockRef LLVMGetFirstBasicBlock(LLVMValueRef v) { return v->first; }
LLVMBasicBlockRef LLVMGetNextBasicBlock(LLVMBasicBlockRef b) { return b->next; }
LLVMValueRef LLVMGetFirstInstruction(LLVMBasicBlockRef b) { return b->first; }
LLVMValueRef LLVMGetBasicBlockTerminator(LLVMBasicBlockRef b) {
  return b->last && b->last->terminator ? b->last : NULL;
}
unsigned LLVMGetNumSuccessors(LLVMValueRef v) { return v->successor_count; }
LLVMBasicBlockRef LLVMGetSuccessor(LLVMValueRef v, unsigned n) {
  return v->successors[n];
}
static LLVMValueRef inst(LLVMBuilderRef b, LLVMTypeRef t, const char *text) {
  LLVMValueRef v = val(t, t->kind ? fmt(b->c, "%%v%u", b->c->serial++) : "");
  v->text = text;
  v->debug = b->location;
  v->block = b->block;
  LLVMValueRef *p =
      !b->before && b->block->last ? &b->block->last->next : &b->block->first;
  if (b->before)
    while (*p && *p != b->before)
      p = &(*p)->next;
  v->next = *p;
  *p = v;
  if (!v->next)
    b->block->last = v;
  return v;
}
LLVMValueRef LLVMBuildAlloca(LLVMBuilderRef b, LLVMTypeRef t, const char *n) {
  (void)n;
  return inst(b, LLVMPointerTypeInContext(b->c, 0),
              fmt(b->c, "alloca %s", ts(t)));
}
LLVMValueRef LLVMBuildLoad2(LLVMBuilderRef b, LLVMTypeRef t, LLVMValueRef p,
                            const char *n) {
  (void)n;
  LLVMValueRef v = inst(b, t, fmt(b->c, "load %s, ptr %s", ts(t), p->name));
  v->load = true;
  v->operand = p;
  return v;
}
LLVMValueRef LLVMBuildStore(LLVMBuilderRef b, LLVMValueRef v, LLVMValueRef p) {
  return inst(b, LLVMVoidTypeInContext(b->c),
              fmt(b->c, "store %s %s, ptr %s", ts(v->type), v->name, p->name));
}
LLVMValueRef LLVMBuildSelect(LLVMBuilderRef b, LLVMValueRef c, LLVMValueRef x,
                             LLVMValueRef y, const char *n) {
  (void)n;
  return inst(b, x->type,
              fmt(b->c, "select i1 %s, %s %s, %s %s", c->name, ts(x->type),
                  x->name, ts(y->type), y->name));
}
LLVMValueRef LLVMBuildInsertValue(LLVMBuilderRef b, LLVMValueRef v,
                                  LLVMValueRef x, unsigned i, const char *n) {
  (void)n;
  return inst(b, v->type,
              fmt(b->c, "insertvalue %s %s, %s %s, %u", ts(v->type), v->name,
                  ts(x->type), x->name, i));
}
LLVMValueRef LLVMBuildExtractValue(LLVMBuilderRef b, LLVMValueRef v, unsigned i,
                                   const char *n) {
  (void)n;
  LLVMTypeRef t = v->type->kind == 11 ? v->type->element : v->type->members[i];
  return inst(b, t,
              fmt(b->c, "extractvalue %s %s, %u", ts(v->type), v->name, i));
}
LLVMValueRef LLVMBuildGEP2(LLVMBuilderRef b, LLVMTypeRef t, LLVMValueRef p,
                           LLVMValueRef *indices, unsigned count,
                           const char *n) {
  (void)n;
  Text s = {.c = b->c};
  add(&s, "getelementptr %s, ptr %s", ts(t), p->name);
  for (unsigned i = 0; i < count; i++)
    add(&s, ", %s %s", ts(indices[i]->type), indices[i]->name);
  return inst(b, LLVMPointerTypeInContext(b->c, 0), finish(b->c, &s));
}
LLVMValueRef LLVMBuildStructGEP2(LLVMBuilderRef b, LLVMTypeRef t,
                                 LLVMValueRef p, unsigned i, const char *n) {
  LLVMValueRef indices[] = {LLVMConstInt(LLVMInt32TypeInContext(b->c), 0, 0),
                            LLVMConstInt(LLVMInt32TypeInContext(b->c), i, 0)};
  return LLVMBuildGEP2(b, t, p, indices, 2, n);
}
#define BIN(Name, op)                                                          \
  LLVMValueRef LLVMBuild##Name(LLVMBuilderRef b, LLVMValueRef x,               \
                               LLVMValueRef y, const char *n) {                \
    (void)n;                                                                   \
    return inst(b, x->type,                                                    \
                fmt(b->c, op " %s %s, %s", ts(x->type), x->name, y->name));    \
  }
BIN(Add, "add")
BIN(Sub, "sub")
BIN(Mul, "mul")
BIN(SDiv, "sdiv")
BIN(UDiv, "udiv")
BIN(SRem, "srem") BIN(URem, "urem") BIN(FAdd, "fadd") BIN(FSub, "fsub")
    BIN(FMul, "fmul") BIN(FDiv, "fdiv") BIN(FRem, "frem") BIN(And, "and")
        BIN(Or, "or") BIN(Xor, "xor") BIN(Shl, "shl") BIN(AShr, "ashr")
            BIN(LShr, "lshr")
#define CAST(Name, op)                                                         \
  LLVMValueRef LLVMBuild##Name(LLVMBuilderRef b, LLVMValueRef x,               \
                               LLVMTypeRef t, const char *n) {                 \
    (void)n;                                                                   \
    if (x->type == t)                                                          \
      return x;                                                                \
    return inst(b, t,                                                          \
                fmt(b->c, op " %s %s to %s", ts(x->type), x->name, ts(t)));    \
  }
                CAST(PtrToInt, "ptrtoint") CAST(IntToPtr, "inttoptr")
                    CAST(SExt, "sext") CAST(ZExt, "zext") CAST(Trunc, "trunc")
                        CAST(SIToFP, "sitofp") CAST(UIToFP, "uitofp")
                            CAST(FPExt, "fpext") CAST(FPTrunc, "fptrunc")
                                CAST(FPToSI, "fptosi") CAST(FPToUI, "fptoui")
                                    CAST(BitCast, "bitcast") LLVMValueRef
    LLVMBuildNeg(LLVMBuilderRef b, LLVMValueRef v, const char *n) {
  return LLVMBuildSub(b, LLVMConstNull(v->type), v, n);
}
LLVMValueRef LLVMBuildNot(LLVMBuilderRef b, LLVMValueRef v, const char *n) {
  return LLVMBuildXor(b, v, LLVMConstInt(v->type, UINT64_MAX, 0), n);
}
LLVMValueRef LLVMBuildFNeg(LLVMBuilderRef b, LLVMValueRef v, const char *n) {
  (void)n;
  return inst(b, v->type, fmt(b->c, "fneg %s %s", ts(v->type), v->name));
}
LLVMValueRef LLVMBuildICmp(LLVMBuilderRef b, int pred, LLVMValueRef x,
                           LLVMValueRef y, const char *n) {
  (void)n;
  const char *ops[] = {"eq",  "ne",  "ugt", "uge", "ult",
                       "ule", "sgt", "sge", "slt", "sle"};
  if (pred < 32 || pred > 41) {
    b->c->error = "unknown integer predicate";
    pred = 32;
  }
  return inst(b, LLVMInt1TypeInContext(b->c),
              fmt(b->c, "icmp %s %s %s, %s", ops[pred - 32], ts(x->type),
                  x->name, y->name));
}
LLVMValueRef LLVMBuildFCmp(LLVMBuilderRef b, int pred, LLVMValueRef x,
                           LLVMValueRef y, const char *n) {
  (void)n;
  const char *ops[] = {"false", "oeq", "ogt", "oge", "olt", "ole",
                       "one",   "ord", "uno", "ueq", "ugt", "uge",
                       "ult",   "ule", "une", "true"};
  if (pred < 0 || pred > 15) {
    b->c->error = "unknown float predicate";
    pred = 0;
  }
  return inst(
      b, LLVMInt1TypeInContext(b->c),
      fmt(b->c, "fcmp %s %s %s, %s", ops[pred], ts(x->type), x->name, y->name));
}
static LLVMValueRef term(LLVMBuilderRef b, const char *s) {
  LLVMValueRef v = inst(b, LLVMVoidTypeInContext(b->c), s);
  v->terminator = true;
  return v;
}
LLVMValueRef LLVMBuildRet(LLVMBuilderRef b, LLVMValueRef v) {
  return term(b, fmt(b->c, "ret %s %s", ts(v->type), v->name));
}
LLVMValueRef LLVMBuildRetVoid(LLVMBuilderRef b) { return term(b, "ret void"); }
LLVMValueRef LLVMBuildUnreachable(LLVMBuilderRef b) {
  return term(b, "unreachable");
}
LLVMValueRef LLVMBuildBr(LLVMBuilderRef b, LLVMBasicBlockRef to) {
  LLVMValueRef v =
      term(b, fmt(b->c, "br label %%%s", identifier(b->c, to->name)));
  v->successors[0] = to;
  v->successor_count = 1;
  return v;
}
LLVMValueRef LLVMBuildCondBr(LLVMBuilderRef b, LLVMValueRef c,
                             LLVMBasicBlockRef yes, LLVMBasicBlockRef no) {
  LLVMValueRef v =
      term(b, fmt(b->c, "br i1 %s, label %%%s, label %%%s", c->name,
                  identifier(b->c, yes->name), identifier(b->c, no->name)));
  v->successors[0] = yes;
  v->successors[1] = no;
  v->successor_count = 2;
  return v;
}
LLVMValueRef LLVMBuildPhi(LLVMBuilderRef b, LLVMTypeRef t, const char *n) {
  (void)n;
  LLVMValueRef v = inst(b, t, fmt(b->c, "phi %s ", ts(t)));
  v->phi = true;
  return v;
}
void LLVMAddIncoming(LLVMValueRef v, LLVMValueRef *values,
                     LLVMBasicBlockRef *blocks, unsigned n) {
  Text s = {.c = v->c};
  add(&s, "%s", v->text);
  for (unsigned i = 0; i < n; i++) {
    if (i || v->successor_count)
      add(&s, ", ");
    add(&s, "[ %s, %%%s ]", values[i]->name, identifier(v->c, blocks[i]->name));
  }
  v->successor_count += n;
  v->text = finish(v->c, &s);
}
static const char *attribute(LLVMContextRef c, LLVMAttributeRef a) {
  if (a->type)
    return fmt(c, "%s(%s)", a->name, ts(a->type));
  if (a->value)
    return fmt(c, "%s=%s", quote(c, a->name), quote(c, a->value));
  if (!strcmp(a->name, "alignstack"))
    return fmt(c, "alignstack(%llu)", a->number);
  if (!strcmp(a->name, "align") || !strcmp(a->name, "stackalignment"))
    return fmt(c, "align %llu", a->number);
  return a->name;
}
static void attributes(Text *s, LLVMValueRef v, unsigned i) {
  for (Attr *a = v->attrs; a; a = a->next)
    if (a->index == i)
      add(s, " %s", attribute(v->c, a->value));
}
/* A stable local registry replaces LLVM's runtime attribute IDs. */
static const char *attr_names[] = {
    "",        "noreturn", "returns_twice",   "sret",           "byval",
    "align",   "noalias",  "nocapture",       "readonly",       "signext",
    "zeroext", "inreg",    "nounwind",        "uwtable",        "nest",
    "nonnull", "noundef",  "dereferenceable", "stackalignment", "alignstack"};
unsigned LLVMGetEnumAttributeKindForName(const char *s, size_t n) {
  for (unsigned i = 1; i < sizeof(attr_names) / sizeof(*attr_names); i++)
    if (strlen(attr_names[i]) == n && !memcmp(s, attr_names[i], n))
      return i;
  return 0;
}
LLVMAttributeRef LLVMCreateEnumAttribute(LLVMContextRef c, unsigned id,
                                         unsigned long long n) {
  LLVMAttributeRef a = arena(c, sizeof(*a));
  if (!id || id >= sizeof(attr_names) / sizeof(*attr_names)) {
    c->error = "unsupported LLVM attribute";
    id = 0;
  }
  a->name = attr_names[id];
  a->number = n;
  return a;
}
LLVMAttributeRef LLVMCreateTypeAttribute(LLVMContextRef c, unsigned id,
                                         LLVMTypeRef t) {
  LLVMAttributeRef a = LLVMCreateEnumAttribute(c, id, 0);
  a->type = t;
  return a;
}
LLVMAttributeRef LLVMCreateStringAttribute(LLVMContextRef c, const char *s,
                                           unsigned n, const char *v,
                                           unsigned len) {
  LLVMAttributeRef a = arena(c, sizeof(*a));
  char *name = arena(c, (size_t)n + 1), *value = arena(c, (size_t)len + 1);
  memcpy(name, s, n);
  memcpy(value, v, len);
  a->name = name;
  a->value = value;
  return a;
}
void LLVMAddAttributeAtIndex(LLVMValueRef v, unsigned i, LLVMAttributeRef a) {
  Attr *x = arena(v->c, sizeof(*x));
  x->index = i;
  x->value = a;
  x->next = v->attrs;
  v->attrs = x;
}
void LLVMAddCallSiteAttribute(LLVMValueRef v, unsigned i, LLVMAttributeRef a) {
  LLVMAddAttributeAtIndex(v, i, a);
}
/* Calls retain operands until printing, because ABI attributes arrive
 * afterward. */
typedef struct {
  LLVMTypeRef type;
  LLVMValueRef function;
  LLVMValueRef *args;
  unsigned count;
} Call;
LLVMValueRef LLVMBuildCall2(LLVMBuilderRef b, LLVMTypeRef t, LLVMValueRef f,
                            LLVMValueRef *args, unsigned n, const char *name) {
  (void)name;
  LLVMValueRef v = inst(b, t->result, NULL);
  Call *call = arena(b->c, sizeof(*call));
  call->type = t;
  call->function = f;
  call->count = n;
  call->args = arena(b->c, (n ? n : 1) * sizeof(*args));
  if (n)
    memcpy(call->args, args, n * sizeof(*args));
  v->operand = (LLVMValueRef)call;
  return v;
}
LLVMValueRef LLVMBuildMemMove(LLVMBuilderRef b, LLVMValueRef d, unsigned da,
                              LLVMValueRef s, unsigned sa, LLVMValueRef n) {
  (void)da;
  (void)sa;
  LLVMModuleRef m = b->block->function->module;
  LLVMTypeRef types[] = {d->type, s->type, n->type,
                         LLVMInt1TypeInContext(b->c)};
  LLVMTypeRef ft = LLVMFunctionType(LLVMVoidTypeInContext(b->c), types, 4, 0);
  LLVMValueRef f = LLVMAddFunction(
      m, fmt(b->c, "llvm.memmove.p0.p0.i%u", n->type->bits), ft);
  LLVMValueRef args[] = {d, s, n, LLVMConstInt(types[3], 0, 0)};
  return LLVMBuildCall2(b, ft, f, args, 4, "");
}
LLVMValueRef LLVMBuildGlobalStringPtr(LLVMBuilderRef b, const char *s,
                                      const char *name) {
  (void)name;
  LLVMValueRef init = LLVMConstStringInContext(b->c, s, (unsigned)strlen(s), 0);
  LLVMValueRef g = LLVMAddGlobal(b->block->function->module, init->type,
                                 fmt(b->c, ".str.%u", b->c->serial++));
  g->linkage = LLVMPrivateLinkage;
  g->constant = true;
  g->initializer = init;
  return g;
}
static LLVMValueRef const_bin(const char *op, LLVMValueRef x, LLVMValueRef y) {
  if (x->type->bits > 64) {
    x->c->error = "constant arithmetic wider than 64 bits unsupported";
    return LLVMConstNull(x->type);
  }
  if (x->constant_int && y->constant_int) {
    uint64_t a = x->integer, b = y->integer, z = 0;
    if (!strcmp(op, "add"))
      z = a + b;
    else if (!strcmp(op, "sub"))
      z = a - b;
    else if (!strcmp(op, "mul"))
      z = a * b;
    else if (!strcmp(op, "and"))
      z = a & b;
    else if (!strcmp(op, "or"))
      z = a | b;
    else if (!strcmp(op, "xor"))
      z = a ^ b;
    else if (!strcmp(op, "shl") && b < 64)
      z = a << b;
    else if (!strcmp(op, "lshr") && b < 64)
      z = a >> b;
    else {
      x->c->error = "unsupported constant integer operation";
      return LLVMConstNull(x->type);
    }
    return LLVMConstInt(x->type, z, 0);
  }
  x->c->error = "unsupported constant expression";
  return LLVMConstNull(x->type);
}
#define CBIN(Name, op)                                                         \
  LLVMValueRef LLVMConst##Name(LLVMValueRef x, LLVMValueRef y) {               \
    return const_bin(op, x, y);                                                \
  }
CBIN(Add, "add")
CBIN(Sub, "sub")
CBIN(Mul, "mul")
CBIN(And, "and")
CBIN(Or, "or")
CBIN(Xor, "xor") CBIN(Shl, "shl") CBIN(LShr, "lshr") LLVMValueRef
    LLVMConstNeg(LLVMValueRef v) {
  return LLVMConstSub(LLVMConstNull(v->type), v);
}
LLVMValueRef LLVMConstNot(LLVMValueRef v) {
  return LLVMConstXor(v, LLVMConstInt(v->type, UINT64_MAX, 0));
}
LLVMValueRef LLVMConstTrunc(LLVMValueRef v, LLVMTypeRef t) {
  if (v->constant_int)
    return LLVMConstInt(t, v->integer, 0);
  v->c->error = "unsupported constant truncation";
  return LLVMConstNull(t);
}
static void print_inst(Text *s, LLVMValueRef v) {
  add(s, "  ");
  if (v->type->kind)
    add(s, "%s = ", v->name);
  if (v->text)
    add(s, "%s", v->text);
  else {
    Call *c = (Call *)v->operand;
    add(s, "call");
    attributes(s, v, 0);
    add(s, " %s %s(", ts(c->type->variadic ? c->type : c->type->result),
        c->function->name);
    for (unsigned i = 0; i < c->count; i++) {
      if (i)
        add(s, ", ");
      add(s, "%s", ts(c->args[i]->type));
      attributes(s, v, i + 1);
      add(s, " %s", c->args[i]->name);
    }
    add(s, ")");
    attributes(s, v, ~0u);
  }
  if (v->alignment)
    add(s, ", align %u", v->alignment);
  if (v->debug)
    add(s, ", !dbg %s", v->debug->ref);
  add(s, "\n");
}
static const char *linkage(unsigned l) {
  return l == LLVMInternalLinkage  ? "internal "
         : l == LLVMPrivateLinkage ? "private "
         : l == 7                  ? "appending "
                                   : "";
}
char *LLVMPrintModuleToString(LLVMModuleRef m) {
  Text s = {.c = m->c};
  add(&s, "; Generated by Dyn's independent LLVM syntax writer.\n");
  if (m->triple)
    add(&s, "target triple = %s\n", quote(m->c, m->triple));
  if (m->layout)
    add(&s, "target datalayout = %s\n", quote(m->c, m->layout));
  for (LLVMTypeRef t = m->c->types; t; t = t->next)
    if (t->name) {
      add(&s, "%%%s = type ", identifier(m->c, t->name));
      print_type(&s, t, true);
      add(&s, "\n");
    }
  for (LLVMValueRef v = m->first; v; v = v->next) {
    if (v->global) {
      add(&s, "%s = %s%s", v->name,
          v->initializer ? linkage(v->linkage) : "external ",
          v->visibility == 1 ? "hidden " : "");
      add(&s, "%s %s", v->constant ? "constant" : "global", ts(v->declared));
      if (v->initializer)
        add(&s, " %s", v->initializer->name);
      if (v->section)
        add(&s, ", section %s", quote(m->c, v->section));
      if (v->alignment)
        add(&s, ", align %u", v->alignment);
      if (v->debug)
        add(&s, ", !dbg %s", v->debug->ref);
      add(&s, "\n");
      continue;
    }
    add(&s, "%s %s%s", v->first ? "define" : "declare",
        v->first ? linkage(v->linkage) : "",
        v->visibility == 1 ? "hidden " : "");
    attributes(&s, v, 0);
    add(&s, " %s %s(", ts(v->declared->result), v->name);
    for (unsigned i = 0; i < v->declared->count; i++) {
      if (i)
        add(&s, ", ");
      add(&s, "%s", ts(v->declared->members[i]));
      attributes(&s, v, i + 1);
      if (v->first)
        add(&s, " %s", v->params[i]->name);
    }
    if (v->declared->variadic)
      add(&s, v->declared->count ? ", ..." : "...");
    add(&s, ")");
    attributes(&s, v, ~0u);
    if (!v->first) {
      add(&s, "\n");
      continue;
    }
    if (v->debug)
      add(&s, " !dbg %s", v->debug->ref);
    add(&s, " {\n");
    for (LLVMBasicBlockRef b = v->first; b; b = b->next) {
      add(&s, "%s:\n", identifier(m->c, b->name));
      for (LLVMValueRef i = b->first; i; i = i->next)
        print_inst(&s, i);
    }
    add(&s, "}\n");
  }
  if (m->unit)
    add(&s, "!llvm.dbg.cu = !{%s}\n", m->unit->ref);
  if (m->flags)
    add(&s, "!llvm.module.flags = !{%s}\n", m->flags);
  for (LLVMMetadataRef md = m->c->metadata; md; md = md->next)
    if (md->text)
      add(&s, "%s = %s\n", md->ref, md->text);
  if (s.failed || m->c->error) {
    free(s.data);
    if (s.owner)
      s.owner->data = NULL;
    return NULL;
  }
  if (s.owner)
    s.owner->data = NULL;
  return s.data;
}
void LLVMDisposeMessage(char *s) { free(s); }
int dyn_text_verify(LLVMModuleRef m, char **error) {
  const char *why = m->c->error;
  for (LLVMValueRef f = m->first; !why && f; f = f->next)
    if (f->function)
      for (LLVMBasicBlockRef b = f->first; !why && b; b = b->next) {
        if (!b->last || !b->last->terminator)
          why = "unterminated block in independent LLVM export";
        for (LLVMValueRef v = b->first; !why && v; v = v->next)
          if (v->terminator && v->next)
            why = "instruction after terminator in independent LLVM export";
      }
  if (why) {
    size_t n = strlen(why) + 1;
    *error = malloc(n);
    if (*error)
      memcpy(*error, why, n);
    return 1;
  }
  return 0;
}
static LLVMMetadataRef md(LLVMContextRef c, const char *text) {
  LLVMMetadataRef m = arena(c, sizeof(*m));
  m->c = c;
  m->ref = fmt(c, "!%u", c->serial++);
  m->text = text;
  m->next = c->metadata;
  c->metadata = m;
  return m;
}
static const char *mr(LLVMMetadataRef m) { return m ? m->ref : "null"; }
static const char *qn(LLVMContextRef c, const char *s, size_t n) {
  char *p = arena(c, n + 1);
  memcpy(p, s, n);
  return quote(c, p);
}
static const char *tuple(LLVMContextRef c, LLVMMetadataRef *nodes, unsigned n) {
  Text t = {.c = c};
  add(&t, "!{");
  for (unsigned i = 0; i < n; i++) {
    if (i)
      add(&t, ", ");
    add(&t, "%s", mr(nodes[i]));
  }
  add(&t, "}");
  return md(c, finish(c, &t))->ref;
}
LLVMMetadataRef LLVMValueAsMetadata(LLVMValueRef a0) {
  LLVMMetadataRef m = md(a0->c, NULL);
  m->ref = fmt(a0->c, "%s %s", ts(a0->type), a0->name);
  return m;
}
void LLVMAddModuleFlag(LLVMModuleRef a0, int a1, const char *a2, size_t a3,
                       LLVMMetadataRef a4) {
  LLVMMetadataRef m = md(a0->c, fmt(a0->c, "!{i32 %d, !%s, %s}", a1 + 1,
                                    qn(a0->c, a2, a3), mr(a4)));
  a0->flags = a0->flags ? fmt(a0->c, "%s, %s", a0->flags, m->ref) : m->ref;
}
unsigned LLVMGetMDKindIDInContext(LLVMContextRef a0, const char *a1,
                                  unsigned a2) {
  (void)a0;
  (void)a1;
  (void)a2;
  return 1;
}
void LLVMGlobalSetMetadata(LLVMValueRef a0, unsigned a1, LLVMMetadataRef a2) {
  (void)a1;
  a0->debug = a2;
}
unsigned LLVMDebugMetadataVersion(void) { return 3; }
LLVMDIBuilderRef LLVMCreateDIBuilder(LLVMModuleRef a0) {
  LLVMDIBuilderRef b = arena(a0->c, sizeof(*b));
  b->module = a0;
  return b;
}
void LLVMDisposeDIBuilder(LLVMDIBuilderRef a0) { (void)a0; }
void LLVMDIBuilderFinalize(LLVMDIBuilderRef a0) { (void)a0; }
LLVMMetadataRef LLVMDIBuilderCreateFile(LLVMDIBuilderRef a0, const char *a1,
                                        size_t a2, const char *a3, size_t a4) {
  LLVMContextRef c = a0->module->c;
  return md(c, fmt(c, "!DIFile(filename: %s, directory: %s)", qn(c, a1, a2),
                   qn(c, a3, a4)));
}
LLVMMetadataRef LLVMDIBuilderCreateCompileUnit(
    LLVMDIBuilderRef a0, unsigned a1, LLVMMetadataRef a2, const char *a3,
    size_t a4, int a5, const char *a6, size_t a7, unsigned a8, const char *a9,
    size_t a10, unsigned a11, unsigned a12, int a13, int a14, const char *a15,
    size_t a16, const char *a17, size_t a18) {
  LLVMContextRef c = a0->module->c;
  (void)a6;
  (void)a7;
  (void)a8;
  (void)a9;
  (void)a10;
  (void)a11;
  (void)a12;
  (void)a13;
  (void)a14;
  (void)a15;
  (void)a16;
  (void)a17;
  (void)a18;
  a0->module->unit =
      md(c, fmt(c,
                "distinct !DICompileUnit(language: %u, file: %s, producer: %s, "
                "isOptimized: %s, runtimeVersion: 0, emissionKind: FullDebug)",
                a1, mr(a2), qn(c, a3, a4), a5 ? "true" : "false"));
  return a0->module->unit;
}
LLVMMetadataRef LLVMDIBuilderCreateSubroutineType(LLVMDIBuilderRef a0,
                                                  LLVMMetadataRef a1,
                                                  LLVMMetadataRef *a2,
                                                  unsigned a3, unsigned a4) {
  (void)a1;
  (void)a4;
  LLVMContextRef c = a0->module->c;
  return md(c, fmt(c, "!DISubroutineType(types: %s)", tuple(c, a2, a3)));
}
LLVMMetadataRef LLVMDIBuilderCreateFunction(
    LLVMDIBuilderRef a0, LLVMMetadataRef a1, const char *a2, size_t a3,
    const char *a4, size_t a5, LLVMMetadataRef a6, unsigned a7,
    LLVMMetadataRef a8, int a9, int a10, unsigned a11, unsigned a12, int a13) {
  (void)a12;
  LLVMContextRef c = a0->module->c;
  return md(
      c,
      fmt(c,
          "distinct !DISubprogram(name: %s, linkageName: %s, scope: %s, file: "
          "%s, line: %u, type: %s, scopeLine: %u, spFlags: %s%s%s, unit: %s)",
          qn(c, a2, a3), qn(c, a4, a5), mr(a1), mr(a6), a7, mr(a8), a11,
          a10 ? "DISPFlagDefinition" : "DISPFlagZero",
          a9 ? " | DISPFlagLocalToUnit" : "", a13 ? " | DISPFlagOptimized" : "",
          mr(a0->module->unit)));
}
LLVMMetadataRef LLVMDIBuilderCreateDebugLocation(LLVMContextRef a0, unsigned a1,
                                                 unsigned a2,
                                                 LLVMMetadataRef a3,
                                                 LLVMMetadataRef a4) {
  return md(a0, fmt(a0, "!DILocation(line: %u, column: %u, scope: %s%s%s)", a1,
                    a2, mr(a3), a4 ? ", inlinedAt: " : "", a4 ? mr(a4) : ""));
}
LLVMMetadataRef LLVMDIBuilderCreateBasicType(LLVMDIBuilderRef a0,
                                             const char *a1, size_t a2,
                                             uint64_t a3, unsigned a4,
                                             unsigned a5) {
  (void)a5;
  LLVMContextRef c = a0->module->c;
  return md(c, fmt(c, "!DIBasicType(name: %s, size: %" PRIu64 ", encoding: %u)",
                   qn(c, a1, a2), a3, a4));
}
LLVMMetadataRef LLVMDIBuilderCreatePointerType(LLVMDIBuilderRef a0,
                                               LLVMMetadataRef a1, uint64_t a2,
                                               uint32_t a3, unsigned a4,
                                               const char *a5, size_t a6) {
  (void)a4;
  LLVMContextRef c = a0->module->c;
  return md(c, fmt(c,
                   "!DIDerivedType(tag: DW_TAG_pointer_type, name: %s, "
                   "baseType: %s, size: %" PRIu64 ", align: %u)",
                   qn(c, a5, a6), mr(a1), a2, a3));
}
LLVMMetadataRef
LLVMDIBuilderCreateMemberType(LLVMDIBuilderRef a0, LLVMMetadataRef a1,
                              const char *a2, size_t a3, LLVMMetadataRef a4,
                              unsigned a5, uint64_t a6, uint32_t a7,
                              uint64_t a8, unsigned a9, LLVMMetadataRef a10) {
  (void)a9;
  LLVMContextRef c = a0->module->c;
  return md(c, fmt(c,
                   "!DIDerivedType(tag: DW_TAG_member, name: %s, scope: %s, "
                   "file: %s, line: %u, baseType: %s, size: %" PRIu64
                   ", align: %u, offset: %" PRIu64 ")",
                   qn(c, a2, a3), mr(a1), mr(a4), a5, mr(a10), a6, a7, a8));
}
LLVMMetadataRef LLVMDIBuilderCreateStructType(
    LLVMDIBuilderRef a0, LLVMMetadataRef a1, const char *a2, size_t a3,
    LLVMMetadataRef a4, unsigned a5, uint64_t a6, uint32_t a7, unsigned a8,
    LLVMMetadataRef a9, LLVMMetadataRef *a10, unsigned a11, unsigned a12,
    LLVMMetadataRef a13, const char *a14, size_t a15) {
  (void)a8;
  (void)a9;
  (void)a12;
  (void)a13;
  (void)a14;
  (void)a15;
  LLVMContextRef c = a0->module->c;
  return md(c,
            fmt(c,
                "!DICompositeType(tag: DW_TAG_structure_type, name: %s, scope: "
                "%s, file: %s, line: %u, size: %" PRIu64
                ", align: %u, elements: %s)",
                qn(c, a2, a3), mr(a1), mr(a4), a5, a6, a7, tuple(c, a10, a11)));
}
LLVMMetadataRef LLVMDIBuilderCreateReplaceableCompositeType(
    LLVMDIBuilderRef a0, unsigned a1, const char *a2, size_t a3,
    LLVMMetadataRef a4, LLVMMetadataRef a5, unsigned a6, unsigned a7,
    uint64_t a8, uint32_t a9, unsigned a10, const char *a11, size_t a12) {
  (void)a1;
  (void)a4;
  (void)a5;
  (void)a6;
  (void)a7;
  (void)a8;
  (void)a9;
  (void)a10;
  (void)a11;
  (void)a12;
  LLVMContextRef c = a0->module->c;
  return md(c, fmt(c,
                   "!DICompositeType(tag: DW_TAG_structure_type, name: %s, "
                   "flags: DIFlagFwdDecl)",
                   qn(c, a2, a3)));
}
LLVMMetadataRef
LLVMDIBuilderCreateUnionType(LLVMDIBuilderRef a0, LLVMMetadataRef a1,
                             const char *a2, size_t a3, LLVMMetadataRef a4,
                             unsigned a5, uint64_t a6, uint32_t a7, unsigned a8,
                             LLVMMetadataRef *a9, unsigned a10, unsigned a11,
                             const char *a12, size_t a13) {
  (void)a8;
  (void)a11;
  (void)a12;
  (void)a13;
  LLVMContextRef c = a0->module->c;
  return md(
      c, fmt(c,
             "!DICompositeType(tag: DW_TAG_union_type, name: %s, scope: %s, "
             "file: %s, line: %u, size: %" PRIu64 ", align: %u, elements: %s)",
             qn(c, a2, a3), mr(a1), mr(a4), a5, a6, a7, tuple(c, a9, a10)));
}
void LLVMMetadataReplaceAllUsesWith(LLVMMetadataRef a0, LLVMMetadataRef a1) {
  a0->text = a1->text;
}
LLVMMetadataRef LLVMDIBuilderGetOrCreateSubrange(LLVMDIBuilderRef a0,
                                                 int64_t a1, int64_t a2) {
  LLVMContextRef c = a0->module->c;
  return md(c,
            fmt(c, "!DISubrange(count: %" PRId64 ", lowerBound: %" PRId64 ")",
                a2, a1));
}
LLVMMetadataRef LLVMDIBuilderCreateArrayType(LLVMDIBuilderRef a0, uint64_t a1,
                                             uint32_t a2, LLVMMetadataRef a3,
                                             LLVMMetadataRef *a4, unsigned a5) {
  LLVMContextRef c = a0->module->c;
  return md(c, fmt(c,
                   "!DICompositeType(tag: DW_TAG_array_type, baseType: %s, "
                   "size: %" PRIu64 ", align: %u, elements: %s)",
                   mr(a3), a1, a2, tuple(c, a4, a5)));
}
LLVMMetadataRef LLVMDIBuilderCreateEnumerator(LLVMDIBuilderRef a0,
                                              const char *a1, size_t a2,
                                              int64_t a3, int a4) {
  LLVMContextRef c = a0->module->c;
  return md(
      c, fmt(c, "!DIEnumerator(name: %s, value: %" PRId64 ", isUnsigned: %s)",
             qn(c, a1, a2), a3, a4 ? "true" : "false"));
}
LLVMMetadataRef LLVMDIBuilderCreateEnumerationType(
    LLVMDIBuilderRef a0, LLVMMetadataRef a1, const char *a2, size_t a3,
    LLVMMetadataRef a4, unsigned a5, uint64_t a6, uint32_t a7,
    LLVMMetadataRef *a8, unsigned a9, LLVMMetadataRef a10) {
  LLVMContextRef c = a0->module->c;
  return md(c, fmt(c,
                   "!DICompositeType(tag: DW_TAG_enumeration_type, name: %s, "
                   "scope: %s, file: %s, line: %u, baseType: %s, size: %" PRIu64
                   ", align: %u, elements: %s)",
                   qn(c, a2, a3), mr(a1), mr(a4), a5, mr(a10), a6, a7,
                   tuple(c, a8, a9)));
}
LLVMMetadataRef LLVMDIBuilderCreateAutoVariable(LLVMDIBuilderRef a0,
                                                LLVMMetadataRef a1,
                                                const char *a2, size_t a3,
                                                LLVMMetadataRef a4, unsigned a5,
                                                LLVMMetadataRef a6, int a7,
                                                unsigned a8, uint32_t a9) {
  (void)a7;
  (void)a8;
  LLVMContextRef c = a0->module->c;
  return md(c, fmt(c,
                   "!DILocalVariable(name: %s, scope: %s, file: %s, line: %u, "
                   "type: %s, align: %u)",
                   qn(c, a2, a3), mr(a1), mr(a4), a5, mr(a6), a9));
}
LLVMMetadataRef
LLVMDIBuilderCreateParameterVariable(LLVMDIBuilderRef a0, LLVMMetadataRef a1,
                                     const char *a2, size_t a3, unsigned a4,
                                     LLVMMetadataRef a5, unsigned a6,
                                     LLVMMetadataRef a7, int a8, unsigned a9) {
  (void)a8;
  (void)a9;
  LLVMContextRef c = a0->module->c;
  return md(c, fmt(c,
                   "!DILocalVariable(name: %s, arg: %u, scope: %s, file: %s, "
                   "line: %u, type: %s)",
                   qn(c, a2, a3), a4, mr(a1), mr(a5), a6, mr(a7)));
}
LLVMMetadataRef LLVMDIBuilderCreateExpression(LLVMDIBuilderRef a0, int64_t *a1,
                                              size_t a2) {
  LLVMContextRef c = a0->module->c;
  Text s = {.c = c};
  add(&s, "!DIExpression(");
  for (size_t i = 0; i < a2; i++) {
    if (i)
      add(&s, ", ");
    add(&s, "%" PRId64, a1[i]);
  }
  add(&s, ")");
  return md(c, finish(c, &s));
}
LLVMValueRef LLVMDIBuilderInsertDeclareRecordAtEnd(
    LLVMDIBuilderRef a0, LLVMValueRef a1, LLVMMetadataRef a2,
    LLVMMetadataRef a3, LLVMMetadataRef a4, LLVMBasicBlockRef a5) {
  LLVMContextRef c = a0->module->c;
  LLVMTypeRef metadata = simple(c, 14),
              types[] = {metadata, metadata, metadata};
  LLVMAddFunction(a0->module, "llvm.dbg.declare",
                  LLVMFunctionType(LLVMVoidTypeInContext(c), types, 3, 0));
  struct LLVMOpaqueBuilder b = {.c = c, .block = a5, .location = a4};
  return inst(&b, LLVMVoidTypeInContext(c),
              fmt(c,
                  "call void @llvm.dbg.declare(metadata %s %s, metadata %s, "
                  "metadata %s)",
                  ts(a1->type), a1->name, mr(a2), mr(a3)));
}
LLVMValueRef LLVMDIBuilderInsertDbgValueRecordAtEnd(
    LLVMDIBuilderRef a0, LLVMValueRef a1, LLVMMetadataRef a2,
    LLVMMetadataRef a3, LLVMMetadataRef a4, LLVMBasicBlockRef a5) {
  LLVMContextRef c = a0->module->c;
  LLVMTypeRef metadata = simple(c, 14),
              types[] = {metadata, metadata, metadata};
  LLVMAddFunction(a0->module, "llvm.dbg.value",
                  LLVMFunctionType(LLVMVoidTypeInContext(c), types, 3, 0));
  struct LLVMOpaqueBuilder b = {.c = c, .block = a5, .location = a4};
  return inst(
      &b, LLVMVoidTypeInContext(c),
      fmt(c,
          "call void @llvm.dbg.value(metadata %s %s, metadata %s, metadata %s)",
          ts(a1->type), a1->name, mr(a2), mr(a3)));
}
LLVMMetadataRef LLVMDIBuilderCreateGlobalVariableExpression(
    LLVMDIBuilderRef a0, LLVMMetadataRef a1, const char *a2, size_t a3,
    const char *a4, size_t a5, LLVMMetadataRef a6, unsigned a7,
    LLVMMetadataRef a8, int a9, LLVMMetadataRef a10, LLVMMetadataRef a11,
    uint32_t a12) {
  (void)a11;
  LLVMContextRef c = a0->module->c;
  LLVMMetadataRef variable =
      md(c, fmt(c,
                "distinct !DIGlobalVariable(name: %s, linkageName: %s, scope: "
                "%s, file: %s, line: %u, type: %s, isLocal: %s, isDefinition: "
                "true, align: %u)",
                qn(c, a2, a3), qn(c, a4, a5), mr(a1), mr(a6), a7, mr(a8),
                a9 ? "true" : "false", a12));
  return md(c, fmt(c, "!DIGlobalVariableExpression(var: %s, expr: %s)",
                   mr(variable), mr(a10)));
}
void LLVMSetSubprogram(LLVMValueRef a0, LLVMMetadataRef a1) { a0->debug = a1; }
void LLVMSetCurrentDebugLocation2(LLVMBuilderRef a0, LLVMMetadataRef a1) {
  a0->location = a1;
}
