const std = @import("std");
const dyn = @import("dyn");

pub fn main() !void {
    try dyn.bufferedPrint();
}
