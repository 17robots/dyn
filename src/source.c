#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include "dyn_compact.h"
#include "dyn_compact.h"
#include <ctype.h>
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#ifndef _WIN32
#include <pthread.h>
#include <stdatomic.h>
#endif

/* Bound compiler memory from accidental/generated hostile source inputs. */
#define DYN_MAX_SOURCE_BYTES (64u * 1024u * 1024u)
#define DYN_MAX_MODULE_BYTES (256u * 1024u * 1024u)
#define DYN_MAX_MODULE_SOURCES 4096u

char *dyn_path_join(const char *a, const char *b) {
  size_t an = strlen(a), bn = strlen(b);
  bool slash = an && a[an - 1] != '/';
  char *r = malloc(an + (size_t)slash + bn + 1);
  if (!r)
    return NULL;
  memcpy(r, a, an);
  if (slash)
    r[an++] = '/';
  memcpy(r + an, b, bn + 1);
  return r;
}
char *dyn_path_basename(const char *path) {
  char resolved[4096];
  if ((strcmp(path, ".") == 0 || strcmp(path, "..") == 0) &&
      getcwd(resolved, sizeof(resolved))) {
#ifdef _WIN32
    dyn_host_slashes(resolved);
#endif
    if (strcmp(path, "..") == 0) {
      char *slash = strrchr(resolved, '/');
      if (slash && slash != resolved)
        *slash = 0;
    }
    path = resolved;
  }
  size_t n = strlen(path);
  while (n > 1 && (path[n - 1] == '/'
#ifdef _WIN32
                   || path[n - 1] == '\\'
#endif
                   ))
    --n;
  size_t start = n;
  while (start && path[start - 1] != '/'
#ifdef _WIN32
         && path[start - 1] != '\\'
#endif
         )
    --start;
  char *r = malloc(n - start + 1);
  if (!r)
    return NULL;
  memcpy(r, path + start, n - start);
  r[n - start] = 0;
  return r;
}
bool dyn_path_is_directory(const char *path) {
  struct stat st;
  return stat(path, &st) == 0 && S_ISDIR(st.st_mode);
}
static int source_compare(const void *a, const void *b) {
  return strcmp(((const DynSource *)a)->path, ((const DynSource *)b)->path);
}
static int prepare_failure(DynSource *s, bool quiet) {
  if (!dyn_work_step(&s->context, 0)) {
    if (!quiet) dyn_diagnostic(&s->context, "error", s->path, 1, 1, 1, 1, "analysis work budget exceeded");
    return 1;
  }
  if (s->syntax_too_deep)
    if (!quiet) dyn_diagnostic(&s->context, "error", s->path, 1, 1, 1, 1,
                   "syntax nesting exceeds 1024 tree levels");
  bool syntax_error = quiet ? s->syntax_error != NULL : dyn_source_report_syntax(s);
  return s->syntax_too_deep || syntax_error ? 1 : 2;
}
#ifndef _WIN32
typedef struct {
  DynSources *sources;
  bool *prepared;
  atomic_size_t next;
} PrepareJobs;
static void *prepare_worker(void *raw) {
  PrepareJobs *jobs = raw;
  for (;;) {
    size_t i = atomic_fetch_add(&jobs->next, 1);
    if (i >= jobs->sources->count) return NULL;
    jobs->prepared[i] = dyn_source_prepare(&jobs->sources->items[i]);
  }
}
#endif
/* Parses every file read by sources_load on several threads, then reports
   the first failure in directory order, as the serial loop would have. */
