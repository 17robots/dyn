#pragma once
#include <string>
#include <vector>

class Node {
public:
  virtual ~Node() {}
};
class Statement : public Node {};
class Expression : public Node {};

class Identifier;
class Block;

class Variable : public Statement {
public:
  std::string *mutability;
  const Identifier &type;
  const Identifier &id;
  Expression *assignment;
  Variable(std::string *mutability, Identifier &type, Identifier &id,
           Expression *assignment)
      : mutability(mutability), type(type), id(id), assignment(assignment) {}
};
class Function : public Statement {
public:
  const Identifier &type;
  const Identifier &id;
  std::vector<Variable *> args;
  Block *block;
  Function(Identifier &type, Identifier &id, std::vector<Variable*> args, Block *block) : type(type), id(id), args(args), block(block) {}
};
class EnumMember {
public:
  const Identifier &id;
  std::vector<Identifier *> partners;
  EnumMember(Identifier &id) : id(id), partners({}) {}
  EnumMember(Identifier &id, std::vector<Identifier*> &partners) : id(id), partners(partners) {}
};
class Enum : public Statement {
public:
  const Identifier &id;
  std::vector<EnumMember *> members;
  Enum(Identifier &id, std::vector<EnumMember*> &members) : id(id), members(members) {}
};
class StructFields {
public:
  std::vector<Variable *> vars;
  std::vector<Function *> methods;
  StructFields() : vars({}), methods({}) {}
};
class Struct : public Statement {
public:
  const Identifier &id;
  std::vector<Identifier *> traits;
  StructFields &fields;
  Struct(Identifier &id, StructFields &fields) : id(id), traits({}), fields(fields) {}
  Struct(Identifier &id, std::vector<Identifier*> &traits, StructFields &fields) : id(id), traits(traits), fields(fields) {}
};

class If : public Statement {
public:
  const Expression &condition;
  const Block &block;
  If(Expression &condition, Block &block) : condition(condition), block(block) {}
};

class For : public Statement {
  public:
  const Identifier &id;
  const Expression &expr;
  Block &block;
  For(Identifier &id, Expression &expr, Block &block): id(id), expr(expr), block(block) {}
};

class MatchBranch {
public:
  Expression *branch;
  Block &block;
  MatchBranch(Block &block) : branch(NULL), block(block) {}
  MatchBranch(Expression *branch, Block &block) : branch(branch), block(block) {}
};
class Match : public Statement {
public:
  const Identifier &id;
  std::vector<MatchBranch *> branches;
  Match(Identifier &id, std::vector<MatchBranch*> branches) : id(id), branches(branches) {}
};

class Loop : public Statement {
public:
  Block &block;
  Loop(Block &block) : block(block) {}
};

class Defer : public Statement {
public:
  Expression &expr;
  Defer(Expression &expr) : expr(expr) {}
};

class Return : public Statement {
public:
  Expression *expr;
  Return(Expression *expr) : expr(NULL) {}
  Return() : expr(NULL) {}
};

class Block : public Expression {
public:
  std::vector<Statement *> statements;
  Block() : statements({}) {}
};
class Identifier : public Expression {
public:
  std::string name;
  Identifier() : name("") {}
};
class Integer : public Expression {
public:
  long long value;
  Integer() : value(0) {}
};
class Double : public Expression {
public:
  double value;
  Double() : value(0.) {}
};
class FunctionCall : public Expression {
public:
  const Identifier &id;
  std::vector<Expression *> args;
  FunctionCall(Identifier &id, std::vector<Expression *> &args)
      : id(id), args(args) {}
};
class FunctionLiteral : public Expression {
public:
  const Identifier &type;
  std::vector<Variable *> args;
  Block *block;
  FunctionLiteral(Identifier &type, std::vector<Variable *> args, Block *block)
      : type(type), args(args), block(block) {}
};
class StructLiteral : public Expression {
public:
  std::vector<Identifier *> traits;
  StructFields &fields;
  StructLiteral(StructFields &fields) : traits({}), fields(fields) {}
  StructLiteral(StructFields &fields, std::vector<Identifier *> traits)
      : traits(traits), fields(fields) {}
};
class BinaryOp : public Expression {
public:
  int op;
  Expression &lhs;
  Expression &rhs;
  BinaryOp(int op, Expression &lhs, Expression &rhs)
      : op(0), lhs(lhs), rhs(rhs) {}
};

class Assignment : public Expression {
  public:
  Identifier &lhs;
  Expression &rhs;
  Assignment(Identifier &lhs, Expression &rhs): lhs(lhs), rhs(rhs) {}
};

class UnaryOp : public Expression {
public:
  int op;
  Expression &rhs;
  UnaryOp(int op, Expression &rhs) : op(op), rhs(rhs) {}
};

class GenericItem {
public:
  const Identifier &id;
  std::vector<Identifier *> restrictions;
  GenericItem(Identifier &id) : id(id), restrictions({}) {}
};
class Generic : public Expression {
public:
  std::vector<GenericItem *> items;
  Generic() : items({}) {}
};

class Program {
public:
  std::vector<Statement *> pub_decls;
  std::vector<Statement *> decls;
  Program() : pub_decls({}), decls({}) {}
};
