#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include "dyn_ast.h"
#include "sema.h"
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>
#include <tree_sitter/api.h>

extern const TSLanguage *tree_sitter_dyn(void);

static bool canonicalize(const DynSource *s, char **result, size_t *length) {
  char *out = malloc(s->length + 2);
  if (!out) return false;
  size_t at = 0, line = 0;
  for (size_t i = 0; i < s->length; ++i) {
    unsigned char c = (unsigned char)s->text[i];
    if (c == '\r' && i + 1 < s->length && s->text[i + 1] == '\n') continue;
    if (c == '\n') {
      while (at > line && (out[at - 1] == ' ' || out[at - 1] == '\t')) --at;
      out[at++] = '\n'; line = at;
    } else out[at++] = (char)c;
  }
  while (at > line && (out[at - 1] == ' ' || out[at - 1] == '\t')) --at;
  if (at && out[at - 1] != '\n') out[at++] = '\n';
  out[at] = 0; *result = out; *length = at;
  return true;
}
static int replace_file(const DynSource *s, const char *text, size_t length) {
  struct stat st;
  if (stat(s->path, &st)) return 2;
  size_t n = strlen(s->path);
  char *temporary = malloc(n + 16);
  if (!temporary) return 2;
  snprintf(temporary, n + 16, "%s.tmp.XXXXXX", s->path);
  int fd = mkstemp(temporary);
  if (fd < 0) { free(temporary); return 2; }
  size_t done = 0;
  while (done < length) {
    ssize_t wrote = write(fd, text + done, length - done);
    if (wrote <= 0) { close(fd); unlink(temporary); free(temporary); return 2; }
    done += (size_t)wrote;
  }
  int failed = fchmod(fd, st.st_mode & 07777) || fsync(fd) || close(fd) ||
               rename(temporary, s->path);
  if (failed) unlink(temporary);
  free(temporary); return failed ? 2 : 0;
}
int dyn_format_directory(const char *directory, bool check) {
  DynSources sources = {0};
  if (dyn_sources_load(directory, &sources)) return 2;
  char *main_path = dyn_path_join(directory, "main.dyn");
  if (!main_path) { dyn_sources_free(&sources); return 2; }
  DynCheckResult parsed = dyn_check_sources(&sources, main_path, false);
  free(main_path);
  if (parsed.errors) { dyn_sources_free(&sources); return 1; }
  int result = 0;
  for (size_t i = 0; i < sources.count; ++i) {
    char *text = NULL; size_t length = 0;
    if (!canonicalize(&sources.items[i], &text, &length)) { result = 2; break; }
    if (length != sources.items[i].length ||
        memcmp(text, sources.items[i].text, length)) {
      if (check) { fprintf(stderr, "%s: needs formatting\n", sources.items[i].path); result = 1; }
      else if (replace_file(&sources.items[i], text, length)) result = 2;
    }
    free(text);
    if (result == 2) break;
  }
  dyn_sources_free(&sources); return result;
}

int dyn_docs_directory(const char *directory) {
  DynSources sources = {0};
  if (dyn_sources_load(directory, &sources)) return 2;
  char *name = dyn_path_basename(directory);
  printf("# %s\n\n", name ? name : "module");
  for (size_t si = 0; si < sources.count; ++si) {
    const char *p = sources.items[si].text, *end = p + sources.items[si].length;
    while (p < end) {
      const char *line_end = memchr(p, '\n', (size_t)(end - p));
      if (!line_end) line_end = end;
      const char *q = p; while (q < line_end && isspace((unsigned char)*q)) ++q;
      if ((size_t)(line_end - q) >= 4 && !memcmp(q, "pub ", 4))
        printf("```dyn\n%.*s\n```\n\n", (int)(line_end - q), q);
      p = line_end < end ? line_end + 1 : end;
    }
  }
  free(name); dyn_sources_free(&sources); return 0;
}

static void lsp_send(const char *body) {
  printf("Content-Length: %zu\r\n\r\n%s", strlen(body), body); fflush(stdout);
}
static long request_id(const char *body) {
  const char *p = strstr(body, "\"id\"");
  if (!p || !(p = strchr(p, ':'))) return -1;
  return strtol(p + 1, NULL, 10);
}

typedef struct { char *uri; char *text; TSParser *parser; TSTree *tree; size_t parsed_length; TSPoint parsed_end; } LspDocument;
typedef struct { DynSource source; DynAstFunction ast; bool ok; } LspSemantic;
enum { LSP_DOCUMENT_LIMIT = 32 };
typedef struct {
  char severity[8], path[256], message[256];
  unsigned line, column, end_line, end_column;
} LspDiagnostic;
typedef struct { LspDiagnostic items[64]; size_t count; } LspDiagnostics;
typedef struct { char path[512], alias[128]; TSNode node, alias_node; } LspImport;
static LspSemantic lsp_semantic_build(LspDocument *,size_t);
static void lsp_semantic_free(LspSemantic *);
static void lsp_completion_fields(LspDocument *,size_t,const char *,char *,size_t,size_t *,bool *);

static LspDocument *lsp_document(LspDocument *documents, size_t count, const char *uri) {
  for (size_t i = 0; i < count; ++i) if (documents[i].uri && !strcmp(documents[i].uri, uri)) return &documents[i];
  return NULL;
}
static const char *lsp_file_path(const char *uri) { return !strncmp(uri,"file://",7)?uri+7:uri; }
static char *lsp_directory(const char *path) { char *r=strdup(path);if(!r)return NULL;char *slash=strrchr(r,'/');if(slash)*slash=0;else strcpy(r,".");return r; }
static char *lsp_project_root(const char *uri) {
  char *at=lsp_directory(lsp_file_path(uri)),*candidate=NULL;if(!at)return NULL;
  for(;;){char *manifest=dyn_path_join(at,"dyn.project");bool found=manifest&&!access(manifest,F_OK);free(manifest);if(found){free(candidate);return at;}
    char *main_path=dyn_path_join(at,"main.dyn");bool has_main=main_path&&!access(main_path,F_OK);free(main_path);if(has_main&&!candidate)candidate=strdup(at);
    char *slash=strrchr(at,'/');if(!slash||slash==at)break;*slash=0;}
  free(at);return candidate?candidate:lsp_directory(lsp_file_path(uri));
}
static size_t lsp_imports(const LspDocument *document,LspImport *imports,size_t capacity) {
  if(!document->tree)return 0;
  TSNode root=ts_tree_root_node(document->tree);size_t count=0;
  for(uint32_t i=0;i<ts_node_named_child_count(root)&&count<capacity;++i){TSNode n=ts_node_named_child(root,i);if(!strcmp(ts_node_type(n),"declaration"))n=ts_node_named_child(n,ts_node_named_child_count(n)-1);if(strcmp(ts_node_type(n),"use"))continue;
    TSNode string=ts_node_named_child(n,0),alias=ts_node_child_by_field_name(n,"alias",5);uint32_t a=ts_node_start_byte(string)+1,b=ts_node_end_byte(string)-1;if(b<=a||b-a>=sizeof(imports[count].path))continue;
    memcpy(imports[count].path,document->text+a,b-a);imports[count].path[b-a]=0;imports[count].node=n;imports[count].alias_node=alias;
    if(!ts_node_is_null(alias)){a=ts_node_start_byte(alias);b=ts_node_end_byte(alias);}
    else {const char *base=strrchr(imports[count].path,'/');const char *name=base?base+1:imports[count].path;a=0;b=(uint32_t)strlen(name);memcpy(imports[count].alias,name,b);imports[count].alias[b]=0;++count;continue;}
    if(b-a<sizeof(imports[count].alias)){memcpy(imports[count].alias,document->text+a,b-a);imports[count].alias[b-a]=0;++count;}
  }return count;
}
static char *lsp_resolve_import(const LspDocument *document,const char *path) {
  char *root=lsp_project_root(document->uri),*current=lsp_directory(lsp_file_path(document->uri));
  char *result=root&&current?dyn_module_resolve_import(root,current,path):NULL;free(root);free(current);return result;
}
static char *lsp_first_dyn_file(const char *directory) {
  DIR *dir=opendir(directory);if(!dir)return NULL;struct dirent *entry;char *best=NULL;
  while((entry=readdir(dir))){size_t n=strlen(entry->d_name);if(n<4||strcmp(entry->d_name+n-4,".dyn"))continue;if(!best||!strcmp(entry->d_name,"main.dyn")||strcmp(entry->d_name,best)<0){free(best);best=strdup(entry->d_name);if(best&&!strcmp(best,"main.dyn"))break;}}
  closedir(dir);if(!best)return NULL;char *path=dyn_path_join(directory,best);free(best);return path;
}
static char *lsp_path_uri(const char *path){size_t n=strlen(path);char *uri=malloc(n+8);if(uri)snprintf(uri,n+8,"file://%s",path);return uri;}

static char *json_string_after(const char *body, const char *key, size_t maximum) {
  const char *p = strstr(body, key);
  if (!p || !(p = strchr(p + strlen(key), ':'))) return NULL;
  while (*++p && isspace((unsigned char)*p)) {}
  if (*p != '"') return NULL;
  ++p;
  char *out = malloc(maximum + 1);
  if (!out) return NULL;
  size_t at = 0;
  while (*p && *p != '"' && at < maximum) {
    if (*p == '\\') {
      ++p;
      if (!*p) break;
      if (*p == 'n') out[at++] = '\n';
      else if (*p == 'r') out[at++] = '\r';
      else if (*p == 't') out[at++] = '\t';
      else if (*p == '"' || *p == '\\' || *p == '/') out[at++] = *p;
      else { free(out); return NULL; }
      ++p;
    } else out[at++] = *p++;
  }
  if (*p != '"') { free(out); return NULL; }
  out[at] = 0;
  return out;
}

static bool json_position(const char *body, size_t *line, size_t *character) {
  const char *position = strstr(body, "\"position\"");
  const char *line_key = position ? strstr(position, "\"line\"") : NULL;
  const char *character_key = position ? strstr(position, "\"character\"") : NULL;
  if (!line_key || !(line_key = strchr(line_key, ':')) || !character_key ||
      !(character_key = strchr(character_key, ':'))) return false;
  *line = (size_t)strtoull(line_key + 1, NULL, 10);
  *character = (size_t)strtoull(character_key + 1, NULL, 10);
  return true;
}

