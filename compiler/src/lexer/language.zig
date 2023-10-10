const std = @import("std");
const string = @import("../util.zig").string;

pub const language = [_]string{
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

pub fn contains(val: string) bool {
    var found = false;
    for (language) |x| {
        if (std.mem.eql(u8, x, val)) {
            found = true;
        }
    }
    return found;
}
