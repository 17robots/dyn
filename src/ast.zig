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
    nodes: std.ArrayList(?Node),
    metadata: ?Metadata,

    pub fn init(alloc: std.mem.Allocator, t: NodeType, metadata: ?Metadata) Node {
        return Node{ .t = t, .nodes = std.ArrayList(?Node).init(alloc), .metadata = metadata };
    }

    pub fn deinit(s: *Node) void {
        s.nodes.deinit();
    }
};

pub const Metadata = struct {
    kind: ?LiteralKind,
    val: ?[]const u8,

    pub const LiteralKind = enum {
        string,
        int,
        float,
    };
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
