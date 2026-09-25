#define _POSIX_C_SOURCE 200809L
#include "lsp_internal.h"

static void lsp_identifier_edits(TSNode node, const LspDocument *document,
                                 const char *word, size_t word_length,
                                 const char *uri, const char *replacement,
                                 char *body, size_t capacity, size_t *at,
                                 bool *comma);
static void lsp_rename_edits(TSNode node, const LspDocument *document,
                             const char *word, size_t word_length,
                             const char *replacement, char *body,
                             size_t capacity, size_t *at, bool *comma);
static void lsp_symbols(TSTree *tree, const char *text, const char *uri,
                        const char *query, char *body, size_t capacity,
                        size_t *at, bool *comma);
static bool lsp_foldable(const char *kind);
static void lsp_folding_nodes(TSNode node, char *body, size_t capacity,
                              size_t *at, bool *comma);
static void lsp_selection_node(TSNode node, char *body, size_t capacity,
                               size_t *at);
static void lsp_semantic_token_node(TSNode node, unsigned *previous_line,
                                    unsigned *previous_column, bool *first,
                                    char *body, size_t capacity, size_t *at,
                                    bool *comma, LspSemantic *semantic,
                                    LspDocument *document);
static bool lsp_symbol_matches(const char *name, size_t length,
                               const char *query);
static void lsp_workspace_symbol_text(const char *text, const char *uri,
                                      const char *query, char *body,
                                      size_t capacity, size_t *at, bool *comma);
static void lsp_workspace_symbol_directory(const char *directory,
                                           const char *query,
                                           LspDocument *documents, size_t count,
                                           char *body, size_t capacity,
                                           size_t *at, bool *comma,
                                           unsigned depth);
static bool lsp_span_location(LspDocument *documents, size_t count,
                              DynSpan span, LspDocument **document,
                              size_t *line, size_t *column);
static DynSpan lsp_expr_definition(DynAstProgram *a, DynAstExpr *e);
static bool lsp_same_span(DynSpan a, DynSpan b);
static size_t lsp_semantic_origins(LspSemantic *semantic, DynSpan target,
                                   LspOrigin *origins, size_t capacity);
static bool lsp_function_origin(LspSemantic *semantic, uint32_t index,
                                LspOrigin *origin);
static size_t lsp_call_item(LspSemantic *semantic, uint32_t function,
                            const char *data, char *body, size_t capacity,
                            size_t at);
static uint32_t lsp_function_for_span(LspSemantic *semantic, DynSpan span);
static bool lsp_call_data(const char *body, uint32_t *function, char **uri);
static void lsp_function_hover(LspSemantic *semantic, uint32_t index, char *out,
                               size_t capacity);
static bool lsp_field_source_type(LspSemantic *semantic, DynAstField *field,
                                  char *out, size_t capacity);
static void lsp_struct_hover(LspSemantic *semantic, uint32_t index, char *out,
                             size_t capacity);
static void lsp_enum_hover(LspSemantic *semantic, uint32_t index, char *out,
                           size_t capacity);
static void lsp_alias_hover(LspSemantic *semantic, uint32_t index, char *out,
                            size_t capacity);
static void lsp_global_hover(LspSemantic *semantic, uint32_t index, char *out,
                             size_t capacity);

const char *lsp_builtin_hover(const char *text, size_t line, size_t character) {
  const char *row = text;
  for (size_t i = 0; i < line; ++i) {
    row = strchr(row, '\n');
    if (!row)
      return NULL;
    ++row;
  }
  const char *end = strchr(row, '\n');
  if (!end)
    end = row + strlen(row);
  if (row == end)
    return NULL;
  const char *at =
      row +
      (character < (size_t)(end - row) ? character : (size_t)(end - row) - 1);
  if (!isalnum((unsigned char)*at) && *at != '_' && *at != '#' && at > row)
    --at;
  const char *a = at, *b = at + 1;
  while (a > row &&
         (isalnum((unsigned char)a[-1]) || a[-1] == '_' || a[-1] == '#'))
    --a;
  while (b < end && (isalnum((unsigned char)*b) || *b == '_'))
    ++b;
  struct {
    const char *name, *hover;
  } builtins[] = {
      {"#cast", "#cast(type) value -> type\nExplicitly converts compatible "
                "numeric, integer, or pointer values."},
      {"#bitcast", "#bitcast(type) value -> type\nReinterprets equal-sized "
                   "compatible scalar bits without numeric conversion."},
      {"#len", "#len(array_or_slice) -> usize\nReturns an array or slice "
               "element count."},
      {"#sizeof", "#sizeof(type_or_value) -> usize\nReturns the compile-time "
                  "size in bytes."},
      {"#alignof", "#alignof(type_or_value) -> usize\nReturns the compile-time "
                   "alignment in bytes."},
      {"#typeof", "#typeof(type_or_value) -> TypeInfo\nReturns reflection "
                  "metadata for a type or value."},
      {"#syscall",
       "#syscall(number, arguments...) -> isize\nPerforms a target system call "
       "with at most six integer or pointer arguments."},
      {"#panic", "#panic(message: []const u8) -> never\nRuns active defers, "
                 "prints a stack trace, and terminates execution."},
      {"#target", "#target(condition)\nIncludes a source file only when its "
                  "structured target condition matches."},
      {"#link", "#link(\"library\")\nDeclares a native library required when "
                "this source file is included."},
  };
  size_t n = (size_t)(b - a);
  for (size_t i = 0; i < sizeof(builtins) / sizeof(builtins[0]); ++i)
    if (strlen(builtins[i].name) == n && !memcmp(a, builtins[i].name, n))
      return builtins[i].hover;
  return NULL;
}

size_t lsp_active_parameter(const char *text, size_t line, size_t character) {
  const char *cursor = text;
  for (size_t i = 0; i < line; ++i) {
    cursor = strchr(cursor, '\n');
    if (!cursor)
      return 0;
    ++cursor;
  }
  cursor += character;
  const char *open = NULL;
  int depth = 0;
  for (const char *p = cursor; p > text;) {
    --p;
    if (*p == ')')
      ++depth;
    else if (*p == '(') {
      if (!depth) {
        open = p;
        break;
      }
      --depth;
    }
  }
  if (!open)
    return 0;
  size_t active = 0;
  depth = 0;
  for (const char *p = open + 1; p < cursor; ++p) {
    if (*p == '(' || *p == '[' || *p == '{')
      ++depth;
    else if ((*p == ')' || *p == ']' || *p == '}') && depth)
      --depth;
    else if (*p == ',' && !depth)
      ++active;
  }
  return active;
}

bool lsp_call_identifier(const char *text, size_t line, size_t character,
                         const char **start, size_t *length) {
  const char *cursor = text;
  for (size_t i = 0; i < line; ++i) {
    cursor = strchr(cursor, '\n');
    if (!cursor)
      return false;
    ++cursor;
  }
  cursor += character;
  const char *open = NULL;
  int depth = 0;
  for (const char *p = cursor; p > text;) {
    --p;
    if (*p == ')')
      ++depth;
    else if (*p == '(') {
      if (!depth) {
        open = p;
        break;
      }
      --depth;
    }
  }
  if (!open)
    return false;
  const char *end = open;
  while (end > text && isspace((unsigned char)end[-1]))
    --end;
  const char *begin = end;
  while (begin > text &&
         (isalnum((unsigned char)begin[-1]) || begin[-1] == '_'))
    --begin;
  if (begin == end)
    return false;
  *start = begin;
  *length = (size_t)(end - begin);
  return true;
}

static void lsp_identifier_edits(TSNode node, const LspDocument *document,
                                 const char *word, size_t word_length,
                                 const char *uri, const char *replacement,
                                 char *body, size_t capacity, size_t *at,
                                 bool *comma) {
  if (!strcmp(ts_node_type(node), "identifier") &&
      ts_node_end_byte(node) - ts_node_start_byte(node) == word_length &&
      !memcmp(document->text + ts_node_start_byte(node), word, word_length)) {
    TSPoint a = ts_node_start_point(node), b = ts_node_end_point(node);
    *at += (size_t)lsp_bounded_printf(
        body + *at, capacity - *at,
        "%s{\"uri\":\"%s\",\"range\":{\"start\":{\"line\":%u,\"character\":%u},"
        "\"end\":{\"line\":%u,\"character\":%u}}%s%s%s}",
        *comma ? "," : "", uri, a.row, a.column, b.row, b.column,
        replacement ? ",\"newText\":\"" : "", replacement ? replacement : "",
        replacement ? "\"" : "");
    *comma = true;
  }
  for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i)
    lsp_identifier_edits(ts_node_named_child(node, i), document, word,
                         word_length, uri, replacement, body, capacity, at,
                         comma);
}

