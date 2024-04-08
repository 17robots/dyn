mod lexer;

use std::{fs, path::Path};

use lexer::Lexer;

fn main() {
    let file = "main.dyn";
    let contents = fs::read_to_string(file).expect("Unable to find file");
    let mut y = Lexer::new(Path::new(&file), &contents);
    y.scan_toks().unwrap();
    println!("{:?}", y.filename);
    for x in y.toks.iter() {
        println!("{:?}", x);
    }
}
