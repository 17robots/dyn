%{
	#include "ast.h"
	extern int yylex();
	void yyerror(const char *s) { printf("ERROR: %s", s); }
	Program *program;
%}

%union {
	Node node;
	Block block;
	Expression expr;
	Statement stmt;
	Identifier ident;
	Variable var;
	std::vector<Variable> vars;
	std::vector<Statement> stmts;
	std::string string;
	int token;
}

%token <string> IDENTIFIER INTEGER DOUBLE UNDERSCORE
%token <token> EQUAL_EQUAL BANG_EQUAL LT LT_EQUAL GT GT_EQUAL EQUAL BANG
%token <token> L_PAREN L_BRACK L_BRACE R_PAREN R_BRACK R_BRACE
%token <token> COMMA SEMICOLON PERIOD COLON
%token <token> PLUS PLUS_EQUAL
%token <token< MINUS MINUS_EQUAL
%token <token> ASTERISK ASTERISK_EQUAL
%token <token> AMPERSAND AMPERSAND_AMPERSAND AMPERSAND_EQUAL "&="
%token <token> PIPE PIPE_PIPE PIPE_EQUAL

%type <ident> ident
%type <expr> numeric expr
%type <vars> func_decl_args
%type <exprs> call_args
%type <block> stmts block
%type <stmt> stmt var_decl func_decl
%type <token> comparison mop uop crement

%left PLUS MINUS
%left ASTERISK DIV

%start program

%%

program: decls { program = $1; };

decls: decl { $$ = Program(); $$.decls.push_back($<stmt>1); }
	| "pub" decl { $$ = Program(); $$.pub_decls.push_back($<stmt>1); }
	| decls decl { $1.decls.push_back($<stmt>2); }
	| decls "pub" decl { $1.pub_decls.push_back($<stmt>3); }
	| %empty;

decl: var_decl
	| func_decl
	| enum_decl
	| struct_decl
	| type_decl;

var_decl: ident ident EQUAL expr SEMICOLON { $$ = Variable(NULL, $1, $2, $4); }
	| "mut" ident ident SEMICOLON { $$ = Variable($1, $2, $3, NULL); }
	| "con" ident ident EQUAL expr SEMICOLON { $$ = Variable($1, $2, $3, $5); }
	| "mut" ident ident EQUAL expr SEMICOLON { $$ = Variable($1, $2, $3, $5); };
	
func_decl: ident ident L_PAREN func_args R_PAREN body 
	{ $$ = Function($1, $2, $4, $6); delete $4;}
	| ident ident L_PAREN func_decl_args R_PAREN { $$ = Function($1, $2, $4, NULL); delete $4; };

func_decl_args: %empty { $$ = Variables(); }
	| var_decl { $$ = Variables(); $$.push_back($<var>1); }
	| func_decl_args COMMA var_decl { $1.push_back($<var>3); };
	
enum_decl: "enum" ident L_BRACE enum_fields R_BRACE { $$ = Enum($2, $4); delete $4; };

enum_fields: ident { $$ = EnumMembers(); $$.push_back(EnumMember($<ident>1));}
	| enum_fields ident { $1.push_back(EnumMember($2));}
	| ident L_PAREN enum_partners R_PAREN { $$ = EnumMembers(); $$.push_back(EnumMember($1, $2)); delete $2; }
	| enum_fields ident enum_partners { $1.push_back(EnumMember($2, $3)); delete $3; };
	
enum_partners: ident { $$ = EnumPartners(); $$.push_back($1); }
	| partners COMMA ident { $1.push_back($3); };

struct_decl: "struct" ident L_BRACE struct_fields R_BRACE { $$ = Struct($2, $3); delete $3; }
	| "struct" ident COLON struct_inherits L_BRACE struct_fields R_BRACE { $$ = Struct(); };

struct_fields: %empty { $$ = StructFields(); }
	| var_decl { $$ = StructFields(); $$.vars.push_back($1); }
	| func_decl { $$ = StructFields(); $$.methods.push_back($1); }
	| struct_fields var_decl { $1.variables.push_back($2); }
	| struct_fields func_decl { $1.methods.push_back($2); };

struct_inherits: ident {$$; $$.push_back($<ident>1); }
	| struct_inherits COMMA ident { $1.push_back($<ident>2); };

type_decl: "type" type_list { $$ = Type($2); };

type_list: ident { $$ = ; $$.push_back($<ident>1); }
	| type_list PIPE ident { $1.push_back($<ident>2); };

stmts: stmt { $$ = Block(); $$.s.push_back($<stmt>1); }
	| stmts stmt { $1.push_back($<stmt>2); }
	| %empty;

stmt: decl
	| "if" boolean_expr L_BRACE block R_BRACE { $$ = If($2, $4); }
	| "loop" block { $$ = Loop($2); }
	| for ident COLON expr LBRACE block R_BRACE { $$ = For($<ident>1, $4, $6); }
	| match ident L_BRACE match_branches R_BRACE { $$ = Match($<ident>2, $4); }
	| "return" expr SEMICOLON { $$ = Return($2); }
	| "return" SEMICOLON { $$ = Return(); }
	| "defer" expr SEMICOLON { $$ = Defer($2); }
	| "break" SEMICOLON { $$ = Break(); }
	| "continue" SEMICOLON { $$ = Continue(); };

match_branches: %empty
	| match_branch { $$ = MatchBranch($1, $4); }
	| match_branches match_branch { $$ = MatchBranch($1, $4); }

match_branch: expr COLON L_BRACE block R_BRACE { $$ = MatchBranch($1, $4); }
	UNDERSCORE COLON L_BRACE block R_BRACE { $$ = MatchBranch($4); };

block: L_BRACE stmts R_BRACE { $$ = $2; }
	| L_BRACE R_BRACE { $$ = Block(); };

ident: IDENTIFIER { $$ = Identifier($1); delete $1; };

numeric: INTEGER { $$ = Integer(atol($1.c_str())); delete $1; }
	| DOUBLE { $$ = Double(atof($1.c_str())); delete $1; };

expr: ident EQUAL ident { $$ = Assignment($1, $3); }
	| ident L_PAREN call_args R_PAREN { $$ = FunctionCall($<ident>1, $3); }
	| ident { $<ident>$ = $1; }
	| numeric
	| boolean_expr
	| crement expr
	| expr crement
	| uop expr
	| L_PAREN expr R_PAREN { $$ = $2; }
	| expr mop expr
	| func_literal
	| struct_literal;

call_args: %empty
	| ident {}
	| call_args COMMA ident {};
	
boolean_expr: boolean {}
	| boolen_expr lop boolean {};
	
boolean: expr comparison expr {}
	| L_PAREN boolean R_PAREN {}
	| BANG boolean {};
	
lop: AMPERSAND_AMPERSAND
	| PIPE_PIPE;
	
mop: PLUS
	| MINUS
	| ASTERISK
	| SLASH
	| PERCENT
	| AMPERSAND
	| PIPE;

crement: PLUS_PLUS
	| MINUS_MINUS;
	
uop: ASTERISK /* deref */
	| AMPERSAND; /* addrof */
	
comparison: EQUAL_EQUAL
	| BANG_EQUAL
	| LT
	| LT_EQUAL
	| GT
	| GT_EQUAL;

func_literal: ident L_PAREN func_decl_args R_PAREN body { $$ = FunctionLiteral($1, $3, $5); };

struct_literal: "struct" L_BRACE struct_fields R_BRACE { $$ = StructLiteral(); }
	| "struct" COLON struct_inherits L_BRACE struct_fields R_BRACE { $$ = StructLiteral($5, $3); };
