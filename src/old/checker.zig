const std = @import("std");
const Module = @import("module.zig").Module;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const Node = @import("ast.zig").Node;
const SourceManager = @import("file.zig").SourceManager;
const SourceLocation = @import("file.zig").SourceLocation;
const Span = @import("token.zig").Span;

m: *Module,
d: *DiagnosticEmitter,
sm: *SourceManager,
global: *ScopedSymbolTable,
dependency_graph: void,

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

fn check_ast(s: *Checker, file_id: u32, ast: Node, ctx: Context) void {
    switch (ast.type) {
        .arm => |i| {},
        .array_index => |i| {},
        .array_init => |i| {},
        .arrow_expression => |i| {},
        .assign_expression => |i| {},
        .binary_expression => |i| {},
        .block => |i| {
            var block_scope = ScopedSymbolTable.init_from_scope(.{ .name = i.name.type.identifier, .parent = ctx.scope });
        },
        .break_expression => |i| {},
        .call => |i| {},
        .capture => |i| {},
        .capture_val => |i| {},
        .catch_ => |i| {},
        .comp_expression => |i| {},
        .continue_expression => |i| {},
        .declaration => |i| {
            // verify that type and value match
            if (i.val) |v| {
                if (i.type) |t| {
                    // compare type of val and type of type
                }
            } else {
                if (i.mut) {
                    if (i.type == null) s.d.emit(SourceLocation.init(file_id, ast.span), .err, "Mutable declaration {s} must have a type, value, or both", .{i.name.type.identifier});
                } else s.d.emit(SourceLocation.init(file_id, ast.span), .err, "Immutable declaration {s} must have a value", .{i.name.type.identifier});
            }
            if (!ctx.is_global) {
                if (ctx.scope.lookup_symbol(i.name.type.identifier)) s.d.emit(SourceLocation.init(file_id, ast.span), .err, "Symbol {s} already declared", .{i.name.type.identifier});
                if (i.pub_) s.d.emit(SourceLocation.init(file_id, ast.span), .err, "Declaration {s} inside scope cannot be public", .{i.name.type.identifier});
                ctx.scope.push_symbol(SymbolEntry{ .name = i.name.type.identifier, .val = i.val, .type = i.type, .public = i.pub_, .location = SourceLocation.init(file_id, ast.span) });
            }
            if (i.type) |t| s.check_ast(file_id, t.*, ctx);
            if (i.val) |v| s.check_ast(file_id, v.*, ctx);
        },
        .defer_statement => |i| {},
        .enum_ => |i| {
            var enum_scope = ScopedSymbolTable.init_from_scope(.{ .name = i.name.type.identifier, .parent = ctx.scope });
        },
        .enum_error_init => |i| {},
        .error_ => |i| {
            var error_scope = ScopedSymbolTable.init_from_scope(.{ .name = i.name.type.identifier, .parent = ctx.scope });
        },
        .for_statement => |i| {},
        .function => |i| {
            // so this is interesting because we need to load the symbols in from the definition, then we need to check all the statements and the return type, passing the return type as the type in the context
            var fn_scope = ScopedSymbolTable.init_from_scope(.{ .name = i.name.type.identifier, .parent = ctx.scope });
        },
        .function_parameter => |i| {},
        .function_type => |i| {},
        .grouped => |i| {},
        .identifier => |i| {},
        .if_expression => |i| {},
        .if_prefix => |i| {},
        .literal => |i| {},
        .match => |i| {
            var match_scope = ScopedSymbolTable.init_from_scope(.{ .name = i.name.type.identifier, .parent = ctx.scope });
        },
        .member => |i| {},
        .member_access => |i| {},
        .member_basic => |i| {},
        .nullish_expression => |i| {},
        .optional_dereference => |i| {},
        .optional_type => |i| {},
        .pointer_dereference => |i| {},
        .pointer_type => |i| {},
        .program => |i| for (i.declarations.items) |d| s.check_ast(file_id, d, .{ .is_global = true, .scope = ctx.scope }),
        .range_expression => |i| {},
        .return_expression => |i| {},
        .struct_ => |i| {
            var struct_scope = ScopedSymbolTable.init_from_scope(.{ .name = i.name.type.identifier, .parent = ctx.scope });
        },
        .struct_init => |i| {
            var struct_init_scope = ScopedSymbolTable.init_from_scope(.{ .name = i.name.type.identifier, .parent = ctx.scope });
        },
        .struct_init_member => |i| {},
        .try_ => |i| {},
        .unary => |i| {},
        .use => |i| {},
        .while_statement => |i| {},
        else => {},
    }
}

const Context = struct { type: ?TypeInfo = null, is_global: bool = false, scope: *ScopedSymbolTable };
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
    pub fn init_from_scope(opts: struct { parent: *ScopedSymbolTable, name: []const u8 }) ScopedSymbolTable {
        return .{
            .allocator = opts.parent.allocator,
            .symbols = std.StringHashMap(SymbolEntry).init(opts.parent.allocator),
            .scope_name = opts.name,
            .scope_level = opts.parent.scope_level + 1,
            .d = opts.parent.d,
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
    // kind: enum { variable, function, @"struct", @"enum", type },
    symbol_type: ?TypeInfo,
    type: ?*Node,
    val: ?*Node,
    mut: bool = false,
    public: bool = false,
    location: SourceLocation,
};
const DependencyGraph = struct {
    scope: *ScopedSymbolTable,
    name: []const u8,
    dependencies: []*SymbolEntry
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
const TypeInfo = union(Type) {
    void: null,
    int: struct { signed: bool, length: u16 },
    float: struct { signed: bool, length: u16 },
    undefined: void,
    nullable: struct { subtype: *TypeInfo },
    pointer: struct { subtype: *TypeInfo },
    type: void,
};
