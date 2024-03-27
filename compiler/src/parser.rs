use crate::lexer::Token;

const KEYWORDS: [&str; 14] = [
    "mut", "if", "for", "con", "match", "true", "false", "break", "continue", "defer", "loop",
    "enum", "struct", "pub",
];

enum NodeKind {
    Program,
    ModuleDeclaration(bool),
    Variable(bool),
    StructDeclaration,
    EnumDeclaration,
    Identifier(String),
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
        self.parse_node(&mut Node{ t: NodeKind::Program, c: vec![] })
    }
    pub fn parse_node(&mut self, _node: &mut Node) -> ParsingResult { Err(ParserError::None) }
}
