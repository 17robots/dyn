const std = @import("std");
const Tok = @import("token.zig").Tok;
const Span = @import("token.zig").Span;
const Ast = @import("ast.zig");
const Lexer = @import("lexer.zig");

const ParserError = struct { span: Span, message: []const u8 };
const Self = @This();

allocator: std.mem.Allocator,
toks: []const Tok,
i: usize = 0,

pub fn init(allocator: std.mem.Allocator, toks: []const Tok) Self {
    return .{ .allocator = allocator, .toks = toks };
}
pub fn parse(self: *Self) !Ast {
    var ast = Ast.init(self.allocator);
}
