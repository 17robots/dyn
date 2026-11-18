const std = @import("std");

fn print(init: std.process.Init, value: anytype) !void {
    var buffer: [64]u8 = undefined;
    var writer = std.Io.File.stdout().writer(init.io, &buffer);
    try writer.interface.print("{d}\n", .{value});
    try writer.interface.flush();
}

var flags: [8000000]u8 = undefined;

pub fn main(init: std.process.Init) !void {
    var total: u64 = 0;
    for (0..10) |round| {
        @memset(&flags, 1);
        var count: u64 = 0;
        var i: usize = 2;
        while (i < flags.len) : (i += 1) {
            if (flags[i] == 1) {
                count += 1;
                var j = i * 2;
                while (j < flags.len) : (j += i) flags[j] = 0;
            }
        }
        total += count + round;
    }
    try print(init, total);
}