static int prepare_parallel(DynSources *out, bool quiet) {
  bool *prepared = calloc(out->count ? out->count : 1, sizeof(bool));
  if (!prepared) return 2;
#ifndef _WIN32
  PrepareJobs jobs = {.sources = out, .prepared = prepared};
  atomic_init(&jobs.next, 0);
  long online = sysconf(_SC_NPROCESSORS_ONLN);
  size_t workers = online > 1 ? (size_t)online : 1;
  if (workers > out->count) workers = out->count;
  if (workers > 64) workers = 64;
  pthread_t threads[64];
  size_t started = 0;
  for (; started + 1 < workers; ++started)
    if (pthread_create(&threads[started], NULL, prepare_worker, &jobs)) break;
  prepare_worker(&jobs);
  for (size_t i = 0; i < started; ++i) pthread_join(threads[i], NULL);
#else
  for (size_t i = 0; i < out->count; ++i) prepared[i] = dyn_source_prepare(&out->items[i]);
#endif
  int result = 0;
  for (size_t i = 0; i < out->count && !result; ++i)
    if (!prepared[i]) result = prepare_failure(&out->items[i], quiet);
  free(prepared);
  return result;
}
static int sources_load(const DynContext *context, const char *dir,
                        DynSources *out, bool quiet) {
  memset(out, 0, sizeof(*out));
  /* Budgeted and cached editor analysis share mutable context state, so
     only plain command loads parse on several threads. */
  bool parallel = !quiet && context && !context->work && !context->syntax_cache;
  /* An error stops the serial loop after parsing every earlier file; report
     an earlier syntax error first here too. */
#define EARLIER(skip) do { if (parallel) { size_t all = out->count; out->count -= (skip); \
    int earlier = prepare_parallel(out, quiet); out->count = all; if (earlier) return earlier; } } while (0)
  DIR *d = opendir(dir);
  if (!d) {
    if (!quiet) fprintf(stderr, "error: cannot open module directory '%s'\n", dir);
    return 1;
  }
  struct dirent *entry;
  while ((entry = readdir(d))) {
    size_t n = strlen(entry->d_name);
    if (n < 5 || strcmp(entry->d_name + n - 4, ".dyn") != 0)
      continue;
    if (out->count == DYN_MAX_MODULE_SOURCES) {
      closedir(d);
      EARLIER(0);
      if (!quiet) fprintf(stderr, "error: module exceeds 4096 source-file limit\n");
      return 1;
    }
    DynSource *items = realloc(out->items, (out->count + 1) * sizeof(*items));
    if (!items) {
      closedir(d);
      return 2;
    }
    out->items = items;
    DynSource *s = &out->items[out->count++];
    memset(s, 0, sizeof(*s));
    if (context)
      s->context = *context;
    s->path = dyn_path_join(dir, entry->d_name);
    if (!s->path) {
      closedir(d);
      return 2;
    }
    FILE *f = fopen(s->path, "rb");
    if (!f) {
      if (!quiet) fprintf(stderr, "error: cannot read '%s'\n", s->path);
      closedir(d);
      EARLIER(1);
      return 1;
    }
    if (fseek(f, 0, SEEK_END)) {
      fclose(f);
      closedir(d);
      EARLIER(1);
      return 1;
    }
    long size = ftell(f);
    if (size < 0 || fseek(f, 0, SEEK_SET)) {
      fclose(f);
      closedir(d);
      EARLIER(1);
      return 1;
    }
    if ((unsigned long)size > DYN_MAX_SOURCE_BYTES) {
      if (!quiet) fprintf(stderr, "error: source '%s' exceeds 64 MiB limit\n", s->path);
      fclose(f);
      closedir(d);
      EARLIER(1);
      return 1;
    }
    if (!dyn_work_step(&s->context, (uint64_t)size + 1)) {
      if (!quiet) dyn_diagnostic(&s->context, "error", s->path, 1, 1, 1, 1, "analysis work budget exceeded or cancelled");
      fclose(f); closedir(d); return 1;
    }
    s->text = malloc((size_t)size + 1);
    if (!s->text) {
      fclose(f);
      closedir(d);
      return 2;
    }
    s->length = fread(s->text, 1, (size_t)size, f);
    s->text[s->length] = 0;
    bool failed = s->length != (size_t)size || ferror(f);
    if (fclose(f))
      failed = true;
    if (!failed && !parallel && !dyn_source_prepare(s)) {
      closedir(d);
      return prepare_failure(s, quiet);
    }
    if (failed) {
      if (!quiet) fprintf(stderr, "error: cannot completely read '%s'\n", s->path);
      closedir(d);
      EARLIER(1);
      return 1;
    }
  }
  closedir(d);
  if (parallel) {
    int result = prepare_parallel(out, quiet);
    if (result) return result;
  }
#undef EARLIER
  if (out->count > 1)
    qsort(out->items, out->count, sizeof(*out->items), source_compare);
  return 0;
}
int dyn_sources_load(const DynContext *context, const char *dir,
                     DynSources *out) {
  int result = sources_load(context, dir, out, false);
  if (result)
    dyn_sources_free(out);
  return result;
}
int dyn_sources_load_quiet(const DynContext *context, const char *dir,
                           DynSources *out) {
  int result = sources_load(context, dir, out, true);
  if (result)
    dyn_sources_free(out);
  return result;
}
void dyn_sources_free(DynSources *sources) {
  for (size_t i = 0; i < sources->count; ++i)
    dyn_source_free(&sources->items[i]);
  free(sources->items);
  memset(sources, 0, sizeof(*sources));
}
/* Target filtering precedes parsing, including for files excluded from this
   target. Ignore comment and literal contents without requiring an otherwise
   valid AST. */
