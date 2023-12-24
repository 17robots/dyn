#pragma once

#include "lexer.h"
#include <vector>

namespace Parser {
class Declaration {};
class Expression {};
class Statement {};
class Type {};
class VariableDeclaration : Declaration {};
class StructField {};
class LiteralExpression : Expression {};
class ArrayAccessExpression : Expression {};
  
class TraitDeclaration : Declaration {
    Lexer::Token Trait;
    
  };
class BinaryExpression : Expression {
public:
private:
  Expression *left;
  Expression *right;
  Lexer::Token *bop;
};
class MathExpression : Expression {
public:
private:
  Expression *left;
  Expression *right;
  Lexer::Token *mop;
};
class FunctionCallExpression : Expression {
public:
private:
  Lexer::Token *functionIdentifier;
  Lexer::Token *LParen;
  std::vector<Lexer::Token *> parameters;
  Lexer::Token *RParen;
};

class NumberLiteral : LiteralExpression {
public:
private:
  Lexer::Token *Value;
};
class DecimalLiteral : LiteralExpression {
public:
private:
  Lexer::Token *Value;
};
class StructLiteral : LiteralExpression {
public:
private:
  Lexer::Token *Struct;
  Lexer::Token *LBrace;
  std::vector<TraitDeclaration *> traits;
  std::vector<StructField *> members;
  Lexer::Token *RBrace;
};

class FunctionLiteral : LiteralExpression {
public:
private:
  Type *t;
  Lexer::Token *LParen;
  std::vector<VariableDeclaration *> params;
  Lexer::Token *RParen;
};
class PointerDereferenceExpression : Expression {
    private:
    Lexer::Token* Asterisk;
    Lexer::Token* Identifier;
  };
class PrimitiveType : Type {
public:
private:
  std::string numType;
  std::string bits;
};
class ArrayType : Type {
public:
private:
  Type *type;
  Lexer::Token *LBrack;
  LiteralExpression *amount;
  Lexer::Token *RBrack;
};
class PointerType : Type {
public:
private:
  Type *t;
  Lexer::Token *asterisk;
};
class FunctionType : Type {
public:
private:
  Type *t;
  Lexer::Token *LParen;
  std::vector<Type *> params;
  Lexer::Token *RParen;
};
class IdentifierType : Type {
public:
private:
  Lexer::Token *identifier;
};
class ReferenceType : Type {
public:
private:
  Type *t;
  Lexer::Token *ampersand;
};
class MutVariableDeclaration : VariableDeclaration {
public:
private:
  Lexer::Token *Mut;
  Type *type;
  Lexer::Token *Identifier;
  Lexer::Token *Equal;
  Expression *expr;
};
class ConVariableDeclaration : VariableDeclaration {
public:
private:
  Lexer::Token *Con;
  Type *type;
  Lexer::Token *Identifier;
  Lexer::Token *Equal;
  Expression *expr;
};
class PublicDeclaration : Declaration {
public:
private:
  Lexer::Token *PubToken;
  std::vector<Declaration *> decl;
};
class EnumField {
public:
private:
  Lexer::Token *Identifier;
  Lexer::Token *LParen;
  Type *T;
  Lexer::Token *RParen;
};
class EnumDeclaration : Declaration {
public:
private:
  Lexer::Token *EnumToken;
  Lexer::Token *Identifier;
  Lexer::Token *LBrace;
  std::vector<EnumField *> EnumField;
  Lexer::Token *RBrace;
};
class StructMember : StructField {
public:
private:
  Type *t;
  Lexer::Token *Identifer;
};
class StructFunction : StructField {
public:
private:
  Type *T;
  Lexer::Token *Identifier;
  Lexer::Token *LParen;
  Lexer::Token *Self;
  Lexer::Token *Ampersand;
  std::vector<VariableDeclaration *> parameters;
  Lexer::Token *RParen;
};
class StructDeclaration : Declaration {
public:
private:
  Lexer::Token *StructToken;
  Lexer::Token *Identifier;
  std::vector<Lexer::Token *> TraitIdentifiers;
  Lexer::Token *LBrace;
  std::vector<StructField *> Members;
  Lexer::Token *RBrace;
};

class BlockStatement : Statement {
public:
private:
  Lexer::Token *LBrace;
  std::vector<Statement *> statements;
  std::vector<Declaration *> decls;
  Lexer::Token *RBrace;
};
class IfStatement : Statement {
public:
private:
  Lexer::Token *If;
  BinaryExpression *Binary;
  BlockStatement *Block;
};
class LoopStatement : Statement {
public:
private:
  Lexer::Token *Loop;
  BlockStatement *Block;
};
class ForStatement : Statement {
public:
private:
  Lexer::Token *For;
  BlockStatement *Block;
};
class VariableAssignmentStatement : Statement {
public:
private:
  Lexer::Token *identifier;
  LiteralExpression *value;
};
class BreakStatement : Statement {
public:
private:
  Lexer::Token *Break;
};
class ContinueStatement : Statement {
public:
private:
  Lexer::Token *Continue;
};
class Program {
public:
private:
  std::vector<Declaration *> declarations;
  std::vector<Statement *> statements;
};
}; // namespace Parser
