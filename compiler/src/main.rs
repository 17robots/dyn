mod lexer;
use crate::lexer::{Tokenizer, Token};
fn main() {
    Tokenizer::init("i8 x = 5;")
        .lex()
        .into_iter()
        .for_each(|y| {
            match y {
                Token::Illegal => println!("Illegal"),
                Token::Word(x) => println!("Word: {}", x),
                Token::NumberLiteral(x) => println!("Number: {}", x),
                Token::CharLiteral(x) => println!("Character: {}", x),
                Token::StringLiteral(x) => println!("String: {}", x),
                Token::Operator(x) => println!("Operator: \"{}\"", x),
            }
        });
}
