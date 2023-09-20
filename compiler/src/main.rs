use phf::{phf_map, Map};

// tokens
#[derive(Clone, Debug)]
enum TokenType {
    // literals
    Floating(f64),
    Identifier(String),
    Integer(i128),
    StringLiteral(String),
    Character(char),

    // operators
    Add,
    Sub,
    Mul,
    Div,
    Per,
    Inc,
    Dec,
    Semicolon,
    Colon,
    Comma,
    Equal,
    Eq,
    And,
    LAnd,
    Or,
    LOr,
    Not,
    Neq,
    Gt,
    Gte,
    Lt,
    Lte,
    LParen,
    LBrace,
    LBrack,
    RParen,
    RBrace,
    RBrack,
    Period,

    // keywords
    Void,
    Bool,
    Char,
    F32,
    F64,
    I8,
    I16,
    I32,
    I64,
    I128,
    U8,
    U16,
    U32,
    U64,
    U128,
    Mut,
    Con,
}

static KEYWORDS: Map<&str, TokenType> = phf_map! {
    "void" => TokenType::Void,
    "bool" => TokenType::Bool,
    "char" => TokenType::Char,
    "f32" => TokenType::F32,
    "f64" => TokenType::F64,
    "i8" => TokenType::I8,
    "i16" => TokenType::I16,
    "i32" => TokenType::I32,
    "i64" => TokenType::I64,
    "i128" => TokenType::I128,
    "u8" => TokenType::U8,
    "u16" => TokenType::U16,
    "u32" => TokenType::U32,
    "u64" => TokenType::U64,
    "u128" => TokenType::U128,
    "mut" => TokenType::Mut,
    "con" => TokenType::Con,
};

static OPERATORS: Map<&str, TokenType> = phf_map! {
    "+" => TokenType::Add,
    "-" => TokenType::Sub,
    "*" => TokenType::Mul,
    "/" => TokenType::Div,
    "%" => TokenType::Per,
    ";" => TokenType::Semicolon,
    ":" => TokenType::Colon,
    "=" => TokenType::Equal,
    "&" => TokenType::And,
    "|" => TokenType::Or,
    "!" => TokenType::Not,
    "<" => TokenType::Lt,
    ">" => TokenType::Gt,
    "(" => TokenType::LParen,
    "[" => TokenType::LBrace,
    "{" => TokenType::LBrack,
    ")" => TokenType::RParen,
    "]" => TokenType::RBrace,
    "}" => TokenType::RBrack,
};

static COMPOUND_OPERATORS: Map<&str, TokenType> = phf_map! {
    "--" => TokenType::Dec,
    "++" => TokenType::Inc,
    "==" => TokenType::Eq,
    "!=" => TokenType::Neq,
    ">=" => TokenType::Gte,
    "<=" => TokenType::Lte,
    "&&" => TokenType::LAnd,
    "||" => TokenType::LOr,
};

static SEPARATORS: Map<&str, TokenType> = phf_map! {
    ";" => TokenType::Semicolon,
    "," => TokenType::Comma,
};

