const std = @import("std");
const File = @import("file.zig");
const Module = @import("module.zig");

const Checker = @This();
const Import = union(enum) {
    file: File,
    module: Module
};

imports: std.ArrayList(Import),
files: std.ArrayList(File),

