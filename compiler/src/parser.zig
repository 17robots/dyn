const std = @import("std");
const Lexer = @import("lexer.zig");
const CompilerError = @import("errors.zig").CompilerError;
const Ast = @import("ast.zig");

const Parser = struct {
    err: ?CompilerError,
    lexer: Lexer,
    alloc: *std.mem.Allocator,

    pub fn init(alloc: *std.mem.Allocator, s: []u8) Parser {
        return .{
            .err = null,
            .lexer = Lexer.init(s),
            .alloc = alloc,
        };
    }
    pub fn program(s: *Parser) Ast.Program {
        var x = Ast.Program.init(s.alloc);
    }
};
