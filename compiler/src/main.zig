const std = @import("std");
const l = @import("lexer.zig").Tokenizer;

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer std.testing.expect(gpa.deinit() == .ok) catch @panic("uh oh leak time");
    var t = l.init(gpa.allocator(), "i8 x = 5;");
    defer t.deinit();
    try t.lex();
    for (t.tokens.items) |tok| {
        std.debug.print("{}, {s}\n", .{ tok.t, tok.v });
    }
}
