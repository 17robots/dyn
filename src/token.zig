const FileId = @import("source.zig").FileId;
const SourceLocation = @import("source.zig").SourceLocation;
pub const Token = struct {
    tok_type: TokenType,
    loc: SourceLocation,
    val: ?[]const u8 = null,
    pub fn init(tok: TokenType, file_id: FileId, index: u32, val: ?[]const u8) Token {
        return Token{ .tok_type = tok, .loc = SourceLocation{ .file_id = file_id, .index = index }, .val = val };
    }
};
pub const Span = struct {
    start: u32,
    end: u32,
    pub fn from(start: u32, end: u32) Span { return .{ .start = start, .end = end }; }
    pub fn from(a: Span, b: Span) Span { return .{ .start = a.start, .end = b.end }; }
};

pub const TokenType = enum {
    eof,
    invalid,
    // literals
    identifier,
    int,
    float,
    string,
    char,
    // operators
    add, // +
    sub, // -
    mul, // *
    div, // /
    mod, // %
    @"and", // &
    @"or", // |
    xor, // ^
    flip, // ~
    eq, // =
    addeq, // +=
    addadd, // ++
    subeq, // -=
    subsub, // --
    muleq, // *=
    diveq, // /=
    modeq, // %=
    andeq, // &=
    oreq, // |=
    xoreq, // ^=
    flipeq, // ~=
    andand, // &&
    oror, // ||
    eqeq, // ==
    gt, // >
    lt, // <
    gteq, // >=
    lteq, // <=
    lparen, // (
    rparen, // )
    lbrack, // [
    rbrack, // ]
    lbrace, // {
    rbrace, // }
    dot, // .
    dotdot, // ..
    colon, // :
    semicolon, // ;
    underscore, // _
    comma, // ,
    arrow, // =>
    bang, // !
    bangeq, // !=
    question, // ?
    dollar, // $
    walrus, // :=
    nullish, // ??
    // keywords
    module,
    pointer_deref,
    optional_deref,
    use,
    mut,
    true,
    false,
    @"if",
    @"else",
    match,
    @"defer",
    @"while",
    @"for",
    @"enum",
    @"error",
    @"try",
    @"catch",
    @"struct",
    @"packed",
    type,
    comp,
    @"pub",
    null,
    undefined,
    @"return",
    @"break",
    @"inline",
    @"continue",
    @"fn",
};
