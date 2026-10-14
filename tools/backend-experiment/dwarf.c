#include "dwarf.h"
#include <elf.h>
#include <stdlib.h>
#include <string.h>

#define DWARF_LIMIT (1024u * 1024u * 1024u)
#define RECORD_LIMIT (1u << 26)
#define FILE_LIMIT (1u << 20)
#define FUNCTION_LIMIT (1u << 20)
#define TYPE_LIMIT (1u << 20)

typedef struct {
  size_t pc;
  unsigned file, line, column;
  bool prologue_end;
} Row;
typedef struct {
  size_t begin, end, first_row, last_row, first_epilogue, last_epilogue,
      first_variable, last_variable;
  char *name;
  unsigned file, line, column;
} Function;
enum { TYPE_BASE, TYPE_POINTER, TYPE_STRUCT, TYPE_ARRAY, TYPE_ENUM, TYPE_UNION };
typedef struct {
  unsigned kind, encoding, target;
  char *name;
  uint64_t size, count;
  size_t first, members;
} Type;
/* Struct members carry offsets; enumerators carry values. */
typedef struct { char *name; unsigned type; uint64_t value; } Member;
typedef struct { char *name; unsigned type; int64_t offset; bool parameter; size_t begin, end; } Variable;
struct BackendDwarf {
  Function *functions;
  size_t function_count, function_capacity;
  Row *rows;
  size_t row_count, row_capacity;
  size_t *epilogues;
  size_t epilogue_count, epilogue_capacity;
  char **files;
  size_t file_count, file_capacity, string_bytes;
  Type *types;
  size_t type_count, type_capacity;
  Member *members;
  size_t member_count, member_capacity;
  Variable *variables;
  size_t variable_count, variable_capacity;
  const char *last_path; /* callers pass stable location-index paths */
  unsigned last_file;
  bool active, failed, a64;
};
static bool grow(void **data, size_t *capacity, size_t count, size_t size, size_t limit) {
  if (count > limit || size > SIZE_MAX / count) return false;
  if (count <= *capacity) return true;
  size_t n = *capacity ? *capacity * 2 : 16;
  if (n < count) n = count;
  if (n > limit) n = limit;
  void *p = realloc(*data, n * size);
  if (!p) return false;
  *data = p; *capacity = n; return true;
}
static char *copy_string(BackendDwarf *d, const char *s) {
  size_t n = strlen(s) + 1;
  if (n > DWARF_LIMIT - d->string_bytes) return NULL;
  char *p = malloc(n);
  if (p) { memcpy(p, s, n); d->string_bytes += n; }
  return p;
}
static unsigned file_index(BackendDwarf *d, const char *path) {
  if (path == d->last_path) return d->last_file;
  for (size_t i = d->file_count; i-- > 0;)
    if (!strcmp(d->files[i], path)) {
      d->last_path = path; d->last_file = (unsigned)i + 1;
      return d->last_file;
    }
  if (!grow((void **)&d->files, &d->file_capacity, d->file_count + 1,
            sizeof(*d->files), FILE_LIMIT)) return 0;
  char *p = copy_string(d, path);
  if (!p) return 0;
  d->files[d->file_count++] = p;
  d->last_path = path; d->last_file = (unsigned)d->file_count;
  return d->last_file;
}
BackendDwarf *backend_dwarf_create(void) { return calloc(1, sizeof(BackendDwarf)); }
BackendDwarf *backend_dwarf_create_a64(void) {
  BackendDwarf *d = calloc(1, sizeof(BackendDwarf));
  if (d) d->a64 = true;
  return d;
}
void backend_dwarf_free(BackendDwarf *d) {
  if (!d) return;
  for (size_t i = 0; i < d->function_count; ++i) free(d->functions[i].name);
  for (size_t i = 0; i < d->file_count; ++i) free(d->files[i]);
  for (size_t i = 0; i < d->type_count; ++i) free(d->types[i].name);
  for (size_t i = 0; i < d->member_count; ++i) free(d->members[i].name);
  for (size_t i = 0; i < d->variable_count; ++i) free(d->variables[i].name);
  free(d->functions); free(d->files); free(d->rows); free(d->epilogues);
  free(d->types); free(d->members); free(d->variables); free(d);
}
bool backend_dwarf_begin(BackendDwarf *d, size_t pc, const char *name,
                         const char *path, unsigned line, unsigned column) {
  if (!d || d->failed) return false;
  if (d->active || pc > UINT32_MAX || !name || !path || !line ||
      (d->function_count && pc < d->functions[d->function_count - 1].end) ||
      !grow((void **)&d->functions, &d->function_capacity, d->function_count + 1,
            sizeof(*d->functions), FUNCTION_LIMIT)) return !(d->failed = true);
  unsigned file = file_index(d, path);
  char *copy = file ? copy_string(d, name) : NULL;
  if (!copy) return !(d->failed = true);
  d->functions[d->function_count++] = (Function){.begin=pc, .first_row=d->row_count,
    .first_epilogue=d->epilogue_count, .first_variable=d->variable_count,
    .name=copy, .file=file, .line=line, .column=column};
  d->active = true;
  return backend_dwarf_line(d, pc, path, line, column, false);
}
bool backend_dwarf_line(BackendDwarf *d, size_t pc, const char *path,
                        unsigned line, unsigned column, bool prologue_end) {
  if (!d || d->failed) return false;
  if (!d->active || pc > UINT32_MAX || !path || !line ||
      (d->row_count && pc < d->rows[d->row_count - 1].pc) ||
      !grow((void **)&d->rows, &d->row_capacity, d->row_count + 1,
            sizeof(*d->rows), RECORD_LIMIT)) return !(d->failed = true);
  unsigned file = file_index(d, path);
  if (!file) return !(d->failed = true);
  d->rows[d->row_count++] = (Row){pc, file, line, column, prologue_end}; return true;
}
bool backend_dwarf_epilogue(BackendDwarf *d, size_t pc) {
  if (!d || d->failed) return false;
  if (!d->active || pc > UINT32_MAX - 2 || pc < d->functions[d->function_count - 1].begin + 4 ||
      (d->epilogue_count && pc < d->epilogues[d->epilogue_count - 1] + 2) ||
      !grow((void **)&d->epilogues, &d->epilogue_capacity, d->epilogue_count + 1,
            sizeof(*d->epilogues), RECORD_LIMIT)) return !(d->failed = true);
  d->epilogues[d->epilogue_count++] = pc; return true;
}
bool backend_dwarf_end(BackendDwarf *d, size_t end) {
  if (!d || d->failed) return false;
  if (!d->active) return !(d->failed = true);
  Function *f = &d->functions[d->function_count - 1];
  if (end > UINT32_MAX || end < f->begin + 4 || d->rows[d->row_count - 1].pc >= end ||
      (d->epilogue_count > f->first_epilogue && d->epilogues[d->epilogue_count - 1] + 2 > end))
    return !(d->failed = true);
  f->end = end; f->last_row = d->row_count; f->last_epilogue = d->epilogue_count;
  f->last_variable = d->variable_count;
  d->active = false; return true;
}
static unsigned add_type(BackendDwarf *d, Type type, const char *name, unsigned members) {
  if (!d || d->failed) return 0;
  if (!grow((void **)&d->types, &d->type_capacity, d->type_count + 1,
            sizeof(*d->types), TYPE_LIMIT) ||
      !grow((void **)&d->members, &d->member_capacity, d->member_count + members,
            sizeof(*d->members), RECORD_LIMIT)) { d->failed = true; return 0; }
  if (name && !(type.name = copy_string(d, name))) { d->failed = true; return 0; }
  type.first = d->member_count; type.members = members;
  memset(d->members + d->member_count, 0, members * sizeof(*d->members));
  d->member_count += members;
  d->types[d->type_count++] = type;
  return (unsigned)d->type_count;
}
unsigned backend_dwarf_base_type(BackendDwarf *d, const char *name,
                                 unsigned encoding, unsigned size) {
  return add_type(d, (Type){.kind=TYPE_BASE, .encoding=encoding, .size=size}, name, 0);
}
unsigned backend_dwarf_pointer_type(BackendDwarf *d, unsigned target) {
  return add_type(d, (Type){.kind=TYPE_POINTER, .target=target, .size=8}, NULL, 0);
}
unsigned backend_dwarf_struct_type(BackendDwarf *d, const char *name,
                                   uint64_t size, unsigned members) {
  return add_type(d, (Type){.kind=TYPE_STRUCT, .size=size}, name, members);
}
unsigned backend_dwarf_union_type(BackendDwarf *d, const char *name,
                                  uint64_t size, unsigned members) {
  return add_type(d, (Type){.kind=TYPE_UNION, .size=size}, name, members);
}
unsigned backend_dwarf_array_type(BackendDwarf *d, unsigned element, uint64_t count) {
  if (!element) return 0;
  return add_type(d, (Type){.kind=TYPE_ARRAY, .target=element, .count=count}, NULL, 0);
}
unsigned backend_dwarf_enum_type(BackendDwarf *d, const char *name, unsigned base,
                                 uint64_t size, unsigned enumerators) {
  if (!base) return 0;
  return add_type(d, (Type){.kind=TYPE_ENUM, .target=base, .size=size}, name, enumerators);
}
static bool set_member(BackendDwarf *d, unsigned type, unsigned index,
                       const char *name, unsigned member_type, uint64_t value) {
  if (!d || d->failed || !type || type > d->type_count) return false;
  Type *owner = &d->types[type - 1];
  if (index >= owner->members || !name) return false;
  Member *m = &d->members[owner->first + index];
  if (m->name) return false;
  if (!(m->name = copy_string(d, name))) return !(d->failed = true);
  m->type = member_type; m->value = value;
  return true;
}
bool backend_dwarf_member(BackendDwarf *d, unsigned type, unsigned index,
                          const char *name, unsigned member_type, uint64_t offset) {
  return member_type && set_member(d, type, index, name, member_type, offset);
}
bool backend_dwarf_enumerator(BackendDwarf *d, unsigned type, unsigned index,
                              const char *name, int64_t value) {
  return set_member(d, type, index, name, 0, (uint64_t)value);
}
bool backend_dwarf_variable(BackendDwarf *d, const char *name, unsigned type,
                            int64_t offset, bool parameter, size_t begin, size_t end) {
  if (!d || d->failed) return false;
  if (!d->active || !type || type > d->type_count || !name || !*name) return true;
  if (!grow((void **)&d->variables, &d->variable_capacity, d->variable_count + 1,
            sizeof(*d->variables), RECORD_LIMIT)) return !(d->failed = true);
  char *copy = copy_string(d, name);
  if (!copy) return !(d->failed = true);
  Function *f = &d->functions[d->function_count - 1];
  if (end <= begin || begin < f->begin) begin = end = 0;
  d->variables[d->variable_count++] = (Variable){copy, type, offset, parameter, begin, end};
  return true;
}
static bool bytes(BackendDwarfBytes *b, const void *data, size_t n) {
  if (n > DWARF_LIMIT - b->size) return false;
  if (!n) return true;
  if (!grow((void **)&b->data, &b->capacity, b->size+n, 1, DWARF_LIMIT)) return false;
  memcpy(b->data+b->size, data, n); b->size += n; return true;
}
static bool number(BackendDwarfBytes *b, uint64_t v, unsigned n) {
  unsigned char p[8];
  for (unsigned i=0; i<n; ++i) p[i]=(unsigned char)(v>>(i*8));
  return bytes(b,p,n);
}
static bool uleb(BackendDwarfBytes *b, uint64_t v) {
  do { unsigned char x=v&127; v>>=7; if (v) x|=128; if (!bytes(b,&x,1)) return false; } while(v);
  return true;
}
static bool sleb(BackendDwarfBytes *b, int64_t v) {
  for (;;) {
    unsigned char x=v&127; v>>=7;
    bool last=(v==0 && !(x&64)) || (v==-1 && (x&64));
    if (!last) x|=128;
    if (!bytes(b,&x,1)) return false;
    if (last) return true;
  }
}
static bool string(BackendDwarfBytes *b,const char *s) { return bytes(b,s,strlen(s)+1); }
static void patch32(BackendDwarfBytes *b,size_t at,size_t n) {
  for (unsigned i=0;i<4;++i) b->data[at+i]=(unsigned char)(n>>(8*i));
}
static bool relocation(BackendDwarfOutput *out,unsigned section,unsigned target,
                       unsigned type,int64_t addend) {
  if (!grow((void **)&out->relocations,&out->relocation_capacity,out->relocation_count+1,
            sizeof(*out->relocations),RECORD_LIMIT)) return false;
  BackendDwarfBytes *b=&out->sections[section];
  out->relocations[out->relocation_count++]=(BackendDwarfRelocation){section,target,type,b->size,addend};
  return number(b,0,type==R_X86_64_64?8:4);
}
#define PUT(x) do { if (!(x)) return false; } while(0)
static bool abbreviations(BackendDwarfBytes *b) {
  /* abbrev, tag, children; attribute/form pairs; terminator */
  const unsigned char data[]={
    1,0x11,1, 0x03,0x08, 0x25,0x08, 0x13,0x05, 0x10,0x17,
    0x11,0x01, 0x12,0x07, 0,0,
    2,0x2e,1, 0x03,0x08, 0x6e,0x08, 0x3a,0x0f, 0x3b,0x0f,
    0x39,0x0f, 0x11,0x01, 0x12,0x07, 0x40,0x18, 0,0,
    3,0x34,0, 0x03,0x08, 0x49,0x13, 0x02,0x18, 0,0,
    4,0x05,0, 0x03,0x08, 0x49,0x13, 0x02,0x18, 0,0,
    5,0x24,0, 0x03,0x08, 0x3e,0x0b, 0x0b,0x0f, 0,0,
    6,0x0f,0, 0x0b,0x0f, 0x49,0x13, 0,0,
    7,0x0f,0, 0x0b,0x0f, 0,0,
    8,0x13,1, 0x03,0x08, 0x0b,0x0f, 0,0,
    9,0x0d,0, 0x03,0x08, 0x49,0x13, 0x38,0x0f, 0,0,
    10,0x01,1, 0x49,0x13, 0,0,
    11,0x21,0, 0x37,0x0f, 0,0,
    12,0x04,1, 0x03,0x08, 0x0b,0x0f, 0x49,0x13, 0,0,
    13,0x28,0, 0x03,0x08, 0x1c,0x0d, 0,0,
    14,0x0b,1, 0x11,0x01, 0x12,0x07, 0,0,
    15,0x17,1, 0x03,0x08, 0x0b,0x0f, 0,0,
    0};
  return bytes(b,data,sizeof(data));
}
typedef struct { size_t at; unsigned type; } TypeRef;
static bool scope_before(const Variable *a, const Variable *b) {
  return a->begin < b->begin || (a->begin == b->begin && a->end > b->end);
}
static bool emit_variable(BackendDwarfOutput *out, BackendDwarfBytes *b, const Variable *variable,
                          TypeRef **refs, size_t *count, size_t *capacity) {
  (void)out;
  if (!uleb(b,variable->parameter?4:3) || !string(b,variable->name)) return false;
  if (!grow((void **)refs,capacity,*count+1,sizeof(**refs),SIZE_MAX/sizeof(**refs)) || !number(b,0,4)) return false;
  (*refs)[*count].at=b->size-4; (*refs)[(*count)++].type=variable->type;
  BackendDwarfBytes location={0};
  bool ok=number(&location,0x91,1) && sleb(&location,variable->offset) && /* DW_OP_fbreg */
          uleb(b,location.size) && bytes(b,location.data,location.size);
  free(location.data);
  return ok;
}
static bool information(BackendDwarf *d,BackendDwarfOutput *out) {
  BackendDwarfBytes *b=&out->sections[BACKEND_DWARF_INFO];
  PUT(number(b,0,4)); PUT(number(b,4,2));
  PUT(relocation(out,BACKEND_DWARF_INFO,BACKEND_DWARF_ABBREV,R_X86_64_32,0)); PUT(number(b,8,1));
  PUT(uleb(b,1)); PUT(string(b,d->files[0])); PUT(string(b,"dyn native experimental"));
  PUT(number(b,0x15b9,2)); /* LLVM's existing Dyn language code. */
  PUT(relocation(out,BACKEND_DWARF_INFO,BACKEND_DWARF_LINE,R_X86_64_32,0));
  PUT(relocation(out,BACKEND_DWARF_INFO,BACKEND_DWARF_TEXT,R_X86_64_64,d->functions[0].begin));
  PUT(number(b,d->functions[d->function_count-1].end-d->functions[0].begin,8));
  /* Type DIEs precede functions; ref4 forms are patched once offsets exist. */
  size_t *offsets=calloc(d->type_count?d->type_count:1,sizeof(*offsets));
  size_t ref_count=0,ref_capacity=0; TypeRef *refs=NULL;
  bool ok=offsets!=NULL;
#define REF(id) do { if (!grow((void **)&refs,&ref_capacity,ref_count+1,sizeof(*refs),SIZE_MAX/sizeof(*refs)) || !number(b,0,4)) { ok=false; break; } \
    refs[ref_count].at=b->size-4; refs[ref_count++].type=(id); } while(0)
  for (size_t i=0;ok && i<d->type_count;++i) {
    Type *type=&d->types[i]; offsets[i]=b->size;
    switch (type->kind) {
    case TYPE_BASE:
      ok=uleb(b,5) && string(b,type->name) && number(b,type->encoding,1) && uleb(b,type->size); break;
    case TYPE_POINTER:
      if (type->target) { ok=uleb(b,6) && uleb(b,8); if (ok) REF(type->target); }
      else ok=uleb(b,7) && uleb(b,8);
      break;
    case TYPE_ARRAY:
      ok=uleb(b,10); if (ok) REF(type->target);
      ok=ok && uleb(b,11) && uleb(b,type->count) && uleb(b,0); break;
    case TYPE_STRUCT: case TYPE_ENUM: case TYPE_UNION:
      if (type->kind!=TYPE_ENUM) ok=uleb(b,type->kind==TYPE_UNION?15:8) && string(b,type->name) && uleb(b,type->size);
      else { ok=uleb(b,12) && string(b,type->name) && uleb(b,type->size); if (ok) REF(type->target); }
      for (size_t m=0;ok && m<type->members;++m) {
        Member *member=&d->members[type->first+m];
        if (!member->name) continue;
        if (type->kind!=TYPE_ENUM) {
          ok=uleb(b,9) && string(b,member->name); if (ok) REF(member->type);
          ok=ok && uleb(b,member->value);
        } else ok=uleb(b,13) && string(b,member->name) && sleb(b,(int64_t)member->value);
      }
      ok=ok && uleb(b,0); break;
    }
  }
  for (size_t i=0;ok && i<d->function_count;++i) {
    Function *f=&d->functions[i];
    const unsigned char frame_base[]={1,d->a64?0x6d:0x56}; /* DW_OP_reg29 (x29) / reg6 (rbp) */
    ok=uleb(b,2) && string(b,f->name) && string(b,f->name) && uleb(b,f->file) &&
       uleb(b,f->line) && uleb(b,f->column) &&
       relocation(out,BACKEND_DWARF_INFO,BACKEND_DWARF_TEXT,R_X86_64_64,f->begin) &&
       number(b,f->end-f->begin,8) && bytes(b,frame_base,sizeof(frame_base));
    /* Function-wide variables first; scoped ones nest as lexical blocks ordered
       by start, outer ranges before the ranges they contain. */
    size_t first=f->first_variable,count=f->last_variable-first,scoped=0;
    size_t *order=count?malloc(count*sizeof(*order)):NULL;
    size_t stack_begin[64],stack_end[64]; unsigned open=0;
    if (count && !order) ok=false;
    for (size_t v=0;ok && v<count;++v) {
      Variable *variable=&d->variables[first+v];
      if (variable->end>variable->begin) { order[scoped++]=first+v; continue; }
      ok=emit_variable(out,b,variable,&refs,&ref_count,&ref_capacity);
    }
    for (size_t x=1;ok && x<scoped;++x) {
      size_t value=order[x],y=x;
      for (;y && scope_before(&d->variables[value],&d->variables[order[y-1]]);--y) order[y]=order[y-1];
      order[y]=value;
    }
    for (size_t x=0;ok && x<scoped;++x) {
      Variable *variable=&d->variables[order[x]];
      while (ok && open && !(stack_begin[open-1]<=variable->begin && variable->end<=stack_end[open-1])) { ok=uleb(b,0); --open; }
      if (ok && !(open && stack_begin[open-1]==variable->begin && stack_end[open-1]==variable->end)) {
        if (open==64) { ok=uleb(b,0); --open; }
        ok=ok && uleb(b,14) &&
           relocation(out,BACKEND_DWARF_INFO,BACKEND_DWARF_TEXT,R_X86_64_64,(int64_t)variable->begin) &&
           number(b,variable->end-variable->begin,8);
        stack_begin[open]=variable->begin; stack_end[open++]=variable->end;
      }
      ok=ok && emit_variable(out,b,variable,&refs,&ref_count,&ref_capacity);
    }
    while (ok && open) { ok=uleb(b,0); --open; }
    free(order);
    ok=ok && uleb(b,0);
  }
