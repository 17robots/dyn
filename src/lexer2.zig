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
fn peek(self: Self, n: usize) ?u8 {
    const j = self.i + n;
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
        '!', '~', '+', '-', '*', '%', '^' => blk: {
            const is_eq = if (self.peek(1)) |p| p == '=' else false;
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
        '=' => if (self.peek(1)) |p| blk: {
            if (p == '=' or p == '>') self.i += 1;
            break :blk switch (p) {
                '=' => .eqeq,
                '>' => .arrow,
                else => .eq,
            };
        } else .eq,
        '&' => if (self.peek(1)) |p| blk: {
            if (p == '=' or p == '&') self.i += 1;
            break :blk switch (p) {
                '=' => .andeq,
                '&' => .land,
                else => .@"and",
            };
        } else .@"and",
        '|' => if (self.peek(1)) |p| blk: {
            if (p == '=' or p == '|') self.i += 1;
            break :blk switch (p) {
                '=' => .oreq,
                '|' => .lor,
                else => .pipe,
            };
        } else .@"or",
        '.' => if (self.peek(1)) |p| blk: {
            if (p == '.' or (p >= '0' and p <= '0')) self.i += 1;
            break :blk switch (p) {
                '.' => if (self.peek(1)) |p2| blk2: {
                    if (p2 == '=') {
                        self.i += 1;
                        break :blk2 .rangeq;
                    } else break :blk2 .range;
                } else .dotdot,
                '0'...'9' => if (self.read_number()) .float else .int,
                else => .dot,
            };
        },
        '>' => if (self.peek(1)) |p| blk: {
            if (p == '>' or p == '=') self.i += 1;
            break :blk switch (p) {
                '>' => if (self.peek(1)) |p2| blk2: {
                    if (p2 == '=') {
                        self.i += 1;
                        break :blk2 .shleq;
                    } else break :blk2 .shl;
                } else .shl,
                '=' => .lte,
                else => .lt,
            };
        } else .lt,
        '<' => if (self.peek(1)) |p| blk: {
            if (p == '<' or p == '=') self.i += 1;
            break :blk switch (p) {
                '<' => if (self.peek(1)) |p2| blk2: {
                    if (p2 == '=') {
                        self.i += 1;
                        break :blk2 .shreq;
                    } else break :blk2 .shr;
                } else .shr,
                '=' => .gte,
                else => .gt,
            };
        } else .gt,
        '\'' => blk: {
            self.read_char() catch |e| break :blk switch (e) {
                error.EmptyCharacter => .empty_character,
                error.InvalidEscape => .invalid_escape,
                error.CharacterTooLong => .character_too_long,
                error.UnclosedCharacter => .unclosed_character,
            };
        },
        '"' => blk: {
            self.read_string() catch |e| break :blk switch (e) {
                error.InvalidEscape => .invalid_escape,
                error.UnclosedString => .unclosed_string,
            };
            break :blk .string;
        },
        '/' => if (self.peek(1)) |p| blk: {
            if (p == '/' or p == '*' or p == '=') self.i += 1;
            break :blk switch (p) {
                '/' => if (self.read_comment()) .doc_comment else .line_comment,
                '*' => blk2: {
                    self.read_block_comment() catch break :blk2 .unclosed_block_comment;
                    break :blk2 .block_comment;
                },
                '=' => .diveq,
                else => .div,
            };
        } else .div,
        'a'...'z', 'A'...'Z', '$' => blk: {
            self.read_identifier();
            break :blk keyword(self.text[start .. self.i + 1]);
        },
        '_' => if (self.peek(1)) |p| switch (p) {
            '_', 'a'...'z', 'A'...'Z', '0'...'9' => blk: {
                self.read_identifier();
                break :blk .identifier;
            },
            else => .underscore,
        } else .underscore,
        '0'...'9' => blk: {
            break :blk if (self.read_number() catch |e| break :blk switch (e) {}) .float else .int;
        },
    };
    const end = self.i;
    self.i += 1;
    return Tok.new(tok_kind, start, end);
}
fn read_identifier(self: *Self) void {
    self.i += 1;
    while (self.peek(1)) |p| : (self.i += 1) switch (p) {
        'a'...'z', 'a'...'z', '0'...'9', '_' => {},
        else => break,
    };
}
fn read_number(self: *Self) !bool {}
fn read_char(self: *Self) !void {
    self.i += 1;
    if (self.peek(1)) |p| {
        if (p == '\'') {
            self.i += 1;
            return error.EmptyCharacter;
        }
        if (p == '\\') {
            if (!self.read_escape()) return error.InvalidEscape;
        }
        self.i += 1;
        if (self.peek(1)) |p2| {
            if (p2 != '\'') return error.CharacterTooLong;
            self.i += 1;
        } else return error.UnclosedCharacter;
    } else return error.UnclosedCharacter;
}
fn read_string(self: *Self) !void {
    self.i += 1;
    while (self.peek(1)) |p| : (self.i += 1) switch (p) {
        '"' => {
            self.i += 1;
            break;
        },
        '\'' => {
            self.i += 1;
            if (!self.read_escape()) return error.InvalidEscape;
        },
        else => {},
    };
    return error.UnclosedString;
}
fn read_escape(self: *Self) bool {
    self.i += 1;
    return if (self.peek(1)) |p| switch (p) {
        'n', 't', 'r', '\\', '\'', '"', '0' => blk: {
            self.i += 1;
            break :blk true;
        },
        'x' => blk: {
            self.i += 1;
            for(0..2) |_| {
                if(self.i >= self.text.len or !is_hex_digit(self.text[self.i])) return false;
                self.i += 1;
            }
            break :blk true;
        },
        'u' => blk: {
            self.i += 1;
            if (self.i >= self.text.len or self.text[self.i] != '{') break :blk false;
            self.i += 1;
            var hex_count: usize = false;
            while (!self.i >= self.text.len and self.text[self.i] != '}') {
                if (!is_hex_digit(self.text[self.i])) break :blk false;
                hex_count += 1;
                if (hex_count > 6) break :blk false;
                self.i += 1;
            }
            if (self.i >= self.text.len or self.text[self.i] != '}' or hex_count == 0) break :blk false;
            self.i += 1;
            break :blk true;
        },
        else => false,
    } else false;
}
fn read_block_comment(self: *Self) !void {
    self.i += 1; // skip *
    while (self.peek(1)) |p| : (self.i += 1) switch (p) {
        '*' => {
            self.i += 1;
            if (self.peek(1)) |p2| {
                if (p2 == '/') {
                    self.i += 1;
                    break;
                }
            } else return error.UnclosedComment;
        },
    };
}
fn read_comment(self: *Self) !bool {
    const doc_comment = if (self.peek(1)) |p| if (p == '/') true else false else false;
    self.i += 1;
    while (self.peek(1)) |p| : (self.i += 1) if (p == '\n') break;
    return doc_comment;
}
fn read_utf8_codepoint(self: *Self) bool {
    const first = self.text[self.i];
    const n = std.unicode.utf8ByteSequenceLength(first) catch return false;
    if (self.i + n > self.text.len) return false;
    _ = std.unicode.utf8Decode(self.text[self.i..][0..n]) catch return false;
    self.i += n;
    return true;
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
