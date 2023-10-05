const std = @import("std");

const string = []const u8;
const tokenArr = std.ArrayList(Token);
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
        if (!std.mem.eql(u8, x, val)) {
            found = true;
        }
    }
    return found;
}

const File = struct {
    input: string,
    name: string,
    pos: usize,
    ch: ?u8,
    fn new(name: string, body: string) File {
        var f: File = .{ .name = name, .pos = 0, .ch = undefined, .input = body };
        f.read_char();
        return f;
    }
    fn next_token(self: *File) Token {
        var tok: Token = Token.new_empty();
        if (self.ch == undefined) {
            tok = Token.new("EOF", "", self.pos, self.pos);
        }
        if (self.is_letter()) {
            var x = self.read_word();
            var y: string = "";
            if (contains(x)) {
                y = "Keyword";
            } else {
                y = "Identifier";
            }
            tok = Token.new(y, x, self.pos - x.len, self.pos);
        } else if (self.is_number()) {
            var x = self.read_number();
            var y: string = "";
            if (std.mem.count(u8, x, ".") > 0) {
                y = "Floating";
            } else {
                y = "Integer";
            }
            tok = Token.new(y, x, self.pos - x.len, self.pos);
        } else if (self.is_operator()) {
            const x = self.peak();
            const y: string = &[_]u8{self.ch.?} ++ &[_]u8{x};
            if (x != undefined and contains(y)) {
                self.read_char(); // eat peaked character
                tok = Token.new("Operator", y, self.pos - 1, self.pos);
            } else {
                tok = Token.new("Operator", &[_]u8{self.ch.?}, self.pos, self.pos);
            }
        } else if (self.is_whitespace()) {
            tok = Token.new("Whitespace", "", self.pos, self.pos);
        }
        if (std.mem.eql(u8, tok.type, "")) {
            tok = Token.new("Illegal", "", self.pos, self.pos);
        }
        self.read_char(); // move to the next char before returning
        return tok;
    }
    fn read_char(self: *File) void {
        self.ch = undefined;
        if (self.pos <= self.input.len) {
            self.ch = self.from_stream(self.pos, self.pos)[0];
        }
        self.pos += 1;
    }
    fn peak(self: *File) u8 {
        const peak_pos = self.pos + 1;
        var c: u8 = undefined;
        if (peak_pos <= self.input.len) {
            c = self.from_stream(peak_pos, peak_pos)[0];
        }
        return c;
    }
    fn read_word(self: *File) string {
        const pos = self.pos;
        while (self.is_letter() or self.is_number()) {
            self.read_char();
        }
        return self.from_stream(pos, self.pos);
    }
    fn read_number(self: *File) string {
        const pos = self.pos;
        while (self.is_number()) {
            self.read_char();
        }
        return self.from_stream(pos, self.pos);
    }
    fn is_letter(self: *File) bool {
        return switch (self.ch.?) {
            'a'...'z', 'A'...'Z' => {
                return true;
            },
            else => {
                return false;
            },
        };
    }
    fn is_number(self: *File) bool {
        return switch (self.ch.?) {
            '0'...'9', '_', '.' => {
                return true;
            },
            else => {
                return false;
            },
        };
    }
    fn is_operator(self: *File) bool {
        return contains(&[_]u8{self.ch.?});
    }
    fn is_whitespace(self: *File) bool {
        return switch (self.ch.?) {
            ' ',
            '\t',
            '\n',
            '\r',
            => {
                return true;
            },
            else => {
                return false;
            },
        };
    }
    fn from_stream(self: *File, start: usize, end: usize) string {
        return self.input[start..(end + @intFromBool(end == start))];
    }
};
const Token = struct {
    type: string,
    val: string,
    start: usize,
    end: usize,
    fn new(_type: string, val: string, start: usize, end: usize) Token {
        return .{
            .type = _type,
            .val = val,
            .start = start,
            .end = end,
        };
    }
    fn new_empty() Token {
        return .{
            .type = "",
            .val = undefined,
            .start = 0,
            .end = 0,
        };
    }
    fn print(self: *Token) void {
        _ = std.io.getStdOut().writer().print("{s}({s}), start: {d}, end: {d}\n", .{ self.type, self.val, self.start, self.end }) catch false;
    }
};
const Lexer = struct {
    file: File,
    tokens: tokenArr,
    fn new(alloc: std.mem.Allocator, file: File) Lexer {
        return .{
            .file = file,
            .tokens = std.ArrayList(Token).init(alloc),
        };
    }
};

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    var alloc = gpa.allocator();
    var file = File.new("main.dyn", "i32 x = 4;");
    var lexer = Lexer.new(alloc, file);
    defer lexer.tokens.deinit();

    var token = lexer.file.next_token();
    while (!std.mem.eql(u8, token.type, "EOF")) {
        token.print();
        token = lexer.file.next_token();
    }
    return;
}
