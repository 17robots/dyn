use crate::lexer::Token;

#[derive(Debug)]
pub enum ParserError {
    None,
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

enum NodeKind {
    Program,

    // declarations
    Declaration(bool),
    VariableDeclaration,
    EnumDeclaration,
    FunctionDeclaration,
    StructDeclaration,

    // Statements
    Statement,
    IfStatement,
    LoopStatement(Option<String>),
    ForStatement(Option<String>),
    MatchStatement,
    ContinueStatement,
    BreakStatement,

    // Expressions
    Block,
    FunctionCall,
    BinaryOp,
    UnaryOp,
    Literal(LiteralKind),
    Identifier,

    // Supporting Types
    FunctionParameter,
    EnumMember,
    EnumPartner,
    MatchBranch,
}

struct Node {
    t: NodeKind,
    children: Vec<Node>,
}

pub fn parse(_toks: &Vec<Token>) -> ParsingResult {
    program()
}

fn program() -> ParsingResult {
    Err(ParserError::None)
}

fn declaration() -> ParsingResult {
    Err(ParserError::None)
}

fn variable_declaration() -> ParsingResult {
    Err(ParserError::None)
}

fn enum_declaraton() -> ParsingResult {
    Err(ParserError::None)
}
fn function_declaraton() -> ParsingResult {
    Err(ParserError::None)
}
fn struct_declaraton() -> ParsingResult {
    Err(ParserError::None)
}

fn statement() -> ParsingResult {
    Err(ParserError::None)
}
fn if_statement() -> ParsingResult {
    Err(ParserError::None)
}
fn loop_statement() -> ParsingResult {
    Err(ParserError::None)
}
fn for_statement() -> ParsingResult {
    Err(ParserError::None)
}
fn match_statement() -> ParsingResult {
    Err(ParserError::None)
}
fn continue_statement() -> ParsingResult {
    Err(ParserError::None)
}
fn break_statement() -> ParsingResult {
    Err(ParserError::None)
}

fn block() -> ParsingResult {
    Err(ParserError::None)
}
fn function_call() -> ParsingResult {
    Err(ParserError::None)
}
fn binary_op() -> ParsingResult {
    Err(ParserError::None)
}
fn unary_op() -> ParsingResult {
    Err(ParserError::None)
}
fn literal() -> ParsingResult {
    Err(ParserError::None)
}
fn identifier() -> ParsingResult {
    Err(ParserError::None)
}

fn function_parameter() -> ParsingResult {
    Err(ParserError::None)
}
fn enum_member() -> ParsingResult {
    Err(ParserError::None)
}
fn enum_partner() -> ParsingResult {
    Err(ParserError::None)
}
fn match_branch() -> ParsingResult {
    Err(ParserError::None)
}
