use std::{
    collections::HashMap,
    fmt::{self, Display},
    path::Path,
};

#[derive(Debug, PartialEq, Eq, Copy, Clone)]
pub enum LexingError {
    IllegalCharacter,
    UnterminatedString,
    InvalidEscapeSequence,
    UnterminatedChar,
}

#[derive(Debug, PartialEq, Clone)]
pub enum Token {
    Eof,

    // Single Character Tokens
    LeftParen,
    RightParen,
    LeftBrace,
    RightBrace,
    LeftBracket,
    RightBracket,
    Dot,
    Comma,
    Semicolon,

    // Compound Character Tokens
    Asterisk,
    AsteriskEqual,
    Percent,
    PercentEqual,
    Slash,
    SlashEqual,
    Plus,
    PlusEqual,
    Minus,
    MinusEqual,
    GreaterThan,
    LeftShift,
    LeftShiftEqual,
    GreaterThanEqual,
    LessThan,
    LessThanEqual,
    RightShift,
    RightShiftEqual,
    Equal,
    EqualEqual,
    Bang,
    BangEqual,
    And,
    AndAnd,
    AndEqual,
    Or,
    OrOr,
    OrEqual,

    // Literals,
    Identifier(String),
    Float(f64),
    Int(i128),
    String(String),
    Char(char),

    // Keywords
    Mut,
    If,
    For,
    Con,
    Match,
    True,
    False,
    Break,
    Continue,
    Defer,
    Loop,
    Enum,
    Struct,
    Pub,
}

impl Display for Token {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Token::Eof => write!(f, "end of file"),
            Token::LeftParen => write!(f, "("),
            Token::RightParen => write!(f, ")"),
            Token::LeftBrace => write!(f, "{{"),
            Token::RightBrace => write!(f, "}}"),
            Token::LeftBracket => write!(f, "["),
            Token::RightBracket => write!(f, "]"),
            Token::Dot => write!(f, "."),
            Token::Comma => write!(f, ","),
            Token::Semicolon => write!(f, ";"),
            Token::Asterisk => write!(f, "*"),
            Token::AsteriskEqual => write!(f, "*="),
            Token::Percent => write!(f, "%"),
            Token::PercentEqual => write!(f, "%="),
            Token::Slash => write!(f, "/"),
            Token::SlashEqual => write!(f, "/="),
            Token::Plus => write!(f, "+"),
            Token::PlusEqual => write!(f, "+="),
            Token::Minus => write!(f, "-"),
            Token::MinusEqual => write!(f, "-="),
            Token::GreaterThan => write!(f, ">"),
            Token::LeftShift => write!(f, "<<"),
            Token::LeftShiftEqual => write!(f, "<<="),
            Token::GreaterThanEqual => write!(f, ">="),
            Token::LessThan => write!(f, "<"),
            Token::LessThanEqual => write!(f, "<="),
            Token::RightShift => write!(f, ">>"),
            Token::RightShiftEqual => write!(f, ">>="),
            Token::Equal => write!(f, "="),
            Token::EqualEqual => write!(f, "=="),
            Token::Bang => write!(f, "!"),
            Token::BangEqual => write!(f, "!="),
            Token::And => write!(f, "&"),
            Token::AndAnd => write!(f, "&&"),
            Token::AndEqual => write!(f, "&="),
            Token::Or => write!(f, "|"),
            Token::OrOr => write!(f, "||"),
            Token::OrEqual => write!(f, "|="),
            Token::Identifier(_) => write!(f, "identifier"),
            Token::Float(_) => write!(f, "float"),
            Token::Int(_) => write!(f, "int"),
            Token::String(_) => write!(f, "string"),
            Token::Char(_) => write!(f, "char"),
            Token::Mut => write!(f, "mut"),
            Token::If => write!(f, "if"),
            Token::For => write!(f, "for"),
            Token::Con => write!(f, "con"),
            Token::Match => write!(f, "match"),
            Token::True => write!(f, "true"),
            Token::False => write!(f, "false"),
            Token::Break => write!(f, "break"),
            Token::Continue => write!(f, "continue"),
            Token::Defer => write!(f, "defer"),
            Token::Loop => write!(f, "loop"),
            Token::Enum => write!(f, "enum"),
            Token::Struct => write!(f, "struct"),
            Token::Pub => write!(f, "pub"),
        }
    }
}
impl Display for LexingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            LexingError::IllegalCharacter => write!(f, "Lexing error: Illegal character"),
            LexingError::UnterminatedString => {
                write!(f, "Lexing error: Unterminated string literal")
            }
            LexingError::UnterminatedChar => write!(f, "Lexing error: Unterminated char literal"),
            LexingError::InvalidEscapeSequence => {
                write!(f, "Lexing error: Invalid escape sequence")
            }
        }
    }
}