fn main() {
    // tokenizer
    let tokens = get_tokens(r#"123.45"#);
    tokens.iter().for_each(|x| {
        println!("{:?}", x);
    });
}

fn get_tokens(stream: &str) -> Vec<TokenType> {
    let mut curr_pos: u32 = 0;
    let mut offset: i32 = -1;
    let mut tokens = Vec::new();

    loop {
        if curr_pos as usize >= stream.len() {
            break;
        }

        let ch = &stream.chars().nth(curr_pos as usize).unwrap();

        match ch {
            'a'..='z' | 'A'..='Z' | '0'..='9' => {
                if offset < 0 {
                    offset = curr_pos as i32;
                } else {
                    let buff = &stream[offset as usize..curr_pos as usize];
                    match buff {
                        _ if COMPOUND_OPERATORS.contains_key(&buff) => {
                            tokens.push(COMPOUND_OPERATORS.get(&buff).unwrap().clone());
                            offset = curr_pos as i32;
                        }
                        _ if OPERATORS.contains_key(&buff) => {
                            tokens.push(OPERATORS.get(&buff).unwrap().clone());
                            offset = curr_pos as i32;
                        }
                        _ => {} // nothing that I care about
                    }
                }
            }
            _ => {
                let mut s = String::from("");
                if offset > -1 {
                    let buff = &stream[offset as usize..curr_pos as usize];
                    match buff {
                        _ if COMPOUND_OPERATORS
                            .contains_key(&format!("{}{}", buff, ch).as_str()) =>
                        {
                            tokens.push(
                                COMPOUND_OPERATORS
                                    .get(&format!("{}{}", buff, ch).as_str())
                                    .unwrap()
                                    .clone(),
                            );
                        }
                        _ if OPERATORS.contains_key(&buff) => {
                            tokens.push(OPERATORS.get(&buff).unwrap().clone());
                        }
                        _ if KEYWORDS.contains_key(&buff) => {
                            tokens.push(KEYWORDS.get(&buff).unwrap().clone())
                        }

                        _ if is_number(buff) => s = buff.to_string(), // dont do anything
                        _ => tokens.push(TokenType::Identifier(buff.to_owned().clone())),
                    }
                    offset = if is_number(buff) { offset } else { -1 }; // keep offset for now since its a number
                }
                match ch {
                    _ if SEPARATORS.contains_key(&ch.to_string()) => {
                        if offset > -1 {
                            tokens.push(if s.contains('.') {
                                TokenType::Floating(s.parse::<f64>().unwrap())
                            } else {
                                TokenType::Integer(s.parse::<i128>().unwrap())
                            });
                        }
                        offset = -1;
                        tokens.push(SEPARATORS.get(&ch.to_string()).unwrap().clone());
                    }
                    '.' => {
                        if offset > -1 {
                            if s.contains('.') {
                                tokens.push(TokenType::Floating(s.parse::<f64>().unwrap()));
                                tokens.push(TokenType::Period);
                            }
                        } else {
                            tokens.push(TokenType::Period);
                        }
                    } // this needs to also factor in numbers but again Im too lazy rn
                    _ if OPERATORS.contains_key(&ch.to_string()) => {
                        if offset > -1 {
                            tokens.push(if s.contains('.') {
                                TokenType::Floating(s.parse::<f64>().unwrap())
                            } else {
                                TokenType::Integer(s.parse::<i128>().unwrap())
                            });
                        }
                        offset = curr_pos as i32; // move into buffer in case theres compound operator
                    }
                    _ => {} // ignore spaces and other stuff for now because I just dont care yet thisll also factor in other stuff
                }
            }
        }

        curr_pos += 1;
    }
    if offset > -1 {
        let buff = &stream[offset as usize..curr_pos as usize];
        match buff {
            _ if COMPOUND_OPERATORS.contains_key(&buff) => {
                tokens.push(COMPOUND_OPERATORS.get(&buff).unwrap().clone());
            }
            _ if OPERATORS.contains_key(&buff) => {
                tokens.push(OPERATORS.get(&buff).unwrap().clone());
            }
            _ if KEYWORDS.contains_key(&buff) => tokens.push(KEYWORDS.get(&buff).unwrap().clone()),
            _ if SEPARATORS.contains_key(&buff) => {
                tokens.push(SEPARATORS.get(&buff).unwrap().clone())
            }
            "." => tokens.push(TokenType::Period),
            _ if is_number(&buff) => tokens.push(if buff.contains('.') {
                TokenType::Floating(buff.parse::<f64>().unwrap())
            } else {
                TokenType::Integer(buff.parse::<i128>().unwrap())
            }),
            _ => tokens.push(TokenType::Identifier(buff.to_owned().clone())),
        }
    }
    tokens
}

fn is_number(s: &str) -> bool {
    if let Ok(_) = s.parse::<f64>() {
        true
    } else {
        false
    }
}
