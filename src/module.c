#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <tree_sitter/api.h>
#include <unistd.h>
extern const TSLanguage *tree_sitter_dyn(void);
extern char *realpath(const char *, char *);

typedef struct {
  char *name;
  bool is_public;
} InterfaceDecl;
typedef struct {
  char *directory;
  InterfaceDecl *decls;
  size_t decl_count;
} ModuleInterface;
typedef struct {
  char **visited;
  size_t visited_count;
  char **stack;
  size_t stack_count;
  char *root;
  char **dependency_names;
  char **dependency_roots;
  size_t dependency_count;
  DynSources *out;
  const DynSources *overrides;
  ModuleInterface *interfaces;
  size_t interface_count;
} Resolver;
static void apply_overrides(DynSources *sources, const DynSources *overrides) {
  if (!overrides) return;
  for (size_t i=0;i<sources->count;++i) for(size_t j=0;j<overrides->count;++j) {
    const char *path=overrides->items[j].path;
    if(!strncmp(path,"file://",7))path+=7;
    if(strcmp(sources->items[i].path,path))continue;
    char *text=malloc(overrides->items[j].length+1);if(!text)continue;
    memcpy(text,overrides->items[j].text,overrides->items[j].length);
    text[overrides->items[j].length]=0;free(sources->items[i].text);
    sources->items[i].text=text;sources->items[i].length=overrides->items[j].length;
  }
}
static bool has(char **v, size_t n, const char *s) {
  for (size_t i = 0; i < n; ++i)
    if (!strcmp(v[i], s))
      return true;
  return false;
}
static bool push(char ***v, size_t *n, const char *s) {
  char **p = realloc(*v, (*n + 1) * sizeof(*p));
  if (!p)
    return false;
  *v = p;
  p[*n] = strdup(s);
  if (!p[*n])
    return false;
  ++*n;
  return true;
}
static void pop(char **v, size_t *n) { free(v[--*n]); }
static bool append_source(DynSources *out, const DynSource *s) {
  DynSource *p = realloc(out->items, (out->count + 1) * sizeof(*p));
  if (!p)
    return false;
  out->items = p;
  DynSource *d = &p[out->count];
  memset(d, 0, sizeof(*d));
  d->path = strdup(s->path);
  d->text = malloc(s->length + 1);
  d->length = s->length;
  if (!d->path || !d->text) {
    free(d->path);
    free(d->text);
    return false;
  }
  memcpy(d->text, s->text, s->length + 1);
  ++out->count;
  return true;
}
static char *node_text(TSNode n, const DynSource *s, bool quoted) {
  uint32_t a = ts_node_start_byte(n) + (quoted ? 1u : 0u),
           b = ts_node_end_byte(n) - (quoted ? 1u : 0u);
  char *r = malloc((size_t)(b - a) + 1);
  if (!r)
    return NULL;
  memcpy(r, s->text + a, b - a);
  r[b - a] = 0;
  return r;
}
static void module_diagnostic(TSNode node,const DynSource *source,const char *severity,const char *message) {
  TSPoint start=ts_node_start_point(node),end=ts_node_end_point(node);
  dyn_diagnostic(severity,source->path,start.row+1,start.column+1,end.row+1,end.column+1,message);
}
static bool within(const char *root, const char *path) {
  size_t n = strlen(root);
  return !strncmp(root, path, n) && (path[n] == 0 || path[n] == '/');
}
static char *resolve_configured_sdk(const char *path) {
  const char *configured = getenv("DYN_SDK");
  if (!configured || !*configured)
    return NULL;
  char *root = realpath(configured, NULL);
  if (!root)
    return NULL;
  char *candidate = dyn_path_join(root, path);
  char *result = candidate ? realpath(candidate, NULL) : NULL;
  free(candidate);
  if (!result || !within(root, result)) {
    free(result);
    result = NULL;
  }
  free(root);
  return result;
}
static char *resolve_std(const char *path) {
  char *configured = resolve_configured_sdk(path);
  if (configured)
    return configured;
  char executable[4096];
  ssize_t n = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
  if (n < 0)
    return NULL;
  executable[n] = 0;
  char *slash = strrchr(executable, '/');
  if (!slash)
    return NULL;
  *slash = 0;
  char relative[4096];
  if (snprintf(relative, sizeof(relative), "%s/../compiler/%s", executable,
               path) < (int)sizeof(relative)) {
    char *found = realpath(relative, NULL);
    if (found)
      return found;
  }
  if (snprintf(relative, sizeof(relative), "%s/../%s", executable, path) <
      (int)sizeof(relative))
    {
      char *found = realpath(relative, NULL);
      if (found)
        return found;
    }
  if (snprintf(relative, sizeof(relative), "%s/../share/dyn/%s", executable,
               path + 4) < (int)sizeof(relative))
    return realpath(relative, NULL);
  return NULL;
}
static char *resolve_vendor(const char *path) {
  char *configured = resolve_configured_sdk(path);
  if (configured)
    return configured;
  char executable[4096];
  ssize_t n = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
  if (n < 0)
    return NULL;
  executable[n] = 0;
  char *slash = strrchr(executable, '/');
  if (!slash)
    return NULL;
  *slash = 0;
  char relative[4096];
  if (snprintf(relative, sizeof(relative), "%s/../compiler/%s", executable,
               path) < (int)sizeof(relative)) {
    char *found = realpath(relative, NULL);
    if (found)
      return found;
  }
  if (snprintf(relative, sizeof(relative), "%s/../sdk/%s", executable, path) <
      (int)sizeof(relative)) {
    char *found = realpath(relative, NULL);
    if (found)
      return found;
  }
  if (snprintf(relative, sizeof(relative), "%s/../%s", executable, path) <
      (int)sizeof(relative)) {
    char *found = realpath(relative, NULL);
    if (found)
      return found;
  }
  if (snprintf(relative, sizeof(relative), "%s/../share/dyn/%s", executable,
               path) < (int)sizeof(relative))
    return realpath(relative, NULL);
  return NULL;
}
static char *resolve(Resolver *r, const char *current, const char *path) {
  if (!strncmp(path, "std/", 4))
    return resolve_std(path);
  if (!strncmp(path, "vendor/", 7))
    return resolve_vendor(path);
  const char *slash = strchr(path, '/');
  size_t first = slash ? (size_t)(slash - path) : strlen(path);
  for (size_t i = 0; i < r->dependency_count; ++i) {
    if (strlen(r->dependency_names[i]) == first &&
        !memcmp(path, r->dependency_names[i], first)) {
      char *candidate = slash ? dyn_path_join(r->dependency_roots[i], slash + 1)
                              : strdup(r->dependency_roots[i]);
      char *result = candidate ? realpath(candidate, NULL) : NULL;
      free(candidate);
      if (!result || !within(r->dependency_roots[i], result)) { free(result); return NULL; }
      return result;
    }
  }
  char *candidate = (!strncmp(path, "./", 2) || !strncmp(path, "../", 3))
                        ? dyn_path_join(current, path)
                        : dyn_path_join(r->root, path);
  if (!candidate)
    return NULL;
  char *result = realpath(candidate, NULL);
  free(candidate);
  if (!result || !within(r->root, result)) {
    free(result);
    return NULL;
  }
  return result;
}
static int load_manifest(Resolver *r) {
  char *path = dyn_path_join(r->root, "dyn.project");
  FILE *f = path ? fopen(path, "r") : NULL;
  free(path);
  if (!f) return errno == ENOENT ? 0 : 1;
  char line[4096]; int result = 0;
  while (fgets(line, sizeof(line), f)) {
    char name[128], relative[3072], extra;
    char *p = line; while (isspace((unsigned char)*p)) ++p;
    if (!*p || *p == '#') continue;
    if (sscanf(p, "dependency %127s %3071s %c", name, relative, &extra) != 2) {
      fprintf(stderr, "error: dyn.project expects 'dependency NAME PATH'\n");
      result = 1; break;
    }
    if (strchr(name, '/') || has(r->dependency_names, r->dependency_count, name)) {
      fprintf(stderr, "error: invalid or duplicate dependency '%s'\n", name);
      result = 1; break;
    }
    char *candidate = dyn_path_join(r->root, relative);
    char *root = candidate ? realpath(candidate, NULL) : NULL;
    free(candidate);
    if (!root || !dyn_path_is_directory(root)) {
      fprintf(stderr, "error: dependency '%s' path does not resolve\n", name);
      free(root); result = 1; break;
    }
    char **names = malloc((r->dependency_count + 1) * sizeof(char *));
    char **roots = malloc((r->dependency_count + 1) * sizeof(char *));
    if (!names || !roots) { free(names); free(roots); free(root); result = 2; break; }
    for (size_t i = 0; i < r->dependency_count; ++i) {
      names[i] = r->dependency_names[i];
      roots[i] = r->dependency_roots[i];
    }
    free(r->dependency_names); free(r->dependency_roots);
    r->dependency_names = names; r->dependency_roots = roots;
    r->dependency_names[r->dependency_count] = strdup(name);
    r->dependency_roots[r->dependency_count] = root;
    if (!r->dependency_names[r->dependency_count]) { result = 2; break; }
    ++r->dependency_count;
  }
  fclose(f); return result;
}
char *dyn_module_resolve_import(const char *project_root, const char *current,
                                const char *path) {
  char *root = realpath(project_root, NULL);
  if (!root) return NULL;
  Resolver r = {.root = root};
  char *result = load_manifest(&r) ? NULL : resolve(&r, current, path);
  for (size_t i = 0; i < r.dependency_count; ++i) {
    free(r.dependency_names[i]); free(r.dependency_roots[i]);
  }
  free(r.dependency_names); free(r.dependency_roots); free(root);
  return result;
}
static ModuleInterface *find_interface(Resolver *r, const char *directory) {
  for (size_t i = 0; i < r->interface_count; ++i)
    if (!strcmp(r->interfaces[i].directory, directory))
      return &r->interfaces[i];
  return NULL;
}
static void free_interface(ModuleInterface *value) {
  free(value->directory);
  for (size_t i = 0; i < value->decl_count; ++i) free(value->decls[i].name);
  free(value->decls);
  memset(value, 0, sizeof(*value));
}
static int extract_interface(Resolver *r, const char *directory,
                             const DynSources *sources) {
  if (find_interface(r, directory)) return 0;
  ModuleInterface value = {.directory = strdup(directory)};
  if (!value.directory) return 2;
  TSParser *p = ts_parser_new();
  if (!p || !ts_parser_set_language(p, tree_sitter_dyn())) {
    if (p) ts_parser_delete(p);
    free_interface(&value);
    return 2;
  }
  for (size_t si = 0; si < sources->count; ++si) {
      const DynSource *s = &sources->items[si];
      if (dyn_source_target_enabled(s) == 0) continue;
      TSTree *t = ts_parser_parse_string(p, NULL, s->text, (uint32_t)s->length);
      TSNode root = ts_tree_root_node(t);
      for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
        TSNode wrapper = ts_node_named_child(root, i), d = wrapper;
        if (!strcmp(ts_node_type(d), "declaration"))
          d = ts_node_named_child(d, ts_node_named_child_count(d) - 1);
        const char *k = ts_node_type(d);
        if (!strcmp(k, "const_variable")) {
          d = ts_node_named_child(d, 0);
          k = ts_node_type(d);
        }
        if (strcmp(k, "fn") && strcmp(k, "extern_fn") &&
            strcmp(k, "extern_variable") && strcmp(k, "struct") &&
            strcmp(k, "enum") && strcmp(k, "variable") && strcmp(k, "type_alias"))
          continue;
        TSNode n = (!strcmp(k, "fn") || !strcmp(k, "extern_fn") ||
                    !strcmp(k, "extern_variable"))
                       ? ts_node_child_by_field_name(d, "name", 4)
                       : ts_node_named_child(d, 0);
        char *text = node_text(n, s, false);
        InterfaceDecl *next = realloc(value.decls,
            (value.decl_count + 1) * sizeof(*next));
        if (!text || !next) {
          free(text);
          ts_tree_delete(t);
          ts_parser_delete(p);
          free_interface(&value);
          return 2;
        }
        value.decls = next;
        uint32_t at = ts_node_start_byte(wrapper);
        value.decls[value.decl_count++] = (InterfaceDecl){
            .name = text,
            .is_public = at + 3 <= s->length && !memcmp(s->text + at, "pub", 3)};
      }
      ts_tree_delete(t);
    }
  ts_parser_delete(p);
  ModuleInterface *next = realloc(r->interfaces,
      (r->interface_count + 1) * sizeof(*next));
  if (!next) { free_interface(&value); return 2; }
  r->interfaces = next;
  r->interfaces[r->interface_count++] = value;
  return 0;
}
static bool decl_named(Resolver *r, const char *directory, const char *name,
                       bool *is_public) {
  ModuleInterface *interface = find_interface(r, directory);
  if (!interface) return false;
  for (size_t i = 0; i < interface->decl_count; ++i)
    if (!strcmp(interface->decls[i].name, name)) {
      *is_public = interface->decls[i].is_public;
      return true;
    }
  return false;
}
static size_t alias_index(char **aliases, size_t count, const char *name) {
  for (size_t i = 0; i < count; ++i)
    if (!strcmp(aliases[i], name))
      return i;
  return count;
}
static bool imported_decl(Resolver *r, char **targets, size_t count,
                          const char *name) {
  for (size_t i = 0; i < count; ++i) {
    bool pub = false;
    if (decl_named(r, targets[i], name, &pub))
      return true;
  }
  return false;
}
static int validate_member(Resolver *r, TSNode n, const DynSource *s, char **aliases,
                           char **targets, size_t count, const char *qualifier,
                           const char *member) {
  size_t found = alias_index(aliases, count, qualifier);
  if (found < count) {
    bool pub = false;
    if (decl_named(r, targets[found], member, &pub) && pub)
      return 0;
    char message[512];snprintf(message,sizeof(message),"imported member '%s.%s' is missing or not pub",qualifier,member);
    module_diagnostic(n,s,"error",message);
    return 1;
  }
  if (imported_decl(r, targets, count, member)) {
    char message[512];snprintf(message,sizeof(message),"unknown import alias '%s' for member '%s'",qualifier,member);
    module_diagnostic(n,s,"error",message);
    return 1;
  }
  return 0;
}
static int validate_refs(Resolver *r, TSNode n, const DynSource *s, const char *directory,
                         char **aliases, char **targets, size_t count) {
  int errors = 0;
  const char *kind = ts_node_type(n);
  if (!strcmp(kind, "field_access")) {
    TSNode base = ts_node_named_child(n, 0);
    if (strcmp(ts_node_type(base), "field_access")) {
      while (ts_node_named_child_count(base) == 1)
        base = ts_node_named_child(base, 0);
      if (!strcmp(ts_node_type(base), "identifier")) {
        char *qualifier = node_text(base, s, false),
             *member = node_text(ts_node_named_child(n, 1), s, false);
        errors +=
            validate_member(r, n, s, aliases, targets, count, qualifier, member);
        free(qualifier);
        free(member);
      }
    }
  } else if (!strcmp(kind, "field_type")) {
    uint32_t names = ts_node_named_child_count(n);
    if (names > 1) {
      char *qualifier = node_text(ts_node_named_child(n, 0), s, false),
           *member = node_text(ts_node_named_child(n, 1), s, false);
      errors +=
          validate_member(r, n, s, aliases, targets, count, qualifier, member);
      free(qualifier);
      free(member);
    } else if (names == 1) {
      char *name = node_text(ts_node_named_child(n, 0), s, false);
      bool pub = false;
      if (!decl_named(r, directory, name, &pub) &&
          imported_decl(r, targets, count, name)) {
        char message[512];snprintf(message,sizeof(message),"imported type '%s' must be module-qualified",name);
        module_diagnostic(n,s,"error",message);
        ++errors;
      }
      free(name);
    }
  } else if (!strcmp(kind, "call")) {
    TSNode callee = ts_node_named_child(n, 0);
    while (ts_node_named_child_count(callee) == 1)
      callee = ts_node_named_child(callee, 0);
    if (!strcmp(ts_node_type(callee), "identifier")) {
      char *name = node_text(callee, s, false);
      bool pub = false;
      if (!decl_named(r, directory, name, &pub) &&
          imported_decl(r, targets, count, name)) {
        char message[512];snprintf(message,sizeof(message),"imported function '%s' must be module-qualified",name);
        module_diagnostic(callee,s,"error",message);
        ++errors;
      }
      free(name);
    }
  } else if (!strcmp(kind, "struct_literal")) {
    uint32_t names = 0, total = ts_node_named_child_count(n);
    while (names < total &&
           !strcmp(ts_node_type(ts_node_named_child(n, names)), "identifier"))
      ++names;
    if (names > 1) {
      char *qualifier = node_text(ts_node_named_child(n, 0), s, false),
           *member = node_text(ts_node_named_child(n, 1), s, false);
      errors +=
          validate_member(r, n, s, aliases, targets, count, qualifier, member);
      free(qualifier);
      free(member);
    } else if (names == 1) {
      char *name = node_text(ts_node_named_child(n, 0), s, false);
      bool pub = false;
      if (!decl_named(r, directory, name, &pub) &&
          imported_decl(r, targets, count, name)) {
        char message[512];snprintf(message,sizeof(message),"imported type '%s' must be module-qualified",name);
        module_diagnostic(n,s,"error",message);
        ++errors;
      }
      free(name);
    }
  }
  for (uint32_t i = 0; i < ts_node_named_child_count(n); ++i)
    errors += validate_refs(r, ts_node_named_child(n, i), s, directory, aliases,
                            targets, count);
  return errors;
}
static int visit(Resolver *r, const char *directory,
                 const DynSources *provided) {
  if (has(r->stack, r->stack_count, directory)) {
    fprintf(stderr, "error: cyclic import:\n");
    size_t first = 0;
    while (first < r->stack_count && strcmp(r->stack[first], directory))
      ++first;
    for (size_t i = first; i < r->stack_count; ++i) {
      char *b = dyn_path_basename(r->stack[i]);
      fprintf(stderr, "  %s ->\n", b);
      free(b);
    }
    char *b = dyn_path_basename(directory);
    fprintf(stderr, "  %s\n", b);
    free(b);
    return 1;
  }
  if (has(r->visited, r->visited_count, directory))
    return 0;
  if (!push(&r->stack, &r->stack_count, directory))
    return 2;
  DynSources owned = {0};
  const DynSources *sources = provided;
  if (!sources) {
    int e = dyn_sources_load(directory, &owned);
    if (e) {
      pop(r->stack, &r->stack_count);
      return e;
    }
    apply_overrides(&owned,r->overrides);
    sources = &owned;
  }
  int result = 0;
  result = extract_interface(r, directory, sources);
  TSParser *p = ts_parser_new();
  if (!p || !ts_parser_set_language(p, tree_sitter_dyn()))
    result = 2;
  char **aliases = NULL, **targets = NULL;
  size_t alias_count = 0, target_count = 0;
  for (size_t si = 0; si < sources->count && !result; ++si) {
    if (dyn_source_target_enabled(&sources->items[si]) == 0) continue;
    const DynSource *s = &sources->items[si];
    TSTree *t = ts_parser_parse_string(p, NULL, s->text, (uint32_t)s->length);
    TSNode root = ts_tree_root_node(t);
    for (uint32_t i = 0; i < ts_node_named_child_count(root) && !result; ++i) {
      TSNode d = ts_node_named_child(root, i);
      if (!strcmp(ts_node_type(d), "declaration"))
        d = ts_node_named_child(d, ts_node_named_child_count(d) - 1);
      if (strcmp(ts_node_type(d), "use"))
        continue;
      char *path = node_text(ts_node_named_child(d, 0), s, true),
           *target = resolve(r, directory, path);
      TSNode an = ts_node_named_child_count(d) > 1 ? ts_node_named_child(d, 1)
                                                   : (TSNode){0};
      if (!ts_node_is_null(an) &&
          ts_node_start_point(an).row != ts_node_start_point(d).row)
        an = (TSNode){0};
      char *alias = ts_node_is_null(an) ? dyn_path_basename(path)
                                        : node_text(an, s, false);
      if (has(aliases, alias_count, alias)) {
        char message[512];snprintf(message,sizeof(message),"duplicate import alias '%s'",alias);
        module_diagnostic(d,s,"error",message);
        result = 1;
      } else if (!target || !dyn_path_is_directory(target)) {
        char message[512];snprintf(message,sizeof(message),"import '%s' does not resolve inside project root",path);
        module_diagnostic(d,s,"error",message);
        result = 1;
      } else {
        if (has(targets, target_count, target)) {
          char message[512];snprintf(message,sizeof(message),"module '%s' is imported more than once under different aliases",path);
          module_diagnostic(d,s,"warning",message);
        }
        if (!push(&aliases, &alias_count, alias) ||
            !push(&targets, &target_count, target))
          result = 2;
        else
          result = visit(r, target, NULL);
      }
      free(path);
      free(target);
      free(alias);
    }
    ts_tree_delete(t);
  }
  for (size_t si = 0; si < sources->count && !result; ++si) {
    if (dyn_source_target_enabled(&sources->items[si]) == 0) continue;
    const DynSource *s = &sources->items[si];
    TSTree *t = ts_parser_parse_string(p, NULL, s->text, (uint32_t)s->length);
    result += validate_refs(r, ts_tree_root_node(t), s, directory, aliases,
                            targets, alias_count);
    ts_tree_delete(t);
  }
  for (size_t i = 0; i < sources->count && !result; ++i)
    if (r->out && !append_source(r->out, &sources->items[i]))
      result = 2;
  for (size_t i = 0; i < alias_count; ++i)
    free(aliases[i]);
  for (size_t i = 0; i < target_count; ++i)
    free(targets[i]);
  free(aliases);
  free(targets);
  if (p)
    ts_parser_delete(p);
  dyn_sources_free(&owned);
  if (!result && !push(&r->visited, &r->visited_count, directory))
    result = 2;
  pop(r->stack, &r->stack_count);
  return result;
}
static int load(const char *project_root, const DynSources *root_sources,
                const DynSources *overrides, DynSources *out) {
  if (out)
    memset(out, 0, sizeof(*out));
  char *root = realpath(project_root, NULL);
  if (!root)
    return 1;
  Resolver r = {.root = root, .out = out, .overrides = overrides};
  int result = load_manifest(&r);
  if (!result) result = visit(&r, root, root_sources);
  if (!result && out)
    result = dyn_module_rewrite_project(root, out);
  for (size_t i = 0; i < r.visited_count; ++i)
    free(r.visited[i]);
  free(r.visited);
  free(r.stack);
  for (size_t i = 0; i < r.dependency_count; ++i) {
    free(r.dependency_names[i]); free(r.dependency_roots[i]);
  }
  free(r.dependency_names); free(r.dependency_roots);
  for (size_t i = 0; i < r.interface_count; ++i) {
    free_interface(&r.interfaces[i]);
  }
  free(r.interfaces);
  free(root);
  if (result && out)
    dyn_sources_free(out);
  return result;
}
int dyn_module_validate_imports(const char *root, const DynSources *sources) {
  return load(root, sources, NULL, NULL);
}
int dyn_module_load_project(const char *root, const DynSources *sources,
                            DynSources *out) {
  return load(root, sources, NULL, out);
}
int dyn_module_load_project_overlay(const char *root, const DynSources *sources,
                                    const DynSources *overrides,
                                    DynSources *out) {
  return load(root, sources, overrides, out);
}
