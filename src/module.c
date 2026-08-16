#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <tree_sitter/api.h>
#include <unistd.h>
extern const TSLanguage *tree_sitter_dyn(void);
extern char *realpath(const char *, char *);

typedef struct {
  char **visited;
  size_t visited_count;
  char **stack;
  size_t stack_count;
  char *root;
  DynSources *out;
} Resolver;
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
static bool within(const char *root, const char *path) {
  size_t n = strlen(root);
  return !strncmp(root, path, n) && (path[n] == 0 || path[n] == '/');
}
static char *resolve_std(const char *path) {
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
    return realpath(relative, NULL);
  return NULL;
}
static char *resolve(Resolver *r, const char *current, const char *path) {
  if (!strncmp(path, "std/", 4))
    return resolve_std(path);
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
static bool decl_named(const char *directory, const char *name,
                       bool *is_public) {
  DynSources sources = {0};
  if (dyn_sources_load(directory, &sources))
    return false;
  TSParser *p = ts_parser_new();
  bool found = false;
  if (p && ts_parser_set_language(p, tree_sitter_dyn()))
    for (size_t si = 0; si < sources.count && !found; ++si) {
      DynSource *s = &sources.items[si];
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
        if (strcmp(k, "fn") && strcmp(k, "foreign_fn") &&
            strcmp(k, "struct") && strcmp(k, "enum") &&
            strcmp(k, "variable"))
          continue;
        TSNode n = (!strcmp(k, "fn") || !strcmp(k, "foreign_fn"))
                       ? ts_node_child_by_field_name(d, "name", 4)
                                    : ts_node_named_child(d, 0);
        char *text = node_text(n, s, false);
        if (!strcmp(text, name)) {
          found = true;
          uint32_t at = ts_node_start_byte(wrapper);
          *is_public = at + 3 <= s->length && !memcmp(s->text + at, "pub", 3);
        }
        free(text);
      }
      ts_tree_delete(t);
    }
  if (p)
    ts_parser_delete(p);
  dyn_sources_free(&sources);
  return found;
}
static size_t alias_index(char **aliases, size_t count, const char *name) {
  for (size_t i = 0; i < count; ++i)
    if (!strcmp(aliases[i], name))
      return i;
  return count;
}
static bool imported_decl(char **targets, size_t count, const char *name) {
  for (size_t i = 0; i < count; ++i) {
    bool pub = false;
    if (decl_named(targets[i], name, &pub))
      return true;
  }
  return false;
}
static int validate_member(TSNode n, const DynSource *s, char **aliases,
                           char **targets, size_t count, const char *qualifier,
                           const char *member) {
  size_t found = alias_index(aliases, count, qualifier);
  if (found < count) {
    bool pub = false;
    if (decl_named(targets[found], member, &pub) && pub)
      return 0;
    TSPoint p = ts_node_start_point(n);
    fprintf(stderr,
            "%s:%u:%u: error: imported member '%s.%s' is missing or not pub\n",
            s->path, p.row + 1, p.column + 1, qualifier, member);
    return 1;
  }
  if (imported_decl(targets, count, member)) {
    TSPoint p = ts_node_start_point(n);
    fprintf(stderr,
            "%s:%u:%u: error: unknown import alias '%s' for member '%s'\n",
            s->path, p.row + 1, p.column + 1, qualifier, member);
    return 1;
  }
  return 0;
}
static int validate_refs(TSNode n, const DynSource *s, const char *directory,
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
            validate_member(n, s, aliases, targets, count, qualifier, member);
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
          validate_member(n, s, aliases, targets, count, qualifier, member);
      free(qualifier);
      free(member);
    } else if (names == 1) {
      char *name = node_text(ts_node_named_child(n, 0), s, false);
      bool pub = false;
      if (!decl_named(directory, name, &pub) &&
          imported_decl(targets, count, name)) {
        TSPoint p = ts_node_start_point(n);
        fprintf(
            stderr,
            "%s:%u:%u: error: imported type '%s' must be module-qualified\n",
            s->path, p.row + 1, p.column + 1, name);
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
      if (!decl_named(directory, name, &pub) &&
          imported_decl(targets, count, name)) {
        TSPoint p = ts_node_start_point(callee);
        fprintf(stderr,
                "%s:%u:%u: error: imported function '%s' must be "
                "module-qualified\n",
                s->path, p.row + 1, p.column + 1, name);
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
          validate_member(n, s, aliases, targets, count, qualifier, member);
      free(qualifier);
      free(member);
    } else if (names == 1) {
      char *name = node_text(ts_node_named_child(n, 0), s, false);
      bool pub = false;
      if (!decl_named(directory, name, &pub) &&
          imported_decl(targets, count, name)) {
        TSPoint p = ts_node_start_point(n);
        fprintf(
            stderr,
            "%s:%u:%u: error: imported type '%s' must be module-qualified\n",
            s->path, p.row + 1, p.column + 1, name);
        ++errors;
      }
      free(name);
    }
  }
  for (uint32_t i = 0; i < ts_node_named_child_count(n); ++i)
    errors += validate_refs(ts_node_named_child(n, i), s, directory, aliases,
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
    sources = &owned;
  }
  int result = 0;
  TSParser *p = ts_parser_new();
  if (!p || !ts_parser_set_language(p, tree_sitter_dyn()))
    result = 2;
  char **aliases = NULL, **targets = NULL;
  size_t alias_count = 0, target_count = 0;
  for (size_t si = 0; si < sources->count && !result; ++si) {
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
        TSPoint q = ts_node_start_point(d);
        fprintf(stderr, "%s:%u:%u: error: duplicate import alias '%s'\n",
                s->path, q.row + 1, q.column + 1, alias);
        result = 1;
      } else if (!target || !dyn_path_is_directory(target)) {
        TSPoint q = ts_node_start_point(d);
        fprintf(stderr,
                "%s:%u:%u: error: import '%s' does not resolve inside project "
                "root\n",
                s->path, q.row + 1, q.column + 1, path);
        result = 1;
      } else {
        if (has(targets, target_count, target)) {
          TSPoint q = ts_node_start_point(d);
          fprintf(stderr,
                  "%s:%u:%u: warning: module '%s' is imported more than once "
                  "under different aliases\n",
                  s->path, q.row + 1, q.column + 1, path);
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
    const DynSource *s = &sources->items[si];
    TSTree *t = ts_parser_parse_string(p, NULL, s->text, (uint32_t)s->length);
    result += validate_refs(ts_tree_root_node(t), s, directory, aliases,
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
                DynSources *out) {
  if (out)
    memset(out, 0, sizeof(*out));
  char *root = realpath(project_root, NULL);
  if (!root)
    return 1;
  Resolver r = {.root = root, .out = out};
  int result = visit(&r, root, root_sources);
  if (!result && out)
    result = dyn_module_rewrite_project(root, out);
  for (size_t i = 0; i < r.visited_count; ++i)
    free(r.visited[i]);
  free(r.visited);
  free(r.stack);
  free(root);
  if (result && out)
    dyn_sources_free(out);
  return result;
}
int dyn_module_validate_imports(const char *root, const DynSources *sources) {
  return load(root, sources, NULL);
}
int dyn_module_load_project(const char *root, const DynSources *sources,
                            DynSources *out) {
  return load(root, sources, out);
}
