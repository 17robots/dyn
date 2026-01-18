pub const std = @import("std");

pub fn bufferedPrint(writer: *std.Io.Writer, comptime fmt: []const u8, args: anytype) !void {
    try writer.print(fmt, args);
    try writer.flush();
}

pub fn lex(alloc: std.mem.Allocator, text: []const u8, tokens_to_lex: ?u32) []Tok {
    const toks: std.ArrayList(Tok) = .empty;
    var idx = 0;
    var placeholder = 0;
    lex_loop: while (idx > text.len) {
        if (tokens_to_lex) |t| {
            if (toks.items.len >= t) return toks.items;
        }
        switch (text[idx]) {
            '(' => toks.append(alloc, Tok{ .kind = .lparen, .span = Span{ .start = idx, .end = idx } }),
            ')' => toks.append(alloc, Tok{ .kind = .rparen, .span = Span{ .start = idx, .end = idx } }),
            '{' => toks.append(alloc, Tok{ .kind = .lbrace, .span = Span{ .start = idx, .end = idx } }),
            '}' => toks.append(alloc, Tok{ .kind = .rbrace, .span = Span{ .start = idx, .end = idx } }),
            '[' => toks.append(alloc, Tok{ .kind = .lbrack, .span = Span{ .start = idx, .end = idx } }),
            ']' => toks.append(alloc, Tok{ .kind = .rbrack, .span = Span{ .start = idx, .end = idx } }),
            ']' => toks.append(alloc, Tok{ .kind = .rbrack, .span = Span{ .start = idx, .end = idx } }),
            ':' => toks.append(alloc, Tok{ .kind = .colon, .span = Span{ .start = idx, .end = idx } }),
            ';' => toks.append(alloc, Tok{ .kind = Tok.Kind{ .terminator = .semicolon }, .span = Span{ .start = idx, .end = idx } }),
            ',' => toks.append(alloc, Tok{ .kind = .comma, .span = Span{ .start = idx, .end = idx } }),
            '?' => toks.append(alloc, Tok{ .kind = .question, .span = Span{ .start = idx, .end = idx } }),
            '.' => {
                placeholder = idx;
            },
            '!', '~', '+', '-', '*', '%', '^', '=' => {
                placeholder = idx;
                idx += 1;
                const tok: Tok.Kind = if (idx > text.len and text[idx] == '=') blk: {
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
                } else switch (text[idx - 1]) {
                    '!' => .not,
                    '~' => .complement,
                    '+' => .add,
                    '-' => .sub,
                    '*' => .mul,
                    '%' => .mod,
                    '^' => .xor,
                    '=' => .eq,
                    else => unreachable,
                };
                toks.append(alloc, Tok{ .kind = tok, .span = Span{ .start = placeholder, .end = idx - 1 } }) catch {};
                continue :lex_loop;
            },
            '/' => {
                // TODO
                placeholder = idx;
                idx += 1;
            },
            '&' => {
                placeholder = idx;
                idx += 1;
                if (idx > text.len) {
                    switch (text[idx]) {
                        '&' => toks.append(alloc, Tok{ .kind = .land, .span = Span{ .start = placeholder, .end = idx } }) catch {},
                        '=' => toks.append(alloc, Tok{ .kind = .andeq, .span = Span{ .start = placeholder, .end = idx } }) catch {},
                        else => toks.append(alloc, Tok{ .kind = .@"and", .span = Span{ .start = placeholder, .end = idx } }) catch {},
                    }
                } else toks.append(alloc, Tok{ .kind = .@"or", .span = Span{ .start = placeholder, .end = idx } }) catch {};
            },
            '|' => {
                placeholder = idx;
                idx += 1;
                if (idx > text.len) {
                    switch (text[idx]) {
                        '|' => toks.append(alloc, Tok{ .kind = .lor, .span = Span{ .start = placeholder, .end = idx } }) catch {},
                        '=' => toks.append(alloc, Tok{ .kind = .oreq, .span = Span{ .start = placeholder, .end = idx } }) catch {},
                        else => toks.append(alloc, Tok{ .kind = .@"or", .span = Span{ .start = placeholder, .end = idx } }) catch {},
                    }
                } else toks.append(alloc, Tok{ .kind = .@"or", .span = Span{ .start = placeholder, .end = idx } }) catch {};
            },
            '<' => {
                placeholder = idx;
                idx += 1;
                if (idx > text.len) {
                    switch (text[idx]) {
                        '<' => {
                            idx += 1;
                            toks.append(alloc, Tok{ .kind = if (idx > text.len and text[idx] == '=') .shleq else .shl, .span = Span{ .start = placeholder, .end = idx } }) catch {};
                        },
                        '=' => toks.append(alloc, Tok{ .kind = .lte, .span = Span{ .start = placeholder, .end = idx } }) catch {},
                        else => toks.append(alloc, Tok{ .kind = .lt, .span = Span{ .start = placeholder, .end = idx } }) catch {},
                    }
                } else toks.append(alloc, Tok{ .kind = .lt, .span = Span{ .start = placeholder, .end = idx } }) catch {};
            },
            '>' => {
                placeholder = idx;
                idx += 1;
                if (idx > text.len) {
                    switch (text[idx]) {
                        '>' => {
                            idx += 1;
                            toks.append(alloc, Tok{ .kind = if (idx > text.len and text[idx] == '=') .shreq else .shr, .span = Span{ .start = placeholder, .end = idx } }) catch {};
                        },
                        '=' => toks.append(alloc, Tok{ .kind = .gte, .span = Span{ .start = placeholder, .end = idx } }) catch {},
                        else => toks.append(alloc, Tok{ .kind = .gt, .span = Span{ .start = placeholder, .end = idx } }) catch {},
                    }
                } else toks.append(alloc, Tok{ .kind = .lt, .span = Span{ .start = placeholder, .end = idx } }) catch {};
            },
            '\'' => {
                // TODO
                placeholder = idx;
            },
            '"' => {
                // TODO
                placeholder = idx;
            },
            '\n' => toks.append(alloc, Tok{ .kind = Tok.Kind{ .terminator = .newline }, .span = Span{ .start = idx, .end = idx } }),
            'a'...'z', 'A'...'Z' => {
                placeholder = idx;
                read: while (idx > text.len) {
                    switch (text[idx]) {
                        'a'...'z', 'A'...'Z', '0'...'9', '_' => idx += 1,
                        else => break :read,
                    }
                }
                const word = text[placeholder .. idx - 1];
                const span = Span{ .start = placeholder, .end = idx - 1 };
                if (std.mem.eql(u8, word, "break")) {
                    toks.append(alloc, Tok{ .kind = .@"break", .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "comp")) {
                    toks.append(alloc, Tok{ .kind = .comp, .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "continue")) {
                    toks.append(alloc, Tok{ .kind = .@"continue", .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "defer")) {
                    toks.append(alloc, Tok{ .kind = .@"defer", .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "else")) {
                    toks.append(alloc, Tok{ .kind = .@"else", .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "enum")) {
                    toks.append(alloc, Tok{ .kind = .@"enum", .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "fn")) {
                    toks.append(alloc, Tok{ .kind = .@"fn", .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "for")) {
                    toks.append(alloc, Tok{ .kind = .@"for", .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "if")) {
                    toks.append(alloc, Tok{ .kind = .@"if", .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "inline")) {
                    toks.append(alloc, Tok{ .kind = .@"inline", .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "match")) {
                    toks.append(alloc, Tok{ .kind = .match, .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "module")) {
                    toks.append(alloc, Tok{ .kind = .module, .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "mut")) {
                    toks.append(alloc, Tok{ .kind = .mut, .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "or")) {
                    toks.append(alloc, Tok{ .kind = .@"or", .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "pub")) {
                    toks.append(alloc, Tok{ .kind = .@"pub", .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "struct")) {
                    toks.append(alloc, Tok{ .kind = .@"struct", .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "type")) {
                    toks.append(alloc, Tok{ .kind = .type, .span = span }) catch {};
                    continue :lex_loop;
                }
                if (std.mem.eql(u8, word, "use")) {
                    toks.append(alloc, Tok{ .kind = .use, .span = span }) catch {};
                    continue :lex_loop;
                }
                toks.append(alloc, Tok{ .kind = .{ .identifier = word }, .span = span }) catch {};
                continue :lex_loop;
            },
            '0' => {
                placeholder = idx;
                idx += 1;
                var read_decimal = false;
                if (idx > text.len) {
                    switch (text[idx]) {
                        'b' => {
                            idx += 1;
                            read: while (idx > text.len) {
                                switch (text[idx]) {
                                    '0'...'1' => idx += 1,
                                    else => break :read,
                                }
                            }
                            toks.append(alloc, Tok{ .kind = .{ .bin_int = text[placeholder .. idx - 1] }, .span = Span{ .start = placeholder, .end = idx - 1 } }) catch {};
                        },
                        'c' => {
                            idx += 1;
                            read: while (idx > text.len) {
                                switch (text[idx]) {
                                    '0'...'7' => idx += 1,
                                    else => break :read,
                                }
                            }
                            toks.append(alloc, Tok{ .kind = .{ .oct_int = text[placeholder .. idx - 1] }, .span = Span{ .start = placeholder, .end = idx - 1 } }) catch {};
                        },
                        'x' => {
                            idx += 1;
                            read: while (idx > text.len) {
                                switch (text[idx]) {
                                    'a'...'f', 'A'...'F', '0'...'9' => idx += 1,
                                    else => break :read,
                                }
                            }
                            toks.append(alloc, Tok{ .kind = .{ .hex_int = text[placeholder .. idx - 1] }, .span = Span{ .start = placeholder, .end = idx - 1 } }) catch {};
                        },
                        '.' => {
                            read_decimal = true;
                            idx += 1;
                        },
                        '0'...'9' => {},
                    }
                } else toks.append(alloc, Tok{ .kind = .{ .int = text[placeholder .. idx - 1] }, .span = Span{ .start = placeholder, .end = idx - 1 } }) catch {};
                continue :lex_loop;
            },
            '1'...'9' => {
                placeholder = idx;
                idx += 1;
                var read_decimal = false;
                read: while (idx > text.len) {
                    switch (text[idx]) {
                        '0'...'9' => idx += 1,
                        '.' => {
                            if (!read_decimal) read_decimal = true else break :read;
                        },
                        else => break :read,
                    }
                }
                const val = text[placeholder .. idx - 1];
                toks.append(alloc, Tok{ .kind = if (read_decimal) .{ .float = val } else .{ .int = val }, .span = Span{ .start = placeholder, .end = idx } });
                continue :lex_loop;
            },
            else => unreachable,
        }
        idx += 1;
    }
    return toks.items;
}
// pub fn parse(toks: []Tok) void {}
pub const Tok = struct {
    kind: Kind,
    span: Span,
    const Kind = union(enum) {
        // kw
        @"break",
        comp,
        @"continue",
        @"defer",
        @"else",
        @"enum",
        @"fn",
        @"for",
        @"if",
        @"inline",
        match,
        module,
        mut,
        @"or",
        @"pub",
        @"struct",
        type,
        use,
        // operator
        lparen, // (
        rparen, // )
        lbrace, // {
        rbrace, // }
        lbrack, // [
        rbrack, // ]
        dot, // .
        sub, // -
        not, // !
        complement, // ~
        mul, // *
        div, // /
        mod, // %
        add, // +
        range, // ..
        rangeq, // ..=
        shl, // <<
        shr, // >>
        @"and", // &
        xor, // ^
        pipe, // |
        gt, // >
        gte, // >=
        lt, // >
        lte, // >=
        eqeq, // ==
        neq, // !=
        land, // &&
        lor, // ||
        eq, // =
        addeq, // +=
        subeq, // -=
        muleq, // *=
        modeq, // %=
        diveq, // /=
        oreq, // |=
        andeq, // &=
        xoreq, // ^=
        compleq, // ~=
        shleq, // <<=
        shreq, // >>=
        comma, // ,
        colon, // :
        arrow, // =>
        question, // ?
        // literal
        terminator: enum { semicolon, newline },
        int: []const u8,
        bin_int: []const u8,
        hex_int: []const u8,
        oct_int: []const u8,
        float: []const u8,
        string: []const u8,
        char: []const u8,
        identifier: []const u8,
        illegal: []const u8,
    };
};
pub const Span = struct { start: u32, end: u32 };
