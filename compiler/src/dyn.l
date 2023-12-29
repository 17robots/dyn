%{
  #include <string>
  #include "ast.h"
  #include "parser.h"
  #define SAVE_TOKEN yylval.string = new std::string(yytext, yyleng)
  extern "C" int yywrap() {}
%}

%%

[ \t\n];
[a-zA-Z_][a-zA-Z0-9_]* SAVE_TOKEN; rerturn IDENTIFIER;
[0-9]+.[0-9]* SAVE_TOKEN; return DOUBLE;
[0-9]+ SAVE_TOKEN; return INTEGER;
"==" return TOKEN(EQUAL);
"!=" return TOKEN(BANG_EQUAL);
"<" return TOKEN(LT);
"<=" return TOKEN(LT_EQUAL);
">" return TOKEN(GT);
">=" return TOKEN(GT_EQUAL);
"=" return TOKEN(EQUAL);
"(" return TOKEN(L_PAREN);
"[" return TOKEN(L_BRACK);
"{" return TOKEN(L_BRACE);
"," return TOKEN(R_PAREN);
";" return TOKEN(R_BRACK);
":" return TOKEN(R_BRACE);
"." return TOKEN(PERIOD);
"+" return TOKEN(PLUS);
"+=" return TOKEN(PLUS_EQUAL);
"-" return TOKEN(MINUS);
"-=" return TOKEN(MINUS_EQUAL);
"*" return TOKEN(ASTERISK);
"*=" return TOKEN(ASTERISK_EQUAL);
"&" return TOKEN(AMPERSAND);
"&&" return TOKEN(AMPERSAND_AMPERSAND);
"&=" return TOKEN(AMPERSAND_EQUAL);
"|" return TOKEN(PIPE);
"||" return TOKEN(PIPE_PIPE);
"|=" return TOKEN(PIPE_EQUAL);
"!" return TOKEN(BANG);
. printf("Unknown token!\n"); yyterminate();

%%
