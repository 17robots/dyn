%{
	#include "ast.h"
	extern int yylex();
	void yyerror(const char *s) { printf("ERROR: %s", s); }
	Program *program;
%}

%union {
	Node *node;
	Block *block;
	Expression *expr;
	Statement *stmt;
	Identifier *ident;
	Variable *var;
	std::vector<Variable*> *vars;
	std::vector<Statement*> *stmts;
	std::string *string;
	int token;
}

%token <string> IDENTIFIER INTEGER DOUBLE
%token <token> EQUAL_EQUAL "==" BANG_EQUAL "!=" LT "<" LT_EQUAL "<=" GT ">" GT_EQUAL ">=" EQUAL "="
%token <token> L_PAREN "(" L_BRACK "[" L_BRACE "{" R_PAREN ")" R_BRACK "]" R_BRACE "}"
%token <token> COMMA "," SEMICOLON ";" PERIOD "." COLON ":"
%token <token> PLUS "+" PLUS_EQUAL "+="
%token <token< MINUS "-" MINUS_EQUAL "-="
%token <token> ASTERISK "*" ASTERISK_EQUAL "*="
%token <token> AMPERSAND "&" AMPERSAND_AMPERSAND "&&" AMPERSAND_EQUAL "&="
%token <token> PIPE "|" PIPE_PIPE "||" PIPE_EQUAL "|="
%token <token> BANG "!"

%type <ident> ident
%type <expr> numeric expr
%type <varvec>
%type <exprvec>
%type <block> stmts block
%type <stmy> stmt var_decl func_decl
%type <token> comparison

%left PLUS MINUS
%left ASTERISK DIV

%start program

%%

program: decls { program = $1; };

decls: decl { $$ = new Program(); $$->decls.push_back($<stmt>1); }
	| "pub" decl { $$ = new Program(); $$->pub_decls.push_back($<stmt>1); }
	| decls decl { $1->decls.push_back($<stmt>2); }
	| decls "pub" decl { $1->pub_decls.push_back($<stmt>3); }
	| %empty;

decl: var_decl
	| func_decl
	| enum_decl
	| struct_decl
	| type_decl;

var_decl:
	ident ident EQUAL expr { $$ = new Variable(NULL, *$1, *$2, *$4); }
	| "mut" ident ident { $$ = new Variable(*$1, *$2, *$3, NULL); }
	| "con" ident ident EQUAL expr { $$ = new Variable(*$1, *$2, *$3, *$5); }
	| "mut" ident ident EQUAL expr { $$ = new Variable(*$1, *$2, *$3, *$5); }
	;
	
func_decl: ident ident L_PAREN func_args R_PAREN body 
	{ $$ = new Function(*$1, *$2, *$4, *$6); delete $4;}
	| ident ident L_PAREN func_args R_PAREN { $$ = new Function(*$1, *$2, *$4, NULL); delete $4; };

func_args: %empty { $$ = new Variables(); }
	| var_decl { $$ = new Variables(); $$->push_back($<var>1); }
	| func_args COMMA var_decl { $1->push_back($<var>3); };
	
enum_decl: "enum" ident L_BRACE enum_fields R_BRACE { $$ = new Enum(*$2, *$4); delete $4; };

enum_fields: ident { $$ = new EnumMembers(); $$->push_back(new EnumMember(*$<ident>1));}
	| enum_fields ident { $1->push_back(new EnumMember(*$2));}
	| ident L_PAREN enum_partners R_PAREN { $$ = new EnumMembers(); $$->push_back(new EnumMember(*$1, *$2)); delete $2; }
	| enum_fields ident enum_partners { $1->push_back(new EnumMember(*$2, *$3)); delete $3; };
	
enum_partners: ident { $$ = new EnumPartners(); $$->push_back(*$1); }
	| partners COMMA ident { $1->push_back(*$3); };

struct_decl: "struct" ident L_BRACE struct_fields R_BRACE { $$ = new Struct(); }
	| "struct" ident COLON struct_inherits L_BRACE struct_fields R_BRACE { $$ = new Struct(); };

struct_fields: %empty { $$ = new StructFields(); }
	| var_decl { $$ = new StructFields(); $$->variables.push_back($1); }
	| func_decl { $$ = new StructFields(); $$->methods.push_back($1); }
	| struct_fields var_decl { $1->variables.push_back($2); }
	| struct_fields func_decl { $1->methods.push_back($2); };

struct_inherits: ident {}
	| struct_inherits COMMA ident {};

type_decl: "type" type_list {};

type_list: ident {}
	| type_list PIPE ident {};

stmts: stmt { $$ = new Block(); $$->s.push_back($<stmt>1); }
	| stmts stmt { $1->s.push_back($<stmt>2); }
	| %empty;

stmt: decl
	| /* if */
	| /* loop */
	| /* for */
	| /* match */
	| /* return */
	| /* defer */
	| "break" ';'
	| "continue" ';';

block: L_BRACE stmts R_BRACE { $$ = $2; }
	| L_BRACE R_BRACE { $$ = new Block(); };

ident: IDENTIFIER { $$ = new Identifier(*$1); delete $1; };

numeric: INTEGER { $$ = new Integer(atol($1->c_str())); delete $1; }
	| DOUBLE { $$ = new Double(atof($1->c_str())); delete $1; };

expr: ident EQUAL ident {}
	| ident L_PAREN call_args R_PAREN { $$ = new FunctionCall($<ident>1, *$3); }
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

func_literal: ident L_PAREN func_args R_PAREN body { $$ = new FunctionLiteral($1, *$3, *$5); };

struct_literal: "struct" L_BRACE struct_fields R_BRACE { $$ = new StructLiteral(); }
	| "struct" COLON struct_inherits L_BRACE struct_fields R_BRACE { $$ = new StructLiteral(*$5, *$3); };
