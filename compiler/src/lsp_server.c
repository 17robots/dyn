#define _POSIX_C_SOURCE 200809L
#include "lsp_internal.h"

static long request_id(const char *body);
static bool json_hex_quad(const char **input, uint32_t *value);
static bool json_position(const char *body, size_t *line, size_t *character);
static const DynTarget *lsp_target;
const DynTarget *lsp_target_current(void) { return lsp_target; }

#include "lsp_wire.h"
#include "lsp_input.h"
#include "lsp_work.h"

static long request_id(const char *body) {
  const char *p = lsp_json_member(body, "\"id\"");
  if (!p)
    return -1;
  return 0; /* The exact numeric/string ID is preserved by the wire serializer.
             */
}

static bool json_hex_quad(const char **input, uint32_t *value) {
  const char *p = *input;
  uint32_t code = 0;
  for (unsigned i = 0; i < 4; ++i) {
    unsigned char c = (unsigned char)p[i];
    if (!c)
      return false;
    unsigned digit = c >= '0' && c <= '9'   ? c - '0'
                     : c >= 'a' && c <= 'f' ? c - 'a' + 10
                     : c >= 'A' && c <= 'F' ? c - 'A' + 10
                                            : 16;
    if (digit == 16)
      return false;
    code = (code << 4) | digit;
  }
  *input = p + 4;
  *value = code;
  return true;
}

char *json_string_after(const char *body, const char *key, size_t maximum) {
  const char *p = lsp_json_find(body, key);
  if (!p)
    return NULL;
  if (*p != '"')
    return NULL;
  ++p;
  size_t remaining = strlen(p);
  if (remaining < maximum)
    maximum = remaining;
  char *out = calloc(maximum + 1, 1);
  if (!out)
    return NULL;
  size_t at = 0;
  while (*p && *p != '"' && at < maximum) {
    if (*p == '\\') {
      ++p;
      if (!*p)
        break;
      if (*p == 'n')
        out[at++] = '\n';
      else if (*p == 'r')
        out[at++] = '\r';
      else if (*p == 't')
        out[at++] = '\t';
      else if (*p == 'b')
        out[at++] = '\b';
      else if (*p == 'f')
        out[at++] = '\f';
      else if (*p == 'u') {
        ++p;
        uint32_t code;
        if (!json_hex_quad(&p, &code)) {
          free(out);
          return NULL;
        }
        if (code >= 0xd800 && code <= 0xdbff) {
          uint32_t low;
          if (strncmp(p, "\\u", 2)) {
            free(out);
            return NULL;
          }
          p += 2;
          if (!json_hex_quad(&p, &low) || low < 0xdc00 || low > 0xdfff) {
            free(out);
            return NULL;
          }
          code = 0x10000 + ((code - 0xd800) << 10) + (low - 0xdc00);
        } else if (code >= 0xdc00 && code <= 0xdfff) {
          free(out);
          return NULL;
        }
        // Document storage is NUL-terminated; embedded NUL cannot be
        // represented.
        if (!code) {
          free(out);
          return NULL;
        }
        unsigned bytes = code < 0x80      ? 1
                         : code < 0x800   ? 2
                         : code < 0x10000 ? 3
                                          : 4;
        if (bytes > maximum - at) {
          free(out);
          return NULL;
        }
        if (bytes == 1)
          out[at++] = (char)code;
        else {
          unsigned shift = 6 * (bytes - 1);
          out[at++] = (char)((bytes == 2   ? 0xc0
                              : bytes == 3 ? 0xe0
                                           : 0xf0) |
                             (code >> shift));
          while (shift) {
            shift -= 6;
            out[at++] = (char)(0x80 | ((code >> shift) & 0x3f));
          }
        }
        continue;
      } else if (*p == '"' || *p == '\\' || *p == '/')
        out[at++] = *p;
      else {
        free(out);
        return NULL;
      }
      ++p;
    } else
      out[at++] = *p++;
  }
  if (*p != '"') {
    free(out);
    return NULL;
  }
  out[at] = 0;
  return out;
}

bool json_point(const char *point, size_t *line, size_t *character) {
  return point && lsp_json_size(lsp_json_member(point, "\"line\""), line) &&
         lsp_json_size(lsp_json_member(point, "\"character\""), character);
}

