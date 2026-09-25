#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include "dyn_syntax.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int replace_file(const DynSource *s, const char *text, size_t length);
int dyn_format_directory(const char *directory, bool check);
int dyn_docs_directory(const char *directory, bool json);

bool dyn_format_source(const DynSource *s, char **result, size_t *length) {
  char *out = malloc(s->length + 2);
  if (!out)
    return false;
  size_t at = 0, line = 0;
  for (size_t i = 0; i < s->length; ++i) {
    unsigned char c = (unsigned char)s->text[i];
    if (c == '\r' && i + 1 < s->length && s->text[i + 1] == '\n')
      continue;
    if (c == '\n') {
      while (at > line && (out[at - 1] == ' ' || out[at - 1] == '\t'))
        --at;
      out[at++] = '\n';
      line = at;
    } else
      out[at++] = (char)c;
  }
  while (at > line && (out[at - 1] == ' ' || out[at - 1] == '\t'))
    --at;
  if (at && out[at - 1] != '\n')
    out[at++] = '\n';
  out[at] = 0;
  *result = out;
  *length = at;
  return true;
}

static int replace_file(const DynSource *s, const char *text, size_t length) {
  struct stat st;
  if (stat(s->path, &st))
    return 2;
  size_t n = strlen(s->path);
  char *temporary = malloc(n + 16);
  if (!temporary)
    return 2;
  snprintf(temporary, n + 16, "%s.tmp.XXXXXX", s->path);
  int fd = mkstemp(temporary);
  if (fd < 0) {
    free(temporary);
    return 2;
  }
  size_t done = 0;
  while (done < length) {
    ssize_t wrote = write(fd, text + done, length - done);
    if (wrote <= 0) {
      close(fd);
      unlink(temporary);
      free(temporary);
      return 2;
    }
    done += (size_t)wrote;
  }
  int failed = fchmod(fd, st.st_mode & 07777) || fsync(fd) || close(fd) ||
               rename(temporary, s->path);
  if (failed)
    unlink(temporary);
  free(temporary);
  return failed ? 2 : 0;
}

int dyn_format_directory(const char *directory, bool check) {
  DynSources sources = {0};
  if (dyn_sources_load(NULL, directory, &sources))
    return 2;
  char *main_path = dyn_path_join(directory, "main.dyn");
  if (!main_path) {
    dyn_sources_free(&sources);
    return 2;
  }
  DynCheckResult parsed = dyn_check_sources(&sources, main_path, false);
  free(main_path);
  if (parsed.errors) {
    dyn_sources_free(&sources);
    return 1;
  }
  int result = 0;
  for (size_t i = 0; i < sources.count; ++i) {
    char *text = NULL;
    size_t length = 0;
    if (!dyn_format_source(&sources.items[i], &text, &length)) {
      result = 2;
      break;
    }
    if (length != sources.items[i].length ||
        memcmp(text, sources.items[i].text, length)) {
      if (check) {
        fprintf(stderr, "%s: needs formatting\n", sources.items[i].path);
        result = 1;
      } else if (replace_file(&sources.items[i], text, length))
        result = 2;
    }
    free(text);
    if (result == 2)
      break;
  }
  dyn_sources_free(&sources);
  return result;
}

/* Length-delimited strings preserve source comments and escape JSON controls. */
static void docs_quote(FILE *out, const char *text, size_t length) {
  fputc('"', out);
  for (size_t i = 0; i < length; ++i) {
    unsigned char c = (unsigned char)text[i];
    if (c == '"' || c == '\\') {
      fputc('\\', out);
      fputc(c, out);
    } else if (c < 32)
      fprintf(out, "\\u%04x", c);
    else
      fputc(c, out);
  }
  fputc('"', out);
}

