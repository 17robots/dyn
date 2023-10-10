const std = @import("std");
const string = @import("../util.zig").string;
const Token = @import("./token.zig").Token;
const lang = @import("language.zig");

pub const File = struct {
    name: string,
    input: string,
    curr: usize,
    pub fn new(name: string, input: string) File {
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
                    tok = Token.new(if (lang.contains(x)) "Keyword" else "Identifier", x, pos, self.curr);
                },
                '0'...'9' => {
                    var x = self.r_n();
                    tok = Token.new(if (std.mem.count(u8, x, ".") > 0) "Floating" else "Integer", x, pos, self.curr);
                },
                else => {
                    tok = if (lang.contains(self.sub(self.curr, self.curr))) {
                        return Token.new("Operator", self.r_o(), pos, self.curr);
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
    fn valid(self: *File) bool {
        return self.curr < self.input.len;
    }
    fn r_w(self: *File) string {
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
    fn r_n(self: *File) string {
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
    fn r_o(self: *File) string {
        const pos = self.curr;
        blk: while (self.valid()) {
            switch (self.input[self.curr]) {
                else => {
                    if (lang.contains(self.sub(pos, self.curr)) and lang.contains(self.sub(self.curr, self.curr))) {
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
    fn sub(self: *File, s: usize, e: usize) string {
        return self.input[s..(e + @intFromBool(s == e))];
    }
};
