mod lexer;
mod ast;
mod parser;

use lexer::Scanner;

fn main() {
    let mut y = Scanner::new(&"main.dyn".to_string(), &"i8 x = 5;".to_string());
    y.scan_toks().unwrap();
    for x in y.toks.iter() {
        println!("{:?}", x);
    }
}
