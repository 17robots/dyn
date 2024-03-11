use crate::lexer::Token;

const KEYWORDS: [&str; 13] = [
    "mut", "if", "for", "con", "match", "true", "false", "break", "continue", "defer", "loop",
    "enum", "struct",
];

#[derive(Debug)]
pub enum ParserError {
    None,
    InvalidToken,
}
pub type ParsingResult = Result<Action, ParserError>;

pub enum Actions {
    PublicDeclare,
    Declare,
    MutableVariableDeclare,
    ConstantVariableDeclare,
    VariableDeclare,
}

pub struct Action {
    t: Actions,
    children: Vec<Action>,
}

pub struct Parser {
    toks: Vec<Token>,
    curr: usize,
}

impl Parser {
    pub fn init(toks: Vec<Token>) -> Parser {
        Parser { toks, curr: 0 }
    }
    pub fn parse(&mut self) -> Vec<Action> { vec![] }
}
