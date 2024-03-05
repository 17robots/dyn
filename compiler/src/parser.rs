use crate::lexer::Token;

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
    pub fn parse(&mut self) -> ParsingResult {
        self.program()
    }
    fn program(&mut self) -> ParsingResult {
        let mut n = Node {
            t: NodeKind::Program,
            children: vec![],
        };
        while self.curr < self.toks.len() {
            n.children.push(self.declaration()?);
        }
        Ok(n)
    }
    fn declaration(&mut self) -> ParsingResult {
        let mut public = false;
        if let Token::Word(s) = self.toks.get(self.curr).unwrap() {
            if s == "pub" {
                public = true;
                self.curr += 1;
            }
        } else {
            return Err(ParserError::InvalidToken);
        }
        let mut n = Node {
            t: NodeKind::Declaration(public),
            children: vec![],
        };
        if let Token::Word(s) = self.toks.get(self.curr).unwrap() {
            match s.as_ref() {
                "struct" => n.children.push(self.struct_declaraton()?),
                "enum" => n.children.push(self.enum_declaraton()?),
                _ => n.children.push(self.fn_var_declaration()?),
            }
        }
        Ok(n)
    }
    fn variable_declaration(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn enum_declaraton(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn fn_var_declaration(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn function_declaraton(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn struct_declaraton(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn statement(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn if_statement(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn loop_statement(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn for_statement(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn match_statement(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn continue_statement(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn break_statement(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn block(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn function_call(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn binary_op(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn unary_op(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn literal(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn identifier(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn function_parameter(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn enum_member(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn enum_partner(&self) -> ParsingResult {
        Err(ParserError::None)
    }
    fn match_branch(&self) -> ParsingResult {
        Err(ParserError::None)
    }
}
