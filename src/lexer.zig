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

pub fn lex(alloc: std.mem.Allocator, text: []const u8) ![]Tok {
    var toks: std.ArrayList(Tok) = .empty;
    var idx: usize = 0;
    var placeholder: usize = 0;
    var tok_to_add: ?Tok.Kind = null;
    while (idx < text.len) {
        placeholder = idx;
        tok_to_add = switch (text[idx]) {
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
            '.' => if (idx + 1 < text.len) switch (text[idx + 1]) {
                '.' => blk: {
                    idx += 1;
                    break :blk if (idx + 1 < text.len and text[idx + 1] == '=') blk2: {
                        idx += 1;
                        break :blk2 .rangeq;
                    } else .range;
                },
                '0'...'9' => blk: {
                    var exponent = false;
                    idx += 1;
                    while (idx + 1 < text.len) switch (text[idx + 1]) {
                        '0'...'9' => idx += 1,
                        'e', 'E' => {
                            if (exponent) break :blk Tok.Kind{ .float = text[placeholder .. idx + 1] };
                            if (text[idx] == '.') break :blk Tok.Kind{ .illegal = text[placeholder .. idx + 1] };
                            exponent = true;
                            idx += 1;
                            if (idx + 1 < text.len) switch (text[idx + 1]) {
                                '+', '-' => idx += 1,
                                else => {},
                            };
                            if (idx + 1 >= text.len or text[idx + 1] < '0' or text[idx + 1] > '9') break :blk Tok.Kind{ .illegal = text[placeholder .. idx + 1] };
                        },
                        else => break :blk Tok.Kind{ .float = text[placeholder .. idx + 1] },
                    };
                    break :blk Tok.Kind{ .float = text[placeholder .. idx + 1] };
                },
                else => .dot,
            } else .dot,
            '!', '~', '+', '-', '*', '%', '^' => if (idx + 1 < text.len and text[idx + 1] == '=') blk: {
                idx += 1;
                break :blk switch (text[idx - 1]) {
                    '!' => .neq,
                    '~' => .compleq,
                    '+' => .addeq,
                    '-' => .subeq,
                    '*' => .muleq,
                    '%' => .modeq,
                    '^' => .xoreq,
                    else => unreachable,
                };
            } else switch (text[idx]) {
                '!' => .not,
                '~' => .complement,
                '+' => .add,
                '-' => .sub,
                '*' => .mul,
                '%' => .mod,
                '^' => .xor,
                else => unreachable,
            },
            '/' => if (idx + 1 < text.len) switch (text[idx + 1]) {
                '=' => blk2: {
                    idx += 1;
                    break :blk2 .diveq;
                },
                '/' => blk2: {
                    idx += 1;
                    break :blk2 if (idx + 1 < text.len and text[idx + 1] == '/') blk3: {
                        idx += 1;
                        while (idx + 1 < text.len) {
                            if (text[idx + 1] == '\n') break :blk3 Tok.Kind{ .doc_comment = text[placeholder + 3 .. idx + 1] };
                            idx += 1;
                        }
                        break :blk3 Tok.Kind{ .doc_comment = text[placeholder + 3 .. idx + 1] };
                    } else blk3: {
                        while (idx + 1 < text.len) {
                            if (text[idx + 1] == '\n') break :blk3 Tok.Kind{ .line_comment = text[placeholder + 2 .. idx + 1] };
                            idx += 1;
                        }
                        break :blk3 Tok.Kind{ .line_comment = text[placeholder + 2 .. idx + 1] };
                    };
                },
                '*' => blk2: {
                    idx += 1;
                    while (idx + 1 < text.len) {
                        if (text[idx + 1] == '*') {
                            idx += 1;
                            if (idx + 1 < text.len and text[idx + 1] == '/') break :blk2 blk3: {
                                idx += 1;
                                break :blk3 Tok.Kind{ .block_comment = text[placeholder + 2 .. idx - 1] };
                            };
                        }
                        idx += 1;
                    }
                    break :blk2 Tok.Kind{ .unclosed_block_comment = .{ .start = placeholder, .end = idx } };
                },
                else => .div,
            } else .div,
            '=' => if (idx + 1 < text.len) switch (text[idx + 1]) {
                '>' => blk2: {
                    idx += 1;
                    break :blk2 .arrow;
                },
                '=' => blk2: {
                    idx += 1;
                    break :blk2 .eqeq;
                },
                else => .eq,
            } else .eq,
            '&' => if (idx + 1 < text.len) switch (text[idx + 1]) {
                '&' => blk2: {
                    idx += 1;
                    break :blk2 .land;
                },
                '=' => blk2: {
                    idx += 1;
                    break :blk2 .andeq;
                },
                else => .@"and",
            } else .@"and",
            '|' => if (idx + 1 < text.len) switch (text[idx + 1]) {
                '|' => blk2: {
                    idx += 1;
                    break :blk2 .lor;
                },
                '=' => blk2: {
                    idx += 1;
                    break :blk2 .pipeq;
                },
                else => .pipe,
            } else .pipe,
            '<' => if (idx + 1 < text.len) switch (text[idx + 1]) {
                '<' => blk2: {
                    idx += 1;
                    break :blk2 if (idx + 1 < text.len and text[idx + 1] == '=') blk3: {
                        idx += 1;
                        break :blk3 .shleq;
                    } else .shl;
                },
                '=' => blk2: {
                    idx += 1;
                    break :blk2 .lte;
                },
                else => .lt,
            } else .lt,
            '>' => if (idx + 1 < text.len) switch (text[idx + 1]) {
                '>' => blk2: {
                    idx += 1;
                    break :blk2 if (idx + 1 < text.len and text[idx + 1] == '=') blk3: {
                        idx += 1;
                        break :blk3 .shreq;
                    } else .shr;
                },
                '=' => blk2: {
                    idx += 1;
                    break :blk2 .gte;
                },
                else => .gt,
            } else .gt,
            '\'' => blk: {
                idx += 1;
                if (idx >= text.len) break :blk Tok.Kind{ .illegal = text[placeholder..idx] };
                if (text[idx] == '\\') {
                    idx += 1;
                    if (idx >= text.len) break :blk Tok.Kind{ .illegal = text[placeholder..idx] };
                    switch (text[idx]) {
                        'n', 't', 'r', '\\', '\'', '0' => {},
                        'x' => {
                            var i: usize = 0;
                            while (i < 2) : (i += 1) {
                                idx += 1;
                                if (idx >= text.len) break :blk Tok.Kind{ .illegal = text[placeholder..idx] };
                                switch (text[idx]) {
                                    '0'...'9', 'a'...'f', 'A'...'F' => {},
                                    else => break :blk Tok.Kind{ .illegal = text[placeholder .. idx + 1] },
                                }
                            }
                        },
                        'u' => {
                            idx += 1;
                            if (idx >= text.len or text[idx] != '{') break :blk Tok.Kind{ .illegal = text[placeholder..idx] };
                            idx += 1;
                            var hex_count: usize = 0;
                            while (idx < text.len and text[idx] != '}') : (idx += 1) {
                                switch (text[idx]) {
                                    '0'...'9', 'a'...'f', 'A'...'F' => hex_count += 1,
                                    else => break :blk Tok.Kind{ .illegal = text[placeholder .. idx + 1] },
                                }
                            }
                            if (idx >= text.len or text[idx] != '}' or hex_count == 0 or hex_count > 6) break :blk Tok.Kind{ .illegal = text[placeholder .. idx + 1] };
                        },
                        else => break :blk Tok.Kind{ .illegal = text[placeholder..idx] },
                    }
                } else if (text[idx] == '\'') break :blk Tok.Kind{ .illegal = text[placeholder..idx] } else if (text[idx] >= 0x80) {
                    idx += 1;
                    while (idx < text.len and (text[idx] & 0xC0) == 0x80) idx += 1;
                    idx -= 1;
                }
                idx += 1;
                if (idx >= text.len or text[idx] != '\'') break :blk Tok.Kind{ .illegal = text[placeholder..idx] };
                break :blk Tok.Kind{ .char = text[placeholder + 1 .. idx] };
            },
            '\"' => blk: {
                idx += 1;
                while (idx < text.len) {
                    switch (text[idx]) {
                        '\\' => idx += 1,
                        '\"' => break :blk Tok.Kind{ .string = text[placeholder + 1 .. idx] },
                        else => {},
                    }
                    idx += 1;
                }
                break :blk Tok.Kind{ .unclosed_string = .{ .start = placeholder, .end = idx } };
            },
            '\n' => Tok.Kind{ .terminator = .newline },
            'a'...'z', 'A'...'Z', '$' => blk: {
                while (idx + 1 < text.len) {
                    switch (text[idx + 1]) {
                        'a'...'z', 'A'...'Z', '_', '0'...'9' => idx += 1,
                        else => break :blk keyword(text[placeholder .. idx + 1]),
                    }
                }
                break :blk keyword(text[placeholder .. idx + 1]);
            },
            '_' => if (idx + 1 < text.len) switch (text[idx + 1]) {
                'a'...'z', 'A'...'Z', '$', '0'...'9' => blk: {
                    while (idx + 1 < text.len) {
                        switch (text[idx + 1]) {
                            'a'...'z', 'A'...'Z', '_', '0'...'9' => idx += 1,
                            else => break :blk keyword(text[placeholder .. idx + 1]),
                        }
                    }
                    break :blk keyword(text[placeholder .. idx + 1]);
                },
                else => .underscore,
            } else .underscore,
            '0' => if (idx + 1 < text.len) switch (text[idx + 1]) {
                'b', 'B' => read_num(text, placeholder, &idx, .bin),
                'e', 'E' => blk: {
                    var has_num = false;
                    idx += 1;
                    if (idx + 1 < text.len) switch (text[idx + 1]) {
                        '+', '-' => idx += 1,
                        else => {},
                    };
                    while (idx + 1 < text.len) switch (text[idx + 1]) {
                        '0'...'9' => {
                            has_num = true;
                            idx += 1;
                        },
                        '_' => idx += 1,
                        else => break,
                    };
                    break :blk if (has_num) Tok.Kind{ .float = text[placeholder .. idx + 1] } else Tok.Kind{ .illegal = text[placeholder .. idx + 1] };
                },
                'o', 'O' => read_num(text, placeholder, &idx, .oct),
                'x', 'X' => read_num(text, placeholder, &idx, .hex),
                '.' => blk: {
                    if (idx + 2 < text.len and text[idx + 2] == '.') break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] };
                    var has_num = false;
                    idx += 1;
                    var exponent = false;
                    while (idx + 1 < text.len) switch (text[idx + 1]) {
                        '0'...'9' => {
                            if (!has_num) has_num = true;
                            idx += 1;
                        },
                        '_' => idx += 1,
                        'e', 'E' => {
                            if (!has_num) break :blk Tok.Kind{ .illegal = text[placeholder .. idx + 1] };
                            if (exponent) break :blk Tok.Kind{ .float = text[placeholder .. idx + 1] };
                            if (text[idx] == '.') break :blk Tok.Kind{ .illegal = text[placeholder .. idx + 1] };
                            exponent = true;
                            idx += 1;
                            if (idx + 1 < text.len) switch (text[idx + 1]) {
                                '+', '-' => idx += 1,
                                else => {},
                            };
                            if (idx + 1 >= text.len or text[idx + 1] < '0' or text[idx + 1] > '9') break :blk Tok.Kind{ .illegal = text[placeholder .. idx + 1] };
                        },
                        else => break,
                    };
                    break :blk Tok.Kind{ .float = text[placeholder .. idx + 1] };
                },
                else => Tok.Kind{ .int = text[placeholder .. idx + 1] },
            } else Tok.Kind{ .int = text[placeholder .. idx + 1] },
            '1'...'9' => blk: {
                var decimal = false;
                var exponent = false;
                while (idx + 1 < text.len) switch (text[idx + 1]) {
                    '0'...'9' => idx += 1,
                    '_' => idx += 1,
                    '.' => {
                        if (idx + 2 < text.len and text[idx + 2] == '.') break;
                        if (decimal or exponent) break;
                        decimal = true;
                        idx += 1;
                    },
                    'e', 'E' => {
                        if (exponent) break;
                        exponent = true;
                        decimal = true;
                        idx += 1;
                        if (idx + 1 < text.len) switch (text[idx + 1]) {
                            '+', '-' => idx += 1,
                            else => {},
                        };
                        if (idx + 1 >= text.len or text[idx + 1] < '0' or text[idx + 1] > '9') break :blk Tok.Kind{ .illegal = text[placeholder .. idx + 1] };
                    },
                    else => break,
                };
                break :blk if (decimal) Tok.Kind{ .float = text[placeholder .. idx + 1] } else Tok.Kind{ .int = text[placeholder .. idx + 1] };
            },
            '\t', ' ', '\r' => null,
            else => Tok.Kind{ .illegal = text[placeholder .. idx + 1] },
        };
        if (tok_to_add) |t| try toks.append(alloc, Tok.new(t, @intCast(placeholder), @intCast(idx)));
        tok_to_add = null;
        idx += 1;
    }
    return try toks.toOwnedSlice(alloc);
}

