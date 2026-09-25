#define _POSIX_C_SOURCE 200809L
#include "lsp_internal.h"

static const unsigned lsp_completion_kinds[] = {3, 22, 13, 25, 21, 6};
typedef struct {
  const char *import_path, *prefix;
  char *body;
  size_t capacity, *at;
  bool *comma;
} LspAutoImport;
static void lsp_completion_packages(const char *directory, char *body,
                                    size_t capacity, size_t *at, bool *comma);
static void lsp_completion_namespace(const char *label, char *body,
                                     size_t capacity, size_t *at, bool *comma);
static void lsp_completion_imports(const LspDocument *document,
                                   const char *typed, char *body,
                                   size_t capacity, size_t *at, bool *comma);
static bool lsp_completion_has_label(const char *body, size_t length,
                                     const char *label, size_t label_length);
static bool lsp_auto_import_declaration(const char *name, size_t length,
                                        DynDeclarationKind kind, void *context);
static void lsp_completion_auto_import_directory(const LspDocument *document,
                                                 const char *directory,
                                                 const char *import_path,
                                                 const char *prefix, char *body,
                                                 size_t capacity, size_t *at,
                                                 bool *comma, unsigned depth);
static void lsp_completion_auto_imports(const LspDocument *document,
                                        const char *prefix, char *body,
                                        size_t capacity, size_t *at,
                                        bool *comma);
static void lsp_call_snippet(const char *name, size_t name_length,
                             TSNode declaration, const char *source, char *out,
                             size_t capacity);
static void lsp_completion_decls(const char *text, bool public_only, char *body,
                                 size_t capacity, size_t *at, bool *comma);
static void lsp_completion_module(LspDocument *documents, size_t count,
                                  const char *directory, bool public_only,
                                  char *body, size_t capacity, size_t *at,
                                  bool *comma);
static bool lsp_completion_import_prefix(const char *row, const char *cursor,
                                         char *out, size_t capacity);
static void lsp_completion_type_fields(LspSemantic *semantic, DynType type,
                                       char *body, size_t capacity, size_t *at,
                                       bool *comma);
static void lsp_completion_fields(LspDocument *documents, size_t count,
                                  const char *name, char *body, size_t capacity,
                                  size_t *at, bool *comma);
static void lsp_completion_expression_fields(
    LspDocument *documents, size_t count, LspDocument *requested, size_t line,
    size_t character, char *body, size_t capacity, size_t *at, bool *comma);
static void lsp_completion_locals(LspDocument *documents, size_t count,
                                  LspDocument *requested, size_t line,
                                  size_t character, char *body, size_t capacity,
                                  size_t *at, bool *comma);
static void lsp_completion_struct_fields(LspDocument *documents, size_t count,
                                         LspDocument *requested, size_t line,
                                         size_t character, char *body,
                                         size_t capacity, size_t *at,
                                         bool *comma);
static void lsp_completion_enum_variants(LspDocument *documents, size_t count,
                                         LspDocument *requested,
                                         const char *name, bool qualify,
                                         char *body, size_t capacity,
                                         size_t *at, bool *comma);
static void lsp_completion_expected_enum(LspDocument *documents, size_t count,
                                         LspDocument *requested, size_t line,
                                         size_t character, char *body,
                                         size_t capacity, size_t *at,
                                         bool *comma);
static bool lsp_type_name(TSNode node, const char *text, char *out,
                          size_t capacity);
static bool lsp_expected_enum_name(LspDocument *documents, size_t count,
                                   LspDocument *requested, size_t line,
                                   size_t character, char *out,
                                   size_t capacity);

bool lsp_import_path_representable(const char *path) {
  for (const unsigned char *p = (const unsigned char *)path; *p; ++p)
    if (*p < 32 || *p == '"' || *p == '\\') return false;
  return true;
}

static void lsp_completion_packages(const char *directory, char *body,
                                    size_t capacity, size_t *at, bool *comma) {
  DIR *dir = opendir(directory);
  if (!dir)
    return;
  struct dirent *entry;
  while (lsp_work_step(1) && (entry = readdir(dir))) {
    if (entry->d_name[0] == '.' || !lsp_import_path_representable(entry->d_name))
      continue;
    char *path = dyn_path_join(directory, entry->d_name);
    if (!path || !dyn_path_is_directory(path) ||
        !lsp_directory_contains_dyn(path, 0)) {
      free(path);
      continue;
    }
    bool package = lsp_directory_has_dyn(path);
    *at += (size_t)lsp_bounded_printf(
        body + *at, capacity - *at,
        "%s{\"label\":\"%s\",\"kind\":19,\"detail\":\"Dyn "
        "%s\",\"insertText\":\"%s\"}",
        *comma ? "," : "", entry->d_name, package ? "package" : "package group",
        entry->d_name);
    *comma = true;
    free(path);
  }
  closedir(dir);
}

static void lsp_completion_namespace(const char *label, char *body,
                                     size_t capacity, size_t *at, bool *comma) {
  *at +=
      (size_t)lsp_bounded_printf(body + *at, capacity - *at,
                                 "%s{\"label\":\"%s\",\"kind\":19,\"detail\":"
                                 "\"Dyn package root\",\"insertText\":\"%s\"}",
                                 *comma ? "," : "", label, label);
  *comma = true;
}

static void lsp_completion_imports(const LspDocument *document,
                                   const char *typed, char *body,
                                   size_t capacity, size_t *at, bool *comma) {
  char *std_package = lsp_resolve_import(document, "std/io"),
       *std_root = std_package ? lsp_directory(std_package) : NULL;
  char *vendor_package = lsp_resolve_import(document, "vendor/sqlite"),
       *vendor_root = vendor_package ? lsp_directory(vendor_package) : NULL;
  char *project = lsp_project_root(document->uri),
       *current = lsp_directory(lsp_file_path(document->uri));
  char *directory = NULL;
  if (!*typed) {
    lsp_completion_namespace("std", body, capacity, at, comma);
    lsp_completion_namespace("vendor", body, capacity, at, comma);
    *at += (size_t)lsp_bounded_printf(
        body + *at, capacity - *at,
        "%s{\"label\":\".\",\"kind\":19,\"insertText\":\".\"}",
        *comma ? "," : "");
    *comma = true;
    if (current && project && strcmp(current, project)) {
      *at += (size_t)lsp_bounded_printf(
          body + *at, capacity - *at,
          ",{\"label\":\"..\",\"kind\":19,\"insertText\":\"..\"}");
    }
    directory = project ? strdup(project) : NULL;
  } else {
    const char *slash = strrchr(typed, '/');
    if (slash) {
      size_t n = (size_t)(slash - typed);
      char path[1024];
      if (n < sizeof(path)) {
        memcpy(path, typed, n);
        path[n] = 0;
        if (!strcmp(path, "std"))
          directory = std_root ? strdup(std_root) : NULL;
        else if (!strcmp(path, "vendor"))
          directory = vendor_root ? strdup(vendor_root) : NULL;
        else if (!strcmp(path, "."))
          directory = current ? strdup(current) : NULL;
        else if (!strcmp(path, ".."))
          directory = current ? lsp_directory(current) : NULL;
        else
          directory = lsp_resolve_import(document, path);
      }
    } else if (!strcmp(typed, "std"))
      lsp_completion_namespace("std", body, capacity, at, comma);
    else if (!strcmp(typed, "vendor"))
      lsp_completion_namespace("vendor", body, capacity, at, comma);
    else
      directory = project ? strdup(project) : NULL;
  }
  if (directory)
    lsp_completion_packages(directory, body, capacity, at, comma);
  free(directory);
  free(std_package);
  free(std_root);
  free(vendor_package);
  free(vendor_root);
  free(project);
  free(current);
}

