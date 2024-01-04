// A Bison parser, made by GNU Bison 3.8.2.

// Skeleton implementation for Bison LALR(1) parsers in C++

// Copyright (C) 2002-2015, 2018-2021 Free Software Foundation, Inc.

// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.

// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.

// As a special exception, you may create a larger work that contains
// part or all of the Bison parser skeleton and distribute that work
// under terms of your choice, so long as that work isn't itself a
// parser generator using the skeleton or a modified version thereof
// as a parser skeleton.  Alternatively, if you modify or redistribute
// the parser skeleton itself, you may (at your option) remove this
// special exception, which will cause the skeleton and the resulting
// Bison output files to be licensed under the GNU General Public
// License without this special exception.

// This special exception was added by the Free Software Foundation in
// version 2.2 of Bison.

// DO NOT RELY ON FEATURES THAT ARE NOT DOCUMENTED in the manual,
// especially those whose name start with YY_ or yy_.  They are
// private implementation details that can be changed or removed.



// First part of user prologue.
#line 1 "dyn.y"

  #include "ast.h"
  extern int yylex();
  void yyerror(const char *s) { printf("Error: %s", s); }

#line 47 "parser.cc"



# include <cassert>
# include <cstdlib> // std::abort
# include <iostream>
# include <stdexcept>
# include <string>
# include <vector>

#if defined __cplusplus
# define YY_CPLUSPLUS __cplusplus
#else
# define YY_CPLUSPLUS 199711L
#endif

// Support move semantics when possible.
#if 201103L <= YY_CPLUSPLUS
# define YY_MOVE           std::move
# define YY_MOVE_OR_COPY   move
# define YY_MOVE_REF(Type) Type&&
# define YY_RVREF(Type)    Type&&
# define YY_COPY(Type)     Type
#else
# define YY_MOVE
# define YY_MOVE_OR_COPY   copy
# define YY_MOVE_REF(Type) Type&
# define YY_RVREF(Type)    const Type&
# define YY_COPY(Type)     const Type&
#endif

// Support noexcept when possible.
#if 201103L <= YY_CPLUSPLUS
# define YY_NOEXCEPT noexcept
# define YY_NOTHROW
#else
# define YY_NOEXCEPT
# define YY_NOTHROW throw ()
#endif

// Support constexpr when possible.
#if 201703 <= YY_CPLUSPLUS
# define YY_CONSTEXPR constexpr
#else
# define YY_CONSTEXPR
#endif

#include <typeinfo>
#ifndef YY_ASSERT
# include <cassert>
# define YY_ASSERT assert
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

/* Debug traces.  */
#ifndef YYDEBUG
# define YYDEBUG 0
#endif

namespace yy {
#line 189 "parser.cc"




  /// A Bison parser.
  class parser
  {
  public:
#ifdef YYSTYPE
# ifdef __GNUC__
#  pragma GCC message "bison: do not #define YYSTYPE in C++, use %define api.value.type"
# endif
    typedef YYSTYPE value_type;
#else
  /// A buffer to store and retrieve objects.
  ///
  /// Sort of a variant, but does not keep track of the nature
  /// of the stored data, since that knowledge is available
  /// via the current parser state.
  class value_type
  {
  public:
    /// Type of *this.
    typedef value_type self_type;

    /// Empty construction.
    value_type () YY_NOEXCEPT
      : yyraw_ ()
      , yytypeid_ (YY_NULLPTR)
    {}

    /// Construct and fill.
    template <typename T>
    value_type (YY_RVREF (T) t)
      : yytypeid_ (&typeid (T))
    {
      YY_ASSERT (sizeof (T) <= size);
      new (yyas_<T> ()) T (YY_MOVE (t));
    }

#if 201103L <= YY_CPLUSPLUS
    /// Non copyable.
    value_type (const self_type&) = delete;
    /// Non copyable.
    self_type& operator= (const self_type&) = delete;
#endif

    /// Destruction, allowed only if empty.
    ~value_type () YY_NOEXCEPT
    {
      YY_ASSERT (!yytypeid_);
    }

# if 201103L <= YY_CPLUSPLUS
    /// Instantiate a \a T in here from \a t.
    template <typename T, typename... U>
    T&
    emplace (U&&... u)
    {
      YY_ASSERT (!yytypeid_);
      YY_ASSERT (sizeof (T) <= size);
      yytypeid_ = & typeid (T);
      return *new (yyas_<T> ()) T (std::forward <U>(u)...);
    }
# else
    /// Instantiate an empty \a T in here.
    template <typename T>
    T&
    emplace ()
    {
      YY_ASSERT (!yytypeid_);
      YY_ASSERT (sizeof (T) <= size);
      yytypeid_ = & typeid (T);
      return *new (yyas_<T> ()) T ();
    }

    /// Instantiate a \a T in here from \a t.
    template <typename T>
    T&
    emplace (const T& t)
    {
      YY_ASSERT (!yytypeid_);
      YY_ASSERT (sizeof (T) <= size);
      yytypeid_ = & typeid (T);
      return *new (yyas_<T> ()) T (t);
    }
# endif

    /// Instantiate an empty \a T in here.
    /// Obsolete, use emplace.
    template <typename T>
    T&
    build ()
    {
      return emplace<T> ();
    }

    /// Instantiate a \a T in here from \a t.
    /// Obsolete, use emplace.
    template <typename T>
    T&
    build (const T& t)
    {
      return emplace<T> (t);
    }

    /// Accessor to a built \a T.
    template <typename T>
    T&
    as () YY_NOEXCEPT
    {
      YY_ASSERT (yytypeid_);
      YY_ASSERT (*yytypeid_ == typeid (T));
      YY_ASSERT (sizeof (T) <= size);
      return *yyas_<T> ();
    }

    /// Const accessor to a built \a T (for %printer).
    template <typename T>
    const T&
    as () const YY_NOEXCEPT
    {
      YY_ASSERT (yytypeid_);
      YY_ASSERT (*yytypeid_ == typeid (T));
      YY_ASSERT (sizeof (T) <= size);
      return *yyas_<T> ();
    }

    /// Swap the content with \a that, of same type.
    ///
    /// Both variants must be built beforehand, because swapping the actual
    /// data requires reading it (with as()), and this is not possible on
    /// unconstructed variants: it would require some dynamic testing, which
    /// should not be the variant's responsibility.
    /// Swapping between built and (possibly) non-built is done with
    /// self_type::move ().
    template <typename T>
    void
    swap (self_type& that) YY_NOEXCEPT
    {
      YY_ASSERT (yytypeid_);
      YY_ASSERT (*yytypeid_ == *that.yytypeid_);
      std::swap (as<T> (), that.as<T> ());
    }

    /// Move the content of \a that to this.
    ///
    /// Destroys \a that.
    template <typename T>
    void
    move (self_type& that)
    {
# if 201103L <= YY_CPLUSPLUS
      emplace<T> (std::move (that.as<T> ()));
# else
      emplace<T> ();
      swap<T> (that);
# endif
      that.destroy<T> ();
    }

# if 201103L <= YY_CPLUSPLUS
    /// Move the content of \a that to this.
    template <typename T>
    void
    move (self_type&& that)
    {
      emplace<T> (std::move (that.as<T> ()));
      that.destroy<T> ();
    }
#endif

    /// Copy the content of \a that to this.
    template <typename T>
    void
    copy (const self_type& that)
    {
      emplace<T> (that.as<T> ());
    }

    /// Destroy the stored \a T.
    template <typename T>
    void
    destroy ()
    {
      as<T> ().~T ();
      yytypeid_ = YY_NULLPTR;
    }

  private:
#if YY_CPLUSPLUS < 201103L
    /// Non copyable.
    value_type (const self_type&);
    /// Non copyable.
    self_type& operator= (const self_type&);
#endif

    /// Accessor to raw memory as \a T.
    template <typename T>
    T*
    yyas_ () YY_NOEXCEPT
    {
      void *yyp = yyraw_;
      return static_cast<T*> (yyp);
     }

    /// Const accessor to raw memory as \a T.
    template <typename T>
    const T*
    yyas_ () const YY_NOEXCEPT
    {
      const void *yyp = yyraw_;
      return static_cast<const T*> (yyp);
     }

    /// An auxiliary type to compute the largest semantic type.
    union union_type
    {
      // block
      // expr
      // ident
      // number
      char dummy1[sizeof (Expression)];

      // decl
      // enum_decl
      // fn_decl
      // var_decl
      // stmts
      // stmt
      char dummy2[sizeof (Statement)];

      // SEMICOLON
      // EQUAL
      // L_BRACE
      // R_BRACE
      // L_PAREN
      // R_PAREN
      // COMMA
      char dummy3[sizeof (int)];

      // INT
      // DOUB
      // IDENT
      char dummy4[sizeof (std::string)];

      // enum_members
      char dummy5[sizeof (std::vector<EnumMember>)];

      // partners
      char dummy6[sizeof (std::vector<Identifier>)];

      // fn_args
      char dummy7[sizeof (std::vector<Variable>)];
    };

    /// The size of the largest semantic type.
    enum { size = sizeof (union_type) };

    /// A buffer to store semantic values.
    union
    {
      /// Strongest alignment constraints.
      long double yyalign_me_;
      /// A buffer large enough to store any of the semantic values.
      char yyraw_[size];
    };

    /// Whether the content is built: if defined, the name of the stored type.
    const std::type_info *yytypeid_;
  };

#endif
    /// Backward compatibility (Bison 3.8).
    typedef value_type semantic_type;


    /// Syntax errors thrown from user actions.
    struct syntax_error : std::runtime_error
    {
      syntax_error (const std::string& m)
        : std::runtime_error (m)
      {}

      syntax_error (const syntax_error& s)
        : std::runtime_error (s.what ())
      {}

      ~syntax_error () YY_NOEXCEPT YY_NOTHROW;
    };

