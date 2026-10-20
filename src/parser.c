#include "parser.h"
#include <stdlib.h>
#include <string.h>

#define NONE UINT32_MAX
#define MAX_DEPTH 1024
/* Multi-byte punctuation uses its spelling rather than a public token enum. */
typedef enum { END, NAME, NUMBER, STRING, CHARACTER, PUNCT, BAD } TokenKind;
typedef struct { uint32_t start, end; TokenKind kind; } Token;
typedef struct {
  const char *text;
  uint32_t length, offset, depth;
  uint32_t block_brace;
  uint64_t scan_next;
  uint64_t *work_remaining;
  const ExpOptions *options;
  Token token;
  ExpTree *tree;
} Parser;
static bool alpha(unsigned char c) {
  return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_';
}
static bool digit(unsigned char c) { return c >= '0' && c <= '9'; }
static bool hex(unsigned char c) {
  return digit(c) || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}
static bool space(unsigned char c) {
  return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v';
}
static void fail(Parser *p, uint32_t offset, const char *message) {
  if (!p->tree->error) {
    p->tree->error = message; p->tree->error_offset = offset; p->tree->error_expected = NULL;
    p->tree->error_kind = !strcmp(message, "out of memory") ? EXP_ALLOCATION_ERROR :
      (!strcmp(message, "tree too large") || strstr(message, "limit exceeded")) ? EXP_LIMIT_ERROR : EXP_SYNTAX_ERROR;
  }
}
static void propagate_error(Parser *p, const ExpTree *from) {
  if (!p->tree->error && from->error) {
    p->tree->error = from->error;
    p->tree->error_offset = from->error_offset;
    p->tree->error_kind = from->error_kind;
    p->tree->error_expected = from->error_expected;
  }
}
static bool charge(Parser *p, uint64_t units, uint32_t offset) {
  if (p->tree->error) return false;
  if (p->work_remaining) {
    if (units > *p->work_remaining) { *p->work_remaining = 0; fail(p, offset, "parse work limit exceeded"); return false; }
    *p->work_remaining -= units;
  }
  if (p->options && p->options->work && !p->options->work(p->options->data, units)) {
    fail(p, offset, "analysis work budget exceeded or cancelled");
    p->tree->error_kind = EXP_CANCELLED;
    return false;
  }
  return true;
}
static bool scan_byte(Parser *p, uint32_t offset) {
  if (offset < 1024 || offset < p->scan_next) return true;
  p->scan_next = (uint64_t)offset + 1024;
  return charge(p, 1024, offset);
}
static uint32_t depth_limit(Parser *p) {
  uint32_t requested = p->options ? p->options->max_depth : 0;
  return requested && requested < MAX_DEPTH ? requested : MAX_DEPTH;
}
static bool at(Parser *p, uint32_t offset, const char *s) {
  size_t n = strlen(s);
  return offset <= p->length && n <= p->length - offset && !memcmp(p->text + offset, s, n);
}
static bool is(Parser *p, const char *s) {
  return strlen(s) == p->token.end - p->token.start && at(p, p->token.start, s);
}
static bool escape(Parser *p, uint32_t *i) {
  if (*i == p->length) return false;
  unsigned char c = p->text[(*i)++];
  if (strchr("nrt0\\\"'", c) && c) return true;
  if (c == 'x') {
    if (p->length - *i < 2 || !hex(p->text[*i]) || !hex(p->text[*i + 1])) return false;
    *i += 2; return true;
  }
  if (c == 'u' && *i < p->length && p->text[*i] == '{') {
    uint32_t start = ++*i;
    while (*i < p->length && *i - start <= 6 && hex(p->text[*i])) ++*i;
    if (*i == start || *i - start > 6 || *i == p->length || p->text[*i] != '}') return false;
    ++*i; return true;
  }
  return false;
}
static void lex(Parser *p) {
  if (!charge(p, 1, p->offset)) {
    p->token = (Token){p->offset, p->offset, END};
    return;
  }
  uint32_t i = p->offset;
  bool external_space = true;
  for (;;) {
    while (i < p->length && space(p->text[i])) {
      if (!scan_byte(p, i)) return;
      if (p->text[i] == '\v') external_space = false;
      ++i;
    }
    if (at(p, i, "//")) {
      i += 2; while (i < p->length && p->text[i] != '\n') { if (!scan_byte(p, i)) return; ++i; }
      external_space = true;
    } else if (at(p, i, "/*")) {
      uint32_t start = i; i += 2;
      while (i < p->length && !at(p, i, "*/")) { if (!scan_byte(p, i)) return; ++i; }
      if (i == p->length) { fail(p, start, "unterminated comment"); break; }
      i += 2;
      external_space = true;
    } else break;
  }
  uint32_t start = i;
  TokenKind kind = PUNCT;
  if (i == p->length) kind = END;
  else if (alpha(p->text[i])) {
    kind = NAME; ++i;
    while (i < p->length && (alpha(p->text[i]) || digit(p->text[i]))) { if (!scan_byte(p, i)) return; ++i; }
  } else if (digit(p->text[i]) || (p->text[i] == '.' && i + 1 < p->length && digit(p->text[i + 1]))) {
    kind = NUMBER;
    if (at(p, i, "0x") || at(p, i, "0b") || at(p, i, "0o")) {
      char base = p->text[i + 1]; i += 2; uint32_t digits = i;
      while (i < p->length && (p->text[i] == '_' ||
        (base == 'x' ? hex(p->text[i]) : p->text[i] >= '0' && p->text[i] <= (base == 'b' ? '1' : '7')))) { if (!scan_byte(p, i)) return; ++i; }
      if (i == digits) fail(p, start, "missing base digits");
    } else {
      bool leading_dot = p->text[i] == '.';
      if (leading_dot) ++i;
      while (i < p->length && (digit(p->text[i]) || p->text[i] == '_')) { if (!scan_byte(p, i)) return; ++i; }
      bool trailing_dot = false;
      if (!leading_dot && i < p->length && p->text[i] == '.' && !at(p, i, "..")) {
        ++i; uint32_t first = i;
        /* The grammar requires a digit immediately after a decimal point. */
        if (i < p->length && digit(p->text[i])) {
          ++i; while (i < p->length && (digit(p->text[i]) || p->text[i] == '_')) { if (!scan_byte(p, i)) return; ++i; }
        }
        trailing_dot = first == i;
        if (trailing_dot && !external_space) fail(p, start, "unsupported trailing float whitespace");
      }
      if (!trailing_dot && i < p->length && (p->text[i] == 'e' || p->text[i] == 'E')) {
        uint32_t exponent = i++;
        if (i < p->length && (p->text[i] == '+' || p->text[i] == '-')) ++i;
        if (i == p->length || !digit(p->text[i])) i = exponent;
        else { ++i; while (i < p->length && (digit(p->text[i]) || p->text[i] == '_')) { if (!scan_byte(p, i)) return; ++i; } }
      }
    }
  } else if (p->text[i] == '"' || p->text[i] == '\'') {
    char quote = p->text[i++]; kind = quote == '"' ? STRING : CHARACTER;
    unsigned characters = 0;
    while (i < p->length && p->text[i] != quote && p->text[i] != '\n') {
      if (!scan_byte(p, i)) return;
      ++characters;
      if (p->text[i] == '\\') {
        ++i; if (!escape(p, &i)) { fail(p, i, "invalid escape"); break; }
      } else {
        /* Count UTF-8 scalar values, rejecting malformed encodings. */
        unsigned char c = p->text[i++];
        unsigned n = c < 0x80 ? 0 : c >= 0xc2 && c <= 0xdf ? 1 : c >= 0xe0 && c <= 0xef ? 2 : c >= 0xf0 && c <= 0xf4 ? 3 : 4;
        if (n == 4 || n > p->length - i) { fail(p, i - 1, "invalid UTF-8"); break; }
        if (n && ((c == 0xe0 && (unsigned char)p->text[i] < 0xa0) ||
                  (c == 0xed && (unsigned char)p->text[i] >= 0xa0) ||
                  (c == 0xf0 && (unsigned char)p->text[i] < 0x90) ||
                  (c == 0xf4 && (unsigned char)p->text[i] >= 0x90))) fail(p, i - 1, "invalid UTF-8");
        while (n--) { if (((unsigned char)p->text[i] & 0xc0) != 0x80) fail(p, i, "invalid UTF-8"); ++i; }
      }
    }
    if (i == p->length || p->text[i] != quote) fail(p, start, "unterminated literal");
    else ++i;
    if (kind == CHARACTER && characters != 1) fail(p, start, "character literal requires one character");
  } else {
    unsigned char c = p->text[i++];
    if (c == '$') {
      if (i == p->length || !alpha(p->text[i])) fail(p, start, "expected type parameter");
      while (i < p->length && (alpha(p->text[i]) || digit(p->text[i]))) { if (!scan_byte(p, i)) return; ++i; }
    } else if (c == '#') {
      while (i < p->length && alpha(p->text[i])) { if (!scan_byte(p, i)) return; ++i; }
    } else {
      unsigned char next = i < p->length ? p->text[i] : 0;
      bool pair = (c == '.' && (next == '.' || next == '*')) ||
                  ((c == '<' || c == '>') && next == c) ||
                  ((c == '&' || c == '|') && next == c) ||
                  (next == '=' && c && strchr(":+-*/%&|^!<>=", c)) ||
                  (c == '=' && next == '>');
      if (pair) {
        ++i;
        if (((c == '.' && next == '.') || ((c == '<' || c == '>') && next == c)) &&
            i < p->length && p->text[i] == '=') ++i;
      } else if (!c || !strchr("()[]{}.,:+-*/%&|^!~<>=", c)) {
        kind = BAD; fail(p, start, "unexpected character");
      }
    }
  }
  p->token = (Token){start, i, kind}; p->offset = i;
}
static bool take(Parser *p, const char *s) {
  if (!is(p, s)) return false;
  lex(p); return true;
}
static void expect(Parser *p, const char *s) {
  if (take(p, s) || p->tree->error) return;
  fail(p, p->token.start, "unexpected token");
  p->tree->error_expected = s;
}
static uint32_t node(Parser *p, ExpKind kind, uint32_t start, uint32_t end, uint32_t first, Token op) {
  ExpTree *t = p->tree;
  if (t->error) return NONE;
  if (t->count == t->capacity) {
    uint32_t capacity = t->capacity ? t->capacity * 2 : 64;
    size_t bytes = (size_t)capacity * sizeof(ExpNode);
    if (capacity < t->capacity || bytes / sizeof(ExpNode) != capacity) { fail(p, start, "tree too large"); return NONE; }
    ExpNode *nodes = realloc(t->nodes, bytes);
    if (!nodes) { fail(p, start, "out of memory"); return NONE; }
    t->nodes = nodes; t->capacity = capacity;
  }
  uint32_t id = t->count++;
  t->nodes[id] = (ExpNode){.start=start, .end=end, .first=first, .next=NONE,
    .operator_start=op.start, .parent=NONE, .kind=(uint16_t)kind,
    .operator_length=(uint16_t)(op.end - op.start)};
  return id;
}
static uint32_t mark(Parser *p, uint32_t id, unsigned flags) {
  if (id != NONE) p->tree->nodes[id].flags |= flags;
  return id;
}
static bool finish_tree(Parser *p, uint32_t root);
static int precedence(Parser *p) {
  uint32_t n = p->token.end - p->token.start;
  if (!n || n > 2) return 0;
  unsigned char c = p->text[p->token.start];
  if (n == 2) {
    unsigned char next = p->text[p->token.start + 1];
    if (next == c) {
      if (c == '|') return 2;
      if (c == '&') return 3;
      if (c == '<' || c == '>') return 9;
    }
    if (next == '=') {
      if (c == '=' || c == '!') return 4;
      if (c == '<' || c == '>') return 5;
    }
    return 0;
  }
  switch (c) {
  case '<': case '>': return 5;
  case '|': return 6;
  case '^': return 7;
  case '&': return 8;
  case '+': case '-': return 10;
  case '*': case '/': case '%': return 11;
  default: return 0;
  }
}
static uint32_t expression(Parser *p, int minimum);
static uint32_t type(Parser *p);
static uint32_t aggregate(Parser *p);
static uint32_t expression_tail(Parser *p, uint32_t left, bool primary, int minimum);
static bool primitive(Parser *p) {
  static const char *const names[] = {"i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64", "f32", "f64", "isize", "usize", "bool", "rawptr", "any"};
  for (size_t i = 0; i < sizeof(names) / sizeof(*names); ++i)
    if (is(p, names[i])) return true;
  return false;
}
static bool optional_type_start(Parser *p) {
  static const char *const declarations[] = {"fn", "pub", "use", "const", "type", "distinct", "packed", "struct", "enum", "extern"};
  for (size_t i = 0; i < sizeof(declarations) / sizeof(*declarations); ++i)
    if (is(p, declarations[i])) return false;
  return p->token.kind == NAME || is(p, "*") || is(p, "[") || at(p, p->token.start, "$");
}
static void append(Parser *p, uint32_t *first, uint32_t *last, uint32_t child) {
  if (child == NONE || p->tree->error) return;
  if (*first == NONE) *first = child;
  else p->tree->nodes[*last].next = child;
  *last = child;
}
static uint32_t name(Parser *p) {
  Token token = p->token;
  if (token.kind != NAME) { fail(p, token.start, "expected identifier"); return NONE; }
  lex(p);
  return node(p, EXP_NAME, token.start, token.end, NONE, (Token){0});
}
static uint32_t type_body(Parser *p) {
  if (p->tree->error) return NONE;
  Token token = p->token;
  uint32_t first = NONE, last = NONE, end = token.end;
  ExpKind kind;
  unsigned flags = 0;
  if (take(p, "*")) {
    kind = EXP_POINTER_TYPE;
    uint32_t fn_start = p->token.start;
    if (take(p, "fn")) {
      expect(p, "(");
      while (!is(p, ")") && !p->tree->error) {
        append(p, &first, &last, type(p));
        if (!take(p, ",")) break;
      }
      end = p->token.end; expect(p, ")");
      if (optional_type_start(p)) {
        append(p, &first, &last, type(p));
        if (last != NONE) p->tree->nodes[last].field = EXP_ROLE_RETURN;
        if (last != NONE) end = p->tree->nodes[last].end;
      }
      first = node(p, EXP_FN_TYPE, fn_start, end, first, (Token){0});
    } else {
      if (take(p, "const")) flags |= EXP_CONST;
      first = type(p);
      if (first != NONE) end = p->tree->nodes[first].end;
    }
  } else if (take(p, "[")) {
    kind = EXP_ARRAY_TYPE;
    if (!is(p, "]")) append(p, &first, &last, expression(p, 0));
    expect(p, "]"); if (take(p, "const")) flags |= EXP_CONST;
    append(p, &first, &last, type(p));
    if (last != NONE) end = p->tree->nodes[last].end;
  } else if (primitive(p)) {
    kind = EXP_PRIMITIVE; lex(p);
  } else if (at(p, token.start, "$")) {
    kind = EXP_TYPE_PARAMETER; lex(p);
  } else if (token.kind == NAME) {
    kind = EXP_FIELD_TYPE;
    append(p, &first, &last, name(p));
    while (take(p, ".") && !p->tree->error) append(p, &first, &last, name(p));
    if (last != NONE) end = p->tree->nodes[last].end;
  } else { fail(p, token.start, "expected type"); return NONE; }
  return mark(p, node(p, kind, token.start, end, first, (Token){0}), flags);
}
static uint32_t type(Parser *p) {
  if (p->tree->error) return NONE;
  if (++p->depth > depth_limit(p)) { fail(p, p->token.start, "expression nesting limit exceeded"); --p->depth; return NONE; }
  uint32_t start = p->token.start, child = type_body(p);
  --p->depth;
  return child == NONE ? NONE : node(p, EXP_TYPE, start, p->tree->nodes[child].end, child, (Token){0});
}
/* Ambiguous array literals and names are resolved at the enclosing delimiter.
   Speculation retains allocated capacity but never hides allocation failure. */
