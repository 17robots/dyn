const std = @import("std");

fn print(init: std.process.Init, value: anytype) !void {
    var buffer: [64]u8 = undefined;
    var writer = std.Io.File.stdout().writer(init.io, &buffer);
    try writer.interface.print("{d}\n", .{value});
    try writer.interface.flush();
}

var a: [65536]f64 = undefined;
var b: [65536]f64 = undefined;
var c: [65536]f64 = undefined;

pub fn main(init: std.process.Init) !void {
    const n: usize = 256;
    for (0..n * n) |i| {
        a[i] = @as(f64, @floatFromInt(i % 7)) * 0.5;
        b[i] = @as(f64, @floatFromInt(i % 5)) * 0.25;
    }
    for (0..8) |round| {
        for (0..n) |i| {
            for (0..n) |j| {
                var sum: f64 = 0.0;
                for (0..n) |k| sum += a[i * n + k] * b[k * n + j];
                c[i * n + j] = sum + @as(f64, @floatFromInt(round));
            }
        }
    }
    var total: f64 = 0.0;
    for (c) |value| total += value;
    try print(init, @as(u64, @intFromFloat(total)));
}
