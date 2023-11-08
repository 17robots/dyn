const std = @import("std");

pub const File = struct {
    name: []const u8,
    relevant_bytes: []const u8,
};

pub const Tag = enum {
    // general / literals
    // symbols
    // keywords
};

pub const Loc = struct {
    file: *File,
    start: usize,
    end: usize,
};

pub const Token = struct {
    loc: Loc,
    tag: Tag,
};

pub const Tokenizer = struct {
    file: *File,
    pub const ReadStates = enum {
        start,
        identifier,
        literal_number,
        literal_string,
        literal_char,
    };
};
