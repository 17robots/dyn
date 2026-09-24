#define _POSIX_C_SOURCE 200809L
#include "lsp_internal.h"

typedef struct {
  const char *text;
  size_t length;
} LspIdentifier;
typedef struct {
  const char *path;
  unsigned line, column;
  bool used;
} LspBinding;
typedef struct {
  LspIdentifier *items;
  size_t count, capacity;
  DynSources sources;
  LspSemantic semantic;
  LspBinding *bindings;
  size_t binding_count;
  bool complete, borrowed;
} LspUsage;
static void lsp_collect_diagnostic(const char *severity, const char *path,
                                   unsigned line, unsigned column,
                                   unsigned end_line, unsigned end_column,
                                   const char *message, void *context);
static int lsp_identifier_compare(const void *left, const void *right);
static bool lsp_usage_collect(LspUsage *usage, TSNode node, const char *text);
static int lsp_binding_compare(const void *left, const void *right);
static void lsp_binding_index(LspUsage *usage);
static LspUsage lsp_usage_build(LspDocument *documents, size_t count,
                                LspDocument *document, const LspSemantic *semantic);
static size_t lsp_usage_count(const LspUsage *usage, const char *name);
static void lsp_usage_free(LspUsage *usage);
static bool lsp_binding_used(const LspUsage *usage, LspDocument *document,
                             TSNode name);
static void lsp_unused_nodes(TSNode node, LspDocument *document,
                             const LspUsage *usage, char *body, size_t capacity,
                             size_t *at, bool *comma);
static bool lsp_overlay_sources(DynSources *sources, LspDocument *documents,
                                size_t count);
static LspSemantic lsp_snapshot_view(DynAnalysisSnapshot *snapshot);

static void lsp_collect_diagnostic(const char *severity, const char *path,
                                   unsigned line, unsigned column,
                                   unsigned end_line, unsigned end_column,
                                   const char *message, void *context) {
  LspDiagnostics *all = context;
  if (all->allocation_failed) return;
  if (all->count == all->capacity) {
    size_t capacity = all->capacity ? all->capacity * 2 : 64;
    if (capacity < all->capacity || capacity > SIZE_MAX / sizeof(*all->items)) {
      all->allocation_failed = true; return;
    }
    LspDiagnostic *items = realloc(all->items, capacity * sizeof(*items));
    if (!items) { all->allocation_failed = true; return; }
    all->items = items; all->capacity = capacity;
  }
  LspDiagnostic *item = &all->items[all->count++];
  snprintf(item->severity, sizeof(item->severity), "%s",
           severity ? severity : "error");
  snprintf(item->path, sizeof(item->path), "%s", path ? path : "");
  snprintf(item->message, sizeof(item->message), "%s",
           message ? message : "diagnostic");
  item->line = line;
  item->column = column;
  item->end_line = end_line;
  item->end_column = end_column;
}

static int lsp_identifier_compare(const void *left, const void *right) {
  const LspIdentifier *a = left, *b = right;
  size_t length = a->length < b->length ? a->length : b->length;
  int result = memcmp(a->text, b->text, length);
  return result ? result : (a->length > b->length) - (a->length < b->length);
}

static bool lsp_usage_collect(LspUsage *usage, TSNode node, const char *text) {
  const char *kind = ts_node_type(node);
  if (!strcmp(kind, "use"))
    return true;
  if (!strcmp(kind, "identifier")) {
    TSNode base = node, parent = ts_node_parent(base);
    while (!ts_node_is_null(parent) &&
           !strcmp(ts_node_type(parent), "primary") &&
           ts_node_named_child_count(parent) == 1) {
      base = parent;
      parent = ts_node_parent(base);
    }
    bool qualified = !ts_node_is_null(parent) &&
                     (!strcmp(ts_node_type(parent), "field_access") ||
                      !strcmp(ts_node_type(parent), "field_type")) &&
                     ts_node_named_child_count(parent) > 1 &&
                     ts_node_start_byte(base) ==
                         ts_node_start_byte(ts_node_named_child(parent, 0));
    if (!qualified)
      return true;
    if (usage->count == usage->capacity) {
      size_t capacity = usage->capacity ? usage->capacity * 2 : 128;
      LspIdentifier *items = realloc(usage->items, capacity * sizeof(*items));
      if (!items)
        return false;
      usage->items = items;
      usage->capacity = capacity;
    }
    uint32_t start = ts_node_start_byte(node), end = ts_node_end_byte(node);
    usage->items[usage->count++] = (LspIdentifier){text + start, end - start};
  }
  for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i)
    if (!lsp_usage_collect(usage, ts_node_named_child(node, i), text))
      return false;
  return true;
}