static const char *source_skip_trivia(const char *p) {
  for (;;) {
    while (isspace((unsigned char)*p))
      ++p;
    if (p[0] == '/' && p[1] == '/') {
      p += 2;
      while (*p && *p != '\n')
        ++p;
    } else if (p[0] == '/' && p[1] == '*') {
      p += 2;
      while (*p && !(p[0] == '*' && p[1] == '/'))
        ++p;
      if (*p)
        p += 2;
    } else
      return p;
  }
}
static const char *source_target_directive(const char *p) {
  while (*(p = source_skip_trivia(p))) {
    if (*p == '\"' || *p == '\'') {
      char quote = *p++;
      while (*p && *p != quote) {
        if (*p == '\\' && p[1])
          ++p;
        ++p;
      }
      if (*p)
        ++p;
    } else {
      if (!strncmp(p, "#target", 7) &&
          !(isalnum((unsigned char)p[7]) || p[7] == '_'))
        return p + 7;
      ++p;
    }
  }
  return NULL;
}
int dyn_source_target_enabled(const DynSource *s) {
  /* Most files have no target directive. The substring test is only a
     rejection fast path; the lexer below still excludes comments/literals. */
  if (!strstr(s->text, "#target")) return 1;
  const char *p = source_target_directive(s->text);
  if (!p)
    return 1;
  p = source_skip_trivia(p);
  if (*p != '(')
    return -1;
  ++p;
  while (*p && *p != ')') {
    p = source_skip_trivia(p);
    if (*p == ',')
      p = source_skip_trivia(p + 1);
    char key[32] = {0}, value[32] = {0};
    size_t k = 0, v = 0;
    while ((*p == '_' || isalnum((unsigned char)*p)) && k + 1 < sizeof(key))
      key[k++] = *p++;
    p = source_skip_trivia(p);
    if (*p++ != ':')
      return -1;
    p = source_skip_trivia(p);
    while ((*p == '_' || isalnum((unsigned char)*p)) && v + 1 < sizeof(value))
      value[v++] = *p++;
    const char *want =
        dyn_target_property(dyn_context_target(&s->context), key);
    if (!want)
      return -1;
    if (strcmp(value, want))
      return 0;
    p = source_skip_trivia(p);
  }
  return *p == ')' ? 1 : -1;
}
/* Whether byte lies in a module that has platform files but none for the
   current target. Every error inside such a module follows from that, so
   callers report it once per module. name receives the module, shortened to
   its import path for standard modules. Cached per thread: errors cluster. */
