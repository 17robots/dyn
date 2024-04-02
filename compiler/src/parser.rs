use crate::{ast::Expr, lexer::Token};

pub struct Parser {
    t: Vec<Token>,
    curr: usize
}

impl Parser {
    pub fn new(toks: Vec<Token>) -> Self {
        Self { t: toks, curr: 0 }
    }

    fn expression() -> Expr {
        todo!()
    }
    fn equality() -> Expr {
        todo!()
    }
}