#undef REF
  for (size_t i=0;ok && i<ref_count;++i) {
    if (!refs[i].type || refs[i].type>d->type_count) { ok=false; break; }
    patch32(b,refs[i].at,offsets[refs[i].type-1]);
  }
  free(refs); free(offsets);
  PUT(ok);
  PUT(uleb(b,0)); patch32(b,0,b->size-4); return true;
}
static bool lines(BackendDwarf *d,BackendDwarfOutput *out) {
  BackendDwarfBytes *b=&out->sections[BACKEND_DWARF_LINE];
  PUT(number(b,0,4)); PUT(number(b,4,2)); PUT(number(b,0,4));
  const unsigned char header[]={1,1,1,251,14,13,0,1,1,1,1,0,0,0,1,0,0,1,0};
  PUT(bytes(b,header,sizeof(header)));
  for (size_t i=0;i<d->file_count;++i) { PUT(string(b,d->files[i])); PUT(uleb(b,0)); PUT(uleb(b,0)); PUT(uleb(b,0)); }
  PUT(number(b,0,1)); patch32(b,6,b->size-10);
  for (size_t i=0;i<d->function_count;++i) {
    Function *f=&d->functions[i]; size_t pc=f->begin; unsigned file=1,line=1,column=0;
    PUT(number(b,0,1)); PUT(uleb(b,9)); PUT(number(b,2,1));
    PUT(relocation(out,BACKEND_DWARF_LINE,BACKEND_DWARF_TEXT,R_X86_64_64,pc));
    for (size_t j=f->first_row;j<f->last_row;++j) {
      Row *r=&d->rows[j];
      if (r->pc!=pc) { PUT(number(b,2,1)); PUT(uleb(b,r->pc-pc)); pc=r->pc; }
      if (r->file!=file) { PUT(number(b,4,1)); PUT(uleb(b,r->file)); file=r->file; }
      if (r->line!=line) { PUT(number(b,3,1)); PUT(sleb(b,(int64_t)r->line-line)); line=r->line; }
      if (r->column!=column) { PUT(number(b,5,1)); PUT(uleb(b,r->column)); column=r->column; }
      if (r->prologue_end) PUT(number(b,10,1));
      PUT(number(b,1,1));
    }
    PUT(number(b,2,1)); PUT(uleb(b,f->end-pc));
    PUT(number(b,0,1)); PUT(uleb(b,1)); PUT(number(b,1,1));
  }
  patch32(b,0,b->size-4); return true;
}
static bool advance(BackendDwarfBytes *b,size_t delta) {
  if (delta<64) return number(b,0x40|delta,1);
  return number(b,4,1) && number(b,delta,4);
}
static bool frames_a64(BackendDwarf *d,BackendDwarfOutput *out) {
  BackendDwarfBytes *b=&out->sections[BACKEND_DWARF_FRAME];
  /* CIE: code alignment 4, data alignment -8, return address x30, CFA = sp. */
  PUT(number(b,0,4)); PUT(number(b,UINT32_MAX,4)); PUT(number(b,1,1)); PUT(number(b,0,1));
  PUT(uleb(b,4)); PUT(sleb(b,-8)); PUT(number(b,30,1));
  const unsigned char initial[]={0x0c,31,0}; PUT(bytes(b,initial,sizeof(initial)));
  while (b->size%8) PUT(number(b,0,1));
  patch32(b,0,b->size-4);
  for (size_t i=0;i<d->function_count;++i) {
    Function *f=&d->functions[i]; size_t start=b->size;
    PUT(number(b,0,4)); PUT(relocation(out,BACKEND_DWARF_FRAME,BACKEND_DWARF_FRAME,R_X86_64_32,0));
    PUT(relocation(out,BACKEND_DWARF_FRAME,BACKEND_DWARF_TEXT,R_X86_64_64,f->begin));
    PUT(number(b,f->end-f->begin,8));
    /* After stp: CFA = sp + 16, x29 at CFA-16, x30 at CFA-8; after mov: CFA = x29 + 16. */
    const unsigned char prologue[]={0x41,0x0e,16,0x80|29,2,0x80|30,1,0x41,0x0d,29};
    PUT(bytes(b,prologue,sizeof(prologue))); size_t pc=f->begin+8;
    for (size_t j=f->first_epilogue;j<f->last_epilogue;++j) {
      size_t after_ldp=d->epilogues[j]+8; /* mov sp, x29; ldp x29, x30, [sp], #16 */
      PUT(advance(b,(after_ldp-pc)/4));
      const unsigned char epilogue[]={0x0a,0x0c,31,0,0xc0|29,0xc0|30,0x41,0x0b};
      PUT(bytes(b,epilogue,sizeof(epilogue))); pc=after_ldp+4;
    }
    while (b->size%8) PUT(number(b,0,1));
    patch32(b,start,b->size-start-4);
  }
  return true;
}
static bool frames(BackendDwarf *d,BackendDwarfOutput *out) {
  if (d->a64) return frames_a64(d,out);
  BackendDwarfBytes *b=&out->sections[BACKEND_DWARF_FRAME];
  PUT(number(b,0,4)); PUT(number(b,UINT32_MAX,4)); PUT(number(b,1,1)); PUT(number(b,0,1));
  PUT(uleb(b,1)); PUT(sleb(b,-8)); PUT(number(b,16,1));
  const unsigned char initial[]={0x0c,7,8,0x90,1}; PUT(bytes(b,initial,sizeof(initial)));
  while (b->size%8) PUT(number(b,0,1));
  patch32(b,0,b->size-4);
  for (size_t i=0;i<d->function_count;++i) {
    Function *f=&d->functions[i]; size_t start=b->size;
    PUT(number(b,0,4)); PUT(relocation(out,BACKEND_DWARF_FRAME,BACKEND_DWARF_FRAME,R_X86_64_32,0));
    PUT(relocation(out,BACKEND_DWARF_FRAME,BACKEND_DWARF_TEXT,R_X86_64_64,f->begin));
    PUT(number(b,f->end-f->begin,8));
    const unsigned char prologue[]={0x41,0x0e,16,0x86,2,0x43,0x0d,6};
    PUT(bytes(b,prologue,sizeof(prologue))); size_t pc=f->begin+4;
    for (size_t j=f->first_epilogue;j<f->last_epilogue;++j) {
      size_t after_leave=d->epilogues[j]+1;
      PUT(advance(b,after_leave-pc));
      const unsigned char epilogue[]={0x0a,0x0c,7,8,0xc6,0x41,0x0b};
      PUT(bytes(b,epilogue,sizeof(epilogue))); pc=after_leave+1;
    }
    while (b->size%8) PUT(number(b,0,1));
    patch32(b,start,b->size-start-4);
  }
  return true;
}
#undef PUT
void backend_dwarf_output_free(BackendDwarfOutput *out) {
  for (unsigned i=0;i<BACKEND_DWARF_SECTION_COUNT;++i) free(out->sections[i].data);
  free(out->relocations); memset(out,0,sizeof(*out));
}
bool backend_dwarf_finish(BackendDwarf *d,BackendDwarfOutput *out) {
  if (!d || d->failed || d->active || !d->function_count) return false;
  bool ok=abbreviations(&out->sections[BACKEND_DWARF_ABBREV]) && information(d,out) && lines(d,out) && frames(d,out);
  if (!ok) backend_dwarf_output_free(out);
  return ok;
}
