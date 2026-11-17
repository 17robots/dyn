#include <ctype.h>
#include "dyn.h"
#include "dyn_compact.h"
#include <stdio.h>
#include <stdlib.h>
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
/* The fix waiting for its diagnostic; see dyn_diagnostic_fix. */
typedef struct PendingFix {
  const DynSource *source;
  size_t at, start, end;
  char replacement[256];
  bool set, certain;
} PendingFix;
static _Thread_local PendingFix pending_fix;
static _Thread_local DynFixSink fix_sink;
static _Thread_local void *fix_sink_data;
void dyn_diagnostic_fix_sink(DynFixSink sink, void *data) {
  fix_sink = sink;
  fix_sink_data = data;
}
void dyn_diagnostic_fix(const DynSource *source, size_t at, size_t start, size_t end, const char *replacement,
                        bool certain) {
  size_t length = replacement ? strlen(replacement) : 0;
  if (!source || end < start || length >= sizeof(pending_fix.replacement)) return;
  pending_fix = (PendingFix){.source = source, .at = at, .start = start, .end = end, .set = true, .certain = certain};
  memcpy(pending_fix.replacement, replacement ? replacement : "", length + 1);
}
/* A located fix, for output. */
typedef struct Fix {
  const char *replacement, *path, *text;
  size_t start, end;
  unsigned line, column, end_line, end_column;
  bool certain;
} Fix;
static void report(const DynContext *context, const char *severity,
                   const char *path, unsigned line, unsigned column,
                   unsigned end_line, unsigned end_column,
                   const char *message, const Fix *fix);
void dyn_diagnostic(const DynContext *context, const char *severity,
                    const char *path, unsigned line, unsigned column,
                    unsigned end_line, unsigned end_column,
                    const char *message) {
  report(context, severity, path, line, column, end_line, end_column, message, NULL);
}
static void report(const DynContext *context, const char *severity,
                   const char *path, unsigned line, unsigned column,
                   unsigned end_line, unsigned end_column,
                   const char *message, const Fix *fix) {
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
    fprintf(stderr, "%s:%u:%u: %s: %s\n", path ? path : "<compiler>", line,
            column, severity, message);
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
          "\"end\":{\"line\":%u,\"column\":%u}}",
          line, column, end_line ? end_line : line,
          end_column ? end_column : column);
  if (fix) {
    fputs(",\"fix\":{\"replacement\":", stderr);
    quote(fix->replacement);
    fputs(",\"path\":", stderr);
    quote(fix->path ? fix->path : "");
    fprintf(stderr, ",\"certain\":%s", fix->certain ? "true" : "false");
    fprintf(stderr,
            ",\"offset\":%zu,\"length\":%zu,\"range\":{\"start\":{\"line\":%u,\"column\":%u},"
            "\"end\":{\"line\":%u,\"column\":%u}}}",
            fix->start, fix->end - fix->start, fix->line, fix->column, fix->end_line, fix->end_column);
  }
  fputs("}\n", stderr);
}

/* The source line under a text diagnostic, with the span underlined:

     8 |   total := count + "a"
       |                    ^~~

   Tabs in the line are kept under the caret so the marks line up. A span
   that continues past its first line is underlined to the line's end. */
