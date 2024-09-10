const std = @import("std");
const ast = @import("ast.zig");
const lexer = @import("lexer.zig");
const token = @import("token.zig");
const errors = @import("errors.zig");

pub const Parser = struct {
    l: lexer.Lexer,
    allocator: std.mem.Allocator,

    pub fn init(
        alloc: std.mem.Allocator,
        b: []const u8,
    ) Parser {
        return Parser{ .l = lexer.Lexer.init(b), .allocator = alloc };
    }
    pub fn parse(s: *Parser) ?ast.Node {
        return s.program();
    }
    pub fn program(s: Parser) ?ast.Node {
        return ast.Node.init(s.allocator, .program, null);
    }
};
