const std = @import("std");

const Compiler = struct {};
const CompilerBuilder = struct {};
const Module = struct {};
const Message = struct {
    const Reporter = enum { lexer, parser, checker, builder, gen };
    const Severity = enum { err, info, warn };
    message: []const u8,
    severity: Severity,
    reporter: Reporter,
};
const FileSet = struct {
    allocator: std.mem.Allocator,
    base: u32 = 1,
    files: std.ArrayList(*File) = .empty,
    mu: std.Thread.Mutex,
    pub fn init(allocator: std.mem.Allocator) FileSet {
        return .{ .allocator = allocator };
    }
    pub fn add_file(s: *FileSet, filename: []const u8, base_: i32, size: u32) *File {
        s.mu.lock();
        defer s.mu.unlock();
        var base = if (base_ < 0) s.base else base_;
        if (base < s.base) @panic("invalid base");
        const file_ = s.allocator.create(File);
        file_.* = File{ .name = filename, .base = base, .size = size };
        if (size < 0) @panic("Invalid size, must be >= 0");
        base += size + 1;
        if (base < 1) @panic("token.Pos offset overflow (> 2G of source code in file set)");
        s.base = base;
        s.files.append(s.allocator, file_) catch {};
        return file_;
    }
    fn search_file(s: FileSet, x: u32) i32 {
        var min = 0;
        var max = s.files.items.len;
        while (min < max) {
            const mid = (min + max) / 2;
            if (s.files.items[mid].base <= x) min = mid + 1 else max = mid;
        }
        return min - 1;
    }
    pub fn file(s: FileSet, pos: Pos) *File {
        s.mu.lock();
        defer s.mu.unlock();
        const i = s.search_file(pos);
        if (i >= 0) {
            const file_ = s.files.items[i];
            if (pos <= file_.base + file_.size) return file_;
        }
        @panic("Unable to find file at given position");
    }
};
const File = struct {
    name: []const u8,
    base: u32,
    size: u32,
    line_offsets: std.ArrayList(u32) = .empty,
    pub fn line_count(s: File) u32 {
        return s.line_offsets.items.len;
    }
    pub fn line_start(s: File, line_: u32) u32 {
        if (line_ > s.line_offsets.items.len) @panic("Invalid line");
        return s.line_offsets.items[line_ - 1];
    }
    fn find_line(s: File, pos_: Pos) u32 {
        var min = 0;
        const max = s.line_offsets.items.len;
        while (min < max) {
            const mid = (min + max) / 2;
            if (s.line_offsets.items[mid] <= pos_) min = mid + 1 else max = mid;
        }
        return min;
    }
    pub fn line(s: File, pos_: Pos) u32 {
        return s.find_line(pos_);
    }
    pub fn pos(s: File, offset: u32) Pos {
        if (offset > s.size) @panic("Invalid offset");
        return s.base + offset;
    }
    pub fn position(s: File, pos_: Pos) Position {
        const offset = pos_ - s.base;
        const line_col = s.find_line_and_column(offset);
        return .{ .filename = s.name, .offset = offset, .line = line_col.line, .col = line_col.col };
    }
    fn find_line_and_column(s: File, pos_: u32) struct { line: u32, col: u32 } {
        const line_ = s.find_line(pos_);
        return .{ .line = line_, .col = pos_ - s.line_offsets.items[line_ - 1] + 1 };
    }
    pub fn add_line(s: *File, allocator: std.mem.Allocator, offset: u32) void {
        s.line_offsets.append(allocator, offset) catch {};
    }
};
const Lexer = struct {
    allocator: std.mem.Allocator,
    file: *File = undefined,
    src: []const u8 = undefined,
    idx: Pos = 0,
    placeholder: u32 = 0,
    pub fn init(allocator: std.mem.Allocator) Lexer {
        return .{ .allocator = allocator };
    }
    pub fn set(s: *Lexer, file: *File, src: []const u8) void {
        s.idx = 0;
        s.placeholder = 0;
        s.file = file;
        s.src = src;
    }
    fn advance(s: *Lexer, n: Pos) void {
        s.idx += n;
    }
    fn peek(s: *Lexer, n: usize) ?u8 {
        if (s.idx + n >= s.src.len) return null;
        return s.src[s.idx + n];
    }
    fn skipSpaces(s: *Lexer) void {
        while (s.idx < s.src.len) {
            switch (s.src[s.idx]) {
                '\n' => {
                    s.idx += 1;
                    s.file.add_line(s.allocator, s.idx);
                },
                ' ', '\t', '\r' => s.idx += 1,
                else => break,
            }
        }
    }
    fn is_alpha(c: u8) bool {
        return switch (c) {
            'a'...'z', 'A'...'Z', '_' => true,
            else => false,
        };
    }
    fn is_dec(c: u8) bool {
        return switch (c) {
            '0'...'9' => true,
            else => false,
        };
    }
    fn keyword_or_ident(s: *Lexer, start: u32, end: u32) Token {
        const word = s.src[start..end];
        const word_tok = switch (word.len) {
            1 => blk: {
                if (std.mem.eql(u8, word, "_")) break :blk TokenKind.underscore;
                break :blk null;
            },
            2 => blk: {
                if (std.mem.eql(u8, word, "if")) break :blk TokenKind.@"if";
                break :blk null;
            },
            3 => blk: {
                if (std.mem.eql(u8, word, "for")) break :blk TokenKind.@"for";
                if (std.mem.eql(u8, word, "mut")) break :blk TokenKind.mut;
                if (std.mem.eql(u8, word, "pub")) break :blk TokenKind.@"pub";
                if (std.mem.eql(u8, word, "try")) break :blk TokenKind.@"try";
                if (std.mem.eql(u8, word, "use")) break :blk TokenKind.use;
                break :blk null;
            },
            4 => blk: {
                if (std.mem.eql(u8, word, "comp")) break :blk TokenKind.comp;
                if (std.mem.eql(u8, word, "else")) break :blk TokenKind.@"else";
                if (std.mem.eql(u8, word, "enum")) break :blk TokenKind.@"enum";
                if (std.mem.eql(u8, word, "null")) break :blk TokenKind.null;
                if (std.mem.eql(u8, word, "true")) break :blk TokenKind.true;
                if (std.mem.eql(u8, word, "type")) break :blk TokenKind.type;
                if (std.mem.eql(u8, word, "void")) break :blk TokenKind.void;
                break :blk null;
            },
            5 => blk: {
                if (std.mem.eql(u8, word, "break")) break :blk TokenKind.@"break";
                if (std.mem.eql(u8, word, "catch")) break :blk TokenKind.@"catch";
                if (std.mem.eql(u8, word, "defer")) break :blk TokenKind.@"defer";
                if (std.mem.eql(u8, word, "error")) break :blk TokenKind.@"error";
                if (std.mem.eql(u8, word, "false")) break :blk TokenKind.false;
                if (std.mem.eql(u8, word, "match")) break :blk TokenKind.match;
                break :blk null;
            },
            6 => blk: {
                if (std.mem.eql(u8, word, "inline")) break :blk TokenKind.@"inline";
                if (std.mem.eql(u8, word, "packed")) break :blk TokenKind.@"packed";
                if (std.mem.eql(u8, word, "return")) break :blk TokenKind.@"return";
                if (std.mem.eql(u8, word, "struct")) break :blk TokenKind.@"struct";
                break :blk null;
            },
            8 => blk: {
                if (std.mem.eql(u8, word, "comptime")) break :blk TokenKind.comp;
                if (std.mem.eql(u8, word, "continue")) break :blk TokenKind.@"continue";
                break :blk null;
            },
            else => null,
        };
        if (word_tok) |wt| {
            return s.tok(wt, null, start, end);
        } else {
            return s.tok(.identifier, word, start, end);
        }
    }
    fn read_ident(s: *Lexer) Token {
        const start = s.idx;
        s.advance(1);
        while (s.idx < s.src.len) : (s.idx += 1) {
            const c = s.src[s.idx];
            if (!is_alpha(c) and !is_dec(c)) break;
        }
        return s.keyword_or_ident(start, s.idx);
    }
    fn read_num_float_range(s: *Lexer) Token {
        const start = s.idx;
        while (s.idx < s.src.len and is_dec(s.source.content[s.idx])) s.advance(1);
        if (s.idx < s.src.len and s.source.content[s.idx] == '.') {
            if (s.peek(1)) |i| {
                if (i == '.') {
                    const end = s.idx;
                    return s.tok(.int, s.src[start..end], start, end);
                }
            }
            s.advance(1);
            while (s.idx < s.src.len and is_dec(s.source.content[s.idx])) s.advance(1);
            return s.tok(.float, s.src[start..s.idx], start, s.idx);
        }
        return s.tok(.int, s.src[start..s.idx], start, s.idx);
    }
    fn read_string(s: *Lexer) Token {
        const start = s.idx;
        s.advance(1);
        while (s.idx < s.src.len) : (s.advance(1)) {
            const c = s.src[s.idx];
            if (c == '\"') {
                const end = s.idx;
                s.advance(1);
                return s.tok(.string, s.src[start + 1 .. end], start, end);
            }
            if (c == '\\') {
                if (s.idx + 1 < s.src.len) s.idx += 1;
            }
            if (c == '\n') {
                s.advance(1);
                s.file.add_line(s.allocator, s.idx);
            }
        }
        s.diag.emit(.{ .file_id = s.source.id, .span = Span.from(start, s.idx) }, .err, "Unclosed string literal", .{});
        s.errored = true;
        return s.tok(.invalid, null, start, s.idx);
    }
    fn read_char(s: *Lexer) Token {
        const start = s.idx;
        s.advance(1);
        if (s.idx >= s.src.len) {
            s.diag.emit(.{ .file_id = s.source.id, .span = Span.from(start, s.idx) }, .err, "Unclosed characer literal", .{});
            s.errored = true;
            return s.tok(.invalid, null, start, s.idx);
        }
        if (s.src[s.idx] == '\\') {
            s.advance(1);
            if (s.idx >= s.src.len) {
                s.diag.emit(.{ .file_id = s.source.id, .span = Span.from(start, s.idx) }, .err, "Unclosed characer literal", .{});
                s.errored = true;
                return s.tok(.invalid, null, start, s.idx);
            }
            const esc = s.src[s.idx];
            switch (esc) {
                '\'', '\"', '?', '\\', 'a', 'b', 'f', 'n', 'r', 't', 'v' => {},
                else => {
                    s.diag.emit(.{ .file_id = s.source.id, .span = Span.from(start, s.idx) }, .err, "Invalid character escape {c}", .{esc});
                    s.errored = true;
                    return s.tok(.invalid, null, start, s.idx);
                },
            }
            s.advance(1);
        } else s.advance(1);
        if (s.idx >= s.src.len or s.source.content[s.idx] != '\'') {
            s.diag.emit(.{ .file_id = s.source.id, .span = Span.from(start, s.idx) }, .err, "Unclosed characer literal", .{});
            s.errored = true;
            return s.tok(.invalid, null, start, s.idx);
        }
        const end = s.idx;
        s.advance(1);
        return s.tok(.char, s.src[start..end], start, end);
    }
    fn skip_line_comment(s: *Lexer) void {
        // while (s.idx < s.src.len and s.source.content[s.idx] != '\n') s.advance(1);
        while (s.idx < s.src.len) {
            if (s.src[s.idx] == '\n') {
                s.advance(1);
                s.file.add_line(s.allocator, s.idx);
                break;
            }
            s.advance(1);
        }
    }
    fn skip_block_comment(s: *Lexer) void {
        while (s.idx < s.src.len) {
            if (s.src[s.idx] == '*' and s.idx + 1 < s.source.content.len and s.source.content[s.idx + 1] == '/') {
                s.advance(2);
                return;
            }
            if (s.src[s.idx] == '\n') {
                s.advance(1);
                s.file.add_line(s.allocator, s.idx);
            } else s.advance(1);
        }
        s.diag.emit(.{ .file_id = s.source.id, .span = Span.from(s.idx, s.idx) }, .err, "Unclosed comment", .{});
        s.errored = true;
        return;
    }
    fn read_compound_op(s: *Lexer, single: TokenType, pairs: []const struct { ch: u8, tok: TokenType }) Token {
        const start = s.idx;
        s.advance(1);
        if (s.idx < s.src.len) {
            const c1 = s.peek(0);
            for (pairs) |p| {
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
        if (s.idx >= s.src.len) return s.tok(.eof, null, s.idx, s.idx);
        s.skipSpaces();
        if (s.idx >= s.src.len) return s.tok(.eof, null, s.idx, s.idx);
        const c = s.src[s.idx];
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
                if (s.peek(0)) |p| {
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
            '>' => return s.read_compound_op(.gt, &.{.{ .ch = '=', .tok = .gteq }}),
            '<' => return s.read_compound_op(.lt, &.{.{ .ch = '=', .tok = .lteq }}),
            '!' => return s.read_compound_op(.bang, &.{.{ .ch = '=', .tok = .bangeq }}),
            '=' => return s.read_compound_op(.eq, &.{ .{ .ch = '=', .tok = .eqeq }, .{ .ch = '>', .tok = .arrow } }),
            '|' => return s.read_compound_op(.@"or", &.{ .{ .ch = '=', .tok = .oreq }, .{ .ch = '|', .tok = .oror } }),
            '&' => return s.read_compound_op(.@"and", &.{ .{ .ch = '=', .tok = .andeq }, .{ .ch = '&', .tok = .andand } }),
            else => return s.tok(.invalid, null, s.idx, s.idx),
        }
    }
};
const Parser = struct {
    lexer: *Lexer = &Lexer.init(),
    line: u32 = 0,
    tok: Token = undefined,
    next_tok: Token = undefined,
    peek_tok: Token = undefined,
    file: *File = undefined,
    pos: Pos = 0,
    pub fn init() Parser {
        return .{};
    }
    pub fn set(s: *Parser, filename: []const u8, src: []const u8, file_set: *FileSet) void {
        s.file = file_set.add_file(filename, -1, src.len);
        s.lexer.set(s.file, src);
    }
    pub fn parse_files(s: *Parser) void {}
    pub fn parse_file(s: *Parser) void {}
};
const Pos = u32;
const Position = struct {
    filename: []const u8,
    offset: u32,
    line: u32,
    column: u32,
};
const Preferences = struct {};
const Token = struct {
    kind: TokenKind,
    val: ?[]const u8,
    pos: Pos,
    len: u32,
};
const TokenKind = enum {
    eof,
    invalid,
    // literals
    identifier,
    int,
    float,
    string,
    char,
    // operators
    add, // +
    sub, // -
    mul, // *
    div, // /
    mod, // %
    @"and", // &
    @"or", // |
    xor, // ^
    flip, // ~
    eq, // =
    addeq, // +=
    addadd, // ++
    subeq, // -=
    subsub, // --
    muleq, // *=
    diveq, // /=
    modeq, // %=
    andeq, // &=
    oreq, // |=
    xoreq, // ^=
    flipeq, // ~=
    andand, // &&
    oror, // ||
    eqeq, // ==
    gt, // >
    lt, // <
    gteq, // >=
    lteq, // <=
    lparen, // (
    rparen, // )
    lbrack, // [
    rbrack, // ]
    lbrace, // {
    rbrace, // }
    dot, // .
    dotdot, // ..
    colon, // :
    semicolon, // ;
    underscore, // _
    comma, // ,
    arrow, // =>
    bang, // !
    bangeq, // !=
    question, // ?
    dollar, // $
    walrus, // :=
    nullish, // ??
    // keywords
    pointer_deref,
    optional_deref,
    use,
    mut,
    true,
    false,
    @"if",
    @"else",
    match,
    @"defer",
    @"for",
    @"enum",
    @"error",
    @"try",
    @"catch",
    @"struct",
    @"packed",
    type,
    comp,
    @"pub",
    null,
    undefined,
    @"return",
    @"break",
    @"inline",
    @"continue",
    void,
};
// ast
const Expr = union(enum) {
    basic_literal: struct {},
    call: struct {},
    comp: struct {},
    func: struct {},
    ident: struct {},
    if_: struct {},
    index: struct {},
    infix: struct {},
    init: struct {},
    match: struct {},
    paren: struct {},
    postfix: struct {},
    prefix: struct {},
    range: struct {},
    select: struct {},
    selector: struct {},
    string: struct {},
    type: Type,
};
const Stmt = union(enum) {
    assign: struct {},
    block: struct {},
    comp: struct {},
    defer_: struct {},
    for_: struct {},
    label: struct {},
    return_: struct {},
    expr_: struct {},
};
const Type = union(enum) {
    array: struct {},
    func: struct {},
    null,
    type,
    option: struct {},
    pointer: struct {},
    struct_decl: struct {},
    enum_decl: struct {},
    error_decl: struct {},
};
pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    // const allocator = arena.allocator();
}
