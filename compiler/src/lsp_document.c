#define _POSIX_C_SOURCE 200809L
#include "lsp_internal.h"

TSTree *lsp_parse(const char *text, size_t length) {
  DynContext context = {.target = lsp_target_current(), .work = lsp_work_current()};
  return dyn_syntax_reparse_context(text, length, NULL, NULL, &context);
}

typedef struct LspUriPath {
  char *uri, *path;
  struct LspUriPath *next;
} LspUriPath;
static LspUriPath *lsp_uri_paths;
static unsigned lsp_hex(unsigned char c);
static bool lsp_text_offset(const char *text, size_t line, size_t character,
                            size_t *offset);
static char *lsp_apply_change(LspDocument *document, const char *replacement,
                              size_t start_line, size_t start_character,
                              size_t end_line, size_t end_character);
static TSNode first_syntax_error(TSNode node);

LspDocument *lsp_document(LspDocument *documents, size_t count,
                          const char *uri) {
  for (size_t i = 0; i < count; ++i)
    if (documents[i].uri && !strcmp(documents[i].uri, uri))
      return &documents[i];
  return NULL;
}

void lsp_uri_paths_clear(void) {
  while (lsp_uri_paths) {
    LspUriPath *next = lsp_uri_paths->next;
    free(lsp_uri_paths->uri);
    free(lsp_uri_paths->path);
    free(lsp_uri_paths);
    lsp_uri_paths = next;
  }
}

static unsigned lsp_hex(unsigned char c) {
  return c >= '0' && c <= '9'   ? c - '0'
         : c >= 'a' && c <= 'f' ? c - 'a' + 10
         : c >= 'A' && c <= 'F' ? c - 'A' + 10
                                : 16;
}

const char *lsp_file_path(const char *uri) {
  if (strlen(uri) < 7 || strncmp(uri, "file://", 7))
    return uri;
  for (LspUriPath *entry = lsp_uri_paths; entry; entry = entry->next)
    if (!strcmp(entry->uri, uri))
      return entry->path;
  const char *input = uri + 7;
  if (strlen(input) >= 10 && !strncmp(input, "localhost/", 10))
    input += 9;
  if (*input != '/')
    return ""; /* Remote authorities are not local paths. */
  LspUriPath *entry = calloc(1, sizeof(*entry));
  if (!entry)
    return "";
  entry->uri = strdup(uri);
  entry->path = malloc(strlen(input) + 1);
  if (!entry->uri || !entry->path) {
    free(entry->uri);
    free(entry->path);
    free(entry);
    return "";
  }
  size_t at = 0;
  while (*input) {
    unsigned char value = (unsigned char)*input++;
    if (value == '%') {
      if (!input[0] || !input[1] || lsp_hex(input[0]) == 16 ||
          lsp_hex(input[1]) == 16) {
        at = 0;
        break;
      }
      value = (unsigned char)(lsp_hex(input[0]) * 16 + lsp_hex(input[1]));
      input += 2;
      if (!value) {
        at = 0;
        break;
      }
    }
    entry->path[at++] = (char)value;
  }
  entry->path[at] = 0;
  entry->next = lsp_uri_paths;
  lsp_uri_paths = entry;
  return entry->path;
}

char *lsp_directory(const char *path) {
  char *r = strdup(path);
  if (!r)
    return NULL;
  char *slash = strrchr(r, '/');
  if (slash)
    *slash = 0;
  else
    strcpy(r, ".");
  return r;
}

char *lsp_project_root(const char *uri) {
  char *at = lsp_directory(lsp_file_path(uri)), *candidate = NULL;
  if (!at)
    return NULL;
  for (;;) {
    char *manifest = dyn_path_join(at, "dyn.project");
    bool found = manifest && !access(manifest, F_OK);
    free(manifest);
    if (found) {
      free(candidate);
      return at;
    }
    char *main_path = dyn_path_join(at, "main.dyn");
    bool has_main = main_path && !access(main_path, F_OK);
    free(main_path);
    if (has_main && !candidate)
      candidate = strdup(at);
    char *slash = strrchr(at, '/');
    if (!slash || slash == at)
      break;
    *slash = 0;
  }
  free(at);
  return candidate ? candidate : lsp_directory(lsp_file_path(uri));
}

