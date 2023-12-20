#include <iostream>
#include <unordered_map>
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

enum TokenState {
  START,
  READ_WORD,
  READ_STRING,
  READ_CHAR,
  READ_NUM,
  READ_OP,
  PAUSE,
};

std::unordered_map<std::string, TokenType> operators = {
    {"(", L_PAREN},
    {"[", L_BRACK},
    {"{", L_BRACE},
    {")", R_PAREN},
    {"]", R_BRACK},
    {"}", R_BRACE},
    {";", SEMICOLON},
    {":", COLON},
    {"~", TILDE},
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

bool is_l(char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
bool is_w(char c) { return c == ' ' || c == '\n' || c == '\t'; }
bool is_n(char c, TokenState s) {
  return (c == '.' || c == '_') ? s == READ_NUM : (c >= '0' && c <= '9');
}
bool is_o(char c) {
  return operators.find(std::string(1, c)) != operators.end();
}

int main() {
  // is_l tests
  if(is_l('a'))  { std::cout << "Letter test 1 passsed\n";} else { std::cout << "Letter test 1 failed\n";}
  if(is_l('b'))  { std::cout << "Letter test 2 passsed\n";} else { std::cout << "Letter test 2 failed\n";}
  if(!is_l('9')) { std::cout << "Letter test 3 passsed\n";} else { std::cout << "Letter test 3 failed\n";}
  if(!is_l(' ')) { std::cout << "Letter test 4 passsed\n";} else { std::cout << "Letter test 4 failed\n";}
  
  // is_n tests
  if(is_n('0',READ_NUM)) { std::cout << "Number test 1 passsed\n";} else { std::cout << "Number test 1 failed\n";}
  if(is_n('0',READ_WORD)) { std::cout << "Number test 2 passsed\n";} else { std::cout << "Number test 2 failed\n";}
  if(!is_n('a',READ_NUM)) { std::cout << "Number test 3 passsed\n";} else { std::cout << "Number test 3 failed\n";}
  if(!is_n('b',READ_NUM)) { std::cout << "Number test 4 passsed\n";} else { std::cout << "Number test 4 failed\n";}
  if(is_n('.',READ_NUM)) { std::cout << "Number test 5 passsed\n";} else { std::cout << "Number test 5 failed\n";}
  if(!is_n('.',READ_WORD)) { std::cout << "Number test 6 passsed\n";} else { std::cout << "Number test 6 failed\n";}
  if(!is_n(' ',READ_NUM)) { std::cout << "Number test 7 passsed\n";} else { std::cout << "Number test 7 failed\n";}
  if(!is_n(' ',READ_WORD)) { std::cout << "Number test 8 passsed\n";} else { std::cout << "Number test 8 failed\n";}
  if(!is_n('\t',READ_NUM)) { std::cout << "Number test 9 passsed\n";} else { std::cout << "Number test 9 failed\n";}
  if(!is_n('\t',READ_WORD)) { std::cout << "Number test 10 passsed\n";} else { std::cout << "Number test 10 failed\n";}

  // is_o tests
  if(is_o(';')) { std::cout << "Operator test 1 passsed\n";} else { std::cout << "Operator test 1 failed\n";}
  if(!is_o('a')) { std::cout << "Operator test 2 passsed\n";} else { std::cout << "Operator test 2 failed\n";}
  if(!is_o('0')) { std::cout << "Operator test 3 passsed\n";} else { std::cout << "Operator test 3 failed\n";}
  if(is_o('=')) { std::cout << "Operator test 4 passsed\n";} else { std::cout << "Operator test 4 failed\n";}

  // is_w tests
  if(is_w(' '))  { std::cout << "Whitespace test 1 passsed\n";} else { std::cout << "Whitespace test 1 failed\n";}
  if(is_w('\n')) { std::cout << "Whitespace test 2 passsed\n";} else { std::cout << "Whitespace test 2 failed\n";}
  if(is_w('\t')) { std::cout << "Whitespace test 3 passsed\n";} else { std::cout << "Whitespace test 3 failed\n";}
  if(!is_w('a')) { std::cout << "Whitespace test 4 passsed\n";} else { std::cout << "Whitespace test 4 failed\n";}
}
