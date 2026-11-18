const std = @import("std");

fn print(init: std.process.Init, value: anytype) !void {
    var buffer: [64]u8 = undefined;
    var writer = std.Io.File.stdout().writer(init.io, &buffer);
    try writer.interface.print("{d}\n", .{value});
    try writer.interface.flush();
}

const Body = struct { x: f64, y: f64, z: f64, vx: f64, vy: f64, vz: f64, mass: f64, charge: f64 };
var bodies: [1024]Body = undefined;

fn energy(b: Body, scale: f64) f64 {
    return 0.5 * b.mass * (b.vx * b.vx + b.vy * b.vy + b.vz * b.vz) * scale + b.charge * (b.x + b.y + b.z);
}

pub fn main(init: std.process.Init) !void {
    for (&bodies, 0..) |*b, i| {
        const v: f64 = @floatFromInt(i % 13);
        b.* = .{ .x = v, .y = v * 2, .z = v * 3, .vx = v * 0.5, .vy = v * 0.25, .vz = v * 0.125, .mass = 1 + v, .charge = 0.5 };
    }
    var total: f64 = 0;
    for (0..20000) |round| {
        for (bodies) |b| total += energy(b, 1.0 + @as(f64, @floatFromInt(round % 3)));
    }
    try print(init, @as(u64, @intFromFloat(total)));
}
