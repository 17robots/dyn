const std = @import("std");

fn print(init: std.process.Init, value: anytype) !void {
    var buffer: [64]u8 = undefined;
    var writer = std.Io.File.stdout().writer(init.io, &buffer);
    try writer.interface.print("{d}\n", .{value});
    try writer.interface.flush();
}

var text: [1048576]u8 = undefined;

fn fnv(data: []const u8) u64 {
    var h: u64 = 14695981039346656037;
    for (data) |byte| h = (h ^ byte) *% 1099511628211;
    return h;
}

pub fn main(init: std.process.Init) !void {
    for (&text, 0..) |*byte, i| byte.* = @intCast(i % 251);
    var total: u64 = 0;
    for (0..100) |round| {
        text[round] = @intCast(round);
        total +%= fnv(&text);
    }
    try print(init, total);
}