    /// Token kinds.
    struct token
    {
      enum token_kind_type
      {
        YYEMPTY = -2,
    YYEOF = 0,                     // "end of file"
    YYerror = 256,                 // error
    YYUNDEF = 257,                 // "invalid token"
    SEMICOLON = 258,               // SEMICOLON
    EQUAL = 259,                   // EQUAL
    L_BRACE = 260,                 // L_BRACE
    R_BRACE = 261,                 // R_BRACE
    L_PAREN = 262,                 // L_PAREN
    R_PAREN = 263,                 // R_PAREN
    COMMA = 264,                   // COMMA
    INT = 265,                     // INT
    DOUB = 266,                    // DOUB
    IDENT = 267                    // IDENT
      };
      /// Backward compatibility alias (Bison 3.6).
      typedef token_kind_type yytokentype;
    };

    /// Token kind, as returned by yylex.
    typedef token::token_kind_type token_kind_type;

    /// Backward compatibility alias (Bison 3.6).
    typedef token_kind_type token_type;

    /// Symbol kinds.
    struct symbol_kind
    {
      enum symbol_kind_type
      {
        YYNTOKENS = 17, ///< Number of tokens.
        S_YYEMPTY = -2,
        S_YYEOF = 0,                             // "end of file"
        S_YYerror = 1,                           // error
        S_YYUNDEF = 2,                           // "invalid token"
        S_SEMICOLON = 3,                         // SEMICOLON
        S_EQUAL = 4,                             // EQUAL
        S_L_BRACE = 5,                           // L_BRACE
        S_R_BRACE = 6,                           // R_BRACE
        S_L_PAREN = 7,                           // L_PAREN
        S_R_PAREN = 8,                           // R_PAREN
        S_COMMA = 9,                             // COMMA
        S_INT = 10,                              // INT
        S_DOUB = 11,                             // DOUB
        S_IDENT = 12,                            // IDENT
        S_13_pub_ = 13,                          // "pub"
        S_14_enum_ = 14,                         // "enum"
        S_15_mut_ = 15,                          // "mut"
        S_16_con_ = 16,                          // "con"
        S_YYACCEPT = 17,                         // $accept
        S_decls = 18,                            // decls
        S_decl = 19,                             // decl
        S_enum_decl = 20,                        // enum_decl
        S_enum_members = 21,                     // enum_members
        S_partners = 22,                         // partners
        S_fn_decl = 23,                          // fn_decl
        S_fn_args = 24,                          // fn_args
        S_var_decl = 25,                         // var_decl
        S_stmts = 26,                            // stmts
        S_stmt = 27,                             // stmt
        S_block = 28,                            // block
        S_expr = 29,                             // expr
        S_ident = 30,                            // ident
        S_number = 31                            // number
      };
    };

    /// (Internal) symbol kind.
    typedef symbol_kind::symbol_kind_type symbol_kind_type;

    /// The number of tokens.
    static const symbol_kind_type YYNTOKENS = symbol_kind::YYNTOKENS;

    /// A complete symbol.
    ///
    /// Expects its Base type to provide access to the symbol kind
    /// via kind ().
    ///
    /// Provide access to semantic value.
    template <typename Base>
    struct basic_symbol : Base
    {
      /// Alias to Base.
      typedef Base super_type;

      /// Default constructor.
      basic_symbol () YY_NOEXCEPT
        : value ()
      {}

#if 201103L <= YY_CPLUSPLUS
      /// Move constructor.
      basic_symbol (basic_symbol&& that)
        : Base (std::move (that))
        , value ()
      {
        switch (this->kind ())
    {
      case symbol_kind::S_block: // block
      case symbol_kind::S_expr: // expr
      case symbol_kind::S_ident: // ident
      case symbol_kind::S_number: // number
        value.move< Expression > (std::move (that.value));
        break;

      case symbol_kind::S_decl: // decl
      case symbol_kind::S_enum_decl: // enum_decl
      case symbol_kind::S_fn_decl: // fn_decl
      case symbol_kind::S_var_decl: // var_decl
      case symbol_kind::S_stmts: // stmts
      case symbol_kind::S_stmt: // stmt
        value.move< Statement > (std::move (that.value));
        break;

      case symbol_kind::S_SEMICOLON: // SEMICOLON
      case symbol_kind::S_EQUAL: // EQUAL
      case symbol_kind::S_L_BRACE: // L_BRACE
      case symbol_kind::S_R_BRACE: // R_BRACE
      case symbol_kind::S_L_PAREN: // L_PAREN
      case symbol_kind::S_R_PAREN: // R_PAREN
      case symbol_kind::S_COMMA: // COMMA
        value.move< int > (std::move (that.value));
        break;

      case symbol_kind::S_INT: // INT
      case symbol_kind::S_DOUB: // DOUB
      case symbol_kind::S_IDENT: // IDENT
        value.move< std::string > (std::move (that.value));
        break;

      case symbol_kind::S_enum_members: // enum_members
        value.move< std::vector<EnumMember> > (std::move (that.value));
        break;

      case symbol_kind::S_partners: // partners
        value.move< std::vector<Identifier> > (std::move (that.value));
        break;

      case symbol_kind::S_fn_args: // fn_args
        value.move< std::vector<Variable> > (std::move (that.value));
        break;

      default:
        break;
    }

      }
#endif

      /// Copy constructor.
      basic_symbol (const basic_symbol& that);

      /// Constructors for typed symbols.
#if 201103L <= YY_CPLUSPLUS
      basic_symbol (typename Base::kind_type t)
        : Base (t)
      {}
#else
      basic_symbol (typename Base::kind_type t)
        : Base (t)
      {}
#endif

#if 201103L <= YY_CPLUSPLUS
      basic_symbol (typename Base::kind_type t, Expression&& v)
        : Base (t)
        , value (std::move (v))
      {}
#else
      basic_symbol (typename Base::kind_type t, const Expression& v)
        : Base (t)
        , value (v)
      {}
#endif

#if 201103L <= YY_CPLUSPLUS
      basic_symbol (typename Base::kind_type t, Statement&& v)
        : Base (t)
        , value (std::move (v))
      {}
#else
      basic_symbol (typename Base::kind_type t, const Statement& v)
        : Base (t)
        , value (v)
      {}
#endif

#if 201103L <= YY_CPLUSPLUS
      basic_symbol (typename Base::kind_type t, int&& v)
        : Base (t)
        , value (std::move (v))
      {}
#else
      basic_symbol (typename Base::kind_type t, const int& v)
        : Base (t)
        , value (v)
      {}
#endif

#if 201103L <= YY_CPLUSPLUS
      basic_symbol (typename Base::kind_type t, std::string&& v)
        : Base (t)
        , value (std::move (v))
      {}
#else
      basic_symbol (typename Base::kind_type t, const std::string& v)
        : Base (t)
        , value (v)
      {}
#endif

#if 201103L <= YY_CPLUSPLUS
      basic_symbol (typename Base::kind_type t, std::vector<EnumMember>&& v)
        : Base (t)
        , value (std::move (v))
      {}
#else
      basic_symbol (typename Base::kind_type t, const std::vector<EnumMember>& v)
        : Base (t)
        , value (v)
      {}
#endif

#if 201103L <= YY_CPLUSPLUS
      basic_symbol (typename Base::kind_type t, std::vector<Identifier>&& v)
        : Base (t)
        , value (std::move (v))
      {}
#else
      basic_symbol (typename Base::kind_type t, const std::vector<Identifier>& v)
        : Base (t)
        , value (v)
      {}
#endif

#if 201103L <= YY_CPLUSPLUS
      basic_symbol (typename Base::kind_type t, std::vector<Variable>&& v)
        : Base (t)
        , value (std::move (v))
      {}
#else
      basic_symbol (typename Base::kind_type t, const std::vector<Variable>& v)
        : Base (t)
        , value (v)
      {}
#endif

      /// Destroy the symbol.
      ~basic_symbol ()
      {
        clear ();
      }



      /// Destroy contents, and record that is empty.
      void clear () YY_NOEXCEPT
      {
        // User destructor.
        symbol_kind_type yykind = this->kind ();
        basic_symbol<Base>& yysym = *this;
        (void) yysym;
        switch (yykind)
        {
       default:
          break;
        }

        // Value type destructor.
switch (yykind)
    {
      case symbol_kind::S_block: // block
      case symbol_kind::S_expr: // expr
      case symbol_kind::S_ident: // ident
      case symbol_kind::S_number: // number
        value.template destroy< Expression > ();
        break;

      case symbol_kind::S_decl: // decl
      case symbol_kind::S_enum_decl: // enum_decl
      case symbol_kind::S_fn_decl: // fn_decl
      case symbol_kind::S_var_decl: // var_decl
      case symbol_kind::S_stmts: // stmts
      case symbol_kind::S_stmt: // stmt
        value.template destroy< Statement > ();
        break;

      case symbol_kind::S_SEMICOLON: // SEMICOLON
      case symbol_kind::S_EQUAL: // EQUAL
      case symbol_kind::S_L_BRACE: // L_BRACE
      case symbol_kind::S_R_BRACE: // R_BRACE
      case symbol_kind::S_L_PAREN: // L_PAREN
      case symbol_kind::S_R_PAREN: // R_PAREN
      case symbol_kind::S_COMMA: // COMMA
        value.template destroy< int > ();
        break;

      case symbol_kind::S_INT: // INT
      case symbol_kind::S_DOUB: // DOUB
      case symbol_kind::S_IDENT: // IDENT
        value.template destroy< std::string > ();
        break;

      case symbol_kind::S_enum_members: // enum_members
        value.template destroy< std::vector<EnumMember> > ();
        break;

      case symbol_kind::S_partners: // partners
        value.template destroy< std::vector<Identifier> > ();
        break;

      case symbol_kind::S_fn_args: // fn_args
        value.template destroy< std::vector<Variable> > ();
        break;

      default:
        break;
    }

        Base::clear ();
      }

#if YYDEBUG || 0
      /// The user-facing name of this symbol.
      const char *name () const YY_NOEXCEPT
      {
        return parser::symbol_name (this->kind ());
      }
#endif // #if YYDEBUG || 0


      /// Backward compatibility (Bison 3.6).
      symbol_kind_type type_get () const YY_NOEXCEPT;

      /// Whether empty.
      bool empty () const YY_NOEXCEPT;

      /// Destructive move, \a s is emptied into this.
      void move (basic_symbol& s);

      /// The semantic value.
      value_type value;