static bool lsp_completion_has_label(const char *body, size_t length,
                                     const char *label, size_t label_length) {
  const char prefix[] = "\"label\":\"";
  const char *p = body, *end = body + length;
  while (p < end && (p = memchr(p, '"', (size_t)(end - p)))) {
    if ((size_t)(end - p) >= sizeof(prefix) - 1 + label_length + 1 &&
        !memcmp(p, prefix, sizeof(prefix) - 1) &&
        !memcmp(p + sizeof(prefix) - 1, label, label_length) &&
        p[sizeof(prefix) - 1 + label_length] == '"')
      return true;
    ++p;
  }
  return false;
}

static bool lsp_auto_import_declaration(const char *name, size_t length,
                                        DynDeclarationKind kind,
                                        void *context) {
  LspAutoImport *out = context;
  size_t prefix_length = strlen(out->prefix);
  if (!length || prefix_length > length ||
      strncasecmp(name, out->prefix, prefix_length))
    return false;
  const char *slash = strrchr(out->import_path, '/');
  const char *alias = slash ? slash + 1 : out->import_path;
  /* Paths with escapes cannot currently be represented by the module loader.
     Omit that candidate rather than emitting malformed protocol JSON. */
  if (!lsp_import_path_representable(out->import_path)) return false;
  if (!(isalpha((unsigned char)*alias) || *alias == '_')) return false;
  for (const unsigned char *p = (const unsigned char *)alias; *p; ++p)
    if (!(isalnum(*p) || *p == '_')) return false;
  *out->at += (size_t)lsp_bounded_printf(
      out->body + *out->at, out->capacity - *out->at,
      "%s{\"label\":\"%.*s\",\"kind\":%u,\"detail\":\"auto import "
      "%s\",\"insertText\":\"%s.%.*s\",\"additionalTextEdits\":[{\"range\":{"
      "\"start\":{\"line\":0,\"character\":0},\"end\":{\"line\":0,"
      "\"character\":0}},\"newText\":\"use \\\"%s\\\"\\n\"}]}",
      *out->comma ? "," : "", (int)length, name, lsp_completion_kinds[kind],
      out->import_path, alias, (int)length, name, out->import_path);
  *out->comma = true;
  return *out->at + 4096 >= out->capacity;
}

static void lsp_completion_auto_import_directory(const LspDocument *document,
                                                 const char *directory,
                                                 const char *import_path,
                                                 const char *prefix, char *body,
                                                 size_t capacity, size_t *at,
                                                 bool *comma, unsigned depth) {
  if (depth > 8 || *at + 4096 >= capacity)
    return;
  DIR *dir = opendir(directory);
  if (!dir)
    return;
  struct dirent *entry;
  while (lsp_work_step(1) && (entry = readdir(dir))) {
    if (entry->d_name[0] == '.')
      continue;
    char *path = dyn_path_join(directory, entry->d_name);
    if (!path)
      continue;
    if (dyn_path_is_directory(path)) {
      char child_import[1024];
      int n = snprintf(child_import, sizeof(child_import), "%s%s%s",
                       import_path, *import_path ? "/" : "", entry->d_name);
      if (n > 0 && (size_t)n < sizeof(child_import))
        lsp_completion_auto_import_directory(document, path, child_import,
                                             prefix, body, capacity, at, comma,
                                             depth + 1);
      free(path);
      continue;
    }
    size_t path_length = strlen(path);
    if (path_length < 4 || strcmp(path + path_length - 4, ".dyn") ||
        !*import_path || lsp_has_import(document, import_path)) {
      free(path);
      continue;
    }
    LspAutoImport out = {import_path, prefix, body, capacity, at, comma};
    lsp_public_declarations(path, lsp_auto_import_declaration, &out);
    free(path);
    if (*at + 4096 >= capacity)
      break;
  }
  closedir(dir);
}

static void lsp_completion_auto_imports(const LspDocument *document,
                                        const char *prefix, char *body,
                                        size_t capacity, size_t *at,
                                        bool *comma) {
  if (strlen(prefix) < 2)
    return;
  char *std_package = lsp_resolve_import(document, "std/io"),
       *std_root = std_package ? lsp_directory(std_package) : NULL;
  char *vendor_package = lsp_resolve_import(document, "vendor/sqlite"),
       *vendor_root = vendor_package ? lsp_directory(vendor_package) : NULL;
  char *project = lsp_project_root(document->uri);
  if (std_root)
    lsp_completion_auto_import_directory(document, std_root, "std", prefix,
                                         body, capacity, at, comma, 0);
  if (vendor_root)
    lsp_completion_auto_import_directory(document, vendor_root, "vendor",
                                         prefix, body, capacity, at, comma, 0);
  if (project)
    lsp_completion_auto_import_directory(document, project, "", prefix, body,
                                         capacity, at, comma, 0);
  free(std_package);
  free(std_root);
  free(vendor_package);
  free(vendor_root);
  free(project);
}

void lsp_completion_signature(const char *start, char *out, size_t capacity) {
  size_t at = 0;
  bool space = false;
  for (const char *p = start; *p && *p != '{'; ++p) {
    if (isspace((unsigned char)*p)) {
      space = at > 0;
      continue;
    }
    if (space && at + 1 < capacity)
      out[at++] = ' ';
    space = false;
    if ((*p == '"' || *p == '\\') && at + 1 < capacity)
      out[at++] = '\\';
    if (at + 1 < capacity)
      out[at++] = *p;
  }
  while (at && out[at - 1] == ' ')
    --at;
  out[at] = 0;
}

