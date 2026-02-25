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
    defer if (!keep_text) self.allocator.free(data);
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
pub fn ensure_text_loaded(self: *Self, file_id: FileId) !void {
    const f = &self.files.items[file_id];
    if (f.text) |_| return;
    f.text = try std.fs.cwd().readFileAlloc(self.allocator, f.path, std.math.maxInt(usize));
}
pub fn position_of(self: *Self, file_id: FileId, offset: usize) Position {
    const starts = self.files.items[file_id].line_starts;
    const idx = line_index_for_offset(starts, @as(u32, @intCast(offset)));
    const line_start: usize = starts[idx];
    return .{ .line = idx + 1, .column = (offset - line_start) + 1 };
}
pub fn line_slice(self: *Self, file_id: FileId, line: usize) ![]const u8 {
    const f = self.files.items[file_id];
    const text = f.text orelse return error.SourceNotLoaded;
    if(line == 0 or line > f.line_starts.len) return error.InvalidLine;
    const start: usize = f.line_starts[line - 1];
    const end: usize = if(line < f.line_starts.len) f.line_starts[line] - 1 else text.len;
    return text[start..end];
}
pub fn span_slice(self: *Self, file_id: FileId, span: Span) ![]const u8 {
    const f = self.files.items[file_id];
    const text = f.text orelse return error.SourceNotLoaded;
    if(span.start > span.end or span.end >= text.len) return error.InvalidSpan;
    return text[span.start..span.end + 1];
}
fn line_index_for_offset(starts: []const u32, offset: u32) usize {
    var lo: usize = 0;
    var hi: usize = starts.len;
    while (lo < hi) {
        const mid = lo + (hi - lo) / 2;
        if (starts[mid] <= offset) lo = mid + 1 else hi = mid;
    }
    return if (lo == 0) 0 else lo - 1;
}
fn build_line_starts(allocator: std.mem.Allocator, text: []const u8) ![]u32 {
    var starts: std.ArrayList(u32) = .empty;
    errdefer starts.deinit(allocator);

    try starts.append(allocator, 0);
    for (text, 0..) |b, i| if (b == '\n' and i + 1 < text.len) try starts.append(allocator, @intCast(i + 1));
    return try starts.toOwnedSlice(allocator);
}
