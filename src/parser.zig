const std = @import("std");
const Lexer = @import("lexer.zig");
const Token = @import("token.zig").TokenType;
const Error = @import("errors.zig").Error;
const Node = @import("ast.zig").Node;
const LiteralKind = @import("ast.zig").LiteralKind;
const Op = @import("ast.zig").Op;
const NodeList = std.ArrayList(Node);

const Self = @This();

const LexerState = struct { tok: ?Token, literal: ?[]const u8, line: usize, col: usize, index: usize };

l: Lexer,
a: std.mem.Allocator,

// things to get working/reconsider
// - captures
// - comments
pub fn init(alloc: std.mem.Allocator, buf: []const u8) Self {
    return Self{ .l = Lexer.init(buf), .a = alloc };
}
pub fn program(s: *Self) !Node {
    s.l.next_tok();
    var pub_decls = NodeList.init(s.a);
    var decls = NodeList.init(s.a);
    try pub_decls.append(try s.module());
    while (s.l.tok.? != .eof) {
        const public = if (s.l.tok.? == .@"pub") blk: {
            _ = try s.eat(.@"pub");
            break :blk true;
        } else false;
        if (s.l.tok.? == .mut) @panic("Module Level Declarations Cannot Be Mut");

        if (public) try pub_decls.append(try s.decl()) else try decls.append(try s.decl());
    }
    return Node{ .Program = .{ .decls = decls, .pub_decls = pub_decls } };
}
fn module(s: *Self) !Node {
    _ = try s.eat(.module);
    const module_ = Node{ .Module = .{ .name = try s.create_node_ptr(Node{ .Literal = .{ .kind = .string, .value = try s.eat(.string) } }) } };
    _ = try s.eat(.semicolon);
    return module_;
}
fn use(s: *Self) !Node {
    _ = try s.eat(.use);
    const alias = switch (s.l.tok.?) {
        .identifier => try s.create_node_ptr(try s.identifier()),
        else => null,
    };
    const import = try s.create_node_ptr(Node{ .Literal = .{ .kind = .string, .value = try s.eat(.string) } });
    return Node{ .Use = .{ .alias = alias, .import = import } };
}
fn decl(s: *Self) !Node {
    if (s.l.tok.? == .use) {
        const use_ = try s.use();
        _ = try s.eat(.semicolon);
        return use_;
    }
    const ident = try s.create_node_ptr(try s.identifier());
    const a = switch (s.l.tok.?) {
        .comma => blk: {
            _ = try s.eat(.comma);
            break :blk try s.var_(ident, false);
        },
        .colon => try s.var_(ident, false),
        .eq => blk: {
            _ = try s.eat(.eq);
            break :blk switch (s.l.tok.?) {
                .lparen => blk2: {
                    const state = s.save_lexer_state();
                    break :blk2 s.fn_type() catch blk3: {
                        s.restore_lexer_state(state);
                        break :blk3 try s.fn_(ident);
                    };
                },
                .@"inline" => try s.fn_(ident),
                .@"struct", .@"packed" => try s.struct_(ident),
                .@"enum" => try s.enum_(ident),
                .@"error" => try s.error_(ident),
                else => blk2: {
                    const var_default = try s.create_node_ptr(try s.expr(0));
                    var idents = NodeList.init(s.a);
                    try idents.append(ident.*);
                    _ = try s.eat(.semicolon);
                    break :blk2 Node{ .Var = .{ .names = idents, .mut = false, .type = null, .default = var_default } };
                },
            };
        },
        else => @panic("Invalid marker for declaration"),
    };
    switch (a) {
        .Var, .FnType => _ = try s.eat(.semicolon),
        .Fn => |b| {
            if (b.body.* != .Block) _ = try s.eat(.semicolon);
        },
        else => {},
    }
    return a;
}
fn struct_(s: *Self, ident: ?*Node) !Node {
    const pack = if (s.l.tok.? == .@"packed") blk: {
        _ = try s.eat(.@"packed");
        break :blk true;
    } else false;
    _ = try s.eat(.@"struct");
    var members = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        try members.append(try s.member(true));
        if (s.l.tok.? == .rbrace) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rbrace);
    return Node{ .Struct = .{ .pack = pack, .name = ident, .members = members } };
}
fn enum_(s: *Self, ident: ?*Node) !Node {
    _ = try s.eat(.@"enum");
    var members = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        try members.append(try s.member(false));
        if (s.l.tok.? == .rbrace) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rbrace);
    return Node{ .Enum = .{ .name = ident, .members = members } };
}
fn error_(s: *Self, ident: ?*Node) !Node {
    _ = try s.eat(.@"error");
    var members = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        try members.append(try s.member(false));
        if (s.l.tok.? == .rbrace) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rbrace);
    return Node{ .Error = .{ .name = ident, .members = members } };
}
fn member(s: *Self, allow_list: bool) anyerror!Node {
    var members = NodeList.init(s.a);
    if (allow_list) {
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .colon or s.l.tok.? == .eq) break;
            try members.append(try s.identifier());
            if (s.l.tok.? == .colon or s.l.tok.? == .eq) break;
            _ = try s.eat(.comma);
        }
        const member_type = if (s.l.tok.? == .colon) blk: {
            _ = try s.eat(.colon);
            break :blk try s.create_node_ptr(try s.type_());
        } else null;
        const member_default = if (s.l.tok.? == .eq) blk: {
            _ = try s.eat(.eq);
            if (members.items.len > 1) break :blk try s.create_node_ptr(try s.expr(0));
            const ident = try s.create_node_ptr(members.items[0]);
            break :blk try s.create_node_ptr(switch (s.l.tok.?) {
                .lparen, .@"inline" => {
                    defer {
                        if (member_type) |i| {
                            i.deinit(s.a);
                            s.a.destroy(i);
                        }
                        members.deinit();
                    }
                    return try s.fn_(ident);
                },
                .@"struct", .@"packed" => {
                    defer {
                        if (member_type) |i| {
                            i.deinit(s.a);
                            s.a.destroy(i);
                        }
                        members.deinit();
                    }
                    return try s.struct_(ident);
                },
                .@"enum" => {
                    defer {
                        if (member_type) |i| {
                            i.deinit(s.a);
                            s.a.destroy(i);
                        }
                        members.deinit();
                    }
                    return try s.enum_(ident);
                },
                .@"error" => {
                    defer {
                        if (member_type) |i| {
                            i.deinit(s.a);
                            s.a.destroy(i);
                        }
                        members.deinit();
                    }
                    return try s.error_(ident);
                },
                else => try s.expr(0),
            });
        } else null;
        return Node{ .Member = .{ .ident = members, .type = member_type, .default = member_default } };
    }
    const ident = try s.identifier();
    if (s.l.tok.? == .eq) {
        _ = try s.eat(.eq);
        return switch (s.l.tok.?) {
            .lparen, .@"inline" => try s.fn_(try s.create_node_ptr(ident)),
            .@"struct", .@"packed" => try s.struct_(try s.create_node_ptr(ident)),
            .@"enum" => try s.enum_(try s.create_node_ptr(ident)),
            .@"error" => try s.error_(try s.create_node_ptr(ident)),
            else => try s.var_(try s.create_node_ptr(ident), false),
        };
    }
    try members.append(ident);
    const member_type: ?*Node = if (s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.create_node_ptr(try s.type_());
    } else null;
    const default = if (s.l.tok.? == .eq) blk: {
        _ = try s.eat(.eq);
        break :blk try s.create_node_ptr(try s.expr(0));
    } else null;
    return Node{ .Member = .{ .ident = members, .type = member_type, .default = default } };
}
fn var_(s: *Self, first_ident: ?*Node, mut: bool) !Node {
    var idents_no_type = std.ArrayList(Node).init(s.a);
    if (first_ident) |fi| try idents_no_type.append(fi.*) else {
        if (mut) _ = try s.eat(.mut);
    }
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .colon or s.l.tok.? == .eq) break;
        try idents_no_type.append(try s.identifier());
        if (s.l.tok.? == .colon or s.l.tok.? == .eq) break;
        _ = try s.eat(.comma);
    }
    const var_type: ?*Node = if (s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.create_node_ptr(try s.type_());
    } else null;
    const var_default: ?*Node = if (s.l.tok.? == .eq) blk: {
        _ = try s.eat(.eq);
        break :blk try s.create_node_ptr(try s.expr(0));
    } else null;
    return Node{ .Var = .{ .names = idents_no_type, .mut = mut, .type = var_type, .default = var_default } };
}
fn fn_(s: *Self, ident: ?*Node) !Node {
    const inlined = if (s.l.tok.? == .@"inline") blk: {
        _ = try s.eat(.@"inline");
        break :blk true;
    } else false;
    _ = try s.eat(.lparen);
    var fn_args_names_without_types = std.ArrayList([]const u8).init(s.a);
    var fn_args = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rparen) break;
        try fn_args_names_without_types.append(try s.eat(.identifier));
        if (s.l.tok.? == .colon) {
            _ = try s.eat(.colon);
            const arg_type = try s.create_node_ptr(try s.type_());
            const arg_default: ?*Node = if (s.l.tok.? == .eq) blk: {
                _ = try s.eat(.eq);
                break :blk try s.create_node_ptr(try s.expr(0));
            } else null;
            for (fn_args_names_without_types.items) |i| {
                const arg_ident = try s.create_node_ptr(Node{ .Ident = .{ .value = i } });
                try fn_args.append(Node{ .Arg = .{ .name = arg_ident, .type = arg_type, .default = arg_default } });
            }
            fn_args_names_without_types.clearAndFree();
        }
        if (s.l.tok.? == .rparen) break;
        _ = try s.eat(.comma);
    }
    if (fn_args_names_without_types.items.len > 0) {
        std.debug.print("l: {} c: {}", .{ s.l.line, s.l.col });
        @panic("Not all identifiers in the fn have a type");
    }
    _ = try s.eat(.rparen);
    const ret_type: ?*Node = if (s.l.tok.? == .lbrace or s.l.tok.? == .arrow) null else try s.create_node_ptr(try s.type_());
    const fn_body = if (s.l.tok.? == .lbrace) try s.create_node_ptr(try s.block(null)) else if (s.l.tok.? == .arrow) blk: {
        _ = try s.eat(.arrow);
        break :blk try s.create_node_ptr(try s.expr(0));
    } else @panic("Please use either => or {} for a fn body");
    return Node{ .Fn = .{ .name = ident, .inlined = inlined, .args = fn_args, .type = ret_type, .body = fn_body } };
}
fn type_(s: *Self) anyerror!Node {
    var t: Node = undefined;
    switch (s.l.tok.?) {
        .comp => {
            _ = try s.eat(.comp);
            t = Node{ .CompType = .{ .type = try s.create_node_ptr(try s.type_()) } };
        },
        .lbrack => {
            _ = try s.eat(.lbrack);
            _ = try s.eat(.rbrack);
            t = Node{ .ArrayType = .{ .type = try s.create_node_ptr(try s.type_()) } };
        },
        .question => {
            _ = try s.eat(.question);
            t = Node{ .OptionalType = .{ .type = try s.create_node_ptr(try s.type_()) } };
        },
        .mul => {
            _ = try s.eat(.mul);
            t = Node{ .PointerType = .{ .type = try s.create_node_ptr(try s.type_()) } };
        },
        .identifier => {
            var i = try s.identifier();
            while (s.l.tok.? != .eof) {
                if (s.l.tok.? == .dot) {
                    _ = try s.eat(.dot);
                    i = Node{ .MemberAccess = .{ .accessed = try s.create_node_ptr(i), .member = try s.create_node_ptr(try s.identifier()) } };
                } else {
                    t = i;
                    break;
                }
            }
        },
        .@"struct" => t = try s.struct_(null),
        .@"enum" => t = try s.enum_(null),
        .@"error" => t = try s.error_(null),
        .type => t = blk: {
            _ = try s.eat(.type);
            break :blk .Type;
        },
        .lparen => t = try s.fn_type(),
        else => {
            std.debug.print("{} l: {}, c: {}\n", .{ s.l.tok.?, s.l.line, s.l.col });
            @panic("This is not a type");
        },
    }
    if (s.l.tok.? == .bang) t = try s.type_err(try s.create_node_ptr(t));
    return t;
}
fn type_err(s: *Self, ident: *Node) !Node {
    var errs = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        _ = try s.eat(.bang);
        try errs.append(try s.identifier());
        if (s.l.tok.? != .bang) break;
    }
    return Node{ .ErrorUnionType = .{ .base = ident, .errs = errs } };
}
fn block(s: *Self, label: ?*Node) anyerror!Node {
    var stmts = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        const x = try s.stmt();
        switch (x) {
            .Var, .FnCall, .OpAssign, .Struct, .Enum, .Error, .Break, .Return, .Try, .CompStmt, .FnType => _ = try s.eat(.semicolon),
            .Defer => |a| {
                if (a.body.* != .Block) _ = try s.eat(.semicolon);
            },
            .For => |a| {
                if (a.body.* != .Block) _ = try s.eat(.semicolon);
            },
            .Fn => |a| {
                if (a.body.* != .Block) _ = try s.eat(.semicolon);
            },
            .Catch => |a| {
                if (a.body.* != .Block) _ = try s.eat(.semicolon);
            },
            .If => |a| {
                if (a.body.* != .Block) _ = try s.eat(.semicolon);
            },
            .InlineLoop => |a| {
                switch (a.stmt.*) {
                    .For => |b| {
                        if (b.body.* != .Block) _ = try s.eat(.semicolon);
                    },
                    .While => |b| {
                        if (b.body.* != .Block) _ = try s.eat(.semicolon);
                    },
                    else => unreachable,
                }
            },
            else => {},
        }
        try stmts.append(x);
        if (s.l.tok.? == .rbrace) break;
    }
    _ = try s.eat(.rbrace);
    return Node{ .Block = .{ .label = label, .stmts = stmts } };
}
fn expr(s: *Self, prec: u8) anyerror!Node {
    var expr_ = switch (s.l.tok.?) {
        .type => {
            _ = try s.eat(.type);
            return .Type;
        },
        .comp => blk: {
            _ = try s.eat(.comp);
            break :blk Node{ .CompExpr = .{ .expr = try s.create_node_ptr(try s.expr(0)) } };
        },
        .identifier => try s.member_chain(),
        .dot => blk: {
            _ = try s.eat(.dot);
            break :blk switch (s.l.tok.?) {
                .lbrack => try s.array_init(),
                .lbrace => try s.struct_init(null),
                .identifier => try s.member_initializer(),
                else => @panic(""),
            };
        },
        .int, .float, .string, .char, .true, .false, .undefined, .null => blk: {
            const kind: LiteralKind = switch (s.l.tok.?) {
                .string => .string,
                .int => .int,
                .float => .float,
                .true => .boolean,
                .false => .boolean,
                .char => .char,
                .undefined => .undefined,
                .null => .null,
                else => @panic("We failed to get a proper literal kind"),
            };
            break :blk Node{ .Literal = .{ .kind = kind, .value = try s.eat(s.l.tok.?) } }; // literal node
        },
        .lparen => blk: {
            const state = s.save_lexer_state();
            break :blk s.fn_type() catch blk2: {
                s.restore_lexer_state(state);
                break :blk2 s.fn_(null) catch blk3: {
                    s.restore_lexer_state(state);
                    break :blk3 try s.grp_expr();
                };
            };
        },
        .bang, .flip, .sub, .@"and" => Node{ .Unary = .{ .op = try s.op(), .r = try s.create_node_ptr(try s.expr(0)) } },
        .lbrack, .mul, .question => try s.type_(),
        .@"if" => try s.if_(true),
        .match => try s.match(true),
        .@"struct" => try s.struct_(null),
        .@"enum" => try s.enum_(null),
        .@"error" => try s.error_(null),
        else => {
            std.debug.print("{} line: {} col: {}\n", .{ s.l.tok.?, s.l.line, s.l.col });
            @panic("Other Parser Error Here");
        },
    };
    while (s.l.tok.? != .eof and prec < s.precedence()) {
        expr_ = switch (s.l.tok.?) {
            .add, .sub, .mul, .div, .mod, .eq, .addeq, .subeq, .muleq, .modeq, .xoreq, .andeq, .oreq, .flipeq, .andand, .oror, .eqeq, .@"else", .@"or", .@"and", .dotdot => blk: {
                const new_prec = s.precedence();
                const op_ = try s.op();
                break :blk Node{ .Binary = .{ .l = try s.create_node_ptr(expr_), .op = op_, .r = try s.create_node_ptr(try s.expr(new_prec)) } };
            },
            else => {
                std.debug.print("{}\n", .{s.l.tok.?});
                @panic("Invalid infix operator");
            },
        };
    }
    return expr_;
}
fn op(s: *Self) !Op {
    const x = s.l.tok.?;
    _ = try s.eat(s.l.tok.?);
    return switch (x) {
        .add => .add,
        .addeq => .addeq,
        .sub => .sub,
        .subeq => .subeq,
        .mul => .mul,
        .muleq => .muleq,
        .div => .div,
        .diveq => .diveq,
        .mod => .mod,
        .modeq => .modeq,
        .xor => .xor,
        .xoreq => .xoreq,
        .@"and" => .@"and",
        .andeq => .andeq,
        .@"or" => .@"or",
        .oreq => .oreq,
        .@"else" => .@"else",
        .eqeq => .eqeq,
        .dotdot => .dotdot,
        .eq => .eq,
        else => @panic(""),
    };
}
fn precedence(s: *Self) u8 {
    return switch (s.l.tok.?) {
        .lparen, .lbrack, .dot => 17,
        .bang, .xor => 16,
        .mul, .div, .mod => 15,
        .add, .sub => 14,
        .@"and", .@"or" => 12,
        .lt, .gt => 11,
        .lteq, .gteq => 10,
        .eqeq, .bangeq => 9,
        .andand => 8,
        .oror => 7,
        .dotdot => 6,
        .eq, .addeq, .subeq, .muleq, .diveq, .modeq, .andeq, .oreq, .xoreq, .flipeq, .pointer_deref, .optional_deref, .@"else" => 2,
        else => 0,
    };
}
fn member_chain(s: *Self) !Node {
    var chain = try s.identifier();
    while (s.l.tok.? != .eof) {
        switch (s.l.tok.?) {
            .dot => chain = try s.member_access(try s.create_node_ptr(chain)),
            .lbrack => chain = try s.arr_index(try s.create_node_ptr(chain)),
            .lparen => chain = try s.fn_call(try s.create_node_ptr(chain)),
            .pointer_deref => chain = try s.pointer_deref(try s.create_node_ptr(chain)),
            .optional_deref => chain = try s.optional_deref(try s.create_node_ptr(chain)),
            else => break,
        }
    }
    return chain;
}
fn stmt(s: *Self) anyerror!Node {
    var x = switch (s.l.tok.?) {
        .@"if" => try s.if_(false),
        .@"while" => try s.while_(),
        .@"for" => try s.for_(),
        .@"defer" => try s.defer_(),
        .@"break" => try s.break_(),
        .@"return" => try s.return_(),
        .@"try" => try s.try_(),
        .@"inline" => try s.inline_(),
        .comp => try s.comp_stmt(),
        .mut => blk: {
            const v = try s.var_(null, true);
            break :blk v;
        },
        .lparen => blk: {
            const literal = try s.create_node_ptr(try s.fn_(null));
            break :blk try s.fn_call(literal);
        },
        .match => try s.match(false),
        .identifier => inner: {
            const ident = try s.member_chain();
            const x = switch (ident) {
                .Ident, .PointerDereference, .OptionalDereference, .ArrayIndex => switch (s.l.tok.?) {
                    .colon => blk: {
                        _ = try s.eat(.colon);
                        break :blk switch (s.l.tok.?) {
                            .lbrace => try s.block(try s.create_node_ptr(ident)),
                            else => blk2: {
                                var names = NodeList.init(s.a);
                                try names.append(ident);
                                const var_type = try s.create_node_ptr(try s.type_());
                                _ = try s.eat(.eq);
                                const var_default = try s.create_node_ptr(try s.expr(0));
                                break :blk2 Node{ .Var = .{ .mut = false, .names = names, .type = var_type, .default = var_default } };
                            }, // handle this as the ending of a var decl
                        };
                    },
                    .eq => blk2: {
                        _ = try s.eat(.eq);
                        const v = switch (s.l.tok.?) {
                            .lparen, .@"inline" => try s.fn_(try s.create_node_ptr(ident)),
                            .@"struct", .@"packed" => try s.struct_(try s.create_node_ptr(ident)),
                            .@"enum" => try s.enum_(try s.create_node_ptr(ident)),
                            .@"error" => try s.error_(try s.create_node_ptr(ident)),
                            else => blk3: {
                                const var_default = try s.create_node_ptr(try s.expr(0));
                                var idents = NodeList.init(s.a);
                                try idents.append(ident);
                                break :blk3 Node{ .Var = .{ .names = idents, .mut = false, .type = null, .default = var_default } };
                            },
                        };
                        break :blk2 v;
                    },
                    .addeq, .subeq, .muleq, .diveq, .modeq, .xoreq, .andeq, .oreq, .flipeq => blk2: {
                        const o = try s.op();
                        break :blk2 Node{ .OpAssign = .{ .l = try s.create_node_ptr(ident), .op = o, .r = try s.create_node_ptr(try s.expr(0)) } };
                    },
                    .comma => blk2: {
                        _ = try s.eat(.comma);
                        break :blk2 try s.var_(try s.create_node_ptr(ident), false);
                    },
                    else => {
                        std.debug.print("{}", .{s.l.tok.?});
                        @panic("");
                    },
                },
                else => ident,
            };
            break :inner x;
        },
        else => {
            std.debug.print("Got {any}, line: {}, col: {}", .{ s.l.tok.?, s.l.line, s.l.col });
            @panic("");
        },
    };
    if (s.l.tok.? == .@"catch") x = try s.catch_(try s.create_node_ptr(x));
    return x;
}
fn fn_call(s: *Self, caller: *Node) !Node {
    _ = try s.eat(.lparen);
    var args = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rparen) break;
        try args.append(try s.expr(0));
        if (s.l.tok.? == .rparen) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rparen);
    return Node{ .FnCall = .{ .caller = caller, .args = args } };
}
fn arr_index(s: *Self, ident: *Node) !Node {
    _ = try s.eat(.lbrack);
    const index = try s.create_node_ptr(try s.expr(0));
    _ = try s.eat(.rbrack);
    return Node{ .ArrayIndex = .{ .ident = ident, .index = index } };
}
fn member_access(s: *Self, ident: *Node) !Node {
    _ = try s.eat(.dot);
    const member_ = try s.create_node_ptr(try s.identifier());
    return Node{ .MemberAccess = .{ .accessed = ident, .member = member_ } };
}
fn while_(s: *Self) !Node {
    _ = try s.eat(.@"while");
    const condition = try s.create_node_ptr(try s.expr(0));
    const while_capture = if (s.l.tok.? == .@"or") try s.create_node_ptr(try s.capture()) else null;
    const body = try s.create_node_ptr(if (s.l.tok.? == .lbrace) try s.block(null) else try s.stmt());
    return Node{ .While = .{ .condition = condition, .capture = while_capture, .body = body } };
}
fn for_(s: *Self) !Node {
    _ = try s.eat(.@"for");
    var conditions = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .colon) break;
        try conditions.append(try s.expr(0));
        if (s.l.tok.? == .colon) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.colon);
    const for_capture_ = try s.create_node_ptr(try s.capture());
    const body = try s.create_node_ptr(if (s.l.tok.? == .lbrace) try s.block(null) else try s.stmt());
    return Node{ .For = .{ .condition = conditions, .capture = for_capture_, .body = body } };
}
fn for_capture(s: *Self) !Node {
    const mut_capture = if (s.l.tok.? == .mut) blk: {
        _ = try s.eat(.mut);
        break :blk true;
    } else false;
    const capture_ident = try s.create_node_ptr(try s.identifier());
    return Node{ .ForCapture = .{ .mut = mut_capture, .item = capture_ident } };
}
fn if_(s: *Self, is_expr: bool) anyerror!Node {
    _ = try s.eat(.@"if");
    const condition = try s.create_node_ptr(try s.expr(0));
    const if_capture = if (s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.create_node_ptr(try s.capture());
    } else null;
    const if_body = try s.create_node_ptr(if (is_expr) try s.expr(0) else blk: {
        break :blk if (s.l.tok.? == .lbrace) try s.block(null) else try s.stmt();
    });
    const if_next = if (s.l.tok.? == .@"else") blk: {
        _ = try s.eat(.@"else");
        break :blk try s.create_node_ptr(if (s.l.tok.? == .@"if") try s.if_(is_expr) else if (is_expr) try s.expr(0) else blk2: {
            break :blk2 if (s.l.tok.? == .lbrace) try s.block(null) else try s.stmt();
        });
    } else null;
    return Node{ .If = .{ .condition = condition, .capture = if_capture, .body = if_body, .if_next = if_next } };
}
fn match(s: *Self, expr_match: bool) !Node {
    _ = try s.eat(.match);
    const match_expression = try s.create_node_ptr(try s.expr(0));
    var branches = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        try branches.append(try s.match_branch(expr_match));
        if (s.l.tok.? == .rbrace) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rbrace);
    return Node{ .Match = .{ .expr = match_expression, .branches = branches } };
}
fn match_branch(s: *Self, expr_branch: bool) !Node {
    var exprs = NodeList.init(s.a);
    if (s.l.tok.? == .underscore) {
        _ = try s.eat(.underscore);
        try exprs.append(.Underscore);
    } else {
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .colon) break;
            try exprs.append(try s.expr(0));
            if (s.l.tok.? == .colon) break;
            _ = try s.eat(.comma);
        }
    }
    _ = try s.eat(.colon);
    const match_capture = if (s.l.tok.? == .@"or") try s.create_node_ptr(try s.capture()) else null;
    const result = try s.create_node_ptr(if (expr_branch) try s.expr(0) else blk: {
        break :blk if (s.l.tok.? == .lbrace) try s.block(null) else try s.stmt();
    });
    return Node{ .MatchBranch = .{ .exprs = exprs, .capture = match_capture, .result = result } };
}
fn capture(s: *Self) !Node {
    _ = try s.eat(.@"or");
    var captures = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .@"or") break;
        const capt_mut = if (s.l.tok.? == .mut) blk: {
            _ = try s.eat(.mut);
            break :blk true;
        } else false;
        const capt_ident = try s.create_node_ptr(try s.identifier());
        try captures.append(Node{ .CaptureMember = .{ .mut = capt_mut, .ident = capt_ident } });
        if (s.l.tok.? == .@"or") break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.@"or");
    return Node{ .Capture = .{ .captures = captures } };
}
fn identifier(s: *Self) !Node {
    return Node{ .Ident = .{ .value = try s.eat(.identifier) } };
}

