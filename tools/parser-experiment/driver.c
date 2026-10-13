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
static uint32_t base = sizeof(prefix) - 1;
static const char *const kinds[] = {"identifier", "number_", "bool_", "null_", "string_", "char_", "group", "unary_prefix", "binary", "unary_postfix", "field_access", "call", "index", "slice", "wrap", "len", "type", "type_argument", "primitive", "type_parameter", "field_type", "pointer_type", "array_type", "fn_type", "cast", "size", "align", "offset", "typeof", "load", "syscall", "struct_literal", "struct_literal_member", "array_literal"};
static bool fast_print(const ExpTree *tree, uint32_t id) {
  /* Explicit traversal stack: long left-associated trees need not consume the C stack. */
  uint32_t *pending = malloc((size_t)tree->count * sizeof(*pending));
  if (!pending) return false;
  uint32_t depth = 0;
  for (;;) {
    ExpNode n = tree->nodes[id];
    printf("[\"%s\",%u,%u,%u,%u,%u,%u", n.kind >= 1000 ? exp_source_kind(n.kind) : kinds[n.kind], n.start, n.end, n.operator_start, n.operator_length, n.flags, n.field);
    if (n.first != NONE) {
      pending[depth++] = tree->nodes[n.first].next;
      id = n.first; putchar(','); continue;
    }
    putchar(']');
    while (depth && pending[depth - 1] == NONE) { --depth; putchar(']'); }
    if (!depth) break;
    id = pending[depth - 1]; pending[depth - 1] = tree->nodes[id].next;
    putchar(',');
  }
  free(pending);
  return true;
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
static void empty(uint32_t offset) { printf("[\"group\",%u,%u,0,0,0,0]", offset, offset); }
static unsigned field_id(const char *name) {
  static const char *const fields[] = {"", "name", "link_name", "path", "alias", "library", "length", "call_args", "type"};
  if (name) for (unsigned i = 1; i < sizeof(fields)/sizeof(*fields); ++i)
    if (!strcmp(name, fields[i])) return i;
  return EXP_ROLE_NONE;
}
static void oracle_print_role(TSNode node, unsigned field, unsigned forced_flags) {
  unsigned flags = forced_flags | (!strcmp(ts_node_type(node), "primary") ? EXP_PRIMARY : 0);
  node = unwrap(node);
  const char *kind = ts_node_type(node);
  uint32_t start = ts_node_start_byte(node) - base, end = ts_node_end_byte(node) - base;
  uint32_t op = 0, oplen = 0, range = NONE, open = 0, close = 0;
  bool operation = !strcmp(kind, "binary") || !strcmp(kind, "unary_prefix") || !strcmp(kind, "unary_postfix") || !strcmp(kind, "assignment") || !strcmp(kind, "range");
  bool index = !strcmp(kind, "index");
  uint32_t return_after = UINT32_MAX;
  for (uint32_t i = 0; i < ts_node_child_count(node); ++i) {
    TSNode child = ts_node_child(node, i);
    if (ts_node_is_named(child)) continue;
    const char *token = ts_node_type(child);
    if (!strcmp(token, "const")) flags |= EXP_CONST;
    if (!strcmp(token, "pub")) flags |= EXP_PUBLIC;
    if (!strcmp(token, "packed")) flags |= EXP_PACKED;
    if (!strcmp(token, "distinct")) flags |= EXP_DISTINCT;
    if (!strcmp(kind, "for_condition") && !strcmp(token, "*")) flags |= EXP_POINTER_BINDING;
    if (!strcmp(token, "in")) flags |= EXP_ITERATION;
    if (!strcmp(token, "..=")) flags |= EXP_INCLUSIVE;
    if (!strcmp(token, "#bitcast")) flags |= EXP_BITCAST;
    if (!strcmp(kind, "case_arm") && !strcmp(token, "_")) flags |= EXP_WILDCARD;
    if (!strcmp(kind, "fn_type") && !strcmp(token, ")")) return_after = ts_node_end_byte(child);
    if (!strcmp(kind, "cast") && (!strcmp(token, "#cast") || !strcmp(token, "#bitcast"))) {
      op = ts_node_start_byte(child) - base; oplen = ts_node_end_byte(child) - ts_node_start_byte(child);
    }
    if (operation) { op = ts_node_start_byte(child) - base; oplen = ts_node_end_byte(child) - ts_node_start_byte(child); }
    if (index && !strcmp(ts_node_type(child), "..")) range = ts_node_start_byte(child) - base;
    if (index && !strcmp(ts_node_type(child), "[")) open = ts_node_end_byte(child) - base;
    if (index && !strcmp(ts_node_type(child), "]")) close = ts_node_start_byte(child) - base;
  }
  if (range != NONE) { op = range; oplen = 2; }
  printf("[\"%s\",%u,%u,%u,%u,%u,%u", range != NONE ? "slice" : kind, start, end, op, oplen, flags, field);
  if (!leaf(kind)) {
    unsigned named = 0; bool low = false, high = false;
    for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i) {
      TSNode child = ts_node_named_child(node, i);
      if (ts_node_is_extra(child)) continue;
      if (range != NONE && named) {
        if (ts_node_start_byte(child) - base < range) low = true;
        else { high = true; if (!low) { putchar(','); empty(open); } }
      }
      unsigned role = field_id(ts_node_field_name_for_named_child(node, i));
      if (ts_node_start_byte(child) >= return_after) role = EXP_ROLE_RETURN;
      putchar(','); oracle_print_role(child, role, 0); ++named;
    }
    if (range != NONE) {
      if (!low && !high) { putchar(','); empty(open); }
      if (!high) { putchar(','); empty(close); }
    }
  }
  putchar(']');
}
static void oracle_print(TSNode node) { oracle_print_role(node, EXP_ROLE_NONE, 0); }
static bool expression_node(TSNode node) {
  const char *kind = ts_node_type(node);
  if (!strcmp(kind, "primary")) return true;
  for (unsigned i = 1; i < sizeof(kinds) / sizeof(*kinds); ++i)
    if ((i < EXP_TYPE || i >= EXP_CAST) && i != EXP_MEMBER && !strcmp(kind, kinds[i])) return true;
  return false;
}
static void corpus_print(TSNode root) {
  TSTreeCursor cursor = ts_tree_cursor_new(root);
  bool done = false, first = true;
  putchar('[');
  while (!done) {
    TSNode current = ts_tree_cursor_current_node(&cursor);
    if (expression_node(current)) {
      if (!first) putchar(',');
      first = false;
      base = ts_node_start_byte(current);
      printf("{\"start\":%u,\"end\":%u,\"tree\":", base, ts_node_end_byte(current));
      /* A call statement becomes a primary when tested at the expression entry point. */
      unsigned root_flags = !strcmp(ts_node_type(current), "call") ? EXP_PRIMARY : 0;
      oracle_print_role(current, EXP_ROLE_NONE, root_flags); putchar('}');
    } else if (ts_tree_cursor_goto_first_child(&cursor)) continue;
    while (!ts_tree_cursor_goto_next_sibling(&cursor))
      if (!ts_tree_cursor_goto_parent(&cursor)) { done = true; break; }
  }
  puts("]");
  ts_tree_cursor_delete(&cursor);
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
  bool corpus = !strcmp(argv[1], "corpus");
  bool source_fast = !strcmp(argv[1], "source-fast"), source_tree = !strcmp(argv[1], "source-tree");
  bool fast = source_fast || !strcmp(argv[1], "fast"), oracle = corpus || source_tree || !strcmp(argv[1], "tree");
  if (!fast && !oracle) { free(text); return 2; }
  unsigned repeats = argc == 3 ? (unsigned)strtoul(argv[2], NULL, 10) : 1;
  if (!repeats) { free(text); return 2; }
  ExpTree result = {0};
  TSParser *parser = NULL; char *wrapped = NULL;
  if (oracle) {
    parser = ts_parser_new();
    if (!parser || !ts_parser_set_language(parser, tree_sitter_dyn())) return 2;
    if (corpus) {
      TSTree *tree = ts_parser_parse_string(parser, NULL, text, (uint32_t)length);
      bool valid = tree && !ts_node_has_error(ts_tree_root_node(tree));
      if (valid) corpus_print(ts_tree_root_node(tree));
      else fprintf(stderr, "invalid expression: corpus source has syntax errors\n");
      if (tree) ts_tree_delete(tree);
      ts_parser_delete(parser); free(text);
      return valid ? 0 : 1;
    }
    wrapped = malloc(sizeof(prefix) + length);
    if (!wrapped) return 2;
    memcpy(wrapped, prefix, sizeof(prefix) - 1); memcpy(wrapped + sizeof(prefix) - 1, text, length + 1);
  }
  bool valid = true;
  clock_t start = clock();
  for (unsigned i = 0; i < repeats; ++i) {
    if (fast) {
      valid = source_fast ? exp_parse_source(text, length, &result) : exp_parse(text, length, &result);
      if (repeats == 1 && valid) { if (!fast_print(&result, result.root)) { exp_free(&result); free(text); return 2; } putchar('\n'); }
    } else {
      TSTree *tree = ts_parser_parse_string(parser, NULL, source_tree ? text : wrapped,
          (uint32_t)(length + (source_tree ? 0 : sizeof(prefix) - 1)));
      TSNode root = tree ? ts_tree_root_node(tree) : (TSNode){0};
      valid = tree && !ts_node_has_error(root);
      if (source_tree) {
        if (valid && repeats == 1) { base = 0; oracle_print(root); putchar('\n'); }
        if (tree) ts_tree_delete(tree);
        if (!valid) break;
        continue;
      }
      TSNode declaration = {0};
      unsigned declarations = 0;
      if (valid) for (uint32_t j = 0; j < ts_node_named_child_count(root); ++j) {
        TSNode child = ts_node_named_child(root, j);
        if (ts_node_is_extra(child)) continue;
        declaration = child;
        ++declarations;
      }
      valid = valid && declarations == 1 && !strcmp(ts_node_type(declaration), "declaration");
      if (valid && repeats == 1) {
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
