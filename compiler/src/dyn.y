%{
  #include "ast.h"
  extern int yylex();
  void yyerror(const char *s) { printf("Error: %s", s); }
%}

%language "c++"

%define api.value.type variant
%define parse.assert

%token <int> SEMICOLON EQUAL;
%token <Identifier> IDENTIFIER;
%token <Expression> EXPRESSION;
%type <Expression> expr;
%type <Identifier> ident;
%type <Variable> var_decl;

%start decls;
%%

decls: decl 
     | decls decl;

decl: var_decl

var_decl: "mut" ident ident SEMICOLON { $$ = Variable($<std::string>1, $2, $3, NULL); }
        | "mut" ident ident EQUAL expr SEMICOLON { $$ = Variable($<std::string>1, $2, $3, &$5); }
        | "con" ident ident EQUAL expr SEMICOLON { $$ = Variable($<std::string>1, $2, $3, &$5); }
        | ident ident EQUAL expr SEMICOLON { $$ = Variable($<std::string>1, $2, $3, &$4); };

expr: { $$ = Expression(); }
ident: IDENTIFIER { $$ = Identifier($1); };
