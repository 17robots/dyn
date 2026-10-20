#define _XOPEN_SOURCE 700
#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include "dyn_compact.h"
#include "ir.h"
#include "native_opt.h"
#include "native_cpu.h"
#include "native_asm.h"
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#ifndef DYN_VERSION
#define DYN_VERSION "0.1.0-dev"
#endif

extern char *realpath(const char *, char *);

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
  /* Prefer our supported libSystem ABI metadata; fall back to the target SDK. */
  if (!strcmp(dyn_context_target(context)->kernel, "darwin") &&
      !strcmp(name, "System")) {
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
    const ExpSnapshotTree *compact = dyn_compact_tree(&sources->items[i]);
    if (!compact) return 2;
    for (uint32_t id = compact->nodes[compact->root].first; id != UINT32_MAX;
         id = compact->nodes[id].next) {
      if (!dyn_work_step(&sources->items[i].context, 1)) return 2;
      if (compact->nodes[id].kind != SRC_LINK) continue;
      uint32_t value = dyn_compact_field(compact, id, EXP_ROLE_LIBRARY);
      if (value == UINT32_MAX) return 2;
      uint32_t start = compact->nodes[value].start, end = compact->nodes[value].end;
      if (end <= start + 2 || end - start - 2 >= sizeof(names[0])) {
        fprintf(stderr, "error: invalid #link library in %s\n",
                sources->items[i].path);
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
/* Every supported target uses independent emission. */
static int emit_native(const DynSource *source, const DynIrProgram *ir,
                       const char *object, const char *asm_path,
                       const DynOptions *options) {
  bool report = true;
  struct timespec phase = timer_start();
  DynNativeOptimization optimized = {0};
  if (options->release) {
    unsigned level = options->optimization.level ? options->optimization.level : 2;
    if (!dyn_native_optimize(source, ir, level, &optimized)) return 2;
    ir = &optimized.ir;
  }
  int result = !strcmp(dyn_context_target(&source->context)->arch, "wasm32")
      ? dyn_wasm_object(source, ir, object, report)
      : dyn_native_object(source, ir, object, !options->release, options->debug_info, options->shared, report);
  if (!result && asm_path)
    result = !strcmp(dyn_context_target(&source->context)->arch, "wasm32")
        ? dyn_wasm_assembly(source, ir, asm_path, report)
        : dyn_native_assembly(object, asm_path);
  if (options->release) dyn_native_optimization_free(&optimized);
  if (options->timings)
    fprintf(stderr, "timing detail native emit %.3f ms\n", elapsed_ms(phase));
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
static int execute_command(DynOptions *options, const char *compiler) {
  DynWork work = {.remaining = options->max_work};
  unsigned vet_findings = 0;
  bool vet = is_command(options, "vet");
  DynContext context = {.work = options->max_work ? &work : NULL, .target = dyn_target_find(options->target),
                        .optimization = &options->optimization,
                        .runtime_support = options->runtime_support,
                        .json_diagnostics = options->json_diagnostics,
                        .vet = vet, .vet_findings = &vet_findings,
                        .timings = options->timings, .strict_syntax = true};
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
  if (!is_command(options, "check") && !vet && !is_command(options, "build") && !is_command(options, "query") && !run) {
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
  if (options->shared && options->no_link && !options->emit_object) {
    fprintf(stderr, "error: --shared --no-link requires --emit-object\n");
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
            "x86_64-linux, aarch64-linux, riscv64-linux, x86_64-macos, aarch64-macos, x86_64-windows, aarch64-windows, wasm32-browser, wasm32-wasi\n",
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
  bool native = (is_command(options, "build") || run);
  if (options->backend == DYN_BACKEND_LLVM) {
    fprintf(stderr, "error: LLVM backend was removed; use --backend native\n");
    return 2;
  }
  if (options->backend == DYN_BACKEND_NATIVE && !native) {
    fprintf(stderr, "error: --backend native requires build/run\n");
    return 2;
  }
  if (native)
    options->backend = DYN_BACKEND_NATIVE;
  if (options->runtime_support && (!native || !options->release || !options->shared ||
      !options->emit_object || !options->no_link || options->emit_asm)) {
    fprintf(stderr, "error: --runtime-support requires native --release --shared --emit-object --no-link\n"); return 2;
  }
  options->native_backend = native;
  struct timespec phase = timer_start();
  if (options->optimization.native_cpu) {
    if (strcmp(options->target, DYN_HOST_TARGET)) {
      fprintf(stderr, "error: --cpu native requires the host target\n"); return 2;
    }
    if (native) {
      options->optimization.cpu = strdup("native");
      options->optimization.features = strdup(dyn_native_host_features());
      if (!options->optimization.cpu || !options->optimization.features) return 2;
    }
  }
  if (options->optimization.level && !options->release) {
    fprintf(stderr, "error: --opt-level requires --release\n"); return 2;
  }
  if (options->optimization.level == 1 && !native) {
    fprintf(stderr, "error: --opt-level 1 currently requires the independent backend\n"); return 2;
  }
  if (options->optimization.sample_profile && native &&
      (!options->release || access(options->optimization.sample_profile, R_OK))) {
    fprintf(stderr, "error: independent --sample-profile requires --release and a readable text profile\n"); return 2;
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
  if (checked.errors || vet_findings) {
    dyn_sources_free(&sources);
    free(main_path);
    return 1;
  }
  if (options->timings && !build)
    fprintf(stderr, "timing check %.3f ms\n", elapsed_ms(phase));
  if (!build) {
    if (!options->quiet)
      puts("ok");
    /* The process exits next; freeing every syntax tree first costs about a
       tenth of a large check. Sanitizer builds still free for leak checks. */
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
  // Run reuses native objects, but never persists its temporary executable.
  bool cacheable = strcmp(context.target->arch, "wasm32") && !options->shared && !options->no_link &&
                   !options->emit_object &&
                   !options->emit_asm;
  if (cacheable && !options->no_cache)
    options->compiler_hash = dyn_cache_file_hash(compiler);
  if (!run && cacheable && dyn_cache_hit(&sources, options, compiler, output)) {
    if (!options->quiet)
      printf("cached %s\n", output);
    dyn_sources_free(&sources);
    free(main_path);
    free(base);
    return 0;
  }
  char object[4096], assembly[4096];
  /* A native object is private unless requested: "<output>.o" may name a
     --link input. On macOS it is kept beside the output instead, because the
     executable's debug map refers to the object's DWARF. */
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
  if ((!private_object && !kept_object && snprintf(object, sizeof(object), "%s.o", output) >= (int)sizeof(object)) ||
      snprintf(assembly, sizeof(assembly), "%s.s", output) >= (int)sizeof(assembly)) {
    fprintf(stderr, "error: output path too long\n");
    dyn_sources_free(&sources); free(main_path); free(base); return 2;
  }
  phase = timer_start();
  /* Native objects depend on source and code-generation options, not link
     inputs or output names. Reuse them when relinking or running again. */
  bool restored = cacheable && dyn_object_cache_restore(
      &sources, options, compiler, output, object);
  if (restored && options->verbose)
    fprintf(stderr, "cached native object\n");
  if (!restored) {
    DynSource module_source = {0};
    result = dyn_sources_merge(&sources, main_path, &module_source);
    module_source.context = context;
    DynIrProgram prepared;
    bool have_ir = false;
    if (!result) {
      result = dyn_codegen_prepare_owned(&module_source, options->shared, NULL, &prepared);
      have_ir = !result;
    }
    if (!result)
      result = emit_native(&module_source, &prepared, object,
          options->emit_asm ? assembly : NULL, options);
    if (have_ir)
      dyn_codegen_release(&prepared);
    dyn_source_free(&module_source);
    if (!result && cacheable)
      dyn_object_cache_store(&sources, options, compiler, output, object);
  }
  if (options->timings)
    fprintf(stderr, "timing codegen %.3f ms\n", elapsed_ms(phase));
  phase = timer_start();
  if (!result && !options->no_link)
    result = options->shared
        ? dyn_link_shared(&context, object, output, options->link_inputs,
                          options->link_input_count, options->verbose)
        : dyn_link_executable(&context, object, output, options->link_inputs,
                              options->link_input_count, options->release,
                              options->verbose);
  if (!result && !run && cacheable)
    dyn_cache_store(&sources, options, compiler, output);
  if (options->timings && !options->no_link)
    fprintf(stderr, "timing link %.3f ms\n", elapsed_ms(phase));
  if (!options->emit_object && !options->no_link) {
    if (!kept_object || run) remove(object);
    if (!strcmp(context.target->arch, "wasm32")) {
      char *imports = malloc(strlen(object) + 9);
      if (imports) { sprintf(imports, "%s.imports", object); remove(imports); free(imports); }
    }
  }
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
  /* argv[0] is commonly just "dyn" when launched through PATH. Hash the
     running executable, not a nonexistent file in the project directory. */
  char executable[4096];
  ssize_t executable_length = dyn_host_executable(executable, sizeof(executable) - 1);
  const char *compiler = argv[0];
  if (executable_length > 0 && executable_length < (ssize_t)sizeof(executable) - 1) {
    executable[executable_length] = 0;
    compiler = executable;
  }
  int result = execute_command(&o, compiler);
  {
    free(o.optimization.cpu);
    free(o.optimization.features);
  }
  for (size_t i = borrowed_links; i < o.link_input_count; ++i)
    free((void *)o.link_inputs[i]);
  return result;
}