size_t lsp_imports(const LspDocument *document, LspImport *imports,
                   size_t capacity) {
  if (!document->tree)
    return 0;
  TSNode root = ts_tree_root_node(document->tree);
  size_t count = 0;
  for (uint32_t i = 0; i < ts_node_named_child_count(root) && count < capacity;
       ++i) {
    TSNode n = ts_node_named_child(root, i);
    if (!strcmp(ts_node_type(n), "declaration"))
      n = ts_node_named_child(n, ts_node_named_child_count(n) - 1);
    if (strcmp(ts_node_type(n), "use"))
      continue;
    TSNode string = ts_node_child_by_field_name(n, "path", 4),
           alias = ts_node_child_by_field_name(n, "alias", 5);
    uint32_t a = ts_node_start_byte(string) + 1,
             b = ts_node_end_byte(string) - 1;
    if (b <= a || b - a >= sizeof(imports[count].path))
      continue;
    memcpy(imports[count].path, document->text + a, b - a);
    imports[count].path[b - a] = 0;
    imports[count].node = n;
    imports[count].alias_node = alias;
    if (!ts_node_is_null(alias)) {
      a = ts_node_start_byte(alias);
      b = ts_node_end_byte(alias);
    } else {
      const char *base = strrchr(imports[count].path, '/');
      const char *name = base ? base + 1 : imports[count].path;
      b = (uint32_t)strlen(name);
      if (b >= sizeof(imports[count].alias))
        continue;
      memcpy(imports[count].alias, name, b);
      imports[count].alias[b] = 0;
      ++count;
      continue;
    }
    if (b - a < sizeof(imports[count].alias)) {
      memcpy(imports[count].alias, document->text + a, b - a);
      imports[count].alias[b - a] = 0;
      ++count;
    }
  }
  return count;
}

char *lsp_resolve_import(const LspDocument *document, const char *path) {
  char *root = lsp_project_root(document->uri),
       *current = lsp_directory(lsp_file_path(document->uri));
  DynContext context = {.target = lsp_target_current(), .work = lsp_work_current(), .diagnostic = lsp_ignore_diagnostic};
  char *result = root && current
                     ? dyn_module_resolve_import(&context, root, current, path)
                     : NULL;
  free(root);
  free(current);
  return result;
}

char *lsp_first_dyn_file(const char *directory) {
  DIR *dir = opendir(directory);
  if (!dir)
    return NULL;
  struct dirent *entry;
  char *best = NULL;
  while (lsp_work_step(1) && (entry = readdir(dir))) {
    size_t n = strlen(entry->d_name);
    if (n < 4 || strcmp(entry->d_name + n - 4, ".dyn"))
      continue;
    if (!best || !strcmp(entry->d_name, "main.dyn") ||
        strcmp(entry->d_name, best) < 0) {
      free(best);
      best = strdup(entry->d_name);
      if (best && !strcmp(best, "main.dyn"))
        break;
    }
  }
  closedir(dir);
  if (!best)
    return NULL;
  char *path = dyn_path_join(directory, best);
  free(best);
  return path;
}

char *lsp_path_uri(const char *path) {
  size_t n = strlen(path);
  if (n > (SIZE_MAX - 8) / 3)
    return NULL;
  char *uri = malloc(n * 3 + 8);
  if (!uri)
    return NULL;
  memcpy(uri, "file://", 7);
  size_t at = 7;
  const char *hex = "0123456789ABCDEF";
  for (size_t i = 0; i < n; ++i) {
    unsigned char c = (unsigned char)path[i];
    if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
        (c >= '0' && c <= '9') || strchr("/-._~", c))
      uri[at++] = (char)c;
    else {
      uri[at++] = '%';
      uri[at++] = hex[c >> 4];
      uri[at++] = hex[c & 15];
    }
  }
  uri[at] = 0;
  return uri;
}

