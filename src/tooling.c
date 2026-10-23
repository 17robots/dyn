#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include "syntax_tree.h"
#include "dyn_compact.h"
#include "syntax_depth.h"
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

/* Line starts give statement rows without a syntax-tree point API. */
typedef struct {
  const ExpSnapshotTree *tree;
  const size_t *lines;
  size_t line_count;
} FormatTree;

static uint32_t format_row(const FormatTree *t, size_t offset) {
  size_t low = 0, high = t->line_count;
  while (high - low > 1) {
    size_t mid = low + (high - low) / 2;
    if (t->lines[mid] <= offset) low = mid;
    else high = mid;
  }
  return (uint32_t)low;
}

/* Same rules as the grammar walk: commas are found lexically, and every
   child of a block is a statement because comments are not tree nodes. */
static void format_layout_compact(FormatEdits *edits, const FormatTree *t,
                                  uint32_t id, uint32_t anchor_row,
                                  unsigned anchor_indent) {
  const ExpNode *nodes = t->tree->nodes, *node = &nodes[id];
  if (node->kind != SRC_BLOCK) {
    for (uint32_t child = node->first; child != UINT32_MAX; child = nodes[child].next)
      format_layout_compact(edits, t, child, anchor_row, anchor_indent);
    return;
  }
  uint32_t row = format_row(t, node->start);
  unsigned base = row == anchor_row ? anchor_indent
                                    : format_line_indent(edits->text, node->start);
  uint32_t previous = row;
  bool statements = false;
  for (uint32_t child = node->first; child != UINT32_MAX; child = nodes[child].next) {
    uint32_t start = format_row(t, nodes[child].start);
    unsigned indent = format_line_indent(edits->text, nodes[child].start);
    if (start == previous) {
      indent = base + 2;
      format_insert(edits, nodes[child].start, indent);
    }
    format_layout_compact(edits, t, child, start, indent);
    previous = format_row(t, nodes[child].end);
    statements = true;
  }
  if (statements && node->end > node->start && edits->text[node->end - 1] == '}' &&
      format_row(t, node->end - 1) == previous)
    format_insert(edits, node->end - 1, base);
}

/* Skips literals and comments with the handwritten lexer's rules. */
static void format_commas(FormatEdits *edits, size_t length) {
  const char *text = edits->text;
  for (size_t i = 0; i < length; ++i) {
    char c = text[i];
    if (c == '/' && i + 1 < length && text[i + 1] == '/') {
      while (i < length && text[i] != '\n') ++i;
    } else if (c == '/' && i + 1 < length && text[i + 1] == '*') {
      for (i += 2; i + 1 < length && !(text[i] == '*' && text[i + 1] == '/'); ++i) {}
      ++i;
    } else if (c == '"') {
      for (++i; i < length && text[i] != '"'; ++i)
        if (text[i] == '\\') ++i;
    } else if (c == '\'') {
      /* A character literal, or the quote of a type parameter. */
      size_t end = i + 1;
      if (end < length && text[end] == '\\') {
        ++end;
        while (end < length && text[end] != '\'' && text[end] != '\n') ++end;
      } else if (end < length) {
        ++end;
        while (end < length && ((unsigned char)text[end] & 0xc0) == 0x80) ++end;
      }
      if (end < length && text[end] == '\'') i = end;
    } else if (c == ',') {
      char next = i + 1 < length ? text[i + 1] : 0;
      if (next && !strchr(" \t\r\n)]}", next))
        format_insert(edits, i + 1, UINT_MAX);
    }
  }
}

static void format_compact(FormatEdits *edits, const DynSource *s) {
  ExpSnapshot *snapshot = exp_snapshot_create(s->text, s->length, NULL, NULL);
  const ExpSnapshotTree *tree = exp_snapshot_tree(snapshot);
  if (!tree) return;
  size_t count = 1;
  for (size_t i = 0; i < s->length; ++i) count += s->text[i] == '\n';
  size_t *lines = malloc(count * sizeof(*lines));
  if (!lines) { edits->failed = true; exp_snapshot_release(snapshot); return; }
  lines[0] = 0;
  for (size_t i = 0, at = 1; i < s->length; ++i)
    if (s->text[i] == '\n') lines[at++] = i + 1;
  FormatTree t = {tree, lines, count};
  format_commas(edits, s->length);
  format_layout_compact(edits, &t, tree->root, UINT32_MAX, 0);
  free(lines);
  exp_snapshot_release(snapshot);
}

