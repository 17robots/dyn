use std::io::ErrorKind;

use crate::lexer::Token;

const KEYWORDS: [&str; 14] = [
    "mut", "if", "for", "con", "match", "true", "false", "break", "continue", "defer", "loop",
    "enum", "struct", "pub",
];

enum NodeKind {
    Program,
    Declaration,
    Variable(bool)
}

pub struct Node {
    t: NodeKind,
    c: Vec<Node>
}

#[derive(Debug)]
pub enum ParserError {
    None,
    InvalidToken,
}

pub type ParsingResult = Result<Node, ParserError>;

pub struct Parser {
    toks: Vec<Token>,
    curr: usize,
}

impl Parser {
    pub fn init(toks: Vec<Token>) -> Parser {
        Parser { toks, curr: 0 }
    }
    pub fn parse(&mut self) -> ParsingResult {
        self.program()
    }
    pub fn program(&self) -> ParsingResult {
        let mut n = Node { t: NodeKind::Program, c: vec![] };
        while self.curr < self.toks.len() {
            n.c.push(self.declaration()?);
        }
        // Ok(n)
        Err(ParserError::None)
    }
    pub fn declaration(&self) -> ParsingResult { Ok(Node { t: NodeKind::Declaration, c: vec![] }) }
    // if it exists then return true, else false 
    fn optional(&self, x: Token) -> bool { false }
    
    // if exists return true, else false
    fn require(&self, x: Token) -> bool { false }

    // if exists return value, else error
    fn read(&self, x: Token) -> Result<String,ErrorKind> { Ok("".to_owned()) }
}
