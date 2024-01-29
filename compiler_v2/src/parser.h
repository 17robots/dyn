#pragma once

#include "lexer.h"

enum NodeType { Program, ProgramDeclaration, Invalid, Type, Mut, Pub };

static std::vector<std::string> KEYWORDS = {};

struct Node {
  NodeType type;
  bool pub, mut;
  std::vector<Node> children;
  std::string val;
};

class Parser {
public:
  Parser(const std::vector<Token> &tks) : tks(tks), currentToken(0) {}
  Node parse() { return this->programDeclarations(); }

private:
  std::vector<Token> tks;
  int currentToken;
  Token current() { return this->tks.at(this->currentToken); }
  bool nextToken() { return this->currentToken + 1 < this->tks.size(); }
  Node enumNode() { return {}; }
  Node structNode() { return {}; }
  Node functionNode() { return {}; }
  Node functionLiteralNode(std::string &type) { return {}; }
  Node variableNode() { return {}; }
  Node var() {
    Node v;
    // read type
    v.children.push_back({.type = Type, .val = this->current().val});
    this->currentToken++;
    // read if ( or name or mut
    if (this->current().val == "(") {
      v.children.push_back({});
    } else if(this->current().val == "mut") {}
    v.children.push_back({.type = Type, .val = this->current().val});
    // read if ( then return fn
    // else return var
    return v;
  }
  Node programDeclaration() {
    Node programDeclaration = {.type = ProgramDeclaration, .children = {}};
    Token curr = this->current();
    if (curr.type == 3 && curr.val == "pub") {
      programDeclaration.children.push_back({.type = Pub});
      this->currentToken++;
    }
    if (curr.type == 3) {
      if (curr.val == "enum") {
        programDeclaration.children.push_back(this->enumNode());
      } else if (curr.val == "struct") {
        programDeclaration.children.push_back(this->structNode());
      } else {
        programDeclaration.children.push_back(this->var());
      }
    }
    return programDeclaration;
  }
  Node programDeclarations() {
    Node program = {.type = Program, .children = {}};
    while (this->nextToken()) {
      program.children.push_back(programDeclaration());
    }
    return program;
  }
};
