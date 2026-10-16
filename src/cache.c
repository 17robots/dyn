#define _POSIX_C_SOURCE 200809L
#include "dyn_load.h"
#include "dyn.h"
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static uint64_t hash_bytes(uint64_t hash, const void *data, size_t length) {
  if (!hash)
    return 0; /* Zero is reserved for an unavailable cache key. */
  const unsigned char *bytes = data;
  for (size_t i = 0; i < length; ++i) {
    hash ^= bytes[i];
    hash *= UINT64_C(1099511628211);
  }
  return hash;
}

static bool make_directories(char *path) {
  char *start = path + 1;
#ifdef _WIN32
  if (strlen(path) > 2 && path[1] == ':') start = path + 3;
#endif
  for (char *p = start; *p; ++p)
    if (*p == '/') {
      *p = 0;
      if (mkdir(path, 0777) && errno != EEXIST) {
        *p = '/';
        return false;
      }
      *p = '/';
    }
  return !mkdir(path, 0777) || errno == EEXIST;
}

bool dyn_cache_directory(char *path, size_t capacity) {
  const char *configured = getenv("DYN_CACHE_DIR");
  const char *xdg = getenv("XDG_CACHE_HOME"), *home = getenv("HOME");
#ifdef _WIN32
  if (!home) home = getenv("USERPROFILE");
  if (!xdg) xdg = getenv("LOCALAPPDATA");
  long cache_identity = (long)GetCurrentProcessId();
#else
  long cache_identity = (long)getuid();
#endif
  int n;
  if (configured && *configured)
    n = snprintf(path, capacity, "%s", configured);
  else if (xdg && *xdg)
    n = snprintf(path, capacity, "%s/dyn/c-frontend-" DYN_FRONTEND_VERSION, xdg);
  else if (home && *home)
    n = snprintf(path, capacity, "%s/.cache/dyn/c-frontend-" DYN_FRONTEND_VERSION, home);
  else
    n = snprintf(path, capacity, "/tmp/dyn-cache-%ld/c-frontend-" DYN_FRONTEND_VERSION,
                 cache_identity);
  return n > 0 && (size_t)n < capacity && make_directories(path);
}

static int cache_walk(const char *path, bool remove_files, uint64_t *bytes,
                      uint64_t *files) {
  DIR *directory = opendir(path);
  if (!directory)
    return errno == ENOENT ? 0 : 2;
  struct dirent *entry;
  int result = 0;
  while (!result && (entry = readdir(directory))) {
    if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, ".."))
      continue;
    char child[4096];
    if (snprintf(child, sizeof(child), "%s/%s", path, entry->d_name) >=
        (int)sizeof(child)) {
      result = 2;
      break;
    }
    struct stat st;
    if (lstat(child, &st)) {
      result = 2;
      break;
    }
    if (S_ISDIR(st.st_mode)) {
      result = cache_walk(child, remove_files, bytes, files);
      if (remove_files && !result && rmdir(child))
        result = 2;
    } else {
      *bytes += (uint64_t)st.st_size;
      ++*files;
      if (remove_files && unlink(child))
        result = 2;
    }
  }
  closedir(directory);
  return result;
}

int dyn_cache_command(const char *action) {
  char path[4096];
  if (!dyn_cache_directory(path, sizeof(path)))
    return 2;
  uint64_t bytes = 0, files = 0;
  if (!action || !strcmp(action, "stats")) {
    int result = cache_walk(path, false, &bytes, &files);
    if (!result)
      printf("cache %s: %llu files, %llu bytes\n", path,
             (unsigned long long)files, (unsigned long long)bytes);
    return result;
  }
  if (!strcmp(action, "clean")) {
    int result = cache_walk(path, true, &bytes, &files);
    if (!result)
      printf("removed %llu cache files (%llu bytes)\n",
             (unsigned long long)files, (unsigned long long)bytes);
    return result;
  }
  fprintf(stderr, "error: cache expects 'stats' or 'clean'\n");
  return 2;
}

