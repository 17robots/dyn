/* Full-source syntax. Included by parser.c; no semantic analysis. */

const char *exp_source_kind(unsigned kind) {
  static const char *const names[] = {
    "source_file", "declaration", "target_directive", "target_condition", "link_directive",
    "use", "import", "variable", "const_variable", "type_alias", "struct",
    "struct_member", "enum", "enum_member", "fn", "extern_fn",
    "extern_variable", "fn_param", "variadic_param", "variadic",
    "block", "return_", "continue_", "break_", "if_", "else_",
    "case_", "case_arm", "case_pattern", "type_pattern", "for_",
    "for_condition", "defer", "assignment", "static_assert", "panic",
    "range", "type_qualifier", "reverse", "ERROR"
  };
  return kind >= SRC_FILE && kind - SRC_FILE < sizeof(names) / sizeof(*names)
      ? names[kind - SRC_FILE] : "unknown_source_node";
}
static uint32_t src_node(Parser *p, unsigned kind, uint32_t start,
                         uint32_t end, uint32_t first) {
  return node(p, (ExpKind)kind, start, end, first, (Token){0});
}
static uint32_t src_end(Parser *p, uint32_t id, uint32_t fallback) {
  return id == NONE ? fallback : p->tree->nodes[id].end;
}
static bool src_fatal(Parser *p) {
  return resource_error(p);
}
static bool src_restore(Parser *p, Parser saved, uint32_t count) {
  if (src_fatal(p)) return false;
  *p = saved; p->tree->count = count; p->tree->error = NULL; p->tree->error_kind = EXP_OK;
  p->tree->error_offset = 0; return true;
}
static Token src_peek(Parser *p) {
  if (p->tree->error) return (Token){p->offset, p->offset, END};
  Parser probe = *p;
  ExpTree scratch = {0}; probe.tree = &scratch;
  lex(&probe);
  if (scratch.error) propagate_error(p, &scratch);
  return probe.token;
}
static bool src_next_is(Parser *p, const char *word) {
  Token next = src_peek(p);
  return next.end - next.start == strlen(word) && at(p, next.start, word);
}
/* distinct, packed and is are keywords only where they start their construct,
   so they stay usable as ordinary names everywhere else. */
static bool src_distinct(Parser *p) { return is(p, "distinct") && src_next_is(p, "type"); }
static bool src_packed(Parser *p) { return is(p, "packed") && src_next_is(p, "struct"); }
static bool src_type_pattern(Parser *p) {
  return is(p, "is") && !src_next_is(p, "=>") && !src_next_is(p, ",") && !src_next_is(p, "..");
}
static uint32_t src_literal(Parser *p, TokenKind token_kind, ExpKind kind) {
  Token token = p->token;
  if (token.kind != token_kind) { fail(p, token.start, "expected literal"); return NONE; }
  lex(p); return node(p, kind, token.start, token.end, NONE, (Token){0});
}
static uint32_t src_qualifier(Parser *p) {
  uint32_t start = p->token.start; expect(p, ":");
  uint32_t child = type(p);
  return src_node(p, SRC_QUALIFIER, start, src_end(p, child, start), child);
}
static bool src_dots(Parser *p) {
  if (take(p, "...")) return true;
  uint32_t start = p->token.start;
  if (!take(p, "..")) return false;
  if (p->token.start != start + 2) fail(p, start, "variadic marker must be contiguous");
  expect(p, "."); return !p->tree->error;
}
static uint32_t src_variadic(Parser *p) {
  uint32_t start = p->token.start;
  if (!src_dots(p)) fail(p, start, "expected variadic marker");
  return src_node(p, SRC_VARIADIC, start, start + 3, NONE);
}
static uint32_t src_variable(Parser *p) {
  uint32_t start = p->token.start, first = NONE, last = NONE;
  append(p, &first, &last, name(p));
  if (take(p, ":=")) append(p, &first, &last, expression(p, 0));
  else {
    uint32_t colon = p->token.start; expect(p, ":");
    uint32_t target = type(p);
    if (take(p, "=")) {
      append(p, &first, &last, target);
      append(p, &first, &last, expression(p, 0));
    } else append(p, &first, &last,
        src_node(p, SRC_QUALIFIER, colon, src_end(p, target, colon), target));
  }
  return src_node(p, SRC_VARIABLE, start, src_end(p, last, start), first);
}
static uint32_t src_const(Parser *p) {
  uint32_t start = p->token.start; expect(p, "const");
  uint32_t child = src_variable(p);
  return mark(p, src_node(p, SRC_CONST, start, src_end(p, child, start), child), EXP_CONST);
}
static uint32_t src_alias(Parser *p) {
  uint32_t start = p->token.start, first = NONE, last = NONE;
  bool distinct = take(p, "distinct"); expect(p, "type"); append(p, &first, &last, name(p));
  expect(p, "="); append(p, &first, &last, type(p));
  return mark(p, src_node(p, SRC_ALIAS, start, src_end(p, last, start), first), distinct ? EXP_DISTINCT : 0);
}
static uint32_t src_block(Parser *p);
static uint32_t src_statement(Parser *p);
static uint32_t src_if(Parser *p);
static uint32_t src_for(Parser *p);
static uint32_t src_case(Parser *p);
/* A condition can end in a name directly before its block. The initial
   expression attempt can consume that block as a named struct literal. Scan
   only the bytes reached by that attempt, retaining the final top-level brace;
   earlier braces belong to genuine struct operands. At most one retry runs,
   and both scanning and parsing charge the shared work budget. */