static int lsp_binding_compare(const void *left, const void *right) {
  const LspBinding *a = left, *b = right;
  int path = strcmp(a->path, b->path);
  if (path)
    return path;
  if (a->line != b->line)
    return (a->line > b->line) - (a->line < b->line);
  return (a->column > b->column) - (a->column < b->column);
}

static void lsp_binding_index(LspUsage *usage) {
  DynAstProgram *ast = &usage->semantic.ast;
  size_t count = ast->local_count + ast->global_count + ast->function_count;
  if (!count || !usage->semantic.checked)
    return;
  usage->bindings = calloc(count, sizeof(*usage->bindings));
  if (!usage->bindings) {
    usage->semantic.checked = false;
    return;
  }
  usage->binding_count = count;
  for (size_t i = 0; i < count; ++i) {
    DynSpan span =
        i < ast->local_count ? ast->locals[i].name
        : i < ast->local_count + ast->global_count
            ? ast->globals[i - ast->local_count].name
            : ast->functions[i - ast->local_count - ast->global_count].name;
    LspBinding *binding = &usage->bindings[i];
    dyn_source_location(&usage->semantic.source, span.start_byte,
                        &binding->path, &binding->line, &binding->column);
    binding->path = binding->path ? lsp_file_path(binding->path) : "";
  }
  for (size_t i = 0; i < ast->expression_count; ++i) {
    DynAstExpr *expression = &ast->expressions[i];
    if (expression->type == DYN_TYPE_ERROR ||
        expression->type == DYN_TYPE_INFER)
      continue;
    size_t id = (size_t)expression->integer;
    if (expression->kind == DYN_EXPR_NAME && id < ast->local_count)
      usage->bindings[id].used = true;
    else if (expression->kind == DYN_EXPR_GLOBAL && id < ast->global_count)
      usage->bindings[ast->local_count + id].used = true;
    else if ((expression->kind == DYN_EXPR_FUNCTION ||
              expression->kind == DYN_EXPR_CALL) &&
             id < ast->function_count)
      usage->bindings[ast->local_count + ast->global_count + id].used = true;
  }
  qsort(usage->bindings, count, sizeof(*usage->bindings), lsp_binding_compare);
}

static LspUsage lsp_usage_build(LspDocument *documents, size_t count,
                                LspDocument *document, const LspSemantic *semantic) {
  LspUsage usage = {.complete = true, .borrowed = semantic != NULL};
  usage.semantic = semantic ? *semantic :
      lsp_semantic_project(documents, count, document, document->text);
  if (!usage.semantic.ok && !usage.borrowed) {
    lsp_semantic_free(&usage.semantic);
    usage.semantic = lsp_semantic_build_related(documents, count, document);
  }
  lsp_binding_index(&usage);
  char *directory = lsp_directory(lsp_file_path(document->uri));
  if (!directory) {
    usage.complete = false;
    return usage;
  }
  for (size_t i = 0; i < count; ++i) {
    char *other = lsp_directory(lsp_file_path(documents[i].uri));
    if (!other)
      usage.complete = false;
    else if (!strcmp(directory, other) && documents[i].tree &&
             !lsp_usage_collect(&usage, ts_tree_root_node(documents[i].tree),
                                documents[i].text))
      usage.complete = false;
    free(other);
  }
  if (dyn_path_is_directory(directory)) {
    if (dyn_sources_load(NULL, directory, &usage.sources))
      usage.complete = false;
    else {
      TSParser *parser = ts_parser_new();
      if (!parser || !ts_parser_set_language(parser, tree_sitter_dyn()))
        usage.complete = false;
      else
        for (size_t i = 0; i < usage.sources.count && usage.complete; ++i) {
          DynSource *source = &usage.sources.items[i];
          bool opened = false;
          for (size_t j = 0; j < count; ++j)
            if (!strcmp(source->path, lsp_file_path(documents[j].uri)))
              opened = true;
          if (opened)
            continue;
          TSTree *tree = dyn_source_tree(source);
          if (!tree)
            usage.complete = false;
          else {
            usage.complete = lsp_usage_collect(&usage, ts_tree_root_node(tree),
                                               source->text);
            ts_tree_delete(tree);
          }
        }
      if (parser)
        ts_parser_delete(parser);
    }
  }
  free(directory);
  if (usage.complete && usage.count)
    qsort(usage.items, usage.count, sizeof(*usage.items),
          lsp_identifier_compare);
  return usage;
}

