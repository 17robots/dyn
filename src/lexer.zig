const std = @import("std");
const Tok = @import("token.zig").Tok;

pub fn lex(alloc: std.mem.Allocator, text: []const u8) ![]Tok {
    var toks: std.ArrayList(Tok) = .empty;
    var idx = 0;
    var placeholder = 0;
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
                        else => break :blk Tok.Kind{ .float = text[placeholder..idx] },
                    };
                    break :blk Tok.Kind{ .float = text[placeholder..idx] };
                },
                else => .dot,
            } else .dot,
            '!', '~', '+', '-', '*', '%', '^', '=' => if (idx + 1 < text.len and text[idx + 1] == '=') blk: {
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
            '&' => if (idx + 1 < text.len) blk: {
                break :blk switch (text[idx + 1]) {
                    '&' => blk2: {
                        idx += 1;
                        break :blk2 .andand;
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
                        break :blk2 .lteq;
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
                        break :blk2 .gteq;
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
                        else => break :blk if (std.mem.eql(u8, text[placeholder .. idx + 1], "break")) .@"break" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "comp")) .comp else if (std.mem.eql(u8, text[placeholder .. idx + 1], "continue")) .@"continue" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "defer")) .@"defer" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "enum")) .@"enum" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "fn")) .@"fn" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "for")) .@"for" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "if")) .@"if" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "inline")) .@"inline" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "match")) .match else if (std.mem.eql(u8, text[placeholder .. idx + 1], "mut")) .mut else if (std.mem.eql(u8, text[placeholder .. idx + 1], "or")) .@"or" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "pub")) .@"pub" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "struct")) .@"struct" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "type")) .type else if (std.mem.eql(u8, text[placeholder .. idx + 1], "use")) .use else Tok.Kind{ .identifier = text[placeholder .. idx + 1] },
                    }
                }
                break :blk if (std.mem.eql(u8, text[placeholder .. idx + 1], "break")) .@"break" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "comp")) .comp else if (std.mem.eql(u8, text[placeholder .. idx + 1], "continue")) .@"continue" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "defer")) .@"defer" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "enum")) .@"enum" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "fn")) .@"fn" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "for")) .@"for" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "if")) .@"if" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "inline")) .@"inline" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "match")) .match else if (std.mem.eql(u8, text[placeholder .. idx + 1], "mut")) .mut else if (std.mem.eql(u8, text[placeholder .. idx + 1], "or")) .@"or" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "pub")) .@"pub" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "struct")) .@"struct" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "type")) .type else if (std.mem.eql(u8, text[placeholder .. idx + 1], "use")) .use else Tok.Kind{ .identifier = text[placeholder .. idx + 1] };
            },
            '_' => if (idx + 1 < text.len) switch (text[idx + 1]) {
                'a'...'z', 'A'...'Z', '$' => blk: {
                    while (idx + 1 < text.len) {
                        switch (text[idx + 1]) {
                            'a'...'z', 'A'...'Z', '_', '0'...'9' => idx += 1,
                            else => break :blk if (std.mem.eql(u8, text[placeholder .. idx + 1], "break")) .@"break" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "comp")) .comp else if (std.mem.eql(u8, text[placeholder .. idx + 1], "continue")) .@"continue" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "defer")) .@"defer" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "enum")) .@"enum" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "fn")) .@"fn" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "for")) .@"for" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "if")) .@"if" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "inline")) .@"inline" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "match")) .match else if (std.mem.eql(u8, text[placeholder .. idx + 1], "mut")) .mut else if (std.mem.eql(u8, text[placeholder .. idx + 1], "or")) .@"or" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "pub")) .@"pub" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "struct")) .@"struct" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "type")) .type else if (std.mem.eql(u8, text[placeholder .. idx + 1], "use")) .use else Tok.Kind{ .identifier = text[placeholder .. idx + 1] },
                        }
                    }
                    break :blk if (std.mem.eql(u8, text[placeholder .. idx + 1], "break")) .@"break" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "comp")) .comp else if (std.mem.eql(u8, text[placeholder .. idx + 1], "continue")) .@"continue" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "defer")) .@"defer" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "enum")) .@"enum" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "fn")) .@"fn" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "for")) .@"for" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "if")) .@"if" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "inline")) .@"inline" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "match")) .match else if (std.mem.eql(u8, text[placeholder .. idx + 1], "mut")) .mut else if (std.mem.eql(u8, text[placeholder .. idx + 1], "or")) .@"or" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "pub")) .@"pub" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "struct")) .@"struct" else if (std.mem.eql(u8, text[placeholder .. idx + 1], "type")) .type else if (std.mem.eql(u8, text[placeholder .. idx + 1], "use")) .use else Tok.Kind{ .identifier = text[placeholder .. idx + 1] };
                },
                else => .underscore,
            } else .underscore,
            // todo: validate that at least 1 number comes out from these
            '0' => if (idx + 1 < text.len) switch (text[idx + 1]) {
                'b', 'B' => blk: {
                    idx += 1;
                    while (idx + 1 < text.len) switch (text[idx + 1]) {
                        '0', '1', '_' => idx += 1,
                        else => break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] },
                    };
                    if (text[idx] == 'b' or text[idx] == 'B') {}
                    break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] };
                },
                // todo: allow for exponent decimals
                'e', 'E' => blk: {
                    idx += 1;
                    while (idx + 1 < text.len) switch (text[idx + 1]) {
                        '0'...'9', '_' => idx += 1,
                        else => break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] },
                    };
                    if (text[idx] == 'e' or text[idx] == 'E') {}
                    break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] };
                },
                'o', 'O' => blk: {
                    idx += 1;
                    while (idx + 1 < text.len) switch (text[idx + 1]) {
                        '0'...'7', '_' => idx += 1,
                        else => break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] },
                    };
                    if (text[idx] == 'o' or text[idx] == 'O') {}
                    break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] };
                },
                'x', 'X' => blk: {
                    idx += 1;
                    while (idx + 1 < text.len) switch (text[idx + 1]) {
                        '0'...'9', 'a'...'f', 'A'...'F', '_' => idx += 1,
                        else => break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] },
                    };
                    if (text[idx] == 'x' or text[idx] == 'X') {}
                    break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] };
                },
                '.' => blk: {
                    if (idx + 2 < text.len and text[idx + 2] == '.') break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] };
                    idx += 1;
                    var exponent = false;
                    while (idx + 1 < text.len) switch (text[idx + 1]) {
                        '0'...'9', '_' => idx += 1,
                        'e', 'E' => {
                            if (exponent) break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] };
                            if (text[idx] == '.') break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] };
                            exponent = true;
                            idx += 1;
                        },
                        else => break :blk if (exponent) Tok.Kind{ .int = text[placeholder .. idx + 1] } else Tok.Kind{ .float = text[placeholder .. idx + 1] },
                    };
                    break :blk if (exponent) Tok.Kind{ .int = text[placeholder .. idx + 1] } else Tok.Kind{ .float = text[placeholder .. idx + 1] };
                },
            } else Tok.Kind{ .int = text[placeholder .. idx + 1] },
            '1'...'9' => blk: {
                var decimal = false;
                var exponent = false;
                while (idx + 1 < text.len) {
                    switch (text[idx + 1]) {
                        '0'...'9' => idx += 1,
                        'e', 'E' => {
                            if (exponent) break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] };
                            exponent = true;
                            idx += 1;
                        },
                        '.' => {
                            if (exponent) break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] };
                            if (decimal) break :blk Tok.Kind{ .float = text[placeholder .. idx + 1] };
                            if (idx + 2 < text.len and text[idx + 2] == '.') break :blk Tok.Kind{ .int = text[placeholder .. idx + 1] };
                            decimal = true;
                            idx += 1;
                        },
                        else => break :blk if (exponent) Tok.Kind{ .int = text[placeholder .. idx + 1] } else if (decimal) Tok.Kind{ .float = text[placeholder .. idx + 1] } else Tok.Kind{ .int = text[placeholder .. idx + 1] },
                    }
                }
                break :blk if (decimal) Tok.Kind{ .float = text[placeholder .. idx + 1] } else Tok.Kind{ .int = text[placeholder .. idx + 1] };
            },
            '\t', ' ', '\r' => null,
            else => Tok.Kind{ .illegal = text[placeholder .. idx + 1] },
        };
        if (tok_to_add) |t| try toks.append(alloc, Tok.new(t, placeholder, idx));
        tok_to_add = null;
        idx += 1;
    }
    return try toks.toOwnedSlice(alloc);
}