static uint64_t hash_file(uint64_t hash, const char *path) {
  if (!hash)
    return 0;
  FILE *file = fopen(path, "rb");
  if (!file)
    return 0;
  unsigned char bytes[16384];
  size_t count;
  do {
    count = fread(bytes, 1, sizeof(bytes), file);
    hash = hash_bytes(hash, bytes, count);
    if (ferror(file)) {
      hash = 0;
      break;
    }
  } while (count == sizeof(bytes));
  if (fclose(file))
    hash = 0;
  return hash;
}

static int hash_module(const DynSources *sources, size_t first, size_t count,
                       void *context, uint64_t *value) {
  (void)context;
  uint64_t hash = UINT64_C(1469598103934665603);
  for (size_t i = first; i < first + count; ++i) {
    size_t path_length = strlen(sources->items[i].path);
    hash = hash_bytes(hash, &path_length, sizeof(path_length));
    hash = hash_bytes(hash, sources->items[i].path, path_length);
    hash = hash_bytes(hash, &sources->items[i].length, sizeof(sources->items[i].length));
    hash = hash_bytes(hash, sources->items[i].text, sources->items[i].length);
    hash = dyn_load_hash(hash, sources->items[i].path, sources->items[i].text,
                         sources->items[i].length);
  }
  *value = hash;
  return 0;
}

uint64_t dyn_cache_file_hash(const char *compiler_path) {
  return hash_file(UINT64_C(1469598103934665603), compiler_path);
}
static uint64_t compiler_key(const DynOptions *options, const char *path) {
  return options->compiler_hash ? options->compiler_hash
                                : dyn_cache_file_hash(path);
}
static uint64_t hash_project_sources(uint64_t hash, const DynSources *sources) {
  /* Fingerprinting is short CPU work. Forking a build worker for each module
     costs more than hashing its bytes. Preserve the existing grouped key. */
  for (size_t first = 0; first < sources->count;) {
    const char *path = sources->items[first].path, *slash = strrchr(path, '/');
    size_t length = slash ? (size_t)(slash - path) : 0, end = first + 1;
    while (end < sources->count) {
      const char *next = sources->items[end].path, *last = strrchr(next, '/');
      size_t size = last ? (size_t)(last - next) : 0;
      if (size != length || memcmp(path, next, length)) break;
      ++end;
    }
    uint64_t module = 0;
    hash_module(sources, first, end - first, NULL, &module);
    if (!module) return 0;
    hash = hash_bytes(hash, &module, sizeof(module));
    first = end;
  }
  return hash;
}

static uint64_t hash_runtime(uint64_t hash, const DynOptions *options,
                             const char *compiler_path) {
  const char *start = options->release ? "dynrt_release.o" : "dynrt_start.o";
  const char *support = "dynrt_support.o";
  if (!strcmp(options->target, "aarch64-linux")) {
    start = options->release ? "dynrt_aarch64_release.o" : "dynrt_aarch64_start.o";
    support = "dynrt_aarch64_support.o";
  } else if (!strcmp(options->target, "aarch64-macos")) {
    start = "dynrt_macos_start.o"; support = "dynrt_macos_support.o";
  } else if (!strcmp(options->target, "x86_64-macos")) {
    start = "dynrt_macos_x64_start.o"; support = "dynrt_macos_x64_support.o";
  } else if (!strcmp(options->target, "aarch64-windows")) {
    start = "dynrt_windows_arm64_start.o"; support = "dynrt_windows_arm64_support.o";
  } else if (!strcmp(options->target, "riscv64-linux")) {
    start = options->release ? "dynrt_riscv64_release.o" : "dynrt_riscv64_start.o";
    support = "dynrt_riscv64_support.o";
  } else if (!strcmp(options->target, "x86_64-windows")) {
    start = "dynrt_windows_start.o"; support = "dynrt_windows_support.o";
  }
  const char *slash = strrchr(compiler_path, '/');
  if (!slash) return 0;
  size_t directory = (size_t)(slash - compiler_path);
  if (directory > 4000) return 0;
  bool darwin = strstr(options->target, "-macos") != NULL;
  const char *names[] = {start, support, "libSystem.tbd"};
  for (size_t i = 0; hash && i < (darwin ? 3u : 2u); ++i) {
    char path[4096];
    int n = snprintf(path, sizeof(path), "%.*s/%s", (int)directory, compiler_path, names[i]);
    if (n < 0 || (size_t)n >= sizeof(path)) return 0;
    if (access(path, R_OK)) {
      n = snprintf(path, sizeof(path), "%.*s/../lib/dyn/%s", (int)directory, compiler_path, names[i]);
      if (n < 0 || (size_t)n >= sizeof(path)) return 0;
    }
    if (i == 2) {
      bool present = !access(path, R_OK);
      hash = hash_bytes(hash, &present, sizeof(present));
      if (!present) continue; /* Matches the linker's optional system stub. */
    }
    hash = hash_file(hash, path);
  }
  return hash;
}

