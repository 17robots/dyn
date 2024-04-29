const std = @import("std");
const lexer = @import("lexer.zig");
const Token = @import("token.zig").Token;
const CompilerError = @import("errors.zig").CompilerError;

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

    var l = lexer.Lexer.init(buf);
    l.next();
    while (l.tok.type != .Eof) {
        if (l.err != null) {
            const err = switch (l.err.?) {
                CompilerError.InvalidEscape => "invalid escape",
                CompilerError.NewlineInSingleLineString => "newline in string",
                CompilerError.UnterminatedString => "unterminated string",
                CompilerError.UnterminatedChar => "unterminated char",
                CompilerError.CharLiteralMoreThanOne => "char literal more than 1 char",
                CompilerError.UndefinedSymbol => "undefined symbol",
            };
            std.debug.print("error: {s} at {d}:{d}", .{ err, l.l, l.c });
            break;
        }
        std.debug.print("token: {s} {s}\n", .{ @tagName(l.tok.type), l.tok.lit });
        l.next();
    }
}
