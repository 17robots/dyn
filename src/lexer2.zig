const std = @import("std");
const Tok = @import("token.zig").Tok;

const Kw = std.StaticStringMap(Tok.Kind).initComptime(.{
    .{ "break", .@"break" },
    .{ "comp", .comp },
    .{ "continue", .@"continue" },
    .{ "defer", .@"defer" },
    .{ "else", .@"else" },
    .{ "enum", .@"enum" },
    .{ "extern", .@"extern" },
    .{ "fn", .@"fn" },
    .{ "for", .@"for" },
    .{ "false", .false },
    .{ "if", .@"if" },
    .{ "inline", .@"inline" },
    .{ "match", .match },
    .{ "module", .module },
    .{ "mut", .mut },
    .{ "or", .@"or" },
    .{ "pub", .@"pub" },
    .{ "return", .@"return" },
    .{ "struct", .@"struct" },
    .{ "true", .true },
    .{ "type", .type },
    .{ "use", .use },
});

inline fn keyword(str: []const u8) Tok.Kind {
    return Kw.get(str) orelse .identifier;
}
fn isHexDigit(b: u8) bool {
    return switch (b) {
        '0'...'9', 'a'...'f', 'A'...'F' => true,
        else => false,
    };
}
fn isDigitBase(b: u8, base: u8) bool {
    return switch (base) {
        2 => b == '0' or b == '1',
        8 => b >= '0' and b <= '7',
        10 => b >= '0' and b <= '9',
        16 => isHexDigit(b),
        else => false,
    };
}
const Self = @This();

text: []const u8,
i: usize = 0,