static size_t lsp_usage_count(const LspUsage *usage, const char *name) {
  if (!usage->complete)
    return 2; /* Incomplete evidence cannot justify an unused warning. */
  LspIdentifier key = {name, strlen(name)};
  size_t first = 0, end = usage->count;
  while (first < end) {
    size_t middle = first + (end - first) / 2;
    if (lsp_identifier_compare(&usage->items[middle], &key) < 0)
      first = middle + 1;
    else
      end = middle;
  }
  if (first == usage->count ||
      lsp_identifier_compare(&usage->items[first], &key))
    return 0;
  return first + 1 < usage->count &&
                 !lsp_identifier_compare(&usage->items[first + 1], &key)
             ? 2
             : 1;
}

static void lsp_usage_free(LspUsage *usage) {
  free(usage->bindings);
  if (!usage->borrowed) lsp_semantic_free(&usage->semantic);
  free(usage->items);
  dyn_sources_free(&usage->sources);
}

static bool lsp_binding_used(const LspUsage *usage, LspDocument *document,
                             TSNode name) {
  if (!usage->semantic.checked)
    return true;
  TSPoint point = ts_node_start_point(name);
  LspBinding key = {lsp_file_path(document->uri), point.row + 1,
                    point.column + 1, false};
  size_t first = 0, end = usage->binding_count;
  while (first < end) {
    size_t middle = first + (end - first) / 2;
    int order = lsp_binding_compare(&usage->bindings[middle], &key);
    if (!order)
      return usage->bindings[middle].used;
    if (order < 0)
      first = middle + 1;
    else
      end = middle;
  }
  return true; /* No resolved declaration is evidence against an unused warning.
                */
}

static void lsp_unused_nodes(TSNode node, LspDocument *document,
                             const LspUsage *usage, char *body, size_t capacity,
                             size_t *at, bool *comma) {
  if (*at + 1024 >= capacity)
    return;
  const char *kind = ts_node_type(node);
  TSNode names[16];
  size_t name_count = 0;
  const char *label = NULL;
  TSNode ancestor = node;
  bool exported = false, foreign = false;
  for (unsigned depth = 0; depth < 3 && !ts_node_is_null(ancestor); ++depth) {
    if (!strcmp(ts_node_type(ancestor), "extern_fn"))
      foreign = true;
    if (!strcmp(ts_node_type(ancestor), "declaration")) {
      uint32_t start = ts_node_start_byte(ancestor);
      exported = start + 4 <= strlen(document->text) &&
                 !memcmp(document->text + start, "pub ", 4);
    }
    ancestor = ts_node_parent(ancestor);
  }
  if (!strcmp(kind, "variable")) {
    if (ts_node_named_child_count(node))
      names[name_count++] = ts_node_named_child(node, 0);
    label = !strcmp(ts_node_type(ts_node_parent(node)), "const_variable")
                ? "constant"
                : "variable";
  } else if (!strcmp(kind, "fn_param") && !foreign) {
    for (uint32_t i = 0; i < ts_node_named_child_count(node) && name_count < 16;
         ++i) {
      TSNode child = ts_node_named_child(node, i);
      if (!strcmp(ts_node_type(child), "identifier"))
        names[name_count++] = child;
    }
    label = "parameter";
  } else if (!strcmp(kind, "fn") && !exported) {
    TSNode name = ts_node_child_by_field_name(node, "name", 4);
    if (!ts_node_is_null(name)) {
      names[name_count++] = name;
      label = "function";
    }
  }
  if (exported && label &&
      (!strcmp(label, "variable") || !strcmp(label, "constant")))
    name_count = 0;
  for (size_t i = 0; i < name_count && *at + 1024 < capacity; ++i) {
    uint32_t a = ts_node_start_byte(names[i]), b = ts_node_end_byte(names[i]);
    size_t n = b - a;
    if (!n || n >= 128 || document->text[a] == '_')
      continue;
    char name[128];
    memcpy(name, document->text + a, n);
    name[n] = 0;
    if (!strcmp(name, "main") || lsp_binding_used(usage, document, names[i]))
      continue;
    TSPoint p = ts_node_start_point(names[i]), e = ts_node_end_point(names[i]);
    *at += (size_t)lsp_bounded_printf(
        body + *at, capacity - *at,
        "%s{\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{"
        "\"line\":%u,\"character\":%u}},\"severity\":2,\"source\":\"dyn\","
        "\"code\":\"unused-%s\",\"message\":\"unused %s '%s'\"}",
        *comma ? "," : "", p.row, p.column, e.row, e.column, label, label,
        name);
    *comma = true;
  }
  for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i)
    lsp_unused_nodes(ts_node_named_child(node, i), document, usage, body,
                     capacity, at, comma);
}

