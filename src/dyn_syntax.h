#ifndef DYN_SYNTAX_H
#define DYN_SYNTAX_H

#include "dyn.h"
#include <stdlib.h>
#include <string.h>
#include <tree_sitter/api.h>

extern const TSLanguage *tree_sitter_dyn(void);

static inline bool dyn_syntax_has_reflection(TSNode node) {
  if (!strcmp(ts_node_type(node), "typeof"))
    return true;
  for (uint32_t i = 0; i < ts_node_named_child_count(node); ++i)
    if (dyn_syntax_has_reflection(ts_node_named_child(node, i)))
      return true;
  return false;
}

/* Operands exclude comments and other parser extras. Use indexed access for
   fixed-arity syntax; walk raw children once for unbounded lists. */
static inline TSNode dyn_syntax_child(TSNode node, uint32_t index) {
  for (uint32_t i = 0, count = ts_node_named_child_count(node); i < count;
       ++i) {
    TSNode child = ts_node_named_child(node, i);
    if (ts_node_is_extra(child))
      continue;
    if (!index--)
      return child;
  }
  return (TSNode){0};
}
static inline uint32_t dyn_syntax_child_count(TSNode node) {
  uint32_t count = 0;
  for (uint32_t i = 0, end = ts_node_named_child_count(node); i < end; ++i)
    count += !ts_node_is_extra(ts_node_named_child(node, i));
  return count;
}
static inline TSNode dyn_syntax_last_child(TSNode node) {
  for (uint32_t i = ts_node_named_child_count(node); i; --i) {
    TSNode child = ts_node_named_child(node, i - 1);
    if (!ts_node_is_extra(child))
      return child;
  }
  return (TSNode){0};
}
static inline bool dyn_syntax_has_token(TSNode node, const char *token) {
  for (uint32_t i = 0, count = ts_node_child_count(node); i < count; ++i) {
    TSNode child = ts_node_child(node, i);
    if (!ts_node_is_named(child) && !strcmp(ts_node_type(child), token))
      return true;
  }
  return false;
}
static inline TSNode dyn_syntax_declaration_node(TSNode node) {
  if (ts_node_is_null(node))
    return node;
  return !strcmp(ts_node_type(node), "declaration")
             ? dyn_syntax_last_child(node)
             : node;
}
static inline bool dyn_syntax_public(TSNode wrapper) {
  return !ts_node_is_null(wrapper) &&
         !strcmp(ts_node_type(wrapper), "declaration") &&
         dyn_syntax_has_token(wrapper, "pub");
}

typedef enum {
  DYN_DECL_FUNCTION,
  DYN_DECL_STRUCT,
  DYN_DECL_ENUM,
  DYN_DECL_ALIAS,
  DYN_DECL_CONSTANT,
  DYN_DECL_VARIABLE
} DynDeclarationKind;
typedef struct {
  TSNode node, name;
  DynDeclarationKind kind;
  bool is_public;
} DynDeclaration;

/* Trees own all returned nodes. Missing names and non-declarations are skipped,
   allowing the same interface to serve complete builds and editor recovery. */
