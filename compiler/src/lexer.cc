#include "lexer.h"

namespace Lexer {
bool is_l(char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
bool is_w(char c) { return c == ' ' || c == '\n' || c == '\t'; }
bool is_n(char c, TokenState s) {
  return (c == '.' || c == '_') ? s == READ_NUM : (c >= '0' && c <= '9');
}
bool is_o(char c) {
  return operators.find(std::string(1, c)) != operators.end();
}

std::string pop_buf(std::vector<char> &buf) {
  auto y = std::string(buf.begin(), buf.end());
  buf.clear();
  return y;
}

TokenState grab_state(char x, TokenState s) {
  if (is_l(x)) {
    return READ_WORD;
  } else if (is_n(x, s)) {
    return READ_NUM;
  } else if (x == '\"') {
    return READ_STRING;
  } else if (x == '\'') {
    return READ_CHAR;
  } else if (is_o(x)) {
    return READ_OP;
  }
  return START;
}

std::vector<Token> tokenize(std::string input) {
  std::vector<Token> t = {};
  std::vector<char> b = {};
  TokenState s = START;
  for (auto x : input) {
    switch (s) {
    case START:
      if (!is_w(x)) {
        b.push_back(x);
      }
      s = grab_state(x, s);
      break;
    case READ_WORD:
      if (!(is_l(x) || is_n(x, s))) {
        auto y = pop_buf(b);
        t.push_back({
            .t = kwds.find(y) != kwds.end() ? kwds.at(y) : IDENTIFIER,
            .v = kwds.find(y) != kwds.end() ? "" : y,
        });
        s = grab_state(x, START);
      }
      if (!is_w(x)) {
        b.push_back(x);
      }
      break;
    case READ_NUM:
      if (!is_n(x, s)) {
        auto y = pop_buf(b);
        t.push_back({
            .t = y.find('.') != std::string::npos ? FLOAT : INT,
            .v = y,
        });
        s = grab_state(x, START);
      }
      if (!is_w(x)) {
        b.push_back(x);
      }
      break;
    case READ_OP:
      if (!is_o(x)) {
        if (b.size() == 1 && b.at(0) == '.' && is_n(x, s)) {
          s = grab_state(x, START);
        } else {
          auto y = pop_buf(b);
          t.push_back({.t = operators.at(y), .v = ""});
          s = grab_state(x, START);
        }
      } else {
        auto z = std::string(b.begin(), b.end()).append(std::string(1, x));
        if (operators.find(z) == operators.end()) {
          auto y = pop_buf(b);
          t.push_back({.t = operators.at(y), .v = ""});
        }
      }
      if (!is_w(x)) {
        b.push_back(x);
      }
      break;
    case READ_STRING:
    case READ_CHAR:
    default:
      break;
    }
  }
  auto y = pop_buf(b);
  switch (s) {
  case READ_WORD:
    t.push_back({
        .t = kwds.find(y) != kwds.end() ? kwds.at(y) : IDENTIFIER,
        .v = kwds.find(y) != kwds.end() ? "" : y,
    });
    break;
  case READ_NUM:
    t.push_back({
        .t = y.find('.') != std::string::npos ? FLOAT : INT,
        .v = y,
    });
    break;
  case READ_OP:
    t.push_back({.t = operators.at(y), .v = ""});
    break;
  default:
    break;
  }
  t.push_back({.t = END_OF_FILE, .v = ""});
  return t;
}
}
