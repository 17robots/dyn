#define _POSIX_C_SOURCE 200809L
#include "lsp_internal.h"

typedef struct {
  const char *name;
  size_t length;
} LspImportSymbol;
static bool lsp_import_symbol_matches(const char *name, size_t length,
                                      DynDeclarationKind kind, void *context);
typedef struct { char paths[32][1024]; size_t count; } LspImportChoices;
static void lsp_find_public_import(const char *directory, const char *import_path,
                                  const char *symbol, size_t symbol_length,
                                  LspImportChoices *choices, unsigned depth);
static void lsp_missing_import(const LspDocument *document, const char *symbol,
                               size_t length, LspImportChoices *choices);
static bool lsp_default_value(LspSemantic *semantic, DynType type, char *out,
                              size_t capacity, size_t *at, unsigned depth);
static bool lsp_fill_struct_fields(LspDocument *documents, size_t count,
                                   LspDocument *document, size_t line,
                                   size_t character, char *text,
                                   size_t capacity, TSPoint *edit);
static bool lsp_action_diagnostic(const char *body, const char *key,
                                  const char *value);

static bool lsp_import_symbol_matches(const char *name, size_t length,
                                      DynDeclarationKind kind, void *context) {
  (void)kind;
  LspImportSymbol *symbol = context;
  return length == symbol->length && !memcmp(name, symbol->name, length);
}

static void lsp_add_import_choice(LspImportChoices *choices, const char *path) {
  if (strlen(path) >= sizeof(choices->paths[0]) || !lsp_import_path_representable(path))
    return;
  size_t at = 0;
  while (at < choices->count && strcmp(choices->paths[at], path) < 0) ++at;
  if (at < choices->count && !strcmp(choices->paths[at], path)) return;
  if (at == 32) return;
  if (choices->count < 32) ++choices->count;
  for (size_t i = choices->count - 1; i > at; --i)
    memcpy(choices->paths[i], choices->paths[i - 1], sizeof(choices->paths[i]));
  strcpy(choices->paths[at], path);
}
static void lsp_find_public_import(const char *directory, const char *import_path,
                                  const char *symbol, size_t symbol_length,
                                  LspImportChoices *choices, unsigned depth) {
  if (depth > 16) return;
  DIR *dir = opendir(directory);
  if (!dir) return;
  struct dirent *entry;
  while ((entry = readdir(dir))) {
    if (entry->d_name[0] == '.' || !lsp_import_path_representable(entry->d_name)) continue;
    char *path = dyn_path_join(directory, entry->d_name);
    if (!path) continue;
    if (dyn_path_is_directory(path)) {
      char child[1024];
      int n = snprintf(child, sizeof(child), "%s/%s", import_path, entry->d_name);
      if (n > 0 && (size_t)n < sizeof(child))
        lsp_find_public_import(path, child, symbol, symbol_length, choices, depth + 1);
    } else {
      size_t n = strlen(path);
      LspImportSymbol wanted = {symbol, symbol_length};
      if (n >= 4 && !strcmp(path + n - 4, ".dyn") &&
          lsp_public_declarations(path, lsp_import_symbol_matches, &wanted))
        lsp_add_import_choice(choices, import_path);
    }
    free(path);
  }
  closedir(dir);
}
static void lsp_missing_import(const LspDocument *document, const char *symbol,
                               size_t length, LspImportChoices *choices) {
  char *std_package = lsp_resolve_import(document, "std/io"),
       *std_root = std_package ? lsp_directory(std_package) : NULL;
  char *vendor_package = lsp_resolve_import(document, "vendor/sqlite"),
       *vendor_root = vendor_package ? lsp_directory(vendor_package) : NULL;
  if (std_root) lsp_find_public_import(std_root, "std", symbol, length, choices, 0);
  if (vendor_root) lsp_find_public_import(vendor_root, "vendor", symbol, length, choices, 0);
  free(std_package); free(std_root); free(vendor_package); free(vendor_root);
}
static bool lsp_send_import_choices(long id, const LspImportChoices *choices,
                                    const char *uri, const char *word, size_t length,
                                    size_t line, size_t start, size_t end) {
  /* Each bounded import path occurs twice. URI and identifier sizes are shared. */
  size_t uri_length = strlen(uri);
  if (uri_length > SIZE_MAX / 64 || length > SIZE_MAX / 128) return false;
  size_t per_item = uri_length + length * 2 + 9000;
  if (per_item > (SIZE_MAX - 128) / 32) return false;
  size_t capacity = per_item * choices->count + 128;
  char *response = malloc(capacity);
  if (!response) return false;
  size_t at = (size_t)snprintf(response, capacity,
      "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[", id);
  for (size_t i = 0; i < choices->count; ++i) {
    const char *path = choices->paths[i], *slash = strrchr(path, '/');
    const char *alias = slash ? slash + 1 : path;
    int n = snprintf(response + at, capacity - at,
      "%s{\"title\":\"Import %.*s from %s\",\"kind\":\"quickfix\","
      "\"isPreferred\":%s,\"edit\":{\"changes\":{\"%s\":["
      "{\"range\":{\"start\":{\"line\":0,\"character\":0},"
      "\"end\":{\"line\":0,\"character\":0}},\"newText\":\"use \\\"%s\\\"\\n\"},"
      "{\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},"
      "\"end\":{\"line\":%zu,\"character\":%zu}},\"newText\":\"%s.%.*s\"}]}}}",
      i ? "," : "", (int)length, word, path, choices->count == 1 ? "true" : "false",
      uri, path, line, start, line, end, alias, (int)length, word);
    if (n < 0 || (size_t)n >= capacity - at) { free(response); return false; }
    at += (size_t)n;
  }
  snprintf(response + at, capacity - at, "]}");
  lsp_send(response); free(response); return true;
}

