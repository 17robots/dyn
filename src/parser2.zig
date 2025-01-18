const std = @import("std");
const Lexer = @import("lexer.zig");
const Token = @import("token.zig").TokenType;
const Error = @import("errors.zig").Error;
const Node = @import("ast2.zig").Node;
const NodeList = std.ArrayList(Node);

const Self = @This();

l: Lexer,
a: std.mem.Allocator,

pub fn init(alloc: std.mem.Allocator, buf: []const u8) Self {
    return Self{ .l = Lexer.init(buf), .a = alloc };
}
fn program(s: *Self) !Node {
    s.l.next_tok();
    var pub_decls = NodeList.init(s.a);
    var decls = NodeList.init(s.a);
    try pub_decls.append(try s.module());
    while (s.l.tok.? != .eof) {
        const eat_public = if (s.l.tok.? == .@"pub") blk: {
            _ = try s.eat(.@"pub");
            break :blk true;
        } else false;
        if (eat_public) try pub_decls.append(try s.decl(false)) else try decls.append(try s.decl(false));
    }
    return Node{ .Program = .{ .decls = decls, .pub_decls = pub_decls } };
}
fn module(s: *Self) !Node {
    _ = try s.eat(.module);
    const module_ = Node{ .ModuleDecl = .{ .name = try s.create_node_ptr(Node{ .Literal = .{ .type = .string, .value = try s.eat(.string) } }) } };
    _ = try s.eat(.semicolon);
    return module_;
}
fn use(s: *Self) anyerror!Node {
    _ = try s.eat(.use);
    const alias = switch (s.l.tok.?) {
        .identifier => try s.create_node_ptr(try s.identifier()),
        else => null,
    };
    const import = try s.create_node_ptr(Node{ .Literal = .{ .type = .string, .value = try s.eat(.string) } });
    return Node{ .UseStmt = .{ .alias = alias, .value = import } };
}
fn decl(s: *Self, allow_mut: bool) !Node {
    if (s.l.tok.? == .mut) {
        if (!allow_mut) @panic("Declaration cannot be mut in this scope");
        _ = try s.eat(.mut);
        return s.var_(null);
    }
    const ident = try s.create_node_ptr(try s.identifier());
    return switch (s.l.tok.?) {
        .lparen, .@"inline" => try s.fn_(ident),
        .@"struct", .@"packed" => try s.struct_(ident),
        .@"enum" => try s.enum_(ident),
        .@"error" => try s.error_(ident),
        else => try s.var_(ident),
    };
}
fn struct_(s: *Self, ident: ?*Node) !Node {
    if (s.l.tok.? == .@"packed") _ = try s.eat(.@"packed");
    _ = try s.eat(.@"struct");
    var members = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        try members.appendSlice(try s.member());
        if (s.l.tok.? == .rbrace) break;
    }
    _ = try s.eat(.rbrace);
    return Node{ .Struct = .{ .name = ident } };
}
fn enum_(s: *Self, ident: ?*Node) !Node {
    _ = try s.eat(.@"enum");
    var members = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        try members.appendSlice(try s.member());
        if (s.l.tok.? == .rbrace) break;
    }
    _ = try s.eat(.rbrace);
    return Node{ .Enum = .{ .name = ident } };
}
fn error_(s: *Self, ident: ?*Node) !Node {
    _ = try s.eat(.@"error");
    var members = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        try members.appendSlice(try s.member());
        if (s.l.tok.? == .rbrace) break;
    }
    _ = try s.eat(.rbrace);
    return Node{ .Error = .{ .name = ident } };
}
fn member(s: *Self, allow_list: bool) ![]Node {
    var members = try NodeList.init(s.a);
    if (allow_list) {
        var idents_no_type = std.ArrayList([]const u8).init(s.a);
        defer idents_no_type.deinit();
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .colon) break;
            try idents_no_type.append(try s.eat(.identifier));
            if (s.l.tok.? == .colon) break;
            _ = try s.eat(.comma);
        }
        _ = try s.eat(.colon);
        const member_type = try s.type_();
        const member_d.Node{ .Type }ault = if (s.l.tok.? == .eq) blk: {
            _ = try s.eat(.eq);
            break :blk try s.create_node_ptr(try s.expr());
        } else null;
        for (idents_no_type.items) |i| try members.append(Node{ .Member = .{ .ident = try s.create_node_ptr(Node{ .Ident = .{ .value = i } }), .type = member_type, .default = member_default } });
        return members.toOwnedSlice();
    }
    const member_ident = try s.create_node_ptr(try s.identifier());
    if (s.l.tok.? == .eq) return try s.decl(member_ident);
    const member_type: ?*Node = if (s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.create_node_ptr(s.type_());
    } else null;
    const default = if (s.l.tok.? == .eq) blk: {
        _ = try s.eat(.eq);
        break :blk try s.create_node_ptr(try s.expr());
    } else null;
    try members.append(Node{ .Member = .{ .ident = member_ident, .type = member_type, .default = default } });
    return members.toOwnedSlice();
}
// todo: support var1,var2,var3 syntax
fn var_(s: *Self, first_ident: ?*Node) ![]Node {
    var idents_no_type = std.ArrayList([]const u8).init(s.a);
    defer idents_no_type.deinit();
    const mut = if (s.l.tok.? == .mut) blk: {
        _ = try s.eat(.mut);
        break :blk true;
    } else false;
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .colon or s.l.tok.? == .eq) break;
        try idents_no_type.append(try s.eat(.identifier));
        if (s.l.tok.? == .colon or s.l.tok.? == .eq) break;
        try s.eat(.comma);
    }
    var vars = NodeList.init(s.a);
    const var_type: ?*Node = if (s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.create_node_ptr(try s.type_());
    } else null;
    const var_default: ?*Node = if (s.l.tok.? == .eq) blk: {
        _ = try s.eat(.eq);
        break :blk try s.create_node_ptr(try s.expr());
    } else null;
    if (first_ident) |fi| try vars.append(Node{ .Var = .{ .name = fi, .mut = mut, .type = var_type, .default = var_default } });
    for (idents_no_type) |i| try vars.append(Node{ .Var = .{ .name = try s.create_node_ptr(Node{ .Ident = .{ .value = i } }), .mut = mut, .type = var_type, .default = var_default } });
    return vars.toOwnedSlice();
}
fn fn_(s: *Self, ident: *Node) !Node {
    _ = try s.eat(.lparen);
    var fn_args_names_without_types = std.ArrayList([]const u8).init(s.a);
    defer fn_args_names_without_types.deinit();
    var fn_args = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rparen) break;
        try fn_args_names_without_types.append(try s.eat(.identifier));
        if (s.l.tok.? == .colon) {
            _ = try s.eat(.colon);
            const arg_type = try s.create_node_ptr(try s.type_());
            const arg_default: ?*Node = if (s.l.tok.? == .eq) blk: {
                _ = try s.eat(.eq);
                break :blk try s.create_node_ptr(try s.expr());
            } else null;
            for (fn_args_names_without_types.items) |i| {
                const arg_ident = try s.create_node_ptr(Node{ .Ident = .{ .value = i } });
                try fn_args.append(Node{ .Member = .{ .ident = arg_ident, .type = arg_type, .default = arg_default } });
            }
            fn_args_names_without_types.deinit();
            fn_args_names_without_types = NodeList.init(s.a);
        }
        if (s.l.tok.? == .rparen) break;
        _ = try s.eat(.comma);
    }
    if (fn_args_names_without_types.items.len > 0) @panic("Not all identifiers in the fn have a type");
    _ = try s.eat(.rparen);
    const fn_type: ?*Node = if (s.l.tok.? == .lbrace or s.l.tok.? == .arrow) null else try s.create_node_ptr(try s.type_());
    const fn_body = if (s.l.tok.? == .rbrace) try s.create_node_ptr(try s.block()) else if (s.l.tok.? == .arrow) blk: {
        _ = try s.eat(.arrow);
        break :blk try s.create_node_ptr(try s.expr());
    } else @panic("Please use either => or {} for a fn body");
    return Node{ .Fn = .{ .name = ident, .args = fn_args, .type = fn_type, .body = fn_body } };
}
fn type_(s: *Self) !Node {
    var t: Node = switch (s.l.tok.?) {
        .lparen => Node{ .GroupType = .{ .type = try s.create_node_ptr(try s.type_()) } },
        .identifier => try s.identifier(),
        .@"enum" => try s.enum_(null),
        .@"struct" => try s.struct_(null),
        .type => {
            _ = try s.eat(.type);
            return .Node{.Type};
        },
    };
    while(true) {
        switch(s.l.tok.?) {
            .lbrack => {
                _ = try s.eat(.lbrack);
                _ = try s.eat(.rbrack);
                t = Node{ .ArrayType = .{ .type = try s.create_node_ptr(t) }};
            },
            .question => {
                _ = try s.eat(.question);
                t = Node{ .OptionalType = .{ .type = try s.create_node_ptr(t) }};
            },
            .mul => {
                _ = try s.eat(.mul);
                t = Node{ .PointerType = .{ .type = try s.create_node_ptr(t) }};
            },
        }
        break;
    }
}
fn block(s: *Self) !Node {
    _ = s;
}
fn expr(s: *Self) !Node {
    _ = s;
}
fn stmt(s: *Self) !Node {
    _ = s;
}
fn eat(s: *Self, expected: Token) ![]const u8 {
    if (s.l.tok.? != expected) return Error.ParserError;
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
