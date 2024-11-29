const std = @import("std");
const Parser = @import("parser.zig");
const Lexer = @import("lexer.zig");

pub fn main() !void {
    const page_allocator = std.heap.page_allocator;
    var arena = std.heap.ArenaAllocator.init(page_allocator);
    const alloc = arena.allocator();
    defer arena.deinit();

    const file_body = try read_file(alloc, "syntax.dyn");

    var l = Lexer.init(file_body);
    l.next_tok();
    std.debug.print("Current Tok: {any} {s}", .{ l.tok, l.literal orelse "" });
    l.index = 0;
    l.next_tok();
    std.debug.print("Current Tok: {any} {s}", .{ l.tok, l.literal orelse "" });
    // var parser = Parser.init(alloc, file_body);
    // const p = try parser.program();
    // defer p.deinit(parser.allocator);
    // p.print();
}

pub fn read_file(a: std.mem.Allocator, filename: []const u8) ![]const u8 {
    const file = try std.fs.cwd().openFile(filename, .{ .mode = .read_only });
    defer file.close();
    const stat = try file.stat();
    return try file.readToEndAlloc(a, stat.size);
}
