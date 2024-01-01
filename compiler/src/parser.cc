/* A Bison parser, made by GNU Bison 3.8.2.  */

/* Bison implementation for Yacc-like parsers in C

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

/* C LALR(1) parser skeleton written by Richard Stallman, by
   simplifying the original so-called "semantic" parser.  */

/* DO NOT RELY ON FEATURES THAT ARE NOT DOCUMENTED in the manual,
   especially those whose name start with YY_ or yy_.  They are
   private implementation details that can be changed or removed.  */

/* All symbols defined below should begin with yy or YY, to avoid
   infringing on user name space.  This should be done even for local
   variables, as they might otherwise be expanded by user macros.
   There are some unavoidable exceptions within include files to
   define necessary library symbols; they are noted "INFRINGES ON
   USER NAME SPACE" below.  */

/* Identify Bison output, and Bison version.  */
#define YYBISON 30802

/* Bison version string.  */
#define YYBISON_VERSION "3.8.2"

/* Skeleton name.  */
#define YYSKELETON_NAME "yacc.c"

/* Pure parsers.  */
#define YYPURE 0

/* Push parsers.  */
#define YYPUSH 0

/* Pull parsers.  */
#define YYPULL 1




/* First part of user prologue.  */
#line 1 "dyn.y"

	#include "ast.h"
	extern int yylex();
	void yyerror(const char *s) { printf("ERROR: %s", s); }
	Program program = Program();

#line 78 "parser.cc"

# ifndef YY_CAST
#  ifdef __cplusplus
#   define YY_CAST(Type, Val) static_cast<Type> (Val)
#   define YY_REINTERPRET_CAST(Type, Val) reinterpret_cast<Type> (Val)
#  else
#   define YY_CAST(Type, Val) ((Type) (Val))
#   define YY_REINTERPRET_CAST(Type, Val) ((Type) (Val))
#  endif
# endif
# ifndef YY_NULLPTR
#  if defined __cplusplus
#   if 201103L <= __cplusplus
#    define YY_NULLPTR nullptr
#   else
#    define YY_NULLPTR 0
#   endif
#  else
#   define YY_NULLPTR ((void*)0)
#  endif
# endif

#include "parser.hh"
/* Symbol kind.  */
enum yysymbol_kind_t
{
  YYSYMBOL_YYEMPTY = -2,
  YYSYMBOL_YYEOF = 0,                      /* "end of file"  */
  YYSYMBOL_YYerror = 1,                    /* error  */
  YYSYMBOL_YYUNDEF = 2,                    /* "invalid token"  */
  YYSYMBOL_IDENTIFIER = 3,                 /* IDENTIFIER  */
  YYSYMBOL_INTEGER = 4,                    /* INTEGER  */
  YYSYMBOL_DOUBLE = 5,                     /* DOUBLE  */
  YYSYMBOL_EQUAL_EQUAL = 6,                /* EQUAL_EQUAL  */
  YYSYMBOL_BANG_EQUAL = 7,                 /* BANG_EQUAL  */
  YYSYMBOL_LT = 8,                         /* LT  */
  YYSYMBOL_LT_EQUAL = 9,                   /* LT_EQUAL  */
  YYSYMBOL_GT = 10,                        /* GT  */
  YYSYMBOL_GT_EQUAL = 11,                  /* GT_EQUAL  */
  YYSYMBOL_EQUAL = 12,                     /* EQUAL  */
  YYSYMBOL_BANG = 13,                      /* BANG  */
  YYSYMBOL_L_PAREN = 14,                   /* L_PAREN  */
  YYSYMBOL_L_BRACK = 15,                   /* L_BRACK  */
  YYSYMBOL_L_BRACE = 16,                   /* L_BRACE  */
  YYSYMBOL_R_PAREN = 17,                   /* R_PAREN  */
  YYSYMBOL_R_BRACK = 18,                   /* R_BRACK  */
  YYSYMBOL_R_BRACE = 19,                   /* R_BRACE  */
  YYSYMBOL_COMMA = 20,                     /* COMMA  */
  YYSYMBOL_SEMICOLON = 21,                 /* SEMICOLON  */
  YYSYMBOL_PERIOD = 22,                    /* PERIOD  */
  YYSYMBOL_COLON = 23,                     /* COLON  */
  YYSYMBOL_PLUS = 24,                      /* PLUS  */
  YYSYMBOL_PLUS_PLUS = 25,                 /* PLUS_PLUS  */
  YYSYMBOL_PLUS_EQUAL = 26,                /* PLUS_EQUAL  */
  YYSYMBOL_MINUS = 27,                     /* MINUS  */
  YYSYMBOL_MINUS_MINUS = 28,               /* MINUS_MINUS  */
  YYSYMBOL_MINUS_EQUAL = 29,               /* MINUS_EQUAL  */
  YYSYMBOL_ASTERISK = 30,                  /* ASTERISK  */
  YYSYMBOL_ASTERISK_EQUAL = 31,            /* ASTERISK_EQUAL  */
  YYSYMBOL_SLASH = 32,                     /* SLASH  */
  YYSYMBOL_SLASH_EQUAL = 33,               /* SLASH_EQUAL  */
  YYSYMBOL_PERCENT = 34,                   /* PERCENT  */
  YYSYMBOL_PERCENT_EQUAL = 35,             /* PERCENT_EQUAL  */
  YYSYMBOL_AMPERSAND = 36,                 /* AMPERSAND  */
  YYSYMBOL_AMPERSAND_AMPERSAND = 37,       /* AMPERSAND_AMPERSAND  */
  YYSYMBOL_AMPERSAND_EQUAL = 38,           /* "&="  */
  YYSYMBOL_PIPE = 39,                      /* PIPE  */
  YYSYMBOL_PIPE_PIPE = 40,                 /* PIPE_PIPE  */
  YYSYMBOL_PIPE_EQUAL = 41,                /* PIPE_EQUAL  */
  YYSYMBOL_DIV = 42,                       /* DIV  */
  YYSYMBOL_43_pub_ = 43,                   /* "pub"  */
  YYSYMBOL_44_mut_ = 44,                   /* "mut"  */
  YYSYMBOL_45_con_ = 45,                   /* "con"  */
  YYSYMBOL_46_enum_ = 46,                  /* "enum"  */
  YYSYMBOL_47_struct_ = 47,                /* "struct"  */
  YYSYMBOL_48_type_ = 48,                  /* "type"  */
  YYSYMBOL_49_if_ = 49,                    /* "if"  */
  YYSYMBOL_50_loop_ = 50,                  /* "loop"  */
  YYSYMBOL_51_for_ = 51,                   /* "for"  */
  YYSYMBOL_52_match_ = 52,                 /* "match"  */
  YYSYMBOL_53_return_ = 53,                /* "return"  */
  YYSYMBOL_54_defer_ = 54,                 /* "defer"  */
  YYSYMBOL_55_break_ = 55,                 /* "break"  */
  YYSYMBOL_56_continue_ = 56,              /* "continue"  */
  YYSYMBOL_57___ = 57,                     /* "_"  */
  YYSYMBOL_YYACCEPT = 58,                  /* $accept  */
  YYSYMBOL_decls = 59,                     /* decls  */
  YYSYMBOL_decl = 60,                      /* decl  */
  YYSYMBOL_var_decl = 61,                  /* var_decl  */
  YYSYMBOL_func_decl = 62,                 /* func_decl  */
  YYSYMBOL_func_decl_args = 63,            /* func_decl_args  */
  YYSYMBOL_enum_decl = 64,                 /* enum_decl  */
  YYSYMBOL_enum_fields = 65,               /* enum_fields  */
  YYSYMBOL_enum_partners = 66,             /* enum_partners  */
  YYSYMBOL_struct_decl = 67,               /* struct_decl  */
  YYSYMBOL_struct_fields = 68,             /* struct_fields  */
  YYSYMBOL_struct_inherits = 69,           /* struct_inherits  */
  YYSYMBOL_type_decl = 70,                 /* type_decl  */
  YYSYMBOL_type_list = 71,                 /* type_list  */
  YYSYMBOL_stmts = 72,                     /* stmts  */
  YYSYMBOL_stmt = 73,                      /* stmt  */
  YYSYMBOL_match_branches = 74,            /* match_branches  */
  YYSYMBOL_match_branch = 75,              /* match_branch  */
  YYSYMBOL_block = 76,                     /* block  */
  YYSYMBOL_ident = 77,                     /* ident  */
  YYSYMBOL_numeric = 78,                   /* numeric  */
  YYSYMBOL_expr = 79,                      /* expr  */
  YYSYMBOL_call_args = 80,                 /* call_args  */
  YYSYMBOL_boolean_expr = 81,              /* boolean_expr  */
  YYSYMBOL_boolean = 82,                   /* boolean  */
  YYSYMBOL_lop = 83,                       /* lop  */
  YYSYMBOL_mop = 84,                       /* mop  */
  YYSYMBOL_crement = 85,                   /* crement  */
  YYSYMBOL_uop = 86,                       /* uop  */
  YYSYMBOL_comparison = 87,                /* comparison  */
  YYSYMBOL_func_literal = 88,              /* func_literal  */
  YYSYMBOL_struct_literal = 89             /* struct_literal  */
};
typedef enum yysymbol_kind_t yysymbol_kind_t;




#ifdef short
# undef short
#endif

/* On compilers that do not define __PTRDIFF_MAX__ etc., make sure
   <limits.h> and (if available) <stdint.h> are included
   so that the code can choose integer types of a good width.  */

#ifndef __PTRDIFF_MAX__
# include <limits.h> /* INFRINGES ON USER NAME SPACE */
# if defined __STDC_VERSION__ && 199901 <= __STDC_VERSION__
#  include <stdint.h> /* INFRINGES ON USER NAME SPACE */
#  define YY_STDINT_H
# endif
#endif

/* Narrow types that promote to a signed type and that can represent a
   signed or unsigned integer of at least N bits.  In tables they can
   save space and decrease cache pressure.  Promoting to a signed type
   helps avoid bugs in integer arithmetic.  */

#ifdef __INT_LEAST8_MAX__
typedef __INT_LEAST8_TYPE__ yytype_int8;
#elif defined YY_STDINT_H
typedef int_least8_t yytype_int8;
#else
typedef signed char yytype_int8;
#endif

#ifdef __INT_LEAST16_MAX__
typedef __INT_LEAST16_TYPE__ yytype_int16;
#elif defined YY_STDINT_H
typedef int_least16_t yytype_int16;
#else
typedef short yytype_int16;
#endif