    private:
#if YY_CPLUSPLUS < 201103L
      /// Assignment operator.
      basic_symbol& operator= (const basic_symbol& that);
#endif
    };

    /// Type access provider for token (enum) based symbols.
    struct by_kind
    {
      /// The symbol kind as needed by the constructor.
      typedef token_kind_type kind_type;

      /// Default constructor.
      by_kind () YY_NOEXCEPT;

#if 201103L <= YY_CPLUSPLUS
      /// Move constructor.
      by_kind (by_kind&& that) YY_NOEXCEPT;
#endif

      /// Copy constructor.
      by_kind (const by_kind& that) YY_NOEXCEPT;

      /// Constructor from (external) token numbers.
      by_kind (kind_type t) YY_NOEXCEPT;



      /// Record that this symbol is empty.
      void clear () YY_NOEXCEPT;

      /// Steal the symbol kind from \a that.
      void move (by_kind& that);

      /// The (internal) type number (corresponding to \a type).
      /// \a empty when empty.
      symbol_kind_type kind () const YY_NOEXCEPT;

      /// Backward compatibility (Bison 3.6).
      symbol_kind_type type_get () const YY_NOEXCEPT;

      /// The symbol kind.
      /// \a S_YYEMPTY when empty.
      symbol_kind_type kind_;
    };

    /// Backward compatibility for a private implementation detail (Bison 3.6).
    typedef by_kind by_type;

    /// "External" symbols: returned by the scanner.
    struct symbol_type : basic_symbol<by_kind>
    {
      /// Superclass.
      typedef basic_symbol<by_kind> super_type;

      /// Empty symbol.
      symbol_type () YY_NOEXCEPT {}

      /// Constructor for valueless symbols, and symbols from each type.
#if 201103L <= YY_CPLUSPLUS
      symbol_type (int tok)
        : super_type (token_kind_type (tok))
#else
      symbol_type (int tok)
        : super_type (token_kind_type (tok))
#endif
      {
#if !defined _MSC_VER || defined __clang__
        YY_ASSERT (tok == token::YYEOF
                   || (token::YYerror <= tok && tok <= token::YYUNDEF)
                   || (268 <= tok && tok <= 271));
#endif
      }
#if 201103L <= YY_CPLUSPLUS
      symbol_type (int tok, int v)
        : super_type (token_kind_type (tok), std::move (v))
#else
      symbol_type (int tok, const int& v)
        : super_type (token_kind_type (tok), v)
#endif
      {
#if !defined _MSC_VER || defined __clang__
        YY_ASSERT ((token::SEMICOLON <= tok && tok <= token::COMMA));
#endif
      }
#if 201103L <= YY_CPLUSPLUS
      symbol_type (int tok, std::string v)
        : super_type (token_kind_type (tok), std::move (v))
#else
      symbol_type (int tok, const std::string& v)
        : super_type (token_kind_type (tok), v)
#endif
      {
#if !defined _MSC_VER || defined __clang__
        YY_ASSERT ((token::INT <= tok && tok <= token::IDENT));
#endif
      }
    };

    /// Build a parser object.
    parser ();
    virtual ~parser ();

#if 201103L <= YY_CPLUSPLUS
    /// Non copyable.
    parser (const parser&) = delete;
    /// Non copyable.
    parser& operator= (const parser&) = delete;
#endif

    /// Parse.  An alias for parse ().
    /// \returns  0 iff parsing succeeded.
    int operator() ();

    /// Parse.
    /// \returns  0 iff parsing succeeded.
    virtual int parse ();

#if YYDEBUG
    /// The current debugging stream.
    std::ostream& debug_stream () const YY_ATTRIBUTE_PURE;
    /// Set the current debugging stream.
    void set_debug_stream (std::ostream &);

    /// Type for debugging levels.
    typedef int debug_level_type;
    /// The current debugging level.
    debug_level_type debug_level () const YY_ATTRIBUTE_PURE;
    /// Set the current debugging level.
    void set_debug_level (debug_level_type l);
#endif

    /// Report a syntax error.
    /// \param msg    a description of the syntax error.
    virtual void error (const std::string& msg);

    /// Report a syntax error.
    void error (const syntax_error& err);

#if YYDEBUG || 0
    /// The user-facing name of the symbol whose (internal) number is
    /// YYSYMBOL.  No bounds checking.
    static const char *symbol_name (symbol_kind_type yysymbol);
#endif // #if YYDEBUG || 0


    // Implementation of make_symbol for each token kind.
#if 201103L <= YY_CPLUSPLUS
      static
      symbol_type
      make_YYEOF ()
      {
        return symbol_type (token::YYEOF);
      }
#else
      static
      symbol_type
      make_YYEOF ()
      {
        return symbol_type (token::YYEOF);
      }
#endif
#if 201103L <= YY_CPLUSPLUS
      static
      symbol_type
      make_YYerror ()
      {
        return symbol_type (token::YYerror);
      }
#else
      static
      symbol_type
      make_YYerror ()
      {
        return symbol_type (token::YYerror);
      }
#endif
#if 201103L <= YY_CPLUSPLUS
      static
      symbol_type
      make_YYUNDEF ()
      {
        return symbol_type (token::YYUNDEF);
      }
#else
      static
      symbol_type
      make_YYUNDEF ()
      {
        return symbol_type (token::YYUNDEF);
      }
#endif
#if 201103L <= YY_CPLUSPLUS
      static
      symbol_type
      make_SEMICOLON (int v)
      {
        return symbol_type (token::SEMICOLON, std::move (v));
      }
#else
      static
      symbol_type
      make_SEMICOLON (const int& v)
      {
        return symbol_type (token::SEMICOLON, v);
      }
#endif
#if 201103L <= YY_CPLUSPLUS
      static
      symbol_type
      make_EQUAL (int v)
      {
        return symbol_type (token::EQUAL, std::move (v));
      }
#else
      static
      symbol_type
      make_EQUAL (const int& v)
      {
        return symbol_type (token::EQUAL, v);
      }
#endif
#if 201103L <= YY_CPLUSPLUS
      static
      symbol_type
      make_L_BRACE (int v)
      {
        return symbol_type (token::L_BRACE, std::move (v));
      }
#else
      static
      symbol_type
      make_L_BRACE (const int& v)
      {
        return symbol_type (token::L_BRACE, v);
      }
#endif
#if 201103L <= YY_CPLUSPLUS
      static
      symbol_type
      make_R_BRACE (int v)
      {
        return symbol_type (token::R_BRACE, std::move (v));
      }
#else
      static
      symbol_type
      make_R_BRACE (const int& v)
      {
        return symbol_type (token::R_BRACE, v);
      }
#endif
#if 201103L <= YY_CPLUSPLUS
      static
      symbol_type
      make_L_PAREN (int v)
      {
        return symbol_type (token::L_PAREN, std::move (v));
      }
#else
      static
      symbol_type
      make_L_PAREN (const int& v)
      {
        return symbol_type (token::L_PAREN, v);
      }
#endif
#if 201103L <= YY_CPLUSPLUS
      static
      symbol_type
      make_R_PAREN (int v)
      {
        return symbol_type (token::R_PAREN, std::move (v));
      }
#else
      static
      symbol_type
      make_R_PAREN (const int& v)
      {
        return symbol_type (token::R_PAREN, v);
      }
#endif
#if 201103L <= YY_CPLUSPLUS
      static
      symbol_type
      make_COMMA (int v)
      {
        return symbol_type (token::COMMA, std::move (v));
      }
#else
      static
      symbol_type
      make_COMMA (const int& v)
      {
        return symbol_type (token::COMMA, v);
      }
#endif
#if 201103L <= YY_CPLUSPLUS
      static
      symbol_type
      make_INT (std::string v)
      {
        return symbol_type (token::INT, std::move (v));
      }
#else
      static
      symbol_type
      make_INT (const std::string& v)
      {
        return symbol_type (token::INT, v);
      }
#endif
#if 201103L <= YY_CPLUSPLUS
      static
      symbol_type
      make_DOUB (std::string v)
      {
        return symbol_type (token::DOUB, std::move (v));
      }
#else
      static
      symbol_type
      make_DOUB (const std::string& v)
      {
        return symbol_type (token::DOUB, v);
      }
#endif
#if 201103L <= YY_CPLUSPLUS
      static
      symbol_type
      make_IDENT (std::string v)
      {
        return symbol_type (token::IDENT, std::move (v));
      }
#else
      static
      symbol_type
      make_IDENT (const std::string& v)
      {
        return symbol_type (token::IDENT, v);
      }
#endif


  private:
#if YY_CPLUSPLUS < 201103L
    /// Non copyable.
    parser (const parser&);
    /// Non copyable.
    parser& operator= (const parser&);
#endif


    /// Stored state numbers (used for stacks).
    typedef signed char state_type;

    /// Compute post-reduction state.
    /// \param yystate   the current state
    /// \param yysym     the nonterminal to push on the stack
    static state_type yy_lr_goto_state_ (state_type yystate, int yysym);

    /// Whether the given \c yypact_ value indicates a defaulted state.
    /// \param yyvalue   the value to check
    static bool yy_pact_value_is_default_ (int yyvalue) YY_NOEXCEPT;

    /// Whether the given \c yytable_ value indicates a syntax error.
    /// \param yyvalue   the value to check
    static bool yy_table_value_is_error_ (int yyvalue) YY_NOEXCEPT;

    static const signed char yypact_ninf_;
    static const signed char yytable_ninf_;

    /// Convert a scanner token kind \a t to a symbol kind.
    /// In theory \a t should be a token_kind_type, but character literals
    /// are valid, yet not members of the token_kind_type enum.
    static symbol_kind_type yytranslate_ (int t) YY_NOEXCEPT;

#if YYDEBUG || 0
    /// For a symbol, its name in clear.
    static const char* const yytname_[];
#endif // #if YYDEBUG || 0


    // Tables.
    // YYPACT[STATE-NUM] -- Index in YYTABLE of the portion describing
    // STATE-NUM.
    static const signed char yypact_[];

    // YYDEFACT[STATE-NUM] -- Default reduction number in state STATE-NUM.
    // Performed when YYTABLE does not specify something else to do.  Zero
    // means the default is an error.
    static const signed char yydefact_[];

