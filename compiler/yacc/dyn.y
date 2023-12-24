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

stmt: com_stmt
| "if" expr stmt
| "loop" stmt
| "return" expr ';'
| var_defs ';'
| expr ';'
| ';';
