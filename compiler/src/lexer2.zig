const std = @import("std");

pub const Tag = enum { num_literal, char_literal, string_literal, identifier, invalid, eof, plus, plus_equal, minus, minus_equal, asterisk, asterisk_equal, slash, slash_equal, ampersand, ampersand_equal, ampersand_ampersand, pipe, pipe_equal, pipe_pipe, keyword_con, keyword_pub, keyword_mut, keyword_if, keyword_loop, keyword_struct, keyword_enum };

pub const keywords = std.ComptimeStringMap(Tag, .{
    .{ "if", .keyword_if },
    .{ "con", .keyword_con },
    .{ "mut", .keyword_mut },
    .{ "pub", .keyword_pub },
});

pub const Loc = struct {
    start: usize,
    end: usize,
};
pub const Token = struct {
    tag: Tag,
    loc: Loc,
};

pub const Tokenizer = struct {
    buf: [:0]const u8,
    index: usize,
    state: State,

    pub const State = enum {
        string_literal,
        int,
        float,
        char_literal,
        identifier,
        start,
        period,
    };
    pub fn init(buf: [:0]const u8) Tokenizer {
        return .{
            .buf = buf,
            .index = undefined,
            .state = .start,
        };
    }

    pub fn next(self: *Tokenizer) Token {
        var res = Token{ .eof = undefined, .loc = .{ .start = self.index, .end = undefined } };
        self.state = .start;
        while (true) : (self.index += 1) {
            const c = self.buf[self.index];
            switch (c) {
                'a'...'z', 'A'...'Z', '_' => switch (self.state) {
                    .start => {
                        self.state = .identifier;
                    },
                    .identifier => {},
                    else => {
                        if (keywords.get(self.buf[res.loc.start..self.index])) |token| {
                            res.tag = token;
                        }
                        break;
                    },
                },
                '0'...'9' => switch (self.state) {
                    .start => {
                        self.state = .int;
                    },
                    .int,
                    .float,
                    .identifier,
                    => {},
                    else => {
                        self.state = .int;
                    },
                },
                '.' => switch (self.state) {
                    .start => {
                        self.state = .period;
                    },
                    .int => {
                        self.state = .float;
                    },
                    .float => {
                        break;
                    },
                    else => {
                        res.tag = .period;
                        break;
                    },
                },
                ' ', '\t', '\r' => {},
                else => {},
            }
        }
        res.loc.end = self.index;
        return res;
    }
};
