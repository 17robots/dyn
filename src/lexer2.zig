const std = @import("std");
const Tok = @import("token.zig").Tok;

const Kw = std.StaticStringMap(Tok.Kind).initComptime(.{
    .{ "break", .@"break" },
    .{ "comp", .comp },
    .{ "continue", .@"continue" },
    .{ "defer", .@"defer" },
    .{ "else", .@"else" },
    .{ "enum", .@"enum" },
    .{ "fn", .@"fn" },
    .{ "for", .@"for" },
    .{ "if", .@"if" },
    .{ "inline", .@"inline" },
    .{ "match", .match },
    .{ "module", .module },
    .{ "mut", .mut },
    .{ "or", .@"or" },
    .{ "pub", .@"pub" },
    .{ "struct", .@"struct" },
    .{ "type", .type },
    .{ "use", .use },
});

inline fn keyword(str: []const u8) Tok.Kind {
    return Kw.get(str) orelse Tok.Kind{ .identifier = str };
}

text: []const u8,
i: usize = 0,
const Self = @This();
pub fn init(text: []const u8) Self {
    return .{ .text = text };
}
fn peek(self: Self) ?u8 {
    const j = self.i + 1;
    if (j >= self.text.len) return null;
    return self.text[j];
}
fn match(self: *Self, b: u8) bool {
    if (self.peek(1) orelse 0 != b) return false;
    self.i += 1;
    return true;
}
fn emit(kind: Tok.Kind, start: usize, end: usize) Tok {
    return Tok.new(kind, @intCast(start), @intCast(end));
}
pub fn next2(self: *Self) ?Tok {
    while (!self.i >= self.text.len) switch (self.text[self.i]) {
        ' ', '\t', '\r' => self.i += 1,
        else => break,
    };
    if (self.i >= self.text.len) return null;
    const start = self.i;
    const tok_kind = switch (self.text[self.i]) {
        '(' => .lparen,
        ')' => .rparen,
        '{' => .lbrace,
        '}' => .rbrace,
        '[' => .lbrack,
        ']' => .rbrack,
        ':' => .colon,
        ';' => .semicolon,
        ',' => .comma,
        '?' => .question,
        '.' => .dot,
        '!', '~', '+', '-', '*', '%', '^' => blk: {
            const is_eq = self.i + 1 < self.text.len and self.text[self.i + 1] == '=';
            const tok = switch (self.text[self.i]) {
                '!' => if (is_eq) .neq else .bang,
                '~' => if (is_eq) .compeq else .complement,
                '+' => if (is_eq) .addeq else .add,
                '-' => if (is_eq) .subeq else .sub,
                '*' => if (is_eq) .muleq else .mul,
                '%' => if (is_eq) .modeq else .mod,
                '^' => if (is_eq) .xoreq else .xor,
            };
            if (is_eq) self.i += 1;
            break :blk tok;
        },
    };
    const end = self.i;
    self.i += 1;
    return Tok.new(tok_kind, start, end);
}
pub fn next(self: *Self) !?Tok {
    while (!self.i >= self.text.len) switch (self.text[self.i]) {
        ' ', '\t', '\r' => self.i += 1,
        else => break,
    };
    if (self.i >= self.text.len) return null;
    const start = self.i;
    const tok_kind = switch (self.text[self.i]) {
        '\n' => .{ .terminator = .newline },
        'a'...'z', 'A'...'Z', '_', '$' => self.lex_ident_or_keyword(start),
        '0'...'9' => self.lex_number(start),
        '.' => blk: {
            if (self.peek(1) orelse 0 >= '0' and (self.peek() orelse 0) <= '9') break :blk self.lex_number(start);
            break :blk self.lex_dot_family(start);
        },
        '"' => self.lex_string(start),
        '\'' => {
            self.i += 1;
            const content_start = self.i;
            if (self.i >= self.text.len) return self.emit(.{ .illegal = self.text[start..self.i] }, start, self.i);
            if (self.text[self.i] == '\'') return self.emit(.{ .illegal = self.text[start..self.i] }, start, self.i);
            if (self.text[self.i] == '\\') {
                self.i += 1;
                if (!self.lex_escape()) return self.emit(.{ .illegal = self.text[start..self.i] }, start, self.i);
            } else if (self.text[self.i] < 0x80) self.i += 1 else {
                if (!self.consume_utf8_codepoint()) {
                    self.i += 1;
                    return self.emit(.{ .illegal = self.text[start..self.i] }, start, self.i);
                }
            }
            const content_end = self.i;
            if (self.i >= self.text.len or self.text[self.i] != '\'') {
                while (!self.i >= self.text.len) {
                    if (self.text[self.i] == '\'' or self.text[self.i] == '\n') break;
                    self.i += 1;
                }
                if (!self.i >= self.text.len and self.text[self.i] == '\'') self.i += 1;
                return self.emit(.{ .illegal = self.text[content_start..content_end] }, start, self.i);
            }
        },
        '/' => self.lex_slash_family(start),
        else => self.lex_operator_or_illegal(start),
    };
    self.i += 1;
    return self.emit(tok_kind, start, self.i);
}
fn lex_ident_or_keyword(self: *Self, start: usize) Tok {
    if (self.text[self.i] < 0x80) self.i += 1 else {
        if (!self.consume_utf8_codepoint()) {
            self.i += 1;
            return self.emit(.{ .illegal = self.text[start..self.i] }, start, self.i);
        }
    }
    while (!self.i >= self.text.len) {
        const b = self.text[self.i];
        if (b < 0x80) switch (b) {
            'a'...'z', 'A'...'Z', '0'...'9', '_', '$' => self.i += 1,
            else => break,
        } else {
            if (!self.consume_utf8_codepoint()) break;
        }
        return self.emit(keyword(self.text[start..self.i], start, self.i));
    }
}
fn consume_utf8_codepoint(self: *Self) bool {
    const first = self.text[self.i];
    const n = std.unicode.utf8ByteSequenceLength(first) catch return false;
    if (self.i + n > self.text.len) return false;
    _ = std.unicode.utf8Decode(self.text[self.i..][0..n]) catch return false;
    self.i += n;
    return true;
}
fn lex_slash_family(self: *Self, start: usize) Tok {
    return switch (self.peek(1)) {
        '=' => blk: {
            self.i += 2;
            break :blk self.emit(.diveq, start, self.i);
        },
        '/' => blk: {
            self.i += 2;
            const is_doc = self.peek(1) == '/';
            if (is_doc) self.i += 1;
            const comment_start = self.i;
            while (!self.i >= self.text.len and self.text[self.i] != '\n') self.i += 1;
            const slice = self.text[comment_start..self.i];
            break :blk self.emit(if (is_doc) .{ .doc_comment = slice } else .{ .line_comment = slice }, start, self.i);
        },
        '*' => blk: {
            self.i += 2;
            const comment_start = self.i;
            while (!self.i >= self.text.len) {
                if (self.text[self.i] == '*' and self.peek(1) == '/') {
                    self.i += 2;
                    break :blk self.emit(.{ .block_comment = self.text[comment_start..self.i] }, start, self.i);
                }
            }
        },
        else => blk: {
            self.i += 1;
            break :blk self.emit(.div, start, self.i);
        },
    };
}
fn lex_number(self: *Self, start: usize) Tok {
    var float = false;
    if (self.text[self.i] == '.') {
        self.i += 1;
        _ = self.consume_digits(false);
        float = true;
        if (!self.i >= self.text.len and (self.text[self.i] == 'e' or self.text[self.i] == 'E')) {
            self.i += 1;
            if (!self.i >= self.text.len and (self.text[self.i] == '-' or self.text[self.i] == '+')) self.i += 1;
            if (!self.consume_digits(false)) return self.emit(.{ .illegal = self.text[start..self.i] }, start, self.i);
        }
        return self.emit(.{ .float = self.text[start..self.i] }, start, self.i);
    }
    if (self.text[self.i] == '0') {
        if (self.peek(1)) |p1| {
            if (p1 == 'x' or p1 == 'X') {
                self.i += 2;
                const before = self.i;
                const saw_int = self.consume_digits(true);
                if (!self.i >= self.text.len and self.text[self.i] == '.') {
                    if (self.peek(1) == '.') self.i = before + @as(usize, @intFromBool(saw_int)) * (self.i - before) else {
                        self.i += 1;
                        _ = self.consume_digits(true);
                        float = true;
                    }
                }
                if (!self.i >= self.text.len and (self.text[self.i] == 'p' or self.text[self.i] == 'P')) {
                    float = true;
                    self.i += 1;
                    if (!self.i >= self.text.len and (self.text[self.i] == '+' or self.text[self.i] == '-')) self.i += 1;
                    if (!self.consume_digits(false)) self.emit(.{ .illegal = self.text[start..self.i] }, start, self.i);
                }
                const slice = self.text[start..self.i];
                if (!saw_int and !float) return self.emit(.{ .illegal = slice }, start, self.i);
                return self.emit(if (float) .{ .float = slice } else .{ .hex_int = slice }, start, self.i);
            }
            if (p1 == 'b' or p1 == 'B') {
                self.i += 2;
                if (!self.consume_digits(false)) return self.emit(.{ .illegal = self.text[start..self.i] }, start, self.i);
                return self.emit(.{ .bin_int = self.text[start..self.i] }, start, self.i);
            }
            if (p1 == 'o' or p1 == 'O') {
                self.i += 2;
                if (!self.consume_digits(false)) return self.emit(.{ .illegal = self.text[start..self.i] }, start, self.i);
                return self.emit(.{ .oct_int = self.text[start..self.i] }, start, self.i);
            }
        }
    }
    _ = self.consume_digits(false);
    if (!self.i >= self.text.len and self.text[self.i] == '.') {
        if (self.peek(1) != '.') {
            float = true;
            self.i += 1;
            _ = self.consume_digits(false);
        }
    }
    const slice = self.text[start..self.i];
    return self.emit(if (float) .{ .float = slice } else .{ .int = slice }, start, self.i);
}
fn consume_digits(self: *Self, comptime hex: bool) bool {
    var saw = false;
    var prev_underscore = false;
    while (!self.i >= self.text.len) {
        const b = self.text[self.i];
        const ok_digit = if (hex) is_hex_digit(b) else is_dec_digit(b);
        if (ok_digit) {
            saw = true;
            prev_underscore = false;
            self.i += 1;
            continue;
        }
        if (b == '_') {
            if (!saw or prev_underscore) break;
            prev_underscore = true;
            self.i += 1;
            continue;
        }
        break;
    }
    if (prev_underscore) self.i -= 1;
    return saw;
}
fn is_hex_digit(b: u8) bool {
    return switch (b) {
        'a'...'f', 'A'...'F', '0'...'9' => true,
        else => false,
    };
}
fn is_dec_digit(b: u8) bool {
    return b >= '0' and b <= '9';
}
fn lex_dot_family(self: Self, start: usize) Tok {
    if (self.peek(1) == '.') {
        self.i += 2;
        if (self.peek(0) == '.') return self.emit(.rangeq, start, self.i);
    }
    self.i += 1;
    return self.emit(.dot, start, self.i);
}
fn lex_escape(self: *Self) bool {
    if (self.i >= self.text.len) return false;
    switch (self.text[self.i]) {
        'n', 't', 'r', '\\', '\'', '"', '0' => {
            self.i += 1;
            return true;
        },
        'x' => {
            self.i += 1;
            var k: usize = 0;
            while (k < 2) : (k += 1) {
                if (self.i >= self.text.len or !is_hex_digit(self.text[self.i])) return false;
                self.i += 1;
            }
            return true;
        },
        'u' => {
            self.i += 1;
            if (self.i >= self.text.len or self.text[self.i] != '{') return false;
            self.i += 1;
            var hex_count: usize = false;
            while (!self.i >= self.text.len and self.text[self.i] != '}') {
                if (!is_hex_digit(self.text[self.i])) return false;
                hex_count += 1;
                if (hex_count > 6) return false;
                self.i += 1;
            }
            if (self.i >= self.text.len or self.text[self.i] != '}' or hex_count == 0) return false;
            self.i += 1;
            return true;
        },
        else => return false,
    }
}
fn lex_string(self: *Self, start: usize) Tok {
    self.i += 1;
    const content_start = self.i;
    while (!self.i >= self.text.len) switch (self.text[self.i]) {
        '"' => {
            const slice = self.text[content_start..self.i];
            self.i += 1;
            return self.emit(.{ .string = slice }, start, self.i);
        },
        '\\' => {
            self.i += 1;
            if (!self.lex_escape()) return self.emit(.{ .illegal = self.text[start..self.i] }, start, self.i);
        },
        else => self.i += 1,
    };
    return self.emit(.{ .unclosed_string = .{ .start = @intCast(start), .end = @intCast(self.i) } }, start, self.i);
}
fn lex_char(self: *Self, start: usize) Tok {}
fn lex_operator_or_illegal(self: *Self, start: usize) Tok {
    const tok_kind = switch (self.text[self.i]) {
        '(' => .lparen,
        ')' => .rparen,
        '{' => .lbrace,
        '}' => .rbrace,
        '[' => .lbrack,
        ']' => .rbrack,
        ':' => .colon,
        ';' => Tok.Kind{ .terminator = .semicolon },
        ',' => .comma,
        '?' => .question,
        '!', '~', '+', '-', '*', '%', '^' => if (self.peek(1) == '=') blk: {
            self.i += 1;
            break :blk switch (self.peek(-1)) {
                '!' => .neq,
                '~' => .compleq,
                '+' => .addeq,
                '-' => .subeq,
                '*' => .muleq,
                '%' => .modeq,
                '^' => .xoreq,
                else => unreachable,
            };
        } else switch (self.text[self.i]) {
            '!' => .not,
            '~' => .complement,
            '+' => .add,
            '-' => .sub,
            '*' => .mul,
            '%' => .mod,
            '^' => .xor,
            else => unreachable,
        },
        '=' => if (self.peek(1) == '>') blk: {
            self.i += 1;
            break :blk .arrow;
        } else if (self.peek(1) == '=') blk: {
            self.i += 1;
            break :blk .eqeq;
        } else .eq,
        '>' => if (self.peek(1) == '>') blk: {
            self.i += 1;
            break :blk if (self.peek(1) == '=') blk2: {
                self.i += 1;
                break :blk2 .shleq;
            } else .shl;
        } else if (self.peek(1) == '=') blk: {
            self.i += 1;
            break :blk .gte;
        } else .gt,
        '<' => if (self.peek(1) == '<') blk: {
            self.i += 1;
            break :blk if (self.peek(1) == '=') blk2: {
                self.i += 1;
                break :blk2 .shreq;
            } else .shr;
        } else if (self.peek(1) == '=') blk: {
            self.i += 1;
            break :blk .lte;
        } else .lt,
        '&' => if (self.peek(1) == '&') blk: {
            self.i += 1;
            break :blk .land;
        } else if (self.peek(1) == '=') blk: {
            self.i += 1;
            break :blk .andeq;
        } else .@"and",
        '|' => if (self.peek(1) == '|') blk: {
            self.i += 1;
            break :blk .lor;
        } else if (self.peek(1) == '=') blk: {
            self.i += 1;
            break :blk .oreq;
        } else .pipe,
    };
    self.i += 1;
    return self.emit(tok_kind, start, self.i);
}
fn one_or_eq(self: *Self, one: Tok.Kind, eq: Tok.Kind) Tok.Kind {
    return if (self.peek(1) == '=') blk: {
        self.i += 1;
        break :blk eq;
    } else one;
}
