#define _XOPEN_SOURCE 700
#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <tree_sitter/api.h>
#include <unistd.h>
#ifndef DYN_VERSION
#define DYN_VERSION "0.1.0-dev"
#endif

extern char *realpath(const char *, char *);
extern const TSLanguage *tree_sitter_dyn(void);

static bool native_link_matches(const char *path, const char *name) {
  const char *base = strrchr(path, '/');
  base = base ? base + 1 : path;
  size_t name_length = strlen(name), base_length = strlen(base);
  if (base_length < 3 + name_length || strncmp(base, "lib", 3) ||
      memcmp(base + 3, name, name_length))
    return false;
  const char *suffix = base + 3 + name_length;
  return !strcmp(suffix, ".so") || !strncmp(suffix, ".so.", 4) ||
         !strcmp(suffix, ".dylib") || !strcmp(suffix, ".dll.a");
}

static char *native_link_in_directory(const DynContext *context,
                                      const char *directory, const char *name) {
  const char *format =
      !strcmp(dyn_context_target(context)->kernel, "darwin")    ? "lib%s.dylib"
      : !strcmp(dyn_context_target(context)->kernel, "windows") ? "lib%s.dll.a"
                                                                : "lib%s.so";
  char filename[160], candidate[4096];
  if (snprintf(filename, sizeof(filename), format, name) >=
          (int)sizeof(filename) ||
      snprintf(candidate, sizeof(candidate), "%s/%s", directory, filename) >=
          (int)sizeof(candidate))
    return NULL;
  char *resolved = realpath(candidate, NULL);
  if (resolved)
    return resolved;
  if (strcmp(dyn_context_target(context)->kernel, "linux"))
    return NULL;
  DIR *entries = opendir(directory);
  if (!entries)
    return NULL;
  size_t prefix = strlen(filename);
  struct dirent *entry;
  while ((entry = readdir(entries))) {
    if (strncmp(entry->d_name, filename, prefix) ||
        entry->d_name[prefix] != '.')
      continue;
    if (snprintf(candidate, sizeof(candidate), "%s/%s", directory,
                 entry->d_name) >= (int)sizeof(candidate))
      continue;
    resolved = realpath(candidate, NULL);
    if (resolved)
      break;
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
      if (!end)
        end = at + strlen(at);
      if (end > at && (size_t)(end - at) < 4096) {
        char directory[4096];
        memcpy(directory, at, (size_t)(end - at));
        directory[end - at] = 0;
        char *found = native_link_in_directory(context, directory, name);
        if (found)
          return found;
      }
      at = *end ? end + 1 : end;
    }
  }
  /* libSystem is supplied by the Darwin SDK (often as a .tbd stub), not
     necessarily a real dylib on the build host. Let the target linker find it. */
  if (!strcmp(dyn_context_target(context)->kernel, "darwin") &&
      !strcmp(name, "System"))
    return strdup("-lSystem");
  static const char *directories[] = {
      "/usr/lib",
      "/usr/local/lib",
      "/lib",
      "/usr/lib/x86_64-linux-gnu",
      "/lib/x86_64-linux-gnu",
      "/usr/lib/aarch64-linux-gnu",
      "/lib/aarch64-linux-gnu",
      "/opt/homebrew/lib",
      "/usr/local/opt/lib",
  };
  for (size_t i = 0; i < sizeof(directories) / sizeof(directories[0]); ++i) {
    char *found = native_link_in_directory(context, directories[i], name);
    if (found)
      return found;
  }
  return NULL;
}