static uint32_t src_condition(Parser *p) {
  Parser saved = *p; uint32_t count = p->tree->count;
  uint32_t value = expression(p, 0);
  if (!p->tree->error && (is(p, "{") || is(p, "..") || is(p, "..="))) return value;
  uint32_t stop = p->token.start;
  if (!src_restore(p, saved, count)) return NONE;
  Parser probe = *p; ExpTree scratch = {0}; probe.tree = &scratch;
  unsigned parens = 0, brackets = 0, braces = 0;
  uint32_t brace = 0;
  while (probe.token.kind != END && probe.token.start <= stop && !scratch.error) {
    if (is(&probe, "{")) {
      if (!parens && !brackets && !braces) brace = probe.token.start;
      ++braces;
    } else if (is(&probe, "}")) {
      if (!braces) break;
      --braces;
    } else if (is(&probe, "(")) ++parens;
    else if (is(&probe, ")")) { if (!parens) break; --parens; }
    else if (is(&probe, "[")) ++brackets;
    else if (is(&probe, "]")) { if (!brackets) break; --brackets; }
    lex(&probe);
  }
  if (scratch.error) { propagate_error(p, &scratch); return NONE; }
  p->block_brace = brace;
  value = expression(p, 0);
  p->block_brace = saved.block_brace;
  return value;
}
static uint32_t src_range(Parser *p, bool condition) {
  uint32_t first = condition ? src_condition(p) : expression(p, 0);
  if (first == NONE || (!is(p, "..") && !is(p, "..="))) return first;
  Token operator = p->token; lex(p);
  uint32_t last = condition ? src_condition(p) : expression(p, 0);
  if (last == NONE) return NONE;
  p->tree->nodes[first].next = last;
  return mark(p, node(p, (ExpKind)SRC_RANGE, p->tree->nodes[first].start,
              p->tree->nodes[last].end, first, operator), operator.end - operator.start == 3 ? EXP_INCLUSIVE : 0);
}
static uint32_t src_if(Parser *p) {
  uint32_t start = p->token.start, first = NONE, last = NONE;
  expect(p, "if"); append(p, &first, &last, src_condition(p));
  append(p, &first, &last, src_block(p));
  if (is(p, "else")) {
    uint32_t begin = p->token.start; lex(p);
    uint32_t child = is(p, "if") ? src_statement(p) : src_block(p);
    append(p, &first, &last, src_node(p, SRC_ELSE, begin, src_end(p, child, begin), child));
  }
  return src_node(p, SRC_IF, start, src_end(p, last, start), first);
}
static uint32_t src_for(Parser *p) {
  uint32_t start = p->token.start, first = NONE, last = NONE;
  if (!is(p, "for")) { append(p, &first, &last, name(p)); expect(p, ":"); }
  expect(p, "for");
  if (!is(p, "{")) {
    uint32_t begin = p->token.start, cf = NONE, cl = NONE;
    Parser saved = *p; uint32_t count = p->tree->count;
    bool pointer = take(p, "*");
    bool constant = pointer && take(p, "const");
    unsigned flags = 0;
    uint32_t binding = p->token.kind == NAME ? name(p) : NONE;
    if (binding != NONE && take(p, "in")) {
      flags = EXP_ITERATION | (pointer ? EXP_POINTER_BINDING : 0) | (constant ? EXP_CONST : 0);
      append(p, &cf, &cl, binding);
      if (is(p, "#reverse")) {
        uint32_t reverse_start = p->token.start; lex(p); expect(p, "(");
        uint32_t value = src_range(p, false), end = p->token.end; expect(p, ")");
        append(p, &cf, &cl, src_node(p, SRC_REVERSE, reverse_start, end, value));
      } else append(p, &cf, &cl, src_range(p, true));
    } else {
      if (!src_restore(p, saved, count)) return NONE;
      append(p, &cf, &cl, src_condition(p));
    }
    append(p, &first, &last, mark(p, src_node(p, SRC_FOR_CONDITION, begin, src_end(p, cl, begin), cf), flags));
  }
  append(p, &first, &last, src_block(p));
  return src_node(p, SRC_FOR, start, src_end(p, last, start), first);
}
static uint32_t src_case(Parser *p) {
  uint32_t start = p->token.start, first = NONE, last = NONE;
  expect(p, "case"); append(p, &first, &last, src_condition(p)); expect(p, "{");
  while (!is(p, "}") && !p->tree->error) {
    uint32_t begin = p->token.start, af = NONE, al = NONE;
    bool wildcard = false;
    if (src_type_pattern(p)) {
      lex(p);
      uint32_t pf = NONE, pl = NONE;
      append(p, &pf, &pl, type(p));
      if (p->token.kind == NAME) append(p, &pf, &pl, name(p));
      append(p, &af, &al, src_node(p, SRC_TYPE_PATTERN, begin, src_end(p, pl, begin), pf));
    } else {
      wildcard = take(p, "_");
      if (!wildcard) {
        do {
          uint32_t pattern = src_range(p, false);
          if (pattern == NONE) break;
          append(p, &af, &al, src_node(p, SRC_CASE_PATTERN, p->tree->nodes[pattern].start,
                  p->tree->nodes[pattern].end, pattern));
        } while (take(p, ",") && !p->tree->error);
      }
      if (p->token.kind == NAME) append(p, &af, &al, name(p));
    }
    expect(p, "=>"); append(p, &af, &al, src_block(p));
    append(p, &first, &last, mark(p, src_node(p, SRC_CASE_ARM, begin, src_end(p, al, begin), af), wildcard ? EXP_WILDCARD : 0));
    if (is(p, ",")) fail(p, p->token.start, "case arms are not separated by commas");
  }
  uint32_t end = p->token.end; expect(p, "}");
  return src_node(p, SRC_CASE, start, end, first);
}
static bool src_expression_start(Parser *p) {
  if (is(p, "return") || is(p, "break") || is(p, "continue") ||
      is(p, "const") || is(p, "if") || is(p, "case") || is(p, "for") ||
      is(p, "defer") || is(p, "type") || src_distinct(p)) return false;
  return p->token.kind == NAME || p->token.kind == NUMBER || p->token.kind == STRING ||
      p->token.kind == CHARACTER || is(p, "(") || is(p, "[") || is(p, ".") ||
      is(p, "-") || is(p, "&") || is(p, "!") || is(p, "~") ||
      is(p, "#cast") || is(p, "#bitcast") || is(p, "#sizeof") ||
      is(p, "#alignof") || is(p, "#offsetof") || is(p, "#typeof") ||
      is(p, "#len") || is(p, "#wrap") || is(p, "#load") || is(p, "#syscall");
}
static uint32_t src_panic(Parser *p) {
  uint32_t start = p->token.start; expect(p, "#panic"); expect(p, "(");
  uint32_t child = expression(p, 0), end = p->token.end; expect(p, ")");
  return src_node(p, SRC_PANIC, start, end, child);
}
static bool src_assignment_operator(Parser *p) {
  return is(p, "=") || is(p, "+=") || is(p, "-=") || is(p, "*=") ||
      is(p, "/=") || is(p, "%=") || is(p, "&=") || is(p, "|=") ||
      is(p, "^=") || is(p, "<<=") || is(p, ">>=");
}
static bool src_primary_kind(unsigned kind) {
  return kind == EXP_NAME || kind == EXP_GROUP || kind == EXP_DEREF ||
      kind == EXP_CALL || kind == EXP_FIELD || kind == EXP_INDEX || kind == EXP_SLICE;
}
static uint32_t src_statement_body(Parser *p) {
  if (p->tree->error) return NONE;
  uint32_t start = p->token.start;
  if (is(p, "if")) return src_if(p);
  if (is(p, "case")) return src_case(p);
  if (is(p, "for")) return src_for(p);
  if (is(p, "const")) return src_const(p);
  if (is(p, "type") || src_distinct(p)) return src_alias(p);
  if (is(p, "#panic")) return src_panic(p);
  if (is(p, "defer")) {
    lex(p); uint32_t child = is(p, "{") ? src_block(p) : src_statement(p);
    if (child != NONE) {
      unsigned kind = p->tree->nodes[child].kind;
      if (kind != SRC_BLOCK && kind != EXP_CALL && kind != SRC_ASSIGNMENT &&
          kind != SRC_IF && kind != SRC_CASE && kind != SRC_FOR &&
          kind != SRC_PANIC && kind != EXP_SYSCALL)
        fail(p, start, "invalid deferred statement");
    }
    return src_node(p, SRC_DEFER, start, src_end(p, child, start), child);
  }
  if (is(p, "break") || is(p, "continue")) {
    unsigned kind = is(p, "break") ? SRC_BREAK : SRC_CONTINUE;
    uint32_t end = p->token.end; lex(p);
    uint32_t child = take(p, ":") ? name(p) : NONE;
    return src_node(p, kind, start, src_end(p, child, end), child);
  }
  if (is(p, "return")) {
    uint32_t end = p->token.end; lex(p);
    uint32_t child = NONE;
    if (src_expression_start(p)) {
      Parser saved = *p; uint32_t count = p->tree->count;
      child = expression(p, 0);
      if (p->tree->error) {
        if (!src_restore(p, saved, count)) return NONE;
        child = NONE;
      }
    }
    return src_node(p, SRC_RETURN, start, src_end(p, child, end), child);
  }
  if (p->token.kind == NAME && !is(p, "true") && !is(p, "false") && !is(p, "nil") &&
      (src_next_is(p, ":") || src_next_is(p, ":="))) {
    Parser probe = *p; ExpTree scratch = {0}; probe.tree = &scratch;
    lex(&probe); bool colon = take(&probe, ":");
    if (scratch.error) { propagate_error(p, &scratch); return NONE; }
    if (colon && is(&probe, "for")) return src_for(p);
    return src_variable(p);
  }
  uint32_t value = expression(p, 0);
  if (value == NONE) return NONE;
  if (src_assignment_operator(p)) {
    if (!src_primary_kind(p->tree->nodes[value].kind)) {
      fail(p, start, "assignment target must be primary"); return NONE;
    }
    Token operator = p->token; lex(p); uint32_t right = expression(p, 0);
    if (right == NONE) return NONE;
    p->tree->nodes[value].next = right;
    return node(p, (ExpKind)SRC_ASSIGNMENT, start, p->tree->nodes[right].end, value, operator);
  }
  if (p->tree->nodes[value].kind != EXP_CALL && p->tree->nodes[value].kind != EXP_SYSCALL) {
    fail(p, start, "expression is not a statement"); return NONE;
  }
  p->tree->nodes[value].flags &= ~EXP_PRIMARY;
  return value;
}
static uint32_t src_statement(Parser *p) {
  if (p->tree->error) return NONE;
  if (++p->depth > depth_limit(p)) { --p->depth; fail(p, p->token.start, "source nesting limit exceeded"); return NONE; }
  uint32_t value = src_statement_body(p); --p->depth; return value;
}
/* Recovery records the pending syntax error, rewinds to the failed item and
   skips to a synchronization token: one at the start of a line, at or after the
   error, and either outside every bracket opened by the item or indented no
   deeper than the item. Blocks also stop before their closing brace; the top
   level stops only at column zero. At least one token is always skipped. */
