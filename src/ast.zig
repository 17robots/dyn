const std = @import("std");
pub const NodeType = enum {
    program,
    moduleDeclaration,
    useDeclaration,
    useBlock,
    literal,
    identifier,
};

pub const Node = struct {
    t: NodeType,
    nodes: std.MultiArrayList(?Node),
    metadata: ?anyopaque,

    pub fn init(t: NodeType, metadata: ?anyopaque) Node {
        return Node{ .t = t, .nodes = {}, .metadata = metadata };
    }
};

pub const LiteralMetadata = struct {
    kind: LiteralKind,
    val: []const u8,
    pub const LiteralKind = enum {
        string,
        int,
        float,
    };
};

pub const IdentifierMetadata = struct {
    val: []const u8,
};

// useBlock,
// useDeclaration,
// functionDeclaration,
// functionCall,
// variableDeclaration,
// literal,
// typeLiteral,
// optionalType,
// pointerType,
// arrayType,
// variableReference,
// pointerDereference,
// condition,
// block,
// match,
// matchBranch,
// deferStatement,
// breakStatement,
// returnStatement,
// loop,
// forStatement,
// rangeClause,
// capture,
// loopModifier,
// arrayLiteral,
// structLiteral,
// callArgs,
// declArgs,
// errorDecl,
// errorMember,
// errorType,
// tryStatement,
// catchStatement,
// unionDeclaration,
// unionMember,
// unionLiteral,
// selectionExpression,
