mod ast;
mod error;
mod lexer;
mod parser;

use std::{fs, path::Path};

use lexer::Lexer;

fn main() {
    let file = "main.dyn";
    let contents = fs::read_to_string(file).expect("Unable to find file");
    let mut y = Lexer::new(Path::new(&file), &contents);
    y.scan_toks();
    for x in y.toks.iter() {
        println!("{}", x);
    }
    for x in y.errs.iter() {
        println!("{}", x);
    }
}