fn pointer_deref(s: *Self, expr_: *Node) !Node {
    _ = try s.eat(.pointer_deref);
    return Node{ .PointerDereference = .{ .expr = expr_ } };
}
fn optional_deref(s: *Self, expr_: *Node) !Node {
    _ = try s.eat(.optional_deref);
    return Node{ .OptionalDereference = .{ .expr = expr_ } };
}
fn member_initializer(s: *Self) !Node {
    const ident = try s.create_node_ptr(try s.identifier());
    if (s.l.tok.? == .lbrace) return try s.struct_init(ident);
    const expr_ = if (s.l.tok.? == .lparen) blk: {
        _ = try s.eat(.lparen);
        const x = try s.create_node_ptr(try s.expr(0));
        _ = try s.eat(.rparen);
        break :blk x;
    } else null;
    return Node{ .MemberInitializer = .{ .name = ident, .val = expr_ } };
}
fn array_init(s: *Self) !Node {
    var exprs = NodeList.init(s.a);
    _ = try s.eat(.lbrack);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrack) break;
        try exprs.append(try s.expr(0));
        if (s.l.tok.? == .rbrack) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rbrack);
    return Node{ .ArrayInitializer = .{ .exprs = exprs } };
}
fn struct_init(s: *Self, ident: ?*Node) !Node {
    var fields = NodeList.init(s.a);
    var exprs = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        try fields.append(try s.identifier());
        _ = try s.eat(.colon);
        try exprs.append(try s.expr(0));
        if (s.l.tok.? == .rbrace) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rbrace);
    return Node{ .StructInitializer = .{ .ident = ident, .fields = fields, .exprs = exprs } };
}
fn defer_(s: *Self) !Node {
    _ = try s.eat(.@"defer");
    const defer_capture = if (s.l.tok.? == .@"or") try s.create_node_ptr(try s.capture()) else null;
    const defer_body = try s.create_node_ptr(if (s.l.tok.? == .lbrace) try s.block(null) else try s.stmt());
    return Node{ .Defer = .{ .capture = defer_capture, .body = defer_body } };
}
fn return_(s: *Self) !Node {
    _ = try s.eat(.@"return");
    const ret_val = if (s.l.tok.? == .semicolon) null else try s.create_node_ptr(try s.expr(0));
    return Node{ .Return = .{ .val = ret_val } };
}
fn break_(s: *Self) !Node {
    _ = try s.eat(.@"break");
    const break_label = if (s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.create_node_ptr(try s.identifier());
    } else null;
    const break_val = if (s.l.tok.? == .semicolon) null else try s.create_node_ptr(try s.expr(0));
    return Node{ .Break = .{ .label = break_label, .val = break_val } };
}
fn try_(s: *Self) !Node {
    _ = try s.eat(.@"try");
    return Node{ .Try = .{ .stmt = try s.create_node_ptr(try s.stmt()) } };
}
fn catch_(s: *Self, stmt_: *Node) !Node {
    _ = try s.eat(.@"catch");
    const catch_capture = if (s.l.tok.? == .@"or") try s.create_node_ptr(try s.capture()) else null;
    const catch_body = try s.create_node_ptr(if (s.l.tok.? == .lbrace) try s.block(null) else try s.stmt());
    return Node{ .Catch = .{ .stmt = stmt_, .capture = catch_capture, .body = catch_body } };
}
fn comp_stmt(s: *Self) !Node {
    _ = try s.eat(.comp);
    return Node{ .CompStmt = .{ .stmt = try s.create_node_ptr(try s.stmt()) } };
}
fn inline_(s: *Self) !Node {
    _ = try s.eat(.@"inline");
    return Node{ .InlineLoop = .{ .stmt = try s.create_node_ptr(switch (s.l.tok.?) {
        .@"for" => try s.for_(),
        .@"while" => try s.while_(),
        else => @panic("Invalid statement for inline"),
    }) } };
}
fn grp_expr(s: *Self) !Node {
    _ = try s.eat(.lparen);
    const group_expr = try s.expr(0);
    _ = try s.eat(.rparen);
    return Node{ .Group = .{ .expr = try s.create_node_ptr(group_expr) } }; // GroupExpr
}
fn fn_type(s: *Self) !Node {
    var args = NodeList.init(s.a);
    _ = try s.eat(.lparen);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rparen) break;
        try args.append(try s.type_());
        if (s.l.tok.? == .rparen) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rparen);
    const return_type = if (s.l.tok.? == .semicolon or s.l.tok.? == .lbrace or s.l.tok.? == .arrow) null else try s.create_node_ptr(try s.type_());
    if (s.l.tok.? == .lbrace or s.l.tok.? == .arrow) return Error.ParserError;
    return Node{ .FnType = .{ .args = args, .type = return_type } };
}
fn save_lexer_state(s: *Self) LexerState {
    return LexerState{
        .tok = s.l.tok,
        .literal = s.l.literal,
        .line = s.l.line,
        .col = s.l.col,
        .index = s.l.index,
    };
}
fn restore_lexer_state(s: *Self, state: LexerState) void {
    s.l.tok = state.tok;
    s.l.literal = state.literal;
    s.l.line = state.line;
    s.l.col = state.col;
    s.l.index = state.index;
}
fn eat(s: *Self, expected: Token) ![]const u8 {
    if (s.l.tok.? != expected) {
        std.debug.print("Wanted {any}, got {any}, l: {}, c: {} \n", .{ expected, s.l.tok.?, s.l.line, s.l.col });
        return Error.ParserError;
    }
    defer s.l.next_tok();
    return s.l.literal orelse "";
}
fn create_node_ptr(s: *Self, n: Node) !*Node {
    const x = try s.a.create(Node);
    x.* = n;
    return x;
}
