#pragma once

#include "lexer.h"
#include <vector>

namespace Parser {
class Declaration {};
class VariableDeclaration : Declaration {};
class TraitDeclaration : Declaration {};
class StructField {};
class Expression {};
class BinaryExpression : Expression {
  Expression left, right;
  Lexer::Token bop;
};
class MathExpression : Expression {
  Expression left, right;
  Lexer::Token mop;
};
class FunctionCallExpression : Expression {
  Lexer::Token functionIdentifier;
  Lexer::Token LParen;
  std::vector<Lexer::Token> parameters;
  Lexer::Token RParen;
};
class LiteralExpression : Expression {};
class NumberLiteral : LiteralExpression {
  Lexer::Token Value;
};
class DecimalLiteral : LiteralExpression {
  Lexer::Token Value;
};
class StructLiteral : LiteralExpression {
  Lexer::Token Struct;
  Lexer::Token LBrace;
  std::vector<TraitDeclaration> traits;
  std::vector<StructField> members;
  Lexer::Token RBrace;
};
class Type {};
class FunctionLiteral : LiteralExpression {
  Type t;
  Lexer::Token LParen;
  std::vector<VariableDeclaration> params;
  Lexer::Token RParen;
};
class ArrayAccessExpression : Expression {};
class PointerDereferenceExpression : Expression {};

class PrimitiveType : Type {
  union IntOrFloat {};
  std::string bits;
};
class ArrayType : Type {
  Type type;
  Lexer::Token LBrack;
  LiteralExpression amount;
  Lexer::Token RBrack;
};
class PointerType : Type {
  Type t;
  Lexer::Token asterisk;
};
class FunctionType : Type {
  Type t;
  Lexer::Token LParen;
  std::vector<Type> params;
  Lexer::Token RParen;
};
class IdentifierType : Type {
  Lexer::Token identifier;
};
class ReferenceType : Type {
  Type t;
  Lexer::Token ampersand;
};
class MutVariableDeclaration : VariableDeclaration {
  Lexer::Token Mut;
  Type type;
  Lexer::Token Identifier;
  Lexer::Token Equal;
  Expression expr;
};
class ConVariableDeclaration : VariableDeclaration {
  Lexer::Token Con;
  Type type;
  Lexer::Token Identifier;
  Lexer::Token Equal;
  Expression expr;
};
class PublicDeclaration : Declaration {
  Lexer::Token PubToken;
  std::vector<Declaration> decl;
};
class EnumField {
  Lexer::Token identifier;
  Lexer::Token LParen;
  Type t;
  Lexer::Token RParen;
};
class EnumDeclaration : Declaration {
  Lexer::Token EnumToken;
  Lexer::Token Identifier;
  Lexer::Token LBrace;
  std::vector<EnumField> EnumField;
  Lexer::Token RBrace;
};
class StructMember : StructField {
  Type t;
  Lexer::Token identifer;
};
class StructFunction : StructField {
  Type t;
  Lexer::Token identifier;
  Lexer::Token LParen;
  Lexer::Token self;
  Lexer::Token ampersand;
  std::vector<VariableDeclaration> parameters;
  Lexer::Token RParen;
};
class StructDeclaration : Declaration {
  Lexer::Token StructToken;
  Lexer::Token Identifier;
  std::vector<Lexer::Token> TraitIdentifiers;
  Lexer::Token LBrace;
  std::vector<StructField> Members;
  Lexer::Token RBrace;
};
class Statement {};
class BlockStatement : Statement {
    Lexer::Token LBrace;
    std::vector<Statement> statements;
    std::vector<Declaration> decls;
    Lexer::Token RBrace;
  };
class IfStatement : Statement {
  Lexer::Token If;
  BinaryExpression Binary;
  BlockStatement Block;
};
class LoopStatement : Statement {
  Lexer::Token Loop;
  BlockStatement Block;
};
class ForStatement : Statement {
  Lexer::Token For;
  BlockStatement Block;
};
class VariableAssignmentStatement : Statement {
  Lexer::Token identifier;
  LiteralExpression value;
};
class BreakStatement : Statement {
  Lexer::Token Break;
};
class ContinueStatement : Statement {
  Lexer::Token Continue;
};
class Program {
  std::vector<Declaration> declarations;
  std::vector<Statement> statements;
};
}; // namespace Parser