static void lsp_call_snippet(const char *name, size_t name_length,
                             TSNode declaration, const char *source, char *out,
                             size_t capacity) {
  size_t at = (size_t)lsp_bounded_printf(out, capacity, "%.*s(",
                                         (int)name_length, name);
  unsigned slot = 1;
  for (uint32_t i = 0; i < ts_node_named_child_count(declaration); ++i) {
    TSNode param = ts_node_named_child(declaration, i);
    if (strcmp(ts_node_type(param), "fn_param") &&
        strcmp(ts_node_type(param), "variadic_param"))
      continue;
    for (uint32_t j = 0; j < ts_node_named_child_count(param); ++j) {
      TSNode label = ts_node_named_child(param, j);
      if (strcmp(ts_node_type(label), "identifier"))
        continue;
      size_t start = ts_node_start_byte(label),
             length = ts_node_end_byte(label) - start;
      at += (size_t)lsp_bounded_printf(out + at, capacity - at, "%s${%u:%.*s}",
                                       slot > 1 ? ", " : "", slot, (int)length,
                                       source + start);
      ++slot;
    }
  }
  lsp_bounded_printf(out + at, capacity - at, ")");
}

static void lsp_completion_decls(const char *text, bool public_only, char *body,
                                 size_t capacity, size_t *at, bool *comma) {
  TSTree *tree = lsp_parse(text, strlen(text));
  if (!tree)
    return;
  static const char *details[] = {"function", "struct",   "enum",
                                  "type",     "constant", "global"};
  TSNode root = ts_tree_root_node(tree);
  for (uint32_t i = 0; i < ts_node_named_child_count(root) && lsp_work_step(1); ++i) {
    DynDeclaration decl;
    if (!dyn_syntax_declaration(ts_node_named_child(root, i), &decl) ||
        (public_only && !decl.is_public))
      continue;
    TSNode declaration = decl.node;
    unsigned item_kind = lsp_completion_kinds[decl.kind];
    const char *detail = details[decl.kind];
    const char *name = text + ts_node_start_byte(decl.name);
    size_t length = ts_node_end_byte(decl.name) - ts_node_start_byte(decl.name);
    if (!length || lsp_completion_has_label(body, *at, name, length))
      continue;
    if (item_kind == 3) {
      size_t start = ts_node_start_byte(declaration),
             end = ts_node_end_byte(declaration);
      char *source = strndup(text + start, end - start);
      if (!source)
        continue;
      char signature[512], snippet[512];
      lsp_completion_signature(source, signature, sizeof(signature));
      lsp_call_snippet(name, length, declaration, text, snippet,
                       sizeof(snippet));
      free(source);
      char *escaped_signature = json_escape(signature, strlen(signature));
      char *escaped_snippet = json_escape(snippet, strlen(snippet));
      if (escaped_signature && escaped_snippet) {
        *at += (size_t)lsp_bounded_printf(
            body + *at, capacity - *at,
            "%s{\"label\":\"%.*s\",\"kind\":3,\"detail\":\"%s\","
            "\"documentation\":{\"kind\":\"plaintext\",\"value\":\"%s\"},"
            "\"insertText\":\"%s\",\"insertTextFormat\":2,\"sortText\":\"2_%.*"
            "s\"}",
            *comma ? "," : "", (int)length, name, escaped_signature,
            escaped_signature, escaped_snippet, (int)length, name);
        *comma = true;
      }
      free(escaped_signature);
      free(escaped_snippet);
    } else {
      *at += (size_t)lsp_bounded_printf(
          body + *at, capacity - *at,
          "%s{\"label\":\"%.*s\",\"kind\":%u,\"detail\":\"%s\",\"sortText\":"
          "\"2_%.*s\"}",
          *comma ? "," : "", (int)length, name, item_kind, detail, (int)length,
          name);
      *comma = true;
    }
  }
  ts_tree_delete(tree);
}

static void lsp_completion_module(LspDocument *documents, size_t count,
                                  const char *directory, bool public_only,
                                  char *body, size_t capacity, size_t *at,
                                  bool *comma) {
  if (!directory)
    return;
  DynSources sources = {0};
  if (dyn_path_is_directory(directory) &&
      !dyn_sources_load(NULL, directory, &sources)) {
    for (size_t i = 0; i < sources.count; ++i) {
      bool opened = false;
      for (size_t j = 0; j < count; ++j)
        if (!strcmp(sources.items[i].path, lsp_file_path(documents[j].uri))) {
          opened = true;
          break;
        }
      if (!opened)
        lsp_completion_decls(sources.items[i].text, public_only, body, capacity,
                             at, comma);
    }
  }
  dyn_sources_free(&sources);
  for (size_t i = 0; i < count; ++i) {
    char *parent = lsp_directory(lsp_file_path(documents[i].uri));
    if (parent && !strcmp(parent, directory))
      lsp_completion_decls(documents[i].text, public_only, body, capacity, at,
                           comma);
    free(parent);
  }
}

static bool lsp_completion_import_prefix(const char *row, const char *cursor,
                                         char *out, size_t capacity) {
  const char *p = row;
  while (p < cursor && isspace((unsigned char)*p))
    ++p;
  if (cursor - p < 3 || memcmp(p, "use", 3))
    return false;
  p += 3;
  if (p < cursor && (isalnum((unsigned char)*p) || *p == '_'))
    return false;
  for (;;) {
    while (p < cursor && isspace((unsigned char)*p))
      ++p;
    if (cursor - p < 2 || p[0] != '/' || p[1] != '*')
      break;
    p += 2;
    while (cursor - p >= 2 && !(p[0] == '*' && p[1] == '/'))
      ++p;
    if (cursor - p < 2)
      return false;
    p += 2;
  }
  if (p == cursor || *p++ != '"')
    return false;
  size_t length = (size_t)(cursor - p);
  if (length >= capacity || memchr(p, '"', length))
    return false;
  memcpy(out, p, length);
  out[length] = 0;
  return true;
}

