const std = @import("std");
const FileId = @import("source.zig").FileId;
const Token = @import("token.zig").Token;

pub const LexerResult = struct { tokens: []Token };

pub const Lexer = struct {
    allocator: std.mem.Allocator,
    file: FileId,
    input: []const u8,
    i: usize = 0,
    tokens: std.ArrayList(Token) = .empty,
    diagnostics: i32, // fix
};