    // YYPGOTO[NTERM-NUM].
    static const signed char yypgoto_[];

    // YYDEFGOTO[NTERM-NUM].
    static const signed char yydefgoto_[];

    // YYTABLE[YYPACT[STATE-NUM]] -- What to do in state STATE-NUM.  If
    // positive, shift that token.  If negative, reduce the rule whose
    // number is the opposite.  If YYTABLE_NINF, syntax error.
    static const signed char yytable_[];

    static const signed char yycheck_[];

    // YYSTOS[STATE-NUM] -- The symbol kind of the accessing symbol of
    // state STATE-NUM.
    static const signed char yystos_[];

    // YYR1[RULE-NUM] -- Symbol kind of the left-hand side of rule RULE-NUM.
    static const signed char yyr1_[];

    // YYR2[RULE-NUM] -- Number of symbols on the right-hand side of rule RULE-NUM.
    static const signed char yyr2_[];


#if YYDEBUG
    // YYRLINE[YYN] -- Source line where rule number YYN was defined.
    static const signed char yyrline_[];
    /// Report on the debug stream that the rule \a r is going to be reduced.
    virtual void yy_reduce_print_ (int r) const;
    /// Print the state stack on the debug stream.
    virtual void yy_stack_print_ () const;

    /// Debugging level.
    int yydebug_;
    /// Debug stream.
    std::ostream* yycdebug_;

    /// \brief Display a symbol kind, value and location.
    /// \param yyo    The output stream.
    /// \param yysym  The symbol.
    template <typename Base>
    void yy_print_ (std::ostream& yyo, const basic_symbol<Base>& yysym) const;
#endif

    /// \brief Reclaim the memory associated to a symbol.
    /// \param yymsg     Why this token is reclaimed.
    ///                  If null, print nothing.
    /// \param yysym     The symbol.
    template <typename Base>
    void yy_destroy_ (const char* yymsg, basic_symbol<Base>& yysym) const;

  private:
    /// Type access provider for state based symbols.
    struct by_state
    {
      /// Default constructor.
      by_state () YY_NOEXCEPT;

      /// The symbol kind as needed by the constructor.
      typedef state_type kind_type;

      /// Constructor.
      by_state (kind_type s) YY_NOEXCEPT;

      /// Copy constructor.
      by_state (const by_state& that) YY_NOEXCEPT;

      /// Record that this symbol is empty.
      void clear () YY_NOEXCEPT;

      /// Steal the symbol kind from \a that.
      void move (by_state& that);

      /// The symbol kind (corresponding to \a state).
      /// \a symbol_kind::S_YYEMPTY when empty.
      symbol_kind_type kind () const YY_NOEXCEPT;

      /// The state number used to denote an empty symbol.
      /// We use the initial state, as it does not have a value.
      enum { empty_state = 0 };

      /// The state.
      /// \a empty when empty.
      state_type state;
    };

    /// "Internal" symbol: element of the stack.
    struct stack_symbol_type : basic_symbol<by_state>
    {
      /// Superclass.
      typedef basic_symbol<by_state> super_type;
      /// Construct an empty symbol.
      stack_symbol_type ();
      /// Move or copy construction.
      stack_symbol_type (YY_RVREF (stack_symbol_type) that);
      /// Steal the contents from \a sym to build this.
      stack_symbol_type (state_type s, YY_MOVE_REF (symbol_type) sym);
#if YY_CPLUSPLUS < 201103L
      /// Assignment, needed by push_back by some old implementations.
      /// Moves the contents of that.
      stack_symbol_type& operator= (stack_symbol_type& that);

      /// Assignment, needed by push_back by other implementations.
      /// Needed by some other old implementations.
      stack_symbol_type& operator= (const stack_symbol_type& that);
#endif
    };

    /// A stack with random access from its top.
    template <typename T, typename S = std::vector<T> >
    class stack
    {
    public:
      // Hide our reversed order.
      typedef typename S::iterator iterator;
      typedef typename S::const_iterator const_iterator;
      typedef typename S::size_type size_type;
      typedef typename std::ptrdiff_t index_type;

      stack (size_type n = 200) YY_NOEXCEPT
        : seq_ (n)
      {}

#if 201103L <= YY_CPLUSPLUS
      /// Non copyable.
      stack (const stack&) = delete;
      /// Non copyable.
      stack& operator= (const stack&) = delete;
#endif

      /// Random access.
      ///
      /// Index 0 returns the topmost element.
      const T&
      operator[] (index_type i) const
      {
        return seq_[size_type (size () - 1 - i)];
      }

      /// Random access.
      ///
      /// Index 0 returns the topmost element.
      T&
      operator[] (index_type i)
      {
        return seq_[size_type (size () - 1 - i)];
      }

      /// Steal the contents of \a t.
      ///
      /// Close to move-semantics.
      void
      push (YY_MOVE_REF (T) t)
      {
        seq_.push_back (T ());
        operator[] (0).move (t);
      }

      /// Pop elements from the stack.
      void
      pop (std::ptrdiff_t n = 1) YY_NOEXCEPT
      {
        for (; 0 < n; --n)
          seq_.pop_back ();
      }

      /// Pop all elements from the stack.
      void
      clear () YY_NOEXCEPT
      {
        seq_.clear ();
      }

      /// Number of elements on the stack.
      index_type
      size () const YY_NOEXCEPT
      {
        return index_type (seq_.size ());
      }

      /// Iterator on top of the stack (going downwards).
      const_iterator
      begin () const YY_NOEXCEPT
      {
        return seq_.begin ();
      }

      /// Bottom of the stack.
      const_iterator
      end () const YY_NOEXCEPT
      {
        return seq_.end ();
      }

      /// Present a slice of the top of a stack.
      class slice
      {
      public:
        slice (const stack& stack, index_type range) YY_NOEXCEPT
          : stack_ (stack)
          , range_ (range)
        {}

        const T&
        operator[] (index_type i) const
        {
          return stack_[range_ - i];
        }

      private:
        const stack& stack_;
        index_type range_;
      };

    private:
#if YY_CPLUSPLUS < 201103L
      /// Non copyable.
      stack (const stack&);
      /// Non copyable.
      stack& operator= (const stack&);
#endif
      /// The wrapped container.
      S seq_;
    };


    /// Stack type.
    typedef stack<stack_symbol_type> stack_type;

    /// The stack.
    stack_type yystack_;

    /// Push a new state on the stack.
    /// \param m    a debug message to display
    ///             if null, no trace is output.
    /// \param sym  the symbol
    /// \warning the contents of \a s.value is stolen.
    void yypush_ (const char* m, YY_MOVE_REF (stack_symbol_type) sym);

    /// Push a new look ahead token on the state on the stack.
    /// \param m    a debug message to display
    ///             if null, no trace is output.
    /// \param s    the state
    /// \param sym  the symbol (for its value and location).
    /// \warning the contents of \a sym.value is stolen.
    void yypush_ (const char* m, state_type s, YY_MOVE_REF (symbol_type) sym);

    /// Pop \a n symbols from the stack.
    void yypop_ (int n = 1) YY_NOEXCEPT;

    /// Constants.
    enum
    {
      yylast_ = 67,     ///< Last index in yytable_.
      yynnts_ = 15,  ///< Number of nonterminal symbols.
      yyfinal_ = 16 ///< Termination state number.
    };



  };


} // yy
#line 1487 "parser.cc"








#ifndef YY_
# if defined YYENABLE_NLS && YYENABLE_NLS
#  if ENABLE_NLS
#   include <libintl.h> // FIXME: INFRINGES ON USER NAME SPACE.
#   define YY_(msgid) dgettext ("bison-runtime", msgid)
#  endif
# endif
# ifndef YY_
#  define YY_(msgid) msgid
# endif
#endif


// Whether we are compiled with exception support.
#ifndef YY_EXCEPTIONS
# if defined __GNUC__ && !defined __EXCEPTIONS
#  define YY_EXCEPTIONS 0
# else
#  define YY_EXCEPTIONS 1
# endif
#endif



// Enable debugging if requested.
#if YYDEBUG

// A pseudo ostream that takes yydebug_ into account.
# define YYCDEBUG if (yydebug_) (*yycdebug_)

# define YY_SYMBOL_PRINT(Title, Symbol)         \
  do {                                          \
    if (yydebug_)                               \
    {                                           \
      *yycdebug_ << Title << ' ';               \
      yy_print_ (*yycdebug_, Symbol);           \
      *yycdebug_ << '\n';                       \
    }                                           \
  } while (false)

# define YY_REDUCE_PRINT(Rule)          \
  do {                                  \
    if (yydebug_)                       \
      yy_reduce_print_ (Rule);          \
  } while (false)

# define YY_STACK_PRINT()               \
  do {                                  \
    if (yydebug_)                       \
      yy_stack_print_ ();                \
  } while (false)

#else // !YYDEBUG

# define YYCDEBUG if (false) std::cerr
# define YY_SYMBOL_PRINT(Title, Symbol)  YY_USE (Symbol)
# define YY_REDUCE_PRINT(Rule)           static_cast<void> (0)
# define YY_STACK_PRINT()                static_cast<void> (0)

#endif // !YYDEBUG

#define yyerrok         (yyerrstatus_ = 0)
#define yyclearin       (yyla.clear ())

#define YYACCEPT        goto yyacceptlab
#define YYABORT         goto yyabortlab
#define YYERROR         goto yyerrorlab
#define YYRECOVERING()  (!!yyerrstatus_)

namespace yy {
#line 1566 "parser.cc"

  /// Build a parser object.
  parser::parser ()
#if YYDEBUG
    : yydebug_ (false),
      yycdebug_ (&std::cerr)
#else

#endif
  {}

  parser::~parser ()
  {}

  parser::syntax_error::~syntax_error () YY_NOEXCEPT YY_NOTHROW
  {}

  /*---------.
  | symbol.  |
  `---------*/

