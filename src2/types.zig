const std = @import("std");

pub const TypeId = enum(u32) { _ };
pub const Signedness = enum { signed, unsigned };
pub const FloatWidth = enum { f32, f64 };
pub const Param = struct {
    ty: TypeId,
    mutating: enum { none, pointer, slice } = .none,
    is_comptime: bool = false,
};
pub const Field = struct { name: []const u8, ty: TypeId };
pub const EnumVariant = struct { name: []const u8, payload: ?TypeId = null };
pub const Type = union(enum) {
    err,
    type,
    void,
    any,
    comptime_int,
    comptime_float,
    int: struct { signedness: Signedness, width: u16 },
    isize,
    usize,
    float: FloatWidth,
    pointer: TypeId,
    slice: TypeId,
    array: struct { len: u64, elem: TypeId },
    range: TypeId,
    function: struct { params: []const Param, ret: TypeId },
    struct_type: []const Field,
    enum_type: []const EnumVariant,
    recursive_ref: TypeId,
    optional: TypeId,
    error_set: []const TypeId,
    error_union: struct { ok: TypeId, err: TypeId },
};
pub const Builtins = struct {
    err: TypeId,
    type: TypeId,
    void: TypeId,
    any: TypeId,
    comptime_int: TypeId,
    comptime_float: TypeId,
    u1: TypeId,
    i32: TypeId,
    u8: TypeId,
    f32: TypeId,
    f64: TypeId,
};
pub const TypeTable = struct {
    allocator: std.mem.Allocator,
    items: std.ArrayList(Type),
    builtins: Builtins,

    pub fn init(allocator: std.mem.Allocator) !TypeTable {
        var self = TypeTable{ .allocator = allocator, .items = .empty, .builtins = undefined };
        self.builtins.err = try self.intern(.err);
        self.builtins.type = try self.intern(.type);
        self.builtins.void = try self.intern(.void);
        self.builtins.any = try self.intern(.any);
        self.builtins.comptime_int = try self.intern(.comptime_int);
        self.builtins.comptime_float = try self.intern(.comptime_float);
        self.builtins.u1 = try self.int(.unsigned, 1);
        self.builtins.i32 = try self.int(.signed, 32);
        self.builtins.u8 = try self.int(.unsigned, 8);
        self.builtins.f32 = try self.intern(.{ .float = .f32 });
        self.builtins.f64 = try self.intern(.{ .float = .f64 });
        return self;
    }

    pub fn deinit(self: *TypeTable) void {
        for (self.items.items) |t| switch (t) {
            .function => self.allocator.free(t.function.params),
            .struct_type => |fs| self.allocator.free(fs),
            .enum_type => |vs| self.allocator.free(vs),
            else => {},
        };
        self.items.deinit(self.allocator);
    }

    pub fn get(self: *const TypeTable, id: TypeId) Type {
        return self.items.items[@intFromEnum(id)];
    }

    pub fn int(self: *TypeTable, signedness: Signedness, width: u16) !TypeId {
        return self.intern(.{ .int = .{ .signedness = signedness, .width = width } });
    }

    pub fn pointer(self: *TypeTable, elem: TypeId) !TypeId {
        return self.intern(.{ .pointer = elem });
    }
    pub fn slice(self: *TypeTable, elem: TypeId) !TypeId {
        return self.intern(.{ .slice = elem });
    }
    pub fn array(self: *TypeTable, len: u64, elem: TypeId) !TypeId {
        return self.intern(.{ .array = .{ .len = len, .elem = elem } });
    }
    pub fn range(self: *TypeTable, elem: TypeId) !TypeId {
        return self.intern(.{ .range = elem });
    }

    pub fn function(self: *TypeTable, params: []const Param, ret: TypeId) !TypeId {
        for (self.items.items, 0..) |old, i| if (old == .function and old.function.ret == ret and paramsEqual(old.function.params, params)) return @enumFromInt(i);
        const owned = try self.allocator.dupe(Param, params);
        errdefer self.allocator.free(owned);
        const id: TypeId = @enumFromInt(self.items.items.len);
        try self.items.append(self.allocator, .{ .function = .{ .params = owned, .ret = ret } });
        return id;
    }

    pub fn recursiveRef(self: *TypeTable, target: TypeId) !TypeId {
        return self.intern(.{ .recursive_ref = target });
    }
    pub fn optional(self: *TypeTable, child: TypeId) !TypeId {
        return self.intern(.{ .optional = child });
    }
    pub fn errorSet(self: *TypeTable, members: []const TypeId) !TypeId {
        return self.intern(.{ .error_set = try self.allocator.dupe(TypeId, members) });
    }
    pub fn errorUnion(self: *TypeTable, ok: TypeId, err: TypeId) !TypeId {
        return self.intern(.{ .error_union = .{ .ok = ok, .err = err } });
    }

    pub fn structType(self: *TypeTable, fields: []const Field) !TypeId {
        for (self.items.items, 0..) |old, i| if (old == .struct_type and fieldsEqual(old.struct_type, fields)) return @enumFromInt(i);
        const owned = try self.allocator.dupe(Field, fields);
        errdefer self.allocator.free(owned);
        const id: TypeId = @enumFromInt(self.items.items.len);
        try self.items.append(self.allocator, .{ .struct_type = owned });
        return id;
    }

    pub fn enumType(self: *TypeTable, variants: []const EnumVariant) !TypeId {
        for (self.items.items, 0..) |old, i| if (old == .enum_type and variantsEqual(old.enum_type, variants)) return @enumFromInt(i);
        const owned = try self.allocator.dupe(EnumVariant, variants);
        errdefer self.allocator.free(owned);
        const id: TypeId = @enumFromInt(self.items.items.len);
        try self.items.append(self.allocator, .{ .enum_type = owned });
        return id;
    }

    pub fn intern(self: *TypeTable, ty: Type) !TypeId {
        for (self.items.items, 0..) |old, i| if (typeEqual(old, ty)) return @enumFromInt(i);
        const id: TypeId = @enumFromInt(self.items.items.len);
        try self.items.append(self.allocator, ty);
        return id;
    }
};
fn fieldsEqual(a: []const Field, b: []const Field) bool {
    if (a.len != b.len) return false;
    for (a, b) |x, y| if (!std.mem.eql(u8, x.name, y.name) or x.ty != y.ty) return false;
    return true;
}
fn variantsEqual(a: []const EnumVariant, b: []const EnumVariant) bool {
    if (a.len != b.len) return false;
    for (a, b) |x, y| if (!std.mem.eql(u8, x.name, y.name) or x.payload != y.payload) return false;
    return true;
}
fn paramsEqual(a: []const Param, b: []const Param) bool {
    if (a.len != b.len) return false;
    for (a, b) |x, y| if (x.ty != y.ty or x.mutating != y.mutating or x.is_comptime != y.is_comptime) return false;
    return true;
}
pub fn typeEqual(a: Type, b: Type) bool {
    if (@as(std.meta.Tag(Type), a) != @as(std.meta.Tag(Type), b)) return false;
    return switch (a) {
        .err, .type, .void, .any, .comptime_int, .comptime_float, .isize, .usize => true,
        .int => |x| x.signedness == b.int.signedness and x.width == b.int.width,
        .float => |x| x == b.float,
        .pointer => |x| x == b.pointer,
        .slice => |x| x == b.slice,
        .array => |x| x.len == b.array.len and x.elem == b.array.elem,
        .range => |x| x == b.range,
        .function => |x| x.ret == b.function.ret and paramsEqual(x.params, b.function.params),
        .struct_type => |x| fieldsEqual(x, b.struct_type),
        .enum_type => |x| variantsEqual(x, b.enum_type),
        .recursive_ref => |x| x == b.recursive_ref,
        .optional => |x| x == b.optional,
        .error_set => |xs| blk: {
            if (xs.len != b.error_set.len) break :blk false;
            for (xs, b.error_set) |x, y| if (x != y) break :blk false;
            break :blk true;
        },
        .error_union => |x| x.ok == b.error_union.ok and x.err == b.error_union.err,
    };
}
pub fn canWiden(table: *const TypeTable, from: TypeId, to: TypeId) bool {
    const a = table.get(from);
    const b = table.get(to);
    if (from == to) return true;
    if (a != .int or b != .int) return false;
    const aw = a.int.width;
    const bw = b.int.width;
    return switch (a.int.signedness) {
        .unsigned => switch (b.int.signedness) {
            .unsigned => bw >= aw,
            .signed => bw >= aw + 1,
        },
        .signed => switch (b.int.signedness) {
            .signed => bw >= aw,
            .unsigned => false,
        },
    };
}

test "type table interns arbitrary integer widths" {
    var tt = try TypeTable.init(std.testing.allocator);
    defer tt.deinit();
    const a = try tt.int(.unsigned, 17);
    const b = try tt.int(.unsigned, 17);
    const c = try tt.int(.signed, 17);
    try std.testing.expectEqual(a, b);
    try std.testing.expect(a != c);
}
test "integer widening follows bit-width rules" {
    var tt = try TypeTable.init(std.testing.allocator);
    defer tt.deinit();
    const ty_u3 = try tt.int(.unsigned, 3);
    const ty_u17 = try tt.int(.unsigned, 17);
    const ty_i4 = try tt.int(.signed, 4);
    const ty_i3 = try tt.int(.signed, 3);
    try std.testing.expect(canWiden(&tt, ty_u3, ty_u17));
    try std.testing.expect(canWiden(&tt, ty_u3, ty_i4));
    try std.testing.expect(!canWiden(&tt, ty_u3, ty_i3));
    try std.testing.expect(!canWiden(&tt, ty_i3, ty_u17));
}
