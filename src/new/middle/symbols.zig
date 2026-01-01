const std = @import("std");
const ast = @import("../frontend/ast.zig");

pub const SymbolId = u32;
pub const SymbolKind = enum { variable, constant, function, parameter, type_alias, struct_type, enum_type, error_type, module, namespace, label };
pub const Symbol = struct {
    id: SymbolId,
    name: []const u8,
    kind: SymbolKind,
    decl_node: ast.NodeId,
    type: ?Type,
    is_pub: bool,
    is_mut: bool,
    scope_id: u32,
    parent_symbol: ?SymbolId,
    type_params: ?[]TypeParam,
    data: union {
        variable: struct { init_val: ?ast.NodeId },
        function: struct { params: []ast.NodeId, return_type: ast.NodeId, body: ?ast.NodeId },
        type_alias: struct { target_type: ast.NodeId },
        struct_type: struct { fields: []StructField, methods: []SymbolId },
        enum_type: struct { variants: []EnumVariant, methods: []SymbolId },
        error_type: struct { variants: []ErrorVariant, methods: []SymbolId },
    },
    pub const TypeParam = struct { name: []const u8, constraints: ?[]Constraint };
    pub const Constraint = struct { trait: []const u8, args: ?[]ast.NodeId };
    pub const StructField = struct { name: []const u8, type: Type, default_val: ?ast.NodeId };
    pub const EnumVariant = struct { name: []const u8, tag_value: ?u64, payload: ?Type };
    pub const ErrorVariant = struct { name: []const u8, payload: ?Type };
};
pub const Scope = struct {
    id: u32,
    parent: ?*Scope,
    symbols: std.StringArrayHashMap(SymbolId),
    children: std.ArrayList(*Scope) = .empty,
    pub fn init(allocator: std.mem.Allocator, id: u32, parent: ?*Scope) Scope {
        return .{ .id = id, .parent = parent, .symbols = std.StringArrayHashMap(SymbolId).init(allocator) };
    }
    pub fn deinit(self: *Scope, allocator: std.mem.Allocator) void {
        self.symbols.deinit();
        for (self.children.items) |c| {
            c.deinit(allocator);
            allocator.destroy(c);
        }
        self.children.deinit(allocator);
    }
    pub fn lookup(self: Scope, name: []const u8) ?SymbolId {
        if (self.symbols.get(name)) |id| return id;
        if (self.parent) |p| return p.lookup(name);
        return null;
    }
    pub fn add_symbol(self: *Scope, name: []const u8, symbol_id: SymbolId) void {
        self.symbols.put(name, symbol_id) catch {};
    }
    pub fn create_child(self: *Scope, allocator: std.mem.Allocator, id: u32) *Scope {
        const child = allocator.create(Scope) catch {};
        child.* = Scope.init(allocator, id, self);
        self.children.append(allocator, child);
        return child;
    }
};
pub const SymbolTable = struct {
    allocator: std.mem.Allocator,
    symbols: std.MultiArrayList(Symbol),
    next_id: u32 = 1,
    global_scope: *Scope,
    current_scope: *Scope,
    pub fn init(allocator: std.mem.Allocator) SymbolTable {
        const global_scope = allocator.create(Scope) catch {};
        global_scope.* = Scope.init(allocator, 0, null);
        return .{ .allocator = allocator, .symbols = .empty, .next_id = 1, .global_scope = global_scope, .current_scope = global_scope };
    }
    pub fn deinit(self: *SymbolTable, allocator: std.mem.Allocator) void {
        self.symbols.deinit(allocator);
        self.global_scope.deinit(allocator);
        self.allocator.destroy(self.global_scope);
    }
    pub fn enter_scope(self: *SymbolTable) void {
        const new_scope = self.current_scope.create_child(self.allocator, @intCast(self.current_scope.children.items.len)) catch {};
        self.current_scope = new_scope;
    }
    pub fn exit_scope(self: *SymbolTable) void {
        if (self.current_scope.parent) |p| self.current_scope = p;
    }
    pub fn add_symbol(self: *SymbolTable, symbol: Symbol) void {
        const id = self.next_id;
        self.next_id += 1;
        var sym = symbol;
        sym.id = id;
        self.symbols.append(self.allocator, sym) catch {};
        self.current_scope.add_symbol(sym.name, id);
    }
    pub fn lookup(self: SymbolTable, name: []const u8) ?SymbolId {
        return self.current_scope.lookup(name);
    }
    pub fn get_symbol(self: SymbolTable, id: SymbolId) Scope {
        return self.symbols.get(id);
    }
    pub fn update_symbol(self: *SymbolTable, id: SymbolId, symbol: Symbol) void {
        self.symbols.set(id, symbol);
    }
};
pub const Type = struct {
    kind: TypeKind,
    pub const TypeKind = enum {
        void,
        bool,
        float,
        char,
        string,
        pointer,
        array,
        slice,
        optional,
        error_union,
        function,
        struct_,
        enum_,
        error_set,
        type_param,
        inferred,
        pub const Int = struct { signed: bool, bits: u16 };
        pub const Float = struct { bits: u16 };
        pub const Pointer = struct { elem_type: *Type, is_const: bool, is_volatile: bool, is_mutable: bool };
        pub const Array = struct { elem_type: *Type, size: ?u64 };
        pub const Function = struct { params: []*Type, return_type: *Type, calling_convention: CallingConvention };
        pub const Struct = struct { name: []const u8, fields: []*Symbol.StructField, methods: []SymbolId, is_packed: bool };
        pub const CallingConvention = enum { c, stdcall, fastcall, system };
    };
};
