const std = @import("std");
const l = @import("lexer.zig");

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer std.debug.assert(gpa.deinit() == .ok);
    const alloc = gpa.allocator();
    var t = l.Tokenizer.init(&alloc, "i8 x = 5");
    defer t.deinit();
    errdefer t.deinit();
    try t.lex();
    for (t.tokens.items) |v| {
        std.debug.print("{d}, {s}\n", .{ v.t, v.v });
    }
}