void lsp_completion(long id, LspDocument *documents, size_t count,
                    LspDocument *requested, size_t line, size_t character) {
  size_t capacity = 1024u * 1024u, at = 0;
  char *body = malloc(capacity);
  if (!body)
    return;
  at = (size_t)lsp_bounded_printf(
      body, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id);
  bool comma = false;
  char qualifier[128] = {0}, word_prefix[128] = {0};
  bool qualified = false;
  bool import_path = false;
  char import_typed[1024] = {0};
  if (requested && requested->text) {
    const char *p = requested->text;
    for (size_t row = 0; row < line && p; ++row) {
      p = strchr(p, '\n');
      if (p)
        ++p;
    }
    if (p) {
      const char *end = strchr(p, '\n');
      if (!end)
        end = p + strlen(p);
      const char *cursor =
                     p + ((size_t)(end - p) < character ? (size_t)(end - p)
                                                        : character),
                 *dot = cursor;
      while (dot > p && (isalnum((unsigned char)dot[-1]) || dot[-1] == '_'))
        --dot;
      if (dot > p && dot[-1] == '.') {
        qualified = true;
        const char *q = dot - 1, *start = q;
        while (start > p &&
               (isalnum((unsigned char)start[-1]) || start[-1] == '_'))
          --start;
        size_t n = (size_t)(q - start);
        if (n && n < sizeof(qualifier)) {
          memcpy(qualifier, start, n);
          qualifier[n] = 0;
          qualified = true;
        }
      }
    }
  }
  if (requested && requested->text) {
    const char *p = requested->text;
    for (size_t row = 0; row < line && p; ++row) {
      p = strchr(p, '\n');
      if (p)
        ++p;
    }
    if (p) {
      const char *end = strchr(p, '\n');
      if (!end)
        end = p + strlen(p);
      const char *cursor =
          p + (character > (size_t)(end - p) ? (size_t)(end - p) : character);
      import_path = lsp_completion_import_prefix(p, cursor, import_typed,
                                                 sizeof(import_typed));
    }
  }
  if (requested && requested->text) {
    const char *p = requested->text;
    for (size_t row = 0; row < line && p; ++row) {
      p = strchr(p, '\n');
      if (p)
        ++p;
    }
    if (p) {
      const char *end = strchr(p, '\n');
      if (!end)
        end = p + strlen(p);
      const char *cursor =
                     p + (character > (size_t)(end - p) ? (size_t)(end - p)
                                                        : character),
                 *start = cursor;
      while (start > p &&
             (isalnum((unsigned char)start[-1]) || start[-1] == '_'))
        --start;
      size_t n = (size_t)(cursor - start);
      if (n < sizeof(word_prefix)) {
        memcpy(word_prefix, start, n);
        word_prefix[n] = 0;
      }
    }
  }
  if (import_path)
    lsp_completion_imports(requested, import_typed, body, capacity, &at,
                           &comma);
  else if (qualified) {
    LspImport imports[32];
    size_t n = lsp_imports(requested, imports, 32);
    bool imported = false;
    for (size_t i = 0; i < n; ++i)
      if (!strcmp(imports[i].alias, qualifier)) {
        char *target = lsp_resolve_import(requested, imports[i].path);
        lsp_completion_module(documents, count, target, true, body, capacity,
                              &at, &comma);
        free(target);
        imported = true;
        break;
      }
    if (!imported) {
      lsp_completion_expression_fields(documents, count, requested, line,
                                       character, body, capacity, &at, &comma);
      if (!comma)
        lsp_completion_enum_variants(documents, count, requested, qualifier,
                                     false, body, capacity, &at, &comma);
      if (!comma)
        lsp_completion_fields(documents, count, qualifier, body, capacity, &at,
                              &comma);
    }
  } else {
    if (requested) {
      lsp_completion_expression_fields(documents, count, requested, line,
                                       character, body, capacity, &at, &comma);
      lsp_completion_struct_fields(documents, count, requested, line, character,
                                   body, capacity, &at, &comma);
      lsp_completion_expected_enum(documents, count, requested, line, character,
                                   body, capacity, &at, &comma);
      lsp_completion_locals(documents, count, requested, line, character, body,
                            capacity, &at, &comma);
    }
    char *directory =
        requested ? lsp_directory(lsp_file_path(requested->uri)) : NULL;
    lsp_completion_module(documents, count, directory, false, body, capacity,
                          &at, &comma);
    free(directory);
    if (requested) {
      LspImport imports[32];
      size_t n = lsp_imports(requested, imports, 32);
      for (size_t i = 0; i < n; ++i) {
        size_t length = strlen(imports[i].alias);
        if (!lsp_completion_has_label(body, at, imports[i].alias, length)) {
          char *label = json_escape(imports[i].alias, length);
          if (label) {
            at += (size_t)lsp_bounded_printf(
                body + at, capacity - at,
                "%s{\"label\":\"%s\",\"kind\":9,\"detail\":\"import\"}",
                comma ? "," : "", label);
            comma = true;
            free(label);
          }
        }
      }
    }
    if (requested)
      lsp_completion_auto_imports(requested, word_prefix, body, capacity, &at,
                                  &comma);
    const char *words[] = {"pub",    "type", "const", "else",
                           "return", "true", "false", "nil"};
    for (size_t i = 0; i < sizeof(words) / sizeof(words[0]); ++i)
      at += (size_t)lsp_bounded_printf(
          body + at, capacity - at,
          "%s{\"label\":\"%s\",\"kind\":14,\"detail\":\"keyword\"}",
          comma ? "," : "", words[i]),
          comma = true;
    struct {
      const char *label, *signature, *snippet;
    } builtins[] = {
        {"#cast", "#cast(type) value -> type", "#cast(${1:type}) ${2:value}"},
        {"#bitcast", "#bitcast(type) value -> type",
         "#bitcast(${1:type}) ${2:value}"},
        {"#len", "#len(array_or_slice) -> usize", "#len(${1:array_or_slice})"},
        {"#sizeof", "#sizeof(type_or_value) -> usize",
         "#sizeof(${1:type_or_value})"},
        {"#alignof", "#alignof(type_or_value) -> usize",
         "#alignof(${1:type_or_value})"},
        {"#typeof", "#typeof(type_or_value) -> TypeInfo",
         "#typeof(${1:type_or_value})"},
        {"#syscall", "#syscall(number, arguments...) -> isize",
         "#syscall(${1:number}${2:, arguments})"},
        {"#panic", "#panic(message: []const u8) -> never",
         "#panic(${1:message})"},
        {"#target", "#target(condition)", "#target(${1:condition})"},
        {"#link", "#link(\\\"library\\\")", "#link(\\\"${1:library}\\\")"},
    };
    for (size_t i = 0; i < sizeof(builtins) / sizeof(builtins[0]); ++i)
      at += (size_t)lsp_bounded_printf(
          body + at, capacity - at,
          "%s{\"label\":\"%s\",\"kind\":3,\"detail\":\"%s\",\"documentation\":{"
          "\"kind\":\"plaintext\",\"value\":\"%s\"},\"insertText\":\"%s\","
          "\"insertTextFormat\":2}",
          comma ? "," : "", builtins[i].label, builtins[i].signature,
          builtins[i].signature, builtins[i].snippet),
          comma = true;
    const char *labels[] = {"fn",     "main", "if",  "for",  "case",
                            "struct", "enum", "use", "defer"};
    const char *snippets[] = {
        "fn ${1:name}(${2}) {\\n\\t$0\\n}",
        "fn main() {\\n\\t$0\\n}",
        "if ${1:condition} {\\n\\t$0\\n}",
        "for ${1:item} in ${2:items} {\\n\\t$0\\n}",
        "case ${1:value} {\\n\\t${2:_ => { $0 }}\\n}",
        "struct ${1:Name} {\\n\\t${2:field}: ${3:type},\\n}",
        "enum ${1:Name} {\\n\\t${2:Value},\\n}",
        "use \\\"${1:std/package}\\\"$0",
        "defer {\\n\\t$0\\n}"};
    for (size_t i = 0; i < sizeof(labels) / sizeof(labels[0]); ++i)
      if (!lsp_completion_has_label(body, at, labels[i], strlen(labels[i])))
        at += (size_t)lsp_bounded_printf(
            body + at, capacity - at,
            "%s{\"label\":\"%s\",\"kind\":15,\"detail\":\"Dyn "
            "snippet\",\"insertText\":\"%s\",\"insertTextFormat\":2,"
            "\"filterText\":\"%s\",\"sortText\":\"5_%s\"}",
            comma ? "," : "", labels[i], snippets[i], labels[i], labels[i]),
            comma = true;
  }
  lsp_bounded_printf(body + at, capacity - at, "]}");
  lsp_send(body);
  free(body);
}

