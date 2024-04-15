use std::path::Path;

use crate::{ast::Expr, error::ParsingError, lexer::Token};

pub struct Parser<'cache> {
    t: Vec<Token>,
    f: &'cache Path,
    c: usize,
}

impl<'cache> Parser<'cache> {
    pub fn new(t: Vec<Token>, f: &'cache Path) -> Self {
        Self { t, f, c: 0 }
    }
    fn advance(&mut self) -> Token {
        if !self.is_end() {
            self.c += 1;
        }
        self.previous()
    }
    fn is_end(&self) -> bool {
        self.t.iter().nth(self.c).unwrap() == &Token::Eof
    }
    fn previous(&self) -> Token {
        self.t.iter().nth(self.c - 1).unwrap().clone()
    }
    fn peek(&self) -> Token {
        self.t.iter().nth(self.c).unwrap().clone()
    }
    fn expression(&mut self) -> Result<Expr, ParsingError> {
        self.equality()
    }
    fn equality(&mut self) -> Result<Expr, ParsingError> {
        let mut expr = self.comparison()?;

        while matches!(self.peek(), Token::BangEqual | Token::EqualEqual) {
            self.advance();
            let op = self.previous();
            let right = self.comparison()?;
            expr = if op == Token::BangEqual {
                Expr::BangEqual(Box::new(expr), Box::new(right))
            } else {
                Expr::EqualEqual(Box::new(expr), Box::new(right))
            }
        }
        Ok(expr)
    }
    fn comparison(&mut self) -> Result<Expr, ParsingError> {
        let mut expr = self.term()?;

        while matches!(
            self.peek(),
            Token::GreaterThan | Token::GreaterThanEqual | Token::LessThan | Token::LessThanEqual
        ) {
            self.advance();
            let op = self.previous();
            let right = self.term()?;
            expr = if op == Token::GreaterThan {
                Expr::GreaterThan(Box::new(expr), Box::new(right))
            } else if op == Token::GreaterThanEqual {
                Expr::GreaterThanEqual(Box::new(expr), Box::new(right))
            } else if op == Token::LessThan {
                Expr::LessThan(Box::new(expr), Box::new(right))
            } else {
                Expr::LessThanEqual(Box::new(expr), Box::new(right))
            }
        }
        Ok(expr)
    }
    fn term(&mut self) -> Result<Expr, ParsingError> {
        let mut expr = self.factor()?;

        while matches!(self.peek(), Token::Plus | Token::Minus) {
            self.advance();
            let op = self.previous();
            let right = self.factor()?;
            expr = if op == Token::Plus {
                Expr::Plus(Box::new(expr), Box::new(right))
            } else {
                Expr::Minus(Box::new(expr), Box::new(right))
            }
        }
        Ok(expr)
    }
    fn factor(&mut self) -> Result<Expr, ParsingError> {
        let mut expr = self.unary()?;

        while matches!(self.peek(), Token::Asterisk | Token::Slash) {
            self.advance();
            let op = self.previous();
            let right = self.factor()?;
            expr = if op == Token::Asterisk {
                Expr::Multiply(Box::new(expr), Box::new(right))
            } else {
                Expr::Slash(Box::new(expr), Box::new(right))
            }
        }
        Ok(expr)
    }
    fn unary(&mut self) -> Result<Expr, ParsingError> {
        if matches!(self.peek(), Token::Minus | Token::Bang | Token::Asterisk) {
            self.advance();
            let op = self.previous();
            let right = self.unary()?;
            if op == Token::Bang {
                Ok(Expr::Not(Box::new(right)))
            } else if op == Token::Minus {
                Ok(Expr::Negate(Box::new(right)))
            } else {
                Ok(Expr::PointerDereference(Box::new(right)))
            }
        } else {
            self.primary()
        }
    }
    fn primary(&mut self) -> Result<Expr, ParsingError> {
        if matches!(self.peek(), Token::False) {
            return Ok(Expr::FalseLiteral);
        }
        if matches!(self.peek(), Token::True) {
            return Ok(Expr::TrueLiteral);
        }
        if let Token::Float(s) = self.peek() {
            return Ok(Expr::Float(s));
        }
        if let Token::Int(s) = self.peek() {
            return Ok(Expr::Int(s));
        }
        if let Token::Identifier(s) = self.peek() {
            return Ok(Expr::Ident(s));
        }
        if let Token::String(s) = self.peek() {
            return Ok(Expr::String(s));
        }
        if matches!(self.peek(), Token::LeftParen) {
            let expr = self.expression()?;
            if matches!(self.peek(), Token::RightParen) {
                return Ok(Expr::Grouping(Box::new(expr)));
            } else {
                return Err(ParsingError::NoClosingParenGrouping);
            }
        }
        Err(ParsingError::None) // this needs to be something different
    }
    fn sync(&mut self) {
        self.advance();

        while !self.is_end() {
            if let Token::Semicolon = self.previous() {
                return;
            }

            if matches!(
                self.peek(),
                Token::For
                    | Token::If
                    | Token::Loop
                    | Token::Return
                    | Token::Pub
                    | Token::Break
                    | Token::Continue
                    | Token::Enum
                    | Token::Defer
                    | Token::Mut
                    | Token::Con
                    | Token::Void
            ) {
                return;
            }
            self.advance();
        }
    }
    pub fn parse(&mut self) -> Option<Expr> {
        let x = self.expression();
        match x {
            Ok(e) => Some(e),
            Err(e) => {
                println!("Error {}", e);
                None
            }
        }
    }
}
