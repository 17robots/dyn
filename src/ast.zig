pub const NodeType = enum {
    // declarations
    declaration,
    packageDeclaration,
    useDeclaration,
    variableDeclaration,
    typeDeclaration,
    functionDeclaration,
    structDeclaration,
    unionDeclaration,
    enumDeclaration,
    // statements
    assignStmt,
    returnStmt,
    deferStmt,
    ifStmt,
    loopStmt,
    forStmt,
    matchStmt,
    rangeClause,
    matchBranch,
    // expressions
    integerTypeExpression,
    literalExpression,
    functionLiteral,
    parenExpression,
    memberAccessorExpression,
    arrayAccessorExpression,
    sliceExpression,
    operationExpression,
    functionCallExpression,
    arrayTypeExpression,
    structLiteral,
    functionTypeExpression,
    structTypeExpression,
};

pub const Node = struct {
    t: NodeType,
    l: ?*Node,
    r: ?*Node,
    metadata: ?anyopaque,
};

// node metainformation
const Declaration = struct {

};

const PackageDeclaration = struct {

};

const UseDeclaration = struct {

};

const VariableDeclaration = struct {

};

const TypeDeclaration = struct {

};

const FunctionDeclaration = struct {

};

const StructDeclaration = struct {

};

const UnionDeclaration = struct {

};

const EnumDeclaration = struct {

};
