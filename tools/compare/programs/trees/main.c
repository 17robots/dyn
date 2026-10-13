#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define MAX_DEPTH 18

typedef struct Node {
  struct Node *left, *right;
} Node;

static Node *build_tree(int depth) {
  Node *node = calloc(1, sizeof(Node));
  if (depth > 0) {
    node->left = build_tree(depth - 1);
    node->right = build_tree(depth - 1);
  }
  return node;
}

static int64_t count(Node *node) {
  if (!node->left) return 1;
  return 1 + count(node->left) + count(node->right);
}

static void release(Node *node) {
  if (node->left) {
    release(node->left);
    release(node->right);
  }
  free(node);
}

// Each node is malloc'd and freed individually.
int main(void) {
  int64_t total = 0;
  for (int depth = 4; depth <= MAX_DEPTH; depth += 2) {
    long iterations = 1L << (MAX_DEPTH - depth + 4);
    for (long i = 0; i < iterations; i++) {
      Node *tree = build_tree(depth);
      total += count(tree);
      release(tree);
    }
  }
  printf("%lld\n", (long long)total);
  return 0;
}