static int format_insert_order(const void *a, const void *b) {
  size_t x = ((const FormatInsert *)a)->offset,
         y = ((const FormatInsert *)b)->offset;
  return x < y ? -1 : x > y;
}

/* Indentation: two spaces per enclosing bracket, measured from the line that
   starts the statement. A line ending in a binary operator continues its
   statement one level deeper. Leading closers return to their opener's level.
   Block comment interiors keep their text. Unbalanced input is left as is. */
typedef struct {
  unsigned statement;
  char kind;
} FormatBracket;

static bool format_continues(const char *code, size_t length) {
  static const char *const tails[] = {"||", "&&", "==", "!=", "<=", ">=", ":=", "+=", "-=",
                                      "+", "-", "*", "/", "%", "|", "&", "^", "<", ">", "="};
  if (length >= 2 && code[length - 2] == '.' && code[length - 1] == '*')
    return false;
  for (size_t i = 0; i < sizeof(tails) / sizeof(*tails); ++i) {
    size_t n = strlen(tails[i]);
    if (length >= n && !memcmp(code + length - n, tails[i], n))
      return true;
  }
  return false;
}

static char *format_reindent(const char *text, size_t length, size_t *result_length) {
  size_t lines = 1, capacity = 0;
  for (size_t i = 0; i < length; ++i) {
    lines += text[i] == '\n';
    capacity += text[i] == '(' || text[i] == '[' || text[i] == '{';
  }
  FormatBracket *stack = malloc((capacity + 1) * sizeof(*stack));
  char *code = malloc(length + 1);
  /* Each line gains at most two spaces per open bracket plus one level. */
  size_t limit = length + 1 + lines * 2 * (capacity + 2);
  char *out = stack && code ? malloc(limit) : NULL;
  if (!out) {
    free(stack);
    free(code);
    return NULL;
  }
  size_t depth = 0, at = 0;
  unsigned previous_statement = 0;
  bool in_block = false, continued = false, balanced = true;
  for (size_t start = 0; start < length;) {
    size_t end = start;
    while (end < length && text[end] != '\n')
      ++end;
    size_t first = start;
    while (first < end && (text[first] == ' ' || text[first] == '\t'))
      ++first;
    if (in_block || first == end) {
      size_t from = in_block ? start : end;
      memcpy(out + at, text + from, end - from);
      at += end - from;
      for (size_t i = start; in_block && i + 1 < end; ++i)
        if (text[i] == '*' && text[i + 1] == '/')
          in_block = false;
    } else {
      size_t leading = 0;
      while (first + leading < end && leading < depth && strchr(")]}", text[first + leading]))
        ++leading;
      unsigned indent, statement;
      if (leading) {
        indent = statement = stack[depth - leading].statement;
      } else {
        indent = (depth ? stack[depth - 1].statement + 1 : 0) + (continued ? 1 : 0);
        if (continued)
          statement = previous_statement;
        else if (depth && stack[depth - 1].kind != '{')
          statement = stack[depth - 1].statement;
        else
          statement = indent;
      }
      memset(out + at, ' ', 2 * (size_t)indent);
      at += 2 * (size_t)indent;
      memcpy(out + at, text + first, end - first);
      at += end - first;
      size_t code_length = 0;
      for (size_t i = first; i < end; ++i) {
        char c = text[i];
        if (c == '/' && i + 1 < end && text[i + 1] == '/')
          break;
        if (c == '/' && i + 1 < end && text[i + 1] == '*') {
          size_t close = i + 2;
          while (close + 1 < end && !(text[close] == '*' && text[close + 1] == '/'))
            ++close;
          if (close + 1 >= end) {
            in_block = true;
            break;
          }
          i = close + 1;
          continue;
        }
        if (c == '"') {
          for (++i; i < end && text[i] != '"'; ++i)
            if (text[i] == '\\')
              ++i;
          code[code_length++] = '"';
          continue;
        }
        if (c == '\'') {
          size_t close = i + 1;
          if (close < end && text[close] == '\\')
            while (close < end && text[close] != '\'')
              ++close;
          else if (close < end) {
            ++close;
            while (close < end && ((unsigned char)text[close] & 0xc0) == 0x80)
              ++close;
          }
          if (close < end && text[close] == '\'') {
            i = close;
            code[code_length++] = '0';
            continue;
          }
        }
        if (c == '(' || c == '[' || c == '{')
          stack[depth++] = (FormatBracket){statement, c};
        else if (c == ')' || c == ']' || c == '}') {
          if (!depth || stack[depth - 1].kind != (c == ')' ? '(' : c == ']' ? '[' : '{'))
            balanced = false;
          else
            --depth;
        }
        code[code_length++] = c;
      }
      while (code_length && (code[code_length - 1] == ' ' || code[code_length - 1] == '\t'))
        --code_length;
      continued = format_continues(code, code_length);
      previous_statement = statement;
    }
    if (end < length)
      out[at++] = '\n';
    start = end + 1;
    if (!balanced)
      break;
  }
  free(stack);
  free(code);
  if (!balanced || depth || in_block) {
    free(out);
    return NULL;
  }
  out[at] = 0;
  *result_length = at;
  return out;
}