static void lsp_completion_type_fields(LspSemantic *semantic, DynType type,
                                       char *body, size_t capacity, size_t *at,
                                       bool *comma) {
  if (dyn_type_is_pointer(type)) {
    uint32_t p = type - DYN_TYPE_POINTER_BASE;
    if (p < semantic->ast.pointer_count)
      type = semantic->ast.pointers[p].pointee;
  }
  if (!dyn_type_is_struct(type))
    return;
  uint32_t sid = type - DYN_TYPE_STRUCT_BASE;
  if (sid >= semantic->ast.struct_count)
    return;
  DynAstStruct *s = &semantic->ast.structs[sid];
  for (uint32_t i = 0; i < s->field_count; ++i) {
    DynAstField *field = &semantic->ast.fields[s->field_start + i];
    char field_type[128];
    dyn_type_format(&semantic->ast, field->type, &semantic->source, field_type,
                    sizeof(field_type));
    *at += (size_t)lsp_bounded_printf(
        body + *at, capacity - *at,
        "%s{\"label\":\"%.*s\",\"kind\":5,\"detail\":\"%s\"}",
        *comma ? "," : "", (int)(field->name.end_byte - field->name.start_byte),
        semantic->source.text + field->name.start_byte, field_type);
    *comma = true;
  }
}

static void lsp_completion_fields(LspDocument *documents, size_t count,
                                  const char *name, char *body, size_t capacity,
                                  size_t *at, bool *comma) {
  LspSemantic semantic = lsp_semantic_build(documents, count);
  DynType type = DYN_TYPE_ERROR;
  for (size_t i = semantic.ast.local_count; i > 0; --i) {
    DynAstLocal *local = &semantic.ast.locals[i - 1];
    size_t n = local->name.end_byte - local->name.start_byte;
    if (strlen(name) == n &&
        !memcmp(semantic.source.text + local->name.start_byte, name, n)) {
      type = local->type;
      break;
    }
  }
  lsp_completion_type_fields(&semantic, type, body, capacity, at, comma);
  lsp_semantic_free(&semantic);
}

static void lsp_completion_expression_fields(
    LspDocument *documents, size_t count, LspDocument *requested, size_t line,
    size_t character, char *body, size_t capacity, size_t *at, bool *comma) {
  const char *row = requested->text;
  for (size_t i = 0; i < line && row; ++i) {
    row = strchr(row, '\n');
    if (row)
      ++row;
  }
  if (!row)
    return;
  const char *row_end = strchr(row, '\n');
  if (!row_end)
    row_end = row + strlen(row);
  const char *cursor = row + (character > (size_t)(row_end - row)
                                  ? (size_t)(row_end - row)
                                  : character),
             *start = cursor;
  while (start > row && (isalnum((unsigned char)start[-1]) || start[-1] == '_'))
    --start;
  if (start <= row || start[-1] != '.')
    return;
  const char marker[] = "__dyn_completion_field";
  const char *end = cursor;
  while (end < row_end && (isalnum((unsigned char)*end) || *end == '_'))
    ++end;
  size_t before = (size_t)(start - requested->text), after = strlen(end);
  char *patched = malloc(before + sizeof(marker) - 1 + after + 1);
  if (!patched)
    return;
  memcpy(patched, requested->text, before);
  memcpy(patched + before, marker, sizeof(marker) - 1);
  memcpy(patched + before + sizeof(marker) - 1, end, after + 1);
  const char *first = row;
  while (first < cursor && isspace((unsigned char)*first))
    ++first;
  bool contextual =
      ((size_t)(cursor - first) >= 3 && !memcmp(first, "if ", 3)) ||
      ((size_t)(cursor - first) >= 4 && !memcmp(first, "for ", 4)) ||
      ((size_t)(cursor - first) >= 5 && !memcmp(first, "case ", 5));
  if (contextual && !memchr(cursor, '{', (size_t)(row_end - cursor))) {
    const char *expression = first;
    while (expression < start && !isspace((unsigned char)*expression))
      ++expression;
    while (expression < start && isspace((unsigned char)*expression))
      ++expression;
    size_t prefix = (size_t)(first - requested->text),
           value = (size_t)(start - expression), suffix = strlen(row_end);
    char *repaired =
        malloc(prefix + 4 + value + sizeof(marker) - 1 + suffix + 1);
    if (!repaired) {
      free(patched);
      return;
    }
    memcpy(repaired, requested->text, prefix);
    memcpy(repaired + prefix, "_ = ", 4);
    memcpy(repaired + prefix + 4, expression, value);
    memcpy(repaired + prefix + 4 + value, marker, sizeof(marker) - 1);
    memcpy(repaired + prefix + 4 + value + sizeof(marker) - 1, row_end,
           suffix + 1);
    free(patched);
    patched = repaired;
  }
  const char *chain = start - 1;
  while (chain > row && (isalnum((unsigned char)chain[-1]) ||
                         chain[-1] == '_' || chain[-1] == '.'))
    --chain;
  const char *previous = chain;
  while (previous > row && isspace((unsigned char)previous[-1]))
    --previous;
  if (!contextual && previous > row &&
      (previous[-1] == '{' || previous[-1] == '}'))
    first = chain;
  bool standalone = !contextual && first < cursor &&
                    (isalpha((unsigned char)*first) || *first == '_');
  for (const char *p = first; p < start - 1 && standalone; ++p)
    if (*p == '=' || *p == '(' || *p == '{' || isspace((unsigned char)*p))
      standalone = false;
  if (standalone) {
    size_t insert = (size_t)(first - requested->text), length = strlen(patched);
    char *wrapped = malloc(length + 5);
    if (!wrapped) {
      free(patched);
      return;
    }
    memcpy(wrapped, patched, insert);
    memcpy(wrapped + insert, "_ = ", 4);
    memcpy(wrapped + insert + 4, patched + insert, length - insert + 1);
    free(patched);
    patched = wrapped;
  }
  LspSemantic semantic =
      lsp_semantic_project(documents, count, requested, patched);
  free(patched);
  if (semantic.ok)
    for (size_t i = semantic.ast.expression_count; i > 0; --i) {
      DynAstExpr *e = &semantic.ast.expressions[i - 1];
      size_t n = e->span.end_byte - e->span.start_byte;
      if (e->kind == DYN_EXPR_FIELD && n == sizeof(marker) - 1 &&
          !memcmp(semantic.source.text + e->span.start_byte, marker, n) &&
          e->left < semantic.ast.expression_count) {
        lsp_completion_type_fields(&semantic,
                                   semantic.ast.expressions[e->left].type, body,
                                   capacity, at, comma);
        break;
      }
    }
  lsp_semantic_free(&semantic);
}

