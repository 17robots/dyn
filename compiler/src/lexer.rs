// doing this again to see if this is better
#[derive(Debug)]
pub struct Location {
    line: usize,
    start: usize,
    end: usize,
    file_name: String,
}

#[derive(Debug)]
pub enum Token2 {
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

pub enum ScannerError {
    None,
}

#[derive(Debug)]
pub struct Scanner {
    source: String,
    toks: Vec<Token2>,
    file_name: String,
    start: usize,
    current: usize,
    line: usize,
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
        self.toks.push(Token2::EOF);
        Ok(())
    }
    pub fn is_end(&mut self) -> bool {
        self.current as usize >= self.source.len()
    }

    pub fn scan_token(&mut self) {
        let l = self.get_location();
        let c = self.advance();
        match c {
            // single character tokens
            '(' => self.toks.push(Token2::LeftParen(l)),
            ')' => self.toks.push(Token2::RightParen(l)),
            '[' => self.toks.push(Token2::LeftBracket(l)),
            ']' => self.toks.push(Token2::RightBracket(l)),
            '{' => self.toks.push(Token2::LeftBrace(l)),
            '}' => self.toks.push(Token2::RightBrace(l)),
            '.' => self.toks.push(Token2::Dot(l)),
            ',' => self.toks.push(Token2::Comma(l)),
            ';' => self.toks.push(Token2::Semicolon(l)),
            // compound character tokens
            '*' => {
                let value = if self.matches('=') {
                    Token2::AsteriskEqual(l)
                } else {
                    Token2::Asterisk(l)
                };
                self.toks.push(value)
            }
            '%' => {
                let value = if self.matches('=') {
                    Token2::PercentEqual(l)
                } else {
                    Token2::Percent(l)
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
                let value = if self.matches('=') {
                    Token2::SlashEqual(l)
                } else {
                    Token2::Slash(l)
                };
                self.toks.push(value)
            }
            '+' => {
                let value = if self.matches('=') {
                    Token2::PlusEqual(l)
                } else {
                    Token2::Plus(l)
                };
                self.toks.push(value)
            }
            '-' => {
                let value = if self.matches('=') {
                    Token2::MinusEqual(l)
                } else {
                    Token2::Minus(l)
                };
                self.toks.push(value)
            }
            '>' => {
                let value = if self.matches('=') {
                    Token2::GreaterThanEqual(l)
                } else {
                    Token2::GreaterThan(l)
                };
                self.toks.push(value)
            }
            '<' => {
                let value = if self.matches('=') {
                    Token2::LessThanEqual(l)
                } else {
                    Token2::LessThan(l)
                };
                self.toks.push(value)
            }
            '=' => {
                let value = if self.matches('=') {
                    Token2::EqualEqual(l)
                } else {
                    Token2::Equal(l)
                };
                self.toks.push(value)
            }
            '!' => {
                let value = if self.matches('=') {
                    Token2::BangEqual(l)
                } else {
                    Token2::Bang(l)
                };
                self.toks.push(value)
            }
            ' ' | '\r' | '\t' => {}
            '\n' => self.line += 1,
            '"' => self.string(),
            _ => {
                if c.is_digit(10) {}
                if c.is_alphabetic() {}
                self.toks.push(Token2::Illegal(l));
            }
        }
    }

    pub fn get_location(&mut self) -> Location {
        Location {
            line: self.line,
            start: self.start,
            end: self.current,
            file_name: self.file_name.to_string(),
        }
    }
    pub fn advance(&mut self) -> char {
        self.current += 1;
        self.source.chars().nth(self.current - 1).unwrap()
    }
    pub fn matches(&mut self, expected: char) -> bool {
        if self.is_end() {
            return false;
        }
        if self.source.chars().nth(self.current).unwrap() != expected {
            return false;
        }
        self.current += 1;
        true
    }
    pub fn peek(&mut self) -> char {
        if self.is_end() {
            return '\0';
        }
        self.source.chars().nth(self.current).unwrap()
    }
    pub fn peek_next(&mut self) -> char {
        if self.current + 1 >= self.source.len()  {
            return '\0';
        }
        self.source.chars().nth(self.current + 1).unwrap()
    }
    pub fn string(&mut self) {
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
        self.toks.push(Token2::String(l, value.to_string()));
    }
    pub fn number(&mut self) {
        while self.peek().is_digit(10) {
            self.advance();
        }

        if (self.peek() == '.' && self.peek_next().is_digit(10)) {
            self.advance();
            while self.peek().is_digit(10) {
                self.advance();
            }
        }
    }
}

#[derive(Debug)]
pub enum Token {
    Illegal,
    Word(String),
    NumberLiteral(String),
    StringLiteral(String),
    CharLiteral(String),
    Operator(String),
}

const OPS: [&str; 33] = [
    ";", ":", ".", ",", "(", "[", "{", ")", "]", "}", "=", "!", "<", ">", "*", "+", "/", "-", "&",
    "|", "==", "!=", "<=", ">=", "*=", "+=", "/=", "-=", "&=", "&&", "|=", "||", "=>",
];

#[derive(Debug)]
enum TokenError {
    None,
}

pub type LexerResult = Result<Token, TokenError>;

#[derive(PartialEq)]
enum ParserState {
    Start,
    ReadWord,
    ReadNum,
    ReadString,
    ReadChar,
    ReadOp,
}

pub struct Tokenizer {
    stream: String,
    state: ParserState,
}

impl Tokenizer {
    pub fn init(stream: &str) -> Tokenizer {
        Tokenizer {
            stream: stream.to_owned(),
            state: ParserState::Start,
        }
    }
    fn is_c(x: char) -> bool {
        x.is_ascii_alphabetic()
    }
    fn is_n(x: char, s: &ParserState) -> bool {
        if x == '.' {
            *s == ParserState::ReadNum
        } else {
            x.is_ascii_digit()
        }
    }
    fn is_o(x: &str) -> bool {
        OPS.into_iter().any(|v| v == x)
    }
    fn is_w(x: char) -> bool {
        matches!(x, ' ' | '\t' | '\n')
    }
    fn grab_state(&self, x: char) -> ParserState {
        if x == '\'' {
            ParserState::ReadChar
        } else if x == '\"' {
            ParserState::ReadString
        } else if Tokenizer::is_c(x) {
            ParserState::ReadWord
        } else if Tokenizer::is_n(x, &self.state) {
            ParserState::ReadNum
        } else if Tokenizer::is_o(&x.to_string()) {
            ParserState::ReadOp
        } else {
            ParserState::Start
        }
    }
    fn clear_buf(b: &mut Vec<char>) -> String {
        let x: String = b.iter().clone().collect();
        b.clear();
        x
    }
    pub fn lex(&mut self) -> Vec<Token> {
        let mut t: Vec<Token> = vec![];
        let mut buf: Vec<char> = vec![];
        for c in self.stream.chars() {
            match self.state {
                ParserState::Start => {
                    self.state = self.grab_state(c);
                    if self.state == ParserState::Start && !Tokenizer::is_w(c) {
                        t.push(Token::Illegal);
                    }
                }
                ParserState::ReadWord => {
                    if !Tokenizer::is_c(c) && !Tokenizer::is_n(c, &self.state) {
                        t.push(Token::Word(Tokenizer::clear_buf(&mut buf)));
                        self.state = self.grab_state(c);
                    }
                }
                ParserState::ReadNum => {
                    if !Tokenizer::is_n(c, &self.state) {
                        t.push(Token::NumberLiteral(Tokenizer::clear_buf(&mut buf)));
                        self.state = self.grab_state(c);
                    }
                }
                ParserState::ReadString => {
                    if c == '\"' {
                        t.push(Token::StringLiteral(Tokenizer::clear_buf(&mut buf)));
                        self.state = ParserState::Start;
                    }
                }
                ParserState::ReadChar => {}
                ParserState::ReadOp => {
                    buf.push(c);
                    let y = buf.iter().clone().collect::<String>();
                    if !Tokenizer::is_o(&y) {
                        _ = buf.pop();
                        t.push(Token::Operator(Tokenizer::clear_buf(&mut buf)));
                        self.state = self.grab_state(c);
                    }
                }
            }
            if self.state != ParserState::Start {
                buf.push(c);
            }
        }
        let x = Tokenizer::clear_buf(&mut buf);
        t.push(match self.state {
            ParserState::Start => Token::Illegal,
            ParserState::ReadWord => Token::Word(x),
            ParserState::ReadChar => Token::CharLiteral(x),
            ParserState::ReadNum => Token::NumberLiteral(x),
            ParserState::ReadString => Token::StringLiteral(x),
            ParserState::ReadOp => Token::Operator(x),
        });
        t
    }
}
