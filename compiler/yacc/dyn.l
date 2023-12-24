%{
  #include <iostream>
  #include <string>
  #include "parser.hpp"
  #define SAVE_TOKEN yylval.string = new std::string(yytext, yyleng)
  extern "C" int yywrap() { }
  #include "node.h"
%}

%%

[ \t\n ] ;
[a-zA-Z_][a-zA-Z0-9_]* SAVE_TOKEN; return TIDENTIFIER;
[0-9]+.[0-9]* SAVE_TOKEN; return TDOUBLE;
[0-9]+ SAVE_TOKEN; return TINTEGER;
"=" return TOKEN(TEQUAL);
"~" return TOKEN(TEQUAL);
"'" return TOKEN(TEQUAL);
"\"" return TOKEN(TEQUAL);
"==" return TOKEN(TEQUAL);
"+" return TOKEN(TEQUAL);
"+=" return TOKEN(TEQUAL);
"-" return TOKEN(TEQUAL);
"-=" return TOKEN(TEQUAL);
"*" return TOKEN(TEQUAL);
"*=" return TOKEN(TEQUAL);
"/" return TOKEN(TEQUAL);
"/=" return TOKEN(TEQUAL);
"&" return TOKEN(TEQUAL);
"&=" return TOKEN(TEQUAL);
"|" return TOKEN(TEQUAL);
"||" return TOKEN(TEQUAL);
"|=" return TOKEN(TEQUAL);
"<" return TOKEN(TEQUAL);
">" return TOKEN(TEQUAL);
">=" return TOKEN(TEQUAL);
"<=" return TOKEN(TEQUAL);
"(" return TOKEN(TEQUAL);
"[" return TOKEN(TEQUAL);
"{" return TOKEN(TEQUAL);
")" return TOKEN(TEQUAL);
"]" return TOKEN(TEQUAL);
"}" return TOKEN(TEQUAL);
";" return TOKEN(TEQUAL);
"," return TOKEN(TEQUAL);
":" return TOKEN(TEQUAL);
"." return TOKEN(TEQUAL);
"break" return TOKEN(TEQUAL);
"continue" return TOKEN(TEQUAL);
"for" return TOKEN(TEQUAL);
"if" return TOKEN(TEQUAL);
"loop" return TOKEN(TEQUAL);
"match" return TOKEN(TEQUAL);
"mut" return TOKEN(TEQUAL);
"pub" return TOKEN(TEQUAL);
"return" return TOKEN(TEQUAL);
"import" return TOKEN(TEQUAL);
"from" return TOKEN(TEQUAL);
"struct" return TOKEN(TEQUAL);
. printf("Unknown Token!n"); yyterminate();
%%
