use crate::lexer::Token;

enum Node {
    Declaration(bool, Vec<Node>),
    FunctionDeclaration(Vec<Node>),
    StructDeclaration(Vec<Node>),
    EnumDeclaration(Vec<Node>),
}

pub fn parse(toks: &Vec<Token>) -> Option<Node> {
    None
}

