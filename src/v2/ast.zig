const std = @import("std");
const Span = @import("token.zig").Span;

pub const Id = u32;
pub const Node = struct {
    tag: NodeTag,
    data: Id,
    main_token: Id,
    const NodeTag = enum {};
};

const Self = @This();

allocator: std.mem.Allocator,
nodes: std.MultiArrayList(Node) = .empty,
extras: std.ArrayList(Id) = .empty,

pub fn init(allocator: std.mem.Allocator) Self {
    return .{ .allocator = allocator };
}

