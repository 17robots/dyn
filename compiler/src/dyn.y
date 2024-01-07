%{
  #include "ast.h"
  extern int yylex();
  void yyerror(const char *s) { printf("Error: %s", s); }
%}

%language "c++"

%define api.value.type variant
%define parse.assert

// tokens 
%token <int> SEMICOLON EQUAL L_BRACE R_BRACE L_PAREN R_PAREN COMMA COLON;
%token <std::string> INT DOUB IDENT;

// types
%type <Expression> ident expr number block fn_call;
%type <Statement> stmt decl stmts var_decl fn_decl enum_decl struct_decl;
%type <FunctionSignature> fn_sig;
%type <std::vector<EnumMember>> enum_members;
%type <std::vector<Expression>> call_args;
%type <std::vector<Identifier>> partners traits;
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

struct_decl: "struct" ident R_BRACE struct_members L_BRACE { $<Struct>$ = Struct($2, $4); }
           | "struct" ident COLON traits R_BRACE struct_members L_BRACE { $<Struct>$ = Struct($2, $4); };

traits: { $$ = {}; }

struct_members: { $$ = {}; }
              | var SEMICOLON { $$ = {}; $$.push_back(Variable("", $<Var>1, NULL)); }
              | var EQUAL expr SEMICOLON { $$ = {}; $$.push_back(Variable("", $<Var>1, &$3)); }
              | fn_decl { $$ = {}; $$.push_back($<Function>1); }
              | struct_members var SEMICOLON { $$.push_back(Variable("", $<Var>1, NULL)); }
              | struct_members var EQUAL expr SEMICOLON { $1.push_back(Variable("", $<Var>2, &$4)); }
              | struct_members fn_decl { $1.push_back($<Function>2); }

enum_decl: "enum" ident L_BRACE enum_members R_BRACE { $<Enum>$ = Enum($<Identifier>2, $2); };

enum_members: { $$ = {}; } 
            | ident { $$ = {}; $$.push_back(EnumMember($1)); }
            | ident L_PAREN partners R_PAREN { $$ = {}; $$.push_back(EnumMember($1, $2)); }
            | enum_members COMMA ident COMMA { $1.push_back(EnumMember($2)); }
            | enum_members COMMA ident L_PAREN partners R_PAREN { $1.push_back(EnumMember($2, $3)); }

partners: ident { $$ = {}; $$.push_back($1); }
        | partners COMMA ident { $1.push_back($2); };

fn_sig: var L_PAREN fn_args R_PAREN { $$ = FunctionSignature($<Var>1, $<std::vector<Variable>2); }

fn_decl: fn_sig block { $<Function>$ = Function($<FunctionSignature>1, &$<Block>2); }
       | fn_sig SEMICOLON { $<Function>$ = Function($<FunctionSignature>1, NULL); };

fn_args: { $$ = {}; }
       | var { $<std::Vector<Variable>$ = {}; $$.push_back(Variable(NULL, $<Var>1, NULL)); }
       | "mut" var { $<std::Vector<Variable>$ = {}; $$.push_back(Variable($<std::string>1, $<Var>1, NULL)); }
       | fn_args COMMA var { $1.push_back(Variable(NULL, $<Var>3, NULL)); }
       | fn_args COMMA "mut" var { $1.push_back(Variable($<std::string>3, $<Var>4, NULL)); }

var: ident ident;

var_decl: "mut" var SEMICOLON { $$ = Variable($<std::string>1, $<Var>2, $3, NULL); }
   | "mut" var EQUAL expr SEMICOLON { $$ = Variable($<std::string>1, $<Var>2, $4, &$5); }
   | "con" var EQUAL expr SEMICOLON { $$ = Variable($<std::string>1, $<Var>2, $4, &$5); }
   | var EQUAL expr SEMICOLON { $$ = Variable($<std::string>1, $2, $3, &$4); };

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