pub fn init(text: []const u8) Self {
    return .{ .text = text };
}
fn peek(self: Self) ?u8 {
    return self.peekN(1);
}
fn peekN(self: Self, n: usize) ?u8 {
    const j = self.i + n;
    if (j >= self.text.len) return null;
    return self.text[j];
}
fn atEnd(self: Self) bool {
    return self.i >= self.text.len;
}
pub fn next(self: *Self) ?Tok {
    while (!self.atEnd()) {
        switch (self.text[self.i]) {
            ' ', '\t', '\r' => self.i += 1,
            else => break,
        }
    }
    if (self.atEnd()) return null;

    const start = self.i;
    const tok_kind: Tok.Kind = switch (self.text[self.i]) {
        '\n' => .newline,
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
        '!' => blk: {
            if (self.peek() == '=') {
                self.i += 1;
                break :blk .neq;
            }
            break :blk .not;
        },
        '~' => blk: {
            if (self.peek() == '=') {
                self.i += 1;
                break :blk .compleq;
            }
            break :blk .complement;
        },
        '+' => blk: {
            if (self.peek() == '=') {
                self.i += 1;
                break :blk .addeq;
            }
            break :blk .add;
        },
        '-' => blk: {
            if (self.peek() == '=') {
                self.i += 1;
                break :blk .subeq;
            }
            break :blk .sub;
        },
        '*' => blk: {
            if (self.peek() == '=') {
                self.i += 1;
                break :blk .muleq;
            }
            break :blk .mul;
        },
        '%' => blk: {
            if (self.peek() == '=') {
                self.i += 1;
                break :blk .modeq;
            }
            break :blk .mod;
        },
        '^' => blk: {
            if (self.peek() == '=') {
                self.i += 1;
                break :blk .xoreq;
            }
            break :blk .xor;
        },
        '=' => blk: {
            if (self.peek()) |p| {
                if (p == '=') {
                    self.i += 1;
                    break :blk .eqeq;
                }
                if (p == '>') {
                    self.i += 1;
                    break :blk .arrow;
                }
            }
            break :blk .eq;
        },
        '&' => blk: {
            if (self.peek()) |p| {
                if (p == '=') {
                    self.i += 1;
                    break :blk .andeq;
                }
                if (p == '&') {
                    self.i += 1;
                    break :blk .land;
                }
            }
            break :blk .@"and";
        },
        '|' => blk: {
            if (self.peek()) |p| {
                if (p == '=') {
                    self.i += 1;
                    break :blk .pipeq;
                }
                if (p == '|') {
                    self.i += 1;
                    break :blk .lor;
                }
            }
            break :blk .pipe;
        },
        '.' => blk: {
            if (self.peek()) |p| {
                if (p == '.') {
                    self.i += 1;
                    if (self.peek() == '=') {
                        self.i += 1;
                        break :blk .rangeq;
                    }
                    break :blk .range;
                }
                if (p >= '0' and p <= '9') {
                    self.i += 1;
                    if (self.readFractionAndExponent()) |_| {
                        break :blk .float;
                    } else |_| {
                        break :blk .illegal;
                    }
                }
            }
            break :blk .dot;
        },
        '<' => blk: {
            if (self.peek()) |p| {
                if (p == '<') {
                    self.i += 1;
                    if (self.peek() == '=') {
                        self.i += 1;
                        break :blk .shleq;
                    }
                    break :blk .shl;
                }
                if (p == '=') {
                    self.i += 1;
                    break :blk .lte;
                }
            }
            break :blk .lt;
        },
        '>' => blk: {
            if (self.peek()) |p| {
                if (p == '>') {
                    self.i += 1;
                    if (self.peek() == '=') {
                        self.i += 1;
                        break :blk .shreq;
                    }
                    break :blk .shr;
                }
                if (p == '=') {
                    self.i += 1;
                    break :blk .gte;
                }
            }
            break :blk .gt;
        },
        '\'' => self.readChar(),
        '"' => self.readString(),
        '/' => blk: {
            if (self.peek()) |p| {
                if (p == '=') {
                    self.i += 1;
                    break :blk .diveq;
                }
                if (p == '/') {
                    self.i += 1;
                    const is_doc = self.peek() == '/';
                    if (is_doc) self.i += 1;
                    while (self.peek()) |c| {
                        if (c == '\n') break;
                        self.i += 1;
                    }
                    break :blk if (is_doc) .doc_comment else .line_comment;
                }
                if (p == '*') {
                    self.i += 1;
                    while (self.peek()) |c| {
                        self.i += 1;
                        if (c == '*' and self.peek() == '/') {
                            self.i += 1;
                            break :blk .block_comment;
                        }
                    }
                    break :blk .unclosed_block_comment;
                }
            }
            break :blk .div;
        },
        'a'...'z', 'A'...'Z', '$' => blk: {
            self.readIdentifier();
            break :blk keyword(self.text[start .. self.i + 1]);
        },
        '_' => blk: {
            if (self.peek()) |p| {
                switch (p) {
                    '_', 'a'...'z', 'A'...'Z', '0'...'9', '$' => {
                        self.readIdentifier();
                        break :blk .identifier;
                    },
                    else => {},
                }
            }
            break :blk .underscore;
        },
        '0'...'9' => blk: {
            const is_float = self.readNumber() catch break :blk .illegal;
            break :blk if (is_float) .float else .int;
        },
        else => .illegal,
    };

    const end = self.i;
    self.i += 1;
    return Tok.new(tok_kind, start, end);
}
fn readIdentifier(self: *Self) void {
    while (self.peek()) |p| {
        switch (p) {
            'a'...'z', 'A'...'Z', '0'...'9', '_' => self.i += 1,
            else => break,
        }
    }
}
fn readDigits(self: *Self, base: u8, allow_underscore: bool) bool {
    var saw_digit = false;
    var last_underscore = false;
    while (self.peek()) |p| {
        if (isDigitBase(p, base)) {
            saw_digit = true;
            last_underscore = false;
            self.i += 1;
            continue;
        }
        if (allow_underscore and p == '_') {
            if (!saw_digit or last_underscore) return false;
            last_underscore = true;
            self.i += 1;
            continue;
        }
        break;
    }
    return saw_digit and !last_underscore;
}
fn readFractionAndExponent(self: *Self) !void {
    _ = self.readDigits(10, true);

    if (self.peek()) |p| {
        if (p == 'e' or p == 'E') {
            self.i += 1;
            if (self.peek()) |sign| {
                if (sign == '+' or sign == '-') self.i += 1;
            }
            if (!self.readDigits(10, true)) return error.InvalidNumber;
        }
    }
}
fn readNumber(self: *Self) !bool {
    if (self.text[self.i] == '0') {
        if (self.peek()) |p| {
            const base: ?u8 = switch (p) {
                'b', 'B' => 2,
                'o', 'O' => 8,
                'x', 'X' => 16,
                else => null,
            };
            if (base) |b| {
                self.i += 1;
                if (!self.readDigits(b, true)) return error.InvalidNumber;
                return false;
            }
        }
    }

    var last_underscore = false;
    while (self.peek()) |p| {
        if (isDigitBase(p, 10)) {
            self.i += 1;
            last_underscore = false;
            continue;
        }
        if (p == '_') {
            const p2 = self.peekN(2) orelse return error.InvalidNumber;
            if (last_underscore or !isDigitBase(p2, 10)) return error.InvalidNumber;
            self.i += 1;
            last_underscore = true;
            continue;
        }
        break;
    }
    if (last_underscore) return error.InvalidNumber;

    if (self.peek() == '.') {
        if (self.peekN(2) == '.') return false;
        self.i += 1;
        try self.readFractionAndExponent();
        return true;
    }

    if (self.peek()) |p| {
        if (p == 'e' or p == 'E') {
            self.i += 1;
            if (self.peek()) |sign| {
                if (sign == '+' or sign == '-') self.i += 1;
            }
            if (!self.readDigits(10, true)) return error.InvalidNumber;
            return true;
        }
    }

    return false;
}
fn readChar(self: *Self) Tok.Kind {
    if (self.peek() == null) return .unclosed_character;
    self.i += 1;

    if (self.text[self.i] == '\'') {
        self.i += 1;
        return .empty_character;
    }

    if (self.text[self.i] == '\\') {
        if (!self.readEscape()) return .invalid_escape;
    } else if (self.text[self.i] >= 0x80) {
        if (!self.readUtf8Codepoint()) return .illegal;
    }

    if (self.peek() == null) return .unclosed_character;
    if (self.peek().? != '\'') return .character_too_long;
    self.i += 1;
    return .char;
}
fn readString(self: *Self) Tok.Kind {
    while (self.peek()) |p| {
        self.i += 1;
        if (p == '"') return .string;
        if (p == '\\' and !self.readEscape()) return .invalid_escape;
    }
    return .unclosed_string;
}
fn readEscape(self: *Self) bool {
    if (self.peek()) |p| {
        switch (p) {
            'n', 't', 'r', '\\', '\'', '"', '0' => {
                self.i += 1;
                return true;
            },
            'x' => {
                self.i += 1;
                var k: usize = 0;
                while (k < 2) : (k += 1) {
                    if (self.peek()) |h| {
                        if (!isHexDigit(h)) return false;
                        self.i += 1;
                    } else return false;
                }
                return true;
            },
            'u' => {
                self.i += 1;
                if (self.peek() != '{') return false;
                self.i += 1;
                var hex_count: usize = 0;
                while (self.peek()) |h| {
                    if (h == '}') break;
                    if (!isHexDigit(h)) return false;
                    hex_count += 1;
                    if (hex_count > 6) return false;
                    self.i += 1;
                }
                if (self.peek() != '}' or hex_count == 0) return false;
                self.i += 1;
                return true;
            },
            else => return false,
        }
    }
    return false;
}
fn readUtf8Codepoint(self: *Self) bool {
    const first = self.text[self.i];
    const n = std.unicode.utf8ByteSequenceLength(first) catch return false;
    if (self.i + n > self.text.len) return false;
    _ = std.unicode.utf8Decode(self.text[self.i..][0..n]) catch return false;
    self.i += n - 1;
    return true;
}
