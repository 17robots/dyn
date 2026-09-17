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
static void lsp_completion_expression_fields(LspDocument *,size_t,LspDocument *,size_t,size_t,char *,size_t,size_t *,bool *);
static void lsp_completion_locals(LspDocument *,size_t,LspDocument *,size_t,size_t,char *,size_t,size_t *,bool *);
static void lsp_completion_struct_fields(LspDocument *,size_t,LspDocument *,size_t,size_t,char *,size_t,size_t *,bool *);
static void lsp_completion_enum_variants(LspDocument *,size_t,LspDocument *,const char *,bool,char *,size_t,size_t *,bool *);
static void lsp_completion_expected_enum(LspDocument *,size_t,LspDocument *,size_t,size_t,char *,size_t,size_t *,bool *);
static bool lsp_expected_enum_name(LspDocument *,size_t,LspDocument *,size_t,size_t,char *,size_t);
static bool lsp_typed_symbol(LspSemantic *,uint32_t,char *,size_t,DynSpan *);
static void lsp_completion_auto_imports(const LspDocument *,const char *,char *,size_t,size_t *,bool *);
static bool lsp_completion_has_label(const char *,size_t,const char *,size_t);

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

static bool lsp_directory_has_dyn(const char *directory) {
  DIR *dir=opendir(directory);if(!dir)return false;struct dirent *entry;bool found=false;
  while((entry=readdir(dir))){size_t n=strlen(entry->d_name);if(n>=4&&!strcmp(entry->d_name+n-4,".dyn")){found=true;break;}}
  closedir(dir);return found;
}
static bool lsp_directory_contains_dyn(const char *directory,unsigned depth) {
  if(depth>8)return false;
  if(lsp_directory_has_dyn(directory))return true;
  DIR *dir=opendir(directory);if(!dir)return false;struct dirent *entry;bool found=false;
  while(!found&&(entry=readdir(dir))){if(entry->d_name[0]=='.')continue;char *path=dyn_path_join(directory,entry->d_name);if(path&&dyn_path_is_directory(path))found=lsp_directory_contains_dyn(path,depth+1);free(path);}closedir(dir);return found;
}
static void lsp_completion_packages(const char *directory,char *body,size_t capacity,size_t *at,bool *comma) {
  DIR *dir=opendir(directory);if(!dir)return;struct dirent *entry;
  while((entry=readdir(dir))){if(entry->d_name[0]=='.')continue;char *path=dyn_path_join(directory,entry->d_name);if(!path||!dyn_path_is_directory(path)||!lsp_directory_contains_dyn(path,0)){free(path);continue;}bool package=lsp_directory_has_dyn(path);*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"label\":\"%s\",\"kind\":19,\"detail\":\"Dyn %s\",\"insertText\":\"%s%s\"}",*comma?",":"",entry->d_name,package?"package":"package group",entry->d_name,package?"":"/");*comma=true;free(path);
  }closedir(dir);
}
static void lsp_completion_namespace(const char *label,char *body,size_t capacity,size_t *at,bool *comma) {
  *at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"label\":\"%s\",\"kind\":19,\"detail\":\"Dyn package root\",\"insertText\":\"%s/\"}",*comma?",":"",label,label);*comma=true;
}
static void lsp_completion_imports(const LspDocument *document,const char *typed,char *body,size_t capacity,size_t *at,bool *comma) {
  char *std_package=lsp_resolve_import(document,"std/io"),*std_root=std_package?lsp_directory(std_package):NULL;
  char *vendor_package=lsp_resolve_import(document,"vendor/sqlite"),*vendor_root=vendor_package?lsp_directory(vendor_package):NULL;
  char *project=lsp_project_root(document->uri),*current=lsp_directory(lsp_file_path(document->uri));
  char *directory=NULL;
  if(!*typed){lsp_completion_namespace("std",body,capacity,at,comma);lsp_completion_namespace("vendor",body,capacity,at,comma);*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"label\":\".\",\"kind\":19,\"insertText\":\"./\"}",*comma?",":"");*comma=true;if(current&&project&&strcmp(current,project)){*at+=(size_t)snprintf(body+*at,capacity-*at,",{\"label\":\"..\",\"kind\":19,\"insertText\":\"../\"}");}directory=project?strdup(project):NULL;}
  else {const char *slash=strrchr(typed,'/');if(slash){size_t n=(size_t)(slash-typed);char path[1024];if(n<sizeof(path)){memcpy(path,typed,n);path[n]=0;if(!strcmp(path,"std"))directory=std_root?strdup(std_root):NULL;else if(!strcmp(path,"vendor"))directory=vendor_root?strdup(vendor_root):NULL;else if(!strcmp(path,"."))directory=current?strdup(current):NULL;else if(!strcmp(path,".."))directory=current?lsp_directory(current):NULL;else directory=lsp_resolve_import(document,path);}}else if(!strcmp(typed,"std"))lsp_completion_namespace("std",body,capacity,at,comma);else if(!strcmp(typed,"vendor"))lsp_completion_namespace("vendor",body,capacity,at,comma);else directory=project?strdup(project):NULL;}
  if(directory)lsp_completion_packages(directory,body,capacity,at,comma);
  free(directory);
  free(std_package);free(std_root);free(vendor_package);free(vendor_root);free(project);free(current);
}
static bool lsp_has_import(const LspDocument *document,const char *path) {
  LspImport imports[32];size_t count=lsp_imports(document,imports,32);for(size_t i=0;i<count;++i)if(!strcmp(imports[i].path,path))return true;return false;
}
static bool lsp_completion_has_label(const char *body,size_t length,const char *label,size_t label_length) {
  const char prefix[]="\"label\":\"";const char *p=body,*end=body+length;
  while(p<end&&(p=memchr(p,'"',(size_t)(end-p)))){if((size_t)(end-p)>=sizeof(prefix)-1+label_length+1&&!memcmp(p,prefix,sizeof(prefix)-1)&&!memcmp(p+sizeof(prefix)-1,label,label_length)&&p[sizeof(prefix)-1+label_length]=='"')return true;++p;}return false;
}
static void lsp_completion_auto_import_directory(const LspDocument *document,
    const char *directory,const char *import_path,const char *prefix,char *body,
    size_t capacity,size_t *at,bool *comma,unsigned depth) {
  if(depth>8||*at+4096>=capacity)return;
  DIR *dir=opendir(directory);if(!dir)return;struct dirent *entry;
  while((entry=readdir(dir))){if(entry->d_name[0]=='.')continue;char *path=dyn_path_join(directory,entry->d_name);if(!path)continue;if(dyn_path_is_directory(path)){char child_import[1024];int n=snprintf(child_import,sizeof(child_import),"%s%s%s",import_path,*import_path?"/":"",entry->d_name);if(n>0&&(size_t)n<sizeof(child_import))lsp_completion_auto_import_directory(document,path,child_import,prefix,body,capacity,at,comma,depth+1);free(path);continue;}size_t path_length=strlen(path);if(path_length<4||strcmp(path+path_length-4,".dyn")||!*import_path||lsp_has_import(document,import_path)){free(path);continue;}FILE *file=fopen(path,"rb");free(path);if(!file)continue;char line[4096];while(fgets(line,sizeof(line),file)){char *q=line;while(isspace((unsigned char)*q))++q;if(strncmp(q,"pub ",4))continue;q+=4;const char *kinds[]={"fn ","struct ","enum ","type ","const "};const unsigned item_kinds[]={3,22,13,25,21};for(size_t k=0;k<sizeof(kinds)/sizeof(kinds[0]);++k){size_t n=strlen(kinds[k]);if(strncmp(q,kinds[k],n))continue;const char *name=q+n,*end=name;while(isalnum((unsigned char)*end)||*end=='_')++end;size_t length=(size_t)(end-name),prefix_length=strlen(prefix);if(!length||prefix_length>length||strncasecmp(name,prefix,prefix_length))break;const char *slash=strrchr(import_path,'/'),*alias=slash?slash+1:import_path;*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"label\":\"%.*s\",\"kind\":%u,\"detail\":\"auto import %s\",\"insertText\":\"%s.%.*s\",\"additionalTextEdits\":[{\"range\":{\"start\":{\"line\":0,\"character\":0},\"end\":{\"line\":0,\"character\":0}},\"newText\":\"use \\\"%s\\\"\\n\"}]}",*comma?",":"",(int)length,name,item_kinds[k],import_path,alias,(int)length,name,import_path);*comma=true;break;}if(*at+4096>=capacity)break;}fclose(file);if(*at+4096>=capacity)break;}closedir(dir);
}
static void lsp_completion_auto_imports(const LspDocument *document,const char *prefix,
    char *body,size_t capacity,size_t *at,bool *comma) {
  if(strlen(prefix)<2)return;
  char *std_package=lsp_resolve_import(document,"std/io"),*std_root=std_package?lsp_directory(std_package):NULL;char *vendor_package=lsp_resolve_import(document,"vendor/sqlite"),*vendor_root=vendor_package?lsp_directory(vendor_package):NULL;char *project=lsp_project_root(document->uri);
  if(std_root)lsp_completion_auto_import_directory(document,std_root,"std",prefix,body,capacity,at,comma,0);
  if(vendor_root)lsp_completion_auto_import_directory(document,vendor_root,"vendor",prefix,body,capacity,at,comma,0);
  if(project)lsp_completion_auto_import_directory(document,project,"",prefix,body,capacity,at,comma,0);
  free(std_package);free(std_root);free(vendor_package);free(vendor_root);free(project);
}

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
static bool json_range_positions(const char *body,size_t *start_line,size_t *start_character,
    size_t *end_line,size_t *end_character) {
  const char *range=strstr(body,"\"range\"");if(!range)return false;const char *start=strstr(range,"\"start\""),*end=strstr(range,"\"end\"");if(!start||!end||start>end)return false;const char *sl=strstr(start,"\"line\""),*sc=strstr(start,"\"character\""),*el=strstr(end,"\"line\""),*ec=strstr(end,"\"character\"");if(!sl||!sc||!el||!ec)return false;*start_line=(size_t)strtoull(strchr(sl,':')+1,NULL,10);*start_character=(size_t)strtoull(strchr(sc,':')+1,NULL,10);*end_line=(size_t)strtoull(strchr(el,':')+1,NULL,10);*end_character=(size_t)strtoull(strchr(ec,':')+1,NULL,10);return true;
}
static bool lsp_text_offset(const char *text,size_t line,size_t character,size_t *offset) {
  const char *p=text;for(size_t i=0;i<line;++i){p=strchr(p,'\n');if(!p)return false;++p;}const char *end=strchr(p,'\n');if(!end)end=p+strlen(p);if(character>(size_t)(end-p))return false;*offset=(size_t)(p-text)+character;return true;
}
static char *lsp_apply_change(LspDocument *document,const char *replacement,
    size_t start_line,size_t start_character,size_t end_line,size_t end_character) {
  size_t start=0,end=0;if(!lsp_text_offset(document->text,start_line,start_character,&start)||!lsp_text_offset(document->text,end_line,end_character,&end)||end<start)return NULL;size_t old_length=strlen(document->text),new_length=strlen(replacement);char *text=malloc(start+new_length+(old_length-end)+1);if(!text)return NULL;memcpy(text,document->text,start);memcpy(text+start,replacement,new_length);memcpy(text+start+new_length,document->text+end,old_length-end+1);
  if(document->tree){TSPoint new_end={(uint32_t)start_line,(uint32_t)start_character};for(size_t i=0;i<new_length;++i){if(replacement[i]=='\n'){++new_end.row;new_end.column=0;}else ++new_end.column;}TSInputEdit edit={.start_byte=(uint32_t)start,.old_end_byte=(uint32_t)end,.new_end_byte=(uint32_t)(start+new_length),.start_point={(uint32_t)start_line,(uint32_t)start_character},.old_end_point={(uint32_t)end_line,(uint32_t)end_character},.new_end_point=new_end};ts_tree_edit(document->tree,&edit);}
  return text;
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
    {"#target","#target(condition)\nIncludes a source file only when its structured target condition matches."},
    {"#link","#link(\"library\")\nDeclares a native library required when this source file is included."},
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
    char *main_path=dyn_path_join(root,"main.dyn"),*module_path=dyn_path_join(root,"module.dyn"),*manifest=dyn_path_join(root,"dyn.project");bool has_main=main_path&&!access(main_path,F_OK),has_module=module_path&&!access(module_path,F_OK);bool disk_project=has_main||has_module||(manifest&&!access(manifest,F_OK));free(manifest);
    dyn_diagnostic_sink(lsp_collect_diagnostic,&diagnostics);
    int loaded=disk_project?dyn_sources_load(root,&roots):1;if(!loaded){lsp_overlay_sources(&roots,documents,count);loaded=dyn_module_load_project_overlay(root,&roots,&overrides,&sources);owned=!loaded;}dyn_sources_free(&roots);bool project_failed=disk_project&&loaded;
    const char *check_main=has_main?main_path:(has_module?module_path:"");
    if(loaded&&!project_failed){size_t flat_count=0;for(size_t i=0;i<count;++i){char *r=lsp_project_root(documents[i].uri);bool same=r&&!strcmp(root,r);free(r);if(!same)continue;flat[flat_count++]=(DynSource){.path=documents[i].uri,.text=documents[i].text,.length=strlen(documents[i].text)};}sources=(DynSources){flat,flat_count};loaded=0;if(flat_count)check_main=flat[0].path;}
    if(!loaded){(void)dyn_check_sources(&sources,check_main,false);}
    dyn_diagnostic_sink(NULL,NULL);free(main_path);free(module_path);
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
                           const char *word, size_t word_length, const char *replacement,
                           const char *project_root) {
  size_t capacity = 1024u * 1024u, at = 0; char *body = malloc(capacity); if (!body) return;
  at = (size_t)snprintf(body, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id);
  bool comma = false;
  for (size_t i = 0; i < count; ++i) if (documents[i].tree) {
    char *uri = json_escape(documents[i].uri, strlen(documents[i].uri));
    if (uri) lsp_identifier_edits(ts_tree_root_node(documents[i].tree), &documents[i], word, word_length, uri, replacement, body, capacity, &at, &comma);
    free(uri);
  }
  DIR *dir=project_root?opendir(project_root):NULL;struct dirent *entry;while(dir&&(entry=readdir(dir))){size_t n=strlen(entry->d_name);if(n<4||strcmp(entry->d_name+n-4,".dyn"))continue;char *path=dyn_path_join(project_root,entry->d_name);if(!path)continue;bool opened=false;for(size_t i=0;i<count;++i)if(!strcmp(lsp_file_path(documents[i].uri),path)){opened=true;break;}if(opened){free(path);continue;}FILE *file=fopen(path,"rb");if(!file){free(path);continue;}fseek(file,0,SEEK_END);long length=ftell(file);fseek(file,0,SEEK_SET);char *source=length>=0?malloc((size_t)length+1):NULL;if(!source||fread(source,1,(size_t)length,file)!=(size_t)length){free(source);fclose(file);free(path);continue;}source[length]=0;fclose(file);TSParser *parser=ts_parser_new();TSTree *tree=NULL;if(parser&&ts_parser_set_language(parser,tree_sitter_dyn()))tree=ts_parser_parse_string(parser,NULL,source,(uint32_t)length);char *uri=lsp_path_uri(path),*escaped=uri?json_escape(uri,strlen(uri)):NULL;LspDocument disk={.uri=uri,.text=source,.parser=parser,.tree=tree};if(tree&&escaped)lsp_identifier_edits(ts_tree_root_node(tree),&disk,word,word_length,escaped,replacement,body,capacity,&at,&comma);free(escaped);free(uri);if(tree)ts_tree_delete(tree);if(parser)ts_parser_delete(parser);free(source);free(path);}if(dir)closedir(dir);
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
                       const char *word, size_t word_length, const char *replacement,
                       const char *project_root) {
  size_t capacity = 1024u * 1024u; char *body = malloc(capacity); if (!body) return;
  size_t at = (size_t)snprintf(body, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"changes\":{", id); bool document_comma = false;
  for (size_t i = 0; i < count; ++i) if (documents[i].tree) {
    char *uri = json_escape(documents[i].uri, strlen(documents[i].uri)); if (!uri) continue;
    at += (size_t)snprintf(body + at, capacity - at, "%s\"%s\":[", document_comma ? "," : "", uri); bool edit_comma = false;
    lsp_rename_edits(ts_tree_root_node(documents[i].tree), &documents[i], word, word_length, replacement, body, capacity, &at, &edit_comma);
    at += (size_t)snprintf(body + at, capacity - at, "]"); document_comma = true; free(uri);
  }
  DIR *dir=project_root?opendir(project_root):NULL;struct dirent *entry;while(dir&&(entry=readdir(dir))){size_t n=strlen(entry->d_name);if(n<4||strcmp(entry->d_name+n-4,".dyn"))continue;char *path=dyn_path_join(project_root,entry->d_name);if(!path)continue;bool opened=false;for(size_t i=0;i<count;++i)if(!strcmp(lsp_file_path(documents[i].uri),path)){opened=true;break;}if(opened){free(path);continue;}FILE *file=fopen(path,"rb");if(!file){free(path);continue;}fseek(file,0,SEEK_END);long length=ftell(file);fseek(file,0,SEEK_SET);char *source=length>=0?malloc((size_t)length+1):NULL;if(!source||fread(source,1,(size_t)length,file)!=(size_t)length){free(source);fclose(file);free(path);continue;}source[length]=0;fclose(file);TSParser *parser=ts_parser_new();TSTree *tree=NULL;if(parser&&ts_parser_set_language(parser,tree_sitter_dyn()))tree=ts_parser_parse_string(parser,NULL,source,(uint32_t)length);char edits[65536];size_t edit_at=0;bool edit_comma=false;LspDocument disk={.text=source,.tree=tree};if(tree)lsp_rename_edits(ts_tree_root_node(tree),&disk,word,word_length,replacement,edits,sizeof(edits),&edit_at,&edit_comma);if(edit_comma){char *uri=lsp_path_uri(path),*escaped=uri?json_escape(uri,strlen(uri)):NULL;if(escaped)at+=(size_t)snprintf(body+at,capacity-at,"%s\"%s\":[%s]",document_comma?",":"",escaped,edits),document_comma=true;free(escaped);free(uri);}if(tree)ts_tree_delete(tree);if(parser)ts_parser_delete(parser);free(source);free(path);}if(dir)closedir(dir);
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
  while(p&&*p){const char *end=strchr(p,'\n');if(!end)end=p+strlen(p);const char *q=p;while(q<end&&isspace((unsigned char)*q))++q;const char *declaration=q;bool pub=(size_t)(end-q)>=4&&!memcmp(q,"pub ",4);if(pub)q+=4;if(!public_only||pub)for(size_t k=0;k<sizeof(kinds)/sizeof(kinds[0]);++k){size_t n=strlen(kinds[k]);if((size_t)(end-q)<n||memcmp(q,kinds[k],n))continue;const char *name=q+n,*name_end=name;while(name_end<end&&(isalnum((unsigned char)*name_end)||*name_end=='_'))++name_end;if(name_end>name&&!lsp_completion_has_label(body,*at,name,(size_t)(name_end-name))){int length=(int)(name_end-name);if(item_kinds[k]==3){char signature[512],snippet[512];lsp_completion_signature(declaration,signature,sizeof(signature));lsp_call_snippet(name,(size_t)length,declaration,snippet,sizeof(snippet));*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"label\":\"%.*s\",\"kind\":3,\"detail\":\"%s\",\"documentation\":{\"kind\":\"plaintext\",\"value\":\"%s\"},\"insertText\":\"%s\",\"insertTextFormat\":2,\"sortText\":\"2_%.*s\"}",*comma?",":"",length,name,signature,signature,snippet,length,name);}else *at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"label\":\"%.*s\",\"kind\":%u,\"detail\":\"%s\",\"sortText\":\"2_%.*s\"}",*comma?",":"",length,name,item_kinds[k],details[k],length,name);*comma=true;}break;}p=*end?end+1:end;}
}
static void lsp_completion(long id, LspDocument *documents, size_t count,
                           LspDocument *requested,size_t line,size_t character) {
  size_t capacity = 1024u * 1024u, at = 0; char *body = malloc(capacity); if (!body) return;
  at = (size_t)snprintf(body, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id); bool comma = false;
  char qualifier[128]={0},word_prefix[128]={0};bool qualified=false;
  bool import_path=false;char import_typed[1024]={0};
  if(requested&&requested->text){const char *p=requested->text;for(size_t row=0;row<line&&p;++row){p=strchr(p,'\n');if(p)++p;}if(p){const char *end=strchr(p,'\n');if(!end)end=p+strlen(p);const char *cursor=p+((size_t)(end-p)<character?(size_t)(end-p):character),*dot=cursor;while(dot>p&&(isalnum((unsigned char)dot[-1])||dot[-1]=='_'))--dot;if(dot>p&&dot[-1]=='.'){const char *q=dot-1,*start=q;while(start>p&&(isalnum((unsigned char)start[-1])||start[-1]=='_'))--start;size_t n=(size_t)(q-start);if(n&&n<sizeof(qualifier)){memcpy(qualifier,start,n);qualifier[n]=0;qualified=true;}}}}
  if(requested&&requested->text){const char *p=requested->text;for(size_t row=0;row<line&&p;++row){p=strchr(p,'\n');if(p)++p;}if(p){const char *end=strchr(p,'\n');if(!end)end=p+strlen(p);const char *cursor=p+(character>(size_t)(end-p)?(size_t)(end-p):character);const char *q=p;while(q<cursor&&isspace((unsigned char)*q))++q;if((size_t)(cursor-q)>=5&&!memcmp(q,"use \"",5)&&!memchr(q+5,'\"',(size_t)(cursor-(q+5)))){size_t n=(size_t)(cursor-(q+5));if(n<sizeof(import_typed)){memcpy(import_typed,q+5,n);import_typed[n]=0;import_path=true;}}}}
  if(requested&&requested->text){const char *p=requested->text;for(size_t row=0;row<line&&p;++row){p=strchr(p,'\n');if(p)++p;}if(p){const char *end=strchr(p,'\n');if(!end)end=p+strlen(p);const char *cursor=p+(character>(size_t)(end-p)?(size_t)(end-p):character),*start=cursor;while(start>p&&(isalnum((unsigned char)start[-1])||start[-1]=='_'))--start;size_t n=(size_t)(cursor-start);if(n<sizeof(word_prefix)){memcpy(word_prefix,start,n);word_prefix[n]=0;}}}
  if(import_path)lsp_completion_imports(requested,import_typed,body,capacity,&at,&comma);
  else if(qualified){LspImport imports[32];size_t n=lsp_imports(requested,imports,32);bool imported=false;for(size_t i=0;i<n;++i)if(!strcmp(imports[i].alias,qualifier)){char *target=lsp_resolve_import(requested,imports[i].path);DynSources sources={0};if(target&&!dyn_sources_load(target,&sources))for(size_t s=0;s<sources.count;++s)lsp_completion_decls(sources.items[s].text,true,body,capacity,&at,&comma);dyn_sources_free(&sources);free(target);imported=true;break;}if(!imported){lsp_completion_expression_fields(documents,count,requested,line,character,body,capacity,&at,&comma);if(!comma)lsp_completion_enum_variants(documents,count,requested,qualifier,false,body,capacity,&at,&comma);if(!comma)lsp_completion_fields(documents,count,qualifier,body,capacity,&at,&comma);}}
  else {if(requested){lsp_completion_expression_fields(documents,count,requested,line,character,body,capacity,&at,&comma);lsp_completion_struct_fields(documents,count,requested,line,character,body,capacity,&at,&comma);lsp_completion_expected_enum(documents,count,requested,line,character,body,capacity,&at,&comma);lsp_completion_locals(documents,count,requested,line,character,body,capacity,&at,&comma);}char *requested_root=requested?lsp_project_root(requested->uri):NULL;for(size_t d=0;d<count;++d){char *candidate_root=lsp_project_root(documents[d].uri);bool same=!requested_root||(candidate_root&&!strcmp(requested_root,candidate_root));free(candidate_root);if(same)lsp_completion_decls(documents[d].text,false,body,capacity,&at,&comma);}free(requested_root);if(requested)lsp_completion_auto_imports(requested,word_prefix,body,capacity,&at,&comma);
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
      {"#link","#link(\\\"library\\\")","#link(\\\"${1:library}\\\")"},
    };for(size_t i=0;i<sizeof(builtins)/sizeof(builtins[0]);++i)at+=(size_t)snprintf(body+at,capacity-at,"%s{\"label\":\"%s\",\"kind\":3,\"detail\":\"%s\",\"documentation\":{\"kind\":\"plaintext\",\"value\":\"%s\"},\"insertText\":\"%s\",\"insertTextFormat\":2}",comma?",":"",builtins[i].label,builtins[i].signature,builtins[i].signature,builtins[i].snippet),comma=true;
    const char *labels[]={"fn","main","if","for","case","struct","enum","use","defer"};
    const char *snippets[]={"fn ${1:name}(${2}) {\\n\\t$0\\n}","fn main() {\\n\\t$0\\n}","if ${1:condition} {\\n\\t$0\\n}","for ${1:item} in ${2:items} {\\n\\t$0\\n}","case ${1:value} {\\n\\t${2:_ => { $0 }}\\n}","struct ${1:Name} {\\n\\t${2:field}: ${3:type},\\n}","enum ${1:Name} {\\n\\t${2:Value},\\n}","use \\\"${1:std/package}\\\"$0","defer {\\n\\t$0\\n}"};
    for(size_t i=0;i<sizeof(labels)/sizeof(labels[0]);++i)if(!lsp_completion_has_label(body,at,labels[i],strlen(labels[i])))at+=(size_t)snprintf(body+at,capacity-at,"%s{\"label\":\"%s\",\"kind\":15,\"detail\":\"Dyn snippet\",\"insertText\":\"%s\",\"insertTextFormat\":2,\"filterText\":\"%s\",\"sortText\":\"5_%s\"}",comma?",":"",labels[i],snippets[i],labels[i],labels[i]),comma=true;}
  snprintf(body+at,capacity-at,"]}"); lsp_send(body); free(body);
}
static void lsp_document_symbols(long id,const LspDocument *document) {
  size_t capacity=1024u*1024u,at=0;char *body=malloc(capacity);if(!body)return;at=(size_t)snprintf(body,capacity,"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[",id);bool comma=false;const char *p=document->text;size_t line=0;
  const char *kinds[]={"fn ","extern fn ","struct ","enum ","type ","const "};const unsigned symbol_kinds[]={12,12,23,10,5,14};
  while(p&&*p){const char *end=strchr(p,'\n');if(!end)end=p+strlen(p);const char *q=p;while(q<end&&isspace((unsigned char)*q))++q;if((size_t)(end-q)>=4&&!memcmp(q,"pub ",4))q+=4;for(size_t k=0;k<sizeof(kinds)/sizeof(kinds[0]);++k){size_t n=strlen(kinds[k]);if((size_t)(end-q)<n||memcmp(q,kinds[k],n))continue;const char *name=q+n,*name_end=name;while(name_end<end&&(isalnum((unsigned char)*name_end)||*name_end=='_'))++name_end;if(name_end>name)at+=(size_t)snprintf(body+at,capacity-at,"%s{\"name\":\"%.*s\",\"kind\":%u,\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}},\"selectionRange\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}}}",comma?",":"",(int)(name_end-name),name,symbol_kinds[k],line,(size_t)(q-p),line,(size_t)(end-p),line,(size_t)(name-p),line,(size_t)(name_end-p)),comma=true;break;}p=*end?end+1:end;++line;}snprintf(body+at,capacity-at,"]}");lsp_send(body);free(body);
}
static void lsp_highlight_nodes(TSNode node,const LspDocument *document,const char *word,
    size_t length,char *body,size_t capacity,size_t *at,bool *comma) {
  if(!strcmp(ts_node_type(node),"identifier")&&ts_node_end_byte(node)-ts_node_start_byte(node)==length&&!memcmp(document->text+ts_node_start_byte(node),word,length)){TSPoint a=ts_node_start_point(node),b=ts_node_end_point(node);*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{\"line\":%u,\"character\":%u}},\"kind\":2}",*comma?",":"",a.row,a.column,b.row,b.column);*comma=true;}
  for(uint32_t i=0;i<ts_node_named_child_count(node);++i)lsp_highlight_nodes(ts_node_named_child(node,i),document,word,length,body,capacity,at,comma);
}
static void lsp_document_highlight(long id,const LspDocument *document,size_t line,size_t character) {
  const char *word=NULL;size_t length=0;char body[65536];size_t at=(size_t)snprintf(body,sizeof(body),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[",id);bool comma=false;if(identifier_at(document->text,line,character,&word,&length)&&document->tree)lsp_highlight_nodes(ts_tree_root_node(document->tree),document,word,length,body,sizeof(body),&at,&comma);snprintf(body+at,sizeof(body)-at,"]}");lsp_send(body);
}
static bool lsp_foldable(const char *kind) {
  return !strcmp(kind,"fn")||!strcmp(kind,"extern_fn")||!strcmp(kind,"struct")||!strcmp(kind,"enum")||!strcmp(kind,"block")||!strcmp(kind,"case")||!strcmp(kind,"if")||!strcmp(kind,"for")||!strcmp(kind,"defer");
}
static void lsp_folding_nodes(TSNode node,char *body,size_t capacity,size_t *at,bool *comma) {
  TSPoint a=ts_node_start_point(node),b=ts_node_end_point(node);if(b.row>a.row&&lsp_foldable(ts_node_type(node))){*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"startLine\":%u,\"startCharacter\":%u,\"endLine\":%u,\"endCharacter\":%u,\"kind\":\"region\"}",*comma?",":"",a.row,a.column,b.row,b.column);*comma=true;}
  for(uint32_t i=0;i<ts_node_named_child_count(node);++i)lsp_folding_nodes(ts_node_named_child(node,i),body,capacity,at,comma);
}
static void lsp_folding_ranges(long id,const LspDocument *document) {
  char body[65536];size_t at=(size_t)snprintf(body,sizeof(body),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[",id);bool comma=false;if(document->tree)lsp_folding_nodes(ts_tree_root_node(document->tree),body,sizeof(body),&at,&comma);snprintf(body+at,sizeof(body)-at,"]}");lsp_send(body);
}
static void lsp_selection_node(TSNode node,char *body,size_t capacity,size_t *at) {
  TSPoint a=ts_node_start_point(node),b=ts_node_end_point(node);*at+=(size_t)snprintf(body+*at,capacity-*at,"{\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{\"line\":%u,\"character\":%u}}",a.row,a.column,b.row,b.column);TSNode parent=ts_node_parent(node);while(!ts_node_is_null(parent)&&!ts_node_is_named(parent))parent=ts_node_parent(parent);if(!ts_node_is_null(parent)){*at+=(size_t)snprintf(body+*at,capacity-*at,",\"parent\":");lsp_selection_node(parent,body,capacity,at);}*at+=(size_t)snprintf(body+*at,capacity-*at,"}");
}
static void lsp_selection_range(long id,const LspDocument *document,size_t line,size_t character) {
  char body[65536];size_t at=(size_t)snprintf(body,sizeof(body),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[",id);if(document->tree){TSPoint point={(uint32_t)line,(uint32_t)character};TSNode node=ts_node_named_descendant_for_point_range(ts_tree_root_node(document->tree),point,point);if(!ts_node_is_null(node))lsp_selection_node(node,body,sizeof(body),&at);}snprintf(body+at,sizeof(body)-at,"]}");lsp_send(body);
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
static bool lsp_symbol_matches(const char *name,size_t length,const char *query) {
  if(!query||!*query)return true;
  size_t q=strlen(query);if(q>length)return false;for(size_t i=0;i+q<=length;++i)if(!strncasecmp(name+i,query,q))return true;return false;
}
static void lsp_workspace_symbol_text(const char *text,const char *uri,const char *query,
    char *body,size_t capacity,size_t *at,bool *comma) {
  const char *p=text;size_t line=0;const char *kinds[]={"fn ","extern fn ","struct ","enum ","type ","const "};const unsigned symbol_kinds[]={12,12,23,10,5,14};char *escaped=json_escape(uri,strlen(uri));
  while(escaped&&p&&*p){const char *end=strchr(p,'\n');if(!end)end=p+strlen(p);const char *q=p;while(q<end&&isspace((unsigned char)*q))++q;if((size_t)(end-q)>=4&&!memcmp(q,"pub ",4))q+=4;for(size_t k=0;k<sizeof(kinds)/sizeof(kinds[0]);++k){size_t n=strlen(kinds[k]);if((size_t)(end-q)<n||memcmp(q,kinds[k],n))continue;const char *name=q+n,*name_end=name;while(name_end<end&&(isalnum((unsigned char)*name_end)||*name_end=='_'))++name_end;if(name_end>name&&lsp_symbol_matches(name,(size_t)(name_end-name),query))*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"name\":\"%.*s\",\"kind\":%u,\"location\":{\"uri\":\"%s\",\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}}}}",*comma?",":"",(int)(name_end-name),name,symbol_kinds[k],escaped,line,(size_t)(name-p),line,(size_t)(name_end-p)),*comma=true;break;}p=*end?end+1:end;++line;}free(escaped);
}
static void lsp_workspace_symbol_directory(const char *directory,const char *query,
    LspDocument *documents,size_t count,char *body,size_t capacity,size_t *at,bool *comma,unsigned depth) {
  if(depth>16||*at+4096>=capacity)return;
  DIR *dir=opendir(directory);if(!dir)return;struct dirent *entry;
  while((entry=readdir(dir))){if(entry->d_name[0]=='.'||!strcmp(entry->d_name,"build"))continue;char *path=dyn_path_join(directory,entry->d_name);if(!path)continue;if(dyn_path_is_directory(path)){lsp_workspace_symbol_directory(path,query,documents,count,body,capacity,at,comma,depth+1);free(path);continue;}size_t n=strlen(path);if(n<4||strcmp(path+n-4,".dyn")){free(path);continue;}const char *text=NULL;for(size_t i=0;i<count;++i)if(!strcmp(lsp_file_path(documents[i].uri),path)){text=documents[i].text;break;}char *owned=NULL;if(!text){FILE *file=fopen(path,"rb");if(file){if(!fseek(file,0,SEEK_END)){long length=ftell(file);if(length>=0&&!fseek(file,0,SEEK_SET)){owned=malloc((size_t)length+1);if(owned&&fread(owned,1,(size_t)length,file)==(size_t)length)owned[length]=0;else{free(owned);owned=NULL;}}}fclose(file);text=owned;}}if(text){char *uri=lsp_path_uri(path);if(uri){lsp_workspace_symbol_text(text,uri,query,body,capacity,at,comma);free(uri);}}free(owned);free(path);if(*at+4096>=capacity)break;}closedir(dir);
}
static void lsp_workspace_symbols(long id,LspDocument *documents,size_t count,const char *workspace_root,const char *query) {
  size_t capacity=1024u*1024u,at=0;char *body=malloc(capacity);if(!body)return;at=(size_t)snprintf(body,capacity,"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[",id);bool comma=false;const char *kinds[]={"fn ","extern fn ","struct ","enum ","type ","const "};const unsigned symbol_kinds[]={12,12,23,10,5,14};
  (void)kinds;(void)symbol_kinds;if(workspace_root)lsp_workspace_symbol_directory(workspace_root,query,documents,count,body,capacity,&at,&comma,0);else for(size_t d=0;d<count;++d)lsp_workspace_symbol_text(documents[d].text,documents[d].uri,query,body,capacity,&at,&comma);snprintf(body+at,capacity-at,"]}");lsp_send(body);free(body);
}
static bool lsp_find_public_import(const char *directory,const char *import_path,
    const char *symbol,size_t symbol_length,char *out,size_t capacity,unsigned depth) {
  if(depth>16)return false;
  DIR *dir=opendir(directory);if(!dir)return false;struct dirent *entry;bool found=false;
  while(!found&&(entry=readdir(dir))){if(entry->d_name[0]=='.')continue;char *path=dyn_path_join(directory,entry->d_name);if(!path)continue;
    if(dyn_path_is_directory(path)){char child[1024];int n=snprintf(child,sizeof(child),"%s/%s",import_path,entry->d_name);if(n>0&&(size_t)n<sizeof(child))found=lsp_find_public_import(path,child,symbol,symbol_length,out,capacity,depth+1);free(path);continue;}
    size_t n=strlen(path);if(n<4||strcmp(path+n-4,".dyn")){free(path);continue;}FILE *file=fopen(path,"rb");free(path);if(!file)continue;char line[4096];
    while(!found&&fgets(line,sizeof(line),file)){char *q=line;while(isspace((unsigned char)*q))++q;if(strncmp(q,"pub ",4))continue;q+=4;const char *kinds[]={"fn ","struct ","enum ","type ","const "};for(size_t k=0;k<sizeof(kinds)/sizeof(kinds[0]);++k){size_t kind_length=strlen(kinds[k]);if(strncmp(q,kinds[k],kind_length))continue;const char *name=q+kind_length,*end=name;while(isalnum((unsigned char)*end)||*end=='_')++end;if((size_t)(end-name)==symbol_length&&!memcmp(name,symbol,symbol_length)){snprintf(out,capacity,"%s",import_path);found=true;}break;}}
    fclose(file);
  }closedir(dir);return found;
}
static bool lsp_missing_import(const LspDocument *document,const char *symbol,size_t length,
    char *out,size_t capacity) {
  char *std_package=lsp_resolve_import(document,"std/io"),*std_root=std_package?lsp_directory(std_package):NULL;
  char *vendor_package=lsp_resolve_import(document,"vendor/sqlite"),*vendor_root=vendor_package?lsp_directory(vendor_package):NULL;bool found=false;
  if(std_root)found=lsp_find_public_import(std_root,"std",symbol,length,out,capacity,0);
  if(!found&&vendor_root)found=lsp_find_public_import(vendor_root,"vendor",symbol,length,out,capacity,0);
  free(std_package);free(std_root);free(vendor_package);free(vendor_root);return found;
}
static bool lsp_fill_struct_fields(const LspDocument *document,size_t line,size_t character,
    char *text,size_t capacity,size_t *edit_column) {
  const char *row=document->text;for(size_t i=0;i<line&&row;++i){row=strchr(row,'\n');if(row)++row;}if(!row)return false;const char *row_end=strchr(row,'\n');if(!row_end)row_end=row+strlen(row);const char *cursor=row+(character>(size_t)(row_end-row)?(size_t)(row_end-row):character),*open=cursor;while(open>row&&open[-1]!='{')--open;if(open<=row||open[-1]!='{')return false;--open;const char *close=memchr(open,'}',(size_t)(row_end-open));if(!close)return false;const char *name_end=open,*name=name_end;while(name>row&&(isalnum((unsigned char)name[-1])||name[-1]=='_'))--name;if(name==name_end)return false;
  char needle[160];int needle_length=snprintf(needle,sizeof(needle),"struct %.*s",(int)(name_end-name),name);if(needle_length<=0||(size_t)needle_length>=sizeof(needle))return false;const char *decl=strstr(document->text,needle),*decl_open=decl?strchr(decl,'{'):NULL,*decl_close=decl_open?strchr(decl_open,'}'):NULL;if(!decl_open||!decl_close)return false;
  size_t at=0;for(const char *p=decl_open+1;p<decl_close;){while(p<decl_close&&(isspace((unsigned char)*p)||*p==','))++p;const char *field=p;while(p<decl_close&&(isalnum((unsigned char)*p)||*p=='_'))++p;if(field==p){++p;continue;}const char *colon=p;while(colon<decl_close&&isspace((unsigned char)*colon))++colon;if(colon>=decl_close||*colon!=':'){p=colon;continue;}const char *type=colon+1;while(type<decl_close&&isspace((unsigned char)*type))++type;const char *type_end=type;while(type_end<decl_close&&*type_end!=','&&*type_end!='\n'&&*type_end!='}')++type_end;while(type_end>type&&isspace((unsigned char)type_end[-1]))--type_end;
    bool present=false;for(const char *q=open+1;q<close;){while(q<close&&!(isalnum((unsigned char)*q)||*q=='_'))++q;const char *id=q;while(q<close&&(isalnum((unsigned char)*q)||*q=='_'))++q;const char *after=q;while(after<close&&isspace((unsigned char)*after))++after;if((size_t)(q-id)==(size_t)(p-field)&&!memcmp(id,field,(size_t)(p-field))&&after<close&&*after==':'){present=true;break;}}
    if(!present){const char *value="0";if((size_t)(type_end-type)==4&&!memcmp(type,"bool",4))value="false";else if((size_t)(type_end-type)>=2&&type[0]=='['&&type[1]==']')value="\"\"";else if(type_end>type&&*type=='[')value="{}";else if(type_end>type&&*type=='*')value="nil";int n=snprintf(text+at,capacity-at,"%s%.*s: %s",at?", ":(close>open+1?", ":""),(int)(p-field),field,value);if(n<0||(size_t)n>=capacity-at)return false;at+=(size_t)n;}
    p=type_end;if(p<decl_close)++p;
  }
  *edit_column=(size_t)(close-row);return at>0;
}
static void lsp_code_actions(long id,const LspDocument *document,const char *body_text) {
  size_t line=0,character=0,end_line=0,end_character=0;(void)json_range_positions(body_text,&line,&character,&end_line,&end_character);const char *row=document->text;for(size_t i=0;i<line&&row;++i){row=strchr(row,'\n');if(row)++row;}const char *q=row;while(q&&isspace((unsigned char)*q)&&*q!='\n')++q;bool unused=strstr(body_text,"\"code\":\"unused-use\"")!=NULL,unknown=strstr(body_text,"unknown name")!=NULL||strstr(body_text,"unknown function")!=NULL;bool is_use=q&&!memcmp(q,"use ",4);char *uri=json_escape(document->uri,strlen(document->uri));char response[8192];
  const char *word=NULL;size_t word_length=0;char import_path[1024]={0},fields[2048]={0};size_t insert_column=0;bool can_import=unknown&&identifier_at(document->text,line,character,&word,&word_length)&&lsp_missing_import(document,word,word_length,import_path,sizeof(import_path));bool can_fill=lsp_fill_struct_fields(document,line,character,fields,sizeof(fields),&insert_column);
  if(unused&&is_use&&uri)snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[{\"title\":\"Remove unused use\",\"kind\":\"quickfix\",\"isPreferred\":true,\"diagnostics\":[{\"code\":\"unused-use\"}],\"edit\":{\"changes\":{\"%s\":[{\"range\":{\"start\":{\"line\":%zu,\"character\":0},\"end\":{\"line\":%zu,\"character\":0}},\"newText\":\"\"}]}}}]}",id,uri,line,line+1);
  else if(can_import&&uri){const char *slash=strrchr(import_path,'/'),*alias=slash?slash+1:import_path;snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[{\"title\":\"Import %.*s from %s\",\"kind\":\"quickfix\",\"isPreferred\":true,\"edit\":{\"changes\":{\"%s\":[{\"range\":{\"start\":{\"line\":0,\"character\":0},\"end\":{\"line\":0,\"character\":0}},\"newText\":\"use \\\"%s\\\"\\n\"},{\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}},\"newText\":\"%s.%.*s\"}]}}}]}",id,(int)word_length,word,import_path,uri,import_path,line,character,line,character+word_length,alias,(int)word_length,word);}
  else if(can_fill&&uri){char *escaped_fields=json_escape(fields,strlen(fields));if(escaped_fields){snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[{\"title\":\"Fill missing struct fields\",\"kind\":\"refactor.rewrite\",\"edit\":{\"changes\":{\"%s\":[{\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}},\"newText\":\"%s\"}]}}}]}",id,uri,line,insert_column,line,insert_column,escaped_fields);free(escaped_fields);}else snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}",id);}
  else snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}",id);
  lsp_send(response);free(uri);
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
static LspSemantic lsp_semantic_build_related(LspDocument *documents,size_t count,
    LspDocument *requested) {
  LspDocument related[LSP_DOCUMENT_LIMIT];size_t related_count=0;char *root=lsp_project_root(requested->uri);for(size_t i=0;i<count&&related_count<LSP_DOCUMENT_LIMIT;++i){char *candidate=lsp_project_root(documents[i].uri);bool same=root&&candidate&&!strcmp(root,candidate);free(candidate);if(same)related[related_count++]=documents[i];}free(root);return lsp_semantic_build(related,related_count);
}
static LspSemantic lsp_semantic_project(LspDocument *documents,size_t count,
    LspDocument *requested,const char *replacement) {
  LspSemantic semantic={0};char *root=lsp_project_root(requested->uri);if(!root)return semantic;
  if(access(root,F_OK)){free(root);return semantic;}
  DynSources roots={0},project={0};DynSource override_items[LSP_DOCUMENT_LIMIT];
  for(size_t i=0;i<count;++i)override_items[i]=(DynSource){.path=(char *)lsp_file_path(documents[i].uri),.text=(char *)(&documents[i]==requested?replacement:documents[i].text),.length=strlen(&documents[i]==requested?replacement:documents[i].text)};
  DynSources overrides={override_items,count};
  int loaded=dyn_sources_load(root,&roots);if(!loaded){lsp_overlay_sources(&roots,documents,count);for(size_t i=0;i<roots.count;++i)if(!strcmp(roots.items[i].path,lsp_file_path(requested->uri))){free(roots.items[i].text);roots.items[i].text=strdup(replacement);roots.items[i].length=strlen(replacement);}
    loaded=dyn_module_load_project_overlay(root,&roots,&overrides,&project);}
  if(!loaded&&dyn_sources_merge(&project,"<lsp-completion>",&semantic.source)==0){unsigned errors=0;dyn_diagnostic_sink(lsp_ignore_diagnostic,NULL);bool parsed=dyn_ast_parse_source_owner(&semantic.source,&semantic.ast,&errors,NULL,true);if(parsed)(void)dyn_sema_function(&semantic.ast,&semantic.source,&errors);dyn_diagnostic_sink(NULL,NULL);semantic.ok=parsed;}
  dyn_sources_free(&project);dyn_sources_free(&roots);free(root);return semantic;
}
static void lsp_semantic_free(LspSemantic *semantic) {
  dyn_ast_function_free(&semantic->ast); dyn_source_free(&semantic->source);
}
static void lsp_completion_type_fields(LspSemantic *semantic,DynType type,char *body,
    size_t capacity,size_t *at,bool *comma) {
  if(dyn_type_is_pointer(type)){uint32_t p=type-DYN_TYPE_POINTER_BASE;if(p<semantic->ast.pointer_count)type=semantic->ast.pointers[p].pointee;}
  if(!dyn_type_is_struct(type))return;
  uint32_t sid=type-DYN_TYPE_STRUCT_BASE;if(sid>=semantic->ast.struct_count)return;DynAstStruct *s=&semantic->ast.structs[sid];
  for(uint32_t i=0;i<s->field_count;++i){DynAstField *field=&semantic->ast.fields[s->field_start+i];char field_type[128];dyn_type_format(&semantic->ast,field->type,&semantic->source,field_type,sizeof(field_type));*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"label\":\"%.*s\",\"kind\":5,\"detail\":\"%s\"}",*comma?",":"",(int)(field->name.end_byte-field->name.start_byte),semantic->source.text+field->name.start_byte,field_type);*comma=true;}
}
static void lsp_completion_fields(LspDocument *documents,size_t count,const char *name,char *body,size_t capacity,size_t *at,bool *comma) {
  LspSemantic semantic=lsp_semantic_build(documents,count);DynType type=DYN_TYPE_ERROR;for(size_t i=semantic.ast.local_count;i>0;--i){DynAstLocal *local=&semantic.ast.locals[i-1];size_t n=local->name.end_byte-local->name.start_byte;if(strlen(name)==n&&!memcmp(semantic.source.text+local->name.start_byte,name,n)){type=local->type;break;}}lsp_completion_type_fields(&semantic,type,body,capacity,at,comma);lsp_semantic_free(&semantic);
}
static void lsp_completion_expression_fields(LspDocument *documents,size_t count,
    LspDocument *requested,size_t line,size_t character,char *body,size_t capacity,
    size_t *at,bool *comma) {
  const char *row=requested->text;for(size_t i=0;i<line&&row;++i){row=strchr(row,'\n');if(row)++row;}if(!row)return;const char *row_end=strchr(row,'\n');if(!row_end)row_end=row+strlen(row);const char *cursor=row+(character>(size_t)(row_end-row)?(size_t)(row_end-row):character),*start=cursor;while(start>row&&(isalnum((unsigned char)start[-1])||start[-1]=='_'))--start;if(start<=row||start[-1]!='.')return;
  const char marker[]="__dyn_completion_field";const char *end=cursor;while(end<row_end&&(isalnum((unsigned char)*end)||*end=='_'))++end;size_t before=(size_t)(start-requested->text),after=strlen(end);char *patched=malloc(before+sizeof(marker)-1+after+1);if(!patched)return;memcpy(patched,requested->text,before);memcpy(patched+before,marker,sizeof(marker)-1);memcpy(patched+before+sizeof(marker)-1,end,after+1);
  const char *first=row;while(first<cursor&&isspace((unsigned char)*first))++first;bool contextual=((size_t)(cursor-first)>=3&&!memcmp(first,"if ",3))||((size_t)(cursor-first)>=4&&!memcmp(first,"for ",4))||((size_t)(cursor-first)>=5&&!memcmp(first,"case ",5));
  if(contextual&&!memchr(cursor,'{',(size_t)(row_end-cursor))){const char *dot=start-1,*expression=dot;while(expression>first&&(isalnum((unsigned char)expression[-1])||expression[-1]=='_'))--expression;size_t prefix=(size_t)(first-requested->text),value=(size_t)(start-expression),suffix=strlen(row_end);char *repaired=malloc(prefix+4+value+sizeof(marker)-1+suffix+1);if(!repaired){free(patched);return;}memcpy(repaired,requested->text,prefix);memcpy(repaired+prefix,"_ = ",4);memcpy(repaired+prefix+4,expression,value);memcpy(repaired+prefix+4+value,marker,sizeof(marker)-1);memcpy(repaired+prefix+4+value+sizeof(marker)-1,row_end,suffix+1);free(patched);patched=repaired;}
  bool standalone=!contextual&&first<cursor&&(isalpha((unsigned char)*first)||*first=='_');for(const char *p=first;p<start-1&&standalone;++p)if(*p=='='||*p=='('||*p=='{'||isspace((unsigned char)*p))standalone=false;
  if(standalone){size_t insert=(size_t)(first-requested->text),length=strlen(patched);char *wrapped=malloc(length+5);if(!wrapped){free(patched);return;}memcpy(wrapped,patched,insert);memcpy(wrapped+insert,"_ = ",4);memcpy(wrapped+insert+4,patched+insert,length-insert+1);free(patched);patched=wrapped;}
  LspSemantic semantic=lsp_semantic_project(documents,count,requested,patched);free(patched);if(semantic.ok)for(size_t i=semantic.ast.expression_count;i>0;--i){DynAstExpr *e=&semantic.ast.expressions[i-1];size_t n=e->span.end_byte-e->span.start_byte;if(e->kind==DYN_EXPR_FIELD&&n==sizeof(marker)-1&&!memcmp(semantic.source.text+e->span.start_byte,marker,n)&&e->left<semantic.ast.expression_count){lsp_completion_type_fields(&semantic,semantic.ast.expressions[e->left].type,body,capacity,at,comma);break;}}lsp_semantic_free(&semantic);
}
static void lsp_completion_locals(LspDocument *documents,size_t count,
    LspDocument *requested,size_t line,size_t character,char *body,size_t capacity,
    size_t *at,bool *comma) {
  const char *row=requested->text;for(size_t i=0;i<line&&row;++i){row=strchr(row,'\n');if(row)++row;}if(!row)return;const char *row_end=strchr(row,'\n');if(!row_end)row_end=row+strlen(row);const char *cursor=row+(character>(size_t)(row_end-row)?(size_t)(row_end-row):character),*start=cursor,*end=cursor;while(start>row&&(isalnum((unsigned char)start[-1])||start[-1]=='_'))--start;while(end<row_end&&(isalnum((unsigned char)*end)||*end=='_'))++end;
  const char marker[]="__dyn_completion_local";size_t before=(size_t)(start-requested->text),after=strlen(end);char *patched=malloc(before+sizeof(marker)-1+after+1);if(!patched)return;memcpy(patched,requested->text,before);memcpy(patched+before,marker,sizeof(marker)-1);memcpy(patched+before+sizeof(marker)-1,end,after+1);
  const char *first=row;while(first<cursor&&isspace((unsigned char)*first))++first;bool contextual=((size_t)(cursor-first)>=3&&!memcmp(first,"if ",3))||((size_t)(cursor-first)>=4&&!memcmp(first,"for ",4))||((size_t)(cursor-first)>=5&&!memcmp(first,"case ",5));
  if(contextual&&!memchr(cursor,'{',(size_t)(row_end-cursor))){size_t prefix=(size_t)(first-requested->text),suffix=strlen(row_end);char *repaired=malloc(prefix+4+sizeof(marker)-1+suffix+1);if(!repaired){free(patched);return;}memcpy(repaired,requested->text,prefix);memcpy(repaired+prefix,"_ = ",4);memcpy(repaired+prefix+4,marker,sizeof(marker)-1);memcpy(repaired+prefix+4+sizeof(marker)-1,row_end,suffix+1);free(patched);patched=repaired;}
  else if(first==start&&end==row_end){size_t insert=(size_t)(first-requested->text),length=strlen(patched);char *repaired=malloc(length+5);if(!repaired){free(patched);return;}memcpy(repaired,patched,insert);memcpy(repaired+insert,"_ = ",4);memcpy(repaired+insert+4,patched+insert,length-insert+1);free(patched);patched=repaired;}
  TSParser *scope_parser=ts_parser_new();TSTree *scope_tree=NULL;if(scope_parser&&ts_parser_set_language(scope_parser,tree_sitter_dyn()))scope_tree=ts_parser_parse_string(scope_parser,NULL,patched,(uint32_t)strlen(patched));
  LspSemantic semantic=lsp_semantic_project(documents,count,requested,patched);if(!semantic.ok){if(scope_tree)ts_tree_delete(scope_tree);if(scope_parser)ts_parser_delete(scope_parser);free(patched);lsp_semantic_free(&semantic);return;}const char *position=strstr(semantic.source.text,marker),*scope_position=strstr(patched,marker);if(!position||!scope_position){if(scope_tree)ts_tree_delete(scope_tree);if(scope_parser)ts_parser_delete(scope_parser);free(patched);lsp_semantic_free(&semantic);return;}uint32_t offset=(uint32_t)(position-semantic.source.text),owner=UINT32_MAX;
  for(uint32_t i=0;i<semantic.ast.function_count;++i){DynAstFn *fn=&semantic.ast.functions[i];if(offset>=fn->span.start_byte&&offset<=fn->span.end_byte){owner=i;break;}}
  uint32_t document_offset=(uint32_t)(scope_position-patched);
  if(owner!=UINT32_MAX)for(size_t i=0;i<semantic.ast.local_count;++i){DynAstLocal *local=&semantic.ast.locals[i];if(local->owner_function!=owner||local->name.start_byte>=offset)continue;size_t length=local->name.end_byte-local->name.start_byte;if(!length)continue;const char *name=semantic.source.text+local->name.start_byte;bool visible=false;if(scope_tree){TSNode root=ts_tree_root_node(scope_tree);TSNode stack[256];uint32_t indices[256]={0};size_t depth=1;stack[0]=root;while(depth&&!visible){TSNode node=stack[depth-1];uint32_t child_count=ts_node_named_child_count(node);if(indices[depth-1]<child_count&&depth<256){TSNode child=ts_node_named_child(node,indices[depth-1]++);stack[depth]=child;indices[depth++]=0;continue;}const char *kind=ts_node_type(node);if(!strcmp(kind,"identifier")&&ts_node_end_byte(node)-ts_node_start_byte(node)==length&&!memcmp(patched+ts_node_start_byte(node),name,length)&&ts_node_start_byte(node)<document_offset){TSNode parent=ts_node_parent(node);const char *parent_kind=ts_node_type(parent);bool declaration=(!strcmp(parent_kind,"variable")||!strcmp(parent_kind,"const_variable"))&&ts_node_start_byte(ts_node_named_child(parent,0))==ts_node_start_byte(node);declaration=declaration||!strcmp(parent_kind,"fn_param")||!strcmp(parent_kind,"variadic_param");if(!strcmp(parent_kind,"for_condition")&&ts_node_named_child_count(parent)>1&&ts_node_start_byte(ts_node_named_child(parent,0))==ts_node_start_byte(node))declaration=true;if(!strcmp(parent_kind,"case_arm")||!strcmp(parent_kind,"type_pattern"))declaration=true;if(declaration){TSNode scope=parent;while(!ts_node_is_null(scope)&&strcmp(ts_node_type(scope),"block")&&strcmp(ts_node_type(scope),"fn")&&strcmp(ts_node_type(scope),"for_")&&strcmp(ts_node_type(scope),"case_arm"))scope=ts_node_parent(scope);if(!ts_node_is_null(scope)&&document_offset>=ts_node_start_byte(scope)&&document_offset<=ts_node_end_byte(scope))visible=true;}}--depth;}}
    if(!visible)continue;
    char type[128];dyn_type_format(&semantic.ast,local->type,&semantic.source,type,sizeof(type));if(!lsp_completion_has_label(body,*at,name,length)){*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"label\":\"%.*s\",\"kind\":6,\"detail\":\"%s\",\"sortText\":\"0_%.*s\"}",*comma?",":"",(int)length,name,type,(int)length,name);*comma=true;}}
  if(scope_tree)ts_tree_delete(scope_tree);
  if(scope_parser)ts_parser_delete(scope_parser);
  free(patched);lsp_semantic_free(&semantic);
}
static void lsp_completion_struct_fields(LspDocument *documents,size_t count,
    LspDocument *requested,size_t line,size_t character,char *body,size_t capacity,
    size_t *at,bool *comma) {
  const char *row=requested->text;for(size_t i=0;i<line&&row;++i){row=strchr(row,'\n');if(row)++row;}if(!row)return;const char *row_end=strchr(row,'\n');if(!row_end)row_end=row+strlen(row);const char *cursor=row+(character>(size_t)(row_end-row)?(size_t)(row_end-row):character),*brace=cursor;while(brace>requested->text&&brace[-1]!='{'&&brace[-1]!='}'&&brace[-1]!='\n')--brace;if(brace<=requested->text+1||brace[-1]!='{')return;const char *type_end=brace-2;while(type_end>requested->text&&isspace((unsigned char)*type_end))--type_end;if(!(isalnum((unsigned char)*type_end)||*type_end=='.'||*type_end=='_'))return;
  const char *start=cursor,*end=cursor;while(start>brace&&(isalnum((unsigned char)start[-1])||start[-1]=='_'))--start;while(end<row_end&&(isalnum((unsigned char)*end)||*end=='_'))++end;const char marker[]="__dyn_completion_member";size_t before=(size_t)(start-requested->text),after=strlen(end);char *patched=malloc(before+sizeof(marker)-1+3+after+1);if(!patched)return;memcpy(patched,requested->text,before);memcpy(patched+before,marker,sizeof(marker)-1);memcpy(patched+before+sizeof(marker)-1,": 0",3);memcpy(patched+before+sizeof(marker)-1+3,end,after+1);
  LspSemantic semantic=lsp_semantic_project(documents,count,requested,patched);free(patched);if(semantic.ok){uint32_t item=UINT32_MAX;for(uint32_t i=0;i<semantic.ast.item_count;++i){DynAstItem *candidate=&semantic.ast.items[i];size_t n=candidate->name.end_byte-candidate->name.start_byte;if(n==sizeof(marker)-1&&!memcmp(semantic.source.text+candidate->name.start_byte,marker,n)){item=i;break;}}if(item!=UINT32_MAX)for(size_t i=semantic.ast.expression_count;i>0;--i){DynAstExpr *expression=&semantic.ast.expressions[i-1];if(expression->kind==DYN_EXPR_STRUCT&&item>=expression->item_start&&item<expression->item_start+expression->item_count){lsp_completion_type_fields(&semantic,expression->type,body,capacity,at,comma);break;}}}lsp_semantic_free(&semantic);
}
static void lsp_completion_enum_variants(LspDocument *documents,size_t count,
    LspDocument *requested,const char *name,bool qualify,char *body,size_t capacity,size_t *at,
    bool *comma) {
  LspSemantic semantic=lsp_semantic_project(documents,count,requested,requested->text);if(semantic.ok)for(uint32_t i=0;i<semantic.ast.enum_count;++i){DynAstEnum *value=&semantic.ast.enums[i];size_t n=value->name.end_byte-value->name.start_byte;if(strlen(name)!=n||memcmp(semantic.source.text+value->name.start_byte,name,n))continue;for(uint32_t j=0;j<value->variant_count;++j){DynAstVariant *variant=&semantic.ast.variants[value->variant_start+j];size_t length=variant->name.end_byte-variant->name.start_byte;const char *label=semantic.source.text+variant->name.start_byte;if(variant->payload_type==DYN_TYPE_VOID)*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"label\":\"%.*s\",\"kind\":20,\"detail\":\"enum variant\",\"insertText\":\"%s%s%.*s\"}",*comma?",":"",(int)length,label,qualify?name:"",qualify?".":"",(int)length,label);else{char type[128];dyn_type_format(&semantic.ast,variant->payload_type,&semantic.source,type,sizeof(type));*at+=(size_t)snprintf(body+*at,capacity-*at,"%s{\"label\":\"%.*s\",\"kind\":20,\"detail\":\"%s\",\"insertText\":\"%s%s%.*s(${1:value})\",\"insertTextFormat\":2}",*comma?",":"",(int)length,label,type,qualify?name:"",qualify?".":"",(int)length,label);}*comma=true;}break;}lsp_semantic_free(&semantic);
}
static void lsp_completion_expected_enum(LspDocument *documents,size_t count,
    LspDocument *requested,size_t line,size_t character,char *body,size_t capacity,
    size_t *at,bool *comma) {
  char name[128];if(lsp_expected_enum_name(documents,count,requested,line,character,name,sizeof(name)))lsp_completion_enum_variants(documents,count,requested,name,true,body,capacity,at,comma);
}
static bool lsp_copy_type_name(const char *start,const char *end,char *out,size_t capacity) {
  while(start<end&&isspace((unsigned char)*start))++start;
  while(end>start&&isspace((unsigned char)end[-1]))--end;
  if(start==end||(size_t)(end-start)>=capacity)return false;
  for(const char *p=start;p<end;++p)if(!(isalnum((unsigned char)*p)||*p=='_'))return false;
  memcpy(out,start,(size_t)(end-start));out[end-start]=0;return true;
}
static bool lsp_expected_enum_name(LspDocument *documents,size_t count,LspDocument *requested,
    size_t line,size_t character,char *out,size_t capacity) {
  const char *row=requested->text;for(size_t i=0;i<line&&row;++i){row=strchr(row,'\n');if(row)++row;}if(!row)return false;
  const char *row_end=strchr(row,'\n');if(!row_end)row_end=row+strlen(row);const char *cursor=row+(character>(size_t)(row_end-row)?(size_t)(row_end-row):character);
  const char *equal=memchr(row,'=',(size_t)(cursor-row));if(equal){const char *colon=memchr(row,':',(size_t)(equal-row));if(colon&&lsp_copy_type_name(colon+1,equal,out,capacity))return true;}
  const char *trim=row;while(trim<cursor&&isspace((unsigned char)*trim))++trim;
  if((size_t)(cursor-trim)>=6&&!memcmp(trim,"return",6)&&isspace((unsigned char)trim[6])){
    const char *scan=row,*last=NULL;while(scan>requested->text){scan--;if((scan==requested->text||scan[-1]=='\n')&&!memcmp(scan,"fn ",3)){last=scan;break;}}
    if(last){const char *close=strchr(last,')'),*brace=close?strchr(close,'{'):NULL;if(close&&brace&&lsp_copy_type_name(close+1,brace,out,capacity))return true;}
  }
  const char *open=cursor;unsigned depth=0;while(open>row){--open;if(*open==')')++depth;else if(*open=='('){if(!depth)break;--depth;}}
  if(open<=row||*open!='(')return false;
  const char *name_end=open,*name=name_end;
  while(name>row&&(isalnum((unsigned char)name[-1])||name[-1]=='_'))--name;
  if(name==name_end)return false;
  size_t active=0;depth=0;for(const char *p=open+1;p<cursor;++p){if(*p=='('||*p=='['||*p=='{')++depth;else if((*p==')'||*p==']'||*p=='}')&&depth)--depth;else if(*p==','&&!depth)++active;}
  for(size_t d=0;d<count;++d){const char *p=documents[d].text;while((p=strstr(p,"fn "))){const char *candidate=p+3;size_t n=(size_t)(name_end-name);if(!memcmp(candidate,name,n)&&candidate[n]=='('){const char *q=candidate+n+1;size_t index=0;while(*q&&*q!=')'){const char *item=q;unsigned nested=0;while(*q&&(nested||(*q!=','&&*q!=')'))){if(*q=='['||*q=='(')++nested;else if((*q==']'||*q==')')&&nested)--nested;++q;}if(index++==active){const char *colon=memchr(item,':',(size_t)(q-item));if(colon&&lsp_copy_type_name(colon+1,q,out,capacity))return true;break;}if(*q==',')++q;}}++p;}}
  return false;
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
static bool lsp_semantic_offset(LspSemantic *semantic,LspDocument *document,
    size_t line,size_t character,uint32_t *offset) {
  const char *word=NULL;size_t length=0;if(!identifier_at(document->text,line,character,&word,&length))return false;const char *row=document->text;for(size_t i=0;i<line;++i){row=strchr(row,'\n');if(!row)return false;++row;}size_t column=(size_t)(word-row),original=(size_t)(word-document->text);
  for(size_t i=0;i<semantic->source.map_count;++i){DynSourceMap *map=&semantic->source.maps[i];if(strcmp(map->path,document->uri)&&strcmp(map->path,lsp_file_path(document->uri)))continue;for(size_t j=0;j<map->span_count;++j){DynSourceSpan span=map->spans[j];if(original<span.original_start||original>span.original_end)continue;size_t on=span.original_end-span.original_start,gn=span.generated_end-span.generated_start;*offset=(uint32_t)(map->start+span.generated_start+(on?(original-span.original_start)*gn/on:0));return true;}if(original<=map->original_length){*offset=(uint32_t)(map->start+original);return true;}}
  for(size_t i=0;i+length<=semantic->source.length;++i)if(!memcmp(semantic->source.text+i,word,length)&&(i==0||!(isalnum((unsigned char)semantic->source.text[i-1])||semantic->source.text[i-1]=='_'))&&(i+length==semantic->source.length||!(isalnum((unsigned char)semantic->source.text[i+length])||semantic->source.text[i+length]=='_'))){const char *path=NULL;unsigned found_line=0,found_column=0;dyn_source_location(&semantic->source,i,&path,&found_line,&found_column);if(path&&(!strcmp(path,document->uri)||!strcmp(path,lsp_file_path(document->uri)))&&found_line==line+1&&found_column==column+1){*offset=(uint32_t)i;return true;}}
  return false;
}
static bool lsp_span_location(LspDocument *documents,size_t count,DynSpan span,
    LspDocument **document,size_t *line,size_t *column) {
  size_t base=0;for(size_t i=0;i<count;++i){size_t length=strlen(documents[i].text);
    if(span.start_byte>=base&&span.start_byte<base+length){size_t local=span.start_byte-base;*document=&documents[i];*line=0;*column=0;
      for(size_t j=0;j<local;++j){if(documents[i].text[j]=='\n'){++*line;*column=0;}else ++*column;}return true;}base+=length+1;}return false;
}
static void lsp_inlay_hints(long id,LspDocument *documents,size_t count,
    LspDocument *requested,size_t range_start,size_t range_end) {
  LspSemantic semantic=lsp_semantic_build_related(documents,count,requested);
  char body[65536];size_t at=(size_t)snprintf(body,sizeof(body),
      "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[",id);bool comma=false;
  for(size_t i=0;semantic.ok&&i<semantic.ast.local_count;++i){
    DynAstLocal *local=&semantic.ast.locals[i];LspDocument *document=NULL;size_t line=0,column=0;
    if(!lsp_span_location(documents,count,local->name,&document,&line,&column)||
        document!=requested||line<range_start||line>range_end)continue;
    size_t length=local->name.end_byte-local->name.start_byte;const char *row=requested->text;
    for(size_t r=0;r<line&&row;++r){row=strchr(row,'\n');if(row)++row;}if(!row)continue;
    const char *after=row+column+length;while(*after==' '||*after=='\t')++after;
    if(after[0]!=':'||after[1]!='=')continue;
    char type[128];
    dyn_type_format(&semantic.ast,local->type,&semantic.source,type,sizeof(type));
    at+=(size_t)snprintf(body+at,sizeof(body)-at,
        "%s{\"position\":{\"line\":%zu,\"character\":%zu},\"label\":\": %s\",\"kind\":1,\"paddingLeft\":true}",
        comma?",":"",line,column+length,type);comma=true;if(at+512>=sizeof(body))break;
  }
  for(size_t i=0;semantic.ok&&i<semantic.ast.expression_count&&at+512<sizeof(body);++i){
    DynAstExpr *call=&semantic.ast.expressions[i];
    if(call->kind!=DYN_EXPR_CALL||call->integer>=semantic.ast.function_count)continue;
    DynAstFn *callee=&semantic.ast.functions[call->integer];
    uint32_t arguments=call->item_count<callee->param_count?call->item_count:callee->param_count;
    for(uint32_t j=0;j<arguments&&at+512<sizeof(body);++j){
      DynAstItem *item=&semantic.ast.items[call->item_start+j];if(item->expression>=semantic.ast.expression_count)continue;
      DynAstExpr *argument=&semantic.ast.expressions[item->expression];
      while(argument->kind==DYN_EXPR_CONVERT&&argument->left<semantic.ast.expression_count)argument=&semantic.ast.expressions[argument->left];
      DynAstParam *parameter=&semantic.ast.params[callee->param_start+j];const char *path=NULL;unsigned line=0,column=0;
      dyn_source_location(&semantic.source,argument->span.start_byte,&path,&line,&column);size_t zero_line=line?line-1:0;
      if(!path||(strcmp(path,requested->uri)&&strcmp(path,lsp_file_path(requested->uri)))||zero_line<range_start||zero_line>range_end)continue;
      size_t length=parameter->name.end_byte-parameter->name.start_byte;if(!length)continue;
      at+=(size_t)snprintf(body+at,sizeof(body)-at,
          "%s{\"position\":{\"line\":%zu,\"character\":%u},\"label\":\"%.*s:\",\"kind\":2,\"paddingRight\":true}",
          comma?",":"",zero_line,column?column-1:0,(int)length,semantic.source.text+parameter->name.start_byte);comma=true;
    }
  }
  snprintf(body+at,sizeof(body)-at,"]}");lsp_send(body);lsp_semantic_free(&semantic);
}
static DynSpan lsp_expr_definition(DynAstFunction *a,DynAstExpr *e) {
  if(e->kind==DYN_EXPR_NAME&&e->integer<a->local_count)return a->locals[e->integer].name;
  if(e->kind==DYN_EXPR_GLOBAL&&e->integer<a->global_count)return a->globals[e->integer].name;
  if(e->kind==DYN_EXPR_FUNCTION&&e->integer<a->function_count)return a->functions[e->integer].name;
  if(e->kind==DYN_EXPR_CALL&&e->integer<a->function_count)return a->functions[e->integer].name;
  if(e->kind==DYN_EXPR_FIELD&&e->left<a->expression_count){DynType base=a->expressions[e->left].type;if(dyn_type_is_pointer(base)){uint32_t p=base-DYN_TYPE_POINTER_BASE;if(p<a->pointer_count)base=a->pointers[p].pointee;}if(dyn_type_is_struct(base)){DynAstStruct *s=&a->structs[base-DYN_TYPE_STRUCT_BASE];if(e->integer<s->field_count)return a->fields[s->field_start+(uint32_t)e->integer].name;}}
  return (DynSpan){0};
}
static bool lsp_same_span(DynSpan a,DynSpan b){return a.start_byte==b.start_byte&&a.end_byte==b.end_byte;}
static bool lsp_valid_identifier(const char *name){if(!name||!(*name=='_'||isalpha((unsigned char)*name)))return false;for(++name;*name;++name)if(!(*name=='_'||isalnum((unsigned char)*name)))return false;return true;}
typedef struct {char uri[1024];size_t line,column,length;} LspOrigin;
static size_t lsp_semantic_origins(LspSemantic *semantic,DynSpan target,LspOrigin *origins,size_t capacity) {
  DynSpan spans[4096];size_t span_count=0,count=0;spans[span_count++]=target;
  for(size_t i=0;i<semantic->ast.expression_count&&span_count<4096;++i){DynAstExpr *e=&semantic->ast.expressions[i];if(lsp_same_span(lsp_expr_definition(&semantic->ast,e),target)&&!lsp_same_span(e->span,target))spans[span_count++]=e->span;}
  for(size_t i=0;i<span_count&&count<capacity;++i){const char *path=NULL;unsigned line=0,column=0;dyn_source_location(&semantic->source,spans[i].start_byte,&path,&line,&column);if(!path)continue;char *owned=!strncmp(path,"file://",7)?NULL:lsp_path_uri(path);const char *uri=owned?owned:path;if(uri&&strlen(uri)<sizeof(origins[count].uri)){strcpy(origins[count].uri,uri);origins[count].line=line?line-1:0;origins[count].column=column?column-1:0;origins[count].length=spans[i].end_byte-spans[i].start_byte;++count;}free(owned);}
  return count;
}
static void lsp_semantic_references(long id,LspSemantic *semantic,LspDocument *documents,size_t count,DynSpan target) {
  (void)documents;(void)count;
  size_t capacity=1024u*1024u,at=0;char *body=malloc(capacity);if(!body)return;at=(size_t)snprintf(body,capacity,"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[",id);bool comma=false;
  LspOrigin origins[4096];size_t origin_count=lsp_semantic_origins(semantic,target,origins,4096);
  for(size_t i=0;i<origin_count;++i){char *uri=json_escape(origins[i].uri,strlen(origins[i].uri));if(uri){at+=(size_t)snprintf(body+at,capacity-at,"%s{\"uri\":\"%s\",\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}}}",comma?",":"",uri,origins[i].line,origins[i].column,origins[i].line,origins[i].column+origins[i].length);comma=true;}free(uri);}snprintf(body+at,capacity-at,"]}");lsp_send(body);free(body);
}
static void lsp_semantic_rename(long id,LspSemantic *semantic,LspDocument *documents,size_t count,DynSpan target,const char *replacement) {
  (void)documents;(void)count;
  size_t capacity=1024u*1024u,at=0;char *body=malloc(capacity);if(!body)return;at=(size_t)snprintf(body,capacity,"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"changes\":{",id);
  LspOrigin origins[4096];size_t origin_count=lsp_semantic_origins(semantic,target,origins,4096);bool document_comma=false;
  for(size_t d=0;d<origin_count;++d){bool seen=false;for(size_t p=0;p<d;++p)if(!strcmp(origins[p].uri,origins[d].uri)){seen=true;break;}if(seen)continue;char *uri=json_escape(origins[d].uri,strlen(origins[d].uri));if(!uri)continue;at+=(size_t)snprintf(body+at,capacity-at,"%s\"%s\":[",document_comma?",":"",uri);bool edit_comma=false;for(size_t i=0;i<origin_count;++i)if(!strcmp(origins[i].uri,origins[d].uri)){at+=(size_t)snprintf(body+at,capacity-at,"%s{\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}},\"newText\":\"%s\"}",edit_comma?",":"",origins[i].line,origins[i].column,origins[i].line,origins[i].column+origins[i].length,replacement);edit_comma=true;}at+=(size_t)snprintf(body+at,capacity-at,"]");document_comma=true;free(uri);}
  snprintf(body+at,capacity-at,"}}}");lsp_send(body);free(body);
}
static bool lsp_function_origin(LspSemantic *semantic,uint32_t index,LspOrigin *origin) {
  if(index>=semantic->ast.function_count)return false;
  DynAstFn *fn=&semantic->ast.functions[index];const char *path=NULL;unsigned line=0,column=0;dyn_source_location(&semantic->source,fn->name.start_byte,&path,&line,&column);if(!path)return false;char *owned=!strncmp(path,"file://",7)?NULL:lsp_path_uri(path);const char *uri=owned?owned:path;bool ok=uri&&strlen(uri)<sizeof(origin->uri);if(ok){strcpy(origin->uri,uri);origin->line=line?line-1:0;origin->column=column?column-1:0;origin->length=fn->name.end_byte-fn->name.start_byte;}free(owned);return ok;
}
static size_t lsp_call_item(LspSemantic *semantic,uint32_t function,const char *data,
    char *body,size_t capacity,size_t at) {
  LspOrigin origin;if(!lsp_function_origin(semantic,function,&origin))return at;DynAstFn *fn=&semantic->ast.functions[function];char *name=json_escape(semantic->source.text+fn->name.start_byte,fn->name.end_byte-fn->name.start_byte),*uri=json_escape(origin.uri,strlen(origin.uri)),*escaped_data=data?json_escape(data,strlen(data)):NULL;if(name&&uri)at+=(size_t)snprintf(body+at,capacity-at,"{\"name\":\"%s\",\"kind\":12,\"uri\":\"%s\",\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}},\"selectionRange\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}}%s%s%s}",name,uri,origin.line,origin.column,origin.line,origin.column+origin.length,origin.line,origin.column,origin.line,origin.column+origin.length,escaped_data?",\"data\":\"":"",escaped_data?escaped_data:"",escaped_data?"\"":"");free(name);free(uri);free(escaped_data);return at;
}
static uint32_t lsp_function_for_span(LspSemantic *semantic,DynSpan span) {for(uint32_t i=0;i<semantic->ast.function_count;++i)if(lsp_same_span(semantic->ast.functions[i].name,span))return i;return UINT32_MAX;}
static void lsp_prepare_call_hierarchy(long id,LspDocument *documents,size_t count,LspDocument *requested,size_t line,size_t character) {
  LspSemantic semantic=lsp_semantic_project(documents,count,requested,requested->text);if(!semantic.ok){lsp_semantic_free(&semantic);semantic=lsp_semantic_build_related(documents,count,requested);}uint32_t offset=0;DynSpan definition={0};char hover[8];uint32_t function=UINT32_MAX;bool found=semantic.ok&&lsp_semantic_offset(&semantic,requested,line,character,&offset)&&lsp_typed_symbol(&semantic,offset,hover,sizeof(hover),&definition)&&(function=lsp_function_for_span(&semantic,definition))!=UINT32_MAX;char body[4096];size_t at=(size_t)snprintf(body,sizeof(body),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":",id);if(found){char data[128];snprintf(data,sizeof(data),"%u|%s",function,requested->uri);body[at++]='[';at=lsp_call_item(&semantic,function,data,body,sizeof(body),at);body[at++]=']';body[at]=0;}else at+=(size_t)snprintf(body+at,sizeof(body)-at,"null");snprintf(body+at,sizeof(body)-at,"}");lsp_send(body);lsp_semantic_free(&semantic);
}
static bool lsp_call_data(const char *body,uint32_t *function,char **uri) {char *data=json_string_after(body,"\"data\"",64u*1024u);if(!data)return false;char *bar=strchr(data,'|');if(!bar){free(data);return false;}*bar=0;*function=(uint32_t)strtoul(data,NULL,10);*uri=strdup(bar+1);free(data);return *uri!=NULL;}
static void lsp_call_hierarchy(long id,LspDocument *documents,size_t count,const char *request,bool incoming) {
  uint32_t target=UINT32_MAX;char *source_uri=NULL;LspDocument *requested=NULL;bool parsed=lsp_call_data(request,&target,&source_uri);if(parsed)requested=lsp_document(documents,count,source_uri);LspSemantic semantic=requested?lsp_semantic_project(documents,count,requested,requested->text):(LspSemantic){0};if(requested&&!semantic.ok){lsp_semantic_free(&semantic);semantic=lsp_semantic_build_related(documents,count,requested);}size_t capacity=1024u*1024u,at=0;char *body=malloc(capacity);if(!body){free(source_uri);lsp_semantic_free(&semantic);return;}at=(size_t)snprintf(body,capacity,"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[",id);bool comma=false;
  if(semantic.ok&&target<semantic.ast.function_count)for(uint32_t i=0;i<semantic.ast.expression_count;++i){DynAstExpr *call=&semantic.ast.expressions[i];if(call->kind!=DYN_EXPR_CALL||call->integer>=semantic.ast.function_count)continue;uint32_t item_function=incoming?UINT32_MAX:(uint32_t)call->integer;if(incoming){if(call->integer!=target)continue;for(uint32_t f=0;f<semantic.ast.function_count;++f)if(call->span.start_byte>=semantic.ast.functions[f].span.start_byte&&call->span.end_byte<=semantic.ast.functions[f].span.end_byte){item_function=f;break;}}else if(!(call->span.start_byte>=semantic.ast.functions[target].span.start_byte&&call->span.end_byte<=semantic.ast.functions[target].span.end_byte))continue;if(item_function==UINT32_MAX)continue;const char *path=NULL;unsigned line=0,column=0;dyn_source_location(&semantic.source,call->span.start_byte,&path,&line,&column);if(!path)continue;char data[128];snprintf(data,sizeof(data),"%u|%s",item_function,source_uri);at+=(size_t)snprintf(body+at,capacity-at,"%s{\"%s\":",comma?",":"",incoming?"from":"to");at=lsp_call_item(&semantic,item_function,data,body,capacity,at);at+=(size_t)snprintf(body+at,capacity-at,",\"%sRanges\":[{\"start\":{\"line\":%u,\"character\":%u},\"end\":{\"line\":%u,\"character\":%u}}]}",incoming?"from":"from",line?line-1:0,column?column-1:0,line?line-1:0,(column?column-1:0)+(call->span.end_byte-call->span.start_byte));comma=true;}
  snprintf(body+at,capacity-at,"]}");lsp_send(body);free(body);free(source_uri);lsp_semantic_free(&semantic);
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
static bool lsp_field_source_type(LspSemantic *semantic,DynAstField *field,char *out,size_t capacity) {
  if(!capacity||field->name.end_byte>=semantic->source.length)return false;
  const char *text=semantic->source.text,*p=text+field->name.end_byte,*line=strchr(p,'\n');if(!line)line=text+semantic->source.length;
  const char *colon=memchr(p,':',(size_t)(line-p));if(!colon)return false;p=colon+1;while(p<line&&isspace((unsigned char)*p))++p;
  const char *end=p;unsigned depth=0;for(;end<line;++end){if(*end=='['||*end=='(')++depth;else if((*end==']'||*end==')')&&depth)--depth;else if(!depth&&(*end==','||*end=='='))break;}
  while(end>p&&isspace((unsigned char)end[-1]))--end;
  size_t n=(size_t)(end-p);if(!n)return false;if(n>=capacity)n=capacity-1;memcpy(out,p,n);out[n]=0;return true;
}
static void lsp_struct_hover(LspSemantic *semantic,uint32_t index,char *out,size_t capacity) {
  DynAstFunction *a=&semantic->ast;DynAstStruct *s=&a->structs[index];size_t at=0;
#define APPEND_STRUCT(...) do{if(at<capacity){int n=snprintf(out+at,capacity-at,__VA_ARGS__);if(n>0)at+=(size_t)n<capacity-at?(size_t)n:capacity-at-1;}}while(0)
  APPEND_STRUCT("%s%sstruct %.*s {",s->is_public?"pub ":"",s->packed?"packed ":"",(int)(s->name.end_byte-s->name.start_byte),semantic->source.text+s->name.start_byte);
  uint32_t shown=s->field_count<8?s->field_count:8;for(uint32_t i=0;i<shown;++i){DynAstField *field=&a->fields[s->field_start+i];char type[128];if(!lsp_field_source_type(semantic,field,type,sizeof(type)))dyn_type_format(a,field->type,&semantic->source,type,sizeof(type));APPEND_STRUCT("\n  %.*s: %s",(int)(field->name.end_byte-field->name.start_byte),semantic->source.text+field->name.start_byte,type);}
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
static bool lsp_type_definition_span(LspSemantic *semantic,uint32_t offset,DynSpan *definition) {
  DynAstFunction *a=&semantic->ast;DynType type=DYN_TYPE_ERROR;DynAstExpr *best=NULL;for(size_t i=0;i<a->expression_count;++i){DynAstExpr *e=&a->expressions[i];if(offset>=e->span.start_byte&&offset<e->span.end_byte&&e->type!=DYN_TYPE_INFER&&e->type!=DYN_TYPE_ERROR)if(!best||e->span.end_byte-e->span.start_byte<best->span.end_byte-best->span.start_byte)best=e;}if(best)type=best->type;for(size_t i=0;i<a->local_count&&type==DYN_TYPE_ERROR;++i)if(offset>=a->locals[i].name.start_byte&&offset<a->locals[i].name.end_byte)type=a->locals[i].type;if(dyn_type_is_pointer(type)){uint32_t p=type-DYN_TYPE_POINTER_BASE;if(p<a->pointer_count)type=a->pointers[p].pointee;}if(dyn_type_is_struct(type)){uint32_t i=type-DYN_TYPE_STRUCT_BASE;if(i<a->struct_count){*definition=a->structs[i].name;return true;}}if(dyn_type_is_enum(type)){uint32_t i=type-DYN_TYPE_ENUM_BASE;if(i<a->enum_count){*definition=a->enums[i].name;return true;}}if(dyn_type_is_distinct(type)){uint32_t i=type-DYN_TYPE_DISTINCT_BASE;if(i<a->alias_count){*definition=a->aliases[i].name;return true;}}return false;
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

static void lsp_import_hover_text(const char *path,size_t line,char *out,size_t capacity) {
  if(!capacity)return;
  out[0]=0;FILE *file=fopen(path,"rb");if(!file)return;char source_line[1024]={0};for(size_t row=0;row<=line&&fgets(source_line,sizeof(source_line),file);++row){}char *start=source_line;while(isspace((unsigned char)*start))++start;
  bool aggregate=strstr(start,"struct ")==start||strstr(start,"pub struct ")==start||strstr(start,"packed struct ")==start||strstr(start,"pub packed struct ")==start||strstr(start,"enum ")==start||strstr(start,"pub enum ")==start;
  if(!aggregate){fclose(file);lsp_completion_signature(start,out,capacity);return;}
  size_t at=0;int depth=0;bool opened=false;for(;;){for(char *p=start;*p;++p){if(*p=='{'){++depth;opened=true;}else if(*p=='}'&&depth)--depth;}size_t n=strlen(start);while(n&&isspace((unsigned char)start[n-1]))--n;if(at&&n&&start[n-1]==',')--n;if(at&&at+1<capacity)out[at++]='\n';if(at&&*start!='}'&&at+2<capacity){out[at++]=' ';out[at++]=' ';}size_t copy=n<capacity-at-1?n:capacity-at-1;memcpy(out+at,start,copy);at+=copy;out[at]=0;if((opened&&!depth)||!fgets(source_line,sizeof(source_line),file))break;start=source_line;while(isspace((unsigned char)*start))++start;}
  fclose(file);
}

int dyn_lsp(void) {
  char header[256];
  LspDocument documents[LSP_DOCUMENT_LIMIT] = {{0}}; size_t document_count = 0;
  char *workspace_root=NULL;
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
      char *root_uri=json_string_after(body,"\"rootUri\"",64u*1024u);if(root_uri){free(workspace_root);workspace_root=strdup(lsp_file_path(root_uri));free(root_uri);}
      char response[2048];
      snprintf(response, sizeof(response),
        "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"capabilities\":{"
        "\"positionEncoding\":\"utf-8\",\"textDocumentSync\":{\"openClose\":true,\"change\":2},\"hoverProvider\":true,"
        "\"definitionProvider\":true,\"declarationProvider\":true,\"implementationProvider\":true,\"typeDefinitionProvider\":true,\"referencesProvider\":true,\"renameProvider\":{\"prepareProvider\":true},"
        "\"documentSymbolProvider\":true,\"workspaceSymbolProvider\":true,"
        "\"documentFormattingProvider\":true,\"inlayHintProvider\":true,\"codeActionProvider\":true,"
        "\"documentHighlightProvider\":true,\"foldingRangeProvider\":true,\"selectionRangeProvider\":true,\"callHierarchyProvider\":true,"
        "\"semanticTokensProvider\":{\"legend\":{\"tokenTypes\":[\"namespace\",\"type\","
        "\"struct\",\"enum\",\"parameter\",\"variable\",\"property\",\"enumMember\",\"function\"],"
        "\"tokenModifiers\":[]},\"full\":true},\"completionProvider\":{\"triggerCharacters\":["
        "\".\",\"/\",\"#\",\"\\\"\",\"_\",\"a\",\"b\",\"c\",\"d\",\"e\",\"f\",\"g\",\"h\","
        "\"i\",\"j\",\"k\",\"l\",\"m\",\"n\",\"o\",\"p\",\"q\",\"r\",\"s\",\"t\","
        "\"u\",\"v\",\"w\",\"x\",\"y\",\"z\"]},\"signatureHelpProvider\":{"
        "\"triggerCharacters\":[\"(\",\",\"]}}}}", id);
      lsp_send(response);
    } else if(strstr(body,"\"method\":\"textDocument/didClose\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);for(size_t i=0;uri&&i<document_count;++i)if(!strcmp(documents[i].uri,uri)){char *escaped=json_escape(uri,strlen(uri));char response[512];if(escaped){snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/publishDiagnostics\",\"params\":{\"uri\":\"%s\",\"diagnostics\":[]}}",escaped);lsp_send(response);}free(escaped);free(documents[i].uri);free(documents[i].text);if(documents[i].tree)ts_tree_delete(documents[i].tree);if(documents[i].parser)ts_parser_delete(documents[i].parser);memmove(&documents[i],&documents[i+1],(document_count-i-1)*sizeof(*documents));--document_count;memset(&documents[document_count],0,sizeof(*documents));break;}free(uri);
    } else if (strstr(body, "\"method\":\"textDocument/didOpen\"") ||
               strstr(body, "\"method\":\"textDocument/didChange\"")) {
      bool changing=strstr(body,"\"method\":\"textDocument/didChange\"")!=NULL;
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      char *text = json_string_after(body, "\"text\"", 1024u * 1024u);
      LspDocument *document = uri ? lsp_document(documents, document_count, uri) : NULL;
      size_t start_line=0,start_character=0,end_line=0,end_character=0;bool ranged=changing&&document&&text&&json_range_positions(body,&start_line,&start_character,&end_line,&end_character);if(ranged){char *updated=lsp_apply_change(document,text,start_line,start_character,end_line,end_character);free(text);text=updated;}else if(changing&&document&&document->tree){ts_tree_delete(document->tree);document->tree=NULL;}
      if (!document && uri && document_count < LSP_DOCUMENT_LIMIT) document = &documents[document_count++];
      if (document && uri && text) {
        free(document->uri); free(document->text); document->uri = uri; document->text = text;
        bool syntax_error=lsp_publish_syntax(document);if(!syntax_error)lsp_publish_semantic(documents, document_count);
      } else { free(uri); free(text); }
    } else if(strstr(body,"\"method\":\"textDocument/documentSymbol\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;if(document)lsp_document_symbols(id,document);else{char response[96];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",id);lsp_send(response);}free(uri);
    } else if(strstr(body,"\"method\":\"textDocument/documentHighlight\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);size_t line=0,character=0;LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;(void)json_position(body,&line,&character);if(document)lsp_document_highlight(id,document,line,character);else{char response[96];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}",id);lsp_send(response);}free(uri);
    } else if(strstr(body,"\"method\":\"textDocument/foldingRange\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;if(document)lsp_folding_ranges(id,document);else{char response[96];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}",id);lsp_send(response);}free(uri);
    } else if(strstr(body,"\"method\":\"textDocument/selectionRange\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);size_t line=0,character=0;LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;(void)json_position(body,&line,&character);if(document)lsp_selection_range(id,document,line,character);else{char response[96];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}",id);lsp_send(response);}free(uri);
    } else if(strstr(body,"\"method\":\"textDocument/semanticTokens/full\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;if(document)lsp_semantic_tokens(id,document);else{char response[96];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",id);lsp_send(response);}free(uri);
    } else if(strstr(body,"\"method\":\"workspace/symbol\"")){
      char *query=json_string_after(body,"\"query\"",1024),*derived=NULL;if(!workspace_root&&document_count)derived=lsp_project_root(documents[0].uri);lsp_workspace_symbols(id,documents,document_count,workspace_root?workspace_root:derived,query);free(derived);free(query);
    } else if(strstr(body,"\"method\":\"workspace/didChangeWatchedFiles\"")||strstr(body,"\"method\":\"workspace/didChangeConfiguration\"")){
      lsp_publish_semantic(documents,document_count);
    } else if(strstr(body,"\"method\":\"workspace/didChangeWorkspaceFolders\"")){
      const char *added=strstr(body,"\"added\"");char *uri=added?json_string_after(added,"\"uri\"",64u*1024u):NULL;if(uri){free(workspace_root);workspace_root=strdup(lsp_file_path(uri));free(uri);}lsp_publish_semantic(documents,document_count);
    } else if(strstr(body,"\"method\":\"textDocument/codeAction\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;if(document)lsp_code_actions(id,document,body);else{char response[96];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}",id);lsp_send(response);}free(uri);
    } else if(strstr(body,"\"method\":\"textDocument/formatting\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;if(document)lsp_format(id,document);free(uri);
    } else if(strstr(body,"\"method\":\"textDocument/inlayHint\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);size_t first=0,a=0,last=SIZE_MAX,b=0;(void)json_range_positions(body,&first,&a,&last,&b);LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;if(document)lsp_inlay_hints(id,documents,document_count,document,first,last);free(uri);
    } else if (strstr(body, "\"method\":\"textDocument/completion\"")) {
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);size_t line=0,character=0;
      LspDocument *requested=uri?lsp_document(documents,document_count,uri):NULL;(void)json_position(body,&line,&character);
      lsp_completion(id,documents,document_count,requested,line,character);free(uri);
    } else if(strstr(body,"\"method\":\"textDocument/typeDefinition\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);size_t line=0,character=0;LspDocument *requested=uri?lsp_document(documents,document_count,uri):NULL;(void)json_position(body,&line,&character);LspSemantic semantic=requested?lsp_semantic_build_related(documents,document_count,requested):(LspSemantic){0};uint32_t offset=0;DynSpan span={0};const char *path=NULL;unsigned found_line=0,found_column=0;bool found=requested&&semantic.ok&&lsp_semantic_offset(&semantic,requested,line,character,&offset)&&lsp_type_definition_span(&semantic,offset,&span);if(found)dyn_source_location(&semantic.source,span.start_byte,&path,&found_line,&found_column);found=found&&path;if(found){const char *target=!strncmp(path,"file://",7)?path:NULL;char *owned=target?NULL:lsp_path_uri(path);if(!target)target=owned;char *escaped=target?json_escape(target,strlen(target)):NULL;char response[1024];if(escaped){size_t target_line=found_line?found_line-1:0,target_column=found_column?found_column-1:0;snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"uri\":\"%s\",\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}}}}",id,escaped,target_line,target_column,target_line,target_column+(span.end_byte-span.start_byte));lsp_send(response);}free(escaped);free(owned);}else{char response[96];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",id);lsp_send(response);}lsp_semantic_free(&semantic);free(uri);
    } else if(strstr(body,"\"method\":\"textDocument/prepareCallHierarchy\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);size_t line=0,character=0;LspDocument *requested=uri?lsp_document(documents,document_count,uri):NULL;(void)json_position(body,&line,&character);if(requested)lsp_prepare_call_hierarchy(id,documents,document_count,requested,line,character);else{char response[96];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",id);lsp_send(response);}free(uri);
    } else if(strstr(body,"\"method\":\"callHierarchy/incomingCalls\"")){
      lsp_call_hierarchy(id,documents,document_count,body,true);
    } else if(strstr(body,"\"method\":\"callHierarchy/outgoingCalls\"")){
      lsp_call_hierarchy(id,documents,document_count,body,false);
    } else if(strstr(body,"\"method\":\"textDocument/prepareRename\"")){
      char *uri=json_string_after(body,"\"uri\"",64u*1024u);size_t line=0,character=0;const char *word=NULL;size_t length=0;LspDocument *document=uri?lsp_document(documents,document_count,uri):NULL;(void)json_position(body,&line,&character);if(document&&identifier_at(document->text,line,character,&word,&length)){const char *row=document->text;for(size_t i=0;i<line;++i){row=strchr(row,'\n');if(row)++row;}size_t column=(size_t)(word-row);char *escaped=json_escape(word,length);char response[1024];if(escaped){snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%zu}},\"placeholder\":\"%s\"}}",id,line,column,line,column+length,escaped);lsp_send(response);}free(escaped);}else{char response[96];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",id);lsp_send(response);}free(uri);
    } else if (strstr(body, "\"method\":\"textDocument/hover\"") ||
               strstr(body, "\"method\":\"textDocument/definition\"") ||
               strstr(body, "\"method\":\"textDocument/declaration\"") ||
               strstr(body, "\"method\":\"textDocument/implementation\"") ||
               strstr(body, "\"method\":\"textDocument/references\"") ||
               strstr(body, "\"method\":\"textDocument/rename\"") ||
               strstr(body, "\"method\":\"textDocument/signatureHelp\"")) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      size_t line=0, character=0; const char *word=NULL, *display=NULL; size_t word_length=0, display_length=0, found_line=0, found_column=0;
      LspDocument *requested = uri ? lsp_document(documents, document_count, uri) : NULL;
      LspDocument *definition = NULL, external={0};bool import_found=false,builtin_found=false;char import_hover[512]={0},signature[512]={0};
      bool positioned = requested && requested->text && json_position(body, &line, &character);
      bool navigation=strstr(body,"textDocument/definition")||strstr(body,"textDocument/declaration")||strstr(body,"textDocument/implementation");
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
      if(!builtin_found&&positioned&&(navigation||strstr(body,"textDocument/hover")||strstr(body,"textDocument/signatureHelp"))){size_t target_length=0;import_found=lsp_import_definition(requested,line,character,&external.uri,&found_line,&found_column,&target_length);if(import_found){definition=&external;word_length=target_length;found=true;if(strstr(body,"textDocument/hover")||strstr(body,"textDocument/signatureHelp")){lsp_import_hover_text(lsp_file_path(external.uri),found_line,import_hover,sizeof(import_hover));display=import_hover;display_length=strlen(import_hover);}}}
      if(found&&!import_found&&strstr(body,"textDocument/signatureHelp")){lsp_completion_signature(display,signature,sizeof(signature));display=signature;display_length=strlen(signature);}
      bool reference_request=strstr(body,"textDocument/references")||strstr(body,"textDocument/rename");
      LspSemantic semantic = reference_request?lsp_semantic_project(documents,document_count,requested,requested->text):lsp_semantic_build(documents, document_count); char typed_hover[512]; DynSpan typed_definition={0}; uint32_t typed_offset=0;
      if(reference_request&&!semantic.ok){lsp_semantic_free(&semantic);semantic=lsp_semantic_build(documents,document_count);}
      bool typed = positioned && semantic.ok && (reference_request?lsp_semantic_offset(&semantic,requested,line,character,&typed_offset):lsp_document_offset(documents,document_count,requested,line,character,&typed_offset)) &&
                   lsp_typed_symbol(&semantic,typed_offset,typed_hover,sizeof(typed_hover),&typed_definition);
      if (!builtin_found&&!import_found&&typed && strstr(body,"textDocument/hover") &&
          (!found || typed_definition.end_byte > typed_definition.start_byte)) {
        display=typed_hover; display_length=strlen(typed_hover); found=true;
      }
      if (!import_found&&typed && navigation && typed_definition.end_byte>typed_definition.start_byte)
        found=lsp_span_location(documents,document_count,typed_definition,&definition,&found_line,&found_column);
      if(typed&&typed_definition.end_byte>typed_definition.start_byte&&(strstr(body,"textDocument/references")||strstr(body,"textDocument/rename")))found=true;
      if (found && (strstr(body, "textDocument/references") || strstr(body, "textDocument/rename"))) {
        char *new_name = strstr(body, "textDocument/rename") ? json_string_after(body, "\"newName\"", 1024) : NULL;
        bool semantic_target=typed&&typed_definition.end_byte>typed_definition.start_byte;
        if(new_name&&!lsp_valid_identifier(new_name)){char response[192];snprintf(response,sizeof(response),"{\"jsonrpc\":\"2.0\",\"id\":%ld,\"error\":{\"code\":-32602,\"message\":\"rename requires a valid Dyn identifier\"}}",id);lsp_send(response);}
        else if(new_name&&semantic_target)lsp_semantic_rename(id,&semantic,documents,document_count,typed_definition,new_name);
        else if(new_name){char *root=lsp_project_root(requested->uri);lsp_rename(id,documents,document_count,word,word_length,new_name,root);free(root);}
        else if(semantic_target)lsp_semantic_references(id,&semantic,documents,document_count,typed_definition);
        else {char *root=lsp_project_root(requested->uri);lsp_references(id,documents,document_count,word,word_length,NULL,root);free(root);}
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
      free(body); for (size_t i = 0; i < document_count; ++i) { free(documents[i].uri); free(documents[i].text); if (documents[i].tree) ts_tree_delete(documents[i].tree); if (documents[i].parser) ts_parser_delete(documents[i].parser); } free(workspace_root); return 0;
    }
    else if (id >= 0) {
      char response[160]; snprintf(response, sizeof(response),
        "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"error\":{\"code\":-32601,\"message\":\"method not supported\"}}", id); lsp_send(response);
    }
    free(body);
  }
  for (size_t i = 0; i < document_count; ++i) { free(documents[i].uri); free(documents[i].text); if (documents[i].tree) ts_tree_delete(documents[i].tree); if (documents[i].parser) ts_parser_delete(documents[i].parser); } free(workspace_root);
  return 0;
}
