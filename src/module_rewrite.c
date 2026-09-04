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
  char *name;
} Decl;
typedef struct {
  char *name;
  char *target;
} Alias;
typedef struct {
  char *dir;
  Decl *decls;
  size_t decl_count;
  Alias *aliases;
  size_t alias_count;
  bool root;
} Module;
typedef struct {
  uint32_t start, end;
  char *text;
} Edit;
typedef struct {
  Edit *items;
  size_t count;
} Edits;

static char *rewrite_std_path(const char *path) {
  char executable[4096], relative[4096];
  ssize_t n = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
  if (n < 0)
    return NULL;
  executable[n] = 0;
  char *slash = strrchr(executable, '/');
  if (!slash)
    return NULL;
  *slash = 0;
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

static char *text_of(TSNode n, const DynSource *s) {
  uint32_t a = ts_node_start_byte(n), b = ts_node_end_byte(n);
  char *r = malloc((size_t)(b - a) + 1);
  if (!r)
    return NULL;
  memcpy(r, s->text + a, b - a);
  r[b - a] = 0;
  return r;
}
static TSNode rewrite_unwrap(TSNode n) {
  while (ts_node_named_child_count(n) == 1)
    n = ts_node_named_child(n, 0);
  return n;
}
static TSNode rewrite_declaration_value(TSNode n) {
  return !strcmp(ts_node_type(n), "declaration")
             ? ts_node_named_child(n, ts_node_named_child_count(n) - 1)
             : n;
}
static TSNode global_name_node(TSNode n) {
  if (!strcmp(ts_node_type(n), "const_variable"))
    n = ts_node_named_child(n, 0);
  return !strcmp(ts_node_type(n), "variable") ? ts_node_named_child(n, 0)
                                              : (TSNode){0};
}
static bool top_level_node(TSNode n) {
  TSNode p = ts_node_parent(n);
  if (!strcmp(ts_node_type(p), "declaration"))
    p = ts_node_parent(p);
  return !strcmp(ts_node_type(p), "source_file");
}
static char *source_dir(const char *path) {
  char *full = realpath(path, NULL);
  if (!full)
    return NULL;
  char *slash = strrchr(full, '/');
  if (slash && slash != full)
    *slash = 0;
  return full;
}
static Module *find_module(Module *modules, size_t count, const char *dir) {
  for (size_t i = 0; i < count; ++i)
    if (!strcmp(modules[i].dir, dir))
      return &modules[i];
  return NULL;
}
static bool add_decl(Module *m, const char *name) {
  for (size_t i = 0; i < m->decl_count; ++i)
    if (!strcmp(m->decls[i].name, name))
      return true;
  Decl *p = realloc(m->decls, (m->decl_count + 1) * sizeof(*p));
  if (!p)
    return false;
  m->decls = p;
  p[m->decl_count].name = strdup(name);
  if (!p[m->decl_count].name)
    return false;
  ++m->decl_count;
  return true;
}
static bool add_alias(Module *m, const char *name, const char *target) {
  Alias *p = realloc(m->aliases, (m->alias_count + 1) * sizeof(*p));
  if (!p)
    return false;
  m->aliases = p;
  p[m->alias_count] = (Alias){strdup(name), strdup(target)};
  if (!p[m->alias_count].name || !p[m->alias_count].target)
    return false;
  ++m->alias_count;
  return true;
}
static bool has_decl(const Module *m, const char *name) {
  for (size_t i = 0; i < m->decl_count; ++i)
    if (!strcmp(m->decls[i].name, name))
      return true;
  return false;
}
static const char *alias_target(const Module *m, const char *name) {
  for (size_t i = 0; i < m->alias_count; ++i)
    if (!strcmp(m->aliases[i].name, name))
      return m->aliases[i].target;
  return NULL;
}
static uint64_t hash_path(const char *s) {
  uint64_t h = UINT64_C(1469598103934665603);
  for (; *s; ++s) {
    h ^= (unsigned char)*s;
    h *= UINT64_C(1099511628211);
  }
  return h;
}
static char *symbol(const Module *m, const char *name) {
  if (m->root)
    return strdup(name);
  int n = snprintf(NULL, 0, "dyn_m%016llx_%s",
                   (unsigned long long)hash_path(m->dir), name);
  char *r = malloc((size_t)n + 1);
  if (r)
    snprintf(r, (size_t)n + 1, "dyn_m%016llx_%s",
             (unsigned long long)hash_path(m->dir), name);
  return r;
}
static bool add_edit(Edits *e, TSNode n, char *replacement) {
  if (!replacement)
    return false;
  uint32_t start = ts_node_start_byte(n), end = ts_node_end_byte(n);
  for (size_t i = 0; i < e->count; ++i)
    if (e->items[i].start == start && e->items[i].end == end) {
      free(replacement);
      return true;
    }
  Edit *p = realloc(e->items, (e->count + 1) * sizeof(*p));
  if (!p) {
    free(replacement);
    return false;
  }
  e->items = p;
  p[e->count++] = (Edit){start, end, replacement};
  return true;
}
static Module *target_module(Module *modules, size_t count,
                             const Module *current, const char *alias) {
  const char *dir = alias_target(current, alias);
  return dir ? find_module(modules, count, dir) : NULL;
}
static bool rewrite_node(TSNode n, const DynSource *s, Module *current,
                         Module *modules, size_t module_count, Edits *edits) {
  const char *k = ts_node_type(n);
  if (!strcmp(k, "fn") || !strcmp(k, "extern_fn") || !strcmp(k, "struct") ||
      !strcmp(k, "enum") || !strcmp(k, "type_alias")) {
    TSNode name = {0};
    if (!strcmp(k, "fn") || !strcmp(k, "extern_fn"))
      name = ts_node_child_by_field_name(n, "name", 4);
    else
      for (uint32_t i = 0; i < ts_node_named_child_count(n); ++i) {
        TSNode c = ts_node_named_child(n, i);
        if (!strcmp(ts_node_type(c), "identifier")) {
          name = c;
          break;
        }
      }
    if (!current->root && !ts_node_is_null(name)) {
      char *t = text_of(name, s), *replacement = t ? symbol(current, t) : NULL;
      free(t);
      if (!add_edit(edits, name, replacement))
        return false;
    }
  }
  if ((!strcmp(k, "variable") || !strcmp(k, "const_variable")) &&
      top_level_node(n)) {
    TSNode name = global_name_node(n);
    if (!current->root && !ts_node_is_null(name)) {
      char *t = text_of(name, s), *replacement = t ? symbol(current, t) : NULL;
      free(t);
      if (!add_edit(edits, name, replacement))
        return false;
    }
  }
  if (!strcmp(k, "field_type")) {
    uint32_t count = ts_node_named_child_count(n);
    char *first = count ? text_of(ts_node_named_child(n, 0), s) : NULL;
    if (count > 1 && first) {
      Module *target = target_module(modules, module_count, current, first);
      if (target) {
        char *member = text_of(ts_node_named_child(n, 1), s),
             *replacement = member ? symbol(target, member) : NULL;
        free(member);
        free(first);
        return add_edit(edits, n, replacement);
      }
    }
    if (count == 1 && first && has_decl(current, first)) {
      char *replacement = symbol(current, first);
      free(first);
      return add_edit(edits, n, replacement);
    }
    free(first);
  }
  if (!strcmp(k, "struct_literal")) {
    uint32_t names = 0, total = ts_node_named_child_count(n);
    while (names < total &&
           !strcmp(ts_node_type(ts_node_named_child(n, names)), "identifier"))
      ++names;
    if (names > 1) {
      TSNode a = ts_node_named_child(n, 0), b = ts_node_named_child(n, 1);
      char *first = text_of(a, s);
      Module *target =
          first ? target_module(modules, module_count, current, first) : NULL;
      if (target) {
        char *member = text_of(b, s),
             *replacement = member ? symbol(target, member) : NULL;
        uint32_t start = ts_node_start_byte(a), end = ts_node_end_byte(b);
        free(member);
        free(first);
        if (!replacement)
          return false;
        Edit *p = realloc(edits->items, (edits->count + 1) * sizeof(*p));
        if (!p) {
          free(replacement);
          return false;
        }
        edits->items = p;
        p[edits->count++] = (Edit){start, end, replacement};
        goto children;
      }
      free(first);
    } else if (names == 1) {
      TSNode name = ts_node_named_child(n, 0);
      char *t = text_of(name, s);
      if (t && has_decl(current, t)) {
        char *replacement = symbol(current, t);
        free(t);
        if (!add_edit(edits, name, replacement))
          return false;
      } else
        free(t);
    }
  }
  if (!strcmp(k, "field_access")) {
    TSNode base = rewrite_unwrap(ts_node_named_child(n, 0));
    if (!strcmp(ts_node_type(base), "identifier")) {
      char *first = text_of(base, s);
      Module *target =
          first ? target_module(modules, module_count, current, first) : NULL;
      if (target) {
        char *member = text_of(ts_node_named_child(n, 1), s),
             *replacement = member ? symbol(target, member) : NULL;
        free(member);
        free(first);
        return add_edit(edits, n, replacement);
      }
      if (first && has_decl(current, first)) {
        char *replacement = symbol(current, first);
        free(first);
        if (!add_edit(edits, base, replacement))
          return false;
      } else
        free(first);
    }
  }
  if (!strcmp(k, "call")) {
    TSNode callee = rewrite_unwrap(ts_node_named_child(n, 0));
    if (!strcmp(ts_node_type(callee), "identifier")) {
      char *t = text_of(callee, s);
      if (t && has_decl(current, t)) {
        char *replacement = symbol(current, t);
        free(t);
        if (!add_edit(edits, callee, replacement))
          return false;
      } else
        free(t);
    }
  }
  if (!strcmp(k, "primary") && ts_node_named_child_count(n) == 1) {
    TSNode child = ts_node_named_child(n, 0);
    if (!strcmp(ts_node_type(child), "identifier")) {
      char *t = text_of(child, s);
      if (t && has_decl(current, t)) {
        char *replacement = symbol(current, t);
        free(t);
        if (!add_edit(edits, child, replacement))
          return false;
      } else
        free(t);
    }
  }
children:
  for (uint32_t i = 0; i < ts_node_named_child_count(n); ++i)
    if (!rewrite_node(ts_node_named_child(n, i), s, current, modules,
                      module_count, edits))
      return false;
  return true;
}
static int edit_compare(const void *a, const void *b) {
  const Edit *x = a, *y = b;
  return x->start < y->start ? -1 : x->start > y->start ? 1 : 0;
}
static bool apply_edits(DynSource *s, Edits *e) {
  if (!e->count)
    return true;
  qsort(e->items, e->count, sizeof(*e->items), edit_compare);
  size_t size = s->length, previous = 0;
  for (size_t i = 0; i < e->count; ++i) {
    if (e->items[i].start < previous)
      return false;
    previous = e->items[i].end;
    size =
        size - (e->items[i].end - e->items[i].start) + strlen(e->items[i].text);
  }
  char *out = malloc(size + 1);
  if (!out)
    return false;
  size_t in = 0, at = 0;
  for (size_t i = 0; i < e->count; ++i) {
    size_t chunk = e->items[i].start - in;
    memcpy(out + at, s->text + in, chunk);
    at += chunk;
    size_t n = strlen(e->items[i].text);
    memcpy(out + at, e->items[i].text, n);
    at += n;
    in = e->items[i].end;
  }
  memcpy(out + at, s->text + in, s->length - in);
  at += s->length - in;
  out[at] = 0;
  free(s->text);
  s->text = out;
  s->length = at;
  return true;
}
static bool normalize_default_imports(DynSource *s) {
  Edits edits = {0};
  size_t line = 0;
  while (line < s->length) {
    size_t end = line;
    while (end < s->length && s->text[end] != '\n')
      ++end;
    size_t p = line;
    while (p < end && (s->text[p] == ' ' || s->text[p] == '\t'))
      ++p;
    if (p + 4 < end && !memcmp(s->text + p, "use ", 4)) {
      size_t quote = p + 4;
      while (quote < end && s->text[quote] != '"')
        ++quote;
      if (quote < end) {
        size_t close = quote + 1;
        while (close < end && s->text[close] != '"')
          ++close;
        if (close < end) {
          size_t rest = close + 1;
          while (rest < end && (s->text[rest] == ' ' || s->text[rest] == '\t' ||
                                s->text[rest] == '\r'))
            ++rest;
          if (rest == end) {
            size_t n = close - quote - 1;
            char *path = malloc(n + 1);
            if (!path)
              goto fail;
            memcpy(path, s->text + quote + 1, n);
            path[n] = 0;
            char *base = dyn_path_basename(path);
            free(path);
            if (!base)
              goto fail;
            size_t bn = strlen(base);
            char *replacement = malloc(bn + 2);
            if (!replacement) {
              free(base);
              goto fail;
            }
            replacement[0] = ' ';
            memcpy(replacement + 1, base, bn + 1);
            free(base);
            Edit *q = realloc(edits.items, (edits.count + 1) * sizeof(*q));
            if (!q) {
              free(replacement);
              goto fail;
            }
            edits.items = q;
            q[edits.count++] = (Edit){(uint32_t)(close + 1),
                                      (uint32_t)(close + 1), replacement};
          }
        }
      }
    }
    line = end < s->length ? end + 1 : end;
  }
  if (!apply_edits(s, &edits))
    goto fail;
  for (size_t i = 0; i < edits.count; ++i)
    free(edits.items[i].text);
  free(edits.items);
  return true;
fail:
  for (size_t i = 0; i < edits.count; ++i)
    free(edits.items[i].text);
  free(edits.items);
  return false;
}
static void free_modules(Module *m, size_t count) {
  for (size_t i = 0; i < count; ++i) {
    free(m[i].dir);
    for (size_t j = 0; j < m[i].decl_count; ++j)
      free(m[i].decls[j].name);
    free(m[i].decls);
    for (size_t j = 0; j < m[i].alias_count; ++j) {
      free(m[i].aliases[j].name);
      free(m[i].aliases[j].target);
    }
    free(m[i].aliases);
  }
  free(m);
}
int dyn_module_rewrite_project(const char *project_root, DynSources *sources) {
  char *root = realpath(project_root, NULL);
  if (!root)
    return 1;
  Module *modules = NULL;
  size_t module_count = 0;
  int result = 0;
  for (size_t i = 0; i < sources->count && !result; ++i)
    if (!normalize_default_imports(&sources->items[i]))
      result = 2;
  for (size_t i = 0; i < sources->count && !result; ++i) {
    char *dir = source_dir(sources->items[i].path);
    if (!dir) {
      result = 2;
      break;
    }
    if (!find_module(modules, module_count, dir)) {
      Module *p = realloc(modules, (module_count + 1) * sizeof(*p));
      if (!p) {
        free(dir);
        result = 2;
        break;
      }
      modules = p;
      modules[module_count] = (Module){.dir = dir, .root = !strcmp(dir, root)};
      ++module_count;
    } else
      free(dir);
  }
  TSParser *p = ts_parser_new();
  if (!p || !ts_parser_set_language(p, tree_sitter_dyn()))
    result = 2;
  for (size_t si = 0; si < sources->count && !result; ++si) {
    if (dyn_source_target_enabled(&sources->items[si]) == 0) continue;
    DynSource *s = &sources->items[si];
    char *dir = source_dir(s->path);
    Module *m = find_module(modules, module_count, dir);
    free(dir);
    TSTree *t = ts_parser_parse_string(p, NULL, s->text, (uint32_t)s->length);
    TSNode file = ts_tree_root_node(t);
    for (uint32_t i = 0; i < ts_node_named_child_count(file) && !result; ++i) {
      TSNode d = rewrite_declaration_value(ts_node_named_child(file, i));
      const char *k = ts_node_type(d);
      if (!strcmp(k, "fn") || !strcmp(k, "extern_fn") ||
          !strcmp(k, "struct") || !strcmp(k, "enum") || !strcmp(k, "type_alias")) {
        TSNode name = {0};
        if (!strcmp(k, "fn") || !strcmp(k, "extern_fn"))
          name = ts_node_child_by_field_name(d, "name", 4);
        else
          for (uint32_t q = 0; q < ts_node_named_child_count(d); ++q)
            if (!strcmp(ts_node_type(ts_node_named_child(d, q)),
                        "identifier")) {
              name = ts_node_named_child(d, q);
              break;
            }
        char *n = text_of(name, s);
        if (!n || !add_decl(m, n))
          result = 2;
        free(n);
      } else if (!strcmp(k, "use")) {
        char *path = text_of(ts_node_named_child(d, 0), s);
        if (path) {
          size_t n = strlen(path);
          if (n >= 2) {
            memmove(path, path + 1, n - 2);
            path[n - 2] = 0;
          }
        }
        char *candidate =
            path && strncmp(path, "std/", 4)
                ? ((!strncmp(path, "./", 2) || !strncmp(path, "../", 3))
                       ? dyn_path_join(m->dir, path)
                       : dyn_path_join(root, path))
                : NULL;
        char *target = path && !strncmp(path, "std/", 4)
                           ? rewrite_std_path(path)
                           : (candidate ? realpath(candidate, NULL) : NULL);
        TSNode an = ts_node_named_child_count(d) > 1 ? ts_node_named_child(d, 1)
                                                     : (TSNode){0};
        char *alias = ts_node_is_null(an) ? dyn_path_basename(path ? path : "")
                                          : text_of(an, s);
        if (!target || !alias || !add_alias(m, alias, target))
          result = 2;
        free(path);
        free(candidate);
        free(target);
        free(alias);
      }
    }
    ts_tree_delete(t);
  }
  for (size_t si = 0; si < sources->count && !result; ++si) {
    if (dyn_source_target_enabled(&sources->items[si]) == 0) continue;
    DynSource *s = &sources->items[si];
    char *dir = source_dir(s->path);
    Module *m = find_module(modules, module_count, dir);
    free(dir);
    TSTree *t = ts_parser_parse_string(p, NULL, s->text, (uint32_t)s->length);
    TSNode file = ts_tree_root_node(t);
    for (uint32_t i = 0; i < ts_node_named_child_count(file) && !result; ++i) {
      TSNode d = rewrite_declaration_value(ts_node_named_child(file, i)),
             name = global_name_node(d);
      if (!ts_node_is_null(name)) {
        char *n = text_of(name, s);
        if (!n || !add_decl(m, n))
          result = 2;
        free(n);
      }
    }
    ts_tree_delete(t);
  }
  for (size_t si = 0; si < sources->count && !result; ++si) {
    if (dyn_source_target_enabled(&sources->items[si]) == 0) continue;
    DynSource *s = &sources->items[si];
    char *dir = source_dir(s->path);
    Module *m = find_module(modules, module_count, dir);
    free(dir);
    TSTree *t = ts_parser_parse_string(p, NULL, s->text, (uint32_t)s->length);
    Edits edits = {0};
    if (!rewrite_node(ts_tree_root_node(t), s, m, modules, module_count,
                      &edits) ||
        !apply_edits(s, &edits))
      result = 2;
    for (size_t i = 0; i < edits.count; ++i)
      free(edits.items[i].text);
    free(edits.items);
    ts_tree_delete(t);
  }
  if (p)
    ts_parser_delete(p);
  free_modules(modules, module_count);
  free(root);
  if (result)
    fprintf(stderr,
            "error: failed to create module-qualified compiler symbols\n");
  return result;
}
