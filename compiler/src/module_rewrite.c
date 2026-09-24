#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include "dyn_syntax.h"
#include "dyn_scope.h"
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
  uint64_t abi;
} Module;
typedef struct {
  uint32_t start, end;
  char *text;
  TSPoint start_point, end_point;
} Edit;
typedef struct {
  Edit *items;
  size_t count, capacity;
} Edits;

static TSNode rewrite_unwrap(TSNode n) {
  while (dyn_syntax_child_count(n) == 1)
    n = dyn_syntax_child(n, 0);
  return n;
}
static TSNode global_name_node(TSNode node) {
  DynDeclaration declaration;
  return dyn_syntax_declaration(node, &declaration) &&
                 (declaration.kind == DYN_DECL_VARIABLE ||
                  declaration.kind == DYN_DECL_CONSTANT)
             ? declaration.name
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
  if (!full) {
    // An editor overlay may name a file which has not been saved yet.
    char *parent = strdup(path);
    if (!parent)
      return NULL;
    char *separator = strrchr(parent, '/');
    if (separator) {
      if (separator == parent)
        separator[1] = 0;
      else
        *separator = 0;
    } else {
      free(parent);
      parent = strdup(".");
      if (!parent)
        return NULL;
    }
    full = realpath(parent, NULL);
    free(parent);
    return full;
  }
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
  if (!p[m->alias_count].name || !p[m->alias_count].target) {
    free(p[m->alias_count].name);
    free(p[m->alias_count].target);
    p[m->alias_count] = (Alias){0};
    return false;
  }
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
/* Collect once, then sort/deduplicate. Tree traversal can revisit a name. */
static bool append_edit(Edits *e, Edit edit) {
  if (!edit.text) return false;
  if (e->count == e->capacity) {
    size_t capacity = e->capacity ? e->capacity * 2 : 32;
    if (capacity < e->capacity || capacity > SIZE_MAX / sizeof(*e->items)) {
      free(edit.text); return false;
    }
    Edit *items = realloc(e->items, capacity * sizeof(*items));
    if (!items) { free(edit.text); return false; }
    e->items = items; e->capacity = capacity;
  }
  e->items[e->count++] = edit;
  return true;
}
static bool add_edit(Edits *e, TSNode n, char *replacement) {
  return append_edit(e, (Edit){ts_node_start_byte(n), ts_node_end_byte(n),
      replacement, ts_node_start_point(n), ts_node_end_point(n)});
}
static Module *target_module(Module *modules, size_t count,
                             const Module *current, const char *alias) {
  const char *dir = alias_target(current, alias);
  return dir ? find_module(modules, count, dir) : NULL;
}
static bool rewrite_node(TSNode n, const DynSource *s, Module *current,
                         Module *modules, size_t module_count, Edits *edits,
                         const DynScopeIndex *locals) {
  /* Missing syntax is handled by frontend diagnostics, not allocation errors.
   */
  if (ts_node_is_error(n) || ts_node_is_missing(n))
    return true;
  if (ts_node_has_error(n))
    for (uint32_t i = 0; i < ts_node_named_child_count(n); ++i)
      if (ts_node_is_missing(ts_node_named_child(n, i))) goto children;
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
      char *t = dyn_syntax_copy_text(name, s, false),
           *replacement = t ? symbol(current, t) : NULL;
      if (!t)
        return false;
      free(t);
      if (!add_edit(edits, name, replacement))
        return false;
    }
  }
  if ((!strcmp(k, "variable") || !strcmp(k, "const_variable") ||
       !strcmp(k, "extern_variable")) &&
      top_level_node(n)) {
    TSNode name = global_name_node(n);
    if (!current->root && !ts_node_is_null(name)) {
      char *t = dyn_syntax_copy_text(name, s, false),
           *replacement = t ? symbol(current, t) : NULL;
      if (!t)
        return false;
      free(t);
      if (!add_edit(edits, name, replacement))
        return false;
    }
  }
  if (!strcmp(k, "field_type")) {
    uint32_t count = dyn_syntax_child_count(n);
    char *first =
        count ? dyn_syntax_copy_text(dyn_syntax_child(n, 0), s, false)
              : NULL;
    if (count && !first)
      return false;
    if (first && dyn_syntax_value_type(n) && dyn_scope_local(locals, n, s, first)) {
      free(first);
      return true;
    }
    if (count > 1) {
      Module *target = target_module(modules, module_count, current, first);
      if (target) {
        char *member =
                 dyn_syntax_copy_text(dyn_syntax_child(n, 1), s, false),
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
    uint32_t names = 0, total = dyn_syntax_child_count(n);
    while (names < total &&
           !strcmp(ts_node_type(dyn_syntax_child(n, names)), "identifier"))
      ++names;
    if (names > 1) {
      TSNode a = dyn_syntax_child(n, 0), b = dyn_syntax_child(n, 1);
      char *first = dyn_syntax_copy_text(a, s, false);
      if (!first)
        return false;
      Module *target =
          first ? target_module(modules, module_count, current, first) : NULL;
      if (target) {
        char *member = dyn_syntax_copy_text(b, s, false),
             *replacement = member ? symbol(target, member) : NULL;
        uint32_t start = ts_node_start_byte(a), end = ts_node_end_byte(b);
        free(member);
        free(first);
        if (!replacement)
          return false;
        if (!append_edit(edits, (Edit){start, end, replacement,
                ts_node_start_point(a), ts_node_end_point(b)}))
          return false;
        goto children;
      }
      free(first);
    } else if (names == 1) {
      TSNode name = dyn_syntax_child(n, 0);
      char *t = dyn_syntax_copy_text(name, s, false);
      if (!t)
        return false;
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
    TSNode base = rewrite_unwrap(dyn_syntax_child(n, 0));
    if (!ts_node_is_missing(base) &&
        !strcmp(ts_node_type(base), "identifier")) {
      char *first = dyn_syntax_copy_text(base, s, false);
      if (!first)
        return false;
      Module *target =
          first ? target_module(modules, module_count, current, first) : NULL;
      if (target && !dyn_scope_local(locals, base, s, first)) {
        char *member =
                 dyn_syntax_copy_text(dyn_syntax_child(n, 1), s, false),
             *replacement = member ? symbol(target, member) : NULL;
        free(member);
        free(first);
        return add_edit(edits, n, replacement);
      }
      if (first && has_decl(current, first) && !dyn_scope_local(locals, base, s, first)) {
        char *replacement = symbol(current, first);
        free(first);
        if (!add_edit(edits, base, replacement))
          return false;
      } else
        free(first);
    }
  }
  if (!strcmp(k, "call")) {
    TSNode callee = rewrite_unwrap(dyn_syntax_child(n, 0));
    if (!ts_node_is_missing(callee) &&
        !strcmp(ts_node_type(callee), "identifier")) {
      char *t = dyn_syntax_copy_text(callee, s, false);
      if (!t)
        return false;
      if (t && has_decl(current, t) && !dyn_scope_local(locals, n, s, t)) {
        char *replacement = symbol(current, t);
        free(t);
        if (!add_edit(edits, callee, replacement))
          return false;
      } else
        free(t);
    }
  }
  if (!strcmp(k, "primary") && dyn_syntax_child_count(n) == 1) {
    TSNode child = dyn_syntax_child(n, 0);
    if (!strcmp(ts_node_type(child), "identifier")) {
      char *t = dyn_syntax_copy_text(child, s, false);
      if (!t)
        return false;
      if (t && has_decl(current, t) && !dyn_scope_local(locals, n, s, t)) {
        char *replacement = symbol(current, t);
        free(t);
        if (!add_edit(edits, child, replacement))
          return false;
      } else
        free(t);
    }
  }
children:;
  TSTreeCursor cursor = ts_tree_cursor_new(n);
  bool ok = true;
  if (ts_tree_cursor_goto_first_child(&cursor)) do {
    TSNode child = ts_tree_cursor_current_node(&cursor);
    if (ts_node_is_named(child) &&
        !rewrite_node(child, s, current, modules, module_count, edits, locals)) {
      ok = false; break;
    }
  } while (ts_tree_cursor_goto_next_sibling(&cursor));
  ts_tree_cursor_delete(&cursor);
  return ok;
}
static int edit_compare(const void *a, const void *b) {
  const Edit *x = a, *y = b;
  if (x->start != y->start) return x->start < y->start ? -1 : 1;
  return x->end < y->end ? -1 : x->end > y->end ? 1 : 0;
}
static size_t original_offset(const DynSource *s, size_t offset) {
  size_t first = 0, end = s->span_count;
  while (first < end) {
    size_t middle = first + (end - first) / 2;
    if (s->spans[middle].generated_end < offset) first = middle + 1;
    else end = middle;
  }
  if (first < s->span_count) {
    DynSourceSpan p = s->spans[first];
    if (offset >= p.generated_start && offset <= p.generated_end) {
      size_t gn = p.generated_end - p.generated_start,
             on = p.original_end - p.original_start;
      return p.original_start +
             (gn ? (offset - p.generated_start) * on / gn : 0);
    }
  }
  return offset;
}
static bool add_span(DynSourceSpan **items, size_t *count, size_t *capacity, size_t gs, size_t ge,
                     size_t os, size_t oe) {
  if (ge == gs && oe == os)
    return true;
  if (*count == *capacity) {
    size_t next = *capacity ? *capacity * 2 : 32;
    if (next < *capacity || next > SIZE_MAX / sizeof(**items)) return false;
    DynSourceSpan *p = realloc(*items, next * sizeof(*p));
    if (!p) return false;
    *items = p; *capacity = next;
  }
  (*items)[(*count)++] = (DynSourceSpan){gs, ge, os, oe};
  return true;
}
static bool copy_spans(const DynSource *s, DynSourceSpan **out, size_t *count,
                       size_t *capacity, size_t *cursor,
                       size_t from, size_t to, size_t at) {
  while (*cursor < s->span_count && s->spans[*cursor].generated_end <= from) ++*cursor;
  for (size_t i = *cursor; i < s->span_count; ++i) {
    DynSourceSpan p = s->spans[i];
    if (p.generated_start >= to) break;
    size_t a = from > p.generated_start ? from : p.generated_start,
           b = to < p.generated_end ? to : p.generated_end;
    if (a >= b)
      continue;
    size_t os = original_offset(s, a), oe = original_offset(s, b);
    if (!add_span(out, count, capacity, at + (a - from), at + (b - from), os, oe))
      return false;
  }
  return true;
}
static bool apply_edits(DynSource *s, Edits *e) {
  if (!e->count)
    return true;
  qsort(e->items, e->count, sizeof(*e->items), edit_compare);
  size_t unique = 0;
  for (size_t i = 0; i < e->count; ++i) {
    if (unique && e->items[unique - 1].start == e->items[i].start &&
        e->items[unique - 1].end == e->items[i].end) {
      /* Duplicate rewrites must agree; never select an arbitrary replacement. */
      if (strcmp(e->items[unique - 1].text, e->items[i].text)) return false;
      free(e->items[i].text);
    } else e->items[unique++] = e->items[i];
    if (unique - 1 != i) e->items[i].text = NULL;
  }
  e->count = unique;
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
  if (!s->original_text) {
    s->original_text = strdup(s->text);
    if (!s->original_text) {
      free(out);
      return false;
    }
    s->original_length = s->length;
    s->spans = malloc(sizeof(*s->spans));
    if (!s->spans) {
      free(out);
      return false;
    }
    s->spans[0] = (DynSourceSpan){0, s->length, 0, s->length};
    s->span_count = 1;
  }
  DynSourceSpan *spans = NULL;
  size_t span_count = 0, span_capacity = 0, span_cursor = 0;
  size_t in = 0, at = 0;
  for (size_t i = 0; i < e->count; ++i) {
    size_t chunk = e->items[i].start - in;
    if (!copy_spans(s, &spans, &span_count, &span_capacity, &span_cursor, in, e->items[i].start, at)) {
      free(out);
      free(spans);
      return false;
    }
    memcpy(out + at, s->text + in, chunk);
    at += chunk;
    size_t n = strlen(e->items[i].text);
    if (!add_span(&spans, &span_count, &span_capacity, at, at + n,
                  original_offset(s, e->items[i].start),
                  original_offset(s, e->items[i].end))) {
      free(out);
      free(spans);
      return false;
    }
    memcpy(out + at, e->items[i].text, n);
    at += n;
    in = e->items[i].end;
  }
  if (!copy_spans(s, &spans, &span_count, &span_capacity, &span_cursor, in, s->length, at)) {
    free(out);
    free(spans);
    return false;
  }
  memcpy(out + at, s->text + in, s->length - in);
  at += s->length - in;
  out[at] = 0;
  /* Edit from the end so earlier node coordinates remain valid. Incremental
     parsing can then retain large unchanged function bodies and literal tables. */
  if (s->syntax)
    for (size_t i = e->count; i; --i) {
      const Edit *item = &e->items[i - 1];
      size_t length = strlen(item->text);
      TSInputEdit edit = {item->start, item->end, item->start + (uint32_t)length,
          item->start_point, item->end_point,
          dyn_syntax_advance(item->start_point, item->text, length)};
      ts_tree_edit(s->syntax, &edit);
    }
  TSTree *tree = dyn_syntax_reparse(out, at, s->syntax);
  dyn_source_discard_syntax(s);
  s->syntax = tree;
  free(s->text);
  free(s->spans);
  s->text = out;
  s->length = at;
  s->spans = spans;
  s->span_count = span_count;
  return s->syntax != NULL;
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
/* Hash declarations, never function implementations. Include private types and
   constants because public signatures and constant expressions can expose them.
   Syntax ranges avoid matching "pub " inside comments and string literals. */
static uint64_t rewrite_hash(uint64_t hash, const void *data, size_t length) {
  const unsigned char *bytes = data;
  for (size_t i = 0; i < length; ++i)
    hash = (hash ^ bytes[i]) * UINT64_C(1099511628211);
  return hash;
}
static bool capture_dependencies(DynSources *sources, Module *modules, size_t count) {
  bool reflection = false;
  size_t *owners = calloc(sources->count, sizeof(*owners));
  bool *selected = calloc(count, sizeof(*selected));
  if (!owners || !selected) { free(owners); free(selected); return false; }
  for (size_t i = 0; i < count; ++i) modules[i].abi = hash_path(modules[i].dir);
  for (size_t i = 0; i < sources->count; ++i) {
    DynSource *source = &sources->items[i];
    char *dir = source_dir(source->path);
    Module *module = dir ? find_module(modules, count, dir) : NULL;
    free(dir);
    if (!module) { free(owners); free(selected); return false; }
    owners[i] = (size_t)(module - modules);
    if (!dyn_source_target_enabled(source)) continue;
    TSTree *tree = dyn_source_tree(source);
    if (!tree) { free(owners); free(selected); return false; }
    TSNode root = ts_tree_root_node(tree);
    reflection |= source->needs_reflection ||
        (strstr(source->text, "#typeof") && dyn_syntax_has_reflection(root));
    for (uint32_t j = 0; j < ts_node_named_child_count(root); ++j) {
      TSNode wrapper = ts_node_named_child(root, j);
      TSNode node = dyn_syntax_declaration_node(wrapper);
      const char *kind = ts_node_type(node);
      if (!strcmp(kind, "comment") || !strcmp(kind, "use")) continue;
      uint32_t start = ts_node_start_byte(wrapper), end = ts_node_end_byte(wrapper);
      if (!strcmp(kind, "fn")) {
        if (!dyn_syntax_public(wrapper)) continue;
        for (uint32_t k = 0; k < ts_node_named_child_count(node); ++k) {
          TSNode child = ts_node_named_child(node, k);
          if (!strcmp(ts_node_type(child), "block")) { end = ts_node_start_byte(child); break; }
        }
      }
      size_t length = end - start;
      module->abi = rewrite_hash(module->abi, &length, sizeof(length));
      module->abi = rewrite_hash(module->abi, source->text + start, length);
    }
    ts_tree_delete(tree);
  }
  for (size_t i = 0; i < sources->count; ++i) {
    if (i && owners[i] == owners[i - 1]) continue;
    memset(selected, reflection ? 1 : 0, count * sizeof(*selected));
    selected[owners[i]] = true;
    bool changed = true;
    while (changed) {
      changed = false;
      for (size_t j = 0; j < count; ++j) if (selected[j])
        for (size_t k = 0; k < modules[j].alias_count; ++k) {
          Module *target = find_module(modules, count, modules[j].aliases[k].target);
          if (target && !selected[target - modules]) {
            selected[target - modules] = true; changed = true;
          }
        }
    }
    DynSource *source = &sources->items[i];
    size_t needed = 0;
    for (size_t j = 0; j < sources->count; ++j) needed += selected[owners[j]];
    source->dependency_sources = malloc(needed * sizeof(size_t));
    if (!source->dependency_sources) { free(owners); free(selected); return false; }
    uint64_t hash = UINT64_C(1469598103934665603);
    hash = rewrite_hash(hash, &reflection, sizeof(reflection));
    for (size_t j = 0; j < count; ++j) if (selected[j])
      hash = rewrite_hash(hash, &modules[j].abi, sizeof(modules[j].abi));
    /* Reflection can expose types introduced while lowering implementations.
       Keep that uncommon case conservative, including enabling/disabling it. */
    if (reflection)
      for (size_t j = 0; j < sources->count; ++j)
        hash = rewrite_hash(hash, sources->items[j].text, sources->items[j].length);
    for (size_t j = 0; j < sources->count; ++j) if (selected[owners[j]])
      source->dependency_sources[source->dependency_count++] = j;
    source->dependency_hash = hash ? hash : 1;
  }
  free(owners); free(selected);
  return true;
}
int dyn_module_rewrite_project(const char *project_root, DynSources *sources) {
  char *root = realpath(project_root, NULL);
  if (!root)
    return 1;
  Module *modules = NULL;
  size_t module_count = 0;
  int result = 0;
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
  for (size_t si = 0; si < sources->count && !result; ++si) {
    if (dyn_source_target_enabled(&sources->items[si]) == 0)
      continue;
    DynSource *s = &sources->items[si];
    char *dir = source_dir(s->path);
    Module *m = find_module(modules, module_count, dir);
    free(dir);
    TSTree *t = dyn_source_tree(s);
    if (!t) {
      result = 2;
      break;
    }
    TSNode file = ts_tree_root_node(t);
    for (uint32_t i = 0; i < ts_node_named_child_count(file) && !result; ++i) {
      TSNode d = dyn_syntax_declaration_node(ts_node_named_child(file, i));
      const char *k = ts_node_type(d);
      if (!strcmp(k, "fn") || !strcmp(k, "extern_fn") ||
          !strcmp(k, "extern_variable") || !strcmp(k, "struct") ||
          !strcmp(k, "enum") || !strcmp(k, "type_alias")) {
        TSNode name = {0};
        if (!strcmp(k, "fn") || !strcmp(k, "extern_fn") ||
            !strcmp(k, "extern_variable"))
          name = ts_node_child_by_field_name(d, "name", 4);
        else
          for (uint32_t q = 0; q < ts_node_named_child_count(d); ++q)
            if (!strcmp(ts_node_type(ts_node_named_child(d, q)),
                        "identifier")) {
              name = ts_node_named_child(d, q);
              break;
            }
        char *n = dyn_syntax_copy_text(name, s, false);
        if (!n || !add_decl(m, n))
          result = 2;
        free(n);
      } else if (!strcmp(k, "use")) {
        char *path = dyn_syntax_copy_text(
            ts_node_child_by_field_name(d, "path", 4), s, true);
        char *target =
            path ? dyn_module_resolve_import(&s->context, root, m->dir, path)
                 : NULL;
        TSNode an = ts_node_child_by_field_name(d, "alias", 5);
        char *alias = ts_node_is_null(an) ? dyn_path_basename(path ? path : "")
                                          : dyn_syntax_copy_text(an, s, false);
        if (!target || !alias || !add_alias(m, alias, target))
          result = 2;
        free(path);
        free(target);
        free(alias);
      }
    }
    ts_tree_delete(t);
  }
  for (size_t si = 0; si < sources->count && !result; ++si) {
    if (dyn_source_target_enabled(&sources->items[si]) == 0)
      continue;
    DynSource *s = &sources->items[si];
    char *dir = source_dir(s->path);
    Module *m = find_module(modules, module_count, dir);
    free(dir);
    TSTree *t = dyn_source_tree(s);
    if (!t) {
      result = 2;
      break;
    }
    TSNode file = ts_tree_root_node(t);
    for (uint32_t i = 0; i < ts_node_named_child_count(file) && !result; ++i) {
      TSNode d = dyn_syntax_declaration_node(ts_node_named_child(file, i)),
             name = global_name_node(d);
      if (!ts_node_is_null(name)) {
        char *n = dyn_syntax_copy_text(name, s, false);
        if (!n || !add_decl(m, n))
          result = 2;
        free(n);
      }
    }
    ts_tree_delete(t);
  }
  for (size_t si = 0; si < sources->count && !result; ++si) {
    if (dyn_source_target_enabled(&sources->items[si]) == 0)
      continue;
    DynSource *s = &sources->items[si];
    char *dir = source_dir(s->path);
    Module *m = find_module(modules, module_count, dir);
    free(dir);
    TSTree *t = dyn_source_tree(s);
    if (!t) {
      result = 2;
      break;
    }
    Edits edits = {0};
    DynScopeIndex locals = {0};
    if (!dyn_scope_build(&locals, ts_tree_root_node(t), s) ||
        !rewrite_node(ts_tree_root_node(t), s, m, modules, module_count,
                      &edits, &locals) ||
        !apply_edits(s, &edits))
      result = 2;
    for (size_t i = 0; i < edits.count; ++i)
      free(edits.items[i].text);
    free(edits.items);
    dyn_scope_free(&locals);
    ts_tree_delete(t);
  }
  if (!result && !capture_dependencies(sources, modules, module_count)) result = 2;
  free_modules(modules, module_count);
  free(root);
  if (result)
    fprintf(stderr,
            "error: failed to create module-qualified compiler symbols\n");
  return result;
}
