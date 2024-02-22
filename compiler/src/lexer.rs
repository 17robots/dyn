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
                    let y =buf.iter().clone().collect::<String>(); 
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

