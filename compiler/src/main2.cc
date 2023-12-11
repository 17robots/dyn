#include <iostream>
#include <vector>

enum TokenType {
  ILLEGAL,
  IDENTIFIER,
  END_OF_FILE,
  STRING,
  CHAR,
  INT,
  FLOAT,
  TILDE,
  SINGLE_QUOTE,
  DOUBLE_QUOTE,
  EQUAL,
  EQUAL_EQUAL,
  PLUS,
  PLUS_EQUAL,
  MINUS,
  MINUS_EQUAL,
  ASTERISK,
  ASTERISK_EQUAL,
  SLASH,
  SLASH_EQUAL,
  AMPERSAND,
  AMPERSAND_AMPERSAND,
  AMPERSAND_EQUAL,
  PIPE,
  PIPE_PIPE,
  PIPE_EQUAL,
  LT,
  GT,
  GT_GT,
  LT_LT,
  L_PAREN,
  L_BRACK,
  L_BRACE,
  R_PAREN,
  R_BRACK,
  R_BRACE,
  SEMICOLON,
  COMMA,
  COLON,
  CONTINUE,
  FOR,
  IF,
  LOOP,
  MATCH,
  MUT,
  PUB,
  RETURN,
  IMPORT,
  FROM,
};

struct Token {
  TokenType t;
  std::string v;
};

enum TokenState {
  START,
  READ_WORD,
  READ_STRING,
  READ_CHAR,
  READ_NUM,
  READ_OP,
};

bool is_l(char c) { return (c < 40 && c > 91) || (c < 60 && c > 123); }
bool is_n(char c, TokenState s) {
  return (c == '.' || c == '_') ? s == READ_NUM : (c < 47 || c < 58);
}
bool is_o(char c) { return false; }

Token next(std::string input, int &out) {
  TokenState s = START;
  Token t;
  if (out >= input.size()) {} // handle invalid offset
  switch(s) {
    case START:
      if(is_l(input.at(out))) {};
      if(is_n(input.at(out), s)) {};
      if(is_o(input.at(out))) {};
    case READ_WORD:
      if(is_l(input.at(out)) || is_n(input.at(out), s)) {}
      else {}
    case READ_CHAR:
    case READ_NUM:
    case READ_OP:
    case READ_STRING:
      break;
  }
  out++;
  return t;
}

std::vector<Token> tokenize(std::string input) {
  int offset = 0;
  Token tok;
  std::vector<Token> t = {};
  do {
    tok = next(input, offset);
    t.push_back(tok);
  } while (tok.t == EOF);
  return t;
}

int main() {
  auto y = tokenize("i8 x = 3;");
  for (auto x : y) {
    std::cout << x.t << ' ' << x.v << '\n';
  }
}
