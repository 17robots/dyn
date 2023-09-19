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
    "++" => TokenType::Inc,
    "-" => TokenType::Sub,
    "--" => TokenType::Dec,
    "*" => TokenType::Mul,
    "/" => TokenType::Div,
    "%" => TokenType::Per,
    ";" => TokenType::Semicolon,
    ":" => TokenType::Colon,
    "=" => TokenType::Equal,
    "==" => TokenType::Eq,
    "&" => TokenType::And,
    "&&" => TokenType::LAnd,
    "|" => TokenType::Or,
    "||" => TokenType::LOr,
    "!" => TokenType::Not,
    "!=" => TokenType::Neq,
    "<" => TokenType::Lt,
    "<=" => TokenType::Lte,
    ">" => TokenType::Gt,
    ">=" => TokenType::Gte,
    "(" => TokenType::LParen,
    "[" => TokenType::LBrace,
    "{" => TokenType::LBrack,
    ")" => TokenType::RParen,
    "]" => TokenType::RBrace,
    "}" => TokenType::RBrack,
};

fn main() {
    // tokenizer
    let tokens = get_tokens(
        r#"void main() {
            io.println("hello world");
        }"#,
    );
    tokens.iter().for_each(|x| {
        println!("{:?}", x);
    });
}

fn get_tokens(stream: &str) -> Vec<TokenType> {
    let mut tokens = Vec::new();
    let mut buff = String::from("");

    if stream.len() == 0 {
        return tokens;
    }
    stream
        .replace("\n", " ")
        .split(' ')
        .map(|z| z.trim())
        .for_each(|x| {
            if x.len() > 1 {
                x.chars().for_each(|y| match y {
                    '0'..='9' | 'a'..='z' | 'A'..='Z' => {
                        buff.push(y);
                    }
                    '.' => {
                        if buff.contains('.') {}
                        if let Ok(_) = buff.parse::<i128>() {
                            buff.push(y);
                        } else {
                            tokens.push(TokenType::Identifier(buff.clone()));
                            buff.clear();
                            tokens.push(TokenType::Period);
                        }
                    }
                    ',' => {
                        if buff.len() > 0 {
                            tokens.push(TokenType::Identifier(buff.clone()));
                            buff.clear();
                        }
                        tokens.push(TokenType::Comma);
                    }
                    '\"' => {
                        if buff.contains(y) {
                            buff.remove(0); // remove matching "
                            tokens.push(TokenType::StringLiteral(buff.clone()));
                            buff.clear();
                        } else {
                            if buff.len() > 0 {
                                // handle error
                            } else {
                                buff.push(y);
                            }
                        }
                    }
                    '\'' => {
                        if buff.contains(y) {
                            // pop buff out and store as char literal
                            if buff.len() > 2 {
                                // handle error
                            } else {
                                buff.remove(0);
                                tokens.push(TokenType::Character(buff.chars().last().unwrap()));
                                buff.clear();
                            }
                        } else {
                            if buff.len() > 0 {
                                // handle error
                            } else {
                                buff.push(y);
                            }
                        }
                    }
                    '(' | '[' | '{' | ')' | ']' | '}' => {
                        if buff.len() > 0 {
                            // could be fn call or the end of an arg list
                            tokens.push(TokenType::Identifier(buff.clone()));
                            buff.clear();
                        }
                        tokens.push(OPERATORS.get(&y.to_string()).unwrap().clone());
                    }
                    ';' => {
                        if buff.len() > 0 {
                            let mut buff_tokens = get_tokens(&buff);
                            tokens.append(&mut buff_tokens);
                            buff.clear();
                        }
                        tokens.push(TokenType::Semicolon);
                    }
                    _ => {}
                });
                if buff.len() > 0 {
                    // we still have stuff left over
                    if KEYWORDS.contains_key(&buff) {
                        tokens.push(KEYWORDS.get(&buff).unwrap().clone());
                    } else {
                        if let Ok(num) = buff.parse::<i128>() {
                            tokens.push(TokenType::Integer(num));
                        } else if let Ok(num) = buff.parse::<f64>() {
                            tokens.push(TokenType::Floating(num));
                        } else {
                            tokens.push(TokenType::Identifier(buff.clone()));
                        }
                    }
                    buff.clear();
                }
            } else {
                if x.is_empty() {
                    return;
                }
                if let Some(token) = get_token_from_char(&x.chars().next().unwrap()) {
                    tokens.push(token);
                } else {
                    // TODO: handle this as an error later
                }
            }
        });
    tokens.append(&mut get_tokens(&buff));
    tokens
}

fn get_token_from_char(x: &char) -> Option<TokenType> {
    match x {
        'a'..='z' | 'A'..='Z' => Some(TokenType::Identifier(x.to_string().clone())),
        '0'..='9' => Some(TokenType::Integer(x.to_string().parse::<i128>().unwrap())),
        _ if OPERATORS.contains_key(&x.to_string()) => {
            Some(OPERATORS.get(&x.to_string()).unwrap().clone())
        }
        _ => None,
    }
}
