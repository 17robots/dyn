const std = @import("std");
const ast = @import("ast.zig");
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;

pub const Symbol = struct {
    name: []const u8,
    type: Type,
    scope: *Scope,
    value_node: ?*ast.Node,
};
pub const SymbolTable = std.ArrayList(Symbol);
pub const ScopeStack = std.ArrayList(Scope);
pub const Scope = struct {
    parent: ?*Scope,
    type: union(enum) {
        block: ?[]const u8,
        function: []const u8,
        global: void,
    },
};

pub const Type = union(enum) {
    const ContainerLayout = enum {
        auto,
        @"extern",
        @"packed",
    };
    const Error = struct { name: [:0]const u8 };
    const Field = struct {
        name: [:0]const u8,
        type: type,
        default_val_ptr: ?*const anyopaque,
        _comptime: bool,
        alignment: comptime_int,
    };
    const Declaration = struct { name: [:0]const u8 };
    array: struct {
        const this = @This();
        len: comptime_int,
        child: type,
        _sentinel: ?*const anyopaque,
        pub inline fn sentinel(comptime ptr: @This()) ?this.child {
            const sp: *const ptr.child = @ptrCast(@alignCast(ptr._sentinel orelse return null));
            return sp.*;
        }
    },
    comptime_float: void,
    comptime_int: void,
    @"enum": struct { fields: []const Field, decls: []const Declaration },
    enum_literal: void,
    @"error": struct { fields: []const Field, decls: []const Declaration },
    error_set: ?[]const Error,
    error_union: struct { payload: type, error_set: type },
    float: struct { bits: u16 },
    @"fn": struct {
        // calling_convention: type,
        _generic: bool,
        return_type: ?type,
        params: []const struct { _generic: bool, _noalias: bool, type: ?type },
    },
    int: struct { signed: bool, bits: u16 },
    null: void,
    optional: struct { child: type },
    pointer: struct {
        const this = @This();
        _allowzero: bool,
        _const: bool,
        _volatile: bool,
        alignment: comptime_int,
        address_space: enum {},
        child: type,
        size: enum { one, many, slice, c },
        _sentinel: ?*const anyopaque,
        pub inline fn sentinel(comptime ptr: @This()) ?this.child {
            const sp: *const ptr.child = @ptrCast(@alignCast(ptr._sentinel orelse return null));
            return sp.*;
        }
    },
    @"struct": struct {
        layout: ContainerLayout,
        backing_int: ?type = null,
        fields: []const Field,
        decls: []const Declaration,
        _tuple: bool,
    },
    type: void,
    undefined: void,
    void: void,
};