/* Work around bug in HP-UX 11.23, which defines these macros
   incorrectly for preprocessor constants.  This workaround can likely
   be removed in 2023, as HPE has promised support for HP-UX 11.23
   (aka HP-UX 11i v2) only through the end of 2022; see Table 2 of
   <https://h20195.www2.hpe.com/V2/getpdf.aspx/4AA4-7673ENW.pdf>.  */
#ifdef __hpux
# undef UINT_LEAST8_MAX
# undef UINT_LEAST16_MAX
# define UINT_LEAST8_MAX 255
# define UINT_LEAST16_MAX 65535
#endif

#if defined __UINT_LEAST8_MAX__ && __UINT_LEAST8_MAX__ <= __INT_MAX__
typedef __UINT_LEAST8_TYPE__ yytype_uint8;
#elif (!defined __UINT_LEAST8_MAX__ && defined YY_STDINT_H \
       && UINT_LEAST8_MAX <= INT_MAX)
typedef uint_least8_t yytype_uint8;
#elif !defined __UINT_LEAST8_MAX__ && UCHAR_MAX <= INT_MAX
typedef unsigned char yytype_uint8;
#else
typedef short yytype_uint8;
#endif

#if defined __UINT_LEAST16_MAX__ && __UINT_LEAST16_MAX__ <= __INT_MAX__
typedef __UINT_LEAST16_TYPE__ yytype_uint16;
#elif (!defined __UINT_LEAST16_MAX__ && defined YY_STDINT_H \
       && UINT_LEAST16_MAX <= INT_MAX)
typedef uint_least16_t yytype_uint16;
#elif !defined __UINT_LEAST16_MAX__ && USHRT_MAX <= INT_MAX
typedef unsigned short yytype_uint16;
#else
typedef int yytype_uint16;
#endif

#ifndef YYPTRDIFF_T
# if defined __PTRDIFF_TYPE__ && defined __PTRDIFF_MAX__
#  define YYPTRDIFF_T __PTRDIFF_TYPE__
#  define YYPTRDIFF_MAXIMUM __PTRDIFF_MAX__
# elif defined PTRDIFF_MAX
#  ifndef ptrdiff_t
#   include <stddef.h> /* INFRINGES ON USER NAME SPACE */
#  endif
#  define YYPTRDIFF_T ptrdiff_t
#  define YYPTRDIFF_MAXIMUM PTRDIFF_MAX
# else
#  define YYPTRDIFF_T long
#  define YYPTRDIFF_MAXIMUM LONG_MAX
# endif
#endif

#ifndef YYSIZE_T
# ifdef __SIZE_TYPE__
#  define YYSIZE_T __SIZE_TYPE__
# elif defined size_t
#  define YYSIZE_T size_t
# elif defined __STDC_VERSION__ && 199901 <= __STDC_VERSION__
#  include <stddef.h> /* INFRINGES ON USER NAME SPACE */
#  define YYSIZE_T size_t
# else
#  define YYSIZE_T unsigned
# endif
#endif

#define YYSIZE_MAXIMUM                                  \
  YY_CAST (YYPTRDIFF_T,                                 \
           (YYPTRDIFF_MAXIMUM < YY_CAST (YYSIZE_T, -1)  \
            ? YYPTRDIFF_MAXIMUM                         \
            : YY_CAST (YYSIZE_T, -1)))

#define YYSIZEOF(X) YY_CAST (YYPTRDIFF_T, sizeof (X))


/* Stored state numbers (used for stacks). */
typedef yytype_uint8 yy_state_t;

/* State numbers in computations.  */
typedef int yy_state_fast_t;

#ifndef YY_
# if defined YYENABLE_NLS && YYENABLE_NLS
#  if ENABLE_NLS
#   include <libintl.h> /* INFRINGES ON USER NAME SPACE */
#   define YY_(Msgid) dgettext ("bison-runtime", Msgid)
#  endif
# endif
# ifndef YY_
#  define YY_(Msgid) Msgid
# endif
#endif


#ifndef YY_ATTRIBUTE_PURE
# if defined __GNUC__ && 2 < __GNUC__ + (96 <= __GNUC_MINOR__)
#  define YY_ATTRIBUTE_PURE __attribute__ ((__pure__))
# else
#  define YY_ATTRIBUTE_PURE
# endif
#endif

#ifndef YY_ATTRIBUTE_UNUSED
# if defined __GNUC__ && 2 < __GNUC__ + (7 <= __GNUC_MINOR__)
#  define YY_ATTRIBUTE_UNUSED __attribute__ ((__unused__))
# else
#  define YY_ATTRIBUTE_UNUSED
# endif
#endif

/* Suppress unused-variable warnings by "using" E.  */
#if ! defined lint || defined __GNUC__
# define YY_USE(E) ((void) (E))
#else
# define YY_USE(E) /* empty */
#endif

/* Suppress an incorrect diagnostic about yylval being uninitialized.  */
#if defined __GNUC__ && ! defined __ICC && 406 <= __GNUC__ * 100 + __GNUC_MINOR__
# if __GNUC__ * 100 + __GNUC_MINOR__ < 407
#  define YY_IGNORE_MAYBE_UNINITIALIZED_BEGIN                           \
    _Pragma ("GCC diagnostic push")                                     \
    _Pragma ("GCC diagnostic ignored \"-Wuninitialized\"")
# else
#  define YY_IGNORE_MAYBE_UNINITIALIZED_BEGIN                           \
    _Pragma ("GCC diagnostic push")                                     \
    _Pragma ("GCC diagnostic ignored \"-Wuninitialized\"")              \
    _Pragma ("GCC diagnostic ignored \"-Wmaybe-uninitialized\"")
# endif
# define YY_IGNORE_MAYBE_UNINITIALIZED_END      \
    _Pragma ("GCC diagnostic pop")
#else
# define YY_INITIAL_VALUE(Value) Value
#endif
#ifndef YY_IGNORE_MAYBE_UNINITIALIZED_BEGIN
# define YY_IGNORE_MAYBE_UNINITIALIZED_BEGIN
# define YY_IGNORE_MAYBE_UNINITIALIZED_END
#endif
#ifndef YY_INITIAL_VALUE
# define YY_INITIAL_VALUE(Value) /* Nothing. */
#endif

#if defined __cplusplus && defined __GNUC__ && ! defined __ICC && 6 <= __GNUC__
# define YY_IGNORE_USELESS_CAST_BEGIN                          \
    _Pragma ("GCC diagnostic push")                            \
    _Pragma ("GCC diagnostic ignored \"-Wuseless-cast\"")
# define YY_IGNORE_USELESS_CAST_END            \
    _Pragma ("GCC diagnostic pop")
#endif
#ifndef YY_IGNORE_USELESS_CAST_BEGIN
# define YY_IGNORE_USELESS_CAST_BEGIN
# define YY_IGNORE_USELESS_CAST_END
#endif


#define YY_ASSERT(E) ((void) (0 && (E)))

#if !defined yyoverflow

/* The parser invokes alloca or malloc; define the necessary symbols.  */

# ifdef YYSTACK_USE_ALLOCA
#  if YYSTACK_USE_ALLOCA
#   ifdef __GNUC__
#    define YYSTACK_ALLOC __builtin_alloca
#   elif defined __BUILTIN_VA_ARG_INCR
#    include <alloca.h> /* INFRINGES ON USER NAME SPACE */
#   elif defined _AIX
#    define YYSTACK_ALLOC __alloca
#   elif defined _MSC_VER
#    include <malloc.h> /* INFRINGES ON USER NAME SPACE */
#    define alloca _alloca
#   else
#    define YYSTACK_ALLOC alloca
#    if ! defined _ALLOCA_H && ! defined EXIT_SUCCESS
#     include <stdlib.h> /* INFRINGES ON USER NAME SPACE */
      /* Use EXIT_SUCCESS as a witness for stdlib.h.  */
#     ifndef EXIT_SUCCESS
#      define EXIT_SUCCESS 0
#     endif
#    endif
#   endif
#  endif
# endif

# ifdef YYSTACK_ALLOC
   /* Pacify GCC's 'empty if-body' warning.  */
#  define YYSTACK_FREE(Ptr) do { /* empty */; } while (0)
#  ifndef YYSTACK_ALLOC_MAXIMUM
    /* The OS might guarantee only one guard page at the bottom of the stack,
       and a page size can be as small as 4096 bytes.  So we cannot safely
       invoke alloca (N) if N exceeds 4096.  Use a slightly smaller number
       to allow for a few compiler-allocated temporary stack slots.  */
#   define YYSTACK_ALLOC_MAXIMUM 4032 /* reasonable circa 2006 */
#  endif
# else
#  define YYSTACK_ALLOC YYMALLOC
#  define YYSTACK_FREE YYFREE
#  ifndef YYSTACK_ALLOC_MAXIMUM
#   define YYSTACK_ALLOC_MAXIMUM YYSIZE_MAXIMUM
#  endif
#  if (defined __cplusplus && ! defined EXIT_SUCCESS \
       && ! ((defined YYMALLOC || defined malloc) \
             && (defined YYFREE || defined free)))
#   include <stdlib.h> /* INFRINGES ON USER NAME SPACE */
#   ifndef EXIT_SUCCESS
#    define EXIT_SUCCESS 0
#   endif
#  endif
#  ifndef YYMALLOC
#   define YYMALLOC malloc
#   if ! defined malloc && ! defined EXIT_SUCCESS
void *malloc (YYSIZE_T); /* INFRINGES ON USER NAME SPACE */
#   endif
#  endif
#  ifndef YYFREE
#   define YYFREE free
#   if ! defined free && ! defined EXIT_SUCCESS
void free (void *); /* INFRINGES ON USER NAME SPACE */
#   endif
#  endif
# endif
#endif /* !defined yyoverflow */

#if (! defined yyoverflow \
     && (! defined __cplusplus \
         || (defined YYSTYPE_IS_TRIVIAL && YYSTYPE_IS_TRIVIAL)))

/* A type that is properly aligned for any stack member.  */
union yyalloc
{
  yy_state_t yyss_alloc;
  YYSTYPE yyvs_alloc;
};

/* The size of the maximum gap between one aligned stack and the next.  */
# define YYSTACK_GAP_MAXIMUM (YYSIZEOF (union yyalloc) - 1)

/* The size of an array large to enough to hold all stacks, each with
   N elements.  */
# define YYSTACK_BYTES(N) \
     ((N) * (YYSIZEOF (yy_state_t) + YYSIZEOF (YYSTYPE)) \
      + YYSTACK_GAP_MAXIMUM)

# define YYCOPY_NEEDED 1

/* Relocate STACK from its old location to the new one.  The
   local variables YYSIZE and YYSTACKSIZE give the old and new number of
   elements in the stack, and YYPTR gives the new location of the
   stack.  Advance YYPTR to a properly aligned location for the next
   stack.  */