static void lsp_completion_locals(LspDocument *documents, size_t count,
                                  LspDocument *requested, size_t line,
                                  size_t character, char *body, size_t capacity,
                                  size_t *at, bool *comma) {
  const char *row = requested->text;
  for (size_t i = 0; i < line && row; ++i) {
    row = strchr(row, '\n');
    if (row)
      ++row;
  }
  if (!row)
    return;
  const char *row_end = strchr(row, '\n');
  if (!row_end)
    row_end = row + strlen(row);
  const char *cursor = row + (character > (size_t)(row_end - row)
                                  ? (size_t)(row_end - row)
                                  : character),
             *start = cursor, *end = cursor;
  while (start > row && (isalnum((unsigned char)start[-1]) || start[-1] == '_'))
    --start;
  while (end < row_end && (isalnum((unsigned char)*end) || *end == '_'))
    ++end;
  const char marker[] = "__dyn_completion_local";
  size_t before = (size_t)(start - requested->text), after = strlen(end);
  char *patched = malloc(before + sizeof(marker) - 1 + after + 1);
  if (!patched)
    return;
  memcpy(patched, requested->text, before);
  memcpy(patched + before, marker, sizeof(marker) - 1);
  memcpy(patched + before + sizeof(marker) - 1, end, after + 1);
  const char *first = row;
  while (first < cursor && isspace((unsigned char)*first))
    ++first;
  bool contextual =
      ((size_t)(cursor - first) >= 3 && !memcmp(first, "if ", 3)) ||
      ((size_t)(cursor - first) >= 4 && !memcmp(first, "for ", 4)) ||
      ((size_t)(cursor - first) >= 5 && !memcmp(first, "case ", 5));
  if (contextual && !memchr(cursor, '{', (size_t)(row_end - cursor))) {
    size_t prefix = (size_t)(first - requested->text), suffix = strlen(row_end);
    char *repaired = malloc(prefix + 4 + sizeof(marker) - 1 + suffix + 1);
    if (!repaired) {
      free(patched);
      return;
    }
    memcpy(repaired, requested->text, prefix);
    memcpy(repaired + prefix, "_ = ", 4);
    memcpy(repaired + prefix + 4, marker, sizeof(marker) - 1);
    memcpy(repaired + prefix + 4 + sizeof(marker) - 1, row_end, suffix + 1);
    free(patched);
    patched = repaired;
  } else if (first == start && end == row_end) {
    size_t insert = (size_t)(first - requested->text), length = strlen(patched);
    char *repaired = malloc(length + 5);
    if (!repaired) {
      free(patched);
      return;
    }
    memcpy(repaired, patched, insert);
    memcpy(repaired + insert, "_ = ", 4);
    memcpy(repaired + insert + 4, patched + insert, length - insert + 1);
    free(patched);
    patched = repaired;
  }
  TSParser *scope_parser = ts_parser_new();
  TSTree *scope_tree = NULL;
  if (scope_parser && ts_parser_set_language(scope_parser, tree_sitter_dyn()))
    scope_tree = ts_parser_parse_string(scope_parser, NULL, patched,
                                        (uint32_t)strlen(patched));
  LspSemantic semantic =
      lsp_semantic_project(documents, count, requested, patched);
  if (!semantic.ok) {
    if (scope_tree)
      ts_tree_delete(scope_tree);
    if (scope_parser)
      ts_parser_delete(scope_parser);
    free(patched);
    lsp_semantic_free(&semantic);
    return;
  }
  const char *position = strstr(semantic.source.text, marker),
             *scope_position = strstr(patched, marker);
  if (!position || !scope_position) {
    if (scope_tree)
      ts_tree_delete(scope_tree);
    if (scope_parser)
      ts_parser_delete(scope_parser);
    free(patched);
    lsp_semantic_free(&semantic);
    return;
  }
  uint32_t offset = (uint32_t)(position - semantic.source.text),
           owner = UINT32_MAX;
  for (uint32_t i = 0; i < semantic.ast.function_count; ++i) {
    DynAstFn *fn = &semantic.ast.functions[i];
    if (offset >= fn->span.start_byte && offset <= fn->span.end_byte) {
      owner = i;
      break;
    }
  }
  uint32_t document_offset = (uint32_t)(scope_position - patched);
  if (owner != UINT32_MAX)
    for (size_t i = 0; i < semantic.ast.local_count; ++i) {
      DynAstLocal *local = &semantic.ast.locals[i];
      if (local->owner_function != owner || local->name.start_byte >= offset)
        continue;
      size_t length = local->name.end_byte - local->name.start_byte;
      if (!length)
        continue;
      const char *name = semantic.source.text + local->name.start_byte;
      bool visible = false;
      if (scope_tree) {
        TSNode root = ts_tree_root_node(scope_tree);
        TSNode stack[256];
        uint32_t indices[256] = {0};
        size_t depth = 1;
        stack[0] = root;
        while (depth && !visible) {
          TSNode node = stack[depth - 1];
          uint32_t child_count = ts_node_named_child_count(node);
          if (indices[depth - 1] < child_count && depth < 256) {
            TSNode child = ts_node_named_child(node, indices[depth - 1]++);
            stack[depth] = child;
            indices[depth++] = 0;
            continue;
          }
          const char *kind = ts_node_type(node);
          if (!strcmp(kind, "identifier") &&
              ts_node_end_byte(node) - ts_node_start_byte(node) == length &&
              !memcmp(patched + ts_node_start_byte(node), name, length) &&
              ts_node_start_byte(node) < document_offset) {
            TSNode parent = ts_node_parent(node);
            const char *parent_kind = ts_node_type(parent);
            bool declaration =
                (!strcmp(parent_kind, "variable") ||
                 !strcmp(parent_kind, "const_variable")) &&
                ts_node_start_byte(ts_node_named_child(parent, 0)) ==
                    ts_node_start_byte(node);
            declaration = declaration || !strcmp(parent_kind, "fn_param") ||
                          !strcmp(parent_kind, "variadic_param");
            if (!strcmp(parent_kind, "for_condition") &&
                ts_node_named_child_count(parent) > 1 &&
                ts_node_start_byte(ts_node_named_child(parent, 0)) ==
                    ts_node_start_byte(node))
              declaration = true;
            if (!strcmp(parent_kind, "case_arm") ||
                !strcmp(parent_kind, "type_pattern"))
              declaration = true;
            if (declaration) {
              TSNode scope = parent;
              while (!ts_node_is_null(scope) &&
                     strcmp(ts_node_type(scope), "block") &&
                     strcmp(ts_node_type(scope), "fn") &&
                     strcmp(ts_node_type(scope), "for_") &&
                     strcmp(ts_node_type(scope), "case_arm"))
                scope = ts_node_parent(scope);
              if (!ts_node_is_null(scope) &&
                  document_offset >= ts_node_start_byte(scope) &&
                  document_offset <= ts_node_end_byte(scope))
                visible = true;
            }
          }
          --depth;
        }
      }
      if (!visible)
        continue;
      char type[128];
      dyn_type_format(&semantic.ast, local->type, &semantic.source, type,
                      sizeof(type));
      if (!lsp_completion_has_label(body, *at, name, length)) {
        *at += (size_t)lsp_bounded_printf(
            body + *at, capacity - *at,
            "%s{\"label\":\"%.*s\",\"kind\":6,\"detail\":\"%s\",\"sortText\":"
            "\"0_%.*s\"}",
            *comma ? "," : "", (int)length, name, type, (int)length, name);
        *comma = true;
      }
    }
  if (scope_tree)
    ts_tree_delete(scope_tree);
  if (scope_parser)
    ts_parser_delete(scope_parser);
  free(patched);
  lsp_semantic_free(&semantic);
}

