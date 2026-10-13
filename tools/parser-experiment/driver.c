#define _POSIX_C_SOURCE 200809L
#include "parser.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <tree_sitter/api.h>

extern const TSLanguage *tree_sitter_dyn(void);
#define NONE UINT32_MAX
static const char prefix[] = "const result := ";
static const char *const kinds[] = {"identifier", "number_", "bool_", "null_", "string_", "char_", "group", "unary_prefix", "binary", "unary_postfix", "field_access", "call", "index", "slice", "wrap", "len"};
static void fast_print(const ExpTree *tree, uint32_t id) {
  ExpNode n = tree->nodes[id];
  printf("[\"%s\",%u,%u,%u,%u", kinds[n.kind], n.start, n.end, n.operator_start, n.operator_length);
  for (uint32_t child = n.first; child != NONE; child = tree->nodes[child].next) {
    putchar(','); fast_print(tree, child);
  }
  putchar(']');
}
static TSNode unwrap(TSNode node) {
  while (!strcmp(ts_node_type(node), "primary") || !strcmp(ts_node_type(node), "expression") || !strcmp(ts_node_type(node), "literal")) {
    TSNode next = {0};
    for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i) {
      TSNode child = ts_node_named_child(node, i);
      if (!ts_node_is_extra(child)) { next = child; break; }
    }
    node = next;
  }
  return node;
}
static bool leaf(const char *kind) {
  for (unsigned i = 0; i < 6; ++i) if (!strcmp(kind, kinds[i])) return true;
  return false;
}
static void empty(uint32_t offset) { printf("[\"group\",%u,%u,0,0]", offset, offset); }
static void oracle_print(TSNode node) {
  node = unwrap(node);
  const char *kind = ts_node_type(node);
  uint32_t base = sizeof(prefix) - 1, start = ts_node_start_byte(node) - base, end = ts_node_end_byte(node) - base;
  uint32_t op = 0, oplen = 0, range = NONE, open = 0, close = 0;
  bool operation = !strcmp(kind, "binary") || !strcmp(kind, "unary_prefix") || !strcmp(kind, "unary_postfix");
  bool index = !strcmp(kind, "index");
  for (uint32_t i = 0; i < ts_node_child_count(node); ++i) {
    TSNode child = ts_node_child(node, i);
    if (ts_node_is_named(child)) continue;
    if (operation) { op = ts_node_start_byte(child) - base; oplen = ts_node_end_byte(child) - ts_node_start_byte(child); }
    if (index && !strcmp(ts_node_type(child), "..")) range = ts_node_start_byte(child) - base;
    if (index && !strcmp(ts_node_type(child), "[")) open = ts_node_end_byte(child) - base;
    if (index && !strcmp(ts_node_type(child), "]")) close = ts_node_start_byte(child) - base;
  }
  printf("[\"%s\",%u,%u,%u,%u", range != NONE ? "slice" : kind, start, end, op, oplen);
  if (!leaf(kind)) {
    unsigned named = 0; bool low = false, high = false;
    for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i) {
      TSNode child = ts_node_named_child(node, i);
      if (ts_node_is_extra(child)) continue;
      if (range != NONE && named) {
        if (ts_node_start_byte(child) - base < range) low = true;
        else { high = true; if (!low) { putchar(','); empty(open); } }
      }
      putchar(','); oracle_print(child); ++named;
    }
    if (range != NONE) {
      if (!low && !high) { putchar(','); empty(open); }
      if (!high) { putchar(','); empty(close); }
    }
  }
  putchar(']');
}
int main(int argc, char **argv) {
  if (argc < 2 || argc > 3) return 2;
  size_t length = 0, capacity = 4096;
  char *text = malloc(capacity);
  if (!text) return 2;
  int c;
  while ((c = getchar()) != EOF) {
    if (length + 1 == capacity) {
      capacity *= 2; char *next = realloc(text, capacity);
      if (!next) { free(text); return 2; } text = next;
    }
    text[length++] = (char)c;
  }
  text[length] = 0;
  bool fast = !strcmp(argv[1], "fast"), oracle = !strcmp(argv[1], "tree");
  if (!fast && !oracle) { free(text); return 2; }
  unsigned repeats = argc == 3 ? (unsigned)strtoul(argv[2], NULL, 10) : 1;
  if (!repeats) { free(text); return 2; }
  ExpTree result = {0};
  TSParser *parser = NULL; char *wrapped = NULL;
  if (oracle) {
    parser = ts_parser_new();
    if (!parser || !ts_parser_set_language(parser, tree_sitter_dyn())) return 2;
    wrapped = malloc(sizeof(prefix) + length);
    if (!wrapped) return 2;
    memcpy(wrapped, prefix, sizeof(prefix) - 1); memcpy(wrapped + sizeof(prefix) - 1, text, length + 1);
  }
  bool valid = true;
  clock_t start = clock();
  for (unsigned i = 0; i < repeats; ++i) {
    if (fast) {
      valid = exp_parse(text, length, &result);
      if (repeats == 1 && valid) { fast_print(&result, result.root); putchar('\n'); }
    } else {
      TSTree *tree = ts_parser_parse_string(parser, NULL, wrapped, (uint32_t)(length + sizeof(prefix) - 1));
      TSNode root = tree ? ts_tree_root_node(tree) : (TSNode){0};
      valid = tree && !ts_node_has_error(root);
      if (valid && repeats == 1) {
        TSNode declaration = ts_node_named_child(root, 0);
        TSNode constant = ts_node_named_child(declaration, 0);
        TSNode variable = ts_node_named_child(constant, 0);
        TSNode expression = ts_node_named_child(variable, ts_node_named_child_count(variable) - 1);
        oracle_print(expression); putchar('\n');
      }
      if (tree) ts_tree_delete(tree);
    }
    if (!valid) break;
  }
  if (!valid) fprintf(stderr, "invalid expression%s%s at %u\n", fast ? ": " : "", fast ? result.error : "", result.error_offset);
  else if (repeats > 1) printf("{\"seconds\":%.9f,\"repeats\":%u,\"nodes\":%u,\"retained_bytes\":%zu}\n", (double)(clock() - start) / CLOCKS_PER_SEC, repeats, result.count, (size_t)result.capacity * sizeof(ExpNode));
  exp_free(&result); if (parser) ts_parser_delete(parser); free(wrapped); free(text);
  return valid ? 0 : 1;
}