static bool src_line_start(Parser *p, uint32_t offset) {
  while (offset && (p->text[offset - 1] == ' ' || p->text[offset - 1] == '\t')) --offset;
  return !offset || p->text[offset - 1] == '\n';
}
static uint32_t src_column(Parser *p, uint32_t offset) {
  uint32_t line = offset;
  while (line && p->text[line - 1] != '\n') --line;
  return offset - line;
}
static bool src_record(Parser *p) {
  ExpTree *t = p->tree;
  if (!p->options || !p->options->recover || t->error_kind != EXP_SYNTAX_ERROR) return false;
  if (t->error_count == t->error_capacity) {
    uint32_t capacity = t->error_capacity ? t->error_capacity * 2 : 8;
    ExpSyntaxError *errors = capacity > t->error_capacity ? realloc(t->errors, capacity * sizeof(*errors)) : NULL;
    if (!errors) { t->error = "out of memory"; t->error_kind = EXP_ALLOCATION_ERROR; return false; }
    t->errors = errors; t->error_capacity = capacity;
  }
  t->errors[t->error_count++] = (ExpSyntaxError){t->error_offset, t->error, t->error_expected};
  return true;
}
/* An invalid token: resume lexing at the end of its line. */
static void src_resume(Parser *p, uint32_t *end) {
  ExpTree *t = p->tree;
  while (t->error_kind == EXP_SYNTAX_ERROR) {
    uint32_t resume = t->error_offset > *end ? t->error_offset : *end;
    while (resume < p->length && p->text[resume] != '\n') ++resume;
    t->error = NULL; t->error_expected = NULL; t->error_kind = EXP_OK;
    *end = resume; p->offset = resume; lex(p);
  }
}
static uint32_t src_recover(Parser *p, Parser saved, uint32_t count, bool top) {
  ExpTree *t = p->tree;
  uint32_t offset = t->error_offset;
  if (!src_record(p)) return NONE;
  uint32_t start = saved.token.start, column = src_column(p, start), end = saved.token.end;
  if (!src_restore(p, saved, count)) return NONE;
  t->error_expected = NULL;
  /* Braces are counted apart from parentheses and brackets: an unmatched
     brace always belongs to an enclosing block. */
  uint32_t braces = 0, parens = 0;
  while (p->token.kind != END && !t->error) {
    uint32_t at = p->token.start;
    bool brace = is(p, "}"), closer = brace || is(p, ")") || is(p, "]");
    if (!top && brace && !braces && at > start) break;
    if (at > start && at >= offset && src_line_start(p, at)) {
      uint32_t indent = src_column(p, at);
      /* A closer aligned with the item ends the item's own bracket. */
      bool own = closer && indent == column && (brace ? braces : parens) > 0;
      if (!own && (top ? !indent : (!braces && !parens) || indent <= column)) break;
    }
    if (is(p, "{")) ++braces;
    else if (is(p, "(") || is(p, "[")) ++parens;
    else if (brace) { if (braces) --braces; }
    else if (closer && parens) --parens;
    end = p->token.end; lex(p);
    src_resume(p, &end);
  }
  if (t->error) return NONE;
  return src_node(p, SRC_ERROR, start, end, NONE);
}
static uint32_t src_block(Parser *p) {
  uint32_t start = p->token.start, first = NONE, last = NONE;
  expect(p, "{");
  while (!is(p, "}") && !p->tree->error && p->token.kind != END) {
    Parser saved = *p; uint32_t count = p->tree->count;
    uint32_t statement = src_statement(p);
    if (!p->tree->error && !is(p, "}") && p->token.kind != END && !src_line_start(p, p->token.start))
      fail(p, p->token.start, "each statement must start on its own line");
    if (p->tree->error) statement = src_recover(p, saved, count, false);
    append(p, &first, &last, statement);
  }
  uint32_t end = p->token.end; expect(p, "}");
  return src_node(p, SRC_BLOCK, start, end, first);
}
static uint32_t src_param(Parser *p, bool variadic_allowed) {
  uint32_t start = p->token.start, first = NONE, last = NONE;
  if (at(p, start, "$")) {
    Token token = p->token; lex(p);
    append(p, &first, &last, node(p, EXP_TYPE_PARAMETER, start, token.end, NONE, (Token){0}));
  } else {
    append(p, &first, &last, name(p));
    while (take(p, ",") && !p->tree->error) append(p, &first, &last, name(p));
  }
  uint32_t colon = p->token.start; expect(p, ":");
  if (variadic_allowed && (is(p, "..") || is(p, "..."))) {
    if (first != last || (first != NONE && p->tree->nodes[first].kind != EXP_NAME))
      fail(p, start, "variadic parameter requires one identifier");
    append(p, &first, &last, src_variadic(p));
    append(p, &first, &last, type(p));
    return src_node(p, SRC_VARIADIC_PARAM, start, src_end(p, last, start), first);
  }
  uint32_t target = type(p);
  append(p, &first, &last, src_node(p, SRC_QUALIFIER, colon, src_end(p, target, colon), target));
  return src_node(p, SRC_FN_PARAM, start, src_end(p, last, start), first);
}
static uint32_t src_function(Parser *p, bool external) {
  uint32_t start = p->token.start, first = NONE, last = NONE;
  if (external) expect(p, "extern");
  expect(p, "fn"); append(p, &first, &last, name(p));
  if (external && p->token.kind == STRING)
    append(p, &first, &last, src_literal(p, STRING, EXP_STRING));
  expect(p, "(");
  while (!is(p, ")") && !p->tree->error) {
    if (external && (is(p, "..") || is(p, "..."))) {
      append(p, &first, &last, src_variadic(p)); break;
    }
    append(p, &first, &last, src_param(p, !external));
    if (!take(p, ",")) break;
  }
  uint32_t end = p->token.end; expect(p, ")");
  if (external) {
    if (optional_type_start(p)) {
      append(p, &first, &last, type(p)); end = src_end(p, last, end);
    }
  } else {
    if (!is(p, "{")) append(p, &first, &last, type(p));
    append(p, &first, &last, src_block(p)); end = src_end(p, last, end);
  }
  return src_node(p, external ? SRC_EXTERN_FN : SRC_FN, start, end, first);
}
static uint32_t src_struct(Parser *p) {
  uint32_t start = p->token.start, first = NONE, last = NONE;
  bool packed = take(p, "packed"); expect(p, "struct"); append(p, &first, &last, name(p)); expect(p, "{");
  while (!is(p, "}") && !p->tree->error) {
    uint32_t begin = p->token.start, mf = NONE, ml = NONE;
    append(p, &mf, &ml, name(p));
    while (take(p, ",") && !p->tree->error) append(p, &mf, &ml, name(p));
    append(p, &mf, &ml, src_qualifier(p));
    if (take(p, "=")) append(p, &mf, &ml, expression(p, 0));
    append(p, &first, &last, src_node(p, SRC_STRUCT_MEMBER, begin, src_end(p, ml, begin), mf));
    if (!take(p, ",")) break;
  }
  uint32_t end = p->token.end; expect(p, "}");
  return mark(p, src_node(p, SRC_STRUCT, start, end, first), packed ? EXP_PACKED : 0);
}
static uint32_t src_enum(Parser *p) {
  uint32_t start = p->token.start, first = NONE, last = NONE;
  expect(p, "enum");
  if (take(p, "(")) {
    if (!primitive(p) && p->token.kind != NAME) fail(p, p->token.start, "invalid enum tag type");
    append(p, &first, &last, type_body(p)); expect(p, ")");
  }
  append(p, &first, &last, name(p)); expect(p, "{");
  while (!is(p, "}") && !p->tree->error) {
    uint32_t begin = p->token.start, mf = NONE, ml = NONE;
    append(p, &mf, &ml, name(p));
    if (is(p, ":")) append(p, &mf, &ml, src_qualifier(p));
    if (take(p, "=")) append(p, &mf, &ml, expression(p, 0));
    append(p, &first, &last, src_node(p, SRC_ENUM_MEMBER, begin, src_end(p, ml, begin), mf));
    if (!take(p, ",")) break;
  }
  uint32_t end = p->token.end; expect(p, "}");
  return src_node(p, SRC_ENUM, start, end, first);
}
static bool src_declaration_keyword(Parser *p) {
  return is(p, "fn") || is(p, "pub") || is(p, "const") || is(p, "extern") ||
      is(p, "struct") || src_packed(p) || is(p, "enum") || is(p, "type") ||
      src_distinct(p) || is(p, "use");
}
static uint32_t src_use(Parser *p) {
  uint32_t start = p->token.start, first = NONE, last = NONE;
  expect(p, "use");
  do {
    uint32_t begin = p->token.start, path = src_literal(p, STRING, EXP_STRING), end = src_end(p, path, begin);
    if (p->token.kind == NAME && !src_declaration_keyword(p) &&
        !src_next_is(p, ":") && !src_next_is(p, ":=")) {
      uint32_t alias = name(p);
      if (path != NONE) p->tree->nodes[path].next = alias;
      end = src_end(p, alias, end);
    }
    append(p, &first, &last, src_node(p, SRC_IMPORT, begin, end, path));
  } while (take(p, ",") && !p->tree->error);
  return src_node(p, SRC_USE, start, src_end(p, last, start), first);
}
static uint32_t src_assert(Parser *p) {
  uint32_t start = p->token.start, first = NONE, last = NONE;
  expect(p, "#assert"); expect(p, "("); append(p, &first, &last, expression(p, 0));
  if (take(p, ",")) append(p, &first, &last, src_literal(p, STRING, EXP_STRING));
  uint32_t end = p->token.end; expect(p, ")");
  return src_node(p, SRC_ASSERT, start, end, first);
}
static uint32_t src_directive(Parser *p) {
  bool target = is(p, "#target");
  uint32_t start = p->token.start, first = NONE, last = NONE;
  lex(p); expect(p, "(");
  if (target) {
    do {
      uint32_t begin = p->token.start, cf = NONE, cl = NONE;
      append(p, &cf, &cl, name(p)); expect(p, ":");
      append(p, &cf, &cl, p->token.kind == NUMBER ? src_literal(p, NUMBER, EXP_NUMBER) : name(p));
      append(p, &first, &last, src_node(p, SRC_TARGET_CONDITION, begin, src_end(p, cl, begin), cf));
    } while (take(p, ",") && !p->tree->error);
  } else append(p, &first, &last, src_literal(p, STRING, EXP_STRING));
  uint32_t end = p->token.end; expect(p, ")");
  return src_node(p, target ? SRC_TARGET : SRC_LINK, start, end, first);
}
static uint32_t src_declaration(Parser *p) {
  if (is(p, "#target") || is(p, "#link")) return src_directive(p);
  uint32_t start = p->token.start, child;
  bool public = take(p, "pub");
  if (is(p, "fn")) child = src_function(p, false);
  else if (is(p, "extern")) {
    if (src_next_is(p, "fn")) child = src_function(p, true);
    else {
      uint32_t begin = p->token.start, first = NONE, last = NONE; lex(p);
      append(p, &first, &last, name(p));
      if (p->token.kind == STRING) append(p, &first, &last, src_literal(p, STRING, EXP_STRING));
      append(p, &first, &last, src_qualifier(p));
      child = src_node(p, SRC_EXTERN_VARIABLE, begin, src_end(p, last, begin), first);
    }
  } else if (is(p, "struct") || src_packed(p)) child = src_struct(p);
  else if (is(p, "enum")) child = src_enum(p);
  else if (is(p, "const")) child = src_const(p);
  else if (is(p, "type") || src_distinct(p)) child = src_alias(p);
  else if (!public && is(p, "use")) child = src_use(p);
  else if (!public && is(p, "#assert")) child = src_assert(p);
  else if (p->token.kind == NAME && src_peek(p).kind == END) {
    /* A dangling declaration name is the offending token, not the empty
       position after its trailing newline. Editors need a visible range. */
    fail(p, p->token.start, "incomplete or invalid syntax");
    child = NONE;
  } else child = src_variable(p);
  return mark(p, src_node(p, SRC_DECLARATION, start, src_end(p, child, start), child), public ? EXP_PUBLIC : 0);
}
bool exp_parse_source_with_options(const char *source, size_t length, ExpTree *tree, const ExpOptions *options) {
  tree->count = 0; tree->root = NONE; tree->error = NULL; tree->error_expected = NULL; tree->error_kind = EXP_OK; tree->error_offset = 0;
  tree->error_count = 0;
  if (length > UINT32_MAX || (!source && length)) { tree->error = "invalid source or source too large"; tree->error_kind = EXP_LIMIT_ERROR; return false; }
  uint64_t work_remaining = options && options->max_work ? options->max_work : (uint64_t)length * 128 + 1024;
  Parser p = {.text = source, .length = (uint32_t)length, .tree = tree,
              .work_remaining = &work_remaining, .options = options};
  if (!charge(&p, length, 0)) return false;
  /* Sources are text: NUL is never valid, even in comments or literals. */
  const char *nul = length ? memchr(source, '\0', length) : NULL;
  if (nul) { fail(&p, (uint32_t)(nul - source), "unexpected character"); return false; }
  lex(&p); uint32_t first = NONE, last = NONE;
  if (tree->error && src_record(&p)) {
    uint32_t end = 0;
    src_resume(&p, &end);
  }
  while (p.token.kind != END && !tree->error) {
    uint32_t offset = p.token.start;
    Parser saved = p; uint32_t count = tree->count;
    uint32_t declaration = src_declaration(&p);
    if (tree->error) declaration = src_recover(&p, saved, count, true);
    append(&p, &first, &last, declaration);
    if (!tree->error && p.token.start == offset) fail(&p, offset, "source parser made no progress");
  }
  uint32_t start = 0; p.scan_next = 0;
  if (tree->error) return false;
  while (start < length && space((unsigned char)source[start])) {
    if (!scan_byte(&p, start)) return false;
    ++start;
  }
  uint32_t root = src_node(&p, SRC_FILE, start, (uint32_t)length, first);
  if (tree->error) return false;
  if (!finish_tree(&p, root)) return false;
  tree->root = root; return true;
}

