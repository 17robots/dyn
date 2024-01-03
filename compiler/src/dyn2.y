%{
	#include "ast.h"
	extern int yylex();
	void yyerror(const char *s) { printf("ERROR: %s", s); }
	Program program = Program();
	program.decls = {};
	program.pub_decls = {};
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
	std::vector<EnumMember> enum_members;
	std::vector<Struct> traits;
	std::vector<MatchBranch> match_branches;
	std::vector<Identifier> type_list;
	std::vector<Identifier> enum_partners;
	StructFields fields;
	MatchBranch match_branch;
	std::string string;
	int token;
}

%token <string> IDENTIFIER INTEGER DOUBLE
%token <token> EQUAL_EQUAL BANG_EQUAL LT LT_EQUAL GT GT_EQUAL EQUAL BANG
%token <token> L_PAREN L_BRACK L_BRACE R_PAREN R_BRACK R_BRACE
%token <token> COMMA SEMICOLON PERIOD COLON
%token <token> PLUS PLUS_PLUS PLUS_EQUAL
%token <token> MINUS MINUS_MINUS MINUS_EQUAL
%token <token> ASTERISK ASTERISK_EQUAL
%token <token> SLASH SLASH_EQUAL
%token <token> PERCENT PERCENT_EQUAL
%token <token> AMPERSAND AMPERSAND_AMPERSAND AMPERSAND_EQUAL
%token <token> PIPE PIPE_PIPE PIPE_EQUAL

%type <ident> ident
%type <expr> numeric expr boolean_expr func_literal struct_literal boolean
%type <vars> func_decl_args
%type <exprs> call_args
%type <block> stmts block
%type <stmt> stmt var_decl func_decl enum_decl struct_decl decl type_decl
%type <token> comparison mop uop crement lop
%type <traits> struct_inherits
%type <match_branches> match_branches
%type <type_list> type_list
%type <enum_members> enum_fields
%type <enum_partners> enum_partners
%type <fields> struct_fields
%type <match_branch> match_branch

%left COMMA
%left AMPERSAND_AMPERSAND PIPE_PIPE
%right EQUAL
%right BANG PLUS_PLUS MINUS_MINUS MINUS
%left SLASH
%right ASTERISK AMPERSAND PIPE
%left L_PAREN
%left L_BRACE
%left L_BRACK
%nonassoc GT GT_EQUAL LT LT_EQUAL
%nonassoc EQUAL_EQUAL BANG_EQUAL

%start decls

%%

decls:
	decls decl { program.decls.push_back($<stmt>2); }
	| decls "pub" decl { program.pub_decls.push_back($<stmt>3); };
	| decl { program.decls.push_back($<stmt>1); }
	| "pub" decl { program.pub_decls.push_back($<stmt>1); }

decl: var_decl
	| func_decl
	| enum_decl
	| struct_decl
	| type_decl;

var_decl: ident ident EQUAL expr SEMICOLON { $<var>$ = Variable(NULL, $<string>1, $2, $4); }
	| "mut" ident ident SEMICOLON { $<var>$ = Variable($<string>1, $2, $3, NULL); }
	| "con" ident ident EQUAL expr SEMICOLON { $<var>$ = Variable($<string>1, $2, $3, $5); }
	| "mut" ident ident EQUAL expr SEMICOLON { $<var>$ = Variable($<string>1, $2, $3, $5); };
	
func_decl: ident ident L_PAREN func_decl_args R_PAREN block 
	{ $$ = Function($1, $2, $4, $6); }
	| ident ident L_PAREN func_decl_args R_PAREN { $$ = Function($1, $2, $4, NULL);  };

func_decl_args: %empty { $$ = Variables(); }
	| var_decl { $$ = Variables(); $$.push_back($<var>1); }
	| func_decl_args COMMA var_decl { $1.push_back($<var>3); };
	
enum_decl: "enum" ident L_BRACE enum_fields R_BRACE { $$ = Enum($2, $4);  };

enum_fields: ident { $$ = {}; $$.push_back(EnumMember($<ident>1)); }
	| enum_fields ident { $1.push_back(EnumMember($2)); }
	| ident L_PAREN enum_partners R_PAREN { $$ = EnumMembers(); $$.push_back(EnumMember($1, $2));  }
	| enum_fields ident enum_partners { $1.push_back(EnumMember($2, $3));  }
	| %empty { $$ = {}; };
	
