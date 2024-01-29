#pragma once

#include <string>
#include <vector>
class Node {};

class Expression : Node {};
class Statement : Node {};

class Identifier : public Expression {
public:
  std::string id;
  Identifier(std::string &id) : id(id) {}
};

class Integer : public Expression {
public:
  long long value;
  Integer(long long value) : value(value){};
};

class Double : public Expression {
public:
  double value;
  Double(double value) : value(value) {}
};

class FunctionCall : public Expression {
public:
  Identifier id;
  std::vector<Expression> args;
  FunctionCall(Identifier &id, std::vector<Expression> &args)
      : id(id), args(args) {}
};

class FunctionCallStatement : public Statement {
public:
  FunctionCall call;
  FunctionCallStatement(FunctionCall &call) : call(call) {}
};

class Block : public Expression {
public:
  std::vector<Statement> statements;
  Block() : statements({}) {}
};

class Var : public Statement {
  Identifier type;
  Identifier id;
};

class Variable : public Statement {
public:
  std::string mutability;
  Var var;
  Expression *assignment;
  Variable(std::string &mutability, Var &var, Expression *assignment)
      : mutability(mutability), var(var), assignment(assignment) {}
};

class FunctionSignature : public Statement {
public:
  Var var;
  std::vector<Variable> args;
  FunctionSignature(Var &var, std::vector<Variable> &args)
      : var(var), args(args) {}
};

class Function : public Statement {
public:
  FunctionSignature sig;
  Block *block;
  Function(FunctionSignature &sig, Block *block) : sig(sig), block(block) {}
};

class EnumMember {
public:
  Identifier id;
  std::vector<Identifier> partners;
  EnumMember(Identifier &id, std::vector<Identifier> &partners)
      : id(id), partners(partners) {}
};

class Enum : public Statement {
public:
  Identifier id;
  std::vector<EnumMember> members;
  Enum(Identifier &id, std::vector<EnumMember> &members)
      : id(id), members(members) {}
};

class Struct {
public:
  Identifier id;
  std::vector<Statement> members;
  Struct(Identifier &id, std::vector<Statement> &members)
      : id(id), members(members) {}
};

class Program : public Node {
public:
  std::vector<Statement> statements;
  Program() : statements({}){};
};

// ast v 3