pub struct Lexer<'cache, 'contents> {
    curr: usize,
    filename: &'cache Path,
    source: &'contents str,
    start: usize,
    line: usize,
    pub toks: Vec<Result<Token, LexingError>>,
}
impl<'cache, 'contents> Lexer<'cache, 'contents> {
    pub fn new(filename: &'cache Path, source: &'contents str) -> Lexer<'cache, 'contents> {
        Lexer {
            curr: 0,
            filename,
            source,
            start: 0,
            line: 0,
            toks: vec![],
        }
    }
    pub fn scan_toks(&mut self) -> Result<(), LexingError> {
        while !self.is_end() {
            self.start = self.curr;
            self.scan_token();
        }
        self.toks.push(Ok(Token::Eof));
        Ok(())
    }
    fn is_end(&mut self) -> bool {
        self.curr >= self.source.len()
    }
    fn scan_token(&mut self) {
        let c = self.advance();
        match c {
            // single character tokens
            '(' => self.toks.push(Ok(Token::LeftParen)),
            ')' => self.toks.push(Ok(Token::RightParen)),
            '[' => self.toks.push(Ok(Token::LeftBracket)),
            ']' => self.toks.push(Ok(Token::RightBracket)),
            '{' => self.toks.push(Ok(Token::LeftBrace)),
            '}' => self.toks.push(Ok(Token::RightBrace)),
            '.' => self.toks.push(Ok(Token::Dot)),
            ',' => self.toks.push(Ok(Token::Comma)),
            ';' => self.toks.push(Ok(Token::Semicolon)),
            // compound character tokens
            '*' => {
                let value = if self.matches('=') {
                    Token::AsteriskEqual
                } else {
                    Token::Asterisk
                };
                self.toks.push(Ok(value))
            }
            '%' => {
                let value = if self.matches('=') {
                    Token::PercentEqual
                } else {
                    Token::Percent
                };
                self.toks.push(Ok(value))
            }
            '/' => {
                if self.matches('/') {
                    while self.peek() != '\n' && !self.is_end() {
                        self.advance();
                    }
                    return;
                }
                let value = if self.matches('=') {
                    Token::SlashEqual
                } else {
                    Token::Slash
                };
                self.toks.push(Ok(value))
            }
            '+' => {
                let value = if self.matches('=') {
                    Token::PlusEqual
                } else {
                    Token::Plus
                };
                self.toks.push(Ok(value))
            }
            '-' => {
                let value = if self.matches('=') {
                    Token::MinusEqual
                } else {
                    Token::Minus
                };
                self.toks.push(Ok(value))
            }
            '>' => {
                let value = if self.matches('=') {
                    Token::GreaterThanEqual
                } else if self.matches('>') {
                    if self.matches('=') {
                        Token::RightShiftEqual
                    } else {
                        Token::RightShift
                    }
                } else {
                    Token::GreaterThan
                };
                self.toks.push(Ok(value))
            }
            '<' => {
                let value = if self.matches('=') {
                    Token::LessThanEqual
                } else if self.matches('<') {
                    if self.matches('=') {
                        Token::LeftShiftEqual
                    } else {
                        Token::LeftShift
                    }
                } else {
                    Token::LessThan
                };
                self.toks.push(Ok(value))
            }
            '=' => {
                let value = if self.matches('=') {
                    Token::EqualEqual
                } else {
                    Token::Equal
                };
                self.toks.push(Ok(value))
            }
            '!' => {
                let value = if self.matches('=') {
                    Token::BangEqual
                } else {
                    Token::Bang
                };
                self.toks.push(Ok(value))
            }
            '&' => {
                let value = if self.matches('=') {
                    Token::AndEqual
                } else if self.matches('&') {
                    Token::AndAnd
                } else {
                    Token::And
                };
                self.toks.push(Ok(value))
            }
            '|' => {
                let value = if self.matches('=') {
                    Token::OrEqual
                } else if self.matches('|') {
                    Token::OrOr
                } else {
                    Token::Or
                };
                self.toks.push(Ok(value))
            }
            ' ' | '\r' | '\t' => {}
            '\n' => self.line += 1,
            '"' => self.string(),
            '\'' => self.char(),
            _ => {
                if c.is_ascii_digit() {
                    self.number()
                } else if c.is_alphabetic() {
                    self.identifier()
                } else {
                    self.toks.push(Err(LexingError::IllegalCharacter));
                }
            }
        }
    }
    fn advance(&mut self) -> char {
        self.curr += 1;
        self.source.chars().nth(self.curr - 1).unwrap()
    }
    fn matches(&mut self, expected: char) -> bool {
        if self.is_end() {
            return false;
        }
        if self.source.chars().nth(self.curr).unwrap() != expected {
            return false;
        }
        self.curr += 1;
        true
    }
    fn peek(&mut self) -> char {
        if self.is_end() {
            return '\0';
        }
        self.source.chars().nth(self.curr).unwrap()
    }
    fn peek_next(&mut self) -> char {
        if self.curr + 1 >= self.source.len() {
            return '\0';
        }
        self.source.chars().nth(self.curr + 1).unwrap()
    }
    fn string(&mut self) {
        self.start = self.curr;
        while self.peek() != '"' && !self.is_end() {
            if self.peek() == '\n' {
                self.line += 1;
            }
            self.advance();
        }
        if self.is_end() {
            self.toks.push(Err(LexingError::UnterminatedString))
        }
        self.advance();
        let value = &self.source[self.start + 1..self.curr - 1].to_string();
        self.toks.push(Ok(Token::String(value.to_string())));
    }
    fn char(&mut self) {
        self.start = self.curr;
        self.advance(); // lets move to the char
        while self.peek() != '\'' && !self.is_end() {
            if self.peek() == '\n' {
                self.line += 1;
            }
            self.advance();
        }
        if self.is_end() {
            self.toks.push(Err(LexingError::UnterminatedChar))
        }
        self.advance();
        let value = &self.source[self.start + 1..self.curr - 1].to_string();
        self.toks.push(Ok(Token::String(value.to_string())));
    }
    fn escape(&mut self) {}
    fn number(&mut self) {
        while self.peek().is_ascii_digit() {
            self.advance();
        }
        if self.peek() == '.' && self.peek_next().is_ascii_digit() {
            self.advance();
            while self.peek().is_ascii_digit() {
                self.advance();
            }
        }
        let value = &self.source[self.start + 1..self.curr - 1].to_string();
        self.toks.push(if value.parse::<i128>().is_err() {
            Ok(Token::Float(value.parse::<f64>().unwrap()))
        } else {
            Ok(Token::Int(value.parse::<i128>().unwrap()))
        });
    }
    fn identifier(&mut self) {
        while self.peek().is_alphanumeric() {
            self.advance();
        }
        let value = &self.source[self.start + 1..self.curr - 1].to_string();
        let kw = self.get_keyword(value.to_string());
        self.toks.push(if let Some(x) = kw {
            Ok(x)
        } else {
            Ok(Token::Identifier(value.to_string()))
        });
    }
    fn get_keyword(&mut self, word: String) -> Option<Token> {
        let keywords = HashMap::from([
            ("mut", Token::Mut),
            ("if", Token::If),
            ("for", Token::For),
            ("con", Token::Con),
            ("match", Token::Match),
            ("true", Token::True),
            ("false", Token::False),
            ("break", Token::Break),
            ("continue", Token::Continue),
            ("defer", Token::Defer),
            ("loop", Token::Loop),
            ("enum", Token::Enum),
            ("struct", Token::Struct),
            ("pub", Token::Pub),
        ]);
        keywords.get(word.as_str()).cloned()
    }
}
