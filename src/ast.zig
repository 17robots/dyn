const std = @import("std");

pub const LiteralKind = enum {
    // literals
    string,
    int,
    float,
    char,
    bool,
    null,
    undefined,
};

pub const OperatorKind = enum {
    add,
    sub,
    mul,
    div,
    mod,
    eqeq,
    bangeq,
    lt,
    lte,
    gt,
    gte,
    andand,
    oror,
    dotdot,
};

pub const AssignmentKind = enum {
    normal,
    add,
    sub,
    mul,
    div,
    mod,
    xor,
    @"and",
    @"or",
};

pub const Node = union(enum) {
    Program: struct { pub_decls: std.ArrayList(Node), decls: std.ArrayList(Node) },
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
    ArrayType: struct { type: *Node, number: ?*Node },
    Statement, // remove this eventually
    GroupingExpr: struct { expr: *Node },
    NotExpr: struct { expr: *Node },
    NegateExpr: struct { expr: *Node },
    FlipExpr: struct { expr: *Node },
    ReferenceExpr: struct { expr: *Node },
    PointerDereferenceExpr: struct { expr: *Node },
    OptionalDereferenceExpr: struct { expr: *Node },
    BinaryExpr: struct { left: *Node, op: OperatorKind, right: *Node },
    FnCall: struct { callee: *Node, args: std.ArrayList(Node) },
    MemberAccess: struct { root: ?*Node, access: *Node },
    StructLiteral: struct { initializers: std.ArrayList(Node) },
    StructInitializer: struct { ident: *Node, value: *Node },
    BlockExpr: struct { block: *Node },
    IfExpr: struct { expr: *Node },
    MatchExpr: struct { expr: *Node },
    Void,
    Type,
    Underscore,
    IfStmt: struct { condition: *Node, capture: ?*Node, body: *Node, else_body: ?*Node },
    DeferStmt: struct { capture: ?*Node, stmt: *Node },
    ReturnStmt: struct { expr: *Node },
    ForStmt: struct { expr: *Node, capture: *Node, body: *Node },
    WhileStmt: struct { expr: *Node, body: *Node },
    MatchStmt: struct { to_match: *Node, match_arms: std.ArrayList(Node) },
    MatchArm: struct { branches: std.ArrayList(Node), capture: ?*Node, block: *Node },
    Capture: struct { mut: bool, ident: *Node },
    Assignment: struct { left: *Node, assign: AssignmentKind, right: *Node },
    ArrayIndex: struct { callee: *Node, index: *Node },
    ElseIdentifier: struct { ident: *Node, else_ident: *Node },
    ArrayLiteral: struct { items: std.ArrayList(Node) },
    BreakStmt,
    ErrorUnionType: struct { base_type: *Node, error_types: std.ArrayList(Node) },
    TryStmt: struct { call: *Node },
    CatchStmt: struct { call: *Node, capture: ?*Node, body: *Node },
    CompType: struct { base_type: *Node },
    InlineStmt: struct { base_stmt: *Node },

    pub fn deinit(n: Node, alloc: std.mem.Allocator) void {
        switch (n) {
            .Program => |s| {
                for (s.decls.items) |i| i.deinit(alloc);
                for (s.pub_decls.items) |i| i.deinit(alloc);
                s.decls.deinit();
                s.pub_decls.deinit();
            },
            .ModuleDecl => |s| {
                s.name.deinit(alloc);
                alloc.destroy(s.name);
            },
            .UseBlock => |s| {
                for (s.uses.items) |i| i.deinit(alloc);
                s.uses.deinit();
            },
            .UseStmt => |s| {
                s.value.deinit(alloc);
                alloc.destroy(s.value);
                if (s.alias) |*a| {
                    a.*.deinit(alloc);
                    alloc.destroy(a);
                }
            },
            .Declarator => |s| {
                defer alloc.destroy(s.type);
                defer alloc.destroy(s.name);
                s.name.deinit(alloc);
                s.type.deinit(alloc);
            },
            .Literal, .Identifier, .Statement, .Void, .Type, .Underscore, .BreakStmt => {},
            .StructDecl => |s| {
                s.name.deinit(alloc);
                alloc.destroy(s.name);
                for (s.members.items) |i| {
                    i.deinit(alloc);
                }
                s.members.deinit();
            },
            .EnumDecl => |s| {
                s.name.deinit(alloc);
                alloc.destroy(s.name);
                for (s.members.items) |i| {
                    i.deinit(alloc);
                }
                s.members.deinit();
            },
            .ErrorDecl => |s| {
                s.name.deinit(alloc);
                alloc.destroy(s.name);
                for (s.members.items) |i| {
                    i.deinit(alloc);
                }
                s.members.deinit();
            },
            .StructType => |s| {
                for (s.members.items) |i| {
                    i.deinit(alloc);
                }
                s.members.deinit();
            },
            .EnumType => |s| {
                for (s.members.items) |i| {
                    i.deinit(alloc);
                }
                s.members.deinit();
            },
            .ErrorType => |s| {
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
            .OptionalType => |s| {
                s.type.deinit(alloc);
                alloc.destroy(s.type);
            },
            .ArrayType => |s| {
                s.type.deinit(alloc);
                alloc.destroy(s.type);
                if (s.number) |nu| {
                    nu.deinit(alloc);
                    alloc.destroy(nu);
                }
            },
            .PointerType => |s| {
                s.type.deinit(alloc);
                alloc.destroy(s.type);
            },
            .VarDecl => |s| {
                s.declarator.deinit(alloc);
                alloc.destroy(s.declarator);
                if (s.default_val) |d| {
                    d.deinit(alloc);
                    alloc.destroy(d);
                }
            },
            .FnDecl => |s| {
                s.declarator.deinit(alloc);
                alloc.destroy(s.declarator);
                s.body.deinit(alloc);
                alloc.destroy(s.body);
                for (s.args.items) |i| i.deinit(alloc);
                s.args.deinit();
            },
            .BlockStmt => |s| {
                for (s.stmts.items) |i| i.deinit(alloc);
                s.stmts.deinit();
            },
            .GroupingExpr => |s| {
                s.expr.deinit(alloc);
                alloc.destroy(s.expr);
            },
            .NotExpr => |s| {
                s.expr.deinit(alloc);
                alloc.destroy(s.expr);
            },
            .NegateExpr => |s| {
                s.expr.deinit(alloc);
                alloc.destroy(s.expr);
            },
            .FlipExpr => |s| {
                s.expr.deinit(alloc);
                alloc.destroy(s.expr);
            },
            .ReferenceExpr => |s| {
                s.expr.deinit(alloc);
                alloc.destroy(s.expr);
            },
            .PointerDereferenceExpr => |s| {
                s.expr.deinit(alloc);
                alloc.destroy(s.expr);
            },
            .OptionalDereferenceExpr => |s| {
                s.expr.deinit(alloc);
                alloc.destroy(s.expr);
            },
            .BinaryExpr => |s| {
                s.left.deinit(alloc);
                alloc.destroy(s.left);
                s.right.deinit(alloc);
                alloc.destroy(s.right);
            },
            .FnCall => |s| {
                s.callee.deinit(alloc);
                alloc.destroy(s.callee);
                for (s.args.items) |i| i.deinit(alloc);
                s.args.deinit();
            },
            .MemberAccess => |s| {
                if (s.root) |r| {
                    r.deinit(alloc);
                    alloc.destroy(r);
                }
                s.access.deinit(alloc);
                alloc.destroy(s.access);
            },
            .StructLiteral => |s| {
                for (s.initializers.items) |i| i.deinit(alloc);
                s.initializers.deinit();
            },
            .StructInitializer => |s| {
                s.ident.deinit(alloc);
                alloc.destroy(s.ident);
                s.value.deinit(alloc);
                alloc.destroy(s.value);
            },
            .BlockExpr => |s| {
                s.block.deinit(alloc);
                alloc.destroy(s.block);
            },
            .IfExpr => |s| {
                s.expr.deinit(alloc);
                alloc.destroy(s.expr);
            },
            .MatchExpr => |s| {
                s.expr.deinit(alloc);
                alloc.destroy(s.expr);
            },
            .IfStmt => |s| {
                s.condition.deinit(alloc);
                alloc.destroy(s.condition);
                s.body.deinit(alloc);
                alloc.destroy(s.body);
                if (s.else_body) |eb| {
                    eb.deinit(alloc);
                    alloc.destroy(eb);
                }
                if (s.capture) |c| {
                    c.deinit(alloc);
                    alloc.destroy(c);
                }
            },
            .DeferStmt => |s| {
                s.stmt.deinit(alloc);
                alloc.destroy(s.stmt);
                if (s.capture) |c| {
                    c.deinit(alloc);
                    alloc.destroy(c);
                }
            },
            .ReturnStmt => |s| {
                s.expr.deinit(alloc);
                alloc.destroy(s.expr);
            },
            .ForStmt => |s| {
                s.expr.deinit(alloc);
                alloc.destroy(s.expr);
                s.capture.deinit(alloc);
                alloc.destroy(s.capture);
                s.body.deinit(alloc);
                alloc.destroy(s.body);
            },
            .WhileStmt => |s| {
                s.expr.deinit(alloc);
                alloc.destroy(s.expr);
                s.body.deinit(alloc);
                alloc.destroy(s.body);
            },
            .MatchStmt => |s| {
                s.to_match.deinit(alloc);
                alloc.destroy(s.to_match);
                for (s.match_arms.items) |i| i.deinit(alloc);
                s.match_arms.deinit();
            },
            .MatchArm => |s| {
                s.block.deinit(alloc);
                alloc.destroy(s.block);
                if (s.capture) |c| {
                    c.deinit(alloc);
                    alloc.destroy(c);
                }
                for (s.branches.items) |i| i.deinit(alloc);
                s.branches.deinit();
            },
            .Capture => |s| {
                s.ident.deinit(alloc);
                alloc.destroy(s.ident);
            },
            .Assignment => |s| {
                s.left.deinit(alloc);
                alloc.destroy(s.left);
                s.right.deinit(alloc);
                alloc.destroy(s.right);
            },
            .ArrayIndex => |s| {
                s.callee.deinit(alloc);
                alloc.destroy(s.callee);
                s.index.deinit(alloc);
                alloc.destroy(s.index);
            },
            .ElseIdentifier => |s| {
                s.ident.deinit(alloc);
                alloc.destroy(s.ident);
                s.else_ident.deinit(alloc);
                alloc.destroy(s.else_ident);
            },
            .ArrayLiteral => |s| {
                for (s.items.items) |i| i.deinit(alloc);
                s.items.deinit();
            },
            .ErrorUnionType => |s| {
                s.base_type.deinit(alloc);
                alloc.destroy(s.base_type);
                for (s.error_types.items) |e| {
                    e.deinit(alloc);
                }
                s.error_types.deinit();
            },
            .TryStmt => |s| {
                s.call.deinit(alloc);
                alloc.destroy(s.call);
            },
            .CatchStmt => |s| {
                s.call.deinit(alloc);
                alloc.destroy(s.call);
                if (s.capture) |c| {
                    c.deinit(alloc);
                    alloc.destroy(c);
                }
                s.body.deinit(alloc);
                alloc.destroy(s.body);
            },
            .CompType => |s| {
                s.base_type.deinit(alloc);
                alloc.destroy(s.base_type);
            },
            .InlineStmt => |s| {
                s.base_stmt.deinit(alloc);
                alloc.destroy(s.base_stmt);
            },
        }
    }
    pub fn print(n: Node) void {
        switch (n) {
            .Program => |s| {
                for (s.decls.items) |i| i.print();
                for (s.pub_decls.items) |i| i.print();
            },
            .ModuleDecl => |s| {
                std.debug.print("Module Declaration\n", .{});
                std.debug.print("Name: \n", .{});
                s.name.print();
            },
            .UseStmt => |s| {
                std.debug.print("Use Statement\n", .{});
                std.debug.print("Value: \n", .{});
                s.value.print();
                if (s.alias) |a| {
                    std.debug.print("Alias: ", .{});
                    a.print();
                }
            },
            .UseBlock => |s| {
                std.debug.print("Use Block\n", .{});
                for (s.uses.items) |i| i.print();
            },
            .Declarator => |s| {
                std.debug.print("Declarator\n", .{});
                std.debug.print("Type: \n", .{});
                s.type.print();
                std.debug.print("Name: \n", .{});
                s.name.print();
            },
            .Literal => |s| {
                std.debug.print("Literal\n", .{});
                switch (s.kind) {
                    .string => std.debug.print("Type: string\n", .{}),
                    .int => std.debug.print("Type: int\n", .{}),
                    .float => std.debug.print("Type: float\n", .{}),
                    .char => std.debug.print("Type: char\n", .{}),
                    .bool => std.debug.print("Type: bool\n", .{}),
                    .null => std.debug.print("Type: null\n", .{}),
                    .undefined => std.debug.print("Type: undefined\n", .{}),
                }
                std.debug.print("Value: {s}\n", .{s.value});
            },
            .Identifier => |s| {
                std.debug.print("Identifier\n", .{});
                std.debug.print("Value: {s}\n", .{s.value});
            },
            .Statement => { // remove this after
                std.debug.print("Statement\n", .{});
            },
            .StructDecl => |s| {
                std.debug.print("Struct Decl\n", .{});
                std.debug.print("Name: \n", .{});
                s.name.print();
                for (s.members.items) |i| i.print();
            },
            .EnumDecl => |s| {
                std.debug.print("Enum Decl\n", .{});
                std.debug.print("Name: \n", .{});
                s.name.print();
                for (s.members.items) |i| {
                    std.debug.print("Member: ", .{});
                    i.print();
                }
            },
            .ErrorDecl => |s| {
                std.debug.print("Error Decl\n", .{});
                std.debug.print("Name: \n", .{});
                s.name.print();
                for (s.members.items) |i| {
                    std.debug.print("Member: ", .{});
                    i.print();
                }
            },
            .StructType => |s| {
                std.debug.print("Struct Type\n", .{});
                for (s.members.items) |i| {
                    std.debug.print("Member: ", .{});
                    i.print();
                }
            },
            .EnumType => |s| {
                std.debug.print("Enum Type\n", .{});
                for (s.members.items) |i| {
                    std.debug.print("Member: ", .{});
                    i.print();
                }
            },
            .ErrorType => |s| {
                std.debug.print("Error Type\n", .{});
                for (s.members.items) |i| i.print();
            },
            .TypeDecl => |s| {
                std.debug.print("Type Decl\n", .{});
                s.name.print();
                s.type.print();
            },
            .FnType => |s| {
                std.debug.print("Fn Type\n", .{});
                s.type.print();
                for (s.args.items) |i| {
                    i.print();
                }
            },
            .OptionalType => |s| {
                std.debug.print("Optional Type\n", .{});
                std.debug.print("Type: ", .{});
                s.type.print();
            },
            .ArrayType => |s| {
                std.debug.print("Array Type\n", .{});
                s.type.print();
                if (s.number) |nu| nu.print();
            },
            .PointerType => |s| {
                std.debug.print("Pointer Type\n", .{});
                std.debug.print("Type: ", .{});
                s.type.print();
            },
            .VarDecl => |s| {
                std.debug.print("Var Declaration\n", .{});
                s.declarator.print();
                if (s.default_val) |d| {
                    std.debug.print("Default Val: ", .{});
                    d.print();
                }
            },
            .FnDecl => |s| {
                std.debug.print("Fn Declaration\n", .{});
                s.declarator.print();
                for (s.args.items) |i| {
                    std.debug.print("Arg: ", .{});
                    i.print();
                }
                std.debug.print("Body: ", .{});
                s.body.print();
            },
            .BlockStmt => |s| {
                std.debug.print("Block Stmt\n", .{});
                for (s.stmts.items) |i| i.print();
            },
            .Void => {
                std.debug.print("Void\n", .{});
            },
            .Underscore => {
                std.debug.print("Underscore\n", .{});
            },
            .GroupingExpr => |s| {
                std.debug.print("Grouping Expr\n", .{});
                std.debug.print("Expr: ", .{});
                s.expr.print();
            },
            .NotExpr => |s| {
                std.debug.print("Not Expr\n", .{});
                std.debug.print("Expr: ", .{});
                s.expr.print();
            },
            .NegateExpr => |s| {
                std.debug.print("Negate Expr\n", .{});
                std.debug.print("Expr: ", .{});
                s.expr.print();
            },
            .FlipExpr => |s| {
                std.debug.print("Flip Expr\n", .{});
                std.debug.print("Expr: ", .{});
                s.expr.print();
            },
            .ReferenceExpr => |s| {
                std.debug.print("Reference Expr\n", .{});
                std.debug.print("Expr: ", .{});
                s.expr.print();
            },
            .PointerDereferenceExpr => |s| {
                std.debug.print("Pointer Dereference Expr\n", .{});
                std.debug.print("Expr: ", .{});
                s.expr.print();
            },
            .OptionalDereferenceExpr => |s| {
                std.debug.print("Optional Dereference Expr\n", .{});
                std.debug.print("Expr: ", .{});
                s.expr.print();
            },
            .BinaryExpr => |s| {
                std.debug.print("Binary Expr\n", .{});
                std.debug.print("Left Expr: ", .{});
                s.left.print();
                std.debug.print("Op: {any}\n", .{s.op});
                std.debug.print("Right Expr: ", .{});
                s.right.print();
            },
            .FnCall => |s| {
                std.debug.print("Fn Call\n", .{});
                std.debug.print("Callee: ", .{});
                s.callee.print();
                for (s.args.items) |i| {
                    std.debug.print("Arg: ", .{});
                    i.print();
                }
            },
            .MemberAccess => |s| {
                std.debug.print("Member Access\n", .{});
                if (s.root) |r| {
                    std.debug.print("Root: ", .{});
                    r.print();
                }
                std.debug.print("Access: ", .{});
                s.access.print();
            },
            .StructLiteral => |s| {
                std.debug.print("Struct Literal\n", .{});
                for (s.initializers.items) |i| i.print();
            },
            .StructInitializer => |s| {
                std.debug.print("Struct Intializer\n", .{});
                s.ident.print();
                s.value.print();
            },
            .BlockExpr => |s| {
                std.debug.print("Block Expr\n", .{});
                s.block.print();
            },
            .IfExpr => |s| {
                std.debug.print("If Expr\n", .{});
                s.expr.print();
            },
            .MatchExpr => |s| {
                std.debug.print("Match Expr\n", .{});
                s.expr.print();
            },
            .IfStmt => |s| {
                std.debug.print("If Stmt\n", .{});
                s.condition.print();
                if (s.capture) |eb| eb.print();
                s.body.print();
                if (s.else_body) |eb| eb.print();
            },
            .DeferStmt => |s| {
                std.debug.print("Defer Stmt\n", .{});
                if (s.capture) |c| c.print();
                s.stmt.print();
            },
            .ReturnStmt => |s| {
                std.debug.print("Return Stmt\n", .{});
                s.expr.print();
            },
            .ForStmt => |s| {
                std.debug.print("For Stmt\n", .{});
                s.expr.print();
                s.capture.print();
                s.body.print();
            },
            .WhileStmt => |s| {
                std.debug.print("While Stmt\n", .{});
                s.expr.print();
                s.body.print();
            },
            .MatchStmt => |s| {
                std.debug.print("Match Stmt\n", .{});
                s.to_match.print();
                for (s.match_arms.items) |i| i.print();
            },
            .MatchArm => |s| {
                std.debug.print("Match Arm\n", .{});
                for (s.branches.items) |i| i.print();
                if (s.capture) |c| c.print();
                s.block.print();
            },
            .Capture => |s| {
                std.debug.print("Capture\n", .{});
                std.debug.print("Mut: {any}\n", .{s.mut});
                s.ident.print();
            },
            .Assignment => |s| {
                std.debug.print("Assignment\n", .{});
                s.left.print();
                std.debug.print("Assignment: {any}\n", .{s.assign});
                s.right.print();
            },
            .ArrayIndex => |s| {
                std.debug.print("Array Index\n", .{});
                s.callee.print();
                s.index.print();
            },
            .ElseIdentifier => |s| {
                std.debug.print("Else Identifier\n", .{});
                s.ident.print();
                s.else_ident.print();
            },
            .ArrayLiteral => |s| {
                std.debug.print("Array Literal\n", .{});
                for (s.items.items) |i| i.print();
            },
            .BreakStmt => {
                std.debug.print("Break Stmt\n", .{});
            },
            .ErrorUnionType => |s| {
                std.debug.print("Error Union Type\n", .{});
                s.base_type.print();
                for (s.error_types.items) |e| e.print();
            },
            .TryStmt => |s| {
                std.debug.print("Try Stmt\n", .{});
                s.call.print();
            },
            .CatchStmt => |s| {
                std.debug.print("Catch Stmt\n", .{});
                s.call.print();
                if (s.capture) |c| c.print();
                s.body.print();
            },
            .CompType => |s| {
                std.debug.print("Comp Type\n", .{});
                s.base_type.print();
            },
            .InlineStmt => |s| {
                std.debug.print("Inline Stmt\n", .{});
                s.base_stmt.print();
            },
            .Type => {
                std.debug.print("Type\n", .{});
            },
        }
    }
};
