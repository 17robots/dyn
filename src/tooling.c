#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include "dyn_syntax.h"
#include <ctype.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int replace_file(const DynSource *s, const char *text, size_t length);
int dyn_format_directory(const char *directory, bool check);
int dyn_docs_directory(const char *directory, bool json);

/* Layout edits are insertions only, so they cannot change tokens. */
typedef struct {
  size_t offset;
  unsigned indent; /* UINT_MAX inserts one space; otherwise newline + indent */
} FormatInsert;

typedef struct {
  const char *text;
  FormatInsert *items;
  size_t count, capacity;
  bool failed;
} FormatEdits;

static void format_insert(FormatEdits *edits, size_t offset, unsigned indent) {
  if (edits->count == edits->capacity) {
    size_t capacity = edits->capacity ? edits->capacity * 2 : 32;
    FormatInsert *items = realloc(edits->items, capacity * sizeof(*items));
    if (!items) {
      edits->failed = true;
      return;
    }
    edits->items = items;
    edits->capacity = capacity;
  }
  edits->items[edits->count++] = (FormatInsert){offset, indent};
}

static unsigned format_line_indent(const char *text, uint32_t offset) {
  size_t line = offset;
  while (line && text[line - 1] != '\n')
    --line;
  unsigned indent = 0;
  while (text[line + indent] == ' ' || text[line + indent] == '\t')
    ++indent;
  return indent;
}

/* anchor_row/anchor_indent give the post-format indent of a line whose
   statement moved; other lines keep their existing indentation. */
static void format_layout(FormatEdits *edits, TSNode node, uint32_t anchor_row,
                          unsigned anchor_indent) {
  const char *text = edits->text;
  if (!ts_node_is_named(node) && !strcmp(ts_node_type(node), ",")) {
    char next = text[ts_node_end_byte(node)];
    if (next && !strchr(" \t\r\n)]}", next))
      format_insert(edits, ts_node_end_byte(node), UINT_MAX);
    return;
  }
  uint32_t count = ts_node_child_count(node);
  if (strcmp(ts_node_type(node), "block")) {
    for (uint32_t i = 0; i < count; ++i)
      format_layout(edits, ts_node_child(node, i), anchor_row, anchor_indent);
    return;
  }
  uint32_t row = ts_node_start_point(node).row;
  unsigned base = row == anchor_row
                      ? anchor_indent
                      : format_line_indent(text, ts_node_start_byte(node));
  uint32_t previous = row;
  bool statements = false;
  for (uint32_t i = 0; i < count; ++i) {
    TSNode child = ts_node_child(node, i);
    uint32_t start = ts_node_start_point(child).row;
    if (!strcmp(ts_node_type(child), "statement")) {
      unsigned indent = format_line_indent(text, ts_node_start_byte(child));
      if (start == previous) {
        indent = base + 2;
        format_insert(edits, ts_node_start_byte(child), indent);
      }
      format_layout(edits, child, start, indent);
      previous = ts_node_end_point(child).row;
      statements = true;
    } else if (statements && !ts_node_is_named(child) &&
               !strcmp(ts_node_type(child), "}") && start == previous)
      format_insert(edits, ts_node_start_byte(child), base);
    else
      format_layout(edits, child, anchor_row, anchor_indent);
  }
}

static int format_insert_order(const void *a, const void *b) {
  size_t x = ((const FormatInsert *)a)->offset,
         y = ((const FormatInsert *)b)->offset;
  return x < y ? -1 : x > y;
}

/* Canonical layout: one statement per line, a space after each comma, LF line
   endings, no trailing horizontal whitespace, and a final newline. Malformed
   sources receive only the whitespace rules. */
