const std = @import("std");
const File = @import("file.zig");

const Checker = @This();

const Module = struct {
    name: []const u8,
    files: std.ArrayList(),
    a: std.mem.Allocator,
    fn init(a: std.mem.Allocator, name: []const u8) Module {
        return .{ .name = name, .a = a, .files = std.ArrayList(File).init(a) };
    }
};

const Import = union(enum) { file: File, module: Module };

imports: std.ArrayList(Import),
module: *Module,
