const std = @import("std");

fn print(init: std.process.Init, value: anytype) !void {
    var buffer: [64]u8 = undefined;
    var writer = std.Io.File.stdout().writer(init.io, &buffer);
    try writer.interface.print("{d}\n", .{value});
    try writer.interface.flush();
}

const Point = struct { x: i64, y: i64 };
var points: [4096]Point = undefined;

fn step(p: Point, d: Point) Point {
    return .{ .x = @rem(p.x + d.x, 1000003), .y = @rem(p.y * 3 + d.y, 1000003) };
}

pub fn main(init: std.process.Init) !void {
    for (&points, 0..) |*p, i| p.* = .{ .x = @intCast(i), .y = @intCast(i * 7) };
    const delta = Point{ .x = 5, .y = 11 };
    for (0..2000) |_| {
        for (&points) |*p| p.* = step(p.*, delta);
    }
    var total: i64 = 0;
    for (points) |p| total += p.x + p.y;
    try print(init, total);
}
