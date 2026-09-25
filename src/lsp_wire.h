#ifndef DYN_LSP_WIRE_H
#define DYN_LSP_WIRE_H
/* Protocol columns are converted at the boundary; compiler/parser columns stay
 * bytes. */
static bool lsp_wire_utf8;
static LspDocument *lsp_wire_documents;
static size_t lsp_wire_count;
static const char *lsp_wire_text;
static char *lsp_wire_id;
static bool lsp_response_overflow;
static long lsp_wire_number;
size_t lsp_wire_column(const char *text, size_t line, size_t column,
                       bool to_bytes) {
  if (!text || lsp_wire_utf8)
    return column;
  const unsigned char *p = (const unsigned char *)text;
  for (size_t i = 0; i < line; ++i) {
    const char *end = strchr((const char *)p, '\n');
    if (!end)
      return column;
    p = (const unsigned char *)end + 1;
  }
  size_t bytes = 0, units = 0;
  while (p[bytes] && p[bytes] != '\n' && (to_bytes ? units : bytes) < column) {
    unsigned width = p[bytes] < 0x80   ? 1
                     : p[bytes] < 0xe0 ? 2
                     : p[bytes] < 0xf0 ? 3
                                       : 4;
    unsigned valid = 1;
    while (valid < width && p[bytes + valid] &&
           (p[bytes + valid] & 0xc0) == 0x80)
      ++valid;
    if (valid != width)
      width = 1;
    unsigned step = width == 4 ? 2 : 1;
    if (to_bytes && units + step > column)
      break;
    if (!to_bytes && bytes + width > column)
      break;
    bytes += width;
    units += step;
  }
  return to_bytes ? bytes : units;
}
int lsp_bounded_printf(char *out, size_t capacity, const char *format, ...) {
  va_list arguments;
  va_start(arguments, format);
  int n = vsnprintf(out, capacity, format, arguments);
  va_end(arguments);
  if (n < 0 || (size_t)n >= capacity) {
    lsp_response_overflow = true;
    if (capacity)
      out[0] = 0;
    return 0; /* Never advance a caller's cursor beyond its allocation. */
  }
  return n;
}
typedef struct {
  char *text;
  size_t length, capacity;
  bool failed;
  const char *failure;
} LspWireBuffer;
static void lsp_wire_append(LspWireBuffer *out, const char *text,
                            size_t length) {
  if (out->failed)
    return;
  if (length > 16u * 1024u * 1024u - out->length) {
    out->failed = true;
    out->failure = "response exceeds server capacity";
    return;
  }
  size_t needed = out->length + length + 1;
  if (needed > out->capacity) {
    size_t capacity = out->capacity ? out->capacity * 2 : 1024;
    if (capacity < needed)
      capacity = needed;
    char *next = realloc(out->text, capacity);
    if (!next) {
      out->failed = true;
      out->failure = "response allocation failed";
      return;
    }
    out->text = next;
    out->capacity = capacity;
  }
  memcpy(out->text + out->length, text, length);
  out->length += length;
  out->text[out->length] = 0;
}
static char *lsp_wire_source(const char *object) {
  char *uri = json_string_after(object, "\"uri\"", 64u * 1024u);
  if (!uri)
    return NULL;
  char *text = NULL;
  for (size_t i = 0; i < lsp_wire_count; ++i)
    if (!strcmp(lsp_file_path(uri), lsp_file_path(lsp_wire_documents[i].uri))) {
      text = strdup(lsp_wire_documents[i].text);
      break;
    }
  if (!text) {
    FILE *file = fopen(lsp_file_path(uri), "rb");
    if (file) {
      if (!fseek(file, 0, SEEK_END)) {
        long length = ftell(file);
        if (length >= 0 && length <= 16 * 1024 * 1024 &&
            !fseek(file, 0, SEEK_SET)) {
          text = malloc((size_t)length + 1);
          if (text && fread(text, 1, (size_t)length, file) == (size_t)length)
            text[length] = 0;
          else {
            free(text);
            text = NULL;
          }
        }
      }
      fclose(file);
    }
  }
  free(uri);
  return text;
}
static const char *lsp_wire_transform(LspWireBuffer *out, const char *input,
                                      const char *text) {
  input = lsp_json_space(input);
  const char *end = lsp_json_end(input, 0);
  if (!end) {
    out->failed = true;
    return input;
  }
  bool object = *input == '{';
  if (!object && *input != '[') {
    lsp_wire_append(out, input, (size_t)(end - input));
    return end;
  }
  char *owned = NULL;
  if (object && lsp_json_member(input, "\"uri\"")) {
    owned = lsp_wire_source(input);
    if (owned)
      text = owned;
  }
  size_t line, column;
  if (object && text && json_point(input, &line, &column)) {
    char point[128];
    int n = snprintf(point, sizeof(point), "{\"line\":%zu,\"character\":%zu}",
                     line, lsp_wire_column(text, line, column, false));
    lsp_wire_append(out, point, (size_t)n);
    free(owned);
    return end;
  }
  lsp_wire_append(out, input, 1);
  const char *p = lsp_json_space(input + 1);
  bool comma = false;
  while (*p != '}' && *p != ']') {
    if (comma)
      lsp_wire_append(out, ",", 1);
    const char *key = NULL, *key_end = NULL;
    if (object) {
      key = p;
      key_end = lsp_json_end(p, 0);
      lsp_wire_append(out, p, (size_t)(key_end - p));
      lsp_wire_append(out, ":", 1);
      p = lsp_json_space(lsp_json_space(key_end) + 1);
    }
    if (key && text &&
        ((key_end - key == 16 && !memcmp(key, "\"startCharacter\"", 16)) ||
         (key_end - key == 14 && !memcmp(key, "\"endCharacter\"", 14)))) {
      const char *line_key =
          key_end - key == 16 ? "\"startLine\"" : "\"endLine\"";
      size_t fold_line, fold_column;
      if (lsp_json_size(lsp_json_member(input, line_key), &fold_line) &&
          lsp_json_size(p, &fold_column)) {
        char number[32];
        int n = snprintf(number, sizeof(number), "%zu",
                         lsp_wire_column(text, fold_line, fold_column, false));
        lsp_wire_append(out, number, (size_t)n);
        p = lsp_json_end(p, 0);
      } else
        p = lsp_wire_transform(out, p, text);
    } else if (key && key_end - key == 4 && !memcmp(key, "\"id\"", 4) &&
               lsp_wire_id) {
      lsp_wire_append(out, lsp_wire_id, strlen(lsp_wire_id));
      p = lsp_json_end(p, 0);
    } else if (key && key_end - key == 6 && !memcmp(key, "\"data\"", 6) &&
               *p == '[' && text) {
      /* Semantic tokens use byte deltas internally; convert absolute positions
         before deriving wire deltas and lengths. */
      const char *q = lsp_json_space(p + 1);
      size_t row = 0, byte = 0, previous_row = 0, previous_column = 0;
      bool first = true;
      lsp_wire_append(out, "[", 1);
      while (*q != ']') {
        size_t values[5];
        for (unsigned i = 0; i < 5; ++i) {
          if (!lsp_json_size(q, &values[i])) {
            out->failed = true;
            break;
          }
          q = lsp_json_space(lsp_json_end(q, 0));
          if (i != 4) {
            if (*q != ',') {
              out->failed = true;
              break;
            }
            q = lsp_json_space(q + 1);
          }
        }
        if (out->failed)
          break;
        row += values[0];
        byte = values[0] ? values[1] : byte + values[1];
        size_t col = lsp_wire_column(text, row, byte, false),
               limit = lsp_wire_column(text, row, byte + values[2], false);
        char token[160];
        int n = snprintf(token, sizeof(token), "%s%zu,%zu,%zu,%zu,%zu",
                         first ? "" : ",", row - previous_row,
                         row != previous_row ? col : col - previous_column,
                         limit - col, values[3], values[4]);
        lsp_wire_append(out, token, (size_t)n);
        first = false;
        previous_row = row;
        previous_column = col;
        if (*q == ']')
          break;
        if (*q != ',') {
          out->failed = true;
          break;
        }
        q = lsp_json_space(q + 1);
      }
      lsp_wire_append(out, "]", 1);
      p = lsp_json_end(p, 0);
    } else if (key && key_end - key > 9 && !memcmp(key + 1, "file://", 7)) {
      LspWireBuffer location = {0};
      lsp_wire_append(&location, "{\"uri\":", 7);
      lsp_wire_append(&location, key, (size_t)(key_end - key));
      lsp_wire_append(&location, "}", 1);
      char *document_text =
          location.failed ? NULL : lsp_wire_source(location.text);
      p = lsp_wire_transform(out, p, document_text ? document_text : text);
      free(document_text);
      free(location.text);
    } else
      p = lsp_wire_transform(out, p, text);
    p = lsp_json_space(p);
    comma = true;
    if (*p == ',')
      p = lsp_json_space(p + 1);
    else
      break;
  }
  lsp_wire_append(out, end - 1, 1);
  free(owned);
  return end;
}
void lsp_send(const char *body) {
  DynWork *work = lsp_work_current();
  char stopped[256];
  if (work) {
    DynContext context = {.target = lsp_target_current(), .work = work};
    if (lsp_json_member(body, "\"id\"")) { work->until_poll = 0; (void)dyn_work_step(&context, 0); }
    if (work->status) {
      if (!lsp_json_member(body, "\"id\"")) return;
      snprintf(stopped, sizeof(stopped), "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"error\":{\"code\":%d,\"message\":\"%s\"}}", lsp_wire_number,
          work->status == DYN_WORK_CANCELLED ? -32800 : -32803,
          work->status == DYN_WORK_CANCELLED ? "Request cancelled" : "Analysis budget exceeded");
      body = stopped;
    }
  }
  LspWireBuffer out = {0};
  const char *failure = lsp_response_overflow ? "response exceeds server capacity" :
      !lsp_json_valid(body) ? "invalid server response JSON" : "invalid response transformation";
  if (!lsp_response_overflow && lsp_json_valid(body))
    lsp_wire_transform(&out, body, lsp_wire_text);
  else
    out.failed = true;
  if (out.failed) {
    if (out.failure) failure = out.failure;
    free(out.text);
    out = (LspWireBuffer){0};
    if (lsp_wire_number < 0) {
      lsp_response_overflow = false;
      return;
    }
    char error[256];
    snprintf(error, sizeof(error),
             "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"error\":{\"code\":-32603,"
             "\"message\":\"%s\"}}",
             lsp_wire_number, failure);
    lsp_response_overflow = false;
    lsp_wire_transform(&out, error, NULL);
  }
  if (out.text && !out.failed) {
    printf("Content-Length: %zu\r\n\r\n%s", out.length, out.text);
    fflush(stdout);
  }
  free(out.text);
  lsp_response_overflow = false;
}
#endif
