const std = @import("std");
const File = @import("file.zig");

name: []const u8,
files: std.ArrayList(),
a: std.mem.Allocator,

const Module = @This();

pub fn init(a: std.mem.Allocator, name: []const u8) Module {
    return .{ .name = name, .a = a, .files = std.ArrayList(File).init(a) };
}
