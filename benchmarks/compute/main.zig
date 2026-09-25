const std = @import("std");
pub fn main() !void {
    var value: u64 = 1;
    for (0..50_000_000) |_| value = (value *% 1_664_525 +% 1_013_904_223) & 0xffffffff;
    std.debug.print("{d}\n", .{value});
}
