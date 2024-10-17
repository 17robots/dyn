pub const LiteralType = enum {
    int,
    float,
    string,
};

pub const Node = union(enum) { Program: struct {
    declarations: []*Node,
    pub_declarations: []*Node,
}, ModuleDeclaration: struct {
    name: []const u8,
} };
