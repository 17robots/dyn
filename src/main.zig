const std = @import("std");
const Parser = @import("parser.zig").Parser;

pub fn main() !void {
    const page_allocator = std.heap.page_allocator;
    var arena = std.heap.ArenaAllocator.init(page_allocator);
    const alloc = arena.allocator();
    defer arena.deinit();

    const file_body = try read_file(alloc, "src/main.dyn");

    var parser = Parser.init(alloc, file_body);
    const p = try parser.parse_program();
    defer p.deinit(parser.allocator);
    p.print();
}

pub fn read_file(a: std.mem.Allocator, filename: []const u8) ![]const u8 {
    const file = try std.fs.cwd().openFile(filename, .{ .mode = .read_only });
    defer file.close();
    const stat = try file.stat();
    return try file.readToEndAlloc(a, stat.size);
}
