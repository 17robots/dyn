use std::fmt::{self, Display};

#[derive(Debug, PartialEq, Eq, Clone)]
pub enum LexingError {
    IllegalCharacter(String, usize, usize),
    UnterminatedString(String, usize, usize),
    InvalidChar(String, usize, usize),
    UnterminatedChar(String, usize, usize),
}
impl Display for LexingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            LexingError::IllegalCharacter(s, l, c) => {
                write!(
                    f,
                    "Lexing error: Illegal character {} line {} col {}",
                    s, l, c
                )
            }
            LexingError::UnterminatedString(s, l, c) => {
                write!(
                    f,
                    "Lexing error: Unterminated string literal {} line {} col {}",
                    s, l, c
                )
            }
            LexingError::UnterminatedChar(s, l, c) => write!(
                f,
                "Lexing error: Unterminated char literal {} line {} col {}",
                s, l, c
            ),
            LexingError::InvalidChar(s, l, c) => {
                write!(
                    f,
                    "Lexing error: Invalid escape sequence {} line {} col {}",
                    s, l, c
                )
            }
        }
    }
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub enum ParsingError {
    None,
    NoClosingParenGrouping,
}

impl Display for ParsingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ParsingError::None => write!(f, "This error needs to be written"),
            ParsingError::NoClosingParenGrouping => {
                write!(f, "We dont have a closing paren for a grouping")
            }
        }
    }
}
