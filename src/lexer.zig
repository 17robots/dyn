const std = @import("std");
const FileId = @import("source.zig").FileId;
const SourceLocation = @import("source.zig").SourceLocation;
const Source = @import("source.zig").Source;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const TokenType = @import("token.zig").TokenType;
const Token = @import("token.zig").Token;

const Lexer = @This();
diag: *DiagnosticEmitter,
source: *Source,
idx: usize = 0,
errored: bool = false,

pub fn init(source: *Source, diag: *DiagnosticEmitter) Lexer {
    return Lexer{ .source = source, .diag = diag };
}
fn advance(s: *Lexer, n: usize) void {
    s.idx += n;
}
fn peek(s: *Lexer, n: usize) ?u8 {
    if (s.idx + n > s.source.content.len) return null;
    return s.source.content[s.idx + n];
}
fn skipSpaces(s: *Lexer) void {
    while (s.idx < s.source.content.len) {
        switch (s.source.content[s.idx]) {
            ' ', '\t', '\n', '\r' => s.idx += 1,
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
    const word = s.source.content[s.placeholder..s.idx];
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
    const start = s.idx;
    s.advance(1);
    while (s.idx < s.source.content.len) : (s.idx += 1) {
        const c = s.source.content[s.idx];
        if (!is_alpha(c) and !is_dec(c)) break;
    }
    return s.keyword_or_ident(start, s.idx);
}
fn read_num_float_range(s: *Lexer) Token {
    const start = s.idx;
    while (s.idx < s.source.content.len and is_dec(s.source.content[s.idx])) s.advance(1);
    if (s.idx < s.source.content.len and s.source.content[s.idx] == '.') {
        if (s.peek(1)) |i| {
            if (i == '.') {
                const end = s.idx - 1;
                return s.tok(.int, s.source.content[start..end], start, end);
            }
        }
        s.advance(1);
        while (s.idx < s.source.content.len and is_dec(s.source.content[s.idx])) s.advance(1);
        return s.tok(.float, s.source.content[start..s.idx], start, s.idx);
    }
    return s.tok(.int, s.source.content[start..s.idx], start, s.idx);
}
fn read_string(s: *Lexer) Token {
    const start = s.idx;
    s.advance(1);
    while (s.idx < s.source.content.len) : (s.advance(1)) {
        const c = s.source.content[s.idx];
        if (c == '\"') {
            const end = s.idx;
            s.advance(1);
            return s.tok(.string, s.source.content[start..end], start, end);
        }
        if (c == '\\') {
            if (s.idx + 1 < s.source.content.len) s.idx += 1;
        }
    }
    s.diag.emit(s.source.id, @intCast(s.idx - 1), .err, "Unclosed string literal", .{});
}
fn read_char(s: *Lexer) Token {
    const start = s.idx;
    s.advance(1);
    if (s.indexs >= s.source.content.len) {
        s.diag.emit(s.source.id, @intCast(s.idx), .err, "Unclosed characer literal", .{});
        s.errored = true;
        return s.tok(.invalid, null, start, s.idx);
    }
    if (s.source.content[s.idx] == '\\') {
        s.advance(1);
        if (s.idx >= s.source.content.len) {
            s.diag.emit(s.source.id, @intCast(s.idx), .err, "Unclosed characer literal", .{});
            s.errored = true;
            return s.tok(.invalid, null, start, s.idx);
        }
        const esc = s.source.content[s.idx];
        switch (esc) {
            '\'', '\"', '?', '\\', 'a', 'b', 'f', 'n', 'r', 't', 'v' => {},
            else => {
                s.diag.emit(s.source.id, @intCast(s.idx), .err, "Invalid character escape {s}", .{esc});
                s.errored = true;
                return s.tok(.invalid, null, start, s.idx);
            },
        }
        s.advance(1);
    } else s.advance(1);
    if (s.idx >= s.source.content.len or s.source.content[s.idx] != '\'') {
        s.diag.emit(s.source.id, @intCast(s.idx), .err, "Unclosed characer literal", .{});
        s.errored = true;
        return s.tok(.invalid, null, start, s.idx);
    }
    const end = s.idx;
    s.advance(1);
    return s.tok(.char, s.source.content[start..end], start, end);
}
fn skip_line_comment(s: *Lexer) void {
    while (s.idx < s.source.content.len and s.source.content[s.idx] != '\n') s.advance(1);
}
fn skip_block_comment(s: *Lexer) void {
    while (s.idx < s.source.content.len) {
        if (s.source.content[s.idx] == '*' and s.idx + 1 < s.source.content.len and s.source.content[s.idx + 1] == '/') {
            s.advance(2);
            return;
        }
        s.advance(1);
    }
    s.diag.emit(s.source.id, @intCast(s.idx), .err, "Unclosed comment", .{});
    s.errored = true;
    return;
}
fn read_compound_op(s: *Lexer, single: TokenType, pairs: []const struct { ch: u8, tok: TokenType }) Token {
    const start = s.idx;
    s.advance(1);
    if (s.idx < s.source.content.len) {
        const c1 = s.peek(0);
        inline for (pairs) |p| {
            if (c1) |c| {
                if (c == p.ch) {
                    s.advance(1);
                    return s.tok(p.tok, null, start, s.idx);
                }
            }
        }
    }
    return s.tok(single, null, start, s.idx);
}
pub fn next(s: *Lexer) Token {
    if (s.errored) return s.tok(.invalid, null, s.idx, s.idx);
    if(s.idx >= s.source.content.len) return s.tok(.eof, null, s.idx, s.idx);
    s.skipSpaces();
    if(s.idx >= s.source.content.len) return s.tok(.eof, null, s.idx, s.idx);
    const c = s.source.content[s.idx];
    switch (c) {
        '(' => {
            s.advance(1);
            return s.tok(.lparen, null, s.idx - 1, s.idx - 1);
        },
        ')' => {
            s.advance(1);
            return s.tok(.rparen, null, s.idx - 1, s.idx - 1);
        },
        '[' => {
            s.advance(1);
            return s.tok(.lbrack, null, s.idx - 1, s.idx - 1);
        },
        ']' => {
            s.advance(1);
            return s.tok(.rbrack, null, s.idx - 1, s.idx - 1);
        },
        '{' => {
            s.advance(1);
            return s.tok(.lbrace, null, s.idx - 1, s.idx - 1);
        },
        '}' => {
            s.advance(1);
            return s.tok(.rbrace, null, s.idx - 1, s.idx - 1);
        },
        ';' => {
            s.advance(1);
            return s.tok(.semicolon, null, s.idx - 1, s.idx - 1);
        },
        ',' => {
            s.advance(1);
            return s.tok(.comma, null, s.idx - 1, s.idx - 1);
        },
        '_' => {
            s.advance(1);
            return s.tok(.underscore, null, s.idx - 1, s.idx - 1);
        },
        '$', '_', 'a'...'z', 'A'...'Z' => return s.read_ident(),
        '0'...'9' => return s.read_num_float_range(),
        '.' => {
            const start = s.idx;
            s.advance(1);
            if (s.peek(0)) |p| {
                if (p == '.') {
                    s.advance(1);
                    return s.tok(.dotdot, null, start, s.idx);
                }
                if (p == '?') {
                    s.advance(1);
                    return s.tok(.optional_deref, null, start, s.idx);
                }
                if (p == '*') {
                    s.advance(1);
                    return s.tok(.pointer_deref, null, start, s.idx);
                }
            }
            return s.tok(.dot, null, start, s.idx);
        },
        '/' => {
            const start = s.idx;
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
                    return s.tok(.diveq, null, start, s.idx);
                }
            }
            s.advance(1);
            return s.tok(.div, null, start, s.idx - 1);
        },
        ':' => {
            const start = s.idx;
            s.advance(1);
            if (s.peek(1)) |p| {
                if (p == '=') {
                    s.advance(1);
                    return s.tok(.walrus, null, start, s.idx);
                }
            }
            return s.tok(.colon, null, start, s.idx);
        },
        '\"' => return s.read_string(),
        '\'' => return s.read_char(),
        '?' => return s.read_compound_op(.question, &.{.{ .ch = '?', .tok = .nullish }}),
        '+' => return s.read_compound_op(.add, &.{ .{ .ch = '+', .tok = .addadd }, .{ .ch = '=', .tok = .addeq } }),
        '-' => return s.read_compound_op(.sub, &.{ .{ .ch = '-', .tok = .subsub }, .{ .ch = '=', .tok = .subeq } }),
        '*' => return s.read_compound_op(.mul, &.{.{ .ch = '=', .tok = .muleq }}),
        '%' => return s.read_compound_op(.mod, &.{.{ .ch = '=', .tok = .modeq }}),
        '^' => return s.read_compound_op(.xor, &.{.{ .ch = '=', .tok = .xoreq }}),
        '~' => return s.read_compound_op(.flip, &.{.{ .ch = '=', .tok = .flipeq }}),
        '>' => return s.read_compound_op(.gt, &.{.{ .ch = '=', .tok = .gte }}),
        '<' => return s.read_compound_op(.lt, &.{.{ .ch = '=', .tok = .lte }}),
        '!' => return s.read_compound_op(.bang, &.{.{ .ch = '=', .tok = .bangeq }}),
    }
}
fn tok(s: Lexer, t: TokenType, val: ?[]const u8, start: usize, end: usize) Token {
    return Token.init(t, s.source.id, val, @intCast(start), @intCast(end));
}
