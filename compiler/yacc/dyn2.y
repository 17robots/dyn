%token END 0
%token BREAK "break" CONTINUE "continue" FOR "for" IF "if" LOOP "loop" MATCH "match" MUT "mut" PUB "pub" RETURN "return" IMPORT "import" FROM "from" STRUCT "struct"
%token IDENTIFIER STRINGCONST CHARCONST INTCONST FLOATCONST
%token TILDE SINGLEQUOTE DOUBLEQUOTE 
%token OR "||" AND "&&" EQ "==" NE "!=" PP "++" MM "--" PL_EQ "+=" MI_EQ "-="
%%

program : declarations
declarations: declarations declaration
|;
declaration :  
statements : statements statement
| %empty;
statement : %empty;
