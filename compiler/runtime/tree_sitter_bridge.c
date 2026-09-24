#include <stdlib.h>
#include <string.h>
#include <tree_sitter/api.h>
#include <stdint.h>

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

bool dyn_tree_cursor_is_error(const DynTreeCursor *cursor) {
  TSNode node = ts_tree_cursor_current_node(&cursor->cursor);
  return ts_node_is_error(node) || ts_node_is_missing(node);
}

uint32_t dyn_tree_cursor_operator(const DynTreeCursor *cursor) {
  TSNode node = ts_tree_cursor_current_node(&cursor->cursor);
  for (uint32_t i = 0, count = ts_node_child_count(node); i < count; ++i) {
    TSNode child = ts_node_child(node, i);
    if (ts_node_is_named(child)) continue;
    const char *op = ts_node_type(child);
    static const char *operators[] = {
      "", "=", ":=", "+", "-", "*", "/", "%", "==", "!=", "<",
      "<=", ">", ">=", "&&", "||", "&", "|", "^", "<<", ">>", "!",
      "~", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=",
      ">>=", ".*",
      "..", "..=",
      "#cast", "#bitcast",
    };
    for (uint32_t j = 1; j < sizeof(operators) / sizeof(operators[0]); ++j)
      if (strcmp(op, operators[j]) == 0) return j;
  }
  return 0;
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
      {"variadic_param", 146}, {"extern_variable", 147},
      {"type_pattern", 148},
      {"variadic", 149},
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
void dyn_ast_node_init(void *node, uint32_t kind) {
  static const struct { uint32_t raw, ast; } kinds[] = {
      {88,1},{89,2},{91,3},{93,4},{95,5},{97,6},{98,7},{92,8},{90,9},
      {1,10},{134,11},{141,12},{120,13},{113,14},{127,15},{100,16},
      {142,17},{104,18},{130,19},{107,20},{108,21},{109,22},{137,23},
      {145,24},{103,25},{112,26},{106,27},{96,28},{124,29},{131,30},
      {119,31},{99,32},{122,33},{110,34},{111,35},{126,36},{105,37},
      {132,38},{136,39},{138,40},{143,41},{114,42},{121,43},{125,44},
      {116,45},{102,46},{133,47},{87,48},{101,49},{144,50},{139,51},
      {140,52},{94,53},{123,54},{115,55},{118,56},{117,57},{135,58},
      {129,59},{128,60},{85,61},{84,62},{78,63},{49,64}};
  uint32_t ast_kind = 0;
  for (size_t i = 0; i < sizeof(kinds) / sizeof(kinds[0]); ++i)
    if (kinds[i].raw == kind) { ast_kind = kinds[i].ast; break; }
  uint32_t *fields = node;
  fields[0] = ast_kind;
  fields[1] = 0;
  fields[2] = 0;
  fields[3] = 0;
  fields[4] = UINT32_MAX;
  fields[5] = UINT32_MAX;
  fields[6] = UINT32_MAX;
}

void dyn_ast_node_set_location(void *node, uint32_t source_id, uint32_t start,
                               uint32_t end) {
  uint32_t *fields = node;
  fields[1] = source_id;
  fields[2] = start;
  fields[3] = end;
}

void dyn_ast_node_set_parent(void *node, uint32_t parent) {
  ((uint32_t *)node)[4] = parent;
}

void dyn_ast_node_set_first_child(void *node, uint32_t child) {
  ((uint32_t *)node)[5] = child;
}

void dyn_ast_node_set_next_sibling(void *node, uint32_t sibling) {
  ((uint32_t *)node)[6] = sibling;
}
