const std = @import("std");
const string = @import("util.zig").string;
const File = @import("./lexer.zig").File;
const print_token = @import("./lexer.zig").print_token;

pub fn main() !void {
    var f = File.new("main.dyn", "if x == 3 { io.println(x) }");
    var token = f.get_token();
    while (std.mem.count(u8, token.type, "EOF") == 0) {
        print_token(token);
        token = f.get_token();
    }
    return;
}
