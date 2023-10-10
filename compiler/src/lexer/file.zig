const std = @import("std");
const string = @import("../util.zig").string;
const Token = @import("./token.zig").Token;
const lang = @import("language.zig");

pub const File = struct {
    name: string,
    input: string,
    curr: usize,
    next: usize,
    ch: u8,
    pub fn new(name: string, input: string) File {
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
    pub fn get_token(self: *File) Token {
        const pos = self.curr;
        var tok: Token = undefined;
        self.read_ws();
        switch (self.ch) {
            'a'...'z', 'A'...'Z' => {
                var x = self.read_word();
                var y: string = undefined;
                if (lang.contains(x)) {
                    y = "Keyword"; // keyword
                } else {
                    y = "Identifer"; // identifier
                }
                tok = Token.new(y, x, pos, self.curr - @intFromBool(self.curr > pos));
            },
            '0'...'9' => {
                var x = self.read_num();
                var y: string = undefined;
                if (std.mem.count(u8, x, ".") > 0) {
                    y = "Floating"; // float
                } else {
                    y = "Integer"; // integer
                }
                tok = Token.new(y, x, pos, self.curr - @intFromBool(self.curr > pos)); // int
            },
            else => {
                if (lang.contains(&[_]u8{self.ch})) {
                    const x = self.read_op();
                    tok = Token.new("Operator", x, pos, self.curr - @intFromBool(self.curr > pos));
                } else if (self.next >= self.input.len) {
                    tok = Token.new("EOF", "", pos, self.curr - @intFromBool(self.curr > pos)); // eof
                } else {
                    tok = Token.new("Illegal", "", pos, self.curr - @intFromBool(self.curr > pos)); // illegal
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
        while (lang.contains(self.get_piece(pos, self.curr)) and self.next <= self.input.len) {
            self.read_char();
        }
        return self.get_piece(pos, self.curr);
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
    fn get_piece(self: *File, s: usize, e: usize) string {
        return self.input[s..(e + @intFromBool(s == e))];
    }
};

pub const File2 = struct {
    name: string,
    input: string,
    curr: usize,
    pub fn new(name: string, input: string) File2 {
        var f: File = .{
            .name = name,
            .input = input,
            .curr = 0,
        };
        f.read_char();
        return f;
    }
    fn read_char(self: *File2) void {
        self.curr += 1;
        return;
    }
    pub fn get_token(self: *File2) Token {
        var tok: Token = undefined;
        if (self.curr >= self.input.len) {
            tok = Token.new("EOF", "", self.curr, self.curr);
        } else {
            const pos = self.curr;
            switch (self.input[self.curr]) {
                'a'...'z', 'A'...'Z' => {
                    var x = self.r_w();
                    tok = Token.new(if (lang.contains) {
                        return "Keyword";
                    } else {
                        return "Identifier";
                    }, x, pos, self.curr);
                },
                '0'...'9' => {
                    var x = self.r_n();
                    tok = Token.new(if (std.mem.count(u8, x, ".") > 0) {
                        return "Floating";
                    } else {
                        return "Integer";
                    }, x, pos, self.curr);
                },
                else => {
                    tok = if (lang.contains(self.input[self.curr .. self.curr + 1])) {
                        return Token.new("Operator", self.read_op(), pos, self.curr);
                    } else {
                        return Token.new("Illegal", "", pos, self.curr);
                    };
                },
            }
            if (self.curr == pos) {
                self.read_char();
            }
        }
        return tok;
    }
    fn r_w(self: *File2) string {
        _ = self;
    }
    fn r_n(self: *File2) string {
        _ = self;
    }
    fn r_o(self: *File2) string {
        _ = self;
    }
    fn r_ws(self: *File2) string {
        _ = self;
    }
};