void lsp_references(long id, LspDocument *documents, size_t count,
                    const char *word, size_t word_length,
                    const char *replacement, const char *project_root) {
  size_t capacity = 1024u * 1024u, at = 0;
  char *body = malloc(capacity);
  if (!body)
    return;
  at = (size_t)lsp_bounded_printf(
      body, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id);
  bool comma = false;
  for (size_t i = 0; i < count; ++i)
    if (documents[i].tree) {
      char *uri = json_escape(documents[i].uri, strlen(documents[i].uri));
      if (uri)
        lsp_identifier_edits(ts_tree_root_node(documents[i].tree),
                             &documents[i], word, word_length, uri, replacement,
                             body, capacity, &at, &comma);
      free(uri);
    }
  DIR *dir = project_root ? opendir(project_root) : NULL;
  struct dirent *entry;
  while (dir && lsp_work_step(1) && (entry = readdir(dir))) {
    size_t n = strlen(entry->d_name);
    if (n < 4 || strcmp(entry->d_name + n - 4, ".dyn"))
      continue;
    char *path = dyn_path_join(project_root, entry->d_name);
    if (!path)
      continue;
    bool opened = false;
    for (size_t i = 0; i < count; ++i)
      if (!strcmp(lsp_file_path(documents[i].uri), path)) {
        opened = true;
        break;
      }
    if (opened) {
      free(path);
      continue;
    }
    char *source = lsp_read_source(path);
    if (!source) {
      free(path);
      continue;
    }
    size_t length = strlen(source);
    TSParser *parser = ts_parser_new();
    TSTree *tree = NULL;
    if (parser && ts_parser_set_language(parser, tree_sitter_dyn()))
      tree = ts_parser_parse_string(parser, NULL, source, (uint32_t)length);
    char *uri = lsp_path_uri(path),
         *escaped = uri ? json_escape(uri, strlen(uri)) : NULL;
    LspDocument disk = {
        .uri = uri, .text = source, .parser = parser, .tree = tree};
    if (tree && escaped)
      lsp_identifier_edits(ts_tree_root_node(tree), &disk, word, word_length,
                           escaped, replacement, body, capacity, &at, &comma);
    free(escaped);
    free(uri);
    if (tree)
      ts_tree_delete(tree);
    if (parser)
      ts_parser_delete(parser);
    free(source);
    free(path);
  }
  if (dir)
    closedir(dir);
  lsp_bounded_printf(body + at, capacity - at, "]}");
  lsp_send(body);
  free(body);
}

static void lsp_rename_edits(TSNode node, const LspDocument *document,
                             const char *word, size_t word_length,
                             const char *replacement, char *body,
                             size_t capacity, size_t *at, bool *comma) {
  if (!strcmp(ts_node_type(node), "identifier") &&
      ts_node_end_byte(node) - ts_node_start_byte(node) == word_length &&
      !memcmp(document->text + ts_node_start_byte(node), word, word_length)) {
    TSPoint a = ts_node_start_point(node), b = ts_node_end_point(node);
    *at += (size_t)lsp_bounded_printf(
        body + *at, capacity - *at,
        "%s{\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{"
        "\"line\":%u,\"character\":%u}},\"newText\":\"%s\"}",
        *comma ? "," : "", a.row, a.column, b.row, b.column, replacement);
    *comma = true;
  }
  for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i)
    lsp_rename_edits(ts_node_named_child(node, i), document, word, word_length,
                     replacement, body, capacity, at, comma);
}

void lsp_rename(long id, LspDocument *documents, size_t count, const char *word,
                size_t word_length, const char *replacement,
                const char *project_root) {
  size_t capacity = 1024u * 1024u;
  char *body = malloc(capacity);
  if (!body)
    return;
  size_t at = (size_t)lsp_bounded_printf(
      body, capacity,
      "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"changes\":{", id);
  bool document_comma = false;
  for (size_t i = 0; i < count; ++i)
    if (documents[i].tree) {
      char *uri = json_escape(documents[i].uri, strlen(documents[i].uri));
      if (!uri)
        continue;
      at += (size_t)lsp_bounded_printf(body + at, capacity - at, "%s\"%s\":[",
                                       document_comma ? "," : "", uri);
      bool edit_comma = false;
      lsp_rename_edits(ts_tree_root_node(documents[i].tree), &documents[i],
                       word, word_length, replacement, body, capacity, &at,
                       &edit_comma);
      at += (size_t)lsp_bounded_printf(body + at, capacity - at, "]");
      document_comma = true;
      free(uri);
    }
  DIR *dir = project_root ? opendir(project_root) : NULL;
  struct dirent *entry;
  while (dir && lsp_work_step(1) && (entry = readdir(dir))) {
    size_t n = strlen(entry->d_name);
    if (n < 4 || strcmp(entry->d_name + n - 4, ".dyn"))
      continue;
    char *path = dyn_path_join(project_root, entry->d_name);
    if (!path)
      continue;
    bool opened = false;
    for (size_t i = 0; i < count; ++i)
      if (!strcmp(lsp_file_path(documents[i].uri), path)) {
        opened = true;
        break;
      }
    if (opened) {
      free(path);
      continue;
    }
    char *source = lsp_read_source(path);
    if (!source) {
      free(path);
      continue;
    }
    size_t length = strlen(source);
    TSParser *parser = ts_parser_new();
    TSTree *tree = NULL;
    if (parser && ts_parser_set_language(parser, tree_sitter_dyn()))
      tree = ts_parser_parse_string(parser, NULL, source, (uint32_t)length);
    char edits[65536];
    size_t edit_at = 0;
    bool edit_comma = false;
    LspDocument disk = {.text = source, .tree = tree};
    if (tree)
      lsp_rename_edits(ts_tree_root_node(tree), &disk, word, word_length,
                       replacement, edits, sizeof(edits), &edit_at,
                       &edit_comma);
    if (edit_comma) {
      char *uri = lsp_path_uri(path),
           *escaped = uri ? json_escape(uri, strlen(uri)) : NULL;
      if (escaped)
        at += (size_t)lsp_bounded_printf(
            body + at, capacity - at, "%s\"%s\":[%s]",
            document_comma ? "," : "", escaped, edits),
            document_comma = true;
      free(escaped);
      free(uri);
    }
    if (tree)
      ts_tree_delete(tree);
    if (parser)
      ts_parser_delete(parser);
    free(source);
    free(path);
  }
  if (dir)
    closedir(dir);
  lsp_bounded_printf(body + at, capacity - at, "}}}");
  lsp_send(body);
  free(body);
}

static void lsp_symbols(TSTree *tree, const char *text, const char *uri,
                        const char *query, char *body, size_t capacity,
                        size_t *at, bool *comma) {
  if (!tree)
    return;
  static const unsigned kinds[] = {12, 23, 10, 5, 14, 13};
  TSNode root = ts_tree_root_node(tree);
  char *escaped = uri ? json_escape(uri, strlen(uri)) : NULL;
  if (uri && !escaped)
    return;
  for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
    DynDeclaration decl;
    if (!dyn_syntax_declaration(ts_node_named_child(root, i), &decl))
      continue;
    const char *name = text + ts_node_start_byte(decl.name);
    size_t length = ts_node_end_byte(decl.name) - ts_node_start_byte(decl.name);
    if (!lsp_symbol_matches(name, length, query))
      continue;
    TSPoint a = ts_node_start_point(decl.name),
            b = ts_node_end_point(decl.name);
    *at += (size_t)lsp_bounded_printf(
        body + *at, capacity - *at, "%s{\"name\":\"%.*s\",\"kind\":%u,",
        *comma ? "," : "", (int)length, name, kinds[decl.kind]);
    if (uri) {
      *at += (size_t)lsp_bounded_printf(
          body + *at, capacity - *at, "\"location\":{\"uri\":\"%s\",", escaped);
    } else {
      TSPoint start = ts_node_start_point(decl.node),
              end = ts_node_end_point(decl.node);
      *at += (size_t)lsp_bounded_printf(
          body + *at, capacity - *at,
          "\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{"
          "\"line\":%u,\"character\":%u}},",
          start.row, start.column, end.row, end.column);
    }
    *at += (size_t)lsp_bounded_printf(
        body + *at, capacity - *at,
        "\"%s\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{\"line\":%u,"
        "\"character\":%u}}}%s",
        uri ? "range" : "selectionRange", a.row, a.column, b.row, b.column,
        uri ? "}" : "");
    *comma = true;
  }
  free(escaped);
}

void lsp_document_symbols(long id, const LspDocument *document) {
  size_t capacity = 1024u * 1024u;
  char *body = malloc(capacity);
  if (!body)
    return;
  size_t at = (size_t)lsp_bounded_printf(
      body, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id);
  bool comma = false;
  lsp_symbols(document->tree, document->text, NULL, NULL, body, capacity, &at,
              &comma);
  lsp_bounded_printf(body + at, capacity - at, "]}");
  lsp_send(body);
  free(body);
}

static bool lsp_foldable(const char *kind) {
  return !strcmp(kind, "fn") || !strcmp(kind, "extern_fn") ||
         !strcmp(kind, "struct") || !strcmp(kind, "enum") ||
         !strcmp(kind, "block") || !strcmp(kind, "case") ||
         !strcmp(kind, "if") || !strcmp(kind, "for") || !strcmp(kind, "defer");
}

