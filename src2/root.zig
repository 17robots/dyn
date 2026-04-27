pub const source = @import("source.zig");
pub const token = @import("token.zig");
pub const lexer = @import("lexer.zig");
pub const ast = @import("ast.zig");
pub const diag = @import("diag.zig");
pub const parser = @import("parser.zig");
pub const pattern = @import("pattern.zig");
pub const pretty = @import("pretty.zig");
pub const module_loader = @import("module_loader.zig");
pub const resolver = @import("resolver.zig");
pub const types = @import("types.zig");
pub const checker = @import("checker.zig");
pub const comptime_eval = @import("comptime.zig");
pub const hir = @import("hir.zig");
pub const codegen = @import("codegen.zig");

const std = @import("std");
test {
    std.testing.refAllDecls(@This());
}
