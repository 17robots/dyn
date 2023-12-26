%{
	#include "node.h"
	NBlock *programBlock; /* the top level root node of our final ast */

	extern int yylex();
	void yyerror(const char *s) { printf("ERROR: %sn", s); }
%}

%union {
	Node *node;
	NExpression *expr;
	NStatement *stmt;
	NIdentifier *ident;
	NVariableDeclaration *var;
	std::vector<NVariableDeclaration*> *varvec;
	std::vector<NExpression*> *exprvec;
	std::string *string;
	int token;
}

/*
	Define the terminal symbols (tokens) this should match the tokens.l lex file.
	Also define the node type they represent
*/
%token <string> TIDENTIFIER TINTEGER TDOUBLE
%token <token> TEQUALEQUAL TNEQUAL TLESS TGREAT TLESSEQUAL TGREATEQUAL TEQUAL
%token <token> TLPAREN TRPAREN TLBRACK TRBRACK TLBRACE TRBRACE TCOMMA TPERIOD
%token <token> TPLUS TMINUS TASTERISK TSLASH TPERCENT TAMPERSAND TPIPE
%token <token> TPLUSEQUAL TMINUSEQUAL TASTERISKEQUAL TSLASHEQUAL TPERCENTEQUAL TAMPERSANDEQUAL TPIPEEQUAL
%token <token> TAMPERSANDAMPERSAND TPIPEPIPE

/*
	Define the type of node our nonterminal symbols represent
	The types refer to the %union decl above
*/
%type <ident> ident
%type <expr> numeric_expr
%type <varvec> func_decl_args
%type <exprvec> call_args
%type <block> program stmts block
%type <stmt> stmt var_decl func_decl
%type <token> comparison

/* Operator preference for math operators */
%left TPLUS TMINUS
%left TASTERISK TSLASH TPERCENT

%start program

%%

program : stmts { programBlock = $1; }
        ;

stmts : stmt { $$ = new NBlock(); $$->statements.push_back($<stmt>1); }
      | stmts stmt { $1->statements.push_back($<stmt>2); }
	  ;

stmt : pub_stmt | var_decl | func_decl | enum_decl | struct_decl | type_decl
	 | expr { $$ = new NExpressionStatement(*$1); }
	 ;

block : TLBRACE stmts TRBRACE { $$ = $2; }
	  | TLBRACE TRBRACE { $$ = new NBlock(); }
	  ;

pub_stmt : "pub" stmt
;

var_decl : ident ident { $$ = new NVariableDeclaration(*$1, *$2); }
		 | ident ident ''
;

func_decl : ident ident 
;

enum_decl : "enum" ident TLBRACE enum_members TRBRACE
;

enum_members : enum_member { $$ = new }
			 | enum_members TCOMMA enum_member

struct_decl :
;

type_decl :
;

ident : TIDENTIFIER { $$ = new NIdentifier(*$1); delete $1; }
;

numeric : TINTEGER { $$ = new NInteger(atol($1->c_str())); delete $1; }
		| TDOUBLE { $$ = new NDouble(atof($1->c_str())); delete $1; }

expr : 

call_args : /* blank */ { $$ = new ExpressionList(); }
		  | expr { $$ = new ExpressionList(); $$->push_back($1); }
		  | call_args TCOMMA expr { $1->push_back($3); }
		  ;

comparison : TEQUAL | TNEQUAL | TLESS | TGREAT | TLESSEQUAL | TGREATEQUAL
		   | TPLUS | TMINUS | TASTERISK | TSLASH
		   ;

%% 
