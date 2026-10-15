#include "dyn.h"
#include "dyn_compact.h"
#include <stdio.h>
#include <string.h>
static void quote(const char *s) {
  fputc('"', stderr);
  for (; s && *s; ++s) {
    unsigned char c = (unsigned char)*s;
    if (c == '"' || c == '\\') {
      fputc('\\', stderr);
      fputc(c, stderr);
    } else if (c == '\n')
      fputs("\\n", stderr);
    else if (c == '\r')
      fputs("\\r", stderr);
    else if (c == '\t')
      fputs("\\t", stderr);
    else if (c < 32)
      fprintf(stderr, "\\u%04x", c);
    else
      fputc(c, stderr);
  }
  fputc('"', stderr);
}
void dyn_diagnostic(const DynContext *context, const char *severity,
                    const char *path, unsigned line, unsigned column,
                    unsigned end_line, unsigned end_column,
                    const char *message) {
  if (context && context->work && context->work->status) {
    if (context->work->reported) return;
    context->work->reported = true;
    severity = "error";
    message = context->work->status == DYN_WORK_CANCELLED ? "analysis cancelled" : "analysis work budget exceeded";
  }
  if (context && context->diagnostic) {
    context->diagnostic(severity, path, line, column, end_line, end_column,
                        message, context->diagnostic_data);
    return;
  }
  if (!context || !context->json_diagnostics) {
    fprintf(stderr, "%s:%u:%u: %s: %s", path ? path : "<compiler>", line,
            column, severity, message);
    if (end_line || end_column)
      fprintf(stderr, " [range %u:%u-%u:%u]", line, column,
              end_line ? end_line : line, end_column ? end_column : column);
    fputc('\n', stderr);
    return;
  }
  fputs("{\"severity\":", stderr);
  quote(severity);
  fputs(",\"message\":", stderr);
  quote(message);
  fputs(",\"path\":", stderr);
  quote(path ? path : "");
  fprintf(stderr,
          ",\"range\":{\"start\":{\"line\":%u,\"column\":%u},"
          "\"end\":{\"line\":%u,\"column\":%u}}}\n",
          line, column, end_line ? end_line : line,
          end_column ? end_column : column);
}

void dyn_diagnostic_source(const char *severity, const DynSource *source,
                           size_t start, size_t end, const char *message) {
  const char *path, *end_path;
  unsigned line, column, end_line, end_column;
  dyn_source_location(source, start, &path, &line, &column);
  dyn_source_location(source, end, &end_path, &end_line, &end_column);
  if (end < start ||
      (path != end_path && (!path || !end_path || strcmp(path, end_path)))) {
    end_line = line;
    end_column = column + 1;
  }
  dyn_diagnostic(&source->context, severity, path, line, column, end_line,
                 end_column, message);
}

/* Parser diagnostics name the offending token and what was expected. */
static size_t syntax_token_end(const char *text, size_t length, size_t at) {
  unsigned char c = (unsigned char)text[at];
  size_t end = at + 1;
  if (c == '_' || (c >= '0' && c <= '9') || ((c | 32) >= 'a' && (c | 32) <= 'z')) {
    while (end < length) {
      c = (unsigned char)text[end];
      if (c != '_' && !(c >= '0' && c <= '9') && !((c | 32) >= 'a' && (c | 32) <= 'z')) break;
      ++end;
    }
  } else if (c >= 0x80)
    while (end < length && ((unsigned char)text[end] & 0xc0) == 0x80) ++end;
  else if (strchr(":=<>!&|+-*/%^.~", c))
    while (end < length && end - at < 3 && text[end] && strchr(":=<>!&|+-*/%^.~", text[end])) ++end;
  return end - at > 32 ? at + 32 : end;
}
void dyn_syntax_error_message(const char *text, size_t length, uint32_t offset,
                              const char *error, const char *expected,
                              char *message, size_t capacity, uint32_t *token_end) {
  size_t start = offset;
  if (start > length) start = length;
  size_t end = start;
  char found[48];
  if (start == length) snprintf(found, sizeof(found), "end of file");
  else {
    end = syntax_token_end(text, length, start);
    unsigned char c = (unsigned char)text[start];
    if (c == '\n') snprintf(found, sizeof(found), "end of line");
    else if (c < 0x20 || c == 0x7f) snprintf(found, sizeof(found), "U+%04X", c);
    else if (c >= 0x80) {
      /* Name the code point: it may be invisible or a line separator. */
      unsigned value = c >= 0xf0 ? c & 7 : c >= 0xe0 ? c & 15 : c & 31;
      for (size_t i = start + 1; i < end; ++i)
        value = value << 6 | ((unsigned char)text[i] & 63);
      snprintf(found, sizeof(found), "U+%04X", value);
    } else snprintf(found, sizeof(found), "'%.*s'", (int)(end - start), text + start);
  }
  if (expected)
    snprintf(message, capacity, "expected '%s', found %s", expected, found);
  else if (!strcmp(error, "unexpected token"))
    snprintf(message, capacity, "unexpected %s", found);
  else if (!strcmp(error, "unexpected character"))
    snprintf(message, capacity, "unexpected character %s", found);
  else if (!strncmp(error, "expected ", 9))
    snprintf(message, capacity, "%s, found %s", error, found);
  else
    snprintf(message, capacity, "%s", error);
  *token_end = (uint32_t)end;
}
void dyn_report_syntax_error(const DynSource *source, uint32_t offset,
                             const char *error, const char *expected) {
  char message[160];
  uint32_t end;
  dyn_syntax_error_message(source->text, source->length, offset, error, expected,
                           message, sizeof(message), &end);
  size_t start = offset > source->length ? source->length : offset;
  dyn_diagnostic_source("error", source, start, end, message);
}
bool dyn_source_report_syntax(const DynSource *source) {
  if (!source->syntax_error) return false;
  const ExpSnapshotTree *tree = dyn_compact_tree(source);
  if (!tree || !tree->error_count) {
    dyn_report_syntax_error(source, source->syntax_error_offset, source->syntax_error,
                        source->syntax_expected);
    return true;
  }
  /* Later errors can follow from recovery; report a bounded prefix. */
  for (uint32_t i = 0; i < tree->error_count && i < DYN_SYNTAX_ERROR_LIMIT; ++i)
    dyn_report_syntax_error(source, tree->errors[i].offset, tree->errors[i].message,
                        tree->errors[i].expected);
  return true;
}