static bool lsp_overlay_sources(DynSources *sources, LspDocument *documents,
                                size_t count) {
  for (size_t i = 0; i < sources->count; ++i)
    for (size_t j = 0; j < count; ++j) {
      const char *path = lsp_file_path(documents[j].uri);
      if (strcmp(sources->items[i].path, path))
        continue;
      size_t length = strlen(documents[j].text);
      char *text = malloc(length + 1);
      if (!text)
        return false;
      memcpy(text, documents[j].text, length + 1);
      dyn_source_discard_syntax(&sources->items[i]);
      free(sources->items[i].text);
      sources->items[i].text = text;
      sources->items[i].length = length;
      sources->items[i].syntax =
          documents[j].tree ? ts_tree_copy(documents[j].tree) : NULL;
    }
  return true;
}

static int lsp_load_semantic_project(LspDocument *documents, size_t count,
    LspDocument *requested, const char *replacement, const char *root,
    DynContext context, DynSources *project) {
  DynSources roots = {0};
  DynSource *override_items = calloc(count ? count : 1, sizeof(*override_items));
  if (!override_items) return 2;
  for (size_t i = 0; i < count; ++i)
    override_items[i] = (DynSource){
        .path = (char *)lsp_file_path(documents[i].uri),
        .text = (char *)(&documents[i] == requested ? replacement
                                                    : documents[i].text),
        .length = strlen(&documents[i] == requested ? replacement
                                                    : documents[i].text),
        .syntax = &documents[i] != requested || replacement == requested->text
                      ? documents[i].tree
                      : NULL};
  DynSources overrides = {override_items, count};
  for (size_t i = 0; i < count; ++i)
    override_items[i].context = context;
  int loaded = dyn_sources_load(&context, root, &roots);
  if (!loaded) {
    if (!lsp_overlay_sources(&roots, documents, count))
      loaded = 2;
    for (size_t i = 0; !loaded && i < roots.count; ++i)
      if (replacement != requested->text &&
          !strcmp(roots.items[i].path, lsp_file_path(requested->uri))) {
        char *copy = strdup(replacement);
        if (!copy) {
          loaded = 2;
          break;
        }
        dyn_source_discard_syntax(&roots.items[i]);
        free(roots.items[i].text);
        roots.items[i].text = copy;
        roots.items[i].length = strlen(replacement);
        if (!dyn_source_prepare(&roots.items[i]))
          loaded = 2;
      }
    if (!loaded)
      loaded =
          dyn_module_load_project_overlay(root, &roots, &overrides, project);
  }
  free(override_items); dyn_sources_free(&roots);
  return loaded;
}

/* Diagnostics use independently retained module analyses. Cross-project
   navigation still requests a complete AST so reference/rename results remain
   complete. Unsupported interfaces or errors fall back to canonical analysis. */
