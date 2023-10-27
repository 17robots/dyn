const std = @import("std");

pub const language = [_][]u8{
    "con",
    "mut",
    "i8",
    "i16",
    "i32",
    "i64",
    "i128",
    "u8",
    "u16",
    "u32",
    "u64",
    "u128",
    "f32",
    "f64",
    "if",
    "void",
    "+",
    "-",
    "*",
    "/",
    "&",
    "|",
    "=",
    "!",
    ";",
    ",",
    ".",
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    "++",
    "--",
    "&&",
    "||",
    "==",
    "!=",
};

pub const Token = struct {
    type: []u8,
    val: []u8,
    start: usize,
    end: usize,
    pub fn new(_type: []u8, val: []u8, s: usize, e: usize) Token {
        return .{
            .type = _type,
            .val = val,
            .start = s,
            .end = e,
        };
    }
};

pub fn print_token(t: Token) void {
    std.debug.print("{s}({s}), start: {d}, end: {d}\n", .{ t.type, t.val, t.start, t.end });
}

pub fn contains(val: []u8) bool {
    var found = false;
    for (language) |x| {
        if (std.mem.eql(u8, x, val)) {
            found = true;
        }
    }
    return found;
}

pub const File = struct {
    name: []u8,
    input: []u8,
    curr: usize,
    pub fn new(name: []u8, input: []u8) File {
        return .{
            .name = name,
            .input = input,
            .curr = 0,
        };
    }
    fn read_char(self: *File) void {
        self.curr += 1;
        return;
    }
    pub fn get_token(self: *File) Token {
        var tok: Token = undefined;
        if (!self.valid()) {
            tok = Token.new("EOF", "", self.curr, self.curr);
        } else {
            const pos = self.curr;
            self.r_ws();
            switch (self.input[self.curr]) {
                'a'...'z', 'A'...'Z' => {
                    var x = self.r_w();
                    tok = Token.new(if (contains(x)) "Keyword" else "Identifier", x, pos, pos + x.len - 1);
                },
                '0'...'9' => {
                    var x = self.r_n();
                    tok = Token.new(if (std.mem.count(u8, x, ".") > 0) "Floating" else "Integer", x, pos, pos + x.len - 1);
                },
                else => {
                    tok = if (contains(self.sub(self.curr, self.curr))) {
                        var x = self.r_o();
                        return Token.new("Operator", x, pos, pos + x.len - 1);
                    } else {
                        return Token.new("Illegal", "", pos, pos);
                    };
                },
            }
            if (self.curr == pos) {
                self.read_char();
            }
        }
        return tok;
    }
    fn valid(self: *File) bool {
        return self.curr < self.input.len;
    }
    fn r_w(self: *File) []u8 {
        const pos = self.curr;
        blk: while (self.valid()) {
            switch (self.input[self.curr]) {
                'a'...'z',
                'A'...'Z',
                '0'...'9',
                '_',
                => {
                    self.read_char();
                },
                else => {
                    break :blk;
                },
            }
        }
        return self.sub(pos, self.curr);
    }
    fn r_n(self: *File) []u8 {
        const pos = self.curr;
        blk: while (self.valid()) {
            switch (self.input[self.curr]) {
                '0'...'9', '_', '.' => {
                    self.read_char();
                },
                else => {
                    break :blk;
                },
            }
        }
        return self.sub(pos, self.curr);
    }
    fn r_o(self: *File) []u8 {
        const pos = self.curr;
        blk: while (self.valid()) {
            switch (self.input[self.curr]) {
                else => {
                    if (contains(self.sub(pos, self.curr)) and contains(self.sub(self.curr, self.curr))) {
                        self.read_char();
                    } else {
                        break :blk;
                    }
                },
            }
        }
        return self.sub(pos, self.curr);
    }
    fn r_ws(self: *File) void {
        blk: while (self.valid()) {
            switch (self.input[self.curr]) {
                ' ',
                '\t',
                '\r',
                => {
                    self.read_char();
                },
                else => {
                    break :blk;
                },
            }
        }
    }
    fn sub(self: *File, s: usize, e: usize) []u8 {
        return self.input[s..(e + @intFromBool(s == e))];
    }
};