static bool lsp_default_value(LspSemantic *semantic, DynType type, char *out,
                              size_t capacity, size_t *at, unsigned depth) {
  if (depth > 16)
    return false;
  DynAstProgram *a = &semantic->ast;
#define DEFAULT_APPEND(...)                                                    \
  do {                                                                         \
    int n = snprintf(out + *at, capacity - *at, __VA_ARGS__);                  \
    if (n < 0 || (size_t)n >= capacity - *at) {                                \
      return false;                                                            \
    }                                                                          \
    *at += (size_t)n;                                                          \
  } while (0)
  if (dyn_type_is_distinct(type)) {
    uint32_t index = type - DYN_TYPE_DISTINCT_BASE;
    return index < a->alias_count &&
           lsp_default_value(semantic, a->aliases[index].target, out, capacity,
                             at, depth + 1);
  }
  if (type == DYN_TYPE_BOOL) {
    DEFAULT_APPEND("false");
  } else if (dyn_type_is_pointer(type) || type == DYN_TYPE_RAWPTR) {
    DEFAULT_APPEND("nil");
  } else if (type >= DYN_TYPE_I8 && type <= DYN_TYPE_F64) {
    DEFAULT_APPEND("0");
  } else if (dyn_type_is_slice(type)) {
    uint32_t index = type - DYN_TYPE_SLICE_BASE;
    if (index >= a->slice_count)
      return false;
    DynType element = a->slices[index].element;
    if (a->slices[index].is_const && element == DYN_TYPE_U8) {
      DEFAULT_APPEND("\"\"");
    } else if (element == DYN_TYPE_BOOL) {
      DEFAULT_APPEND("([false])[..0]");
    } else if (element >= DYN_TYPE_I8 && element <= DYN_TYPE_F64) {
      DEFAULT_APPEND("([#cast(%s) 0])[..0]", dyn_type_name(element));
    } else
      return false;
  } else if (dyn_type_is_array(type)) {
    uint32_t index = type - DYN_TYPE_ARRAY_BASE;
    if (index >= a->array_count || a->arrays[index].length > 64)
      return false;
    DEFAULT_APPEND("[");
    for (uint64_t i = 0; i < a->arrays[index].length; ++i) {
      if (i) {
        DEFAULT_APPEND(", ");
      }
      if (!lsp_default_value(semantic, a->arrays[index].element, out, capacity,
                             at, depth + 1))
        return false;
    }
    DEFAULT_APPEND("]");
  } else if (dyn_type_is_struct(type)) {
    uint32_t index = type - DYN_TYPE_STRUCT_BASE;
    if (index >= a->struct_count)
      return false;
    DynAstStruct *structure = &a->structs[index];
    DEFAULT_APPEND(".{");
    bool comma = false;
    for (uint32_t i = 0; i < structure->field_count; ++i) {
      DynAstField *field = &a->fields[structure->field_start + i];
      if (field->default_expression != DYN_NO_EXPR)
        continue;
      DEFAULT_APPEND("%s%.*s: ", comma ? ", " : "",
                     (int)(field->name.end_byte - field->name.start_byte),
                     semantic->source.text + field->name.start_byte);
      if (!lsp_default_value(semantic, field->type, out, capacity, at,
                             depth + 1))
        return false;
      comma = true;
    }
    DEFAULT_APPEND("}");
  } else if (dyn_type_is_enum(type)) {
    uint32_t index = type - DYN_TYPE_ENUM_BASE;
    if (index >= a->enum_count || !a->enums[index].variant_count)
      return false;
    DynAstVariant *variant = &a->variants[a->enums[index].variant_start];
    DEFAULT_APPEND(".%.*s",
                   (int)(variant->name.end_byte - variant->name.start_byte),
                   semantic->source.text + variant->name.start_byte);
    if (variant->payload_type != DYN_TYPE_VOID) {
      DEFAULT_APPEND("(");
      if (!lsp_default_value(semantic, variant->payload_type, out, capacity, at,
                             depth + 1))
        return false;
      DEFAULT_APPEND(")");
    }
  } else
    return false;
#undef DEFAULT_APPEND
  return true;
}

