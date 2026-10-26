/* Reference dump for tests/selfhost-parser: parses each path argument with
   exp_parse_source and prints the reachable tree in preorder. */
#include "../src/parser.h"
#include <stdio.h>
#include <stdlib.h>

static void dump(const ExpTree *tree) {
  uint32_t id = tree->root;
  for (;;) {
    const ExpNode *n = &tree->nodes[id];
    printf("%u %u %u %u\n", n->kind, n->start, n->end, n->flags);
    if (n->first != UINT32_MAX) { id = n->first; continue; }
    while (id != tree->root && tree->nodes[id].next == UINT32_MAX) id = tree->nodes[id].parent;
    if (id == tree->root) return;
    id = tree->nodes[id].next;
  }
}

int main(int argc, char **argv) {
  ExpTree tree = {0};
  for (int i = 1; i < argc; ++i) {
    FILE *file = fopen(argv[i], "rb");
    if (!file) { perror(argv[i]); return 1; }
    fseek(file, 0, SEEK_END);
    long length = ftell(file);
    fseek(file, 0, SEEK_SET);
    char *source = malloc(length ? (size_t)length : 1);
    if (!source || fread(source, 1, (size_t)length, file) != (size_t)length) { perror(argv[i]); return 1; }
    fclose(file);
    printf("== %s\n", argv[i]);
    if (exp_parse_source(source, (size_t)length, &tree)) dump(&tree);
    else printf("error %u %s\n", tree.error_offset, tree.error);
    free(source);
  }
  exp_free(&tree);
  return 0;
}
