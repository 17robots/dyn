const std = @import("std");

pub fn bufferedPrint(writer: *std.Io.Writer, comptime fmt: []const u8, args: anytype) !void {
    try writer.print(fmt, args);
    try writer.flush();
}
