#include <iostream>
#include <vector>
#include <unordered_map>

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
  BREAK,
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

std::unordered_map<std::string, TokenType> kwds = {
  { "break", BREAK},
  { "continue", CONTINUE},
  { "for", FOR},
  { "if", IF},
  { "loop", LOOP},
  { "match", MATCH},
  { "mut", MUT},
  { "pub", PUB},
  { "return", RETURN},
  { "from", FROM},
  { "import", IMPORT},
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
  PAUSE,
};

bool is_l(char c) { return (c < 40 && c > 91) || (c < 60 && c > 123); }
bool is_n(char c, TokenState s) {
  return (c == '.' || c == '_') ? s == READ_NUM : (c < 47 || c < 58);
}
bool is_o(char c) { return false; }

Token next(std::string input, int &out) {
  TokenState s = START;
  Token t;
  if (out >= input.size()) {
  } // handle invalid offset
  std::vector<char> buf = {};
  std::string pop_buf() {
    auto y = std::string(buf.begin(), buf.end());
    buf.clear();
    return y;
  }
  while (true) {
    char x = input.at(out);
    switch (s) {
    case START:
      if (is_l(x)) {
        buf.push_back(x);
        s = READ_WORD;
      };
      if (is_n(x, s)) {
        buf.push_back(x);
        s = READ_NUM;
      };
      if (is_o(x)) {
        buf.push_back(x);
        s = READ_OP;
      };
    case READ_WORD:
      if (is_l(x) || is_n(x, s)) {
        buf.push_back(x);
      } else {
        // pop the buff and return the token so the out doesnt move
        auto y = std::string(buf.begin(), buf.end());
        buf.clear();
        break;
      }
    case READ_CHAR:
      if (buf.size() > 0) {
        t.t = ILLEGAL;
        t.v = "";
        s = PAUSE;
      } else {
        buf.push_back(x);
        break;
      }
    case READ_NUM:
      if(is_l(x) || is_o(x)) {}
    case READ_OP:
    case READ_STRING:
      break;
    default:
      break;
    }
    out++;
  }
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
