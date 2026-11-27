#define _XOPEN_SOURCE 700
#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include "dyn_compact.h"
#include "ir.h"
#include "ir_dump.h"
#include "frontend.h"
#include "native_opt.h"
#include "native_cpu.h"
#include "native_asm.h"
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#if defined(__GLIBC__)
#include <malloc.h>
#endif
#ifndef DYN_VERSION
#define DYN_VERSION "0.1.0-dev"
#endif

extern char *realpath(const char *, char *);
static bool native_link_matches(const char *path, const char *name) {
  const char *base = strrchr(path, '/');
  base = base ? base + 1 : path;
  size_t name_length = strlen(name), base_length = strlen(base);
  if (base_length < 3 + name_length || strncmp(base, "lib", 3) || memcmp(base + 3, name, name_length)) return false;
  const char *suffix = base + 3 + name_length;
  return !strcmp(suffix, ".so") || !strncmp(suffix, ".so.", 4) || !strcmp(suffix, ".dylib") || !strcmp(suffix, ".dll.a");
}
static char *native_link_in_directory(const DynContext *context, const char *directory, const char *name) {
  const char *format = !strcmp(dyn_context_target(context)->kernel, "darwin") ? "lib%s.dylib" : !strcmp(dyn_context_target(context)->kernel, "windows") ? "lib%s.dll.a" : "lib%s.so";
  char filename[160], candidate[4096];
  if (snprintf(filename, sizeof(filename), format, name) >= (int)sizeof(filename) || snprintf(candidate, sizeof(candidate), "%s/%s", directory, filename) >= (int)sizeof(candidate)) return NULL;
  char *resolved = realpath(candidate, NULL);
  if (resolved) return resolved;
  if (strcmp(dyn_context_target(context)->kernel, "linux")) return NULL;
  DIR *entries = opendir(directory);
  if (!entries) return NULL;
  size_t prefix = strlen(filename);
  struct dirent *entry;
  while ((entry = readdir(entries))) {
    if (strncmp(entry->d_name, filename, prefix) || entry->d_name[prefix] != '.') continue;
    if (snprintf(candidate, sizeof(candidate), "%s/%s", directory, entry->d_name) >= (int)sizeof(candidate)) continue;
    resolved = realpath(candidate, NULL);
    if (resolved) break;
  }
  closedir(entries);
  return resolved;
}
static char *find_native_link(const DynContext *context, const char *name) {
  const char *configured = getenv("DYN_LIBRARY_PATH");
  if (configured && *configured) {
    const char *at = configured;
    while (*at) {
      const char *end = strchr(at, DYN_PATH_SEPARATOR);
      if (!end) end = at + strlen(at);
      if (end > at && (size_t)(end - at) < 4096) {
        char directory[4096];
        memcpy(directory, at, (size_t)(end - at));
        directory[end - at] = 0;
        char *found = native_link_in_directory(context, directory, name);
        if (found) return found;
      }
      at = *end ? end + 1 : end;
    }
  }
  /* Prefer our supported libSystem ABI metadata; fall back to the target SDK. */
  if (!strcmp(dyn_context_target(context)->kernel, "darwin") && !strcmp(name, "System")) {
    char stub[4096];
    if (dyn_host_runtime_file("libSystem.tbd", stub, sizeof(stub))) return strdup(stub);
    return strdup("-lSystem");
  }
  static const char *directories[] = {
      "/usr/lib",
      "/usr/local/lib",
      "/lib",
      "/usr/lib/x86_64-linux-gnu",
      "/lib/x86_64-linux-gnu",
      "/usr/lib/riscv64-linux-gnu",
      "/lib/riscv64-linux-gnu",
      "/usr/lib/aarch64-linux-gnu",
      "/lib/aarch64-linux-gnu",
      "/opt/homebrew/lib",
      "/usr/local/opt/lib",
  };
  for (size_t i = 0; i < sizeof(directories) / sizeof(directories[0]); ++i) {
    char *found = native_link_in_directory(context, directories[i], name);
    if (found) return found;
  }
  return NULL;
}

static int add_source_native_links(const DynContext *context, const DynSources *sources, DynOptions *options) {
  char names[32][128];
  size_t name_count = 0;
  for (size_t i = 0; i < sources->count; ++i) {
    if (dyn_source_target_enabled(&sources->items[i]) == 0) continue;
    const ExpSnapshotTree *compact = dyn_compact_tree(&sources->items[i]);
    if (!compact) return 2;
    for (uint32_t id = compact->nodes[compact->root].first; id != UINT32_MAX; id = compact->nodes[id].next) {
      if (!dyn_work_step(&sources->items[i].context, 1)) return 2;
      if (compact->nodes[id].kind != SRC_LINK) continue;
      uint32_t value = dyn_compact_field(compact, id, EXP_ROLE_LIBRARY);
      if (value == UINT32_MAX) return 2;
      uint32_t start = compact->nodes[value].start, end = compact->nodes[value].end;
      if (end <= start + 2 || end - start - 2 >= sizeof(names[0])) {
        fprintf(stderr, "error: invalid #link library in %s\n", sources->items[i].path);
        return 1;
      }
      char name[128];
      size_t length = (size_t)(end - start - 2);
      memcpy(name, sources->items[i].text + start + 1, length);
      name[length] = 0;
      for (size_t byte = 0; byte < length; ++byte)
        if (!(name[byte] == '_' || name[byte] == '-' || name[byte] == '.' || (name[byte] >= '0' && name[byte] <= '9') || (name[byte] >= 'A' && name[byte] <= 'Z') || (name[byte] >= 'a' && name[byte] <= 'z'))) {
          fprintf(stderr, "error: invalid #link library '%s' in %s\n", name, sources->items[i].path);
          return 1;
        }
      bool duplicate = false;
      for (size_t j = 0; j < name_count; ++j)
        if (!strcmp(names[j], name)) {
          duplicate = true;
          break;
        }
      if (!duplicate) {
        if (name_count == 32) {
          fprintf(stderr, "error: too many native libraries\n");
          return 2;
        }
        strcpy(names[name_count++], name);
      }
    }
  }
  for (size_t i = 0; i < name_count; ++i) {
    bool supplied = false;
    for (size_t j = 0; j < options->link_input_count; ++j)
      if (native_link_matches(options->link_inputs[j], names[i])) {
        supplied = true;
        break;
      }
    if (supplied) continue;
    char *library = find_native_link(context, names[i]);
    if (!library) {
      fprintf(stderr, "error: package requires native library '%s' for %s; install " "its development package, set DYN_LIBRARY_PATH, or pass --link\n", names[i], dyn_context_target(context)->kernel);
      return 1;
    }
    if (options->link_input_count == 64) {
      free(library);
      fprintf(stderr, "error: at most 64 native link inputs are supported\n");
      return 2;
    }
    options->link_inputs[options->link_input_count++] = library;
  }
  return 0;
}
static double elapsed_ms(struct timespec start) {
  struct timespec end;
  clock_gettime(CLOCK_MONOTONIC, &end);
  return (double)(end.tv_sec - start.tv_sec) * 1000.0 + (double)(end.tv_nsec - start.tv_nsec) / 1000000.0;
}
static struct timespec timer_start(void) {
  struct timespec value;
  clock_gettime(CLOCK_MONOTONIC, &value);
  return value;
}
/* Every supported target uses independent emission. */
/* Release builds consume the input IR's expressions and statements. */
static int emit_native(const DynSource *source, DynIrProgram *input, const char *object, const char *asm_path, const DynOptions *options) {
  const DynIrProgram *ir = input;
  bool report = true;
  struct timespec phase = timer_start();
  DynNativeOptimization optimized = {0};
  if (options->release) {
    unsigned level = options->optimization.level ? options->optimization.level : 2;
    if (!dyn_native_optimize_owned(source, input, level, !options->debug_info, &optimized)) return 2;
    ir = &optimized.ir;
  }
  int result = !strcmp(dyn_context_target(&source->context)->arch, "wasm32") ? dyn_wasm_object(source, ir, object, report) : dyn_native_object(source, ir, object, !options->release, options->debug_info, options->shared, report);
  if (!result && asm_path)
    result = !strcmp(dyn_context_target(&source->context)->arch, "wasm32") ? dyn_wasm_assembly(source, ir, asm_path, report) : dyn_native_assembly(object, asm_path);
  if (options->release) dyn_native_optimization_free(&optimized);
  if (options->timings) fprintf(stderr, "timing detail native emit %.3f ms\n", elapsed_ms(phase));
  return result;
}

