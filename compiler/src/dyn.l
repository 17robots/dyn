%option C++ noyywrap

%{
  #include <string>
%}

%%

[ \t\n];

[a-zA-Z_][a-zA-Z0-9_]* {
  return IDENT;
}

[0-9]+.[0-9]* {
  return DOUB;
}

[0-9]+ {
 return INT;
}

"==" {
 return EQ;
}

"!=" {
 return NEQ;
}

"<" {
 return LT;
}

"<=" {
 return LTE;
}

">" {
 return GT;
}

">=" {
 return GTE;
}

"=" {
 return EQUAL;
}

"(" {
 return L_PAREN;
}

"[" {
 return L_BRACK;
}

"{" {
 return L_BRACE;
}

"," {
 return R_PAREN;
}

";" {
 return R_BRACK;
}

":" {
 return R_BRACE;
}

"." {
 return DOT;
}

"+" {
 return ADD;
}

"+=" {
 return ADD_EQ;
}

"++" {
 return ADD_ADD;
}

"-" {
 return SUB;
}

"-=" {
 return SUB_EQ;
}

"--" {
 return SUB_SUB;
}

"*" {
 return STAR;
}

"*=" {
 return STAR_EQUAL;
}

"/" {
 return SLASH;
}

"/=" {
 return SLASH_EQUAL;
}

"%" {
 return PER;
}

"%=" {
 return PER_EQ;
}

"&" {
 return AMP;
}

"&&" {
 return AMP_AMP;
}

"&=" {
 return AMP_EQ;
}

"|" {
 return PIPE;
}

"||" {
 return PIPE_PIPE;
}

"|=" {
 return PIPE_EQ;
}

"!" {
 return NOT;
}

"=>" {
  return ARROW;
}

. printf("Unknown token!\n"); yyterminate();

%%