inline fn keyword(str: []const u8) Tok.Kind {
    return Kw.get(str) orelse Tok.Kind{ .identifier = str };
}

fn read_num(str: []const u8, placeholder: usize, idx: *usize, read_kind: enum { bin, hex, oct }) Tok.Kind {
    var has_num = false;
    idx.* += 1;
    while (idx.* + 1 < str.len) {
        const next = str[idx.* + 1];
        const is_digit = switch (read_kind) {
            .bin => next >= '0' and next <= '1',
            .oct => next >= '0' and next <= '7',
            .hex => (next >= '0' and next <= '9') or (next >= 'a' and next <= 'f') or (next >= 'A' and next <= 'F'),
        };
        if (is_digit) {
            has_num = true;
            idx.* += 1;
        } else if (next == '_') idx.* += 1 else break;
    }
    return if (has_num) switch (read_kind) {
        .bin => Tok.Kind{ .bin_int = str[placeholder .. idx.* + 1] },
        .hex => Tok.Kind{ .hex_int = str[placeholder .. idx.* + 1] },
        .oct => Tok.Kind{ .oct_int = str[placeholder .. idx.* + 1] },
    } else Tok.Kind{ .illegal = str[placeholder .. idx.* + 1] };
}

// new struct implementation
text: []const u8,
i: usize = 0,
const Self = @This();
pub fn init(text: []const u8) Self {
    return .{ .text = text };
}
fn eof(self: Self) bool {
    return self.i >= self.text.len;
}
fn cur(self: Self) u8 {
    return self.text[self.i];
}
fn peek(self: Self) ?u8 {
    const j = self.i + 1;
    if (j >= self.text.len) return null;
    return self.text[j];
}
fn advance(self: *Self, n: usize) void {
    self.i += n;
}
fn match(self: *Self, b: u8) bool {
    if (self.peek(1) orelse 0 != b) return false;
    self.advance(1);
    return true;
}
fn emit(kind: Tok.Kind, start: usize, end: usize) Tok {
    return Tok.new(kind, @intCast(start), @intCast(end));
}
pub fn next(self: *Self) !?Tok {
    while (!self.eof()) switch (self.cur()) {
        ' ', '\t', '\r' => self.advance(1),
        else => break,
    };
    if (self.eof()) return null;
    const start = self.i;
    return switch (self.cur()) {
        '\n' => blk: {
            self.advance(1);
            break :blk self.emit(.{ .terminator = .newline });
        },
        'a'...'z', 'A'...'Z', '_', '$' => self.lex_ident_or_keyword(start),
        '0'...'9' => {},
        '.' => blk: {
            if (self.peek(1) orelse 0 >= '0' and (self.peek() orelse 0) <= '9') break :blk {};
            break :blk {};
        },
        '"' => {},
        '\'' => {},
        '/' => self.lex_slash_family(start),
        else => {},
    };
}
fn lex_ident_or_keyword(self: *Self, start: usize) Tok {
    if (self.cur() < 0x80) self.advance(1) else {
        if (!self.consume_utf8_codepoint()) {
            self.advance(1);
            return self.emit(.{ .illegal = self.text[start..self.i] }, start, self.i);
        }
    }
    while (!self.eof()) {
        const b = self.cur();
        if (b < 0x80) switch (b) {
            'a'...'z', 'A'...'Z', '0'...'9', '_', '$' => self.advance(1),
            else => break,
        } else {
            if (!self.consume_utf8_codepoint()) break;
        }
        return self.emit(keyword(self.text[start..self.i], start, self.i));
    }
}
fn consume_utf8_codepoint(self: *Self) bool {
    const first = self.cur();
    const n = std.unicode.utf8ByteSequenceLength(first) catch return false;
    if (self.i + n > self.text.len) return false;
    _ = std.unicode.utf8Decode(self.text[self.i..][0..n]) catch return false;
    self.advance(n);
    return true;
}
fn lex_slash_family(self: *Self, start: usize) Tok {
    return switch (self.peek(1)) {
        '=' => blk: {
            self.advance(2);
            break :blk self.emit(.diveq, start, self.i);
        },
        '/' => blk: {
            self.advance(2);
            const is_doc = self.peek(1) == '/';
            if (is_doc) self.advance(1);
            const comment_start = self.i;
            while (!self.eof() and self.cur() != '\n') self.advance(1);
            const slice = self.text[comment_start..self.i];
            break :blk self.emit(if (is_doc) .{ .doc_comment = slice } else .{ .line_comment = slice }, start, self.i);
        },
        '*' => blk: {
            self.advance(2);
            const comment_start = self.i;
            while (!self.eof()) {
                if (self.cur() == '*' and self.peek(1) == '/') {
                    self.advance(2);
                    break :blk self.emit(.{ .block_comment = self.text[comment_start..self.i] }, start, self.i);
                }
            }
        },
        else => blk: {
            self.advance(1);
            break :blk self.emit(.div, start, self.i);
        },
    };
}
fn lex_number(self: *Self, start: usize) Tok {
    var float = false;
    if (self.cur() == '.') {
        self.advance(1);
        _ = self.consume_digits(false);
        float = true;
        if (!self.eof() and (self.cur() == 'e' or self.cur() == 'E')) {
            self.advance(1);
            if(!self.eof() and (self.cur() == '-' or self.cur() == '+')) self.advance(1);
            if(!self.consume_digits(false)) return self.emit(.{ .illegal = self.text[start..self.i]}, start, self.i);
        }
        return self.emit(.{.float = self.text[start..self.i]}, start, self.i);
    }
}
fn consume_digits(self: *Self, comptime hex: bool) bool {
    var saw = false;
    var prev_underscore = false;
    while (!self.eof()) {
        const b = self.cur();
        const ok_digit = if (hex) is_hex_digit(b) else is_dec_digit(b);
        if (ok_digit) {
            saw = true;
            prev_underscore = false;
            self.advance(1);
            continue;
        }
        if (b == '_') {
            if (!saw or prev_underscore) break;
            prev_underscore = true;
            self.advance(1);
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
        self.advance(2);
        if (self.peek(0) == '.') return self.emit(.rangeq, start, self.i);
    }
    self.advance(1);
    return self.emit(.dot, start, self.i);
}
