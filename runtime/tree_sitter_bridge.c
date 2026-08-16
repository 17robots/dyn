#include <tree_sitter/api.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
  TSTreeCursor cursor;
} DynTreeCursor;

bool dyn_tree_has_error(const TSTree *tree) {
  return ts_node_has_error(ts_tree_root_node(tree));
}

DynTreeCursor *dyn_tree_cursor_new(const TSTree *tree) {
  DynTreeCursor *result = malloc(sizeof(*result));
  if (!result)
    return NULL;
  result->cursor = ts_tree_cursor_new(ts_tree_root_node(tree));
  return result;
}

DynTreeCursor *dyn_tree_cursor_copy(const DynTreeCursor *cursor) {
  DynTreeCursor *result = malloc(sizeof(*result));
  if (!result)
    return NULL;
  result->cursor = ts_tree_cursor_copy(&cursor->cursor);
  return result;
}

void dyn_tree_cursor_delete(DynTreeCursor *cursor) {
  if (!cursor)
    return;
  ts_tree_cursor_delete(&cursor->cursor);
  free(cursor);
}

static bool dyn_tree_cursor_named(const DynTreeCursor *cursor) {
  return ts_node_is_named(ts_tree_cursor_current_node(&cursor->cursor));
}

bool dyn_tree_cursor_first_named_child(DynTreeCursor *cursor) {
  if (!ts_tree_cursor_goto_first_child(&cursor->cursor))
    return false;
  while (!dyn_tree_cursor_named(cursor)) {
    if (!ts_tree_cursor_goto_next_sibling(&cursor->cursor)) {
      ts_tree_cursor_goto_parent(&cursor->cursor);
      return false;
    }
  }
  return true;
}

bool dyn_tree_cursor_next_named_sibling(DynTreeCursor *cursor) {
  while (ts_tree_cursor_goto_next_sibling(&cursor->cursor)) {
    if (dyn_tree_cursor_named(cursor))
      return true;
  }
  return false;
}

bool dyn_tree_cursor_parent(DynTreeCursor *cursor) {
  return ts_tree_cursor_goto_parent(&cursor->cursor);
}

uint32_t dyn_tree_cursor_start(const DynTreeCursor *cursor) {
  return ts_node_start_byte(ts_tree_cursor_current_node(&cursor->cursor));
}

uint32_t dyn_tree_cursor_end(const DynTreeCursor *cursor) {
  return ts_node_end_byte(ts_tree_cursor_current_node(&cursor->cursor));
}

uint32_t dyn_tree_cursor_kind(const DynTreeCursor *cursor) {
  const char *kind = ts_node_type(ts_tree_cursor_current_node(&cursor->cursor));
  if (!strcmp(kind, "declaration"))
    return 1;
  if (!strcmp(kind, "use"))
    return 2;
  if (!strcmp(kind, "const_variable"))
    return 3;
  if (!strcmp(kind, "struct"))
    return 4;
  if (!strcmp(kind, "enum"))
    return 5;
  if (!strcmp(kind, "fn"))
    return 6;
  if (!strcmp(kind, "foreign_fn"))
    return 7;
  if (!strcmp(kind, "type_alias"))
    return 8;
  if (!strcmp(kind, "variable"))
    return 9;
  if (!strcmp(kind, "identifier"))
    return 10;
#define DYN_NODE_KIND(name, value)                                             \
  if (!strcmp(kind, name))                                                    \
    return value
  DYN_NODE_KIND("align", 11);
  DYN_NODE_KIND("array_literal", 12);
  DYN_NODE_KIND("array_type", 13);
  DYN_NODE_KIND("assignment", 14);
  DYN_NODE_KIND("binary", 15);
  DYN_NODE_KIND("block", 16);
  DYN_NODE_KIND("bool_", 17);
  DYN_NODE_KIND("break_", 18);
  DYN_NODE_KIND("call", 19);
  DYN_NODE_KIND("case_", 20);
  DYN_NODE_KIND("case_arm", 21);
  DYN_NODE_KIND("case_pattern", 22);
  DYN_NODE_KIND("cast", 23);
  DYN_NODE_KIND("char_", 24);
  DYN_NODE_KIND("continue_", 25);
  DYN_NODE_KIND("defer", 26);
  DYN_NODE_KIND("else_", 27);
  DYN_NODE_KIND("enum_member", 28);
  DYN_NODE_KIND("expression", 29);
  DYN_NODE_KIND("field_access", 30);
  DYN_NODE_KIND("field_type", 31);
  DYN_NODE_KIND("fn_param", 32);
  DYN_NODE_KIND("fn_type", 33);
  DYN_NODE_KIND("for_", 34);
  DYN_NODE_KIND("for_condition", 35);
  DYN_NODE_KIND("group", 36);
  DYN_NODE_KIND("if_", 37);
  DYN_NODE_KIND("index", 38);
  DYN_NODE_KIND("len", 39);
  DYN_NODE_KIND("literal", 40);
  DYN_NODE_KIND("number_", 41);
  DYN_NODE_KIND("panic", 42);
  DYN_NODE_KIND("pointer_type", 43);
  DYN_NODE_KIND("primary", 44);
  DYN_NODE_KIND("range", 45);
  DYN_NODE_KIND("return_", 46);
  DYN_NODE_KIND("size", 47);
  DYN_NODE_KIND("source_file", 48);
  DYN_NODE_KIND("statement", 49);
  DYN_NODE_KIND("string_", 50);
  DYN_NODE_KIND("struct_literal", 51);
  DYN_NODE_KIND("struct_literal_member", 52);
  DYN_NODE_KIND("struct_member", 53);
  DYN_NODE_KIND("struct_type", 54);
  DYN_NODE_KIND("syscall", 55);
  DYN_NODE_KIND("type", 56);
  DYN_NODE_KIND("type_qualifier", 57);
  DYN_NODE_KIND("typeof", 58);
  DYN_NODE_KIND("unary_postfix", 59);
  DYN_NODE_KIND("unary_prefix", 60);
  DYN_NODE_KIND("comment", 61);
  DYN_NODE_KIND("escape_sequence", 62);
  DYN_NODE_KIND("null_", 63);
  DYN_NODE_KIND("primitive", 64);
#undef DYN_NODE_KIND
  return 0;
}
