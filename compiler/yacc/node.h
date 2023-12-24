#include <iostream>
#include <llvm/Value.h>
#include <vector>

class CodeGenContext;
class NStatement;
class NExpression;
class NDeclaration;

typedef std::vector<NStatement *> Statements;
typedef std::vector<NExpression *> Expressions;
typedef std::vector<NDeclaration *> Declarations;

class Node {
public:
  virtual ~Node() {}
  virtual llvm::Value *codeGen(CodeGenContext &context) {}
};

class NExpression : public Node {};

class NInteger : public NExpression {};
class NDouble : public NExpression {};
class NIdentifier : public NExpression {};
class NMethodCall : public NExpression {};
class NBinaryOperator : public NExpression {};
class NUnaryOperator : public NExpression {};
class NAssignment : public NExpression {};
class NBlock : public NExpression {};

class NStatement : public Node {};
class NExpressionStatement : public NStatement {};
class NFunctionDeclaration : public NStatement {};
class NStructDeclaration : public NStatement {};
class NEnumDeclaration : public NStatement {};
class NVariableDeclaration : public NStatement {};

class NDeclaration : public Node {};
