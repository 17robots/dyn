/* A Bison parser, made by GNU Bison 3.8.2.  */

/* Bison interface for Yacc-like parsers in C

   Copyright (C) 1984, 1989-1990, 2000-2015, 2018-2021 Free Software Foundation,
   Inc.

   This program is free software: you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation, either version 3 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program.  If not, see <https://www.gnu.org/licenses/>.  */

/* As a special exception, you may create a larger work that contains
   part or all of the Bison parser skeleton and distribute that work
   under terms of your choice, so long as that work isn't itself a
   parser generator using the skeleton or a modified version thereof
   as a parser skeleton.  Alternatively, if you modify or redistribute
   the parser skeleton itself, you may (at your option) remove this
   special exception, which will cause the skeleton and the resulting
   Bison output files to be licensed under the GNU General Public
   License without this special exception.

   This special exception was added by the Free Software Foundation in
   version 2.2 of Bison.  */

/* DO NOT RELY ON FEATURES THAT ARE NOT DOCUMENTED in the manual,
   especially those whose name start with YY_ or yy_.  They are
   private implementation details that can be changed or removed.  */

#ifndef YY_YY_PARSER_HH_INCLUDED
# define YY_YY_PARSER_HH_INCLUDED
/* Debug traces.  */
#ifndef YYDEBUG
# define YYDEBUG 0
#endif
#if YYDEBUG
extern int yydebug;
#endif

/* Token kinds.  */
#ifndef YYTOKENTYPE
# define YYTOKENTYPE
  enum yytokentype
  {
    YYEMPTY = -2,
    YYEOF = 0,                     /* "end of file"  */
    YYerror = 256,                 /* error  */
    YYUNDEF = 257,                 /* "invalid token"  */
    IDENTIFIER = 258,              /* IDENTIFIER  */
    INTEGER = 259,                 /* INTEGER  */
    DOUBLE = 260,                  /* DOUBLE  */
    EQUAL_EQUAL = 261,             /* EQUAL_EQUAL  */
    BANG_EQUAL = 262,              /* BANG_EQUAL  */
    LT = 263,                      /* LT  */
    LT_EQUAL = 264,                /* LT_EQUAL  */
    GT = 265,                      /* GT  */
    GT_EQUAL = 266,                /* GT_EQUAL  */
    EQUAL = 267,                   /* EQUAL  */
    BANG = 268,                    /* BANG  */
    L_PAREN = 269,                 /* L_PAREN  */
    L_BRACK = 270,                 /* L_BRACK  */
    L_BRACE = 271,                 /* L_BRACE  */
    R_PAREN = 272,                 /* R_PAREN  */
    R_BRACK = 273,                 /* R_BRACK  */
    R_BRACE = 274,                 /* R_BRACE  */
    COMMA = 275,                   /* COMMA  */
    SEMICOLON = 276,               /* SEMICOLON  */
    PERIOD = 277,                  /* PERIOD  */
    COLON = 278,                   /* COLON  */
    PLUS = 279,                    /* PLUS  */
    PLUS_PLUS = 280,               /* PLUS_PLUS  */
    PLUS_EQUAL = 281,              /* PLUS_EQUAL  */
    MINUS = 282,                   /* MINUS  */
    MINUS_MINUS = 283,             /* MINUS_MINUS  */
    MINUS_EQUAL = 284,             /* MINUS_EQUAL  */
    ASTERISK = 285,                /* ASTERISK  */
    ASTERISK_EQUAL = 286,          /* ASTERISK_EQUAL  */
    SLASH = 287,                   /* SLASH  */
    SLASH_EQUAL = 288,             /* SLASH_EQUAL  */
    PERCENT = 289,                 /* PERCENT  */
    PERCENT_EQUAL = 290,           /* PERCENT_EQUAL  */
    AMPERSAND = 291,               /* AMPERSAND  */
    AMPERSAND_AMPERSAND = 292,     /* AMPERSAND_AMPERSAND  */
    AMPERSAND_EQUAL = 293,         /* "&="  */
    PIPE = 294,                    /* PIPE  */
    PIPE_PIPE = 295,               /* PIPE_PIPE  */
    PIPE_EQUAL = 296,              /* PIPE_EQUAL  */
    DIV = 297                      /* DIV  */
  };
  typedef enum yytokentype yytoken_kind_t;
#endif

/* Value type.  */
#if ! defined YYSTYPE && ! defined YYSTYPE_IS_DECLARED
union YYSTYPE
{
#line 8 "dyn.y"

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

#line 126 "parser.hh"

};
typedef union YYSTYPE YYSTYPE;
# define YYSTYPE_IS_TRIVIAL 1
# define YYSTYPE_IS_DECLARED 1
#endif


extern YYSTYPE yylval;


int yyparse (void);


#endif /* !YY_YY_PARSER_HH_INCLUDED  */
