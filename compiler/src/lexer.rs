// doing this again to see if this is better

use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct Location {
    line: usize,
    start: usize,
    end: usize,
    file_name: String,
}

#[derive(Debug, Clone)]
pub enum Token {
    Illegal(Location),
    EOF,

    // Single Character Tokens
    LeftParen(Location),
    RightParen(Location),
    LeftBrace(Location),
    RightBrace(Location),
    LeftBracket(Location),
    RightBracket(Location),
    Dot(Location),
    Comma(Location),
    Semicolon(Location),

    // Compound Character Tokens
    Asterisk(Location),
    AsteriskEqual(Location),
    Percent(Location),
    PercentEqual(Location),
    Slash(Location),
    SlashEqual(Location),
    Plus(Location),
    PlusEqual(Location),
    Minus(Location),
    MinusEqual(Location),
    GreaterThan(Location),
    GreaterThanEqual(Location),
    LessThan(Location),
    LessThanEqual(Location),
    Equal(Location),
    EqualEqual(Location),
    Bang(Location),
    BangEqual(Location),

    // Literals,
    Identifier(Location, String),
    Float(Location, f64),
    Int(Location, i128),
    String(Location, String),
    Char(Location, char),

    // Keywords
    Mut(Location),
    If(Location),
    For(Location),
    Con(Location),
    Match(Location),
    True(Location),
    False(Location),
    Break(Location),
    Continue(Location),
    Defer(Location),
    Loop(Location),
    Enum(Location),
    Struct(Location),
    Pub(Location),
}

#[derive(Debug)]
pub enum ScannerError {
    None,
    UnterminatedString,
}

#[derive(Debug)]
pub struct Scanner {
    pub source: String,
    pub toks: Vec<Result<Token, ScannerError>>,
    pub file_name: String,
    pub start: usize,
    pub current: usize,
    pub line: usize,
}