typedef struct {
  DynSources project;
  DynInterface *interfaces;
  LspSemantic *modules;
  size_t *firsts, *counts, count;
} LspModuleAnalyses;
static bool lsp_same_module(const char *a, const char *b) {
  const char *x = strrchr(a, '/'), *y = strrchr(b, '/');
  size_t an = x ? (size_t)(x - a) : 0, bn = y ? (size_t)(y - b) : 0;
  return an == bn && !memcmp(a, b, an);
}
static void lsp_module_analyses_free(LspModuleAnalyses *all) {
  for (size_t i = 0; i < all->count; ++i) {
    if (all->interfaces) dyn_interface_free(&all->interfaces[i]);
    if (all->modules) lsp_semantic_free(&all->modules[i]);
  }
  free(all->interfaces); free(all->modules); free(all->firsts); free(all->counts);
  dyn_sources_free(&all->project); memset(all, 0, sizeof(*all));
}
static bool lsp_module_analyses(LspModuleAnalyses *all, LspDocument *documents,
    size_t count, LspDocument *requested, const char *root) {
  DynAnalysisCache *cache = requested->analysis_cache;
  if (!cache || access(root, F_OK)) return false;
  DynContext context = {.target = lsp_target_current(), .work = lsp_work_current(), .diagnostic = lsp_ignore_diagnostic, .syntax_cache = &cache->syntax};
  if (lsp_load_semantic_project(documents, count, requested, requested->text,
                                 root, context, &all->project)) return false;
  size_t capacity = all->project.count;
  all->interfaces = calloc(capacity, sizeof(*all->interfaces));
  all->modules = calloc(capacity, sizeof(*all->modules));
  all->firsts = calloc(capacity, sizeof(*all->firsts));
  all->counts = calloc(capacity, sizeof(*all->counts));
  if (!all->interfaces || !all->modules || !all->firsts || !all->counts) return false;
  for (size_t first = 0; first < capacity;) {
    size_t end = first + 1;
    while (end < capacity && lsp_same_module(all->project.items[first].path,
                                            all->project.items[end].path)) ++end;
    size_t index = all->count++;
    all->firsts[index] = first; all->counts[index] = end - first;
    DynSources slice = {all->project.items + first, end - first};
    if (!dyn_analysis_interface_get(cache, &slice, &all->interfaces[index])) {
      if (dyn_interface_build(&slice, &all->interfaces[index])) return false;
      dyn_analysis_interface_put(cache, &slice, &all->interfaces[index]);
    }
    first = end;
  }
  for (size_t i = 0; i < all->count; ++i) {
    size_t first = all->firsts[i];
    const char *path = all->project.items[first].path;
    LspSemantic *semantic = &all->modules[i];
    if (dyn_interface_compose(&all->project, first, all->counts[i],
        all->interfaces, all->count, path, &semantic->source)) return false;
    DynAnalysisSnapshot *hit = dyn_analysis_module_get(cache, &semantic->source);
    if (hit) {
      dyn_source_free(&semantic->source); *semantic = lsp_snapshot_view(hit); continue;
    }
    char *dir = lsp_directory(path);
    if (!dir) return false;
    uint64_t hash = UINT64_C(1469598103934665603);
    for (const unsigned char *p = (const unsigned char *)dir; *p; ++p)
      hash = (hash ^ *p) * UINT64_C(1099511628211);
    char owner[32];
    if (!strcmp(dir, root)) strcpy(owner, "root");
    else snprintf(owner, sizeof(owner), "dyn_m%016llx", (unsigned long long)hash);
    free(dir);
    char *entry = dyn_path_join(root, "main.dyn");
    if (!entry) return false;
    semantic->source.context = context;
    DynAnalysisResult result = dyn_analyze(&semantic->source, &semantic->ast,
        (DynAnalysisOptions){.recover = true, .owner_key = owner, .main_path = entry});
    free(entry);
    if (!result.checked) return false;
    semantic->ok = result.parsed; semantic->checked = result.checked;
    hit = dyn_analysis_module_put(cache, &semantic->source, &semantic->ast, result);
    if (hit) *semantic = lsp_snapshot_view(hit);
  }
  return true;
}