# define YYSTACK_RELOCATE(Stack_alloc, Stack)                           \
    do                                                                  \
      {                                                                 \
        YYPTRDIFF_T yynewbytes;                                         \
        YYCOPY (&yyptr->Stack_alloc, Stack, yysize);                    \
        Stack = &yyptr->Stack_alloc;                                    \
        yynewbytes = yystacksize * YYSIZEOF (*Stack) + YYSTACK_GAP_MAXIMUM; \
        yyptr += yynewbytes / YYSIZEOF (*yyptr);                        \
      }                                                                 \
    while (0)

#endif

#if defined YYCOPY_NEEDED && YYCOPY_NEEDED
/* Copy COUNT objects from SRC to DST.  The source and destination do
   not overlap.  */
# ifndef YYCOPY
#  if defined __GNUC__ && 1 < __GNUC__
#   define YYCOPY(Dst, Src, Count) \
      __builtin_memcpy (Dst, Src, YY_CAST (YYSIZE_T, (Count)) * sizeof (*(Src)))
#  else
#   define YYCOPY(Dst, Src, Count)              \
      do                                        \
        {                                       \
          YYPTRDIFF_T yyi;                      \
          for (yyi = 0; yyi < (Count); yyi++)   \
            (Dst)[yyi] = (Src)[yyi];            \
        }                                       \
      while (0)
#  endif
# endif
#endif /* !YYCOPY_NEEDED */

/* YYFINAL -- State number of the termination state.  */
#define YYFINAL  23
/* YYLAST -- Last index in YYTABLE.  */
#define YYLAST   660

/* YYNTOKENS -- Number of terminals.  */
#define YYNTOKENS  58
/* YYNNTS -- Number of nonterminals.  */
#define YYNNTS  32
/* YYNRULES -- Number of rules.  */
#define YYNRULES  104
/* YYNSTATES -- Number of states.  */
#define YYNSTATES  194

/* YYMAXUTOK -- Last valid token kind.  */
#define YYMAXUTOK   312


/* YYTRANSLATE(TOKEN-NUM) -- Symbol number corresponding to TOKEN-NUM
   as returned by yylex, with out-of-bounds checking.  */
#define YYTRANSLATE(YYX)                                \
  (0 <= (YYX) && (YYX) <= YYMAXUTOK                     \
   ? YY_CAST (yysymbol_kind_t, yytranslate[YYX])        \
   : YYSYMBOL_YYUNDEF)

/* YYTRANSLATE[TOKEN-NUM] -- Symbol number corresponding to TOKEN-NUM
   as returned by yylex.  */
static const yytype_int8 yytranslate[] =
{
       0,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
       2,     2,     2,     2,     2,     2,     1,     2,     3,     4,
       5,     6,     7,     8,     9,    10,    11,    12,    13,    14,
      15,    16,    17,    18,    19,    20,    21,    22,    23,    24,
      25,    26,    27,    28,    29,    30,    31,    32,    33,    34,
      35,    36,    37,    38,    39,    40,    41,    42,    43,    44,
      45,    46,    47,    48,    49,    50,    51,    52,    53,    54,
      55,    56,    57
};

#if YYDEBUG
/* YYRLINE[YYN] -- Source line where rule number YYN was defined.  */
static const yytype_uint8 yyrline[] =
{
       0,    62,    62,    63,    64,    65,    66,    68,    69,    70,
      71,    72,    74,    75,    76,    77,    79,    81,    83,    84,
      85,    87,    89,    90,    91,    92,    94,    95,    97,    98,
     100,   101,   102,   103,   104,   106,   107,   109,   111,   112,
     114,   115,   116,   118,   119,   120,   121,   122,   123,   124,
     125,   126,   127,   129,   130,   131,   133,   134,   136,   137,
     139,   141,   142,   144,   145,   146,   147,   148,   149,   150,
     151,   152,   153,   154,   155,   157,   158,   159,   161,   162,
     164,   165,   166,   168,   169,   171,   172,   173,   174,   175,
     176,   177,   179,   180,   182,   183,   185,   186,   187,   188,
     189,   190,   192,   194,   195
};
#endif

/** Accessing symbol of state STATE.  */
#define YY_ACCESSING_SYMBOL(State) YY_CAST (yysymbol_kind_t, yystos[State])

#if YYDEBUG || 0
/* The user-facing name of the symbol whose (internal) number is
   YYSYMBOL.  No bounds checking.  */
static const char *yysymbol_name (yysymbol_kind_t yysymbol) YY_ATTRIBUTE_UNUSED;

/* YYTNAME[SYMBOL-NUM] -- String name of the symbol SYMBOL-NUM.
   First, the terminals, then, starting at YYNTOKENS, nonterminals.  */
static const char *const yytname[] =
{
  "\"end of file\"", "error", "\"invalid token\"", "IDENTIFIER",
  "INTEGER", "DOUBLE", "EQUAL_EQUAL", "BANG_EQUAL", "LT", "LT_EQUAL", "GT",
  "GT_EQUAL", "EQUAL", "BANG", "L_PAREN", "L_BRACK", "L_BRACE", "R_PAREN",
  "R_BRACK", "R_BRACE", "COMMA", "SEMICOLON", "PERIOD", "COLON", "PLUS",
  "PLUS_PLUS", "PLUS_EQUAL", "MINUS", "MINUS_MINUS", "MINUS_EQUAL",
  "ASTERISK", "ASTERISK_EQUAL", "SLASH", "SLASH_EQUAL", "PERCENT",
  "PERCENT_EQUAL", "AMPERSAND", "AMPERSAND_AMPERSAND", "\"&=\"", "PIPE",
  "PIPE_PIPE", "PIPE_EQUAL", "DIV", "\"pub\"", "\"mut\"", "\"con\"",
  "\"enum\"", "\"struct\"", "\"type\"", "\"if\"", "\"loop\"", "\"for\"",
  "\"match\"", "\"return\"", "\"defer\"", "\"break\"", "\"continue\"",
  "\"_\"", "$accept", "decls", "decl", "var_decl", "func_decl",
  "func_decl_args", "enum_decl", "enum_fields", "enum_partners",
  "struct_decl", "struct_fields", "struct_inherits", "type_decl",
  "type_list", "stmts", "stmt", "match_branches", "match_branch", "block",
  "ident", "numeric", "expr", "call_args", "boolean_expr", "boolean",
  "lop", "mop", "crement", "uop", "comparison", "func_literal",
  "struct_literal", YY_NULLPTR
};

static const char *
yysymbol_name (yysymbol_kind_t yysymbol)
{
  return yytname[yysymbol];
}
#endif

#define YYPACT_NINF (-92)

#define yypact_value_is_default(Yyn) \
  ((Yyn) == YYPACT_NINF)

#define YYTABLE_NINF (-83)

#define yytable_value_is_error(Yyn) \
  0

/* YYPACT[STATE-NUM] -- Index in YYTABLE of the portion describing
   STATE-NUM.  */
static const yytype_int16 yypact[] =
{
     208,   -92,   213,     8,     8,     8,     8,     8,   179,   -92,
     -92,   -92,   -92,   -92,   -92,     8,   -92,     8,     8,    -4,
      -7,   -17,   -92,   -92,   213,   -92,   137,    52,    22,     8,
      10,     8,     8,   -92,   284,    10,   284,   -92,   284,     7,
      31,   -92,   -92,    17,    69,   -92,   -92,   -92,   -92,   284,
     284,   -92,   -92,   -92,   -92,    24,   154,   -92,   315,    67,
     -92,   284,   284,   -92,   -92,   -92,    92,     8,   349,   383,
     -92,     8,     8,   -92,   -92,   -92,    10,     8,   621,   181,
     417,    10,     8,     8,    10,   -92,   -92,   -92,   -92,   -92,
     -92,   -92,   -92,   -92,   -92,   -92,   -92,   -92,   -92,   284,
     -92,   284,   -92,   -92,   284,   621,   621,    36,    10,    45,
     -92,   -92,    38,   -92,    94,    50,   -92,   -92,   284,    56,
      71,   -92,   101,     8,   107,   621,   621,   279,   187,   -92,
     -92,     8,   -92,   -92,   451,   -92,    10,    36,   -92,     8,
     -92,   284,    36,     8,     8,   280,   284,    49,    59,   -92,
     226,   -92,   -92,   -92,   103,   -92,   -92,   100,   -92,    40,
      82,   -92,   485,   519,   -92,   -92,   -92,   -92,   -92,    36,
     284,   171,   -92,   -92,    83,   553,   102,   158,   -92,   587,
     -92,    36,   110,   -92,   -92,   113,    91,    36,    36,   -92,
     111,   116,   -92,   -92
};

/* YYDEFACT[STATE-NUM] -- Default reduction number in state STATE-NUM.
   Performed when YYTABLE does not specify something else to do.  Zero
   means the default is an error.  */
static const yytype_int8 yydefact[] =
{
       6,    60,     0,     0,     0,     0,     0,     0,     0,     2,
       7,     8,     9,    10,    11,     0,     3,     0,     0,     0,
       0,    37,    38,     1,     0,     4,     0,     0,     0,     0,
      30,     0,     0,     5,     0,    18,     0,    13,     0,     0,
      22,    31,    32,     0,     0,    35,    39,    61,    62,     0,
       0,    92,    93,    94,    95,     0,    65,    66,     0,    67,
      78,     0,     0,    73,    74,    19,     0,     0,     0,     0,
      21,    23,     0,    28,    33,    34,    30,     0,     0,    78,
       0,    30,     0,     0,    18,    96,    97,    98,    99,   100,
     101,    12,    85,    86,    87,    88,    89,    90,    91,     0,
      69,     0,    83,    84,     0,    68,    70,    17,     0,     0,
      15,    14,    25,    26,     0,     0,    36,    71,     0,     0,
       0,    63,     0,    76,     0,    72,    80,    78,     0,    16,
      20,     0,    24,    29,    80,   103,    30,     0,    64,     0,
      59,     0,     0,     0,     0,     0,     0,     0,     0,    43,
       0,    41,    27,    81,     0,   102,    77,    67,    45,     0,
       0,    49,     0,     0,    51,    52,    58,    42,   104,     0,
       0,    53,    48,    50,     0,     0,     0,     0,    54,     0,
      44,     0,     0,    47,    55,     0,     0,     0,     0,    46,
       0,     0,    57,    56
};