#if defined(__SANITIZE_ADDRESS__)
#define DYN_SANITIZED 1
#elif defined(__has_feature)
#if __has_feature(address_sanitizer)
#define DYN_SANITIZED 1
#endif
#endif
#ifndef DYN_SANITIZED
#define DYN_SANITIZED 0
#endif

static bool is_command(const DynOptions *o, const char *s) {
  return strcmp(o->command, s) == 0;
}
static int emit_ir_dump(const DynSources *sources, const char *main_path,
                        const DynOptions *options) {
  DynSource merged = {0};
  int result = dyn_sources_merge(sources, main_path, &merged);
  if (result) return result;
  DynAstProgram ast = {0};
  DynIrProgram ir = {0};
  DynAnalysisResult analyzed = dyn_analyze(&merged, &ast,
      (DynAnalysisOptions){.main_path = main_path, .require_main = !options->shared});
  if (!analyzed.checked) result = 1;
  else if (!dyn_ir_lower_structural(&ast, &merged, &ir)) {
    fprintf(stderr, "error: failed to lower structural Dyn IR\n");
    result = 2;
  }
  dyn_ast_program_free(&ast);
  if (!result && !options->output) {
    result = dyn_ir_dump(stdout, &ir, dyn_context_target(&merged.context));
    if (fflush(stdout) || ferror(stdout)) result = 2;
  } else if (!result) {
    size_t length = strlen(options->output);
    char *temporary = length <= SIZE_MAX - 12 ? malloc(length + 12) : NULL;
    if (!temporary) result = 2;
    else {
      memcpy(temporary, options->output, length);
      memcpy(temporary + length, ".tmp.XXXXXX", 12);
      int descriptor = mkstemp(temporary);
      if (descriptor < 0) result = 2;
      else {
        FILE *stream = fdopen(descriptor, "wb");
        if (!stream) { close(descriptor); result = 2; }
        else {
          result = dyn_ir_dump(stream, &ir, dyn_context_target(&merged.context));
          if (fflush(stream) || ferror(stream)) result = 2;
          if (fclose(stream)) result = 2;
        }
        if (!result && rename(temporary, options->output)) result = 2;
        if (result) remove(temporary);
      }
      free(temporary);
    }
  }
  if (result == 2) fprintf(stderr, "error: failed to write Dyn IR dump\n");
  dyn_ir_free(&ir);
  dyn_source_free(&merged);
  return result;
}
/* A lone source file is a module of one file: its directory, with only
   that file loaded and standing for main.dyn. */
static char single_file_directory[4096], single_file_output[4096];
static const char *single_file_name;
static bool single_file_module(DynOptions *options) {
  size_t length = strlen(options->input);
  if (length < 5 || strcmp(options->input + length - 4, ".dyn")) return false;
  FILE *f = fopen(options->input, "rb");
  if (!f) return false;
  fclose(f);
  const char *slash = strrchr(options->input, '/');
#ifdef _WIN32
  const char *back = strrchr(options->input, '\\');
  if (back && (!slash || back > slash)) slash = back;
#endif
  const char *name = slash ? slash + 1 : options->input;
  if (slash) snprintf(single_file_directory, sizeof(single_file_directory), "%.*s", (int)(slash - options->input), options->input);
  else snprintf(single_file_directory, sizeof(single_file_directory), ".");
  if (!single_file_directory[0]) snprintf(single_file_directory, sizeof(single_file_directory), "/");
  /* `dyn build hello.dyn` writes ./hello, as for a directory named hello. */
  if (!options->output) {
    snprintf(single_file_output, sizeof(single_file_output), "%.*s", (int)(strlen(name) - 4), name);
    options->output = single_file_output;
  }
  single_file_name = name;
  dyn_sources_single_file(single_file_directory, name);
  options->input = single_file_directory;
  return true;
}
static void silent_diagnostic(const char *severity, const char *path, unsigned line, unsigned column,
                              unsigned end_line, unsigned end_column, const char *message, void *data) {
  (void)severity; (void)path; (void)line; (void)column; (void)end_line; (void)end_column; (void)message; (void)data;
}
static int execute_command(DynOptions *options, const char *compiler);