void lsp_publish_semantic(LspDocument *documents, size_t count) {
  for (size_t group = 0; group < count; ++group) {
    char *root = lsp_project_root(documents[group].uri);
    if (!root)
      continue;
    bool seen = false;
    for (size_t before = 0; before < group && !seen; ++before) {
      char *other = lsp_project_root(documents[before].uri);
      seen = other && !strcmp(root, other);
      free(other);
    }
    if (seen) {
      free(root);
      continue;
    }
    LspModuleAnalyses modules = {0};
    bool modular = lsp_module_analyses(&modules, documents, count, &documents[group], root);
    LspSemantic semantic = modular ? (LspSemantic){.ok = true, .checked = true} :
        lsp_semantic_project(documents, count, &documents[group], documents[group].text);
    if (!semantic.ok && !dyn_path_is_directory(root)) {
      lsp_semantic_free(&semantic);
      semantic =
          lsp_semantic_build_related(documents, count, &documents[group]);
    }
    LspDiagnostics *diagnostics = &semantic.diagnostics;
    if (diagnostics->allocation_failed)
      lsp_send("{\"jsonrpc\":\"2.0\",\"method\":\"window/logMessage\",\"params\":{\"type\":1,\"message\":\"Diagnostic allocation failed; results are incomplete\"}}");
    for (size_t d = 0; d < count; ++d) {
      char *document_root = lsp_project_root(documents[d].uri);
      bool same = document_root && !strcmp(root, document_root);
      free(document_root);
      if (!same)
        continue;
      if (documents[d].syntax_too_deep || (documents[d].tree &&
          ts_node_has_error(ts_tree_root_node(documents[d].tree)))) {
        (void)lsp_publish_syntax(&documents[d]);
        continue;
      }
      char *uri = json_escape(documents[d].uri, strlen(documents[d].uri));
      char *body = uri ? malloc(strlen(uri) + 64 * 512 + 192) : NULL;
      if (!body) {
        free(uri);
        continue;
      }
      size_t capacity = strlen(uri) + 64 * 512 + 192;
      size_t at = (size_t)lsp_bounded_printf(
          body, capacity,
          "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/"
          "publishDiagnostics\",\"params\":{\"uri\":\"%s\",\"diagnostics\":[",
          uri);
      bool comma = false;
      for (size_t i = 0; i < diagnostics->count && at + 4096 < capacity; ++i) {
        LspDiagnostic *item = &diagnostics->items[i];
        if ((strcmp(item->path, documents[d].uri) &&
             strcmp(item->path, lsp_file_path(documents[d].uri))))
          continue;
        char *message = json_escape(item->message, strlen(item->message));
        if (!message)
          continue;
        unsigned line = item->line ? item->line - 1 : 0,
                 column = item->column ? item->column - 1 : 0;
        unsigned end_line = item->end_line ? item->end_line - 1 : line,
                 end_column =
                     item->end_column ? item->end_column - 1 : column + 1;
        at += (size_t)lsp_bounded_printf(
            body + at, capacity - at,
            "%s{\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{"
            "\"line\":%u,\"character\":%u}},\"severity\":%u,\"source\":\"dyn\","
            "\"message\":\"%s\"}",
            comma ? "," : "", line, column, end_line, end_column,
            !strcmp(item->severity, "error") ? 1u : 2u, message);
        comma = true;
        free(message);
      }
      const LspSemantic *view = &semantic;
      if (modular)
        for (size_t i = 0; i < modules.count; ++i)
          if (lsp_same_module(lsp_file_path(documents[d].uri),
                              modules.project.items[modules.firsts[i]].path)) {
            view = &modules.modules[i]; break;
          }
      LspUsage usage = lsp_usage_build(documents, count, &documents[d], view);
      LspImport imports[32];
      size_t import_count = lsp_imports(&documents[d], imports, 32);
      TSNode root = documents[d].tree ? ts_tree_root_node(documents[d].tree)
                                      : (TSNode){0};
      for (size_t i = 0; i < import_count && at + 4096 < capacity; ++i)
        if (!ts_node_is_null(root) &&
            !lsp_usage_count(&usage, imports[i].alias)) {
          TSNode marked = ts_node_is_null(imports[i].alias_node)
                              ? imports[i].node
                              : imports[i].alias_node;
          TSPoint a = ts_node_start_point(marked),
                  b = ts_node_end_point(marked);
          char *escaped_path = json_escape(imports[i].path, strlen(imports[i].path));
          char *escaped_alias = json_escape(imports[i].alias, strlen(imports[i].alias));
          if (!escaped_path || !escaped_alias) { free(escaped_path); free(escaped_alias); continue; }
          at += (size_t)lsp_bounded_printf(
              body + at, capacity - at,
              "%s{\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{"
              "\"line\":%u,\"character\":%u}},\"severity\":2,\"source\":"
              "\"dyn\",\"code\":\"unused-use\",\"message\":\"unused use '%s' "
              "(alias '%s')\"}",
              comma ? "," : "", a.row, a.column, b.row, b.column,
              escaped_path, escaped_alias);
          free(escaped_path); free(escaped_alias);
          comma = true;
        }
      if (!ts_node_is_null(root))
        lsp_unused_nodes(root, &documents[d], &usage, body, capacity, &at,
                         &comma);
      lsp_usage_free(&usage);
      lsp_bounded_printf(body + at, capacity - at, "]}}");
      lsp_send(body);
      free(body);
      free(uri);
    }
    lsp_semantic_free(&semantic);
    lsp_module_analyses_free(&modules);
    free(root);
  }
}

