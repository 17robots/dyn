use std::fmt::Display;

use crate::error::LexerError;
use phf::phf_map;

#[derive(Clone, Debug)]
pub enum Token {
    Eof,
    // operators
    LParen,
    RParen,
    LBrack,
    RBrack,
    LBrace,
    RBrace,
    Comma,
    Semicolon,
    Colon,
    Dot,
    DotDot,
    AddAssign,
    SubAssign,
    MulAssign,
    DivAssign,
    ModAssign,
    AndAssign,
    OrAssign,
    XorAssign,
    Add,
    AddAdd,
    Sub,
    SubSub,
    Mul,
    Div,
    Mod,
    And,
    AndAnd,
    Or,
    OrOr,
    Xor,
    Lesser,
    LesserEqual,
    RightShift,
    Greater,
    GreaterEqual,
    LeftShift,
    Equal,
    EqualEqual,
    Bang,
    BangEqual,

    // keywords
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
    Enum,
    Struct,
    Pub,
    Void,
    Return,

    // literals
    Ident(String),
    Int(u128),
    Float(f64),
    String(String),
}

impl Display for Token {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Token::Eof => write!(f, ""),
            Token::LParen => write!(f, "("),
            Token::RParen => write!(f, ")"),
            Token::LBrack => write!(f, "["),
            Token::RBrack => write!(f, "]"),
            Token::LBrace => write!(f, "{{"),
            Token::RBrace => write!(f, "}}"),
            Token::Comma => write!(f, ","),
            Token::Semicolon => write!(f, ";"),
            Token::Colon => write!(f, ":"),
            Token::Dot => write!(f, "."),
            Token::DotDot => write!(f, ".."),
            Token::AddAssign => write!(f, "+="),
            Token::SubAssign => write!(f, "-="),
            Token::MulAssign => write!(f, "*="),
            Token::DivAssign => write!(f, "/="),
            Token::ModAssign => write!(f, "%="),
            Token::AndAssign => write!(f, "&="),
            Token::OrAssign => write!(f, "|="),
            Token::XorAssign => write!(f, "^="),
            Token::Add => write!(f, "+"),
            Token::AddAdd => write!(f, "++"),
            Token::Sub => write!(f, "-"),
            Token::SubSub => write!(f, "--"),
            Token::Mul => write!(f, "*"),
            Token::Div => write!(f, "/"),
            Token::Mod => write!(f, "%"),
            Token::And => write!(f, "&"),
            Token::AndAnd => write!(f, "&&"),
            Token::Or => write!(f, "|"),
            Token::OrOr => write!(f, "||"),
            Token::Xor => write!(f, "^"),
            Token::Lesser => write!(f, "<"),
            Token::LesserEqual => write!(f, "<="),
            Token::RightShift => write!(f, ">>"),
            Token::Greater => write!(f, ">"),
            Token::GreaterEqual => write!(f, ">="),
            Token::LeftShift => write!(f, "<<"),
            Token::Equal => write!(f, "="),
            Token::EqualEqual => write!(f, "=="),
            Token::Bang => write!(f, "!"),
            Token::BangEqual => write!(f, "!="),
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
            Token::Enum => write!(f, "enum"),
            Token::Struct => write!(f, "struct"),
            Token::Pub => write!(f, "pub"),
            Token::Void => write!(f, "void"),
            Token::Return => write!(f, "return"),
            Token::Ident(s) => write!(f, "ident: {}", s),
            Token::Int(s) => write!(f, "int: {}", s),
            Token::Float(s) => write!(f, "float: {}", s),
            Token::String(s) => write!(f, "string: {}", s),
        }
    }
}

static KWDS: phf::Map<&'static str, Token> = phf_map! {
    "mut" => Token::Mut,
    "if" => Token::If,
    "for" => Token::For,
    "con" => Token::Con,
    "match" => Token::Match,
    "true" => Token::True,
    "false" => Token::False,
    "break" => Token::Break,
    "continue" => Token::Continue,
    "defer" => Token::Defer,
    "enum" => Token::Enum,
    "struct" => Token::Struct,
    "pub" => Token::Pub,
    "void" => Token::Void,
    "return" => Token::Return,
};

