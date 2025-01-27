const std = @import("std");
const Token = @import("token.zig").TokenType;
pub const LiteralKind = enum {
    string,
    int,
    float,
    boolean,
    char,
    null,
    undefined,
    pub fn to_string(s: LiteralKind) []const u8 {
        return switch (s) {
            .string => "string",
            .int => "int",
            .float => "float",
            .boolean => "boolean",
            .char => "char",
            .null => "null",
            .undefined => "undefined",
        };
    }
};
pub const Op = enum {
    add,
    addeq,
    sub,
    subeq,
    mul,
    muleq,
    div,
    diveq,
    mod,
    modeq,
    xor,
    xoreq,
    @"and",
    andeq,
    @"or",
    oreq,
    pub fn to_string(s: Op) []const u8 {
        return switch (s) {
            .add => "add",
            .addeq => "addeq",
            .sub => "sub",
            .subeq => "subeq",
            .mul => "mul",
            .muleq => "muleq",
            .div => "div",
            .diveq => "diveq",
            .mod => "mod",
            .modeq => "modeq",
            .xor => "xor",
            .xoreq => "xoreq",
            .@"and" => "and",
            .andeq => "andeq",
            .@"or" => "or",
            .oreq => "oreq",
        };
    }
};
pub const Node = union(enum) {
    Program: struct { pub_decls: std.ArrayList(Node), decls: std.ArrayList(Node) },
    Module: struct { name: *Node },
    Use: struct { alias: ?*Node, import: *Node },
    Struct: struct { pack: bool, name: ?*Node, members: std.ArrayList(Node) },
    Enum: struct { name: ?*Node, members: std.ArrayList(Node) },
    Error: struct { name: ?*Node, members: std.ArrayList(Node) },
    Member: struct { ident: std.ArrayList(Node), type: ?*Node, default: ?*Node },
    Var: struct { names: std.ArrayList(Node), mut: bool, type: ?*Node, default: ?*Node },
    Fn: struct { name: ?*Node, type: ?*Node, args: std.ArrayList(Node), body: *Node },
    Ident: struct { value: []const u8 },
    GroupType: struct { type: *Node },
    ArrayType: struct { type: *Node },
    OptionalType: struct { type: *Node },
    PointerType: struct { type: *Node },
    Block: struct { label: ?*Node, stmts: std.ArrayList(Node) },
    MemberAccess: struct { accessed: *Node, member: *Node },
    While: struct { condition: *Node, capture: ?*Node, body: *Node },
    For: struct { condition: std.ArrayList(Node), capture: ?*Node, body: *Node },
    Match: struct { expr: *Node, branches: std.ArrayList(Node) },
    MatchBranch: struct { exprs: std.ArrayList(Node), result: *Node },
    If: struct { condition: *Node, capture: ?*Node, body: *Node, if_next: ?*Node },
    Capture: struct { captures: std.ArrayList(Node) },
    CaptureMember: struct { ident: *Node, mut: bool },
    PointerDereference: struct { expr: *Node },
    OptionalDereference: struct { expr: *Node },
    FnCall: struct { caller: *Node, args: std.ArrayList(Node) },
    Literal: struct { kind: LiteralKind, value: []const u8 },
    Binary: struct { l: *Node, op: Op, r: *Node },
    Unary: struct { op: Op, r: *Node },
    Group: struct { expr: *Node },
    ArrayIndex: struct { ident: *Node, index: *Node },
    Arg: struct { name: *Node, type: *Node, default: ?*Node },
    Type,
    Underscore,
    pub fn print(s: Node) void {
        switch (s) {
            .Program => |a| {
                std.debug.print("Program\n", .{});
                std.debug.print("Public Declarations\n", .{});
                for (a.pub_decls.items) |i| i.print();
                std.debug.print("Private Declarations\n", .{});
                for (a.decls.items) |i| i.print();
            },
            .Module => |a| {
                std.debug.print("Module:\n", .{});
                a.name.print();
            },
            .Use => |a| {
                std.debug.print("Use: ", .{});
                if (a.alias) |i| i.print();
                a.import.print();
            },
            .Struct => |a| {
                std.debug.print("Struct, packed: {}\n", .{a.pack});
                if (a.name) |i| i.print();
                std.debug.print("\nMembers\n", .{});
                for (a.members.items) |i| i.print();
            },
            .Enum => |a| {
                std.debug.print("Enum\n", .{});
                if (a.name) |i| i.print();
                std.debug.print("\nMembers\n", .{});
                for (a.members.items) |i| i.print();
            },
            .Error => |a| {
                std.debug.print("Error\n", .{});
                if (a.name) |i| i.print();
                std.debug.print("\nMembers\n", .{});
                for (a.members.items) |i| i.print();
            },
            .Member => |a| {
                std.debug.print("Member", .{});
                for (a.ident.items) |i| i.print();
                if (a.type) |i| i.print();
                if (a.default) |i| i.print();
            },
            .Var => |a| {
                std.debug.print("Var, mut: {}\n", .{a.mut});
                for (a.names.items) |i| i.print();
                if (a.type) |i| i.print();
                if (a.default) |i| i.print();
            },
            .Fn => |a| {
                std.debug.print("Fn", .{});
                if (a.name) |i| i.print() else std.debug.print("Literal\n", .{});
                if (a.type) |i| i.print() else std.debug.print("Void", .{});
                for (a.args.items) |i| i.print();
                a.body.print();
            },
            .Ident => |a| std.debug.print("Ident: {s}", .{a.value}),
            .GroupType => |a| {
                std.debug.print("GroupType\n", .{});
                a.type.print();
            },
            .ArrayType => |a| {
                std.debug.print("ArrayType\n", .{});
                a.type.print();
            },
            .OptionalType => |a| {
                std.debug.print("OptionalType\n", .{});
                a.type.print();
            },
            .PointerType => |a| {
                std.debug.print("PointerType\n", .{});
                a.type.print();
            },
            .Block => |a| {
                std.debug.print("Block\n", .{});
                if (a.label) |i| i.print();
                for (a.stmts.items) |i| i.print();
            },
            .MemberAccess => |a| {
                std.debug.print("MemberAccess\n", .{});
                a.accessed.print();
                a.member.print();
            },
            .While => |a| {
                std.debug.print("While\n", .{});
                a.condition.print();
                if (a.capture) |i| i.print();
                a.body.print();
            },
            .For => |a| {
                std.debug.print("For\n", .{});
                for (a.condition.items) |i| i.print();
                if (a.capture) |i| i.print();
                a.body.print();
            },
            .Match => |a| {
                std.debug.print("Match\n", .{});
                a.expr.print();
                for (a.branches.items) |i| i.print();
            },
            .MatchBranch => |a| {
                std.debug.print("Match Branch\n", .{});
                for (a.exprs.items) |i| i.print();
                a.result.print();
            },
            .If => |a| {
                std.debug.print("If\n", .{});
                a.condition.print();
                if (a.capture) |i| i.print();
                a.body.print();
                if (a.if_next) |i| i.print();
            },
            .Capture => |a| {
                std.debug.print("Capture\n", .{});
                for (a.captures.items) |i| i.print();
            },
            .CaptureMember => |a| {
                std.debug.print("Capture Member: mut {}\n", .{a.mut});
                a.ident.print();
            },
            .PointerDereference => |a| {
                std.debug.print("Pointer dereference\n", .{});
                a.expr.print();
            },
            .OptionalDereference => |a| {
                std.debug.print("Optional dereference\n", .{});
                a.expr.print();
            },
            .FnCall => |a| {
                std.debug.print("Fn Call\n", .{});
                a.caller.print();
                for (a.args.items) |i| i.print();
            },
            .Literal => |a| std.debug.print("Literal: {s}, {s}\n", .{ a.kind.to_string(), a.value }),
            .Binary => |a| {
                std.debug.print("Binary\n", .{});
                a.l.print();
                std.debug.print("Op: {s}\n", .{a.op.to_string()});
                a.r.print();
            },
            .Unary => |a| {
                std.debug.print("Unary\n", .{});
                std.debug.print("Op: {s}\n", .{a.op.to_string()});
                a.r.print();
            },
            .Group => |a| {
                std.debug.print("Grouped Expression\n", .{});
                a.expr.print();
            },
            .ArrayIndex => |a| {
                std.debug.print("Array Index\n", .{});
                a.ident.print();
                a.index.print();
            },
            .Arg => |a| {
                std.debug.print("Arg\n", .{});
                a.name.print();
                a.type.print();
                if (a.default) |i| i.print();
            },
            .Type => std.debug.print("Type\n", .{}),
            .Underscore => std.debug.print("Underscore", .{}),
        }
    }
    pub fn deinit(s: Node, alloc: std.mem.Allocator) void {
        switch (s) {
            .Program => |a| {
                defer a.pub_decls.deinit();
                defer a.decls.deinit();
                for (a.pub_decls.items) |i| i.deinit();
                for (a.decls.items) |i| i.deinit();
            },
            .Use => |a| {
                a.import.deinit(alloc);
                alloc.destroy(a.import);
                if (a.alias) |i| {
                    i.deinit();
                    alloc.destroy(i);
                }
            },
            .Struct => |a| {
                if (a.name) |i| {
                    i.deinit(alloc);
                    alloc.destroy(i);
                }
                for (a.members.items) |i| i.deinit();
                a.members.deinit();
            },
            .Enum => |a| {
                if (a.name) |i| {
                    i.deinit(alloc);
                    alloc.destroy(i);
                }
                for (a.members.items) |i| i.deinit();
                a.members.deinit();
            },
            .Error => |a| {
                if (a.name) |i| {
                    i.deinit(alloc);
                    alloc.destroy(i);
                }
                for (a.members.items) |i| i.deinit();
                a.members.deinit();
            },
            .Member => |a| {
                for (a.ident.items) |i| i.deinit();
                a.ident.deinit();
                if (a.type) |i| {
                    i.deinit();
                    alloc.destroy(i);
                }
                if (a.default) |i| {
                    i.deinit();
                    alloc.destroy(i);
                }
            },
            .Var => |a| {
                for (a.names.items) |i| i.deinit(alloc);
                a.names.deinit();
                if (a.default) |i| {
                    i.deinit(alloc);
                    alloc.destroy(i);
                }
                if (a.type) |i| {
                    i.deinit(alloc);
                    alloc.destroy(i);
                }
            },
            .Fn => |a| {
                if (a.name) |i| {
                    i.deinit(alloc);
                    alloc.destroy(i);
                }
                if (a.type) |i| {
                    i.deinit(alloc);
                    alloc.destroy(i);
                }
                for (a.args.items) |i| i.deinit(alloc);
                a.args.deinit();
                a.body.deinit(alloc);
                alloc.destroy(a.body);
            },
            .GroupType => |a| {
                a.type.deinit(alloc);
                alloc.destroy(a.type);
            },
            .ArrayType => |a| {
                a.type.deinit(alloc);
                alloc.destroy(a.type);
            },
            .OptionalType => |a| {
                a.type.deinit(alloc);
                alloc.destroy(a.type);
            },
            .PointerType => |a| {
                a.type.deinit(alloc);
                alloc.destroy(a.type);
            },
            .Block => |a| {
                if (a.label) |i| {
                    i.deinit(alloc);
                    alloc.destroy(i);
                }
                for (a.stmts.items) |i| i.deinit();
                a.stmts.deinit();
            },
            .MemberAccess => |a| {
                a.accessed.deinit(alloc);
                alloc.destroy(a.accessed);
                a.member.deinit(alloc);
                alloc.destroy(a.member);
            },
            .While => |a| {
                a.condition.deinit(alloc);
                alloc.destroy(a.condition);
                if (a.capture) |i| {
                    i.deinit(alloc);
                    alloc.destroy(i);
                }
                a.body.deinit(alloc);
                alloc.destroy(a.body);
            },
            .For => |a| {
                for (a.condition.items) |i| i.deinit();
                a.condition.deinit();
                if (a.capture) |i| {
                    i.deinit(alloc);
                    alloc.destroy(i);
                }
                a.body.deinit(alloc);
                alloc.destroy(a.body);
            },
            .Match => |a| {
                a.expr.deinit(alloc);
                alloc.destroy(a.expr);
                for (a.branches.items) |i| i.deinit();
                a.branches.deinit();
            },
            .MatchBranch => |a| {
                a.result.deinit(alloc);
                alloc.destroy(a.result);
                for (a.exprs.items) |i| i.deinit();
                a.exprs.deinit();
            },
            .If => |a| {
                a.condition.deinit(alloc);
                alloc.destroy(a.condition);
                a.body.deinit(alloc);
                alloc.destroy(a.body);
                if (a.capture) |i| {
                    i.deinit(alloc);
                    alloc.destroy(i);
                }
                if (a.if_next) |i| {
                    i.deinit(alloc);
                    alloc.destroy(i);
                }
            },
            .Capture => |a| {
                for (a.captures.items) |i| i.deinit();
                a.captures.deinit();
            },
            .CaptureMember => |a| {
                a.ident.deinit(alloc);
                alloc.destroy(a.ident);
            },
            .PointerDereference => |a| {
                a.expr.deinit(alloc);
                alloc.destroy(a.expr);
            },
            .OptionalDereference => |a| {
                a.expr.deinit(alloc);
                alloc.destroy(a.expr);
            },
            .FnCall => |a| {
                a.caller.deinit(alloc);
                alloc.destroy(a.caller);
                for (a.args.items) |i| i.deinit(alloc);
                a.args.deinit();
            },
            .Binary => |a| {
                a.l.deinit(alloc);
                alloc.destroy(a.l);
                a.r.deinit(alloc);
                alloc.destroy(a.r);
            },
            .Unary => |a| {
                a.r.deinit(alloc);
                alloc.destroy(a.r);
            },
            .Group => |a| {
                a.expr.deinit(alloc);
                alloc.destroy(a.expr);
            },
            .ArrayIndex => |a| {
                a.ident.deinit(alloc);
                alloc.destroy(a.ident);
                a.index.deinit(alloc);
                alloc.destroy(a.index);
            },
            .Arg => |a| {
                a.name.deinit(alloc);
                alloc.destroy(a.name);
                a.type.deinit(alloc);
                alloc.destroy(a.type);
                if (a.default) |i| {
                    i.deinit(alloc);
                    alloc.destroy(i);
                }
            },
            .Type, .Underscore, .Module, .Ident, .Literal => {},
        }
    }
};
