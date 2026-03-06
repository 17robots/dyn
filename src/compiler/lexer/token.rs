use crate::compiler::diagnostics::SourceSpan;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Token {
    pub kind: TokenKind,
    pub lexeme: String,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TokenKind {
    Identifier,
    BuiltinIdentifier,
    IntLiteral,
    FloatLiteral,
    StringLiteral,
    CharLiteral,
    BoolLiteral(bool),
    NullLiteral,
    DocComment,
    Keyword(Keyword),
    Operator(Operator),
    Delimiter(Delimiter),
    Eof,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash)]
pub enum Keyword {
    Module,
    Pub,
    Mut,
    Use,
    Struct,
    Enum,
    If,
    Else,
    Match,
    For,
    Break,
    Continue,
    Return,
    Defer,
    Inline,
    Comp,
    Or,
    Type,
}

pub const KEYWORDS: &[(&str, Keyword)] = &[
    ("module", Keyword::Module),
    ("pub", Keyword::Pub),
    ("mut", Keyword::Mut),
    ("use", Keyword::Use),
    ("struct", Keyword::Struct),
    ("enum", Keyword::Enum),
    ("if", Keyword::If),
    ("else", Keyword::Else),
    ("match", Keyword::Match),
    ("for", Keyword::For),
    ("break", Keyword::Break),
    ("continue", Keyword::Continue),
    ("return", Keyword::Return),
    ("defer", Keyword::Defer),
    ("inline", Keyword::Inline),
    ("comp", Keyword::Comp),
    ("or", Keyword::Or),
    ("type", Keyword::Type),
];

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash)]
pub enum Operator {
    Dot,
    DotDot,
    DotDotEq,
    DotStar,
    DotBang,
    DotQuestion,
    Colon,
    Equal,
    FatArrow,
    Plus,
    Minus,
    Star,
    Slash,
    Percent,
    PlusEqual,
    MinusEqual,
    StarEqual,
    SlashEqual,
    PercentEqual,
    EqualEqual,
    BangEqual,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    AndAnd,
    OrOr,
    Bang,
    Ampersand,
    Pipe,
    Caret,
    Tilde,
    LeftShift,
    RightShift,
    AmpersandEqual,
    PipeEqual,
    CaretEqual,
    LeftShiftEqual,
    RightShiftEqual,
    Question,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash)]
pub enum Delimiter {
    LParen,
    RParen,
    LBrace,
    RBrace,
    LBracket,
    RBracket,
    Comma,
    Semicolon,
}

pub const NUMERIC_RULES: &[&str] = &[
    "Integer prefixes: 0b, 0o, 0x, and decimal without prefix",
    "Decimal floats support exponent markers e/E",
    "Hex floats use p/P exponent markers and require p/P when fractional",
    "Underscores are allowed only between digits",
    "Range operators .. and ..= must win over float-dot ambiguity",
    "The pair ':' and '=' are always separate tokens",
    "Invalid numbers emit diagnostics and lexer recovers by consuming full malformed span",
];

pub fn keyword_from_identifier(identifier: &str) -> Option<TokenKind> {
    if identifier == "true" {
        return Some(TokenKind::BoolLiteral(true));
    }

    if identifier == "false" {
        return Some(TokenKind::BoolLiteral(false));
    }

    if identifier == "null" {
        return Some(TokenKind::NullLiteral);
    }

    KEYWORDS
        .iter()
        .find_map(|(word, keyword)| (*word == identifier).then_some(TokenKind::Keyword(*keyword)))
}
