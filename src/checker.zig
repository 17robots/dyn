const std = @import("std");
const Module = @import("module.zig").Module;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const Node = @import("ast.zig").Node;
const SourceManager = @import("source.zig").SourceManager;
const SourceLocation = @import("source.zig").SourceLocation;

m: *Module,
d: *DiagnosticEmitter,
sm: *SourceManager,
// scopes: symbol.ScopeStack,

const Checker = @This();

pub fn init(m: *Module, d: *DiagnosticEmitter, sm: *SourceManager) Checker {
    return .{ .m = m, .d = d, .sm = sm, .scopes = .empty };
}
pub fn check(s: *Checker) !void {
    var global_scope = ScopedSymbolTable.init(s.m.allocator, .{ .name = "global", .level = 0, .d = s.d, .parent = null });
    for (s.m.asts.items) |a| s.check_file_globals(a, &global_scope);
}
fn check_file_globals(s: *Checker, file_id: u32, ast: Node, scope: *ScopedSymbolTable) void {
    switch (ast.type) {
        .program => |p| {
            for (p.declarations.items) |d| {
                switch (d.type) {
                    .module => {},
                    .declaration => |decl| {
                        // check that the variable hasnt already been declared already
                        if (scope.lookup_symbol(decl.name.type.identifier)) |sym| {
                            s.d.emit(.{ .file_id = file_id, .span = d.span }, .err, "Redeclaration of symbol {s}", .{sym.name});
                            break;
                        }
                        // check
                        if (decl.mut) {
                            if (decl.type == null and decl.val == null) s.d.emit(.{ .file_id = file_id, .span = d.span }, .err, "Mutable declaration {s} needs a type or value", .{decl.name.type.identifier});
                        } else {
                            if (decl.val) |v| {
                                if (v.type == .undefined) s.d.emit(.{ .file_id = file_id, .span = d.span }, .err, "Immutable declarations' initial values cannot be undefined", .{decl.name.type.identifier});
                            } else s.d.emit(.{ .file_id = file_id, .span = d.span }, .err, "Immutable declarations need an initial value", .{decl.name.type.identifier});
                        }
                    },
                    else => unreachable,
                }
            }
        },
        else => unreachable,
    }
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
const TypeInfo = union(enum) {};
