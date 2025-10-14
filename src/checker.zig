const std = @import("std");
const Module = @import("module.zig").Module;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const Node = @import("ast.zig").Node;
const symbol = @import("symbol.zig");

m: *Module,
d: *DiagnosticEmitter,
sm: *SourceManager,
// scopes: symbol.ScopeStack,

const Checker = @This();

pub fn init(m: *Module, d: *DiagnosticEmitter, sm: *SourceManager) Checker {
    return .{ .m = m, .d = d, .sm = sm, .scopes = .empty };
}
pub fn check(s: *Checker) !void {}

const ScopedSymbolTable = struct {
    allocator: std.mem.Allocator,
    d: *DiagnosticEmitter,
    file_id: u32,
    symbols: std.StringHashMap(SymbolEntry),
    scope_name: []const u8,
    scope_level: u32 = 0,
    parent: ?*ScopedSymbolTable,
    pub fn init(allocator: std.mem.Allocator, opts: struct { name: []const u8, level: u32, file_id: u32, d: *DiagnosticEmitter, parent: ?*ScopedSymbolTable }) ScopedSymbolTable {
        return .{
            .allocator = allocator,
            .symbols = std.StringHashMap(SymbolEntry).init(allocator),
            .scope_name = opts.name,
            .scope_level = opts.level,
            .file_id = opts.file_id,
            .d = opts.d,
            .parent = opts.parent,
        };
    }
    pub fn push_symbol(s: *ScopedSymbolTable, sym: SymbolEntry) void {
        if (s.symbols.contains(sym.name)) {}
    }
};
const SymbolEntry = struct {
    name: []const u8,
    kind: enum { variable, function, @"struct", @"enum", type },
    type: ?*Node,
    val: ?*Node,
    mut: bool = false,
    public: bool = false,
};
