#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static int failure;
static void *source_test_malloc(size_t size) {
  if (failure == 1) { failure = 0; return NULL; }
  return malloc(size);
}
static size_t source_test_fread(void *p, size_t size, size_t count, FILE *stream) {
  size_t read = fread(p, size, count, stream);
  return failure == 2 && read ? read - 1 : read;
}
static int source_test_fseek(FILE *stream, long offset, int origin) {
  return failure == 3 ? -1 : fseek(stream, offset, origin);
}
#define malloc source_test_malloc
#define fread source_test_fread
#define fseek source_test_fseek
#include "../compiler/src/source.c"
#undef malloc
#undef fread
#undef fseek

int main(void) {
  char directory[] = "/tmp/dyn-source-failure-XXXXXX";
  assert(mkdtemp(directory));
  char path[128];
  snprintf(path, sizeof(path), "%s/main.dyn", directory);
  FILE *file = fopen(path, "wb");
  assert(file);
  assert(fputs("fn main() {}\n", file) >= 0);
  assert(!fclose(file));
  const int cases[] = {0, 2, 3, 1};
  for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
    failure = cases[i];
    DynSources sources;
    int status = dyn_sources_load(NULL, directory, &sources);
    assert(cases[i] ? status != 0 : status == 0);
    TSTree *retained = !status && sources.count ? dyn_source_tree(&sources.items[0]) : NULL;
    if (retained) assert(!ts_node_has_error(ts_tree_root_node(retained)));
    dyn_sources_free(&sources);
    if (retained) {
      assert(ts_node_end_byte(ts_tree_root_node(retained)) == strlen("fn main() {}\n"));
      ts_tree_delete(retained);
    }
  }
  assert(!unlink(path));
  DynSources empty;
  assert(!dyn_sources_load(NULL, directory, &empty));
  assert(empty.count == 0);
  dyn_sources_free(&empty);
  assert(!rmdir(directory));
  return 0;
}
