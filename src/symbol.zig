const std = @import("std");
const ast = @import("ast.zig");
const Span = @import("token.zig").Span;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;

pub const SymbolKind = enum {
    @"var",
    func,
    type,
    enum_member,
    error_member,
    module,
    label
};
pub const Mutability = enum { immutable, mutable };
pub const Symbol = struct {
    name: []const u8,
    kind: SymbolKind,
    span: Span,
    mutability: Mutability = .immutable,
    type_id: ?u32 = null
};
pub const Scope = struct {
    parent: ?*Scope,
    type: union(enum) {
        block: ?[]const u8,
        function: struct { name: []const u8, fn_result: ?u32 },
        global: void,
    },
};
pub const ScopeStack = struct {
    allocator: std.mem.Allocator,
    stack: std.ArrayList(*Scope),
    pub fn init(allocator: std.mem.Allocator) ScopeStack {
        return .{ .allocator = allocator, .stack = .empty};
    }
    pub fn deinit(s: *ScopeStack) void {
        for (s.stack.items) |item| item.deinit(s.allocator);
        s.stack.deinit(s.allocator);
    }
    pub fn push(s: *ScopeStack, kind: Scope.kind) !*Scope {
        const scope = try s.allocator.create(Scope);
        scope.* = Scope.init();
        s.kind = kind;
        s.parent = if(s.stack.items.len == 0) null else s.stack.items[s.items.len - 1];
        try s.stack.append(s.allocator, s);
        return s;
    }
    pub fn pop(s: *ScopeStack) void {
        const item = s.stack.pop();
        item.deinit(s.allocator);
        s.allocator.destroy(item);
    }
    pub fn current(s: *ScopeStack) *Scope {
        return s.stack.items[s.stack.items.len - 1];
    }
    pub fn declare(s: *ScopeStack, sym: Symbol, diag: *DiagnosticEmitter, file_id: u32) void {
        var cur = s.current();
        if (cur.table.get(sym.name) != null) {
            diag.emit(file_id, sym.span, .err, "Duplicate symbol: '{s}'", .{sym.name});
            return;
        }
        cur.table.putAssumeCapacityNoClobber(sym.name, sym);
    }
    pub fn lookup(s: *ScopeStack, name: []const u8) ?Symbol {
        var cur = if(s.stack.items.len == 0) null else s.current();
        while(cur) |scope| {
            if(scope.table.get(name)) |sym| return sym;
            cur = scope.parent;
        }
        return null;
    }
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
    unknown
};
pub const Type = struct {
    tag: TypeTag,
    payload: union(TypeTag) {
        pointer: u32,
        optional: u32,
        error_union: struct { val: u32, errs: []const []const u8 },
        array: struct { elem: u32, len: usize },
        slice: u32,
        function: struct { params: []u32, result: u32, is_inline: bool },
        struct_: void,
        enum_: void,
        error_: void,
        void: void,
        boolean: void,
        char: void,
        int: void,
        float: void,
        string: void,
        undefined: void,
        null: void,
        type: void,
        unknown: void,
    },
};
pub const TypeTable = struct {
    allocator: std.mem.Allocator,
    store: std.ArrayList(Type),
    pub fn init(a: std.mem.Allocator) TypeTable {
        return .{ .allocator = a, .store = .empty };
    }
    pub fn deinit(s: *TypeTable) void {
        s.store.deinit(s.allocator);
    }
    pub fn add(s: *TypeTable, t: Type) !u32 {
        try s.store.append(s.allocator, t);
        return @intCast(s.store.items.len - 1);
    }
    pub fn get(s: *TypeTable, id: u32) *Type {
        return &s.store.items[id];
    }
};
pub const SymbolTable = std.ArrayList(Symbol);
