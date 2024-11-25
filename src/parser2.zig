const std = @import("std");
const Lexer = @import("lexer.zig").Lexer;
const Token = @import("token.zig").TokenType;
const Error = @import("errors.zig").Error;

const Self = @This();

l: Lexer,
a: std.mem.Allocator,
pub fn init(alloc: std.mem.Allocator, buf: []const u8) Self {
    return Self{ .l = Lexer.init(buf), .a = alloc };
}
pub fn program(s: *Self) !Node {
    const pubs = s.create_node_list();
    const privs = s.create_node_list();
    return Node{ .Program = .{ .pub_decls = pubs, .priv_decls = privs } };
}
fn decl(s: *Self) !Node { }
fn module(s: *Self) !Node {}
fn struct_parse(s: *Self) !Node {}
fn enum_parse(s: *Self) !Node {}
fn error_parse(s: *Self) !Node {}
fn typing(s: *Self) !Node {
    var base = switch(s.l.tok.?) {
        .@"struct" => s.struct_parse(),
        .@"enum" => s.enum_parse(),
        .@"error" => s.error_parse(),
        .identifier => Node.Identifier{ .value = try s.consume(.identifier)},
        else => return Error.SelfError,
    };
    while(s.l.tok.? != .eof) {
        switch(s.l.tok.?) {
            .lbrack => {
                _ = try s.consume(.lbrack);
                _ = try s.consume(.rbrack);
                base = Node.ArrayType{ .expr = try s.create_node_pointer(base)};
            },
            .mul => {
                _ = try s.consume(.mul);
                base = Node.PointerType{ .expr = try s.create_node_pointer(base)};
            },
            .question => {
                _ = try s.consume(.question);
                base = Node.OptionalType{ .expr = try s.create_node_pointer(base)};
            },
            .bang => {},
            .lparen => {
                var arg_types = try s.create_node_list();
                try s.read_list(.lparen, .rparen, .comma, struct {
                    pub fn do_thing() !void {
                        try arg_types.append(Identifier{ .value = try s.consume(.identifier)});
                    }
                }.do_thing);
            },
        }
    }
}
fn read_list(s: *Self, begin_tok: Token, end_token: Token, separator: Token, something: fn() anyerror!void) !void {
    _ = try s.consume(begin_tok);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == end_token) break;
        something();
        if(s.l.tok.? == end_token) break;
        _ = try s.consume(separator);
    }
    _ = try s.consume(end_token);
}
fn create_node_pointer(s: *Self, n: Node) !*Node {
    const node = try s.a.create(Node);
    errdefer s.a.destroy(node);
    node.* = n;
    return node;
}
fn create_node_list(s: *Self) std.ArrayList(Node) {
    return std.ArrayList(Node).init(s.a);
}
fn consume(s: *Self, t: Token) []const u8 {
    if(s.l.tok.? != t) {}
    defer s.l.next_tok();
    return s.l.literal orelse "";
}

const Node = union(enum) {
    Program: struct { pub_decls: std.ArrayList(Node), priv_decls: std.ArrayList(Node) },
    Identifier: struct { value: []const u8 },
    ArrayType: struct { expr: *Node },
    PointerType: struct { expr: *Node },
    OptionalType: struct { expr: *Node },
};