static bool identifier_at(const char *text, size_t line, size_t character,
                          const char **start, size_t *length) {
  const char *p = text;
  for (size_t n = 0; n < line; ++n) {
    p = strchr(p, '\n');
    if (!p) return false;
    ++p;
  }
  const char *end = strchr(p, '\n');
  if (!end) end = p + strlen(p);
  if ((size_t)(end - p) <= character) return false;
  const char *at = p + character;
  if (!(isalnum((unsigned char)*at) || *at == '_')) return false;
  const char *a = at, *b = at + 1;
  while (a > p && (isalnum((unsigned char)a[-1]) || a[-1] == '_')) --a;
  while (b < end && (isalnum((unsigned char)*b) || *b == '_')) ++b;
  *start = a; *length = (size_t)(b - a); return true;
}
static const char *lsp_builtin_hover(const char *text,size_t line,size_t character) {
  const char *row=text;for(size_t i=0;i<line;++i){row=strchr(row,'\n');if(!row)return NULL;++row;}const char *end=strchr(row,'\n');if(!end)end=row+strlen(row);if(row==end)return NULL;const char *at=row+(character<(size_t)(end-row)?character:(size_t)(end-row)-1);if(!isalnum((unsigned char)*at)&&*at!='_'&&*at!='#'&&at>row)--at;const char *a=at,*b=at+1;while(a>row&&(isalnum((unsigned char)a[-1])||a[-1]=='_'||a[-1]=='#'))--a;while(b<end&&(isalnum((unsigned char)*b)||*b=='_'))++b;
  struct {const char *name,*hover;} builtins[]={
    {"#cast","#cast(type) value -> type\nExplicitly converts compatible numeric, integer, or pointer values."},
    {"#bitcast","#bitcast(type) value -> type\nReinterprets equal-sized compatible scalar bits without numeric conversion."},
    {"#len","#len(array_or_slice) -> usize\nReturns an array or slice element count."},
    {"#sizeof","#sizeof(type_or_value) -> usize\nReturns the compile-time size in bytes."},
    {"#alignof","#alignof(type_or_value) -> usize\nReturns the compile-time alignment in bytes."},
    {"#typeof","#typeof(type_or_value) -> TypeInfo\nReturns reflection metadata for a type or value."},
    {"#syscall","#syscall(number, arguments...) -> isize\nPerforms a target system call with at most six integer or pointer arguments."},
    {"#panic","#panic(message: []const u8) -> never\nRuns active defers, prints a stack trace, and terminates execution."},
    {"#target","#target(condition)\nIncludes a declaration only when its structured target condition matches."},
  };size_t n=(size_t)(b-a);for(size_t i=0;i<sizeof(builtins)/sizeof(builtins[0]);++i)if(strlen(builtins[i].name)==n&&!memcmp(a,builtins[i].name,n))return builtins[i].hover;return NULL;
}
static size_t lsp_active_parameter(const char *text,size_t line,size_t character) {
  const char *cursor=text;for(size_t i=0;i<line;++i){cursor=strchr(cursor,'\n');if(!cursor)return 0;++cursor;}cursor+=character;const char *open=NULL;int depth=0;
  for(const char *p=cursor;p>text;){--p;if(*p==')')++depth;else if(*p=='('){if(!depth){open=p;break;}--depth;}}
  if(!open)return 0;
  size_t active=0;depth=0;for(const char *p=open+1;p<cursor;++p){if(*p=='('||*p=='['||*p=='{')++depth;else if((*p==')'||*p==']'||*p=='}')&&depth)--depth;else if(*p==','&&!depth)++active;}return active;
}
static bool lsp_call_identifier(const char *text,size_t line,size_t character,const char **start,size_t *length) {
  const char *cursor=text;for(size_t i=0;i<line;++i){cursor=strchr(cursor,'\n');if(!cursor)return false;++cursor;}cursor+=character;const char *open=NULL;int depth=0;for(const char *p=cursor;p>text;){--p;if(*p==')')++depth;else if(*p=='('){if(!depth){open=p;break;}--depth;}}if(!open)return false;const char *end=open;while(end>text&&isspace((unsigned char)end[-1]))--end;const char *begin=end;while(begin>text&&(isalnum((unsigned char)begin[-1])||begin[-1]=='_'))--begin;if(begin==end)return false;*start=begin;*length=(size_t)(end-begin);return true;
}

static bool find_declaration(const char *text, const char *word, size_t word_length,
                             size_t *line, size_t *column, const char **display,
                             size_t *display_length) {
  const char *p = text; size_t row = 0;
  while (*p) {
    const char *end = strchr(p, '\n'); if (!end) end = p + strlen(p);
    const char *q = p; while (q < end && isspace((unsigned char)*q)) ++q;
    if ((size_t)(end - q) >= 4 && !memcmp(q, "pub ", 4)) q += 4;
    const char *kinds[] = {"fn ", "struct ", "enum ", "type ", "const ", "extern fn "};
    for (size_t i = 0; i < sizeof(kinds) / sizeof(kinds[0]); ++i) {
      size_t n = strlen(kinds[i]);
      if ((size_t)(end - q) >= n + word_length && !memcmp(q, kinds[i], n) &&
          !memcmp(q + n, word, word_length) &&
          (q + n + word_length == end || !(isalnum((unsigned char)q[n + word_length]) || q[n + word_length] == '_'))) {
        *line = row; *column = (size_t)(q + n - p); *display = q;
        *display_length = (size_t)(end - q); return true;
      }
    }
    p = *end ? end + 1 : end; ++row;
  }
  return false;
}

static char *json_escape(const char *text, size_t length) {
  char *out = malloc(length * 2 + 1); if (!out) return NULL;
  size_t at = 0;
  for (size_t i = 0; i < length; ++i) {
    if (text[i] == '"' || text[i] == '\\') { out[at++] = '\\'; out[at++] = text[i]; }
    else if (text[i] == '\n') { out[at++] = '\\'; out[at++] = 'n'; }
    else if (text[i] == '\r') { out[at++] = '\\'; out[at++] = 'r'; }
    else if (text[i] == '\t') { out[at++] = '\\'; out[at++] = 't'; }
    else out[at++] = text[i];
  }
  out[at] = 0; return out;
}

static TSNode first_syntax_error(TSNode node) {
  if(ts_node_is_error(node)||ts_node_is_missing(node))return node;
  uint32_t count = ts_node_child_count(node);
  for (uint32_t i = 0; i < count; ++i) {
    TSNode child = ts_node_child(node, i);
    if (ts_node_is_error(child) || ts_node_is_missing(child)) return child;
    if (ts_node_has_error(child)) {
      TSNode found = first_syntax_error(child);
      if (!ts_node_is_null(found)) return found;
    }
  }
  return (TSNode){0};
}

static TSPoint lsp_text_end(const char *text) {
  TSPoint point = {0};
  for (; *text; ++text) { if (*text == '\n') { ++point.row; point.column = 0; } else ++point.column; }
  return point;
}

static bool lsp_publish_syntax(LspDocument *document) {
  if (!document->uri || !document->text) return false;
  if (!document->parser) { document->parser = ts_parser_new(); if (document->parser) ts_parser_set_language(document->parser, tree_sitter_dyn()); }
  size_t length = strlen(document->text); TSPoint end = lsp_text_end(document->text);
  if (document->tree) {
    TSInputEdit edit = {0, (uint32_t)document->parsed_length, (uint32_t)length, {0,0}, document->parsed_end, end};
    ts_tree_edit(document->tree, &edit);
  }
  TSTree *tree = document->parser ? ts_parser_parse_string(document->parser, document->tree, document->text, (uint32_t)length) : NULL;
  if (tree) { if (document->tree) ts_tree_delete(document->tree); document->tree = tree; document->parsed_length = length; document->parsed_end = end; }
  TSNode error = document->tree ? first_syntax_error(ts_tree_root_node(document->tree)) : (TSNode){0};
  char *uri = json_escape(document->uri, strlen(document->uri));
  char *body = uri ? malloc(strlen(uri) + 512) : NULL;
  if (body) {
    if (ts_node_is_null(error))
      snprintf(body, strlen(uri) + 512, "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/publishDiagnostics\",\"params\":{\"uri\":\"%s\",\"diagnostics\":[]}}", uri);
    else {
      TSPoint a = ts_node_start_point(error), b = ts_node_end_point(error);const char *message="incomplete or invalid syntax";TSNode ancestor=error;for(unsigned i=0;i<6&&!ts_node_is_null(ancestor);++i){const char *kind=ts_node_type(ancestor);if(!strcmp(kind,"call")){message="incomplete function call; expected ')'";break;}if(!strcmp(kind,"fn")){message="incomplete function declaration; expected a function body";break;}if(!strcmp(kind,"block")){message="incomplete block; expected '}'";break;}ancestor=ts_node_parent(ancestor);}const char *callee=NULL;size_t callee_length=0;if(lsp_call_identifier(document->text,end.row,end.column,&callee,&callee_length))message="incomplete function call; expected ')'";else{const char *tail=document->text+length,*line_start=tail;while(tail>document->text&&isspace((unsigned char)tail[-1]))--tail;line_start=tail;while(line_start>document->text&&line_start[-1]!='\n')--line_start;while(line_start<tail&&isspace((unsigned char)*line_start))++line_start;if((size_t)(tail-line_start)>=3&&!memcmp(line_start,"fn ",3))message="incomplete function declaration; expected a function body";}if(a.row==b.row&&a.column==b.column)++b.column;
      snprintf(body, strlen(uri) + 512, "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/publishDiagnostics\",\"params\":{\"uri\":\"%s\",\"diagnostics\":[{\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{\"line\":%u,\"character\":%u}},\"severity\":1,\"source\":\"dyn\",\"code\":\"syntax\",\"message\":\"%s\"}]}}", uri, a.row, a.column, b.row, b.column,message);
    }
    lsp_send(body);
  }
  free(body); free(uri);return !ts_node_is_null(error);
}

