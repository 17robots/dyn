const std = @import("std");
const ast = @import("ast.zig");
const Span = @import("token.zig").Span;
const SourceLocation = @import("source.zig").SourceLocation;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;

pub const SymbolKind = enum {
    @"var",
    func,
    type,
    enum_member,
    error_member,
    label,
    unknown,
    pub fn from_node(n: ast.Node) SymbolKind {
        return switch (n) {};
    }
};
pub const Mutability = enum { immutable, mutable };
pub const Symbol = struct {
    name: []const u8,
    kind: SymbolKind,
    mutability: Mutability = .immutable,
    type_id: ?u32 = null,
    public: bool = false,
    location: SourceLocation,
};
pub const Scope = struct {
    type: union(enum) {
        block: ?[]const u8,
        function: struct { name: []const u8, fn_result: ?u32 },
        global: void,
    },
    symbols: std.ArrayList(Symbol),
    types: std.ArrayList(Type),
    parent_scope: ?u32,
};
pub const TypeTag = enum {
    void,
    boolean,
    char,
    int,
    float,
    string,
    undefined,
    null,
    pointer,
    optional,
    error_union,
    array,
    slice,
    function,
    struct_,
    enum_,
    error_,
    type,
    unknown,
};
pub const Type = struct {
    tag: TypeTag,
    payload: union(TypeTag) {
        void: void,
        boolean: void,
        char: void,
        int: void,
        float: void,
        string: void,
        undefined: void,
        null: void,
        pointer: u32,
        optional: u32,
        error_union: struct { val: u32, errs: []const []const u8 },
        array: struct { elem: u32, len: usize },
        slice: u32,
        function: struct { params: []u32, result: u32, is_inline: bool },
        struct_: void,
        enum_: void,
        error_: void,
        type: void,
        unknown: void,
    },
};
pub const ScopeStack = struct {
    scopes: std.ArrayList(Scope),
    pub const empty = ScopeStack{ .scopes = .empty };
    pub fn push(s: *ScopeStack, alloc: std.mem.Allocator, val: Scope) void {
        s.scopes.append(alloc, val) catch {};
    }
    pub fn pop(s: *ScopeStack) ?Scope {
        return s.scopes.pop();
    }
    pub fn current(s: *ScopeStack) ?Scope {
        return if (s.scopes.items.len == 0 or s.current_scope > s.scopes.items.len) null else s.scopes.items[s.current_scope];
    }
    pub fn pub_symbols(s: *ScopeStack, allocator: std.mem.Allocator) []*Symbol {
        var symbols: std.ArrayList(*Symbol) = .empty;
        for (s.scopes.items) |scopes| {
            for (scopes.symbols.items) |*symbol| {
                if (symbol.public) symbols.append(allocator, symbol);
            }
        }
        return symbols.toOwnedSlice(allocator);
    }
};
