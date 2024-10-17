const std = @import("std");
const Parser = @import("parser.zig").Parser;
const ast = @import("ast.zig");

pub fn main() !void {
    const page_allocator = std.heap.page_allocator;
    var arena = std.heap.ArenaAllocator.init(page_allocator);
    const alloc = arena.allocator();
    defer arena.deinit();

    const x = try read_file(alloc, "syntax.dyn");

    var p = Parser.init(alloc, x);
    const t = p.parse();
    std.debug.print("{!}\n", .{t});
}

pub fn read_file(a: std.mem.Allocator, filename: []const u8) ![]const u8 {
    const file = try std.fs.cwd().openFile(filename, .{ .mode = .read_only });
    defer file.close();
    const stat = try file.stat();
    return try file.readToEndAlloc(a, stat.size);
}
