pub enum LexerError {
    InvalidEndOfFile,
}
pub enum Token {
    None,
}

pub struct Lexer {
    l: usize,
    c: usize,
    s: String,
    curr: usize,
}

impl Lexer {
    pub fn new(source: String) -> Self {
        Self {
            l: 1,
            c: 1,
            s: source,
            curr: 0,
        }
    }
    fn ch(&self) -> char {
        self.s.chars().nth(self.curr).unwrap()
    }
    pub fn next(&mut self) -> Result<Token, LexerError> {
        loop {
            if !matches!(self.ch(), ' ' | '\t' | '\n' | '\r') {
                break;
            }
            self.advance()?;
        }
        let c = self.ch();
        match c {
            _ => if c.is_alphabetic() || c == '_' {},
        }
        Ok(Token::None)
    }
    fn advance(&mut self) -> Result<(), LexerError> {
        self.curr += 1;
        if self.curr >= self.s.len() {
            return Err(LexerError::InvalidEndOfFile);
        }
        if self.ch() == '\n' {
            self.l += 1;
            self.c = 0;
        } else {
            self.c += 1;
        }
        Ok(())
    }
}
