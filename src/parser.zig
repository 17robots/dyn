const std = @import("std");
const ast = @import("ast.zig");
const Lexer = @import("lexer.zig");
const token = @import("token.zig");
const errors = @import("errors.zig");
const Node = ast.Node;
const LiteralKind = ast.LiteralKind;
const OperatorKind = ast.OperatorKind;
const AssignmentKind = ast.AssignmentKind;

const Self = @This();
l: Lexer,
allocator: std.mem.Allocator,

const Precedence = enum(u8) {
    none,
    @"or",
    @"and",
    equals,
    compare,
    add,
    mul,
    postfix,
    primary,
};

pub fn init(alloc: std.mem.Allocator, b: []const u8) Self {
    return Self{ .l = Lexer.init(b), .allocator = alloc };
}
pub fn program(s: *Self) anyerror!Node {
    s.l.next_tok();
    var pub_decls = try s.create_node_list();
    var decls = try s.create_node_list();
    try decls.append(try s.module_declaration());
    while (s.l.tok.? != .eof) {
        switch (s.l.tok.?) {
            .@"pub" => {
                _ = try s.eat(.@"pub");
                try pub_decls.append(switch (s.l.tok.?) {
                    .use => try s.use_decl(),
                    else => try s.decl(),
                });
            },
            else => try decls.append(switch (s.l.tok.?) {
                .use => try s.use_decl(),
                else => try s.decl(),
            }),
        }
    }
    return Node{ .Program = .{ .pub_decls = pub_decls, .decls = decls } };
}
fn module_declaration(s: *Self) anyerror!Node {
    _ = try s.eat(.module);
    const name = try s.create_node_ptr(Node{ .Literal = .{ .kind = .string, .value = try s.eat(.string) } });
    _ = try s.eat(.semicolon);
    return Node{ .ModuleDecl = .{ .name = name } };
}
fn use_decl(s: *Self) anyerror!Node {
    _ = try s.eat(.use);
    return switch (s.l.tok.?) {
        .lbrace => try s.use_block(),
        else => try s.use_stmt(true),
    };
}
fn use_block(s: *Self) anyerror!Node {
    var uses = try s.create_node_list();
    try s.loop_read(.lbrace, .rbrace, .comma, struct {
        fn func(_uses: *std.ArrayList(Node), _s: *Self) !void {
            try _uses.append(try _s.use_stmt(false));
        }
    }.func, .{ &uses, s });
    return Node{ .UseBlock = .{ .uses = uses } };
}
fn use_stmt(s: *Self, semicolon: bool) anyerror!Node {
    const alias = switch (s.l.tok.?) {
        .identifier => try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } }),
        else => null,
    };
    const import = try s.create_node_ptr(Node{ .Literal = .{ .kind = .string, .value = try s.eat(.string) } });
    if (semicolon) _ = try s.eat(.semicolon);
    return Node{ .UseStmt = .{ .alias = alias, .value = import } };
}
fn var_decl(s: *Self, _declarator: *Node) anyerror!ast.Node {
    var default: ?*Node = null;
    switch (s.l.tok.?) {
        .eq => {
            _ = try s.eat(.eq);
            default = try s.create_node_ptr(switch (_declarator.*) {
                .Declarator => |d| blk: {
                    break :blk switch (d.type.*) {
                        .Type => try s.type_(),
                        else => try s.expr(.none),
                    };
                },
                else => return errors.Error.ParserError,
            });
        },
        else => switch (_declarator.*) {
            .Declarator => |d| {
                if (!d.mut) {} // error out because var will never be mutatable
            },
            else => {}, // error out cause not declarator
        },
    }
    return Node{ .VarDecl = .{ .declarator = _declarator, .default_val = default } };
}
fn fn_decl(s: *Self, _declarator: *Node) anyerror!ast.Node {
    var fn_params = try s.create_node_list();
    try s.loop_read(.lparen, .rparen, .comma, struct {
        fn func(_fn_params: *std.ArrayList(Node), _s: *Self) !void {
            try _fn_params.append(try _s.declarator(false));
        }
    }.func, .{ &fn_params, s });
    const body = switch (s.l.tok.?) {
        .arrow => arrow_blk: {
            _ = try s.eat(.arrow);
            break :arrow_blk switch (_declarator.*) {
                .Declarator => |d| blk: {
                    break :blk switch (d.type.*) {
                        .Void => try s.stmt(),
                        else => try s.expr(.none),
                    };
                },
                else => return errors.Error.ParserError,
            };
        },
        .lbrace => try s.block(),
        else => return errors.Error.ParserError, // error out
    };
    return Node{ .FnDecl = .{ .declarator = _declarator, .body = try s.create_node_ptr(body), .args = fn_params } };
}
fn fn_literal(s: *Self) anyerror!Node {
    const fn_type = try s.type_();
    switch (fn_type) {
        .StructDecl, .EnumDecl, .ErrorDecl => {}, // error out
        else => {},
    }
    var args = try s.create_node_list();
    try s.loop_read(.lparen, .rparen, .comma, struct {
        fn func(_args: *std.ArrayList(Node), _s: *Self) !void {
            try _args.append(try _s.declarator(false));
        }
    }.func, .{ &args, s });
    const body = switch (s.l.tok.?) {
        .arrow => try s.create_node_ptr(try s.expr(.none)),
        .rbrace => try s.create_node_ptr(try s.block()),
        else => return errors.Error.ParserError,
    };
    _ = body;
}
fn enum_(s: *Self) anyerror!Node {
    _ = try s.eat(.@"enum");
    return switch (s.l.tok.?) {
        .identifier => try s.enum_decl(),
        .lbrace => try s.enum_type(),
        else => errors.Error.ParserError, // error out
    };
}
fn enum_decl(s: *Self) anyerror!Node {
    const name = try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } });
    return Node{ .EnumDecl = .{ .name = name, .members = try s.enum_members() } };
}
fn enum_type(s: *Self) anyerror!Node {
    return Node{ .EnumType = .{ .members = try s.enum_members() } };
}
fn enum_members(s: *Self) anyerror!std.ArrayList(Node) {
    var members = try s.create_node_list();
    try s.loop_read(.lbrace, .rbrace, .comma, struct {
        fn func(_members: *std.ArrayList(Node), _s: *Self) !void {
            var x = try _s.type_();
            if (_s.l.tok.? == .identifier) {
                x = Node{ .Declarator = .{ .mut = false, .type = try _s.create_node_ptr(x), .name = try _s.create_node_ptr(Node{ .Identifier = .{ .value = try _s.eat(.identifier) } }) } };
            } else {
                if (x != .Identifier) return errors.Error.ParserError;
            }
            try _members.append(x);
        }
    }.func, .{ &members, s });
    return members;
}
fn error_(s: *Self) anyerror!Node {
    _ = try s.eat(.@"error");
    return switch (s.l.tok.?) {
        .identifier => try s.error_decl(),
        .lbrace => try s.error_type(),
        else => errors.Error.ParserError,
    };
}
fn error_decl(s: *Self) anyerror!Node {
    const name = try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } });
    return Node{ .ErrorDecl = .{ .name = name, .members = try s.error_members() } };
}
fn error_type(s: *Self) anyerror!Node {
    return Node{ .ErrorType = .{ .members = try s.error_members() } };
}
fn error_members(s: *Self) anyerror!std.ArrayList(Node) {
    var members = try s.create_node_list();
    try s.loop_read(.lbrace, .rbrace, .comma, struct {
        fn func(_members: *std.ArrayList(Node), _s: *Self) !void {
            var x = try _s.type_();
            if (_s.l.tok.? == .identifier) {
                x = Node{ .Declarator = .{ .mut = false, .type = try _s.create_node_ptr(x), .name = try _s.create_node_ptr(Node{ .Identifier = .{ .value = try _s.eat(.identifier) } }) } };
            } else {
                if (x != .Identifier) return errors.Error.ParserError;
            }
            try _members.append(x);
        }
    }.func, .{ &members, s });
    return members;
}

