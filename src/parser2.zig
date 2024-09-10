const std = @import("std");
const ast = @import("ast.zig");
const lexer = @import("lexer.zig");
const token = @import("token.zig");
const errors = @import("errors.zig");

const Parser = struct {
    l: lexer.Lexer,
    allocator: std.mem.Allocator,

    pub fn init(
        alloc: std.mem.Allocator,
        b: []const u8,
    ) Parser {
        return Parser{ .l = lexer.Lexer.init(b), .allcloator = alloc };
    }
    pub fn parse(s: *Parser) ?ast.Node {
        return s.program();
    }
    pub fn program() ?ast.Node {
        return ast.Node.init(.program, null);
    }
};
