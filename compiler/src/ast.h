#pragma once

#include <string>
#include <vector>

// base
class Node {};
class Expr : public Node {};
class Stmt : public Node {};
class Decl : public Node {};

// expr
class Ident : public Expr {
private:
  std::string name;
  bool is_type; // whether or not this is a type identifier or a declared name
};

class Lit : public Expr {
private:
  enum Kind {} kind;
  std::string value;
};

class Type {};

class FuncLit : public Expr {
private:
  union {
    Type t;
    Ident i;
  } type;
  std::string l_paren, r_paren;
  std::vector<Node> args;
  Block block;
};

// types

// stmt
class Block : public Stmt {
private:
  std::string l_brace, r_brace;
  std::vector<Stmt> stmts;
};

// decl

// spec
