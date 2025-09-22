const std = @import("std");
const FileId = @import("source.zig").FileId;
const SourceLocation = @import("source.zig").SourceLocation;
const Source = @import("source.zig").Source;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const TokenType = @import("token2.zig").TokenType;
const Token = @import("token2.zig").Token;

const Lexer = @This();
diag: *DiagnosticEmitter,
source: *Source,
index: usize = 0,
errored: bool = false,

pub fn init(source: *Source, diag: *DiagnosticEmitter) Lexer {
    return Lexer{ .source = source, .diag = diag };
}

fn advance(s: *Lexer, n: usize) void {
    s.index += n;
}
fn peek(s: *Lexer, n: usize) ?u8 {
    if (s.index + n > s.source.content.len) return null;
    return s.source.content[s.index + n];
}
fn skipSpaces(s: *Lexer) void {
    while (s.index < s.source.content.len) {
        switch (s.source.content[s.index]) {
            ' ', '\t', '\n', '\r' => s.index += 1,
            else => break,
        }
    }
}
fn is_alpha(c: u8) bool {
    return switch (c) {
        'a'...'z', 'A'...'Z', '$', '_' => true,
        else => false,
    };
}
fn is_dec(c: u8) bool {
    return switch (c) {
        '0'...'9' => true,
        else => false,
    };
}
fn keyword_or_ident(s: *Lexer, start: usize, end: usize) TokenType {
    const word = s.source.content[s.placeholder..s.index];
    switch (word.len) {
        2 => {
            if (std.mem.eql(u8, word, "fn")) return TokenType.@"fn";
            if (std.mem.eql(u8, word, "if")) return TokenType.@"if";
            return null;
        },
        3 => {
            if (std.mem.eql(u8, word, "for")) return TokenType.@"for";
            if (std.mem.eql(u8, word, "mod")) return TokenType.module;
            if (std.mem.eql(u8, word, "mut")) return TokenType.mut;
            if (std.mem.eql(u8, word, "pub")) return TokenType.@"pub";
            if (std.mem.eql(u8, word, "try")) return TokenType.@"try";
            if (std.mem.eql(u8, word, "use")) return TokenType.use;
            return null;
        },
        4 => {
            if (std.mem.eql(u8, word, "comp")) return TokenType.comp;
            if (std.mem.eql(u8, word, "else")) return TokenType.@"else";
            if (std.mem.eql(u8, word, "enum")) return TokenType.@"enum";
            if (std.mem.eql(u8, word, "null")) return TokenType.null;
            if (std.mem.eql(u8, word, "true")) return TokenType.true;
            if (std.mem.eql(u8, word, "type")) return TokenType.type;
            return null;
        },
        5 => {
            if (std.mem.eql(u8, word, "break")) return TokenType.@"break";
            if (std.mem.eql(u8, word, "catch")) return TokenType.@"catch";
            if (std.mem.eql(u8, word, "defer")) return TokenType.@"defer";
            if (std.mem.eql(u8, word, "error")) return TokenType.@"error";
            if (std.mem.eql(u8, word, "false")) return TokenType.false;
            if (std.mem.eql(u8, word, "match")) return TokenType.match;
            if (std.mem.eql(u8, word, "while")) return TokenType.@"while";
            return null;
        },
        6 => {
            if (std.mem.eql(u8, word, "inline")) return TokenType.@"inline";
            if (std.mem.eql(u8, word, "module")) return TokenType.module;
            if (std.mem.eql(u8, word, "packed")) return TokenType.@"packed";
            if (std.mem.eql(u8, word, "struct")) return TokenType.@"struct";
            if (std.mem.eql(u8, word, "return")) return TokenType.@"return";
            return null;
        },
        8 => {
            if (std.mem.eql(u8, word, "continue")) return TokenType.@"continue";
            return null;
        },
        9 => {
            if (std.mem.eql(u8, word, "undefined")) return TokenType.undefined;
            return null;
        },
        else => return null,
    }
    return TokenType{ .identifier = s.source.content[start..end] };
}
fn read_ident(s: *Lexer) Token {
    const start = s.index;
    s.advance(1);
    while (s.index < s.source.content.len) : (s.index += 1) {
        const c = s.source.content[s.index];
        if (!is_alpha(c) and !is_dec(c)) break;
    }
    return s.keyword_or_ident(start, s.index);
}
fn read_num_float_range(s: *Lexer) Token {
    const start = s.index;
    while (s.index < s.source.content.len and is_dec(s.source.content[s.index])) s.advance(1);
    if (s.index < s.source.content.len and s.source.content[s.index] == '.') {
        if (s.peek(1)) |i| {
            if (i == '.') {
                const end_int = s.index - 1;
                return Token.init(.{ .int = s.source.content[start..end_int] }, null, @intCast(s.index), @intCast(start), @intCast(end_int));
            }
        }
        s.advance(1);
        var saw_digit = false;
        while (s.index < s.source.content.len and is_dec(s.source.content[s.index])) : (s.advance(1)) saw_digit = true;
        if (!saw_digit) return Token.init(.{ .float = s.source.content[start..s.index] }, null, @intCast(s.index), @intCast(start), @intCast(s.index));
        return Token.init(.{ .float = s.source.content[start..s.index] }, null, @intCast(s.index), @intCast(start), @intCast(s.index));
    }
    return Token.init(.{ .int = s.source.content[start..s.index] }, null, @intCast(s.index), @intCast(start), @intCast(s.index));
}
fn read_string(s: *Lexer) Token {
    const start = s.index;
    s.advance(1);
    while (s.index < s.source.content.len) : (s.advance(1)) {
        const c = s.source.content[s.index];
        if (c == '\"') {
            const end = s.index;
            s.advance(1);
            return Token.init(.{ .string = s.source.content[start..end] }, null, @intCast(s.index), @intCast(start), @intCast(end));
        }
        if (c == '\\') {
            if (s.index + 1 < s.source.content.len) s.index += 1;
        }
    }
    s.diag.emit(s.source.id, @intCast(s.index - 1), .err, "Unclosed string literal", .{});
}
fn read_char(s: *Lexer) Token {
    const start = s.index;
    s.advance(1);
    if (s.indexs >= s.source.content.len) {
        s.diag.emit(s.source.id, @intCast(s.index), .err, "Unclosed characer literal", .{});
        s.errored = true;
        return Token.init(.invalid, s.source.id, @intCast(s.index), @intCast(start), @intCast(s.index));
    }

    if (s.source.content[s.index] == '\\') {
        s.advance(1);
        if (s.index >= s.source.content.len) {
            s.diag.emit(s.source.id, @intCast(s.index), .err, "Unclosed characer literal", .{});
            s.errored = true;
            return Token.init(.invalid, s.source.id, @intCast(s.index), @intCast(start), @intCast(s.index));
        }
        const esc = s.source.content[s.index];
        switch (esc) {
            '\'', '\"', '?', '\\', 'a', 'b', 'f', 'n', 'r', 't', 'v' => {},
            else => {
                s.diag.emit(s.source.id, @intCast(s.index), .err, "Invalid character escape {s}", .{esc});
                s.errored = true;
                return Token.init(.invalid, s.source.id, @intCast(s.index), @intCast(start), @intCast(s.index));
            },
        }
        s.advance(1);
    } else s.advance(1);
    if (s.index >= s.source.content.len or s.source.content[s.index] != '\'') {
        s.diag.emit(s.source.id, @intCast(s.index), .err, "Unclosed characer literal", .{});
        s.errored = true;
        return Token.init(.invalid, s.source.id, @intCast(s.index), @intCast(start), @intCast(s.index));
    }
    const end = s.index;
    s.advance(1);
    return Token.init(.{ .char = s.source.content[start..end] }, s.source.id, @intCast(s.index), @intCast(start), @intCast(s.index));
}
fn skip_line_comment(s: *Lexer) void {
    while (s.index < s.source.content.len and s.source.content[s.index] != '\n') s.advance(1);
}
fn skip_block_comment(s: *Lexer) void {
    while (s.index < s.source.content.len) {
        if (s.source.content[s.index] == '*' and s.index + 1 < s.source.content.len and s.source.content[s.index + 1] == '/') {
            s.advance(2);
            return;
        }
        s.advance(1);
    }
    s.diag.emit(s.source.id, @intCast(s.index), .err, "Unclosed comment", .{});
    s.errored = true;
    return;
}
fn read_op_2(s: *Lexer, single: TokenType, pairs: []const struct { ch: u8, tok: TokenType }) Token {
    const start = s.index;
    s.advance(1);
    if (s.index < s.source.content.len) {
        const c1 = s.peek(0);
        inline for (pairs) |p| {
            if (c1) |c| {
                if (c == p.ch) {
                    s.advance(1);
                    return Token.init(p.tok, s.source.id, @intCast(s.index - 1), @intCast(start), @intCast(s.index));
                }
            }
        }
    }
    return Token.init(single, s.source.id, @intCast(s.index - 1), @intCast(start), @intCast(s.index));
}
pub fn next(s: *Lexer) Token {
    if (s.errored) return Token.init(.invalid, s.source.id, @intCast(s.index), @intCast(s.index), @intCast(s.index));
    if (s.index >= s.source.content.len) return Token.init(.eof, s.source.id, @intCast(s.index), @intCast(s.index), @intCast(s.index));
    s.skipSpaces();
    if (s.index >= s.source.content.len) return Token.init(.eof, s.source.id, @intCast(s.index), @intCast(s.index), @intCast(s.index));
    const c = s.source.content[s.index];
    switch (c) {
        '(' => {
            s.advance(1);
            return Token.init(.lparen, s.source.id, @intCast(s.index), @intCast(s.index - 1), @intCast(s.index - 1));
        },
        ')' => {
            s.advance(1);
            return Token.init(.rparen, s.source.id, @intCast(s.index), @intCast(s.index - 1), @intCast(s.index - 1));
        },
        '[' => {
            s.advance(1);
            return Token.init(.lbrack, s.source.id, @intCast(s.index), @intCast(s.index - 1), @intCast(s.index - 1));
        },
        ']' => {
            s.advance(1);
            return Token.init(.rbrack, s.source.id, @intCast(s.index), @intCast(s.index - 1), @intCast(s.index - 1));
        },
        '{' => {
            s.advance(1);
            return Token.init(.lbrace, s.source.id, @intCast(s.index), @intCast(s.index - 1), @intCast(s.index - 1));
        },
        '}' => {
            s.advance(1);
            return Token.init(.rbrace, s.source.id, @intCast(s.index), @intCast(s.index - 1), @intCast(s.index - 1));
        },
        ';' => {
            s.advance(1);
            return Token.init(.semicolon, s.source.id, @intCast(s.index), @intCast(s.index - 1), @intCast(s.index - 1));
        },
        ',' => {
            s.advance(1);
            return Token.init(.comma, s.source.id, @intCast(s.index), @intCast(s.index - 1), @intCast(s.index - 1));
        },
        '_' => {
            s.advance(1);
            return Token.init(.underscore, s.source.id, @intCast(s.index), @intCast(s.index - 1), @intCast(s.index - 1));
        },
        '$', '_', 'a'...'z', 'A'...'Z' => return s.read_ident(),
        '0'...'9' => return s.read_num_float_range(),
        '.' => {
            const start = s.index;
            s.advance(1);
            if (s.peek(1)) |p| {
                if (p == '.') {
                    s.advance(1);
                    return Token.init(.dotdot, s.source.id, @intCast(s.index), @intCast(start), @intCast(s.index));
                }
                if (p == '?') {
                    s.advance(1);
                    return Token.init(.optional_deref, s.source.id, @intCast(s.index), @intCast(start), @intCast(s.index));
                }
                if (p == '*') {
                    s.advance(1);
                    return Token.init(.pointer_deref, s.source.id, @intCast(s.index), @intCast(start), @intCast(s.index));
                }
            }
            return Token.init(.dot, s.source.id, @intCast(s.index), @intCast(start), @intCast(s.index));
        },
        '/' => {
            const start = s.index;
            if (s.peek(1)) |p| {
                if (p == '/') {
                    s.advance(2);
                    s.skip_line_comment();
                    return s.next();
                }
                if (p == '*') {
                    s.advance(2);
                    s.skip_block_comment();
                    return s.next();
                }
                if (p == '=') {
                    s.advance(2);
                    return Token.init(.diveq, s.source.id, @intCast(s.index), @intCast(start), @intCast(s.index));
                }
            }
            s.advance(1);
            return Token.init(.div, s.source.id, @intCast(s.index), @intCast(start), @intCast(s.index));
        },
        ':' => {
            const start = s.index;
            s.advance(1);
            if (s.peek(1)) |p| {
                if (p == '=') {
                    s.advance(1);
                    return Token.init(.walrus, s.source.id, @intCast(s.index), @intCast(start), @intCast(s.index));
                }
            }
            return Token.init(.colon, s.source.id, @intCast(s.index), @intCast(start), @intCast(s.index));
        },
        '\"' => return s.read_string(),
        '\'' => return s.read_char(),
        '?' => return s.read_op_2(.question, &.{.{ .ch = '?', .tok = .nullish }}),
        '+' => return s.read_op_2(.add, &.{ .{ .ch = '+', .tok = .addadd }, .{ .ch = '=', .tok = .addeq } }),
        '-' => return s.read_op_2(.sub, &.{ .{ .ch = '-', .tok = .subsub }, .{ .ch = '=', .tok = .subeq } }),
        '*' => return s.read_op_2(.mul, &.{.{ .ch = '=', .tok = .muleq }}),
        '%' => return s.read_op_2(.mod, &.{.{ .ch = '=', .tok = .modeq }}),
        '^' => return s.read_op_2(.xor, &.{.{ .ch = '=', .tok = .xoreq }}),
        '~' => return s.read_op_2(.flip, &.{.{ .ch = '=', .tok = .flipeq }}),
        '>' => return s.read_op_2(.gt, &.{.{ .ch = '=', .tok = .gte }}),
        '<' => return s.read_op_2(.lt, &.{.{ .ch = '=', .tok = .lte }}),
        '!' => return s.read_op_2(.bang, &.{.{ .ch = '=', .tok = .bangeq }}),
    }
}
