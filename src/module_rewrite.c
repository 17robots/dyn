#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include "dyn_scope.h"
#include "dyn_imports.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stdatomic.h>
#ifndef _WIN32
#include <pthread.h>
#endif
extern char *realpath(const char *, char *);

typedef struct {
  char *name;
} Decl;
typedef struct {
  char *name;
  char *target;
  char *path;
} Alias;
typedef struct {
  char *dir;
  Decl *decls;
  size_t decl_count, decl_capacity;
  size_t *decl_buckets;
  size_t decl_bucket_capacity;
  Alias *aliases;
  size_t alias_count;
  bool root;
  uint64_t abi;
} Module;
typedef struct {
  uint32_t start, end;
  char *text;
} Edit;
typedef struct {
  Edit *items;
  size_t count, capacity;
} Edits;

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
static uint64_t declaration_hash(const char *name) {
  uint64_t hash = UINT64_C(14695981039346656037);
  for (; *name; ++name)
    hash = (hash ^ (unsigned char)*name) * UINT64_C(1099511628211);
  return hash;
}
static bool has_decl(const Module *m, const char *name) {
  if (!m->decl_bucket_capacity)
    return false;
  size_t mask = m->decl_bucket_capacity - 1;
  size_t slot = declaration_hash(name) & mask;
  while (m->decl_buckets[slot]) {
    if (!strcmp(m->decls[m->decl_buckets[slot] - 1].name, name))
      return true;
    slot = (slot + 1) & mask;
  }
  return false;
}
static bool add_decl(Module *m, const char *name) {
  if (has_decl(m, name))
    return true;
  if (m->decl_count == m->decl_capacity) {
    size_t capacity = m->decl_capacity ? m->decl_capacity * 2 : 16;
    if (capacity < m->decl_capacity || capacity > SIZE_MAX / sizeof(*m->decls))
      return false;
    Decl *decls = realloc(m->decls, capacity * sizeof(*decls));
    if (!decls)
      return false;
    m->decls = decls;
    m->decl_capacity = capacity;
  }
  if (m->decl_count >= m->decl_bucket_capacity / 2) {
    size_t capacity = m->decl_bucket_capacity ? m->decl_bucket_capacity * 2 : 32;
    if (capacity < m->decl_bucket_capacity ||
        capacity > SIZE_MAX / sizeof(*m->decl_buckets))
      return false;
    size_t *buckets = calloc(capacity, sizeof(*buckets));
    if (!buckets)
      return false;
    for (size_t i = 0; i < m->decl_count; ++i) {
      size_t slot = declaration_hash(m->decls[i].name) & (capacity - 1);
      while (buckets[slot])
        slot = (slot + 1) & (capacity - 1);
      buckets[slot] = i + 1;
    }
    free(m->decl_buckets);
    m->decl_buckets = buckets;
    m->decl_bucket_capacity = capacity;
  }
  char *copy = strdup(name);
  if (!copy)
    return false;
  size_t slot = declaration_hash(name) & (m->decl_bucket_capacity - 1);
  while (m->decl_buckets[slot])
    slot = (slot + 1) & (m->decl_bucket_capacity - 1);
  m->decls[m->decl_count++].name = copy;
  m->decl_buckets[slot] = m->decl_count;
  return true;
}
static bool add_alias(Module *m, const char *name, const char *target, const char *path) {
  for (size_t i = 0; i < m->alias_count; ++i)
    if (!strcmp(m->aliases[i].name, name))
      return !strcmp(m->aliases[i].target, target);
  Alias *p = realloc(m->aliases, (m->alias_count + 1) * sizeof(*p));
  if (!p)
    return false;
  m->aliases = p;
  p[m->alias_count] = (Alias){strdup(name), strdup(target), strdup(path)};
  if (!p[m->alias_count].name || !p[m->alias_count].target || !p[m->alias_count].path) {
    free(p[m->alias_count].name);
    free(p[m->alias_count].target);
    free(p[m->alias_count].path);
    p[m->alias_count] = (Alias){0};
    return false;
  }
  ++m->alias_count;
  return true;
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
static Module *target_module(Module *modules, size_t count,
                             const Module *current, const char *alias) {
  const char *dir = alias_target(current, alias);
  return dir ? find_module(modules, count, dir) : NULL;
}
#include "module_compact_rewrite.h"
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
/* The edits rename a name, or collapse alias.member (an expression field, a
   type path or a struct literal's type) into one name. Parsing the edited
   text gives the same tree with those spans moved and each collapsed pair
   as one name node, so the tree is patched here instead. */
typedef struct {
  const ExpNode *old;
  const Edit *edits;
  size_t edit_count, matched;
  int64_t *shift; /* shift[k]: growth of the text through edit k */
  ExpNode *nodes;
  uint32_t count;
  bool failed;
} TreePatch;
static const Edit *patch_edit(const TreePatch *p, uint32_t start, uint32_t end) {
  size_t lo = 0, hi = p->edit_count;
  while (lo < hi) {
    size_t mid = (lo + hi) / 2;
    if (p->edits[mid].start < start) lo = mid + 1; else hi = mid;
  }
  return lo < p->edit_count && p->edits[lo].start == start && p->edits[lo].end == end ? &p->edits[lo] : NULL;
}
/* Offsets inside an edit belong to nodes the edit removed. */
static uint32_t patch_offset(TreePatch *p, uint32_t offset) {
  size_t lo = 0, hi = p->edit_count;
  while (lo < hi) {
    size_t mid = (lo + hi) / 2;
    if (p->edits[mid].end <= offset) lo = mid + 1; else hi = mid;
  }
  if (lo < p->edit_count && p->edits[lo].start < offset) p->failed = true;
  return (uint32_t)((int64_t)offset + (lo ? p->shift[lo - 1] : 0));
}
static uint32_t patch_copy(TreePatch *p, uint32_t id, uint32_t parent) {
  uint32_t at = p->count++;
  ExpNode node = p->old[id];
  node.start = patch_offset(p, node.start);
  node.end = patch_offset(p, node.end);
  if (node.operator_length) node.operator_start = patch_offset(p, node.operator_start);
  node.parent = parent;
  node.first = node.next = UINT32_MAX;
  p->nodes[at] = node;
  return at;
}
/* A name spanning the replacement of edit, in place of old node id. */
static uint32_t patch_name(TreePatch *p, uint32_t id, uint32_t parent, const Edit *edit) {
  uint32_t at = p->count++, start = patch_offset(p, edit->start);
  ExpNode node = p->old[id];
  node.kind = EXP_NAME;
  node.start = start;
  node.end = start + (uint32_t)strlen(edit->text);
  node.parent = parent;
  node.first = node.next = UINT32_MAX;
  p->nodes[at] = node;
  ++p->matched;
  return at;
}
static uint32_t patch_node(TreePatch *p, uint32_t id, uint32_t parent) {
  const ExpNode *old = &p->old[id];
  const Edit *edit = patch_edit(p, old->start, old->end);
  if (edit && old->kind == EXP_FIELD) return patch_name(p, id, parent, edit);
  uint32_t at = patch_copy(p, id, parent), child = old->first, last = UINT32_MAX;
  if (edit && old->kind == EXP_NAME && old->first == UINT32_MAX) ++p->matched;
  else if (edit && old->kind == EXP_FIELD_TYPE && child != UINT32_MAX && p->old[child].kind == EXP_NAME) {
    p->nodes[at].first = patch_name(p, child, at, edit);
    return at;
  } else if (old->kind == EXP_STRUCT && child != UINT32_MAX && p->old[child].kind == EXP_NAME) {
    uint32_t second = p->old[child].next;
    const Edit *pair = second != UINT32_MAX && p->old[second].kind == EXP_NAME
                           ? patch_edit(p, p->old[child].start, p->old[second].end) : NULL;
    if (pair) {
      last = p->nodes[at].first = patch_name(p, child, at, pair);
      child = p->old[second].next;
    }
  }
  for (; child != UINT32_MAX && !p->failed; child = p->old[child].next) {
    uint32_t copy = patch_node(p, child, at);
    if (last == UINT32_MAX) p->nodes[at].first = copy;
    else p->nodes[last].next = copy;
    last = copy;
  }
  return at;
}
/* NULL when an edit does not fit those shapes, and the caller reparses, or
   when allocation fails, which sets *oom. */
static ExpSnapshot *patch_tree(const ExpSnapshotTree *tree, const Edits *e, const char *text, size_t length,
                               bool *oom) {
  if (!tree || tree->error_count || tree->root == UINT32_MAX) return NULL;
  TreePatch p = {.old = tree->nodes, .edits = e->items, .edit_count = e->count};
  p.shift = malloc(e->count * sizeof(*p.shift));
  p.nodes = malloc((size_t)tree->count * sizeof(*p.nodes));
  if (!p.shift || !p.nodes) {
    free(p.shift);
    free(p.nodes);
    *oom = true;
    return NULL;
  }
  int64_t growth = 0;
  for (size_t i = 0; i < e->count && !p.failed; ++i) {
    if (e->items[i].start >= e->items[i].end) p.failed = true;
    growth += (int64_t)strlen(e->items[i].text) - (e->items[i].end - e->items[i].start);
    p.shift[i] = growth;
  }
  uint32_t root = p.failed ? UINT32_MAX : patch_node(&p, tree->root, UINT32_MAX);
  free(p.shift);
  if (p.failed || p.matched != e->count) {
    free(p.nodes);
    return NULL;
  }
  /* Only collapsed pairs drop nodes, so the slack is small. */
  ExpSnapshot *snapshot = exp_snapshot_adopt(text, length, p.nodes, p.count, root);
  if (!snapshot) *oom = true;
  return snapshot;
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
    s->original_text = malloc(s->length + 1);
    if (!s->original_text) {
      free(out);
      return false;
    }
    memcpy(s->original_text, s->text, s->length);
    s->original_text[s->length] = 0;
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
  /* Budgeted analysis charges parsing work, so it keeps the parse. */
  bool oom = false;
  ExpSnapshot *patched = s->context.work ? NULL : patch_tree(dyn_compact_tree(s), e, out, at, &oom);
  if (oom) {
    free(out);
    free(spans);
    return false;
  }
  dyn_source_discard_syntax(s);
  free(s->text);
  free(s->spans);
  s->text = out;
  s->length = at;
  s->spans = spans;
  s->span_count = span_count;
  /* Rewritten text must not replace the cached parse of the file on disk. */
  DynSyntaxCache *cache = s->context.syntax_cache;
  s->context.syntax_cache = NULL;
  s->compact = patched;
  bool prepared = dyn_source_prepare(s);
  s->context.syntax_cache = cache;
  return prepared;
}
static void free_modules(Module *m, size_t count) {
  for (size_t i = 0; i < count; ++i) {
    free(m[i].dir);
    for (size_t j = 0; j < m[i].decl_count; ++j)
      free(m[i].decls[j].name);
    free(m[i].decls);
    free(m[i].decl_buckets);
    for (size_t j = 0; j < m[i].alias_count; ++j) {
      free(m[i].aliases[j].name);
      free(m[i].aliases[j].target);
      free(m[i].aliases[j].path);
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
static bool compact_rewrite_abi(const DynSource *source, const ExpSnapshotTree *tree, Module *module) {
  const ExpNode *nodes = tree->nodes;
  for (uint32_t wrapper = nodes[tree->root].first; wrapper != UINT32_MAX; wrapper = nodes[wrapper].next) {
    if (!dyn_work_step(&source->context, 1)) return false;
    uint32_t node = nodes[wrapper].kind == SRC_DECLARATION ? nodes[wrapper].first : wrapper;
    if (node == UINT32_MAX || nodes[node].kind == SRC_USE) continue;
    uint32_t start = nodes[wrapper].start, end = nodes[wrapper].end;
    if (nodes[node].kind == SRC_FN) {
      if (!(nodes[wrapper].flags & EXP_PUBLIC)) continue;
      for (uint32_t child = nodes[node].first; child != UINT32_MAX; child = nodes[child].next) {
        if (!dyn_work_step(&source->context, 1)) return false;
        if (nodes[child].kind == SRC_BLOCK) { end = nodes[child].start; break; }
      }
    }
    size_t length = end - start;
    if (!dyn_work_step(&source->context, length)) return false;
    module->abi = rewrite_hash(module->abi, &length, sizeof(length));
    module->abi = rewrite_hash(module->abi, source->text + start, length);
  }
  return true;
}
static bool compact_rewrite_declarations(const DynSource *source, const ExpSnapshotTree *tree,
                                          Module *module, bool globals) {
  const ExpNode *nodes = tree->nodes;
  for (uint32_t wrapper = nodes[tree->root].first; wrapper != UINT32_MAX; wrapper = nodes[wrapper].next) {
    if (!dyn_work_step(&source->context, 1)) return false;
    if (nodes[wrapper].kind != SRC_DECLARATION) continue;
    uint32_t node = nodes[wrapper].first;
    if (node == UINT32_MAX) continue;
    bool global = nodes[node].kind == SRC_VARIABLE || nodes[node].kind == SRC_CONST;
    if (global != globals) continue;
    uint32_t name = dyn_compact_name(tree, wrapper);
    if (name == UINT32_MAX) continue;
    char *text = compact_rewrite_text(source, tree, name);
    bool ok = text && add_decl(module, text);
    free(text);
    if (!ok) return false;
  }
  return true;
}
static bool compact_rewrite_imports(const DynSource *source, Module *module, const char *root) {
  DynImports reader;
  if (!dyn_imports_open(&reader, source)) return false;
  DynImportView view;
  bool ok = true;
  while (ok && dyn_imports_next(&reader, &view)) {
    char *path = dyn_import_copy(view.path, view.path_length);
    const char *cached = NULL;
    for (size_t i = 0; path && i < module->alias_count; ++i)
      if (!strcmp(module->aliases[i].path, path)) {
        cached = module->aliases[i].target;
        break;
      }
    char *target = cached ? strdup(cached) :
        (path ? dyn_module_resolve_import(&source->context, root, module->dir, path) : NULL);
    char *alias = view.alias_node ? dyn_import_copy(view.alias, view.alias_length)
                                 : dyn_path_basename(path ? path : "");
    ok = target && alias && add_alias(module, alias, target, path);
    free(path); free(target); free(alias);
  }
  ok = ok && !reader.failed;
  dyn_imports_close(&reader);
  return ok;
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
    const ExpSnapshotTree *compact = dyn_compact_tree(source);
    if (!compact) { free(owners); free(selected); return false; }
    reflection |= source->needs_reflection || source->compact_reflection;
    if (!compact_rewrite_abi(source, compact, module)) { free(owners); free(selected); return false; }
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
typedef struct {
  DynSources *sources;
  Module *modules;
  size_t module_count;
  atomic_size_t next;
  atomic_bool failed;
} RewriteJobs;
/* Each source rewrites independently against the read-only module tables. */
static bool rewrite_source(DynSource *s, Module *modules, size_t module_count) {
  char *dir = source_dir(s->path);
  Module *m = dir ? find_module(modules, module_count, dir) : NULL;
  free(dir);
  const ExpSnapshotTree *tree = dyn_compact_tree(s);
  if (!m || !tree) return false;
  Edits edits = {0};
  DynScopeIndex locals = {0};
  bool ok = dyn_scope_build(&locals, s) &&
            compact_rewrite_nodes(s, tree, m, modules, module_count, &edits, &locals) &&
            apply_edits(s, &edits);
  for (size_t i = 0; i < edits.count; ++i)
    free(edits.items[i].text);
  free(edits.items);
  dyn_scope_free(&locals);
  return ok;
}
static void *rewrite_worker(void *raw) {
  RewriteJobs *jobs = raw;
  for (;;) {
    size_t i = atomic_fetch_add(&jobs->next, 1);
    if (i >= jobs->sources->count || atomic_load(&jobs->failed))
      return NULL;
    DynSource *s = &jobs->sources->items[i];
    if (dyn_source_target_enabled(s) != 0 &&
        !rewrite_source(s, jobs->modules, jobs->module_count))
      atomic_store(&jobs->failed, true);
  }
}
static void rewrite_parallel(RewriteJobs *jobs, const DynSources *sources) {
#ifndef _WIN32
  size_t workers = 1;
  /* Budgeted and cached editor analysis share mutable context state. */
  const DynContext *context = sources->count ? &sources->items[0].context : NULL;
  long online = sysconf(_SC_NPROCESSORS_ONLN);
  if (context && !context->work && !context->syntax_cache && online > 1)
    workers = (size_t)online;
  if (workers > sources->count)
    workers = sources->count;
  if (workers > 256)
    workers = 256;
  pthread_t threads[256];
  size_t started = 0;
  for (; started + 1 < workers; ++started)
    if (pthread_create(&threads[started], NULL, rewrite_worker, jobs))
      break;
  rewrite_worker(jobs);
  for (size_t i = 0; i < started; ++i)
    pthread_join(threads[i], NULL);
#else
  (void)sources;
  rewrite_worker(jobs);
#endif
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
    const ExpSnapshotTree *compact = dyn_compact_tree(s);
    if (!compact || !compact_rewrite_declarations(s, compact, m, false) ||
        !compact_rewrite_imports(s, m, root)) result = 2;
  }
  for (size_t si = 0; si < sources->count && !result; ++si) {
    if (dyn_source_target_enabled(&sources->items[si]) == 0)
      continue;
    DynSource *s = &sources->items[si];
    char *dir = source_dir(s->path);
    Module *m = find_module(modules, module_count, dir);
    free(dir);
    const ExpSnapshotTree *compact = dyn_compact_tree(s);
    if (!compact || !compact_rewrite_declarations(s, compact, m, true)) result = 2;
  }
  if (!result) {
    RewriteJobs jobs = {.sources = sources, .modules = modules,
                        .module_count = module_count};
    atomic_init(&jobs.next, 0);
    atomic_init(&jobs.failed, false);
    rewrite_parallel(&jobs, sources);
    if (atomic_load(&jobs.failed))
      result = 2;
  }
  if (!result && !capture_dependencies(sources, modules, module_count)) result = 2;
  free_modules(modules, module_count);
  free(root);
  if (result)
    fprintf(stderr,
            "error: failed to create module-qualified compiler symbols\n");
  return result;
}
