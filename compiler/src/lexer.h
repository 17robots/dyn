#pragma once
#include <unordered_map>
#include <vector>
#include <string>

namespace Lexer {
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
  GT_EQUAL,
  LT_EQUAL,
  L_PAREN,
  L_BRACK,
  L_BRACE,
  R_PAREN,
  R_BRACK,
  R_BRACE,
  SEMICOLON,
  COMMA,
  COLON,
  PERIOD,
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
  STRUCT
};

const std::unordered_map<TokenType, std::string> tokens = {
    {ILLEGAL, "ILLEGAL"},
    {IDENTIFIER, "IDENTIFIER"},
    {END_OF_FILE, "END_OF_FILE"},
    {STRING, "STRING"},
    {CHAR, "CHAR"},
    {INT, "INT"},
    {FLOAT, "FLOAT"},
    {TILDE, "TILDE"},
    {SINGLE_QUOTE, "SINGLE_QUOTE"},
    {DOUBLE_QUOTE, "DOUBLE_QUOTE"},
    {EQUAL, "EQUAL"},
    {EQUAL_EQUAL, "EQUAL_EQUAL"},
    {PLUS, "PLUS"},
    {PLUS_EQUAL, "PLUS_EQUAL"},
    {MINUS, "MINUS"},
    {MINUS_EQUAL, "MINUS_EQUAL"},
    {ASTERISK, "ASTERISK"},
    {ASTERISK_EQUAL, "ASTERISK_EQUAL"},
    {SLASH, "SLASH"},
    {SLASH_EQUAL, "SLASH_EQUAL"},
    {AMPERSAND, "AMPERSAND"},
    {AMPERSAND_AMPERSAND, "AMPERSAND_AMPERSAND"},
    {AMPERSAND_EQUAL, "AMPERSAND_EQUAL"},
    {PIPE, "PIPE"},
    {PIPE_PIPE, "PIPE_PIPE"},
    {PIPE_EQUAL, "PIPE_EQUAL"},
    {LT, "LT"},
    {GT, "GT"},
    {GT_EQUAL, "GT_EQUAL"},
    {LT_EQUAL, "LT_EQUAL"},
    {L_PAREN, "L_PAREN"},
    {L_BRACK, "L_BRACK"},
    {L_BRACE, "L_BRACE"},
    {R_PAREN, "R_PAREN"},
    {R_BRACK, "R_BRACK"},
    {R_BRACE, "R_BRACE"},
    {SEMICOLON, "SEMICOLON"},
    {COMMA, "COMMA"},
    {COLON, "COLON"},
    {BREAK, "BREAK"},
    {CONTINUE, "CONTINUE"},
    {FOR, "FOR"},
    {IF, "IF"},
    {LOOP, "LOOP"},
    {MATCH, "MATCH"},
    {MUT, "MUT"},
    {PUB, "PUB"},
    {RETURN, "RETURN"},
    {IMPORT, "IMPORT"},
    {STRUCT, "STRUCT"},
    {PERIOD, "PERIOD"},
    {FROM, "FROM"}};

const std::unordered_map<std::string, TokenType> kwds = {
    {"break", BREAK}, {"continue", CONTINUE}, {"for", FOR},
    {"if", IF},       {"loop", LOOP},         {"match", MATCH},
    {"mut", MUT},     {"pub", PUB},           {"return", RETURN},
    {"from", FROM},   {"struct", STRUCT},     {"import", IMPORT},
};

const std::unordered_map<std::string, TokenType> operators = {
    {"(", L_PAREN},
    {"[", L_BRACK},
    {"{", L_BRACE},
    {")", R_PAREN},
    {"]", R_BRACK},
    {"}", R_BRACE},
    {";", SEMICOLON},
    {":", COLON},
    {"~", TILDE},
    {".", PERIOD},
    {"\'", SINGLE_QUOTE},
    {"\"", DOUBLE_QUOTE},
    {"=", EQUAL},
    {"==", EQUAL_EQUAL},
    {"+", PLUS},
    {"+=", PLUS_EQUAL},
    {"-", MINUS},
    {"-=", MINUS_EQUAL},
    {"*", ASTERISK},
    {"*=", ASTERISK_EQUAL},
    {"/", SLASH},
    {"/=", SLASH_EQUAL},
    {"&", AMPERSAND},
    {"&&", AMPERSAND_AMPERSAND},
    {"&=", AMPERSAND_EQUAL},
    {"|", PIPE},
    {"||", PIPE_PIPE},
    {"|=", PIPE_EQUAL},
    {"<", LT},
    {">", GT},
    {">=", GT_EQUAL},
    {"<=", LT_EQUAL}};

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

bool is_l(char c);
bool is_w(char c);
bool is_n(char c, TokenState s);
bool is_o(char c);

std::string pop_buf(std::vector<char> &buf);
TokenState grab_state(char x, TokenState s);
std::vector<Token> tokenize(std::string input);
}
