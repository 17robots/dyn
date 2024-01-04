%skeleton "glr2.cc"
%glr-parser

%{
  #include "ast.h"
  extern int yylex();
  void yyerror(const char *s) { printf("Error: %s", s); }
%}

%language "c++"

%define api.value.type variant
%define parse.assert

// tokens 
%token <int> SEMICOLON EQUAL L_BRACE R_BRACE L_PAREN R_PAREN COMMA;
%token <std::string> INT DOUB IDENT;

// types
%type <Expression> ident expr number block fn_call;
%type <Statement> stmt decl stmts var_decl fn_decl enum_decl struct_decl;
%type <std::vector<EnumMember>> enum_members;
%type <std::vector<Expression>> call_args;
%type <std::vector<Identifier>> partners;
%type <std::vector<Statement>> struct_members;
%type <std::vector<Variable>> fn_args;

// precedence
%left L_PAREN L_BRACE;

%start decls;
%%

decls: "pub" decl 
     | decl
     | decls decl;

decl: var_decl SEMICOLON
    | fn_decl
    | enum_decl
    | struct_decl;

struct_decl: "struct" ident R_BRACE struct_members L_BRACE { $<Struct>$ = Struct($2, $4); };

struct_members: { $$ = {}; }
              | ident ident SEMICOLON { $$ = {}; $$.push_back(Variable("", $1, $2, NULL)); }
              | ident ident EQUAL expr SEMICOLON { $$ = {}; $$.push_back(Variable("", $1, $2, &$3)); }
              | ident ident L_PAREN fn_args R_PAREN block { $$ = {}; $$.push_back(Function($1, $2, &$3)); }
              | ident ident L_PAREN fn_args R_PAREN SEMICOLON { $$ = {}; $$.push_back(Function($1, $2, NULL)); }
              | struct_members ident ident SEMICOLON { $1.push_back(Variable("", $1, $2, NULL)); }
              | struct_members ident ident EQUAL expr SEMICOLON { $1.push_back(Variable("", $1, $2, &$3)); }
              | struct_members ident ident L_PAREN fn_args R_PAREN block { $1.push_back(Function($1, $2, &$3)); }
              | struct_members ident ident L_PAREN fn_args R_PAREN SEMICOLON { $1.push_back(Function($1, $2, NULL)); };

enum_decl: "enum" ident L_BRACE enum_members R_BRACE { $<Enum>$ = Enum($<Identifier>2, $2); };

enum_members: ident { $$ = {}; $$.push_back(EnumMember($1)); }
            | ident L_PAREN partners R_PAREN { $$ = {}; $$.push_back(EnumMember($1, $2)); }
            | enum_members ident { $1.push_back(EnumMember($2)); }
            | enum_members ident L_PAREN partners R_PAREN { $1.push_back(EnumMember($2, $3)); }

partners: ident { $$ = {}; $$.push_back($1); }
        | partners COMMA ident { $1.push_back($2); };

fn_decl: ident ident L_PAREN fn_args R_PAREN block { $<Function>$ = Function($1, $2, &$3); }
       | ident ident L_PAREN fn_args R_PAREN { $<Function>$ = Function($1, $2, NULL); } ;

fn_args: { $$ = {}; }
       | var_decl { $<std::Vector<Variable>$ = {}; $$.push_back($<Variable>1)}
       | fn_args COMMA var_decl { $<std::Vector<Variable>1.push_back($<Variable>2)};

var_decl: "mut" ident ident { $$ = Variable($<std::string>1, $2, $3, NULL); }
   | "mut" ident ident EQUAL expr { $$ = Variable($<std::string>1, $2, $3, &$5); }
   | "con" ident ident EQUAL expr { $$ = Variable($<std::string>1, $2, $3, &$5); }
   | ident ident EQUAL expr { $$ = Variable($<std::string>1, $2, $3, &$4); };

stmts: stmt SEMICOLON{ $<Block>$ = Block(); $<Block>$.statements.push_back($<Statement>1); }
     | stmts SEMICOLON stmt {$<Block>1.statements.push_back($<Statement>1); };

stmt: { $$ = Statement(); }
    | decl
    | fn_call SEMICOLON { $$ = FunctionCallStatement($<FunctionCall>1); };

block: L_BRACE stmts R_BRACE { $$ = $2; };

expr: ident
    | number
    | fn_call;

fn_call: ident L_PAREN call_args R_PAREN { $<FunctionCall>$ = FunctionCall($1, $3); };

call_args: { $$ = {}; }
         | expr { $$ = {}; $$.push_back($<Expression>1); }
         | call_args COMMA expr { $1.push_back($<Expression>2); };

ident: IDENT { $$ = Identifier($<std::string>1); };

number: INT { $<Integer>$ = Integer($<long long>1); }
      | DOUB { $<Double>$ = Double($<double>1); };

