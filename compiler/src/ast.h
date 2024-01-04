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

class Block : public Expression {
public:
  std::vector<Statement> statements;
  Block() : statements({}) {}
};

class Variable : public Statement {
public:
  std::string mutability;
  Identifier type;
  Identifier id;
  Expression *assignment;
  Variable(std::string &mutability, Identifier &type, Identifier &id,
           Expression *assignment)
      : mutability(mutability), type(type), id(id), assignment(assignment) {}
};

class Function : public Statement {
public:
  Identifier type;
  Identifier id;
  std::vector<Variable> args;
  Block *block;
  Function(Identifier &type, Identifier &id, std::vector<Variable> &args,
           Block *block)
      : type(type), id(id), args(args), block(block) {}
};

class EnumMember {
public:
  Identifier id;
  std::vector<Identifier> partners;
  EnumMember(Identifier &id, std::vector<Identifier> &partners) : id(id), partners(partners) {}
};

class Enum : public Statement {
public:
  Identifier id;
  std::vector<EnumMember> members;
  Enum(Identifier &id, std::vector<EnumMember> &members)
      : id(id), members(members) {}
};