impl Scanner {
    pub fn new(file_name: &String, source: &String) -> Self {
        Self {
            source: source.to_string(),
            toks: vec![],
            file_name: file_name.to_string(),
            start: 0,
            current: 0,
            line: 0,
        }
    }
    pub fn scan_toks(&mut self) -> Result<(), ScannerError> {
        while !self.is_end() {
            self.start = self.current;
            self.scan_token();
        }
        self.toks.push(Ok(Token::EOF));
        Ok(())
    }
    fn is_end(&mut self) -> bool {
        self.current >= self.source.len()
    }
    fn scan_token(&mut self) {
        let l = self.get_location();
        let c = self.advance();
        match c {
            // single character tokens
            '(' => self.toks.push(Ok(Token::LeftParen(l))),
            ')' => self.toks.push(Ok(Token::RightParen(l))),
            '[' => self.toks.push(Ok(Token::LeftBracket(l))),
            ']' => self.toks.push(Ok(Token::RightBracket(l))),
            '{' => self.toks.push(Ok(Token::LeftBrace(l))),
            '}' => self.toks.push(Ok(Token::RightBrace(l))),
            '.' => self.toks.push(Ok(Token::Dot(l))),
            ',' => self.toks.push(Ok(Token::Comma(l))),
            ';' => self.toks.push(Ok(Token::Semicolon(l))),
            // compound character tokens
            '*' => {
                let value = if self.matches('=') {
                    Token::AsteriskEqual(l)
                } else {
                    Token::Asterisk(l)
                };
                self.toks.push(Ok(value))
            }
            '%' => {
                let value = if self.matches('=') {
                    Token::PercentEqual(l)
                } else {
                    Token::Percent(l)
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
                    Token::SlashEqual(l)
                } else {
                    Token::Slash(l)
                };
                self.toks.push(Ok(value))
            }
            '+' => {
                let value = if self.matches('=') {
                    Token::PlusEqual(l)
                } else {
                    Token::Plus(l)
                };
                self.toks.push(Ok(value))
            }
            '-' => {
                let value = if self.matches('=') {
                    Token::MinusEqual(l)
                } else {
                    Token::Minus(l)
                };
                self.toks.push(Ok(value))
            }
            '>' => {
                let value = if self.matches('=') {
                    Token::GreaterThanEqual(l)
                } else {
                    Token::GreaterThan(l)
                };
                self.toks.push(Ok(value))
            }
            '<' => {
                let value = if self.matches('=') {
                    Token::LessThanEqual(l)
                } else {
                    Token::LessThan(l)
                };
                self.toks.push(Ok(value))
            }
            '=' => {
                let value = if self.matches('=') {
                    Token::EqualEqual(l)
                } else {
                    Token::Equal(l)
                };
                self.toks.push(Ok(value))
            }
            '!' => {
                let value = if self.matches('=') {
                    Token::BangEqual(l)
                } else {
                    Token::Bang(l)
                };
                self.toks.push(Ok(value))
            }
            ' ' | '\r' | '\t' => {}
            '\n' => self.line += 1,
            '"' => self.string(),
            _ => {
                if c.is_ascii_digit() {
                    self.number()
                } else if c.is_alphabetic() {
                    self.identifier()
                } else {
                    self.toks.push(Ok(Token::Illegal(l)));
                }
            }
        }
    }
    fn get_location(&mut self) -> Location {
        Location {
            line: self.line,
            start: self.start,
            end: self.current,
            file_name: self.file_name.to_string(),
        }
    }
    fn advance(&mut self) -> char {
        self.current += 1;
        self.source.chars().nth(self.current - 1).unwrap()
    }
    fn matches(&mut self, expected: char) -> bool {
        if self.is_end() {
            return false;
        }
        if self.source.chars().nth(self.current).unwrap() != expected {
            return false;
        }
        self.current += 1;
        true
    }
    fn peek(&mut self) -> char {
        if self.is_end() {
            return '\0';
        }
        self.source.chars().nth(self.current).unwrap()
    }
    fn peek_next(&mut self) -> char {
        if self.current + 1 >= self.source.len() {
            return '\0';
        }
        self.source.chars().nth(self.current + 1).unwrap()
    }
    fn string(&mut self) {
        while self.peek() != '"' && !self.is_end() {
            if self.peek() == '\n' {
                self.line += 1;
            }
            self.advance();
        }

        if self.is_end() {
            // we need to handle unterminated string literals
        }

        self.advance();

        let value = &self.source[self.start + 1..self.current - 1].to_string();
        let l = self.get_location();
        self.toks.push(Ok(Token::String(l, value.to_string())));
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

        let value = &self.source[self.start + 1..self.current - 1].to_string();
        let l = self.get_location();
        self.toks.push(if value.parse::<i128>().is_err() {
            Ok(Token::Float(l, value.parse::<f64>().unwrap()))
        } else {
            Ok(Token::Int(l, value.parse::<i128>().unwrap()))
        });
    }
    fn identifier(&mut self) {
        while self.peek().is_alphanumeric() {
            self.advance();
        }
        let value = &self.source[self.start + 1..self.current - 1].to_string();
        let l = self.get_location();
        let kw = self.get_keyword(value.to_string());
        self.toks.push(if let Some(x) = kw {
            Ok(x)
        } else {
            Ok(Token::Identifier(l, value.to_string()))
        });
    }
    fn get_keyword(&mut self, word: String) -> Option<Token> {
        let l = self.get_location();
        let kwds = HashMap::from([
            ("mut", Token::Mut(l.clone())),
            ("if", Token::If(l.clone())),
            ("for", Token::For(l.clone())),
            ("con", Token::Con(l.clone())),
            ("match", Token::Match(l.clone())),
            ("true", Token::True(l.clone())),
            ("false", Token::False(l.clone())),
            ("break", Token::Break(l.clone())),
            ("continue", Token::Continue(l.clone())),
            ("defer", Token::Defer(l.clone())),
            ("loop", Token::Loop(l.clone())),
            ("enum", Token::Enum(l.clone())),
            ("struct", Token::Struct(l.clone())),
            ("pub", Token::Pub(l.clone())),
        ]);
        Some(kwds.get(word.as_str()).unwrap().clone())
    }
}