  // basic_symbol.
  template <typename Base>
  parser::basic_symbol<Base>::basic_symbol (const basic_symbol& that)
    : Base (that)
    , value ()
  {
    switch (this->kind ())
    {
      case symbol_kind::S_block: // block
      case symbol_kind::S_expr: // expr
      case symbol_kind::S_ident: // ident
      case symbol_kind::S_number: // number
        value.copy< Expression > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_decl: // decl
      case symbol_kind::S_enum_decl: // enum_decl
      case symbol_kind::S_fn_decl: // fn_decl
      case symbol_kind::S_var_decl: // var_decl
      case symbol_kind::S_stmts: // stmts
      case symbol_kind::S_stmt: // stmt
        value.copy< Statement > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_SEMICOLON: // SEMICOLON
      case symbol_kind::S_EQUAL: // EQUAL
      case symbol_kind::S_L_BRACE: // L_BRACE
      case symbol_kind::S_R_BRACE: // R_BRACE
      case symbol_kind::S_L_PAREN: // L_PAREN
      case symbol_kind::S_R_PAREN: // R_PAREN
      case symbol_kind::S_COMMA: // COMMA
        value.copy< int > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_INT: // INT
      case symbol_kind::S_DOUB: // DOUB
      case symbol_kind::S_IDENT: // IDENT
        value.copy< std::string > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_enum_members: // enum_members
        value.copy< std::vector<EnumMember> > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_partners: // partners
        value.copy< std::vector<Identifier> > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_fn_args: // fn_args
        value.copy< std::vector<Variable> > (YY_MOVE (that.value));
        break;

      default:
        break;
    }

  }




  template <typename Base>
  parser::symbol_kind_type
  parser::basic_symbol<Base>::type_get () const YY_NOEXCEPT
  {
    return this->kind ();
  }


  template <typename Base>
  bool
  parser::basic_symbol<Base>::empty () const YY_NOEXCEPT
  {
    return this->kind () == symbol_kind::S_YYEMPTY;
  }

  template <typename Base>
  void
  parser::basic_symbol<Base>::move (basic_symbol& s)
  {
    super_type::move (s);
    switch (this->kind ())
    {
      case symbol_kind::S_block: // block
      case symbol_kind::S_expr: // expr
      case symbol_kind::S_ident: // ident
      case symbol_kind::S_number: // number
        value.move< Expression > (YY_MOVE (s.value));
        break;

      case symbol_kind::S_decl: // decl
      case symbol_kind::S_enum_decl: // enum_decl
      case symbol_kind::S_fn_decl: // fn_decl
      case symbol_kind::S_var_decl: // var_decl
      case symbol_kind::S_stmts: // stmts
      case symbol_kind::S_stmt: // stmt
        value.move< Statement > (YY_MOVE (s.value));
        break;

      case symbol_kind::S_SEMICOLON: // SEMICOLON
      case symbol_kind::S_EQUAL: // EQUAL
      case symbol_kind::S_L_BRACE: // L_BRACE
      case symbol_kind::S_R_BRACE: // R_BRACE
      case symbol_kind::S_L_PAREN: // L_PAREN
      case symbol_kind::S_R_PAREN: // R_PAREN
      case symbol_kind::S_COMMA: // COMMA
        value.move< int > (YY_MOVE (s.value));
        break;

      case symbol_kind::S_INT: // INT
      case symbol_kind::S_DOUB: // DOUB
      case symbol_kind::S_IDENT: // IDENT
        value.move< std::string > (YY_MOVE (s.value));
        break;

      case symbol_kind::S_enum_members: // enum_members
        value.move< std::vector<EnumMember> > (YY_MOVE (s.value));
        break;

      case symbol_kind::S_partners: // partners
        value.move< std::vector<Identifier> > (YY_MOVE (s.value));
        break;

      case symbol_kind::S_fn_args: // fn_args
        value.move< std::vector<Variable> > (YY_MOVE (s.value));
        break;

      default:
        break;
    }

  }

  // by_kind.
  parser::by_kind::by_kind () YY_NOEXCEPT
    : kind_ (symbol_kind::S_YYEMPTY)
  {}

#if 201103L <= YY_CPLUSPLUS
  parser::by_kind::by_kind (by_kind&& that) YY_NOEXCEPT
    : kind_ (that.kind_)
  {
    that.clear ();
  }
#endif

  parser::by_kind::by_kind (const by_kind& that) YY_NOEXCEPT
    : kind_ (that.kind_)
  {}

  parser::by_kind::by_kind (token_kind_type t) YY_NOEXCEPT
    : kind_ (yytranslate_ (t))
  {}



  void
  parser::by_kind::clear () YY_NOEXCEPT
  {
    kind_ = symbol_kind::S_YYEMPTY;
  }

  void
  parser::by_kind::move (by_kind& that)
  {
    kind_ = that.kind_;
    that.clear ();
  }

  parser::symbol_kind_type
  parser::by_kind::kind () const YY_NOEXCEPT
  {
    return kind_;
  }


  parser::symbol_kind_type
  parser::by_kind::type_get () const YY_NOEXCEPT
  {
    return this->kind ();
  }



  // by_state.
  parser::by_state::by_state () YY_NOEXCEPT
    : state (empty_state)
  {}

  parser::by_state::by_state (const by_state& that) YY_NOEXCEPT
    : state (that.state)
  {}

  void
  parser::by_state::clear () YY_NOEXCEPT
  {
    state = empty_state;
  }

  void
  parser::by_state::move (by_state& that)
  {
    state = that.state;
    that.clear ();
  }

  parser::by_state::by_state (state_type s) YY_NOEXCEPT
    : state (s)
  {}

  parser::symbol_kind_type
  parser::by_state::kind () const YY_NOEXCEPT
  {
    if (state == empty_state)
      return symbol_kind::S_YYEMPTY;
    else
      return YY_CAST (symbol_kind_type, yystos_[+state]);
  }

  parser::stack_symbol_type::stack_symbol_type ()
  {}

  parser::stack_symbol_type::stack_symbol_type (YY_RVREF (stack_symbol_type) that)
    : super_type (YY_MOVE (that.state))
  {
    switch (that.kind ())
    {
      case symbol_kind::S_block: // block
      case symbol_kind::S_expr: // expr
      case symbol_kind::S_ident: // ident
      case symbol_kind::S_number: // number
        value.YY_MOVE_OR_COPY< Expression > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_decl: // decl
      case symbol_kind::S_enum_decl: // enum_decl
      case symbol_kind::S_fn_decl: // fn_decl
      case symbol_kind::S_var_decl: // var_decl
      case symbol_kind::S_stmts: // stmts
      case symbol_kind::S_stmt: // stmt
        value.YY_MOVE_OR_COPY< Statement > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_SEMICOLON: // SEMICOLON
      case symbol_kind::S_EQUAL: // EQUAL
      case symbol_kind::S_L_BRACE: // L_BRACE
      case symbol_kind::S_R_BRACE: // R_BRACE
      case symbol_kind::S_L_PAREN: // L_PAREN
      case symbol_kind::S_R_PAREN: // R_PAREN
      case symbol_kind::S_COMMA: // COMMA
        value.YY_MOVE_OR_COPY< int > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_INT: // INT
      case symbol_kind::S_DOUB: // DOUB
      case symbol_kind::S_IDENT: // IDENT
        value.YY_MOVE_OR_COPY< std::string > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_enum_members: // enum_members
        value.YY_MOVE_OR_COPY< std::vector<EnumMember> > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_partners: // partners
        value.YY_MOVE_OR_COPY< std::vector<Identifier> > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_fn_args: // fn_args
        value.YY_MOVE_OR_COPY< std::vector<Variable> > (YY_MOVE (that.value));
        break;

      default:
        break;
    }

#if 201103L <= YY_CPLUSPLUS
    // that is emptied.
    that.state = empty_state;
#endif
  }

  parser::stack_symbol_type::stack_symbol_type (state_type s, YY_MOVE_REF (symbol_type) that)
    : super_type (s)
  {
    switch (that.kind ())
    {
      case symbol_kind::S_block: // block
      case symbol_kind::S_expr: // expr
      case symbol_kind::S_ident: // ident
      case symbol_kind::S_number: // number
        value.move< Expression > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_decl: // decl
      case symbol_kind::S_enum_decl: // enum_decl
      case symbol_kind::S_fn_decl: // fn_decl
      case symbol_kind::S_var_decl: // var_decl
      case symbol_kind::S_stmts: // stmts
      case symbol_kind::S_stmt: // stmt
        value.move< Statement > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_SEMICOLON: // SEMICOLON
      case symbol_kind::S_EQUAL: // EQUAL
      case symbol_kind::S_L_BRACE: // L_BRACE
      case symbol_kind::S_R_BRACE: // R_BRACE
      case symbol_kind::S_L_PAREN: // L_PAREN
      case symbol_kind::S_R_PAREN: // R_PAREN
      case symbol_kind::S_COMMA: // COMMA
        value.move< int > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_INT: // INT
      case symbol_kind::S_DOUB: // DOUB
      case symbol_kind::S_IDENT: // IDENT
        value.move< std::string > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_enum_members: // enum_members
        value.move< std::vector<EnumMember> > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_partners: // partners
        value.move< std::vector<Identifier> > (YY_MOVE (that.value));
        break;

      case symbol_kind::S_fn_args: // fn_args
        value.move< std::vector<Variable> > (YY_MOVE (that.value));
        break;

      default:
        break;
    }

    // that is emptied.
    that.kind_ = symbol_kind::S_YYEMPTY;
  }

#if YY_CPLUSPLUS < 201103L
  parser::stack_symbol_type&
  parser::stack_symbol_type::operator= (const stack_symbol_type& that)
  {
    state = that.state;
    switch (that.kind ())
    {
      case symbol_kind::S_block: // block
      case symbol_kind::S_expr: // expr
      case symbol_kind::S_ident: // ident
      case symbol_kind::S_number: // number
        value.copy< Expression > (that.value);
        break;

      case symbol_kind::S_decl: // decl
      case symbol_kind::S_enum_decl: // enum_decl
      case symbol_kind::S_fn_decl: // fn_decl
      case symbol_kind::S_var_decl: // var_decl
      case symbol_kind::S_stmts: // stmts
      case symbol_kind::S_stmt: // stmt
        value.copy< Statement > (that.value);
        break;

      case symbol_kind::S_SEMICOLON: // SEMICOLON
      case symbol_kind::S_EQUAL: // EQUAL
      case symbol_kind::S_L_BRACE: // L_BRACE
      case symbol_kind::S_R_BRACE: // R_BRACE
      case symbol_kind::S_L_PAREN: // L_PAREN
      case symbol_kind::S_R_PAREN: // R_PAREN
      case symbol_kind::S_COMMA: // COMMA
        value.copy< int > (that.value);
        break;

      case symbol_kind::S_INT: // INT
      case symbol_kind::S_DOUB: // DOUB
      case symbol_kind::S_IDENT: // IDENT
        value.copy< std::string > (that.value);
        break;

      case symbol_kind::S_enum_members: // enum_members
        value.copy< std::vector<EnumMember> > (that.value);
        break;

      case symbol_kind::S_partners: // partners
        value.copy< std::vector<Identifier> > (that.value);
        break;

      case symbol_kind::S_fn_args: // fn_args
        value.copy< std::vector<Variable> > (that.value);
        break;

      default:
        break;
    }

    return *this;
  }