bool dyn_source_target_gap(const DynSource *s, size_t byte, char *name, size_t capacity) {
  const char *path = NULL;
  unsigned line = 0, column = 0;
  dyn_source_location(s, byte, &path, &line, &column);
  const char *slash = path ? strrchr(path, '/') : NULL;
  if (!slash || (size_t)(slash - path) >= 4096) return false;
  char directory[4096];
  memcpy(directory, path, (size_t)(slash - path));
  directory[slash - path] = 0;
  return dyn_module_target_gap(&s->context, directory, name, capacity);
}
bool dyn_module_target_gap(const DynContext *context, const char *directory, char *name, size_t capacity) {
  size_t length = strlen(directory);
  if (!length || length >= 4096) return false;
  static _Thread_local char cached[4096];
  static _Thread_local bool cached_gap;
  if (strcmp(cached, directory)) {
    memcpy(cached, directory, length + 1);
    DynSources sources = {0};
    size_t gated = 0, enabled = 0;
    if (!dyn_sources_load_quiet(context, cached, &sources)) {
      for (size_t i = 0; i < sources.count; ++i) {
        if (!source_target_directive(sources.items[i].text)) continue;
        ++gated;
        if (dyn_source_target_enabled(&sources.items[i]) == 1) ++enabled;
      }
      dyn_sources_free(&sources);
    }
    cached_gap = gated && !enabled;
  }
  if (!cached_gap) return false;
  const char *shown = strstr(cached, "/std/");
  shown = shown ? shown + 1 : cached;
  int n = snprintf(name, capacity, "%s", shown);
  return n > 0 && (size_t)n < capacity;
}
int dyn_sources_merge(const DynSources *sources, const char *module_name,
                      DynSource *out) {
  static const char reflection_prelude[] =
      "enum TypeKind { Invalid, Void, Bool, Integer, Float, Pointer, Array, "
      "Slice, Struct, Enum, Function }\n"
      "struct TypeMember { name: []const u8, type_id: u64 }\n"
      "struct TypeInfo { id: u64, kind: "
      "TypeKind, name: []const u8, size: usize, alignment: usize, "
      "element_id: u64, length: usize, member_count: usize, "
      "parameter_count: usize, result_id: u64, fields: []const TypeMember, "
      "variants: []const TypeMember, arguments: []const TypeMember }\n";
  memset(out, 0, sizeof(*out));
  if (sources->count)
    out->context = sources->items[0].context;
  size_t total = 0;
  bool reflection = false;
  for (size_t i = 0; i < sources->count; ++i) {
    int enabled = dyn_source_target_enabled(&sources->items[i]);
    if (enabled < 0) {
      fprintf(stderr, "%s: error: invalid or unknown #target condition\n",
              sources->items[i].path);
      return 1;
    }
    if (!enabled)
      continue;
    reflection |= sources->items[i].needs_reflection;
    if (!reflection && !dyn_source_reflection(&sources->items[i], &reflection)) return 2;
    if (SIZE_MAX - total < sources->items[i].length + 1)
      return 2;
    total += sources->items[i].length + 1;
    if (total > DYN_MAX_MODULE_BYTES) {
      fprintf(stderr, "error: merged module exceeds 256 MiB limit\n");
      return 1;
    }
  }
  size_t prelude = reflection ? sizeof(reflection_prelude) - 1 : 0;
  if (SIZE_MAX - total < prelude)
    return 2;
  total += prelude;
  out->text = malloc(total + 1);
  out->path = strdup(module_name ? module_name : "<module>");
  out->maps = calloc(sources->count, sizeof(*out->maps));
  if (!out->text || !out->path || (sources->count && !out->maps)) {
    dyn_source_free(out);
    return 2;
  }
  size_t at = 0;
  if (prelude) {
    if (reflection) {
      memcpy(out->text + at, reflection_prelude,
             sizeof(reflection_prelude) - 1);
      at += sizeof(reflection_prelude) - 1;
    }
  }
  for (size_t i = 0; i < sources->count; ++i) {
    if (!dyn_source_target_enabled(&sources->items[i]))
      continue;
    const DynSource *input = &sources->items[i];
    DynSourceMap *map = &out->maps[out->map_count++];
    map->path = strdup(input->path);
    map->original_length =
        input->original_text ? input->original_length : input->length;
    map->original_text = malloc(map->original_length + 1);
    if (map->original_text) {
      memcpy(map->original_text, input->original_text ? input->original_text : input->text,
             map->original_length);
      map->original_text[map->original_length] = 0;
    }
    if (!map->path || !map->original_text) {
      dyn_source_free(out);
      return 2;
    }
    map->start = at;
    if (input->span_count) {
      map->spans = malloc(input->span_count * sizeof(*map->spans));
      if (!map->spans) {
        dyn_source_free(out);
        return 2;
      }
      memcpy(map->spans, input->spans, input->span_count * sizeof(*map->spans));
      map->span_count = input->span_count;
    }
    memcpy(out->text + at, sources->items[i].text, sources->items[i].length);
    at += sources->items[i].length;
    map->end = at;
    out->text[at++] = '\n';
  }
  out->text[at] = 0;
  out->length = at;
  /* No enabled source: certify the empty text directly. */
  if (!out->map_count && !prelude) {
    if (!dyn_source_prepare(out)) { dyn_source_free(out); return 2; }
    return 0;
  }
  /* Each enabled input keeps its own snapshot: concatenating files can change
     how imports or optional return types parse across a file boundary. */
  size_t count = (prelude ? 1 : 0) + out->map_count;
  out->compact_parts = calloc(count, sizeof(*out->compact_parts));
  if (!out->compact_parts) { dyn_source_free(out); return 2; }
  out->compact_only = out->compact_validated = true;
  if (prelude) {
    DynSource part = {.text = out->text, .length = prelude, .context = out->context};
    if (!dyn_source_prepare(&part) || !part.compact_validated) {
      exp_snapshot_release(part.compact); dyn_source_free(out); return 2;
    }
    out->compact_parts[out->syntax_part_count++] = part.compact;
    out->compact_root_start = part.compact_root_start;
    out->compact_root_end = part.compact_root_end;
  }
  for (size_t i = 0, map = 0; i < sources->count; ++i) {
    const DynSource *input = &sources->items[i];
    if (!dyn_source_target_enabled(input)) continue;
    size_t start = out->maps[map++].start;
    /* Synthetic inputs (interfaces) arrive as text only. */
    DynSource part = {.text = input->text, .length = input->length, .context = input->context,
                      .compact = input->compact};
    if (part.compact ? !exp_snapshot_retain(part.compact) : false) {
      dyn_source_free(out); return 2;
    }
    if (!dyn_source_prepare(&part)) {
      exp_snapshot_release(part.compact); dyn_source_free(out); return 2;
    }
    if (!out->syntax_part_count) {
      out->compact_root_start = (uint32_t)start + part.compact_root_start;
      out->compact_root_end = (uint32_t)start + part.compact_root_end;
    }
    out->compact_validated &= part.compact_validated;
    out->compact_only = out->compact_validated;
    out->compact_parts[out->syntax_part_count++] = part.compact;
  }
  return 0;
}
/* Original offset of local inside the first span containing it, if any.
   Spans ascend and meet only at their ends. */
