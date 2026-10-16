/* WebAssembly linking-v2 object linker. No external linker or LLVM API. */
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include "link_wasm.h"
#include "../tools/backend-experiment/output.h"
#include "host.h"
#include <setjmp.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
  unsigned char *p;
  size_t n, cap;
} Buf;
typedef struct {
  unsigned char *p, *end;
} Read;
typedef struct {
  unsigned char id;
  unsigned char *p;
  size_t n;
} Section;
typedef struct {
  char *module, *name;
  unsigned kind;
  uint32_t type;
} Import;
typedef struct {
  char *name;
  unsigned kind, flags;
  uint32_t index, offset, size, value, type;
} Symbol;
typedef struct {
  unsigned char *p;
  uint32_t n, alignment, address;
} Segment;
typedef struct {
  char *name;
  unsigned kind;
  uint32_t index;
} Export;
typedef struct {
  unsigned char *file;
  Section *sections;
  size_t ns;
  Import *imports;
  size_t ni;
  uint32_t nfimp, ngimp;
  uint32_t *types, nt, *functions, nf, *fmap, *gmap;
  Buf *globals;
  uint32_t ng;
  Segment *data;
  uint32_t nd;
  Symbol *symbols;
  uint32_t ny;
  Export *exports;
  uint32_t ne;
  unsigned char **bodies;
  uint32_t *sizes;
} Object;
typedef struct Allocation {
  void *p;
  struct Allocation *next;
} Allocation;
typedef struct {
  jmp_buf failed;
  Allocation *allocations;
  Object *objects;
  size_t count;
  Buf *types;
  uint32_t nt;
  Import *imports;
  uint32_t ni;
  const char *const *allowed;
  size_t na;
  bool wasi;
  Export *exports;
  uint32_t ne;
} Link;
static void fail(Link *l, const char *fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  fputs("error: Wasm linker: ", stderr);
  vfprintf(stderr, fmt, ap);
  fputc('\n', stderr);
  va_end(ap);
  longjmp(l->failed, 1);
}
static void *alloc(Link *l, size_t n) {
  if (!n)
    n = 1;
  void *p = calloc(1, n);
  Allocation *a = malloc(sizeof(*a));
  if (!p || !a) {
    free(p);
    free(a);
    fail(l, "out of memory");
  }
  *a = (Allocation){p, l->allocations};
  l->allocations = a;
  return p;
}
static void put(Link *l, Buf *b, const void *p, size_t n) {
  if (n > SIZE_MAX - b->n)
    fail(l, "output too large");
  if (b->n + n > b->cap) {
    size_t cap = b->n + n + 256;
    unsigned char *q = alloc(l, cap);
    if (b->n)
      memcpy(q, b->p, b->n);
    b->p = q;
    b->cap = cap;
  }
  if (n)
    memcpy(b->p + b->n, p, n);
  b->n += n;
}
static void byte(Link *l, Buf *b, unsigned v) {
  unsigned char c = (unsigned char)v;
  put(l, b, &c, 1);
}
static void uleb(Link *l, Buf *b, uint32_t n) {
  do {
    unsigned c = n & 127;
    n >>= 7;
    byte(l, b, c | (n ? 128 : 0));
  } while (n);
}
static void sleb(Link *l, Buf *b, int32_t n) {
  bool more;
  do {
    unsigned c = (unsigned)n & 127;
    n >>= 7;
    more = !((n == 0 && !(c & 64)) || (n == -1 && (c & 64)));
    byte(l, b, c | (more ? 128 : 0));
  } while (more);
}
static unsigned get(Link *l, Read *r) {
  if (r->p == r->end)
    fail(l, "truncated object");
  return *r->p++;
}
static uint32_t number(Link *l, Read *r) {
  uint32_t n = 0;
  for (unsigned i = 0; i < 5; i++) {
    unsigned c = get(l, r);
    if (i == 4 && (c & 0x70))
      fail(l, "invalid u32 LEB");
    n |= (c & 127) << (7 * i);
    if (!(c & 128))
      return n;
  }
  fail(l, "invalid LEB");
  return 0;
}
static int32_t signed_number(Link *l, Read *r) {
  uint32_t n = 0;
  unsigned c = 0, shift = 0;
  do {
    if (shift >= 35)
      fail(l, "invalid signed LEB");
    c = get(l, r);
    n |= (uint32_t)(c & 127) << shift;
    shift += 7;
  } while (c & 128);
  if (shift < 32 && (c & 64))
    n |= ~0u << shift;
  return (int32_t)n;
}
static unsigned char *take(Link *l, Read *r, size_t n) {
  if (n > (size_t)(r->end - r->p))
    fail(l, "truncated object");
  unsigned char *p = r->p;
  r->p += n;
  return p;
}
static char *name(Link *l, Read *r) {
  uint32_t n = number(l, r);
  char *s = alloc(l, (size_t)n + 1);
  memcpy(s, take(l, r, n), n);
  if (memchr(s, 0, n))
    fail(l, "NUL in symbol name");
  return s;
}
static void string(Link *l, Buf *b, const char *s) {
  size_t n = strlen(s);
  if (n > UINT32_MAX)
    fail(l, "name too long");
  uleb(l, b, (uint32_t)n);
  put(l, b, s, n);
}
static void section(Link *l, Buf *b, unsigned id, Buf *body) {
  if (body->n > UINT32_MAX)
    fail(l, "section too large");
  byte(l, b, id);
  uleb(l, b, (uint32_t)body->n);
  put(l, b, body->p, body->n);
}
static Read reader(Section *s) { return (Read){s->p, s->p + s->n}; }
static Import *import_at(Link *l, Object *o, unsigned kind, uint32_t index) {
  for (size_t i = 0; i < o->ni; i++)
    if (o->imports[i].kind == kind && index-- == 0)
      return &o->imports[i];
  fail(l, "invalid imported symbol index");
  return NULL;
}
static uint32_t checked_count(Link *l, Read *r, size_t size) {
  uint32_t n = number(l, r);
  if (n > (size_t)(r->end - r->p) + 1 || n > SIZE_MAX / size)
    fail(l, "invalid vector count");
  return n;
}
static void limits(Link *l, Read *r) {
  unsigned flags = number(l, r);
  if (flags > 1)
    fail(l, "shared/memory64 limits unsupported");
  (void)number(l, r);
  if (flags & 1)
    (void)number(l, r);
}
static void expression(Link *l, Read *r) {
  unsigned op = get(l, r);
  if (op == 0x41 || op == 0x42) {
    unsigned n = 0;
    while (get(l, r) & 128)
      if (++n > 9)
        fail(l, "invalid constant");
  } else if (op == 0x43)
    take(l, r, 4);
  else if (op == 0x44)
    take(l, r, 8);
  else
    fail(l, "unsupported global initializer");
  if (get(l, r) != 0xb)
    fail(l, "unsupported initializer expression");
}
static unsigned char *read_file(Link *l, const char *path, size_t *length) {
  FILE *f = fopen(path, "rb");
  if (!f)
    fail(l, "cannot read %s", path);
  if (fseek(f, 0, SEEK_END) || ftell(f) < 8) {
    fclose(f);
    fail(l, "invalid object %s", path);
  }
  *length = (size_t)ftell(f);
  rewind(f);
  unsigned char *data = alloc(l, *length);
  size_t got = fread(data, 1, *length, f);
  fclose(f);
  if (got != *length)
    fail(l, "cannot read %s", path);
  return data;
}
static void parse(Link *l, Object *o, unsigned char *data, size_t length,
                  const char *path) {
  o->file = data;
  if (length < 8 || memcmp(data, "\0asm\1\0\0\0", 8))
    fail(l, "%s is not a wasm32 linking object (bitcode unsupported)", path);
  Read r = {o->file + 8, o->file + length};
  size_t cap = (size_t)length / 2 + 1;
  o->sections = alloc(l, cap * sizeof(Section));
  while (r.p < r.end) {
    unsigned id = get(l, &r);
    uint32_t n = number(l, &r);
    unsigned char *p = take(l, &r, n);
    o->sections[o->ns++] = (Section){(unsigned char)id, p, n};
  }
  bool linking = false;
  for (size_t si = 0; si < o->ns; si++) {
    Section *s = &o->sections[si];
    r = reader(s);
    if (s->id == 0 || s->id == 12)
      continue;
    uint32_t n = checked_count(l, &r, 1);
    if (s->id == 1) {
      o->nt = n;
      o->types = alloc(l, (size_t)n * sizeof(uint32_t));
      for (uint32_t i = 0; i < n; i++) {
        unsigned char *start = r.p;
        if (get(l, &r) != 0x60)
          fail(l, "unsupported function type");
        uint32_t k = number(l, &r);
        take(l, &r, k);
        k = number(l, &r);
        take(l, &r, k);
        size_t bytes = (size_t)(r.p - start);
        uint32_t at = 0;
        for (; at < l->nt; at++)
          if (l->types[at].n == bytes && !memcmp(l->types[at].p, start, bytes))
            break;
        if (at == l->nt) {
          Buf *a = alloc(l, (size_t)(l->nt + 1) * sizeof(Buf));
          if (l->nt)
            memcpy(a, l->types, l->nt * sizeof(Buf));
          l->types = a;
          l->types[l->nt++] = (Buf){start, bytes, bytes};
        }
        o->types[i] = at;
      }
    } else if (s->id == 2) {
      o->ni = n;
      o->imports = alloc(l, (size_t)n * sizeof(Import));
      for (uint32_t i = 0; i < n; i++) {
        Import *im = &o->imports[i];
        im->module = name(l, &r);
        im->name = name(l, &r);
        im->kind = get(l, &r);
        if (im->kind == 0) {
          im->type = number(l, &r);
          o->nfimp++;
        } else if (im->kind == 1) {
          if (get(l, &r) != 0x70)
            fail(l, "unsupported table type");
          limits(l, &r);
        } else if (im->kind == 2)
          limits(l, &r);
        else if (im->kind == 3) {
          im->type = get(l, &r);
          if (get(l, &r) > 1)
            fail(l, "invalid global mutability");
          o->ngimp++;
        } else
          fail(l, "unsupported import kind");
      }
    } else if (s->id == 3) {
      o->nf = n;
      o->functions = alloc(l, (size_t)n * sizeof(uint32_t));
      for (uint32_t i = 0; i < n; i++)
        o->functions[i] = number(l, &r);
    } else if (s->id == 6) {
      o->ng = n;
      o->globals = alloc(l, (size_t)n * sizeof(Buf));
      for (uint32_t i = 0; i < n; i++) {
        unsigned char *p = r.p;
        take(l, &r, 2);
        expression(l, &r);
        o->globals[i] = (Buf){p, (size_t)(r.p - p), (size_t)(r.p - p)};
      }
    } else if (s->id == 7) {
      o->ne = n;
      o->exports = alloc(l, (size_t)n * sizeof(Export));
      for (uint32_t i = 0; i < n; i++) {
        o->exports[i].name = name(l, &r);
        o->exports[i].kind = get(l, &r);
        o->exports[i].index = number(l, &r);
      }
    } else if (s->id == 10) {
      if (n != o->nf)
        fail(l, "function/code count mismatch");
      o->bodies = alloc(l, (size_t)n * sizeof(void *));
      o->sizes = alloc(l, (size_t)n * sizeof(uint32_t));
      for (uint32_t i = 0; i < n; i++) {
        o->sizes[i] = number(l, &r);
        o->bodies[i] = take(l, &r, o->sizes[i]);
      }
    } else if (s->id == 11) {
      o->nd = n;
      o->data = alloc(l, (size_t)n * sizeof(Segment));
      for (uint32_t i = 0; i < n; i++) {
        unsigned flags = number(l, &r);
        if (flags == 2) {
          if (number(l, &r))
            fail(l, "multiple memories unsupported");
        } else if (flags > 1)
          fail(l, "invalid data segment");
        if (flags != 1)
          expression(l, &r);
        o->data[i].n = number(l, &r);
        o->data[i].p = take(l, &r, o->data[i].n);
      }
    } else if (s->id == 8 || s->id == 13)
      fail(l, "start/tag sections unsupported in objects");
  }
  for (size_t si = 0; si < o->ns; si++) {
    Section *s = &o->sections[si];
    if (s->id)
      continue;
    r = reader(s);
    char *custom = name(l, &r);
    if (strcmp(custom, "linking"))
      continue;
    linking = true;
    if (number(l, &r) != 2)
      fail(l, "unsupported linking metadata version");
    while (r.p < r.end) {
      unsigned kind = get(l, &r);
      uint32_t n = number(l, &r);
      unsigned char *p = take(l, &r, n);
      Read sub = {p, p + n};
      if (kind == 5) {
        uint32_t count = number(l, &sub);
        if (count != o->nd)
          fail(l, "segment metadata mismatch");
        for (uint32_t i = 0; i < count; i++) {
          (void)name(l, &sub);
          o->data[i].alignment = number(l, &sub);
          if (o->data[i].alignment > 30)
            fail(l, "invalid segment alignment");
          if (number(l, &sub) & 2)
            fail(l, "TLS unsupported");
        }
      } else if (kind == 8) {
        o->ny = checked_count(l, &sub, sizeof(Symbol));
        o->symbols = alloc(l, (size_t)o->ny * sizeof(Symbol));
        for (uint32_t i = 0; i < o->ny; i++) {
          Symbol *y = &o->symbols[i];
          y->kind = get(l, &sub);
          y->flags = number(l, &sub);
          if ((y->flags & 3) == 3 || (y->flags & 0x100))
            fail(l, "common/TLS symbols unsupported");
          if (y->kind == 1) {
            y->name = name(l, &sub);
            if (!(y->flags & 16)) {
              y->index = number(l, &sub);
              y->offset = number(l, &sub);
              y->size = number(l, &sub);
              if (y->index >= o->nd || y->offset > o->data[y->index].n ||
                  y->size > o->data[y->index].n - y->offset)
                fail(l, "invalid data symbol");
            }
          } else if (y->kind == 3) {
            y->index = number(l, &sub);
          } else if (y->kind == 0 || y->kind == 2 || y->kind == 5) {
            y->index = number(l, &sub);
            if (!(y->flags & 16) || (y->flags & 64))
              y->name = name(l, &sub);
            else
              y->name = import_at(l, o,
                                  y->kind == 2   ? 3
                                  : y->kind == 5 ? 1
                                                 : 0,
                                  y->index)
                            ->name;
          } else
            fail(l, "unsupported symbol kind");
        }
      } else if (kind == 6 && number(l, &sub))
        fail(l, "object constructor lists unsupported; emit explicit "
                "dyn_initialize");
    }
  }
  if (o->nf && !o->bodies)
    fail(l, "missing code section");
  if (!linking)
    fail(l, "%s lacks linking-v2 metadata", path);
  for (uint32_t i = 0; i < o->ny; i++) {
    Symbol *y = &o->symbols[i];
    if (y->kind == 0 || y->kind == 2) {
      uint32_t imports = y->kind == 0 ? o->nfimp : o->ngimp;
      uint32_t total = imports + (y->kind == 0 ? o->nf : o->ng);
      if (y->index >= total || ((y->flags & 16) != 0) != (y->index < imports))
        fail(l, "invalid symbol index: %s", y->name);
      if (y->kind == 0) {
        uint32_t type = y->index < imports ? import_at(l, o, 0, y->index)->type
                                           : o->functions[y->index - imports];
        if (type >= o->nt)
          fail(l, "invalid function type");
        y->type = o->types[type];
      }
    }
  }
  o->fmap = alloc(l, (size_t)(o->nfimp + o->nf) * sizeof(uint32_t));
  o->gmap = alloc(l, (size_t)(o->ngimp + o->ng) * sizeof(uint32_t));
}
static Symbol *definition(Link *l, Symbol *s) {
  if (!s->name || (s->flags & 3) == 2)
    return s;
  Symbol *best = NULL;
  for (size_t k = 0; k < l->count; k++)
    for (uint32_t i = 0; i < l->objects[k].ny; i++) {
      Symbol *v = &l->objects[k].symbols[i];
      if ((v->flags & 16) || (v->flags & 3) == 2 || !v->name ||
          strcmp(s->name, v->name))
        continue;
      if (v->kind != s->kind)
        fail(l, "symbol kind mismatch: %s", s->name);
      if (best && !(best->flags & 1) && !(v->flags & 1) && best != v)
        fail(l, "duplicate symbol: %s", s->name);
      if (!best || !(v->flags & 1))
        best = v;
    }
  return best;
}
static uint32_t mapped_type(Link *l, Object *o, uint32_t i) {
  if (i >= o->nt)
    fail(l, "invalid type index");
  return o->types[i];
}
static uint32_t imported(Link *l, Object *o, Symbol *y) {
  Import *im = import_at(l, o, 0, y->index);
  bool allow = false;
  for (size_t k = 0; k < l->na; k++)
    if (!strcmp(l->allowed[k], y->name))
      allow = true;
  if (!allow)
    fail(l, "undefined symbol: %s", y->name);
  uint32_t type = mapped_type(l, o, im->type);
  for (uint32_t i = 0; i < l->ni; i++)
    if (!strcmp(im->module, l->imports[i].module) &&
        !strcmp(im->name, l->imports[i].name)) {
      if (type != l->imports[i].type)
        fail(l, "import type mismatch: %s", y->name);
      return i;
    }
  Import *a = alloc(l, (size_t)(l->ni + 1) * sizeof(Import));
  if (l->ni)
    memcpy(a, l->imports, l->ni * sizeof(Import));
  l->imports = a;
  a[l->ni] = *im;
  a[l->ni].type = type;
  return l->ni++;
}
static void patch(Link *l, Section *s, uint32_t off, unsigned kind,
                  uint32_t value) {
  bool raw = kind == 2 || kind == 5 || kind == 13 || kind == 26;
  size_t n = raw ? 4 : 5;
  if (off > s->n || n > s->n - off)
    fail(l, "relocation outside section");
  unsigned char *p = s->p + off;
  if (raw)
    for (unsigned i = 0; i < 4; i++)
      p[i] = (unsigned char)(value >> (8 * i));
  else {
    for (unsigned i = 0; i < 4; i++) {
      p[i] = (unsigned char)((value & 127) | 128);
      value >>= 7;
    }
    p[4] = (unsigned char)(value & 15);
    if ((kind == 1 || kind == 4) && (p[4] & 8))
      p[4] |= 0x70;
  }
}
static void relocate(Link *l, Object *o) {
  for (size_t si = 0; si < o->ns; si++) {
    Section *s = &o->sections[si];
    if (s->id)
      continue;
    Read r = reader(s);
    char *custom = name(l, &r);
    if (strncmp(custom, "reloc.", 6))
      continue;
    uint32_t target = number(l, &r), n = number(l, &r);
    if (target >= o->ns)
      fail(l, "invalid relocation section");
    Section *dst = &o->sections[target];
    if (dst->id == 0)
      continue; /* Debug information is omitted. */
    if (dst->id != 10 && dst->id != 11)
      fail(l, "unsupported relocation target");
    for (uint32_t i = 0; i < n; i++) {
      unsigned kind = get(l, &r);
      uint32_t off = number(l, &r), index = number(l, &r), value;
      int32_t add = 0;
      if (kind == 3 || kind == 4 || kind == 5 || kind == 8 || kind == 9)
        add = signed_number(l, &r);
      if (kind == 6)
        value = mapped_type(l, o, index);
      else {
        if (index >= o->ny)
          fail(l, "invalid relocation symbol");
        Symbol *y = &o->symbols[index];
        value = y->value;
        if ((kind == 0 || kind == 26) && y->kind != 0)
          fail(l, "invalid function relocation");
        if ((kind == 3 || kind == 4 || kind == 5) && y->kind != 1)
          fail(l, "invalid memory relocation");
        if ((kind == 7 || kind == 13) && y->kind != 2)
          fail(l, "invalid global relocation");
        if (kind == 20 && y->kind != 5)
          fail(l, "invalid table number relocation");
        if (kind == 1 || kind == 2) {
          if (y->kind != 0)
            fail(l, "invalid table relocation");
          value++;
        } else if (kind != 0 && kind != 3 && kind != 4 && kind != 5 &&
                   kind != 7 && kind != 13 && kind != 20 && kind != 26)
          fail(l, "unsupported relocation type %u", kind);
      }
      size_t width =
          (kind == 2 || kind == 5 || kind == 13 || kind == 26) ? 4 : 5;
      bool contained = false;
      for (uint32_t j = 0; j < (dst->id == 10 ? o->nf : o->nd); j++) {
        unsigned char *start = dst->id == 10 ? o->bodies[j] : o->data[j].p;
        size_t size = dst->id == 10 ? o->sizes[j] : o->data[j].n;
        size_t begin = (size_t)(start - dst->p);
        if (off >= begin && off - begin <= size &&
            width <= size - (off - begin)) {
          contained = true;
          break;
        }
      }
      if (!contained)
        fail(l, "relocation outside function/data payload");
      patch(l, dst, off, kind, value + (uint32_t)add);
    }
  }
}
/* Archive members are extracted only when they satisfy an unresolved symbol.
   Symbol indexes and GNU/BSD long-name tables are metadata, never object
   inputs. */