static void lsp_collect_diagnostic(const char *severity, const char *path,
    unsigned line, unsigned column, unsigned end_line, unsigned end_column,
    const char *message, void *context) {
  LspDiagnostics *all = context; if (all->count >= 64) return;
  LspDiagnostic *item = &all->items[all->count++];
  snprintf(item->severity, sizeof(item->severity), "%s", severity ? severity : "error");
  snprintf(item->path, sizeof(item->path), "%s", path ? path : "");
  snprintf(item->message, sizeof(item->message), "%s", message ? message : "diagnostic");
  item->line = line; item->column = column; item->end_line = end_line; item->end_column = end_column;
}
static size_t lsp_identifier_count(TSNode node,const char *text,const char *name,bool inside_use) {
  inside_use=inside_use||!strcmp(ts_node_type(node),"use");size_t count=0;
  if(!inside_use&&!strcmp(ts_node_type(node),"identifier")){uint32_t a=ts_node_start_byte(node),b=ts_node_end_byte(node);if(strlen(name)==b-a&&!memcmp(text+a,name,b-a))++count;}
  for(uint32_t i=0;i<ts_node_named_child_count(node);++i)
    count+=lsp_identifier_count(ts_node_named_child(node,i),text,name,inside_use);
  return count;
}
static size_t lsp_workspace_identifier_count(LspDocument *documents,size_t count,const char *name){size_t found=0;for(size_t i=0;i<count;++i)if(documents[i].tree)found+=lsp_identifier_count(ts_tree_root_node(documents[i].tree),documents[i].text,name,false);return found;}
static void lsp_unused_nodes(TSNode node,LspDocument *document,LspDocument *documents,size_t document_count,char *body,size_t capacity,size_t *at,bool *comma) {
  const char *kind=ts_node_type(node);TSNode names[16];size_t name_count=0;const char *label=NULL;
  TSNode ancestor=node;bool exported=false,foreign=false;for(unsigned depth=0;depth<3&&!ts_node_is_null(ancestor);++depth){if(!strcmp(ts_node_type(ancestor),"extern_fn"))foreign=true;if(!strcmp(ts_node_type(ancestor),"declaration")){uint32_t start=ts_node_start_byte(ancestor);exported=start+4<=strlen(document->text)&&!memcmp(document->text+start,"pub ",4);}ancestor=ts_node_parent(ancestor);}
  if(!strcmp(kind,"variable")){if(ts_node_named_child_count(node))names[name_count++]=ts_node_named_child(node,0);label="variable";}
  else if(!strcmp(kind,"fn_param")&&!foreign){for(uint32_t i=0;i<ts_node_named_child_count(node)&&name_count<16;++i){TSNode child=ts_node_named_child(node,i);if(!strcmp(ts_node_type(child),"identifier"))names[name_count++]=child;}label="parameter";}
  else if(!strcmp(kind,"fn")&&!exported){TSNode name=ts_node_child_by_field_name(node,"name",4);if(!ts_node_is_null(name)){names[name_count++]=name;label="function";}}
  if(exported&&label&&!strcmp(label,"variable"))name_count=0;
  for(size_t i=0;i<name_count;++i){uint32_t a=ts_node_start_byte(names[i]),b=ts_node_end_byte(names[i]);size_t n=b-a;if(!n||n>=128||document->text[a]=='_')continue;char name[128];memcpy(name,document->text+a,n);name[n]=0;if(!strcmp(name,"main")||lsp_workspace_identifier_count(documents,document_count,name)>1)continue;TSPoint p=ts_node_start_point(names[i]),e=ts_node_end_point(names[i]);*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{\"line\":%u,\"character\":%u}},\"severity\":2,\"source\":\"dyn\",\"code\":\"unused-%s\",\"message\":\"unused %s '%s'\"}",*comma?",":"",p.row,p.column,e.row,e.column,label,label,name);*comma=true;}
  for(uint32_t i=0;i<ts_node_named_child_count(node);++i)lsp_unused_nodes(ts_node_named_child(node,i),document,documents,document_count,body,capacity,at,comma);
}
static bool lsp_import_related(const LspDocument *document,const LspDiagnostic *diagnostic) {
  if(strcmp(diagnostic->message,"unknown name")&&
     strcmp(diagnostic->message,"field access requires struct or struct pointer")&&
     strcmp(diagnostic->message,"call target must be function pointer"))return false;
  LspImport imports[32];size_t count=lsp_imports(document,imports,32);if(!count||!diagnostic->line)return false;
  const char *row=document->text;for(unsigned i=1;i<diagnostic->line&&row;++i){row=strchr(row,'\n');if(row)++row;}if(!row)return false;const char *end=strchr(row,'\n');if(!end)end=row+strlen(row);
  for(size_t i=0;i<count;++i){size_t n=strlen(imports[i].alias);for(const char *p=row;p+n<end;++p)if(!memcmp(p,imports[i].alias,n)&&(p==row||!(isalnum((unsigned char)p[-1])||p[-1]=='_'))&&p[n]=='.'){
      const char *member=p+n+1,*member_end=member;while(member_end<end&&(isalnum((unsigned char)*member_end)||*member_end=='_'))++member_end;size_t first=(size_t)(p-row),last=(size_t)(member_end-row);size_t column=diagnostic->column?diagnostic->column-1:0;if(column>=first&&column<=last)return true;}}
  return false;
}

static void lsp_overlay_sources(DynSources *sources,LspDocument *documents,size_t count){
  for(size_t i=0;i<sources->count;++i)for(size_t j=0;j<count;++j){
    const char *path=lsp_file_path(documents[j].uri);if(strcmp(sources->items[i].path,path))continue;
    size_t length=strlen(documents[j].text);char *text=malloc(length+1);if(!text)continue;
    memcpy(text,documents[j].text,length+1);free(sources->items[i].text);
    sources->items[i].text=text;sources->items[i].length=length;
  }
}
static void lsp_publish_semantic(LspDocument *documents, size_t count) {
  DynSource overrides_items[LSP_DOCUMENT_LIMIT];
  for(size_t i=0;i<count;++i)overrides_items[i]=(DynSource){.path=documents[i].uri,.text=documents[i].text,.length=strlen(documents[i].text)};
  DynSources overrides={overrides_items,count};
  for(size_t group=0;group<count;++group){char *root=lsp_project_root(documents[group].uri);if(!root)continue;bool seen=false;
    for(size_t before=0;before<group&&!seen;++before){char *other=lsp_project_root(documents[before].uri);seen=other&&!strcmp(root,other);free(other);}if(seen){free(root);continue;}
    DynSources roots={0},sources={0};DynSource flat[LSP_DOCUMENT_LIMIT];LspDiagnostics diagnostics={0};bool owned=false;
    char *main_path=dyn_path_join(root,"main.dyn"),*manifest=dyn_path_join(root,"dyn.project");bool disk_project=(main_path&&!access(main_path,F_OK))||(manifest&&!access(manifest,F_OK));free(manifest);
    int loaded=disk_project?dyn_sources_load(root,&roots):1;if(!loaded){lsp_overlay_sources(&roots,documents,count);loaded=dyn_module_load_project_overlay(root,&roots,&overrides,&sources);owned=!loaded;}dyn_sources_free(&roots);
    const char *check_main=main_path?main_path:"";
    if(loaded){size_t flat_count=0;for(size_t i=0;i<count;++i){char *r=lsp_project_root(documents[i].uri);bool same=r&&!strcmp(root,r);free(r);if(!same)continue;flat[flat_count++]=(DynSource){.path=documents[i].uri,.text=documents[i].text,.length=strlen(documents[i].text)};}sources=(DynSources){flat,flat_count};loaded=0;if(flat_count)check_main=flat[0].path;}
    if(!loaded){dyn_diagnostic_sink(lsp_collect_diagnostic,&diagnostics);(void)dyn_check_sources(&sources,check_main,false);dyn_diagnostic_sink(NULL,NULL);}free(main_path);
    for(size_t d=0;d<count;++d){char *document_root=lsp_project_root(documents[d].uri);bool same=document_root&&!strcmp(root,document_root);free(document_root);if(!same)continue;
    char *uri = json_escape(documents[d].uri, strlen(documents[d].uri));
    char *body = uri ? malloc(strlen(uri) + 64 * 512 + 192) : NULL; if (!body) { free(uri); continue; }
    size_t capacity = strlen(uri) + 64 * 512 + 192;
    size_t at = (size_t)snprintf(body, capacity, "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/publishDiagnostics\",\"params\":{\"uri\":\"%s\",\"diagnostics\":[", uri);
    bool comma = false;
    for (size_t i = 0; i < diagnostics.count; ++i) {
      LspDiagnostic *item = &diagnostics.items[i]; if ((strcmp(item->path, documents[d].uri)&&strcmp(item->path,lsp_file_path(documents[d].uri)))||lsp_import_related(&documents[d],item)) continue;
      char *message = json_escape(item->message, strlen(item->message)); if (!message) continue;
      unsigned line = item->line ? item->line - 1 : 0, column = item->column ? item->column - 1 : 0;
      unsigned end_line = item->end_line ? item->end_line - 1 : line, end_column = item->end_column ? item->end_column - 1 : column + 1;
      at += (size_t)snprintf(body + at, capacity - at, "%s{\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{\"line\":%u,\"character\":%u}},\"severity\":%u,\"source\":\"dyn\",\"message\":\"%s\"}", comma ? "," : "", line, column, end_line, end_column, !strcmp(item->severity, "error") ? 1u : 2u, message);
      comma = true; free(message);
    }
    LspImport imports[32];size_t import_count=lsp_imports(&documents[d],imports,32);
    TSNode root=documents[d].tree?ts_tree_root_node(documents[d].tree):(TSNode){0};
    for(size_t i=0;i<import_count;++i)if(!ts_node_is_null(root)&&!lsp_identifier_count(root,documents[d].text,imports[i].alias,false)){
      TSNode marked=ts_node_is_null(imports[i].alias_node)?imports[i].node:imports[i].alias_node;TSPoint a=ts_node_start_point(marked),b=ts_node_end_point(marked);
      at+=(size_t)snprintf(body+at,capacity-at,"%s{\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{\"line\":%u,\"character\":%u}},\"severity\":2,\"source\":\"dyn\",\"code\":\"unused-use\",\"message\":\"unused use '%s' (alias '%s')\"}",comma?",":"",a.row,a.column,b.row,b.column,imports[i].path,imports[i].alias);comma=true;}
    if(!ts_node_is_null(root))lsp_unused_nodes(root,&documents[d],documents,count,body,capacity,&at,&comma);
    snprintf(body + at, capacity - at, "]}}"); lsp_send(body); free(body); free(uri);
    }if(owned)dyn_sources_free(&sources);free(root);
  }
}

static void lsp_identifier_edits(TSNode node, const LspDocument *document,
    const char *word, size_t word_length, const char *uri, const char *replacement,
    char *body, size_t capacity, size_t *at, bool *comma) {
  if (!strcmp(ts_node_type(node), "identifier") &&
      ts_node_end_byte(node) - ts_node_start_byte(node) == word_length &&
      !memcmp(document->text + ts_node_start_byte(node), word, word_length)) {
    TSPoint a = ts_node_start_point(node), b = ts_node_end_point(node);
    *at += (size_t)snprintf(body + *at, capacity - *at,
      "%s{\"uri\":\"%s\",\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{\"line\":%u,\"character\":%u}}%s%s%s}",
      *comma ? "," : "", uri, a.row, a.column, b.row, b.column,
      replacement ? ",\"newText\":\"" : "", replacement ? replacement : "", replacement ? "\"" : "");
    *comma = true;
  }
  for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i)
    lsp_identifier_edits(ts_node_named_child(node, i), document, word, word_length,
                         uri, replacement, body, capacity, at, comma);
}

static void lsp_references(long id, LspDocument *documents, size_t count,
                           const char *word, size_t word_length, const char *replacement) {
  size_t capacity = 1024u * 1024u, at = 0; char *body = malloc(capacity); if (!body) return;
  at = (size_t)snprintf(body, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id);
  bool comma = false;
  for (size_t i = 0; i < count; ++i) if (documents[i].tree) {
    char *uri = json_escape(documents[i].uri, strlen(documents[i].uri));
    if (uri) lsp_identifier_edits(ts_tree_root_node(documents[i].tree), &documents[i], word, word_length, uri, replacement, body, capacity, &at, &comma);
    free(uri);
  }
  snprintf(body + at, capacity - at, "]}"); lsp_send(body); free(body);
}

