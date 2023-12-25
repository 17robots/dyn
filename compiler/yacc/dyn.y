%token ILLEGAL
%token IDENTIFIER
%token END_OF_FILE 0
%token STRING
%token CHAR
%token INT
%token FLOAT
%token TILDE "~"
%token SINGLE_QUOTE "'"
%token DOUBLE_QUOTE "\""
%token EQUAL "="
%token EQUAL_EQUAL "=="
%token PLUS "+"
%token PLUS_EQUAL "+="
%token MINUS "-"
%token MINUS_EQUAL "-="
%token ASTERISK "*"
%token ASTERISK_EQUAL "*="
%token SLASH "/"
%token SLASH_EQUAL "/="
%token AMPERSAND "&"
%token AMPERSAND_AMPERSAND "&&"
%token AMPERSAND_EQUAL "&="
%token PIPE "|"
%token PIPE_PIPE "||"
%token PIPE_EQUAL "|="
%token LT "<"
%token GT ">"
%token GT_EQUAL ">="
%token LT_EQUAL "<="
%token L_PAREN "("
%token L_BRACK "["
%token L_BRACE "{"
%token R_PAREN ")"
%token R_BRACK "]"
%token R_BRACE "}"
%token SEMICOLON ";"
%token COMMA ","
%token COLON ":"
%token PERIOD "."
%token BREAK "break"
%token CONTINUE "continue"
%token FOR "for"
%token IF "if"
%token LOOP "loop"
%token MATCH "match"
%token MUT "mut"
%token PUB "pub"
%token RETURN "return"
%token IMPORT "import"
%token FROM "from"
%token STRUCT "struct"
%%

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