  parser::stack_symbol_type&
  parser::stack_symbol_type::operator= (stack_symbol_type& that)
  {
    state = that.state;
    switch (that.kind ())
    {
      case symbol_kind::S_block: // block
      case symbol_kind::S_expr: // expr
      case symbol_kind::S_ident: // ident
      case symbol_kind::S_number: // number
        value.move< Expression > (that.value);
        break;

      case symbol_kind::S_decl: // decl
      case symbol_kind::S_enum_decl: // enum_decl
      case symbol_kind::S_fn_decl: // fn_decl
      case symbol_kind::S_var_decl: // var_decl
      case symbol_kind::S_stmts: // stmts
      case symbol_kind::S_stmt: // stmt
        value.move< Statement > (that.value);
        break;

      case symbol_kind::S_SEMICOLON: // SEMICOLON
      case symbol_kind::S_EQUAL: // EQUAL
      case symbol_kind::S_L_BRACE: // L_BRACE
      case symbol_kind::S_R_BRACE: // R_BRACE
      case symbol_kind::S_L_PAREN: // L_PAREN
      case symbol_kind::S_R_PAREN: // R_PAREN
      case symbol_kind::S_COMMA: // COMMA
        value.move< int > (that.value);
        break;

      case symbol_kind::S_INT: // INT
      case symbol_kind::S_DOUB: // DOUB
      case symbol_kind::S_IDENT: // IDENT
        value.move< std::string > (that.value);
        break;

      case symbol_kind::S_enum_members: // enum_members
        value.move< std::vector<EnumMember> > (that.value);
        break;

      case symbol_kind::S_partners: // partners
        value.move< std::vector<Identifier> > (that.value);
        break;

      case symbol_kind::S_fn_args: // fn_args
        value.move< std::vector<Variable> > (that.value);
        break;

      default:
        break;
    }

    // that is emptied.
    that.state = empty_state;
    return *this;
  }
#endif

  template <typename Base>
  void
  parser::yy_destroy_ (const char* yymsg, basic_symbol<Base>& yysym) const
  {
    if (yymsg)
      YY_SYMBOL_PRINT (yymsg, yysym);
  }

#if YYDEBUG
  template <typename Base>
  void
  parser::yy_print_ (std::ostream& yyo, const basic_symbol<Base>& yysym) const
  {
    std::ostream& yyoutput = yyo;
    YY_USE (yyoutput);
    if (yysym.empty ())
      yyo << "empty symbol";
    else
      {
        symbol_kind_type yykind = yysym.kind ();
        yyo << (yykind < YYNTOKENS ? "token" : "nterm")
            << ' ' << yysym.name () << " (";
        YY_USE (yykind);
        yyo << ')';
      }
  }
#endif

  void
  parser::yypush_ (const char* m, YY_MOVE_REF (stack_symbol_type) sym)
  {
    if (m)
      YY_SYMBOL_PRINT (m, sym);
    yystack_.push (YY_MOVE (sym));
  }

  void
  parser::yypush_ (const char* m, state_type s, YY_MOVE_REF (symbol_type) sym)
  {
#if 201103L <= YY_CPLUSPLUS
    yypush_ (m, stack_symbol_type (s, std::move (sym)));
#else
    stack_symbol_type ss (s, sym);
    yypush_ (m, ss);
#endif
  }

  void
  parser::yypop_ (int n) YY_NOEXCEPT
  {
    yystack_.pop (n);
  }

#if YYDEBUG
  std::ostream&
  parser::debug_stream () const
  {
    return *yycdebug_;
  }

  void
  parser::set_debug_stream (std::ostream& o)
  {
    yycdebug_ = &o;
  }


  parser::debug_level_type
  parser::debug_level () const
  {
    return yydebug_;
  }

  void
  parser::set_debug_level (debug_level_type l)
  {
    yydebug_ = l;
  }
#endif // YYDEBUG

  parser::state_type
  parser::yy_lr_goto_state_ (state_type yystate, int yysym)
  {
    int yyr = yypgoto_[yysym - YYNTOKENS] + yystate;
    if (0 <= yyr && yyr <= yylast_ && yycheck_[yyr] == yystate)
      return yytable_[yyr];
    else
      return yydefgoto_[yysym - YYNTOKENS];
  }

  bool
  parser::yy_pact_value_is_default_ (int yyvalue) YY_NOEXCEPT
  {
    return yyvalue == yypact_ninf_;
  }

  bool
  parser::yy_table_value_is_error_ (int yyvalue) YY_NOEXCEPT
  {
    return yyvalue == yytable_ninf_;
  }

  int
  parser::operator() ()
  {
    return parse ();
  }

