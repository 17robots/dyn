#pragma once

#include <algorithm>
#include <cstdint>
#include <string>
#include <vector>

struct Token {
  uint8_t type;
  std::string val;
};

const std::vector<std::string> OPS = {
    ";",  ":",  ".",  ",",  "(",  "[",  "{",  ")",  "]",  "}",  "=",
    "!",  "<",  ">",  "*",  "+",  "/",  "-",  "&",  "|",  "==", "!=",
    "<=", ">=", "*=", "+=", "/=", "-=", "&=", "&&", "|=", "||", "=>",
};

enum ParserState {
  START = 0,
  READ_WORD,
  READ_NUM,
  READ_STRING,
  READ_CHAR,
  READ_OP,
};

inline bool is_c(char x) { return (x >= 'a' && x <= 'z') || (x >= 'A' && x <= 'Z'); }
inline bool is_n(char x, ParserState s) {
  return x == '.' ? s == READ_NUM : (x >= '0' && x <= '9');
}
inline bool is_o(std::string x) {
  return std::find(OPS.begin(), OPS.end(), x) != OPS.end();
}
inline bool is_w(char x) { return x == '\r' || x == '\n' || x == '\t' || x == ' '; }

inline ParserState grab_state(char x, ParserState s) {
  if (x == '\"') {
    return READ_STRING;
  }
  if (is_c(x)) {
    return READ_WORD;
  }
  if (is_n(x, s)) {
    return READ_NUM;
  }
  if (is_o(std::string(1, x))) {
    return READ_OP;
  }
  return START;
}

inline std::string clear_buf(std::vector<char> &b) {
  auto x = std::string(b.begin(), b.end());
  b.clear();
  return x;
}

inline std::vector<Token> lexer(std::string &input) {
  ParserState s = START;
  std::vector<Token> t = {};
  std::vector<char> b = {};
  for (auto x : input) {
    switch (s) {
    case START:
      s = grab_state(x, s);
      if(s == START && !is_w(x)) {
          t.push_back({ .type = 0, .val = "" });
      }
      break;
    case READ_WORD:
      if (!(is_c(x) || is_n(x, s))) {
        t.push_back({.type = 1, .val = clear_buf(b)});
        s = grab_state(x, START);
      }
      break;
    case READ_NUM:
      if (!is_n(x, s)) {
        t.push_back({.type = 2, .val = clear_buf(b)});
        s = grab_state(x, START);
      }
      break;
    case READ_STRING:
      if (x == '\"') {
        b.push_back(x);
        t.push_back({.type = 3, .val = clear_buf(b)});
        s = START;
      }
      break;
    case READ_CHAR:
      // this needs redone
      if (!(x == '\"')) {
        t.push_back({.type = 4, .val = clear_buf(b)});
        s = grab_state(x, START);
      }
      break;
    case READ_OP:
      auto str = std::string(b.begin(), b.end()).append(std::string(1, x));
      if (!is_o(str)) {
        t.push_back({.type = 5, .val = clear_buf(b)});
        s = grab_state(x, START);
      }
      break;
    }
    if (s != START)
      b.push_back(x);
  }

  t.push_back({.type = (uint8_t)s, .val = clear_buf(b)});
  return t;
}