static bool resource_error(Parser *p) {
  return p->tree->error_kind >= EXP_ALLOCATION_ERROR;
}
static uint32_t array_type_suffix(Parser *p, uint32_t array, bool named) {
  uint32_t first = p->tree->nodes[array].first;
  if (first != NONE) {
    if (p->tree->nodes[first].next != NONE) { fail(p, p->token.start, "array type requires one length"); return NONE; }
    Parser closing = *p; closing.offset = p->tree->nodes[first].end; closing.scan_next = 0; lex(&closing);
    if (!is(&closing, "]")) { fail(p, closing.token.start, "array type length cannot have a comma"); return NONE; }
  }
  bool is_const = take(p, "const"); uint32_t element = type(p);
  if (element == NONE) return NONE;
  if (first != NONE) p->tree->nodes[first].next = element;
  else first = element;
  uint32_t start = p->tree->nodes[array].start, end = p->tree->nodes[element].end;
  uint32_t child = mark(p, node(p, EXP_ARRAY_TYPE, start, end, first, (Token){0}), is_const ? EXP_CONST : 0);
  return node(p, named ? EXP_TYPE : EXP_TYPE_ARGUMENT, start, end, child, (Token){0});
}
static uint32_t argument(Parser *p, bool allow_named_type) {
  if (p->tree->error) return NONE;
  if (is(p, "true") || is(p, "false") || is(p, "nil")) return expression(p, 0);
  if (is(p, "[")) {
    /* Parse the shared bracket contents once. Replaying them during type
       speculation makes nested array arguments take exponential work. */
    uint32_t array = aggregate(p);
    if (array == NONE) return NONE;
    Parser saved = *p;
    uint32_t count = p->tree->count, first = p->tree->nodes[array].first;
    uint32_t sibling = first == NONE ? NONE : p->tree->nodes[first].next;
    if (allow_named_type) {
      uint32_t candidate = array_type_suffix(p, array, true);
      if (!p->tree->error && (is(p, ")") || is(p, ","))) return candidate;
      if (resource_error(p)) return NONE;
      *p = saved; p->tree->count = count; p->tree->error = NULL; p->tree->error_kind = EXP_OK; p->tree->error_offset = 0;
      if (first != NONE) p->tree->nodes[first].next = sibling;
    }
    uint32_t value = expression_tail(p, array, false, 0);
    if (!p->tree->error && (is(p, ")") || is(p, ","))) return value;
    if (resource_error(p)) return NONE;
    if (allow_named_type) { fail(p, p->token.start, "expected argument delimiter"); return NONE; }
    *p = saved; p->tree->count = count; p->tree->error = NULL; p->tree->error_kind = EXP_OK; p->tree->error_offset = 0;
    p->tree->nodes[array].next = NONE;
    return array_type_suffix(p, array, false);
  }
  if (allow_named_type || primitive(p) || is(p, "*") || at(p, p->token.start, "$")) {
    bool committed = primitive(p) || is(p, "*") || at(p, p->token.start, "$");
    Parser saved = *p;
    uint32_t count = p->tree->count;
    uint32_t child = allow_named_type ? type(p) : type_body(p);
    if (!p->tree->error && (committed || is(p, ")") || is(p, ","))) {
      return allow_named_type ? child : node(p, EXP_TYPE_ARGUMENT, p->tree->nodes[child].start, p->tree->nodes[child].end, child, (Token){0});
    }
    if (resource_error(p)) return NONE;
    *p = saved; p->tree->count = count; p->tree->error = NULL; p->tree->error_kind = EXP_OK; p->tree->error_offset = 0;
  }
  return expression(p, 0);
}
static uint32_t aggregate(Parser *p) {
  uint32_t start = p->token.start, first = NONE, last = NONE;
  bool array = take(p, "[");
  if (!array) {
    if (!take(p, ".")) {
      append(p, &first, &last, name(p));
      while (take(p, ".") && !p->tree->error) append(p, &first, &last, name(p));
    }
    expect(p, "{");
  }
  const char *close = array ? "]" : "}";
  while (!is(p, close) && !p->tree->error) {
    uint32_t child;
    if (array) child = expression(p, 0);
    else {
      uint32_t member_start = p->token.start, field = name(p);
      expect(p, ":"); uint32_t value = expression(p, 0);
      if (p->tree->error) break;
      p->tree->nodes[field].next = value;
      child = node(p, EXP_MEMBER, member_start, p->tree->nodes[value].end, field, (Token){0});
    }
    append(p, &first, &last, child);
    if (!take(p, ",")) break;
  }
  uint32_t end = p->token.end; expect(p, close);
  return node(p, array ? EXP_ARRAY : EXP_STRUCT, start, end, first, (Token){0});
}
static bool struct_start(Parser *p) {
  if (p->tree->error) return false;
  if (is(p, ".")) return true;
  if (is(p, "true") || is(p, "false") || is(p, "nil")) return false;
  if (p->token.kind != NAME) return false;
  Parser probe = *p;
  ExpTree scratch = {0}; probe.tree = &scratch;
  lex(&probe);
  while (take(&probe, ".") && !scratch.error) {
    if (probe.token.kind != NAME) return false;
    lex(&probe);
  }
  propagate_error(p, &scratch);
  return !scratch.error && is(&probe, "{") && probe.token.start != p->block_brace;
}
static uint32_t parse(Parser *p, int minimum) {
  Token token = p->token;
  uint32_t left = NONE;
  bool primary = false;
  if (is(p, "[") || struct_start(p)) {
    left = aggregate(p);
  } else if (take(p, "(")) {
    uint32_t child = expression(p, 0); uint32_t end = p->token.end;
    expect(p, ")"); left = node(p, EXP_GROUP, token.start, end, child, (Token){0}); primary = true;
  } else if (is(p, "-") || is(p, "&") || is(p, "!") || is(p, "~")) {
    lex(p); uint32_t child = expression(p, 12);
    if (child != NONE) left = node(p, EXP_PREFIX, token.start, p->tree->nodes[child].end, child, token);
  } else if (is(p, "#cast") || is(p, "#bitcast")) {
    lex(p); expect(p, "("); uint32_t target = type(p);
    expect(p, ")"); uint32_t value = expression(p, 12);
    if (!p->tree->error) {
      p->tree->nodes[target].next = value;
      left = mark(p, node(p, EXP_CAST, token.start, p->tree->nodes[value].end, target, token),
          at(p, token.start, "#bitcast") ? EXP_BITCAST : 0);
    }
  } else if (is(p, "#sizeof") || is(p, "#alignof") || is(p, "#typeof") || is(p, "#offsetof")) {
    ExpKind kind = is(p, "#sizeof") ? EXP_SIZE : is(p, "#alignof") ? EXP_ALIGN : is(p, "#typeof") ? EXP_TYPEOF : EXP_OFFSET;
    lex(p); expect(p, "(");
    uint32_t child = kind == EXP_OFFSET ? type(p) : argument(p, true);
    if (kind == EXP_OFFSET) {
      expect(p, ","); uint32_t field = name(p);
      if (!p->tree->error) p->tree->nodes[child].next = field;
    }
    uint32_t end = p->token.end; expect(p, ")");
    left = node(p, kind, token.start, end, child, (Token){0});
  } else if (is(p, "#load") || is(p, "#syscall")) {
    bool load = is(p, "#load"); lex(p); expect(p, "(");
    uint32_t first = NONE, last = NONE;
    if (load) {
      Token literal = p->token;
      if (literal.kind != STRING) fail(p, literal.start, "expected string literal");
      else { lex(p); first = node(p, EXP_STRING, literal.start, literal.end, NONE, (Token){0}); }
    } else while (!is(p, ")") && !p->tree->error) {
      append(p, &first, &last, expression(p, 0));
      if (!take(p, ",")) break;
    }
    uint32_t end = p->token.end; expect(p, ")");
    left = node(p, load ? EXP_LOAD : EXP_SYSCALL, token.start, end, first, (Token){0});
  } else if (is(p, "#wrap") || is(p, "#len")) {
    ExpKind kind = is(p, "#wrap") ? EXP_WRAP : EXP_LEN;
    lex(p); expect(p, "("); uint32_t child = expression(p, 0); uint32_t end = p->token.end;
    expect(p, ")"); left = node(p, kind, token.start, end, child, (Token){0});
  } else {
    ExpKind kind = EXP_NAME;
    if (token.kind == NUMBER) kind = EXP_NUMBER;
    else if (token.kind == STRING) kind = EXP_STRING;
    else if (token.kind == CHARACTER) kind = EXP_CHAR;
    else if (token.kind == NAME && (is(p, "true") || is(p, "false"))) kind = EXP_BOOL;
    else if (token.kind == NAME && is(p, "nil")) kind = EXP_NIL;
    else if (token.kind == NAME) primary = true;
    else { fail(p, token.start, "expected expression"); return NONE; }
    lex(p); left = node(p, kind, token.start, token.end, NONE, (Token){0});
  }
  if (primary) mark(p, left, EXP_PRIMARY);
  return expression_tail(p, left, primary, minimum);
}
static uint32_t expression_tail(Parser *p, uint32_t left, bool primary, int minimum) {
  while (left != NONE && !p->tree->error) {
    Token token = p->token;
    uint32_t start = p->tree->nodes[left].start;
    if (take(p, ".*")) {
      left = mark(p, node(p, EXP_DEREF, start, token.end, left, token), EXP_PRIMARY); primary = true;
    } else if (primary && take(p, ".")) {
      if (p->token.kind != NAME) { fail(p, p->token.start, "expected field name"); break; }
      Token field = p->token; lex(p);
      uint32_t name = node(p, EXP_NAME, field.start, field.end, NONE, (Token){0});
      if (name == NONE) break;
      p->tree->nodes[left].next = name;
      left = mark(p, node(p, EXP_FIELD, start, field.end, left, (Token){0}), EXP_PRIMARY);
    } else if (primary && take(p, "(")) {
      uint32_t last = left;
      while (!is(p, ")") && !p->tree->error) {
        uint32_t arg = argument(p, false); if (arg == NONE) break;
        p->tree->nodes[last].next = arg; last = arg;
        if (!take(p, ",")) break;
      }
      uint32_t end = p->token.end; expect(p, ")");
      left = mark(p, node(p, EXP_CALL, start, end, left, (Token){0}), EXP_PRIMARY);
    } else if (primary && take(p, "[")) {
      uint32_t low = NONE, high = NONE;
      if (!is(p, "..")) low = expression(p, 0);
      Token range_token = p->token;
      bool slice = take(p, "..");
      if (slice && !is(p, "]")) high = expression(p, 0);
      uint32_t end = p->token.end; expect(p, "]");
      if (p->tree->error) break;
      /* Missing slice endpoints are represented by zero-width empty groups. */
      if (slice && low == NONE) low = node(p, EXP_GROUP, token.end, token.end, NONE, (Token){0});
      if (slice && high == NONE) high = node(p, EXP_GROUP, end - 1, end - 1, NONE, (Token){0});
      if (p->tree->error) break;
      p->tree->nodes[left].next = low;
      if (slice) p->tree->nodes[low].next = high;
      left = mark(p, node(p, slice ? EXP_SLICE : EXP_INDEX, start, end, left, slice ? range_token : (Token){0}), EXP_PRIMARY);
    } else {
      int level = precedence(p);
      if (!level || level < minimum) break;
      lex(p); uint32_t right = expression(p, level + 1);
      if (right == NONE) break;
      p->tree->nodes[left].next = right;
      left = node(p, EXP_BINARY, start, p->tree->nodes[right].end, left, token); primary = false;
    }
  }
  return left;
}
static uint32_t expression(Parser *p, int minimum) {
  if (p->tree->error) return NONE;
  if (++p->depth > depth_limit(p)) { fail(p, p->token.start, "expression nesting limit exceeded"); --p->depth; return NONE; }
  uint32_t result = parse(p, minimum); --p->depth; return result;
}
bool exp_parse_with_options(const char *source, size_t length, ExpTree *tree, const ExpOptions *options) {
  tree->count = 0; tree->root = NONE; tree->error = NULL; tree->error_expected = NULL; tree->error_kind = EXP_OK; tree->error_offset = 0;
  if (length > UINT32_MAX || (!source && length)) { tree->error = "invalid source or source too large"; tree->error_kind = EXP_LIMIT_ERROR; return false; }
  uint64_t work_remaining = options && options->max_work ? options->max_work : (uint64_t)length * 128 + 1024;
  Parser p = {.text = source, .length = (uint32_t)length, .tree = tree, .work_remaining = &work_remaining, .options = options};
  if (!charge(&p, length, 0)) return false;
  lex(&p); uint32_t root = expression(&p, 0);
  if (p.token.kind != END) fail(&p, p.token.start, "unexpected trailing token");
  if (tree->error) return false;
  if (!finish_tree(&p, root)) return false;
  tree->root = root; return true;
}
bool exp_parse(const char *source, size_t length, ExpTree *tree) {
  return exp_parse_with_options(source, length, tree, NULL);
}
void exp_free(ExpTree *tree) { free(tree->nodes); free(tree->errors); memset(tree, 0, sizeof(*tree)); }

/* Full-source parsing shares the bounded lexer and expression parser. */
#include "parser_source.inc"
