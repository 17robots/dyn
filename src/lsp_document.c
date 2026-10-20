#define _POSIX_C_SOURCE 200809L
#include "lsp_internal.h"
#include "syntax_depth.h"

static bool lsp_parse_work(void *data, uint64_t units) {
  return dyn_work_step(data, units);
}
ExpSnapshot *lsp_parse(const char *text, size_t length) {
  DynContext context = {.target = lsp_target_current(), .work = lsp_work_current()};
  ExpOptions options = {.work = lsp_parse_work, .data = &context, .recover = true};
  ExpSnapshot *snapshot = exp_snapshot_create(text, length, &options, NULL);
  if (snapshot && !exp_depth_certified(exp_snapshot_tree(snapshot), DYN_SYNTAX_DEPTH_LIMIT)) {
    exp_snapshot_release(snapshot);
    return NULL;
  }
  return snapshot;
}
uint32_t lsp_offset(const LspDocument *document, size_t row, size_t column) {
  size_t start = 0;
  if (document->line_starts) {
    if (row >= document->line_count) return (uint32_t)strlen(document->text);
    start = document->line_starts[row];
  } else
    for (size_t r = 0; r < row; ++r) {
      const char *newline = strchr(document->text + start, '\n');
      if (!newline) return (uint32_t)strlen(document->text);
      start = (size_t)(newline - document->text) + 1;
    }
  size_t at = start;
  while (at < start + column && document->text[at] && document->text[at] != '\n') ++at;
  return (uint32_t)at;
}
DynPoint lsp_point(const LspDocument *document, uint32_t offset) {
  if (!document->line_starts) return dyn_text_point(document->text, offset);
  uint32_t low = 0, high = document->line_count;
  while (high - low > 1) {
    uint32_t middle = low + (high - low) / 2;
    if (document->line_starts[middle] <= offset) low = middle;
    else high = middle;
  }
  return (DynPoint){low, offset - document->line_starts[low]};
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
#ifdef _WIN32
  if (input[0] == '/' && isalpha((unsigned char)input[1]) && input[2] == ':') ++input;
#endif
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
  const ExpSnapshotTree *tree = lsp_tree(document);
  size_t count = 0;
  for (DynNode wrapper = dyn_node_first(dyn_node_root(tree));
       !dyn_node_null(wrapper) && count < capacity; wrapper = dyn_node_next(wrapper)) {
    DynNode u = dyn_node_first(wrapper);
    if (!dyn_node_is(wrapper, SRC_DECLARATION) || !dyn_node_is(u, SRC_USE))
      continue;
    bool lone = dyn_node_child_count(u) == 1;
    for (DynNode im = dyn_node_first(u); !dyn_node_null(im) && count < capacity;
         im = dyn_node_next(im)) {
      DynNode string = dyn_node_field(im, EXP_ROLE_PATH),
              alias = dyn_node_field(im, EXP_ROLE_ALIAS);
      uint32_t a = dyn_node_start(string) + 1, b = dyn_node_end(string) - 1;
      if (dyn_node_null(string) || b <= a || b - a >= sizeof(imports[count].path))
        continue;
      memcpy(imports[count].path, document->text + a, b - a);
      imports[count].path[b - a] = 0;
      /* A lone import owns its whole use, so removing it removes the line. */
      DynNode owner = lone ? wrapper : im;
      imports[count].start = imports[count].remove_start = dyn_node_start(owner);
      imports[count].end = imports[count].remove_end = dyn_node_end(owner);
      if (!lone) {
        DynNode previous = {im.tree, UINT32_MAX}, next = dyn_node_next(im);
        for (DynNode c = dyn_node_first(u); c.id != im.id; c = dyn_node_next(c)) previous = c;
        if (!dyn_node_null(previous)) imports[count].remove_start = dyn_node_end(previous);
        else if (!dyn_node_null(next)) imports[count].remove_end = dyn_node_start(next);
      }
      imports[count].has_alias = !dyn_node_null(alias);
      imports[count].alias_start = dyn_node_start(alias);
      imports[count].alias_end = dyn_node_end(alias);
      if (!dyn_node_null(alias)) {
        a = dyn_node_start(alias);
        b = dyn_node_end(alias);
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
  char *uri = malloc(n * 3 + 9);
  if (!uri)
    return NULL;
  memcpy(uri, "file://", 7);
  size_t at = 7;
#ifdef _WIN32
  if (n > 1 && path[1] == ':') uri[at++] = '/';
#endif
  const char *hex = "0123456789ABCDEF";
  for (size_t i = 0; i < n; ++i) {
    unsigned char c = (unsigned char)path[i];
    if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
        (c >= '0' && c <= '9') || strchr("/:-._~", c))
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
static bool lsp_visit_exports(const ExpSnapshot *snapshot, const char *text,
                              LspPublicVisitor visit, void *context) {
  if (!snapshot) return false;
  for (DynNode wrapper = dyn_node_first(dyn_node_root(exp_snapshot_tree(snapshot)));
       !dyn_node_null(wrapper); wrapper = dyn_node_next(wrapper)) {
    if (!lsp_work_step(1)) return true;
    DynDeclaration decl;
    if (!dyn_node_declaration(wrapper, &decl) || !decl.is_public) continue;
    size_t start = dyn_node_start(decl.name);
    if (visit(text + start, dyn_node_end(decl.name) - start, decl.kind, context)) return true;
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
      ExpSnapshot *tree = document->syntax && exp_snapshot_retain(document->syntax)
          ? document->syntax : lsp_parse(document->text, strlen(document->text));
      bool stop = lsp_visit_exports(tree, document->text, visit, context);
      exp_snapshot_release(tree);
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
  ExpSnapshot *tree = lsp_parse(text, strlen(text));
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
  exp_snapshot_release(tree);
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
  next.syntax = NULL;
  next.line_starts = NULL; next.line_count = 0;
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
  ExpSnapshot *tree = lsp_parse(text, strlen(text));
  if (!tree)
    return false;
  bool found = false;
  for (DynNode wrapper = dyn_node_first(dyn_node_root(exp_snapshot_tree(tree)));
       !dyn_node_null(wrapper); wrapper = dyn_node_next(wrapper)) {
    DynDeclaration decl;
    if (!dyn_node_declaration(wrapper, &decl))
      continue;
    size_t start = dyn_node_start(decl.name);
    if (dyn_node_end(decl.name) - start != word_length ||
        memcmp(text + start, word, word_length))
      continue;
    DynPoint point = dyn_text_point(text, (uint32_t)start);
    *line = point.row;
    *column = point.column;
    *display = text + dyn_node_start(decl.node);
    const char *end = strchr(*display, '\n');
    *display_length = end ? (size_t)(end - *display) : strlen(*display);
    found = true;
    break;
  }
  exp_snapshot_release(tree);
  return found;
}

DynPoint lsp_text_end(const char *text) {
  DynPoint point = {0, 0};
  for (; *text; ++text) {
    if (*text == '\n') {
      ++point.row;
      point.column = 0;
    } else
      ++point.column;
  }
  return point;
}

void lsp_document_lines(LspDocument *document) {
  free(document->line_starts);
  document->line_starts = NULL; document->line_count = 0;
  uint32_t count = 1;
  for (const char *p = document->text; *p; ++p) count += *p == '\n';
  uint32_t *starts = malloc(count * sizeof(*starts));
  if (!starts) return;
  starts[0] = 0;
  uint32_t at = 1;
  for (uint32_t i = 0; document->text[i]; ++i)
    if (document->text[i] == '\n') starts[at++] = i + 1;
  document->line_starts = starts; document->line_count = count;
}

bool lsp_document_parse(LspDocument *document) {
  if (document->syntax && document->parsed_revision == document->revision)
    return true;
  DynContext parse_context = {.target = lsp_target_current(), .work = lsp_work_current()};
  ExpSnapshot *tree = lsp_parse(document->text, strlen(document->text));
  exp_snapshot_release(document->syntax);
  document->syntax = tree;
  lsp_document_lines(document);
  document->parsed_revision = document->revision;
  if (!tree && !dyn_work_step(&parse_context, 0)) {
    document->syntax_too_deep = false;
    return false;
  }
  document->syntax_too_deep = !tree;
  return true;
}

bool lsp_publish_syntax(LspDocument *document) {
  if (!document->uri || !document->text)
    return false;
  if (!lsp_document_parse(document))
    return false;
  size_t length = strlen(document->text);
  ExpSnapshot *tree = document->syntax;
  char *uri = json_escape(document->uri, strlen(document->uri));
  if (!uri) return false;
  if (document->syntax_too_deep) {
    size_t capacity = strlen(uri) + 384;
    char *body = malloc(capacity);
    if (body) {
      snprintf(body, capacity, "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/publishDiagnostics\",\"params\":{\"uri\":\"%s\",\"diagnostics\":[{\"range\":{\"start\":{\"line\":0,\"character\":0},\"end\":{\"line\":0,\"character\":0}},\"severity\":1,\"message\":\"syntax nesting exceeds 1024 tree levels\"}]}}", uri);
      lsp_send(body); free(body);
    }
    free(uri);
    return true;
  }
  /* Every recovered error, with the parser's message for its token. */
  const ExpSnapshotTree *syntax = exp_snapshot_tree(tree);
  uint32_t errors = syntax->error_count < DYN_SYNTAX_ERROR_LIMIT ? syntax->error_count : DYN_SYNTAX_ERROR_LIMIT;
  size_t capacity = strlen(uri) + 256 + (size_t)errors * 512;
  char *body = malloc(capacity);
  if (body) {
    size_t at = (size_t)lsp_bounded_printf(body, capacity,
        "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/publishDiagnostics\","
        "\"params\":{\"uri\":\"%s\",\"diagnostics\":[", uri);
    for (uint32_t i = 0; i < errors; ++i) {
      const ExpSyntaxError *error = &syntax->errors[i];
      char message[160];
      uint32_t end;
      dyn_syntax_error_message(document->text, length, error->offset, error->message,
                               error->expected, message, sizeof(message), &end);
      char *escaped = json_escape(message, strlen(message));
      DynPoint a = lsp_point(document, error->offset), b = lsp_point(document, end);
      if (a.row == b.row && a.column == b.column)
        ++b.column;
      at += (size_t)lsp_bounded_printf(body + at, capacity - at,
          "%s{\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{"
          "\"line\":%u,\"character\":%u}},\"severity\":1,\"source\":\"dyn\","
          "\"code\":\"syntax\",\"message\":\"%s\"}",
          i ? "," : "", a.row, a.column, b.row, b.column, escaped ? escaped : "syntax error");
      free(escaped);
    }
    lsp_bounded_printf(body + at, capacity - at, "]}}");
    lsp_send(body);
  }
  free(body);
  free(uri);
  return syntax->error_count != 0;
}