enum_partners: ident { $$ = {}; $$.push_back($1); }
	| enum_partners COMMA ident { $1.push_back($3); };

struct_decl: "struct" ident L_BRACE struct_fields R_BRACE { $$ = Struct($2, $3);  }
	| "struct" ident COLON struct_inherits L_BRACE struct_fields R_BRACE { $$ = Struct(); };

struct_fields: %empty { $$ = StructFields(); }
	| var_decl { $$ = StructFields(); $$.vars.push_back($1); }
	| func_decl { $$ = StructFields(); $$.methods.push_back($1); }
	| struct_fields var_decl { $1.variables.push_back($2); }
	| struct_fields func_decl { $1.methods.push_back($2); };

struct_inherits: ident {$$ = {}; $$.push_back($<ident>1); }
	| struct_inherits COMMA ident { $1.push_back($<ident>2); };

type_decl: "type" type_list { $$ = Type($2); };

type_list: ident { $$ = {}; $$.push_back($<ident>1); }
	| type_list PIPE ident { $1.push_back($<ident>2); };

stmts: stmt { $$ = Block(); $$.s.push_back($<stmt>1); }
	| stmts stmt { $1.s.push_back($<stmt>2); };
	| %empty { $$ = Block(); }

stmt: decl
	| "if" boolean_expr L_BRACE block R_BRACE { $$ = If($2, $4); }
	| "loop" block { $$ = Loop($2); }
	| "for" ident COLON expr L_BRACE block R_BRACE { $$ = For($<ident>1, $4, $6); }
	| "match" ident L_BRACE match_branches R_BRACE { $$ = Match($<ident>2, $4); }
	| "return" expr SEMICOLON { $$ = Return($2); }
	| "return" SEMICOLON { $$ = Return(); }
	| "defer" expr SEMICOLON { $$ = Defer($2); }
	| "break" SEMICOLON { $$ = Break(); }
	| "continue" SEMICOLON { $$ = Continue(); };

match_branches: %empty { $$ = {}; }
	| match_branch { $$ = {}; $$.push_back($1); }
	| match_branches match_branch { $1.push_back($2); };

match_branch: expr COLON L_BRACE block R_BRACE { $$ = MatchBranch($1, $4); }
	| "_" COLON L_BRACE block R_BRACE { $$ = MatchBranch(NULL, $4); };

block: L_BRACE stmts R_BRACE { $$ = $2; }
	| L_BRACE R_BRACE { $$ = Block(); };

ident: IDENTIFIER { $$ = Identifier($1);  };

numeric: INTEGER { $$ = Integer(atol($1.c_str()));  }
	| DOUBLE { $$ = Double(atof($1.c_str()));  };

expr: ident EQUAL ident { $$ = Assignment($1, $3); }
	| ident L_PAREN call_args R_PAREN { $$ = FunctionCall($<ident>1, $3); }
	| ident { $<ident>$ = $1; }
	| numeric
	| boolean_expr
	| crement expr {$$ = UnaryOp($1, $2); }
	| expr crement {$$ = UnaryOp($2, $1); }
	| uop expr { $$ = UnaryOp($1, $2); }
	| L_PAREN expr R_PAREN { $$ = $2; }
	| expr mop expr { $$ = $$ = BinaryOp($2, $1, $3); }
	| func_literal
	| struct_literal;

call_args: %empty { $$ = {}; }
	| ident { $$ = Identifiers(); $$.push_back($<ident>1); }
	| call_args COMMA ident { $1.push_back($<ident>2); };
	
boolean_expr: boolean
	| boolean_expr lop boolean { $$ = BinaryOp($2, $<expr>1, $<expr>2); };
	
boolean: expr comparison expr { $$ = BinaryOp($2, $1, $3); }
	| L_PAREN expr comparison expr R_PAREN { $$ = BinaryOp($2, $1, $3); }
	| BANG boolean { $$ = UnaryOp($1, $<expr>2); };
	
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

func_literal: ident L_PAREN func_decl_args R_PAREN block { $$ = FunctionLiteral($1, $3, $5); };

struct_literal: "struct" L_BRACE struct_fields R_BRACE { $$ = StructLiteral(); }
	| "struct" COLON struct_inherits L_BRACE struct_fields R_BRACE { $$ = StructLiteral($5, $3); };
