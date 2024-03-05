mod lexer;
mod parser;

use parser::Parser;
use crate::lexer::Tokenizer;

fn main() {
    let _x = Parser::init(Tokenizer::init("i8 x = 5;").lex()).parse();
}