fn struct_(s: *Self) anyerror!Node {
    _ = try s.eat(.@"struct");
    return switch (s.l.tok.?) {
        .identifier => try s.struct_decl(),
        .lbrace => try s.struct_type(),
        else => errors.Error.ParserError,
    };
}
fn struct_decl(s: *Self) anyerror!Node {
    const name = try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } });
    return Node{ .StructDecl = .{ .name = name, .members = try s.struct_members() } };
}
fn struct_type(s: *Self) anyerror!Node {
    return Node{ .StructType = .{ .members = try s.struct_members() } };
}
fn struct_members(s: *Self) anyerror!std.ArrayList(Node) {
    var members = try s.create_node_list();
    try s.loop_read(.lbrace, .rbrace, .comma, struct {
        fn func(_members: *std.ArrayList(Node), _s: *Self) !void {
            const _declarator = try _s.declarator(false);
            switch (_declarator) {
                .Declarator => {
                    switch (_s.l.tok.?) {
                        .lparen => {
                            var args = try _s.create_node_list();
                            try _s.loop_read(.lparen, .rparen, .comma, struct {
                                fn func(_args: *std.ArrayList(Node), __s: *Self) !void {
                                    try _args.append(try __s.declarator(false));
                                }
                            }.func, .{ &args, _s });
                            const body = switch (_s.l.tok.?) {
                                .arrow => arrow_blk: {
                                    _ = try _s.eat(.arrow);
                                    break :arrow_blk switch (_declarator) {
                                        .Declarator => |d| blk: {
                                            break :blk switch (d.type.*) {
                                                .Void => void_blk: {
                                                    const _stmt = try _s.stmt();
                                                    break :void_blk _stmt;
                                                },
                                                else => {
                                                    const _expr = try _s.expr(.none);
                                                    break :arrow_blk _expr;
                                                },
                                            };
                                        },
                                        else => return errors.Error.ParserError,
                                    };
                                },
                                .lbrace => try _s.block(),
                                else => return errors.Error.ParserError,
                            };
                            try _members.append(Node{ .FnDecl = .{ .declarator = try _s.create_node_ptr(_declarator), .args = args, .body = try _s.create_node_ptr(body) } });
                        },
                        .eq => {
                            _ = try _s.eat(.eq);
                            try _members.append(Node{ .VarDecl = .{ .declarator = try _s.create_node_ptr(_declarator), .default_val = try _s.create_node_ptr(try _s.expr(.none)) } });
                        },
                        else => try _members.append(_declarator),
                    }
                },
                .StructDecl, .EnumDecl, .ErrorDecl => try _members.append(_declarator),
                else => return errors.Error.ParserError, // error out
            }
        }
    }.func, .{ &members, s });
    return members;
}
fn comp_(s: *Self) anyerror!Node {
    _ = try s.eat(.comp);
    const x = try s.type_();
    if (x == .CompType) return errors.Error.ParserError;
    return Node{ .CompType = .{ .base_type = try s.create_node_ptr(x) } };
}
fn type_(s: *Self) anyerror!Node {
    var base_type = switch (s.l.tok.?) {
        .@"struct" => try s.struct_(),
        .@"enum" => try s.enum_(),
        .@"error" => try s.error_(),
        .identifier => Node{ .Identifier = .{ .value = try s.eat(.identifier) } },
        .void => void_blk: {
            _ = try s.eat(.void);
            break :void_blk .Void;
        },
        .comp => try s.comp_(),
        else => {
            std.debug.print("We had a problem at line {d}, col {d}, {any} \n", .{ s.l.line, s.l.col, s.l.tok.? });
            return errors.Error.ParserError;
        },
    };
    switch (base_type) {
        .StructDecl, .EnumDecl, .ErrorDecl, .UseStmt, .UseBlock, .TypeDecl => return base_type,
        else => {},
    }
    while (s.l.tok.? != .eof) {
        switch (s.l.tok.?) {
            .lbrack => {
                _ = try s.eat(.lbrack);
                _ = try s.eat(.rbrack);
                base_type = Node{ .ArrayType = .{ .type = try s.create_node_ptr(base_type) } };
            },
            .lparen => {
                var types = try s.create_node_list();
                try s.loop_read(.lparen, .rparen, .comma, struct {
                    fn func(_types: *std.ArrayList(Node), _s: *Self) !void {
                        try _types.append(try _s.declarator(false));
                    }
                }.func, .{ &types, s });
                base_type = Node{ .FnType = .{ .type = try s.create_node_ptr(base_type), .args = types } };
            },
            .mul => {
                _ = try s.eat(.mul);
                base_type = Node{ .PointerType = .{ .type = try s.create_node_ptr(base_type) } };
            },
            .question => {
                _ = try s.eat(.question);
                base_type = Node{ .OptionalType = .{ .type = try s.create_node_ptr(base_type) } };
            },
            .bang => {
                _ = try s.eat(.bang);
                var error_types = try s.create_node_list();
                try s.loop_read(.lt, .gt, .@"or", struct {
                    fn func(_error_types: *std.ArrayList(Node), _s: *Self) !void {
                        try _error_types.append(Node{ .Identifier = .{ .value = try _s.eat(.identifier) } });
                    }
                }.func, .{ &error_types, s });
                base_type = Node{ .ErrorUnionType = .{ .base_type = try s.create_node_ptr(base_type), .error_types = error_types } };
            },
            else => break,
        }
    }
    return base_type;
}
fn declarator(s: *Self, check_mut: bool) anyerror!Node {
    var mut = false;
    if (s.l.tok.? == .mut) {
        _ = try s.eat(.mut);
        if (!check_mut) return errors.Error.ParserError;
        mut = true;
    }
    const the_type = try s.create_node_ptr(try s.type_());
    switch (the_type.*) {
        .StructDecl, .EnumDecl, .ErrorDecl, .TypeDecl => {
            if (check_mut) {} // then we have error
            return the_type.*;
        },
        else => {},
    }
    const name = try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } });
    // TODO: rework this
    return Node{ .Declarator = .{ .mut = mut, .type = the_type, .name = name } };
}
fn block(s: *Self) anyerror!Node {
    var stmts = try s.create_node_list();
    try s.loop_read(.lbrace, .rbrace, null, struct {
        fn func(_stmts: *std.ArrayList(Node), _s: *Self) !void {
            const _stmt = try _s.stmt();
            switch (_stmt) {
                .TryStmt, .FnCall, .Assignment, .ReturnStmt => _ = try _s.eat(.semicolon),
                .DeferStmt => |d| {
                    switch (d.stmt.*) {
                        .BlockStmt => {},
                        else => _ = try _s.eat(.semicolon),
                    }
                },
                .FnDecl => |d| {
                    switch (d.body.*) {
                        .BlockStmt => {},
                        else => _ = try _s.eat(.semicolon),
                    }
                },
                .VarDecl => |d| {
                    std.debug.print("We have a var decl\n", .{});
                    if (d.default_val) |_| {
                        switch (d.declarator.*) {
                            .Declarator => |de| {
                                std.debug.print("We have a var declarator\n", .{});
                                switch (de.type.*) {
                                    .Type => {
                                        std.debug.print("We have a type type\n", .{});
                                    },
                                    else => _ = try _s.eat(.semicolon),
                                }
                            },
                            else => return errors.Error.ParserError,
                        }
                    }
                },
                else => {},
            }
            try _stmts.append(_stmt);
        }
    }.func, .{ &stmts, s });
    return Node{ .BlockStmt = .{ .stmts = stmts } };
}
fn decl(s: *Self) anyerror!Node {
    const _declarator = try s.create_node_ptr(try s.declarator(true));
    switch (_declarator.*) {
        .StructDecl, .EnumDecl, .ErrorDecl, .TypeDecl, .UseStmt, .UseBlock => return _declarator.*,
        else => {},
    }
    return switch (s.l.tok.?) {
        .lparen => blk: {
            const x = try s.fn_decl(_declarator);
            switch (x) {
                .FnDecl => |d| {
                    switch (d.body.*) {
                        .BlockStmt => {},
                        else => _ = try s.eat(.semicolon),
                    }
                },
                else => return errors.Error.ParserError,
            }
            break :blk x;
        },
        else => blk: {
            const v = try s.var_decl(_declarator);
            _ = try s.eat(.semicolon);
            break :blk v;
        },
    };
}
fn try_stmt(s: *Self) anyerror!Node {
    _ = try s.eat(.@"try");
    switch (s.l.tok.?) {
        .@"try" => return Node{ .TryStmt = .{ .call = try s.create_node_ptr(try s.try_stmt()) } },
        .lparen => return Node{ .GroupingExpr = .{ .expr = try s.create_node_ptr(try s.try_stmt()) } },
        .identifier => {
            var callee = Node{ .Identifier = .{ .value = try s.eat(.identifier) } };
            var args = try s.create_node_list();
            try s.loop_read(.lparen, .rparen, .comma, struct {
                fn func(_args: *std.ArrayList(Node), _s: *Self) !void {
                    try _args.append(try _s.expr(.none));
                }
            }.func, .{ &args, s });
            callee = Node{ .FnCall = .{ .callee = try s.create_node_ptr(callee), .args = args } };
            if (s.l.tok.? == .@"catch") {
                return try s.catch_stmt(try s.create_node_ptr(callee));
            }
            return Node{ .TryStmt = .{ .call = try s.create_node_ptr(callee) } };
        },
        else => return errors.Error.ParserError,
    }
}
fn catch_stmt(s: *Self, call: *Node) anyerror!Node {
    _ = try s.eat(.@"catch");
    const _capture = switch (s.l.tok.?) {
        .@"or" => try s.create_node_ptr(try s.capture()),
        else => null,
    };
    const body = try s.create_node_ptr(try s.block());
    return Node{ .CatchStmt = .{ .call = call, .capture = _capture, .body = body } };
}
fn decl_stmt(s: *Self) anyerror!Node {
    var mut = false;
    if (s.l.tok.? == .mut) {
        _ = try s.eat(.mut);
        mut = true;
    }
    var the_type: Node = switch (s.l.tok.?) {
        .@"struct" => try s.struct_(),
        .@"enum" => try s.enum_(),
        .@"error" => try s.error_(),
        .identifier => Node{ .Identifier = .{ .value = try s.eat(.identifier) } },
        .void => void_block: {
            _ = try s.eat(.void);
            break :void_block Node.Void;
        },
        .type => type_block: {
            _ = try s.eat(.type);
            break :type_block Node.Type;
        },
        .@"try" => try s.try_stmt(),
        else => {
            std.debug.print("We have a bad token: {any}, line: {}, col: {}\n", .{ s.l.tok.?, s.l.line, s.l.col });
            return errors.Error.ParserError;
        },
    };
    switch (the_type) {
        .StructDecl, .EnumDecl, .ErrorDecl, .TryStmt, .CatchStmt => {
            if (mut) return errors.Error.ParserError; // then we have error
            return the_type;
        },
        .Identifier => {
            while (s.l.tok.? != .eof) {
                switch (s.l.tok.?) {
                    .dot => {
                        _ = try s.eat(.dot);
                        switch (s.l.tok.?) {
                            .question => {
                                _ = try s.eat(.question);
                                the_type = Node{ .OptionalDereferenceExpr = .{ .expr = try s.create_node_ptr(the_type) } };
                            },
                            .mul => {
                                _ = try s.eat(.mul);
                                the_type = Node{ .PointerDereferenceExpr = .{ .expr = try s.create_node_ptr(the_type) } };
                            },
                            .identifier => {
                                the_type = Node{ .MemberAccess = .{ .root = try s.create_node_ptr(the_type), .access = try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } }) } };
                            },
                            .lbrack => {
                                _ = try s.eat(.lbrack);
                                const _expr = try s.expr(.none);
                                _ = try s.eat(.rbrack);
                                the_type = Node{ .ArrayIndex = .{ .callee = try s.create_node_ptr(the_type), .index = try s.create_node_ptr(_expr) } };
                            },
                            else => break,
                        }
                    },
                    .lparen => {
                        var args = try s.create_node_list();
                        try s.loop_read(.lparen, .rparen, .comma, struct {
                            fn func(_args: *std.ArrayList(Node), _s: *Self) !void {
                                try _args.append(try _s.expr(.none));
                            }
                        }.func, .{ &args, s });
                        the_type = Node{ .FnCall = .{ .callee = try s.create_node_ptr(the_type), .args = args } };
                        break;
                    },
                    .lbrack => {
                        _ = try s.eat(.lbrack);
                        the_type = Node{ .ArrayIndex = .{ .callee = try s.create_node_ptr(the_type), .index = try s.create_node_ptr(try s.expr(.none)) } };
                        _ = try s.eat(.rbrack);
                    },
                    else => break,
                }
            }
        },
        .Void => {},
        .Type => {},
        else => {
            std.debug.print("Error, Got {any}, {} {}\n", .{ the_type, s.l.line, s.l.col });
            return errors.Error.ParserError;
        },
    }
    if (the_type == .FnCall) {
        if (s.l.tok.? == .@"catch") {
            the_type = try s.catch_stmt(try s.create_node_ptr(the_type));
        }
        return the_type;
    }
    switch (s.l.tok.?) {
        .eq => {
            _ = try s.eat(.eq);
            the_type = Node{ .Assignment = .{ .left = try s.create_node_ptr(the_type), .assign = .normal, .right = try s.create_node_ptr(try s.expr(.none)) } };
        },
        .addeq => {
            _ = try s.eat(.addeq);
            the_type = Node{ .Assignment = .{ .left = try s.create_node_ptr(the_type), .assign = .add, .right = try s.create_node_ptr(try s.expr(.none)) } };
        },
        .subeq => {
            _ = try s.eat(.subeq);
            the_type = Node{ .Assignment = .{ .left = try s.create_node_ptr(the_type), .assign = .sub, .right = try s.create_node_ptr(try s.expr(.none)) } };
        },
        .muleq => {
            _ = try s.eat(.muleq);
            the_type = Node{ .Assignment = .{ .left = try s.create_node_ptr(the_type), .assign = .mul, .right = try s.create_node_ptr(try s.expr(.none)) } };
        },
        .diveq => {
            _ = try s.eat(.diveq);
            the_type = Node{ .Assignment = .{ .left = try s.create_node_ptr(the_type), .assign = .div, .right = try s.create_node_ptr(try s.expr(.none)) } };
        },
        .modeq => {
            _ = try s.eat(.modeq);
            the_type = Node{ .Assignment = .{ .left = try s.create_node_ptr(the_type), .assign = .mod, .right = try s.create_node_ptr(try s.expr(.none)) } };
        },
        .xoreq => {
            _ = try s.eat(.xoreq);
            the_type = Node{ .Assignment = .{ .left = try s.create_node_ptr(the_type), .assign = .xor, .right = try s.create_node_ptr(try s.expr(.none)) } };
        },
        .andeq => {
            _ = try s.eat(.andeq);
            the_type = Node{ .Assignment = .{ .left = try s.create_node_ptr(the_type), .assign = .@"and", .right = try s.create_node_ptr(try s.expr(.none)) } };
        },
        .oreq => {
            _ = try s.eat(.oreq);
            the_type = Node{ .Assignment = .{ .left = try s.create_node_ptr(the_type), .assign = .@"or", .right = try s.create_node_ptr(try s.expr(.none)) } };
        },
        else => {},
    }
    if (the_type == .Assignment) {
        return the_type;
    }
    while (s.l.tok.? != .eof) {
        switch (s.l.tok.?) {
            .lbrack => {
                _ = try s.eat(.lbrack);
                _ = try s.eat(.rbrack);
                the_type = Node{ .ArrayType = .{ .type = try s.create_node_ptr(the_type) } };
            },
            .lparen => {
                _ = try s.eat(.lparen);
                var types = try s.create_node_list();
                try s.loop_read(.lparen, .rparen, .comma, struct {
                    fn func(_types: *std.ArrayList(Node), _s: *Self) !void {
                        try _types.append(try _s.type_());
                    }
                }.func, .{ &types, s });
                the_type = Node{ .FnType = .{ .type = try s.create_node_ptr(the_type), .args = types } };
            },
            .mul => {
                _ = try s.eat(.mul);
                the_type = Node{ .PointerType = .{ .type = try s.create_node_ptr(the_type) } };
            },
            .question => {
                _ = try s.eat(.question);
                the_type = Node{ .OptionalType = .{ .type = try s.create_node_ptr(the_type) } };
            },
            .bang => {
                _ = try s.eat(.bang);
                var error_types = try s.create_node_list();
                try s.loop_read(.lt, .gt, .@"or", struct {
                    fn func(_error_types: *std.ArrayList(Node), _s: *Self) !void {
                        try _error_types.append(Node{ .Identifier = .{ .value = try _s.eat(.identifier) } });
                    }
                }.func, .{ &error_types, s });
                the_type = Node{ .ErrorUnionType = .{ .base_type = try s.create_node_ptr(the_type), .error_types = error_types } };
            },
            else => break,
        }
    }
    const name = Node{ .Identifier = .{ .value = try s.eat(.identifier) } };
    the_type = Node{ .Declarator = .{ .mut = mut, .type = try s.create_node_ptr(the_type), .name = try s.create_node_ptr(name) } };
    return switch (s.l.tok.?) {
        .lparen => try s.fn_decl(try s.create_node_ptr(the_type)),
        else => try s.var_decl(try s.create_node_ptr(the_type)),
    };
}
fn expr(s: *Self, precedence: Precedence) anyerror!Node {
    var trying = false;
    var base: Node = undefined;
    // prefix
    switch (s.l.tok.?) {
        .int => base = Node{ .Literal = .{ .kind = .int, .value = try s.eat(.int) } },
        .float => base = Node{ .Literal = .{ .kind = .float, .value = try s.eat(.float) } },
        .string => base = Node{ .Literal = .{ .kind = .string, .value = try s.eat(.string) } },
        .char => base = Node{ .Literal = .{ .kind = .char, .value = try s.eat(.char) } },
        .identifier => base = Node{ .Identifier = .{ .value = try s.eat(.identifier) } },
        .undefined => base = Node{ .Literal = .{ .kind = .undefined, .value = try s.eat(.undefined) } },
        .null => base = Node{ .Literal = .{ .kind = .null, .value = try s.eat(.null) } },
        .true => base = Node{ .Literal = .{ .kind = .bool, .value = try s.eat(.true) } },
        .false => base = Node{ .Literal = .{ .kind = .bool, .value = try s.eat(.false) } },
        .lparen => {
            _ = try s.eat(.lparen);
            base = Node{ .GroupingExpr = .{ .expr = try s.create_node_ptr(try s.expr(.none)) } };
            _ = try s.eat(.rparen);
        },
        .sub => {
            _ = try s.eat(.sub);
            base = Node{ .NegateExpr = .{ .expr = try s.create_node_ptr(try s.expr(.none)) } };
        },
        .flip => {
            _ = try s.eat(.flip);
            base = Node{ .FlipExpr = .{ .expr = try s.create_node_ptr(try s.expr(.none)) } };
        },
        .bang => {
            _ = try s.eat(.bang);
            base = Node{ .NotExpr = .{ .expr = try s.create_node_ptr(try s.expr(.none)) } };
        },
        .@"and" => {
            _ = try s.eat(.@"and");
            base = Node{ .ReferenceExpr = .{ .expr = try s.create_node_ptr(try s.expr(.none)) } };
        },
        .lbrace => base = Node{ .BlockExpr = .{ .block = try s.create_node_ptr(try s.block()) } },
        .lbrack => base = try s.array_literal(),
        .dot => {
            _ = try s.eat(.dot);
            switch (s.l.tok.?) {
                .identifier => base = Node{ .MemberAccess = .{ .root = null, .access = try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } }) } },
                .lbrace => base = try s.struct_literal(),
                else => return errors.Error.ParserError,
            }
        },
        .@"if" => base = Node{ .IfExpr = .{ .expr = try s.create_node_ptr(try s.if_()) } },
        .match => base = Node{ .MatchExpr = .{ .expr = try s.create_node_ptr(try s.match_()) } },
        .@"try" => {
            _ = try s.eat(.@"try");
            trying = true;
        },
        else => {}, // invalid prefix
    }
    // infix
    while (s.l.tok.? != .eof) {
        const prec = s.get_precedence();
        if (@intFromEnum(precedence) > prec) break;
        switch (s.l.tok.?) {
            .add, .sub, .mul, .div, .mod, .eqeq, .bangeq, .lt, .gt, .lteq, .gteq, .andand, .oror, .dotdot => {
                const op = try s.get_operator();
                _ = try s.eat(s.l.tok.?);
                const new_precedence: Precedence = @enumFromInt(prec + 1);
                base = Node{ .BinaryExpr = .{ .left = try s.create_node_ptr(base), .op = op, .right = try s.create_node_ptr(try s.expr(new_precedence)) } };
            },
            .lparen => {
                var args = try s.create_node_list();
                try s.loop_read(.lparen, .rparen, .comma, struct {
                    fn func(_args: *std.ArrayList(Node), _s: *Self) !void {
                        try _args.append(try _s.expr(.none));
                    }
                }.func, .{ &args, s });
                base = Node{ .FnCall = .{ .callee = try s.create_node_ptr(base), .args = args } };
            },
            .dot => {
                _ = try s.eat(.dot);
                switch (s.l.tok.?) {
                    .question => {
                        _ = try s.eat(.question);
                        base = Node{ .OptionalDereferenceExpr = .{ .expr = try s.create_node_ptr(base) } };
                    },
                    .mul => {
                        _ = try s.eat(.mul);
                        base = Node{ .PointerDereferenceExpr = .{ .expr = try s.create_node_ptr(base) } };
                    },
                    .identifier => base = Node{ .MemberAccess = .{ .root = try s.create_node_ptr(base), .access = try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } }) } },
                    else => break,
                }
            },
            .lbrack => {
                _ = try s.eat(.lbrack);
                base = Node{ .ArrayIndex = .{ .callee = try s.create_node_ptr(base), .index = try s.create_node_ptr(try s.expr(.none)) } };
                _ = try s.eat(.rbrack);
            },
            .@"else" => {
                _ = try s.eat(.@"else");
                if (base != .Identifier) {
                    std.debug.print("{}, {}:  Using else with identifier not allowed\n", .{ s.l.line, s.l.col });
                    return errors.Error.ParserError;
                }
                base = Node{ .ElseIdentifier = .{ .ident = try s.create_node_ptr(base), .else_ident = try s.create_node_ptr(try s.expr(.none)) } };
                break;
            },
            else => break,
        }
    }
    if (s.l.tok.? == .@"catch") {}
    return base;
}
fn get_precedence(s: Self) u8 {
    return @intFromEnum(switch (s.l.tok.?) {
        .oror => Precedence.@"or",
        .andand => Precedence.@"and",
        .eqeq, .bangeq => Precedence.equals,
        .lt, .gt, .lteq, .gteq => Precedence.compare,
        .add, .sub => Precedence.add,
        .mul, .div, .mod => Precedence.mul,
        .lparen, .dot => Precedence.postfix,
        else => Precedence.none,
    });
}
fn get_operator(s: Self) anyerror!ast.OperatorKind {
    return switch (s.l.tok.?) {
        .add => .add,
        .sub => .sub,
        .mul => .mul,
        .div => .div,
        .mod => .mod,
        .eqeq => .eqeq,
        .bangeq => .bangeq,
        .lt => .lt,
        .lteq => .lte,
        .gt => .gt,
        .gteq => .gte,
        .andand => .andand,
        .oror => .oror,
        .dotdot => .dotdot,
        else => return errors.Error.ParserError,
    };
}
fn struct_literal(s: *Self) anyerror!Node {
    var initializers = try s.create_node_list();
    try s.loop_read(.lbrace, .rbrace, .comma, struct {
        fn func(_initializers: *std.ArrayList(Node), _s: *Self) !void {
            try _initializers.append(try _s.struct_initializer());
        }
    }.func, .{ &initializers, s });
    return Node{ .StructLiteral = .{ .initializers = initializers } };
}
fn struct_initializer(s: *Self) anyerror!Node {
    const ident = Node{ .Identifier = .{ .value = try s.eat(.identifier) } };
    _ = try s.eat(.colon);
    const _expr = try s.expr(.none);
    return Node{ .StructInitializer = .{ .ident = try s.create_node_ptr(ident), .value = try s.create_node_ptr(_expr) } };
}
fn array_literal(s: *Self) anyerror!Node {
    var items = try s.create_node_list();
    try s.loop_read(.lbrack, .rbrack, .comma, struct {
        fn func(_items: *std.ArrayList(Node), _s: *Self) !void {
            try _items.append(try _s.expr(.none));
        }
    }.func, .{ &items, s });
    return Node{ .ArrayLiteral = .{ .items = items } };
}
fn stmt(s: *Self) anyerror!Node {
    return switch (s.l.tok.?) {
        .@"if" => try s.if_(),
        .match => try s.match_(),
        .@"defer" => try s.defer_(),
        .@"return" => try s.return_(),
        .@"for" => try s.for_(),
        .@"while" => try s.while_(),
        .@"break" => try s.break_(),
        .@"inline" => try s.inline_stmt(),
        else => try s.decl_stmt(),
    };
}
fn inline_stmt(s: *Self) anyerror!Node {
    _ = try s.eat(.@"inline");
    return switch (s.l.tok.?) {
        .@"while" => Node{ .InlineStmt = .{ .base_stmt = try s.create_node_ptr(try s.while_()) } },
        .@"for" => Node{ .InlineStmt = .{ .base_stmt = try s.create_node_ptr(try s.for_()) } },
        else => errors.Error.ParserError,
    };
}
fn if_(s: *Self) anyerror!Node {
    _ = try s.eat(.@"if");
    const condition = try s.create_node_ptr(try s.expr(.none));
    const _capture = switch (s.l.tok.?) {
        .@"or" => try s.create_node_ptr(try s.capture()),
        else => null,
    };
    const body = switch (s.l.tok.?) {
        .lbrace => try s.block(),
        else => try s.stmt(),
    };
    const else_body = switch (s.l.tok.?) {
        .@"else" => blk: {
            _ = try s.eat(.@"else");
            break :blk switch (s.l.tok.?) {
                .@"if" => try s.create_node_ptr(try s.if_()),
                .lbrace => try s.create_node_ptr(try s.block()),
                else => try s.create_node_ptr(try s.stmt()),
            };
        },
        else => null,
    };
    return Node{ .IfStmt = .{ .condition = condition, .capture = _capture, .body = try s.create_node_ptr(body), .else_body = else_body } };
}
fn match_(s: *Self) anyerror!Node {
    _ = try s.eat(.match);
    const to_match = Node{ .Identifier = .{ .value = try s.eat(.identifier) } };
    var match_arms = try s.create_node_list();
    try s.loop_read(.lbrace, .rbrace, .comma, struct {
        fn func(_match_arms: *std.ArrayList(Node), _s: *Self) !void {
            try _match_arms.append(try _s.match_arm());
        }
    }.func, .{ &match_arms, s });
    return Node{ .MatchStmt = .{ .to_match = try s.create_node_ptr(to_match), .match_arms = match_arms } };
}
fn match_arm(s: *Self) anyerror!Node {
    var branches = try s.create_node_list();
    try s.loop_read(null, .colon, .comma, struct {
        fn func(_branches: *std.ArrayList(Node), _s: *Self) !void {
            try _branches.append(switch (_s.l.tok.?) {
                .underscore => under: {
                    _ = try _s.eat(.underscore);
                    break :under Node.Underscore;
                },
                else => try _s.expr(.none),
            });
        }
    }.func, .{ &branches, s });
    // verify that if underscore then nothing else
    const _expr = try s.expr(.none);
    return Node{ .MatchArm = .{ .branches = branches, .block = try s.create_node_ptr(_expr) } };
}
fn defer_(s: *Self) anyerror!Node {
    _ = try s.eat(.@"defer");
    const _capture = switch (s.l.tok.?) {
        .@"or" => try s.create_node_ptr(try s.capture()),
        else => null,
    };
    const _stmt = switch (s.l.tok.?) {
        .lbrace => try s.block(),
        else => try s.stmt(),
    };
    return Node{ .DeferStmt = .{ .capture = _capture, .stmt = try s.create_node_ptr(_stmt) } };
}
fn return_(s: *Self) anyerror!Node {
    _ = try s.eat(.@"return");
    const _expr = try s.expr(.none);
    return Node{ .ReturnStmt = .{ .expr = try s.create_node_ptr(_expr) } };
}
fn for_(s: *Self) anyerror!Node {
    _ = try s.eat(.@"for");
    const _expr = try s.expr(.none);
    const _capture = try s.capture();
    const body = switch (s.l.tok.?) {
        .lbrace => try s.block(),
        else => try s.stmt(),
    };
    return Node{ .ForStmt = .{ .expr = try s.create_node_ptr(_expr), .capture = try s.create_node_ptr(_capture), .body = try s.create_node_ptr(body) } };
}
fn capture(s: *Self) anyerror!Node {
    var mut = false;
    _ = try s.eat(.@"or");
    if (s.l.tok.? == .mut) {
        _ = try s.eat(.mut);
        mut = true;
    }
    const ident = Node{ .Identifier = .{ .value = try s.eat(.identifier) } };
    _ = try s.eat(.@"or");
    return Node{ .Capture = .{ .mut = mut, .ident = try s.create_node_ptr(ident) } };
}
fn while_(s: *Self) anyerror!Node {
    _ = try s.eat(.@"while");
    const _expr = try s.expr(.none);
    const body = switch (s.l.tok.?) {
        .lbrace => try s.block(),
        else => try s.stmt(),
    };
    return Node{ .WhileStmt = .{ .expr = try s.create_node_ptr(_expr), .body = try s.create_node_ptr(body) } };
}
fn break_(s: *Self) anyerror!Node {
    _ = try s.eat(.@"break");
    _ = try s.eat(.semicolon);
    return Node.BreakStmt;
}
fn eat(s: *Self, t: token.TokenType) anyerror![]const u8 {
    if (s.l.tok.? != t) {
        std.debug.print("We had a problem, wanted {any}, got {any} at line {d}, col {d} \n", .{ t, s.l.tok.?, s.l.line, s.l.col });
        return errors.Error.ParserError;
    } // error out
    defer s.l.next_tok();
    return s.l.literal orelse "";
}
fn create_node_ptr(s: *Self, val: Node) !*ast.Node {
    const x = try s.allocator.create(Node);
    x.* = val;
    return x;
}
fn create_node_list(s: *Self) !std.ArrayList(Node) {
    return std.ArrayList(Node).init(s.allocator);
}
fn loop_read(s: *Self, l: ?token.TokenType, r: token.TokenType, sep: ?token.TokenType, func: anytype, args: anytype) !void {
    if (l) |_l| _ = try s.eat(_l);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == r) break;
        try @call(.auto, func, args);
        if (s.l.tok.? == r) break;
        if (sep) |_s| _ = try s.eat(_s);
    }
    _ = try s.eat(r);
}
