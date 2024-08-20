const std = @import("std");
const Token = @import("token.zig").Token;
const CompilerError = @import("errors.zig").CompilerError;
const parser = @import("parser.zig");

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    const alloc = gpa.allocator();
    defer {
        _ = gpa.deinit();
    }
    const data = try std.fs.cwd().openFile("main.dyn", .{});
    defer data.close();
    const stat = try data.stat();
    const buf = try data.readToEndAlloc(alloc, stat.size);
    defer alloc.free(buf);

    var p = parser.Parser.init(alloc, buf);
    p.lexer.next();
    _ = p.program();
}
