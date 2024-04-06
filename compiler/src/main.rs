mod lexer2;

use std::path::Path;

use lexer2::Lexer;

fn main() {
    let file = "./main.dyn";
    let source = "i8 x = 5;";
    let mut y = Lexer::new(Path::new(file), source);
    y.scan_toks().unwrap();
    for x in y.toks.iter() {
        println!("{:?}", x);
    }
}