void lsp_ignore_diagnostic(const char *a, const char *b, unsigned c, unsigned d,
                           unsigned e, unsigned f, const char *g, void *h) {
  (void)a;
  (void)b;
  (void)c;
  (void)d;
  (void)e;
  (void)f;
  (void)g;
  (void)h;
}

LspSemantic lsp_semantic_build(LspDocument *documents, size_t count) {
  LspSemantic semantic = {0};
  DynSource *items = calloc(count ? count : 1, sizeof(*items));
  if (!items) return semantic;
  for (size_t i = 0; i < count; ++i)
    items[i] = (DynSource){.path = documents[i].uri,
                           .context = {.target = lsp_target_current(),
                                       .work = lsp_work_current()},
                           .text = documents[i].text,
                           .length = strlen(documents[i].text),
                           .syntax = documents[i].tree};
  DynSources sources = {items, count};
  int merged = dyn_sources_merge(&sources, "<lsp>", &semantic.source);
  free(items);
  if (merged) return semantic;
  semantic.source.context.diagnostic = lsp_collect_diagnostic;
  semantic.source.context.diagnostic_data = &semantic.diagnostics;
  DynAnalysisResult analysis = dyn_analyze(
      &semantic.source, &semantic.ast, (DynAnalysisOptions){.recover = true});
  semantic.source.context.diagnostic = NULL;
  semantic.source.context.diagnostic_data = NULL;
  semantic.ok = analysis.parsed;
  semantic.checked = analysis.checked;
  return semantic;
}

LspSemantic lsp_semantic_build_related(LspDocument *documents, size_t count,
                                       LspDocument *requested) {
  LspDocument *related = calloc(count ? count : 1, sizeof(*related));
  if (!related) return (LspSemantic){0};
  size_t related_count = 0;
  char *root = lsp_project_root(requested->uri);
  for (size_t i = 0; i < count; ++i) {
    char *candidate = lsp_project_root(documents[i].uri);
    bool same = root && candidate && !strcmp(root, candidate);
    free(candidate);
    if (same)
      related[related_count++] = documents[i];
  }
  free(root);
  LspSemantic result = lsp_semantic_build(related, related_count);
  free(related);
  return result;
}

static LspSemantic lsp_snapshot_view(DynAnalysisSnapshot *snapshot) {
  return (LspSemantic){.source = snapshot->source,
                       .ast = snapshot->ast,
                       .ok = snapshot->result.parsed,
                       .checked = snapshot->result.checked,
                       .snapshot = snapshot,
                       .diagnostics = snapshot->diagnostics};
}