static void lsp_completion_struct_fields(LspDocument *documents, size_t count,
                                         LspDocument *requested, size_t line,
                                         size_t character, char *body,
                                         size_t capacity, size_t *at,
                                         bool *comma) {
  const char *row = requested->text;
  for (size_t i = 0; i < line && row; ++i) {
    row = strchr(row, '\n');
    if (row)
      ++row;
  }
  if (!row)
    return;
  const char *row_end = strchr(row, '\n');
  if (!row_end)
    row_end = row + strlen(row);
  const char *cursor = row + (character > (size_t)(row_end - row)
                                  ? (size_t)(row_end - row)
                                  : character),
             *brace = cursor;
  while (brace > requested->text && brace[-1] != '{' && brace[-1] != '}' &&
         brace[-1] != '\n')
    --brace;
  if (brace <= requested->text + 1 || brace[-1] != '{')
    return;
  const char *type_end = brace - 2;
  while (type_end > requested->text && isspace((unsigned char)*type_end))
    --type_end;
  if (!(isalnum((unsigned char)*type_end) || *type_end == '.' ||
        *type_end == '_'))
    return;
  const char *start = cursor, *end = cursor;
  while (start > brace &&
         (isalnum((unsigned char)start[-1]) || start[-1] == '_'))
    --start;
  while (end < row_end && (isalnum((unsigned char)*end) || *end == '_'))
    ++end;
  const char marker[] = "__dyn_completion_member";
  size_t before = (size_t)(start - requested->text), after = strlen(end);
  char *patched = malloc(before + sizeof(marker) - 1 + 3 + after + 1);
  if (!patched)
    return;
  memcpy(patched, requested->text, before);
  memcpy(patched + before, marker, sizeof(marker) - 1);
  memcpy(patched + before + sizeof(marker) - 1, ": 0", 3);
  memcpy(patched + before + sizeof(marker) - 1 + 3, end, after + 1);
  LspSemantic semantic =
      lsp_semantic_project(documents, count, requested, patched);
  free(patched);
  if (semantic.ok) {
    uint32_t item = UINT32_MAX;
    for (uint32_t i = 0; i < semantic.ast.item_count; ++i) {
      DynAstItem *candidate = &semantic.ast.items[i];
      size_t n = candidate->name.end_byte - candidate->name.start_byte;
      if (n == sizeof(marker) - 1 &&
          !memcmp(semantic.source.text + candidate->name.start_byte, marker,
                  n)) {
        item = i;
        break;
      }
    }
    if (item != UINT32_MAX)
      for (size_t i = semantic.ast.expression_count; i > 0; --i) {
        DynAstExpr *expression = &semantic.ast.expressions[i - 1];
        if (expression->kind == DYN_EXPR_STRUCT &&
            item >= expression->item_start &&
            item < expression->item_start + expression->item_count) {
          lsp_completion_type_fields(&semantic, expression->type, body,
                                     capacity, at, comma);
          break;
        }
      }
  }
  lsp_semantic_free(&semantic);
}

