const std = @import("std");
const string = []const u8;

const Token = struct {
    type: string,
    val: TokenValType,
    fn init(tokentype: string, val: TokenValType) Token {
        return .{
            .type = tokentype,
            .val = val,
        };
    }
};

const TokenValType = union {
    float: f64,
    str: string,
    int: i128,
    uint: u128,
    none: void,
    character: u8,
};

const lang = struct {
    literals: []string = []string{ "character", "floating", "integer", "identifier", "string" },
    keywords: []string = []string{ "void", "bool", "char", "f32", "f64", "i8", "i16", "i32", "i64", "i128", "u8", "u16", "u32", "u64", "u128" },
    operators: []string = []string{
        "+",
        "-",
        "*",
        "/",
        "%",
        ";",
        ":",
        ",",
        "=",
        "&",
        "|",
        "!",
        ">",
        "<",
        "(",
        "[",
        "{",
        ")",
        "]",
        "}",
        ".",
    },
    compoundOperators: []string = []string{
        "++",
        "--",
        "&&",
        "||",
        "!=",
        ">=",
        "<=",
    },
};

const Lexer = struct {
    tokens: std.ArrayList(Token),
    pos: i32,
    readPos: i32,
    name: string,
    input: string,
    c: ?u8,
    fn init(comptime filename: string, comptime input: string) Lexer {
        const toReturn = .{
            .tokens = std.ArrayList(Token).init(),
            .pos = 0,
            .readPos = 0,
            .c = undefined,
            .input = input,
            .name = filename,
        };
        toReturn.readChar();
        return toReturn;
    }
    fn readChar(self: *Lexer) void {
        if (self.readPos > self.file.input.len) {
            self.c = undefined;
        } else {
            self.c = self.file.input[self.file.readPos];
            self.pos = self.file.readPos;
            self.readPos += 1;
        }
    }
    fn read_token(self: *Lexer) bool {
        if (self.c != undefined) {
            switch (self.c) {
                blk: {
                    break :blk self.is_op(self.c);
                } => {
                    const peakC = self.peak();
                    var op = std.fmt.allocPrint("{any}{any}", .{ self.c, peakC });
                    if (peak != undefined and lang.compoundOperators.contains(op)) {
                        self.tokens.append(Token.init(op, void));
                        self.readChar(); // skip the char that we peak
                    } else {
                        self.tokens.append(Token.init(self.c, void));
                    }
                },
                blk: {
                    break :blk self.is_letter(self.c);
                } => {
                    const x = self.read_word();
                    if (lang.keywords.contains(x)) {
                        self.tokens.append(lang.keywords.get(x).?.init(x, void));
                    } else {
                        self.tokens.append(Token.init("identifier", x));
                    }
                },
                blk: {
                    break :blk self.is_number(self.c);
                } => {
                    const x = self.read_number();
                    if (x.contains('.')) {
                        self.tokens.append(Token.init("floating", std.fmt.parseFloat(f64, x)));
                    } else {
                        self.tokens.append(Token.init("integer", std.fmt.parseInt(i128, x)));
                    }
                },
                else => {},
            }
            self.readChar();
            return true;
        } else {
            self.tokens.append(Token.init("EOF", void));
            return false;
        }
    }
    fn read_word(self: *Lexer) void {
        var pos = self.pos;
        while (self.is_letter(self.c)) {
            self.readChar();
        }
        return self.input[pos..self.pos];
    }
    fn read_number(self: *Lexer) void {
        var pos = self.pos;
        while (self.is_number(self.c)) {
            self.readChar();
        }
        return self.input[pos..self.pos];
    }

    fn is_op(x: u8) bool {
        lang.operators.contains(x);
    }
    fn is_letter(x: u8) bool {
        return switch (x) {
            'a'...'z', 'A'...'Z' => true,
            else => false,
        };
    }
    fn is_number(x: u8) bool {
        return switch (x) {
            '0'...'9', '-', '_' => true,
            else => false,
        };
    }
    fn peak(self: *Lexer) ?u8 {
        if (self.pos + 1 > self.input.len) {
            return undefined;
        } else {
            return self.input[self.pos + 1];
        }
    }
};

pub fn main() !void {
    var lex = Lexer.init("main.dyn", "i32 x = 4;");
    std.debug.print("{any}\n", .{lex});
}
