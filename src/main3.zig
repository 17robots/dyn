const std = @import("std");

const Compiler = struct {};
const Preferences = struct {};
const CompilerBuilder = struct {};

pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const allocator = arena.allocator();
}