/* Canonical layout: one statement per line, a space after each comma, two-space
   indentation, LF line endings, no trailing horizontal whitespace, and a final
   newline. Malformed
   sources receive only the whitespace rules. */
bool dyn_format_source(const DynSource *s, char **result, size_t *length) {
  FormatEdits edits = {.text = s->text};
  format_compact(&edits, s);
  size_t extra = 0;
  for (size_t i = 0; i < edits.count; ++i)
    extra += edits.items[i].indent == UINT_MAX ? 1 : 1 + edits.items[i].indent;
  char *out = edits.failed ? NULL : malloc(s->length + extra + 2);
  if (!out) {
    free(edits.items);
    return false;
  }
  if (edits.count)
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
  size_t indented_length = 0;
  char *indented = format_reindent(out, at, &indented_length);
  if (indented) {
    free(out);
    out = indented;
    at = indented_length;
  }
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
  ExpSnapshotError error;
  ExpSnapshot *snapshot = exp_snapshot_create(s->text, s->length, NULL, &error);
  if (snapshot) {
    bool deep = !exp_depth_certified(exp_snapshot_tree(snapshot), DYN_SYNTAX_DEPTH_LIMIT);
    exp_snapshot_release(snapshot);
    if (deep && report)
      dyn_diagnostic_source("error", s, 0, 0, "syntax nesting exceeds 1024 tree levels");
    return !deep;
  }
  if (!report) return false;
  if (error.kind == EXP_SYNTAX_ERROR) {
    DynSource failed = *s;
    failed.syntax_error = error.message;
    failed.syntax_expected = error.expected;
    failed.syntax_error_offset = error.offset;
    dyn_source_report_syntax(&failed);
  } else if (error.kind == EXP_LIMIT_ERROR && strstr(error.message, "nesting"))
    dyn_diagnostic_source("error", s, 0, 0, "syntax nesting exceeds 1024 tree levels");
  else
    fprintf(stderr, "%s: cannot parse source\n", s->path);
  return false;
}

/* Batch tools parse with the handwritten parser only; loading reports a
   syntax error itself. */
static int tooling_load(const char *directory, DynSources *sources) {
  DynContext context = {.strict_syntax = true};
  int result = dyn_sources_load(&context, directory, sources);
  return result == 1 ? 1 : result ? 2 : 0;
}

