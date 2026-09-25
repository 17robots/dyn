#include "dyn.h"
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
