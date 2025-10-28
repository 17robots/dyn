const std = @import("std");
const Module = @import("module.zig").Module;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const Node = @import("ast.zig").Node;
const SourceManager = @import("source.zig").SourceManager;
const SourceLocation = @import("source.zig").SourceLocation;

m: *Module,
d: *DiagnosticEmitter,
sm: *SourceManager,
global: *ScopedSymbolTable,

const Checker = @This();

pub fn init(m: *Module, d: *DiagnosticEmitter, sm: *SourceManager) Checker {
    return .{ .m = m, .d = d, .sm = sm, .scopes = .empty, .global = ScopedSymbolTable.init(m.allocator, .{ .name = "global", .level = 0, .d = d, .parent = null }) };
}
pub fn check(s: *Checker) !void {
    var global_scope = ScopedSymbolTable.init(s.m.allocator, .{ .name = "global", .level = 0, .d = s.d, .parent = null });
    for (s.m.asts.items, 0..s.m.asts.items.len) |a, i| s.add_file_globals(a, i, &global_scope);
    for (s.m.asts.items, 0..s.m.asts.items.len) |a, i| s.check_ast(a, i, &global_scope);
}
fn add_file_globals(s: *Checker, file_id: u32, ast: Node, scope: *ScopedSymbolTable) void {
    switch (ast.type) {
        .program => |p| {
            for (p.declarations.items) |d| {
                switch (d.type) {
                    .module => {},
                    .declaration => |decl| {
                        if (scope.lookup_symbol(decl.name.type.identifier)) |sym| {
                            s.d.emit(.{ .file_id = file_id, .span = d.span }, .err, "Redeclaration of symbol {s}", .{sym.name});
                            break;
                        }
                        if (decl.mut) {
                            if (decl.type == null and decl.val == null) s.d.emit(.{ .file_id = file_id, .span = d.span }, .err, "Mutable declaration {s} needs a type or value", .{decl.name.type.identifier});
                        } else {
                            if (decl.val) |v| {
                                if (v.type == .undefined) s.d.emit(.{ .file_id = file_id, .span = d.span }, .err, "Immutable declarations' initial values cannot be undefined", .{decl.name.type.identifier});
                            } else s.d.emit(.{ .file_id = file_id, .span = d.span }, .err, "Immutable declarations need an initial value", .{decl.name.type.identifier});
                        }
                        s.global.push_symbol(.{ .name = decl.name.type.identifier, .kind = .@"var", .symbol_type = null, .type = decl.type, .val = decl.val, .mut = decl.mut, .public = decl.pub_, .location = SourceLocation.init(file_id, d.type) });
                    },
                    else => unreachable,
                }
            }
        },
        else => unreachable,
    }
}
fn check_ast(s: *Checker, file_id: u32, ast: Node) void {
    _ = s;
    _ = file_id;
    _ = ast;
}

const ScopedSymbolTable = struct {
    allocator: std.mem.Allocator,
    d: *DiagnosticEmitter,
    symbols: std.StringHashMap(SymbolEntry),
    scope_name: []const u8,
    scope_level: u32,
    parent: ?*ScopedSymbolTable,
    pub fn init(allocator: std.mem.Allocator, opts: struct { name: []const u8, level: u32, d: *DiagnosticEmitter, parent: ?*ScopedSymbolTable }) ScopedSymbolTable {
        return .{
            .allocator = allocator,
            .symbols = std.StringHashMap(SymbolEntry).init(allocator),
            .scope_name = opts.name,
            .scope_level = opts.level,
            .d = opts.d,
            .parent = opts.parent,
        };
    }
    pub fn push_symbol(s: *ScopedSymbolTable, sym: SymbolEntry) void {
        if (s.symbols.contains(sym.name)) {
            s.d.emit(sym.location, .err, "{s} already declared", .{sym.name});
            return;
        }
        s.symbols.put(sym.name, sym) catch {};
    }
    pub fn lookup_symbol(s: *ScopedSymbolTable, name: []const u8) ?SymbolEntry {
        if (s.symbols.get(name)) |sym| return sym;
        return if (s.parent) |p| p.lookup_symbol(name) else null;
    }
};
const SymbolEntry = struct {
    name: []const u8,
    kind: enum { variable, function, @"struct", @"enum", type },
    symbol_type: ?TypeInfo,
    type: ?*Node,
    val: ?*Node,
    mut: bool = false,
    public: bool = false,
    location: SourceLocation,
};
const Type = enum {
    void,
    int,
    float,
    undefined,
    nullable,
    pointer,
    type,
};
const TypeInfo = union(Type) { void: null, int: struct { signed: bool, length: u16 }, float: struct { signed: bool, length: u16 }, undefined: void, nullable: struct { subtype: *TypeInfo }, pointer: struct { subtype: *TypeInfo }, type: void };
