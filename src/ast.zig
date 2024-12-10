const std = @import("std");
const Token = @import("token.zig").TokenType;

pub const Node = union(enum) {
    const LiteralKind = enum {
        string,
        int,
        float,
        boolean,
        char,
        null,
        undefined,
    };
    ArrayIndex: struct { root: *Node, expr: ?*Node },
    ArrayType: struct { type: *Node, number: ?*Node },
    BinaryExpr: struct { l: *Node, op: Token, r: *Node },
    BlockStmt: struct { stmts: std.ArrayList(Node) },
    Capture: struct { identifier: *Node },
    Declarator: struct { mut: bool, type: *Node, name: *Node },
    DeferStmt: struct { capture: ?*Node, body: *Node },
    EnumDecl: struct { name: *Node, members: std.ArrayList(Node) },
    EnumType: struct { members: std.ArrayList(Node) },
    ErrorDecl: struct { name: *Node, members: std.ArrayList(Node) },
    ErrorUnionType: struct { type: *Node, errs: std.ArrayList(Node) },
    ErrorType: struct { members: std.ArrayList(Node) },
    FnCall: struct { callee: *Node, args: std.ArrayList(Node) },
    FnDecl: struct { declarator: *Node, args: std.ArrayList(Node), body: *Node },
    FnType: struct { type: *Node, args: std.ArrayList(Node) },
    ForStmt: struct { condition: *Node, capture: *Node, body: *Node },
    GroupType: struct { _type: *Node },
    GroupExpr: struct { expr: *Node },
    Identifier: struct { value: []const u8 },
    IfStmt: struct { condition: *Node, capture: ?*Node, body: *Node, else_body: ?*Node },
    Literal: struct { type: LiteralKind, value: []const u8 },
    MatchArm: struct { exprs: std.ArrayList(Node), body: *Node },
    MatchStmt: struct { expr: *Node, arms: std.ArrayList(Node) },
    MemberAccess: struct { root: ?*Node, access: *Node },
    ModuleDecl: struct { name: *Node },
    OptionalType: struct { type: *Node },
    OptionalDereference: struct { root: *Node },
    PointerDereference: struct { root: *Node },
    PointerType: struct { type: *Node },
    PrefixExpr: struct { expr: *Node, op: Token },
    Program: struct { pub_decls: std.ArrayList(Node), decls: std.ArrayList(Node) },
    ReferenceCapture: struct { identifier: *Node },
    ReturnStmt: struct { result: ?*Node },
    StructDecl: struct { name: *Node, members: std.ArrayList(Node) },
    StructType: struct { members: std.ArrayList(Node) },
    UseBlock: struct { uses: std.ArrayList(Node) },
    UseStmt: struct { alias: ?*Node, value: *Node },
    VarDecl: struct { declarator: *Node, default: ?*Node },
    WhileStmt: struct { condition: *Node, body: *Node },
    BreakStmt,
    Null,
    Type,
    Undefined,
    Underscore,
    Void,
    pub fn deinit(s: *Node, alloc: std.mem.Allocator) void {
        _ = alloc;
        switch (s) {
            else => {},
        }
    }
};

const Precedence = enum(u8) { none, equals, lessergreater, sum, mult, prefix, call };
