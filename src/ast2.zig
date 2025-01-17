const std = @import("std");
const Token = @import("token.zig").TokenType;
pub const Node = union(enum) {
    Program: struct { pub_decls: std.ArrayList(Node), decls: std.ArrayList(Node) },
    Module: struct { name: *Node },
    Use: struct { alias: ?*Node, import: *Node },
    Struct: struct { name: *Node, members: std.ArrayList(Node) },
    Enum: struct { name: *Node, members: std.ArrayList(Node) },
    Error: struct { name: *Node, members: std.ArrayList(Node) },
    Member: struct { ident: *Node, type: ?*Node, default: ?*Node },
    Var: struct { name: *Node, mut: bool, type: ?*Node, default: ?*Node },
    Fn: struct { name: *Node, type: ?*Node, args: std.ArrayList(Node), body: *Node },
    Ident: struct { value: []const u8 },
};