pub struct Lexer {
    l: usize,
    c: usize,
    pub s: String,
    curr: usize,
    pub tok: Result<Option<Token>, LexerError>,
}

impl Lexer {
    pub fn new(source: String) -> Self {
        Self {
            l: 1,
            c: 1,
            s: source,
            curr: 0,
            tok: Ok(None),
        }
    }
    fn ch(&self) -> char {
        self.s.chars().nth(self.curr).unwrap()
    }
    pub fn next(&mut self) {
        if let Ok(ref s) = self.tok {
            if let Some(ref t) = s {
                if matches!(t, Token::Eof) {
                    return;
                }
            }
        }
        if self.curr >= self.s.len() - 1 {
            println!("We have hit the end of the file\n");
            self.tok = Ok(Some(Token::Eof));
            return;
        }
        'redo: loop {
            loop {
                if !matches!(self.ch(), ' ' | '\t' | '\n' | '\r') {
                    break;
                }
                self.advance();
            }
            let c = self.ch();
            if c.is_alphabetic() || c == '_' {
                self.ident();
                return;
            }
            match c {
                '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' => self.number(),
                '"' => self.string(),
                '`' => self.raw_string(),
                '\'' => self.char(),
                '(' => {
                    self.advance();
                    self.tok = Ok(Some(Token::LParen));
                }
                ')' => {
                    self.advance();
                    self.tok = Ok(Some(Token::RParen));
                }
                '[' => {
                    self.advance();
                    self.tok = Ok(Some(Token::LBrack));
                }
                ']' => {
                    self.advance();
                    self.tok = Ok(Some(Token::RBrack));
                }
                '{' => {
                    self.advance();
                    self.tok = Ok(Some(Token::LBrace));
                }
                '}' => {
                    self.advance();
                    self.tok = Ok(Some(Token::RBrace));
                }
                ',' => {
                    self.advance();
                    self.tok = Ok(Some(Token::Comma));
                }
                ';' => {
                    println!("We have semicolon");
                    self.advance();
                    self.tok = Ok(Some(Token::Semicolon));
                }
                ':' => {
                    self.advance();
                    self.tok = Ok(Some(Token::Colon));
                }
                '.' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '.' => Some(Token::DotDot),
                        _ => Some(Token::Dot),
                    });
                    self.advance();
                }
                '+' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::AddAssign),
                        '+' => Some(Token::AddAdd),
                        _ => Some(Token::Add),
                    });
                    self.advance();
                }
                '-' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::SubAssign),
                        '-' => Some(Token::SubSub),
                        _ => Some(Token::Sub),
                    });
                    self.advance();
                }
                '*' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::MulAssign),
                        _ => Some(Token::Mul),
                    });
                    self.advance();
                }
                '%' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::ModAssign),
                        _ => Some(Token::Mod),
                    });
                    self.advance();
                }
                '/' => {
                    self.advance();
                    match self.ch() {
                        '=' => self.tok = Ok(Some(Token::DivAssign)),
                        '/' => {
                            self.comment();
                            continue 'redo;
                        }
                        '*' => {
                            self.multi_comment();
                            continue 'redo;
                        }
                        _ => self.tok = Ok(Some(Token::Div)),
                    }
                }
                '^' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::XorAssign),
                        _ => Some(Token::Xor),
                    });
                    self.advance();
                }
                '<' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::LesserEqual),
                        '<' => Some(Token::Lesser),
                        _ => Some(Token::RightShift),
                    });
                    self.advance();
                }
                '>' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::GreaterEqual),
                        '>' => Some(Token::Greater),
                        _ => Some(Token::LeftShift),
                    });
                    self.advance();
                }
                '&' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::AndAssign),
                        '&' => Some(Token::AndAnd),
                        _ => Some(Token::And),
                    });
                    self.advance();
                }
                '|' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::OrAssign),
                        '|' => Some(Token::OrOr),
                        _ => Some(Token::Or),
                    });
                    self.advance();
                }
                '=' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::EqualEqual),
                        _ => Some(Token::Equal),
                    });
                    self.advance();
                }
                '!' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::BangEqual),
                        _ => Some(Token::Bang),
                    });
                    self.advance();
                }
                _ => {}
            }
            break 'redo;
        }
    }
    fn section(&self, start: usize) -> String {
        self.s[start..self.curr].to_owned()
    }
    fn ident(&mut self) {
        let start = self.curr;
        let mut c = self.ch();
        while c.is_ascii_alphanumeric() {
            self.advance();
            c = self.ch();
        }

        let v = self.section(start);
        self.tok = if KWDS.contains_key(v.as_str()) {
            let v: Token = KWDS.get(v.as_str()).unwrap().clone();
            Ok(Some(v))
        } else {
            Ok(Some(Token::Ident(v)))
        }
    }
    fn number(&mut self) {
        let mut floating = false;
        let start = self.curr;
        let mut c = self.ch();
        while c.is_ascii_digit() {
            self.advance();
            c = self.ch();
        }
        if c == '.' {
            floating = true;
            self.advance();
            while c.is_ascii_digit() {
                self.advance();
                c = self.ch();
            }
        }
        let v = self.section(start);
        self.tok = if floating {
            Ok(Some(Token::Float(v.parse::<f64>().unwrap())))
        } else {
            Ok(Some(Token::Int(v.parse::<u128>().unwrap())))
        }
    }
    fn string(&mut self) {
        self.advance();
        let start = self.curr;

        loop {
            match self.ch() {
                '"' => {
                    self.advance();
                    self.tok = Ok(Some(Token::String(self.section(start))));
                    break;
                }
                '\\' => {
                    if !self.escape('"') {
                        self.tok = Err(LexerError::InvalidEscape(self.l, self.c));
                    }
                    continue;
                }
                '\n' => {
                    self.tok = Err(LexerError::NewLineInString(self.l, self.curr));
                    break;
                }
                _ => {
                    if self.curr >= self.s.len() {
                        self.tok = Err(LexerError::UnterminatedString(self.l, start));
                        break;
                    }
                }
            }
            self.advance();
        }
    }
    fn raw_string(&mut self) {
        self.advance();
        let start = self.curr;

        loop {
            let c = self.ch();

            if c == '`' {
                self.advance();
                self.tok = Ok(Some(Token::String(self.section(start))));
                break;
            }
            if self.curr >= self.s.len() {
                self.tok = Err(LexerError::UnterminatedString(self.l, start));
                break;
            }
            self.advance();
        }
    }
    fn char(&mut self) {
        let mut n = 0;
        let start = self.curr;
        loop {
            let c = self.ch();

            if c == '\'' {
                if n > 1 {
                    self.tok = Err(LexerError::MoreThanOneCharacterInChar(self.l, self.curr))
                }
                self.advance();
                break;
            }
            if c == '\\' {
                self.advance();
                if !self.escape('\'') {
                    self.tok = Err(LexerError::InvalidEscape(self.l, self.curr));
                }
            }
            if self.curr >= self.s.len() {
                self.tok = Err(LexerError::UnterminatedChar(self.l, start));
                break;
            }
            self.advance();
            n += 1;
        }
    }
    fn comment(&mut self) {
        loop {
            if self.ch() == '\n' || self.curr >= self.s.len() {
                break;
            }
            self.advance();
        }
    }
    fn multi_comment(&mut self) {
        loop {
            if self.ch() == '*' {
                self.advance();
                if self.ch() == '/' {
                    break;
                }
            }
            if self.curr >= self.s.len() {
                break;
            }
            self.advance();
        }
    }
    fn escape(&mut self, c: char) -> bool {
        matches!(self.ch(), 'a' | 'b' | 'f' | 'n' | 'r' | 't' | 'v' | '\\') || self.ch() == c
    }
    fn advance(&mut self) {
        if self.ch() == '\n' {
            self.l += 1;
            self.c = 0;
        } else {
            self.c += 1;
        }
        self.curr += 1;
        if self.curr >= self.s.len() {
            // we need to error maybe?
        }
    }
}