LspSemantic lsp_semantic_project(LspDocument *documents, size_t count,
                                 LspDocument *requested,
                                 const char *replacement) {
  LspSemantic semantic = {0};
  char *root = lsp_project_root(requested->uri);
  if (!root)
    return semantic;
  DynAnalysisInput *inputs = calloc(count ? count : 1, sizeof(*inputs));
  if (!inputs) { free(root); return semantic; }
  for (size_t i = 0; i < count; ++i)
    inputs[i] =
        (DynAnalysisInput){lsp_file_path(documents[i].uri), documents[i].text,
                           strlen(documents[i].text), documents[i].revision,
                           documents[i].content_hash};
  bool cacheable =
      requested->analysis_cache && !strcmp(replacement, requested->text);
  if (cacheable) {
    DynAnalysisSnapshot *snapshot =
        dyn_analysis_cache_get(requested->analysis_cache, root, inputs, count);
    if (snapshot) {
      free(inputs);
      free(root);
      return lsp_snapshot_view(snapshot);
    }
  }
  if (access(root, F_OK)) {
    free(inputs);
    free(root);
    return semantic;
  }
  DynSources project = {0};
  LspDiagnostics diagnostics = {0};
  DynContext context = {.target = lsp_target_current(), .work = lsp_work_current(), .diagnostic = lsp_collect_diagnostic,
                        .diagnostic_data = &diagnostics,
                        .syntax_cache = requested->analysis_cache
                            ? &requested->analysis_cache->syntax : NULL};
  int loaded = lsp_load_semantic_project(documents, count, requested, replacement,
                                        root, context, &project);
  if (!loaded &&
      dyn_sources_merge(&project, "<lsp-completion>", &semantic.source) == 0) {
    semantic.source.context = context;
    char *main_path = dyn_path_join(root, "main.dyn");
    char *module_path = dyn_path_join(root, "module.dyn");
    const char *entry = main_path && !access(main_path, F_OK) ? main_path
                        : module_path && !access(module_path, F_OK)
                            ? module_path
                            : "";
    DynAnalysisResult analysis =
        dyn_analyze(&semantic.source, &semantic.ast,
                    (DynAnalysisOptions){.recover = true, .main_path = entry});
    free(main_path);
    free(module_path);
    semantic.source.context.diagnostic = NULL;
    semantic.source.context.diagnostic_data = NULL;
    semantic.ok = analysis.parsed;
    semantic.checked = analysis.checked;
    if (cacheable) {
      DynAnalysisSnapshot *snapshot = dyn_analysis_cache_put(
          requested->analysis_cache, root, &project, inputs, count,
          &semantic.source, &semantic.ast, analysis, &diagnostics);
      if (snapshot) {
        free(diagnostics.items);
        diagnostics = (LspDiagnostics){0};
        semantic = lsp_snapshot_view(snapshot);
      }
    }
  }
  if (!semantic.snapshot) semantic.diagnostics = diagnostics;
  free(inputs);
  dyn_sources_free(&project);
  free(root);
  semantic.source.context.diagnostic = NULL;
  semantic.source.context.diagnostic_data = NULL;
  return semantic;
}

void lsp_semantic_free(LspSemantic *semantic) {
  if (semantic->snapshot) {
    dyn_analysis_snapshot_release(semantic->snapshot);
    memset(semantic, 0, sizeof(*semantic));
    return;
  }
  dyn_ast_program_free(&semantic->ast);
  dyn_source_free(&semantic->source);
  free(semantic->diagnostics.items);
  memset(semantic, 0, sizeof(*semantic));
}

bool lsp_semantic_offset(LspSemantic *semantic, LspDocument *document,
                         size_t line, size_t character, uint32_t *offset) {
  const char *word = NULL;
  size_t length = 0;
  if (!identifier_at(document->text, line, character, &word, &length))
    return false;
  const char *row = document->text;
  for (size_t i = 0; i < line; ++i) {
    row = strchr(row, '\n');
    if (!row)
      return false;
    ++row;
  }
  size_t column = (size_t)(word - row),
         original = (size_t)(word - document->text);
  for (size_t i = 0; i < semantic->source.map_count; ++i) {
    DynSourceMap *map = &semantic->source.maps[i];
    if (strcmp(map->path, document->uri) &&
        strcmp(map->path, lsp_file_path(document->uri)))
      continue;
    for (size_t j = 0; j < map->span_count; ++j) {
      DynSourceSpan span = map->spans[j];
      if (original < span.original_start || original > span.original_end)
        continue;
      size_t on = span.original_end - span.original_start,
             gn = span.generated_end - span.generated_start;
      *offset =
          (uint32_t)(map->start + span.generated_start +
                     (on ? (original - span.original_start) * gn / on : 0));
      return true;
    }
    if (original <= map->original_length) {
      *offset = (uint32_t)(map->start + original);
      return true;
    }
  }
  for (size_t i = 0; i + length <= semantic->source.length; ++i)
    if (!memcmp(semantic->source.text + i, word, length) &&
        (i == 0 || !(isalnum((unsigned char)semantic->source.text[i - 1]) ||
                     semantic->source.text[i - 1] == '_')) &&
        (i + length == semantic->source.length ||
         !(isalnum((unsigned char)semantic->source.text[i + length]) ||
           semantic->source.text[i + length] == '_'))) {
      const char *path = NULL;
      unsigned found_line = 0, found_column = 0;
      dyn_source_location(&semantic->source, i, &path, &found_line,
                          &found_column);
      if (path &&
          (!strcmp(path, document->uri) ||
           !strcmp(path, lsp_file_path(document->uri))) &&
          found_line == line + 1 && found_column == column + 1) {
        *offset = (uint32_t)i;
        return true;
      }
    }
  return false;
}
