const std = @import("std");

pub const File = struct {
    name: []const u8,
    relevant_bytes: []const u8,
};

pub const Tag = enum {
    // general / literals
    invalid,
    eof,
    num_literal,
    string_literal,
    char_literal,
    // symbols
    plus,
    plus_plus,
    plus_equal,
    minus,
    minus_minus,
    plus_equal,
    asterisk,
    asterisk_equal,
    slash,
    slash_equal,
    percent,
    percent_equal,
    equal,
    equal_equal,
    bang,
    bang_equal,
    ampersand,
    ampersand_ampersand,
    ampersand_equal,
    pipe,
    pipe_pipe,
    pipe_equal,
    less_than,
    less_than_equal,
    greater_than,
    greater_than_equal,
    l_paren,
    r_paren,
    l_bracket,
    r_bracket,
    l_brace,
    r_brace,
    period,
    comma,
    colon,
    semicolon,
    // keywords
    keyword_if,
    keyword_else,
    keyword_struct,
    keyword_loop,
    keyword_true,
    keyword_false,
    keyword_import,
    keyword_pub,
    keyword_con,
    keyword_mut,
    keyword_type,
    keyword_trait,
    keyword_enum,
};

pub const Loc = struct {
    file: *File,
    start: usize,
    end: usize,
};

pub const Token = struct {
    loc: Loc,
    tag: Tag,
};

pub const Tokenizer = struct {
    file: *File,
    state: ReadStates,
    index: usize,

    pub fn init() Tokenizer {}

    pub const ReadStates = enum {
        start,
        identifier,
        literal_number,
        literal_string,
        literal_char,
    };

    pub fn next(self: *Tokenizer) Token {
        const c = self.file.buf[self.index];
        var tok: Token = .{ .loc = .{
            .file = self.file,
            .start = 0,
            .end = undefined,
        }, .tag = undefined };
        switch (c) {
            '0'...'9' => switch (self.state) {},
            'a'...'z', 'A'...'Z', '_' => switch (self.state) {},
            '"' => switch (self.state) {
                .start => {},
                .string_literal => {},
                else => {},
            },
            '\\' => switch (self.state) {
                .start => {},
                else => {},
            },
            '\'' => switch (self.state) {
                .start => {},
                else => {},
            },
            '<' => switch (self.state) {
                .start => {},
                else => {},
            },
            '>' => switch (self.state) {
                .start => {},
                else => {},
            },
            '=' => switch (self.state) {
                .start => {},
                .ampersand => {},
                .asterisk => {},
                .percent => {},
                .plus => {},
                .minus => {},
                .bang => {},
                .pipe => {},
                .equal => {},
                else => {
                    tok.tag = .equal;
                },
            },
            '+' => switch (self.state) {
                .start => {},
                .plus => {},
                else => {},
            },
            '-' => switch (self.state) {
                .start => {},
                else => {},
            },
            '/' => switch (self.state) {
                .start => {},
                else => {},
            },
            '*' => switch (self.state) {
                .start => {},
                else => {},
            },
            '|' => switch (self.state) {
                .start => {},
                else => {},
            },
            '&' => switch (self.state) {
                .start => {},
                else => {},
            },
            '!' => switch (self.state) {
                .start => {},
                else => {},
            },
            '?' => switch (self.state) {
                .start => {},
                else => {},
            },
            ',' => switch (self.state) {
                .start => {},
                else => {},
            },
            ';' => switch (self.state) {
                .start => {},
                else => {},
            },
            ':' => switch (self.state) {
                .start => {},
                else => {},
            },
            '(' => switch (self.state) {
                .start => {},
                else => {},
            },
            ')' => switch (self.state) {
                .start => {},
                else => {},
            },
            '[' => switch (self.state) {
                .start => {},
                else => {},
            },
            ']' => switch (self.state) {
                .start => {},
                else => {},
            },
            '{' => switch (self.state) {
                .start => {},
                else => {},
            },
            '}' => switch (self.state) {
                .start => {},
                else => {},
            },
            ' ', '\n', '\r' => switch (self.state) {
                .start => {},
                else => {},
            },
            else => switch (self.state) {
                .start => {},
                else => {},
            },
        }
    }
};
