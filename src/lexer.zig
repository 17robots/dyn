const std = @import("std");
const Error = @import("errors.zig").Error;
const Token = @import("token.zig").TokenType;

const Self = @This();
const LexingState = enum {
    base,
    read_word,
    read_num,
    read_float,
    read_string,
    read_char,
    read_add,
    read_sub,
    read_mul,
    read_div,
    read_mod,
    read_and,
    read_or,
    read_xor,
    read_flip,
    read_eq,
    read_gt,
    read_lt,
    read_bang,
    read_dot,
    read_underscore,
    read_comment,
    read_multi_comment,
};

buffer: []const u8,
index: usize,
placeholder: usize,
tok: ?Token,
literal: ?[]const u8,
state: LexingState,
err: ?Error,
line: usize,
col: usize,
reading_comment: bool = false,

pub fn init(buffer: []const u8) Self {
    return .{ .buffer = buffer, .index = 0, .line = 1, .col = 1, .placeholder = 0, .tok = null, .literal = null, .err = null, .state = .base };
}

fn is_whitespace(s: Self) bool {
    return switch (s.buffer[s.index]) {
        ' ', '\t', '\n', '\r' => true,
        else => false,
    };
}

pub fn next_tok(s: *Self) void {
    if (s.err != null or s.tok == .eof) return;
    // skip commented chars
    // skip whitespace
    if (s.state != .read_string) {
        while (s.index < s.buffer.len and s.is_whitespace() or s.reading_comment) {
            if (s.buffer[s.index] == '\n') {
                s.line += 1;
                s.col = 1;
            }
            s.index += 1;
        }
    }
    s.placeholder = s.index;
    while (s.index < s.buffer.len) {
        switch (s.state) {
            .base => switch (s.buffer[s.index]) {
                'a'...'z', 'A'...'Z', '$' => s.state = .read_word,
                '0'...'9' => s.state = .read_num,
                '.' => s.state = .read_dot,
                '\"' => s.state = .read_string,
                '\'' => s.state = .read_char,
                '(' => {
                    s.tok = .lparen;
                    s.literal = null;
                    s.index += 1;
                },
                ')' => {
                    s.tok = .rparen;
                    s.literal = null;
                    s.index += 1;
                },
                '[' => {
                    s.tok = .lbrack;
                    s.literal = null;
                    s.index += 1;
                },
                ']' => {
                    s.tok = .rbrack;
                    s.literal = null;
                    s.index += 1;
                },
                '{' => {
                    s.tok = .lbrace;
                    s.literal = null;
                    s.index += 1;
                },
                '}' => {
                    s.tok = .rbrace;
                    s.literal = null;
                    s.index += 1;
                },
                ':' => {
                    s.tok = .colon;
                    s.literal = null;
                    s.index += 1;
                },
                ';' => {
                    s.tok = .semicolon;
                    s.literal = null;
                    s.index += 1;
                },
                ',' => {
                    s.tok = .comma;
                    s.literal = null;
                    s.index += 1;
                },
                '?' => {
                    s.tok = .question;
                    s.literal = null;
                    s.index += 1;
                },
                '+' => s.state = .read_add,
                '-' => s.state = .read_sub,
                '*' => s.state = .read_mul,
                '/' => s.state = .read_div,
                '%' => s.state = .read_mod,
                '&' => s.state = .read_and,
                '|' => s.state = .read_or,
                '^' => s.state = .read_xor,
                '~' => s.state = .read_flip,
                '=' => s.state = .read_eq,
                '>' => s.state = .read_gt,
                '<' => s.state = .read_lt,
                '!' => s.state = .read_bang,
                '_' => s.state = .read_underscore,
                else => {
                    s.tok = .invalid;
                    s.err = Error.InvalidCharacter;
                    return;
                },
            },
            .read_underscore => {
                switch (s.buffer[s.index]) {
                    'a'...'z', 'A'...'Z', '0'...'9' => s.state = .read_word,
                    else => {
                        s.tok = .underscore;
                        s.literal = null;
                        s.state = .base;
                    },
                }
            },
            .read_word => {
                switch (s.buffer[s.index]) {
                    'a'...'z', 'A'...'Z', '0'...'9', '_' => {},
                    else => {
                        if (s.get_keyword()) |k| {
                            s.tok = k;
                            s.literal = null;
                        } else {
                            s.tok = .identifier;
                            s.literal = s.buffer[s.placeholder..s.index];
                        }
                        s.state = .base;
                    },
                }
            },
            .read_num => {
                switch (s.buffer[s.index]) {
                    '0'...'9' => {},
                    '.' => s.state = .read_float,
                    else => {
                        s.tok = .int;
                        s.literal = s.buffer[s.placeholder..s.index];
                        s.state = .base;
                    },
                }
            },
            .read_float => {
                switch (s.buffer[s.index]) {
                    '0'...'9' => {},
                    '.' => {
                        if (s.index > 0 and s.buffer[s.index - 1] == '.') {
                            s.index -= 1;
                            s.tok = .int;
                            s.literal = s.buffer[s.placeholder..s.index];
                            s.state = .base;
                        } else {
                            s.tok = .float;
                            s.literal = s.buffer[s.placeholder..s.index];
                            s.state = .base;
                        }
                    },
                    else => {
                        s.tok = .float;
                        s.literal = s.buffer[s.placeholder..s.index];
                        s.state = .base;
                    },
                }
            },
            .read_dot => {
                switch (s.buffer[s.index]) {
                    '0'...'9' => {
                        s.state = .read_float;
                    },
                    '.' => {
                        s.tok = .dotdot;
                        s.literal = null;
                        s.state = .base;
                        s.index += 1;
                    },
                    '?' => {
                        s.tok = .optional_deref;
                        s.literal = null;
                        s.state = .base;
                        s.index += 1;
                    },
                    '*' => {
                        s.tok = .pointer_deref;
                        s.literal = null;
                        s.state = .base;
                        s.index += 1;
                    },
                    else => {
                        s.tok = .dot;
                        s.literal = null;
                        s.state = .base;
                    },
                }
            },
            .read_string => {
                switch (s.buffer[s.index]) {
                    '\"' => {
                        s.tok = .string;
                        s.literal = s.buffer[(s.placeholder + 1)..s.index];
                        s.index += 1;
                        s.state = .base;
                    },
                    else => {},
                }
            },
            .read_char => {
                switch (s.buffer[s.index]) {
                    '\'' => {
                        if (s.buffer[(s.placeholder + 1)..s.index].len > 1) {
                            s.tok = .invalid;
                            s.err = Error.InvalidCharLength;
                            s.state = .base;
                        } else {
                            s.tok = .char;
                            s.literal = s.buffer[(s.placeholder + 1)..s.index];
                            s.state = .base;
                            s.index += 1;
                            return;
                        }
                    },
                    '\\' => {
                        s.index += 1;
                        switch (s.buffer[s.index]) {
                            '\'', '\"', '?', '\\', 'a', 'b', 'f', 'n', 'r', 't', 'v' => {},
                            else => {
                                s.tok = .invalid;
                                s.state = .base;
                                s.err = Error.InvalidEscape;
                                return;
                            },
                        }
                    }, // check for valid escape sequences
                    else => {},
                }
            },
            .read_add => {
                s.tok = switch (s.buffer[s.index]) {
                    '+' => .addadd,
                    '=' => .addeq,
                    else => .add,
                };
                s.literal = null;
                s.state = .base;
                if (s.tok != .add) {
                    s.index += 1;
                }
            },
            .read_sub => {
                s.tok = switch (s.buffer[s.index]) {
                    '-' => .subsub,
                    '=' => .subeq,
                    else => .sub,
                };
                s.literal = null;
                s.state = .base;
                if (s.tok != .sub) {
                    s.index += 1;
                }
            },
            .read_mul => {
                s.tok = switch (s.buffer[s.index]) {
                    '=' => .muleq,
                    else => .mul,
                };
                s.literal = null;
                s.state = .base;
                if (s.tok != .mul) {
                    s.index += 1;
                }
            },
            .read_div => {
                switch (s.buffer[s.index]) {
                    '/' => {
                        s.state = .read_comment;
                        s.index += 1;
                    },
                    '*' => {
                        s.state = .read_multi_comment;
                        s.index += 1;
                    },
                    else => {
                        s.tok = switch (s.buffer[s.index]) {
                            '=' => .diveq,
                            else => .div,
                        };
                        s.literal = null;
                        s.state = .base;
                        if (s.tok != .div) {
                            s.index += 1;
                        }
                    },
                }
            },
            .read_comment => {
                switch (s.buffer[s.index]) {
                    '\n' => {
                        s.state = .base;
                        s.line += 1;
                        s.col = 0;
                        return s.next_tok();
                    },
                    else => {},
                }
            },
            .read_multi_comment => {
                if (s.buffer[s.index] == '*') {
                    s.index += 1;
                    if (s.buffer[s.index] == '/') {
                        s.index += 1;
                        s.state = .base;
                        return s.next_tok();
                    }
                }
            },
            .read_mod => {
                s.tok = switch (s.buffer[s.index]) {
                    '=' => .modeq,
                    else => .mod,
                };
                s.literal = null;
                s.state = .base;
                if (s.tok != .mod) {
                    s.index += 1;
                }
            },
            .read_and => {
                s.tok = switch (s.buffer[s.index]) {
                    '&' => .andand,
                    '=' => .andeq,
                    else => .@"and",
                };
                s.literal = null;
                s.state = .base;
                if (s.tok != .@"and") {
                    s.index += 1;
                }
            },
            .read_or => {
                s.tok = switch (s.buffer[s.index]) {
                    '|' => .oror,
                    '=' => .oreq,
                    else => .@"or",
                };
                s.literal = null;
                s.state = .base;
                if (s.tok != .@"or") {
                    s.index += 1;
                }
            },
            .read_xor => {
                s.tok = switch (s.buffer[s.index]) {
                    '=' => .xoreq,
                    else => .xor,
                };
                s.literal = null;
                s.state = .base;
                if (s.tok != .xor) {
                    s.index += 1;
                }
            },
            .read_flip => {
                s.tok = switch (s.buffer[s.index]) {
                    '=' => .flipeq,
                    else => .flip,
                };
                s.literal = null;
                s.state = .base;
                if (s.tok != .flip) {
                    s.index += 1;
                }
            },
            .read_eq => {
                s.tok = switch (s.buffer[s.index]) {
                    '>' => .arrow,
                    '=' => .eqeq,
                    else => .eq,
                };
                s.literal = null;
                s.state = .base;
                if (s.tok != .eq) {
                    s.index += 1;
                }
            },
            .read_gt => {
                s.tok = switch (s.buffer[s.index]) {
                    '=' => .gteq,
                    else => .gt,
                };
                s.literal = null;
                s.state = .base;
                if (s.tok != .gt) {
                    s.index += 1;
                }
            },
            .read_lt => {
                s.tok = switch (s.buffer[s.index]) {
                    '=' => .lteq,
                    else => .lt,
                };
                s.literal = null;
                s.state = .base;
                if (s.tok != .lt) {
                    s.index += 1;
                }
            },
            .read_bang => {
                s.tok = switch (s.buffer[s.index]) {
                    '=' => .bangeq,
                    else => .bang,
                };
                s.literal = null;
                s.state = .base;
                if (s.tok != .bang) {
                    s.index += 1;
                }
            },
        }
        if (s.state == .base) {
            return;
        }
        s.index += 1;
        s.col += 1;
    }
    switch (s.state) {
        .base => {
            s.tok = .eof;
            s.literal = null;
        },
        .read_comment => {
            s.tok = .eof;
            s.literal = null;
        },
        .read_multi_comment => {
            if (s.buffer[s.index - 1] == '/' and s.buffer[s.index - 2] == '*') {
                s.tok = .eof;
                s.literal = null;
            } else {
                @panic("UH OH unclosed multi line comment");
            }
        },
        .read_word => {
            if (s.get_keyword()) |k| {
                s.tok = k;
            } else {
                s.tok = .identifier;
                s.literal = s.buffer[s.placeholder..s.index];
            }
        },
        .read_num => {
            s.tok = .int;
            s.literal = s.buffer[s.placeholder..s.index];
        },
        .read_float => {
            s.tok = .float;
            s.literal = s.buffer[s.placeholder..s.index];
        },
        .read_underscore => {
            s.tok = .underscore;
            s.literal = null;
        },
        .read_add => {
            s.tok = .add;
            s.literal = null;
        },
        .read_sub => {
            s.tok = .sub;
            s.literal = null;
        },
        .read_mul => {
            s.tok = .add;
            s.literal = null;
        },
        .read_div => {
            s.tok = .div;
            s.literal = null;
        },
        .read_mod => {
            s.tok = .mod;
            s.literal = null;
        },
        .read_and => {
            s.tok = .@"and";
            s.literal = null;
        },
        .read_or => {
            s.tok = .@"or";
            s.literal = null;
        },
        .read_xor => {
            s.tok = .xor;
            s.literal = null;
        },
        .read_flip => {
            s.tok = .flip;
            s.literal = null;
        },
        .read_eq => {
            s.tok = .eq;
            s.literal = null;
        },
        .read_gt => {
            s.tok = .gt;
            s.literal = null;
        },
        .read_lt => {
            s.tok = .lt;
            s.literal = null;
        },
        .read_bang => {
            s.tok = .bang;
            s.literal = null;
        },
        .read_string => {
            if (s.buffer[s.index] != '\"') {
                // error out
            }
            s.tok = .string;
            s.literal = s.buffer[s.placeholder..s.index];
        },
        .read_char => {
            if (s.buffer[s.index] != '\'') {
                // error out
            }
            if (s.buffer[(s.placeholder + 1)..s.index].len > 1) {
                s.tok = .invalid;
                s.err = Error.InvalidEscape;
                s.state = .base;
            } else {
                s.tok = .char;
                s.literal = s.buffer[(s.placeholder + 1)..s.index];
                s.state = .base;
                s.index += 1;
            }
        },
        .read_dot => {
            switch (s.buffer[s.index]) {
                '0'...'9' => {
                    s.state = .read_float;
                },
                '.' => {
                    s.tok = .dotdot;
                    s.literal = null;
                    s.state = .base;
                    s.index += 1;
                },
                else => {
                    s.tok = .dot;
                    s.literal = null;
                    s.state = .base;
                    s.index += 1;
                },
            }
        },
    }
    s.state = .base;
}

fn get_keyword(s: *Self) ?Token {
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "module")) {
        return .module;
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "use")) {
        return .use;
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "mut")) {
        return .mut;
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "true")) {
        return .true;
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "false")) {
        return .false;
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "if")) {
        return .@"if";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "else")) {
        return .@"else";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "match")) {
        return .match;
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "defer")) {
        return .@"defer";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "for")) {
        return .@"for";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "enum")) {
        return .@"enum";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "error")) {
        return .@"error";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "try")) {
        return .@"try";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "catch")) {
        return .@"catch";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "struct")) {
        return .@"struct";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "type")) {
        return .type;
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "comp")) {
        return .comp;
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "pub")) {
        return .@"pub";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "while")) {
        return .@"while";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "undefined")) {
        return .undefined;
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "return")) {
        return .@"return";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "break")) {
        return .@"break";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "inline")) {
        return .@"inline";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "fn")) {
        return .@"fn";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "packed")) {
        return .@"packed";
    }
    if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "in")) {
        return .in;
    }
    return null;
}
