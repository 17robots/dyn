use phf::{phf_map, Map};
// tokens
#[derive(Clone, Debug)]
pub enum TokenType {
    // others
    Illegal,
    Eof,

    // literals
    Floating(f64),
    Identifier(String),
    Integer(i128),
    StringLiteral(String),
    Character(char),

    // operators
    Add,
    Sub,
    Mul,
    Div,
    Per,
    Inc,
    Dec,
    Semicolon,
    Colon,
    Comma,
    Equal,
    Eq,
    And,
    LAnd,
    Or,
    LOr,
    Not,
    Neq,
    Gt,
    Gte,
    Lt,
    Lte,
    LParen,
    LBrace,
    LBrack,
    RParen,
    RBrace,
    RBrack,
    Period,

    // keywords
    Void,
    Bool,
    Char,
    F32,
    F64,
    I8,
    I16,
    I32,
    I64,
    I128,
    U8,
    U16,
    U32,
    U64,
    U128,
    Mut,
    Con,
}

pub static KEYWORDS: Map<&str, TokenType> = phf_map! {
    "void" => TokenType::Void,
    "bool" => TokenType::Bool,
    "char" => TokenType::Char,
    "f32" => TokenType::F32,
    "f64" => TokenType::F64,
    "i8" => TokenType::I8,
    "i16" => TokenType::I16,
    "i32" => TokenType::I32,
    "i64" => TokenType::I64,
    "i128" => TokenType::I128,
    "u8" => TokenType::U8,
    "u16" => TokenType::U16,
    "u32" => TokenType::U32,
    "u64" => TokenType::U64,
    "u128" => TokenType::U128,
    "mut" => TokenType::Mut,
    "con" => TokenType::Con,
};

pub static OPERATORS: Map<&str, TokenType> = phf_map! {
    "+" => TokenType::Add,
    "-" => TokenType::Sub,
    "*" => TokenType::Mul,
    "/" => TokenType::Div,
    "%" => TokenType::Per,
    ";" => TokenType::Semicolon,
    ":" => TokenType::Colon,
    "=" => TokenType::Equal,
    "&" => TokenType::And,
    "|" => TokenType::Or,
    "!" => TokenType::Not,
    "<" => TokenType::Lt,
    ">" => TokenType::Gt,
    "(" => TokenType::LParen,
    "[" => TokenType::LBrace,
    "{" => TokenType::LBrack,
    ")" => TokenType::RParen,
    "]" => TokenType::RBrace,
    "}" => TokenType::RBrack,
};

pub static COMPOUND_OPERATORS: Map<&str, TokenType> = phf_map! {
    "--" => TokenType::Dec,
    "++" => TokenType::Inc,
    "==" => TokenType::Eq,
    "!=" => TokenType::Neq,
    ">=" => TokenType::Gte,
    "<=" => TokenType::Lte,
    "&&" => TokenType::LAnd,
    "||" => TokenType::LOr,
};

pub static SEPARATORS: Map<&str, TokenType> = phf_map! {
    ";" => TokenType::Semicolon,
    "," => TokenType::Comma,
};
