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
                _ if self.is_op() => {
                    let x = self.peak();
                    if x != None && COMPOUND_OPERATORS.contains_key(&format!("{}{}",c,x.unwrap()).as_str()) {
                        COMPOUND_OPERATORS.get(&c.to_string()).unwrap().clone()
                    } else {
                        OPERATORS.get(&c.to_string()).unwrap().clone()
                    }
                }
                _ if self.is_letter() => {
                    let x = self.read_word();
                    if KEYWORDS.contains_key(&x) {
                        KEYWORDS.get(&x).unwrap().clone()
                    } else {
                        TokenType::Identifier(x.clone())
                    }
                }
                _ if self.is_number() => {
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
            if self.ch.is_none() || !self.is_letter() {
                break;
            }
            self.read_char();
        }
        self.input[pos as usize..self.position as usize].to_string()
    }

    fn read_number(&mut self) -> String {
        let pos = self.position;
        loop {
            if self.ch.is_none() || !self.is_letter() {
                break;
            }
            self.read_char();
        }
        self.input[pos as usize..self.position as usize].to_string()
    }

    fn is_letter(&self) -> bool {
        matches!(&self.ch.unwrap(), 'a'..='z' | 'A'..='Z' | '_')
    }

    fn is_number(&self) -> bool {
        matches!(&self.ch.unwrap(), '0'..='9' | '.' | '_')
    }

    fn is_op(&self) -> bool {
        OPERATORS.contains_key(&self.ch.unwrap().to_string())
    }

    fn peak(&self) -> Option<char> {
        if (self.position + 1) as usize > self.input.len() { None } else { self.input.chars().nth(self.position as usize + 1) }
    }
}
