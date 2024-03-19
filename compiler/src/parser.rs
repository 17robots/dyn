use crate::lexer::Token;

const KEYWORDS: [&str; 14] = [
    "mut", "if", "for", "con", "match", "true", "false", "break", "continue", "defer", "loop",
    "enum", "struct", "pub",
];

enum NodeKind {
    Program,
    ModuleDeclaration(bool),
    Variable(bool),
}

pub struct Node {
    t: NodeKind,
    c: Vec<Node>,
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
    pub fn program(&mut self) -> ParsingResult {
        let mut n = Node {
            t: NodeKind::Program,
            c: vec![],
        };
        while self.curr < self.toks.len() {
            n.c.push(self.module_declaration()?);
        }
        // Ok(n)
        Err(ParserError::None)
    }
    pub fn module_declaration(&mut self) -> ParsingResult {
        let p = if let Token::Word(x) = self.toks.get(self.curr).unwrap() {
            if x.as_str() == "pub" {
                self.curr += 1;
                true
            } else {
                false
            }
        } else {
            false
        };
        Ok(Node {
            t: NodeKind::ModuleDeclaration(p),
            c: vec![self.declaration()?],
        })
    }
    pub fn declaration(&mut self) -> ParsingResult {
        return if let Token::Word(x) = self.toks.get(self.curr).unwrap() {
            match x.as_str() {
                "enum" => Ok(self.enum_declaration()?),
                "struct" => Ok(self.struct_declaration()?),
                _ => Ok(self.other_declaration()?),
            }
        } else {
            Err(ParserError::InvalidToken)
        };
    }
    pub fn enum_declaration(&mut self) -> ParsingResult {
        Err(ParserError::None)
    }
    pub fn struct_declaration(&mut self) -> ParsingResult {
        Err(ParserError::None)
    }
    pub fn other_declaration(&mut self) -> ParsingResult {
        // check for mut -> var
        // read the token as an identifier type
        // check for parentheses -> fn
        Err(ParserError::None)
    }
    pub fn variable_declaration(&mut self) -> ParsingResult {
        Err(ParserError::None)
    }
    pub fn function_declaration(&mut self) -> ParsingResult {
        Err(ParserError::None)
    }
}