bool lsp_directory_has_dyn(const char *directory) {
  DIR *dir = opendir(directory);
  if (!dir)
    return false;
  struct dirent *entry;
  bool found = false;
  while (lsp_work_step(1) && (entry = readdir(dir))) {
    size_t n = strlen(entry->d_name);
    if (n >= 4 && !strcmp(entry->d_name + n - 4, ".dyn")) {
      found = true;
      break;
    }
  }
  closedir(dir);
  return found;
}

bool lsp_directory_contains_dyn(const char *directory, unsigned depth) {
  if (depth > 8)
    return false;
  if (lsp_directory_has_dyn(directory))
    return true;
  DIR *dir = opendir(directory);
  if (!dir)
    return false;
  struct dirent *entry;
  bool found = false;
  while (!found && lsp_work_step(1) && (entry = readdir(dir))) {
    if (entry->d_name[0] == '.')
      continue;
    char *path = dyn_path_join(directory, entry->d_name);
    if (path && dyn_path_is_directory(path))
      found = lsp_directory_contains_dyn(path, depth + 1);
    free(path);
  }
  closedir(dir);
  return found;
}

bool lsp_has_import(const LspDocument *document, const char *path) {
  LspImport imports[32];
  size_t count = lsp_imports(document, imports, 32);
  for (size_t i = 0; i < count; ++i)
    if (!strcmp(imports[i].path, path))
      return true;
  return false;
}

char *lsp_read_source(const char *path) {
  FILE *file = fopen(path, "rb");
  if (!file)
    return NULL;
  char *text = NULL;
  if (!fseek(file, 0, SEEK_END)) {
    long length = ftell(file);
    if (length >= 0 && (unsigned long)length <= 64u * 1024u * 1024u &&
        lsp_work_step((uint64_t)length + 1) && !fseek(file, 0, SEEK_SET)) {
      text = malloc((size_t)length + 1);
      if (text) {
        if (fread(text, 1, (size_t)length, file) != (size_t)length ||
            ferror(file)) {
          free(text);
          text = NULL;
        } else
          text[length] = 0;
      }
    }
  }
  if (fclose(file)) {
    free(text);
    text = NULL;
  }
  return text;
}

/* Cache only declaration names/kinds, never semantic decisions. Every lookup
   checks file identity/timestamps; open documents bypass disk and cache entirely.
   Discovery still runs per request, so additions/deletions, SDK and target changes
   cannot leave an obsolete candidate inventory. Retention is bounded. */
