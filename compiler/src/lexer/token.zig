const std = @import("std");
const string = @import("../util.zig").string;

pub const Token = struct {
    type: string,
    val: string,
    start: usize,
    end: usize,
    pub fn new(_type: string, val: string, s: usize, e: usize) Token {
        return .{
            .type = _type,
            .val = val,
            .start = s,
            .end = e,
        };
    }
};

pub fn print_token(t: Token) void {
    std.debug.print("{s}({s}), start: {d}, end: {d}\n", .{ t.type, t.val, t.start, t.end });
}
