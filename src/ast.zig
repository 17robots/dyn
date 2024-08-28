pub const NodeType = enum {
    // declarations
    declaration,
    packageDeclaration,
    useDeclaration,
    variableDeclaration,
    typeDeclaration,
    functionDeclaration,
    // statements
    // expressions
};

pub const Node = struct {
    t: NodeType,
    l: ?*Node,
    r: ?*Node,
    metadata: ?anyopaque,
};

// node metainformation