static inline bool dyn_syntax_declaration(TSNode wrapper, DynDeclaration *out) {
  TSNode node = dyn_syntax_declaration_node(wrapper), value = node;
  if (ts_node_is_null(node))
    return false;
  const char *kind = ts_node_type(node);
  DynDeclarationKind declaration_kind;
  if (!strcmp(kind, "fn") || !strcmp(kind, "extern_fn"))
    declaration_kind = DYN_DECL_FUNCTION;
  else if (!strcmp(kind, "struct"))
    declaration_kind = DYN_DECL_STRUCT;
  else if (!strcmp(kind, "enum"))
    declaration_kind = DYN_DECL_ENUM;
  else if (!strcmp(kind, "type_alias"))
    declaration_kind = DYN_DECL_ALIAS;
  else if (!strcmp(kind, "const_variable")) {
    declaration_kind = DYN_DECL_CONSTANT;
    value = dyn_syntax_child(node, 0);
  } else if (!strcmp(kind, "variable") || !strcmp(kind, "extern_variable"))
    declaration_kind = DYN_DECL_VARIABLE;
  else
    return false;
  if (ts_node_is_null(value))
    return false;
  TSNode name = ts_node_child_by_field_name(value, "name", 4);
  if (ts_node_is_null(name))
    for (uint32_t i = 0; i < ts_node_named_child_count(value); ++i) {
      TSNode child = ts_node_named_child(value, i);
      if (!strcmp(ts_node_type(child), "identifier")) {
        name = child;
        break;
      }
    }
  if (ts_node_is_null(name) || ts_node_is_missing(name))
    return false;
  *out = (DynDeclaration){node, name, declaration_kind,
                          dyn_syntax_public(wrapper)};
  return true;
}
static inline TSNode dyn_syntax_name(TSNode node) {
  DynDeclaration declaration;
  return dyn_syntax_declaration(node, &declaration) ? declaration.name
                                                    : (TSNode){0};
}
/* Text is borrowed. Quoted text excludes delimiters but is not escape-decoded.
 */
static inline bool dyn_syntax_text(TSNode node, const DynSource *source,
                                   bool quoted, const char **text,
                                   size_t *length) {
  if (ts_node_is_null(node) || ts_node_is_missing(node))
    return false;
  uint32_t start = ts_node_start_byte(node), end = ts_node_end_byte(node);
  if (end < start || end > source->length)
    return false;
  if (quoted) {
    if (end - start < 2 || source->text[start] != '"' ||
        source->text[end - 1] != '"')
      return false;
    ++start;
    --end;
  }
  *text = source->text + start;
  *length = end - start;
  return true;
}
/* Builtins accept either a type or a value; a field_type there can be a
   parser-selected spelling of a lexical value, unlike a declaration's type. */
static inline bool dyn_syntax_value_type(TSNode node) {
  TSNode parent = ts_node_parent(node);
  while (!ts_node_is_null(parent) && !strcmp(ts_node_type(parent), "type"))
    parent = ts_node_parent(parent);
  if (ts_node_is_null(parent)) return false;
  const char *kind = ts_node_type(parent);
  return !strcmp(kind, "typeof") || !strcmp(kind, "size") || !strcmp(kind, "align");
}
/* Lexical value bindings visible at a use site. This query is shared by
   import validation and qualification; member/type spelling is not a binding. */