/* Include resolved host features, not just the word "native": caches can be
   shared by machines. Profile content changes must invalidate final outputs. */
static uint64_t optimization_key(uint64_t hash, const DynOptions *options) {
  const DynOptimization *o = &options->optimization;
  unsigned level = o->level ? o->level : 2;
  hash = hash_bytes(hash, &level, sizeof(level));
  const char *cpu = o->cpu ? o->cpu : "generic";
  const char *features = o->features ? o->features : "";
  hash = hash_bytes(hash, cpu, strlen(cpu) + 1);
  hash = hash_bytes(hash, features, strlen(features) + 1);
  bool has_profile = o->sample_profile != NULL;
  hash = hash_bytes(hash, &has_profile, sizeof(has_profile));
  if (has_profile) hash = hash_bytes(hash, &o->profile_hash, sizeof(o->profile_hash));
  return hash;
}

/* Linker arguments are not all files. Include spelling/order (SONAME and
   search semantics can depend on paths), and contents of file-valued options.
   Unknown options cannot be safely fingerprinted without resolving their
   dependencies, so leave executable caching unavailable for those commands. */
static uint64_t hash_link_inputs(uint64_t hash, const DynOptions *options) {
  const char *selection = getenv("DYN_LINKER");
  if (selection && *selection && strcmp(selection, "builtin")) return 0;
  hash = hash_bytes(hash, &options->link_input_count, sizeof(options->link_input_count));
  for (size_t i = 0; hash && i < options->link_input_count; ++i) {
    const char *input = options->link_inputs[i];
    hash = hash_bytes(hash, input, strlen(input) + 1);
    if (!strncmp(input, "-rpath=", 7) || !strncmp(input, "--rpath=", 8)) continue;
    if (!strncmp(input, "--version-script=", 17)) input += 17;
    else if (*input == '-') return 0;
    hash = hash_file(hash, input);
  }
  return hash;
}

static uint64_t build_key(const DynSources *sources, const DynOptions *options,
                          const char *compiler_path) {
  uint64_t hash = compiler_key(options, compiler_path);
  hash = hash_bytes(hash, options->target, strlen(options->target));
  hash = hash_bytes(hash, &options->release, sizeof(options->release));
  hash = hash_bytes(hash, &options->no_lto, sizeof(options->no_lto));
  hash = optimization_key(hash, options);
  hash = hash_bytes(hash, &options->debug_info, sizeof(options->debug_info));
  hash = hash_bytes(hash, &options->native_backend, sizeof(options->native_backend));
  hash = hash_project_sources(hash, sources);
  hash = hash_link_inputs(hash, options);
  return hash_runtime(hash, options, compiler_path);
}

