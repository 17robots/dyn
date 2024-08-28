const lexer = @import("lexer.zig");

pub const Declaration = struct {
    public: bool,
    metadata: anyopaque,
};

pub const Statement = struct {};

pub const Expression = struct {};

pub const Program = struct {
    module_name: []const u8,
    decls: []Declaration,
    eof: ?*lexer.TokenType,
};

// decls
pub const UseDecl = struct {};
pub const VariableDecl = struct {};
pub const TypeDecl = struct {};

// stmts
pub const BlockStmt = struct {};

pub const LabeledStmt = struct {};

pub const ExpressionStmt = struct {};

pub const AssignStmt = struct {};

pub const BranchStmt = struct {};

// exprs
