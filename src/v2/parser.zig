const std = @import("std");
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const Diagnostic = @import("diagnostic.zig").Diagnostic;
const Lexer = @import("lexer.zig");
const Node = @import("ast.zig").Node;
const Source = @import("source.zig").Source;
const SourceLocation = @import("source.zig").SourceLocation;
const Token = @import("lexer.zig").Token;
const TokenType = @import("token.zig").TokenType;

const Parser = @This();

allocator: std.mem.Allocator,
diag: *DiagnosticEmitter,
lexer: Lexer,
source: *Source,

pub fn init(allocator: std.mem.Allocator, source: *Source, diagnostics: *DiagnosticEmitter) Parser {
    return .{ .allocator = allocator, .source = source, .lexer = Lexer.init(source, diagnostics), .diag = diagnostics };
}

// parser methods
pub fn parse(s: *Parser) !Node {
    var declarations = std.ArrayList(Node).init(s.allocator);
    declarations.append(try s.module_declaration()) catch |e| @panic(@errorName(e));
    blk: while (s.lexer.index < s.source.content.len or (try s.peek()).tok_type != .eof) {
        const d = s.declaration(true) catch {
            s.recover();
            continue :blk;
        };
        declarations.append(d) catch |e| @panic(@errorName(e));
    }
    return Node{ .program = .{ .declarations = declarations } };
}
fn module_declaration(s: *Parser) !Node {
    _ = s.expect(.module, false) catch {
        s.diag.emit(SourceLocation{ .file_id = s.source.id, .index = 0 }, .err, "File Must Start With Module Declaration", .{});
    };
    const name = try s.identifier();
    _ = s.expect(.semicolon, true);
    return Node{ .module = .{ .name = try s.create_node_ptr(name) } };
}
fn declaration(s: *Parser, root_declaration: bool) !Node {
    const pub_ = if((try s.peek()).tok_type == .@"pub") blk: {
        _ = s.expect(.@"pub", true);
        break :blk true;
    } else false;
    if(pub_ and !root_declaration) {
        s.diag.emit(SourceLocation{ .file_id = s.source.id, .index = @intCast(s.lexer.index)}, .err, "Pub Only Allowed In Global Scope", .{});
        return error.NoPubInLocalScope;
    }
    const mut_ = if((try s.peek()).tok_type == .mut) blk: {
        _ = s.expect(.mut, true);
        break :blk true;
    } else false;
    const name = try s.identifier();
}
fn statement(s: *Parser) !Node {
    return switch((try s.peek()).tok_type) {
       .@"if" => {}, // try if_statement(),
       .@"for" => {}, // try for_statement(),
       .@"while" => {}, // try while_statement(),
       .@"defer" => {}, // try defer_statement(),
       .match => {}, // try match_statement(),
       .lbrace => {}, // try block(),
       .mut => try s.declaration(false),
       else => {
       },
    };
}
fn expression(s: *Parser) !Node {}
fn non_literal_expression(s: *Parser) !Node {}
fn identifier(s: *Parser) !Node {
    return Node{ .identifier = (try s.expect(.identifier, true)).val.? };
}

// helper methods
fn peek(s: *Parser) !Token {
    return try s.lexer.peek();
}
fn expect(s: *Parser, expected: TokenType, emit_diag: bool) !Token {
    const tok = try s.lexer.next_tok();
    if (tok.tok_type != expected) {
        if (emit_diag) s.diag.emit(tok.loc, .err, "Unexpected tok {s}, wanted {s}", .{ tok.tok_type, expected });
        return error.UnexpectedToken;
    }
    return tok;
}
fn create_node_ptr(s: *Parser, n: Node) *Node {
    const x = s.a.create(Node) catch |e| @panic(@errorName(e));
    x.* = n;
    return x;
}
fn recover(s: *Parser) void {
}