/* `dyn fix`: the certain fixes `dyn check` reports, collected and applied. */
typedef struct FixEdit {
  char *path, *replacement;
  size_t offset, length;
} FixEdit;
typedef struct FixEdits {
  FixEdit *items;
  size_t count, capacity;
  const char *root; /* Only files under this real directory change. */
  bool failed;
} FixEdits;
static void fix_collect(const DynFixReport *fix, void *data) {
  FixEdits *edits = data;
  const char *path = fix->path, *replacement = fix->replacement;
  size_t offset = fix->offset, length = fix->length;
  if (!fix->certain || !path || edits->failed) return;
  char *real = realpath(path, NULL);
  size_t root = strlen(edits->root);
  if (!real || strncmp(real, edits->root, root) || (real[root] != '/' && real[root] != '\\' && real[root])) {
    free(real);
    return;
  }
  for (size_t i = 0; i < edits->count; ++i)
    if (!strcmp(edits->items[i].path, real) && edits->items[i].offset == offset) {
      free(real);
      return;
    }
  if (edits->count == edits->capacity) {
    size_t capacity = edits->capacity ? 2 * edits->capacity : 32;
    FixEdit *grown = realloc(edits->items, capacity * sizeof(*grown));
    if (!grown) { free(real); edits->failed = true; return; }
    edits->items = grown;
    edits->capacity = capacity;
  }
  char *text = strdup(replacement);
  if (!text) { free(real); edits->failed = true; return; }
  edits->items[edits->count++] = (FixEdit){real, text, offset, length};
}
static int fix_order(const void *left, const void *right) {
  const FixEdit *a = left, *b = right;
  int path = strcmp(a->path, b->path);
  if (path) return path;
  return a->offset < b->offset ? 1 : a->offset > b->offset ? -1 : 0;
}
/* Applies the edits of one file, last first so earlier offsets hold. An
   edit that overlaps one already applied waits for the next pass. */
static size_t fix_file(const FixEdit *edits, size_t count) {
  FILE *in = fopen(edits[0].path, "rb");
  if (!in) return 0;
  char *text = NULL;
  size_t length = 0, capacity = 0;
  for (;;) {
    if (length == capacity) {
      capacity = capacity ? 2 * capacity : 65536;
      char *grown = realloc(text, capacity);
      if (!grown) { free(text); fclose(in); return 0; }
      text = grown;
    }
    size_t got = fread(text + length, 1, capacity - length, in);
    length += got;
    if (!got) break;
  }
  fclose(in);
  size_t applied = 0, limit = length;
  for (size_t i = 0; i < count; ++i) {
    const FixEdit *e = &edits[i];
    if (e->offset > length || e->length > length - e->offset || e->offset + e->length > limit) continue;
    size_t extra = strlen(e->replacement);
    char *next = malloc(length - e->length + extra + 1);
    if (!next) break;
    memcpy(next, text, e->offset);
    memcpy(next + e->offset, e->replacement, extra);
    memcpy(next + e->offset + extra, text + e->offset + e->length, length - e->offset - e->length);
    length = length - e->length + extra;
    free(text);
    text = next;
    limit = e->offset;
    ++applied;
  }
  if (applied) {
    size_t path_length = strlen(edits[0].path);
    char *temporary = malloc(path_length + 16);
    FILE *out = temporary ? (snprintf(temporary, path_length + 16, "%s.dyn-fix", edits[0].path), fopen(temporary, "wb")) : NULL;
    bool written = out && fwrite(text, 1, length, out) == length;
    if (out && fclose(out)) written = false;
#ifdef _WIN32
    /* rename does not replace an existing file on Windows. */
    if (written) remove(edits[0].path);
#endif
    if (!written || rename(temporary, edits[0].path)) {
      if (temporary) remove(temporary);
      fprintf(stderr, "error: cannot write %s\n", edits[0].path);
      applied = 0;
    }
    free(temporary);
  }
  free(text);
  return applied;
}
static int fix_command(DynOptions *options, const char *compiler) {
  if (!options->input || !dyn_path_is_directory(options->input)) {
    fprintf(stderr, "error: fix requires a module directory\n");
    return 2;
  }
  char *root = realpath(options->input, NULL);
  if (!root) { fprintf(stderr, "error: cannot resolve %s\n", options->input); return 2; }
  size_t total = 0;
  for (unsigned pass = 0; pass < 16; ++pass) {
    FixEdits edits = {.root = root};
    DynOptions check = *options;
    check.command = "check";
    check.fix_pass = true;
    check.no_cache = true;
    dyn_diagnostic_fix_sink(fix_collect, &edits);
    (void)execute_command(&check, compiler);
    dyn_diagnostic_fix_sink(NULL, NULL);
    size_t applied = 0;
    if (!edits.failed && edits.count) {
      qsort(edits.items, edits.count, sizeof(*edits.items), fix_order);
      for (size_t first = 0; first < edits.count;) {
        size_t last = first + 1;
        while (last < edits.count && !strcmp(edits.items[last].path, edits.items[first].path)) ++last;
        size_t done = fix_file(edits.items + first, last - first);
        if (done && !options->quiet) printf("fixed %zu in %s\n", done, edits.items[first].path);
        applied += done;
        first = last;
      }
    }
    for (size_t i = 0; i < edits.count; ++i) { free(edits.items[i].path); free(edits.items[i].replacement); }
    free(edits.items);
    total += applied;
    if (!applied) break;
  }
  free(root);
  if (!options->quiet) printf("%zu fixes applied\n", total);
  /* What is left needs a person: report it as check would. */
  DynOptions check = *options;
  check.command = "check";
  return execute_command(&check, compiler);
}
static bool strbuf_append(char **buf, size_t *len, size_t *cap, const char *text) {
  size_t add = strlen(text);
  if (*len + add + 1 > *cap) {
    size_t next = *cap ? *cap * 2 : 1024;
    while (next < *len + add + 1) next *= 2;
    char *grown = realloc(*buf, next);
    if (!grown) return false;
    *buf = grown;
    *cap = next;
  }
  memcpy(*buf + *len, text, add);
  *len += add;
  (*buf)[*len] = 0;
  return true;
}

typedef struct {
  char name[256];
  bool is_fallible;
} HarnessTarget;

