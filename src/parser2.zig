const std = @import("std");
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const Diagnostic = @import("diagnostic.zig").Diagnostic;
const Lexer = @import("lexer.zig");
const NodeType = @import("ast2.zig").NodeType;
const Node = @import("ast2.zig").Node;
const Source = @import("source.zig").Source;
const SourceLocation = @import("source.zig").SourceLocation;
const Token = @import("token2.zig").Token;
const TokenType = @import("token2.zig").TokenType;
const Span = @import("token2.zig").Span;
const Parser = @This();
const ParserError = error{
    recoverable,
    fatal,
};

allocator: std.mem.Allocator,
diag: *DiagnosticEmitter,
lexer: Lexer,
source: *Source,
curr_tok: Token,
next_tok: Token,
peek_tok: Token,

pub fn init(allocator: std.mem.Allocator, source: *Source, diagnostics: *DiagnosticEmitter) Parser {
    var parser = Parser{ .allocator = allocator, .source = source, .lexer = Lexer.init(source, diagnostics), .diag = diagnostics, .curr_tok = undefined, .next_tok = undefined, .peek_tok = undefined };
    parser.advance();
    parser.advance();
    parser.advance();
    return parser;
}
fn advance(s: *Parser) void {
    s.curr_tok = s.next_tok;
    s.next_tok = s.peek_tok;
    s.peek_tok = s.lexer.next();
}
fn create_node_ptr(s: *Parser, n: Node) *Node {
    const x = s.allocator.create(Node) catch |e| @panic(@errorName(e));
    x.* = n;
    return x;
}
fn expect(s: *Parser, expected: TokenType) ParserError!void {
    if (s.curr_tok.type == .invalid) return ParserError.fatal;
    if (s.curr_tok.type != expected) {
        s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Unexpected token {any}, expected {any}", .{ s.curr_tok.type, expected });
        return ParserError.recoverable;
    }
    s.advance();
}
fn should_read_semicolon(n: Node) bool {
    return switch (n.type) {
        .if_statement => |i| if (i.else_body) |e| should_read_semicolon(e.*) else should_read_semicolon(i.body.*),
        .for_statement => |i| should_read_semicolon(i.body.*),
        .while_statement => |i| should_read_semicolon(i.body.*),
        .block, .match => false,
        .defer_statement => |i| should_read_semicolon(i.body.*),
        else => true,
    };
}
fn precedence(s: *Parser) u8 {
    return switch (s.curr_tok.type) {
        .dot, .lbrack, .lparen => 17,
        .bang, .xor => 16,
        .div, .mod, .mul => 15,
        .add, .sub => 14,
        .nullish => 13,
        .@"and", .@"or" => 12,
        .gt, .lt => 11,
        .gteq, .lteq => 10,
        .bangeq, .eqeq => 9,
        .andand => 8,
        .oror => 7,
        .dotdot => 6,
        else => 0,
    };
}
fn sync(s: *Parser, toks: []const TokenType) void {
    while (s.curr_tok.type != .eof) {
        if (std.mem.indexOf(TokenType, toks, &[_]TokenType{s.curr_tok.type})) |_| {
            s.advance();
            return;
        }
        s.advance();
    }
}
