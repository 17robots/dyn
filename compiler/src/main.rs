mod lexer;

use std::{fs, path::Path};

use lexer::Lexer;

fn main() {
    let file = "./main.dyn";
    let contents = fs::read_to_string(file).expect("Unable to find file");
    let mut y = Lexer::new(Path::new(&file), &contents);
    println!("{:?}", y.scan_toks());
    if y.errs.len() > 0 {
        for x in y.errs.iter() {
            println!("{}", x);
        }
    } else {
        for x in y.errs.iter() {
            println!("{}", x);
        }
    }
}
