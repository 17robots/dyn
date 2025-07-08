const std = @import("std");
// Forward-declare Scope to break the import cycle with checker.zig
const Scope = @import("checker.zig").Scope;

pub const TypeKind = enum {
    Void,
    Type,
    Null,
    Undefined,
    Int,
    Float,
    Bool,
    Enum,
    Error,
    Struct,
    Function,
    Pointer,
    Optional,
    Array,
    ErrorUnion,
    ComptimeInt,
    ComptimeFloat,
    String,
    Module,
};

pub const Type = union(TypeKind) {
    Void: void,
    Type: void,
    Null: void,
    Undefined: void,
    Int: struct { is_signed: bool, width: u16 },
    Float: struct { width: u16 },
    Bool: void,
    Enum: *EnumLit,
    Error: *ErrorLit,
    Struct: *StructLit,
    Function: *FunctionLit,
    Pointer: *PointerLit,
    Optional: *OptionalLit,
    Array: *ArrayLit,
    ErrorUnion: *ErrorUnionLit,
    ComptimeInt: void,
    ComptimeFloat: void,
    String: void,
    Module: *ModuleLit,

    pub fn eql(a: Type, b: Type) bool {
        if (a.kind() != b.kind()) return false;
        return switch (a) {
            .Int => |a_int| {
                const b_int = b.Int;
                return a_int.is_signed == b_int.is_signed and a_int.width == b_int.width;
            },
            // Add comparisons for other types
            else => true,
        };
    }

    pub fn format(self: Type, comptime fmt: []const u8, options: std.fmt.FormatOptions, writer: anytype) !void {
        _ = options;
        _ = fmt;
        switch (self) {
            .Void => try writer.writeAll("void"),
            .Type => try writer.writeAll("type"),
            .Null => try writer.writeAll("null"),
            .Undefined => try writer.writeAll("undefined"),
            .Int => |i| try writer.print("i{d}", .{i.width}),
            .Float => |f| try writer.print("f{d}", .{f.width}),
            .Bool => try writer.writeAll("bool"),
            .Enum => |e| try writer.print("enum {s}", .{e.name orelse ""}),
            .Error => |e| try writer.print("error {s}", .{e.name orelse ""}),
            .Struct => |s| try writer.print("struct {s}", .{s.name orelse ""}),
            .Function => try writer.writeAll("fn"),
            .Pointer => |p| try writer.print("* {any}", .{p.child}),
            .Optional => |o| try writer.print("?{any}", .{o.child}),
            .Array => |a| try writer.print("[]{any}", .{a.child}),
            .ErrorUnion => |eu| try writer.print("{any}!{any}", .{eu.success_type, eu.error_type}),
            .ComptimeInt => try writer.writeAll("comptime_int"),
            .ComptimeFloat => try writer.writeAll("comptime_float"),
            .String => try writer.writeAll("string"),
            .Module => |m| try writer.print("module {s}", .{m.name}),
        }
    }
};

pub const StructLit = struct {
    name: ?[]const u8,
    scope: *Scope,
};

pub const EnumLit = struct {
    name: ?[]const u8,
    scope: *Scope,
};

pub const ErrorLit = struct {
    name: ?[]const u8,
    scope: *Scope,
};

pub const FunctionLit = struct {
    params: []*Type,
    return_type: *Type,
};

pub const PointerLit = struct {
    child: *Type,
};

pub const OptionalLit = struct {
    child: *Type,
};

pub const ArrayLit = struct {
    child: *Type,
};

pub const ErrorUnionLit = struct {
    success_type: *Type,
    error_type: *Type,
};

pub const ModuleLit = struct {
    name: []const u8,
    scope: *Scope,
};
