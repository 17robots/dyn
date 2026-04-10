// cursor
use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase, SourceSpan};
use std::path::PathBuf;

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

pub struct LexOutput {
    pub tokens: Vec<Token>,
    pub diagnostics: Vec<Diagnostic>,
}

pub struct Lexer<'a> {
    cursor: Cursor<'a>,
    source: &'a str,
    file_path: PathBuf,
    diagnostics: Vec<Diagnostic>,
    tokens: Vec<Token>,
}

impl<'a> Lexer<'a> {
    pub fn new(source: &'a str, file_path: PathBuf) -> Self {
        Self {
            cursor: Cursor::new(source),
            source,
            file_path,
            diagnostics: Vec::new(),
            tokens: Vec::new(),
        }
    }

    pub fn lex(mut self) -> LexOutput {
        while !self.cursor.is_eof() {
            self.skip_whitespace();
            if self.cursor.is_eof() {
                break;
            }

            if self.lex_comment_or_doc_comment() {
                continue;
            }

            let start = self.cursor.position();
            let current = match self.cursor.peek() {
                Some(ch) => ch,
                None => break,
            };

            if is_identifier_start(current) {
                self.lex_identifier(start);
                continue;
            }

            if current == '$' {
                self.lex_builtin_identifier(start);
                continue;
            }

            if current == '"' {
                self.lex_string_literal(start);
                continue;
            }

            if current == '\'' {
                self.lex_char_literal(start);
                continue;
            }

            if current.is_ascii_digit() {
                self.lex_number(start, false);
                continue;
            }

            if current == '.' && matches!(self.cursor.peek_next(), Some(ch) if ch.is_ascii_digit())
            {
                self.lex_number(start, true);
                continue;
            }

            if self.lex_operator_or_delimiter(start) {
                continue;
            }

            self.emit_unexpected_character(start, current);
            let _ = self.cursor.bump();
        }

        let eof_pos = self.cursor.position();
        self.tokens.push(Token {
            kind: TokenKind::Eof,
            lexeme: String::new(),
            span: self.cursor.span_from(eof_pos),
        });

        LexOutput {
            tokens: self.tokens,
            diagnostics: self.diagnostics,
        }
    }

    fn skip_whitespace(&mut self) {
        while matches!(self.cursor.peek(), Some(ch) if ch.is_whitespace()) {
            let _ = self.cursor.bump();
        }
    }

