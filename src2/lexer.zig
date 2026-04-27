const std = @import("std");

const source = @import("source.zig");
const tok = @import("token.zig");
const diag = @import("diag.zig");

pub const Result = struct {
    tokens: []tok.Token,
    pub fn deinit(self: Result, allocator: std.mem.Allocator) void {
        allocator.free(self.tokens);
    }
};
const Lexer = struct {
    allocator: std.mem.Allocator,
    file: source.FileId,
    input: []const u8,
    i: usize = 0,
    tokens: std.ArrayList(tok.Token),
    diagnostics: *diag.DiagnosticBag,

    fn init(allocator: std.mem.Allocator, file: source.FileId, input: []const u8, diagnostics: *diag.DiagnosticBag) Lexer {
        return .{ .allocator = allocator, .file = file, .input = input, .tokens = .empty, .diagnostics = diagnostics };
    }
    fn deinit(self: *Lexer) void {
        self.tokens.deinit(self.allocator);
    }

    fn run(self: *Lexer) !Result {
        while (self.i < self.input.len) {
            const c = self.input[self.i];
            switch (c) {
                ' ', '\t', '\r' => self.i += 1,
                '\n' => try self.one(.newline, 1),
                ';' => try self.one(.semicolon, 1),
                'a'...'z', 'A'...'Z', '_' => try self.identifier(),
                '0'...'9' => try self.number(),
                '"' => try self.string(),
                '\'' => try self.char(),
                '$' => try self.builtin(),
                '/' => try self.slash(),
                else => try self.punct(),
            }
        }
        try self.add(.eof, self.i, self.i);
        return .{ .tokens = try self.tokens.toOwnedSlice(self.allocator) };
    }

    fn span(self: *Lexer, start: usize, end: usize) source.Span {
        return .{ .file = self.file, .start = @intCast(start), .end = @intCast(end) };
    }
    fn add(self: *Lexer, kind: tok.TokenKind, start: usize, end: usize) !void {
        try self.tokens.append(self.allocator, .{ .kind = kind, .span = self.span(start, end) });
    }
    fn err(self: *Lexer, code: []const u8, msg: []const u8, start: usize, end: usize) !void {
        try self.diagnostics.errorAt(code, msg, self.span(start, end), msg);
    }
    fn one(self: *Lexer, kind: tok.TokenKind, n: usize) !void {
        const s = self.i;
        self.i += n;
        try self.add(kind, s, self.i);
    }
    fn starts(self: *Lexer, s: []const u8) bool {
        return std.mem.startsWith(u8, self.input[self.i..], s);
    }
    fn identifier(self: *Lexer) !void {
        const s = self.i;
        self.i += 1;
        while (self.i < self.input.len and isIdentContinue(self.input[self.i])) self.i += 1;
        const text = self.input[s..self.i];
        const kind: tok.TokenKind = tok.keywordKind(text) orelse if (std.mem.eql(u8, text, "true")) .true_literal else if (std.mem.eql(u8, text, "false")) .false_literal else if (std.mem.eql(u8, text, "null")) .null_literal else .identifier;
        try self.add(kind, s, self.i);
    }
    fn builtin(self: *Lexer) !void {
        const s = self.i;
        self.i += 1;
        if (self.i >= self.input.len or !isIdentStart(self.input[self.i])) {
            try self.add(.dollar, s, self.i);
            return;
        }
        self.i += 1;
        while (self.i < self.input.len and isIdentContinue(self.input[self.i])) self.i += 1;
        try self.add(.builtin_identifier, s, self.i);
    }
    fn number(self: *Lexer) !void {
        const s = self.i;
        var is_float = false;
        if (self.starts("0x") or self.starts("0X") or self.starts("0b") or self.starts("0B") or self.starts("0o") or self.starts("0O")) {
            const base: u8 = self.input[self.i + 1];
            self.i += 2;
            const ds = self.i;
            while (self.i < self.input.len and (digitFor(base, self.input[self.i]) or self.input[self.i] == '_')) self.i += 1;
            if (self.i == ds) try self.err("L0001", "expected digits after numeric base prefix", s, self.i);
            try self.add(.integer_literal, s, self.i);
            return;
        }
        while (self.i < self.input.len and (std.ascii.isDigit(self.input[self.i]) or self.input[self.i] == '_')) self.i += 1;
        if (self.i + 1 < self.input.len and self.input[self.i] == '.' and self.input[self.i + 1] != '.') {
            is_float = true;
            self.i += 1;
            while (self.i < self.input.len and (std.ascii.isDigit(self.input[self.i]) or self.input[self.i] == '_')) self.i += 1;
        }
        if (self.i < self.input.len and (self.input[self.i] == 'e' or self.input[self.i] == 'E')) {
            is_float = true;
            self.i += 1;
            if (self.i < self.input.len and (self.input[self.i] == '+' or self.input[self.i] == '-')) self.i += 1;
            const es = self.i;
            while (self.i < self.input.len and (std.ascii.isDigit(self.input[self.i]) or self.input[self.i] == '_')) self.i += 1;
            if (self.i == es) try self.err("L0002", "expected exponent digits", s, self.i);
        }
        try self.add(if (is_float) .float_literal else .integer_literal, s, self.i);
    }
    fn string(self: *Lexer) !void {
        const s = self.i;
        self.i += 1;
        while (self.i < self.input.len) {
            const c = self.input[self.i];
            if (c == '"') {
                self.i += 1;
                try self.add(.string_literal, s, self.i);
                return;
            }
            if (c == '\n') break;
            if (c == '\\') try self.escape() else self.i += 1;
        }
        try self.err("L0003", "unterminated string literal", s, self.i);
        try self.add(.string_literal, s, self.i);
    }
    fn char(self: *Lexer) !void {
        const s = self.i;
        self.i += 1;
        if (self.i < self.input.len and self.input[self.i] == '\\') try self.escape() else if (self.i < self.input.len and self.input[self.i] != '\n' and self.input[self.i] != '\'') self.i += 1;
        if (self.i < self.input.len and self.input[self.i] == '\'') {
            self.i += 1;
            try self.add(.char_literal, s, self.i);
        } else {
            try self.err("L0004", "unterminated char literal", s, self.i);
            try self.add(.char_literal, s, self.i);
        }
    }
    fn escape(self: *Lexer) !void {
        const s = self.i;
        self.i += 1;
        if (self.i >= self.input.len) {
            try self.err("L0005", "unterminated escape sequence", s, self.i);
            return;
        }
        switch (self.input[self.i]) {
            '\\', '"', '\'', 'n', 'r', 't', '0' => self.i += 1,
            'x' => {
                self.i += 1;
                if (self.i + 1 >= self.input.len or !std.ascii.isHex(self.input[self.i]) or !std.ascii.isHex(self.input[self.i + 1])) try self.err("L0006", "expected two hex digits after \\x", s, self.i) else self.i += 2;
            },
            'u' => {
                self.i += 1;
                if (self.i >= self.input.len or self.input[self.i] != '{') {
                    try self.err("L0007", "expected `{` after \\u", s, self.i);
                    return;
                }
                self.i += 1;
                const ds = self.i;
                while (self.i < self.input.len and std.ascii.isHex(self.input[self.i])) self.i += 1;
                if (self.i == ds) try self.err("L0008", "expected hex digits in unicode escape", s, self.i);
                if (self.i < self.input.len and self.input[self.i] == '}') self.i += 1 else try self.err("L0009", "expected `}` to close unicode escape", s, self.i);
            },
            else => {
                self.i += 1;
                try self.err("L0010", "unknown escape sequence", s, self.i);
            },
        }
    }
    fn slash(self: *Lexer) !void {
        const s = self.i;
        if (self.starts("///")) {
            self.i += 3;
            while (self.i < self.input.len and self.input[self.i] != '\n') self.i += 1;
            try self.add(.doc_comment, s, self.i);
        } else if (self.starts("//")) {
            self.i += 2;
            while (self.i < self.input.len and self.input[self.i] != '\n') self.i += 1;
        } else if (self.starts("/*")) {
            self.i += 2;
            while (self.i + 1 < self.input.len and !self.starts("*/")) self.i += 1;
            if (self.i + 1 >= self.input.len) try self.err("L0011", "unterminated block comment", s, self.i) else self.i += 2;
        } else if (self.starts("/=")) try self.one(.slash_equal, 2) else try self.one(.slash, 1);
    }
    fn punct(self: *Lexer) !void {
        inline for (.{
            .{ ":=", .colon_equal }, .{ "==", .equal_equal }, .{ "!=", .bang_equal }, .{ "<=", .less_equal }, .{ ">=", .greater_equal }, .{ "+=", .plus_equal }, .{ "-=", .minus_equal }, .{ "*=", .star_equal }, .{ "%=", .percent_equal }, .{ "&&", .amp_amp }, .{ "||", .pipe_pipe }, .{ "<<", .shift_left }, .{ ">>", .shift_right }, .{ "..=", .dot_dot_equal }, .{ "..", .dot_dot }, .{ "=>", .equal_greater }, .{ ".?", .dot_question }, .{ ".!", .dot_bang }, .{ ".*", .dot_star },
        }) |p| if (self.starts(p[0])) return self.one(p[1], p[0].len);
        const s = self.i;
        const c = self.input[self.i];
        self.i += 1;
        const kind: ?tok.TokenKind = switch (c) {
            '(' => .l_paren,
            ')' => .r_paren,
            '{' => .l_brace,
            '}' => .r_brace,
            '[' => .l_bracket,
            ']' => .r_bracket,
            ',' => .comma,
            ':' => .colon,
            '.' => .dot,
            '?' => .question,
            '!' => .bang,
            '+' => .plus,
            '-' => .minus,
            '*' => .star,
            '%' => .percent,
            '&' => .amp,
            '|' => .pipe,
            '^' => .caret,
            '~' => .tilde,
            '=' => .equal,
            '<' => .less,
            '>' => .greater,
            else => null,
        };
        if (kind) |k| try self.add(k, s, self.i) else try self.err("L0012", "unexpected character", s, self.i);
    }
};
pub fn lexWithDiagnostics(allocator: std.mem.Allocator, file: source.FileId, input: []const u8, diagnostics: *diag.DiagnosticBag) !Result {
    var l = Lexer.init(allocator, file, input, diagnostics);
    defer l.deinit();
    return l.run();
}
pub fn lex(allocator: std.mem.Allocator, file: source.FileId, input: []const u8) !Result {
    var bag = diag.DiagnosticBag.init(allocator, .{});
    defer bag.deinit();
    return lexWithDiagnostics(allocator, file, input, &bag);
}
fn isIdentStart(c: u8) bool {
    return std.ascii.isAlphabetic(c) or c == '_';
}
fn isIdentContinue(c: u8) bool {
    return isIdentStart(c) or std.ascii.isDigit(c);
}
fn digitFor(base_marker: u8, c: u8) bool {
    return switch (base_marker) {
        'x', 'X' => std.ascii.isHex(c),
        'b', 'B' => c == '0' or c == '1',
        'o', 'O' => c >= '0' and c <= '7',
        else => false,
    };
}
fn expectNoErrors(src: []const u8) ![]tok.Token {
    var bag = diag.DiagnosticBag.init(std.testing.allocator, .{});
    defer bag.deinit();
    const r = try lexWithDiagnostics(std.testing.allocator, 0, src, &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.diagnostics.items.len);
    return r.tokens;
}

