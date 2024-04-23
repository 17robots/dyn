use std::fs;

use lexer::Lexer;

mod error;
mod lexer;
mod parser;
mod token;

fn main() {
    let mut l = Lexer::new(fs::read_to_string("./main.dyn").unwrap());
    println!("file len: {}", l.s.len());
    l.next();
    loop {
        match l.tok {
            Ok(ref s) => match s {
                Some(t) => {
                    println!("{:?}", t);
                    if matches!(t, token::Token::Eof) {
                        break;
                    }
                }
                None => break,
            },
            Err(e) => {
                println!("{}", e);
                break;
            }
        }
        l.next();
    }
}