static int add_source_native_links(const DynContext *context,
                                   const DynSources *sources,
                                   DynOptions *options) {
  char names[32][128];
  size_t name_count = 0;
  for (size_t i = 0; i < sources->count; ++i) {
    if (dyn_source_target_enabled(&sources->items[i]) == 0)
      continue;
    TSTree *tree = dyn_source_tree(&sources->items[i]);
    if (!tree) {
      return 2;
    }
    TSNode root = ts_tree_root_node(tree);
    for (uint32_t child = 0; child < ts_node_named_child_count(root); ++child) {
      TSNode directive = ts_node_named_child(root, child);
      if (strcmp(ts_node_type(directive), "link_directive"))
        continue;
      TSNode value = ts_node_child_by_field_name(directive, "library", 7);
      uint32_t start = ts_node_start_byte(value), end = ts_node_end_byte(value);
      if (end <= start + 2 || end - start - 2 >= sizeof(names[0])) {
        fprintf(stderr, "error: invalid #link library in %s\n",
                sources->items[i].path);
        ts_tree_delete(tree);
        return 1;
      }
      char name[128];
      size_t length = (size_t)(end - start - 2);
      memcpy(name, sources->items[i].text + start + 1, length);
      name[length] = 0;
      for (size_t byte = 0; byte < length; ++byte)
        if (!(name[byte] == '_' || name[byte] == '-' || name[byte] == '.' ||
              (name[byte] >= '0' && name[byte] <= '9') ||
              (name[byte] >= 'A' && name[byte] <= 'Z') ||
              (name[byte] >= 'a' && name[byte] <= 'z'))) {
          fprintf(stderr, "error: invalid #link library '%s' in %s\n", name,
                  sources->items[i].path);
          ts_tree_delete(tree);
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
          ts_tree_delete(tree);
          fprintf(stderr, "error: too many native libraries\n");
          return 2;
        }
        strcpy(names[name_count++], name);
      }
    }
    ts_tree_delete(tree);
  }
  for (size_t i = 0; i < name_count; ++i) {
    bool supplied = false;
    for (size_t j = 0; j < options->link_input_count; ++j)
      if (native_link_matches(options->link_inputs[j], names[i])) {
        supplied = true;
        break;
      }
    if (supplied)
      continue;
    char *library = find_native_link(context, names[i]);
    if (!library) {
      fprintf(
          stderr,
          "error: package requires native library '%s' for %s; install "
          "its development package, set DYN_LIBRARY_PATH, or pass --link\n",
          names[i], dyn_context_target(context)->kernel);
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
typedef struct {
  const DynSource *merged;
  const DynInterface *interfaces;
  size_t interface_count;
  bool incremental_frontend;
  bool thin_lto;
  const DynOptions *options;
  const char *compiler, *output, *root, *cache_root;
} ModuleBuild;
static bool command_available(const char *name) {
  const char *path = getenv("PATH");
  if (!path)
    return false;
  size_t name_length = strlen(name);
  for (const char *at = path; *at;) {
    const char *end = strchr(at, DYN_PATH_SEPARATOR);
    if (!end)
      end = at + strlen(at);
    size_t length = (size_t)(end - at);
    char candidate[4096];
    if (length + name_length + 2 < sizeof(candidate)) {
      memcpy(candidate, at, length);
      candidate[length] = '/';
      memcpy(candidate + length + 1, name, name_length + 1);
      if (!access(candidate, X_OK))
        return true;
    }
    at = *end ? end + 1 : end;
  }
  return false;
}
static uint64_t path_hash(const char *s) {
  uint64_t h = UINT64_C(1469598103934665603);
  for (; *s; ++s) {
    h ^= (unsigned char)*s;
    h *= UINT64_C(1099511628211);
  }
  return h;
}
static int build_module(const DynSources *sources, size_t first, size_t count,
                        void *raw, uint64_t *value) {
  ModuleBuild *b = raw;
  char object[4096], owner[32];
  bool thin = b->thin_lto;
  if (snprintf(object, sizeof(object), "%s.dynmod.%zu.%s", b->output, first,
               thin ? "bc" : "o") >= (int)sizeof(object))
    return 2;
  char *full = realpath(sources->items[first].path, NULL);
  if (!full)
    return 2;
  char *slash = strrchr(full, '/');
  if (slash)
    *slash = 0;
  if (!strcmp(full, b->root))
    strcpy(owner, "root");
  else
    snprintf(owner, sizeof(owner), "dyn_m%016llx",
             (unsigned long long)path_hash(full));
  free(full);
  *value = first;
  if (dyn_module_cache_restore(sources, first, count, b->options, b->compiler,
                               b->cache_root, object)) {
    if (b->options->verbose)
      fprintf(stderr, "cached module %s\n", sources->items[first].path);
    return 0;
  }
  DynSource composed = {0};
  const DynSource *input = b->merged;
  int result = 0;
  if (b->incremental_frontend && strcmp(owner, "root")) {
    result = dyn_interface_compose(sources, first, count, b->interfaces,
                                   b->interface_count,
                                   sources->items[first].path, &composed);
    input = &composed;
  }
  if (!result)
    result = dyn_codegen_module(input, object, NULL, NULL, b->options->release,
                                b->options->debug_info, false, owner);
  dyn_source_free(&composed);
  if (!result)
    dyn_module_cache_store(sources, first, count, b->options, b->compiler,
                           b->cache_root, object);
  return result;
}

static size_t module_end(const DynSources *sources, size_t first) {
  const char *slash = strrchr(sources->items[first].path, '/');
  size_t n = slash ? (size_t)(slash - sources->items[first].path) : 0,
         end = first + 1;
  while (end < sources->count) {
    const char *s = strrchr(sources->items[end].path, '/');
    size_t m = s ? (size_t)(s - sources->items[end].path) : 0;
    if (m != n ||
        memcmp(sources->items[first].path, sources->items[end].path, n))
      break;
    ++end;
  }
  return end;
}
static bool interface_path(const DynSources *sources, size_t first,
                           const char *root, char *path, size_t capacity) {
  char *full = realpath(sources->items[first].path, NULL);
  if (!full)
    return false;
  char *slash = strrchr(full, '/');
  if (slash)
    *slash = 0;
  uint64_t key = path_hash(full);
  free(full);
  int n = snprintf(path, capacity, "%s/%016llx.dynmi", root,
                   (unsigned long long)key);
  return n > 0 && (size_t)n < capacity;
}
static int prepare_interfaces(const DynSources *sources, const DynOptions *o,
                              const char *cache_root, DynInterface **out,
                              size_t *out_count) {
  *out = NULL; *out_count = 0;
  size_t count = 0;
  for (size_t first = 0; first < sources->count; first = module_end(sources, first)) ++count;
  DynInterface *values = calloc(count ? count : 1, sizeof(*values));
  if (!values) return 2;
  size_t module = 0;
  int result = 0;
  for (size_t first = 0; first < sources->count; ++module) {
    size_t end = module_end(sources, first);
    DynSources slice = {sources->items + first, end - first};
    char path[4096];
    bool cached = !o->no_cache && cache_root &&
        interface_path(sources, first, cache_root, path, sizeof(path));
    if (cached && dyn_interface_load(path, o->target, DYN_FRONTEND_STAMP,
          dyn_interface_source_hash(&slice), &values[module]) == DYN_INTERFACE_HIT) {
      if (o->verbose) fprintf(stderr, "cached interface %s\n", sources->items[first].path);
    } else {
      result = dyn_interface_build(&slice, &values[module]);
      if (result) break;
      /* Caches are optional. Keep the owned in-memory payload even if the
         artifact cannot be persisted; never serialize just to read it back. */
      if (cached) (void)dyn_interface_store(path, o->target, DYN_FRONTEND_STAMP, &values[module]);
    }
    first = end;
  }
  if (result) {
    for (size_t i = 0; i < count; ++i) dyn_interface_free(&values[i]);
    free(values); return result;
  }
  *out = values; *out_count = count;
  return 0;
}
static double elapsed_ms(struct timespec start) {
  struct timespec end;
  clock_gettime(CLOCK_MONOTONIC, &end);
  return (double)(end.tv_sec - start.tv_sec) * 1000.0 +
         (double)(end.tv_nsec - start.tv_nsec) / 1000000.0;
}
static struct timespec timer_start(void) {
  struct timespec value;
  clock_gettime(CLOCK_MONOTONIC, &value);
  return value;
}
static bool is_command(const DynOptions *o, const char *s) {
  return strcmp(o->command, s) == 0;
}
static int execute_command(DynOptions *options, const char *compiler) {
  DynWork work = {.remaining = options->max_work};
  DynContext context = {.work = options->max_work ? &work : NULL, .target = dyn_target_find(options->target),
                        .json_diagnostics = options->json_diagnostics,
                        .timings = options->timings};
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
  if (is_command(options, "cache"))
    return dyn_cache_command(options->input);
  if (is_command(options, "fmt") || is_command(options, "docs")) {
    if (!options->input || !dyn_path_is_directory(options->input)) {
      fprintf(stderr, "error: %s requires a module directory\n",
              options->command);
      return 2;
    }
    return is_command(options, "fmt")
               ? dyn_format_directory(options->input, options->format_check)
               : dyn_docs_directory(options->input, options->docs_json);
  }
  bool run = is_command(options, "run");
  if (!is_command(options, "check") && !is_command(options, "build") && !is_command(options, "query") && !run) {
    fprintf(stderr, "error: command '%s' is not implemented\n",
            options->command);
    return 2;
  }
  if (!options->input) {
    fprintf(stderr, "error: %s requires a module directory\n",
            options->command);
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
  if (options->shared && options->no_link) {
    fprintf(stderr, "error: --shared cannot be combined with --no-link\n");
    return 2;
  }
  if (!dyn_path_is_directory(options->input)) {
    fprintf(stderr, "error: input must be a module directory: '%s'\n",
            options->input);
    return 2;
  }
  if (!context.target) {
    fprintf(stderr,
            "error: target '%s' is not implemented; supported targets: "
            "x86_64-linux, aarch64-linux, aarch64-macos, x86_64-windows, wasm32-browser, wasm32-wasi\n",
            options->target);
    return 2;
  }
  if (!strcmp(context.target->arch, "wasm32") &&
      (run || (is_command(options, "build") &&
       ((!strcmp(context.target->kernel, "browser") && !options->shared) ||
        (!strcmp(context.target->kernel, "wasi") && options->shared))))) {
    fprintf(stderr, "error: Wasm requires an external host; browser builds require --shared, WASI commands forbid --shared\n");
    return 2;
  }
  struct timespec phase = timer_start();
  DynSources sources;
  int result = dyn_sources_load(&context, options->input, &sources);
  if (result)
    return result;
  DynSources project_sources = {0};
  result = dyn_module_load_project(options->input, &sources, &project_sources);
  if (result) {
    dyn_sources_free(&sources);
    return result;
  }
  dyn_sources_free(&sources);
  sources = project_sources;
  /* Windows has no numeric syscall ABI. Darwin's target runtime deliberately
     exposes its stable BSD syscall shim, so target-gated Darwin adapters may
     use native Darwin numbers. */
  if (!strcmp(context.target->kernel, "windows") || !strcmp(context.target->arch, "wasm32")) {
    for (size_t i = 0; i < sources.count; ++i)
      if (dyn_source_target_enabled(&sources.items[i]) != 0 &&
          strstr(sources.items[i].text, "#syscall(")) {
        fprintf(stderr,
                "error: target '%s' does not provide target-mapped "
                "#syscall numbers: %s\n",
                context.target->name, sources.items[i].path);
        dyn_sources_free(&sources);
        return 1;
      }
  }
  if (options->timings)
    fprintf(stderr, "timing load %.3f ms\n", elapsed_ms(phase));
  char *main_path = dyn_path_join(options->input, "main.dyn");
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
    fprintf(stderr,
            "error: target '%s' supports object/assembly generation only; use "
            "--no-link\n",
            context.target->name);
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
  if (!build)
    checked = dyn_check_sources(&sources, main_path, false);
  if (checked.errors) {
    dyn_sources_free(&sources);
    free(main_path);
    return 1;
  }
  if (options->timings && !build)
    fprintf(stderr, "timing check %.3f ms\n", elapsed_ms(phase));
  if (!build) {
    if (!options->quiet)
      puts("ok");
    dyn_sources_free(&sources);
    free(main_path);
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
    dyn_sources_free(&sources); free(main_path); free(base); return 2;
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
  const char *output = run               ? run_output
                       : options->output ? options->output
                                         : base;
  bool cacheable = strcmp(context.target->arch, "wasm32") && !run && !options->shared && !options->no_link &&
                   !options->emit_ir && !options->emit_object &&
                   !options->emit_asm;
  if (cacheable && !options->no_cache)
    options->compiler_hash = dyn_cache_compiler_hash(compiler);
  if (cacheable && dyn_cache_hit(&sources, options, compiler, output)) {
    if (!options->quiet)
      printf("cached %s\n", output);
    dyn_sources_free(&sources);
    free(main_path);
    free(base);
    return 0;
  }
  char object[4096], ir[4096], assembly[4096];
  if (snprintf(object, sizeof(object), "%s.o", output) >= (int)sizeof(object) ||
      snprintf(ir, sizeof(ir), "%s.ll", output) >= (int)sizeof(ir) ||
      snprintf(assembly, sizeof(assembly), "%s.s", output) >= (int)sizeof(assembly)) {
    fprintf(stderr, "error: output path too long\n");
    dyn_sources_free(&sources); free(main_path); free(base); return 2;
  }
  DynSource module_source = {0};
  phase = timer_start();
  uint64_t *module_ids = NULL;
  size_t module_count = 0;
  char **module_objects = NULL;
  DynInterface *interfaces = NULL;
  size_t interface_count = 0;
  bool modular = cacheable;
  if (modular) {
    char *root = realpath(options->input, NULL);
    char cache_root[4096];
    const char *cache = !options->no_cache && dyn_cache_directory(cache_root, sizeof(cache_root))
                            ? cache_root : NULL;
    if (!root) result = 2;
    int prepared = !result ? prepare_interfaces(&sources, options, cache,
                                                &interfaces, &interface_count)
                           : 2;
    bool incremental_frontend = prepared == 0;
    if (prepared && prepared != 3) {
      /* Interface extraction intentionally has no diagnostic sink. Route a
         failed preparation through the canonical frontend before reporting it. */
      DynCheckResult failure = dyn_check_sources(&sources, main_path, false);
      if (failure.errors) result = 1;
      else {
        fprintf(stderr, "error: failed to prepare module interfaces (status %d)\n", prepared);
        result = prepared;
      }
    }
    if (!result)
      result = dyn_sources_merge(&sources, main_path, &module_source);
    module_source.context = context;
    bool thin_lto = options->release &&
                    !strcmp(options->target, "x86_64-linux") &&
                    command_available("ld.lld");
    ModuleBuild module_build = {.merged = &module_source,
                                .interfaces = interfaces,
                                .interface_count = interface_count,
                                .incremental_frontend = incremental_frontend,
                                .thin_lto = thin_lto,
                                .options = options,
                                .compiler = compiler,
                                .output = output,
                                .root = root,
                                .cache_root = cache};
    if (!result)
      result = dyn_build_plan_run(&sources, options->jobs, build_module,
                                  &module_build, &module_ids, &module_count);
    free(root);
    if (!result) {
      module_objects = calloc(module_count, sizeof(*module_objects));
      if (!module_objects)
        result = 2;
    }
    bool thin = thin_lto;
    for (size_t i = 0; !result && i < module_count; ++i) {
      module_objects[i] = malloc(4096);
      if (!module_objects[i] ||
          snprintf(module_objects[i], 4096, "%s.dynmod.%llu.%s", output,
                   (unsigned long long)module_ids[i],
                   thin ? "bc" : "o") >= 4096)
        result = 2;
    }
  } else {
    result = dyn_sources_merge(&sources, main_path, &module_source);
    module_source.context = context;
    if (!result)
      result = dyn_codegen_main(
          &module_source, object, options->emit_ir ? ir : NULL,
          options->emit_asm ? assembly : NULL, options->release,
          options->debug_info, options->shared);
  }
  if (options->timings)
    fprintf(stderr, "timing codegen %.3f ms\n", elapsed_ms(phase));
  dyn_source_free(&module_source);
  if (interfaces) {
    for (size_t i = 0; i < interface_count; ++i)
      dyn_interface_free(&interfaces[i]);
    free(interfaces);
  }
  phase = timer_start();
  if (!result && !options->no_link)
    result =
        options->shared
            ? dyn_link_shared(&context, object, output, options->link_inputs,
                              options->link_input_count, options->verbose)
        : modular
            ? dyn_link_executable_objects(
                  &context, (const char *const *)module_objects, module_count,
                  output, options->link_inputs, options->link_input_count,
                  options->release, options->verbose)
            : dyn_link_executable(&context, object, output,
                                  options->link_inputs,
                                  options->link_input_count, options->release,
                                  options->verbose);
  if (!result && cacheable)
    dyn_cache_store(&sources, options, compiler, output);
  if (options->timings && !options->no_link)
    fprintf(stderr, "timing link %.3f ms\n", elapsed_ms(phase));
  if (!options->emit_object && !options->no_link) {
    remove(object);
    if (!strcmp(context.target->arch, "wasm32")) {
      char *imports = malloc(strlen(object) + 9);
      if (imports) { sprintf(imports, "%s.imports", object); remove(imports); free(imports); }
    }
  }
  if (module_objects)
    for (size_t i = 0; i < module_count; ++i) {
      if (module_objects[i])
        remove(module_objects[i]);
      free(module_objects[i]);
    }
  free(module_objects);
  free(module_ids);
  if (!result && !options->quiet)
    printf("built %s\n", options->no_link ? object : output);
  if (!result && run) {
    char *arguments[] = {(char *)output, NULL};
    result = dyn_host_spawn(arguments);
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
  if (n < 0 || n == (ssize_t)sizeof(executable) - 1)
    return true;
  executable[n] = 0;
  char *slash = strrchr(executable, '/');
  if (!slash)
    return true;
  *slash = 0;
  if (snprintf(directory, sizeof(directory), "%s/../lib/dyn/tools", executable) >=
      (int)sizeof(directory) || access(directory, X_OK))
    return true;
  const char *previous = getenv("PATH");
  size_t size = strlen(directory) + strlen(executable) + (previous ? strlen(previous) : 0) + 3;
  char *path = malloc(size);
  if (!path)
    return false;
#ifdef _WIN32
  /* DLLs live beside dyn.exe; private linker processes must find them too. */
  snprintf(path, size, "%s;%s;%s", directory, executable, previous ? previous : "");
#else
  snprintf(path, size, "%s%s%s", directory, previous ? (DYN_PATH_SEPARATOR == ';' ? ";" : ":") : "",
           previous ? previous : "");
#endif
  int result = setenv("PATH", path, 1);
  free(path);
  return result == 0;
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
  if (argc == 2 &&
      (strcmp(argv[1], "--help") == 0 || strcmp(argv[1], "-h") == 0)) {
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
    dyn_cli_help(NULL);
    return cli;
  }
  /* CLI link inputs borrow argv; discovered libraries are owned suffix entries.
     Keep cleanup outside execution so every early return follows this path. */
  size_t borrowed_links = o.link_input_count;
  int result = execute_command(&o, argv[0]);
  for (size_t i = borrowed_links; i < o.link_input_count; ++i)
    free((void *)o.link_inputs[i]);
  return result;
}