static inline bool dyn_syntax_named(TSNode node, const DynSource *source,
                                     const char *name) {
  const char *text;
  size_t length;
  return dyn_syntax_text(node, source, false, &text, &length) &&
         strlen(name) == length && !memcmp(name, text, length);
}
static inline bool dyn_syntax_binding(TSNode node, const DynSource *source,
                                       const char *name) {
  while (!ts_node_is_null(node) &&
         (!strcmp(ts_node_type(node), "statement") ||
          !strcmp(ts_node_type(node), "const_variable")))
    node = dyn_syntax_child(node, 0);
  return !ts_node_is_null(node) && !strcmp(ts_node_type(node), "variable") &&
         dyn_syntax_named(dyn_syntax_child(node, 0), source, name);
}
static inline bool dyn_syntax_local(TSNode use, const DynSource *source,
                                     const char *name) {
  TSNode child = use;
  for (TSNode scope = ts_node_parent(child); !ts_node_is_null(scope);
       child = scope, scope = ts_node_parent(scope)) {
    const char *kind = ts_node_type(scope);
    if (!strcmp(kind, "block")) {
      for (uint32_t i = 0; i < ts_node_named_child_count(scope); ++i) {
        TSNode declaration = ts_node_named_child(scope, i);
        if (ts_node_end_byte(declaration) > ts_node_start_byte(child))
          break;
        if (dyn_syntax_binding(declaration, source, name))
          return true;
      }
    } else if (!strcmp(kind, "fn")) {
      for (uint32_t i = 0; i < ts_node_named_child_count(scope); ++i) {
        TSNode param = ts_node_named_child(scope, i);
        const char *pk = ts_node_type(param);
        if (strcmp(pk, "fn_param") && strcmp(pk, "variadic_param"))
          continue;
        for (uint32_t j = 0; j < ts_node_named_child_count(param); ++j) {
          TSNode id = ts_node_named_child(param, j);
          if (!strcmp(ts_node_type(id), "identifier") &&
              dyn_syntax_named(id, source, name))
            return true;
        }
      }
      break;
    } else if (!strcmp(kind, "for_") && !strcmp(ts_node_type(child), "block")) {
      for (uint32_t i = 0; i < ts_node_named_child_count(scope); ++i) {
        TSNode condition = ts_node_named_child(scope, i);
        if (!strcmp(ts_node_type(condition), "for_condition") &&
            dyn_syntax_has_token(condition, "in") &&
            dyn_syntax_named(dyn_syntax_child(condition, 0), source, name))
          return true;
      }
    } else if (!strcmp(kind, "case_arm") && !strcmp(ts_node_type(child), "block")) {
      for (uint32_t i = 0; i < ts_node_named_child_count(scope); ++i) {
        TSNode binding = ts_node_named_child(scope, i);
        if (!strcmp(ts_node_type(binding), "type_pattern"))
          binding = dyn_syntax_last_child(binding);
        if (!strcmp(ts_node_type(binding), "identifier") &&
            dyn_syntax_named(binding, source, name))
          return true;
      }
    }
  }
  return false;
}
static inline char *dyn_syntax_copy_text(TSNode node, const DynSource *source,
                                         bool quoted) {
  const char *text;
  size_t length;
  if (!dyn_syntax_text(node, source, quoted, &text, &length))
    return NULL;
  char *copy = malloc(length + 1);
  if (copy) {
    memcpy(copy, text, length);
    copy[length] = 0;
  }
  return copy;
}
static inline bool dyn_syntax_text_is(TSNode node, const DynSource *source,
                                      const char *expected) {
  const char *text;
  size_t length;
  return dyn_syntax_text(node, source, false, &text, &length) &&
         length == strlen(expected) && !memcmp(text, expected, length);
}
static inline TSParser *dyn_syntax_parser(void) {
  TSParser *parser = ts_parser_new();
  if (parser && !ts_parser_set_language(parser, tree_sitter_dyn())) {
    ts_parser_delete(parser);
    parser = NULL;
  }
  return parser;
}
/* Guard every parser entry before recursive compiler/editor consumers. This
   traversal itself uses Tree-sitter's heap-backed cursor, not the C stack. */
