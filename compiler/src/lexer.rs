use crate::error::LexerError;
use crate::token::Token;
use phf::phf_map;

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
        if let Some(c) = self.s.chars().nth(self.curr) {
            c
        } else {
            '\0'
        }
    }
    pub fn next(&mut self) {
        if let Ok(Some(ref t)) = self.tok {
            if matches!(t, Token::Eof) {
                return;
            }
        }
        'redo: loop {
            if self.is_end() {
                self.tok = Ok(Some(Token::Eof));
                return;
            }
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
                '\0' => self.tok = Ok(Some(Token::Eof)),
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
                    if matches!(self.ch(), '.') {
                        self.advance();
                    }
                }
                '+' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::AddAssign),
                        '+' => Some(Token::AddAdd),
                        _ => Some(Token::Add),
                    });
                    if matches!(self.ch(), '=' | '+') {
                        self.advance();
                    }
                }
                '-' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::SubAssign),
                        '-' => Some(Token::SubSub),
                        _ => Some(Token::Sub),
                    });
                    if matches!(self.ch(), '=' | '-') {
                        self.advance();
                    }
                }
                '*' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::MulAssign),
                        _ => Some(Token::Mul),
                    });
                    if matches!(self.ch(), '=' | '*') {
                        self.advance();
                    }
                }
                '%' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::ModAssign),
                        _ => Some(Token::Mod),
                    });
                    if matches!(self.ch(), '=') {
                        self.advance();
                    }
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
                    if matches!(self.ch(), '=') {
                        self.advance();
                    }
                }
                '^' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::XorAssign),
                        _ => Some(Token::Xor),
                    });
                    if matches!(self.ch(), '=') {
                        self.advance();
                    }
                }
                '<' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::LesserEqual),
                        '<' => Some(Token::Lesser),
                        _ => Some(Token::RightShift),
                    });
                    if matches!(self.ch(), '=' | '<') {
                        self.advance();
                    }
                }
                '>' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::GreaterEqual),
                        '>' => Some(Token::Greater),
                        _ => Some(Token::LeftShift),
                    });
                    if matches!(self.ch(), '=' | '>') {
                        self.advance();
                    }
                }
                '&' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::AndAssign),
                        '&' => Some(Token::AndAnd),
                        _ => Some(Token::And),
                    });
                    if matches!(self.ch(), '=' | '&') {
                        self.advance();
                    }
                }
                '|' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::OrAssign),
                        '|' => Some(Token::OrOr),
                        _ => Some(Token::Or),
                    });
                    if matches!(self.ch(), '=' | '|') {
                        self.advance();
                    }
                }
                '=' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::EqualEqual),
                        _ => Some(Token::Equal),
                    });
                    if matches!(self.ch(), '=') {
                        self.advance();
                    }
                }
                '!' => {
                    self.advance();
                    self.tok = Ok(match self.ch() {
                        '=' => Some(Token::BangEqual),
                        _ => Some(Token::Bang),
                    });
                    if matches!(self.ch(), '=') {
                        self.advance();
                    }
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
        while c.is_ascii_alphanumeric() || c == '_' {
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
                    self.tok = Err(LexerError::NewLineInString(self.l, self.c));
                    break;
                }
                _ => {
                    if self.is_end() {
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
            if self.is_end() {
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
            if self.is_end() {
                self.tok = Err(LexerError::UnterminatedChar(self.l, start));
                break;
            }
            self.advance();
            n += 1;
        }
    }
    fn comment(&mut self) {
        loop {
            if self.ch() == '\n' || self.is_end() {
                break;
            }
            self.advance();
        }
    }
    fn is_end(&mut self) -> bool {
        self.curr >= self.s.len()
    }
    fn multi_comment(&mut self) {
        loop {
            if self.ch() == '*' {
                self.advance();
                if self.ch() == '/' {
                    self.advance();
                    break;
                }
            }
            if self.is_end() {
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
    }
}