static bool harness_discover_and_append(const DynContext *context, DynSources *sources,
                                        const DynOptions *options, const char *input_dir,
                                        bool is_test, bool is_bench, bool is_fuzz,
                                        size_t *found_count) {
  const char *prefix = is_test ? "test_" : is_bench ? "bench_" : "fuzz_";
  size_t prefix_len = strlen(prefix);
  HarnessTarget *targets = NULL;
  size_t target_count = 0, target_cap = 0;
  for (size_t i = 0; i < sources->count; ++i) {
    DynSource *src = &sources->items[i];
    if (dyn_source_target_enabled(src) == 0) continue;
    const ExpSnapshotTree *tree = dyn_compact_tree(src);
    if (!tree || tree->root == UINT32_MAX) continue;
    bool renamed_main = false;
    uint32_t main_start = 0;
    for (uint32_t d = tree->nodes[tree->root].first; d != UINT32_MAX; d = tree->nodes[d].next) {
      if (tree->nodes[d].kind != SRC_DECLARATION) continue;
      uint32_t fn = tree->nodes[d].first;
      if (fn == UINT32_MAX || tree->nodes[fn].kind != SRC_FN) continue;
      uint32_t name_node = tree->nodes[fn].first;
      if (name_node == UINT32_MAX || tree->nodes[name_node].kind != EXP_NAME) continue;
      uint32_t ns = tree->nodes[name_node].start, ne = tree->nodes[name_node].end;
      size_t nlen = ne - ns;
      if (nlen == 4 && !memcmp(src->text + ns, "main", 4)) {
        renamed_main = true;
        main_start = ns;
        continue;
      }
      if (nlen <= prefix_len || nlen >= 255 || memcmp(src->text + ns, prefix, prefix_len) != 0)
        continue;
      uint32_t param_count = 0;
      bool is_generic = false, is_fallible = false, has_nonvoid_ret = false;
      for (uint32_t c = tree->nodes[name_node].next; c != UINT32_MAX; c = tree->nodes[c].next) {
        uint16_t ck = tree->nodes[c].kind;
        if (ck == EXP_TYPE_PARAMETER) is_generic = true;
        else if (ck == SRC_FN_PARAM || ck == SRC_VARIADIC_PARAM) ++param_count;
        else if (ck == EXP_FALLIBLE_TYPE) {
          if (tree->nodes[c].flags & EXP_FALLIBLE_VOID) is_fallible = true;
          else has_nonvoid_ret = true;
        } else if (ck == EXP_TYPE) {
          uint32_t inner = tree->nodes[c].first;
          if (inner != UINT32_MAX && tree->nodes[inner].kind == EXP_FALLIBLE_TYPE &&
              (tree->nodes[inner].flags & EXP_FALLIBLE_VOID))
            is_fallible = true;
          else
            has_nonvoid_ret = true;
        }
      }
      if (is_generic || has_nonvoid_ret) continue;
      if ((is_test || is_bench) && param_count != 0) continue;
      if (is_fuzz && param_count != 1) continue;
      if ((is_bench || is_fuzz) && is_fallible) continue;
      char fname[256];
      memcpy(fname, src->text + ns, nlen);
      fname[nlen] = 0;
      if (options->filter && !strstr(fname, options->filter)) continue;
      if (target_count == target_cap) {
        size_t nc = target_cap ? target_cap * 2 : 16;
        HarnessTarget *grown = realloc(targets, nc * sizeof(*grown));
        if (!grown) { free(targets); return false; }
        targets = grown;
        target_cap = nc;
      }
      strcpy(targets[target_count].name, fname);
      targets[target_count].is_fallible = is_fallible;
      ++target_count;
    }
    if (renamed_main) {
      memcpy(src->text + main_start, "_m_n", 4);
      dyn_source_prepare(src);
    }
  }
  *found_count = target_count;
  if (!target_count) {
    free(targets);
    return true;
  }
  char *code = NULL;
  size_t len = 0, cap = 0;
  bool ok = strbuf_append(&code, &len, &cap,
                          "use __dyn_io \"std/io\"\n"
                          "use __dyn_fmt \"std/fmt\"\n");
  if (is_bench)
    ok = ok && strbuf_append(&code, &len, &cap, "use __dyn_time \"std/time\"\n");
  ok = ok && strbuf_append(&code, &len, &cap,
                           "fn main() {\n"
                           "  __dyn_buf: [1024]u8\n");
  if (is_test) {
    ok = ok && strbuf_append(&code, &len, &cap,
                             "  __dyn_passed: u64 = 0\n"
                             "  __dyn_failed: u64 = 0\n");
    for (size_t i = 0; ok && i < target_count; ++i) {
      char line[2048];
      if (targets[i].is_fallible) {
        snprintf(line, sizeof(line),
                 "  __dyn_ok_%zu := true\n"
                 "  %s() catch { __dyn_ok_%zu = false }\n"
                 "  if __dyn_ok_%zu {\n"
                 "    __dyn_passed += 1\n"
                 "    __dyn_io.println(\"PASS %s\")\n"
                 "  } else {\n"
                 "    __dyn_failed += 1\n"
                 "    __dyn_io.println(\"FAIL %s\")\n"
                 "  }\n",
                 i, targets[i].name, i, i, targets[i].name, targets[i].name);
      } else {
        snprintf(line, sizeof(line),
                 "  %s()\n"
                 "  __dyn_passed += 1\n"
                 "  __dyn_io.println(\"PASS %s\")\n",
                 targets[i].name, targets[i].name);
      }
      ok = strbuf_append(&code, &len, &cap, line);
    }
    ok = ok && strbuf_append(&code, &len, &cap,
                             "  __dyn_out := __dyn_fmt.buffer(__dyn_buf[..])\n"
                             "  if __dyn_failed == 0 {\n"
                             "    __dyn_fmt.write(&__dyn_out, \"test result: ok. \")\n"
                             "  } else {\n"
                             "    __dyn_fmt.write(&__dyn_out, \"test result: FAILED. \")\n"
                             "  }\n"
                             "  __dyn_fmt.write_u64(&__dyn_out, __dyn_passed)\n"
                             "  __dyn_fmt.write(&__dyn_out, \" passed; \")\n"
                             "  __dyn_fmt.write_u64(&__dyn_out, __dyn_failed)\n"
                             "  __dyn_fmt.write(&__dyn_out, \" failed\")\n"
                             "  __dyn_io.println(__dyn_fmt.bytes(&__dyn_out))\n"
                             "  if __dyn_failed != 0 { #panic(\"tests failed\") }\n");
  } else if (is_bench) {
    unsigned long long iters = options->iterations ? (unsigned long long)options->iterations : 1000ULL;
    char hdr[256];
    snprintf(hdr, sizeof(hdr), "  __dyn_iters: u64 = %llu\n  __dyn_samples: [11]i64\n", iters);
    ok = ok && strbuf_append(&code, &len, &cap, hdr);
    for (size_t i = 0; ok && i < target_count; ++i) {
      char blk[4096];
      snprintf(blk, sizeof(blk),
               "  for __dyn_w in 0..10 { %s() }\n"
               "  for __dyn_s in 0..11 {\n"
               "    __dyn_t0 := __dyn_time.monotonic_now()\n"
               "    __dyn_k: u64 = 0\n"
               "    for __dyn_k < __dyn_iters { %s()\n __dyn_k += 1 }\n"
               "    __dyn_t1 := __dyn_time.monotonic_now()\n"
               "    __dyn_dt := __dyn_time.elapsed(__dyn_t0, __dyn_t1)\n"
               "    if __dyn_dt < 0 { __dyn_dt = 0 }\n"
               "    __dyn_samples[__dyn_s] = __dyn_dt / #cast(i64, __dyn_iters)\n"
               "  }\n"
               "  for __dyn_a in 0..11 {\n"
               "    for __dyn_b in __dyn_a + 1..11 {\n"
               "      if __dyn_samples[__dyn_b] < __dyn_samples[__dyn_a] {\n"
               "        __dyn_tmp := __dyn_samples[__dyn_a]\n"
               "        __dyn_samples[__dyn_a] = __dyn_samples[__dyn_b]\n"
               "        __dyn_samples[__dyn_b] = __dyn_tmp\n"
               "      }\n"
               "    }\n"
               "  }\n"
               "  __dyn_bo_%zu := __dyn_fmt.buffer(__dyn_buf[..])\n"
               "  __dyn_fmt.write(&__dyn_bo_%zu, \"BENCH %s: iters=\")\n"
               "  __dyn_fmt.write_u64(&__dyn_bo_%zu, __dyn_iters)\n"
               "  __dyn_fmt.write(&__dyn_bo_%zu, \" median=\")\n"
               "  __dyn_fmt.write_i64(&__dyn_bo_%zu, __dyn_samples[5])\n"
               "  __dyn_fmt.write(&__dyn_bo_%zu, \" ns/op p95=\")\n"
               "  __dyn_fmt.write_i64(&__dyn_bo_%zu, __dyn_samples[10])\n"
               "  __dyn_fmt.write(&__dyn_bo_%zu, \" ns/op\")\n"
               "  __dyn_io.println(__dyn_fmt.bytes(&__dyn_bo_%zu))\n",
               targets[i].name, targets[i].name,
               i, i, targets[i].name, i, i, i, i, i, i, i);
      ok = strbuf_append(&code, &len, &cap, blk);
    }
  } else {
    unsigned long long iters = options->iterations ? (unsigned long long)options->iterations : 1000ULL;
    char hdr[256];
    snprintf(hdr, sizeof(hdr),
             "  __dyn_iters: u64 = %llu\n"
             "  __dyn_seed: u64 = 0x9e3779b97f4a7c15\n"
             "  __dyn_fbuf: [256]u8\n",
             iters);
    ok = ok && strbuf_append(&code, &len, &cap, hdr);
    for (size_t i = 0; ok && i < target_count; ++i) {
      char blk[4096];
      snprintf(blk, sizeof(blk),
               "  __dyn_k_%zu: u64 = 0\n"
               "  for __dyn_k_%zu < __dyn_iters {\n"
               "    __dyn_seed ^= __dyn_seed << 13\n"
               "    __dyn_seed ^= __dyn_seed >> 7\n"
               "    __dyn_seed ^= __dyn_seed << 17\n"
               "    __dyn_flen: usize = 0\n"
               "    if __dyn_k_%zu == 0 {\n"
               "      __dyn_flen = 0\n"
               "    } else if __dyn_k_%zu == 1 {\n"
               "      __dyn_flen = 1\n"
               "      __dyn_fbuf[0] = 0\n"
               "    } else if __dyn_k_%zu == 2 {\n"
               "      __dyn_flen = 1\n"
               "      __dyn_fbuf[0] = 255\n"
               "    } else {\n"
               "      __dyn_flen = #cast(usize, __dyn_seed & 63)\n"
               "      for __dyn_j in 0..__dyn_flen {\n"
               "        __dyn_seed ^= __dyn_seed << 13\n"
               "        __dyn_seed ^= __dyn_seed >> 7\n"
               "        __dyn_seed ^= __dyn_seed << 17\n"
               "        __dyn_fbuf[__dyn_j] = #cast(u8, __dyn_seed & 255)\n"
               "      }\n"
               "    }\n"
               "    %s(__dyn_fbuf[..__dyn_flen])\n"
               "    __dyn_k_%zu += 1\n"
               "  }\n"
               "  __dyn_fo_%zu := __dyn_fmt.buffer(__dyn_buf[..])\n"
               "  __dyn_fmt.write(&__dyn_fo_%zu, \"FUZZ %s: OK (\")\n"
               "  __dyn_fmt.write_u64(&__dyn_fo_%zu, __dyn_iters)\n"
               "  __dyn_fmt.write(&__dyn_fo_%zu, \" iterations)\")\n"
               "  __dyn_io.println(__dyn_fmt.bytes(&__dyn_fo_%zu))\n",
               i, i, i, i, i, targets[i].name, i,
               i, i, targets[i].name, i, i, i);
      ok = strbuf_append(&code, &len, &cap, blk);
    }
  }
  ok = ok && strbuf_append(&code, &len, &cap, "}\n");
  free(targets);
  if (!ok) { free(code); return false; }
  char *hpath = dyn_path_join(input_dir, "__dyn_harness.dyn");
  if (!hpath) { free(code); return false; }
  DynSource *grown = realloc(sources->items, (sources->count + 1) * sizeof(*grown));
  if (!grown) { free(hpath); free(code); return false; }
  sources->items = grown;
  DynSource hs = {0};
  hs.path = hpath;
  hs.text = code;
  hs.length = len;
  hs.context = *context;
  dyn_source_target_record(&hs);
  if (!dyn_source_prepare(&hs)) {
    dyn_source_free(&hs);
    return false;
  }
  sources->items[sources->count++] = hs;
  return true;
}

