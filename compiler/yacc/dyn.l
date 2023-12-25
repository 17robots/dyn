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
"~" return TOKEN(TTILDE);
"'" return TOKEN(TSINGLEQUOTE);
"\"" return TOKEN(TDOUBLEQUOTE);
"!=" return TOKEN(TNEQUAL);
"==" return TOKEN(TEQUALEQUAL);
"+" return TOKEN(TPLUS);
"+=" return TOKEN(TPLUSEQUAL);
"%" return TOKEN(TPERCENT);
"%=" return TOKEN(TPERCENTEQUAL);
"-" return TOKEN(TMINUS);
"-=" return TOKEN(TMINUSEQUAL);
"*" return TOKEN(TASTERISK);
"*=" return TOKEN(TASTERISKEQUAL);
"/" return TOKEN(TSLASH);
"/=" return TOKEN(TSLASHEQUAL);
"&" return TOKEN(TAMPERSAND);
"&&" return TOKEN(TAMPERSANDAMPERSAND);
"&=" return TOKEN(TAMERSANDEQUAL);
"|" return TOKEN(TPIPE);
"||" return TOKEN(TPIPEPIPE);
"|=" return TOKEN(TPIPEEQUAL);
"<" return TOKEN(TLESS);
">" return TOKEN(TGREAT);
">=" return TOKEN(TGREATEQUAL);
"<=" return TOKEN(TLESSEQUAL);
"(" return TOKEN(TLPAREN);
"[" return TOKEN(TLBRACK);
"{" return TOKEN(TLBRACE);
")" return TOKEN(TRPAREN);
"]" return TOKEN(TRBRACK);
"}" return TOKEN(TRBRACE);
";" return TOKEN(TSEMICOLON);
"," return TOKEN(TCOMMA);
":" return TOKEN(TCOLON);
"." return TOKEN(TPERIOD);
"break" return TOKEN(TBREAK);
"continue" return TOKEN(TCONTINUE);
"for" return TOKEN(TFOR);
"if" return TOKEN(TIF);
"loop" return TOKEN(TLOOP);
"match" return TOKEN(TMATCH);
"mut" return TOKEN(TMUT);
"pub" return TOKEN(TPUB);
"return" return TOKEN(TRETURN);
"import" return TOKEN(TIMPORT);
"from" return TOKEN(TFROM);
"struct" return TOKEN(TSTRUCT);
. printf("Unknown Token!n"); yyterminate();
%%