/* YYPGOTO[NTERM-NUM].  */
static const yytype_int8 yypgoto[] =
{
     -92,   -92,    42,   -16,    -2,    57,   -92,   -92,    70,   -92,
     -43,    64,   -92,   -92,   -92,     3,   -92,   -18,   -91,     0,
     -92,   -13,   -92,    19,   -48,   -92,   -92,    87,   -92,    89,
     -92,   -92
};

/* YYDEFGOTO[NTERM-NUM].  */
static const yytype_uint8 yydefgoto[] =
{
       0,     8,   149,    10,    11,    66,    12,    39,   112,    13,
      43,    44,    14,    21,   150,   151,   177,   178,   129,    56,
      57,    78,   124,    59,    60,   104,    99,    61,    62,   101,
      63,    64
};

/* YYTABLE[YYPACT[STATE-NUM]] -- What to do in state STATE-NUM.  If
   positive, shift that token.  If negative, reduce the rule whose
   number is the opposite.  If YYTABLE_NINF, syntax error.  */
static const yytype_int16 yytable[] =
{
      15,    79,    15,    17,    18,    19,    20,    22,    15,    30,
       1,     1,    29,     1,    41,    26,    31,    27,    28,    65,
       1,    58,    32,    68,    15,    69,    70,    74,    42,    40,
      15,    45,    46,   115,    38,    67,    73,    80,   119,    71,
      81,    75,     9,    15,    16,    72,   155,    82,   105,   106,
      25,   158,   128,     1,     3,     4,   127,    34,   131,     1,
      41,     3,     4,   170,    36,    41,    33,   109,    65,   133,
     164,   113,   113,    37,    42,   135,    15,   116,   174,    42,
     165,    15,    45,   121,   123,    76,   125,   136,   126,    77,
     186,    77,   130,   154,     3,     4,   190,   191,   171,    74,
       3,     4,   180,    74,   102,   134,     1,   103,    67,   107,
     189,   132,   108,    75,   131,    15,   169,    75,   137,    15,
      41,   108,   168,   109,   138,   182,   187,   139,    15,   188,
     192,   152,   162,   163,    42,   193,    15,   102,    74,   156,
     103,   122,   114,   159,   160,   100,   120,     3,     4,    34,
      15,    35,    75,   167,    15,   100,   100,   175,   179,   184,
     157,     1,    47,    48,   179,   100,    83,   100,    84,   118,
       0,    49,    50,     0,     1,    47,    48,   183,     0,    23,
       0,     0,     1,    51,    49,    50,    52,     0,    53,     0,
       1,     0,   100,   100,    54,     0,    51,   -82,   -82,    52,
       0,    53,   -82,     0,   -82,    55,   140,    54,     0,     0,
       0,     1,   100,   100,     0,   176,     1,     0,    55,     0,
       0,   100,    24,     3,     4,     5,     6,     7,   176,     1,
       0,     3,     4,     5,     6,     7,   141,   142,   143,   144,
     145,   146,   147,   148,     0,   166,     0,     0,     0,   100,
     100,     2,     3,     4,     5,     6,     7,     3,     4,     5,
       6,     7,   100,     0,     0,     0,   100,     0,     0,     0,
       3,     4,     5,     6,     7,   141,   142,   143,   144,   145,
     146,   147,   148,     1,    47,    48,     0,     1,    47,    48,
       0,     0,     0,    49,    50,   -79,   -79,    49,    50,     0,
     -79,   161,   -79,     0,     0,    51,     0,     0,    52,    51,
      53,     0,    52,     0,    53,     0,    54,     0,     0,     0,
      54,    85,    86,    87,    88,    89,    90,    55,     0,     0,
       0,    55,     0,     0,     0,     0,    91,     0,     0,    92,
      51,     0,    93,    52,     0,    94,     0,    95,     0,    96,
       0,    97,     0,     0,    98,    85,    86,    87,    88,    89,
      90,     0,     0,     0,     0,     0,     0,     0,     0,     0,
     110,     0,     0,    92,    51,     0,    93,    52,     0,    94,
       0,    95,     0,    96,     0,    97,     0,     0,    98,    85,
      86,    87,    88,    89,    90,     0,     0,     0,     0,     0,
       0,     0,     0,     0,   111,     0,     0,    92,    51,     0,
      93,    52,     0,    94,     0,    95,     0,    96,     0,    97,
       0,     0,    98,    85,    86,    87,    88,    89,    90,     0,
       0,     0,     0,     0,   117,     0,     0,     0,     0,     0,
       0,    92,    51,     0,    93,    52,     0,    94,     0,    95,
       0,    96,     0,    97,     0,     0,    98,    85,    86,    87,
      88,    89,    90,     0,     0,     0,     0,     0,   153,     0,
       0,     0,     0,     0,     0,    92,    51,     0,    93,    52,
       0,    94,     0,    95,     0,    96,     0,    97,     0,     0,
      98,    85,    86,    87,    88,    89,    90,     0,     0,     0,
       0,     0,     0,     0,     0,     0,   172,     0,     0,    92,
      51,     0,    93,    52,     0,    94,     0,    95,     0,    96,
       0,    97,     0,     0,    98,    85,    86,    87,    88,    89,
      90,     0,     0,     0,     0,     0,     0,     0,     0,     0,
     173,     0,     0,    92,    51,     0,    93,    52,     0,    94,
       0,    95,     0,    96,     0,    97,     0,     0,    98,    85,
      86,    87,    88,    89,    90,     0,     0,     0,     0,   181,
       0,     0,     0,     0,     0,     0,     0,    92,    51,     0,
      93,    52,     0,    94,     0,    95,     0,    96,     0,    97,
       0,     0,    98,    85,    86,    87,    88,    89,    90,     0,
       0,     0,     0,     0,     0,     0,     0,     0,     0,     0,
     185,    92,    51,     0,    93,    52,     0,    94,     0,    95,
       0,    96,     0,    97,     0,     0,    98,    85,    86,    87,
      88,    89,    90,     0,     0,     0,     0,     0,     0,     0,
       0,     0,     0,     0,     0,    92,    51,     0,    93,    52,
       0,    94,     0,    95,     0,    96,     0,    97,     0,     0,
      98
};

static const yytype_int16 yycheck[] =
{
       0,    49,     2,     3,     4,     5,     6,     7,     8,    16,
       3,     3,    16,     3,    30,    15,    23,    17,    18,    35,
       3,    34,    39,    36,    24,    38,    19,    43,    30,    29,
      30,    31,    32,    76,    12,    35,    19,    50,    81,    39,
      16,    43,     0,    43,     2,    14,   137,    23,    61,    62,
       8,   142,    16,     3,    44,    45,   104,    12,    20,     3,
      76,    44,    45,    23,    12,    81,    24,    67,    84,    19,
      21,    71,    72,    21,    76,    19,    76,    77,   169,    81,
      21,    81,    82,    83,    84,    16,    99,    16,   101,    20,
     181,    20,   108,   136,    44,    45,   187,   188,    16,   115,
      44,    45,    19,   119,    37,   118,     3,    40,   108,    17,
      19,    17,    20,   115,    20,   115,    16,   119,    17,   119,
     136,    20,    19,   123,    17,    23,    16,    20,   128,    16,
      19,   131,   145,   146,   136,    19,   136,    37,   154,   139,
      40,    84,    72,   143,   144,    58,    82,    44,    45,    12,
     150,    14,   154,   150,   154,    68,    69,   170,   171,   177,
     141,     3,     4,     5,   177,    78,    12,    80,    14,    80,
      -1,    13,    14,    -1,     3,     4,     5,    19,    -1,     0,
      -1,    -1,     3,    25,    13,    14,    28,    -1,    30,    -1,
       3,    -1,   105,   106,    36,    -1,    25,    16,    17,    28,
      -1,    30,    21,    -1,    23,    47,    19,    36,    -1,    -1,
      -1,     3,   125,   126,    -1,    57,     3,    -1,    47,    -1,
      -1,   134,    43,    44,    45,    46,    47,    48,    57,     3,
      -1,    44,    45,    46,    47,    48,    49,    50,    51,    52,
      53,    54,    55,    56,    -1,    19,    -1,    -1,    -1,   162,
     163,    43,    44,    45,    46,    47,    48,    44,    45,    46,
      47,    48,   175,    -1,    -1,    -1,   179,    -1,    -1,    -1,
      44,    45,    46,    47,    48,    49,    50,    51,    52,    53,
      54,    55,    56,     3,     4,     5,    -1,     3,     4,     5,
      -1,    -1,    -1,    13,    14,    16,    17,    13,    14,    -1,
      21,    21,    23,    -1,    -1,    25,    -1,    -1,    28,    25,
      30,    -1,    28,    -1,    30,    -1,    36,    -1,    -1,    -1,
      36,     6,     7,     8,     9,    10,    11,    47,    -1,    -1,
      -1,    47,    -1,    -1,    -1,    -1,    21,    -1,    -1,    24,
      25,    -1,    27,    28,    -1,    30,    -1,    32,    -1,    34,
      -1,    36,    -1,    -1,    39,     6,     7,     8,     9,    10,
      11,    -1,    -1,    -1,    -1,    -1,    -1,    -1,    -1,    -1,
      21,    -1,    -1,    24,    25,    -1,    27,    28,    -1,    30,
      -1,    32,    -1,    34,    -1,    36,    -1,    -1,    39,     6,
       7,     8,     9,    10,    11,    -1,    -1,    -1,    -1,    -1,
      -1,    -1,    -1,    -1,    21,    -1,    -1,    24,    25,    -1,
      27,    28,    -1,    30,    -1,    32,    -1,    34,    -1,    36,
      -1,    -1,    39,     6,     7,     8,     9,    10,    11,    -1,
      -1,    -1,    -1,    -1,    17,    -1,    -1,    -1,    -1,    -1,
      -1,    24,    25,    -1,    27,    28,    -1,    30,    -1,    32,
      -1,    34,    -1,    36,    -1,    -1,    39,     6,     7,     8,
       9,    10,    11,    -1,    -1,    -1,    -1,    -1,    17,    -1,
      -1,    -1,    -1,    -1,    -1,    24,    25,    -1,    27,    28,
      -1,    30,    -1,    32,    -1,    34,    -1,    36,    -1,    -1,
      39,     6,     7,     8,     9,    10,    11,    -1,    -1,    -1,
      -1,    -1,    -1,    -1,    -1,    -1,    21,    -1,    -1,    24,
      25,    -1,    27,    28,    -1,    30,    -1,    32,    -1,    34,
      -1,    36,    -1,    -1,    39,     6,     7,     8,     9,    10,
      11,    -1,    -1,    -1,    -1,    -1,    -1,    -1,    -1,    -1,
      21,    -1,    -1,    24,    25,    -1,    27,    28,    -1,    30,
      -1,    32,    -1,    34,    -1,    36,    -1,    -1,    39,     6,
       7,     8,     9,    10,    11,    -1,    -1,    -1,    -1,    16,
      -1,    -1,    -1,    -1,    -1,    -1,    -1,    24,    25,    -1,
      27,    28,    -1,    30,    -1,    32,    -1,    34,    -1,    36,
      -1,    -1,    39,     6,     7,     8,     9,    10,    11,    -1,
      -1,    -1,    -1,    -1,    -1,    -1,    -1,    -1,    -1,    -1,
      23,    24,    25,    -1,    27,    28,    -1,    30,    -1,    32,
      -1,    34,    -1,    36,    -1,    -1,    39,     6,     7,     8,
       9,    10,    11,    -1,    -1,    -1,    -1,    -1,    -1,    -1,
      -1,    -1,    -1,    -1,    -1,    24,    25,    -1,    27,    28,
      -1,    30,    -1,    32,    -1,    34,    -1,    36,    -1,    -1,
      39
};