static int execute_command(DynOptions *options, const char *compiler) {
  DynWork work = {.remaining = options->max_work};
  unsigned vet_findings = 0;
  bool vet = is_command(options, "vet");
  DynVetCasts vet_casts = {0};
  DynContext context = {.diagnostic = options->fix_pass ? silent_diagnostic : NULL, .work = options->max_work ? &work : NULL, .target = dyn_target_find(options->target), .optimization = &options->optimization, .runtime_support = options->runtime_support, .json_diagnostics = options->json_diagnostics, .vet = vet, .vet_unsafe = options->vet_unsafe, .vet_findings = &vet_findings, .vet_casts = vet ? &vet_casts : NULL, .timings = options->timings, .strict_syntax = true};
  if (is_command(options, "help")) {
    dyn_cli_help(options->input);
    return 0;
  }
  if (is_command(options, "version")) {
    puts("dyn " DYN_VERSION);
    return 0;
  }
  if (is_command(options, "lsp")) {
    if (!context.target) { fprintf(stderr, "error: unknown LSP target '%s'\n", options->target); return 2; }
    return dyn_lsp(context.target);
  }
  if (is_command(options, "cache")) return dyn_cache_command(options->input);
  if (is_command(options, "guide")) return dyn_guide(options->input, options->guide_brief);
  if (is_command(options, "fmt") || is_command(options, "docs")) {
    char *sdk_path = NULL;
    bool available = options->input && (dyn_path_is_directory(options->input) || single_file_module(options));
    if (!available && is_command(options, "docs")) {
      sdk_path = dyn_module_resolve_sdk(options->input);
      if (sdk_path) {
        options->input = sdk_path;
        available = dyn_path_is_directory(options->input) || single_file_module(options);
      }
    }
    if (!available) {
      fprintf(stderr, "error: %s requires a module directory or a .dyn file\n", options->command);
      free(sdk_path);
      return 2;
    }
    int result = is_command(options, "fmt") ? dyn_format_directory(options->input, options->format_check) : dyn_docs_directory(options->input, options->docs_json);
    free(sdk_path);
    return result;
  }
  bool test_cmd = is_command(options, "test");
  bool bench_cmd = is_command(options, "bench");
  bool fuzz_cmd = is_command(options, "fuzz");
  bool harness_cmd = test_cmd || bench_cmd || fuzz_cmd;
  bool run = is_command(options, "run") || harness_cmd;
  if (harness_cmd) {
    if (!options->input) options->input = ".";
    if (bench_cmd && !options->release) {
      options->release = true;
      if (!options->debug_info_set) options->debug_info = false;
    }
    context.include_tests = true;
    options->no_cache = true;
    if (!options->verbose) options->quiet = true;
  }
  if (!is_command(options, "check") && !vet && !is_command(options, "build") && !is_command(options, "query") && !run) {
    fprintf(stderr, "error: command '%s' is not implemented\n", options->command);
    return 2;
  }
  if (!options->input) {
    fprintf(stderr, "error: %s requires a module directory\n", options->command);
    return 2;
  }
  if (run && options->no_link) {
    fprintf(stderr, "error: run cannot be combined with --no-link\n");
    return 2;
  }
  if (run && options->shared) {
    fprintf(stderr, "error: run cannot be combined with --shared\n");
    return 2;
  }
  if (options->shared && options->no_link && !options->emit_object) {
    fprintf(stderr, "error: --shared --no-link requires --emit-object\n");
    return 2;
  }
  if (!dyn_path_is_directory(options->input) && !single_file_module(options)) {
    fprintf(stderr, "error: input must be a module directory or a .dyn file: '%s'\n", options->input);
    return 2;
  }
  if (!context.target) {
    fprintf(stderr, "error: target '%s' is not implemented; supported targets: " "x86_64-linux, aarch64-linux, riscv64-linux, riscv64-none, riscv32-none, riscv32-none-soft, thumbv7em-none, thumbv7em-none-soft, thumbv7em-none-nucleo-h753zi, x86_64-macos, aarch64-macos, x86_64-windows, aarch64-windows, wasm32-browser, wasm32-wasi\n", options->target);
    return 2;
  }
  if (!options->emit_ir && !strcmp(context.target->kernel, "none") && (run || (options->shared && !options->no_link))) {
    fprintf(stderr, "error: bare-metal targets build static images only; run them under an emulator or on the board\n");
    return 2;
  }
  if (!options->emit_ir && !strcmp(context.target->arch, "wasm32") &&
      (run || (is_command(options, "build") &&
       ((!strcmp(context.target->kernel, "browser") && !options->shared) ||
        (!strcmp(context.target->kernel, "wasi") && options->shared))))) {
    fprintf(stderr, "error: Wasm requires an external host; browser builds require --shared, WASI commands forbid --shared\n");
    return 2;
  }
  bool native = (is_command(options, "build") || run) && !options->emit_ir;
  if (options->backend == DYN_BACKEND_LLVM) {
    fprintf(stderr, "error: LLVM backend was removed; use --backend native\n");
    return 2;
  }
  if (options->backend == DYN_BACKEND_NATIVE && !native) {
    fprintf(stderr, "error: --backend native requires build/run\n");
    return 2;
  }
  if (native) options->backend = DYN_BACKEND_NATIVE;
  if (options->runtime_support && (!native || !options->release || !options->shared || !options->emit_object || !options->no_link || options->emit_asm)) {
    fprintf(stderr, "error: --runtime-support requires native --release --shared --emit-object --no-link\n"); return 2;
  }
  options->native_backend = native;
  struct timespec phase = timer_start();
  if (options->optimization.native_cpu) {
    if (strcmp(options->target, DYN_HOST_TARGET)) {
      fprintf(stderr, "error: --cpu native requires the host target\n");
      return 2;
    }
    if (native) {
      options->optimization.cpu = strdup("native");
      options->optimization.features = strdup(dyn_native_host_features());
      if (!options->optimization.cpu || !options->optimization.features) return 2;
    }
  }
  if (options->optimization.level && !options->release) {
    fprintf(stderr, "error: --opt-level requires --release\n");
    return 2;
  }
  if (options->optimization.level == 1 && !native) {
    fprintf(stderr, "error: --opt-level 1 currently requires the independent backend\n");
    return 2;
  }
  if (options->optimization.sample_profile && native && (!options->release || access(options->optimization.sample_profile, R_OK))) {
    fprintf(stderr, "error: independent --sample-profile requires --release and a readable text profile\n");
    return 2;
  }
  if (options->optimization.sample_profile && !native) {
    fprintf(stderr, "error: --sample-profile requires build/run\n");
    return 2;
  }
  if (options->optimization.sample_profile) {
    options->optimization.profile_hash = dyn_cache_file_hash(options->optimization.sample_profile);
    if (!options->optimization.profile_hash) {
      fprintf(stderr, "error: failed to read sample profile\n"); return 2;
    }
  }
  /* Diagnostics must be regenerated even when all artifacts were cached. */
  if (options->optimization.remarks) {
    options->no_cache = true;
    options->jobs = 1; /* Keep optimization diagnostics ordered. */
  }
  DynSources sources;
  int result = dyn_sources_load(&context, options->input, &sources);
  if (result) return result;
  if (harness_cmd) {
    size_t found = 0;
    if (!harness_discover_and_append(&context, &sources, options, options->input,
                                     test_cmd, bench_cmd, fuzz_cmd, &found)) {
      fprintf(stderr, "error: failed to construct %s harness\n", options->command);
      dyn_sources_free(&sources);
      return 2;
    }
    if (!found) {
      printf("no matching %s functions found\n", options->command);
      dyn_sources_free(&sources);
      return 0;
    }
  }
  DynSources project_sources = {0};
  result = dyn_module_load_project(options->input, &sources, &project_sources);
  if (result) {
    dyn_sources_free(&sources);
    return result;
  }
  dyn_sources_free(&sources);
  sources = project_sources;
  /* Windows has no numeric syscall ABI. Darwin's target runtime deliberately exposes its stable BSD syscall shim, so target-gated Darwin adapters may use native Darwin numbers. */
  if (!strcmp(context.target->kernel, "windows") || !strcmp(context.target->arch, "wasm32")) {
    for (size_t i = 0; i < sources.count; ++i)
      if (dyn_source_target_enabled(&sources.items[i]) != 0 && strstr(sources.items[i].text, "#syscall(")) {
        fprintf(stderr, "error: target '%s' does not provide target-mapped " "#syscall numbers: %s\n", context.target->name, sources.items[i].path);
        dyn_sources_free(&sources);
        return 1;
      }
  }
  if (options->timings) fprintf(stderr, "timing load %.3f ms\n", elapsed_ms(phase));
  char *main_path = dyn_path_join(options->input, harness_cmd ? "__dyn_harness.dyn" : (single_file_name ? single_file_name : "main.dyn"));
  if (options->emit_ir) {
    result = main_path ? emit_ir_dump(&sources, main_path, options) : 2;
    dyn_sources_free(&sources);
    free(main_path);
    return result;
  }
  bool build = is_command(options, "build") || run;
  if (build && !options->no_link) {
    result = add_source_native_links(&context, &sources, options);
    if (result) {
      dyn_sources_free(&sources);
      free(main_path);
      return result;
    }
  }
  if (build && !options->no_link && !context.target->executable_link) {
    fprintf(stderr, "error: target '%s' supports object/assembly generation only; use " "--no-link\n", context.target->name);
    dyn_sources_free(&sources);
    free(main_path);
    return 1;
  }
  phase = timer_start();
  if (is_command(options, "query")) {
    result = dyn_query_sources(&sources, main_path);
    dyn_sources_free(&sources); free(main_path); return result;
  }
  DynCheckResult checked = {0};
  if (vet) checked = dyn_vet_sources(&sources, main_path, options->input);
  else if (!build) checked = dyn_check_sources_owned(&sources, main_path, false);
  if (checked.errors || vet_findings) {
    dyn_sources_free(&sources);
    free(main_path);
    return 1;
  }
  if (options->timings && !build) fprintf(stderr, "timing check %.3f ms\n", elapsed_ms(phase));
  if (!build) {
    if (!options->quiet && !options->fix_pass) puts("ok");
    /* The process exits next; freeing every syntax tree first costs about a tenth of a large check. Sanitizer builds still free for leak checks. */
#if DYN_SANITIZED
    dyn_sources_free(&sources);
    free(main_path);
#endif
    return 0;
  }
  char *base = dyn_path_basename(options->input);
  char run_output[4096];
  const char *temporary_root = getenv("TMPDIR");
#ifdef _WIN32
  if (!temporary_root) temporary_root = getenv("TEMP");
#endif
  if (!temporary_root) temporary_root = "/tmp";
  if (snprintf(run_output, sizeof(run_output), "%s/dyn-run-XXXXXX", temporary_root) >= (int)sizeof(run_output)) {
    dyn_sources_free(&sources);
    free(main_path);
    free(base);
    return 2;
  }
  if (run) {
    int temporary = mkstemp(run_output);
    if (temporary < 0) {
      perror("error: create run executable");
      dyn_sources_free(&sources);
      free(main_path);
      free(base);
      return 2;
    }
    close(temporary);
    remove(run_output);
  }
  const char *output = run ? run_output : options->output ? options->output : base;
  // Run reuses native objects, but never persists its temporary executable.
  bool cacheable = strcmp(context.target->arch, "wasm32") && !options->shared && !options->no_link && !options->emit_object && !options->emit_asm;
  if (cacheable && !options->no_cache) options->compiler_hash = dyn_cache_file_hash(compiler);
  if (!run && cacheable && dyn_cache_hit(&sources, options, compiler, output)) {
    if (!options->quiet) printf("cached %s\n", output);
    dyn_sources_free(&sources);
    free(main_path);
    free(base);
    return 0;
  }
  char object[4096], assembly[4096];
  /* A native object is private unless requested: "<output>.o" may name a --link input. On macOS it is kept beside the output instead, because the executable's debug map refers to the object's DWARF. */
  bool private_object = native && !options->emit_object && !options->no_link;
  bool kept_object = private_object && !strcmp(context.target->kernel, "darwin");
  if (kept_object) {
    private_object = false;
    if (snprintf(object, sizeof(object), "%s.dynnative.o", output) >= (int)sizeof(object)) {
      fprintf(stderr, "error: output path too long\n");
      dyn_sources_free(&sources); free(main_path); free(base); return 2;
    }
  }
  if (private_object) {
    if (snprintf(object, sizeof(object), "%s/dyn-object-XXXXXX", temporary_root) >= (int)sizeof(object)) {
      dyn_sources_free(&sources); free(main_path); free(base); return 2;
    }
    int temporary = mkstemp(object);
    if (temporary < 0) {
      perror("error: create native object");
      dyn_sources_free(&sources); free(main_path); free(base); return 2;
    }
    close(temporary);
  }
  if ((!private_object && !kept_object && snprintf(object, sizeof(object), "%s.o", output) >= (int)sizeof(object)) || snprintf(assembly, sizeof(assembly), "%s.s", output) >= (int)sizeof(assembly)) {
    fprintf(stderr, "error: output path too long\n");
    dyn_sources_free(&sources); free(main_path); free(base); return 2;
  }
  phase = timer_start();
  /* Native objects depend on source and code-generation options, not link inputs or output names. Reuse them when relinking or running again. */
  bool restored = cacheable && dyn_object_cache_restore(&sources, options, compiler, output, object);
  if (restored && options->verbose) fprintf(stderr, "cached native object\n");
  if (!restored) {
    DynSource module_source = {0};
    result = dyn_sources_merge(&sources, main_path, &module_source);
    if (!result && (!cacheable || options->no_cache))
      dyn_sources_free(&sources);
    module_source.context = context;
    DynIrProgram prepared;
    bool have_ir = false;
    if (!result) {
      result = dyn_codegen_prepare_owned(&module_source, options->shared, NULL, &prepared);
      have_ir = !result;
    }
    /* Explicit objects, libraries and --link inputs preserve public ABI roots.
       Libraries discovered from #link are C providers that reach Dyn code only
       through function values, so they do not keep public functions alive. */
    if (!result && native && !options->shared &&
        !options->emit_object && !options->emit_asm && !options->no_link &&
        !options->runtime_support && !options->explicit_link_input_count) {
      struct timespec pruning = timer_start();
      if (!dyn_ir_prune_functions(&prepared)) {
        fprintf(stderr, "error: failed to compute executable reachability\n");
        result = 2;
      }
      if (options->timings) fprintf(stderr, "timing detail reachability %.3f ms\n", elapsed_ms(pruning));
    }
    if (!result) result = emit_native(&module_source, &prepared, object, options->emit_asm ? assembly : NULL, options);
    if (have_ir) dyn_codegen_release(&prepared);
    dyn_source_free(&module_source);
    if (!result && cacheable) dyn_object_cache_store(&sources, options, compiler, output, object);
  }
  if (options->timings) fprintf(stderr, "timing codegen %.3f ms\n", elapsed_ms(phase));
  phase = timer_start();
  if (!result && !options->no_link)
    result = options->shared ? dyn_link_shared(&context, object, output, options->link_inputs, options->link_input_count, options->verbose) : dyn_link_executable(&context, object, output, options->link_inputs, options->link_input_count, options->release, options->verbose);
  if (!result && !run && cacheable) dyn_cache_store(&sources, options, compiler, output);
  if (options->timings && !options->no_link) fprintf(stderr, "timing link %.3f ms\n", elapsed_ms(phase));
  if (!options->emit_object && !options->no_link) {
    if (!kept_object || run) remove(object);
    if (!strcmp(context.target->arch, "wasm32")) {
      char *imports = malloc(strlen(object) + 9);
      if (imports) {
        sprintf(imports, "%s.imports", object);
        remove(imports);
        free(imports);
      }
    }
  }
  if (!result && !options->quiet) printf("built %s\n", options->no_link ? object : output);
  if (!result && run) {
    char **arguments = calloc(options->run_argument_count + 2, sizeof(char *));
    if (!arguments) result = 2;
    else {
      fflush(stdout);
      arguments[0] = (char *)output;
      for (size_t k = 0; k < options->run_argument_count; ++k) arguments[k + 1] = options->run_arguments[k];
      result = dyn_host_spawn(arguments);
      free(arguments);
    }
    remove(output);
  }
  dyn_sources_free(&sources);
  free(main_path);
  free(base);
  return result;
}

