#include "dyn.h"
#include <stdio.h>
static bool json_output;
void dyn_diagnostic_mode(bool json) { json_output = json; }
static void quote(const char *s) {
  fputc('"', stderr);
  for (; s && *s; ++s) {
    unsigned char c = (unsigned char)*s;
    if (c == '"' || c == '\\') { fputc('\\', stderr); fputc(c, stderr); }
    else if (c == '\n') fputs("\\n", stderr);
    else if (c == '\r') fputs("\\r", stderr);
    else if (c == '\t') fputs("\\t", stderr);
    else if (c < 32) fprintf(stderr, "\\u%04x", c); else fputc(c, stderr);
  }
  fputc('"', stderr);
}
void dyn_diagnostic(const char *severity, const char *path, unsigned line,
                    unsigned column, unsigned end_line, unsigned end_column,
                    const char *message) {
  if (!json_output) {
    fprintf(stderr, "%s:%u:%u: %s: %s", path ? path : "<compiler>", line,
            column, severity, message);
    if (end_line || end_column) fprintf(stderr, " [range %u:%u-%u:%u]", line,
      column, end_line ? end_line : line, end_column ? end_column : column);
    fputc('\n', stderr); return;
  }
  fputs("{\"severity\":", stderr); quote(severity);
  fputs(",\"message\":", stderr); quote(message);
  fputs(",\"path\":", stderr); quote(path ? path : "");
  fprintf(stderr, ",\"range\":{\"start\":{\"line\":%u,\"column\":%u},"
    "\"end\":{\"line\":%u,\"column\":%u}}}\n", line, column,
    end_line ? end_line : line, end_column ? end_column : column);
}
