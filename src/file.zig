const std = @import("std");

const Diagnostic = @import("diagnostic.zig");
const Node = @import("ast.zig").Node;
const Parser = @import("parser.zig");

const File = @This();

name: []const u8,
content: []const u8,
diagnostics: std.ArrayList(Diagnostic),
root: ?Node = null,

pub fn init(allocator: std.mem.Allocator, dir: std.fs.Dir, name: []const u8) !File {
    return File{ .name = name, .content = try read_file(allocator, name, dir), .diagnostics = std.ArrayList(Diagnostic).init(allocator) };
}
pub fn parse(s: *File, alloc: std.mem.Allocator) void {
    var parser = Parser.init(alloc, s);
    s.root = switch (parser.program()) {
        .node => |n| n,
        else => null,
    };
}
fn read_file(a: std.mem.Allocator, filename: []const u8, dir: std.fs.Dir) ![]const u8 {
    const file = try dir.openFile(filename, .{ .mode = .read_only });
    defer file.close();
    return try file.readToEndAlloc(a, (try file.stat()).size);
}