static bool lsp_fill_struct_fields(LspDocument *documents, size_t count,
                                   LspDocument *document, size_t line,
                                   size_t character, char *text,
                                   size_t capacity, TSPoint *edit) {
  if (!document->tree || !capacity)
    return false;
  TSPoint point = {(uint32_t)line, (uint32_t)character};
  TSNode literal = ts_node_named_descendant_for_point_range(
      ts_tree_root_node(document->tree), point, point);
  while (!ts_node_is_null(literal) &&
         strcmp(ts_node_type(literal), "struct_literal"))
    literal = ts_node_parent(literal);
  if (ts_node_is_null(literal))
    return false;
  TSNode close = {0};
  bool comma = false, has_members = false;
  for (uint32_t i = 0; i < ts_node_child_count(literal); ++i) {
    TSNode child = ts_node_child(literal, i);
    if (ts_node_is_extra(child))
      continue;
    const char *kind = ts_node_type(child);
    if (!strcmp(kind, "}")) {
      close = child;
      break;
    }
    comma = !strcmp(kind, ",");
    if (!strcmp(kind, "struct_literal_member"))
      has_members = true;
  }
  if (ts_node_is_null(close) || ts_node_is_missing(close))
    return false;
  LspSemantic semantic =
      lsp_semantic_project(documents, count, document, document->text);
  uint32_t offset;
  TSPoint start = ts_node_start_point(literal);
  bool ok = semantic.ok && lsp_semantic_offset(&semantic, document, start.row,
                                               start.column, &offset);
  DynType type = DYN_TYPE_ERROR;
  if (ok)
    for (size_t i = 0; i < semantic.ast.expression_count; ++i) {
      DynAstExpr *expression = &semantic.ast.expressions[i];
      if (expression->kind == DYN_EXPR_STRUCT &&
          expression->span.start_byte == offset) {
        type = expression->type;
        break;
      }
    }
  size_t at = 0;
  if (dyn_type_is_struct(type) &&
      type - DYN_TYPE_STRUCT_BASE < semantic.ast.struct_count) {
    DynAstStruct *structure =
        &semantic.ast.structs[type - DYN_TYPE_STRUCT_BASE];
    for (uint32_t i = 0; i < structure->field_count; ++i) {
      DynAstField *field = &semantic.ast.fields[structure->field_start + i];
      if (field->default_expression != DYN_NO_EXPR)
        continue;
      size_t length = field->name.end_byte - field->name.start_byte;
      const char *name = semantic.source.text + field->name.start_byte;
      bool present = false;
      for (uint32_t j = 0; j < ts_node_named_child_count(literal); ++j) {
        TSNode member = ts_node_named_child(literal, j);
        if (strcmp(ts_node_type(member), "struct_literal_member"))
          continue;
        TSNode named = dyn_syntax_child(member, 0);
        size_t a = ts_node_start_byte(named), b = ts_node_end_byte(named);
        if (b - a == length && !memcmp(document->text + a, name, length)) {
          present = true;
          break;
        }
      }
      if (present)
        continue;
      int n = snprintf(text + at, capacity - at,
                       "%s%.*s: ", at || (has_members && !comma) ? ", " : "",
                       (int)length, name);
      if (n < 0 || (size_t)n >= capacity - at) {
        ok = false;
        break;
      }
      at += (size_t)n;
      if (!lsp_default_value(&semantic, field->type, text, capacity, &at, 0)) {
        ok = false;
        break;
      }
    }
  }
  *edit = ts_node_start_point(close);
  lsp_semantic_free(&semantic);
  return ok && at > 0;
}

static bool lsp_action_diagnostic(const char *body, const char *key,
                                  const char *value) {
  const char *params = lsp_json_member(body, "\"params\"");
  const char *context = params ? lsp_json_member(params, "\"context\"") : NULL;
  const char *items =
      context ? lsp_json_member(context, "\"diagnostics\"") : NULL;
  if (!items || *items != '[')
    return false;
  for (const char *item = lsp_json_space(items + 1); *item && *item != ']';) {
    char *field = json_string_after(item, key, 4096);
    bool match = field && strstr(field, value);
    free(field);
    if (match)
      return true;
    item = lsp_json_end(item, 0);
    if (!item)
      break;
    item = lsp_json_space(item);
    if (*item != ',')
      break;
    item = lsp_json_space(item + 1);
  }
  return false;
}

