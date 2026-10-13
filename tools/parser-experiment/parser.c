#include "parser.h"
#include <stdlib.h>
#include <string.h>

#define NONE UINT32_MAX
#define MAX_DEPTH 256
/* Multi-byte punctuation uses its spelling rather than a public token enum. */
typedef enum { END, NAME, NUMBER, STRING, CHARACTER, PUNCT, BAD } TokenKind;
typedef struct { uint32_t start, end; TokenKind kind; } Token;
typedef struct {
  const char *text;
  uint32_t length, offset, depth;
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
  if (!p->tree->error) { p->tree->error = message; p->tree->error_offset = offset; }
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
    while (*i < p->length && hex(p->text[*i])) ++*i;
    if (*i == start || *i - start > 6 || *i == p->length || p->text[*i] != '}') return false;
    ++*i; return true;
  }
  return false;
}
static void lex(Parser *p) {
  uint32_t i = p->offset;
  for (;;) {
    while (i < p->length && space(p->text[i])) ++i;
    if (at(p, i, "//")) {
      i += 2; while (i < p->length && p->text[i] != '\n') ++i;
    } else if (at(p, i, "/*")) {
      uint32_t start = i; i += 2;
      while (i < p->length && !at(p, i, "*/")) ++i;
      if (i == p->length) { fail(p, start, "unterminated comment"); break; }
      i += 2;
    } else break;
  }
  uint32_t start = i;
  TokenKind kind = PUNCT;
  if (i == p->length) kind = END;
  else if (alpha(p->text[i])) {
    kind = NAME; ++i;
    while (i < p->length && (alpha(p->text[i]) || digit(p->text[i]))) ++i;
  } else if (digit(p->text[i]) || (p->text[i] == '.' && i + 1 < p->length && digit(p->text[i + 1]))) {
    kind = NUMBER;
    if (at(p, i, "0x") || at(p, i, "0b") || at(p, i, "0o")) {
      char base = p->text[i + 1]; i += 2; uint32_t digits = i;
      while (i < p->length && (p->text[i] == '_' ||
        (base == 'x' ? hex(p->text[i]) : p->text[i] >= '0' && p->text[i] <= (base == 'b' ? '1' : '7')))) ++i;
      if (i == digits) fail(p, start, "missing base digits");
    } else {
      bool leading_dot = p->text[i] == '.';
      if (leading_dot) ++i;
      while (i < p->length && (digit(p->text[i]) || p->text[i] == '_')) ++i;
      bool trailing_dot = false;
      if (!leading_dot && i < p->length && p->text[i] == '.' && !at(p, i, "..")) {
        ++i; uint32_t first = i;
        /* The grammar requires a digit immediately after a decimal point. */
        if (i < p->length && digit(p->text[i])) {
          ++i; while (i < p->length && (digit(p->text[i]) || p->text[i] == '_')) ++i;
        }
        trailing_dot = first == i;
      }
      if (!trailing_dot && i < p->length && (p->text[i] == 'e' || p->text[i] == 'E')) {
        uint32_t exponent = i++;
        if (i < p->length && (p->text[i] == '+' || p->text[i] == '-')) ++i;
        if (i == p->length || !digit(p->text[i])) i = exponent;
        else { ++i; while (i < p->length && (digit(p->text[i]) || p->text[i] == '_')) ++i; }
      }
    }
  } else if (p->text[i] == '"' || p->text[i] == '\'') {
    char quote = p->text[i++]; kind = quote == '"' ? STRING : CHARACTER;
    unsigned characters = 0;
    while (i < p->length && p->text[i] != quote && p->text[i] != '\n') {
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
    if (c == '#') {
      while (i < p->length && alpha(p->text[i])) ++i;
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
        kind = BAD; fail(p, start, "unsupported token");
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
  if (!take(p, s)) fail(p, p->token.start, "unexpected token");
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
  t->nodes[id] = (ExpNode){start, end, first, NONE, op.start, (uint16_t)kind, (uint16_t)(op.end - op.start)};
  return id;
}
static bool reserved(Parser *p) {
  static const char *const words[] = {"fn", "pub", "use", "const", "type", "distinct", "packed", "struct", "enum", "extern", "return", "continue", "break", "if", "else", "case", "is", "for", "in", "defer", "i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64", "f32", "f64", "isize", "usize", "bool", "rawptr", "any"};
  for (size_t i = 0; i < sizeof(words) / sizeof(*words); ++i) if (is(p, words[i])) return true;
  return false;
}
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
static uint32_t parse(Parser *p, int minimum) {
  Token token = p->token;
  uint32_t left = NONE;
  bool primary = false;
  if (take(p, "(")) {
    uint32_t child = expression(p, 0); uint32_t end = p->token.end;
    expect(p, ")"); left = node(p, EXP_GROUP, token.start, end, child, (Token){0}); primary = true;
  } else if (is(p, "-") || is(p, "&") || is(p, "!") || is(p, "~")) {
    lex(p); uint32_t child = expression(p, 12);
    if (child != NONE) left = node(p, EXP_PREFIX, token.start, p->tree->nodes[child].end, child, token);
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
    else if (token.kind == NAME && !reserved(p)) primary = true;
    else { fail(p, token.start, "expected supported expression"); return NONE; }
    lex(p); left = node(p, kind, token.start, token.end, NONE, (Token){0});
  }
  while (left != NONE && !p->tree->error) {
    token = p->token;
    uint32_t start = p->tree->nodes[left].start;
    if (take(p, ".*")) {
      left = node(p, EXP_DEREF, start, token.end, left, token); primary = true;
    } else if (primary && take(p, ".")) {
      if (p->token.kind != NAME) { fail(p, p->token.start, "expected field name"); break; }
      Token field = p->token; lex(p);
      uint32_t name = node(p, EXP_NAME, field.start, field.end, NONE, (Token){0});
      if (name == NONE) break;
      p->tree->nodes[left].next = name;
      left = node(p, EXP_FIELD, start, field.end, left, (Token){0});
    } else if (primary && take(p, "(")) {
      uint32_t last = left;
      while (!is(p, ")") && !p->tree->error) {
        uint32_t arg = expression(p, 0); if (arg == NONE) break;
        p->tree->nodes[last].next = arg; last = arg;
        if (!take(p, ",")) break;
      }
      uint32_t end = p->token.end; expect(p, ")");
      left = node(p, EXP_CALL, start, end, left, (Token){0});
    } else if (primary && take(p, "[")) {
      uint32_t low = NONE, high = NONE;
      if (!is(p, "..")) low = expression(p, 0);
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
      left = node(p, slice ? EXP_SLICE : EXP_INDEX, start, end, left, (Token){0});
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
  if (++p->depth > MAX_DEPTH) { fail(p, p->token.start, "expression nesting limit exceeded"); --p->depth; return NONE; }
  uint32_t result = parse(p, minimum); --p->depth; return result;
}
bool exp_parse(const char *source, size_t length, ExpTree *tree) {
  tree->count = 0; tree->root = NONE; tree->error = NULL; tree->error_offset = 0;
  if (length > UINT32_MAX) { tree->error = "source too large"; return false; }
  Parser p = {.text = source, .length = (uint32_t)length, .tree = tree};
  lex(&p); uint32_t root = expression(&p, 0);
  if (p.token.kind != END) fail(&p, p.token.start, "unexpected trailing token");
  if (tree->error) return false;
  tree->root = root; return true;
}
void exp_free(ExpTree *tree) { free(tree->nodes); memset(tree, 0, sizeof(*tree)); }