/* Installed SDK linkers are private: do not require a global LLVM installation. */
static bool configure_sdk_linkers(void) {
  char executable[4096], directory[4096];
  ssize_t n = dyn_host_executable(executable, sizeof(executable) - 1);
  if (n < 0 || n == (ssize_t)sizeof(executable) - 1) return true;
  executable[n] = 0;
  char *slash = strrchr(executable, '/');
  if (!slash) return true;
  *slash = 0;
  if (snprintf(directory, sizeof(directory), "%s/../lib/dyn/tools", executable) >= (int)sizeof(directory) || access(directory, X_OK)) return true;
  const char *previous = getenv("PATH");
  size_t size = strlen(directory) + strlen(executable) + (previous ? strlen(previous) : 0) + 3;
  char *path = malloc(size);
  if (!path) return false;
#ifdef _WIN32
  /* DLLs live beside dyn.exe; private linker processes must find them too. */
  snprintf(path, size, "%s;%s;%s", directory, executable, previous ? previous : "");
#else
  snprintf(path, size, "%s%s%s", directory, previous ? (DYN_PATH_SEPARATOR == ';' ? ";" : ":") : "", previous ? previous : "");
#endif
  int result = setenv("PATH", path, 1);
  free(path);
  return result == 0;
}

/* A batch command allocates its working set, uses it and exits. glibc maps
   blocks over 128 KiB separately at first, so growing arrays are mapped,
   faulted and unmapped again and again: 5 to 7% of a large check or build.
   Blocks up to 4 MiB stay in the heap. Larger thresholds, or keeping freed
   memory, saved no more time and raised peak memory by up to half on
   mid-sized projects (tests/compile-budget.py). The editor server stays on
   the defaults because it runs for hours. */