static uint64_t codegen_key(const DynSources *sources,
                            const DynOptions *options,
                            const char *compiler_path) {
  uint64_t hash = compiler_key(options, compiler_path);
  hash = hash_bytes(hash, options->target, strlen(options->target));
  hash = hash_bytes(hash, &options->release, sizeof(options->release));
  hash = hash_bytes(hash, &options->no_lto, sizeof(options->no_lto));
  hash = optimization_key(hash, options);
  hash = hash_bytes(hash, &options->debug_info, sizeof(options->debug_info));
  hash = hash_bytes(hash, &options->native_backend, sizeof(options->native_backend));
  hash = hash_project_sources(hash, sources);
  return hash;
}

static char *suffixed_path(const char *output, const char *suffix) {
  size_t a = strlen(output), b = strlen(suffix);
  char *path = malloc(a + b + 1);
  if (!path)
    return NULL;
  memcpy(path, output, a);
  memcpy(path + a, suffix, b + 1);
  return path;
}

static bool copy_file_contents(const char *from, const char *to) {
  FILE *input = fopen(from, "rb"), *output = input ? fopen(to, "wb") : NULL;
  if (!output) {
    if (input)
      fclose(input);
    return false;
  }
  unsigned char bytes[16384];
  size_t count;
  bool ok = true;
  do {
    count = fread(bytes, 1, sizeof(bytes), input);
    if (ferror(input) || fwrite(bytes, 1, count, output) != count) {
      ok = false;
      break;
    }
  } while (count == sizeof(bytes));
  if (ferror(input))
    ok = false;
  if (fclose(output) != 0)
    ok = false;
  fclose(input);
  if (!ok)
    remove(to);
  return ok;
}

static bool cache_replace(const char *from, const char *to) {
#ifdef _WIN32
  return MoveFileExA(from, to, MOVEFILE_REPLACE_EXISTING) != 0;
#else
  return rename(from, to) == 0;
#endif
}

/* Publish complete artifacts only; failed restore must preserve the caller's
   output. A unique temporary also keeps concurrent writers independent. */
static bool copy_file_verified(const char *from, const char *to, uint64_t digest) {
  char *temporary = suffixed_path(to, ".XXXXXX");
  if (!temporary) return false;
  int descriptor = mkstemp(temporary);
  bool ok = descriptor >= 0;
  if (ok) close(descriptor);
  if (ok) ok = copy_file_contents(from, temporary);
  if (ok && digest) ok = hash_file(UINT64_C(1469598103934665603), temporary) == digest;
  if (ok) ok = cache_replace(temporary, to);
  if (!ok) remove(temporary);
  free(temporary);
  return ok;
}

static bool store_digest(const char *path, uint64_t key, uint64_t digest) {
  char *temporary = suffixed_path(path, ".XXXXXX");
  if (!temporary) return false;
  int descriptor = mkstemp(temporary);
  FILE *file = descriptor < 0 ? NULL : fdopen(descriptor, "w");
  if (!file && descriptor >= 0) close(descriptor);
  bool ok = file && fprintf(file, "%016llx %016llx\n",
                            (unsigned long long)key, (unsigned long long)digest) > 0;
  if (file && fclose(file)) ok = false;
  if (ok) ok = cache_replace(temporary, path);
  if (!ok) remove(temporary);
  free(temporary);
  return ok;
}

static char *cache_path(const char *output) {
  size_t length = strlen(output);
  char *path = malloc(length + sizeof(".dyncache"));
  if (!path)
    return NULL;
  memcpy(path, output, length);
  memcpy(path + length, ".dyncache", sizeof(".dyncache"));
  return path;
}

bool dyn_cache_hit(const DynSources *sources, const DynOptions *options,
                   const char *compiler_path, const char *output) {
  struct stat status;
  if (options->no_cache || stat(output, &status) != 0 ||
      !S_ISREG(status.st_mode))
    return false;
  char *path = cache_path(output);
  if (!path)
    return false;
  FILE *file = fopen(path, "r");
  unsigned long long stored = 0, artifact = 0;
  bool hit =
      file && fscanf(file, "%llx %llx", &stored, &artifact) == 2 && stored &&
      artifact &&
      (uint64_t)stored == build_key(sources, options, compiler_path) &&
      (uint64_t)artifact == hash_file(UINT64_C(1469598103934665603), output);
  if (file)
    fclose(file);
  free(path);
  return hit;
}