  int
  parser::parse ()
  {
    int yyn;
    /// Length of the RHS of the rule being reduced.
    int yylen = 0;

    // Error handling.
    int yynerrs_ = 0;
    int yyerrstatus_ = 0;

    /// The lookahead symbol.
    symbol_type yyla;

    /// The return value of parse ().
    int yyresult;

#if YY_EXCEPTIONS
    try
#endif // YY_EXCEPTIONS
      {
    YYCDEBUG << "Starting parse\n";


    /* Initialize the stack.  The initial state will be set in
       yynewstate, since the latter expects the semantical and the
       location values to have been already stored, initialize these
       stacks with a primary value.  */
    yystack_.clear ();
    yypush_ (YY_NULLPTR, 0, YY_MOVE (yyla));

  /*-----------------------------------------------.
  | yynewstate -- push a new symbol on the stack.  |
  `-----------------------------------------------*/
  yynewstate:
    YYCDEBUG << "Entering state " << int (yystack_[0].state) << '\n';
    YY_STACK_PRINT ();

    // Accept?
    if (yystack_[0].state == yyfinal_)
      YYACCEPT;

    goto yybackup;


  /*-----------.
  | yybackup.  |
  `-----------*/
  yybackup:
    // Try to take a decision without lookahead.
    yyn = yypact_[+yystack_[0].state];
    if (yy_pact_value_is_default_ (yyn))
      goto yydefault;

    // Read a lookahead token.
    if (yyla.empty ())
      {
        YYCDEBUG << "Reading a token\n";
#if YY_EXCEPTIONS
        try
#endif // YY_EXCEPTIONS
          {
            yyla.kind_ = yytranslate_ (yylex (&yyla.value));
          }
#if YY_EXCEPTIONS
        catch (const syntax_error& yyexc)
          {
            YYCDEBUG << "Caught exception: " << yyexc.what() << '\n';
            error (yyexc);
            goto yyerrlab1;
          }
#endif // YY_EXCEPTIONS
      }
    YY_SYMBOL_PRINT ("Next token is", yyla);

    if (yyla.kind () == symbol_kind::S_YYerror)
    {
      // The scanner already issued an error message, process directly
      // to error recovery.  But do not keep the error token as
      // lookahead, it is too special and may lead us to an endless
      // loop in error recovery. */
      yyla.kind_ = symbol_kind::S_YYUNDEF;
      goto yyerrlab1;
    }

    /* If the proper action on seeing token YYLA.TYPE is to reduce or
       to detect an error, take that action.  */
    yyn += yyla.kind ();
    if (yyn < 0 || yylast_ < yyn || yycheck_[yyn] != yyla.kind ())
      {
        goto yydefault;
      }

    // Reduce or error.
    yyn = yytable_[yyn];
    if (yyn <= 0)
      {
        if (yy_table_value_is_error_ (yyn))
          goto yyerrlab;
        yyn = -yyn;
        goto yyreduce;
      }

    // Count tokens shifted since error; after three, turn off error status.
    if (yyerrstatus_)
      --yyerrstatus_;

    // Shift the lookahead token.
    yypush_ ("Shifting", state_type (yyn), YY_MOVE (yyla));
    goto yynewstate;


  /*-----------------------------------------------------------.
  | yydefault -- do the default action for the current state.  |
  `-----------------------------------------------------------*/
  yydefault:
    yyn = yydefact_[+yystack_[0].state];
    if (yyn == 0)
      goto yyerrlab;
    goto yyreduce;


  /*-----------------------------.
  | yyreduce -- do a reduction.  |
  `-----------------------------*/
  yyreduce:
    yylen = yyr2_[yyn];
    {
      stack_symbol_type yylhs;
      yylhs.state = yy_lr_goto_state_ (yystack_[yylen].state, yyr1_[yyn]);
      /* Variants are always initialized to an empty instance of the
         correct type. The default '$$ = $1' action is NOT applied
         when using variants.  */
      switch (yyr1_[yyn])
    {
      case symbol_kind::S_block: // block
      case symbol_kind::S_expr: // expr
      case symbol_kind::S_ident: // ident
      case symbol_kind::S_number: // number
        yylhs.value.emplace< Expression > ();
        break;

      case symbol_kind::S_decl: // decl
      case symbol_kind::S_enum_decl: // enum_decl
      case symbol_kind::S_fn_decl: // fn_decl
      case symbol_kind::S_var_decl: // var_decl
      case symbol_kind::S_stmts: // stmts
      case symbol_kind::S_stmt: // stmt
        yylhs.value.emplace< Statement > ();
        break;

      case symbol_kind::S_SEMICOLON: // SEMICOLON
      case symbol_kind::S_EQUAL: // EQUAL
      case symbol_kind::S_L_BRACE: // L_BRACE
      case symbol_kind::S_R_BRACE: // R_BRACE
      case symbol_kind::S_L_PAREN: // L_PAREN
      case symbol_kind::S_R_PAREN: // R_PAREN
      case symbol_kind::S_COMMA: // COMMA
        yylhs.value.emplace< int > ();
        break;

      case symbol_kind::S_INT: // INT
      case symbol_kind::S_DOUB: // DOUB
      case symbol_kind::S_IDENT: // IDENT
        yylhs.value.emplace< std::string > ();
        break;

      case symbol_kind::S_enum_members: // enum_members
        yylhs.value.emplace< std::vector<EnumMember> > ();
        break;

      case symbol_kind::S_partners: // partners
        yylhs.value.emplace< std::vector<Identifier> > ();
        break;

      case symbol_kind::S_fn_args: // fn_args
        yylhs.value.emplace< std::vector<Variable> > ();
        break;

      default:
        break;
    }



      // Perform the reduction.
      YY_REDUCE_PRINT (yyn);
#if YY_EXCEPTIONS
      try
#endif // YY_EXCEPTIONS
        {
          switch (yyn)
            {
  case 5: // decl: var_decl SEMICOLON
#line 33 "dyn.y"
      { yylhs.value.as < Statement > () = yystack_[1].value.as < Statement > (); }
#line 2348 "parser.cc"
    break;

  case 6: // decl: fn_decl
#line 34 "dyn.y"
      { yylhs.value.as < Statement > () = yystack_[0].value.as < Statement > (); }
#line 2354 "parser.cc"
    break;

  case 7: // decl: enum_decl
#line 35 "dyn.y"
      { yylhs.value.as < Statement > () = yystack_[0].value.as < Statement > (); }
#line 2360 "parser.cc"
    break;

  case 8: // enum_decl: "enum" ident L_BRACE enum_members R_BRACE
#line 37 "dyn.y"
                                                     { yylhs.value.as< Enum > () = Enum(yystack_[3].value.as< Identifier > (), yystack_[3].value.as < Expression > ()); }
#line 2366 "parser.cc"
    break;

  case 9: // enum_members: ident
#line 39 "dyn.y"
                    { yylhs.value.as < std::vector<EnumMember> > () = {}; yylhs.value.as < std::vector<EnumMember> > ().push_back(EnumMember(yystack_[0].value.as < Expression > ())); }
#line 2372 "parser.cc"
    break;

  case 10: // enum_members: ident L_PAREN partners R_PAREN
#line 40 "dyn.y"
                                             { yylhs.value.as < std::vector<EnumMember> > () = {}; yylhs.value.as < std::vector<EnumMember> > ().push_back(EnumMember(yystack_[3].value.as < Expression > (), yystack_[2].value.as < int > ())); }
#line 2378 "parser.cc"
    break;

  case 11: // enum_members: enum_members ident
#line 41 "dyn.y"
                                 { yystack_[1].value.as < std::vector<EnumMember> > ().push_back(EnumMember(yystack_[0].value.as < Expression > ())); }
#line 2384 "parser.cc"
    break;

  case 12: // enum_members: enum_members ident L_PAREN partners R_PAREN
#line 42 "dyn.y"
                                                          { yystack_[4].value.as < std::vector<EnumMember> > ().push_back(EnumMember(yystack_[3].value.as < Expression > (), yystack_[2].value.as < int > ())); }
#line 2390 "parser.cc"
    break;

  case 13: // partners: ident
#line 44 "dyn.y"
                { yylhs.value.as < std::vector<Identifier> > () = {}; yylhs.value.as < std::vector<Identifier> > ().push_back(yystack_[0].value.as < Expression > ()); }
#line 2396 "parser.cc"
    break;

  case 14: // partners: partners COMMA ident
#line 45 "dyn.y"
                               { yystack_[2].value.as < std::vector<Identifier> > ().push_back(yystack_[1].value.as < int > ()); }
#line 2402 "parser.cc"
    break;

  case 15: // fn_decl: ident ident L_PAREN fn_args R_PAREN block
#line 47 "dyn.y"
                                                   { yylhs.value.as< Function > () = Function(yystack_[5].value.as < Expression > (), yystack_[4].value.as < Expression > (), ); }
#line 2408 "parser.cc"
    break;

  case 16: // fn_args: %empty
#line 49 "dyn.y"
         { yylhs.value.as< std::Vector<Variable > () = {}; }
#line 2414 "parser.cc"
    break;

  case 17: // fn_args: var_decl
#line 50 "dyn.y"
                  { yylhs.value.as< std::Vector<Variable > () = {}; yylhs.value.as < std::vector<Variable> > ().push_back(yystack_[0].value.as< Variable > ())}
#line 2420 "parser.cc"
    break;

  case 18: // fn_args: fn_args COMMA var_decl
#line 51 "dyn.y"
                                { yystack_[2].value.as< std::Vector<Variable > ().push_back(yystack_[1].value.as< Variable > ())}
#line 2426 "parser.cc"
    break;

  case 19: // var_decl: "mut" ident ident
#line 53 "dyn.y"
                            { yylhs.value.as < Statement > () = Variable(yystack_[2].value.as< std::string > (), yystack_[1].value.as < Expression > (), yystack_[0].value.as < Expression > (), NULL); }
#line 2432 "parser.cc"
    break;

  case 20: // var_decl: "mut" ident ident EQUAL expr
#line 54 "dyn.y"
                                  { yylhs.value.as < Statement > () = Variable(yystack_[4].value.as< std::string > (), yystack_[3].value.as < Expression > (), yystack_[2].value.as < Expression > (), &yystack_[0].value.as < Expression > ()); }
#line 2438 "parser.cc"
    break;

  case 21: // var_decl: "con" ident ident EQUAL expr
#line 55 "dyn.y"
                                  { yylhs.value.as < Statement > () = Variable(yystack_[4].value.as< std::string > (), yystack_[3].value.as < Expression > (), yystack_[2].value.as < Expression > (), &yystack_[0].value.as < Expression > ()); }
#line 2444 "parser.cc"
    break;

  case 22: // var_decl: ident ident EQUAL expr
#line 56 "dyn.y"
                            { yylhs.value.as < Statement > () = Variable(yystack_[3].value.as< std::string > (), yystack_[2].value.as < Expression > (), yystack_[1].value.as < int > (), &yystack_[0].value.as < Expression > ()); }
#line 2450 "parser.cc"
    break;

  case 23: // stmts: stmt SEMICOLON
#line 58 "dyn.y"
                     { yylhs.value.as< Block > () = Block(); yylhs.value.as< Block > ().statements.push_back(yystack_[1].value.as< Statement > ()); }
#line 2456 "parser.cc"
    break;

  case 24: // stmts: stmts SEMICOLON stmt
#line 59 "dyn.y"
                            {yystack_[2].value.as< Block > ().statements.push_back(yystack_[2].value.as< Statement > ()); }
#line 2462 "parser.cc"
    break;

  case 25: // stmt: %empty
#line 61 "dyn.y"
      { yylhs.value.as < Statement > () = Statement(); }
#line 2468 "parser.cc"
    break;

  case 26: // stmt: decl
#line 62 "dyn.y"
      { yylhs.value.as < Statement > () = yystack_[0].value.as < Statement > (); }
#line 2474 "parser.cc"
    break;

  case 27: // block: L_BRACE stmts R_BRACE
#line 64 "dyn.y"
                             { yylhs.value.as < Expression > () = yystack_[1].value.as < Statement > (); }
#line 2480 "parser.cc"
    break;

  case 28: // expr: ident
#line 66 "dyn.y"
      { yylhs.value.as < Expression > () = yystack_[0].value.as < Expression > (); }
#line 2486 "parser.cc"
    break;

  case 29: // expr: number
#line 67 "dyn.y"
      { yylhs.value.as < Expression > () = yystack_[0].value.as < Expression > (); }
#line 2492 "parser.cc"
    break;

  case 30: // ident: IDENT
#line 69 "dyn.y"
             { yylhs.value.as < Expression > () = Identifier(yystack_[0].value.as< std::string > ()); }
#line 2498 "parser.cc"
    break;

  case 31: // number: INT
#line 71 "dyn.y"
            { yylhs.value.as< Integer > () = Integer(yystack_[0].value.as< long long > ()); }
#line 2504 "parser.cc"
    break;

  case 32: // number: DOUB
#line 72 "dyn.y"
             { yylhs.value.as< Double > () = Double(yystack_[0].value.as< double > ()); }
#line 2510 "parser.cc"
    break;


#line 2514 "parser.cc"

            default:
              break;
            }
        }
#if YY_EXCEPTIONS
      catch (const syntax_error& yyexc)
        {
          YYCDEBUG << "Caught exception: " << yyexc.what() << '\n';
          error (yyexc);
          YYERROR;
        }
#endif // YY_EXCEPTIONS
      YY_SYMBOL_PRINT ("-> $$ =", yylhs);
      yypop_ (yylen);
      yylen = 0;

      // Shift the result of the reduction.
      yypush_ (YY_NULLPTR, YY_MOVE (yylhs));
    }
    goto yynewstate;


  /*--------------------------------------.
  | yyerrlab -- here on detecting error.  |
  `--------------------------------------*/
  yyerrlab:
    // If not already recovering from an error, report this error.
    if (!yyerrstatus_)
      {
        ++yynerrs_;
        std::string msg = YY_("syntax error");
        error (YY_MOVE (msg));
      }


    if (yyerrstatus_ == 3)
      {
        /* If just tried and failed to reuse lookahead token after an
           error, discard it.  */

        // Return failure if at end of input.
        if (yyla.kind () == symbol_kind::S_YYEOF)
          YYABORT;
        else if (!yyla.empty ())
          {
            yy_destroy_ ("Error: discarding", yyla);
            yyla.clear ();
          }
      }

    // Else will try to reuse lookahead token after shifting the error token.
    goto yyerrlab1;


  /*---------------------------------------------------.
  | yyerrorlab -- error raised explicitly by YYERROR.  |
  `---------------------------------------------------*/
  yyerrorlab:
    /* Pacify compilers when the user code never invokes YYERROR and
       the label yyerrorlab therefore never appears in user code.  */
    if (false)
      YYERROR;

    /* Do not reclaim the symbols of the rule whose action triggered
       this YYERROR.  */
    yypop_ (yylen);
    yylen = 0;
    YY_STACK_PRINT ();
    goto yyerrlab1;


  /*-------------------------------------------------------------.
  | yyerrlab1 -- common code for both syntax error and YYERROR.  |
  `-------------------------------------------------------------*/
  yyerrlab1:
    yyerrstatus_ = 3;   // Each real token shifted decrements this.
    // Pop stack until we find a state that shifts the error token.
    for (;;)
      {
        yyn = yypact_[+yystack_[0].state];
        if (!yy_pact_value_is_default_ (yyn))
          {
            yyn += symbol_kind::S_YYerror;
            if (0 <= yyn && yyn <= yylast_
                && yycheck_[yyn] == symbol_kind::S_YYerror)
              {
                yyn = yytable_[yyn];
                if (0 < yyn)
                  break;
              }
          }

        // Pop the current state because it cannot handle the error token.
        if (yystack_.size () == 1)
          YYABORT;

        yy_destroy_ ("Error: popping", yystack_[0]);
        yypop_ ();
        YY_STACK_PRINT ();
      }
    {
      stack_symbol_type error_token;


      // Shift the error token.
      error_token.state = state_type (yyn);
      yypush_ ("Shifting", YY_MOVE (error_token));
    }
    goto yynewstate;


  /*-------------------------------------.
  | yyacceptlab -- YYACCEPT comes here.  |
  `-------------------------------------*/
  yyacceptlab:
    yyresult = 0;
    goto yyreturn;


  /*-----------------------------------.
  | yyabortlab -- YYABORT comes here.  |
  `-----------------------------------*/
  yyabortlab:
    yyresult = 1;
    goto yyreturn;


  /*-----------------------------------------------------.
  | yyreturn -- parsing is finished, return the result.  |
  `-----------------------------------------------------*/
  yyreturn:
    if (!yyla.empty ())
      yy_destroy_ ("Cleanup: discarding lookahead", yyla);

    /* Do not reclaim the symbols of the rule whose action triggered
       this YYABORT or YYACCEPT.  */
    yypop_ (yylen);
    YY_STACK_PRINT ();
    while (1 < yystack_.size ())
      {
        yy_destroy_ ("Cleanup: popping", yystack_[0]);
        yypop_ ();
      }

    return yyresult;
  }
#if YY_EXCEPTIONS
    catch (...)
      {
        YYCDEBUG << "Exception caught: cleaning lookahead and stack\n";
        // Do not try to display the values of the reclaimed symbols,
        // as their printers might throw an exception.
        if (!yyla.empty ())
          yy_destroy_ (YY_NULLPTR, yyla);

        while (1 < yystack_.size ())
          {
            yy_destroy_ (YY_NULLPTR, yystack_[0]);
            yypop_ ();
          }
        throw;
      }
#endif // YY_EXCEPTIONS
  }