typedef struct LspExportName {
  char *name;
  size_t length;
  DynDeclarationKind kind;
} LspExportName;
typedef struct LspExportEntry {
  char *path;
  struct stat stamp;
  LspExportName *names;
  size_t count, bytes;
  uint64_t used;
  struct LspExportEntry *next;
} LspExportEntry;
static LspExportEntry *lsp_exports;
static size_t lsp_exports_count, lsp_exports_bytes;
static uint64_t lsp_exports_clock;
static LspDocument *lsp_export_documents;
static size_t lsp_export_document_count;
void lsp_declaration_documents(LspDocument *documents, size_t count) {
  lsp_export_documents = documents;
  lsp_export_document_count = count;
}
static void lsp_export_free(LspExportEntry *entry) {
  for (size_t i = 0; i < entry->count; ++i) free(entry->names[i].name);
  free(entry->names);
  free(entry->path);
  free(entry);
}
void lsp_declarations_clear(void) {
  while (lsp_exports) {
    LspExportEntry *next = lsp_exports->next;
    lsp_export_free(lsp_exports);
    lsp_exports = next;
  }
  lsp_exports_count = lsp_exports_bytes = 0;
}
static bool lsp_export_stamp(const struct stat *a, const struct stat *b) {
  return a->st_dev == b->st_dev && a->st_ino == b->st_ino &&
      a->st_size == b->st_size && a->st_mtim.tv_sec == b->st_mtim.tv_sec &&
      a->st_mtim.tv_nsec == b->st_mtim.tv_nsec &&
      a->st_ctim.tv_sec == b->st_ctim.tv_sec && a->st_ctim.tv_nsec == b->st_ctim.tv_nsec;
}
static bool lsp_visit_exports(TSTree *tree, const char *text,
                              LspPublicVisitor visit, void *context) {
  if (!tree) return false;
  TSNode root = ts_tree_root_node(tree);
  for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
    if (!lsp_work_step(1)) return true;
    DynDeclaration decl;
    if (!dyn_syntax_declaration(ts_node_named_child(root, i), &decl) || !decl.is_public) continue;
    size_t start = ts_node_start_byte(decl.name);
    if (visit(text + start, ts_node_end_byte(decl.name) - start, decl.kind, context)) return true;
  }
  return false;
}
static bool lsp_export_collect(const char *name, size_t length,
                                DynDeclarationKind kind, void *context) {
  LspExportEntry *entry = context;
  char *copy = strndup(name, length);
  LspExportName *names = copy ? realloc(entry->names, (entry->count + 1) * sizeof(*names)) : NULL;
  if (!names) { free(copy); return true; }
  entry->names = names;
  entry->names[entry->count++] = (LspExportName){copy, length, kind};
  entry->bytes += length + 1 + sizeof(*names);
  return false;
}
bool lsp_public_declarations(const char *path, LspPublicVisitor visit,
                             void *context) {
  if (!lsp_work_step(1)) return true;
  for (size_t i = 0; i < lsp_export_document_count; ++i) {
    LspDocument *document = &lsp_export_documents[i];
    if (!strcmp(path, lsp_file_path(document->uri))) {
      TSTree *tree = document->tree ? ts_tree_copy(document->tree) :
          lsp_parse(document->text, strlen(document->text));
      bool stop = lsp_visit_exports(tree, document->text, visit, context);
      if (tree) ts_tree_delete(tree);
      return stop;
    }
  }
  struct stat stamp;
  if (stat(path, &stamp)) return false;
  for (LspExportEntry **link = &lsp_exports; *link; link = &(*link)->next) {
    LspExportEntry *entry = *link;
    if (strcmp(path, entry->path)) continue;
    if (lsp_export_stamp(&stamp, &entry->stamp)) {
      entry->used = ++lsp_exports_clock;
      for (size_t i = 0; i < entry->count; ++i) {
        if (!lsp_work_step(1)) return true;
        LspExportName *name = &entry->names[i];
        if (visit(name->name, name->length, name->kind, context)) return true;
      }
      return false;
    }
    *link = entry->next;
    --lsp_exports_count; lsp_exports_bytes -= entry->bytes;
    lsp_export_free(entry);
    break;
  }
  char *text = lsp_read_source(path);
  if (!text) return false;
  TSTree *tree = lsp_parse(text, strlen(text));
  bool stop = lsp_visit_exports(tree, text, visit, context);
  LspExportEntry *entry = tree ? calloc(1, sizeof(*entry)) : NULL;
  if (entry) {
    entry->path = strdup(path);
    entry->bytes = sizeof(*entry) + strlen(path) + 1;
    struct stat after;
    if (!entry->path || !lsp_work_step(1) || lsp_visit_exports(tree, text, lsp_export_collect, entry) ||
        entry->bytes > 4 * 1024 * 1024 || stat(path, &after) || !lsp_export_stamp(&stamp, &after)) {
      lsp_export_free(entry);
    } else {
      while (lsp_exports && (lsp_exports_count >= 512 || lsp_exports_bytes + entry->bytes > 4 * 1024 * 1024)) {
        LspExportEntry **oldest = &lsp_exports;
        for (LspExportEntry **link = &lsp_exports; *link; link = &(*link)->next)
          if ((*link)->used < (*oldest)->used) oldest = link;
        LspExportEntry *removed = *oldest; *oldest = removed->next;
        --lsp_exports_count; lsp_exports_bytes -= removed->bytes;
        lsp_export_free(removed);
      }
      entry->stamp = stamp; entry->used = ++lsp_exports_clock;
      entry->next = lsp_exports; lsp_exports = entry;
      ++lsp_exports_count; lsp_exports_bytes += entry->bytes;
    }
  }
  if (tree) ts_tree_delete(tree);
  free(text);
  return stop;
}