static void lsp_rename_edits(TSNode node, const LspDocument *document,
    const char *word, size_t word_length, const char *replacement,
    char *body, size_t capacity, size_t *at, bool *comma) {
  if (!strcmp(ts_node_type(node), "identifier") && ts_node_end_byte(node) - ts_node_start_byte(node) == word_length &&
      !memcmp(document->text + ts_node_start_byte(node), word, word_length)) {
    TSPoint a = ts_node_start_point(node), b = ts_node_end_point(node);
    *at += (size_t)snprintf(body + *at, capacity - *at, "%s{\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{\"line\":%u,\"character\":%u}},\"newText\":\"%s\"}", *comma ? "," : "", a.row, a.column, b.row, b.column, replacement); *comma = true;
  }
  for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i)
    lsp_rename_edits(ts_node_named_child(node, i), document, word, word_length, replacement, body, capacity, at, comma);
}

static void lsp_rename(long id, LspDocument *documents, size_t count,
                       const char *word, size_t word_length, const char *replacement) {
  size_t capacity = 1024u * 1024u; char *body = malloc(capacity); if (!body) return;
  size_t at = (size_t)snprintf(body, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"changes\":{", id); bool document_comma = false;
  for (size_t i = 0; i < count; ++i) if (documents[i].tree) {
    char *uri = json_escape(documents[i].uri, strlen(documents[i].uri)); if (!uri) continue;
    at += (size_t)snprintf(body + at, capacity - at, "%s\"%s\":[", document_comma ? "," : "", uri); bool edit_comma = false;
    lsp_rename_edits(ts_tree_root_node(documents[i].tree), &documents[i], word, word_length, replacement, body, capacity, &at, &edit_comma);
    at += (size_t)snprintf(body + at, capacity - at, "]"); document_comma = true; free(uri);
  }
  snprintf(body + at, capacity - at, "}}}"); lsp_send(body); free(body);
}

