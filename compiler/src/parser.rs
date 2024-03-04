use crate::lexer::Token;

enum LiteralKind {
    Float,
    Integer,
    String,
    Char,
    Bool,
    Function,
    Struct
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

pub fn parse(_toks: &Vec<Token>) -> Option<Node> {
    program()
}

fn program() -> Option<Node> {
    None
} 

fn declaration() -> Option<Node> {
    None
}

fn variable_declaration() -> Option<Node> {
    None
}

fn enum_declaraton() -> Option<Node> { None }
fn function_declaraton() -> Option<Node> { None }
fn struct_declaraton() -> Option<Node> { None }

fn statement() -> Option<Node> { None }
fn if_statement() -> Option<Node> { None }
fn loop_statement() -> Option<Node> { None }
fn for_statement() -> Option<Node> { None }
fn match_statement() -> Option<Node> { None }
fn continue_statement() -> Option<Node> { None }
fn break_statement() -> Option<Node> { None }

fn block() -> Option<Node> { None }
fn function_call() -> Option<Node> { None }
fn binary_op() -> Option<Node> { None }
fn unary_op() -> Option<Node> { None }
fn literal() -> Option<Node> { None }
fn identifier() -> Option<Node> { None }

fn function_parameter() -> Option<Node> { None }
fn enum_member() -> Option<Node> { None }
fn enum_partner() -> Option<Node> { None }
fn match_branch() -> Option<Node> { None }