void dyn_cache_store(const DynSources *sources, const DynOptions *options,
                     const char *compiler_path, const char *output) {
  if (options->no_cache)
    return;
  char *path = cache_path(output);
  if (!path)
    return;
  uint64_t key = build_key(sources, options, compiler_path);
  uint64_t digest = hash_file(UINT64_C(1469598103934665603), output);
  if (key && digest) store_digest(path, key, digest);
  free(path);
}

static bool object_cache_paths(uint64_t key, char *artifact, size_t capacity,
                               char *metadata, size_t metadata_capacity) {
  char root[4096];
  if (!key || !dyn_cache_directory(root, sizeof(root))) return false;
  int n = snprintf(artifact, capacity, "%s/native-%016llx.o", root,
                   (unsigned long long)key);
  if (n < 0 || (size_t)n >= capacity) return false;
  n = snprintf(metadata, metadata_capacity, "%s.sum", artifact);
  return n >= 0 && (size_t)n < metadata_capacity;
}

bool dyn_object_cache_restore(const DynSources *sources,
                              const DynOptions *options,
                              const char *compiler_path, const char *output,
                              const char *object) {
  (void)output; /* Native objects are reusable across output paths and run. */
  if (options->no_cache) return false;
  char artifact[4096], metadata[4096];
  uint64_t key = codegen_key(sources, options, compiler_path);
  if (!object_cache_paths(key, artifact, sizeof(artifact), metadata, sizeof(metadata))) return false;
  FILE *file = fopen(metadata, "r");
  unsigned long long stored = 0, digest = 0;
  bool hit = file && fscanf(file, "%llx %llx", &stored, &digest) == 2 &&
             stored == key && digest;
  if (file) fclose(file);
  return hit && copy_file_verified(artifact, object, (uint64_t)digest);
}

void dyn_object_cache_store(const DynSources *sources,
                            const DynOptions *options,
                            const char *compiler_path, const char *output,
                            const char *object) {
  (void)output;
  if (options->no_cache) return;
  char artifact[4096], metadata[4096];
  uint64_t key = codegen_key(sources, options, compiler_path);
  if (!object_cache_paths(key, artifact, sizeof(artifact), metadata, sizeof(metadata))) return;
  uint64_t digest = hash_file(UINT64_C(1469598103934665603), object);
  if (digest && copy_file_verified(object, artifact, digest))
    store_digest(metadata, key, digest);
}

/* One artifact per rewritten module. The key deliberately excludes output and
   link inputs: identical module code is reusable across executables and a
   link-only change never triggers code generation. Stores are atomic, so process workers
   may populate the same cache safely. */
/* A chunk depends on its own source files and on the program interface
   (types, globals, signatures). Edits to other files' function bodies leave
   its key unchanged. */
