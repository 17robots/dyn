const Type = @import("types2.zig").Type;
name: []const u8,
symbol_type: enum {},
data_type: type, // change this
offset: i32 = -1, // this will be used later
mutable: bool,
