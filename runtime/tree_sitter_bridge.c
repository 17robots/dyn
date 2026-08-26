#include <stdlib.h>
#include <string.h>
#include <tree_sitter/api.h>

typedef struct {
  TSTreeCursor cursor;
} DynTreeCursor;

bool dyn_tree_has_error(const TSTree *tree) {
  return ts_node_has_error(ts_tree_root_node(tree));
}

DynTreeCursor *dyn_tree_cursor_new(const TSTree *tree) {
  DynTreeCursor *result = malloc(sizeof(*result));
  if (!result) {
    return NULL;
  }
  result->cursor = ts_tree_cursor_new(ts_tree_root_node(tree));
  return result;
}

DynTreeCursor *dyn_tree_cursor_copy(const DynTreeCursor *cursor) {
  DynTreeCursor *result = malloc(sizeof(*result));
  if (!result) {
    return NULL;
  }
  result->cursor = ts_tree_cursor_copy(&cursor->cursor);
  return result;
}

void dyn_tree_cursor_delete(DynTreeCursor *cursor) {
  if (!cursor) {
    return;
  }
  ts_tree_cursor_delete(&cursor->cursor);
  free(cursor);
}

static bool dyn_tree_cursor_named(const DynTreeCursor *cursor) {
  return ts_node_is_named(ts_tree_cursor_current_node(&cursor->cursor));
}

bool dyn_tree_cursor_first_named_child(DynTreeCursor *cursor) {
  if (!ts_tree_cursor_goto_first_child(&cursor->cursor)) {
    return false;
  }
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
    if (dyn_tree_cursor_named(cursor)) {
      return true;
    }
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
  /* Stable Dyn-facing IDs. Tree-sitter symbol numbers are generated details
     and change whenever grammar rules are added or removed. */
  static const struct {
    const char *name;
    uint32_t id;
  } kinds[] = {
      {"escape_sequence", 84}, {"comment", 85},
      {"source_file", 87},     {"declaration", 88},
      {"use", 89},             {"variable", 90},
      {"const_variable", 91},  {"type_alias", 92},
      {"struct", 93},          {"struct_member", 94},
      {"enum", 95},            {"enum_member", 96},
      {"fn", 97},              {"extern_fn", 98},
      {"fn_param", 99},        {"block", 100},
      {"statement", 101},      {"return_", 102},
      {"continue_", 103},      {"break_", 104},
      {"if_", 105},            {"else_", 106},
      {"case_", 107},          {"case_arm", 108},
      {"case_pattern", 109},   {"for_", 110},
      {"for_condition", 111},  {"defer", 112},
      {"assignment", 113},     {"panic", 114},
      {"syscall", 115},        {"range", 116},
      {"type_qualifier", 117}, {"type", 118},
      {"field_type", 119},     {"array_type", 120},
      {"pointer_type", 121},   {"fn_type", 122},
      {"struct_type", 123},    {"expression", 124},
      {"primary", 125},        {"group", 126},
      {"binary", 127},         {"unary_prefix", 128},
      {"unary_postfix", 129},  {"call", 130},
      {"field_access", 131},   {"index", 132},
      {"size", 133},           {"align", 134},
      {"typeof", 135},         {"len", 136},
      {"cast", 137},           {"literal", 138},
      {"struct_literal", 139}, {"struct_literal_member", 140},
      {"array_literal", 141},  {"bool_", 142},
      {"number_", 143},        {"string_", 144},
      {"char_", 145},          {"null_", 78},
      {"primitive", 49},       {"identifier", 1},
  };
  const char *name =
      ts_node_type(ts_tree_cursor_current_node(&cursor->cursor));
  for (size_t i = 0; i < sizeof(kinds) / sizeof(kinds[0]); ++i) {
    if (strcmp(name, kinds[i].name) == 0) {
      return kinds[i].id;
    }
  }
  return 0;
}