static void diagnostic_snippet(const char *text, size_t length, size_t at, size_t end_at, unsigned line) {
  if (!text || at > length) return;
  size_t first = at;
  while (first && text[first - 1] != '\n') --first;
  size_t last = at;
  while (last < length && text[last] != '\n' && text[last] != '\r') ++last;
  if (last - first > 400) return;
  if (end_at < at || end_at > last) end_at = last;
  if (end_at == at) end_at = at + 1;
  char number[16];
  int width = snprintf(number, sizeof(number), "%u", line);
  fprintf(stderr, " %s | %.*s\n %*s | ", number, (int)(last - first), text + first, width, "");
  for (size_t i = first; i < at; ++i) {
    unsigned char c = (unsigned char)text[i];
    if ((c & 0xc0) == 0x80) continue;
    fputc(c == '\t' ? '\t' : ' ', stderr);
  }
  fputc('^', stderr);
  for (size_t i = at + 1; i < end_at; ++i)
    if (((unsigned char)text[i] & 0xc0) != 0x80) fputc('~', stderr);
  fputc('\n', stderr);
}
_Thread_local DynDiagnosticCapture *dyn_diagnostic_capture;
static bool diagnostic_keep(DynDiagnosticCapture *capture, const char *severity, const DynSource *source,
                            size_t start, size_t end, const char *message, const PendingFix *fix) {
  if (capture->count == capture->capacity) {
    size_t capacity = capture->capacity ? 2 * capture->capacity : 16;
    DynDiagnosticRecord *grown = realloc(capture->items, capacity * sizeof(*grown));
    if (!grown) return false;
    capture->items = grown; capture->capacity = capacity;
  }
  char *kept_severity = strdup(severity), *kept_message = strdup(message);
  char *kept_fix = fix ? strdup(fix->replacement) : NULL;
  if (!kept_severity || !kept_message || (fix && !kept_fix)) {
    free(kept_severity); free(kept_message); free(kept_fix);
    return false;
  }
  capture->items[capture->count++] = (DynDiagnosticRecord){source, start, end, kept_severity, kept_message,
                                                           fix ? fix->start : 0, fix ? fix->end : 0, kept_fix,
                                                           fix && fix->certain};
  return true;
}
void dyn_diagnostic_replay(DynDiagnosticCapture *capture, size_t first, size_t count) {
  DynDiagnosticCapture *kept = dyn_diagnostic_capture;
  dyn_diagnostic_capture = NULL;
  for (size_t i = first; i < first + count && i < capture->count; ++i) {
    DynDiagnosticRecord *r = &capture->items[i];
    if (r->replacement) dyn_diagnostic_fix(r->source, r->start, r->fix_start, r->fix_end, r->replacement, r->certain);
    dyn_diagnostic_source(r->severity, r->source, r->start, r->end, r->message);
  }
  dyn_diagnostic_capture = kept;
}
void dyn_diagnostic_capture_free(DynDiagnosticCapture *capture) {
  for (size_t i = 0; i < capture->count; ++i) {
    free(capture->items[i].severity);
    free(capture->items[i].message);
    free(capture->items[i].replacement);
  }
  free(capture->items);
  *capture = (DynDiagnosticCapture){0};
}
void dyn_diagnostic_source(const char *severity, const DynSource *source,
                           size_t start, size_t end, const char *message) {
  PendingFix pending = pending_fix;
  pending_fix.set = false;
  const PendingFix *fix = pending.set && pending.source == source && pending.at == start ? &pending : NULL;
  /* Without memory to keep it, report it now: out of order beats lost. */
  if (dyn_diagnostic_capture && diagnostic_keep(dyn_diagnostic_capture, severity, source, start, end, message, fix)) return;
  const char *path, *end_path;
  unsigned line, column, end_line, end_column;
  dyn_source_location(source, start, &path, &line, &column);
  dyn_source_location(source, end, &end_path, &end_line, &end_column);
  if (end < start ||
      (path != end_path && (!path || !end_path || strcmp(path, end_path)))) {
    end_line = line;
    end_column = column + 1;
  }
  /* A fix inside one file, located in that file's own bytes. */
  Fix located = {0};
  bool has_fix = false;
  if (fix) {
    const char *fix_path, *fix_end_path, *text;
    size_t length, fix_at, fix_end_at;
    dyn_source_position(source, fix->start, &fix_path, &text, &length, &fix_at);
    dyn_source_position(source, fix->end, &fix_end_path, &text, &length, &fix_end_at);
    if (fix_path && fix_end_path && !strcmp(fix_path, fix_end_path) && fix_at <= fix_end_at) {
      located = (Fix){.replacement = fix->replacement, .path = fix_path, .text = text, .start = fix_at, .end = fix_end_at,
                      .certain = fix->certain};
      const char *ignored;
      dyn_source_location(source, fix->start, &ignored, &located.line, &located.column);
      dyn_source_location(source, fix->end, &ignored, &located.end_line, &located.end_column);
      has_fix = true;
      if (fix_sink) {
        DynFixReport reported = {fix_path, fix->replacement, fix_at, fix_end_at - fix_at, located.line,
                                 located.column, located.end_line, located.end_column, fix->certain};
        fix_sink(&reported, fix_sink_data);
      }
    }
  }
  const DynContext *context = &source->context;
  if (context->work && context->work->status) {
    dyn_diagnostic(context, severity, path, line, column, end_line, end_column, message);
    return;
  }
  report(context, severity, path, line, column, end_line, end_column, message, has_fix ? &located : NULL);
  if (context->diagnostic || context->json_diagnostics)
    return;
  const char *text;
  size_t length, at, end_at;
  dyn_source_position(source, start, &path, &text, &length, &at);
  dyn_source_position(source, end, &end_path, &text, &length, &end_at);
  if (path != end_path && (!path || !end_path || strcmp(path, end_path))) end_at = at;
  diagnostic_snippet(text, length, at, end_at, line);
  if (has_fix) {
    /* dyn fix applies a fix; a suggestion is a guess to check by hand. */
    const char *label = located.certain ? "fix" : "suggestion";
    if (located.start == located.end)
      fprintf(stderr, " %s: insert '%s' at %u:%u\n", label, located.replacement, located.line, located.column);
    else if (!located.replacement[0])
      fprintf(stderr, " %s: delete '%.*s'\n", label, (int)(located.end - located.start), located.text + located.start);
    else
      fprintf(stderr, " %s: replace '%.*s' with '%s'\n", label, (int)(located.end - located.start),
              located.text + located.start, located.replacement);
  }
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
  /* A list item on the next line where the list should close: a comma is
     missing at the end of the line above. */
  bool next_line = false;
  if (expected && !strcmp(expected, "}") &&
      start < length && (isalnum((unsigned char)text[start]) || text[start] == '_' || text[start] == '.' ||
                         text[start] == '"' || text[start] == '-')) {
    size_t back = start;
    while (back && (text[back - 1] == ' ' || text[back - 1] == '\t' || text[back - 1] == '\r')) --back;
    next_line = back && text[back - 1] == '\n';
  }
  if (next_line)
    snprintf(message, capacity, "expected ',' or '%s', found %s: is a comma missing at the end of the line above?",
             expected, found);
  else if (expected)
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
/* Whether the line holding at ends with `name++` or `name--`, as in C; a
   newline does not end a Dyn expression, so the error can land anywhere on
   that line. operator_at is the first + or -. */
static bool increment_at(const char *text, size_t length, size_t at, size_t *operator_at) {
  if (at > length) return false;
  size_t end = at;
  while (end < length && text[end] != '\n') ++end;
  while (end > at && (text[end - 1] == ' ' || text[end - 1] == '\t' || text[end - 1] == '\r')) --end;
  if (end < at + 3) {
    size_t line = at;
    while (line && text[line - 1] != '\n') --line;
    if (end < line + 3) return false;
  }
  char sign = text[end - 1];
  if ((sign != '+' && sign != '-') || text[end - 2] != sign) return false;
  char before = text[end - 3];
  if (!(isalnum((unsigned char)before) || before == '_' || before == ']' || before == ')')) return false;
  *operator_at = end - 2;
  return true;
}
/* `let name = value`, `var name: T = value` or `let mut name = value` at at:
   the name, and where its `:` or `=` is. */
static bool declaration_at(const char *text, size_t length, size_t at, size_t *name_at, size_t *name_end,
                           size_t *after) {
  if (length - at < 6 || (memcmp(text + at, "let ", 4) && memcmp(text + at, "var ", 4))) return false;
  size_t k = at + 4;
  while (k < length && text[k] == ' ') ++k;
  if (length - k > 4 && !memcmp(text + k, "mut ", 4)) {
    k += 4;
    while (k < length && text[k] == ' ') ++k;
  }
  *name_at = k;
  while (k < length && (isalnum((unsigned char)text[k]) || text[k] == '_')) ++k;
  if (k == *name_at) return false;
  *name_end = k;
  while (k < length && text[k] == ' ') ++k;
  if (k >= length) return false;
  if (text[k] == ':' || (text[k] == '=' && k + 1 < length && text[k + 1] != '=')) {
    *after = k;
    return true;
  }
  return false;
}
/* Syntax from other languages, or removed Dyn syntax, gets Dyn's spelling:
   message is rewritten, and fix is set when the rewrite is mechanical. */
void dyn_syntax_hint(const char *text, size_t length, size_t start, const char *error, char *message,
                     size_t capacity, DynSyntaxFix *fix) {
  *fix = (DynSyntaxFix){0};
  if (!error || start > length) return;
  size_t rest = length - start, operator_at = 0, name_at = 0, name_end = 0, after = 0;
  if (!strcmp(error, "expression is not a statement") &&
      declaration_at(text, length, start, &name_at, &name_end, &after)) {
    if (text[after] == ':') {
      snprintf(message, capacity, "Dyn has no let or var: write `name: T = value`");
      *fix = (DynSyntaxFix){.start = start, .end = name_at, .set = true};
    } else if (name_end - name_at < 64) {
      snprintf(message, capacity, "Dyn has no let or var: write `name := value`");
      *fix = (DynSyntaxFix){.start = start, .end = after + 1, .set = true};
      snprintf(fix->replacement, sizeof(fix->replacement), "%.*s :=", (int)(name_end - name_at), text + name_at);
    }
  } else if (!strcmp(error, "expression is not a statement") && rest > 6 && !memcmp(text + start, "while", 5) &&
             (text[start + 5] == ' ' || text[start + 5] == '(')) {
    snprintf(message, capacity, "Dyn has no while: write `for condition {`");
    *fix = (DynSyntaxFix){.start = start, .end = start + 5, .replacement = "for", .set = true};
  } else if (increment_at(text, length, start, &operator_at)) {
    bool add = text[operator_at] == '+';
    snprintf(message, capacity, "Dyn has no %s: write `x %s= 1`", add ? "++" : "--", add ? "+" : "-");
    *fix = (DynSyntaxFix){.start = operator_at, .end = operator_at + 2, .set = true};
    snprintf(fix->replacement, sizeof(fix->replacement), "%s", add ? " += 1" : " -= 1");
  } else if (!strcmp(error, "unexpected character") && rest && text[start] == '?') {
    snprintf(message, capacity, "Dyn has no `? :`: assign in each branch of an if/else");
  } else if (!strncmp(error, "write `for *value in`", 21) && rest >= 5 && !memcmp(text + start, "const", 5)) {
    /* `for *const value in`: the const goes, the pointer stays. */
    size_t past = start + 5;
    while (past < length && (text[past] == ' ' || text[past] == '\t')) ++past;
    *fix = (DynSyntaxFix){.start = start, .end = past, .set = true};
  }
}
void dyn_report_syntax_error(const DynSource *source, uint32_t offset,
                             const char *error, const char *expected) {
  char message[160];
  uint32_t end;
  dyn_syntax_error_message(source->text, source->length, offset, error, expected,
                           message, sizeof(message), &end);
  size_t start = offset > source->length ? source->length : offset;
  DynSyntaxFix fix;
  dyn_syntax_hint(source->text, source->length, start, error, message, sizeof(message), &fix);
  if (fix.set) dyn_diagnostic_fix(source, start, fix.start, fix.end, fix.replacement, true);
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
