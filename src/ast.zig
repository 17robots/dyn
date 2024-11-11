const std = @import("std");
pub const LiteralType = enum {
    int,
    float,
    string,
};

pub const Node = union(enum) {
    Program: struct { declarations: std.ArrayList(Node), pub_declarations: std.ArrayList(Node) },

    Declaration: void,
    UseDeclaration: struct { import: *Node, alias: ?*Node },
    ModuleDeclaration: struct { name: *Node },
    EnumDeclaration: struct { name: *Node, members: std.ArrayList(Node) },
    ErrorDeclaration: struct { name: *Node, members: std.ArrayList(Node) },
    VariableDeclaration: struct { var_declarator: *Node, default_val: ?*Node },
    FunctionDeclaration: struct { fn_declarator: *Node, args: std.ArrayList(Node), body: *Node },
    StructDeclaration: struct { name: *Node, members: std.ArrayList(Node) },
    TypeDeclaration: struct { name: *Node, typing: *Node },

    PointerType: struct { value: *Node },
    ArrayType: struct { value: *Node },
    VoidType: void,
    ErrorType: struct { members: std.ArrayList(Node) },
    EnumType: struct { members: std.ArrayList(Node) },
    OptionalType: struct { value: *Node },

    Expression: void,
    Literal: struct { lit_type: LiteralType, value: []const u8 },
    Identifier: struct { value: []const u8 },

    Statement: void,
    Block: struct { stmts: std.ArrayList(Node) },

    ErrorMember: struct { value: *Node },
    EnumMember: struct { value: *Node },
    UseBlock: struct { uses: std.ArrayList(Node) },
    Declarator: struct { mut: bool, declarator_type: *Node, declarator_name: *Node },
    DeclaratorList: struct { mut: bool, declarator_type: *Node, declarator_names: std.ArrayList(Node) },
    FunctionArg: struct { arg_declarator: *Node, default_val: ?*Node },

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
            .Expression => {},
            .FunctionDeclaration => |s| {
                s.fn_declarator.deinit(alloc);
                alloc.destroy(s.fn_declarator);
                s.body.deinit(alloc);
                for (s.args.items) |*arg| {
                    arg.deinit(alloc);
                }
                s.args.deinit();
                alloc.destroy(s.body);
            },
            .FunctionArg => |s| {
                s.arg_declarator.deinit(alloc);
                alloc.destroy(s.arg_declarator);
                if (s.default_val) |d| {
                    d.deinit(alloc);
                    alloc.destroy(d);
                }
            },
            .VariableDeclaration => |s| {
                s.var_declarator.deinit(alloc);
                alloc.destroy(s.var_declarator);
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
            .Declarator => |s| {
                s.declarator_type.deinit(alloc);
                alloc.destroy(s.declarator_type);
                s.declarator_name.deinit(alloc);
                alloc.destroy(s.declarator_name);
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
                std.debug.print("Function Declarator: ", .{});
                s.fn_declarator.print();
                std.debug.print("\n", .{});
                std.debug.print("Fn Args\n", .{});
                for (s.args.items) |a| {
                    a.print();
                    std.debug.print("\n", .{});
                }
                s.body.print();
                std.debug.print("\n", .{});
            },
            .FunctionArg => |s| {
                std.debug.print("Function Arg\n", .{});
                std.debug.print("Arg declarator\n", .{});
                s.arg_declarator.print();
                std.debug.print("\n", .{});
                if (s.default_val) |d| {
                    std.debug.print("Default Val\n", .{});
                    d.print();
                }
            },
            .VariableDeclaration => |s| {
                std.debug.print("Variable Declaration\n", .{});
                std.debug.print("Variable declarator\n", .{});
                s.var_declarator.print();
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
            .Expression => {
                std.debug.print("Expression\n", .{});
            },
            .Declarator => |s| {
                std.debug.print("Declarator\n", .{});
                std.debug.print("Mut: {any}\n", .{s.mut});
                std.debug.print("Type: ", .{});
                s.declarator_type.print();
                std.debug.print("\n", .{});
                std.debug.print("Name: \n", .{});
                s.declarator_name.print();
                std.debug.print("\n", .{});
            },
        }
    }
};
