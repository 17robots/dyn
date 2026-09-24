#include "dyn.h"
#include "frontend.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void query_string(const char *s, size_t n) {
  putchar('"');
  for (size_t i = 0; i < n; ++i) {
    unsigned char c = (unsigned char)s[i];
    if (c == '"' || c == '\\') { putchar('\\'); putchar(c); }
    else if (c < 32) printf("\\u%04x", c);
    else putchar(c);
  }
  putchar('"');
}
static void query_text(const char *s) { query_string(s ? s : "", s ? strlen(s) : 0); }
static void query_location(const DynSource *s, DynSpan span) {
  const char *path; unsigned line, column;
  dyn_source_location(s, span.start_byte, &path, &line, &column);
  printf("\"path\":"); query_text(path);
  printf(",\"line\":%u,\"column\":%u", line, column);
}
static void query_name(const DynSource *s, DynSpan span) {
  const char *path, *text; size_t length, offset;
  dyn_source_position(s, span.start_byte, &path, &text, &length, &offset);
  size_t end = offset;
  while (end < length && ((text[end] >= 'a' && text[end] <= 'z') ||
        (text[end] >= 'A' && text[end] <= 'Z') || (text[end] >= '0' && text[end] <= '9') || text[end] == '_')) ++end;
  query_string(text + offset, end - offset);
}
static void query_comments(const DynSource *s, DynSpan span) {
  const char *path, *text; size_t length, offset;
  dyn_source_position(s, span.start_byte, &path, &text, &length, &offset);
  (void)path;
  if (offset > length) offset = length;
  while (offset && text[offset - 1] != '\n') --offset;
  size_t end = offset, start = offset;
  while (start) {
    size_t previous = start - 1;
    while (previous && text[previous - 1] != '\n') --previous;
    size_t first = previous;
    while (first < start && (text[first] == ' ' || text[first] == '\t')) ++first;
    if (first + 2 > start || text[first] != '/' || text[first + 1] != '/') break;
    start = previous;
  }
  query_string(text + start, end - start);
}
static void query_symbol(const DynSource *s, DynAstProgram *a, const char *kind,
                         size_t id, DynSpan name, DynSpan span, DynType type, bool public) {
  char formatted[1024]; dyn_type_format(a, type, s, formatted, sizeof(formatted));
  printf("{\"id\":\"%s:%zu\",\"kind\":", kind, id); query_text(kind);
  printf(",\"name\":"); query_name(s, name);
  printf(",\"resolved_name\":"); query_string(s->text + name.start_byte, name.end_byte - name.start_byte);
  printf(",\"type_id\":%u,\"type\":", type); query_text(formatted);
  printf(",\"public\":%s,", public ? "true" : "false"); query_location(s, name);
  printf(",\"source_comments\":"); query_comments(s, span); putchar('}');
}
static int query_owner(DynAstProgram *a, DynSpan span) {
  size_t lo = 0, hi = a->function_count;
  while (lo < hi) { size_t mid = lo + (hi - lo) / 2;
    if (a->functions[mid].span.start_byte <= span.start_byte) lo = mid + 1; else hi = mid;
  }
  if (lo && span.end_byte <= a->functions[lo - 1].span.end_byte) return (int)(lo - 1);
  return -1;
}
int dyn_query_sources(const DynSources *sources, const char *main_path) {
  DynSource merged = {0}; DynAstProgram a = {0};
  if (dyn_sources_merge(sources, main_path, &merged)) return 2;
  DynAnalysisResult analyzed = dyn_analyze(&merged, &a, (DynAnalysisOptions){.main_path = main_path});
  if (analyzed.errors) { dyn_ast_program_free(&a); dyn_source_free(&merged); return 1; }
  printf("{\"schema_version\":1,\"analysis\":\"semantic\",\"frontend\":\"" DYN_FRONTEND_STAMP "\",\"target\":");
  query_text(dyn_context_target(&merged.context)->name);
  printf(",\"source_fingerprint\":\"%016llx\",\"limitations\":["
    "\"expression references only; type syntax references are not indexed\","
    "\"indirect calls and foreign effects remain unknown\","
    "\"source comments are documented contracts, not proofs\","
    "\"symbol and type IDs belong to this snapshot\"],\"sources\":[",
    (unsigned long long)dyn_interface_source_hash(sources));
  for (size_t i = 0; i < sources->count; ++i) { if (i) putchar(','); query_text(sources->items[i].path); }
  printf("],\"dependencies\":["); bool comma = false;
  for (size_t i = 0; i < sources->count; ++i)
    for (size_t j = 0; j < sources->items[i].dependency_count; ++j) {
      size_t target = sources->items[i].dependency_sources[j];
      if (target >= sources->count) continue;
      if (comma) { putchar(','); } comma = true;
      printf("{\"source\":"); query_text(sources->items[i].path);
      printf(",\"dependency\":"); query_text(sources->items[target].path); putchar('}');
    }
  printf("],\"symbols\":["); comma = false;
#define QUERY_SYMBOL(...) do { if (comma) { putchar(','); } comma = true; query_symbol(&merged, &a, __VA_ARGS__); } while (0)
  for (size_t i = 0; i < a.function_count; ++i) QUERY_SYMBOL("function",i,a.functions[i].name,a.functions[i].span,a.functions[i].return_type,a.functions[i].is_public);
  for (size_t i = 0; i < a.global_count; ++i) QUERY_SYMBOL("global",i,a.globals[i].name,a.globals[i].name,a.globals[i].type,a.globals[i].is_public);
  for (size_t i = 0; i < a.local_count; ++i) QUERY_SYMBOL("local",i,a.locals[i].name,a.locals[i].name,a.locals[i].type,false);
  for (size_t i = 0; i < a.struct_count; ++i) QUERY_SYMBOL("struct",i,a.structs[i].name,a.structs[i].span,DYN_TYPE_STRUCT_BASE+(DynType)i,a.structs[i].is_public);
  for (size_t i = 0; i < a.enum_count; ++i) QUERY_SYMBOL("enum",i,a.enums[i].name,a.enums[i].span,DYN_TYPE_ENUM_BASE+(DynType)i,a.enums[i].is_public);
  for (size_t i = 0; i < a.alias_count; ++i) QUERY_SYMBOL("alias",i,a.aliases[i].name,a.aliases[i].name,a.aliases[i].target,a.aliases[i].is_public);
#undef QUERY_SYMBOL
  printf("],\"parameters\":["); comma = false;
  for (size_t i = 0; i < a.function_count; ++i)
    for (uint32_t j = 0; j < a.functions[i].param_count; ++j) {
      DynAstParam *p = &a.params[a.functions[i].param_start+j];
      if (comma) { putchar(','); } comma = true;
      printf("{\"function_id\":\"function:%zu\",\"position\":%u,\"type_id\":%u,\"name\":",i,j,p->type);
      query_name(&merged,p->name); putchar('}');
    }
  printf("],\"fields\":["); comma = false;
  for (size_t i = 0; i < a.struct_count; ++i)
    for (uint32_t j = 0; j < a.structs[i].field_count; ++j) {
      DynAstField *f = &a.fields[a.structs[i].field_start+j];
      if (comma) { putchar(','); } comma = true;
      printf("{\"owner_type\":%zu,\"position\":%u,\"type_id\":%u,\"name\":",DYN_TYPE_STRUCT_BASE+i,j,f->type);
      query_name(&merged,f->name); putchar('}');
    }
  printf("],\"references\":["); comma = false;
  for (size_t i = 0; i < a.expression_count; ++i) {
    DynAstExpr *e = &a.expressions[i]; const char *kind = NULL;
    if (e->kind == DYN_EXPR_NAME && e->integer < a.local_count) kind = "local";
    else if (e->kind == DYN_EXPR_GLOBAL) kind = "global";
    else if (e->kind == DYN_EXPR_FUNCTION || e->kind == DYN_EXPR_CALL) kind = "function";
    if (!kind || e->type == DYN_TYPE_INFER || e->type == DYN_TYPE_ERROR) continue;
    if (comma) { putchar(','); } comma = true;
    printf("{\"symbol_id\":\"%s:%llu\",\"type_id\":%u,",kind,(unsigned long long)e->integer,e->type);
    query_location(&merged,e->span); putchar('}');
  }
  printf("],\"calls\":["); comma = false;
  for (size_t i = 0; i < a.expression_count; ++i) {
    DynAstExpr *e = &a.expressions[i];
    if (e->kind != DYN_EXPR_CALL && e->kind != DYN_EXPR_INDIRECT_CALL && e->kind != DYN_EXPR_SYSCALL) continue;
    if (comma) { putchar(','); } comma = true;
    int owner = query_owner(&a,e->span);
    printf("{\"caller_id\":"); if (owner < 0) printf("null"); else printf("\"function:%d\"",owner);
    printf(",\"callee_id\":");
    if (e->kind == DYN_EXPR_CALL) printf("\"function:%llu\"",(unsigned long long)e->integer); else printf("null");
    printf(",\"kind\":\"%s\",\"effects\":\"%s\",",
      e->kind == DYN_EXPR_CALL ? "direct" : e->kind == DYN_EXPR_SYSCALL ? "syscall" : "indirect",
      e->kind == DYN_EXPR_CALL && !a.functions[e->integer].foreign ? "inspect-callee" : "unknown");
    query_location(&merged,e->span); putchar('}');
  }
  printf("],\"types\":["); comma = false;
  const size_t counts[] = {DYN_TYPE_ANY+1,a.struct_count,a.enum_count,a.pointer_count,a.array_count,a.slice_count,a.fn_type_count,a.alias_count};
  const DynType bases[] = {0,DYN_TYPE_STRUCT_BASE,DYN_TYPE_ENUM_BASE,DYN_TYPE_POINTER_BASE,DYN_TYPE_ARRAY_BASE,DYN_TYPE_SLICE_BASE,DYN_TYPE_FN_BASE,DYN_TYPE_DISTINCT_BASE};
  for (size_t group = 0; group < 8; ++group) for (size_t i = 0; i < counts[group]; ++i) {
    if (group == 7 && !a.aliases[i].distinct) continue;
    DynType type = bases[group]+(DynType)i; char name[1024];
    dyn_type_format(&a,type,&merged,name,sizeof(name));
    if (comma) { putchar(','); } comma = true;
    printf("{\"id\":%u,\"name\":",type); query_text(name); putchar('}');
  }
  puts("]}");
  dyn_ast_program_free(&a); dyn_source_free(&merged);
  return fflush(stdout) || ferror(stdout) ? 2 : 0;
}
