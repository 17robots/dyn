#pragma once

#include "lexer.h"
#include <vector>

// ast
class Node {};
class Expr : public Node {};
class Stmt : public Node {};
class Decl : public Node {};

class Type {};
class ArrType {};
class StructType {};
class FuncType {
  Type *type;
  std::vector<Type> parameters;
};
class RefType {};
class NumType {};
class StrType {};
class CharType {};

class Ident : Expr {
private:
  std::string name;
  bool is_type; // whether or not this is a name or a type context
};
class Lit : Expr {
private:
  enum LitKind {
    Int,
    Float,
    String,
    Char,
  } kind;
  std::string value;
};

class BlockStmt;
class FuncLit : Expr {
private:
  FuncType *fn_type;
  BlockStmt *block;
};
class StructLit : public Expr {};
class CallExpr : public Expr {};
class UnaryExpr : public  Expr {};
class BinaryExpr : public Expr {};

class InvalidStmt : public Stmt {};
class DeclStmt : public Stmt {};
class ExprStmt : public Stmt {};
class IncStmt : public Stmt {};
class AssignStmt : public Stmt {};
class DeferStmt : public Stmt {};
class ReturnStmt : public Stmt {};
class BreakStmt : public Stmt {};
class ContinueStmt : public Stmt {};
class BlockStmt : public Stmt {};
class IfStmt : public Stmt {};
class MatchStmt : public Stmt {};
class MatchBranchStmt : public Stmt {};
class ForStmt : public Stmt {};
class RangeStmt : public Stmt {};

class InvalidDecl {};
class GenDecl {};
class FuncDecl {};