bool dyn_format_source(const DynSource *s, char **result, size_t *length) {
  FormatEdits edits = {.text = s->text};
  TSTree *tree = dyn_syntax_parse(s->text, s->length);
  if (tree && !ts_node_has_error(ts_tree_root_node(tree)))
    format_layout(&edits, ts_tree_root_node(tree), UINT32_MAX, 0);
  if (tree)
    ts_tree_delete(tree);
  size_t extra = 0;
  for (size_t i = 0; i < edits.count; ++i)
    extra += edits.items[i].indent == UINT_MAX ? 1 : 1 + edits.items[i].indent;
  char *out = edits.failed ? NULL : malloc(s->length + extra + 2);
  if (!out) {
    free(edits.items);
    return false;
  }
  qsort(edits.items, edits.count, sizeof(*edits.items), format_insert_order);
  size_t at = 0, line = 0, next = 0;
  for (size_t i = 0; i <= s->length; ++i) {
    for (; next < edits.count && edits.items[next].offset == i; ++next) {
      if (edits.items[next].indent == UINT_MAX) {
        out[at++] = ' ';
        continue;
      }
      while (at > line && (out[at - 1] == ' ' || out[at - 1] == '\t'))
        --at;
      out[at++] = '\n';
      line = at;
      memset(out + at, ' ', edits.items[next].indent);
      at += edits.items[next].indent;
    }
    if (i == s->length)
      break;
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
  free(edits.items);
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

/* Formatting only rewrites whitespace, so a clean parse is its whole
   precondition. Semantic checking would need the project's imports. */
bool dyn_format_syntax_ok(const DynSource *s, bool report) {
  TSTree *tree = dyn_syntax_parse(s->text, s->length);
  if (!tree) {
    if (report)
      fprintf(stderr, "%s: cannot parse source\n", s->path);
    return false;
  }
  TSNode node = ts_tree_root_node(tree);
  bool ok = !ts_node_has_error(node);
  while (!ok && report) {
    if (ts_node_is_error(node) || ts_node_is_missing(node)) {
      dyn_syntax_diagnostic(node, s, "error", ts_node_is_missing(node)
                                                  ? "missing syntax"
                                                  : "syntax error");
      break;
    }
    uint32_t count = ts_node_child_count(node), i = 0;
    while (i < count && !ts_node_has_error(ts_node_child(node, i)))
      ++i;
    if (i == count) {
      dyn_syntax_diagnostic(node, s, "error", "syntax error");
      break;
    }
    node = ts_node_child(node, i);
  }
  ts_tree_delete(tree);
  return ok;
}

int dyn_format_directory(const char *directory, bool check) {
  DynSources sources = {0};
  if (dyn_sources_load(NULL, directory, &sources))
    return 2;
  /* Validate every file first so a malformed file never leaves the module
     partially rewritten. */
  bool malformed = false;
  for (size_t i = 0; i < sources.count; ++i)
    if (!dyn_format_syntax_ok(&sources.items[i], true))
      malformed = true;
  if (malformed) {
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

/* Optional summaries come from adjacent comments, just like source_comments.
 * Each label occupies one line; full prose remains available in source_comments. */
static void docs_contracts(FILE *out, const char *text, size_t start, size_t end) {
  const char *labels[] = {"Ownership:", "Invalidation:", "Allocation:", "Failure:", "Thread safety:"};
  const char *keys[] = {"ownership", "invalidation", "allocation", "failure", "thread_safety"};
  fputs(",\"contracts\":{", out);
  bool comma = false;
  for (size_t key = 0; key < sizeof(keys) / sizeof(*keys); ++key) {
    for (size_t line = start; line < end;) {
      size_t next = line;
      while (next < end && text[next] != '\n') ++next;
      size_t at = line;
      while (at < next && isspace((unsigned char)text[at])) ++at;
      if (at + 2 <= next && !memcmp(text + at, "//", 2)) at += 2;
      while (at < next && isspace((unsigned char)text[at])) ++at;
      size_t length = strlen(labels[key]);
      if (at + length <= next && !memcmp(text + at, labels[key], length)) {
        at += length;
        while (at < next && isspace((unsigned char)text[at])) ++at;
        size_t stop = next;
        while (stop > at && isspace((unsigned char)text[stop - 1])) --stop;
        if (comma) fputc(',', out);
        comma = true;
        docs_quote(out, keys[key], strlen(keys[key])); fputc(':', out);
        docs_quote(out, text + at, stop - at);
        break;
      }
      line = next + (next < end);
    }
  }
  fputc('}', out);
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
        docs_contracts(out, source->text, comment, comments_end);
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