int dyn_docs_directory(const char *directory, bool json) {
  DynSources sources = {0};
  if (dyn_sources_load(NULL, directory, &sources))
    return 2;
  /* Publish only complete output: a later malformed file must not leave a
   * plausible partial index on stdout. Bound memory using a temporary stream. */
  FILE *out = tmpfile();
  if (!out) { dyn_sources_free(&sources); return 2; }
  char *name = dyn_path_basename(directory);
  int result = 0;
  if (json) {
    fprintf(out, "{\"schema_version\":1,\"analysis\":\"syntax-only\","
                 "\"target_selection\":\"all-source-files\","
                 "\"source_fingerprint\":\"%016llx\",\"module\":",
            (unsigned long long)dyn_interface_source_hash(&sources));
    docs_quote(out, directory, strlen(directory));
    fputs(",\"files\":[", out);
  } else
    fprintf(out, "# %s\n\n", name ? name : "module");
  for (size_t si = 0; si < sources.count; ++si) {
    DynSource *source = &sources.items[si];
    TSTree *tree = dyn_syntax_parse(source->text, source->length);
    if (!tree) { result = 2; break; }
    if (ts_node_has_error(ts_tree_root_node(tree))) {
      fprintf(stderr, "%s: cannot document malformed source\n", source->path);
      ts_tree_delete(tree); result = 1; break;
    }
    if (json) {
      if (si) fputc(',', out);
      fputs("{\"path\":", out);
      docs_quote(out, source->path, strlen(source->path));
      fputs(",\"target_gates\":[", out);
    } else
      fprintf(out, "## Source: %s\n\n", source->path);
    bool gate_comma = false;
    TSNode root = ts_tree_root_node(tree);
    for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
      TSNode gate = ts_node_named_child(root, i);
      if (strcmp(ts_node_type(gate), "target_directive")) continue;
      uint32_t at = ts_node_start_byte(gate), end = ts_node_end_byte(gate);
      if (json) {
        if (gate_comma) fputc(',', out);
        docs_quote(out, source->text + at, end - at);
        gate_comma = true;
      } else
        fprintf(out, "Target gate: `%.*s`\n\n", (int)(end - at), source->text + at);
    }
    if (json) fputs("],\"declarations\":[", out);
    bool declaration_comma = false;
    for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
      TSNode wrapper = ts_node_named_child(root, i);
      DynDeclaration decl;
      if (!dyn_syntax_declaration(wrapper, &decl) || !decl.is_public)
        continue;
      uint32_t start = ts_node_start_byte(wrapper), end = ts_node_end_byte(wrapper);
      if (decl.kind == DYN_DECL_FUNCTION)
        for (uint32_t j = 0; j < ts_node_named_child_count(decl.node); ++j) {
          TSNode child = ts_node_named_child(decl.node, j);
          if (!strcmp(ts_node_type(child), "block")) { end = ts_node_start_byte(child); break; }
        }
      while (end > start && isspace((unsigned char)source->text[end - 1])) --end;
      TSPoint point = ts_node_start_point(wrapper);
      /* Adjacent line comments are the contract source, not a second registry. */
      size_t comment = start;
      while (comment && (source->text[comment - 1] == ' ' || source->text[comment - 1] == '\t')) --comment;
      size_t comments_end = comment;
      while (comment && source->text[comment - 1] == '\n') {
        size_t line_end = comment - 1, line = line_end;
        while (line && source->text[line - 1] != '\n') --line;
        size_t first = line;
        while (first < line_end && isspace((unsigned char)source->text[first])) ++first;
        if (first + 2 > line_end || memcmp(source->text + first, "//", 2)) break;
        comment = line;
      }
      if (json) {
        static const char *kinds[] = {"function", "struct", "enum", "alias", "constant", "variable"};
        if (declaration_comma) fputc(',', out);
        declaration_comma = true;
        fputs("{\"name\":", out);
        uint32_t ns = ts_node_start_byte(decl.name), ne = ts_node_end_byte(decl.name);
        docs_quote(out, source->text + ns, ne - ns);
        fprintf(out, ",\"kind\":\"%s\",\"line\":%u,\"column\":%u,\"declaration\":",
                kinds[decl.kind], point.row + 1, point.column + 1);
        docs_quote(out, source->text + start, end - start);
        fputs(",\"source_comments\":", out);
        docs_quote(out, source->text + comment, comments_end - comment);
        fputc('}', out);
      } else {
        fprintf(out, "[Source](%s#L%u)\n\n", source->path, point.row + 1);
        for (size_t at = comment; at < comments_end;) {
          size_t line_end = at;
          while (line_end < comments_end && source->text[line_end] != '\n') ++line_end;
          while (at < line_end && isspace((unsigned char)source->text[at])) ++at;
          if (at + 2 <= line_end && !memcmp(source->text + at, "//", 2)) at += 2;
          if (at < line_end && source->text[at] == ' ') ++at;
          fprintf(out, "%.*s\n", (int)(line_end - at), source->text + at);
          at = line_end + 1;
        }
        if (comment < comments_end) fputc('\n', out);
        fprintf(out, "```dyn\n%.*s\n```\n\n", (int)(end - start), source->text + start);
      }
    }
    if (json) fputs("]}", out);
    ts_tree_delete(tree);
  }
  if (json) fputs("]}\n", out);
  if (ferror(out)) result = 2;
  if (!result) {
    if (fseek(out, 0, SEEK_SET)) result = 2;
    else {
      char buffer[8192];
      size_t length;
      for (;;) {
        length = fread(buffer, 1, sizeof(buffer), out);
        if (length && fwrite(buffer, 1, length, stdout) != length) { result = 2; break; }
        if (ferror(out) || feof(out)) break;
      }
      if (ferror(out) || fflush(stdout)) result = 2;
    }
  }
  fclose(out);
  free(name);
  dyn_sources_free(&sources);
  return result;
}