static bool lsp_text_offset(const char *text, size_t line, size_t character,
                            size_t *offset) {
  const char *p = text;
  for (size_t i = 0; i < line; ++i) {
    p = strchr(p, '\n');
    if (!p)
      return false;
    ++p;
  }
  const char *end = strchr(p, '\n');
  if (!end)
    end = p + strlen(p);
  if (character > (size_t)(end - p))
    return false;
  *offset = (size_t)(p - text) + character;
  return true;
}

static char *lsp_apply_change(LspDocument *document, const char *replacement,
                              size_t start_line, size_t start_character,
                              size_t end_line, size_t end_character) {
  start_character =
      lsp_wire_column(document->text, start_line, start_character, true);
  end_character =
      lsp_wire_column(document->text, end_line, end_character, true);
  size_t start = 0, end = 0;
  if (!lsp_text_offset(document->text, start_line, start_character, &start) ||
      !lsp_text_offset(document->text, end_line, end_character, &end) ||
      end < start)
    return NULL;
  size_t old_length = strlen(document->text), new_length = strlen(replacement);
  char *text = malloc(start + new_length + (old_length - end) + 1);
  if (!text)
    return NULL;
  memcpy(text, document->text, start);
  memcpy(text + start, replacement, new_length);
  memcpy(text + start + new_length, document->text + end, old_length - end + 1);
  if (document->tree) {
    TSPoint new_end = {(uint32_t)start_line, (uint32_t)start_character};
    for (size_t i = 0; i < new_length; ++i) {
      if (replacement[i] == '\n') {
        ++new_end.row;
        new_end.column = 0;
      } else
        ++new_end.column;
    }
    TSInputEdit edit = {
        .start_byte = (uint32_t)start,
        .old_end_byte = (uint32_t)end,
        .new_end_byte = (uint32_t)(start + new_length),
        .start_point = {(uint32_t)start_line, (uint32_t)start_character},
        .old_end_point = {(uint32_t)end_line, (uint32_t)end_character},
        .new_end_point = new_end};
    ts_tree_edit(document->tree, &edit);
  }
  return text;
}

char *lsp_apply_changes(LspDocument *document, char *body) {
  char *changes = (char *)lsp_json_find(body, "\"contentChanges\"");
  if (!changes)
    return NULL;
  if (*changes++ != '[')
    return NULL;
  LspDocument next = *document;
  next.text = strdup(document->text);
  next.tree = NULL;
  if (!next.text)
    return NULL;
  for (;;) {
    while (isspace((unsigned char)*changes))
      ++changes;
    if (*changes == ']')
      return next.text;
    if (*changes != '{')
      break;
    char *end = changes;
    unsigned depth = 0;
    bool quoted = false;
    for (; *end; ++end) {
      if (quoted) {
        if (*end == '\\') {
          if (!end[1])
            break;
          ++end;
        } else if (*end == '"')
          quoted = false;
        continue;
      }
      if (*end == '"') {
        quoted = true;
        continue;
      }
      if (*end == '{')
        ++depth;
      else if (*end == '}' && !--depth) {
        ++end;
        break;
      }
    }
    if (depth || quoted)
      break;
    char saved = *end;
    *end = 0;
    char *replacement = json_string_after(changes, "\"text\"", 1024u * 1024u);
    char *updated = NULL;
    if (replacement) {
      size_t sl = 0, sc = 0, el = 0, ec = 0;
      if (lsp_json_member(changes, "\"range\"")) {
        if (json_range_positions(changes, &sl, &sc, &el, &ec))
          updated = lsp_apply_change(&next, replacement, sl, sc, el, ec);
        free(replacement);
      } else
        updated = replacement;
    }
    *end = saved;
    if (!updated)
      break;
    free(next.text);
    next.text = updated;
    changes = end;
    while (isspace((unsigned char)*changes))
      ++changes;
    if (*changes == ']')
      return next.text;
    if (*changes++ != ',')
      break;
  }
  free(next.text);
  return NULL;
}

