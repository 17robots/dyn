use crate::token::{TokenType, COMPOUND_OPERATORS, KEYWORDS, OPERATORS};

pub struct Lexer<'a> {
    pub input: &'a str,
    pub position: u128,
    pub read_pos: u128,
    ch: Option<char>,
}

impl<'a> Lexer<'a> {
    pub fn new(stream: &str) -> Lexer {
        let mut l = Lexer {
            input: stream,
            position: 0,
            read_pos: 0,
            ch: None,
        };
        l.read_char();
        l
    }

    pub fn read_char(&mut self) {
        if self.read_pos as usize > self.input.len() {
            self.ch = None;
        } else {
            self.ch = Some(self.input.chars().nth(self.read_pos as usize).unwrap());
        }

        self.position = self.read_pos;
        self.read_pos += 1;
    }

    pub fn next_token(&mut self) -> TokenType {
        if let Some(c) = self.ch {
            match c {
                _ if is_op(&c) => {
                    let x = self.read_op();
                    if COMPOUND_OPERATORS.contains_key(&x) {
                        COMPOUND_OPERATORS.get(&c.to_string()).unwrap().clone()
                    } else {
                        OPERATORS.get(&c.to_string()).unwrap().clone()
                    }
                }
                _ if is_letter(&c) => {
                    let x = self.read_word();
                    if KEYWORDS.contains_key(&x) {
                        KEYWORDS.get(&x).unwrap().clone()
                    } else {
                        TokenType::Identifier(x.clone())
                    }
                }
                _ if is_number(&c) => {
                    let x = self.read_number();
                    if x.contains('.') {
                        TokenType::Floating(x.parse::<f64>().unwrap())
                    } else {
                        TokenType::Integer(x.parse::<i128>().unwrap())
                    }
                }
                _ => TokenType::Illegal,
            }
        } else {
            TokenType::Eof
        }
    }

    fn read_word(&mut self) -> String {
        let pos = self.position;
        loop {
            if self.ch.is_none() || !is_letter(&self.ch.unwrap()) {
                break;
            }
            self.read_char();
        }
        self.input[pos as usize..self.position as usize].to_string()
    }

    fn read_number(&mut self) -> String {
        let pos = self.position;
        loop {
            if self.ch.is_none() || !is_letter(&self.ch.unwrap()) {
                break;
            }
            self.read_char();
        }
        self.input[pos as usize..self.position as usize].to_string()
    }

    fn read_op(&mut self) -> String {
        let pos = self.position;
        loop {
            if self.ch.is_none() || !is_op(&self.ch.unwrap()) {
                break;
            }
            self.read_char();
        }
        self.input[pos as usize..self.position as usize].to_string()
    }
}

fn is_letter(c: &char) -> bool {
    matches!(c, 'a'..='z' | 'A'..='Z' | '_')
}

fn is_number(c: &char) -> bool {
    matches!(c, '0'..='9' | '.' | '_')
}

fn is_op(c: &char) -> bool {
    OPERATORS.contains_key(&c.to_string())
}
