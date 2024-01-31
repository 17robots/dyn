const std = @import("std");
const a = std.heap.GeneralPurposeAllocator(.{}){};
const alloc = a.allocator();

const Token = struct {
    t: u8,
    v: []const u8,
};

const OPS: [][]const u8 = .{
    ";",  ":",  ".",  ",",  "(",  "[",  "{",  ")",  "]",  "}",  "=",
    "!",  "<",  ">",  "*",  "+",  "/",  "-",  "&",  "|",  "==", "!=",
    "<=", ">=", "*=", "+=", "/=", "-=", "&=", "&&", "|=", "||", "=>",
};

const ParserState = enum {
    START,
    READ_WORD,
    READ_NUM,
    READ_STRING,
    READ_CHAR,
    READ_OP,
};

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
        if (OPS[i] == x) {
            return true;
        }
    }
    return false;
}
fn is_w(x: u8) bool {
    return x == '\r' or x == '\n' or x == '\t' or x == ' ';
}
fn grab_state(x: u8, s: ParserState) ParserState {
    if (x == '\"') {
        return .READ_STRING;
    }
    if (is_c(x)) {
        return .READ_WORD;
    }
    if (is_n(x, s)) {
        return .READ_NUM;
    }
    if (is_o(x)) {
        return .READ_OP;
    }
    return .START;
}
fn clear_buf(x: *std.ArrayList(u8)) []const u8 {
    const y = try std.mem.join(alloc, "", x);
    x.clearAndFree();
    return y;
}
pub fn lex(input: []const u8) std.ArrayList(Token) {
    const s = .START;
    const t = std.ArrayList(Token).init(alloc);
    const b = std.ArrayList(u8).init(alloc);
    defer b.deinit();
    for (0..input.len) |i| {
        switch (s) {
            .START => {
                s = grab_state(input[i], s);
                if (s == .START and !is_w(input[i])) {
                    t.append(Token{ .t = 1, .v = "" });
                }
                break;
            },
            .READ_WORD => {
                if (!(is_c(input[i]) or is_n(input[i], s))) {
                    t.append(Token{ .t = 2, .v = clear_buf(&b) });
                    s = grab_state(input[i], .START);
                }
                break;
            },
            .READ_NUM => {
                if (!is_n(input[i], s)) {
                    t.append(Token{ .t = 3, .v = clear_buf(&b) });
                    s = grab_state(input[i], .START);
                    b.clearAndFree();
                }
                break;
            },
            .READ_STRING => {
                if (input[i] == '\"') {
                    b.append(input[i]);
                    t.append(Token{ .t = 4, .v = clear_buf(&b) });
                    s = .START;
                }
                break;
            },
            .READ_CHAR => {
                break; // this needs done
            },
            .READ_OP => {
                const c = b ++ input[i];
                if (!is_o(c)) {
                    t.append(Token{ .t = 6, .v = clear_buf(&b) });
                    s = grab_state(input[i], .START);
                }
                break;
            },
        }
        if (s != .START) {
            b.append(input[i]);
        }
    }
    t.append(.{});
    return t;
}
