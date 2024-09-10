const std = @import("std");

pub const Error = enum {
    InvalidCharacter,
    InvalidEscape,
    InvalidCharLength,
    ModuleDeclNotFound,
    pub fn err_string(
        e: Error,
    ) []const u8 {
        switch (e) {
            .InvalidCharacter => "Invalid Character",
            .InvalidEscape => "Invalid Escape",
            .InvalidCharLength => "Invalid Char Length",
            .ModuleDeclNotFound => "Module Declaration Not Found At Top Of File",
        }
    }
};

pub const ErrorEntry = struct {
    filename: []const u8,
    l: usize,
    c: usize,
    e: Error,
    pub fn init(filename: []const u8, l: usize, c: usize, e: Error) ErrorEntry {
        return ErrorEntry{ .filename = filename, .l = l, .c = c, .e = e };
    }
};

pub const FileErrors = struct {
    filename: []const u8,
    errs: std.ArrayList(struct { l: usize, c: usize, e: Error }),
    alloc: std.mem.Allocator,
};