  void
  parser::error (const syntax_error& yyexc)
  {
    error (yyexc.what ());
  }

#if YYDEBUG || 0
  const char *
  parser::symbol_name (symbol_kind_type yysymbol)
  {
    return yytname_[yysymbol];
  }
#endif // #if YYDEBUG || 0









  const signed char parser::yypact_ninf_ = -21;

  const signed char parser::yytable_ninf_ = -1;

  const signed char
  parser::yypact_[] =
  {
      31,   -21,    23,    -6,    -6,    -6,    14,   -21,   -21,   -21,
       7,    -6,   -21,    22,    -6,    -6,   -21,   -21,   -21,    11,
      -6,    30,    37,    43,    36,     1,    42,    43,    43,   -21,
     -21,   -21,   -21,   -21,    48,   -21,    -6,   -21,    55,    -6,
     -21,   -21,    58,    36,    60,    -6,    50,   -21,    23,   -21,
     -21,    52,   -21,    -6,   -21,    13,    62,   -21,   -21,    23,
     -21,   -21,   -21
  };

  const signed char
  parser::yydefact_[] =
  {
       0,    30,     0,     0,     0,     0,     0,     3,     7,     6,
       0,     0,     2,     0,     0,     0,     1,     4,     5,     0,
       0,    19,     0,     0,    16,     0,     9,     0,     0,    31,
      32,    22,    28,    29,     0,    17,     0,     8,    11,     0,
      20,    21,     0,     0,     0,     0,     0,    13,    25,    15,
      18,     0,    10,     0,    26,     0,     0,    12,    14,    25,
      27,    23,    24
  };

  const signed char
  parser::yypgoto_[] =
  {
     -21,   -21,     3,   -21,   -21,    21,   -21,   -21,   -20,   -21,
       8,   -21,     4,    -3,   -21
  };

  const signed char
  parser::yydefgoto_[] =
  {
       0,     6,    54,     8,    25,    46,     9,    34,    10,    55,
      56,    49,    31,    11,    33
  };

  const signed char
  parser::yytable_[] =
  {
      13,    14,    15,     7,    35,    12,     1,    37,    19,    17,
      18,    21,    22,     1,    16,    23,    59,    26,    24,    60,
      32,    36,    38,    50,    32,    32,     1,    20,     3,     4,
       5,    40,    41,    44,    27,     1,    47,     3,     4,     5,
      36,    28,    47,     1,     2,     3,     4,     5,     1,    39,
      58,     4,     5,    29,    30,     1,    42,    43,    52,    53,
      57,    53,    45,    48,    23,    61,    51,    62
  };

  const signed char
  parser::yycheck_[] =
  {
       3,     4,     5,     0,    24,     2,    12,     6,    11,     6,
       3,    14,    15,    12,     0,     4,     3,    20,     7,     6,
      23,    24,    25,    43,    27,    28,    12,     5,    14,    15,
      16,    27,    28,    36,     4,    12,    39,    14,    15,    16,
      43,     4,    45,    12,    13,    14,    15,    16,    12,     7,
      53,    15,    16,    10,    11,    12,     8,     9,     8,     9,
       8,     9,     7,     5,     4,     3,    45,    59
  };

  const signed char
  parser::yystos_[] =
  {
       0,    12,    13,    14,    15,    16,    18,    19,    20,    23,
      25,    30,    19,    30,    30,    30,     0,    19,     3,    30,
       5,    30,    30,     4,     7,    21,    30,     4,     4,    10,
      11,    29,    30,    31,    24,    25,    30,     6,    30,     7,
      29,    29,     8,     9,    30,     7,    22,    30,     5,    28,
      25,    22,     8,     9,    19,    26,    27,     8,    30,     3,
       6,     3,    27
  };

  const signed char
  parser::yyr1_[] =
  {
       0,    17,    18,    18,    18,    19,    19,    19,    20,    21,
      21,    21,    21,    22,    22,    23,    24,    24,    24,    25,
      25,    25,    25,    26,    26,    27,    27,    28,    29,    29,
      30,    31,    31
  };

  const signed char
  parser::yyr2_[] =
  {
       0,     2,     2,     1,     2,     2,     1,     1,     5,     1,
       4,     2,     5,     1,     3,     6,     0,     1,     3,     3,
       5,     5,     4,     2,     3,     0,     1,     3,     1,     1,
       1,     1,     1
  };


#if YYDEBUG
  // YYTNAME[SYMBOL-NUM] -- String name of the symbol SYMBOL-NUM.
  // First, the terminals, then, starting at \a YYNTOKENS, nonterminals.
  const char*
  const parser::yytname_[] =
  {
  "\"end of file\"", "error", "\"invalid token\"", "SEMICOLON", "EQUAL",
  "L_BRACE", "R_BRACE", "L_PAREN", "R_PAREN", "COMMA", "INT", "DOUB",
  "IDENT", "\"pub\"", "\"enum\"", "\"mut\"", "\"con\"", "$accept", "decls",
  "decl", "enum_decl", "enum_members", "partners", "fn_decl", "fn_args",
  "var_decl", "stmts", "stmt", "block", "expr", "ident", "number", YY_NULLPTR
  };
#endif


#if YYDEBUG
  const signed char
  parser::yyrline_[] =
  {
       0,    29,    29,    30,    31,    33,    34,    35,    37,    39,
      40,    41,    42,    44,    45,    47,    49,    50,    51,    53,
      54,    55,    56,    58,    59,    61,    62,    64,    66,    67,
      69,    71,    72
  };

  void
  parser::yy_stack_print_ () const
  {
    *yycdebug_ << "Stack now";
    for (stack_type::const_iterator
           i = yystack_.begin (),
           i_end = yystack_.end ();
         i != i_end; ++i)
      *yycdebug_ << ' ' << int (i->state);
    *yycdebug_ << '\n';
  }

  void
  parser::yy_reduce_print_ (int yyrule) const
  {
    int yylno = yyrline_[yyrule];
    int yynrhs = yyr2_[yyrule];
    // Print the symbols being reduced, and their result.
    *yycdebug_ << "Reducing stack by rule " << yyrule - 1
               << " (line " << yylno << "):\n";
    // The symbols being reduced.
    for (int yyi = 0; yyi < yynrhs; yyi++)
      YY_SYMBOL_PRINT ("   $" << yyi + 1 << " =",
                       yystack_[(yynrhs) - (yyi + 1)]);
  }
#endif // YYDEBUG

  parser::symbol_kind_type
  parser::yytranslate_ (int t) YY_NOEXCEPT
  {
    // YYTRANSLATE[TOKEN-NUM] -- Symbol number corresponding to
    // TOKEN-NUM as returned by yylex.
    static
    const signed char
    translate_table[] =
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
      15,    16
    };
    // Last valid token kind.
    const int code_max = 271;

    if (t <= 0)
      return symbol_kind::S_YYEOF;
    else if (t <= code_max)
      return static_cast <symbol_kind_type> (translate_table[t]);
    else
      return symbol_kind::S_YYUNDEF;
  }

} // yy
#line 2902 "parser.cc"

