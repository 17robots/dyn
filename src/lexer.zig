const std = @import("std");
const Tok = @import("token.zig").Tok;

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
                    idx += 1;
                    while (idx + 1 < text.len) switch (text[idx + 1]) {
                        '0'...'9' => idx += 1,
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
                    '=' => .eqeq,
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
                '=' => .eq,
                else => unreachable,
            },
            '/' => if (idx + 1 < text.len) blk: {
                break :blk switch (text[idx + 1]) {
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
                };
            } else .div,
            '=' => if (idx + 1 < text.len) blk: {
                break :blk switch (text[idx + 1]) {
                    '>' => blk2: {
                        idx += 1;
                        break :blk2 .arrow;
                    },
                    '=' => blk2: {
                        idx += 1;
                        break :blk2 .eqeq;
                    },
                    else => .eq,
                };
            } else .eq,
            '&' => if (idx + 1 < text.len) blk: {
                break :blk switch (text[idx + 1]) {
                    '&' => blk2: {
                        idx += 1;
                        break :blk2 .land;
                    },
                    '=' => blk2: {
                        idx += 1;
                        break :blk2 .andeq;
                    },
                    else => .@"and",
                };
            } else .@"and",
            '|' => if (idx + 1 < text.len) blk: {
                break :blk switch (text[idx + 1]) {
                    '|' => blk2: {
                        idx += 1;
                        break :blk2 .lor;
                    },
                    '=' => blk2: {
                        idx += 1;
                        break :blk2 .pipeq;
                    },
                    else => .pipe,
                };
            } else .pipe,
            '<' => if (idx + 1 < text.len) blk: {
                break :blk switch (text[idx + 1]) {
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
                };
            } else .lt,
            '>' => if (idx + 1 < text.len) blk: {
                break :blk switch (text[idx + 1]) {
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
                };
            } else .gt,
            '\'' => {},
            '\"' => blk: {
                idx += 1;
                while (idx < text.len) {
                    if (text[idx] == '\"') break :blk Tok.Kind{ .string = text[placeholder + 1 .. idx] };
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
                'a'...'z', 'A'...'Z', '$' => blk: {
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
                'b', 'B' => read_num(text, &placeholder, &idx, .bin),
                'e', 'E' => blk: {
                    var has_num = false;
                    idx += 1;
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
                'o', 'O' => read_num(text, &placeholder, &idx, .oct),
                'x', 'X' => read_num(text, &placeholder, &idx, .hex),
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
                            if (text[idx] == '.') break :blk Tok.Kind{ .float = text[placeholder .. idx + 1] };
                            exponent = true;
                            idx += 1;
                        },
                        else => break :blk if (exponent) Tok.Kind{ .int = text[placeholder .. idx + 1] } else Tok.Kind{ .float = text[placeholder .. idx + 1] },
                    };
                    break :blk if (exponent) Tok.Kind{ .int = text[placeholder .. idx + 1] } else Tok.Kind{ .float = text[placeholder .. idx + 1] };
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
                        if (idx + 1 >= text.len or text[idx + 1] > '0' or text[idx + 1] < '9') break :blk Tok.Kind{ .illegal = text[placeholder .. idx + 1] };
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

fn keyword(str: []const u8) Tok.Kind {
    return if (std.mem.eql(u8, str, "break")) .@"break" else if (std.mem.eql(u8, str, "comp")) .comp else if (std.mem.eql(u8, str, "continue")) .@"continue" else if (std.mem.eql(u8, str, "defer")) .@"defer" else if (std.mem.eql(u8, str, "else")) .@"else" else if (std.mem.eql(u8, str, "enum")) .@"enum" else if (std.mem.eql(u8, str, "fn")) .@"fn" else if (std.mem.eql(u8, str, "for")) .@"for" else if (std.mem.eql(u8, str, "if")) .@"if" else if (std.mem.eql(u8, str, "inline")) .@"inline" else if (std.mem.eql(u8, str, "match")) .match else if (std.mem.eql(u8, str, "module")) .module else if (std.mem.eql(u8, str, "mut")) .mut else if (std.mem.eql(u8, str, "or")) .@"or" else if (std.mem.eql(u8, str, "pub")) .@"pub" else if (std.mem.eql(u8, str, "struct")) .@"struct" else if (std.mem.eql(u8, str, "type")) .type else if (std.mem.eql(u8, str, "use")) .use else Tok.Kind{ .identifier = str };
}

fn read_num(str: []const u8, placeholder: *usize, idx: *usize, read_kind: enum { bin, hex, oct }) Tok.Kind {
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
        .bin => Tok.Kind{ .bin_int = str[placeholder.* .. idx.* + 1] },
        .hex => Tok.Kind{ .hex_int = str[placeholder.* .. idx.* + 1] },
        .oct => Tok.Kind{ .oct_int = str[placeholder.* .. idx.* + 1] },
    } else Tok.Kind{ .illegal = str[placeholder .. idx + 1] };
}
