const std = @import("std");

pub const Error = error{
    // lexer errors
    InvalidCharacter,
    InvalidEscape,
    InvalidCharLength,
    ModuleDeclNotFound,
    // parser errors
    ParserError,
};
