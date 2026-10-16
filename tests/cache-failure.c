#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <sys/wait.h>
static unsigned injected_reads;
static int inject_read_error;
static size_t failure_read(void *data, size_t size, size_t count, FILE *file) {
  if (!inject_read_error) return fread(data, size, count, file);
  ++injected_reads;
  if (injected_reads == 1 && size && count) { ((unsigned char *)data)[0] = 42; return 1; }
  return 0;
}
static int failure_error(FILE *file) { return inject_read_error ? 1 : ferror(file); }
#define fread failure_read
#define ferror failure_error
#include "../src/cache.c"
#undef fread
#undef ferror

static unsigned descriptor_count(void) {
  DIR *directory = opendir("/proc/self/fd");
  assert(directory);
  unsigned count = 0;
  while (readdir(directory)) ++count;
  closedir(directory);
  return count;
}

static void write_text(const char *path, const char *text) {
  FILE *file = fopen(path, "w");
  assert(file && fputs(text, file) >= 0);
  assert(!fclose(file));
}

int main(void) {
  unsigned before = descriptor_count();
  assert(!copy_file_verified("/tmp", "build/cache-failure-output", 0));
  assert(descriptor_count() == before);
  inject_read_error = 1;
  assert(hash_file(UINT64_C(1469598103934665603), "tests/cache-failure.c") == 0);
  assert(injected_reads == 1);
  injected_reads = 0;
  assert(!copy_file_verified("tests/cache-failure.c", "build/cache-failure-output", 0));
  assert(injected_reads == 1);
  inject_read_error = 0;
  char root[] = "/tmp/dyn-cache-unit-XXXXXX";
  assert(mkdtemp(root));
  char compiler[4096], loaded[4096], source_path[4096], object[4096], output[4096];
  snprintf(compiler, sizeof(compiler), "%s/compiler", root);
  snprintf(loaded, sizeof(loaded), "%s/asset", root);
  snprintf(source_path, sizeof(source_path), "%s/main.dyn", root);
  snprintf(object, sizeof(object), "%s/input.o", root);
  snprintf(output, sizeof(output), "%s/output.o", root);
  write_text(compiler, "compiler"); write_text(loaded, "first");
  write_text(object, "object"); write_text(output, "preserved");
  setenv("DYN_CACHE_DIR", root, 1); unsetenv("DYN_LINKER");
  char text[] = "fn main() { _ = #load /* trivia */ ( \"asset\" ) }";
  DynSource source = {.path = source_path, .text = text, .length = strlen(text)};
  DynSources sources = {.items = &source, .count = 1};
  DynOptions options = {.target = "x86_64-linux"};
  uint64_t key = codegen_key(&sources, &options, compiler);
  assert(key);
  write_text(loaded, "other");
  assert(key != codegen_key(&sources, &options, compiler));
  assert(!dyn_load_hash(0, source_path, text, strlen(text)));
  const char *ignored[] = {"// #load(\"missing\")", "/* #load(\"missing\") */", "\"#load(missing)\"", "'x' // #load"};
  for (size_t i = 0; i < sizeof(ignored) / sizeof(*ignored); ++i)
    assert(dyn_load_hash(123, source_path, ignored[i], strlen(ignored[i])) == 123);
  assert(!module_key(&sources, 0, 1, 0, 1, 1, &options, "/missing/compiler", object));
  assert(!unlink(loaded));
  assert(!codegen_key(&sources, &options, compiler));
  write_text(loaded, "first");
  assert(key == codegen_key(&sources, &options, compiler));
  options.link_input_count = 1;
  options.link_inputs[0] = "-rpath=/one";
  uint64_t link = hash_link_inputs(123, &options);
  assert(link);
  options.link_inputs[0] = "--rpath=/two";
  assert(link != hash_link_inputs(123, &options));
  char script[4200];
  snprintf(script, sizeof(script), "--version-script=%s", loaded);
  options.link_inputs[0] = script;
  link = hash_link_inputs(123, &options);
  write_text(loaded, "other");
  assert(link && link != hash_link_inputs(123, &options));
  options.link_inputs[0] = "--unknown=missing";
  assert(!hash_link_inputs(123, &options));
  options.link_input_count = 0;
  setenv("DYN_LINKER", "external", 1);
  assert(!hash_link_inputs(123, &options));
  unsetenv("DYN_LINKER");
  const char *targets[] = {"x86_64-macos", "aarch64-windows", "riscv64-linux"};
  const char *starts[] = {"dynrt_macos_x64_start.o", "dynrt_windows_arm64_start.o", "dynrt_riscv64_start.o"};
  const char *supports[] = {"dynrt_macos_x64_support.o", "dynrt_windows_arm64_support.o", "dynrt_riscv64_support.o"};
  for (size_t i = 0; i < 3; ++i) {
    char start[4096], support[4096];
    snprintf(start, sizeof(start), "%s/%s", root, starts[i]);
    snprintf(support, sizeof(support), "%s/%s", root, supports[i]);
    write_text(start, "start"); write_text(support, "support");
    options.target = targets[i];
    uint64_t runtime = hash_runtime(123, &options, compiler);
    assert(runtime);
    write_text(support, "changed");
    assert(runtime != hash_runtime(123, &options, compiler));
  }
  options.target = "x86_64-linux";
  dyn_object_cache_store(&sources, &options, compiler, "first-output", object);
  assert(dyn_object_cache_restore(&sources, &options, compiler, "other-output", output));
  assert(dyn_cache_file_hash(object) == dyn_cache_file_hash(output));
  char artifact[4096], metadata[4096];
  assert(object_cache_paths(codegen_key(&sources, &options, compiler), artifact,
                            sizeof(artifact), metadata, sizeof(metadata)));
  write_text(artifact, "corrupt"); write_text(output, "preserved");
  uint64_t preserved = dyn_cache_file_hash(output);
  assert(!dyn_object_cache_restore(&sources, &options, compiler, "other-output", output));
  assert(preserved == dyn_cache_file_hash(output));
  /* Concurrent producers must publish complete artifacts, and a consumer
     verifies the bytes it actually copies rather than a previous pathname. */
  pid_t children[4];
  for (size_t child = 0; child < 4; ++child) {
    children[child] = fork();
    assert(children[child] >= 0);
    if (!children[child]) {
      char child_output[4096];
      snprintf(child_output, sizeof(child_output), "%s/child-%zu.o", root, child);
      for (unsigned iteration = 0; iteration < 20; ++iteration) {
        dyn_object_cache_store(&sources, &options, compiler, "unused", object);
        assert(dyn_object_cache_restore(&sources, &options, compiler, "unused", child_output));
        assert(dyn_cache_file_hash(child_output) == dyn_cache_file_hash(object));
      }
      _exit(0);
    }
  }
  for (size_t child = 0; child < 4; ++child) {
    int status = 0;
    assert(waitpid(children[child], &status, 0) == children[child]);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
  }
  options.no_cache = true;
  assert(!dyn_object_cache_restore(&sources, &options, compiler, "other-output", output));
  uint64_t bytes = 0, files = 0;
  assert(!cache_walk(root, true, &bytes, &files));
  assert(!rmdir(root));
  return 0;
}
