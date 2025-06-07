const std = @import("std");
const Diagnostic = @import("diagnostic.zig");
const Node = @import("ast.zig").Node;

path: []const u8,
content: []const u8,
diagnostics: std.ArrayList(Diagnostic),
root: ?Node = null,
