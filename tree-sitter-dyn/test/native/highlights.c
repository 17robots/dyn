#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <tree_sitter/api.h>

extern const TSLanguage *tree_sitter_dyn(void);

int main(int argc, char **argv) {
  const char source[] = "use \"std/io\" stream\nconst Answer: i32 = 42\nfn main() { const local: i32 = Answer }\n";
  TSParser *parser = ts_parser_new();
  assert(parser && ts_parser_set_language(parser, tree_sitter_dyn()));
  /* An optional import alias must not consume the next global's name. */
  const char *imports[] = {
    "use \"std/io\"\nvalue := 42\n",
    "use \"std/io\"\nvalue: i32 = 42\n",
    "use \"std/io\" /* comment */\nvalue := 42\n",
    "use \"std/io\" value := 42\n",
    "use \"std/io\" stream\nvalue := 42\n",
    "use \"std/io\"\nconst value := 42\n",
  };
  for (size_t i = 0; i < sizeof(imports) / sizeof(*imports); ++i) {
    TSTree *parsed = ts_parser_parse_string(parser, NULL, imports[i], (uint32_t)strlen(imports[i]));
    TSNode root = ts_tree_root_node(parsed);
    if (ts_node_has_error(root)) fprintf(stderr, "import/global parse failed: %s", imports[i]);
    assert(!ts_node_has_error(root));
    unsigned declarations = 0;
    for (uint32_t child = 0; child < ts_node_named_child_count(root); ++child)
      declarations += !strcmp(ts_node_type(ts_node_named_child(root, child)), "declaration");
    assert(declarations == 2);
    TSNode use = ts_node_named_child(ts_node_named_child(root, 0), 0);
    TSNode alias = ts_node_child_by_field_name(use, "alias", 5);
    assert(ts_node_is_null(alias) == (i != 4));
    ts_tree_delete(parsed);
  }
  TSTree *tree = ts_parser_parse_string(parser, NULL, source, sizeof(source) - 1);
  assert(tree && !ts_node_has_error(ts_tree_root_node(tree)));
  for (int arg = 1; arg < argc; ++arg) {
    FILE *file = fopen(argv[arg], "rb");
    assert(file);
    fseek(file, 0, SEEK_END);
    long length = ftell(file);
    rewind(file);
    assert(length >= 0);
    char *text = malloc((size_t)length + 1);
    assert(text && fread(text, 1, (size_t)length, file) == (size_t)length);
    fclose(file);
    uint32_t offset;
    TSQueryError error;
    TSQuery *query = ts_query_new(tree_sitter_dyn(), text, (uint32_t)length, &offset, &error);
    if (!query) { fprintf(stderr, "%s: invalid query at byte %u (error %d)\n", argv[arg], offset, error); return 1; }
    TSQueryCursor *cursor = ts_query_cursor_new();
    ts_query_cursor_exec(cursor, query, ts_tree_root_node(tree));
    TSQueryMatch match;
    uint32_t capture_index;
    unsigned constants = 0;
    while (ts_query_cursor_next_capture(cursor, &match, &capture_index)) {
      TSQueryCapture capture = match.captures[capture_index];
      uint32_t start = ts_node_start_byte(capture.node), end = ts_node_end_byte(capture.node);
      if ((end-start == 6 && !memcmp(source+start, "Answer", 6) && ts_node_start_point(capture.node).row == 1) ||
          (end-start == 5 && !memcmp(source+start, "local", 5))) {
        uint32_t size;
        const char *name = ts_query_capture_name_for_id(query, capture.index, &size);
        if (size == 8 && !memcmp(name, "constant", 8)) ++constants;
        else if ((size == 8 && !memcmp(name, "variable", 8)) || (size == 4 && !memcmp(name, "type", 4))) {
          fprintf(stderr, "%s: constant also captured as %.*s\n", argv[arg], (int)size, name);
          return 1;
        }
      }
    }
    assert(constants == 2);
    ts_query_cursor_delete(cursor);
    ts_query_delete(query);
    free(text);
  }
  ts_tree_delete(tree);
  ts_parser_delete(parser);
  return 0;
}
