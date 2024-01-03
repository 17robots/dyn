#pragma once

#include <string>
class Node {};

class Identifier : Node {
public:
  std::string id;
  Identifier(std::string &id) : id(id) {}
};

class Expression : Node {};

class Variable : Node {
public:
  std::string mutability;
  Identifier type;
  Identifier id;
  Expression *assignment;
  Variable(std::string &mutability, Identifier &type, Identifier &id,
           Expression *assignment)
      : mutability(mutability), type(type), id(id), assignment(assignment) {}
};
