const std = @import("std");
const File = @import("file.zig");

const Checker = @This();

const Module = struct {
    name: []const u8,
    files: std.ArrayList(File),
    a: std.mem.Allocator,
    fn init(a: std.mem.Allocator, name: []const u8) Module {
        return .{ .name = name, .a = a, .files = std.ArrayList(File).init(a) };
    }
};

module: *Module,
imports: std.ArrayList(*Module),
