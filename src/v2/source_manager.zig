const std = @import("std");
const Span = @import("token.zig").Span;

pub const FileId = u32;
pub const Position = struct { line: usize, column: usize };
pub const File = struct { path: []u8, text: ?[]u8, line_starts: []u32 };
pub const Self = @This();

allocator: std.mem.Allocator,
files: std.ArrayList(File) = .empty,

pub fn init(allocator: std.mem.Allocator) Self {
    return .{ .allocator = allocator };
}
pub fn add_file(self: *Self, path: []const u8, text: []const u8, keep_text: bool) !FileId {
    const path_copy = try self.allocator.dupe(u8, path);
    errdefer self.allocator.free(path_copy);

    const line_starts = try build_line_starts(self.allocator, text);
    errdefer self.allocator.free(line_starts);

    const text_copy: ?[]u8 = if (keep_text) try self.allocator.dupe(u8, text) else null;
    errdefer if (text_copy) |t| self.allocator.free(t);

    try self.files.append(self.allocator, .{ .path = path_copy, .text = text_copy, .line_starts = line_starts });
    return @intCast(self.files.items.len - 1);
}
pub fn add_file_from_disk(self: *Self, path: []const u8, keep_text: bool) !FileId {
    const data = try std.fs.cwd().readFileAlloc(self.allocator, path, std.math.maxInt(usize));
    defer if(!keep_text) self.allocator.free(data);
    return if (keep_text) try self.add_file_owned(path, data) else try self.add_file(path, data, keep_text);
}
pub fn add_file_owned(self: *Self, path: []const u8, owned_text: []u8) !FileId {
    const path_copy = try self.allocator.dupe(u8, path);
    errdefer self.allocator.free(path_copy);

    const line_starts = try build_line_starts(self.allocator, owned_text);
    errdefer self.allocator.free(line_starts);

    try self.files.append(self.allocator, .{ .path = path_copy, .text = owned_text, .line_starts = line_starts });
    return @intCast(self.files.items.len - 1);
}

fn build_line_starts(allocator: std.mem.Allocator, text: []const u8) ![]u32 {}