void lsp_code_actions(long id, LspDocument *documents, size_t count,
                      LspDocument *document, const char *body_text) {
  size_t line = 0, character = 0, end_line = 0, end_character = 0;
  (void)json_range_positions(body_text, &line, &character, &end_line,
                             &end_character);
  character = lsp_wire_column(document->text, line, character, true);
  bool unused = lsp_action_diagnostic(body_text, "\"code\"", "unused-use");
  bool unknown =
      lsp_action_diagnostic(body_text, "\"message\"", "unknown name") ||
      lsp_action_diagnostic(body_text, "\"message\"", "unknown function");
  TSNode use = {0};
  LspImport imports[32];
  size_t import_count = lsp_imports(document, imports, 32);
  for (size_t i = 0; i < import_count; ++i) {
    TSPoint start = ts_node_start_point(imports[i].node),
            end = ts_node_end_point(imports[i].node);
    if ((line > start.row ||
         (line == start.row && character >= start.column)) &&
        (line < end.row || (line == end.row && character <= end.column))) {
      use = imports[i].node;
      break;
    }
  }
  char *uri = json_escape(document->uri, strlen(document->uri));
  char response[8192];
  const char *word = NULL;
  size_t word_length = 0;
  char fields[2048] = {0};
  LspImportChoices choices = {0};
  TSPoint insert = {0};
  if (unknown && identifier_at(document->text, line, character, &word, &word_length))
    lsp_missing_import(document, word, word_length, &choices);
  bool can_import = choices.count != 0;
  bool can_fill =
      lsp_fill_struct_fields(documents, count, document, line, character,
                             fields, sizeof(fields), &insert);
  if (unused && !ts_node_is_null(use) && uri) {
    TSPoint start = ts_node_start_point(use), end = ts_node_end_point(use);
    lsp_bounded_printf(
        response, sizeof(response),
        "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[{\"title\":\"Remove "
        "unused "
        "use\",\"kind\":\"quickfix\",\"isPreferred\":true,\"edit\":{"
        "\"changes\":{\"%s\":[{\"range\":{\"start\":{\"line\":%u,\"character\":"
        "%u},\"end\":{\"line\":%u,\"character\":%u}},\"newText\":\"\"}]}}}]}",
        id, uri, start.row, start.column, end.row, end.column);
  } else if (can_import && uri) {
    const char *line_start = word;
    while (line_start > document->text && line_start[-1] != '\n')
      --line_start;
    size_t word_column = (size_t)(word - line_start);
    /* Keep byte columns here; lsp_send converts every outgoing range once. */
    if (lsp_send_import_choices(id, &choices, uri, word, word_length, line,
                                word_column, word_column + word_length)) {
      free(uri);
      return;
    }
    lsp_bounded_printf(response, sizeof(response),
                       "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}", id);
  } else if (can_fill && uri) {
    char *escaped_fields = json_escape(fields, strlen(fields));
    if (escaped_fields) {
      lsp_bounded_printf(
          response, sizeof(response),
          "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[{\"title\":\"Fill "
          "missing struct "
          "fields\",\"kind\":\"refactor.rewrite\",\"edit\":{\"changes\":{\"%"
          "s\":[{\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":"
          "{\"line\":%zu,\"character\":%zu}},\"newText\":\"%s\"}]}}}]}",
          id, uri, (size_t)insert.row, (size_t)insert.column,
          (size_t)insert.row, (size_t)insert.column, escaped_fields);
      free(escaped_fields);
    } else
      lsp_bounded_printf(response, sizeof(response),
                         "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}", id);
  } else
    lsp_bounded_printf(response, sizeof(response),
                       "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}", id);
  lsp_send(response);
  free(uri);
}

void lsp_format(long id, const LspDocument *document) {
  DynSource source = {.path = document->uri,
                      .context = {.target = lsp_target_current(),
                                  .work = lsp_work_current()},
                      .text = document->text,
                      .length = strlen(document->text)};
  char *formatted = NULL;
  size_t length = 0;
  if (!dyn_format_source(&source, &formatted, &length)) {
    char response[96];
    lsp_bounded_printf(response, sizeof(response),
                       "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}", id);
    lsp_send(response);
    return;
  }
  char *escaped = json_escape(formatted, length);
  size_t capacity = (escaped ? strlen(escaped) : 0) + 256;
  char *body = malloc(capacity);
  TSPoint end = lsp_text_end(document->text);
  if (body && escaped) {
    lsp_bounded_printf(body, capacity,
                       "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[{\"range\":"
                       "{\"start\":{\"line\":0,\"character\":0},\"end\":{"
                       "\"line\":%u,\"character\":%u}},\"newText\":\"%s\"}]}",
                       id, end.row, end.column, escaped);
    lsp_send(body);
  }
  free(body);
  free(escaped);
  free(formatted);
}
