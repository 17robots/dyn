use crate::{ast::Expr, lexer::Token};

macro_rules! check_tok {
    ($self:ident, $expression:expr, $pattern:pat $(if $guard:expr)? $(,)?) => {
        if $self.is_end() {false}
        else {
            match $expression {
               $pattern $(if $guard)? => true,
                _ => false
            }
        }
    };
}

macro_rules! match_tok {
    ($self:ident, $expression:expr, $pattern:pat $(if $guard:expr)? $(,)?) => {
        if check_tok!($self, $expression, $pattern) {
            $self.advance();
            true
        } else {
            false
        }
    };
}

macro_rules! consume_tok {
    ($self:ident, $expression:expr, $pattern:pat $(if $guard:expr)? $(,)?) => {
        if check_tok!($self, $expression, $pattern) {
            return $self.advance();
        } else {
            // do something else
        }
    };
}

pub struct Parser {
    t: Vec<Token>,
    curr: usize,
}

impl Parser {
    pub fn new(toks: Vec<Token>) -> Self {
        Self { t: toks, curr: 0 }
    }
    fn expression(&mut self) -> Expr {
        self.expression()
    }
    fn equality(&mut self) -> Expr {
        let mut expr = self.comparison();
        while match_tok!(
            self,
            self.peek(),
            Token::EqualEqual(_) | Token::BangEqual(_)
        ) {
            let operator = self.previous();
            let right = self.comparison();
            expr = Parser::get_binary(operator, expr.clone(), right).unwrap();
        }
        expr
    }
    fn comparison(&mut self) -> Expr {
        let mut expr = self.term();

        while match_tok!(self,self.peek(), Token::GreaterThan(_)|Token::GreaterThanEqual(_)|Token::LessThan(_)|Token::LessThanEqual(_)) {
            let operator = self.previous();
            let right = self.term();
            expr = Parser::get_binary(operator, expr.clone(), right).unwrap();
        }
        expr
    }
    fn term(&mut self) -> Expr {
        let mut expr = self.factor();

        while match_tok!(self, self.peek(), Token::Minus(_)|Token::Plus(_)) {
            let op = self.previous();
            let right = self.factor();
            expr = Parser::get_binary(op, expr.clone(), right).unwrap();
        }
        expr
    }
    fn factor(&mut self) -> Expr {
        let mut expr = self.unary();

        while match_tok!(self,self.peek(), Token::Slash(_)|Token::Asterisk(_)) {
            let operator = self.previous();
            let right = self.unary();
            expr = Parser::get_binary(operator, expr.clone(), right).unwrap();
        }
        expr
    }
    fn unary(&mut self) -> Expr {
        if match_tok!(self, self.peek(), Token::Bang(_)|Token::Minus(_)|Token::Asterisk(_)) {
            let op = self.previous();
            let right = self.unary();
            return Parser::get_unary(op, right).unwrap();
        }
        return self.primary();
    }
    fn primary(&mut self) -> Expr {
        if match_tok!(self, self.peek(), Token::False(_)) {}
        if match_tok!(self, self.peek(), Token::True(_)) {}
        if match_tok!(self, self.peek(), Token::Float(_,_)) {}
        if match_tok!(self, self.peek(), Token::Int(_,_)) {}
        if match_tok!(self, self.peek(), Token::String(_,_)) {}
        if match_tok!(self, self.peek(), Token::Char(_,_)) {}

        if match_tok!(self, self.peek(), Token::LeftParen(_)) {
            let expr = self.expression();
        }
        todo!()
    }
    fn peek(&mut self) -> Token {
        self.t.iter().nth(self.curr).unwrap().clone()
    }
    fn previous(&mut self) -> Token {
        self.t.iter().nth(self.curr - 1).unwrap().clone()
    }
    fn is_end(&mut self) -> bool {
        matches!(self.peek(), Token::EOF)
    }
    fn advance(&mut self) -> Token {
        if !self.is_end() {
            self.curr += 1;
        }
        self.previous()
    }
    fn get_unary(o: Token, r: Expr) -> Option<Expr> {
        match o {
            Token::Asterisk(_) => Some(Expr::PointerDereference(Box::new(r))),
            Token::Minus(_) => Some(Expr::Negate(Box::new(r))),
            Token::Bang(_) => Some(Expr::Not(Box::new(r))),
            _ => None
        }
    }
    fn get_binary(o: Token, l: Expr, r: Expr) -> Option<Expr> {
        match o {
            Token::Asterisk(_) => Some(Expr::Multiply(Box::new(l), Box::new(r))),
            Token::AsteriskEqual(_) => Some(Expr::MultiplyEqual(Box::new(l), Box::new(r))),
            Token::Percent(_) => Some(Expr::Mod(Box::new(l), Box::new(r))),
            Token::PercentEqual(_) => Some(Expr::ModEqual(Box::new(l), Box::new(r))),
            Token::Slash(_) => Some(Expr::Slash(Box::new(l), Box::new(r))),
            Token::SlashEqual(_) => Some(Expr::SlashEqual(Box::new(l), Box::new(r))),
            Token::Plus(_) => Some(Expr::Plus(Box::new(l), Box::new(r))),
            Token::PlusEqual(_) => Some(Expr::PlusEqual(Box::new(l), Box::new(r))),
            Token::Minus(_) => Some(Expr::Minus(Box::new(l), Box::new(r))),
            Token::MinusEqual(_) => Some(Expr::MinusEqual(Box::new(l), Box::new(r))),
            Token::GreaterThan(_) => Some(Expr::GreaterThan(Box::new(l), Box::new(r))),
            Token::GreaterThanEqual(_) => Some(Expr::GreaterThanEqual(Box::new(l), Box::new(r))),
            Token::LessThan(_) => Some(Expr::LessThan(Box::new(l), Box::new(r))),
            Token::LessThanEqual(_) => Some(Expr::LessThanEqual(Box::new(l), Box::new(r))),
            Token::Equal(_) => Some(Expr::Equal(Box::new(l), Box::new(r))),
            Token::EqualEqual(_) => Some(Expr::EqualEqual(Box::new(l), Box::new(r))),
            Token::BangEqual(_) => Some(Expr::BangEqual(Box::new(l), Box::new(r))),
            Token::Or(_) => Some(Expr::Or(Box::new(l), Box::new(r))),
            Token::OrEqual(_) => Some(Expr::OrEqual(Box::new(l), Box::new(r))),
            Token::OrOr(_) => Some(Expr::LogicalOr(Box::new(l), Box::new(r))),
            Token::And(_) => Some(Expr::And(Box::new(l), Box::new(r))),
            Token::AndAnd(_) => Some(Expr::LogicalAnd(Box::new(l), Box::new(r))),
            Token::AndEqual(_) => Some(Expr::AndEqual(Box::new(l), Box::new(r))),
            _ => None
        }
    }
}
