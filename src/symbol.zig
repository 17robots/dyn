const std = @import("std");
const ast = @import("ast.zig");
const Span = @import("token.zig").Span;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;

pub const SymbolKind = enum { @"var", func, type, enum_member, error_member, label };
pub const Mutability = enum { immutable, mutable };
pub const Symbol = struct {
    name: []const u8,
    kind: SymbolKind,
    span: Span,
    mutability: Mutability = .immutable,
    type_id: ?u32 = null,
};
pub const Scope = struct {
    type: union(enum) {
        block: ?[]const u8,
        function: struct { name: []const u8, fn_result: ?u32 },
        global: void,
    },
    symbols: std.ArrayList(Symbol),
    types: std.ArrayList(Type),
};
pub const TypeTag = enum { void, boolean, char, int, float, string, undefined, null, pointer, optional, error_union, array, slice, function, struct_, enum_, error_, type, unknown };
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
pub const ScopeStack = std.ArrayList(Scope);
