pub const Tok = struct {
    kind: Kind,
    span: Span,
    pub const Kind = union(enum) {
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
        pipeq, // |=
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
        unclosed_string: Span,
        unclosed_block_comment: Span,
        line_comment: []const u8,
        block_comment: []const u8,
        doc_comment: []const u8,
    };
    pub fn new(kind: Kind, start: u32, end: u32) Tok {
        return .{ .kind = kind, .span = Span{ .start = start, .end = end } };
    }
};
pub const Span = struct { start: u32, end: u32 };