static void lsp_completion_signature(const char *start,char *out,size_t capacity) {
  size_t at=0;bool space=false;for(const char *p=start;*p&&*p!='{';++p){if(isspace((unsigned char)*p)){space=at>0;continue;}if(space&&at+1<capacity)out[at++]=' ';space=false;if((*p=='"'||*p=='\\')&&at+1<capacity)out[at++]='\\';if(at+1<capacity)out[at++]=*p;}while(at&&out[at-1]==' ')--at;out[at]=0;
}
static void lsp_call_snippet(const char *name,size_t name_length,const char *declaration,char *out,size_t capacity) {
  size_t at=0;int n=snprintf(out,capacity,"%.*s(",(int)name_length,name);if(n<0)return;at=(size_t)n<capacity?(size_t)n:capacity-1;
  const char *p=strchr(declaration,'('),*end=p?strchr(p,')'):NULL;unsigned slot=1;if(p&&end)for(++p;p<end;){while(p<end&&isspace((unsigned char)*p))++p;if(p>=end)break;const char *item=p;int depth=0;while(p<end&&(depth||*p!=',')){if(*p=='['||*p=='(')++depth;else if((*p==']'||*p==')')&&depth)--depth;++p;}const char *colon=memchr(item,':',(size_t)(p-item)),*label=item;size_t length=colon?(size_t)(colon-item):(size_t)(p-item);while(length&&isspace((unsigned char)label[length-1]))--length;if(!length||(length>=3&&!memcmp(label,"...",3))){label="argument";length=8;}if(at<capacity){n=snprintf(out+at,capacity-at,"%s${%u:%.*s}",slot>1?", ":"",slot,(int)length,label);if(n>0)at+=(size_t)n<capacity-at?(size_t)n:capacity-at-1;}++slot;if(p<end)++p;}
  if(at+1<capacity){out[at++]=')';out[at]=0;}
}
static void lsp_completion_decls(const char *text,bool public_only,char *body,size_t capacity,size_t *at,bool *comma) {
  const char *kinds[]={"fn ","struct ","enum ","type ","const ","extern fn "};
  const unsigned item_kinds[]={3,22,13,25,21,3};const char *details[]={"function","struct","enum","type","constant","extern function"};const char *p=text;
  while(p&&*p){const char *end=strchr(p,'\n');if(!end)end=p+strlen(p);const char *q=p;while(q<end&&isspace((unsigned char)*q))++q;const char *declaration=q;bool pub=(size_t)(end-q)>=4&&!memcmp(q,"pub ",4);if(pub)q+=4;if(!public_only||pub)for(size_t k=0;k<sizeof(kinds)/sizeof(kinds[0]);++k){size_t n=strlen(kinds[k]);if((size_t)(end-q)<n||memcmp(q,kinds[k],n))continue;const char *name=q+n,*name_end=name;while(name_end<end&&(isalnum((unsigned char)*name_end)||*name_end=='_'))++name_end;if(name_end>name){int length=(int)(name_end-name);if(item_kinds[k]==3){char signature[512],snippet[512];lsp_completion_signature(declaration,signature,sizeof(signature));lsp_call_snippet(name,(size_t)length,declaration,snippet,sizeof(snippet));*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"label\":\"%.*s\",\"kind\":3,\"detail\":\"%s\",\"documentation\":{\"kind\":\"plaintext\",\"value\":\"%s\"},\"insertText\":\"%s\",\"insertTextFormat\":2}",*comma?",":"",length,name,signature,signature,snippet);}else *at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"label\":\"%.*s\",\"kind\":%u,\"detail\":\"%s\"}",*comma?",":"",length,name,item_kinds[k],details[k]);*comma=true;}break;}p=*end?end+1:end;}
}
static void lsp_completion(long id, LspDocument *documents, size_t count,
                           LspDocument *requested,size_t line,size_t character) {
  size_t capacity = 1024u * 1024u, at = 0; char *body = malloc(capacity); if (!body) return;
  at = (size_t)snprintf(body, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id); bool comma = false;
  char qualifier[128]={0};bool qualified=false;
  bool import_path=false;
  if(requested&&requested->text){const char *p=requested->text;for(size_t row=0;row<line&&p;++row){p=strchr(p,'\n');if(p)++p;}if(p){const char *end=strchr(p,'\n');if(!end)end=p+strlen(p);const char *cursor=p+((size_t)(end-p)<character?(size_t)(end-p):character),*dot=cursor;while(dot>p&&(isalnum((unsigned char)dot[-1])||dot[-1]=='_'))--dot;if(dot>p&&dot[-1]=='.'){const char *q=dot-1,*start=q;while(start>p&&(isalnum((unsigned char)start[-1])||start[-1]=='_'))--start;size_t n=(size_t)(q-start);if(n&&n<sizeof(qualifier)){memcpy(qualifier,start,n);qualifier[n]=0;qualified=true;}}}}
  if(requested&&requested->text){const char *p=requested->text;for(size_t row=0;row<line&&p;++row){p=strchr(p,'\n');if(p)++p;}if(p){const char *end=strchr(p,'\n');if(!end)end=p+strlen(p);const char *cursor=p+(character>(size_t)(end-p)?(size_t)(end-p):character);const char *q=p;while(q<cursor&&isspace((unsigned char)*q))++q;import_path=(size_t)(cursor-q)>=5&&!memcmp(q,"use \"",5);}}
  if(import_path){char *core=lsp_resolve_import(requested,"std/core"),*directory=core?lsp_directory(core):NULL;DIR *dir=directory?opendir(directory):NULL;struct dirent *entry;if(dir)while((entry=readdir(dir)))if(entry->d_name[0]!='.'){char *path=dyn_path_join(directory,entry->d_name);if(path&&dyn_path_is_directory(path))at+=(size_t)snprintf(body+at,capacity-at,"%s{\"label\":\"std/%s\",\"kind\":19}",comma?",":"",entry->d_name),comma=true;free(path);}if(dir)closedir(dir);free(directory);free(core);}
  else if(qualified){LspImport imports[32];size_t n=lsp_imports(requested,imports,32);bool imported=false;for(size_t i=0;i<n;++i)if(!strcmp(imports[i].alias,qualifier)){char *target=lsp_resolve_import(requested,imports[i].path);DynSources sources={0};if(target&&!dyn_sources_load(target,&sources))for(size_t s=0;s<sources.count;++s)lsp_completion_decls(sources.items[s].text,true,body,capacity,&at,&comma);dyn_sources_free(&sources);free(target);imported=true;break;}if(!imported)lsp_completion_fields(documents,count,qualifier,body,capacity,&at,&comma);}
  else {for(size_t d=0;d<count;++d)lsp_completion_decls(documents[d].text,false,body,capacity,&at,&comma);
    const char *words[]={"pub","type","const","else","return","true","false","nil"};for(size_t i=0;i<sizeof(words)/sizeof(words[0]);++i)at+=(size_t)snprintf(body+at,capacity-at,"%s{\"label\":\"%s\",\"kind\":14,\"detail\":\"keyword\"}",comma?",":"",words[i]),comma=true;
    struct {const char *label,*signature,*snippet;} builtins[]={
      {"#cast","#cast(type) value -> type","#cast(${1:type}) ${2:value}"},
      {"#bitcast","#bitcast(type) value -> type","#bitcast(${1:type}) ${2:value}"},
      {"#len","#len(array_or_slice) -> usize","#len(${1:array_or_slice})"},
      {"#sizeof","#sizeof(type_or_value) -> usize","#sizeof(${1:type_or_value})"},
      {"#alignof","#alignof(type_or_value) -> usize","#alignof(${1:type_or_value})"},
      {"#typeof","#typeof(type_or_value) -> TypeInfo","#typeof(${1:type_or_value})"},
      {"#syscall","#syscall(number, arguments...) -> isize","#syscall(${1:number}${2:, arguments})"},
      {"#panic","#panic(message: []const u8) -> never","#panic(${1:message})"},
      {"#target","#target(condition)","#target(${1:condition})"},
    };for(size_t i=0;i<sizeof(builtins)/sizeof(builtins[0]);++i)at+=(size_t)snprintf(body+at,capacity-at,"%s{\"label\":\"%s\",\"kind\":3,\"detail\":\"%s\",\"documentation\":{\"kind\":\"plaintext\",\"value\":\"%s\"},\"insertText\":\"%s\",\"insertTextFormat\":2}",comma?",":"",builtins[i].label,builtins[i].signature,builtins[i].signature,builtins[i].snippet),comma=true;
    const char *labels[]={"fn","main","if","for","case","struct","enum","use","defer"};
    const char *snippets[]={"fn ${1:name}(${2}) {\\n\\t$0\\n}","fn main() {\\n\\t$0\\n}","if ${1:condition} {\\n\\t$0\\n}","for ${1:item} in ${2:items} {\\n\\t$0\\n}","case ${1:value} {\\n\\t${2:_ => { $0 }}\\n}","struct ${1:Name} {\\n\\t${2:field}: ${3:type},\\n}","enum ${1:Name} {\\n\\t${2:Value},\\n}","use \\\"${1:std/package}\\\"$0","defer {\\n\\t$0\\n}"};
    for(size_t i=0;i<sizeof(labels)/sizeof(labels[0]);++i)at+=(size_t)snprintf(body+at,capacity-at,"%s{\"label\":\"%s\",\"kind\":15,\"detail\":\"Dyn snippet\",\"insertText\":\"%s\",\"insertTextFormat\":2,\"filterText\":\"%s\"}",comma?",":"",labels[i],snippets[i],labels[i]),comma=true;}
  snprintf(body+at,capacity-at,"]}"); lsp_send(body); free(body);
}
static void lsp_document_symbols(long id,const LspDocument *document) {
  size_t capacity=1024u*1024u,at=0;char *body=malloc(capacity);if(!body)return;at=(size_t)snprintf(body,capacity,"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[",id);bool comma=false;const char *p=document->text;size_t line=0;
  const char *kinds[]={"fn ","extern fn ","struct ","enum ","type ","const "};const unsigned symbol_kinds[]={12,12,23,10,5,14};
  while(p&&*p){const char *end=strchr(p,'\n');if(!end)end=p+strlen(p);const char *q=p;while(q<end&&isspace((unsigned char)*q))++q;if((size_t)(end-q)>=4&&!memcmp(q,"pub ",4))q+=4;for(size_t k=0;k<sizeof(kinds)/sizeof(kinds[0]);++k){size_t n=strlen(kinds[k]);if((size_t)(end-q)<n||memcmp(q,kinds[k],n))continue;const char *name=q+n,*name_end=name;while(name_end<end&&(isalnum((unsigned char)*name_end)||*name_end=='_'))++name_end;if(name_end>name)at+=(size_t)snprintf(body+at,capacity-at,"%s{\"name\":\"%.*s\",\"kind\":%u,\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}},\"selectionRange\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}}}",comma?",":"",(int)(name_end-name),name,symbol_kinds[k],line,(size_t)(q-p),line,(size_t)(end-p),line,(size_t)(name-p),line,(size_t)(name_end-p)),comma=true;break;}p=*end?end+1:end;++line;}snprintf(body+at,capacity-at,"]}");lsp_send(body);free(body);
}
static void lsp_semantic_token_node(TSNode node,unsigned *previous_line,unsigned *previous_column,
    bool *first,char *body,size_t capacity,size_t *at,bool *comma) {
  if(!strcmp(ts_node_type(node),"identifier")){TSNode parent=ts_node_parent(node);const char *kind=ts_node_type(parent);unsigned type=5;
    if(!strcmp(kind,"fn")||!strcmp(kind,"extern_fn")){TSNode name=ts_node_child_by_field_name(parent,"name",4);if(ts_node_start_byte(name)==ts_node_start_byte(node))type=8;}
    else if(!strcmp(kind,"fn_param")||!strcmp(kind,"variadic_param"))type=4;
    else if(!strcmp(kind,"struct"))type=2;else if(!strcmp(kind,"enum"))type=3;
    else if(!strcmp(kind,"struct_member")||!strcmp(kind,"field_access"))type=6;
    else if(!strcmp(kind,"enum_member"))type=7;else if(!strcmp(kind,"use"))type=0;
    else if(!strcmp(kind,"field_type")||!strcmp(kind,"type"))type=1;
    TSPoint p=ts_node_start_point(node);unsigned delta_line=*first?p.row:p.row-*previous_line;unsigned delta_column=(*first||delta_line)?p.column:p.column-*previous_column;*at+=(size_t)snprintf(body+*at,capacity-*at,"%s%u,%u,%u,%u,0",*comma?",":"",delta_line,delta_column,ts_node_end_point(node).column-p.column,type);*comma=true;*first=false;*previous_line=p.row;*previous_column=p.column;
  }
  for(uint32_t i=0;i<ts_node_named_child_count(node);++i)lsp_semantic_token_node(ts_node_named_child(node,i),previous_line,previous_column,first,body,capacity,at,comma);
}
static void lsp_semantic_tokens(long id,const LspDocument *document) {size_t capacity=1024u*1024u,at=0;char *body=malloc(capacity);if(!body)return;at=(size_t)snprintf(body,capacity,"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"data\":[",id);unsigned line=0,column=0;bool first=true,comma=false;if(document->tree)lsp_semantic_token_node(ts_tree_root_node(document->tree),&line,&column,&first,body,capacity,&at,&comma);snprintf(body+at,capacity-at,"]}}");lsp_send(body);free(body);}
static void lsp_workspace_symbols(long id,LspDocument *documents,size_t count) {
  size_t capacity=1024u*1024u,at=0;char *body=malloc(capacity);if(!body)return;at=(size_t)snprintf(body,capacity,"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[",id);bool comma=false;const char *kinds[]={"fn ","extern fn ","struct ","enum ","type ","const "};const unsigned symbol_kinds[]={12,12,23,10,5,14};
  for(size_t d=0;d<count;++d){const char *p=documents[d].text;size_t line=0;char *uri=json_escape(documents[d].uri,strlen(documents[d].uri));while(uri&&p&&*p){const char *end=strchr(p,'\n');if(!end)end=p+strlen(p);const char *q=p;while(q<end&&isspace((unsigned char)*q))++q;if((size_t)(end-q)>=4&&!memcmp(q,"pub ",4))q+=4;for(size_t k=0;k<sizeof(kinds)/sizeof(kinds[0]);++k){size_t n=strlen(kinds[k]);if((size_t)(end-q)<n||memcmp(q,kinds[k],n))continue;const char *name=q+n,*name_end=name;while(name_end<end&&(isalnum((unsigned char)*name_end)||*name_end=='_'))++name_end;if(name_end>name)at+=(size_t)snprintf(body+at,capacity-at,"%s{\"name\":\"%.*s\",\"kind\":%u,\"location\":{\"uri\":\"%s\",\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}}}}",comma?",":"",(int)(name_end-name),name,symbol_kinds[k],uri,line,(size_t)(name-p),line,(size_t)(name_end-p)),comma=true;break;}p=*end?end+1:end;++line;}free(uri);}snprintf(body+at,capacity-at,"]}");lsp_send(body);free(body);
}
static void lsp_code_actions(long id,const LspDocument *document,const char *body_text) {
  const char *range=strstr(body_text,"\"range\""),*start=range?strstr(range,"\"start\""):NULL,*line_key=start?strstr(start,"\"line\""):NULL;size_t line=line_key&&strchr(line_key,':')?(size_t)strtoull(strchr(line_key,':')+1,NULL,10):SIZE_MAX;const char *row=document->text;for(size_t i=0;i<line&&row;++i){row=strchr(row,'\n');if(row)++row;}const char *q=row;while(q&&isspace((unsigned char)*q)&&*q!='\n')++q;bool is_use=q&&!memcmp(q,"use ",4);char *uri=json_escape(document->uri,strlen(document->uri));char response[4096];if(is_use&&uri)snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[{\"title\":\"Remove unused use\",\"kind\":\"quickfix\",\"isPreferred\":true,\"edit\":{\"changes\":{\"%s\":[{\"range\":{\"start\":{\"line\":%zu,\"character\":0},\"end\":{\"line\":%zu,\"character\":0}},\"newText\":\"\"}]}}}]}",id,uri,line,line+1);else snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}",id);lsp_send(response);free(uri);
}
static void lsp_format(long id,const LspDocument *document) {
  DynSource source={.path=document->uri,.text=document->text,.length=strlen(document->text)};char *formatted=NULL;size_t length=0;if(!canonicalize(&source,&formatted,&length)){char response[96];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",id);lsp_send(response);return;}char *escaped=json_escape(formatted,length);size_t capacity=(escaped?strlen(escaped):0)+256;char *body=malloc(capacity);TSPoint end=lsp_text_end(document->text);if(body&&escaped){snprintf(body,capacity,"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[{\"range\":{\"start\":{\"line\":0,\"character\":0},\"end\":{\"line\":%u,\"character\":%u}},\"newText\":\"%s\"}]}",id,end.row,end.column,escaped);lsp_send(body);}free(body);free(escaped);free(formatted);
}

static void lsp_ignore_diagnostic(const char *a, const char *b, unsigned c,
    unsigned d, unsigned e, unsigned f, const char *g, void *h) {
  (void)a; (void)b; (void)c; (void)d; (void)e; (void)f; (void)g; (void)h;
}
static LspSemantic lsp_semantic_build(LspDocument *documents, size_t count) {
  LspSemantic semantic = {0}; DynSource items[LSP_DOCUMENT_LIMIT];
  for (size_t i=0;i<count;++i) items[i]=(DynSource){.path=documents[i].uri,.text=documents[i].text,.length=strlen(documents[i].text)};
  DynSources sources={items,count}; if (dyn_sources_merge(&sources,"<lsp>",&semantic.source)) return semantic;
  unsigned errors=0; dyn_diagnostic_sink(lsp_ignore_diagnostic,NULL);
  bool parsed=dyn_ast_parse_source_owner(&semantic.source,&semantic.ast,&errors,NULL,true);
  if (parsed) (void)dyn_sema_function(&semantic.ast,&semantic.source,&errors);
  dyn_diagnostic_sink(NULL,NULL); semantic.ok=parsed; return semantic;
}
static void lsp_semantic_free(LspSemantic *semantic) {
  dyn_ast_function_free(&semantic->ast); dyn_source_free(&semantic->source);
}
static void lsp_completion_fields(LspDocument *documents,size_t count,const char *name,char *body,size_t capacity,size_t *at,bool *comma) {
  LspSemantic semantic=lsp_semantic_build(documents,count);DynType type=DYN_TYPE_ERROR;for(size_t i=semantic.ast.local_count;i>0;--i){DynAstLocal *local=&semantic.ast.locals[i-1];size_t n=local->name.end_byte-local->name.start_byte;if(strlen(name)==n&&!memcmp(semantic.source.text+local->name.start_byte,name,n)){type=local->type;break;}}if(dyn_type_is_pointer(type)){uint32_t p=type-DYN_TYPE_POINTER_BASE;if(p<semantic.ast.pointer_count)type=semantic.ast.pointers[p].pointee;}if(dyn_type_is_struct(type)){DynAstStruct *s=&semantic.ast.structs[type-DYN_TYPE_STRUCT_BASE];for(uint32_t i=0;i<s->field_count;++i){DynAstField *field=&semantic.ast.fields[s->field_start+i];char field_type[128];dyn_type_format(&semantic.ast,field->type,&semantic.source,field_type,sizeof(field_type));*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"label\":\"%.*s\",\"kind\":5,\"detail\":\"%s\"}",*comma?",":"",(int)(field->name.end_byte-field->name.start_byte),semantic.source.text+field->name.start_byte,field_type);*comma=true;}}lsp_semantic_free(&semantic);
}
static bool lsp_document_offset(LspDocument *documents,size_t count,LspDocument *document,
    size_t line,size_t character,uint32_t *offset) {
  size_t base=0; for(size_t i=0;i<count;++i){
    if(&documents[i]==document){const char *p=document->text;for(size_t row=0;row<line;++row){p=strchr(p,'\n');if(!p)return false;++p;}
      const char *end=strchr(p,'\n');if(!end)end=p+strlen(p);if((size_t)(end-p)<character)return false;
      *offset=(uint32_t)(base+(size_t)(p-document->text)+character);return true;}
    base+=strlen(documents[i].text)+1;
  } return false;
}
static bool lsp_span_location(LspDocument *documents,size_t count,DynSpan span,
    LspDocument **document,size_t *line,size_t *column) {
  size_t base=0;for(size_t i=0;i<count;++i){size_t length=strlen(documents[i].text);
    if(span.start_byte>=base&&span.start_byte<base+length){size_t local=span.start_byte-base;*document=&documents[i];*line=0;*column=0;
      for(size_t j=0;j<local;++j){if(documents[i].text[j]=='\n'){++*line;*column=0;}else ++*column;}return true;}base+=length+1;}return false;
}
static void lsp_inlay_hints(long id,LspDocument *documents,size_t count,LspDocument *requested) {
  LspSemantic semantic=lsp_semantic_build(documents,count);char body[65536];size_t at=(size_t)snprintf(body,sizeof(body),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[",id);bool comma=false;
  for(size_t i=0;semantic.ok&&i<semantic.ast.local_count;++i){DynAstLocal *local=&semantic.ast.locals[i];LspDocument *document=NULL;size_t line=0,column=0;if(!lsp_span_location(documents,count,local->name,&document,&line,&column)||document!=requested)continue;size_t local_length=local->name.end_byte-local->name.start_byte;const char *row=requested->text;for(size_t r=0;r<line&&row;++r){row=strchr(row,'\n');if(row)++row;}if(!row)continue;const char *after=row+column+local_length;while(*after==' '||*after=='\t')++after;if(after[0]!=':'||after[1]!='=')continue;char type[128];dyn_type_format(&semantic.ast,local->type,&semantic.source,type,sizeof(type));at+=(size_t)snprintf(body+at,sizeof(body)-at,"%s{\"position\":{\"line\":%zu,\"character\":%zu},\"label\":\": %s\",\"kind\":1,\"paddingLeft\":true}",comma?",":"",line,column+local_length,type);comma=true;if(at+512>=sizeof(body))break;}
  snprintf(body+at,sizeof(body)-at,"]}");lsp_send(body);lsp_semantic_free(&semantic);
}
static DynSpan lsp_expr_definition(DynAstFunction *a,DynAstExpr *e) {
  if(e->kind==DYN_EXPR_NAME&&e->integer<a->local_count)return a->locals[e->integer].name;
  if(e->kind==DYN_EXPR_GLOBAL&&e->integer<a->global_count)return a->globals[e->integer].name;
  if(e->kind==DYN_EXPR_FUNCTION&&e->integer<a->function_count)return a->functions[e->integer].name;
  if(e->kind==DYN_EXPR_FIELD&&e->left<a->expression_count){DynType base=a->expressions[e->left].type;if(dyn_type_is_pointer(base)){uint32_t p=base-DYN_TYPE_POINTER_BASE;if(p<a->pointer_count)base=a->pointers[p].pointee;}if(dyn_type_is_struct(base)){DynAstStruct *s=&a->structs[base-DYN_TYPE_STRUCT_BASE];if(e->integer<s->field_count)return a->fields[s->field_start+(uint32_t)e->integer].name;}}
  return (DynSpan){0};
}
static bool lsp_same_span(DynSpan a,DynSpan b){return a.start_byte==b.start_byte&&a.end_byte==b.end_byte;}
static bool lsp_variable_target(DynAstFunction *a,DynSpan target){for(size_t i=0;i<a->local_count;++i)if(lsp_same_span(a->locals[i].name,target))return true;for(size_t i=0;i<a->global_count;++i)if(lsp_same_span(a->globals[i].name,target))return true;return false;}
static bool lsp_valid_identifier(const char *name){if(!name||!(*name=='_'||isalpha((unsigned char)*name)))return false;for(++name;*name;++name)if(!(*name=='_'||isalnum((unsigned char)*name)))return false;return true;}
static void lsp_semantic_references(long id,LspSemantic *semantic,LspDocument *documents,size_t count,DynSpan target) {
  size_t capacity=1024u*1024u,at=0;char *body=malloc(capacity);if(!body)return;at=(size_t)snprintf(body,capacity,"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[",id);bool comma=false;DynSpan spans[4096];size_t span_count=0;spans[span_count++]=target;
  for(size_t i=0;i<semantic->ast.expression_count&&span_count<4096;++i){DynAstExpr *e=&semantic->ast.expressions[i];if(lsp_same_span(lsp_expr_definition(&semantic->ast,e),target)&&!lsp_same_span(e->span,target))spans[span_count++]=e->span;}
  for(size_t i=0;i<span_count;++i){LspDocument *document=NULL;size_t line=0,column=0;if(!lsp_span_location(documents,count,spans[i],&document,&line,&column))continue;char *uri=json_escape(document->uri,strlen(document->uri));if(uri){at+=(size_t)snprintf(body+at,capacity-at,"%s{\"uri\":\"%s\",\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}}}",comma?",":"",uri,line,column,line,column+(spans[i].end_byte-spans[i].start_byte));comma=true;}free(uri);}snprintf(body+at,capacity-at,"]}");lsp_send(body);free(body);
}
static void lsp_semantic_rename(long id,LspSemantic *semantic,LspDocument *documents,size_t count,DynSpan target,const char *replacement) {
  size_t capacity=1024u*1024u,at=0;char *body=malloc(capacity);if(!body)return;at=(size_t)snprintf(body,capacity,"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"changes\":{",id);DynSpan spans[4096];size_t span_count=0;spans[span_count++]=target;for(size_t i=0;i<semantic->ast.expression_count&&span_count<4096;++i){DynAstExpr *e=&semantic->ast.expressions[i];if(lsp_same_span(lsp_expr_definition(&semantic->ast,e),target)&&!lsp_same_span(e->span,target))spans[span_count++]=e->span;}
  bool document_comma=false;for(size_t d=0;d<count;++d){char edits[65536];size_t edit_at=0;bool edit_comma=false;for(size_t i=0;i<span_count;++i){LspDocument *document=NULL;size_t line=0,column=0;if(!lsp_span_location(documents,count,spans[i],&document,&line,&column)||document!=&documents[d])continue;edit_at+=(size_t)snprintf(edits+edit_at,sizeof(edits)-edit_at,"%s{\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}},\"newText\":\"%s\"}",edit_comma?",":"",line,column,line,column+(spans[i].end_byte-spans[i].start_byte),replacement);edit_comma=true;}if(edit_comma){char *uri=json_escape(documents[d].uri,strlen(documents[d].uri));if(uri)at+=(size_t)snprintf(body+at,capacity-at,"%s\"%s\":[%s]",document_comma?",":"",uri,edits),document_comma=true;free(uri);}}
  snprintf(body+at,capacity-at,"}}}");lsp_send(body);free(body);
}
static void lsp_function_hover(LspSemantic *semantic,uint32_t index,char *out,size_t capacity) {
  DynAstFunction *a=&semantic->ast; DynAstFn *fn=&a->functions[index]; size_t at=0;
#define APPEND(...) do { if(at<capacity){int n=snprintf(out+at,capacity-at,__VA_ARGS__);if(n>0)at+=(size_t)n<capacity-at?(size_t)n:capacity-at-1;} } while(0)
  APPEND("%s%sfn %.*s(",fn->is_public?"pub ":"",fn->foreign?"extern ":"",
         (int)(fn->name.end_byte-fn->name.start_byte),semantic->source.text+fn->name.start_byte);
  for(uint32_t i=0;i<fn->param_count;++i){DynAstParam *p=&a->params[fn->param_start+i];char type[128];dyn_type_format(a,p->type,&semantic->source,type,sizeof(type));
    APPEND("%s%.*s: %s",i?", ":"",(int)(p->name.end_byte-p->name.start_byte),semantic->source.text+p->name.start_byte,type);}
  if(fn->variadic){if(fn->param_count)APPEND(", ");if(fn->variadic_name.end_byte>fn->variadic_name.start_byte){DynType t=fn->variadic_type;
      if(dyn_type_is_slice(t)){uint32_t i=t-DYN_TYPE_SLICE_BASE;if(i<a->slice_count)t=a->slices[i].element;}char type[128];dyn_type_format(a,t,&semantic->source,type,sizeof(type));
      APPEND("%.*s: ...%s",(int)(fn->variadic_name.end_byte-fn->variadic_name.start_byte),semantic->source.text+fn->variadic_name.start_byte,type);}else APPEND("...");}
  APPEND(")");if(fn->return_type!=DYN_TYPE_VOID){char type[128];dyn_type_format(a,fn->return_type,&semantic->source,type,sizeof(type));APPEND(" %s",type);}
#undef APPEND
}
static void lsp_struct_hover(LspSemantic *semantic,uint32_t index,char *out,size_t capacity) {
  DynAstFunction *a=&semantic->ast;DynAstStruct *s=&a->structs[index];size_t at=0;
#define APPEND_STRUCT(...) do{if(at<capacity){int n=snprintf(out+at,capacity-at,__VA_ARGS__);if(n>0)at+=(size_t)n<capacity-at?(size_t)n:capacity-at-1;}}while(0)
  APPEND_STRUCT("%s%sstruct %.*s {",s->is_public?"pub ":"",s->packed?"packed ":"",(int)(s->name.end_byte-s->name.start_byte),semantic->source.text+s->name.start_byte);
  uint32_t shown=s->field_count<8?s->field_count:8;for(uint32_t i=0;i<shown;++i){DynAstField *field=&a->fields[s->field_start+i];char type[128];dyn_type_format(a,field->type,&semantic->source,type,sizeof(type));APPEND_STRUCT("\n  %.*s: %s",(int)(field->name.end_byte-field->name.start_byte),semantic->source.text+field->name.start_byte,type);}
  if(shown<s->field_count)APPEND_STRUCT("\n  ... %u more",s->field_count-shown);
  APPEND_STRUCT("\n}");
#undef APPEND_STRUCT
}
static void lsp_enum_hover(LspSemantic *semantic,uint32_t index,char *out,size_t capacity) {
  DynAstFunction *a=&semantic->ast;DynAstEnum *e=&a->enums[index];size_t at=(size_t)snprintf(out,capacity,"%senum %.*s {",e->is_public?"pub ":"",(int)(e->name.end_byte-e->name.start_byte),semantic->source.text+e->name.start_byte);uint32_t shown=e->variant_count<8?e->variant_count:8;
  for(uint32_t i=0;i<shown&&at<capacity;++i){DynAstVariant *v=&a->variants[e->variant_start+i];char payload[128]={0};if(v->payload_type!=DYN_TYPE_VOID)dyn_type_format(a,v->payload_type,&semantic->source,payload,sizeof(payload));int n=snprintf(out+at,capacity-at,"\n  %.*s%s%s",(int)(v->name.end_byte-v->name.start_byte),semantic->source.text+v->name.start_byte,*payload?" ":"",payload);if(n>0)at+=(size_t)n<capacity-at?(size_t)n:capacity-at-1;}
  if(shown<e->variant_count&&at<capacity){int n=snprintf(out+at,capacity-at,"\n  ... %u more",e->variant_count-shown);if(n>0)at+=(size_t)n<capacity-at?(size_t)n:capacity-at-1;}if(at<capacity)snprintf(out+at,capacity-at,"\n}");
}
static void lsp_alias_hover(LspSemantic *semantic,uint32_t index,char *out,size_t capacity) {DynAstAlias *alias=&semantic->ast.aliases[index];char target[256];dyn_type_format(&semantic->ast,alias->target,&semantic->source,target,sizeof(target));snprintf(out,capacity,"%s%stype %.*s = %s",alias->is_public?"pub ":"",alias->distinct?"distinct ":"",(int)(alias->name.end_byte-alias->name.start_byte),semantic->source.text+alias->name.start_byte,target);}
static void lsp_global_hover(LspSemantic *semantic,uint32_t index,char *out,size_t capacity) {DynAstGlobal *global=&semantic->ast.globals[index];char type[256];dyn_type_format(&semantic->ast,global->type,&semantic->source,type,sizeof(type));snprintf(out,capacity,"%s%s %.*s: %s",global->is_public?"pub ":"",global->is_const?"const":"global",(int)(global->name.end_byte-global->name.start_byte),semantic->source.text+global->name.start_byte,type);}
static bool lsp_typed_symbol(LspSemantic *semantic,uint32_t offset,char *hover,size_t capacity,DynSpan *definition) {
  DynAstFunction *a=&semantic->ast; DynAstExpr *best=NULL;
  for(size_t i=0;i<a->expression_count;++i){DynAstExpr *e=&a->expressions[i];if(offset>=e->span.start_byte&&offset<e->span.end_byte&&e->type!=DYN_TYPE_INFER&&e->type!=DYN_TYPE_ERROR)
      if(!best||e->span.end_byte-e->span.start_byte<best->span.end_byte-best->span.start_byte)best=e;}
  DynType type=DYN_TYPE_ERROR; DynSpan declared={0}; const char *kind="value"; uint32_t function=UINT32_MAX,structure=UINT32_MAX,enumeration=UINT32_MAX,alias=UINT32_MAX,global=UINT32_MAX;
  if(best){type=best->type;
    if(best->kind==DYN_EXPR_NAME&&best->integer<a->local_count){declared=a->locals[best->integer].name;kind=a->locals[best->integer].is_const?"const":"variable";}
    else if(best->kind==DYN_EXPR_GLOBAL&&best->integer<a->global_count){global=(uint32_t)best->integer;declared=a->globals[global].name;kind=a->globals[global].is_const?"const":"global";}
    else if(best->kind==DYN_EXPR_FUNCTION&&best->integer<a->function_count){function=(uint32_t)best->integer;declared=a->functions[function].name;kind="function";}
    else if(best->kind==DYN_EXPR_FIELD&&best->left<a->expression_count){
      DynType base=a->expressions[best->left].type;
      if(dyn_type_is_pointer(base)){uint32_t pointer=base-DYN_TYPE_POINTER_BASE;if(pointer<a->pointer_count)base=a->pointers[pointer].pointee;}
      if(dyn_type_is_struct(base)){DynAstStruct *structure=&a->structs[base-DYN_TYPE_STRUCT_BASE];if(best->integer<structure->field_count)declared=a->fields[structure->field_start+(uint32_t)best->integer].name;kind="field";}
    }
  }
  if(function==UINT32_MAX&&offset<semantic->source.length){uint32_t start=offset,end=offset;
    while(start&&((unsigned char)semantic->source.text[start-1]=='_'||isalnum((unsigned char)semantic->source.text[start-1])))--start;
    while(end<semantic->source.length&&((unsigned char)semantic->source.text[end]=='_'||isalnum((unsigned char)semantic->source.text[end])))++end;
    for(size_t i=0;i<a->function_count;++i){DynSpan name=a->functions[i].name;if(name.end_byte-name.start_byte==end-start&&!memcmp(semantic->source.text+name.start_byte,semantic->source.text+start,end-start)){function=(uint32_t)i;type=DYN_TYPE_VOID;declared=name;kind="function";break;}}
    for(size_t i=0;i<a->struct_count&&structure==UINT32_MAX;++i){DynSpan name=a->structs[i].name;if(name.end_byte-name.start_byte==end-start&&!memcmp(semantic->source.text+name.start_byte,semantic->source.text+start,end-start)){structure=(uint32_t)i;type=DYN_TYPE_STRUCT_BASE+(DynType)i;declared=name;kind="struct";}}
    for(size_t i=0;i<a->enum_count&&enumeration==UINT32_MAX;++i){DynSpan name=a->enums[i].name;if(name.end_byte-name.start_byte==end-start&&!memcmp(semantic->source.text+name.start_byte,semantic->source.text+start,end-start)){enumeration=(uint32_t)i;type=DYN_TYPE_ENUM_BASE+(DynType)i;declared=name;kind="enum";}}
    for(size_t i=0;i<a->alias_count&&alias==UINT32_MAX;++i){DynSpan name=a->aliases[i].name;if(name.end_byte-name.start_byte==end-start&&!memcmp(semantic->source.text+name.start_byte,semantic->source.text+start,end-start)){alias=(uint32_t)i;type=a->aliases[i].target;declared=name;kind="type";}}
    for(size_t i=0;i<a->global_count&&global==UINT32_MAX;++i){DynSpan name=a->globals[i].name;if(name.end_byte-name.start_byte==end-start&&!memcmp(semantic->source.text+name.start_byte,semantic->source.text+start,end-start)){global=(uint32_t)i;type=a->globals[i].type;declared=name;kind=a->globals[i].is_const?"const":"global";}}
  }
  for(size_t i=0;i<a->function_count&&function==UINT32_MAX;++i)if(offset>=a->functions[i].name.start_byte&&offset<a->functions[i].name.end_byte){function=(uint32_t)i;type=DYN_TYPE_VOID;declared=a->functions[i].name;kind="function";}
  for(size_t i=0;i<a->local_count&&type==DYN_TYPE_ERROR;++i)if(offset>=a->locals[i].name.start_byte&&offset<a->locals[i].name.end_byte){type=a->locals[i].type;declared=a->locals[i].name;kind=a->locals[i].is_const?"const":"variable";}
  if (type == DYN_TYPE_ERROR) return false;
  if(function!=UINT32_MAX){lsp_function_hover(semantic,function,hover,capacity);*definition=declared;return true;}
  if(structure!=UINT32_MAX){lsp_struct_hover(semantic,structure,hover,capacity);*definition=declared;return true;}
  if(enumeration!=UINT32_MAX){lsp_enum_hover(semantic,enumeration,hover,capacity);*definition=declared;return true;}
  if(alias!=UINT32_MAX){lsp_alias_hover(semantic,alias,hover,capacity);*definition=declared;return true;}
  if(global!=UINT32_MAX){lsp_global_hover(semantic,global,hover,capacity);*definition=declared;return true;}
  char name[384]; dyn_type_format(a,type,&semantic->source,name,sizeof(name));
  if (declared.end_byte > declared.start_byte) {
    size_t declared_length=declared.end_byte-declared.start_byte;
    if(declared_length>96)declared_length=96;
    snprintf(hover,capacity,"%s %.*s: %.*s",kind,(int)declared_length,
             semantic->source.text+declared.start_byte,383,name);
  } else snprintf(hover,capacity,"%s: %.*s",kind,383,name);
  *definition=declared; return true;
}
static bool lsp_import_definition(LspDocument *document,size_t line,size_t character,
    char **uri,size_t *out_line,size_t *out_column,size_t *out_length) {
  if(!document||!document->text)return false;
  const char *row=document->text;for(size_t i=0;i<line;++i){row=strchr(row,'\n');if(!row)return false;++row;}const char *row_end=strchr(row,'\n');if(!row_end)row_end=row+strlen(row);uint32_t offset=(uint32_t)(row-document->text+(character>(size_t)(row_end-row)?(size_t)(row_end-row):character));
  LspImport imports[32];size_t count=lsp_imports(document,imports,32);LspImport *import=NULL;char member[128]={0};
  for(size_t i=0;i<count;++i)if(offset>=ts_node_start_byte(imports[i].node)&&offset<=ts_node_end_byte(imports[i].node)){import=&imports[i];break;}
  if(!import){const char *word=NULL;size_t length=0;if(!identifier_at(document->text,line,character,&word,&length)&&!lsp_call_identifier(document->text,line,character,&word,&length))return false;const char *dot=NULL,*member_start=NULL;size_t member_length=0;
    if(word>row&&word[-1]=='.'){dot=word-1;member_start=word;member_length=length;}else if(word+length<row_end&&word[length]=='.'){dot=word+length;member_start=dot+1;while(member_start+member_length<row_end&&(isalnum((unsigned char)member_start[member_length])||member_start[member_length]=='_'))++member_length;}if(!dot||!member_length||member_length>=sizeof(member))return false;
    const char *alias_end=dot,*alias_start=alias_end;while(alias_start>row&&(isalnum((unsigned char)alias_start[-1])||alias_start[-1]=='_'))--alias_start;
    for(size_t i=0;i<count;++i)if(strlen(imports[i].alias)==(size_t)(alias_end-alias_start)&&!memcmp(imports[i].alias,alias_start,(size_t)(alias_end-alias_start))){import=&imports[i];break;}
    if(!import)return false;
    memcpy(member,member_start,member_length);member[member_length]=0;
  }
  char *target=lsp_resolve_import(document,import->path);if(!target)return false;
  if(!*member){char *path=lsp_first_dyn_file(target);free(target);if(!path)return false;*uri=lsp_path_uri(path);free(path);*out_line=*out_column=0;*out_length=1;return *uri!=NULL;}
  DynSources sources={0};bool found=false;if(!dyn_sources_load(target,&sources))for(size_t i=0;i<sources.count&&!found;++i){const char *display=NULL;size_t display_length=0;if(find_declaration(sources.items[i].text,member,strlen(member),out_line,out_column,&display,&display_length)){*uri=lsp_path_uri(sources.items[i].path);*out_length=strlen(member);found=*uri!=NULL;}}
  dyn_sources_free(&sources);free(target);return found;
}

int dyn_lsp(void) {
  char header[256];
  LspDocument documents[LSP_DOCUMENT_LIMIT] = {{0}}; size_t document_count = 0;
  while (fgets(header, sizeof(header), stdin)) {
    size_t length = 0;
    do {
      if (!strncasecmp(header, "Content-Length:", 15))
        length = (size_t)strtoull(header + 15, NULL, 10);
      if (!strcmp(header, "\n") || !strcmp(header, "\r\n")) break;
    } while (fgets(header, sizeof(header), stdin));
    if (!length || length > 16u * 1024u * 1024u) return 2;
    char *body = malloc(length + 1);
    if (!body) return 2;
    if (fread(body, 1, length, stdin) != length) { free(body); return 2; }
    body[length] = 0; long id = request_id(body);
    if (strstr(body, "\"method\":\"initialize\"")) {
      char response[2048];
      snprintf(response, sizeof(response),
        "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"capabilities\":{"
        "\"positionEncoding\":\"utf-8\",\"textDocumentSync\":1,\"hoverProvider\":true,"
        "\"definitionProvider\":true,\"referencesProvider\":true,\"renameProvider\":true,"
        "\"documentSymbolProvider\":true,\"workspaceSymbolProvider\":true,"
        "\"documentFormattingProvider\":true,\"inlayHintProvider\":true,\"codeActionProvider\":true,"
        "\"semanticTokensProvider\":{\"legend\":{\"tokenTypes\":[\"namespace\",\"type\","
        "\"struct\",\"enum\",\"parameter\",\"variable\",\"property\",\"enumMember\",\"function\"],"
        "\"tokenModifiers\":[]},\"full\":true},\"completionProvider\":{\"triggerCharacters\":["
        "\".\",\"#\",\"\\\"\",\"_\",\"a\",\"b\",\"c\",\"d\",\"e\",\"f\",\"g\",\"h\","
        "\"i\",\"j\",\"k\",\"l\",\"m\",\"n\",\"o\",\"p\",\"q\",\"r\",\"s\",\"t\","
        "\"u\",\"v\",\"w\",\"x\",\"y\",\"z\"]},\"signatureHelpProvider\":{"
        "\"triggerCharacters\":[\"(\",\",\"]}}}}", id);
      lsp_send(response);
    } else if(strstr(body,"\"method\":\"textDocument/didClose\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);for(size_t i=0;uri&&i<document_count;++i)if(!strcmp(documents[i].uri,uri)){char *escaped=json_escape(uri,strlen(uri));char response[512];if(escaped){snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/publishDiagnostics\",\"params\":{\"uri\":\"%s\",\"diagnostics\":[]}}",escaped);lsp_send(response);}free(escaped);free(documents[i].uri);free(documents[i].text);if(documents[i].tree)ts_tree_delete(documents[i].tree);if(documents[i].parser)ts_parser_delete(documents[i].parser);memmove(&documents[i],&documents[i+1],(document_count-i-1)*sizeof(*documents));--document_count;memset(&documents[document_count],0,sizeof(*documents));break;}free(uri);
    } else if (strstr(body, "\"method\":\"textDocument/didOpen\"") ||
               strstr(body, "\"method\":\"textDocument/didChange\"")) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      char *text = json_string_after(body, "\"text\"", 1024u * 1024u);
      LspDocument *document = uri ? lsp_document(documents, document_count, uri) : NULL;
      if (!document && uri && document_count < LSP_DOCUMENT_LIMIT) document = &documents[document_count++];
      if (document && uri && text) {
        free(document->uri); free(document->text); document->uri = uri; document->text = text;
        bool syntax_error=lsp_publish_syntax(document);if(!syntax_error)lsp_publish_semantic(documents, document_count);
      } else { free(uri); free(text); }
    } else if(strstr(body,"\"method\":\"textDocument/documentSymbol\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;if(document)lsp_document_symbols(id,document);else{char response[96];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",id);lsp_send(response);}free(uri);
    } else if(strstr(body,"\"method\":\"textDocument/semanticTokens/full\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;if(document)lsp_semantic_tokens(id,document);else{char response[96];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",id);lsp_send(response);}free(uri);
    } else if(strstr(body,"\"method\":\"workspace/symbol\"")){
      lsp_workspace_symbols(id,documents,document_count);
    } else if(strstr(body,"\"method\":\"textDocument/codeAction\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;if(document)lsp_code_actions(id,document,body);else{char response[96];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}",id);lsp_send(response);}free(uri);
    } else if(strstr(body,"\"method\":\"textDocument/formatting\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;if(document)lsp_format(id,document);free(uri);
    } else if(strstr(body,"\"method\":\"textDocument/inlayHint\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;if(document)lsp_inlay_hints(id,documents,document_count,document);free(uri);
    } else if (strstr(body, "\"method\":\"textDocument/completion\"")) {
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);size_t line=0,character=0;
      LspDocument *requested=uri?lsp_document(documents,document_count,uri):NULL;(void)json_position(body,&line,&character);
      lsp_completion(id,documents,document_count,requested,line,character);free(uri);
    } else if (strstr(body, "\"method\":\"textDocument/hover\"") ||
               strstr(body, "\"method\":\"textDocument/definition\"") ||
               strstr(body, "\"method\":\"textDocument/references\"") ||
               strstr(body, "\"method\":\"textDocument/rename\"") ||
               strstr(body, "\"method\":\"textDocument/signatureHelp\"")) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      size_t line=0, character=0; const char *word=NULL, *display=NULL; size_t word_length=0, display_length=0, found_line=0, found_column=0;
      LspDocument *requested = uri ? lsp_document(documents, document_count, uri) : NULL;
      LspDocument *definition = NULL, external={0};bool import_found=false,builtin_found=false;char import_hover[512]={0},signature[512]={0};
      bool positioned = requested && requested->text && json_position(body, &line, &character);
      const char *builtin=positioned&&strstr(body,"textDocument/hover")?lsp_builtin_hover(requested->text,line,character):NULL;
      bool found=builtin!=NULL;if(found){display=builtin;display_length=strlen(builtin);builtin_found=true;}
      if(!found)found = positioned && (strstr(body,"textDocument/signatureHelp")
        ? lsp_call_identifier(requested->text,line,character,&word,&word_length)
        : identifier_at(requested->text,line,character,&word,&word_length));
      if (found&&!builtin_found) {
        for (size_t i = 0; i < document_count; ++i) {
          size_t candidate = documents + i == requested ? 0 : i + 1;
          LspDocument *doc = candidate == 0 ? requested : &documents[candidate - 1];
          if (candidate != 0 && doc == requested) continue;
          if (doc->text && find_declaration(doc->text, word, word_length, &found_line, &found_column, &display, &display_length)) { definition = doc; break; }
        }
        found = definition != NULL;
      }
      if(!builtin_found&&positioned&&(strstr(body,"textDocument/definition")||strstr(body,"textDocument/hover")||strstr(body,"textDocument/signatureHelp"))){size_t target_length=0;import_found=lsp_import_definition(requested,line,character,&external.uri,&found_line,&found_column,&target_length);if(import_found){definition=&external;word_length=target_length;found=true;if(strstr(body,"textDocument/hover")||strstr(body,"textDocument/signatureHelp")){FILE *file=fopen(lsp_file_path(external.uri),"rb");if(file){char source_line[1024]={0};for(size_t row=0;row<=found_line&&fgets(source_line,sizeof(source_line),file);++row){}fclose(file);char *start=source_line;while(isspace((unsigned char)*start))++start;lsp_completion_signature(start,import_hover,sizeof(import_hover));display=import_hover;display_length=strlen(import_hover);}}}}
      if(found&&!import_found&&strstr(body,"textDocument/signatureHelp")){lsp_completion_signature(display,signature,sizeof(signature));display=signature;display_length=strlen(signature);}
      LspSemantic semantic = lsp_semantic_build(documents, document_count); char typed_hover[512]; DynSpan typed_definition={0}; uint32_t typed_offset=0;
      bool typed = positioned && semantic.ok && lsp_document_offset(documents,document_count,requested,line,character,&typed_offset) &&
                   lsp_typed_symbol(&semantic,typed_offset,typed_hover,sizeof(typed_hover),&typed_definition);
      if (!builtin_found&&!import_found&&typed && strstr(body,"textDocument/hover") &&
          (!found || typed_definition.end_byte > typed_definition.start_byte)) {
        display=typed_hover; display_length=strlen(typed_hover); found=true;
      }
      if (!import_found&&typed && strstr(body,"textDocument/definition") && typed_definition.end_byte>typed_definition.start_byte)
        found=lsp_span_location(documents,document_count,typed_definition,&definition,&found_line,&found_column);
      if(typed&&typed_definition.end_byte>typed_definition.start_byte&&(strstr(body,"textDocument/references")||strstr(body,"textDocument/rename")))found=true;
      if (found && (strstr(body, "textDocument/references") || strstr(body, "textDocument/rename"))) {
        char *new_name = strstr(body, "textDocument/rename") ? json_string_after(body, "\"newName\"", 1024) : NULL;
        bool semantic_target=typed&&typed_definition.end_byte>typed_definition.start_byte&&lsp_variable_target(&semantic.ast,typed_definition);
        if(new_name&&!lsp_valid_identifier(new_name)){char response[192];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"error\":{\"code\":-32602,\"message\":\"rename requires a valid Dyn identifier\"}}",id);lsp_send(response);}
        else if(new_name&&semantic_target)lsp_semantic_rename(id,&semantic,documents,document_count,typed_definition,new_name);
        else if(new_name) lsp_rename(id, documents, document_count, word, word_length, new_name);
        else if(semantic_target)lsp_semantic_references(id,&semantic,documents,document_count,typed_definition);
        else lsp_references(id, documents, document_count, word, word_length, NULL);
        free(new_name);
      } else if (!found) {
        char response[96]; snprintf(response, sizeof(response), "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}", id); lsp_send(response);
      } else if (strstr(body, "textDocument/hover")) {
        char *escaped = json_escape(display, display_length);
        size_t capacity = (escaped ? strlen(escaped) : 0) + 160; char *response = malloc(capacity);
        if (escaped && response) { snprintf(response, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"contents\":{\"kind\":\"plaintext\",\"value\":\"%s\"}}}", id, escaped); lsp_send(response); }
        free(escaped); free(response);
      } else if (strstr(body, "textDocument/signatureHelp")) {
        char *escaped = json_escape(display, display_length); size_t capacity = (escaped ? strlen(escaped) : 0) + 192; char *response = malloc(capacity);size_t active=lsp_active_parameter(requested->text,line,character);
        if (escaped && response) { snprintf(response, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"signatures\":[{\"label\":\"%s\"}],\"activeSignature\":0,\"activeParameter\":%zu}}", id, escaped,active); lsp_send(response); }
        free(escaped); free(response);
      } else {
        char *escaped_uri = json_escape(definition->uri, strlen(definition->uri)); size_t capacity = (escaped_uri ? strlen(escaped_uri) : 0) + 256; char *response = malloc(capacity);
        if (escaped_uri && response) { snprintf(response, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"uri\":\"%s\",\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}}}}", id, escaped_uri, found_line, found_column, found_line, found_column + word_length); lsp_send(response); }
        free(escaped_uri); free(response);
      }
      lsp_semantic_free(&semantic);
      free(external.uri);
      free(uri);
    } else if (strstr(body, "\"method\":\"shutdown\"")) {
      char response[96]; snprintf(response, sizeof(response),
        "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}", id); lsp_send(response);
    } else if (strstr(body, "\"method\":\"exit\"")) {
      free(body); for (size_t i = 0; i < document_count; ++i) { free(documents[i].uri); free(documents[i].text); if (documents[i].tree) ts_tree_delete(documents[i].tree); if (documents[i].parser) ts_parser_delete(documents[i].parser); } return 0;
    }
    else if (id >= 0) {
      char response[160]; snprintf(response, sizeof(response),
        "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"error\":{\"code\":-32601,\"message\":\"method not supported\"}}", id); lsp_send(response);
    }
    free(body);
  }
  for (size_t i = 0; i < document_count; ++i) { free(documents[i].uri); free(documents[i].text); if (documents[i].tree) ts_tree_delete(documents[i].tree); if (documents[i].parser) ts_parser_delete(documents[i].parser); }
  return 0;
}