bool identifier_at(const char *text, size_t line, size_t character,
                   const char **start, size_t *length) {
  if (!text)
    return false;
  const char *p = text;
  for (size_t n = 0; n < line; ++n) {
    p = strchr(p, '\n');
    if (!p)
      return false;
    ++p;
  }
  const char *end = strchr(p, '\n');
  if (!end)
    end = p + strlen(p);
  if ((size_t)(end - p) <= character)
    return false;
  const char *at = p + character;
  if (!(isalnum((unsigned char)*at) || *at == '_'))
    return false;
  const char *a = at, *b = at + 1;
  while (a > p && (isalnum((unsigned char)a[-1]) || a[-1] == '_'))
    --a;
  while (b < end && (isalnum((unsigned char)*b) || *b == '_'))
    ++b;
  *start = a;
  *length = (size_t)(b - a);
  return true;
}

bool find_declaration(const char *text, const char *word, size_t word_length,
                      size_t *line, size_t *column, const char **display,
                      size_t *display_length) {
  TSTree *tree = lsp_parse(text, strlen(text));
  if (!tree)
    return false;
  bool found = false;
  TSNode root = ts_tree_root_node(tree);
  for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
    DynDeclaration decl;
    if (!dyn_syntax_declaration(ts_node_named_child(root, i), &decl))
      continue;
    size_t start = ts_node_start_byte(decl.name);
    if (ts_node_end_byte(decl.name) - start != word_length ||
        memcmp(text + start, word, word_length))
      continue;
    TSPoint point = ts_node_start_point(decl.name);
    *line = point.row;
    *column = point.column;
    *display = text + ts_node_start_byte(decl.node);
    const char *end = strchr(*display, '\n');
    *display_length = end ? (size_t)(end - *display) : strlen(*display);
    found = true;
    break;
  }
  ts_tree_delete(tree);
  return found;
}

static TSNode first_syntax_error(TSNode node) {
  if (ts_node_is_error(node) || ts_node_is_missing(node))
    return node;
  uint32_t count = ts_node_child_count(node);
  for (uint32_t i = 0; i < count; ++i) {
    TSNode child = ts_node_child(node, i);
    if (ts_node_is_error(child) || ts_node_is_missing(child))
      return child;
    if (ts_node_has_error(child)) {
      TSNode found = first_syntax_error(child);
      if (!ts_node_is_null(found))
        return found;
    }
  }
  return (TSNode){0};
}

TSPoint lsp_text_end(const char *text) {
  TSPoint point = {0};
  for (; *text; ++text) {
    if (*text == '\n') {
      ++point.row;
      point.column = 0;
    } else
      ++point.column;
  }
  return point;
}

