use crate::lexer::Token;

pub trait Node<T> {
    fn accept<U: Visitor<T>>(&self, v: &mut U) -> T;
}

#[derive(Debug)]
pub enum Expr {
    // binary
    Multiply(Box<Expr>, Box<Expr>),
    MultiplyEqual(Box<Expr>, Box<Expr>),
    Mod(Box<Expr>, Box<Expr>),
    ModEqual(Box<Expr>, Box<Expr>),
    Slash(Box<Expr>, Box<Expr>),
    SlashEqual(Box<Expr>, Box<Expr>),
    Plus(Box<Expr>, Box<Expr>),
    PlusEqual(Box<Expr>, Box<Expr>),
    Minus(Box<Expr>, Box<Expr>),
    MinusEqual(Box<Expr>, Box<Expr>),
    GreaterThan(Box<Expr>, Box<Expr>),
    GreaterThanEqual(Box<Expr>, Box<Expr>),
    LessThan(Box<Expr>, Box<Expr>),
    LessThanEqual(Box<Expr>, Box<Expr>),
    Equal(Box<Expr>, Box<Expr>),
    EqualEqual(Box<Expr>, Box<Expr>),
    BangEqual(Box<Expr>, Box<Expr>),
    LogicalAnd(Box<Expr>, Box<Expr>),
    LogicalOr(Box<Expr>, Box<Expr>),
    And(Box<Expr>, Box<Expr>),
    AndEqual(Box<Expr>, Box<Expr>),
    Or(Box<Expr>, Box<Expr>),
    OrEqual(Box<Expr>, Box<Expr>),
    Xor(Box<Expr>, Box<Expr>),
    XorEqual(Box<Expr>, Box<Expr>),
    LShift(Box<Expr>, Box<Expr>),
    LShiftEqual(Box<Expr>, Box<Expr>),
    RShift(Box<Expr>, Box<Expr>),
    RShiftEqual(Box<Expr>, Box<Expr>),

    // unary
    Not(Box<Expr>),
    PointerDereference(Box<Expr>), // *x
    ReferenceGrab(Box<Expr>), // &x
    Negate(Box<Expr>) // -x
}

pub enum Stmt {}

impl<T> Node<T> for Expr {
    fn accept<U: Visitor<T>>(&self, v: &mut U) -> T {
        v.visit_expr(self)
    }
}
impl<T> Node<T> for Stmt {
    fn accept<U: Visitor<T>>(&self, v: &mut U) -> T {
        v.visit_stmt(self)
    }
}

pub trait Visitor<T> {
    fn visit_expr(&mut self, e: &Expr) -> T;
    fn visit_stmt(&mut self, s: &Stmt) -> T;
}

pub struct Printer {} // example

impl Visitor<String> for Printer {
    fn visit_expr(&mut self, e: &Expr) -> String {
        match e {
            Expr::Multiply(_, _) => todo!(),
            Expr::MultiplyEqual(_, _) => todo!(),
            Expr::Mod(_, _) => todo!(),
            Expr::ModEqual(_, _) => todo!(),
            Expr::Slash(_, _) => todo!(),
            Expr::SlashEqual(_, _) => todo!(),
            Expr::Plus(_, _) => todo!(),
            Expr::PlusEqual(_, _) => todo!(),
            Expr::Minus(_, _) => todo!(),
            Expr::MinusEqual(_, _) => todo!(),
            Expr::GreaterThan(_, _) => todo!(),
            Expr::GreaterThanEqual(_, _) => todo!(),
            Expr::LessThan(_, _) => todo!(),
            Expr::LessThanEqual(_, _) => todo!(),
            Expr::Equal(_, _) => todo!(),
            Expr::EqualEqual(_, _) => todo!(),
            Expr::BangEqual(_, _) => todo!(),
            Expr::LogicalAnd(_, _) => todo!(),
            Expr::LogicalOr(_, _) => todo!(),
            Expr::And(_, _) => todo!(),
            Expr::AndEqual(_, _) => todo!(),
            Expr::Or(_, _) => todo!(),
            Expr::OrEqual(_, _) => todo!(),
            Expr::Xor(_, _) => todo!(),
            Expr::XorEqual(_, _) => todo!(),
            Expr::LShift(_, _) => todo!(),
            Expr::LShiftEqual(_, _) => todo!(),
            Expr::RShift(_, _) => todo!(),
            Expr::RShiftEqual(_, _) => todo!(),
            Expr::Not(_) => todo!(),
            Expr::PointerDereference(_) => todo!(),
            Expr::ReferenceGrab(_) => todo!(),
            Expr::Negate(_) => todo!(),
        }
    }

    fn visit_stmt(&mut self, s: &Stmt) -> String {
        todo!()
    }
}
