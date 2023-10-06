const std = @import("std");

const string = []const u8;
const language = [_]string{
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
    "++",
    "--",
    "&&",
    "||",
    "==",
    "!=",
};

fn contains(val: string) bool {
    var found = false;
    for (language) |x| {
        if (std.mem.eql(u8, x, val)) {
            found = true;
        }
    }
    return found;
}

const File = struct {
    name: string,
    input: string,
    curr: usize,
    next: usize,
    ch: u8,
    fn new(name: string, input: string) File {
        var f: File = .{
            .name = name,
            .input = input,
            .curr = 0,
            .next = 0,
            .ch = 0,
        };
        f.read_char();
        return f;
    }
    fn read_char(self: *File) void {
        self.ch = self.peak();
        self.curr = self.next;
        self.next += 1;
    }
    fn peak(self: *File) u8 {
        if (self.next < self.input.len) {
            return self.input[self.next];
        }
        return 0;
    }
    fn get_token(self: *File) Token {
        const pos = self.curr;
        var tok: Token = undefined;
        self.read_ws();
        switch (self.ch) {
            'a'...'z', 'A'...'Z' => {
                var x = self.read_word();
                var y: string = undefined;
                if (contains(x)) {
                    y = "Keyword"; // keyword
                } else {
                    y = "Identifer"; // identifier
                }
                tok = Token.new(y, x, pos, self.curr - 1);
            },
            '0'...'9' => {
                var x = self.read_num();
                var y: string = undefined;
                if (std.mem.count(u8, x, ".") > 0) {
                    y = "Floating"; // float
                } else {
                    y = "Integer"; // integer
                }
                tok = Token.new(y, x, pos, self.curr - 1); // int
            },
            else => {
                if (contains(&[_]u8{self.ch})) {
                    const x = self.read_op();
                    tok = Token.new("Operator", x, pos, self.curr - 1);
                } else if (self.next >= self.input.len) {
                    tok = Token.new("EOF", "", pos, self.curr - 1); // eof
                } else {
                    tok = Token.new("Illegal", "", pos, self.curr - 1); // illegal
                }
            },
        }
        if (self.curr == pos)
            self.read_char();
        return tok;
    }
    fn read_num(self: *File) string {
        const pos = self.curr;
        blk: while (true) {
            switch (self.ch) {
                '0'...'9', '.', '_' => {
                    self.read_char();
                },
                else => {
                    break :blk;
                },
            }
        }
        return self.input[pos..self.curr];
    }
    fn read_word(self: *File) string {
        const pos = self.curr;
        blk: while (true) {
            switch (self.ch) {
                'a'...'z', 'A'...'Z', '0'...'9', '_' => {
                    self.read_char();
                },
                else => {
                    break :blk;
                },
            }
        }
        return self.input[pos..self.curr];
    }
    fn read_op(self: *File) string {
        const pos = self.curr;
        blk: while (contains(&[_]u8{self.ch})) {
            self.read_char();
            if (!contains(self.input[pos..self.curr])) {
                break :blk;
            }
        }
        return self.input[pos..self.curr];
    }
    fn read_ws(self: *File) void {
        blk: {
            while (true) {
                switch (self.ch) {
                    ' ', '\t', '\r' => {
                        self.read_char();
                    },
                    else => {
                        break :blk;
                    },
                }
            }
        }
    }
};
const Token = struct {
    type: string,
    val: string,
    start: usize,
    end: usize,
    fn new(_type: string, val: string, s: usize, e: usize) Token {
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

pub fn main() !void {
    var f = File.new("main.dyn", "f32 x = 4.0;");
    var token = f.get_token();
    while (std.mem.count(u8, token.type, "EOF") == 0) {
        print_token(token);
        token = f.get_token();
    }
    return;
}
