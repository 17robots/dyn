const std = @import("std");
pub fn Cache(comptime T: type, items: usize) type {
    return struct {
        const CacheItem = struct { v: T, dirty: bool = false };
        const InvalidateFn = *fn (CacheMap) bool;
        const Self = @This();
        c: [items]CacheItem,
        fn init() Self {
            return Self{ .c = [1]CacheItem{.{ .v = undefined, .dirty = false }} ** items };
        }
        fn is_cached(s: Self, v: T) bool {
            for(s.c) |i| { }
        }
    };
}
pub fn Cache(comptime T: type, comptime U: type) type {
    const CacheMap = std.AutoHashMap(T, struct { v: U, dirty: bool = false });
    const InvalidateFn = *fn (CacheMap) bool;
    return struct {
        const Self = @This();
        c: CacheMap,
        invalidateFn: InvalidateFn,
        fn init(alloc: std.mem.Allocator) Self {
            return Self{ .c = CacheMap.init(alloc) };
        }
        fn is_cached(s: *Self, key: T) bool {
            return if (s.c.get(key)) |*val| blk: {
                if (s.invalidateFn(val.*)) val.dirty = true;
                break :blk val.dirty;
            } else false;
        }
        fn mark_dirty(s: *Self) void {
            while (s.c.valueIterator().next()) |*v| {
                if (s.invalidateFn(v.*)) v.dirty = true;
            }
        }
        fn cache(s: *Self, key: T, val: U) !void {
            if (s.is_cached(key)) return error.AlreadyCached;
            if (s.c.get(key)) |*v| {
                v.v = v;
                v.dirty = false;
                return;
            }
            try s.c.put(key, val);
        }
    };
}