static void lsp_folding_nodes(TSNode node, char *body, size_t capacity,
                              size_t *at, bool *comma) {
  TSPoint a = ts_node_start_point(node), b = ts_node_end_point(node);
  if (b.row > a.row && lsp_foldable(ts_node_type(node))) {
    *at += (size_t)lsp_bounded_printf(
        body + *at, capacity - *at,
        "%s{\"startLine\":%u,\"startCharacter\":%u,\"endLine\":%u,"
        "\"endCharacter\":%u,\"kind\":\"region\"}",
        *comma ? "," : "", a.row, a.column, b.row, b.column);
    *comma = true;
  }
  for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i)
    lsp_folding_nodes(ts_node_named_child(node, i), body, capacity, at, comma);
}

void lsp_folding_ranges(long id, const LspDocument *document) {
  char body[65536];
  size_t at = (size_t)lsp_bounded_printf(
      body, sizeof(body), "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id);
  bool comma = false;
  if (document->tree)
    lsp_folding_nodes(ts_tree_root_node(document->tree), body, sizeof(body),
                      &at, &comma);
  lsp_bounded_printf(body + at, sizeof(body) - at, "]}");
  lsp_send(body);
}

static void lsp_selection_node(TSNode node, char *body, size_t capacity,
                               size_t *at) {
  TSPoint a = ts_node_start_point(node), b = ts_node_end_point(node);
  *at += (size_t)lsp_bounded_printf(
      body + *at, capacity - *at,
      "{\"range\":{\"start\":{\"line\":%u,\"character\":%u},\"end\":{\"line\":%"
      "u,\"character\":%u}}",
      a.row, a.column, b.row, b.column);
  TSNode parent = ts_node_parent(node);
  while (!ts_node_is_null(parent) && !ts_node_is_named(parent))
    parent = ts_node_parent(parent);
  if (!ts_node_is_null(parent)) {
    *at +=
        (size_t)lsp_bounded_printf(body + *at, capacity - *at, ",\"parent\":");
    lsp_selection_node(parent, body, capacity, at);
  }
  *at += (size_t)lsp_bounded_printf(body + *at, capacity - *at, "}");
}

void lsp_selection_range(long id, const LspDocument *document,
                         const char *request) {
  char body[65536];
  size_t at = (size_t)lsp_bounded_printf(
      body, sizeof(body), "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id);
  const char *positions = lsp_json_find(request, "\"positions\"");
  const char *position =
      positions && *positions == '[' ? lsp_json_space(positions + 1) : NULL;
  bool comma = false;
  while (position && *position != ']' && document->tree) {
    size_t line, character;
    if (!json_point(position, &line, &character))
      break;
    character = lsp_wire_column(document->text, line, character, true);
    TSPoint point = {(uint32_t)line, (uint32_t)character};
    TSNode node = ts_node_named_descendant_for_point_range(
        ts_tree_root_node(document->tree), point, point);
    if (comma)
      at += (size_t)lsp_bounded_printf(body + at, sizeof(body) - at, ",");
    if (!ts_node_is_null(node))
      lsp_selection_node(node, body, sizeof(body), &at);
    else
      at += (size_t)lsp_bounded_printf(
          body + at, sizeof(body) - at,
          "{\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{"
          "\"line\":%zu,\"character\":%zu}}}",
          line, character, line, character);
    comma = true;
    position = lsp_json_end(position, 0);
    if (!position)
      break;
    position = lsp_json_space(position);
    if (*position != ',')
      break;
    position = lsp_json_space(position + 1);
  }
  lsp_bounded_printf(body + at, sizeof(body) - at, "]}");
  lsp_send(body);
}

static void lsp_semantic_token_node(TSNode node, unsigned *previous_line,
                                    unsigned *previous_column, bool *first,
                                    char *body, size_t capacity, size_t *at,
                                    bool *comma, LspSemantic *semantic,
                                    LspDocument *document) {
  if (*at + 128 >= capacity)
    return;
  if (!strcmp(ts_node_type(node), "identifier")) {
    TSNode parent = ts_node_parent(node);
    const char *kind = ts_node_type(parent);
    unsigned type = 5, modifiers = 0;
    if (!strcmp(kind, "variable") &&
        !strcmp(ts_node_type(ts_node_parent(parent)), "const_variable"))
      modifiers = 1;
    if (!strcmp(kind, "fn") || !strcmp(kind, "extern_fn")) {
      TSNode name = ts_node_child_by_field_name(parent, "name", 4);
      if (ts_node_start_byte(name) == ts_node_start_byte(node))
        type = 8;
    } else if (!strcmp(kind, "fn_param") || !strcmp(kind, "variadic_param"))
      type = 4;
    else if (!strcmp(kind, "struct"))
      type = 2;
    else if (!strcmp(kind, "enum"))
      type = 3;
    else if (!strcmp(kind, "struct_member") || !strcmp(kind, "field_access"))
      type = 6;
    else if (!strcmp(kind, "enum_member"))
      type = 7;
    else if (!strcmp(kind, "use"))
      type = 0;
    else if (!strcmp(kind, "field_type") || !strcmp(kind, "type"))
      type = 1;
    TSPoint position = ts_node_start_point(node);
    uint32_t offset;
    DynSpan definition = {0};
    char hover[16];
    if (semantic->ok &&
        lsp_semantic_offset(semantic, document, position.row, position.column,
                            &offset) &&
        lsp_typed_symbol(semantic, offset, hover, sizeof(hover), &definition)) {
      for (size_t i = 0; i < semantic->ast.global_count; ++i) {
        DynAstGlobal *global = &semantic->ast.globals[i];
        if (global->is_const &&
            global->name.start_byte == definition.start_byte &&
            global->name.end_byte == definition.end_byte)
          modifiers = 1;
      }
      for (size_t i = 0; i < semantic->ast.local_count; ++i) {
        DynAstLocal *local = &semantic->ast.locals[i];
        if (local->is_const &&
            local->name.start_byte == definition.start_byte &&
            local->name.end_byte == definition.end_byte)
          modifiers = 1;
      }
    }
    TSPoint p = ts_node_start_point(node);
    unsigned delta_line = *first ? p.row : p.row - *previous_line;
    unsigned delta_column =
        (*first || delta_line) ? p.column : p.column - *previous_column;
    *at += (size_t)lsp_bounded_printf(
        body + *at, capacity - *at, "%s%u,%u,%u,%u,%u", *comma ? "," : "",
        delta_line, delta_column, ts_node_end_point(node).column - p.column,
        type, modifiers);
    *comma = true;
    *first = false;
    *previous_line = p.row;
    *previous_column = p.column;
  }
  for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i)
    lsp_semantic_token_node(ts_node_named_child(node, i), previous_line,
                            previous_column, first, body, capacity, at, comma,
                            semantic, document);
}

void lsp_semantic_tokens(long id, LspDocument *documents, size_t count,
                         LspDocument *document) {
  size_t capacity = 1024u * 1024u, at = 0;
  char *body = malloc(capacity);
  if (!body)
    return;
  at = (size_t)lsp_bounded_printf(
      body, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"data\":[",
      id);
  LspSemantic semantic =
      lsp_semantic_project(documents, count, document, document->text);
  if (!semantic.ok) {
    lsp_semantic_free(&semantic);
    semantic = lsp_semantic_build_related(documents, count, document);
  }
  unsigned line = 0, column = 0;
  bool first = true, comma = false;
  if (document->tree)
    lsp_semantic_token_node(ts_tree_root_node(document->tree), &line, &column,
                            &first, body, capacity, &at, &comma, &semantic,
                            document);
  lsp_bounded_printf(body + at, capacity - at, "]}}");
  lsp_send(body);
  free(body);
  lsp_semantic_free(&semantic);
}

static bool lsp_symbol_matches(const char *name, size_t length,
                               const char *query) {
  if (!query || !*query)
    return true;
  size_t q = strlen(query);
  if (q > length)
    return false;
  for (size_t i = 0; i + q <= length; ++i)
    if (!strncasecmp(name + i, query, q))
      return true;
  return false;
}

static void lsp_workspace_symbol_text(const char *text, const char *uri,
                                      const char *query, char *body,
                                      size_t capacity, size_t *at,
                                      bool *comma) {
  TSTree *tree = lsp_parse(text, strlen(text));
  lsp_symbols(tree, text, uri, query, body, capacity, at, comma);
  if (tree)
    ts_tree_delete(tree);
}

static void lsp_workspace_symbol_directory(const char *directory,
                                           const char *query,
                                           LspDocument *documents, size_t count,
                                           char *body, size_t capacity,
                                           size_t *at, bool *comma,
                                           unsigned depth) {
  if (depth > 16 || *at + 4096 >= capacity)
    return;
  DIR *dir = opendir(directory);
  if (!dir)
    return;
  struct dirent *entry;
  while (lsp_work_step(1) && (entry = readdir(dir))) {
    if (entry->d_name[0] == '.' || !strcmp(entry->d_name, "build"))
      continue;
    char *path = dyn_path_join(directory, entry->d_name);
    if (!path)
      continue;
    if (dyn_path_is_directory(path)) {
      lsp_workspace_symbol_directory(path, query, documents, count, body,
                                     capacity, at, comma, depth + 1);
      free(path);
      continue;
    }
    size_t n = strlen(path);
    if (n < 4 || strcmp(path + n - 4, ".dyn")) {
      free(path);
      continue;
    }
    const char *text = NULL;
    for (size_t i = 0; i < count; ++i)
      if (!strcmp(lsp_file_path(documents[i].uri), path)) {
        text = documents[i].text;
        break;
      }
    char *owned = NULL;
    if (!text) {
      owned = lsp_read_source(path);
      text = owned;
    }
    if (text) {
      char *uri = lsp_path_uri(path);
      if (uri) {
        lsp_workspace_symbol_text(text, uri, query, body, capacity, at, comma);
        free(uri);
      }
    }
    free(owned);
    free(path);
    if (*at + 4096 >= capacity)
      break;
  }
  closedir(dir);
}

void lsp_workspace_symbols(long id, LspDocument *documents, size_t count,
                           const char *workspace_root, const char *query) {
  size_t capacity = 1024u * 1024u, at = 0;
  char *body = malloc(capacity);
  if (!body)
    return;
  at = (size_t)lsp_bounded_printf(
      body, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id);
  bool comma = false;
  if (workspace_root)
    lsp_workspace_symbol_directory(workspace_root, query, documents, count,
                                   body, capacity, &at, &comma, 0);
  else
    for (size_t d = 0; d < count; ++d)
      lsp_workspace_symbol_text(documents[d].text, documents[d].uri, query,
                                body, capacity, &at, &comma);
  lsp_bounded_printf(body + at, capacity - at, "]}");
  lsp_send(body);
  free(body);
}

static bool lsp_span_location(LspDocument *documents, size_t count,
                              DynSpan span, LspDocument **document,
                              size_t *line, size_t *column) {
  size_t base = 0;
  for (size_t i = 0; i < count; ++i) {
    size_t length = strlen(documents[i].text);
    if (span.start_byte >= base && span.start_byte < base + length) {
      size_t local = span.start_byte - base;
      *document = &documents[i];
      *line = 0;
      *column = 0;
      for (size_t j = 0; j < local; ++j) {
        if (documents[i].text[j] == '\n') {
          ++*line;
          *column = 0;
        } else
          ++*column;
      }
      return true;
    }
    base += length + 1;
  }
  return false;
}

void lsp_inlay_hints(long id, LspDocument *documents, size_t count,
                     LspDocument *requested, size_t range_start,
                     size_t range_end) {
  LspSemantic semantic =
      lsp_semantic_build_related(documents, count, requested);
  char body[65536];
  size_t at = (size_t)lsp_bounded_printf(
      body, sizeof(body), "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id);
  bool comma = false;
  for (size_t i = 0; semantic.ok && i < semantic.ast.local_count; ++i) {
    DynAstLocal *local = &semantic.ast.locals[i];
    LspDocument *document = NULL;
    size_t line = 0, column = 0;
    if (!lsp_span_location(documents, count, local->name, &document, &line,
                           &column) ||
        document != requested || line < range_start || line > range_end)
      continue;
    size_t length = local->name.end_byte - local->name.start_byte;
    const char *row = requested->text;
    for (size_t r = 0; r < line && row; ++r) {
      row = strchr(row, '\n');
      if (row)
        ++row;
    }
    if (!row)
      continue;
    const char *after = row + column + length;
    while (*after == ' ' || *after == '\t')
      ++after;
    if (after[0] != ':' || after[1] != '=')
      continue;
    char type[128];
    dyn_type_format(&semantic.ast, local->type, &semantic.source, type,
                    sizeof(type));
    at += (size_t)lsp_bounded_printf(
        body + at, sizeof(body) - at,
        "%s{\"position\":{\"line\":%zu,\"character\":%zu},\"label\":\": "
        "%s\",\"kind\":1,\"paddingLeft\":true}",
        comma ? "," : "", line, column + length, type);
    comma = true;
    if (at + 512 >= sizeof(body))
      break;
  }
  for (size_t i = 0; semantic.ok && i < semantic.ast.expression_count &&
                     at + 512 < sizeof(body);
       ++i) {
    DynAstExpr *call = &semantic.ast.expressions[i];
    if (call->kind != DYN_EXPR_CALL ||
        call->integer >= semantic.ast.function_count)
      continue;
    DynAstFn *callee = &semantic.ast.functions[call->integer];
    uint32_t arguments = call->item_count < callee->param_count
                             ? call->item_count
                             : callee->param_count;
    for (uint32_t j = 0; j < arguments && at + 512 < sizeof(body); ++j) {
      DynAstItem *item = &semantic.ast.items[call->item_start + j];
      if (item->expression >= semantic.ast.expression_count)
        continue;
      DynAstExpr *argument = &semantic.ast.expressions[item->expression];
      while (argument->kind == DYN_EXPR_CONVERT &&
             argument->left < semantic.ast.expression_count)
        argument = &semantic.ast.expressions[argument->left];
      DynAstParam *parameter = &semantic.ast.params[callee->param_start + j];
      const char *path = NULL;
      unsigned line = 0, column = 0;
      dyn_source_location(&semantic.source, argument->span.start_byte, &path,
                          &line, &column);
      size_t zero_line = line ? line - 1 : 0;
      if (!path ||
          (strcmp(path, requested->uri) &&
           strcmp(path, lsp_file_path(requested->uri))) ||
          zero_line < range_start || zero_line > range_end)
        continue;
      size_t length = parameter->name.end_byte - parameter->name.start_byte;
      if (!length)
        continue;
      at += (size_t)lsp_bounded_printf(
          body + at, sizeof(body) - at,
          "%s{\"position\":{\"line\":%zu,\"character\":%u},\"label\":\"%.*s:\","
          "\"kind\":2,\"paddingRight\":true}",
          comma ? "," : "", zero_line, column ? column - 1 : 0, (int)length,
          semantic.source.text + parameter->name.start_byte);
      comma = true;
    }
  }
  lsp_bounded_printf(body + at, sizeof(body) - at, "]}");
  lsp_send(body);
  lsp_semantic_free(&semantic);
}

static DynSpan lsp_expr_definition(DynAstProgram *a, DynAstExpr *e) {
  if (e->type == DYN_TYPE_ERROR || e->type == DYN_TYPE_INFER)
    return (DynSpan){0};
  if (e->kind == DYN_EXPR_NAME && e->integer < a->local_count)
    return a->locals[e->integer].name;
  if (e->kind == DYN_EXPR_GLOBAL && e->integer < a->global_count)
    return a->globals[e->integer].name;
  if (e->kind == DYN_EXPR_FUNCTION && e->integer < a->function_count)
    return a->functions[e->integer].name;
  if (e->kind == DYN_EXPR_CALL && e->integer < a->function_count)
    return a->functions[e->integer].name;
  if (e->kind == DYN_EXPR_FIELD && e->left < a->expression_count) {
    DynType base = a->expressions[e->left].type;
    if (dyn_type_is_pointer(base)) {
      uint32_t p = base - DYN_TYPE_POINTER_BASE;
      if (p < a->pointer_count)
        base = a->pointers[p].pointee;
    }
    if (dyn_type_is_struct(base)) {
      DynAstStruct *s = &a->structs[base - DYN_TYPE_STRUCT_BASE];
      if (e->integer < s->field_count)
        return a->fields[s->field_start + (uint32_t)e->integer].name;
    }
  }
  return (DynSpan){0};
}

static bool lsp_same_span(DynSpan a, DynSpan b) {
  return a.start_byte == b.start_byte && a.end_byte == b.end_byte;
}

bool lsp_valid_identifier(const char *name) {
  if (!name || !(*name == '_' || isalpha((unsigned char)*name)))
    return false;
  for (++name; *name; ++name)
    if (!(*name == '_' || isalnum((unsigned char)*name)))
      return false;
  return true;
}

bool lsp_origin_identifier(const DynSource *source, DynSpan span,
                           LspOrigin *origin) {
  const char *path;
  unsigned line, column;
  dyn_source_location(source, span.end_byte, &path, &line, &column);
  if (!path || !line || !column)
    return false;
  const char *text =
      source->original_text ? source->original_text : source->text;
  for (size_t i = 0; i < source->map_count; ++i)
    if (span.end_byte >= source->maps[i].start &&
        span.end_byte <= source->maps[i].end) {
      text = source->maps[i].original_text;
      break;
    }
  const char *row = text;
  for (unsigned i = 1; row && i < line; ++i) {
    row = strchr(row, '\n');
    if (row)
      ++row;
  }
  if (!row)
    return false;
  const char *end = row + column - 1, *start = end;
  while (start > row && (isalnum((unsigned char)start[-1]) || start[-1] == '_'))
    --start;
  if (start == end)
    return false;
  char *owned = !strncmp(path, "file://", 7) ? NULL : lsp_path_uri(path);
  const char *uri = owned ? owned : path;
  bool valid = strlen(uri) < sizeof(origin->uri);
  if (valid) {
    strcpy(origin->uri, uri);
    origin->line = line - 1;
    origin->column = (size_t)(start - row);
    origin->length = (size_t)(end - start);
  }
  free(owned);
  return valid;
}

static size_t lsp_semantic_origins(LspSemantic *semantic, DynSpan target,
                                   LspOrigin *origins, size_t capacity) {
  DynSpan spans[4096];
  size_t span_count = 0, count = 0;
  spans[span_count++] = target;
  for (size_t i = 0; i < semantic->ast.expression_count && span_count < 4096;
       ++i) {
    DynAstExpr *e = &semantic->ast.expressions[i];
    if (lsp_same_span(lsp_expr_definition(&semantic->ast, e), target) &&
        !lsp_same_span(e->span, target))
      spans[span_count++] = e->span;
  }
  for (size_t i = 0; i < span_count && count < capacity; ++i) {
    LspOrigin candidate;
    if (!lsp_origin_identifier(&semantic->source, spans[i], &candidate))
      continue;
    bool duplicate = false;
    for (size_t j = 0; j < count; ++j)
      if (candidate.line == origins[j].line &&
          candidate.column == origins[j].column &&
          !strcmp(candidate.uri, origins[j].uri)) {
        duplicate = true;
        break;
      }
    if (!duplicate)
      origins[count++] = candidate;
  }
  return count;
}

void lsp_document_highlight(long id, LspDocument *documents, size_t count,
                            LspDocument *document, size_t line,
                            size_t character) {
  LspSemantic semantic =
      lsp_semantic_project(documents, count, document, document->text);
  if (!semantic.ok) {
    lsp_semantic_free(&semantic);
    semantic = lsp_semantic_build_related(documents, count, document);
  }
  uint32_t offset;
  DynSpan target = {0};
  char hover[8];
  char body[65536];
  size_t at = (size_t)lsp_bounded_printf(
      body, sizeof(body), "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id);
  bool comma = false;
  if (semantic.ok &&
      lsp_semantic_offset(&semantic, document, line, character, &offset) &&
      lsp_typed_symbol(&semantic, offset, hover, sizeof(hover), &target) &&
      target.end_byte > target.start_byte) {
    LspOrigin origins[4096];
    size_t found = lsp_semantic_origins(&semantic, target, origins, 4096);
    for (size_t i = 0; i < found; ++i) {
      LspOrigin *origin = &origins[i];
      if (strcmp(lsp_file_path(origin->uri), lsp_file_path(document->uri)))
        continue;
      at += (size_t)lsp_bounded_printf(
          body + at, sizeof(body) - at,
          "%s{\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{"
          "\"line\":%zu,\"character\":%zu}},\"kind\":2}",
          comma ? "," : "", origin->line, origin->column, origin->line,
          origin->column + origin->length);
      comma = true;
    }
  }
  lsp_bounded_printf(body + at, sizeof(body) - at, "]}");
  lsp_send(body);
  lsp_semantic_free(&semantic);
}

void lsp_semantic_references(long id, LspSemantic *semantic,
                             LspDocument *documents, size_t count,
                             DynSpan target) {
  (void)documents;
  (void)count;
  size_t capacity = 1024u * 1024u, at = 0;
  char *body = malloc(capacity);
  if (!body)
    return;
  at = (size_t)lsp_bounded_printf(
      body, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id);
  bool comma = false;
  LspOrigin origins[4096];
  size_t origin_count = lsp_semantic_origins(semantic, target, origins, 4096);
  for (size_t i = 0; i < origin_count; ++i) {
    char *uri = json_escape(origins[i].uri, strlen(origins[i].uri));
    if (uri) {
      at += (size_t)lsp_bounded_printf(
          body + at, capacity - at,
          "%s{\"uri\":\"%s\",\"range\":{\"start\":{\"line\":%zu,\"character\":%"
          "zu},\"end\":{\"line\":%zu,\"character\":%zu}}}",
          comma ? "," : "", uri, origins[i].line, origins[i].column,
          origins[i].line, origins[i].column + origins[i].length);
      comma = true;
    }
    free(uri);
  }
  lsp_bounded_printf(body + at, capacity - at, "]}");
  lsp_send(body);
  free(body);
}

void lsp_semantic_rename(long id, LspSemantic *semantic, LspDocument *documents,
                         size_t count, DynSpan target,
                         const char *replacement) {
  (void)documents;
  (void)count;
  size_t capacity = 1024u * 1024u, at = 0;
  char *body = malloc(capacity);
  if (!body)
    return;
  at = (size_t)lsp_bounded_printf(
      body, capacity,
      "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"changes\":{", id);
  LspOrigin origins[4096];
  size_t origin_count = lsp_semantic_origins(semantic, target, origins, 4096);
  bool document_comma = false;
  for (size_t d = 0; d < origin_count; ++d) {
    bool seen = false;
    for (size_t p = 0; p < d; ++p)
      if (!strcmp(origins[p].uri, origins[d].uri)) {
        seen = true;
        break;
      }
    if (seen)
      continue;
    char *uri = json_escape(origins[d].uri, strlen(origins[d].uri));
    if (!uri)
      continue;
    at += (size_t)lsp_bounded_printf(body + at, capacity - at, "%s\"%s\":[",
                                     document_comma ? "," : "", uri);
    bool edit_comma = false;
    for (size_t i = 0; i < origin_count; ++i)
      if (!strcmp(origins[i].uri, origins[d].uri)) {
        at += (size_t)lsp_bounded_printf(
            body + at, capacity - at,
            "%s{\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{"
            "\"line\":%zu,\"character\":%zu}},\"newText\":\"%s\"}",
            edit_comma ? "," : "", origins[i].line, origins[i].column,
            origins[i].line, origins[i].column + origins[i].length,
            replacement);
        edit_comma = true;
      }
    at += (size_t)lsp_bounded_printf(body + at, capacity - at, "]");
    document_comma = true;
    free(uri);
  }
  lsp_bounded_printf(body + at, capacity - at, "}}}");
  lsp_send(body);
  free(body);
}

static bool lsp_function_origin(LspSemantic *semantic, uint32_t index,
                                LspOrigin *origin) {
  return index < semantic->ast.function_count &&
         lsp_origin_identifier(&semantic->source,
                               semantic->ast.functions[index].name, origin);
}

static size_t lsp_call_item(LspSemantic *semantic, uint32_t function,
                            const char *data, char *body, size_t capacity,
                            size_t at) {
  LspOrigin origin;
  if (!lsp_function_origin(semantic, function, &origin))
    return at;
  DynAstFn *fn = &semantic->ast.functions[function];
  char *name = json_escape(semantic->source.text + fn->name.end_byte -
                               origin.length,
                           origin.length),
       *uri = json_escape(origin.uri, strlen(origin.uri)),
       *escaped_data = data ? json_escape(data, strlen(data)) : NULL;
  if (name && uri)
    at += (size_t)lsp_bounded_printf(
        body + at, capacity - at,
        "{\"name\":\"%s\",\"kind\":12,\"uri\":\"%s\",\"range\":{\"start\":{"
        "\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%zu,\"character\":%"
        "zu}},\"selectionRange\":{\"start\":{\"line\":%zu,\"character\":%zu},"
        "\"end\":{\"line\":%zu,\"character\":%zu}}%s%s%s}",
        name, uri, origin.line, origin.column, origin.line,
        origin.column + origin.length, origin.line, origin.column, origin.line,
        origin.column + origin.length, escaped_data ? ",\"data\":\"" : "",
        escaped_data ? escaped_data : "", escaped_data ? "\"" : "");
  free(name);
  free(uri);
  free(escaped_data);
  return at;
}

static uint32_t lsp_function_for_span(LspSemantic *semantic, DynSpan span) {
  for (uint32_t i = 0; i < semantic->ast.function_count; ++i)
    if (lsp_same_span(semantic->ast.functions[i].name, span))
      return i;
  return UINT32_MAX;
}

void lsp_prepare_call_hierarchy(long id, LspDocument *documents, size_t count,
                                LspDocument *requested, size_t line,
                                size_t character) {
  LspSemantic semantic =
      lsp_semantic_project(documents, count, requested, requested->text);
  if (!semantic.ok) {
    lsp_semantic_free(&semantic);
    semantic = lsp_semantic_build_related(documents, count, requested);
  }
  uint32_t offset = 0;
  DynSpan definition = {0};
  char hover[8];
  uint32_t function = UINT32_MAX;
  bool found =
      semantic.ok &&
      lsp_semantic_offset(&semantic, requested, line, character, &offset) &&
      lsp_typed_symbol(&semantic, offset, hover, sizeof(hover), &definition) &&
      (function = lsp_function_for_span(&semantic, definition)) != UINT32_MAX;
  char body[4096];
  size_t at = (size_t)lsp_bounded_printf(
      body, sizeof(body), "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":", id);
  if (found) {
    char data[1200];
    snprintf(data, sizeof(data), "%u|%s", function, requested->uri);
    at += (size_t)lsp_bounded_printf(body + at, sizeof(body) - at, "[");
    at = lsp_call_item(&semantic, function, data, body, sizeof(body), at);
    at += (size_t)lsp_bounded_printf(body + at, sizeof(body) - at, "]");
  } else
    at += (size_t)lsp_bounded_printf(body + at, sizeof(body) - at, "null");
  lsp_bounded_printf(body + at, sizeof(body) - at, "}");
  lsp_send(body);
  lsp_semantic_free(&semantic);
}

static bool lsp_call_data(const char *body, uint32_t *function, char **uri) {
  char *data = json_string_after(body, "\"data\"", 64u * 1024u);
  if (!data)
    return false;
  char *bar = strchr(data, '|');
  if (!bar) {
    free(data);
    return false;
  }
  *bar = 0;
  *function = (uint32_t)strtoul(data, NULL, 10);
  *uri = strdup(bar + 1);
  free(data);
  return *uri != NULL;
}

void lsp_call_hierarchy(long id, LspDocument *documents, size_t count,
                        const char *request, bool incoming) {
  uint32_t target = UINT32_MAX;
  char *source_uri = NULL;
  LspDocument *requested = NULL;
  bool parsed = lsp_call_data(request, &target, &source_uri);
  if (parsed)
    requested = lsp_document(documents, count, source_uri);
  LspSemantic semantic =
      requested
          ? lsp_semantic_project(documents, count, requested, requested->text)
          : (LspSemantic){0};
  if (requested && !semantic.ok) {
    lsp_semantic_free(&semantic);
    semantic = lsp_semantic_build_related(documents, count, requested);
  }
  size_t capacity = 1024u * 1024u, at = 0;
  char *body = malloc(capacity);
  if (!body) {
    free(source_uri);
    lsp_semantic_free(&semantic);
    return;
  }
  at = (size_t)lsp_bounded_printf(
      body, capacity, "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id);
  bool comma = false;
  if (semantic.ok && target < semantic.ast.function_count)
    for (uint32_t i = 0; i < semantic.ast.expression_count; ++i) {
      DynAstExpr *call = &semantic.ast.expressions[i];
      if (call->kind != DYN_EXPR_CALL ||
          call->integer >= semantic.ast.function_count)
        continue;
      uint32_t item_function = incoming ? UINT32_MAX : (uint32_t)call->integer;
      if (incoming) {
        if (call->integer != target)
          continue;
        for (uint32_t f = 0; f < semantic.ast.function_count; ++f)
          if (call->span.start_byte >=
                  semantic.ast.functions[f].span.start_byte &&
              call->span.end_byte <= semantic.ast.functions[f].span.end_byte) {
            item_function = f;
            break;
          }
      } else if (!(call->span.start_byte >=
                       semantic.ast.functions[target].span.start_byte &&
                   call->span.end_byte <=
                       semantic.ast.functions[target].span.end_byte))
        continue;
      if (item_function == UINT32_MAX)
        continue;
      const char *path = NULL;
      unsigned line = 0, column = 0;
      dyn_source_location(&semantic.source, call->span.start_byte, &path, &line,
                          &column);
      if (!path)
        continue;
      char data[1200];
      snprintf(data, sizeof(data), "%u|%s", item_function, source_uri);
      at += (size_t)lsp_bounded_printf(body + at, capacity - at,
                                       "%s{\"%s\":", comma ? "," : "",
                                       incoming ? "from" : "to");
      at = lsp_call_item(&semantic, item_function, data, body, capacity, at);
      at += (size_t)lsp_bounded_printf(
          body + at, capacity - at,
          ",\"%sRanges\":[{\"start\":{\"line\":%u,\"character\":%u},\"end\":{"
          "\"line\":%u,\"character\":%u}}]}",
          incoming ? "from" : "from", line ? line - 1 : 0,
          column ? column - 1 : 0, line ? line - 1 : 0,
          (column ? column - 1 : 0) +
              (call->span.end_byte - call->span.start_byte));
      comma = true;
    }
  lsp_bounded_printf(body + at, capacity - at, "]}");
  lsp_send(body);
  free(body);
  free(source_uri);
  lsp_semantic_free(&semantic);
}

static void lsp_function_hover(LspSemantic *semantic, uint32_t index, char *out,
                               size_t capacity) {
  DynAstProgram *a = &semantic->ast;
  DynAstFn *fn = &a->functions[index];
  size_t at = 0;
#define APPEND(...)                                                            \
  do {                                                                         \
    if (at < capacity) {                                                       \
      int n = snprintf(out + at, capacity - at, __VA_ARGS__);                  \
      if (n > 0)                                                               \
        at += (size_t)n < capacity - at ? (size_t)n : capacity - at - 1;       \
    }                                                                          \
  } while (0)
  APPEND("%s%sfn %.*s(", fn->is_public ? "pub " : "",
         fn->foreign ? "extern " : "",
         (int)(fn->name.end_byte - fn->name.start_byte),
         semantic->source.text + fn->name.start_byte);
  for (uint32_t i = 0; i < fn->param_count; ++i) {
    DynAstParam *p = &a->params[fn->param_start + i];
    char type[128];
    dyn_type_format(a, p->type, &semantic->source, type, sizeof(type));
    APPEND("%s%.*s: %s", i ? ", " : "",
           (int)(p->name.end_byte - p->name.start_byte),
           semantic->source.text + p->name.start_byte, type);
  }
  if (fn->variadic) {
    if (fn->param_count)
      APPEND(", ");
    if (fn->variadic_name.end_byte > fn->variadic_name.start_byte) {
      DynType t = fn->variadic_type;
      if (dyn_type_is_slice(t)) {
        uint32_t i = t - DYN_TYPE_SLICE_BASE;
        if (i < a->slice_count)
          t = a->slices[i].element;
      }
      char type[128];
      dyn_type_format(a, t, &semantic->source, type, sizeof(type));
      APPEND("%.*s: ...%s",
             (int)(fn->variadic_name.end_byte - fn->variadic_name.start_byte),
             semantic->source.text + fn->variadic_name.start_byte, type);
    } else
      APPEND("...");
  }
  APPEND(")");
  if (fn->return_type != DYN_TYPE_VOID) {
    char type[128];
    dyn_type_format(a, fn->return_type, &semantic->source, type, sizeof(type));
    APPEND(" %s", type);
  }
#undef APPEND
}

static bool lsp_field_source_type(LspSemantic *semantic, DynAstField *field,
                                  char *out, size_t capacity) {
  if (!capacity || field->name.end_byte >= semantic->source.length)
    return false;
  const char *text = semantic->source.text, *p = text + field->name.end_byte;
  size_t length = semantic->source.length;
  const char *path;
  unsigned source_line, source_column;
  dyn_source_location(&semantic->source, field->name.end_byte, &path,
                      &source_line, &source_column);
  for (size_t i = 0; i < semantic->source.map_count; ++i) {
    DynSourceMap *map = &semantic->source.maps[i];
    if (strcmp(map->path, path))
      continue;
    text = map->original_text;
    length = map->original_length;
    p = text;
    for (unsigned row = 1; row < source_line; ++row) {
      const char *next = strchr(p, '\n');
      if (!next)
        return false;
      p = next + 1;
    }
    const char *end = strchr(p, '\n');
    if (!end)
      end = text + length;
    if (!source_column || source_column - 1 > (size_t)(end - p))
      return false;
    p += source_column - 1;
    break;
  }
  TSTree *tree = lsp_parse(text, length);
  if (!tree)
    return false;
  uint32_t offset = (uint32_t)(p - text);
  TSNode member = ts_node_named_descendant_for_byte_range(
      ts_tree_root_node(tree), offset, offset);
  while (!ts_node_is_null(member) &&
         strcmp(ts_node_type(member), "struct_member"))
    member = ts_node_parent(member);
  TSNode type = ts_node_is_null(member) ? (TSNode){0} : lsp_type_node(member);
  bool found = !ts_node_is_null(type);
  if (found) {
    size_t start = ts_node_start_byte(type), n = ts_node_end_byte(type) - start;
    if (!n || n >= capacity)
      found = false;
    else {
      memcpy(out, text + start, n);
      out[n] = 0;
    }
  }
  ts_tree_delete(tree);
  return found;
}

static void lsp_struct_hover(LspSemantic *semantic, uint32_t index, char *out,
                             size_t capacity) {
  DynAstProgram *a = &semantic->ast;
  DynAstStruct *s = &a->structs[index];
  size_t at = 0;
#define APPEND_STRUCT(...)                                                     \
  do {                                                                         \
    if (at < capacity) {                                                       \
      int n = snprintf(out + at, capacity - at, __VA_ARGS__);                  \
      if (n > 0)                                                               \
        at += (size_t)n < capacity - at ? (size_t)n : capacity - at - 1;       \
    }                                                                          \
  } while (0)
  APPEND_STRUCT("%s%sstruct %.*s {", s->is_public ? "pub " : "",
                s->packed ? "packed " : "",
                (int)(s->name.end_byte - s->name.start_byte),
                semantic->source.text + s->name.start_byte);
  uint32_t shown = s->field_count < 8 ? s->field_count : 8;
  for (uint32_t i = 0; i < shown; ++i) {
    DynAstField *field = &a->fields[s->field_start + i];
    char type[128];
    if (!lsp_field_source_type(semantic, field, type, sizeof(type)))
      dyn_type_format(a, field->type, &semantic->source, type, sizeof(type));
    APPEND_STRUCT("\n  %.*s: %s",
                  (int)(field->name.end_byte - field->name.start_byte),
                  semantic->source.text + field->name.start_byte, type);
  }
  if (shown < s->field_count)
    APPEND_STRUCT("\n  ... %u more", s->field_count - shown);
  APPEND_STRUCT("\n}");
#undef APPEND_STRUCT
}

static void lsp_enum_hover(LspSemantic *semantic, uint32_t index, char *out,
                           size_t capacity) {
  DynAstProgram *a = &semantic->ast;
  DynAstEnum *e = &a->enums[index];
  size_t at = (size_t)snprintf(out, capacity, "%senum %.*s {",
                               e->is_public ? "pub " : "",
                               (int)(e->name.end_byte - e->name.start_byte),
                               semantic->source.text + e->name.start_byte);
  uint32_t shown = e->variant_count < 8 ? e->variant_count : 8;
  for (uint32_t i = 0; i < shown && at < capacity; ++i) {
    DynAstVariant *v = &a->variants[e->variant_start + i];
    char payload[128] = {0};
    if (v->payload_type != DYN_TYPE_VOID)
      dyn_type_format(a, v->payload_type, &semantic->source, payload,
                      sizeof(payload));
    int n = snprintf(out + at, capacity - at, "\n  %.*s%s%s",
                     (int)(v->name.end_byte - v->name.start_byte),
                     semantic->source.text + v->name.start_byte,
                     *payload ? " " : "", payload);
    if (n > 0)
      at += (size_t)n < capacity - at ? (size_t)n : capacity - at - 1;
  }
  if (shown < e->variant_count && at < capacity) {
    int n = snprintf(out + at, capacity - at, "\n  ... %u more",
                     e->variant_count - shown);
    if (n > 0)
      at += (size_t)n < capacity - at ? (size_t)n : capacity - at - 1;
  }
  if (at < capacity)
    snprintf(out + at, capacity - at, "\n}");
}

static void lsp_alias_hover(LspSemantic *semantic, uint32_t index, char *out,
                            size_t capacity) {
  DynAstAlias *alias = &semantic->ast.aliases[index];
  char target[256];
  dyn_type_format(&semantic->ast, alias->target, &semantic->source, target,
                  sizeof(target));
  snprintf(out, capacity, "%s%stype %.*s = %s", alias->is_public ? "pub " : "",
           alias->distinct ? "distinct " : "",
           (int)(alias->name.end_byte - alias->name.start_byte),
           semantic->source.text + alias->name.start_byte, target);
}

static void lsp_global_hover(LspSemantic *semantic, uint32_t index, char *out,
                             size_t capacity) {
  DynAstGlobal *global = &semantic->ast.globals[index];
  char type[256];
  dyn_type_format(&semantic->ast, global->type, &semantic->source, type,
                  sizeof(type));
  snprintf(out, capacity, "%s%s %.*s: %s", global->is_public ? "pub " : "",
           global->is_const ? "const" : "global",
           (int)(global->name.end_byte - global->name.start_byte),
           semantic->source.text + global->name.start_byte, type);
}

bool lsp_typed_symbol(LspSemantic *semantic, uint32_t offset, char *hover,
                      size_t capacity, DynSpan *definition) {
  DynAstProgram *a = &semantic->ast;
  DynAstExpr *best = NULL;
  for (size_t i = 0; i < a->expression_count; ++i) {
    DynAstExpr *e = &a->expressions[i];
    if (offset >= e->span.start_byte && offset < e->span.end_byte &&
        e->type != DYN_TYPE_INFER && e->type != DYN_TYPE_ERROR)
      if (!best || e->span.end_byte - e->span.start_byte <
                       best->span.end_byte - best->span.start_byte)
        best = e;
  }
  DynType type = DYN_TYPE_ERROR;
  DynSpan declared = {0};
  const char *kind = "value";
  uint32_t function = UINT32_MAX, structure = UINT32_MAX,
           enumeration = UINT32_MAX, alias = UINT32_MAX, global = UINT32_MAX;
  if (best) {
    type = best->type;
    if (best->kind == DYN_EXPR_NAME && best->integer < a->local_count) {
      declared = a->locals[best->integer].name;
      kind = a->locals[best->integer].is_const ? "const" : "variable";
    } else if (best->kind == DYN_EXPR_GLOBAL &&
               best->integer < a->global_count) {
      global = (uint32_t)best->integer;
      declared = a->globals[global].name;
      kind = a->globals[global].is_const ? "const" : "global";
    } else if (best->kind == DYN_EXPR_FUNCTION &&
               best->integer < a->function_count) {
      function = (uint32_t)best->integer;
      declared = a->functions[function].name;
      kind = "function";
    } else if (best->kind == DYN_EXPR_FIELD &&
               best->left < a->expression_count) {
      DynType base = a->expressions[best->left].type;
      if (dyn_type_is_pointer(base)) {
        uint32_t pointer = base - DYN_TYPE_POINTER_BASE;
        if (pointer < a->pointer_count)
          base = a->pointers[pointer].pointee;
      }
      if (dyn_type_is_struct(base)) {
        DynAstStruct *structure = &a->structs[base - DYN_TYPE_STRUCT_BASE];
        if (best->integer < structure->field_count)
          declared =
              a->fields[structure->field_start + (uint32_t)best->integer].name;
        kind = "field";
      }
    }
  }
  if (function == UINT32_MAX && offset < semantic->source.length) {
    uint32_t start = offset, end = offset;
    while (start && ((unsigned char)semantic->source.text[start - 1] == '_' ||
                     isalnum((unsigned char)semantic->source.text[start - 1])))
      --start;
    while (end < semantic->source.length &&
           ((unsigned char)semantic->source.text[end] == '_' ||
            isalnum((unsigned char)semantic->source.text[end])))
      ++end;
    for (size_t i = 0; i < a->function_count; ++i) {
      DynSpan name = a->functions[i].name;
      if (name.end_byte - name.start_byte == end - start &&
          !memcmp(semantic->source.text + name.start_byte,
                  semantic->source.text + start, end - start)) {
        function = (uint32_t)i;
        type = DYN_TYPE_VOID;
        declared = name;
        kind = "function";
        break;
      }
    }
    for (size_t i = 0; i < a->struct_count && structure == UINT32_MAX; ++i) {
      DynSpan name = a->structs[i].name;
      if (name.end_byte - name.start_byte == end - start &&
          !memcmp(semantic->source.text + name.start_byte,
                  semantic->source.text + start, end - start)) {
        structure = (uint32_t)i;
        type = DYN_TYPE_STRUCT_BASE + (DynType)i;
        declared = name;
        kind = "struct";
      }
    }
    for (size_t i = 0; i < a->enum_count && enumeration == UINT32_MAX; ++i) {
      DynSpan name = a->enums[i].name;
      if (name.end_byte - name.start_byte == end - start &&
          !memcmp(semantic->source.text + name.start_byte,
                  semantic->source.text + start, end - start)) {
        enumeration = (uint32_t)i;
        type = DYN_TYPE_ENUM_BASE + (DynType)i;
        declared = name;
        kind = "enum";
      }
    }
    for (size_t i = 0; i < a->alias_count && alias == UINT32_MAX; ++i) {
      DynSpan name = a->aliases[i].name;
      if (name.end_byte - name.start_byte == end - start &&
          !memcmp(semantic->source.text + name.start_byte,
                  semantic->source.text + start, end - start)) {
        alias = (uint32_t)i;
        type = a->aliases[i].target;
        declared = name;
        kind = "type";
      }
    }
    for (size_t i = 0; i < a->global_count && global == UINT32_MAX; ++i) {
      DynSpan name = a->globals[i].name;
      if (name.end_byte - name.start_byte == end - start &&
          !memcmp(semantic->source.text + name.start_byte,
                  semantic->source.text + start, end - start)) {
        global = (uint32_t)i;
        type = a->globals[i].type;
        declared = name;
        kind = a->globals[i].is_const ? "const" : "global";
      }
    }
  }
  for (size_t i = 0; i < a->function_count && function == UINT32_MAX; ++i)
    if (offset >= a->functions[i].name.start_byte &&
        offset < a->functions[i].name.end_byte) {
      function = (uint32_t)i;
      type = DYN_TYPE_VOID;
      declared = a->functions[i].name;
      kind = "function";
    }
  for (size_t i = 0; i < a->local_count && type == DYN_TYPE_ERROR; ++i)
    if (offset >= a->locals[i].name.start_byte &&
        offset < a->locals[i].name.end_byte) {
      type = a->locals[i].type;
      declared = a->locals[i].name;
      kind = a->locals[i].is_const ? "const" : "variable";
    }
  if (type == DYN_TYPE_ERROR)
    return false;
  if (function != UINT32_MAX) {
    lsp_function_hover(semantic, function, hover, capacity);
    *definition = declared;
    return true;
  }
  if (structure != UINT32_MAX) {
    lsp_struct_hover(semantic, structure, hover, capacity);
    *definition = declared;
    return true;
  }
  if (enumeration != UINT32_MAX) {
    lsp_enum_hover(semantic, enumeration, hover, capacity);
    *definition = declared;
    return true;
  }
  if (alias != UINT32_MAX) {
    lsp_alias_hover(semantic, alias, hover, capacity);
    *definition = declared;
    return true;
  }
  if (global != UINT32_MAX) {
    lsp_global_hover(semantic, global, hover, capacity);
    *definition = declared;
    return true;
  }
  char name[384];
  dyn_type_format(a, type, &semantic->source, name, sizeof(name));
  if (declared.end_byte > declared.start_byte) {
    size_t declared_length = declared.end_byte - declared.start_byte;
    if (declared_length > 96)
      declared_length = 96;
    snprintf(hover, capacity, "%s %.*s: %.*s", kind, (int)declared_length,
             semantic->source.text + declared.start_byte, 383, name);
  } else
    snprintf(hover, capacity, "%s: %.*s", kind, 383, name);
  *definition = declared;
  return true;
}

bool lsp_type_definition_span(LspSemantic *semantic, uint32_t offset,
                              DynSpan *definition) {
  DynAstProgram *a = &semantic->ast;
  DynType type = DYN_TYPE_ERROR;
  DynAstExpr *best = NULL;
  for (size_t i = 0; i < a->expression_count; ++i) {
    DynAstExpr *e = &a->expressions[i];
    if (offset >= e->span.start_byte && offset < e->span.end_byte &&
        e->type != DYN_TYPE_INFER && e->type != DYN_TYPE_ERROR)
      if (!best || e->span.end_byte - e->span.start_byte <
                       best->span.end_byte - best->span.start_byte)
        best = e;
  }
  if (best)
    type = best->type;
  for (size_t i = 0; i < a->local_count && type == DYN_TYPE_ERROR; ++i)
    if (offset >= a->locals[i].name.start_byte &&
        offset < a->locals[i].name.end_byte)
      type = a->locals[i].type;
  if (dyn_type_is_pointer(type)) {
    uint32_t p = type - DYN_TYPE_POINTER_BASE;
    if (p < a->pointer_count)
      type = a->pointers[p].pointee;
  }
  if (dyn_type_is_struct(type)) {
    uint32_t i = type - DYN_TYPE_STRUCT_BASE;
    if (i < a->struct_count) {
      *definition = a->structs[i].name;
      return true;
    }
  }
  if (dyn_type_is_enum(type)) {
    uint32_t i = type - DYN_TYPE_ENUM_BASE;
    if (i < a->enum_count) {
      *definition = a->enums[i].name;
      return true;
    }
  }
  if (dyn_type_is_distinct(type)) {
    uint32_t i = type - DYN_TYPE_DISTINCT_BASE;
    if (i < a->alias_count) {
      *definition = a->aliases[i].name;
      return true;
    }
  }
  return false;
}

bool lsp_import_definition(LspDocument *document, size_t line, size_t character,
                           char **uri, size_t *out_line, size_t *out_column,
                           size_t *out_length) {
  if (!document || !document->text)
    return false;
  const char *row = document->text;
  for (size_t i = 0; i < line; ++i) {
    row = strchr(row, '\n');
    if (!row)
      return false;
    ++row;
  }
  const char *row_end = strchr(row, '\n');
  if (!row_end)
    row_end = row + strlen(row);
  uint32_t offset =
      (uint32_t)(row - document->text +
                 (character > (size_t)(row_end - row) ? (size_t)(row_end - row)
                                                      : character));
  LspImport imports[32];
  size_t count = lsp_imports(document, imports, 32);
  LspImport *import = NULL;
  char member[128] = {0};
  for (size_t i = 0; i < count; ++i)
    if (offset >= ts_node_start_byte(imports[i].node) &&
        offset <= ts_node_end_byte(imports[i].node)) {
      import = &imports[i];
      break;
    }
  if (!import) {
    const char *word = NULL;
    size_t length = 0;
    if (!identifier_at(document->text, line, character, &word, &length) &&
        !lsp_call_identifier(document->text, line, character, &word, &length))
      return false;
    const char *dot = NULL, *member_start = NULL;
    size_t member_length = 0;
    if (word > row && word[-1] == '.') {
      dot = word - 1;
      member_start = word;
      member_length = length;
    } else if (word + length < row_end && word[length] == '.') {
      dot = word + length;
      member_start = dot + 1;
      while (member_start + member_length < row_end &&
             (isalnum((unsigned char)member_start[member_length]) ||
              member_start[member_length] == '_'))
        ++member_length;
    }
    if (!dot || !member_length || member_length >= sizeof(member))
      return false;
    const char *alias_end = dot, *alias_start = alias_end;
    while (alias_start > row &&
           (isalnum((unsigned char)alias_start[-1]) || alias_start[-1] == '_'))
      --alias_start;
    for (size_t i = 0; i < count; ++i)
      if (strlen(imports[i].alias) == (size_t)(alias_end - alias_start) &&
          !memcmp(imports[i].alias, alias_start,
                  (size_t)(alias_end - alias_start))) {
        import = &imports[i];
        break;
      }
    if (!import)
      return false;
    memcpy(member, member_start, member_length);
    member[member_length] = 0;
  }
  char *target = lsp_resolve_import(document, import->path);
  if (!target)
    return false;
  if (!*member) {
    char *path = lsp_first_dyn_file(target);
    free(target);
    if (!path)
      return false;
    *uri = lsp_path_uri(path);
    free(path);
    *out_line = *out_column = 0;
    *out_length = 1;
    return *uri != NULL;
  }
  DynSources sources = {0};
  bool found = false;
  if (!dyn_sources_load(NULL, target, &sources))
    for (size_t i = 0; i < sources.count && !found; ++i) {
      const char *display = NULL;
      size_t display_length = 0;
      if (find_declaration(sources.items[i].text, member, strlen(member),
                           out_line, out_column, &display, &display_length)) {
        *uri = lsp_path_uri(sources.items[i].path);
        *out_length = strlen(member);
        found = *uri != NULL;
      }
    }
  dyn_sources_free(&sources);
  free(target);
  return found;
}

void lsp_import_hover_text(const char *path, size_t line, char *out,
                           size_t capacity) {
  if (!capacity)
    return;
  out[0] = 0;
  char *text = lsp_read_source(path);
  if (!text)
    return;
  TSTree *tree = lsp_parse(text, strlen(text));
  if (tree) {
    TSNode root = ts_tree_root_node(tree);
    for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
      DynDeclaration decl;
      TSNode wrapper = ts_node_named_child(root, i);
      if (!dyn_syntax_declaration(wrapper, &decl) ||
          ts_node_start_point(decl.name).row != line)
        continue;
      size_t start = ts_node_start_byte(wrapper),
             end = ts_node_end_byte(wrapper);
      if (decl.kind == DYN_DECL_FUNCTION)
        for (uint32_t j = 0; j < ts_node_named_child_count(decl.node); ++j) {
          TSNode child = ts_node_named_child(decl.node, j);
          if (!strcmp(ts_node_type(child), "block")) {
            end = ts_node_start_byte(child);
            break;
          }
        }
      while (end > start && isspace((unsigned char)text[end - 1]))
        --end;
      snprintf(out, capacity, "%.*s", (int)(end - start), text + start);
      if (decl.kind == DYN_DECL_STRUCT || decl.kind == DYN_DECL_ENUM) {
        /* Omit optional end-of-line separators in the hover presentation. */
        for (uint32_t j = ts_node_child_count(decl.node); j; --j) {
          TSNode token = ts_node_child(decl.node, j - 1);
          if (strcmp(ts_node_type(token), ","))
            continue;
          size_t offset = ts_node_start_byte(token) - start;
          if (offset >= strlen(out))
            continue;
          size_t after = offset + 1;
          while (out[after] == ' ' || out[after] == '\t' || out[after] == '\r')
            ++after;
          if (!out[after] || out[after] == '\n')
            memmove(out + offset, out + offset + 1, strlen(out + offset));
        }
      }
      break;
    }
    ts_tree_delete(tree);
  }
  free(text);
}
