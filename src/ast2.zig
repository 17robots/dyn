pub const LiteralType = enum {
    int,
    float,
    string,
};

pub const Node = union(enum) {
    Program: struct { declarations: []*const Node, pub_declarations: []*const Node },
    ModuleDeclaration: struct { name: []const u8 },
    UseDeclaration: struct { import: *const Node, alias: *const Node },
    UseBlock: struct { uses: []*const Node },
    Literal: struct { lit_type: LiteralType, value: []const u8 },
    Identifier: struct { value: []const u8 },
    Declaration: void,
};
