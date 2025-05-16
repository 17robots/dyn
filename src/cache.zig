const std = @import("std");
pub fn Cache(comptime K: type, comptime V: type, items: usize) type {
    return struct {
        const CacheItem = struct { k: K, v: V, dirty: bool = false };
        const InvalidateFn = *fn (CacheItem) bool;
        const Self = @This();
        c: [items]CacheItem,
        i: InvalidateFn,
        fn init() Self {
            return Self{ .c = [1]CacheItem{.{ .k = undefined, .v = undefined, .dirty = false }} ** items };
        }
        fn get_index(s: *Self, k: K) ?usize {
            for (0..s.c.len) |i| {
                if (s.eq(K, s.c[i], k)) {
                    if (s.i(s.c[i])) s.c[i].dirty = true;
                    return if (!s.c[i].dirty) i else null;
                }
            }
            return null;
        }
        fn get(s: *Self, k: K) ?CacheItem {
            for (0..s.c.len) |i| {
                if (s.eq(K, s.c[i].k, k)) {
                    if (s.i(s.c[i])) s.c[i].dirty = true;
                    return if (!s.c[i].dirty) s.c[i] else null;
                }
            }
            return null;
        }
        fn cache(s: *Self, k: K, v: V) void {
            if (s.get_index(k)) |i| {
                if(s.eq(V, s.c[i], v)) return; // doesnt need to be cached
            }
        }
        fn eq(comptime T: type, v1: T, v2: T) bool {
            return std.mem.eql(T, [_]T{v1}, [_]T{v2});
        }
    };
}