static void batch_allocator(void) {
#if defined(__GLIBC__)
  mallopt(M_MMAP_THRESHOLD, 4 << 20);
#endif
}
int main(int argc, char **argv) {
#ifdef _WIN32
  _setmode(STDIN_FILENO, _O_BINARY);
  _setmode(STDOUT_FILENO, _O_BINARY);
#endif
  if (!configure_sdk_linkers()) {
    perror("error: configure SDK linkers");
    return 2;
  }
  if (argc == 2 && (strcmp(argv[1], "--help") == 0 || strcmp(argv[1], "-h") == 0)) {
    dyn_cli_help(NULL);
    return 0;
  }
  if (argc == 2 && strcmp(argv[1], "--version") == 0) {
    puts("dyn " DYN_VERSION);
    return 0;
  }
  DynOptions o;
  int cli = dyn_cli_parse(argc, argv, &o);
  if (cli) {
    bool dump_requested = o.emit_ir;
    for (int i = 2; i < argc; ++i)
      if (!strcmp(argv[i], "--emit-ir")) dump_requested = true;
    if (!dump_requested) dyn_cli_help(NULL);
    return cli;
  }
  if (!is_command(&o, "lsp")) batch_allocator();
  /* CLI link inputs borrow argv; discovered libraries are owned suffix entries. Keep cleanup outside execution so every early return follows this path. */
  size_t borrowed_links = o.link_input_count;
  o.explicit_link_input_count = o.link_input_count;
  /* argv[0] is commonly just "dyn" when launched through PATH. Hash the running executable, not a nonexistent file in the project directory. */
  char executable[4096];
  ssize_t executable_length = dyn_host_executable(executable, sizeof(executable) - 1);
  const char *compiler = argv[0];
  if (executable_length > 0 && executable_length < (ssize_t)sizeof(executable) - 1) {
    executable[executable_length] = 0;
    compiler = executable;
  }
  int result = is_command(&o, "fix") ? fix_command(&o, compiler) : execute_command(&o, compiler);
  {
    free(o.optimization.cpu);
    free(o.optimization.features);
  }
  for (size_t i = borrowed_links; i < o.link_input_count; ++i) free((void *)o.link_inputs[i]);
  return result;
}
