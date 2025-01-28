const std = @import("std");
const Lexer = @import("lexer.zig");
const Token = @import("token.zig").TokenType;
const Error = @import("errors.zig").Error;
const Node = @import("ast.zig").Node;
const LiteralKind = @import("ast.zig").LiteralKind;
const Op = @import("ast.zig").Op;
const NodeList = std.ArrayList(Node);

const Self = @This();

l: Lexer,
a: std.mem.Allocator,

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
    return switch (s.l.tok.?) {
        .comma => blk: {
            _ = try s.eat(.comma);
            break :blk try s.var_(ident, false);
        },
        .colon => try s.var_(ident, false),
        .eq => blk: {
            _ = try s.eat(.eq);
            break :blk switch (s.l.tok.?) {
                .lparen, .@"inline" => blk2: {
                    const x = try s.fn_(ident);
                    switch (x) {
                        .Fn => |a| {
                            if (a.body.* != .Block) _ = try s.eat(.semicolon);
                            break :blk2 x;
                        },
                        else => @panic("We asked for a fn and didnt get that oops"),
                    }
                    break :blk2 x;
                },
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
            if (s.l.tok.? == .colon) break;
            try members.append(try s.identifier());
            if (s.l.tok.? == .colon) break;
            _ = try s.eat(.comma);
        }
        _ = try s.eat(.colon);
        const member_type = try s.create_node_ptr(try s.type_());
        const member_default = if (s.l.tok.? == .eq) blk: {
            _ = try s.eat(.eq);
            break :blk try s.create_node_ptr(try s.expr(0));
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
    if (fn_args_names_without_types.items.len > 0) @panic("Not all identifiers in the fn have a type");
    _ = try s.eat(.rparen);
    const fn_type: ?*Node = if (s.l.tok.? == .lbrace or s.l.tok.? == .arrow) null else try s.create_node_ptr(try s.type_());
    const fn_body = if (s.l.tok.? == .lbrace) try s.create_node_ptr(try s.block(null)) else if (s.l.tok.? == .arrow) blk: {
        _ = try s.eat(.arrow);
        break :blk try s.create_node_ptr(try s.expr(0));
    } else @panic("Please use either => or {} for a fn body");
    return Node{ .Fn = .{ .name = ident, .args = fn_args, .type = fn_type, .body = fn_body } };
}
// todo: switch this to ?*Node syntax instead of Node*?
fn type_(s: *Self) !Node {
    var t: Node = undefined;
    switch (s.l.tok.?) {
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
            while (true) {
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
        else => @panic("This is not a type"),
    }
    return t;
}
fn block(s: *Self, label: ?*Node) anyerror!Node {
    var stmts = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        try stmts.append(try s.stmt());
        if (s.l.tok.? == .rbrace) break;
    }
    _ = try s.eat(.rbrace);
    return Node{ .Block = .{ .label = label, .stmts = stmts } };
}
fn expr(s: *Self, prec: u8) anyerror!Node {
    var expr_ = switch (s.l.tok.?) {
        .identifier => try s.identifier(),
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
            _ = try s.eat(.lparen);
            const group_expr = try s.expr(0);
            _ = try s.eat(.rparen);
            break :blk Node{ .Group = .{ .expr = try s.create_node_ptr(group_expr) } }; // GroupExpr
        },
        .bang, .flip, .sub, .@"and" => Node{ .Unary = .{ .op = try s.op(), .r = try s.create_node_ptr(try s.expr(0)) } },
        .lbrack, .mul, .question => try s.type_(),
        .@"if" => try s.if_(true),
        .match => try s.match(true),
        else => {
            std.debug.print("{}\n", .{s.l.tok.?});
            @panic("Other Parser Error Here");
        },
    };
    while (s.l.tok.? != .eof and prec < s.precedence()) {
        expr_ = switch (s.l.tok.?) {
            .add, .sub, .mul, .div, .mod, .eq, .addeq, .subeq, .muleq, .modeq, .xoreq, .andeq, .oreq, .flipeq, .andand, .oror, .@"else", .@"or", .@"and" => blk: {
                const new_prec = s.precedence();
                const op_ = try s.op();
                break :blk Node{ .Binary = .{ .l = try s.create_node_ptr(expr_), .op = op_, .r = try s.create_node_ptr(try s.expr(new_prec)) } };
            },
            .lparen => try s.fn_call(try s.create_node_ptr(expr_)),
            .lbrack => try s.arr_index(try s.create_node_ptr(expr_)),
            .dot => try s.member_access(try s.create_node_ptr(expr_)),
            .pointer_deref => try s.pointer_deref(try s.create_node_ptr(expr_)),
            .optional_deref => try s.optional_deref(try s.create_node_ptr(expr_)),
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
        .eq, .addeq, .subeq, .muleq, .diveq, .modeq, .andeq, .oreq, .xoreq, .flipeq, .pointer_deref, .optional_deref, .@"else" => 2,
        else => 0,
    };
}
fn stmt(s: *Self) anyerror!Node {
    return switch (s.l.tok.?) {
        .@"if" => try s.if_(false),
        .@"while" => try s.while_(),
        .@"for" => try s.for_(),
        .mut => blk: {
            const v = try s.var_(null, true);
            _ = try s.eat(.semicolon);
            break :blk v;
        },
        .lparen => blk: {
            const literal = try s.create_node_ptr(try s.fn_(null));
            break :blk try s.fn_call(literal);
        },
        .match => try s.match(false),
        .identifier => blk: {
            const ident = try s.identifier();
            break :blk switch (s.l.tok.?) {
                .colon => {
                    _ = try s.eat(.colon);
                    break :blk switch (s.l.tok.?) {
                        .lbrace => try s.block(try s.create_node_ptr(ident)),
                        else => blk2: {
                            var names = NodeList.init(s.a);
                            try names.append(ident);
                            const var_type = try s.create_node_ptr(try s.type_());
                            _ = try s.eat(.eq);
                            const var_default = try s.create_node_ptr(try s.expr(0));
                            _ = try s.eat(.semicolon);
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
                    _ = try s.eat(.semicolon);
                    break :blk2 v;
                },
                .lparen => blk2: {
                    const v = try s.fn_call(try s.create_node_ptr(ident));
                    _ = try s.eat(.semicolon);
                    break :blk2 v;
                },
                .comma => blk2: {
                    _ = try s.eat(.comma);
                    break :blk2 try s.var_(try s.create_node_ptr(ident), false);
                },
                else => @panic(""),
            };
        },
        else => {
            std.debug.print("Got {any}", .{s.l.tok.?});
            @panic("");
        },
    };
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
        if (s.l.tok.? == .@"or") break;
        try conditions.append(try s.expr(0));
        if (s.l.tok.? == .@"or") break;
        _ = try s.eat(.comma);
    }
    const for_capture = try s.create_node_ptr(try s.capture());
    const body = try s.create_node_ptr(if (s.l.tok.? == .lbrace) try s.block(null) else try s.stmt());
    return Node{ .For = .{ .condition = conditions, .capture = for_capture, .body = body } };
}
fn if_(s: *Self, is_expr: bool) anyerror!Node {
    _ = try s.eat(.@"if");
    const condition = try s.create_node_ptr(try s.expr(0));
    const if_capture = if (s.l.tok.? == .@"or") try s.create_node_ptr(try s.capture()) else null;
    const if_body = try s.create_node_ptr(if (is_expr) try s.expr(0) else try s.stmt());
    const if_next = if (s.l.tok.? == .@"else") blk: {
        _ = try s.eat(.@"else");
        break :blk try s.create_node_ptr(if (s.l.tok.? == .@"if") try s.if_(is_expr) else if (is_expr) try s.expr(0) else try s.stmt());
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
    }
    _ = try s.eat(.rbrace);
    return Node{ .Match = .{ .expr = match_expression, .branches = branches } };
}
fn match_branch(s: *Self, expr_branch: bool) !Node {
    var exprs = NodeList.init(s.a);
    if (s.l.tok.? == .underscore) {
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
    const result = try s.create_node_ptr(if (expr_branch) try s.expr(0) else try s.stmt());
    return Node{ .MatchBranch = .{ .exprs = exprs, .result = result } };
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
fn eat(s: *Self, expected: Token) ![]const u8 {
    if (s.l.tok.? != expected) {
        std.debug.print("Wanted {any}, got {any}\n", .{ expected, s.l.tok.? });
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