static uint64_t module_key(const DynSources *sources, size_t first,
                           size_t count, unsigned chunk, unsigned chunks,
                           uint64_t interface_hash, const DynOptions *options,
                           const char *compiler_path, const char *object) {
  uint64_t hash = compiler_key(options, compiler_path);
  hash = hash_bytes(hash, &chunk, sizeof(chunk));
  hash = hash_bytes(hash, &chunks, sizeof(chunks));
  hash = hash_bytes(hash, options->target, strlen(options->target));
  hash = hash_bytes(hash, &options->release, sizeof(options->release));
  hash = hash_bytes(hash, &options->no_lto, sizeof(options->no_lto));
  hash = optimization_key(hash, options);
  hash = hash_bytes(hash, &options->debug_info, sizeof(options->debug_info));
  size_t object_length = strlen(object);
  bool bitcode =
      object_length >= 3 && !strcmp(object + object_length - 3, ".bc");
  hash = hash_bytes(hash, &bitcode, sizeof(bitcode));
  hash = hash_bytes(hash, &interface_hash, sizeof(interface_hash));
  /* The module's directory decides symbol names, even for an empty chunk. */
  hash = hash_bytes(hash, sources->items[first].path,
                    strlen(sources->items[first].path));
  for (size_t i = first; i < first + count; ++i) {
    const DynSource *source = &sources->items[i];
    if (dyn_chunk_of_path(source->path, chunks) != chunk)
      continue;
    hash = hash_bytes(hash, source->path, strlen(source->path));
    hash = hash_bytes(hash, &source->length, sizeof(source->length));
    hash = hash_bytes(hash, source->text, source->length);
    hash = dyn_load_hash(hash, source->path, source->text, source->length);
  }
  return hash;
}

static bool module_artifact(char *path, size_t capacity, const char *root,
                            uint64_t key) {
  if (mkdir(root, 0777) && errno != EEXIST)
    return false;
  int n =
      snprintf(path, capacity, "%s/%016llx.o", root, (unsigned long long)key);
  return n > 0 && (size_t)n < capacity;
}

bool dyn_module_cache_restore(const DynSources *sources, size_t first,
                              size_t count, unsigned chunk, unsigned chunks, uint64_t interface_hash, const DynOptions *options,
                              const char *compiler_path, const char *cache_root,
                              const char *object) {
  if (options->no_cache || !cache_root)
    return false;
  char artifact[4096];
  uint64_t key =
      module_key(sources, first, count, chunk, chunks, interface_hash, options, compiler_path, object);
  if (!key || !module_artifact(artifact, sizeof(artifact), cache_root, key))
    return false;
  char metadata[4096];
  if (snprintf(metadata, sizeof(metadata), "%s.sum", artifact) >=
      (int)sizeof(metadata))
    return false;
  FILE *file = fopen(metadata, "r");
  unsigned long long digest = 0;
  bool valid =
      file && fscanf(file, "%llx", &digest) == 1 && digest &&
      (uint64_t)digest == hash_file(UINT64_C(1469598103934665603), artifact);
  if (file)
    fclose(file);
  return valid && copy_file_verified(artifact, object, (uint64_t)digest);
}

void dyn_module_cache_store(const DynSources *sources, size_t first,
                            size_t count, unsigned chunk, unsigned chunks, uint64_t interface_hash, const DynOptions *options,
                            const char *compiler_path, const char *cache_root,
                            const char *object) {
  if (options->no_cache || !cache_root)
    return;
  char artifact[4096], temporary[4096], metadata[4096],
      metadata_temporary[4096];
  uint64_t key =
      module_key(sources, first, count, chunk, chunks, interface_hash, options, compiler_path, object);
  if (!key || !module_artifact(artifact, sizeof(artifact), cache_root, key) ||
      snprintf(temporary, sizeof(temporary), "%s.%ld.tmp", artifact,
               (long)getpid()) >= (int)sizeof(temporary) ||
      snprintf(metadata, sizeof(metadata), "%s.sum", artifact) >=
          (int)sizeof(metadata) ||
      snprintf(metadata_temporary, sizeof(metadata_temporary), "%s.%ld.tmp",
               metadata, (long)getpid()) >= (int)sizeof(metadata_temporary))
    return;
  uint64_t digest = hash_file(UINT64_C(1469598103934665603), object);
  if (!digest || !copy_file_verified(object, temporary, digest) || !cache_replace(temporary, artifact)) {
    remove(temporary);
    return;
  }
  FILE *file = fopen(metadata_temporary, "w");
  if (!file)
    return;
  fprintf(
      file, "%016llx\n",
      (unsigned long long)digest);
  if (fclose(file) || !cache_replace(metadata_temporary, metadata))
    remove(metadata_temporary);
}