test "keywords literals identifiers and integer type names" {
    const tokens = try expectNoErrors("module main\ni32 u65535 true false null or");
    defer std.testing.allocator.free(tokens);
    try std.testing.expectEqual(tok.TokenKind.kw_module, tokens[0].kind);
    try std.testing.expectEqual(tok.TokenKind.identifier, tokens[3].kind);
    try std.testing.expectEqual(tok.TokenKind.identifier, tokens[4].kind);
    try std.testing.expectEqual(tok.TokenKind.true_literal, tokens[5].kind);
    try std.testing.expectEqual(tok.TokenKind.kw_or, tokens[8].kind);
}
test "numbers" {
    const tokens = try expectNoErrors("1_000 0xff 0b1010 0o755 1.0 1e3 1.5e-2 0..2");
    defer std.testing.allocator.free(tokens);
    try std.testing.expectEqual(tok.TokenKind.integer_literal, tokens[0].kind);
    try std.testing.expectEqual(tok.TokenKind.float_literal, tokens[4].kind);
    try std.testing.expectEqual(tok.TokenKind.integer_literal, tokens[7].kind);
    try std.testing.expectEqual(tok.TokenKind.dot_dot, tokens[8].kind);
}
test "strings chars escapes comments" {
    const tokens = try expectNoErrors("/// doc\n// no\n/* block */\n\"a\\n\\x41\\u{41}\" '\\''");
    defer std.testing.allocator.free(tokens);
    try std.testing.expectEqual(tok.TokenKind.doc_comment, tokens[0].kind);
    var saw_string = false;
    var saw_char = false;
    for (tokens) |t| {
        saw_string = saw_string or t.kind == .string_literal;
        saw_char = saw_char or t.kind == .char_literal;
    }
    try std.testing.expect(saw_string);
    try std.testing.expect(saw_char);
}
test "bad escape reports lexer diagnostic" {
    var bag = diag.DiagnosticBag.init(std.testing.allocator, .{});
    defer bag.deinit();
    const r = try lexWithDiagnostics(std.testing.allocator, 0, "\"\\q\"", &bag);
    defer r.deinit(std.testing.allocator);
    try std.testing.expectEqual(@as(usize, 1), bag.diagnostics.items.len);
    try std.testing.expectEqualStrings("L0010", bag.diagnostics.items[0].code);
}
test "corpus examples lex without error" {
    inline for (.{ @embedFile("../tests/corpus/examples/main.dyn"), @embedFile("../tests/corpus/examples/main2.dyn"), @embedFile("../tests/corpus/examples/other.dyn") }) |src| {
        var bag = diag.DiagnosticBag.init(std.testing.allocator, .{});
        defer bag.deinit();
        const r = try lexWithDiagnostics(std.testing.allocator, 0, src, &bag);
        defer r.deinit(std.testing.allocator);
        try std.testing.expectEqual(@as(usize, 0), bag.diagnostics.items.len);
    }
}
