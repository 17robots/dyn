pub const Tok = struct {
    kind: Kind,
    span: Span,
    pub const Kind = enum {
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
        underscore, // _
        semicolon, // ;
        newline, // \n
        // literal
        int,
        float,
        string,
        char,
        identifier,
        illegal,
        unclosed_string,
        unclosed_block_comment,
        line_comment,
        block_comment,
        doc_comment,
    };
    pub fn new(kind: Kind, start: usize, end: usize) Tok {
        return .{ .kind = kind, .span = Span{ .start = start, .end = end } };
    }
};
pub const Span = struct { start: usize, end: usize };
