const std = @import("std");
const FileId = @import("source.zig").FileId;
const SourceLocation = @import("source.zig").SourceLocation;
const Source = @import("source.zig").Source;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const TokenType = @import("token.zig").TokenType;
const Token = @import("token.zig").Token;

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
    read_colon,
    read_underscore,
    read_question,
    read_comment,
    read_multi_comment,
};

const Lexer = @This();
diag: *DiagnosticEmitter,
source: *Source,
state: LexingState = .base,
index: usize = 0,
placeholder: usize = 0,
reading_comment: bool = false,
has_char_errored: bool = false,
errored: bool = false,

pub fn init(source: *Source, diag: *DiagnosticEmitter) Lexer {
    return Lexer{ .source = source, .diag = diag };
}
fn whitespace(s: Lexer) bool {
    return switch (s.source.content[s.index]) {
        ' ', '\t', '\n', '\r' => true,
        else => false,
    };
}
pub fn next(s: *Lexer) Token {
    if (s.errored) return Token.init(.invalid, s.source.id, @intCast(s.index), null);
    if (s.index >= s.source.content.len) return Token.init(.eof, s.source.id, @intCast(s.index), null);
    if (s.state != .read_string) {
        while (s.index < s.source.content.len and s.whitespace()) s.index += 1;
    }
    s.placeholder = s.index;
    while (s.index < s.source.content.len) {
        switch (s.state) {
            .base => switch (s.source.content[s.index]) {
                'a'...'z', 'A'...'Z', '$' => s.state = .read_word,
                '0'...'9' => s.state = .read_num,
                '.' => s.state = .read_dot,
                '\"' => s.state = .read_string,
                '\'' => s.state = .read_char,
                '?' => s.state = .read_question,
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
                ':' => s.state = .read_colon,
                '(' => {
                    s.index += 1;
                    return Token.init(.lparen, s.source.id, @intCast(s.index - 1), null);
                },
                ')' => {
                    s.index += 1;
                    return Token.init(.rparen, s.source.id, @intCast(s.index - 1), null);
                },
                '[' => {
                    s.index += 1;
                    return Token.init(.lbrack, s.source.id, @intCast(s.index - 1), null);
                },
                ']' => {
                    s.index += 1;
                    return Token.init(.rbrack, s.source.id, @intCast(s.index - 1), null);
                },
                '{' => {
                    s.index += 1;
                    return Token.init(.lbrace, s.source.id, @intCast(s.index - 1), null);
                },
                '}' => {
                    s.index += 1;
                    return Token.init(.rbrace, s.source.id, @intCast(s.index - 1), null);
                },
                ';' => {
                    s.index += 1;
                    return Token.init(.semicolon, s.source.id, @intCast(s.index - 1), null);
                },
                ',' => {
                    s.index += 1;
                    return Token.init(.comma, s.source.id, @intCast(s.index - 1), null);
                },
                else => {
                    s.diag.emit(s.source.id, @intCast(s.index), .err, "Invalid Character: {any}", .{s.source.content[s.index]});
                    s.index += 1;
                    s.errored = true;
                    return Token.init(.invalid, s.source.id, @intCast(s.index - 1), null);
                },
            },
            .read_underscore => switch (s.source.content[s.index]) {
                'a'...'z', 'A'...'Z', '0'...'9' => s.state = .read_word,
                else => {
                    s.state = .base;
                    return Token.init(.underscore, s.source.id, @intCast(s.index), null);
                },
            },
            .read_word => switch (s.source.content[s.index]) {
                'a'...'z', 'A'...'Z', '0'...'9', '_' => {},
                else => {
                    s.state = .base;
                    if (s.get_keyword()) |kw| return Token.init(kw, s.source.id, @intCast(s.index), null);
                    return Token.init(.identifier, s.source.id, @intCast(s.index), s.source.content[s.placeholder..s.index]);
                },
            },
            .read_num => switch (s.source.content[s.index]) {
                '0'...'9' => {},
                '.' => s.state = .read_float,
                else => {
                    s.state = .base;
                    return Token.init(.int, s.source.id, @intCast(s.index), s.source.content[s.placeholder..s.index]);
                },
            },
            .read_float => switch (s.source.content[s.index]) {
                '0'...'9' => {},
                '.' => {
                    s.state = .base;
                    if (s.index > 0 and s.source.content[s.index - 1] == '.') {
                        s.index -= 1;
                        return Token.init(.int, s.source.id, @intCast(s.index), s.source.content[s.placeholder..s.index]);
                    } else return Token.init(.float, s.source.id, @intCast(s.index), s.source.content[s.placeholder..s.index]);
                },
                else => {
                    s.state = .base;
                    return Token.init(.float, s.source.id, @intCast(s.index), s.source.content[s.placeholder..s.index]);
                },
            },
            .read_dot => switch (s.source.content[s.index]) {
                '0'...'9' => s.state = .read_float,
                '.' => {
                    s.state = .base;
                    s.index += 1;
                    return Token.init(.dotdot, s.source.id, @intCast(s.index), null);
                },
                '?' => {
                    s.state = .base;
                    s.index += 1;
                    return Token.init(.optional_deref, s.source.id, @intCast(s.index), null);
                },
                '*' => {
                    s.state = .base;
                    s.index += 1;
                    return Token.init(.pointer_deref, s.source.id, @intCast(s.index), null);
                },
                else => {
                    s.state = .base;
                    return Token.init(.dot, s.source.id, @intCast(s.index), null);
                },
            },
            .read_colon => switch (s.source.content[s.index]) {
                '=' => {
                    s.state = .base;
                    s.index += 1;
                    return Token.init(.walrus, s.source.id, @intCast(s.index - 1), null);
                },
                else => {
                    s.state = .base;
                    return Token.init(.colon, s.source.id, @intCast(s.index - 1), null);
                },
            },
            .read_question => switch (s.source.content[s.index]) {
                '?' => {
                    s.state = .base;
                    s.index += 1;
                    return Token.init(.nullish, s.source.id, @intCast(s.index - 1), null);
                },
                else => {
                    s.state = .base;
                    return Token.init(.question, s.source.id, @intCast(s.index - 1), null);
                },
            },
            .read_string => switch (s.source.content[s.index]) {
                '\"' => {
                    s.state = .base;
                    s.index += 1;
                    return Token.init(.string, s.source.id, @intCast(s.index - 1), s.source.content[s.placeholder..(s.index - 1)]);
                },
                else => {},
            },
            .read_char => switch(s.source.content[s.index]) {
                '\'' => {
                    const body = s.source.content[(s.placeholder + 1)..s.index];
                    s.state = .base;
                    s.index += 1;

                    if(s.has_char_errored) {
                        s.has_char_errored = false;
                        s.errored = true;
                        return Token.init(.invalid, s.source.id, @intCast(s.index - 1), null);
                    }
                    if(body.len == 0) {
                        s.diag.emit(s.source.id, @intCast(s.index), .err, "Empty character literal", .{});
                        s.errored = true;
                        return Token.init(.invalid, s.source.id, @intCast(s.index), null);
                    }
                    if(body[0] == '\\') {
                        if(body.len != 2) {
                            s.diag.emit(s.source.id, @intCast(s.index), .err, "Invalid character escape length", .{});
                            s.errored = true;
                            return Token.init(.invalid, s.source.id, @intCast(s.index), null);
                        }
                    } else if(body.len != 1) {
                        s.diag.emit(s.source.id, @intCast(s.index), .err, "Invalid character length", .{});
                        s.errored = true;
                        return Token.init(.invalid, s.source.id, @intCast(s.index), null);
                    }
                    return Token.init(.char, s.source.id, @intCast(s.index), s.source.content[s.placeholder..s.index]);
                },
                '\\' => {
                    s.index += 1;
                    if(s.index >= s.source.content.len) {
                        s.diag.emit(s.source.id, @intCast(s.index), .err, "Unfinished character escape", .{});
                        s.has_char_errored = true;
                    } else switch(s.source.content[s.index]) {
                        '\'', '\"', '?', '\\', 'a', 'b', 'f', 'n', 'r', 't', 'v' => {},
                        else => {
                            s.diag.emit(s.source.id, @intCast(s.index), .err, "Invalid character escape {any}", .{s.source.content[(s.index - 1)..s.index]});
                            s.has_char_errored = true;
                        },
                    }
                },
                else => {},
            },
            .read_add => {
                s.state = .base;
                const tok = Token.init(switch (s.source.content[s.index]) {
                    '+' => .addadd,
                    '=' => .addeq,
                    else => .add,
                }, s.source.id, @intCast(s.index), null);
                if (tok.tok_type != .add) s.index += 1;
                return tok;
            },
            .read_sub => {
                s.state = .base;
                const tok = Token.init(switch (s.source.content[s.index]) {
                    '-' => .subsub,
                    '=' => .subeq,
                    else => .sub,
                }, s.source.id, @intCast(s.index), null);
                if (tok.tok_type != .sub) s.index += 1;
                return tok;
            },
            .read_mul => {
                s.state = .base;
                const tok = Token.init(switch (s.source.content[s.index]) {
                    '=' => .muleq,
                    else => .mul,
                }, s.source.id, @intCast(s.index), null);
                if (tok.tok_type != .mul) s.index += 1;
                return tok;
            },
            .read_div => switch (s.source.content[s.index]) {
                '/', '*' => {
                    s.index += 1;
                    s.state = if (s.source.content[s.index] == '/') .read_comment else .read_multi_comment;
                },
                else => {
                    s.state = .base;
                    const tok = Token.init(switch (s.source.content[s.index]) {
                        '=' => .diveq,
                        else => .div,
                    }, s.source.id, @intCast(s.index), null);
                    if (tok.tok_type != .div) s.index += 1;
                    return tok;
                },
            },
            .read_mod => {
                s.state = .base;
                const tok = Token.init(switch (s.source.content[s.index]) {
                    '=' => .modeq,
                    else => .mod,
                }, s.source.id, @intCast(s.index), null);
                if (tok.tok_type != .mod) s.index += 1;
                return tok;
            },
            .read_and => {
                s.state = .base;
                const tok = Token.init(switch (s.source.content[s.index]) {
                    '&' => .andand,
                    '=' => .andeq,
                    else => .@"and",
                }, s.source.id, @intCast(s.index), null);
                if (tok.tok_type != .@"and") s.index += 1;
                return tok;
            },
            .read_or => {
                s.state = .base;
                const tok = Token.init(switch (s.source.content[s.index]) {
                    '|' => .oror,
                    '=' => .oreq,
                    else => .@"or",
                }, s.source.id, @intCast(s.index), null);
                if (tok.tok_type != .@"or") s.index += 1;
                return tok;
            },
            .read_xor => {
                s.state = .base;
                const tok = Token.init(switch (s.source.content[s.index]) {
                    '=' => .xoreq,
                    else => .xor,
                }, s.source.id, @intCast(s.index), null);
                if (tok.tok_type != .xor) s.index += 1;
                return tok;
            },
            .read_flip => {
                s.state = .base;
                const tok = Token.init(switch (s.source.content[s.index]) {
                    '=' => .flipeq,
                    else => .flip,
                }, s.source.id, @intCast(s.index), null);
                if (tok.tok_type != .flip) s.index += 1;
                return tok;
            },
            .read_eq => {
                s.state = .base;
                const tok = Token.init(switch (s.source.content[s.index]) {
                    '>' => .arrow,
                    '=' => .eqeq,
                    else => .eq,
                }, s.source.id, @intCast(s.index), null);
                if (tok.tok_type != .eq) s.index += 1;
                return tok;
            },
            .read_gt => {
                s.state = .base;
                const tok = Token.init(switch (s.source.content[s.index]) {
                    '=' => .gteq,
                    else => .gt,
                }, s.source.id, @intCast(s.index), null);
                if (tok.tok_type != .gt) s.index += 1;
                return tok;
            },
            .read_lt => {
                s.state = .base;
                const tok = Token.init(switch (s.source.content[s.index]) {
                    '=' => .lteq,
                    else => .lt,
                }, s.source.id, @intCast(s.index), null);
                if (tok.tok_type != .lt) s.index += 1;
                return tok;
            },
            .read_bang => {
                s.state = .base;
                const tok = Token.init(switch (s.source.content[s.index]) {
                    '=' => .bangeq,
                    else => .bang,
                }, s.source.id, @intCast(s.index), null);
                if (tok.tok_type != .bang) s.index += 1;
                return tok;
            },
            .read_comment => switch (s.source.content[s.index]) {
                '\n' => {
                    s.state = .base;
                    return s.next();
                },
                else => {},
            },
            .read_multi_comment => {
                if (s.source.content[s.index] == '*') {
                    if(s.index + 1 < s.source.content.len and s.source.content[s.index + 1] == '/') {
                        s.index += 2;
                        s.state = .base;
                        return s.next();
                    }
                }
            },
        }
        s.index += 1;
    }
    const res = switch (s.state) {
        .base => Token.init(.eof, s.source.id, @intCast(s.index), null),
        .read_comment => Token.init(.eof, s.source.id, @intCast(s.index), null),
        .read_multi_comment => blk: {
            if (std.mem.eql(u8, s.source.content[(s.index - 2)..(s.index - 1)], "*/")) break :blk Token.init(.eof, s.source.id, @intCast(s.index), null);
            s.diag.emit(s.source.id, @intCast(s.index), .err, "Unclosed Comment", .{});
            s.errored = true;
            break :blk Token.init(.invalid, s.source.id, @intCast(s.index), null);
        },
        .read_word => if (s.get_keyword()) |kw| Token.init(kw, s.source.id, @intCast(s.index), null) else Token.init(.identifier, s.source.id, @intCast(s.index), s.source.content[s.placeholder..s.index]),
        .read_num => Token.init(.int, s.source.id, @intCast(s.index), s.source.content[s.placeholder..s.index]),
        .read_float => Token.init(.float, s.source.id, @intCast(s.index), s.source.content[s.placeholder..s.index]),
        .read_underscore => Token.init(.underscore, s.source.id, @intCast(s.index), null),
        .read_add => Token.init(.add, s.source.id, @intCast(s.index), null),
        .read_sub => Token.init(.sub, s.source.id, @intCast(s.index), null),
        .read_mul => Token.init(.mul, s.source.id, @intCast(s.index), null),
        .read_div => Token.init(.div, s.source.id, @intCast(s.index), null),
        .read_mod => Token.init(.mod, s.source.id, @intCast(s.index), null),
        .read_and => Token.init(.@"and", s.source.id, @intCast(s.index), null),
        .read_or => Token.init(.@"or", s.source.id, @intCast(s.index), null),
        .read_xor => Token.init(.xor, s.source.id, @intCast(s.index), null),
        .read_flip => Token.init(.flip, s.source.id, @intCast(s.index), null),
        .read_eq => Token.init(.eq, s.source.id, @intCast(s.index), null),
        .read_gt => Token.init(.gt, s.source.id, @intCast(s.index), null),
        .read_lt => Token.init(.lt, s.source.id, @intCast(s.index), null),
        .read_bang => Token.init(.bang, s.source.id, @intCast(s.index), null),
        .read_dot => Token.init(.dot, s.source.id, @intCast(s.index), null),
        .read_colon => Token.init(.colon, s.source.id, @intCast(s.index), null),
        .read_question => Token.init(.question, s.source.id, @intCast(s.index), null),
        .read_string => switch (s.source.content[s.index]) {
            '\"' => Token.init(.string, s.source.id, @intCast(s.index), s.source.content[s.placeholder..s.index]),
            else => blk: {
                s.diag.emit(s.source.id, @intCast(s.index), .err, "Unclosed String Literal", .{});
                s.errored = true;
                break :blk Token.init(.invalid, s.source.id, @intCast(s.index), null);
            },
        },
        .read_char => switch (s.source.content[s.index]) {
            '\'' => blk: {
                const the_char = s.source.content[(s.placeholder + 1)..s.index];
                const val: u32 = if (the_char[0] == '\\') 2 else 1;
                if (the_char.len > val) {
                    s.diag.emit(s.source.id, @intCast(s.index), .err, "Invalid Character Length {any}", .{the_char});
                    s.errored = true;
                    break :blk Token.init(.invalid, s.source.id, @intCast(s.index), null);
                }
                break :blk Token.init(.char, s.source.id, @intCast(s.index), s.source.content[s.placeholder..s.index]);
            },
            else => blk: {
                s.diag.emit(s.source.id, @intCast(s.index), .err, "Unclosed Character Literal", .{});
                s.errored = true;
                break :blk Token.init(.invalid, s.source.id, @intCast(s.index), null);
            },
        },
    };
    s.state = .base;
    return res;
}

