const std = @import("std");
const l = @import("lexer.zig");

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    const alloc = gpa.allocator();
    defer _ = gpa.deinit();
    std.debug.print("Token len {d}\n", .{l.lex(alloc, "u8 x = 5;").items.len});
}