/* YYSTOS[STATE-NUM] -- The symbol kind of the accessing symbol of
   state STATE-NUM.  */
static const yytype_int8 yystos[] =
{
       0,     3,    43,    44,    45,    46,    47,    48,    59,    60,
      61,    62,    64,    67,    70,    77,    60,    77,    77,    77,
      77,    71,    77,     0,    43,    60,    77,    77,    77,    16,
      16,    23,    39,    60,    12,    14,    12,    21,    12,    65,
      77,    61,    62,    68,    69,    77,    77,     4,     5,    13,
      14,    25,    28,    30,    36,    47,    77,    78,    79,    81,
      82,    85,    86,    88,    89,    61,    63,    77,    79,    79,
      19,    77,    14,    19,    61,    62,    16,    20,    79,    82,
      79,    16,    23,    12,    14,     6,     7,     8,     9,    10,
      11,    21,    24,    27,    30,    32,    34,    36,    39,    84,
      85,    87,    37,    40,    83,    79,    79,    17,    20,    77,
      21,    21,    66,    77,    66,    68,    77,    17,    87,    68,
      69,    77,    63,    77,    80,    79,    79,    82,    16,    76,
      61,    20,    17,    19,    79,    19,    16,    17,    17,    20,
      19,    49,    50,    51,    52,    53,    54,    55,    56,    60,
      72,    73,    77,    17,    68,    76,    77,    81,    76,    77,
      77,    21,    79,    79,    21,    21,    19,    73,    19,    16,
      23,    16,    21,    21,    76,    79,    57,    74,    75,    79,
      19,    16,    23,    19,    75,    23,    76,    16,    16,    19,
      76,    76,    19,    19
};

/* YYR1[RULE-NUM] -- Symbol kind of the left-hand side of rule RULE-NUM.  */
static const yytype_int8 yyr1[] =
{
       0,    58,    59,    59,    59,    59,    59,    60,    60,    60,
      60,    60,    61,    61,    61,    61,    62,    62,    63,    63,
      63,    64,    65,    65,    65,    65,    66,    66,    67,    67,
      68,    68,    68,    68,    68,    69,    69,    70,    71,    71,
      72,    72,    72,    73,    73,    73,    73,    73,    73,    73,
      73,    73,    73,    74,    74,    74,    75,    75,    76,    76,
      77,    78,    78,    79,    79,    79,    79,    79,    79,    79,
      79,    79,    79,    79,    79,    80,    80,    80,    81,    81,
      82,    82,    82,    83,    83,    84,    84,    84,    84,    84,
      84,    84,    85,    85,    86,    86,    87,    87,    87,    87,
      87,    87,    88,    89,    89
};

/* YYR2[RULE-NUM] -- Number of symbols on the right-hand side of rule RULE-NUM.  */
static const yytype_int8 yyr2[] =
{
       0,     2,     1,     2,     2,     3,     0,     1,     1,     1,
       1,     1,     5,     4,     6,     6,     6,     5,     0,     1,
       3,     5,     1,     2,     4,     3,     1,     3,     5,     7,
       0,     1,     1,     2,     2,     1,     3,     2,     1,     3,
       0,     1,     2,     1,     5,     2,     7,     5,     3,     2,
       3,     2,     2,     0,     1,     2,     5,     5,     3,     2,
       1,     1,     1,     3,     4,     1,     1,     1,     2,     2,
       2,     3,     3,     1,     1,     0,     1,     3,     1,     3,
       3,     5,     2,     1,     1,     1,     1,     1,     1,     1,
       1,     1,     1,     1,     1,     1,     1,     1,     1,     1,
       1,     1,     5,     4,     6
};


enum { YYENOMEM = -2 };

#define yyerrok         (yyerrstatus = 0)
#define yyclearin       (yychar = YYEMPTY)

#define YYACCEPT        goto yyacceptlab
#define YYABORT         goto yyabortlab
#define YYERROR         goto yyerrorlab
#define YYNOMEM         goto yyexhaustedlab


#define YYRECOVERING()  (!!yyerrstatus)

#define YYBACKUP(Token, Value)                                    \
  do                                                              \
    if (yychar == YYEMPTY)                                        \
      {                                                           \
        yychar = (Token);                                         \
        yylval = (Value);                                         \
        YYPOPSTACK (yylen);                                       \
        yystate = *yyssp;                                         \
        goto yybackup;                                            \
      }                                                           \
    else                                                          \
      {                                                           \
        yyerror (YY_("syntax error: cannot back up")); \
        YYERROR;                                                  \
      }                                                           \
  while (0)

/* Backward compatibility with an undocumented macro.
   Use YYerror or YYUNDEF. */
#define YYERRCODE YYUNDEF


/* Enable debugging if requested.  */
#if YYDEBUG

# ifndef YYFPRINTF
#  include <stdio.h> /* INFRINGES ON USER NAME SPACE */
#  define YYFPRINTF fprintf
# endif

# define YYDPRINTF(Args)                        \
do {                                            \
  if (yydebug)                                  \
    YYFPRINTF Args;                             \
} while (0)




# define YY_SYMBOL_PRINT(Title, Kind, Value, Location)                    \
do {                                                                      \
  if (yydebug)                                                            \
    {                                                                     \
      YYFPRINTF (stderr, "%s ", Title);                                   \
      yy_symbol_print (stderr,                                            \
                  Kind, Value); \
      YYFPRINTF (stderr, "\n");                                           \
    }                                                                     \
} while (0)


/*-----------------------------------.
| Print this symbol's value on YYO.  |
`-----------------------------------*/

static void
yy_symbol_value_print (FILE *yyo,
                       yysymbol_kind_t yykind, YYSTYPE const * const yyvaluep)
{
  FILE *yyoutput = yyo;
  YY_USE (yyoutput);
  if (!yyvaluep)
    return;
  YY_IGNORE_MAYBE_UNINITIALIZED_BEGIN
  YY_USE (yykind);
  YY_IGNORE_MAYBE_UNINITIALIZED_END
}


/*---------------------------.
| Print this symbol on YYO.  |
`---------------------------*/

static void
yy_symbol_print (FILE *yyo,
                 yysymbol_kind_t yykind, YYSTYPE const * const yyvaluep)
{
  YYFPRINTF (yyo, "%s %s (",
             yykind < YYNTOKENS ? "token" : "nterm", yysymbol_name (yykind));

  yy_symbol_value_print (yyo, yykind, yyvaluep);
  YYFPRINTF (yyo, ")");
}

/*------------------------------------------------------------------.
| yy_stack_print -- Print the state stack from its BOTTOM up to its |
| TOP (included).                                                   |
`------------------------------------------------------------------*/

static void
yy_stack_print (yy_state_t *yybottom, yy_state_t *yytop)
{
  YYFPRINTF (stderr, "Stack now");
  for (; yybottom <= yytop; yybottom++)
    {
      int yybot = *yybottom;
      YYFPRINTF (stderr, " %d", yybot);
    }
  YYFPRINTF (stderr, "\n");
}

# define YY_STACK_PRINT(Bottom, Top)                            \
do {                                                            \
  if (yydebug)                                                  \
    yy_stack_print ((Bottom), (Top));                           \
} while (0)


/*------------------------------------------------.
| Report that the YYRULE is going to be reduced.  |
`------------------------------------------------*/

static void
yy_reduce_print (yy_state_t *yyssp, YYSTYPE *yyvsp,
                 int yyrule)
{
  int yylno = yyrline[yyrule];
  int yynrhs = yyr2[yyrule];
  int yyi;
  YYFPRINTF (stderr, "Reducing stack by rule %d (line %d):\n",
             yyrule - 1, yylno);
  /* The symbols being reduced.  */
  for (yyi = 0; yyi < yynrhs; yyi++)
    {
      YYFPRINTF (stderr, "   $%d = ", yyi + 1);
      yy_symbol_print (stderr,
                       YY_ACCESSING_SYMBOL (+yyssp[yyi + 1 - yynrhs]),
                       &yyvsp[(yyi + 1) - (yynrhs)]);
      YYFPRINTF (stderr, "\n");
    }
}

# define YY_REDUCE_PRINT(Rule)          \
do {                                    \
  if (yydebug)                          \
    yy_reduce_print (yyssp, yyvsp, Rule); \
} while (0)

/* Nonzero means print parse trace.  It is left uninitialized so that
   multiple parsers can coexist.  */
int yydebug;
#else /* !YYDEBUG */
# define YYDPRINTF(Args) ((void) 0)
# define YY_SYMBOL_PRINT(Title, Kind, Value, Location)
# define YY_STACK_PRINT(Bottom, Top)
# define YY_REDUCE_PRINT(Rule)
#endif /* !YYDEBUG */


/* YYINITDEPTH -- initial size of the parser's stacks.  */
#ifndef YYINITDEPTH
# define YYINITDEPTH 200
#endif

/* YYMAXDEPTH -- maximum size the stacks can grow to (effective only
   if the built-in stack extension method is used).

   Do not make this value too large; the results are undefined if
   YYSTACK_ALLOC_MAXIMUM < YYSTACK_BYTES (YYMAXDEPTH)
   evaluated with infinite-precision integer arithmetic.  */

#ifndef YYMAXDEPTH
# define YYMAXDEPTH 10000
#endif






/*-----------------------------------------------.
| Release the memory associated to this symbol.  |
`-----------------------------------------------*/

static void
yydestruct (const char *yymsg,
            yysymbol_kind_t yykind, YYSTYPE *yyvaluep)
{
  YY_USE (yyvaluep);
  if (!yymsg)
    yymsg = "Deleting";
  YY_SYMBOL_PRINT (yymsg, yykind, yyvaluep, yylocationp);

  YY_IGNORE_MAYBE_UNINITIALIZED_BEGIN
  YY_USE (yykind);
  YY_IGNORE_MAYBE_UNINITIALIZED_END
}


