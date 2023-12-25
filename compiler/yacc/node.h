#include <iostream>
#include <llvm/Value.h>
#include <vector>

class CodeGenContext;
class NStatement;
class NExpression;
class NVariableDeclaration;

typedef std::vector<NStatement *> Statements;
typedef std::vector<NExpression *> Expressions;
typedef std::vector<NVariableDeclaration *> Variables;

class Node {
public:
  virtual ~Node() {}
  virtual llvm::Value *codeGen(CodeGenContext &context) {}
};

class NExpression : public Node {};

class NInteger : public NExpression {
public:
  long long value;
  NInteger(long long value) : value(value) {}
  virtual llvm::Value *codeGen(CodeGenContext &context) {}
};
class NDouble : public NExpression {
public:
  double value;
  NDouble(double value) : value(value) {}
  virtual llvm::Value *codeGen(CodeGenContext &context) {}
};
class NIdentifier : public NExpression {
public:
  std::string value;
  NIdentifier(const std::string &value) : value(value) {}
  virtual llvm::Value *codeGen(CodeGenContext &context) {}
};
class NMethodCall : public NExpression {
public:
  const NIdentifier id;
  Expressions arguments;
  NMethodCall(const NIdentifier &id, Expressions &arguments)
      : id(id), arguments(arguments) {}
  NMethodCall(const NIdentifier &id) : id(id) {}
  virtual llvm::Value *codeGen(CodeGenContext &context) {}
};
class NBinaryOperator : public NExpression {
public:
  int op;
  NExpression &lhs;
  NExpression &rhs;
  NBinaryOperator(NExpression &lhs, int op, NExpression &rhs)
      : op(op), lhs(lhs), rhs(rhs) {}
  virtual llvm::Value *codeGen(CodeGenContext &context) {}
};
class NUnaryOperator : public NExpression {
public:
  int op;
  NExpression &rhs;
  NUnaryOperator(int op, NExpression &rhs) : op(op), rhs(rhs) {}
  virtual llvm::Value *codeGen(CodeGenContext &context) {}
};
class NAssignment : public NExpression {
public:
  NIdentifier &lhs;
  NExpression &rhs;
  NAssignment(NIdentifier &lhs, NExpression &rhs) : lhs(lhs), rhs(rhs) {}
  virtual llvm::Value *codeGen(CodeGenContext &context) {}
};
class NBlock : public NExpression {
public:
  Statements statements;
  NBlock() {}
  virtual llvm::Value *codeGen(CodeGenContext &context) {}
};

class NStatement : public Node {};
class NExpressionStatement : public NStatement {
public:
  NExpression &expr;
  NExpressionStatement(NExpression &expr) : expr(expr) {}
  virtual llvm::Value *codeGen(CodeGenContext &context) {}
};
class NVariableDeclaration : public NStatement {
  public:
  const NIdentifier& type;
  NIdentifier &id;
  NExpression* expr;
  NVariableDeclaration(const NIdentifier& type, NIdentifier & id) : type(type), id(id) {}
  NVariableDeclaration(const NIdentifier& type, NIdentifier & id, NExpression* expr) : type(type), id(id), expr(expr) {}
};
class NFunctionDeclaration : public NStatement {
  public:
  const NIdentifier &type;
  const NIdentifier &id;
  Variables arguments;
  NBlock &block;
  NFunctionDeclaration(const NIdentifier& type, const NIdentifier& id, const Variables& arguments, NBlock& block) : type(type), id(id), arguments(arguments), block(block) {}
};
class StructField {};
class NStructDeclaration : public NStatement {
  public:
  const NIdentifier &id;
  
};
class NEnumDeclaration : public NStatement {};
