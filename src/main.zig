const std = @import("std");
const Lexer = @import("lexer.zig").Lexer;
const TokenType = @import("token.zig").TokenType;

pub fn main() !void {
    const page_allocator = std.heap.page_allocator;
    var arena = std.heap.ArenaAllocator.init(page_allocator);
    const alloc = arena.allocator();
    defer arena.deinit();

    const x = try read_file(alloc, "syntax.dyn");

    var l = Lexer.init(x);
    while (l.tok != .eof and l.tok != .invalid) {
        l.next_tok();
        if (l.err) |err| {
            switch (err) {
                .InvalidCharacter => std.debug.print("Line {} Column {}: Invalid Character {c}", .{ l.line, l.col, l.buffer[l.index] }),
                .InvalidEscape => std.debug.print("Line {} Col {}: Invalid Escape {c}", .{ l.line, l.col, l.buffer[l.index] }),
                .InvalidCharLength => std.debug.print("Line {} Col {}: Invalid Char Length", .{ l.line, l.col }),
            }
            break;
        } else {
            print_token(l);
        }
    }
}

pub fn read_file(a: std.mem.Allocator, filename: []const u8) ![]const u8 {
    const file = try std.fs.cwd().openFile(filename, .{ .mode = .read_only });
    defer file.close();
    const stat = try file.stat();
    return try file.readToEndAlloc(a, stat.size);
}

pub fn test_for(lex: Lexer, t: TokenType, l: ?[]const u8) void {
    std.debug.assert(lex.tok == t);
    if (l) |lit| {
        std.debug.assert(std.mem.eql(u8, lex.literal orelse "", lit));
    }
}

pub fn print_token(l: Lexer) void {
    std.debug.print("{s} {s}\n", .{
        if (l.tok) |tok|
            switch (tok) {
                .eof => "eof",
                .invalid => "invalid",
                .identifier => "identifier",
                .int => "int",
                .float => "float",
                .string => "string",
                .char => "char",
                .add => "add",
                .sub => "sub",
                .mul => "mul",
                .div => "div",
                .mod => "mod",
                .@"and" => "and",
                .@"or" => "or",
                .xor => "xor",
                .flip => "flip",
                .eq => "eq",
                .addeq => "addeq",
                .addadd => "addadd",
                .subeq => "subeq",
                .subsub => "subsub",
                .muleq => "muleq",
                .diveq => "diveq",
                .modeq => "modeq",
                .andeq => "andeq",
                .oreq => "oreq",
                .xoreq => "xoreq",
                .flipeq => "flipeq",
                .andand => "andand",
                .oror => "oror",
                .eqeq => "eqeq",
                .gt => "gt",
                .lt => "lt",
                .gteq => "gteq",
                .lteq => "lteq",
                .lparen => "lparen",
                .rparen => "rparen",
                .lbrack => "lbrack",
                .rbrack => "rbrack",
                .lbrace => "lbrace",
                .rbrace => "rbrace",
                .dot => "dot",
                .dotdot => "dotdot",
                .colon => "colon",
                .semicolon => "semicolon",
                .underscore => "underscore",
                .comma => "comma",
                .arrow => "arrow",
                .bang => "bang",
                .bangeq => "bangeq",
                .question => "question",
                .dollar => "dollar",
                .module => "module",
                .use => "use",
                .void => "void",
                .mut => "mut",
                .true => "true",
                .false => "false",
                .@"if" => "if",
                .@"else" => "else",
                .match => "match",
                .@"defer" => "defer",
                .loop => "loop",
                .@"for" => "for",
                .@"enum" => "enum",
                .@"error" => "error",
                .@"try" => "try",
                .@"catch" => "catch",
                .@"union" => "union",
                .@"struct" => "struct",
                .type => "type",
                .comp => "comp",
            }
        else
            "",
        l.literal orelse "",
    });
}
