#pragma once

#include <string>
#include <vector>

class Node {};
class Statement : public Node {};
class Expression : public Node {};

typedef std::vector<Statement *> Statements;

// Expressions
class Identifier : public Expression {
public:
  std::string value;
  Identifier(const std::string &value) : value(value) {}
};
class Integer : public Expression {
public:
  long long value;
  Integer(long long value) : value(value) {}
};
class Double : public Expression {
public:
  double value;
  Double(double value) : value(value) {}
};
class FunctionCall : public Expression {
public:
  const Identifier &id;
  std::vector<Identifier *> args;
  FunctionCall(std::vector<Identifier *> args, const Identifier &id)
      : id(id), args(args) {}
};
class BinaryOp : public Expression {
public:
  std::string op;
  const Expression &lhs;
  const Expression &rhs;
  BinaryOp(const std::string &op, const Expression &lhs, const Expression &rhs)
      : op(op), lhs(lhs), rhs(rhs) {}
};
class UnaryOp : public Expression {
public:
  std::string op;
  const Expression &rhs;
  UnaryOp(const std::string &op, const Expression &rhs) : op(op), rhs(rhs) {}
};
class Block : public Expression {
public:
  Statements s;
  Block(Statements s) : s(s) {}
  Block() : s({}) {}
};
class Range : public Expression {
public:
  Range() {}
};
class Union : public Expression {
public:
  std::vector<Identifier *> values;
  Union(std::vector<Identifier *> &values) : values(values) {}
};
class Intersection : public Expression {
public:
  std::vector<Identifier *> values;
  Intersection(std::vector<Identifier *> &values) : values(values) {}
};
class Generic : public Expression {
public:
  class GenericMember {
  public:
    const Identifier &generic;
    std::vector<Identifier *> bounds;
    GenericMember(const Identifier &generic, std::vector<Identifier *> &bounds)
        : generic(generic), bounds(bounds) {}
  };
  std::vector<GenericMember *> members;
  Generic(std::vector<GenericMember *> &members) : members(members) {}
};

// Declarations
class Declaration : public Statement {};
class Variable : public Declaration {
public:
  std::string *mutability;
  const Identifier &type;
  const Identifier &id;
  Expression *value;
  Variable(std::string *mutability, const Identifier &type,
           const Identifier &id, Expression *value)
      : mutability(mutability), type(type), id(id), value(value) {}
};
class Function : public Declaration {
public:
  const Identifier &type;
  const Identifier *id;
  std::vector<Variable *> args;
  Block *block;
  Function(const Identifier &type, const Identifier *id,
           std::vector<Variable *> &args, Block *block)
      : type(type), id(id), args(args), block(block) {}
};
class EnumMember {
public:
  const Identifier &id;
  std::vector<Identifier *> partners;
  EnumMember(const Identifier &id, std::vector<Identifier *> &partners)
      : id(id), partners(partners) {}
  EnumMember(const Identifier &id) : id(id), partners({}) {}
};
typedef std::vector<EnumMember *> EnumMembers;
class Enum : public Declaration {
public:
  const Identifier &id;
  EnumMembers members;
  Enum(const Identifier &id, EnumMembers &members) : id(id), members(members) {}
};
class StructFields {
  public:
  std::vector<Variable *> variables;
  std::vector<Function *> methods;
  StructFields(): variables({}), methods({}) {}
};
class Struct : public Declaration {
public:
  const Identifier *id;
  std::vector<Struct *> traits;
  Struct(const Identifier *id, std::vector<Struct *> &traits,
         std::vector<Variable *> &variables, std::vector<Function *> &methods)
      : id(id), traits(traits), variables(variables), methods(methods) {}
};
class Type : public Declaration {
public:
  const Identifier &id;
  std::vector<Identifier *> types;
  Type(const Identifier &id, std::vector<Identifier *> &types)
      : id(id), types(types) {}
};

// Statements
class If : public Statement {
public:
  const Expression &expr;
  Block *block;
  If(const Expression &expr, Block *block) : expr(expr), block(block) {}
};
class Match : public Statement {
  class MatchBranch {
  public:
    const Expression &expr;
    Block *block;
    MatchBranch(const Expression &expr, Block *block)
        : expr(expr), block(block) {}
  };

public:
  const Expression &expr; // the var to match
  std::vector<MatchBranch *> branches;
  Match(const Expression &expr, std::vector<MatchBranch *> &branches)
      : expr(expr), branches(branches) {}
};
class Loop : public Statement {
public:
  Block *block;
  Loop(Block *block) : block(block) {}
};
class Defer : public Statement {
public:
  const Expression &expr;
  Defer(const Expression &expr) : expr(expr) {}
};

typedef std::vector<Declaration *> Declarations;
typedef std::vector<Variable *> Variables;
class Program {
public:
  Declarations pub_decls;
  Declarations decls;
  Program() : decls({}), pub_decls({}) {}
};
