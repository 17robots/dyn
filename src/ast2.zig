const std = @import("std");
pub const LiteralType = enum {
    int,
    float,
    string,
};

pub const Node = union(enum) {
    Program: struct { declarations: []*const Node, pub_declarations: []*const Node },
    ModuleDeclaration: struct { name: *const Node },
    UseDeclaration: struct { import: *const Node, alias: ?*const Node },
    UseBlock: struct { uses: []*const Node },
    Literal: struct { lit_type: LiteralType, value: []const u8 },
    Identifier: struct { value: []const u8 },
    Declaration: void,

    pub fn deinit(s: *Node, alloc: std.mem.Allocator) void {
        switch (s.*) {
            .Program => |p| {
                for (p.pub_declarations) |pd| {
                    pd.*.deinit(alloc);
                }
                for (p.declarations) |pd| {
                    pd.*.deinit(alloc);
                }
            },
            .ModuleDeclaration => |m| {
                m.name.deinit(alloc);
            },
            .UseDeclaration => |u| {
                u.import.deinit(alloc);
                if (u.alias) |a| {
                    a.deinit(alloc);
                }
            },
            .UseBlock => |u| {
                for (u.uses) |uses| {
                    uses.deinit(alloc);
                }
            },
            else => {},
        }
        alloc.destroy(s);
    }
};
