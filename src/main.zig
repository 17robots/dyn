const std = @import("std");

pub const TokenType = enum {
    eof,
    invalid,
    // literals
    identifier,
    int,
    float,
    string,
    // operators
    add, // +
    sub, // -
    mul, // *
    div, // /
    mod, // %
    @"and", // &
    @"or", // |
    xor, // ^
    flip, // ~
    eq, // =
    addeq, // +=
    addadd, // ++
    subeq, // -=
    subsub, // --
    muleq, // *=
    diveq, // /=
    modeq, // %=
    andeq, // &=
    oreq, // |=
    xoreq, // ^=
    flipeq, // ~=
    andand, // &&
    oror, // ||
    eqeq, // ==
    gt, // >
    lt, // <
    gteq, // >=
    lteq, // <=
    lparen, // (
    rparen, // )
    lbrack, // [
    rbrack, // ]
    lbrace, // {
    rbrace, // }
    dot, // .
    dotdot, // ..
    colon, // :
    semicolon, // ;
    underscore, // _
    arrow, // =>
    // keywords
    module,
    use,
    void,
    mut,
    true,
    false,
    @"if",
    @"else",
    match,
    @"defer",
    loop,
    @"for",
    @"enum",
    @"error",
    @"try",
    @"catch",
    @"union",
    @"struct",
    type,
    comp,
};

pub const Lexer = struct {
    buffer: []const u8,
    index: usize,
    placeholder: usize,
    tok: ?TokenType,
    literal: ?[]const u8,
    state: LexingState,
    err: ?LexingError,
    const LexingState = enum {
        base,
        read_word,
        read_num,
        read_float,
        read_string,
        read_char,
        read_op,
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
    };
    const LexingError = error{
        InvalidCharacter,
    };

    fn init(buffer: []const u8) Lexer {
        return .{ .buffer = buffer, .index = 0, .placeholder = 0, .tok = null, .literal = null, .err = null, .state = .base };
    }

    fn is_whitespace(s: Lexer) bool {
        return switch (s.buffer[s.index]) {
            ' ', '\t', '\n' => true,
            else => false,
        };
    }

    fn next_tok(s: *Lexer) void {
        // skip whitespace
        s.placeholder = s.index;
        while (s.index < s.buffer.len) {
            while (s.is_whitespace()) {
                if (s.buffer[s.index] == '\n') {
                    // do something with line count and col
                }
                s.index += 1;
            }
            switch (s.state) {
                .base => switch (s.buffer[s.index]) {
                    'a'...'z', 'A'...'Z', '_' => s.state = .read_word,
                    '0'...'9' => s.state = .read_num,
                    '.' => s.state = .read_float,
                    '\"' => s.state = .read_string,
                    '\'' => s.state = .read_char,
                    '(' => s.tok = .lparen,
                    ')' => s.tok = .rparen,
                    '[' => s.tok = .lbrack,
                    ']' => s.tok = .rbrack,
                    '{' => s.tok = .lbrace,
                    '}' => s.tok = .rbrace,
                    ':' => s.tok = .colon,
                    ';' => s.tok = .semicolon,
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
                    else => {
                        s.tok = .invalid;
                        s.err = LexingError.InvalidCharacter;
                        return;
                    },
                },
                .read_word => {
                    switch (s.buffer[s.index]) {
                        'a'...'z', 'A'...'Z', '0'...'9', '_' => {},
                        else => {
                            if (s.get_keyword()) |k| {
                                s.tok = k;
                            } else {
                                s.tok = .identifier;
                                s.literal = s.buffer[s.placeholder..s.index];
                            }
                            s.state = .base;
                        },
                    }
                },
                else => {},
            }
            s.index += 1;
            if (s.state == .base) {
                return;
            }
        }
        switch (s.state) {}
    }

    fn get_keyword(s: *Lexer) ?TokenType {
        if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "module")) {
            return .module;
        }
        if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "use")) {
            return .use;
        }
        if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "void")) {
            return .void;
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
        if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "loop")) {
            return .loop;
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
        if (std.mem.eql(u8, s.buffer[s.placeholder..s.index], "union")) {
            return .@"union";
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
        return null;
    }

    fn get_error(s: *Lexer) []const u8 {
        return switch (s.err) {
            .InvalidCharacter => "Invalid Characer",
        };
    }
};

pub fn main() !void {
    const page_allocator = std.heap.page_allocator;
    var arena = std.heap.ArenaAllocator.init(page_allocator);
    const alloc = arena.allocator();
    defer arena.deinit();

    const x = try read_file(alloc, "./src/main.dyn");

    var l = Lexer.init(x);

    l.next_tok();

    std.debug.assert(l.tok == .mut);
    // std.debug.assert(std.mem.eql(u8, l.literal orelse "", "ident"));
    // std.debug.assert(l.state == .base);
}

pub fn read_file(a: std.mem.Allocator, filename: []const u8) ![]const u8 {
    const file = try std.fs.cwd().openFile(filename, .{ .mode = .read_only });
    defer file.close();
    const stat = try file.stat();
    return try file.readToEndAlloc(a, stat.size);
}