bool lsp_publish_syntax(LspDocument *document) {
  if (!document->uri || !document->text)
    return false;
  if (!document->parser) {
    document->parser = ts_parser_new();
    if (document->parser)
      ts_parser_set_language(document->parser, tree_sitter_dyn());
  }
  size_t length = strlen(document->text);
  TSPoint end = lsp_text_end(document->text);
  DynContext parse_context = {.target = lsp_target_current(), .work = lsp_work_current()};
  TSTree *tree = document->parser
                     ? dyn_parse_with_context(document->parser, document->tree,
                                              document->text, length, &parse_context)
                     : NULL;
  if (!tree && !dyn_work_step(&parse_context, 0)) {
    if (document->tree) ts_tree_delete(document->tree);
    document->tree = NULL; document->parsed_length = 0;
    return false;
  }
  document->syntax_too_deep = tree && !dyn_syntax_depth_ok(ts_tree_root_node(tree));
  if (document->syntax_too_deep) {
    ts_tree_delete(tree);
    if (document->tree) ts_tree_delete(document->tree);
    document->tree = NULL;
    document->parsed_length = 0; document->parsed_end = (TSPoint){0};
    char *uri = json_escape(document->uri, strlen(document->uri));
    if (uri) {
      size_t capacity = strlen(uri) + 384;
      char *body = malloc(capacity);
      if (body) {
        snprintf(body, capacity, "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/publishDiagnostics\",\"params\":{\"uri\":\"%s\",\"diagnostics\":[{\"range\":{\"start\":{\"line\":0,\"character\":0},\"end\":{\"line\":0,\"character\":0}},\"severity\":1,\"message\":\"syntax nesting exceeds 1024 tree levels\"}]}}", uri);
        lsp_send(body); free(body);
      }
      free(uri);
    }
    return true;
  }
  if (tree) {
    if (document->tree)
      ts_tree_delete(document->tree);
    document->tree = tree;
    document->parsed_length = length;
    document->parsed_end = end;
  }
  TSNode error = document->tree
                     ? first_syntax_error(ts_tree_root_node(document->tree))
                     : (TSNode){0};
  char *uri = json_escape(document->uri, strlen(document->uri));
  char *body = uri ? malloc(strlen(uri) + 512) : NULL;
  if (body) {
    if (ts_node_is_null(error))
      lsp_bounded_printf(body, strlen(uri) + 512,
                         "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/"
                         "publishDiagnostics\",\"params\":{\"uri\":\"%s\","
                         "\"diagnostics\":[]}}",
                         uri);
    else {
      TSPoint a = ts_node_start_point(error), b = ts_node_end_point(error);
      const char *message = "incomplete or invalid syntax";
      /* Only name an expected delimiter when the parser actually marks it
         missing. An error inside a complete body is not a missing body. */
      if (ts_node_is_missing(error)) {
        const char *kind = ts_node_type(error);
        if (!strcmp(kind, ")"))
          message = "incomplete function call; expected ')'";
        else if (!strcmp(kind, "}"))
          message = "incomplete block; expected '}'";
      }
      const char *tail = document->text + length;
      while (tail > document->text && isspace((unsigned char)tail[-1]))
        --tail;
      /* Recovery can represent an unfinished declaration/call as ERROR rather
         than MISSING. Restrict those hints to an error reaching end of input. */
      if (ts_node_end_byte(error) >= (size_t)(tail - document->text)) {
        const char *callee = NULL;
        size_t callee_length = 0;
        if (lsp_call_identifier(document->text, end.row, end.column, &callee,
                                &callee_length))
          message = "incomplete function call; expected ')'";
        else {
          const char *line_start = tail;
          while (line_start > document->text && line_start[-1] != '\n')
            --line_start;
          while (line_start < tail && isspace((unsigned char)*line_start))
            ++line_start;
          size_t line_length = (size_t)(tail - line_start);
          if (line_length >= 3 && !memcmp(line_start, "fn ", 3) &&
              !memchr(line_start, '{', line_length))
            message = "incomplete function declaration; expected a function body";
        }
      }
      if (a.row == b.row && a.column == b.column)
        ++b.column;
      lsp_bounded_printf(
          body, strlen(uri) + 512,
          "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/"
          "publishDiagnostics\",\"params\":{\"uri\":\"%s\",\"diagnostics\":[{"
          "\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{"
          "\"line\":%u,\"character\":%u}},\"severity\":1,\"source\":\"dyn\","
          "\"code\":\"syntax\",\"message\":\"%s\"}]}}",
          uri, a.row, a.column, b.row, b.column, message);
    }
    lsp_send(body);
  }
  free(body);
  free(uri);
  return !ts_node_is_null(error);
}