static bool source_span_offset(const DynSourceSpan *spans, size_t count, size_t local, size_t *offset) {
  size_t lo = 0, hi = count;
  while (lo < hi) {
    size_t mid = lo + (hi - lo) / 2;
    if (spans[mid].generated_end < local) lo = mid + 1; else hi = mid;
  }
  if (lo == count || local < spans[lo].generated_start) return false;
  DynSourceSpan p = spans[lo];
  size_t gn = p.generated_end - p.generated_start, on = p.original_end - p.original_start;
  *offset = p.original_start + (gn ? (local - p.generated_start) * on / gn : 0);
  return true;
}
void dyn_source_position(const DynSource *s, size_t byte, const char **path,
                         const char **original, size_t *original_length, size_t *original_offset) {
  const char *text = s->original_text ? s->original_text : s->text;
  size_t length = s->original_text ? s->original_length : s->length,
         offset = byte;
  *path = s->path;
  /* Maps ascend and meet only at their ends: the first with end >= byte is
     the only candidate. */
  size_t lo = 0, hi = s->map_count;
  while (lo < hi) {
    size_t mid = lo + (hi - lo) / 2;
    if (s->maps[mid].end < byte) lo = mid + 1; else hi = mid;
  }
  if (lo < s->map_count && byte >= s->maps[lo].start) {
    const DynSourceMap *m = &s->maps[lo];
    *path = m->path;
    text = m->original_text;
    length = m->original_length;
    offset = byte - m->start;
    source_span_offset(m->spans, m->span_count, byte - m->start, &offset);
  }
  if (!s->map_count && s->span_count) source_span_offset(s->spans, s->span_count, byte, &offset);
  *original = text; *original_length = length; *original_offset = offset;
}
void dyn_source_location(const DynSource *s, size_t byte, const char **path,
                         unsigned *line, unsigned *column) {
  const char *text;
  size_t length, offset;
  dyn_source_position(s, byte, path, &text, &length, &offset);
  if (offset > length)
    offset = length;
  /* Columns count bytes after the last newline before offset. */
  unsigned lines = 1;
  const char *start = text, *end = text + offset, *newline;
  while (start < end && (newline = memchr(start, '\n', (size_t)(end - start)))) {
    ++lines;
    start = newline + 1;
  }
  *line = lines;
  *column = (unsigned)(end - start) + 1;
}
void dyn_source_free(DynSource *s) {
  dyn_source_discard_syntax(s);
  if (s->compact_parts) {
    for (size_t i = 0; i < s->syntax_part_count; ++i)
      exp_snapshot_release(s->compact_parts[i]);
    free(s->compact_parts);
  }
  free(s->path);
  free(s->text);
  free(s->original_text);
  free(s->spans);
  free(s->dependency_sources);
  for (size_t i = 0; i < s->map_count; ++i) {
    free(s->maps[i].path);
    free(s->maps[i].original_text);
    free(s->maps[i].spans);
  }
  free(s->maps);
  memset(s, 0, sizeof(*s));
}