    fn lex_comment_or_doc_comment(&mut self) -> bool {
        if self.cursor.peek() != Some('/') {
            return false;
        }

        match self.cursor.peek_next() {
            Some('/') => {
                let start = self.cursor.position();
                let _ = self.cursor.bump();
                let _ = self.cursor.bump();

                if self.cursor.match_char('/') {
                    let text_start = self.cursor.position().byte;
                    while !matches!(self.cursor.peek(), None | Some('\n')) {
                        let _ = self.cursor.bump();
                    }
                    let text_end = self.cursor.position().byte;
                    let lexeme = self.source[text_start..text_end].to_string();
                    self.tokens.push(Token {
                        kind: TokenKind::DocComment,
                        lexeme,
                        span: self.cursor.span_from(start),
                    });
                } else {
                    while !matches!(self.cursor.peek(), None | Some('\n')) {
                        let _ = self.cursor.bump();
                    }
                }

                true
            }
            Some('*') => {
                let start = self.cursor.position();
                let _ = self.cursor.bump();
                let _ = self.cursor.bump();

                let mut closed = false;
                while let Some(ch) = self.cursor.bump() {
                    if ch == '*' && self.cursor.match_char('/') {
                        closed = true;
                        break;
                    }
                }

                if !closed {
                    let span = self.cursor.span_from(start);
                    self.diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::Lexer,
                            DiagnosticCode::E2004,
                            "unterminated block comment",
                        )
                        .with_primary_file_label(
                            self.file_path.clone(),
                            Some(span),
                            "block comment starts here but is never closed",
                        ),
                    );
                }

                true
            }
            _ => false,
        }
    }

    fn lex_identifier(&mut self, start: CursorPosition) {
        while matches!(self.cursor.peek(), Some(ch) if is_identifier_continue(ch)) {
            let _ = self.cursor.bump();
        }

        let span = self.cursor.span_from(start);
        let lexeme = self.source[span.start_byte..span.end_byte].to_string();
        let kind = keyword_from_identifier(&lexeme).unwrap_or(TokenKind::Identifier);

        self.tokens.push(Token { kind, lexeme, span });
    }

    fn lex_builtin_identifier(&mut self, start: CursorPosition) {
        let _ = self.cursor.bump();

        match self.cursor.peek() {
            Some(ch) if is_identifier_start(ch) => {
                while matches!(self.cursor.peek(), Some(ch) if is_identifier_continue(ch)) {
                    let _ = self.cursor.bump();
                }

                let span = self.cursor.span_from(start);
                let lexeme = self.source[span.start_byte..span.end_byte].to_string();
                self.tokens.push(Token {
                    kind: TokenKind::BuiltinIdentifier,
                    lexeme,
                    span,
                });
            }
            _ => {
                let span = self.cursor.span_from(start);
                self.diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::Lexer,
                        DiagnosticCode::E2006,
                        "invalid builtin identifier",
                    )
                    .with_primary_file_label(
                        self.file_path.clone(),
                        Some(span),
                        "expected identifier after '$'",
                    ),
                );
            }
        }
    }

    fn lex_string_literal(&mut self, start: CursorPosition) {
        let _ = self.cursor.bump();
        let mut terminated = false;

        while let Some(ch) = self.cursor.peek() {
            if ch == '"' {
                let _ = self.cursor.bump();
                terminated = true;
                break;
            }

            if ch == '\n' {
                break;
            }

            if ch == '\\' {
                let _ = self.cursor.bump();
                match self.cursor.peek() {
                    Some('x') => {
                        let _ = self.cursor.bump();
                        for _ in 0..2 {
                            if matches!(self.cursor.peek(), Some(c) if c.is_ascii_hexdigit()) {
                                let _ = self.cursor.bump();
                            }
                        }
                    }
                    Some(escape) if is_valid_escape_char(escape) => {
                        let _ = self.cursor.bump();
                    }
                    _ => break,
                }
                continue;
            }

            let _ = self.cursor.bump();
        }

        let span = self.cursor.span_from(start);
        let lexeme = self.source[span.start_byte..span.end_byte].to_string();

        if !terminated {
            self.diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::Lexer,
                    DiagnosticCode::E2002,
                    "unterminated string literal",
                )
                .with_primary_file_label(
                    self.file_path.clone(),
                    Some(span),
                    "string literal starts here but does not terminate",
                ),
            );
        }

        self.tokens.push(Token {
            kind: TokenKind::StringLiteral,
            lexeme,
            span,
        });
    }

    fn lex_char_literal(&mut self, start: CursorPosition) {
        let _ = self.cursor.bump();
        let mut valid = true;
        let mut terminated = false;

        match self.cursor.peek() {
            Some('\\') => {
                let _ = self.cursor.bump();
                match self.cursor.peek() {
                    Some('x') => {
                        let _ = self.cursor.bump();
                        for _ in 0..2 {
                            if matches!(self.cursor.peek(), Some(c) if c.is_ascii_hexdigit()) {
                                let _ = self.cursor.bump();
                            }
                        }
                    }
                    Some(escape) if is_valid_escape_char(escape) => {
                        let _ = self.cursor.bump();
                    }
                    _ => {
                        valid = false;
                    }
                }
            }
            Some('\'') | Some('\n') | None => {
                valid = false;
            }
            Some(_) => {
                let _ = self.cursor.bump();
            }
        }

        if self.cursor.match_char('\'') {
            terminated = true;
        } else {
            valid = false;
            while !matches!(self.cursor.peek(), None | Some('\n') | Some('\'')) {
                let _ = self.cursor.bump();
            }
            if self.cursor.match_char('\'') {
                terminated = true;
            }
        }

        let span = self.cursor.span_from(start);
        let lexeme = self.source[span.start_byte..span.end_byte].to_string();

        if !valid || !terminated {
            self.diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::Lexer,
                    DiagnosticCode::E2003,
                    "invalid char literal",
                )
                .with_primary_file_label(
                    self.file_path.clone(),
                    Some(span),
                    "char literal must contain exactly one character or one valid escape",
                ),
            );
        }

        self.tokens.push(Token {
            kind: TokenKind::CharLiteral,
            lexeme,
            span,
        });
    }

    fn lex_number(&mut self, start: CursorPosition, starts_with_dot: bool) {
        let mut is_float = false;
        let mut is_valid = true;

        if starts_with_dot {
            is_float = true;
            let _ = self.cursor.bump();
            let (has_frac_digits, frac_valid) =
                self.consume_digits_with_underscores(|ch| ch.is_ascii_digit());
            is_valid &= has_frac_digits && frac_valid;

            if self.consume_decimal_exponent() {
                is_valid &= self.last_exponent_valid();
            }

            if self.has_invalid_numeric_trailer() {
                is_valid = false;
                self.consume_invalid_numeric_trailer();
            }
        } else if self.cursor.peek() == Some('0') {
            match self.cursor.peek_next() {
                Some('b') | Some('B') => {
                    let _ = self.cursor.bump();
                    let _ = self.cursor.bump();
                    let (has_digits, digits_valid) =
                        self.consume_digits_with_underscores(|ch| matches!(ch, '0' | '1'));
                    is_valid &= has_digits && digits_valid;
                    if self.has_invalid_numeric_trailer() {
                        is_valid = false;
                        self.consume_invalid_numeric_trailer();
                    }
                }
                Some('o') | Some('O') => {
                    let _ = self.cursor.bump();
                    let _ = self.cursor.bump();
                    let (has_digits, digits_valid) =
                        self.consume_digits_with_underscores(|ch| matches!(ch, '0'..='7'));
                    is_valid &= has_digits && digits_valid;
                    if self.has_invalid_numeric_trailer() {
                        is_valid = false;
                        self.consume_invalid_numeric_trailer();
                    }
                }
                Some('x') | Some('X') => {
                    let _ = self.cursor.bump();
                    let _ = self.cursor.bump();

                    let (has_int_digits, int_valid) =
                        self.consume_digits_with_underscores(|ch| ch.is_ascii_hexdigit());
                    is_valid &= int_valid;

                    let mut has_dot = false;
                    let mut has_frac_digits = false;
                    let mut frac_valid = true;

                    if self.cursor.peek() == Some('.') && self.cursor.peek_next() != Some('.') {
                        has_dot = true;
                        is_float = true;
                        let _ = self.cursor.bump();
                        let (frac_digits, frac_ok) =
                            self.consume_digits_with_underscores(|ch| ch.is_ascii_hexdigit());
                        has_frac_digits = frac_digits;
                        frac_valid = frac_ok;
                    }

                    let has_p_exponent = self.consume_hex_exponent();
                    if has_p_exponent {
                        is_float = true;
                        is_valid &= self.last_exponent_valid();
                    }

                    if has_dot && !has_p_exponent {
                        is_valid = false;
                    }

                    if !(has_int_digits || has_frac_digits) {
                        is_valid = false;
                    }

                    is_valid &= frac_valid;

                    if self.has_invalid_numeric_trailer() {
                        is_valid = false;
                        self.consume_invalid_numeric_trailer();
                    }
                }
                _ => {
                    let (has_digits, digits_valid) =
                        self.consume_digits_with_underscores(|ch| ch.is_ascii_digit());
                    is_valid &= has_digits && digits_valid;

                    if self.cursor.peek() == Some('.') && self.cursor.peek_next() != Some('.') {
                        is_float = true;
                        let _ = self.cursor.bump();
                        let (_, frac_valid) =
                            self.consume_digits_with_underscores(|ch| ch.is_ascii_digit());
                        is_valid &= frac_valid;
                    }

                    if self.consume_decimal_exponent() {
                        is_float = true;
                        is_valid &= self.last_exponent_valid();
                    }

                    if self.has_invalid_numeric_trailer() {
                        is_valid = false;
                        self.consume_invalid_numeric_trailer();
                    }
                }
            }
        } else {
            let (has_digits, digits_valid) =
                self.consume_digits_with_underscores(|ch| ch.is_ascii_digit());
            is_valid &= has_digits && digits_valid;

            if self.cursor.peek() == Some('.') && self.cursor.peek_next() != Some('.') {
                is_float = true;
                let _ = self.cursor.bump();
                let (_, frac_valid) =
                    self.consume_digits_with_underscores(|ch| ch.is_ascii_digit());
                is_valid &= frac_valid;
            }

            if self.consume_decimal_exponent() {
                is_float = true;
                is_valid &= self.last_exponent_valid();
            }

            if self.has_invalid_numeric_trailer() {
                is_valid = false;
                self.consume_invalid_numeric_trailer();
            }
        }

        let span = self.cursor.span_from(start);
        let lexeme = self.source[span.start_byte..span.end_byte].to_string();

        if !is_valid {
            self.diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::Lexer,
                    DiagnosticCode::E2005,
                    format!("invalid numeric literal '{lexeme}'"),
                )
                .with_primary_file_label(
                    self.file_path.clone(),
                    Some(span),
                    "numeric literal does not follow language rules",
                ),
            );
        }

        self.tokens.push(Token {
            kind: if is_float {
                TokenKind::FloatLiteral
            } else {
                TokenKind::IntLiteral
            },
            lexeme,
            span,
        });
    }

    fn consume_digits_with_underscores(
        &mut self,
        is_valid_digit: impl Fn(char) -> bool,
    ) -> (bool, bool) {
        let mut saw_digit = false;
        let mut prev_was_underscore = false;
        let mut valid = true;

        while let Some(ch) = self.cursor.peek() {
            if ch == '_' {
                if !saw_digit || prev_was_underscore {
                    valid = false;
                }
                prev_was_underscore = true;
                let _ = self.cursor.bump();
                continue;
            }

            if is_valid_digit(ch) {
                saw_digit = true;
                prev_was_underscore = false;
                let _ = self.cursor.bump();
                continue;
            }

            break;
        }

        if prev_was_underscore {
            valid = false;
        }

        (saw_digit, valid)
    }

    fn consume_decimal_exponent(&mut self) -> bool {
        if !matches!(self.cursor.peek(), Some('e' | 'E')) {
            return false;
        }

        let _ = self.cursor.bump();
        if matches!(self.cursor.peek(), Some('+' | '-')) {
            let _ = self.cursor.bump();
        }
        true
    }

    fn consume_hex_exponent(&mut self) -> bool {
        if !matches!(self.cursor.peek(), Some('p' | 'P')) {
            return false;
        }

        let _ = self.cursor.bump();
        if matches!(self.cursor.peek(), Some('+' | '-')) {
            let _ = self.cursor.bump();
        }
        true
    }

    fn last_exponent_valid(&mut self) -> bool {
        let (has_digits, digits_valid) =
            self.consume_digits_with_underscores(|ch| ch.is_ascii_digit());
        has_digits && digits_valid
    }

    fn has_invalid_numeric_trailer(&self) -> bool {
        match self.cursor.peek() {
            Some('.') if self.cursor.peek_next() == Some('.') => false,
            Some(ch) => ch.is_ascii_alphanumeric() || ch == '_' || ch == '.',
            None => false,
        }
    }

    fn consume_invalid_numeric_trailer(&mut self) {
        while matches!(
            self.cursor.peek(),
            Some(ch) if ch.is_ascii_alphanumeric() || ch == '_' || ch == '.'
        ) {
            let _ = self.cursor.bump();
        }
    }

    fn lex_operator_or_delimiter(&mut self, start: CursorPosition) -> bool {
        let Some(ch) = self.cursor.bump() else {
            return false;
        };

        let kind = match ch {
            '(' => TokenKind::Delimiter(Delimiter::LParen),
            ')' => TokenKind::Delimiter(Delimiter::RParen),
            '{' => TokenKind::Delimiter(Delimiter::LBrace),
            '}' => TokenKind::Delimiter(Delimiter::RBrace),
            '[' => TokenKind::Delimiter(Delimiter::LBracket),
            ']' => TokenKind::Delimiter(Delimiter::RBracket),
            ',' => TokenKind::Delimiter(Delimiter::Comma),
            ';' => TokenKind::Delimiter(Delimiter::Semicolon),
            ':' => TokenKind::Operator(Operator::Colon),
            '=' => {
                if self.cursor.match_char('>') {
                    TokenKind::Operator(Operator::FatArrow)
                } else if self.cursor.match_char('=') {
                    TokenKind::Operator(Operator::EqualEqual)
                } else {
                    TokenKind::Operator(Operator::Equal)
                }
            }
            '+' => {
                if self.cursor.match_char('=') {
                    TokenKind::Operator(Operator::PlusEqual)
                } else {
                    TokenKind::Operator(Operator::Plus)
                }
            }
            '-' => {
                if self.cursor.match_char('=') {
                    TokenKind::Operator(Operator::MinusEqual)
                } else {
                    TokenKind::Operator(Operator::Minus)
                }
            }
            '*' => {
                if self.cursor.match_char('=') {
                    TokenKind::Operator(Operator::StarEqual)
                } else {
                    TokenKind::Operator(Operator::Star)
                }
            }
            '/' => {
                if self.cursor.match_char('=') {
                    TokenKind::Operator(Operator::SlashEqual)
                } else {
                    TokenKind::Operator(Operator::Slash)
                }
            }
            '%' => {
                if self.cursor.match_char('=') {
                    TokenKind::Operator(Operator::PercentEqual)
                } else {
                    TokenKind::Operator(Operator::Percent)
                }
            }
            '.' => {
                if self.cursor.match_char('.') {
                    if self.cursor.match_char('=') {
                        TokenKind::Operator(Operator::DotDotEq)
                    } else {
                        TokenKind::Operator(Operator::DotDot)
                    }
                } else if self.cursor.match_char('*') {
                    TokenKind::Operator(Operator::DotStar)
                } else if self.cursor.match_char('!') {
                    TokenKind::Operator(Operator::DotBang)
                } else if self.cursor.match_char('?') {
                    TokenKind::Operator(Operator::DotQuestion)
                } else {
                    TokenKind::Operator(Operator::Dot)
                }
            }
            '<' => {
                if self.cursor.match_char('<') {
                    if self.cursor.match_char('=') {
                        TokenKind::Operator(Operator::LeftShiftEqual)
                    } else {
                        TokenKind::Operator(Operator::LeftShift)
                    }
                } else if self.cursor.match_char('=') {
                    TokenKind::Operator(Operator::LessEqual)
                } else {
                    TokenKind::Operator(Operator::Less)
                }
            }
            '>' => {
                if self.cursor.match_char('>') {
                    if self.cursor.match_char('=') {
                        TokenKind::Operator(Operator::RightShiftEqual)
                    } else {
                        TokenKind::Operator(Operator::RightShift)
                    }
                } else if self.cursor.match_char('=') {
                    TokenKind::Operator(Operator::GreaterEqual)
                } else {
                    TokenKind::Operator(Operator::Greater)
                }
            }
            '!' => {
                if self.cursor.match_char('=') {
                    TokenKind::Operator(Operator::BangEqual)
                } else {
                    TokenKind::Operator(Operator::Bang)
                }
            }
            '&' => {
                if self.cursor.match_char('&') {
                    TokenKind::Operator(Operator::AndAnd)
                } else if self.cursor.match_char('=') {
                    TokenKind::Operator(Operator::AmpersandEqual)
                } else {
                    TokenKind::Operator(Operator::Ampersand)
                }
            }
            '|' => {
                if self.cursor.match_char('|') {
                    TokenKind::Operator(Operator::OrOr)
                } else if self.cursor.match_char('=') {
                    TokenKind::Operator(Operator::PipeEqual)
                } else {
                    TokenKind::Operator(Operator::Pipe)
                }
            }
            '^' => {
                if self.cursor.match_char('=') {
                    TokenKind::Operator(Operator::CaretEqual)
                } else {
                    TokenKind::Operator(Operator::Caret)
                }
            }
            '~' => TokenKind::Operator(Operator::Tilde),
            '?' => TokenKind::Operator(Operator::Question),
            _ => return false,
        };

        let span = self.cursor.span_from(start);
        let lexeme = self.source[span.start_byte..span.end_byte].to_string();
        self.tokens.push(Token { kind, lexeme, span });
        true
    }

    fn emit_unexpected_character(&mut self, start: CursorPosition, ch: char) {
        let span = self.cursor.span_from(start);
        self.diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::Lexer,
                DiagnosticCode::E2001,
                format!("unexpected character '{ch}'"),
            )
            .with_primary_file_label(
                self.file_path.clone(),
                Some(span),
                "remove or replace this character",
            ),
        );
    }
}

