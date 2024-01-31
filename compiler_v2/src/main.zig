const std = @import("std");
const l = @import("lexer.zig");

pub fn main() !void {
    std.debug.print("Token len {d}\n", .{l.lex("u8 x = 5;").items.len});
}
