#define _POSIX_C_SOURCE 200809L
/* Parser invariants over std and test sources and deterministic mutations:
   a recovering parse of valid text equals the strict parse; for invalid text
   its first recovered error is the strict error, spans stay in bounds, and
   every reachable node lies inside its parent. */
#include "parser.h"
#include <assert.h>
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static unsigned long long seed = 1;
static unsigned cases, recovered;
static unsigned next_random(void) {
  seed = seed * 6364136223846793005ULL + 1442695040888963407ULL;
  return (unsigned)(seed >> 33);
}
static void reachable(const ExpTree *tree, uint32_t id, uint32_t start, uint32_t end, unsigned depth) {
  assert(depth < 4096);
  const ExpNode *node = &tree->nodes[id];
  assert(node->start <= node->end && start <= node->start && node->end <= end);
  for (uint32_t child = node->first; child != UINT32_MAX; child = tree->nodes[child].next) {
    assert(tree->nodes[child].parent == id);
    reachable(tree, child, node->start, node->end, depth + 1);
  }
}
static void check(const char *text, size_t length, const char *name) {
  ExpTree strict = {0}, recovering = {0};
  ExpOptions options = {.recover = true};
  bool strict_ok = exp_parse_source(text, length, &strict);
  bool recovering_ok = exp_parse_source_with_options(text, length, &recovering, &options);
  ++cases;
  if (strict_ok) {
    if (!recovering_ok || recovering.error_count || recovering.count != strict.count ||
        memcmp(recovering.nodes, strict.nodes, strict.count * sizeof(*strict.nodes))) {
      fprintf(stderr, "%s: recovery changed a valid tree\n", name);
      abort();
    }
  } else if (strict.error_kind == EXP_SYNTAX_ERROR) {
    if (!recovering_ok && recovering.error_kind == EXP_SYNTAX_ERROR) {
      fprintf(stderr, "%s: recovery failed: %s\n", name, recovering.error);
      abort();
    }
    if (recovering_ok) {
      if (!recovering.error_count || recovering.errors[0].offset != strict.error_offset) {
        fprintf(stderr, "%s: first recovered error differs\n", name);
        abort();
      }
      reachable(&recovering, recovering.root, 0, (uint32_t)length, 0);
      ++recovered;
    }
  }
  exp_free(&strict);
  exp_free(&recovering);
}
static void mutate(const char *text, size_t length, const char *name) {
  static const char pieces[] = "{}()[],.:=\n\"'/*";
  char *copy = malloc(length + 2);
  assert(copy);
  for (unsigned k = 0; k < 12; ++k) {
    memcpy(copy, text, length);
    size_t size = length, at = length ? next_random() % length : 0;
    unsigned operation = next_random() % 4;
    if (operation == 0 && size) { memmove(copy + at, copy + at + 1, size - at - 1); --size; }
    else if (operation == 1) {
      memmove(copy + at + 1, copy + at, size - at);
      copy[at] = pieces[next_random() % (sizeof(pieces) - 1)];
      ++size;
    } else if (operation == 2) size = at;
    else if (size) copy[at] = pieces[next_random() % (sizeof(pieces) - 1)];
    check(copy, size, name);
  }
  free(copy);
}
static void walk(const char *directory) {
  DIR *dir = opendir(directory);
  if (!dir) return;
  struct dirent *entry;
  while ((entry = readdir(dir))) {
    if (entry->d_name[0] == '.') continue;
    char path[4096];
    snprintf(path, sizeof(path), "%s/%s", directory, entry->d_name);
    struct stat info;
    if (stat(path, &info)) continue;
    if (S_ISDIR(info.st_mode)) { walk(path); continue; }
    size_t n = strlen(entry->d_name);
    if (n < 5 || strcmp(entry->d_name + n - 4, ".dyn")) continue;
    FILE *file = fopen(path, "rb");
    if (!file) continue;
    char *text = malloc((size_t)info.st_size + 1);
    assert(text);
    size_t length = fread(text, 1, (size_t)info.st_size, file);
    fclose(file);
    check(text, length, path);
    mutate(text, length, path);
    free(text);
  }
  closedir(dir);
}
int main(int argc, char **argv) {
  for (int i = 1; i < argc; ++i) walk(argv[i]);
  if (argc < 2) { walk("std"); walk("tests"); }
  assert(cases > 1000 && recovered > 100);
  printf("PASS parser recovery invariants: %u sources and mutations, %u recovered\n", cases, recovered);
  return 0;
}