#define DYN_SYNTAX_DEPTH_LIMIT 1024u
static inline bool dyn_syntax_depth_ok(TSNode root) {
  TSTreeCursor cursor = ts_tree_cursor_new(root);
  unsigned depth = 0;
  bool ok = true, done = false;
  while (!done) {
    if (ts_tree_cursor_goto_first_child(&cursor)) {
      if (++depth > DYN_SYNTAX_DEPTH_LIMIT) { ok = false; break; }
      continue;
    }
    while (!ts_tree_cursor_goto_next_sibling(&cursor)) {
      if (!ts_tree_cursor_goto_parent(&cursor)) { done = true; break; }
      --depth;
    }
  }
  ts_tree_cursor_delete(&cursor);
  return ok;
}
typedef struct { const char *text; size_t length; const DynContext *context; } DynParseInput;
static inline const char *dyn_parse_read(void *payload, uint32_t offset, TSPoint point, uint32_t *length) {
  (void)point;
  DynParseInput *input = payload;
  *length = offset < input->length ? (uint32_t)(input->length - offset) : 0;
  return *length ? input->text + offset : "";
}
static inline bool dyn_parse_progress(TSParseState *state) {
  return !dyn_work_step(state->payload, 1024);
}
static inline TSTree *dyn_parse_with_context(TSParser *parser, const TSTree *previous,
    const char *text, size_t length, const DynContext *context) {
  if (!dyn_work_step(context, length)) return NULL;
  if (!context || !context->work) return ts_parser_parse_string(parser, previous, text, (uint32_t)length);
  DynParseInput payload = {text, length, context};
  TSInput input = {.payload = &payload, .read = dyn_parse_read, .encoding = TSInputEncodingUTF8};
  TSParseOptions options = {.payload = (void *)context, .progress_callback = dyn_parse_progress};
  TSTree *tree = ts_parser_parse_with_options(parser, previous, input, options);
  if (!tree) ts_parser_reset(parser);
  return tree;
}
/* Caller owns the returned tree; no parser lifetime escapes this operation. */
static inline TSTree *dyn_syntax_reparse_context(const char *text, size_t length,
                                        const TSTree *previous, bool *too_deep, const DynContext *context) {
  if (too_deep) *too_deep = false;
  if (!text || length > UINT32_MAX)
    return NULL;
  TSParser *parser = dyn_syntax_parser();
  TSTree *tree =
      parser ? dyn_parse_with_context(parser, previous, text, length, context)
             : NULL;
  if (parser)
    ts_parser_delete(parser);
  if (tree && !dyn_syntax_depth_ok(ts_tree_root_node(tree))) {
    if (too_deep) *too_deep = true;
    ts_tree_delete(tree); tree = NULL;
  }
  return tree;
}
static inline TSTree *dyn_syntax_reparse_checked(const char *text, size_t length,
    const TSTree *previous, bool *too_deep) {
  return dyn_syntax_reparse_context(text, length, previous, too_deep, NULL);
}
static inline TSTree *dyn_syntax_reparse(const char *text, size_t length,
                                        const TSTree *previous) {
  return dyn_syntax_reparse_context(text, length, previous, NULL, NULL);
}
static inline TSTree *dyn_syntax_parse(const char *text, size_t length) {
  return dyn_syntax_reparse(text, length, NULL);
}
static inline TSPoint dyn_syntax_advance(TSPoint point, const char *text,
                                        size_t length) {
  for (size_t i = 0; i < length; ++i) {
    if (text[i] == '\n') { ++point.row; point.column = 0; }
    else ++point.column;
  }
  return point;
}
/* A transactional editor text update may contain several changes. Collapse its
   final diff to one byte edit while preserving unaffected parser subtrees. */
static inline void dyn_syntax_edit_text(TSTree *tree, const char *before,
                                        const char *after) {
  size_t old_length = strlen(before), new_length = strlen(after), start = 0;
  while (start < old_length && start < new_length && before[start] == after[start])
    ++start;
  if (start == old_length && start == new_length) return;
  while (start && ((unsigned char)before[start] & 0xc0) == 0x80) --start;
  size_t old_end = old_length, new_end = new_length;
  while (old_end > start && new_end > start && before[old_end - 1] == after[new_end - 1]) {
    --old_end; --new_end;
  }
  while (old_end < old_length && new_end < new_length &&
         (((unsigned char)before[old_end] & 0xc0) == 0x80 ||
          ((unsigned char)after[new_end] & 0xc0) == 0x80)) {
    ++old_end; ++new_end;
  }
  TSPoint first = dyn_syntax_advance((TSPoint){0, 0}, before, start);
  TSInputEdit edit = {(uint32_t)start, (uint32_t)old_end, (uint32_t)new_end,
      first, dyn_syntax_advance(first, before + start, old_end - start),
      dyn_syntax_advance(first, after + start, new_end - start)};
  ts_tree_edit(tree, &edit);
}
static inline void dyn_syntax_diagnostic(TSNode node, const DynSource *source,
                                         const char *severity,
                                         const char *message) {
  dyn_diagnostic_source(severity, source, ts_node_start_byte(node),
                        ts_node_end_byte(node), message);
}
#endif