fn is_identifier_start(ch: char) -> bool {
    ch.is_ascii_alphabetic() || ch == '_'
}
fn is_identifier_continue(ch: char) -> bool {
    ch.is_ascii_alphanumeric() || ch == '_'
}
fn is_valid_escape_char(ch: char) -> bool {
    matches!(ch, 'n' | 'r' | 't' | '\\' | '\'' | '"' | '0')
}
// token
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Token {
    pub kind: TokenKind,
    pub lexeme: String,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TokenKind {
    Identifier,
    BuiltinIdentifier,
    IntLiteral,
    FloatLiteral,
    StringLiteral,
    CharLiteral,
    BoolLiteral(bool),
    NullLiteral,
    DocComment,
    Keyword(Keyword),
    Operator(Operator),
    Delimiter(Delimiter),
    Eof,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash)]
pub enum Keyword {
    Module,
    Extern,
    Pub,
    Mut,
    Use,
    Packed,
    Struct,
    Enum,
    If,
    Else,
    Match,
    For,
    Break,
    Continue,
    Return,
    Defer,
    Inline,
    Comp,
    Or,
    Type,
}

pub const KEYWORDS: &[(&str, Keyword)] = &[
    ("module", Keyword::Module),
    ("extern", Keyword::Extern),
    ("pub", Keyword::Pub),
    ("mut", Keyword::Mut),
    ("use", Keyword::Use),
    ("packed", Keyword::Packed),
    ("struct", Keyword::Struct),
    ("enum", Keyword::Enum),
    ("if", Keyword::If),
    ("else", Keyword::Else),
    ("match", Keyword::Match),
    ("for", Keyword::For),
    ("break", Keyword::Break),
    ("continue", Keyword::Continue),
    ("return", Keyword::Return),
    ("defer", Keyword::Defer),
    ("inline", Keyword::Inline),
    ("comp", Keyword::Comp),
    ("or", Keyword::Or),
    ("type", Keyword::Type),
];

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash)]
pub enum Operator {
    Dot,
    DotDot,
    DotDotEq,
    DotStar,
    DotBang,
    DotQuestion,
    Colon,
    Equal,
    FatArrow,
    Plus,
    Minus,
    Star,
    Slash,
    Percent,
    PlusEqual,
    MinusEqual,
    StarEqual,
    SlashEqual,
    PercentEqual,
    EqualEqual,
    BangEqual,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    AndAnd,
    OrOr,
    Bang,
    Ampersand,
    Pipe,
    Caret,
    Tilde,
    LeftShift,
    RightShift,
    AmpersandEqual,
    PipeEqual,
    CaretEqual,
    LeftShiftEqual,
    RightShiftEqual,
    Question,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash)]
pub enum Delimiter {
    LParen,
    RParen,
    LBrace,
    RBrace,
    LBracket,
    RBracket,
    Comma,
    Semicolon,
}

pub fn keyword_from_identifier(identifier: &str) -> Option<TokenKind> {
    if identifier == "true" {
        return Some(TokenKind::BoolLiteral(true));
    }

    if identifier == "false" {
        return Some(TokenKind::BoolLiteral(false));
    }

    if identifier == "null" {
        return Some(TokenKind::NullLiteral);
    }

    KEYWORDS
        .iter()
        .find_map(|(word, keyword)| (*word == identifier).then_some(TokenKind::Keyword(*keyword)))
}
