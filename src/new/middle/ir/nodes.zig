const std = @import("std");

pub const IRValue = struct {
    kind: Kind,
    type: Type,
    pub const Kind = union(enum) {
        constant: Constant,
        temporary: u32,
        parameter: u32,
        global: []const u8,
        undef,
        pub const Constant = union(enum) {
            int: i64,
            float: f64,
            bool: bool,
            null,
            string: []const u8,
            array: []IRValue,
            struct_: []StructField,
        };
    };
};
