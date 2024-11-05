const std = @import("std");
pub const LiteralType = enum {
    int,
    float,
    string,
};

pub const Node = union(enum) {
    Program: struct { declarations: std.ArrayList(Node), pub_declarations: std.ArrayList(Node) },
    ModuleDeclaration: struct { name: *Node },
    UseDeclaration: struct { import: *Node, alias: ?*Node },
    UseBlock: struct { uses: std.ArrayList(Node) },
    Literal: struct { lit_type: LiteralType, value: []const u8 },
    Identifier: struct { value: []const u8 },
    EnumDeclaration: struct { name: *Node, members: std.ArrayList(Node) },
    EnumMember: struct { value: *Node },
    ErrorDeclaration: struct { name: *Node, members: std.ArrayList(Node) },
    ErrorMember: struct { value: *Node },
    Declaration: void,
    OptionalType: struct { value: *Node },
    PointerType: struct { value: *Node },
    ArrayType: struct { value: *Node },
    VoidType: void,
    FunctionDeclaration: struct { fn_type: *Node, fn_name: *Node, args: std.ArrayList(Node), body: *Node },
    FunctionArg: struct { mut: bool, arg_type: *Node, arg_name: *Node, default_val: ?*Node },
    VariableDeclaration: struct { mut: bool, var_type: *Node, var_name: *Node, default_val: ?*Node },
    Block: struct { stmts: std.ArrayList(Node) },
    Statement: void,
    pub fn deinit(n: *Node, alloc: std.mem.Allocator) void {
        switch (n.*) {
            .Program => |s| {
                for (s.declarations.items) |*d| {
                    d.deinit(alloc);
                }
                s.declarations.deinit();
                for (s.pub_declarations.items) |*d| {
                    d.deinit(alloc);
                }
                s.pub_declarations.deinit();
            },
            .ModuleDeclaration => |s| {
                s.name.deinit(alloc);
                alloc.destroy(s.name);
            },
            .UseDeclaration => |s| {
                s.import.deinit(alloc);
                alloc.destroy(s.import);
                if (s.alias) |a| {
                    a.deinit(alloc);
                    alloc.destroy(a);
                }
            },
            .UseBlock => |s| {
                for (s.uses.items) |*u| {
                    u.deinit(alloc);
                }
                s.uses.deinit();
            },
            .EnumDeclaration => |s| {
                s.name.deinit(alloc);
                alloc.destroy(s.name);
                for (s.members.items) |*m| {
                    m.deinit(alloc);
                }
                s.members.deinit();
            },
            .EnumMember => |s| {
                s.value.deinit(alloc);
                alloc.destroy(s.value);
            },
            .ErrorDeclaration => |s| {
                s.name.deinit(alloc);
                alloc.destroy(s.name);
                for (s.members.items) |*m| {
                    m.deinit(alloc);
                }
                s.members.deinit();
            },
            .ErrorMember => |s| {
                s.value.deinit(alloc);
                alloc.destroy(s.value);
            },
            .OptionalType => |s| {
                s.value.deinit(alloc);
                alloc.destroy(s.value);
            },
            .PointerType => |s| {
                s.value.deinit(alloc);
                alloc.destroy(s.value);
            },
            .ArrayType => |s| {
                s.value.deinit(alloc);
                alloc.destroy(s.value);
            },
            .Identifier => {},
            .Literal => {},
            .Declaration => {},
            .VoidType => {},
            .Statement => {},
            .FunctionDeclaration => |s| {
                s.fn_type.deinit(alloc);
                alloc.destroy(s.fn_type);
                s.fn_name.deinit(alloc);
                alloc.destroy(s.fn_name);
                s.body.deinit(alloc);
                alloc.destroy(s.body);
                for (s.args.items) |*arg| {
                    arg.deinit(alloc);
                }
                s.args.deinit();
            },
            .FunctionArg => |s| {
                s.arg_type.deinit(alloc);
                alloc.destroy(s.arg_type);
                s.arg_name.deinit(alloc);
                alloc.destroy(s.arg_name);
                if (s.default_val) |d| {
                    d.deinit(alloc);
                    alloc.destroy(d);
                }
            },
            .VariableDeclaration => |s| {
                s.var_type.deinit(alloc);
                alloc.destroy(s.var_type);
                s.var_name.deinit(alloc);
                alloc.destroy(s.var_name);
                if (s.default_val) |d| {
                    d.deinit(alloc);
                    alloc.destroy(d);
                }
            },
            .Block => |s| {
                for (s.stmts.items) |*st| {
                    st.deinit(alloc);
                }
                s.stmts.deinit();
            },
        }
    }
    pub fn print(n: Node) void {
        switch (n) {
            .Program => |s| {
                std.debug.print("Program\n", .{});
                std.debug.print("public decls\n", .{});
                for (s.pub_declarations.items) |d| {
                    d.print();
                }
                std.debug.print("-----\n", .{});
                std.debug.print("private decls\n", .{});
                for (s.declarations.items) |d| {
                    d.print();
                }
                std.debug.print("-----\n", .{});
            },
            .ModuleDeclaration => |s| {
                std.debug.print("Module declaration\n", .{});
                std.debug.print("Name: ", .{});
                s.name.print();
            },
            .Literal => |s| {
                std.debug.print("Literal; Type: {s}, Value: {s}\n", .{ switch (s.lit_type) {
                    .int => "int",
                    .float => "float",
                    .string => "string",
                }, s.value });
            },
            .Declaration => {
                std.debug.print("Declaration\n", .{});
            },
            .UseDeclaration => |s| {
                std.debug.print("Use Declaration; import: ", .{});
                s.import.print();
                std.debug.print("alias: ", .{});
                if (s.alias) |a| {
                    a.print();
                } else {
                    std.debug.print("none\n", .{});
                }
            },
            .UseBlock => |s| {
                std.debug.print("Use Block decls: \n", .{});
                for (s.uses.items) |u| {
                    u.print();
                }
                std.debug.print("\n-----\n", .{});
            },
            .EnumDeclaration => |s| {
                std.debug.print("Enum Decl; name: ", .{});
                s.name.print();
                std.debug.print(", members: ", .{});
                for (s.members.items) |m| {
                    m.print();
                }
                std.debug.print("\n-----\n", .{});
            },
            .EnumMember => |s| {
                std.debug.print("Enum member; value: ", .{});
                s.value.print();
            },
            .ErrorDeclaration => |s| {
                std.debug.print("Error Decl; name: ", .{});
                s.name.print();
                std.debug.print(", members: ", .{});
                for (s.members.items) |m| {
                    m.print();
                }
                std.debug.print("\n-----\n", .{});
            },
            .ErrorMember => |s| {
                std.debug.print("Error member; value: ", .{});
                s.value.print();
            },
            .Identifier => |s| {
                std.debug.print("Identifier; Value: {s}", .{s.value});
            },
            .OptionalType => |s| {
                std.debug.print("Optional type; value", .{});
                s.value.print();
            },
            .PointerType => |s| {
                std.debug.print("Pointer type; value", .{});
                s.value.print();
            },
            .ArrayType => |s| {
                std.debug.print("Array type; value", .{});
                s.value.print();
            },
            .FunctionDeclaration => |s| {
                std.debug.print("Function Declaration\n", .{});
                s.fn_type.print();
                std.debug.print("\n", .{});
                s.fn_name.print();
                std.debug.print("\n", .{});
                std.debug.print("Fn Args\n", .{});
                for (s.args.items) |a| {
                    a.print();
                    std.debug.print("\n", .{});
                }
            },
            .FunctionArg => |s| {
                std.debug.print("Function Arg\n", .{});
                std.debug.print("Mutable?: {any}\n", .{s.mut});
                s.arg_type.print();
                std.debug.print("\n", .{});
                s.arg_name.print();
                std.debug.print("\n", .{});
                if (s.default_val) |d| {
                    std.debug.print("Default Val\n", .{});
                    d.print();
                }
            },
            .VariableDeclaration => |s| {
                std.debug.print("Variable Declaration\n", .{});
                std.debug.print("Mutable?: {any}", .{s.mut});
                s.var_type.print();
                std.debug.print("\n", .{});
                s.var_name.print();
                std.debug.print("\n", .{});
                if (s.default_val) |d| {
                    std.debug.print("Default Val\n", .{});
                    d.print();
                    std.debug.print("\n", .{});
                }
            },
            .Block => |s| {
                std.debug.print("Block of Statements\n", .{});
                for (s.stmts.items) |st| {
                    st.print();
                    std.debug.print("\n", .{});
                }
            },
            .VoidType => {
                std.debug.print("Void Type\n", .{});
            },
            .Statement => {
                std.debug.print("Statement\n", .{});
            },
        }
    }
};