/* Lookahead token kind.  */
int yychar;

/* The semantic value of the lookahead symbol.  */
YYSTYPE yylval;
/* Number of syntax errors so far.  */
int yynerrs;




/*----------.
| yyparse.  |
`----------*/

int
yyparse (void)
{
    yy_state_fast_t yystate = 0;
    /* Number of tokens to shift before error messages enabled.  */
    int yyerrstatus = 0;

    /* Refer to the stacks through separate pointers, to allow yyoverflow
       to reallocate them elsewhere.  */

    /* Their size.  */
    YYPTRDIFF_T yystacksize = YYINITDEPTH;

    /* The state stack: array, bottom, top.  */
    yy_state_t yyssa[YYINITDEPTH];
    yy_state_t *yyss = yyssa;
    yy_state_t *yyssp = yyss;

    /* The semantic value stack: array, bottom, top.  */
    YYSTYPE yyvsa[YYINITDEPTH];
    YYSTYPE *yyvs = yyvsa;
    YYSTYPE *yyvsp = yyvs;

  int yyn;
  /* The return value of yyparse.  */
  int yyresult;
  /* Lookahead symbol kind.  */
  yysymbol_kind_t yytoken = YYSYMBOL_YYEMPTY;
  /* The variables used to return semantic value and location from the
     action routines.  */
  YYSTYPE yyval;



#define YYPOPSTACK(N)   (yyvsp -= (N), yyssp -= (N))

  /* The number of symbols on the RHS of the reduced rule.
     Keep to zero when no symbol should be popped.  */
  int yylen = 0;

  YYDPRINTF ((stderr, "Starting parse\n"));

  yychar = YYEMPTY; /* Cause a token to be read.  */

  goto yysetstate;


/*------------------------------------------------------------.
| yynewstate -- push a new state, which is found in yystate.  |
`------------------------------------------------------------*/
yynewstate:
  /* In all cases, when you get here, the value and location stacks
     have just been pushed.  So pushing a state here evens the stacks.  */
  yyssp++;


/*--------------------------------------------------------------------.
| yysetstate -- set current state (the top of the stack) to yystate.  |
`--------------------------------------------------------------------*/
yysetstate:
  YYDPRINTF ((stderr, "Entering state %d\n", yystate));
  YY_ASSERT (0 <= yystate && yystate < YYNSTATES);
  YY_IGNORE_USELESS_CAST_BEGIN
  *yyssp = YY_CAST (yy_state_t, yystate);
  YY_IGNORE_USELESS_CAST_END
  YY_STACK_PRINT (yyss, yyssp);

  if (yyss + yystacksize - 1 <= yyssp)
#if !defined yyoverflow && !defined YYSTACK_RELOCATE
    YYNOMEM;
#else
    {
      /* Get the current used size of the three stacks, in elements.  */
      YYPTRDIFF_T yysize = yyssp - yyss + 1;

# if defined yyoverflow
      {
        /* Give user a chance to reallocate the stack.  Use copies of
           these so that the &'s don't force the real ones into
           memory.  */
        yy_state_t *yyss1 = yyss;
        YYSTYPE *yyvs1 = yyvs;

        /* Each stack pointer address is followed by the size of the
           data in use in that stack, in bytes.  This used to be a
           conditional around just the two extra args, but that might
           be undefined if yyoverflow is a macro.  */
        yyoverflow (YY_("memory exhausted"),
                    &yyss1, yysize * YYSIZEOF (*yyssp),
                    &yyvs1, yysize * YYSIZEOF (*yyvsp),
                    &yystacksize);
        yyss = yyss1;
        yyvs = yyvs1;
      }
# else /* defined YYSTACK_RELOCATE */
      /* Extend the stack our own way.  */
      if (YYMAXDEPTH <= yystacksize)
        YYNOMEM;
      yystacksize *= 2;
      if (YYMAXDEPTH < yystacksize)
        yystacksize = YYMAXDEPTH;

      {
        yy_state_t *yyss1 = yyss;
        union yyalloc *yyptr =
          YY_CAST (union yyalloc *,
                   YYSTACK_ALLOC (YY_CAST (YYSIZE_T, YYSTACK_BYTES (yystacksize))));
        if (! yyptr)
          YYNOMEM;
        YYSTACK_RELOCATE (yyss_alloc, yyss);
        YYSTACK_RELOCATE (yyvs_alloc, yyvs);
#  undef YYSTACK_RELOCATE
        if (yyss1 != yyssa)
          YYSTACK_FREE (yyss1);
      }
# endif

      yyssp = yyss + yysize - 1;
      yyvsp = yyvs + yysize - 1;

      YY_IGNORE_USELESS_CAST_BEGIN
      YYDPRINTF ((stderr, "Stack size increased to %ld\n",
                  YY_CAST (long, yystacksize)));
      YY_IGNORE_USELESS_CAST_END

      if (yyss + yystacksize - 1 <= yyssp)
        YYABORT;
    }
#endif /* !defined yyoverflow && !defined YYSTACK_RELOCATE */


  if (yystate == YYFINAL)
    YYACCEPT;

  goto yybackup;


/*-----------.
| yybackup.  |
`-----------*/
yybackup:
  /* Do appropriate processing given the current state.  Read a
     lookahead token if we need one and don't already have one.  */

  /* First try to decide what to do without reference to lookahead token.  */
  yyn = yypact[yystate];
  if (yypact_value_is_default (yyn))
    goto yydefault;

  /* Not known => get a lookahead token if don't already have one.  */

  /* YYCHAR is either empty, or end-of-input, or a valid lookahead.  */
  if (yychar == YYEMPTY)
    {
      YYDPRINTF ((stderr, "Reading a token\n"));
      yychar = yylex ();
    }

  if (yychar <= YYEOF)
    {
      yychar = YYEOF;
      yytoken = YYSYMBOL_YYEOF;
      YYDPRINTF ((stderr, "Now at end of input.\n"));
    }
  else if (yychar == YYerror)
    {
      /* The scanner already issued an error message, process directly
         to error recovery.  But do not keep the error token as
         lookahead, it is too special and may lead us to an endless
         loop in error recovery. */
      yychar = YYUNDEF;
      yytoken = YYSYMBOL_YYerror;
      goto yyerrlab1;
    }
  else
    {
      yytoken = YYTRANSLATE (yychar);
      YY_SYMBOL_PRINT ("Next token is", yytoken, &yylval, &yylloc);
    }

  /* If the proper action on seeing token YYTOKEN is to reduce or to
     detect an error, take that action.  */
  yyn += yytoken;
  if (yyn < 0 || YYLAST < yyn || yycheck[yyn] != yytoken)
    goto yydefault;
  yyn = yytable[yyn];
  if (yyn <= 0)
    {
      if (yytable_value_is_error (yyn))
        goto yyerrlab;
      yyn = -yyn;
      goto yyreduce;
    }

  /* Count tokens shifted since error; after three, turn off error
     status.  */
  if (yyerrstatus)
    yyerrstatus--;

  /* Shift the lookahead token.  */
  YY_SYMBOL_PRINT ("Shifting", yytoken, &yylval, &yylloc);
  yystate = yyn;
  YY_IGNORE_MAYBE_UNINITIALIZED_BEGIN
  *++yyvsp = yylval;
  YY_IGNORE_MAYBE_UNINITIALIZED_END

  /* Discard the shifted token.  */
  yychar = YYEMPTY;
  goto yynewstate;


/*-----------------------------------------------------------.
| yydefault -- do the default action for the current state.  |
`-----------------------------------------------------------*/
yydefault:
  yyn = yydefact[yystate];
  if (yyn == 0)
    goto yyerrlab;
  goto yyreduce;


/*-----------------------------.
| yyreduce -- do a reduction.  |
`-----------------------------*/
yyreduce:
  /* yyn is the number of a rule to reduce with.  */
  yylen = yyr2[yyn];

  /* If YYLEN is nonzero, implement the default value of the action:
     '$$ = $1'.

     Otherwise, the following line sets YYVAL to garbage.
     This behavior is undocumented and Bison
     users should not rely upon it.  Assigning to YYVAL
     unconditionally makes the parser a bit smaller, and it avoids a
     GCC warning that YYVAL may be used uninitialized.  */
  yyval = yyvsp[1-yylen];


  YY_REDUCE_PRINT (yyn);
  switch (yyn)
    {
  case 2: /* decls: decl  */
#line 62 "dyn.y"
            { program.decls.push_back((yyvsp[0].stmt)); }
#line 1386 "parser.cc"
    break;

  case 3: /* decls: "pub" decl  */
#line 63 "dyn.y"
                     { program.pub_decls.push_back((yyvsp[-1].stmt)); }
#line 1392 "parser.cc"
    break;

  case 4: /* decls: decls decl  */
#line 64 "dyn.y"
                     { program.decls.push_back((yyvsp[0].stmt)); }
#line 1398 "parser.cc"
    break;

  case 5: /* decls: decls "pub" decl  */
#line 65 "dyn.y"
                           { program.pub_decls.push_back((yyvsp[0].stmt)); }
#line 1404 "parser.cc"
    break;

  case 12: /* var_decl: ident ident EQUAL expr SEMICOLON  */
#line 74 "dyn.y"
                                           { (yyval.var) = Variable(NULL, (yyvsp[-4].string), (yyvsp[-3].ident), (yyvsp[-1].expr)); }
#line 1410 "parser.cc"
    break;

  case 13: /* var_decl: "mut" ident ident SEMICOLON  */
#line 75 "dyn.y"
                                      { (yyval.var) = Variable((yyvsp[-3].string), (yyvsp[-2].ident), (yyvsp[-1].ident), NULL); }
#line 1416 "parser.cc"
    break;

  case 14: /* var_decl: "con" ident ident EQUAL expr SEMICOLON  */
#line 76 "dyn.y"
                                                 { (yyval.var) = Variable((yyvsp[-5].string), (yyvsp[-4].ident), (yyvsp[-3].ident), (yyvsp[-1].expr)); }
#line 1422 "parser.cc"
    break;

  case 15: /* var_decl: "mut" ident ident EQUAL expr SEMICOLON  */
#line 77 "dyn.y"
                                                 { (yyval.var) = Variable((yyvsp[-5].string), (yyvsp[-4].ident), (yyvsp[-3].ident), (yyvsp[-1].expr)); }
#line 1428 "parser.cc"
    break;

  case 16: /* func_decl: ident ident L_PAREN func_decl_args R_PAREN block  */
#line 80 "dyn.y"
        { (yyval.stmt) = Function((yyvsp[-5].ident), (yyvsp[-4].ident), (yyvsp[-2].vars), (yyvsp[0].block)); }
#line 1434 "parser.cc"
    break;

  case 17: /* func_decl: ident ident L_PAREN func_decl_args R_PAREN  */
#line 81 "dyn.y"
                                                     { (yyval.stmt) = Function((yyvsp[-4].ident), (yyvsp[-3].ident), (yyvsp[-1].vars), NULL);  }
#line 1440 "parser.cc"
    break;

  case 18: /* func_decl_args: %empty  */
#line 83 "dyn.y"
                       { (yyval.vars) = Variables(); }
#line 1446 "parser.cc"
    break;

  case 19: /* func_decl_args: var_decl  */
#line 84 "dyn.y"
                   { (yyval.vars) = Variables(); (yyval.vars).push_back((yyvsp[0].var)); }
#line 1452 "parser.cc"
    break;

  case 20: /* func_decl_args: func_decl_args COMMA var_decl  */
#line 85 "dyn.y"
                                        { (yyvsp[-2].vars).push_back((yyvsp[0].var)); }
#line 1458 "parser.cc"
    break;

  case 21: /* enum_decl: "enum" ident L_BRACE enum_fields R_BRACE  */
#line 87 "dyn.y"
                                                    { (yyval.stmt) = Enum((yyvsp[-3].ident), (yyvsp[-1].enum_members));  }
#line 1464 "parser.cc"
    break;

  case 22: /* enum_fields: ident  */
#line 89 "dyn.y"
                   { (yyval.enum_members) = {}; (yyval.enum_members).push_back(EnumMember((yyvsp[0].ident))); }
#line 1470 "parser.cc"
    break;

  case 23: /* enum_fields: enum_fields ident  */
#line 90 "dyn.y"
                            { (yyvsp[-1].enum_members).push_back(EnumMember((yyvsp[0].ident))); }
#line 1476 "parser.cc"
    break;

  case 24: /* enum_fields: ident L_PAREN enum_partners R_PAREN  */
#line 91 "dyn.y"
                                              { (yyval.enum_members) = EnumMembers(); (yyval.enum_members).push_back(EnumMember((yyvsp[-3].ident), (yyvsp[-2].token)));  }
#line 1482 "parser.cc"
    break;

  case 25: /* enum_fields: enum_fields ident enum_partners  */
#line 92 "dyn.y"
                                          { (yyvsp[-2].enum_members).push_back(EnumMember((yyvsp[-1].ident), (yyvsp[0].enum_partners)));  }
#line 1488 "parser.cc"
    break;

  case 26: /* enum_partners: ident  */
#line 94 "dyn.y"
                     { (yyval.enum_partners) = {}; (yyval.enum_partners).push_back((yyvsp[0].ident)); }
#line 1494 "parser.cc"
    break;

  case 27: /* enum_partners: enum_partners COMMA ident  */
#line 95 "dyn.y"
                                    { (yyvsp[-2].enum_partners).push_back((yyvsp[0].ident)); }
#line 1500 "parser.cc"
    break;

  case 28: /* struct_decl: "struct" ident L_BRACE struct_fields R_BRACE  */
#line 97 "dyn.y"
                                                          { (yyval.stmt) = Struct((yyvsp[-3].ident), (yyvsp[-2].token));  }
#line 1506 "parser.cc"
    break;

  case 29: /* struct_decl: "struct" ident COLON struct_inherits L_BRACE struct_fields R_BRACE  */
#line 98 "dyn.y"
                                                                             { (yyval.stmt) = Struct(); }
#line 1512 "parser.cc"
    break;

  case 30: /* struct_fields: %empty  */
#line 100 "dyn.y"
                      { (yyval.fields) = StructFields(); }
#line 1518 "parser.cc"
    break;

  case 31: /* struct_fields: var_decl  */
#line 101 "dyn.y"
                   { (yyval.fields) = StructFields(); (yyval.fields).vars.push_back((yyvsp[0].stmt)); }
#line 1524 "parser.cc"
    break;

  case 32: /* struct_fields: func_decl  */
#line 102 "dyn.y"
                    { (yyval.fields) = StructFields(); (yyval.fields).methods.push_back((yyvsp[0].stmt)); }
#line 1530 "parser.cc"
    break;

  case 33: /* struct_fields: struct_fields var_decl  */
#line 103 "dyn.y"
                                 { (yyvsp[-1].fields).variables.push_back((yyvsp[0].stmt)); }
#line 1536 "parser.cc"
    break;

  case 34: /* struct_fields: struct_fields func_decl  */
#line 104 "dyn.y"
                                  { (yyvsp[-1].fields).methods.push_back((yyvsp[0].stmt)); }
#line 1542 "parser.cc"
    break;

  case 35: /* struct_inherits: ident  */
#line 106 "dyn.y"
                       {(yyval.traits) = {}; (yyval.traits).push_back((yyvsp[0].ident)); }
#line 1548 "parser.cc"
    break;

  case 36: /* struct_inherits: struct_inherits COMMA ident  */
#line 107 "dyn.y"
                                      { (yyvsp[-2].traits).push_back((yyvsp[-1].ident)); }
#line 1554 "parser.cc"
    break;

  case 37: /* type_decl: "type" type_list  */
#line 109 "dyn.y"
                            { (yyval.stmt) = Type((yyvsp[0].type_list)); }
#line 1560 "parser.cc"
    break;

  case 38: /* type_list: ident  */
#line 111 "dyn.y"
                 { (yyval.type_list) = {}; (yyval.type_list).push_back((yyvsp[0].ident)); }
#line 1566 "parser.cc"
    break;

  case 39: /* type_list: type_list PIPE ident  */
#line 112 "dyn.y"
                               { (yyvsp[-2].type_list).push_back((yyvsp[-1].ident)); }
#line 1572 "parser.cc"
    break;

  case 40: /* stmts: %empty  */
#line 114 "dyn.y"
              { (yyval.block) = Block(); }
#line 1578 "parser.cc"
    break;

  case 41: /* stmts: stmt  */
#line 115 "dyn.y"
               { (yyval.block) = Block(); (yyval.block).s.push_back((yyvsp[0].stmt)); }
#line 1584 "parser.cc"
    break;

  case 42: /* stmts: stmts stmt  */
#line 116 "dyn.y"
                     { (yyvsp[-1].block).s.push_back((yyvsp[0].stmt)); }
#line 1590 "parser.cc"
    break;

  case 44: /* stmt: "if" boolean_expr L_BRACE block R_BRACE  */
#line 119 "dyn.y"
                                                  { (yyval.stmt) = If((yyvsp[-3].expr), (yyvsp[-1].block)); }
#line 1596 "parser.cc"
    break;

  case 45: /* stmt: "loop" block  */
#line 120 "dyn.y"
                       { (yyval.stmt) = Loop((yyvsp[0].block)); }
#line 1602 "parser.cc"
    break;

  case 46: /* stmt: "for" ident COLON expr L_BRACE block R_BRACE  */
#line 121 "dyn.y"
                                                       { (yyval.stmt) = For((yyvsp[-6].ident), (yyvsp[-3].expr), (yyvsp[-1].block)); }
#line 1608 "parser.cc"
    break;

  case 47: /* stmt: "match" ident L_BRACE match_branches R_BRACE  */
#line 122 "dyn.y"
                                                       { (yyval.stmt) = Match((yyvsp[-3].ident), (yyvsp[-1].match_branches)); }
#line 1614 "parser.cc"
    break;

  case 48: /* stmt: "return" expr SEMICOLON  */
#line 123 "dyn.y"
                                  { (yyval.stmt) = Return((yyvsp[-1].expr)); }
#line 1620 "parser.cc"
    break;

  case 49: /* stmt: "return" SEMICOLON  */
#line 124 "dyn.y"
                             { (yyval.stmt) = Return(); }
#line 1626 "parser.cc"
    break;

  case 50: /* stmt: "defer" expr SEMICOLON  */
#line 125 "dyn.y"
                                 { (yyval.stmt) = Defer((yyvsp[-1].expr)); }
#line 1632 "parser.cc"
    break;

  case 51: /* stmt: "break" SEMICOLON  */
#line 126 "dyn.y"
                            { (yyval.stmt) = Break(); }
#line 1638 "parser.cc"
    break;

  case 52: /* stmt: "continue" SEMICOLON  */
#line 127 "dyn.y"
                               { (yyval.stmt) = Continue(); }
#line 1644 "parser.cc"
    break;

  case 53: /* match_branches: %empty  */
#line 129 "dyn.y"
                       { (yyval.match_branches) = {}; }
#line 1650 "parser.cc"
    break;

  case 54: /* match_branches: match_branch  */
#line 130 "dyn.y"
                       { (yyval.match_branches) = {}; (yyval.match_branches).push_back((yyvsp[0].match_branch)); }
#line 1656 "parser.cc"
    break;

  case 55: /* match_branches: match_branches match_branch  */
#line 131 "dyn.y"
                                      { (yyvsp[-1].match_branches).push_back((yyvsp[0].match_branch)); }
#line 1662 "parser.cc"
    break;

  case 56: /* match_branch: expr COLON L_BRACE block R_BRACE  */
#line 133 "dyn.y"
                                               { (yyval.match_branch) = MatchBranch((yyvsp[-4].expr), (yyvsp[-1].block)); }
#line 1668 "parser.cc"
    break;

  case 57: /* match_branch: "_" COLON L_BRACE block R_BRACE  */
#line 134 "dyn.y"
                                          { (yyval.match_branch) = MatchBranch(NULL, (yyvsp[-1].block)); }
#line 1674 "parser.cc"
    break;

  case 58: /* block: L_BRACE stmts R_BRACE  */
#line 136 "dyn.y"
                             { (yyval.block) = (yyvsp[-1].block); }
#line 1680 "parser.cc"
    break;

  case 59: /* block: L_BRACE R_BRACE  */
#line 137 "dyn.y"
                          { (yyval.block) = Block(); }
#line 1686 "parser.cc"
    break;

  case 60: /* ident: IDENTIFIER  */
#line 139 "dyn.y"
                  { (yyval.ident) = Identifier((yyvsp[0].string));  }
#line 1692 "parser.cc"
    break;

  case 61: /* numeric: INTEGER  */
#line 141 "dyn.y"
                 { (yyval.expr) = Integer(atol((yyvsp[0].string).c_str()));  }
#line 1698 "parser.cc"
    break;

  case 62: /* numeric: DOUBLE  */
#line 142 "dyn.y"
                 { (yyval.expr) = Double(atof((yyvsp[0].string).c_str()));  }
#line 1704 "parser.cc"
    break;

  case 63: /* expr: ident EQUAL ident  */
#line 144 "dyn.y"
                        { (yyval.expr) = Assignment((yyvsp[-2].ident), (yyvsp[0].ident)); }
#line 1710 "parser.cc"
    break;

  case 64: /* expr: ident L_PAREN call_args R_PAREN  */
#line 145 "dyn.y"
                                          { (yyval.expr) = FunctionCall((yyvsp[-3].ident), (yyvsp[-1].exprs)); }
#line 1716 "parser.cc"
    break;

  case 65: /* expr: ident  */
#line 146 "dyn.y"
                { (yyval.ident) = (yyvsp[0].ident); }
#line 1722 "parser.cc"
    break;

  case 68: /* expr: crement expr  */
#line 149 "dyn.y"
                       {(yyval.expr) = UnaryOp((yyvsp[-1].token), (yyvsp[0].expr)); }
#line 1728 "parser.cc"
    break;

  case 69: /* expr: expr crement  */
#line 150 "dyn.y"
                       {(yyval.expr) = UnaryOp((yyvsp[0].token), (yyvsp[-1].expr)); }
#line 1734 "parser.cc"
    break;

  case 70: /* expr: uop expr  */
#line 151 "dyn.y"
                   { (yyval.expr) = UnaryOp((yyvsp[-1].token), (yyvsp[0].expr)); }
#line 1740 "parser.cc"
    break;

  case 71: /* expr: L_PAREN expr R_PAREN  */
#line 152 "dyn.y"
                               { (yyval.expr) = (yyvsp[-1].expr); }
#line 1746 "parser.cc"
    break;

  case 72: /* expr: expr mop expr  */
#line 153 "dyn.y"
                        { (yyval.expr) = (yyval.expr) = BinaryOp((yyvsp[-1].token), (yyvsp[-2].expr), (yyvsp[0].expr)); }
#line 1752 "parser.cc"
    break;

  case 75: /* call_args: %empty  */
#line 157 "dyn.y"
                  { (yyval.exprs) = {}; }
#line 1758 "parser.cc"
    break;

  case 76: /* call_args: ident  */
#line 158 "dyn.y"
                { (yyval.exprs) = Identifiers(); (yyval.exprs).push_back((yyvsp[0].ident)); }
#line 1764 "parser.cc"
    break;

  case 77: /* call_args: call_args COMMA ident  */
#line 159 "dyn.y"
                                { (yyvsp[-2].exprs).push_back((yyvsp[-1].ident)); }
#line 1770 "parser.cc"
    break;

  case 79: /* boolean_expr: boolean_expr lop boolean  */
#line 162 "dyn.y"
                                   { (yyval.expr) = BinaryOp((yyvsp[-1].token), (yyvsp[-2].expr), (yyvsp[-1].expr)); }
#line 1776 "parser.cc"
    break;

  case 80: /* boolean: expr comparison expr  */
#line 164 "dyn.y"
                              { (yyval.expr) = BinaryOp((yyvsp[-1].token), (yyvsp[-2].expr), (yyvsp[0].expr)); }
#line 1782 "parser.cc"
    break;

  case 81: /* boolean: L_PAREN expr comparison expr R_PAREN  */
#line 165 "dyn.y"
                                               { (yyval.expr) = BinaryOp((yyvsp[-3].expr), (yyvsp[-4].token), (yyvsp[-2].token)); }
#line 1788 "parser.cc"
    break;

  case 82: /* boolean: BANG boolean  */
#line 166 "dyn.y"
                       { (yyval.expr) = UnaryOp((yyvsp[-1].token), (yyvsp[0].expr)); }
#line 1794 "parser.cc"
    break;

  case 102: /* func_literal: ident L_PAREN func_decl_args R_PAREN block  */
#line 192 "dyn.y"
                                                         { (yyval.expr) = FunctionLiteral((yyvsp[-4].ident), (yyvsp[-2].vars), (yyvsp[0].block)); }
#line 1800 "parser.cc"
    break;

  case 103: /* struct_literal: "struct" L_BRACE struct_fields R_BRACE  */
#line 194 "dyn.y"
                                                       { (yyval.expr) = StructLiteral(); }
#line 1806 "parser.cc"
    break;

  case 104: /* struct_literal: "struct" COLON struct_inherits L_BRACE struct_fields R_BRACE  */
#line 195 "dyn.y"
                                                                       { (yyval.expr) = StructLiteral((yyvsp[-1].fields), (yyvsp[-3].traits)); }
#line 1812 "parser.cc"
    break;


#line 1816 "parser.cc"

      default: break;
    }
  /* User semantic actions sometimes alter yychar, and that requires
     that yytoken be updated with the new translation.  We take the
     approach of translating immediately before every use of yytoken.
     One alternative is translating here after every semantic action,
     but that translation would be missed if the semantic action invokes
     YYABORT, YYACCEPT, or YYERROR immediately after altering yychar or
     if it invokes YYBACKUP.  In the case of YYABORT or YYACCEPT, an
     incorrect destructor might then be invoked immediately.  In the
     case of YYERROR or YYBACKUP, subsequent parser actions might lead
     to an incorrect destructor call or verbose syntax error message
     before the lookahead is translated.  */
  YY_SYMBOL_PRINT ("-> $$ =", YY_CAST (yysymbol_kind_t, yyr1[yyn]), &yyval, &yyloc);

  YYPOPSTACK (yylen);
  yylen = 0;

  *++yyvsp = yyval;

  /* Now 'shift' the result of the reduction.  Determine what state
     that goes to, based on the state we popped back to and the rule
     number reduced by.  */
  {
    const int yylhs = yyr1[yyn] - YYNTOKENS;
    const int yyi = yypgoto[yylhs] + *yyssp;
    yystate = (0 <= yyi && yyi <= YYLAST && yycheck[yyi] == *yyssp
               ? yytable[yyi]
               : yydefgoto[yylhs]);
  }

  goto yynewstate;


/*--------------------------------------.
| yyerrlab -- here on detecting error.  |
`--------------------------------------*/
yyerrlab:
  /* Make sure we have latest lookahead translation.  See comments at
     user semantic actions for why this is necessary.  */
  yytoken = yychar == YYEMPTY ? YYSYMBOL_YYEMPTY : YYTRANSLATE (yychar);
  /* If not already recovering from an error, report this error.  */
  if (!yyerrstatus)
    {
      ++yynerrs;
      yyerror (YY_("syntax error"));
    }

  if (yyerrstatus == 3)
    {
      /* If just tried and failed to reuse lookahead token after an
         error, discard it.  */

      if (yychar <= YYEOF)
        {
          /* Return failure if at end of input.  */
          if (yychar == YYEOF)
            YYABORT;
        }
      else
        {
          yydestruct ("Error: discarding",
                      yytoken, &yylval);
          yychar = YYEMPTY;
        }
    }

  /* Else will try to reuse lookahead token after shifting the error
     token.  */
  goto yyerrlab1;


/*---------------------------------------------------.
| yyerrorlab -- error raised explicitly by YYERROR.  |
`---------------------------------------------------*/
yyerrorlab:
  /* Pacify compilers when the user code never invokes YYERROR and the
     label yyerrorlab therefore never appears in user code.  */
  if (0)
    YYERROR;
  ++yynerrs;

  /* Do not reclaim the symbols of the rule whose action triggered
     this YYERROR.  */
  YYPOPSTACK (yylen);
  yylen = 0;
  YY_STACK_PRINT (yyss, yyssp);
  yystate = *yyssp;
  goto yyerrlab1;


/*-------------------------------------------------------------.
| yyerrlab1 -- common code for both syntax error and YYERROR.  |
`-------------------------------------------------------------*/
yyerrlab1:
  yyerrstatus = 3;      /* Each real token shifted decrements this.  */

  /* Pop stack until we find a state that shifts the error token.  */
  for (;;)
    {
      yyn = yypact[yystate];
      if (!yypact_value_is_default (yyn))
        {
          yyn += YYSYMBOL_YYerror;
          if (0 <= yyn && yyn <= YYLAST && yycheck[yyn] == YYSYMBOL_YYerror)
            {
              yyn = yytable[yyn];
              if (0 < yyn)
                break;
            }
        }

      /* Pop the current state because it cannot handle the error token.  */
      if (yyssp == yyss)
        YYABORT;


      yydestruct ("Error: popping",
                  YY_ACCESSING_SYMBOL (yystate), yyvsp);
      YYPOPSTACK (1);
      yystate = *yyssp;
      YY_STACK_PRINT (yyss, yyssp);
    }

  YY_IGNORE_MAYBE_UNINITIALIZED_BEGIN
  *++yyvsp = yylval;
  YY_IGNORE_MAYBE_UNINITIALIZED_END


  /* Shift the error token.  */
  YY_SYMBOL_PRINT ("Shifting", YY_ACCESSING_SYMBOL (yyn), yyvsp, yylsp);

  yystate = yyn;
  goto yynewstate;


/*-------------------------------------.
| yyacceptlab -- YYACCEPT comes here.  |
`-------------------------------------*/
yyacceptlab:
  yyresult = 0;
  goto yyreturnlab;


/*-----------------------------------.
| yyabortlab -- YYABORT comes here.  |
`-----------------------------------*/
yyabortlab:
  yyresult = 1;
  goto yyreturnlab;


/*-----------------------------------------------------------.
| yyexhaustedlab -- YYNOMEM (memory exhaustion) comes here.  |
`-----------------------------------------------------------*/
yyexhaustedlab:
  yyerror (YY_("memory exhausted"));
  yyresult = 2;
  goto yyreturnlab;


/*----------------------------------------------------------.
| yyreturnlab -- parsing is finished, clean up and return.  |
`----------------------------------------------------------*/
yyreturnlab:
  if (yychar != YYEMPTY)
    {
      /* Make sure we have latest lookahead translation.  See comments at
         user semantic actions for why this is necessary.  */
      yytoken = YYTRANSLATE (yychar);
      yydestruct ("Cleanup: discarding lookahead",
                  yytoken, &yylval);
    }
  /* Do not reclaim the symbols of the rule whose action triggered
     this YYABORT or YYACCEPT.  */
  YYPOPSTACK (yylen);
  YY_STACK_PRINT (yyss, yyssp);
  while (yyssp != yyss)
    {
      yydestruct ("Cleanup: popping",
                  YY_ACCESSING_SYMBOL (+*yyssp), yyvsp);
      YYPOPSTACK (1);
    }
#ifndef yyoverflow
  if (yyss != yyssa)
    YYSTACK_FREE (yyss);
#endif

  return yyresult;
}