typedef struct Candidate {
  Object object;
  bool selected;
  struct Candidate *next;
} Candidate;
static size_t decimal(Link *l, const unsigned char *p, size_t n) {
  size_t value = 0;
  bool seen = false;
  for (size_t i = 0; i < n; i++) {
    if (p[i] == ' ') {
      for (; i < n; i++)
        if (p[i] != ' ')
          fail(l, "invalid archive size");
      break;
    }
    if (p[i] < '0' || p[i] > '9' || value > (SIZE_MAX - (p[i] - '0')) / 10)
      fail(l, "invalid archive size");
    value = value * 10 + (p[i] - '0');
    seen = true;
  }
  if (!seen)
    fail(l, "invalid archive size");
  return value;
}
static void append_object(Link *l, Object *o) {
  if (l->count == SIZE_MAX / sizeof(Object))
    fail(l, "too many input objects");
  Object *objects = alloc(l, (l->count + 1) * sizeof(Object));
  if (l->count)
    memcpy(objects, l->objects, l->count * sizeof(Object));
  objects[l->count++] = *o;
  l->objects = objects;
}
static void inputs(Link *l, const char *const *paths, size_t count) {
  Candidate *first = NULL, **tail = &first;
  for (size_t k = 0; k < count; k++) {
    size_t length;
    unsigned char *data = read_file(l, paths[k], &length);
    if (memcmp(data, "!<arch>\n", 8)) {
      Object o = {0};
      parse(l, &o, data, length, paths[k]);
      append_object(l, &o);
      continue;
    }
    size_t offset = 8;
    while (offset < length) {
      if (length - offset < 60 || memcmp(data + offset + 58, "`\n", 2))
        fail(l, "invalid archive member in %s", paths[k]);
      unsigned char *header = data + offset;
      size_t bytes = decimal(l, header + 48, 10);
      offset += 60;
      if (bytes > length - offset)
        fail(l, "truncated archive %s", paths[k]);
      unsigned char *member = data + offset;
      size_t object_size = bytes;
      bool metadata =
          (header[0] == '/' && (header[1] == ' ' || header[1] == '/')) ||
          !memcmp(header, "__.SYMDEF", 9) || !memcmp(header, "/SYM64/", 7);
      if (!memcmp(header, "#1/", 3)) {
        size_t namesize = decimal(l, header + 3, 13);
        if (namesize > bytes)
          fail(l, "invalid BSD archive name");
        if (namesize >= 9 && !memcmp(member, "__.SYMDEF", 9))
          metadata = true;
        member += namesize;
        object_size -= namesize;
      }
      if (!metadata) {
        Candidate *candidate = alloc(l, sizeof(*candidate));
        parse(l, &candidate->object, member, object_size, paths[k]);
        *tail = candidate;
        tail = &candidate->next;
      }
      offset += bytes;
      if (offset & 1) {
        if (offset >= length)
          fail(l, "missing archive padding");
        offset++;
      }
    }
  }
  bool changed;
  do {
    changed = false;
    for (Candidate *c = first; c; c = c->next) {
      if (c->selected)
        continue;
      bool needed = false;
      for (size_t k = 0; k < l->count && !needed; k++)
        for (uint32_t i = 0; i < l->objects[k].ny && !needed; i++) {
          Symbol *y = &l->objects[k].symbols[i];
          if (!(y->flags & 16) || !y->name || definition(l, y))
            continue;
          for (uint32_t j = 0; j < c->object.ny; j++) {
            Symbol *d = &c->object.symbols[j];
            if (!(d->flags & 16) && (d->flags & 3) != 2 && d->name &&
                !strcmp(y->name, d->name)) {
              needed = true;
              break;
            }
          }
        }
      if (needed) {
        append_object(l, &c->object);
        c->selected = true;
        changed = true;
      }
    }
  } while (changed);
}
static bool export_one(Link *l, Buf *b, const char *name_, unsigned kind,
                       uint32_t index) {
  for (uint32_t i = 0; i < l->ne; i++)
    if (!strcmp(l->exports[i].name, name_)) {
      if (l->exports[i].kind != kind || l->exports[i].index != index)
        fail(l, "duplicate export: %s", name_);
      return false;
    }
  Export *entries = alloc(l, (size_t)(l->ne + 1) * sizeof(Export));
  if (l->ne)
    memcpy(entries, l->exports, l->ne * sizeof(Export));
  l->exports = entries;
  entries[l->ne++] = (Export){(char *)name_, kind, index};
  string(l, b, name_);
  byte(l, b, kind);
  uleb(l, b, index);
  return true;
}
int dyn_link_wasm_objects(const char *const *paths, size_t count,
                          const char *output,
                          const char *const *allowed_imports,
                          size_t import_count, bool wasi, uint32_t max_memory,
                          bool verbose) {
  Link *l = calloc(1, sizeof(Link));
  if (!l)
    return 2;
  int status = 2;
  if (setjmp(l->failed))
    goto cleanup;
  l->allowed = allowed_imports;
  l->na = import_count;
  l->wasi = wasi;
  inputs(l, paths, count);
  uint32_t address = 1024, nf = 0, ng = 1, nd = 0;
  for (size_t k = 0; k < l->count; k++) {
    Object *o = &l->objects[k];
    nf += o->nf;
    ng += o->ng;
    nd += o->nd;
    for (uint32_t i = 0; i < o->nd; i++) {
      Segment *d = &o->data[i];
      uint32_t align = 1u << d->alignment;
      uint64_t a = ((uint64_t)address + align - 1) & ~((uint64_t)align - 1);
      if (a + d->n > UINT32_MAX - 1048592u)
        fail(l, "linear memory overflow");
      d->address = (uint32_t)a;
      address = (uint32_t)a + d->n;
    }
    for (uint32_t i = 0; i < o->ny; i++) {
      Symbol *y = &o->symbols[i];
      if (!(y->flags & 16)) {
        (void)definition(l, y);
        if (y->kind == 1)
          y->value = o->data[y->index].address + y->offset;
      } else if (!definition(l, y) && y->kind == 0)
        y->value = imported(l, o, y);
    }
  }
  uint32_t stack_low = (address + 15u) & ~15u;
  uint32_t heap = stack_low + 1048576u;
  uint32_t fn = l->ni, gn = 1;
  for (size_t k = 0; k < l->count; k++) {
    Object *o = &l->objects[k];
    for (uint32_t i = 0; i < o->nf; i++)
      o->fmap[o->nfimp + i] = fn++;
    for (uint32_t i = 0; i < o->ng; i++)
      o->gmap[o->ngimp + i] = gn++;
    for (uint32_t i = 0; i < o->ny; i++) {
      Symbol *y = &o->symbols[i];
      if (y->flags & 16)
        continue;
      if (y->kind == 0) {
        if (y->index >= o->nfimp + o->nf)
          fail(l, "invalid function symbol");
        y->value = o->fmap[y->index];
      } else if (y->kind == 2) {
        if (y->index >= o->ngimp + o->ng)
          fail(l, "invalid global symbol");
        y->value = o->gmap[y->index];
      }
    }
  }
  for (size_t k = 0; k < l->count; k++) {
    Object *o = &l->objects[k];
    for (uint32_t i = 0; i < o->ny; i++) {
      Symbol *y = &o->symbols[i];
      if (!y->name)
        continue;
      Symbol *def = definition(l, y);
      if (def) {
        if (y->kind == 0 && y->type != def->type)
          fail(l, "function type mismatch: %s", y->name);
        y->value = def->value;
      } else if (y->kind == 2 && !strcmp(y->name, "__stack_pointer"))
        y->value = 0;
      else if (y->kind == 1 && !strcmp(y->name, "__stack_low"))
        y->value = stack_low;
      else if (y->kind == 1 && !strcmp(y->name, "__heap_base"))
        y->value = heap;
      else if (y->kind == 5 && !strcmp(y->name, "__indirect_function_table"))
        y->value = 0;
      else if (y->kind != 0)
        fail(l, "undefined symbol: %s", y->name);
      if (y->kind == 0)
        o->fmap[y->index] = y->value;
      else if (y->kind == 2)
        o->gmap[y->index] = y->value;
    }
    relocate(l, o);
  }
  Buf out = {0}, b = {0};
  put(l, &out, "\0asm\1\0\0\0", 8);
  uleb(l, &b, l->nt);
  for (uint32_t i = 0; i < l->nt; i++)
    put(l, &b, l->types[i].p, l->types[i].n);
  section(l, &out, 1, &b);
  b = (Buf){0};
  if (l->ni) {
    uleb(l, &b, l->ni);
    for (uint32_t i = 0; i < l->ni; i++) {
      string(l, &b, l->imports[i].module);
      string(l, &b, l->imports[i].name);
      byte(l, &b, 0);
      uleb(l, &b, l->imports[i].type);
    }
    section(l, &out, 2, &b);
    b = (Buf){0};
  }
  uleb(l, &b, nf);
  for (size_t k = 0; k < l->count; k++) {
    Object *o = &l->objects[k];
    for (uint32_t i = 0; i < o->nf; i++)
      uleb(l, &b, mapped_type(l, o, o->functions[i]));
  }
  section(l, &out, 3, &b);
  b = (Buf){0};
  uleb(l, &b, 1);
  byte(l, &b, 0x70);
  byte(l, &b, 0);
  uleb(l, &b, fn + 1);
  section(l, &out, 4, &b);
  b = (Buf){0};
  uint32_t pages = (uint32_t)(((uint64_t)heap + 65535u) / 65536u);
  if (max_memory &&
      ((uint64_t)pages * 65536 > max_memory || max_memory % 65536))
    fail(l,
         "maximum memory smaller than static data/stack or not page aligned");
  uleb(l, &b, 1);
  byte(l, &b, max_memory ? 1 : 0);
  uleb(l, &b, pages);
  if (max_memory)
    uleb(l, &b, max_memory / 65536);
  section(l, &out, 5, &b);
  b = (Buf){0};
  uleb(l, &b, ng);
  byte(l, &b, 0x7f);
  byte(l, &b, 1);
  byte(l, &b, 0x41);
  sleb(l, &b, (int32_t)heap);
  byte(l, &b, 0xb);
  for (size_t k = 0; k < l->count; k++)
    for (uint32_t i = 0; i < l->objects[k].ng; i++)
      put(l, &b, l->objects[k].globals[i].p, l->objects[k].globals[i].n);
  section(l, &out, 6, &b);
  b = (Buf){0};
  Buf ex = {0};
  uint32_t ne = 1;
  export_one(l, &ex, "memory", 2, 0);
  for (size_t k = 0; k < l->count; k++) {
    Object *o = &l->objects[k];
    for (uint32_t i = 0; i < o->ne; i++) {
      Export *e = &o->exports[i];
      if (e->kind == 2 && !strcmp(e->name, "memory"))
        continue;
      if (e->kind != 0 && e->kind != 3)
        fail(l, "unsupported object export");
      uint32_t limit = e->kind == 0 ? o->nfimp + o->nf : o->ngimp + o->ng;
      if (e->index >= limit)
        fail(l, "invalid export");
      ne += export_one(l, &ex, e->name, e->kind,
                       e->kind == 0 ? o->fmap[e->index] : o->gmap[e->index]);
    }
    for (uint32_t i = 0; i < o->ny; i++) {
      Symbol *y = &o->symbols[i];
      if (!(y->flags & 32) || y->kind != 0)
        continue;
      bool exists = false;
      for (uint32_t j = 0; j < o->ne; j++)
        if (!strcmp(o->exports[j].name, y->name))
          exists = true;
      if (!exists) {
        ne += export_one(l, &ex, y->name, 0, y->value);
      }
    }
  }
  uleb(l, &b, ne);
  put(l, &b, ex.p, ex.n);
  section(l, &out, 7, &b);
  b = (Buf){0};
  if (fn) {
    uleb(l, &b, 1);
    byte(l, &b, 0);
    byte(l, &b, 0x41);
    byte(l, &b, 1);
    byte(l, &b, 0xb);
    uleb(l, &b, fn);
    for (uint32_t i = 0; i < fn; i++)
      uleb(l, &b, i);
    section(l, &out, 9, &b);
    b = (Buf){0};
  }
  uleb(l, &b, nf);
  for (size_t k = 0; k < l->count; k++) {
    Object *o = &l->objects[k];
    for (uint32_t i = 0; i < o->nf; i++) {
      uleb(l, &b, o->sizes[i]);
      put(l, &b, o->bodies[i], o->sizes[i]);
    }
  }
  section(l, &out, 10, &b);
  b = (Buf){0};
  if (nd) {
    uleb(l, &b, nd);
    for (size_t k = 0; k < l->count; k++) {
      Object *o = &l->objects[k];
      for (uint32_t i = 0; i < o->nd; i++) {
        Segment *d = &o->data[i];
        byte(l, &b, 0);
        byte(l, &b, 0x41);
        sleb(l, &b, (int32_t)d->address);
        byte(l, &b, 0xb);
        uleb(l, &b, d->n);
        put(l, &b, d->p, d->n);
      }
    }
    section(l, &out, 11, &b);
  }
  if (!backend_write_object(output, out.p, out.n))
    fail(l, "cannot publish %s", output);
  if (verbose)
    fprintf(stderr,
            "+ built-in Wasm linker: %zu objects, %u functions, %u memory "
            "pages -> %s\n",
            l->count, nf, pages, output);
  status = 0;
cleanup:
  while (l->allocations) {
    Allocation *a = l->allocations;
    l->allocations = a->next;
    free(a->p);
    free(a);
  }
  free(l);
  return status;
}