static bool json_position(const char *body, size_t *line, size_t *character) {
  const char *position = lsp_json_find(body, "\"position\"");
  if (!position) {
    position = lsp_json_find(body, "\"positions\"");
    if (position && *position == '[')
      position = lsp_json_space(position + 1);
  }
  if (!json_point(position, line, character))
    return false;
  *character = lsp_wire_column(lsp_wire_text, *line, *character, true);
  return true;
}

bool json_range_positions(const char *body, size_t *sl, size_t *sc, size_t *el,
                          size_t *ec) {
  const char *range = lsp_json_find(body, "\"range\"");
  return range && json_point(lsp_json_member(range, "\"start\""), sl, sc) &&
         json_point(lsp_json_member(range, "\"end\""), el, ec);
}

char *json_escape(const char *text, size_t length) {
  if (length > (SIZE_MAX - 1) / 6) return NULL;
  char *out = malloc(length * 6 + 1);
  if (!out)
    return NULL;
  size_t at = 0;
  for (size_t i = 0; i < length; ++i) {
    if (text[i] == '"' || text[i] == '\\') {
      out[at++] = '\\';
      out[at++] = text[i];
    } else if (text[i] == '\n') {
      out[at++] = '\\';
      out[at++] = 'n';
    } else if (text[i] == '\r') {
      out[at++] = '\\';
      out[at++] = 'r';
    } else if (text[i] == '\t') {
      out[at++] = '\\';
      out[at++] = 't';
    } else if ((unsigned char)text[i] < 32) {
      static const char hex[] = "0123456789abcdef";
      out[at++] = '\\'; out[at++] = 'u'; out[at++] = '0'; out[at++] = '0';
      out[at++] = hex[(unsigned char)text[i] >> 4];
      out[at++] = hex[(unsigned char)text[i] & 15];
    } else
      out[at++] = text[i];
  }
  out[at] = 0;
  return out;
}

