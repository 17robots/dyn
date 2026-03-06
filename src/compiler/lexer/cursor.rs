use crate::compiler::diagnostics::SourceSpan;

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub struct CursorPosition {
    pub byte: usize,
    pub line: usize,
    pub col: usize,
}

pub struct Cursor<'a> {
    source: &'a str,
    index: usize,
    line: usize,
    col: usize,
}

impl<'a> Cursor<'a> {
    pub fn new(source: &'a str) -> Self {
        Self {
            source,
            index: 0,
            line: 1,
            col: 1,
        }
    }

    pub fn is_eof(&self) -> bool {
        self.index >= self.source.len()
    }

    pub fn position(&self) -> CursorPosition {
        CursorPosition {
            byte: self.index,
            line: self.line,
            col: self.col,
        }
    }

    pub fn peek(&self) -> Option<char> {
        self.source[self.index..].chars().next()
    }

    pub fn peek_next(&self) -> Option<char> {
        let mut chars = self.source[self.index..].chars();
        chars.next()?;
        chars.next()
    }

    pub fn bump(&mut self) -> Option<char> {
        let ch = self.peek()?;
        self.index += ch.len_utf8();
        if ch == '\n' {
            self.line += 1;
            self.col = 1;
        } else {
            self.col += 1;
        }
        Some(ch)
    }

    pub fn match_char(&mut self, expected: char) -> bool {
        if self.peek() == Some(expected) {
            let _ = self.bump();
            return true;
        }
        false
    }

    pub fn span_from(&self, start: CursorPosition) -> SourceSpan {
        SourceSpan {
            start_byte: start.byte,
            end_byte: self.index,
            start_line: start.line,
            start_col: start.col,
            end_line: self.line,
            end_col: self.col,
        }
    }
}