/* Finalize only reachable nodes. Speculative parses can leave discarded nodes;
   they must not overwrite the parent or field role of a retained child. */
static bool finish_tree(Parser *p, uint32_t root) {
  ExpTree *tree = p->tree;
  uint32_t id = root;
  tree->nodes[root].parent = NONE;
  for (;;) {
    ExpNode *n = &tree->nodes[id];
    if (!charge(p, 1, n->start)) return false;
    for (uint32_t child = n->first; child != NONE; child = tree->nodes[child].next) {
      ExpNode *c = &tree->nodes[child];
      if (!charge(p, 1, c->start)) return false;
      c->parent = id;
      switch (n->kind) {
      case EXP_CALL:
        if (child != n->first) c->field = EXP_ROLE_CALL_ARGS;
        break;
      case EXP_ARRAY_TYPE:
        if (c->kind != EXP_TYPE) c->field = EXP_ROLE_LENGTH;
        break;
      case SRC_FN: case SRC_EXTERN_FN: case SRC_EXTERN_VARIABLE:
        if (child == n->first) c->field = EXP_ROLE_NAME;
        else if (c->kind == EXP_STRING) c->field = EXP_ROLE_LINK_NAME;
        break;
      case SRC_VARIADIC_PARAM:
        if (child == n->first) c->field = EXP_ROLE_NAME;
        else if (c->kind == EXP_TYPE) c->field = EXP_ROLE_TYPE;
        break;
      case SRC_IMPORT:
        c->field = child == n->first ? EXP_ROLE_PATH : EXP_ROLE_ALIAS;
        break;
      case SRC_LINK: c->field = EXP_ROLE_LIBRARY; break;
      default: break;
      }
    }
    if (n->first != NONE) { id = n->first; continue; }
    while (id != root && tree->nodes[id].next == NONE) {
      if (!charge(p, 1, tree->nodes[id].start)) return false;
      id = tree->nodes[id].parent;
    }
    if (id == root) break;
    id = tree->nodes[id].next;
  }
  return true;
}

bool exp_parse_source(const char *source, size_t length, ExpTree *tree) {
  return exp_parse_source_with_options(source, length, tree, NULL);
}