fn get_keyword(s: *Lexer) ?TokenType {
    const word = s.source.content[s.placeholder..s.index];
    switch (word.len) {
        2 => {
            if (std.mem.eql(u8, word, "fn")) return .@"fn";
            if (std.mem.eql(u8, word, "if")) return .@"if";
        },
        3 => {
            if (std.mem.eql(u8, word, "for")) return .@"for";
            if (std.mem.eql(u8, word, "mod")) return .module;
            if (std.mem.eql(u8, word, "mut")) return .mut;
            if (std.mem.eql(u8, word, "pub")) return .@"pub";
            if (std.mem.eql(u8, word, "try")) return .@"try";
            if (std.mem.eql(u8, word, "use")) return .use;
        },
        4 => {
            if (std.mem.eql(u8, word, "comp")) return .comp;
            if (std.mem.eql(u8, word, "else")) return .@"else";
            if (std.mem.eql(u8, word, "enum")) return .@"enum";
            if (std.mem.eql(u8, word, "null")) return .null;
            if (std.mem.eql(u8, word, "true")) return .true;
            if (std.mem.eql(u8, word, "type")) return .type;
        },
        5 => {
            if (std.mem.eql(u8, word, "break")) return .@"break";
            if (std.mem.eql(u8, word, "catch")) return .@"catch";
            if (std.mem.eql(u8, word, "defer")) return .@"defer";
            if (std.mem.eql(u8, word, "error")) return .@"error";
            if (std.mem.eql(u8, word, "false")) return .false;
            if (std.mem.eql(u8, word, "match")) return .match;
            if (std.mem.eql(u8, word, "while")) return .@"while";
        },
        6 => {
            if (std.mem.eql(u8, word, "inline")) return .@"inline";
            if (std.mem.eql(u8, word, "packed")) return .@"packed";
            if (std.mem.eql(u8, word, "struct")) return .@"struct";
            if (std.mem.eql(u8, word, "return")) return .@"return";
        },
        8 => {
            if (std.mem.eql(u8, word, "continue")) return .@"continue";
        },
        9 => {
            if (std.mem.eql(u8, word, "undefined")) return .undefined;
        },
        else => return null,
    }
}
