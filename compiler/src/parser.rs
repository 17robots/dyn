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

pub type ParsingResult = Result<Node, ParserError>;

enum LiteralKind {
    Float,
    Integer,
    String,
    Char,
    Bool,
    Function,
    Struct,
}

enum VariableKind {
    Default,
    Mutable,
    Constant
}

enum NodeKind {
    Program,

    // declarations
    Declaration(bool),
    VariableDeclaration(VariableKind),
    // EnumDeclaration,
    // FunctionDeclaration,
    // StructDeclaration,

    // Statements
    // Statement,
    // IfStatement,
    // LoopStatement(Option<String>),
    // ForStatement(Option<String>),
    // MatchStatement,
    // ContinueStatement,
    // BreakStatement,

    // Expressions
    // Block,
    // FunctionCall,
    // BinaryOp,
    // UnaryOp,
    // Literal(LiteralKind),
    // Identifier(String),

    // Supporting Types
    // FunctionParameter,
    // EnumMember,
    // EnumPartner,
    // MatchBranch,
}

pub struct Node {
    t: NodeKind,
    children: Vec<Node>,
}

pub struct Parser {
    toks: Vec<Token>,
    curr: usize,
}

impl Parser {
    pub fn init(toks: Vec<Token>) -> Parser {
        Parser { toks, curr: 0 }
    }
    pub fn parse(&mut self) -> Vec<Node> { vec![] }
}
