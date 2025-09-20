pub fn Tree(comptime T: type) type {
    return struct {
        const self = @This();
        val: ?T,
        left: ?*self,
        right: ?*self,
        pub fn init(val: ?T, left: ?*self, right: ?*self) self {
            return self{ .val = val, .left = left, .right = right };
        }
    };
}