int dyn_lsp(const DynTarget *target) {
  lsp_target = target;
  int status = 0;
  LspInput input = {0};
  LspWork work_state = {.input = &input};
  char *pending = NULL;
  bool dirty = false;
  uint64_t coalesced = 0;
  LspDocument *documents = NULL;
  size_t document_count = 0, document_capacity = 0;
  DynAnalysisCache analysis_cache = {0};
  uint64_t revision = 0;
  char *workspace_root = NULL;
  for (;;) {
    char *body = pending ? pending : lsp_work_next(&work_state, true);
    pending = NULL;
    lsp_work_begin(&work_state);
    if (!body) { if (input.failed) status = 2; break; }
    free(lsp_wire_id);
    lsp_wire_id = NULL;
    lsp_wire_text = NULL;
    lsp_wire_documents = documents;
    lsp_wire_count = document_count;
    lsp_declaration_documents(documents, document_count);
    lsp_response_overflow = false;
    lsp_wire_number = -1;
    if (!lsp_json_valid(body)) {
      lsp_send("{\"jsonrpc\":\"2.0\",\"id\":null,\"error\":{\"code\":-32700,"
               "\"message\":\"invalid JSON\"}}");
      free(body);
      continue;
    }
    long id = request_id(body);
    lsp_wire_number = id;
    const char *wire_id = lsp_json_member(body, "\"id\"");
    if (wire_id) {
      const char *end = lsp_json_end(wire_id, 0);
      if (end)
        lsp_wire_id = strndup(wire_id, (size_t)(end - wire_id));
    }
    work_state.id = lsp_wire_id;
    char *wire_uri = json_string_after(body, "\"uri\"", 64u * 1024u);
    for (size_t i = 0; wire_uri && i < document_count; ++i)
      if (!strcmp(wire_uri, documents[i].uri)) {
        lsp_wire_text = documents[i].text;
        break;
      }
    free(wire_uri);
    const char *method_value = lsp_json_member(body, "\"method\"");
    const char *version = lsp_json_member(body, "\"jsonrpc\"");
    if (!method_value || *method_value != '"' || !version ||
        strncmp(version, "\"2.0\"", 5) ||
        (wire_id && *wire_id != '"' && *wire_id != '-' &&
         !isdigit((unsigned char)*wire_id) && strncmp(wire_id, "null", 4))) {
      free(lsp_wire_id);
      lsp_wire_id = NULL;
      lsp_send("{\"jsonrpc\":\"2.0\",\"id\":null,\"error\":{\"code\":-32600,"
               "\"message\":\"invalid request\"}}");
      free(body);
      lsp_uri_paths_clear();
      continue;
    }
    char *method_name = json_string_after(body, "\"method\"", 256);
    const char *method = method_name ? method_name : "";
    if ((!strcmp(method, "initialize"))) {
      const char *encodings = lsp_json_find(body, "\"positionEncodings\"");
      lsp_wire_utf8 = false;
      if (encodings && *encodings == '[') {
        const char *end = lsp_json_end(encodings, 0),
                   *utf8 = strstr(encodings, "\"utf-8\"");
        lsp_wire_utf8 = utf8 && end && utf8 < end;
      }
      char *root_uri = json_string_after(body, "\"rootUri\"", 64u * 1024u);
      if (root_uri) {
        free(workspace_root);
        workspace_root = strdup(lsp_file_path(root_uri));
        free(root_uri);
      }
      char response[2048];
      lsp_bounded_printf(
          response, sizeof(response),
          "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"capabilities\":{"
          "\"positionEncoding\":\"%s\",\"textDocumentSync\":{\"openClose\":"
          "true,\"change\":2},\"hoverProvider\":true,"
          "\"definitionProvider\":true,\"declarationProvider\":true,"
          "\"implementationProvider\":true,\"typeDefinitionProvider\":true,"
          "\"referencesProvider\":true,\"renameProvider\":{\"prepareProvider\":"
          "true},"
          "\"documentSymbolProvider\":true,\"workspaceSymbolProvider\":true,"
          "\"documentFormattingProvider\":true,\"inlayHintProvider\":true,"
          "\"codeActionProvider\":true,"
          "\"documentHighlightProvider\":true,\"foldingRangeProvider\":true,"
          "\"selectionRangeProvider\":true,\"callHierarchyProvider\":true,"
          "\"semanticTokensProvider\":{\"legend\":{\"tokenTypes\":["
          "\"namespace\",\"type\","
          "\"struct\",\"enum\",\"parameter\",\"variable\",\"property\","
          "\"enumMember\",\"function\"],"
          "\"tokenModifiers\":[\"readonly\"]},\"full\":true},"
          "\"completionProvider\":{\"triggerCharacters\":["
          "\".\",\"/"
          "\",\"#\",\"\\\"\",\"_\",\"a\",\"b\",\"c\",\"d\",\"e\",\"f\",\"g\","
          "\"h\","
          "\"i\",\"j\",\"k\",\"l\",\"m\",\"n\",\"o\",\"p\",\"q\",\"r\",\"s\","
          "\"t\","
          "\"u\",\"v\",\"w\",\"x\",\"y\",\"z\"]},\"signatureHelpProvider\":{"
          "\"triggerCharacters\":[\"(\",\",\"]}}}}",
          id, lsp_wire_utf8 ? "utf-8" : "utf-16");
      lsp_send(response);
    } else if ((!strcmp(method, "textDocument/didClose"))) {
      lsp_wire_text = NULL;
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      for (size_t i = 0; uri && i < document_count; ++i)
        if (!strcmp(documents[i].uri, uri)) {
          char *escaped = json_escape(uri, strlen(uri));
          char response[512];
          if (escaped) {
            lsp_bounded_printf(response, sizeof(response),
                               "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/"
                               "publishDiagnostics\",\"params\":{\"uri\":\"%"
                               "s\",\"diagnostics\":[]}}",
                               escaped);
            lsp_send(response);
          }
          free(escaped);
          free(documents[i].uri);
          free(documents[i].text);
          if (documents[i].tree)
            ts_tree_delete(documents[i].tree);
          if (documents[i].parser)
            ts_parser_delete(documents[i].parser);
          memmove(&documents[i], &documents[i + 1],
                  (document_count - i - 1) * sizeof(*documents));
          --document_count;
          lsp_wire_count = document_count;
          memset(&documents[document_count], 0, sizeof(*documents));
          break;
        }
      free(uri);
      lsp_publish_semantic(documents, document_count);
    } else if ((!strcmp(method, "textDocument/didOpen")) ||
               (!strcmp(method, "textDocument/didChange"))) {
      bool changing = (!strcmp(method, "textDocument/didChange"));
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      LspDocument *document =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      char *text = changing
                       ? (document ? lsp_apply_changes(document, body) : NULL)
                       : json_string_after(body, "\"text\"", 1024u * 1024u);
      if (document && text && document->tree)
        dyn_syntax_edit_text(document->tree, document->text, text);
      if (!document && !changing && uri && text && *lsp_file_path(uri)) {
        if (document_count == document_capacity) {
          size_t capacity = document_capacity ? document_capacity * 2 : 32;
          LspDocument *next = capacity > document_capacity &&
                                      capacity <= SIZE_MAX / sizeof(*next)
                                  ? realloc(documents, capacity * sizeof(*next))
                                  : NULL;
          if (!next) {
            lsp_send("{\"jsonrpc\":\"2.0\",\"method\":\"window/logMessage\","
                     "\"params\":{\"type\":1,\"message\":\"Cannot open document: out of memory\"}}");
          } else {
            memset(next + document_capacity, 0,
                   (capacity - document_capacity) * sizeof(*next));
            documents = next;
            document_capacity = capacity;
            lsp_wire_documents = documents;
          }
        }
        if (document_count < document_capacity)
          document = &documents[document_count++];
        lsp_wire_count = document_count;
      }
      if (document && uri && text) {
        lsp_wire_text = NULL;
        free(document->uri);
        free(document->text);
        document->uri = uri;
        document->text = text;
        document->analysis_cache = &analysis_cache;
        document->revision = ++revision;
        document->content_hash = dyn_analysis_text_hash(text, strlen(text));
        if (changing) { document->dirty = true; dirty = true; }
        else {
          bool syntax_error = lsp_publish_syntax(document);
          if (!syntax_error) lsp_publish_semantic(documents, document_count);
        }
      } else {
        free(uri);
        free(text);
      }
    } else if ((!strcmp(method, "textDocument/documentSymbol"))) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      LspDocument *document =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      if (document)
        lsp_document_symbols(id, document);
      else {
        char response[96];
        lsp_bounded_printf(response, sizeof(response),
                           "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",
                           id);
        lsp_send(response);
      }
      free(uri);
    } else if ((!strcmp(method, "textDocument/documentHighlight"))) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      size_t line = 0, character = 0;
      LspDocument *document =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      (void)json_position(body, &line, &character);
      if (document)
        lsp_document_highlight(id, documents, document_count, document, line,
                               character);
      else {
        char response[96];
        lsp_bounded_printf(response, sizeof(response),
                           "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}",
                           id);
        lsp_send(response);
      }
      free(uri);
    } else if ((!strcmp(method, "textDocument/foldingRange"))) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      LspDocument *document =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      if (document)
        lsp_folding_ranges(id, document);
      else {
        char response[96];
        lsp_bounded_printf(response, sizeof(response),
                           "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}",
                           id);
        lsp_send(response);
      }
      free(uri);
    } else if ((!strcmp(method, "textDocument/selectionRange"))) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      size_t line = 0, character = 0;
      LspDocument *document =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      (void)json_position(body, &line, &character);
      if (document)
        lsp_selection_range(id, document, body);
      else {
        char response[96];
        lsp_bounded_printf(response, sizeof(response),
                           "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}",
                           id);
        lsp_send(response);
      }
      free(uri);
    } else if ((!strcmp(method, "textDocument/semanticTokens/full"))) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      LspDocument *document =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      if (document)
        lsp_semantic_tokens(id, documents, document_count, document);
      else {
        char response[96];
        lsp_bounded_printf(response, sizeof(response),
                           "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",
                           id);
        lsp_send(response);
      }
      free(uri);
    } else if ((!strcmp(method, "workspace/symbol"))) {
      char *query = json_string_after(body, "\"query\"", 1024), *derived = NULL;
      if (!workspace_root && document_count)
        derived = lsp_project_root(documents[0].uri);
      lsp_workspace_symbols(id, documents, document_count,
                            workspace_root ? workspace_root : derived, query);
      free(derived);
      free(query);
    } else if ((!strcmp(method, "workspace/didChangeWatchedFiles")) ||
               (!strcmp(method, "workspace/didChangeConfiguration"))) {
      if (!strcmp(method, "workspace/didChangeConfiguration"))
        dyn_analysis_cache_clear(&analysis_cache);
      lsp_declarations_clear();
      lsp_publish_semantic(documents, document_count);
    } else if ((!strcmp(method, "workspace/didChangeWorkspaceFolders"))) {
      const char *added = lsp_json_find(body, "\"added\"");
      char *uri =
          added ? json_string_after(added, "\"uri\"", 64u * 1024u) : NULL;
      if (uri) {
        free(workspace_root);
        workspace_root = strdup(lsp_file_path(uri));
        free(uri);
      }
      lsp_publish_semantic(documents, document_count);
    } else if ((!strcmp(method, "textDocument/codeAction"))) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      LspDocument *document =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      if (document)
        lsp_code_actions(id, documents, document_count, document, body);
      else {
        char response[96];
        lsp_bounded_printf(response, sizeof(response),
                           "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":[]}",
                           id);
        lsp_send(response);
      }
      free(uri);
    } else if ((!strcmp(method, "textDocument/formatting"))) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      LspDocument *document =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      if (document)
        lsp_format(id, document);
      free(uri);
    } else if ((!strcmp(method, "textDocument/inlayHint"))) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      size_t first = 0, a = 0, last = SIZE_MAX, b = 0;
      (void)json_range_positions(body, &first, &a, &last, &b);
      LspDocument *document =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      if (document)
        lsp_inlay_hints(id, documents, document_count, document, first, last);
      free(uri);
    } else if ((!strcmp(method, "textDocument/completion"))) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      size_t line = 0, character = 0;
      LspDocument *requested =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      (void)json_position(body, &line, &character);
      lsp_completion(id, documents, document_count, requested, line, character);
      free(uri);
    } else if ((!strcmp(method, "textDocument/typeDefinition"))) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      size_t line = 0, character = 0;
      LspDocument *requested =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      (void)json_position(body, &line, &character);
      LspSemantic semantic =
          requested ? lsp_semantic_project(documents, document_count, requested,
                                           requested->text)
                    : (LspSemantic){0};
      if (requested && !semantic.ok) {
        lsp_semantic_free(&semantic);
        semantic =
            lsp_semantic_build_related(documents, document_count, requested);
      }
      uint32_t offset = 0;
      DynSpan span = {0};
      LspOrigin origin;
      bool found =
          requested && semantic.ok &&
          lsp_semantic_offset(&semantic, requested, line, character, &offset) &&
          lsp_type_definition_span(&semantic, offset, &span) &&
          lsp_origin_identifier(&semantic.source, span, &origin);
      char response[2048];
      char *escaped =
          found ? json_escape(origin.uri, strlen(origin.uri)) : NULL;
      if (escaped)
        lsp_bounded_printf(
            response, sizeof(response),
            "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"uri\":\"%s\","
            "\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{"
            "\"line\":%zu,\"character\":%zu}}}}",
            id, escaped, origin.line, origin.column, origin.line,
            origin.column + origin.length);
      else
        lsp_bounded_printf(response, sizeof(response),
                           "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",
                           id);
      lsp_send(response);
      free(escaped);
      lsp_semantic_free(&semantic);
      free(uri);
    } else if ((!strcmp(method, "textDocument/prepareCallHierarchy"))) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      size_t line = 0, character = 0;
      LspDocument *requested =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      (void)json_position(body, &line, &character);
      if (requested)
        lsp_prepare_call_hierarchy(id, documents, document_count, requested,
                                   line, character);
      else {
        char response[96];
        lsp_bounded_printf(response, sizeof(response),
                           "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",
                           id);
        lsp_send(response);
      }
      free(uri);
    } else if ((!strcmp(method, "callHierarchy/incomingCalls"))) {
      lsp_call_hierarchy(id, documents, document_count, body, true);
    } else if ((!strcmp(method, "callHierarchy/outgoingCalls"))) {
      lsp_call_hierarchy(id, documents, document_count, body, false);
    } else if ((!strcmp(method, "textDocument/prepareRename"))) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      size_t line = 0, character = 0;
      const char *word = NULL;
      size_t length = 0;
      LspDocument *document =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      (void)json_position(body, &line, &character);
      if (document &&
          identifier_at(document->text, line, character, &word, &length)) {
        const char *row = document->text;
        for (size_t i = 0; i < line; ++i) {
          row = strchr(row, '\n');
          if (row)
            ++row;
        }
        size_t column = (size_t)(word - row);
        char *escaped = json_escape(word, length);
        char response[1024];
        if (escaped) {
          lsp_bounded_printf(
              response, sizeof(response),
              "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"range\":{"
              "\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{\"line\":%"
              "zu,\"character\":%zu}},\"placeholder\":\"%s\"}}",
              id, line, column, line, column + length, escaped);
          lsp_send(response);
        }
        free(escaped);
      } else {
        char response[96];
        lsp_bounded_printf(response, sizeof(response),
                           "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",
                           id);
        lsp_send(response);
      }
      free(uri);
    } else if ((!strcmp(method, "textDocument/hover")) ||
               (!strcmp(method, "textDocument/definition")) ||
               (!strcmp(method, "textDocument/declaration")) ||
               (!strcmp(method, "textDocument/implementation")) ||
               (!strcmp(method, "textDocument/references")) ||
               (!strcmp(method, "textDocument/rename")) ||
               (!strcmp(method, "textDocument/signatureHelp"))) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      size_t line = 0, character = 0;
      const char *word = NULL, *display = NULL;
      size_t word_length = 0, display_length = 0, found_line = 0,
             found_column = 0;
      LspDocument *requested =
          uri ? lsp_document(documents, document_count, uri) : NULL;
      LspDocument *definition = NULL, external = {0};
      bool import_found = false, builtin_found = false;
      char import_hover[512] = {0}, signature[512] = {0};
      bool positioned = requested && requested->text &&
                        json_position(body, &line, &character);
      bool navigation = (!strcmp(method, "textDocument/definition")) ||
                        (!strcmp(method, "textDocument/declaration")) ||
                        (!strcmp(method, "textDocument/implementation"));
      const char *builtin =
          positioned && (!strcmp(method, "textDocument/hover"))
              ? lsp_builtin_hover(requested->text, line, character)
              : NULL;
      bool found = builtin != NULL;
      if (found) {
        display = builtin;
        display_length = strlen(builtin);
        builtin_found = true;
      }
      if (!found)
        found = positioned &&
                ((!strcmp(method, "textDocument/signatureHelp"))
                     ? lsp_call_identifier(requested->text, line, character,
                                           &word, &word_length)
                     : identifier_at(requested->text, line, character, &word,
                                     &word_length));
      if (found && !builtin_found) {
        char *requested_root = lsp_project_root(requested->uri);
        for (size_t i = 0; i <= document_count; ++i) {
          LspDocument *doc = i == 0 ? requested : &documents[i - 1];
          if (i && doc == requested)
            continue;
          char *candidate_root = lsp_project_root(doc->uri);
          bool same = requested_root && candidate_root &&
                      !strcmp(requested_root, candidate_root);
          free(candidate_root);
          if (same && doc->text &&
              find_declaration(doc->text, word, word_length, &found_line,
                               &found_column, &display, &display_length)) {
            definition = doc;
            break;
          }
        }
        free(requested_root);
        found = definition != NULL;
      }
      if (!builtin_found && positioned &&
          (navigation || (!strcmp(method, "textDocument/hover")) ||
           (!strcmp(method, "textDocument/signatureHelp")))) {
        size_t target_length = 0;
        import_found =
            lsp_import_definition(requested, line, character, &external.uri,
                                  &found_line, &found_column, &target_length);
        if (import_found) {
          definition = &external;
          word_length = target_length;
          found = true;
          if ((!strcmp(method, "textDocument/hover")) ||
              (!strcmp(method, "textDocument/signatureHelp"))) {
            lsp_import_hover_text(lsp_file_path(external.uri), found_line,
                                  import_hover, sizeof(import_hover));
            display = import_hover;
            display_length = strlen(import_hover);
          }
        }
      }
      if (found && !import_found &&
          (!strcmp(method, "textDocument/signatureHelp"))) {
        lsp_completion_signature(display, signature, sizeof(signature));
        display = signature;
        display_length = strlen(signature);
      }
      LspSemantic semantic =
          requested ? lsp_semantic_project(documents, document_count, requested,
                                           requested->text)
                    : (LspSemantic){0};
      char typed_hover[512];
      DynSpan typed_definition = {0};
      uint32_t typed_offset = 0;
      if (requested && !semantic.ok) {
        lsp_semantic_free(&semantic);
        semantic =
            lsp_semantic_build_related(documents, document_count, requested);
      }
      bool typed = positioned && semantic.ok &&
                   lsp_semantic_offset(&semantic, requested, line, character,
                                       &typed_offset) &&
                   lsp_typed_symbol(&semantic, typed_offset, typed_hover,
                                    sizeof(typed_hover), &typed_definition);
      if (!builtin_found && !import_found && typed &&
          (!strcmp(method, "textDocument/hover")) &&
          (!found || typed_definition.end_byte > typed_definition.start_byte)) {
        display = typed_hover;
        display_length = strlen(typed_hover);
        found = true;
      }
      if (!import_found && typed && navigation &&
          typed_definition.end_byte > typed_definition.start_byte) {
        const char *path;
        unsigned mapped_line, mapped_column;
        dyn_source_location(&semantic.source, typed_definition.start_byte,
                            &path, &mapped_line, &mapped_column);
        free(external.uri);
        external.uri =
            !strncmp(path, "file://", 7) ? strdup(path) : lsp_path_uri(path);
        definition = &external;
        found = external.uri != NULL;
        found_line = mapped_line ? mapped_line - 1 : 0;
        found_column = mapped_column ? mapped_column - 1 : 0;
      }
      if (typed && typed_definition.end_byte > typed_definition.start_byte &&
          ((!strcmp(method, "textDocument/references")) ||
           (!strcmp(method, "textDocument/rename"))))
        found = true;
      if (found && ((!strcmp(method, "textDocument/references")) ||
                    (!strcmp(method, "textDocument/rename")))) {
        char *new_name = (!strcmp(method, "textDocument/rename"))
                             ? json_string_after(body, "\"newName\"", 1024)
                             : NULL;
        bool semantic_target =
            typed && typed_definition.end_byte > typed_definition.start_byte;
        if (new_name && !lsp_valid_identifier(new_name)) {
          char response[192];
          lsp_bounded_printf(
              response, sizeof(response),
              "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"error\":{\"code\":-32602,"
              "\"message\":\"rename requires a valid Dyn identifier\"}}",
              id);
          lsp_send(response);
        } else if (new_name && semantic_target)
          lsp_semantic_rename(id, &semantic, documents, document_count,
                              typed_definition, new_name);
        else if (new_name) {
          char *root = lsp_project_root(requested->uri);
          lsp_rename(id, documents, document_count, word, word_length, new_name,
                     root);
          free(root);
        } else if (semantic_target)
          lsp_semantic_references(id, &semantic, documents, document_count,
                                  typed_definition);
        else {
          char *root = lsp_project_root(requested->uri);
          lsp_references(id, documents, document_count, word, word_length, NULL,
                         root);
          free(root);
        }
        free(new_name);
      } else if (!found) {
        char response[96];
        lsp_bounded_printf(response, sizeof(response),
                           "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",
                           id);
        lsp_send(response);
      } else if ((!strcmp(method, "textDocument/hover"))) {
        char *escaped = json_escape(display, display_length);
        size_t capacity = (escaped ? strlen(escaped) : 0) + 160;
        char *response = malloc(capacity);
        if (escaped && response) {
          lsp_bounded_printf(
              response, capacity,
              "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"contents\":{"
              "\"kind\":\"plaintext\",\"value\":\"%s\"}}}",
              id, escaped);
          lsp_send(response);
        }
        free(escaped);
        free(response);
      } else if ((!strcmp(method, "textDocument/signatureHelp"))) {
        char *escaped = json_escape(display, display_length);
        size_t capacity = (escaped ? strlen(escaped) : 0) + 192;
        char *response = malloc(capacity);
        size_t active = lsp_active_parameter(requested->text, line, character);
        if (escaped && response) {
          lsp_bounded_printf(response, capacity,
                             "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{"
                             "\"signatures\":[{\"label\":\"%s\"}],"
                             "\"activeSignature\":0,\"activeParameter\":%zu}}",
                             id, escaped, active);
          lsp_send(response);
        }
        free(escaped);
        free(response);
      } else {
        char *escaped_uri =
            json_escape(definition->uri, strlen(definition->uri));
        size_t capacity = (escaped_uri ? strlen(escaped_uri) : 0) + 256;
        char *response = malloc(capacity);
        if (escaped_uri && response) {
          lsp_bounded_printf(
              response, capacity,
              "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"uri\":\"%s\","
              "\"range\":{\"start\":{\"line\":%zu,\"character\":%zu},\"end\":{"
              "\"line\":%zu,\"character\":%zu}}}}",
              id, escaped_uri, found_line, found_column, found_line,
              found_column + word_length);
          lsp_send(response);
        }
        free(escaped_uri);
        free(response);
      }
      lsp_semantic_free(&semantic);
      free(external.uri);
      free(uri);
    } else if ((!strcmp(method, "shutdown"))) {
      char response[96];
      lsp_bounded_printf(response, sizeof(response),
                         "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}",
                         id);
      lsp_send(response);
    } else if ((!strcmp(method, "exit"))) {
      free(method_name);
      free(body);
      break;
    } else if (id >= 0) {
      char response[160];
      lsp_bounded_printf(response, sizeof(response),
                         "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"error\":{\"code\":-"
                         "32601,\"message\":\"method not supported\"}}",
                         id);
      lsp_send(response);
    }
    if (dirty) {
      pending = lsp_work_next(&work_state, false);
      char *next_method = pending && lsp_json_valid(pending)
          ? json_string_after(pending, "\"method\"", 256) : NULL;
      const char *next_version = next_method ? lsp_json_member(pending, "\"jsonrpc\"") : NULL;
      bool more_changes = next_method && !strcmp(next_method, "textDocument/didChange") &&
          next_version && !strncmp(next_version, "\"2.0\"", 5) &&
          !lsp_json_member(pending, "\"id\"");
      free(next_method);
      if (more_changes) ++coalesced;
      else {
        for (size_t i = 0; i < document_count; ++i) if (documents[i].dirty) {
          (void)lsp_publish_syntax(&documents[i]); documents[i].dirty = false;
        }
        lsp_publish_semantic(documents, document_count);
        dirty = false;
      }
    }
    if (work_state.work.status == DYN_WORK_LIMIT && id < 0) {
      char *uri = json_string_after(body, "\"uri\"", 64u * 1024u);
      char *escaped = uri ? json_escape(uri, strlen(uri)) : NULL;
      if (escaped) {
        size_t capacity = strlen(escaped) + 512;
        char *message = malloc(capacity);
        if (message) {
          snprintf(message, capacity, "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/publishDiagnostics\",\"params\":{\"uri\":\"%s\",\"diagnostics\":[{\"range\":{\"start\":{\"line\":0,\"character\":0},\"end\":{\"line\":0,\"character\":0}},\"severity\":2,\"source\":\"dyn\",\"message\":\"Analysis budget exceeded; diagnostics are incomplete\"}]}}", escaped);
          work_state.work.status = DYN_WORK_RUNNING;
          work_state.work.until_poll = UINT64_MAX;
          lsp_send(message); free(message);
        }
      }
      free(uri); free(escaped);
    }
    free(method_name);
    free(body);
    lsp_uri_paths_clear();
  }
  for (size_t i = 0; i < document_count; ++i) {
    free(documents[i].uri);
    free(documents[i].text);
    if (documents[i].tree)
      ts_tree_delete(documents[i].tree);
    if (documents[i].parser)
      ts_parser_delete(documents[i].parser);
  }
  if (getenv("DYN_LSP_ANALYSIS_STATS"))
    fprintf(stderr, "analysis-cache hits=%llu misses=%llu syntax-hits=%llu syntax-misses=%llu\n",
            (unsigned long long)analysis_cache.hits,
            (unsigned long long)analysis_cache.misses,
            (unsigned long long)analysis_cache.syntax.hits,
            (unsigned long long)analysis_cache.syntax.misses);
  if (getenv("DYN_LSP_ANALYSIS_STATS"))
    fprintf(stderr, "coalesced-edits=%llu\n", (unsigned long long)coalesced);
  if (getenv("DYN_LSP_ANALYSIS_STATS"))
    fprintf(stderr, "module-analysis hits=%llu misses=%llu\n",
        (unsigned long long)analysis_cache.module_hits,
        (unsigned long long)analysis_cache.module_misses);
  if (getenv("DYN_LSP_ANALYSIS_STATS"))
    fprintf(stderr, "interface-cache hits=%llu misses=%llu\n",
        (unsigned long long)analysis_cache.interface_hits,
        (unsigned long long)analysis_cache.interface_misses);
  free(input.data);
  free(pending);
  while (work_state.head) { char *queued = lsp_work_next(&work_state, false); free(queued); }
  lsp_active_work = NULL;
  free(documents);
  lsp_wire_documents = NULL;
  lsp_wire_count = 0;
  lsp_declaration_documents(NULL, 0);
  lsp_declarations_clear();
  dyn_analysis_cache_clear(&analysis_cache);
  free(workspace_root);
  lsp_uri_paths_clear();
  free(lsp_wire_id);
  lsp_wire_id = NULL;
  return status;
}
