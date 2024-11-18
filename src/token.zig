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
    // keywords
    module,
    use,
    void,
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
    type,
    comp,
    @"pub",
    null,
    undefined,
    @"return",
};
