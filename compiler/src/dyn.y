%{
  #include "ast.h"
  extern int yylex();
  void yyerror(const char *s) { printf("Error: %s", s); }
%}

%language "c++"

%define api.value.type variant
%define parse.assert

// tokens 
%token <int> SEMICOLON EQUAL L_BRACE R_BRACE L_PAREN R_PAREN COMMA COLON WHITESPACE ARROW;
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
     | decl decls;

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
              | var SEMICOLON struct_members { $3.push_back(Variable("", $<Var>1, NULL)); }
              | var EQUAL expr SEMICOLON struct_members { $4.push_back(Variable("", $<Var>1, &$3)); }
              | fn_decl struct_members { $2.push_back($<Function>1); };

enum_decl: "enum" ident L_BRACE enum_members R_BRACE { $<Enum>$ = Enum($<Identifier>2, $2); };

enum_members: { $$ = {}; } 
            | ident { $$ = {}; $$.push_back(EnumMember($1)); }
            | ident L_PAREN partners R_PAREN { $$ = {}; $$.push_back(EnumMember($1, $2)); }
            | ident COMMA enum_members { $1.push_back(EnumMember($2)); }
            | ident L_PAREN partners R_PAREN COMMA enum_members{ $1.push_back(EnumMember($2, $3)); }

partners: ident { $$ = {}; $$.push_back($1); }
        | ident COMMA partners { $2.push_back($1); };

fn_sig: var L_PAREN fn_args R_PAREN { $$ = FunctionSignature($<Var>1, $<std::vector<Variable>2); };

fn_decl: fn_sig block { $<Function>$ = Function($<FunctionSignature>1, &$<Block>2); }
       | fn_sig SEMICOLON { $<Function>$ = Function($<FunctionSignature>1, NULL); }
       | fn_sig ARROW expr { $<Function>$ = Function($<FunctionSignature>1, NULL); };

fn_args: { $$ = {}; }
       | var { $<std::vector<Variable>$ = {}; $$.push_back(Variable(NULL, $<Var>1, NULL)); }
       | "mut" var { $<std::vector<Variable>$ = {}; $$.push_back(Variable($<std::string>1, $<Var>1, NULL)); }
       | var COMMA fn_args { $3.push_back(Variable(NULL, $<Var>1, NULL)); }
       | "mut" var COMMA fn_args { $4.push_back(Variable($<std::string>1, $<Var>2, NULL)); }

var: ident ident;

var_decl: "mut" var SEMICOLON { $$ = Variable($<std::string>1, $<Var>2, $3, NULL); }
   | "mut" var EQUAL expr SEMICOLON { $$ = Variable($<std::string>1, $<Var>2, $4, &$5); }
   | "con" var EQUAL expr SEMICOLON { $$ = Variable($<std::string>1, $<Var>2, $4, &$5); }
   | var EQUAL expr SEMICOLON { $$ = Variable($<std::string>1, $2, $3, &$4); };

stmts: stmt SEMICOLON{ $<Block>$ = Block(); $<Block>$.statements.push_back($<Statement>1); }
     | stmt SEMICOLON stmts {$<Block>1.statements.push_back($<Statement>1); };

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



%start declaration_list
%%
declaration_list: declaration ';' declaration_list |
declaration: enum_declaration | variable_declaration | function_declaration | struct_declaration | type_declaration
statement_list: statement statement_list |
statement: if_statement | loop_statement | for_statement | match_statement | break_statement | return_statement | continue_statement | declaration

enum_declaration: "enum" IDENTIFIER '{' enum_member_list '}'
enum_member_list: enum_member enum_member_list |
enum_member: IDENTIFIER enum_partner_list ','
enum_partner_list: '(' partner_list ')' |
partner_list: IDENTIFIER partner_list_prime
partner_list_prime: ',' IDENTIFIER partner_list' |

variable_declaration: TYPE IDENTIFIER '=' expr ';' | "mut" TYPE IDENTIFIER '=' expr ';' | "mut" TYPE IDENTIFIER ';'

function_declaration: TYPE IDENTIFIER '(' parameter_list ')' function_body
parameter_list: parameter parameter_list_prime |
parameter_list_prime: ',' parameter_list_prime |
parameter: TYPE IDENTIFIER | "mut" TYPE IDENTIFIER | TYPE IDENTIFIER '=' expr | "mut" TYPE IDENTIFIER '=' expr
function_body: '{' statement_list '}' | "=>" expr ';'
statement_block: '{' statement_list '}'

struct_declaration: "struct" IDENTIFIER trait_clause '{' struct_member_list '}'
struct_member_list: struct_member struct_member_list |
struct_member: struct_variable_declaration | struct_function_declaration
struct_variable_declaration: TYPE IDENTIFIER | TYPE IDENTIFIER '=' expr
struct_function_declaration: TYPE IDENTIFIER '(' parameter_list ')' struct_function_body
struct_function_body: '{' statement_list '}' | "=>" expr ';' |
trait_clause: ':' traits_list |
traits_list: IDENTIFIER traits_list_prime
traits_list_prime: ',' traits_list_prime |

if_statement: "if" conditional_expr statement_block optional_else_block
optional_else_block: 'else' else_content |
else_content: if_statement | statement_block
loop_statement: "loop" statement_block
for_statement: "for" TYPE IDENTIFIER ':' iterable_expr statement_block
match_statement: "match" expr '{' match_branches '}'
match_branches: 
break_statement: "break" ';'
continue_statement: "continue" ';'
return_statement: "return" ';' | "return" expr ';' 

expr: term arithmetic_list | term binary_list
arithmetic_list: arithmetic_op term arithmetic_list |
binary_list: binary_op term binary_list |
conditional_expr: expr
term: factor | '(' expr ')' | literal | IDENTIFIER
factor: factor comparison_op factor | factor logical_op | factor | IDENTIFIER | literal | '(' expr ')'
logical_op: '&&' | '||'  
comparison_op: '==' | '!=' | '<' | '>' | '<=' | '>='
arithmetic_op: '+' | '-' | '*' | '/' | '%' | '+=' | '-=' | '*=' | '/=' | '%='
binary_op: '&' | '|' | '&=' | '|=' 

literal: NUMBER | STRING | BOOLEAN | CHAR | struct_literal | enum_literal | enum_variant | function_call | function_literal 
BOOLEAN: "true" | "false"
enum_literal: "enum" '{' enum_member_list '}'
enum_variant: 
function_literal:
function_call: IDENTIFIER '(' arguments ')'
arguments: expr argument_list_prime |
argument_list_prime: ',' argument_list_prime |
struct_literal: "struct" trait_clause '{' struct_members '}'
struct_access: 

TYPE: "f64" | "f32" | integer_type
integer_type: 'i' DIGIT+ | 'u' DIGIT+