static void lsp_completion_enum_variants(LspDocument *documents, size_t count,
                                         LspDocument *requested,
                                         const char *name, bool qualify,
                                         char *body, size_t capacity,
                                         size_t *at, bool *comma) {
  LspSemantic semantic =
      lsp_semantic_project(documents, count, requested, requested->text);
  if (semantic.ok)
    for (uint32_t i = 0; i < semantic.ast.enum_count; ++i) {
      DynAstEnum *value = &semantic.ast.enums[i];
      size_t n = value->name.end_byte - value->name.start_byte;
      if (strlen(name) != n ||
          memcmp(semantic.source.text + value->name.start_byte, name, n))
        continue;
      for (uint32_t j = 0; j < value->variant_count; ++j) {
        DynAstVariant *variant =
            &semantic.ast.variants[value->variant_start + j];
        size_t length = variant->name.end_byte - variant->name.start_byte;
        const char *label = semantic.source.text + variant->name.start_byte;
        if (variant->payload_type == DYN_TYPE_VOID)
          *at += (size_t)lsp_bounded_printf(
              body + *at, capacity - *at,
              "%s{\"label\":\"%.*s\",\"kind\":20,\"detail\":\"enum "
              "variant\",\"insertText\":\"%s%s%.*s\"}",
              *comma ? "," : "", (int)length, label, qualify ? name : "",
              qualify ? "." : "", (int)length, label);
        else {
          char type[128];
          dyn_type_format(&semantic.ast, variant->payload_type,
                          &semantic.source, type, sizeof(type));
          *at += (size_t)lsp_bounded_printf(
              body + *at, capacity - *at,
              "%s{\"label\":\"%.*s\",\"kind\":20,\"detail\":\"%s\","
              "\"insertText\":\"%s%s%.*s(${1:value})\",\"insertTextFormat\":2}",
              *comma ? "," : "", (int)length, label, type, qualify ? name : "",
              qualify ? "." : "", (int)length, label);
        }
        *comma = true;
      }
      break;
    }
  lsp_semantic_free(&semantic);
}

static void lsp_completion_expected_enum(LspDocument *documents, size_t count,
                                         LspDocument *requested, size_t line,
                                         size_t character, char *body,
                                         size_t capacity, size_t *at,
                                         bool *comma) {
  char name[128];
  if (lsp_expected_enum_name(documents, count, requested, line, character, name,
                             sizeof(name)))
    lsp_completion_enum_variants(documents, count, requested, name, true, body,
                                 capacity, at, comma);
}

TSNode lsp_type_node(TSNode node) {
  for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i) {
    TSNode child = ts_node_named_child(node, i);
    if (!strcmp(ts_node_type(child), "type"))
      return child;
    if (!strcmp(ts_node_type(child), "type_qualifier"))
      return lsp_type_node(child);
  }
  return (TSNode){0};
}

static bool lsp_type_name(TSNode node, const char *text, char *out,
                          size_t capacity) {
  if (ts_node_is_null(node))
    return false;
  while (dyn_syntax_child_count(node) == 1)
    node = dyn_syntax_child(node, 0);
  if (strcmp(ts_node_type(node), "identifier"))
    return false;
  size_t start = ts_node_start_byte(node),
         length = ts_node_end_byte(node) - start;
  if (!length || length >= capacity)
    return false;
  memcpy(out, text + start, length);
  out[length] = 0;
  return true;
}

static bool lsp_expected_enum_name(LspDocument *documents, size_t count,
                                   LspDocument *requested, size_t line,
                                   size_t character, char *out,
                                   size_t capacity) {
  if (!requested->tree)
    return false;
  TSPoint point = {(uint32_t)line, (uint32_t)(character ? character - 1 : 0)};
  TSNode node = ts_node_named_descendant_for_point_range(
      ts_tree_root_node(requested->tree), point, point);
  for (; !ts_node_is_null(node); node = ts_node_parent(node)) {
    const char *kind = ts_node_type(node);
    if (!strcmp(kind, "variable"))
      return lsp_type_name(lsp_type_node(node), requested->text, out, capacity);
    if (!strcmp(kind, "return_")) {
      TSNode fn = ts_node_parent(node);
      while (!ts_node_is_null(fn) && strcmp(ts_node_type(fn), "fn"))
        fn = ts_node_parent(fn);
      return !ts_node_is_null(fn) &&
             lsp_type_name(lsp_type_node(fn), requested->text, out, capacity);
    }
    if (strcmp(kind, "call"))
      continue;
    TSNode callee = dyn_syntax_child(node, 0);
    while (dyn_syntax_child_count(callee) == 1)
      callee = dyn_syntax_child(callee, 0);
    if (strcmp(ts_node_type(callee), "identifier"))
      return false;
    size_t start = ts_node_start_byte(callee),
           length = ts_node_end_byte(callee) - start;
    size_t active = 0;
    for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i) {
      TSNode arg = ts_node_named_child(node, i);
      if (strcmp(ts_node_type(arg), "expression"))
        continue;
      TSPoint end = ts_node_end_point(arg);
      if (end.row < point.row ||
          (end.row == point.row && end.column <= point.column))
        ++active;
    }
    char *root = lsp_project_root(requested->uri);
    bool found = false;
    for (size_t d = 0; d < count && !found; ++d) {
      char *other = lsp_project_root(documents[d].uri);
      bool same = root && other && !strcmp(root, other);
      free(other);
      if (!same || !documents[d].tree)
        continue;
      TSNode file = ts_tree_root_node(documents[d].tree);
      for (uint32_t i = 0; i < ts_node_named_child_count(file) && !found; ++i) {
        DynDeclaration decl;
        if (!dyn_syntax_declaration(ts_node_named_child(file, i), &decl) ||
            decl.kind != DYN_DECL_FUNCTION)
          continue;
        size_t first = ts_node_start_byte(decl.name),
               last = ts_node_end_byte(decl.name);
        if (last - first != length ||
            memcmp(documents[d].text + first, requested->text + start, length))
          continue;
        size_t parameter = 0;
        for (uint32_t j = 0; j < ts_node_named_child_count(decl.node); ++j) {
          TSNode param = ts_node_named_child(decl.node, j);
          if (strcmp(ts_node_type(param), "fn_param"))
            continue;
          for (uint32_t k = 0; k < ts_node_named_child_count(param); ++k)
            if (!strcmp(ts_node_type(ts_node_named_child(param, k)),
                        "identifier") &&
                parameter++ == active)
              found = lsp_type_name(lsp_type_node(param), documents[d].text,
                                    out, capacity);
          if (found)
            break;
        }
      }
    }
    free(root);
    return found;
  }
  return false;
}
