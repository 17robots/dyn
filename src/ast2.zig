const std = @import("std");

pub const LiteralKind = enum {
    string,
};

pub const Node = union(enum) {
    Program: struct {
        pub_decls: std.ArrayList(Node),
        decls: std.ArrayList(Node),
    },
    ModuleDecl: struct { name: *Node },
    UseStmt: struct { alias: ?*Node, value: *Node },
    UseBlock: struct { uses: std.ArrayList(Node) },
    Declarator: struct { mut: bool, type: *Node, name: *Node },
    Literal: struct { kind: LiteralKind, value: []const u8 },
    Identifier: struct { value: []const u8 },
    StructDecl: struct { name: *Node, members: std.ArrayList(Node) },
    EnumDecl: struct { name: *Node, members: std.ArrayList(Node) },
    ErrorDecl: struct { name: *Node, members: std.ArrayList(Node) },
    TypeDecl: struct { name: *Node, type: *Node },
    VarDecl: struct { declarator: *Node, default_val: ?*Node },
    FnDecl: struct { declarator: *Node, args: std.ArrayList(Node), body: *Node },
    BlockStmt: struct { stmts: std.ArrayList(Node) },
    FnType: struct { type: *Node, args: std.ArrayList(Node) },
    EnumType: struct { members: std.ArrayList(Node) },
    ErrorType: struct { members: std.ArrayList(Node) },
    StructType: struct { members: std.ArrayList(Node) },
    PointerType: struct { type: *Node },
    OptionalType: struct { type: *Node },
    ArrayType: struct { type: *Node },
    Statement, // remove this eventually
    Expression,

    pub fn deinit(n: Node, alloc: std.mem.Allocator) void {
        switch (n) {
            .Program => |s| {
                defer s.decls.deinit();
                defer s.pub_decls.deinit();
                for (s.decls.items) |i| i.deinit(alloc);
                for (s.pub_decls.items) |i| i.deinit(alloc);
            },
            .ModuleDecl => |s| {
                s.name.deinit(alloc);
                alloc.destroy(s.name);
            },
            .UseStmt => |s| {
                _ = s;
            },
            .Declarator => |s| {
                defer alloc.destroy(s.type);
                defer alloc.destroy(s.name);
                s.name.deinit(alloc);
                s.type.deinit(alloc);
            },
            .Literal, .Identifier, .Statement, .Expression => {},
            .StructDecl, .EnumDecl, .ErrorDecl => |s| {
                s.name.deinit(alloc);
                alloc.destroy(s.name);
                for (s.members.items) |i| {
                    i.deinit(alloc);
                }
                s.members.deinit();
            },
            .StructType, .EnumType, .ErrorType => |s| {
                for (s.members.items) |i| {
                    i.deinit(alloc);
                }
                s.members.deinit();
            },
            .TypeDecl => |s| {
                s.name.deinit(alloc);
                alloc.destroy(s.name);
                s.type.deinit(alloc);
                alloc.destroy(s.type);
            },
            .FnType => |s| {
                s.type.deinit(alloc);
                alloc.destroy(s.type);
                for (s.args.items) |i| {
                    i.deinit(alloc);
                }
                s.args.deinit();
            },
            .OptionalType, .ArrayType, .PointerType => |s| {
                s.type.deinit(alloc);
                alloc.destroy(s.type);
            },
        }
    }
};