int dyn_format_directory(const char *directory, bool check) {
  DynSources sources = {0};
  int loaded = tooling_load(directory, &sources);
  if (loaded)
    return loaded;
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

/* An anonymous temporary file in TMPDIR. tmpfile() always uses /tmp. */
static FILE *docs_temporary(void) {
#ifndef _WIN32
  const char *root = getenv("TMPDIR");
  char path[4096];
  if (root && *root && snprintf(path, sizeof(path), "%s/dyn-docs-XXXXXX", root) < (int)sizeof(path)) {
    int descriptor = mkstemp(path);
    if (descriptor >= 0) {
      unlink(path);
      FILE *file = fdopen(descriptor, "w+b");
      if (file) return file;
      close(descriptor);
    }
  }
#endif
  return tmpfile();
}
int dyn_docs_directory(const char *directory, bool json) {
  DynSources sources = {0};
  int loaded = tooling_load(directory, &sources);
  if (loaded)
    return loaded;
  /* Publish only complete output: a later malformed file must not leave a
   * plausible partial index on stdout. Bound memory using a temporary stream. */
  FILE *out = docs_temporary();
  if (!out) { perror("error: create temporary docs output"); dyn_sources_free(&sources); return 2; }
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
    const ExpSnapshotTree *tree = dyn_compact_tree(source);
    if (!tree) { result = 2; break; }
    const ExpNode *nodes = tree->nodes;
    if (json) {
      if (si) fputc(',', out);
      fputs("{\"path\":", out);
      docs_quote(out, source->path, strlen(source->path));
      fputs(",\"target_gates\":[", out);
    } else
      fprintf(out, "## Source: %s\n\n", source->path);
    bool gate_comma = false;
    for (uint32_t gate = nodes[tree->root].first; gate != UINT32_MAX; gate = nodes[gate].next) {
      if (nodes[gate].kind != SRC_TARGET) continue;
      uint32_t at = nodes[gate].start, end = nodes[gate].end;
      if (json) {
        if (gate_comma) fputc(',', out);
        docs_quote(out, source->text + at, end - at);
        gate_comma = true;
      } else
        fprintf(out, "Target gate: `%.*s`\n\n", (int)(end - at), source->text + at);
    }
    if (json) fputs("],\"declarations\":[", out);
    bool declaration_comma = false;
    for (uint32_t wrapper = nodes[tree->root].first; wrapper != UINT32_MAX; wrapper = nodes[wrapper].next) {
      uint32_t name = dyn_compact_name(tree, wrapper);
      if (name == UINT32_MAX || !(nodes[wrapper].flags & EXP_PUBLIC)) continue;
      const ExpNode *value = &nodes[nodes[wrapper].first];
      DynDeclarationKind kind;
      switch (value->kind) {
      case SRC_FN: case SRC_EXTERN_FN: kind = DYN_DECL_FUNCTION; break;
      case SRC_STRUCT: kind = DYN_DECL_STRUCT; break;
      case SRC_ENUM: kind = DYN_DECL_ENUM; break;
      case SRC_ALIAS: kind = DYN_DECL_ALIAS; break;
      case SRC_CONST: kind = DYN_DECL_CONSTANT; break;
      default: kind = DYN_DECL_VARIABLE; break;
      }
      uint32_t start = nodes[wrapper].start, end = nodes[wrapper].end;
      if (kind == DYN_DECL_FUNCTION)
        for (uint32_t child = value->first; child != UINT32_MAX; child = nodes[child].next)
          if (nodes[child].kind == SRC_BLOCK) { end = nodes[child].start; break; }
      uint32_t ns = nodes[name].start, ne = nodes[name].end;
      unsigned row = 0, column = 0;
      for (uint32_t at = 0; at < start; ++at) {
        if (source->text[at] == '\n') { ++row; column = 0; }
        else ++column;
      }
      while (end > start && isspace((unsigned char)source->text[end - 1])) --end;
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
        docs_quote(out, source->text + ns, ne - ns);
        fprintf(out, ",\"kind\":\"%s\",\"line\":%u,\"column\":%u,\"declaration\":",
                kinds[kind], row + 1, column + 1);
        docs_quote(out, source->text + start, end - start);
        fputs(",\"source_comments\":", out);
        docs_quote(out, source->text + comment, comments_end - comment);
        docs_contracts(out, source->text, comment, comments_end);
        fputc('}', out);
      } else {
        fprintf(out, "[Source](%s#L%u)\n\n", source->path, row + 1);
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
