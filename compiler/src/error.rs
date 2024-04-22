use std::fmt::Display;

pub enum LexerError {
    NewLineInString(usize, usize),
    UnterminatedString(usize, usize),
    MoreThanOneCharacterInChar(usize, usize),
    UnterminatedChar(usize, usize),
    InvalidEscape(usize, usize),
}

impl Display for LexerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LexerError::NewLineInString(l, c) => write!(f, "New line in string: {}:{}", l, c),
            LexerError::UnterminatedString(l, c) => write!(f, "Unterminated string: {}:{}", l, c),
            LexerError::MoreThanOneCharacterInChar(l, c) => {
                write!(f, "More than single character in char literal: {}:{}", l, c)
            }
            LexerError::UnterminatedChar(l, c) => write!(f, "Unterminated char: {}:{}", l, c),
            LexerError::InvalidEscape(l, c) => write!(f, "Invalid escape sequence: {}:{}", l, c),
        }
    }
}
