const std = @import("std");

pub const Token = struct {
    t: u8,
    v: []const u8,
};

const TokenList = std.ArrayList(Token);

const OPS = [_][]const u8{
    ";",  ":",  ".",  ",",  "(",  "[",  "{",  ")",  "]",  "}",  "=",
    "!",  "<",  ">",  "*",  "+",  "/",  "-",  "&",  "|",  "==", "!=",
    "<=", ">=", "*=", "+=", "/=", "-=", "&=", "&&", "|=", "||", "=>",
};

pub const Tokenizer = struct {
    stream: []const u8,
    tokens: std.ArrayList(Token),
    buffer: []const u8,
    state: ParserState,
    const ParserState = enum {
        START,
        READ_WORD,
        READ_NUM,
        READ_STRING,
        READ_CHAR,
        READ_OP,
    };
    pub fn init(alloc: *const std.mem.Allocator, stream: []const u8) Tokenizer {
        return Tokenizer{
            .stream = stream,
            .state = .START,
            .tokens = std.ArrayList(Token).init(alloc.*),
            .buffer = "",
        };
    }
    pub fn deinit(self: *Tokenizer) void {
        self.tokens.deinit();
    }
    fn is_c(x: u8) bool {
        return (x >= 'a' and x <= 'z') or (x >= 'A' and x <= 'Z');
    }
    fn is_n(x: u8, s: ParserState) bool {
        if (x == '.') {
            return s == .READ_NUM;
        }
        return x >= '0' and x <= '9';
    }
    fn is_o(x: []const u8) bool {
        for (0..OPS.len) |i| {
            if (std.mem.eql(u8, OPS[i], x)) {
                return true;
            }
        }
        return false;
    }
    fn is_w(x: u8) bool {
        return x == '\r' or x == '\n' or x == '\t' or x == ' ';
    }
    fn grab_state(self: *Tokenizer, x: u8) ParserState {
        if (x == '\"') {
            return .READ_STRING;
        }
        if (is_c(x)) {
            return .READ_WORD;
        }
        if (is_n(x, self.state)) {
            return .READ_NUM;
        }
        if (is_o(&[1]u8{x})) {
            return .READ_OP;
        }
        return .START;
    }
    fn clear_buf(b: *std.ArrayList(u8)) ![]const u8 {
        const y = try b.*.toOwnedSlice();
        return y;
    }
    pub fn lex(self: *Tokenizer) !void {
        var b2 = std.ArrayList(u8).init(self.tokens.allocator);
        defer b2.deinit();
        for (self.stream) |c| {
            std.debug.print("character: {c}\n", .{c});
            switch (self.state) {
                .START => {
                    self.state = self.grab_state(c);
                    if (self.state == .START and !Tokenizer.is_w(c)) {
                        try self.tokens.append(Token{ .t = 1, .v = "" });
                    }
                },
                .READ_WORD => {
                    if (!(Tokenizer.is_c(c) or Tokenizer.is_n(c, self.state))) {
                        try self.tokens.append(Token{ .t = 2, .v = try Tokenizer.clear_buf(&b2) });
                        self.state = self.grab_state(c);
                    }
                },
                .READ_NUM => {
                    if (!Tokenizer.is_n(c, self.state)) {
                        try self.tokens.append(Token{ .t = 3, .v = try Tokenizer.clear_buf(&b2) });
                        self.state = self.grab_state(c);
                    }
                },
                .READ_STRING => {
                    if (c == '\"') {
                        try self.tokens.append(Token{ .t = 4, .v = try Tokenizer.clear_buf(&b2) });
                        self.state = .START;
                    }
                },
                .READ_CHAR => {},
                .READ_OP => {
                    var curr = try b2.clone();
                    try curr.append(c);
                    if (!Tokenizer.is_o(curr.items)) {
                        try self.tokens.append(Token{ .t = 6, .v = try Tokenizer.clear_buf(&b2) });
                        self.state = self.grab_state(c);
                    }
                    curr.deinit();
                },
            }
            if (self.state != .START) {
                try b2.append(c);
            }
        }
        try self.tokens.append(Token{ .t = @intFromEnum(self.state), .v = try Tokenizer.clear_buf(&b2) });
    }
};
