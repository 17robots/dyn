#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

static bool canonicalize(const DynSource *s, char **result, size_t *length) {
  char *out = malloc(s->length + 2);
  if (!out) return false;
  size_t at = 0, line = 0;
  for (size_t i = 0; i < s->length; ++i) {
    unsigned char c = (unsigned char)s->text[i];
    if (c == '\r' && i + 1 < s->length && s->text[i + 1] == '\n') continue;
    if (c == '\n') {
      while (at > line && (out[at - 1] == ' ' || out[at - 1] == '\t')) --at;
      out[at++] = '\n'; line = at;
    } else out[at++] = (char)c;
  }
  while (at > line && (out[at - 1] == ' ' || out[at - 1] == '\t')) --at;
  if (at && out[at - 1] != '\n') out[at++] = '\n';
  out[at] = 0; *result = out; *length = at;
  return true;
}
static int replace_file(const DynSource *s, const char *text, size_t length) {
  struct stat st;
  if (stat(s->path, &st)) return 2;
  size_t n = strlen(s->path);
  char *temporary = malloc(n + 16);
  if (!temporary) return 2;
  snprintf(temporary, n + 16, "%s.tmp.XXXXXX", s->path);
  int fd = mkstemp(temporary);
  if (fd < 0) { free(temporary); return 2; }
  size_t done = 0;
  while (done < length) {
    ssize_t wrote = write(fd, text + done, length - done);
    if (wrote <= 0) { close(fd); unlink(temporary); free(temporary); return 2; }
    done += (size_t)wrote;
  }
  int failed = fchmod(fd, st.st_mode & 07777) || fsync(fd) || close(fd) ||
               rename(temporary, s->path);
  if (failed) unlink(temporary);
  free(temporary); return failed ? 2 : 0;
}
int dyn_format_directory(const char *directory, bool check) {
  DynSources sources = {0};
  if (dyn_sources_load(directory, &sources)) return 2;
  char *main_path = dyn_path_join(directory, "main.dyn");
  if (!main_path) { dyn_sources_free(&sources); return 2; }
  DynCheckResult parsed = dyn_check_sources(&sources, main_path, false);
  free(main_path);
  if (parsed.errors) { dyn_sources_free(&sources); return 1; }
  int result = 0;
  for (size_t i = 0; i < sources.count; ++i) {
    char *text = NULL; size_t length = 0;
    if (!canonicalize(&sources.items[i], &text, &length)) { result = 2; break; }
    if (length != sources.items[i].length ||
        memcmp(text, sources.items[i].text, length)) {
      if (check) { fprintf(stderr, "%s: needs formatting\n", sources.items[i].path); result = 1; }
      else if (replace_file(&sources.items[i], text, length)) result = 2;
    }
    free(text);
    if (result == 2) break;
  }
  dyn_sources_free(&sources); return result;
}

int dyn_docs_directory(const char *directory) {
  DynSources sources = {0};
  if (dyn_sources_load(directory, &sources)) return 2;
  char *name = dyn_path_basename(directory);
  printf("# %s\n\n", name ? name : "module");
  for (size_t si = 0; si < sources.count; ++si) {
    const char *p = sources.items[si].text, *end = p + sources.items[si].length;
    while (p < end) {
      const char *line_end = memchr(p, '\n', (size_t)(end - p));
      if (!line_end) line_end = end;
      const char *q = p; while (q < line_end && isspace((unsigned char)*q)) ++q;
      if ((size_t)(line_end - q) >= 4 && !memcmp(q, "pub ", 4))
        printf("```dyn\n%.*s\n```\n\n", (int)(line_end - q), q);
      p = line_end < end ? line_end + 1 : end;
    }
  }
  free(name); dyn_sources_free(&sources); return 0;
}

static void lsp_send(const char *body) {
  printf("Content-Length: %zu\r\n\r\n%s", strlen(body), body); fflush(stdout);
}
static long request_id(const char *body) {
  const char *p = strstr(body, "\"id\"");
  if (!p || !(p = strchr(p, ':'))) return -1;
  return strtol(p + 1, NULL, 10);
}
int dyn_lsp(void) {
  char header[256];
  while (fgets(header, sizeof(header), stdin)) {
    size_t length = 0;
    do {
      if (!strncasecmp(header, "Content-Length:", 15))
        length = (size_t)strtoull(header + 15, NULL, 10);
      if (!strcmp(header, "\n") || !strcmp(header, "\r\n")) break;
    } while (fgets(header, sizeof(header), stdin));
    if (!length || length > 16u * 1024u * 1024u) return 2;
    char *body = malloc(length + 1);
    if (!body) return 2;
    if (fread(body, 1, length, stdin) != length) { free(body); return 2; }
    body[length] = 0; long id = request_id(body);
    if (strstr(body, "\"method\":\"initialize\"")) {
      char response[256];
      snprintf(response, sizeof(response),
        "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":{\"capabilities\":{\"textDocumentSync\":0}}}", id);
      lsp_send(response);
    } else if (strstr(body, "\"method\":\"shutdown\"")) {
      char response[96]; snprintf(response, sizeof(response),
        "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"result\":null}", id); lsp_send(response);
    } else if (strstr(body, "\"method\":\"exit\"")) { free(body); return 0; }
    else if (id >= 0) {
      char response[160]; snprintf(response, sizeof(response),
        "{\"jsonrpc\":\"2.0\",\"id\":%ld,\"error\":{\"code\":-32601,\"message\":\"method not supported\"}}", id); lsp_send(response);
    }
    free(body);
  }
  return 0;
}
