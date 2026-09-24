#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include "dyn_syntax.h"
#include "dyn_scope.h"
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
  DynContext context;
  DynSources *out;
  const DynSources *overrides;
  ModuleInterface *interfaces;
  size_t interface_count;
} Resolver;
static bool append_source(DynSources *, const DynSource *);
static int overlay_source_order(const void *left, const void *right) {
  return strcmp(((const DynSource *)left)->path,
                ((const DynSource *)right)->path);
}
static bool apply_overrides(const DynContext *context, DynSources *sources,
                            const DynSources *overrides,
                            const char *directory) {
  if (!overrides)
    return true;
  size_t directory_length = strlen(directory);
  for (size_t j = 0; j < overrides->count; ++j) {
    const DynSource *replacement = &overrides->items[j];
    const char *path = replacement->path;
    if (!strncmp(path, "file://", 7))
      path += 7;
    const char *slash = strrchr(path, '/');
    if (!slash || (size_t)(slash - path) != directory_length ||
        memcmp(path, directory, directory_length))
      continue;
    size_t length = strlen(path);
    if (length < 4 || strcmp(path + length - 4, ".dyn"))
      continue;
    size_t i = 0;
    while (i < sources->count && strcmp(sources->items[i].path, path))
      ++i;
    if (i == sources->count) {
      DynSource added = *replacement;
      added.path = (char *)path;
      added.context = *context;
      if (!append_source(sources, &added))
        return false;
    } else {
      char *text = malloc(replacement->length + 1);
      if (!text)
        return false;
      memcpy(text, replacement->text, replacement->length + 1);
      dyn_source_discard_syntax(&sources->items[i]);
      free(sources->items[i].text);
      sources->items[i].text = text;
      sources->items[i].length = replacement->length;
      sources->items[i].syntax = dyn_source_tree(replacement);
      if (!sources->items[i].syntax)
        return false;
    }
  }
  if (sources->count > 1)
    qsort(sources->items, sources->count, sizeof(*sources->items),
          overlay_source_order);
  return true;
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
  d->context = s->context;
  d->path = strdup(s->path);
  d->text = malloc(s->length + 1);
  d->length = s->length;
  if (!d->path || !d->text) {
    free(d->path);
    free(d->text);
    return false;
  }
  memcpy(d->text, s->text, s->length + 1);
  d->syntax = dyn_source_tree(s);
  if (!d->syntax) {
    dyn_source_free(d);
    return false;
  }
  ++out->count;
  return true;
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
      (int)sizeof(relative)) {
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
  if (!path || !*path)
    return NULL;
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
      if (!result || !within(r->dependency_roots[i], result)) {
        free(result);
        return NULL;
      }
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
  if (!path)
    return 2;
  FILE *f = fopen(path, "r");
  if (!f) {
    int result = errno == ENOENT ? 0 : 1;
    free(path);
    return result;
  }
  char line[4096];
  int result = 0;
  unsigned line_number = 0;
  while (fgets(line, sizeof(line), f)) {
    ++line_number;
    char name[128], relative[3072], extra;
    char *p = line;
    while (isspace((unsigned char)*p))
      ++p;
    if (!*p || *p == '#')
      continue;
    if (sscanf(p, "dependency %127s %3071s %c", name, relative, &extra) != 2) {
      dyn_diagnostic(&r->context, "error", path, line_number, 1, line_number, 1,
                     "dyn.project expects 'dependency NAME PATH'");
      result = 1;
      break;
    }
    if (strchr(name, '/') ||
        has(r->dependency_names, r->dependency_count, name)) {
      char message[256];
      snprintf(message, sizeof(message), "invalid or duplicate dependency '%s'",
               name);
      dyn_diagnostic(&r->context, "error", path, line_number, 1, line_number, 1,
                     message);
      result = 1;
      break;
    }
    char *candidate = dyn_path_join(r->root, relative);
    char *root = candidate ? realpath(candidate, NULL) : NULL;
    free(candidate);
    if (!root || !dyn_path_is_directory(root)) {
      char message[256];
      snprintf(message, sizeof(message),
               "dependency '%s' path does not resolve", name);
      dyn_diagnostic(&r->context, "error", path, line_number, 1, line_number, 1,
                     message);
      free(root);
      result = 1;
      break;
    }
    char **names = malloc((r->dependency_count + 1) * sizeof(char *));
    char **roots = malloc((r->dependency_count + 1) * sizeof(char *));
    if (!names || !roots) {
      free(names);
      free(roots);
      free(root);
      result = 2;
      break;
    }
    for (size_t i = 0; i < r->dependency_count; ++i) {
      names[i] = r->dependency_names[i];
      roots[i] = r->dependency_roots[i];
    }
    free(r->dependency_names);
    free(r->dependency_roots);
    r->dependency_names = names;
    r->dependency_roots = roots;
    r->dependency_names[r->dependency_count] = strdup(name);
    r->dependency_roots[r->dependency_count] = root;
    if (!r->dependency_names[r->dependency_count]) {
      free(root);
      result = 2;
      break;
    }
    ++r->dependency_count;
  }
  if (ferror(f))
    result = 1;
  fclose(f);
  free(path);
  return result;
}
char *dyn_module_resolve_import(const DynContext *context,
                                const char *project_root, const char *current,
                                const char *path) {
  char *root = realpath(project_root, NULL);
  if (!root)
    return NULL;
  Resolver r = {.root = root};
  if (context)
    r.context = *context;
  char *result = load_manifest(&r) ? NULL : resolve(&r, current, path);
  for (size_t i = 0; i < r.dependency_count; ++i) {
    free(r.dependency_names[i]);
    free(r.dependency_roots[i]);
  }
  free(r.dependency_names);
  free(r.dependency_roots);
  free(root);
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
  for (size_t i = 0; i < value->decl_count; ++i)
    free(value->decls[i].name);
  free(value->decls);
  memset(value, 0, sizeof(*value));
}
static int extract_interface(Resolver *r, const char *directory,
                             const DynSources *sources) {
  if (find_interface(r, directory))
    return 0;
  ModuleInterface value = {.directory = strdup(directory)};
  if (!value.directory)
    return 2;
  for (size_t si = 0; si < sources->count; ++si) {
    const DynSource *s = &sources->items[si];
    if (!dyn_work_step(&s->context, 1)) { free_interface(&value); return 2; }
    if (dyn_source_target_enabled(s) == 0)
      continue;
    TSTree *t = dyn_source_tree(s);
    if (!t) {
      free_interface(&value);
      return 2;
    }
    TSNode root = ts_tree_root_node(t);
    for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
      DynDeclaration declaration;
      if (!dyn_syntax_declaration(ts_node_named_child(root, i), &declaration))
        continue;
      TSNode n = declaration.name;
      char *text = dyn_syntax_copy_text(n, s, false);
      InterfaceDecl *next =
          text ? realloc(value.decls, (value.decl_count + 1) * sizeof(*next))
               : NULL;
      if (!text || !next) {
        free(text);
        ts_tree_delete(t);
        free_interface(&value);
        return 2;
      }
      value.decls = next;
      value.decls[value.decl_count++] =
          (InterfaceDecl){.name = text, .is_public = declaration.is_public};
    }
    ts_tree_delete(t);
  }
  ModuleInterface *next =
      realloc(r->interfaces, (r->interface_count + 1) * sizeof(*next));
  if (!next) {
    free_interface(&value);
    return 2;
  }
  r->interfaces = next;
  r->interfaces[r->interface_count++] = value;
  return 0;
}
static bool decl_named(Resolver *r, const char *directory, const char *name,
                       bool *is_public) {
  ModuleInterface *interface = find_interface(r, directory);
  if (!interface)
    return false;
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
static int validate_member(Resolver *r, TSNode n, const DynSource *s,
                           char **aliases, char **targets, size_t count,
                           const char *qualifier, const char *member) {
  size_t found = alias_index(aliases, count, qualifier);
  if (found < count) {
    bool pub = false;
    if (decl_named(r, targets[found], member, &pub) && pub)
      return 0;
    char message[512];
    snprintf(message, sizeof(message),
             "imported member '%s.%s' is missing or not pub", qualifier,
             member);
    dyn_syntax_diagnostic(n, s, "error", message);
    return 1;
  }
  if (imported_decl(r, targets, count, member)) {
    char message[512];
    snprintf(message, sizeof(message),
             "unknown import alias '%s' for member '%s'", qualifier, member);
    dyn_syntax_diagnostic(n, s, "error", message);
    return 1;
  }
  return 0;
}
static int validate_refs(Resolver *r, TSNode n, const DynSource *s,
                         const char *directory, char **aliases, char **targets,
                         size_t count, const DynScopeIndex *locals) {
  int errors = 0;
  const char *kind = ts_node_type(n);
  if (!strcmp(kind, "field_access")) {
    TSNode base = dyn_syntax_child(n, 0);
    if (strcmp(ts_node_type(base), "field_access")) {
      while (dyn_syntax_child_count(base) == 1)
        base = dyn_syntax_child(base, 0);
      if (!strcmp(ts_node_type(base), "identifier")) {
        char *qualifier = dyn_syntax_copy_text(base, s, false),
             *member =
                 dyn_syntax_copy_text(dyn_syntax_child(n, 1), s, false);
        if (!qualifier || !member) {
          free(qualifier);
          free(member);
          return 1;
        }
        // An exported member name does not make an arbitrary expression an
        // import qualifier. Ordinary fields are resolved by semantic analysis.
        if (alias_index(aliases, count, qualifier) < count &&
            !dyn_scope_local(locals, base, s, qualifier))
          errors += validate_member(r, n, s, aliases, targets, count, qualifier,
                                    member);
        free(qualifier);
        free(member);
      }
    }
  } else if (!strcmp(kind, "field_type")) {
    uint32_t names = dyn_syntax_child_count(n);
    if (names > 1) {
      char *qualifier =
               dyn_syntax_copy_text(dyn_syntax_child(n, 0), s, false),
           *member = dyn_syntax_copy_text(dyn_syntax_child(n, 1), s, false);
      if (!qualifier || !member) {
        free(qualifier);
        free(member);
        return 1;
      }
      if (!(dyn_syntax_value_type(n) && dyn_scope_local(locals, n, s, qualifier)))
        errors += validate_member(r, n, s, aliases, targets, count, qualifier, member);
      free(qualifier);
      free(member);
    } else if (names == 1) {
      char *name = dyn_syntax_copy_text(dyn_syntax_child(n, 0), s, false);
      if (!name)
        return 1;
      bool pub = false;
      if (!decl_named(r, directory, name, &pub) &&
          !(dyn_syntax_value_type(n) && dyn_scope_local(locals, n, s, name)) &&
          imported_decl(r, targets, count, name)) {
        char message[512];
        snprintf(message, sizeof(message),
                 "imported type '%s' must be module-qualified", name);
        dyn_syntax_diagnostic(n, s, "error", message);
        ++errors;
      }
      free(name);
    }
  } else if (!strcmp(kind, "call")) {
    TSNode callee = dyn_syntax_child(n, 0);
    while (dyn_syntax_child_count(callee) == 1)
      callee = dyn_syntax_child(callee, 0);
    if (!strcmp(ts_node_type(callee), "identifier")) {
      char *name = dyn_syntax_copy_text(callee, s, false);
      if (!name)
        return 1;
      bool pub = false;
      if (!decl_named(r, directory, name, &pub) &&
          !dyn_scope_local(locals, callee, s, name) &&
          imported_decl(r, targets, count, name)) {
        char message[512];
        snprintf(message, sizeof(message),
                 "imported function '%s' must be module-qualified", name);
        dyn_syntax_diagnostic(callee, s, "error", message);
        ++errors;
      }
      free(name);
    }
  } else if (!strcmp(kind, "struct_literal")) {
    uint32_t names = 0, total = dyn_syntax_child_count(n);
    while (names < total &&
           !strcmp(ts_node_type(dyn_syntax_child(n, names)), "identifier"))
      ++names;
    if (names > 1) {
      char *qualifier =
               dyn_syntax_copy_text(dyn_syntax_child(n, 0), s, false),
           *member = dyn_syntax_copy_text(dyn_syntax_child(n, 1), s, false);
      if (!qualifier || !member) {
        free(qualifier);
        free(member);
        return 1;
      }
      errors +=
          validate_member(r, n, s, aliases, targets, count, qualifier, member);
      free(qualifier);
      free(member);
    } else if (names == 1) {
      char *name = dyn_syntax_copy_text(dyn_syntax_child(n, 0), s, false);
      if (!name)
        return 1;
      bool pub = false;
      if (!decl_named(r, directory, name, &pub) &&
          imported_decl(r, targets, count, name)) {
        char message[512];
        snprintf(message, sizeof(message),
                 "imported type '%s' must be module-qualified", name);
        dyn_syntax_diagnostic(n, s, "error", message);
        ++errors;
      }
      free(name);
    }
  }
  TSTreeCursor children = ts_tree_cursor_new(n);
  if (ts_tree_cursor_goto_first_child(&children)) do {
    TSNode child = ts_tree_cursor_current_node(&children);
    if (ts_node_is_named(child))
      errors += validate_refs(r, child, s, directory, aliases, targets, count, locals);
  } while (ts_tree_cursor_goto_next_sibling(&children));
  ts_tree_cursor_delete(&children);
  return errors;
}
static int visit(Resolver *r, const char *directory,
                 const DynSources *provided) {
  if (has(r->visited, r->visited_count, directory))
    return 0;
  if (r->stack_count >= 256 || !dyn_work_step(&r->context, 1)) {
    dyn_diagnostic(&r->context, "error", directory, 1, 1, 1, 1,
                   r->stack_count >= 256 ? "module dependency depth exceeds 256" :
                                           "analysis work budget exceeded");
    return 1;
  }
  if (!push(&r->stack, &r->stack_count, directory))
    return 2;
  DynSources owned = {0};
  const DynSources *sources = provided;
  if (!sources) {
    int e = dyn_sources_load(&r->context, directory, &owned);
    if (e) {
      pop(r->stack, &r->stack_count);
      return e;
    }
    sources = &owned;
  } else if (r->overrides) {
    for (size_t i = 0; i < provided->count; ++i)
      if (!append_source(&owned, &provided->items[i])) {
        dyn_sources_free(&owned);
        pop(r->stack, &r->stack_count);
        return 2;
      }
    sources = &owned;
  }
  if (r->overrides &&
      !apply_overrides(&r->context, &owned, r->overrides, directory)) {
    dyn_sources_free(&owned);
    pop(r->stack, &r->stack_count);
    return 2;
  }
  int result = 0;
  result = extract_interface(r, directory, sources);
  char **aliases = NULL, **targets = NULL;
  size_t alias_count = 0, target_count = 0;
  for (size_t si = 0; si < sources->count && !result; ++si) {
    if (!dyn_work_step(&r->context, 1)) { result = 2; break; }
    if (dyn_source_target_enabled(&sources->items[si]) == 0)
      continue;
    const DynSource *s = &sources->items[si];
    TSTree *t = dyn_source_tree(s);
    if (!t) {
      result = 2;
      break;
    }
    TSNode root = ts_tree_root_node(t);
    for (uint32_t i = 0; i < ts_node_named_child_count(root) && !result; ++i) {
      TSNode d = dyn_syntax_declaration_node(ts_node_named_child(root, i));
      if (strcmp(ts_node_type(d), "use"))
        continue;
      char *path = dyn_syntax_copy_text(
          ts_node_child_by_field_name(d, "path", 4), s, true);
      if (!path) {
        dyn_syntax_diagnostic(d, s, "error", "incomplete import path");
        result = 1;
        break;
      }
      char *target = resolve(r, directory, path);
      TSNode an = ts_node_child_by_field_name(d, "alias", 5);
      char *alias = ts_node_is_null(an) ? dyn_path_basename(path)
                                        : dyn_syntax_copy_text(an, s, false);
      if (!alias) {
        free(path);
        free(target);
        result = 2;
        break;
      }
      if (has(aliases, alias_count, alias)) {
        char message[512];
        snprintf(message, sizeof(message), "duplicate import alias '%s'",
                 alias);
        dyn_syntax_diagnostic(d, s, "error", message);
        result = 1;
      } else if (!target || !dyn_path_is_directory(target)) {
        char message[512];
        snprintf(message, sizeof(message),
                 "import '%s' does not resolve inside project root", path);
        dyn_syntax_diagnostic(d, s, "error", message);
        result = 1;
      } else if (has(r->stack, r->stack_count, target)) {
        char message[2048] = "cyclic import: ";
        size_t at = strlen(message), first = 0;
        while (first < r->stack_count && strcmp(r->stack[first], target))
          ++first;
        for (size_t j = first; j <= r->stack_count && at < sizeof(message) - 1;
             ++j) {
          const char *item = j == r->stack_count ? target : r->stack[j];
          const char *base = strrchr(item, '/');
          int written = snprintf(message + at, sizeof(message) - at, "%s%s",
                                 base ? base + 1 : item,
                                 j == r->stack_count ? "" : " -> ");
          if (written < 0 || (size_t)written >= sizeof(message) - at)
            break;
          at += (size_t)written;
        }
        dyn_syntax_diagnostic(d, s, "error", message);
        result = 1;
      } else {
        if (has(targets, target_count, target)) {
          char message[512];
          snprintf(
              message, sizeof(message),
              "module '%s' is imported more than once under different aliases",
              path);
          dyn_syntax_diagnostic(d, s, "warning", message);
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
    if (!dyn_work_step(&r->context, 1)) { result = 2; break; }
    if (dyn_source_target_enabled(&sources->items[si]) == 0)
      continue;
    const DynSource *s = &sources->items[si];
    TSTree *t = dyn_source_tree(s);
    DynScopeIndex locals = {0};
    if (!t || !dyn_scope_build(&locals, ts_tree_root_node(t), s)) result = 2;
    else result += validate_refs(r, ts_tree_root_node(t), s, directory, aliases,
                                targets, alias_count, &locals);
    dyn_scope_free(&locals);
    if (t) ts_tree_delete(t);
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
  if (root_sources->count)
    r.context = root_sources->items[0].context;
  else if (overrides && overrides->count)
    r.context = overrides->items[0].context;
  int result = load_manifest(&r);
  if (!result)
    result = visit(&r, root, root_sources);
  if (!result && out)
    result = dyn_module_rewrite_project(root, out);
  for (size_t i = 0; i < r.visited_count; ++i)
    free(r.visited[i]);
  free(r.visited);
  free(r.stack);
  for (size_t i = 0; i < r.dependency_count; ++i) {
    free(r.dependency_names[i]);
    free(r.dependency_roots[i]);
  }
  free(r.dependency_names);
  free(r.dependency_roots);
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
