use std::fmt::{self, Display};
use std::{collections::HashMap, path::Path};

use crate::error::LexingError;

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
    Colon,

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
    Void,
    Return,
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
            Token::Colon => write!(f, ":"),
            Token::Identifier(s) => write!(f, "identifier ({})", s),
            Token::Float(s) => write!(f, "float ({})", s),
            Token::Int(s) => write!(f, "int ({})", s),
            Token::String(s) => write!(f, "string ({})", s),
            Token::Char(s) => write!(f, "char ({})", s),
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
            Token::Void => write!(f, "void"),
            Token::Return => write!(f, "return"),
        }
    }
}

pub struct Lexer<'cache, 'contents> {
    curr: usize,
    pub filename: &'cache Path,
    source: &'contents str,
    start: usize,
    line: usize,
    col: usize,
    pub toks: Vec<Token>,
    pub errs: Vec<LexingError>,
}
impl<'cache, 'contents> Lexer<'cache, 'contents> {
    pub fn new(filename: &'cache Path, source: &'contents str) -> Lexer<'cache, 'contents> {
        Lexer {
            curr: 0,
            filename,
            source,
            start: 0,
            line: 1,
            col: 1,
            toks: vec![],
            errs: vec![],
        }
    }
    pub fn scan_toks(&mut self) {
        while !self.is_end() {
            self.start = self.curr;
            self.scan_token();
            if self.errs.len() > 0 {
                break;
            }
        }
        self.toks.push(Token::Eof);
    }
    fn is_end(&mut self) -> bool {
        self.curr >= self.source.len()
    }
    fn scan_token(&mut self) {
        let c = self.advance().unwrap();
        match c {
            // single character tokens
            '(' => self.toks.push(Token::LeftParen),
            ')' => self.toks.push(Token::RightParen),
            '[' => self.toks.push(Token::LeftBracket),
            ']' => self.toks.push(Token::RightBracket),
            '{' => self.toks.push(Token::LeftBrace),
            '}' => self.toks.push(Token::RightBrace),
            '.' => self.toks.push(Token::Dot),
            ',' => self.toks.push(Token::Comma),
            ';' => self.toks.push(Token::Semicolon),
            // compound character tokens
            '*' => {
                let value = if self.matches('=') {
                    Token::AsteriskEqual
                } else {
                    Token::Asterisk
                };
                self.toks.push(value)
            }
            '%' => {
                let value = if self.matches('=') {
                    Token::PercentEqual
                } else {
                    Token::Percent
                };
                self.toks.push(value)
            }
            '/' => {
                if self.matches('/') {
                    while self.peek() != '\n' && !self.is_end() {
                        self.advance();
                    }
                    return;
                }
                if self.matches('*') {
                    self.multi_line_comment();
                }
                let value = if self.matches('=') {
                    Token::SlashEqual
                } else {
                    Token::Slash
                };
                self.toks.push(value)
            }
            '+' => {
                let value = if self.matches('=') {
                    Token::PlusEqual
                } else {
                    Token::Plus
                };
                self.toks.push(value)
            }
            '-' => {
                let value = if self.matches('=') {
                    Token::MinusEqual
                } else {
                    Token::Minus
                };
                self.toks.push(value)
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
                self.toks.push(value)
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
                self.toks.push(value)
            }
            '=' => {
                let value = if self.matches('=') {
                    Token::EqualEqual
                } else {
                    Token::Equal
                };
                self.toks.push(value)
            }
            '!' => {
                let value = if self.matches('=') {
                    Token::BangEqual
                } else {
                    Token::Bang
                };
                self.toks.push(value)
            }
            '&' => {
                let value = if self.matches('=') {
                    Token::AndEqual
                } else if self.matches('&') {
                    Token::AndAnd
                } else {
                    Token::And
                };
                self.toks.push(value)
            }
            '|' => {
                let value = if self.matches('=') {
                    Token::OrEqual
                } else if self.matches('|') {
                    Token::OrOr
                } else {
                    Token::Or
                };
                self.toks.push(value)
            }
            ':' => self.toks.push(Token::Colon),
            ' ' | '\r' | '\t' | '\n' => {}
            '"' => self.string(),
            '\'' => self.char(),
            _ => {
                if c.is_ascii_digit() {
                    self.number()
                } else if c.is_alphabetic() || c == '_' {
                    self.identifier()
                } else {
                    self.errs.push(LexingError::IllegalCharacter(
                        self.filename.to_str().unwrap().to_owned(),
                        self.line,
                        self.col,
                    ));
                }
            }
        }
    }
    fn advance(&mut self) -> Option<char> {
        self.curr += 1;
        if self.peek() == '\n' {
            self.col = 0;
            self.line += 1;
        } else {
            self.col += 1;
        }
        self.source.chars().nth(self.curr - 1)
    }
    fn matches(&mut self, expected: char) -> bool {
        if self.is_end() {
            return false;
        }
        if self.source.chars().nth(self.curr).unwrap() != expected {
            return false;
        }
        self.advance();
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
        let start_col = self.col;
        let start_line = self.line;
        while self.peek() != '"' && !self.is_end() {
            self.advance();
        }
        if self.is_end() {
            self.errs.push(LexingError::UnterminatedString(
                self.filename.as_os_str().to_str().unwrap().to_owned(),
                start_line,
                start_col - 1,
            ))
        }
        self.advance();
        let value = &self.source[self.start..self.curr - 1].to_string();
        self.toks.push(Token::String(value.to_string()));
    }
    fn char(&mut self) {
        self.start = self.curr;
        let start_col = self.col;
        let start_line = self.line;
        while self.peek() != '\'' && !self.is_end() {
            self.advance();
        }
        if self.is_end() {
            self.errs.push(LexingError::UnterminatedChar(
                self.filename.as_os_str().to_str().unwrap().to_owned(),
                start_line,
                start_col,
            ))
        }
        self.advance();
        let value = &self.source[self.start..self.curr - 1].to_string();
        println!("value {}", value);
        if value.len() > 1 {
            self.errs.push(LexingError::InvalidChar(
                self.filename.as_os_str().to_str().unwrap().to_owned(),
                self.line,
                self.col,
            ));
        } else {
            self.toks.push(Token::Char(value.chars().nth(0).unwrap()));
        }
    }
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
        let value =
            &self.source[self.start..(self.curr + (self.start == self.curr) as usize)].to_string();
        self.toks.push(if value.parse::<i128>().is_err() {
            Token::Float(value.parse::<f64>().unwrap())
        } else {
            Token::Int(value.parse::<i128>().unwrap())
        });
    }
    fn identifier(&mut self) {
        while self.peek().is_alphanumeric() || self.peek() == '_' {
            self.advance();
        }
        let value = &self.source[self.start..self.curr].to_string();
        let kw = self.get_keyword(value.to_string());
        self.toks.push(if let Some(x) = kw {
            x
        } else {
            Token::Identifier(value.to_string())
        });
    }
    fn multi_line_comment(&mut self) {
        loop {
            if self.matches('*') {
                if self.matches('/') {
                    break;
                }
            }
            self.advance();
        }
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
            ("void", Token::Void),
        ]);
        keywords.get(word.as_str()).cloned()
    }
}
