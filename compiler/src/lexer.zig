const std = @import("std");
const Token = @import("token.zig");
const CompilerError = @import("errors.zig").CompilerError;
const KWDS = std.ComptimeStringMap(Token.TokenType, .{
    .{ "mut", .Mut },
    .{ "if", .If },
    .{ "for", .For },
    .{ "con", .Con },
    .{ "match", .Match },
    .{ "true", .True },
    .{ "false", .False },
    .{ "break", .Break },
    .{ "continue", .Continue },
    .{ "defer", .Defer },
    .{ "enum", .Enum },
    .{ "struct", .Struct },
    .{ "pub", .Pub },
    .{ "void", .Void },
    .{ "return", .Return },
    .{ "from", .From },
    .{ "use", .Use },
    .{ "type", .Type },
});

pub const Lexer = struct {
    l: usize,
    c: usize,
    s: []u8,
    curr: usize,
    tok: Token.Token,
    err: ?CompilerError,

    // fns
    pub fn init(s: []u8) Lexer {
        return Lexer{
            .l = 1,
            .c = 1,
            .s = s,
            .curr = 0,
            .tok = .{ .type = .None, .lit = "" },
            .err = null,
        };
    }
    pub fn ch(s: *Lexer) u8 {
        if (s.curr >= s.s.len) {
            return '\\';
        } else {
            return s.s[s.curr];
        }
    }
    pub fn next(s: *Lexer) void {
        if (s.tok.type == .Eof) {
            return;
        }
        redo: while (true) {
            if (s.is_end()) {
                s.tok.type = .Eof;
                s.tok.lit = "";
            }
            while (switch (s.ch()) {
                ' ', '\t', '\n', '\r' => true,
                else => false,
            }) {
                s.advance();
            }
            if (s.is_end()) {
                s.tok.type = .Eof;
                s.tok.lit = "";
                return;
            }
            switch (s.ch()) {
                'a'...'z', 'A'...'Z', '_' => s.ident(),
                '0', '1', '2', '3', '4', '5', '6', '7', '8', '9' => s.number(),
                '"' => s.string(),
                '`' => s.raw_string(),
                '\'' => s.char(),
                '(' => {
                    s.advance();
                    s.tok.type = .LParen;
                    s.tok.lit = "";
                },
                ')' => {
                    s.advance();
                    s.tok.type = .RParen;
                    s.tok.lit = "";
                },
                '[' => {
                    s.advance();
                    s.tok.type = .LBrack;
                    s.tok.lit = "";
                },
                ']' => {
                    s.advance();
                    s.tok.type = .RBrack;
                    s.tok.lit = "";
                },
                '{' => {
                    s.advance();
                    s.tok.type = .LBrace;
                    s.tok.lit = "";
                },
                '}' => {
                    s.advance();
                    s.tok.type = .RBrace;
                    s.tok.lit = "";
                },
                ',' => {
                    s.advance();
                    s.tok.type = .Comma;
                    s.tok.lit = "";
                },
                ';' => {
                    s.advance();
                    s.tok.type = .Semicolon;
                    s.tok.lit = "";
                },
                ':' => {
                    s.advance();
                    s.tok.type = .Colon;
                    s.tok.lit = "";
                },
                '.' => {
                    s.advance();
                    switch (s.ch()) {
                        '.' => {
                            s.tok.type = .DotDot;
                            s.tok.lit = "";
                        },
                        else => {
                            s.tok.type = .Dot;
                            s.tok.lit = "";
                        },
                    }
                },
                '+' => {
                    s.advance();
                    switch (s.ch()) {
                        '+' => {
                            s.tok.type = .AddAdd;
                            s.tok.lit = "";
                        },
                        '=' => {
                            s.tok.type = .AddAssign;
                            s.tok.lit = "";
                        },
                        else => {
                            s.tok.type = .Add;
                            s.tok.lit = "";
                        },
                    }
                },
                '-' => {
                    s.advance();
                    switch (s.ch()) {
                        '-' => {
                            s.tok.type = .SubSub;
                            s.tok.lit = "";
                        },
                        '=' => {
                            s.tok.type = .SubAssign;
                            s.tok.lit = "";
                        },
                        else => {
                            s.tok.type = .Sub;
                            s.tok.lit = "";
                        },
                    }
                },
                '*' => {
                    s.advance();
                    switch (s.ch()) {
                        '=' => {
                            s.tok.type = .MulAssign;
                            s.tok.lit = "";
                        },
                        else => {
                            s.tok.type = .Mul;
                            s.tok.lit = "";
                        },
                    }
                },
                '%' => {
                    s.advance();
                    switch (s.ch()) {
                        '=' => {
                            s.tok.type = .ModAssign;
                            s.tok.lit = "";
                        },
                        else => {
                            s.tok.type = .Mod;
                            s.tok.lit = "";
                        },
                    }
                },
                '/' => {
                    s.advance();
                    switch (s.ch()) {
                        '/' => {
                            s.comment();
                            continue :redo;
                        },
                        '*' => {
                            s.multi_comment();
                            continue :redo;
                        },
                        '=' => {
                            s.tok.type = .DivAssign;
                            s.tok.lit = "";
                        },
                        else => {
                            s.tok.type = .Div;
                            s.tok.lit = "";
                        },
                    }
                    s.advance();
                },
                '^' => {
                    s.advance();
                    switch (s.ch()) {
                        '=' => {
                            s.tok.type = .XorAssign;
                            s.tok.lit = "";
                        },
                        else => {
                            s.tok.type = .Xor;
                            s.tok.lit = "";
                        },
                    }
                    s.advance();
                },
                '<' => {
                    s.advance();
                    switch (s.ch()) {
                        '<' => {
                            s.tok.type = .LeftShift;
                            s.tok.lit = "";
                        },
                        '=' => {
                            s.tok.type = .LesserEqual;
                            s.tok.lit = "";
                        },
                        else => {
                            s.tok.type = .Lesser;
                            s.tok.lit = "";
                        },
                    }
                },
                '>' => {
                    s.advance();
                    switch (s.ch()) {
                        '>' => {
                            s.tok.type = .RightShift;
                            s.tok.lit = "";
                        },
                        '=' => {
                            s.tok.type = .GreaterEqual;
                            s.tok.lit = "";
                        },
                        else => {
                            s.tok.type = .Greater;
                            s.tok.lit = "";
                        },
                    }
                },
                '&' => {
                    s.advance();
                    switch (s.ch()) {
                        '&' => {
                            s.tok.type = .AndAnd;
                            s.tok.lit = "";
                        },
                        '=' => {
                            s.tok.type = .AndAssign;
                            s.tok.lit = "";
                        },
                        else => {
                            s.tok.type = .And;
                            s.tok.lit = "";
                        },
                    }
                },
                '|' => {
                    s.advance();
                    switch (s.ch()) {
                        '|' => {
                            s.tok.type = .OrOr;
                            s.tok.lit = "";
                        },
                        '=' => {
                            s.tok.type = .OrAssign;
                            s.tok.lit = "";
                        },
                        else => {
                            s.tok.type = .Or;
                            s.tok.lit = "";
                        },
                    }
                },
                '=' => {
                    s.advance();
                    switch (s.ch()) {
                        '=' => {
                            s.tok.type = .EqualEqual;
                            s.tok.lit = "";
                        },
                        else => {
                            s.tok.type = .Equal;
                            s.tok.lit = "";
                        },
                    }
                },
                '!' => {
                    s.advance();
                    switch (s.ch()) {
                        '=' => {
                            s.tok.type = .BangEqual;
                            s.tok.lit = "";
                        },
                        else => {
                            s.tok.type = .Bang;
                            s.tok.lit = "";
                        },
                    }
                },
                else => {
                    s.err = CompilerError.UndefinedSymbol;
                },
            }
            break :redo;
        }
    }
    pub fn section(s: *Lexer, start: usize) []u8 {
        return s.s[start..s.curr];
    }
    pub fn ident(s: *Lexer) void {
        const start = s.curr;
        while (switch (s.ch()) {
            'a'...'z', 'A'...'Z', '_', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9' => true,
            else => false,
        }) {
            s.advance();
        }
        const v = s.section(start);
        if (KWDS.has(v)) {
            s.tok.type = KWDS.get(v).?;
            s.tok.lit = "";
        } else {
            s.tok.type = .Ident;
            s.tok.lit = v;
        }
    }
    pub fn number(s: *Lexer) void {
        var floating = false;
        const start = s.curr;
        while (switch (s.ch()) {
            '0', '1', '2', '3', '4', '5', '6', '7', '8', '9' => true,
            else => false,
        }) {
            s.advance();
        }
        if (s.ch() == '.') {
            floating = true;
            s.advance();
            while (switch (s.ch()) {
                '0', '1', '2', '3', '4', '5', '6', '7', '8', '9' => true,
                else => false,
            }) {
                s.advance();
            }
        }
        const v = s.section(start);
        if (floating) {
            s.tok.type = .Float;
        } else {
            s.tok.type = .Int;
        }
        s.tok.lit = v;
    }
    pub fn string(s: *Lexer) void {
        s.advance();
        const start = s.curr;
        const start_col = s.c;
        const start_line = s.l;

        while (true) {
            switch (s.ch()) {
                '"' => {
                    s.tok.type = .String;
                    s.tok.lit = s.section(start);
                    s.advance();
                    break;
                },
                '\\' => {
                    if (!s.escape('"')) {
                        s.err = CompilerError.InvalidEscape;
                        s.l = start_line;
                        s.c = start_col;
                        break;
                    }
                },
                '\n' => {
                    s.err = CompilerError.NewlineInSingleLineString;
                    s.l = start_line;
                    s.c = start_col;
                    break;
                },
                else => {
                    if (s.is_end()) {
                        s.err = CompilerError.UnterminatedChar;
                        s.l = start_line;
                        s.c = start_col;
                        break;
                    }
                },
            }
            s.advance();
        }
    }
    pub fn raw_string(s: *Lexer) void {
        s.advance();
        const start = s.curr;
        const start_col = s.c;
        const start_line = s.l;
        while (true) {
            switch (s.ch()) {
                '`' => {
                    s.tok.type = .String;
                    s.tok.lit = s.section(start);
                    s.advance();
                },
                else => {
                    if (s.is_end()) {
                        s.err.? = CompilerError.UnterminatedChar;
                        s.l = start_line;
                        s.c = start_col;
                        break;
                    }
                },
            }
            s.advance();
        }
    }
    pub fn char(s: *Lexer) void {
        var n: usize = 0;
        const start = s.curr;
        const start_col = s.c;
        const start_line = s.l;
        while (true) {
            switch (s.ch()) {
                '\'' => {
                    if (n > 1) {
                        s.err.? = CompilerError.CharLiteralMoreThanOne;
                        s.l = start_line;
                        s.c = start_col;
                    }
                    s.tok.type = .Char;
                    s.tok.lit = s.section(start);
                    s.advance();
                    break;
                },
                '\\' => {
                    s.advance();
                    if (!s.escape('\'')) {
                        s.err.? = CompilerError.InvalidEscape;
                        s.l = start_line;
                        s.c = start_col;
                        break;
                    }
                },
                else => {
                    if (s.is_end()) {
                        s.err.? = CompilerError.UnterminatedChar;
                        s.l = start_line;
                        s.c = start_col;
                        break;
                    }
                },
            }
            s.advance();
            n += 1;
        }
    }
    pub fn comment(s: *Lexer) void {
        while (true) {
            if (s.ch() == '\n' or s.is_end()) {
                break;
            }
            s.advance();
        }
    }
    pub fn multi_comment(s: *Lexer) void {
        while (true) {
            if (s.ch() == '*') {
                s.advance();
                if (s.ch() == '/') {
                    s.advance();
                    break;
                }
            }
            if (s.is_end()) {
                break;
            }
            s.advance();
        }
    }
    pub fn is_end(s: *Lexer) bool {
        return s.curr >= s.s.len;
    }
    pub fn escape(s: *Lexer, c: u8) bool {
        if (s.ch() == c) {
            return true;
        }
        return switch (s.ch()) {
            'a', 'b', 'f', 'n', 'r', 't', 'v', '\\' => true,
            else => false,
        };
    }
    pub fn advance(s: *Lexer) void {
        if (s.ch() == '\n') {
            s.l += 1;
            s.c = 0;
        } else {
            s.c += 1;
        }
        s.curr += 1;
    }
};
