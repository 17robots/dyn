const std = @import("std");
const Span = @import("token.zig").Span;

pub const FileId = u32;
pub const Position = struct {
    line: usize,
    column: usize,
};
pub const File = struct {
    path: []u8,
    text: ?[]u8,
    line_starts: []u32,
};
pub const Self = @This();

allocator: std.mem.Allocator,
files: std.ArrayListUnmanaged(File) = .empty,

pub fn init(allocator: std.mem.Allocator) Self {
    return .{ .allocator = allocator };
}
pub fn deinit(self: *Self) void {
    for (self.files.items) |entry| {
        self.allocator.free(entry.path);
        if (entry.text) |text| self.allocator.free(text);
        self.allocator.free(entry.line_starts);
    }
    self.files.deinit(self.allocator);
}
pub fn addFile(self: *Self, path: []const u8, text: []const u8, keep_text: bool) !FileId {
    const path_copy = try self.allocator.dupe(u8, path);
    errdefer self.allocator.free(path_copy);

    const line_starts = try buildLineStarts(self.allocator, text);
    errdefer self.allocator.free(line_starts);

    const text_copy: ?[]u8 = if (keep_text) try self.allocator.dupe(u8, text) else null;
    errdefer if (text_copy) |t| self.allocator.free(t);

    try self.files.append(self.allocator, .{
        .path = path_copy,
        .text = text_copy,
        .line_starts = line_starts,
    });
    return @intCast(self.files.items.len - 1);
}
pub fn addFileFromDisk(self: *Self, path: []const u8, keep_text: bool) !FileId {
    const data = try std.fs.cwd().readFileAlloc(self.allocator, path, std.math.maxInt(usize));
    defer if (!keep_text) self.allocator.free(data);
    return if (keep_text)
        self.addFileOwned(path, data)
    else
        self.addFile(path, data, false);
}
pub fn addFileOwned(self: *Self, path: []const u8, owned_text: []u8) !FileId {
    const path_copy = try self.allocator.dupe(u8, path);
    errdefer self.allocator.free(path_copy);

    const line_starts = try buildLineStarts(self.allocator, owned_text);
    errdefer self.allocator.free(line_starts);

    try self.files.append(self.allocator, .{
        .path = path_copy,
        .text = owned_text,
        .line_starts = line_starts,
    });
    return @intCast(self.files.items.len - 1);
}
pub fn filePath(self: *const Self, file_id: FileId) []const u8 {
    return self.file(file_id).path;
}
pub fn fileText(self: *const Self, file_id: FileId) ?[]const u8 {
    return self.file(file_id).text;
}
pub fn evictText(self: *Self, file_id: FileId) void {
    const f = self.fileMut(file_id);
    if (f.text) |text| {
        self.allocator.free(text);
        f.text = null;
    }
}
pub fn ensureTextLoaded(self: *Self, file_id: FileId) !void {
    const f = self.fileMut(file_id);
    if (f.text != null) return;
    f.text = try std.fs.cwd().readFileAlloc(self.allocator, f.path, std.math.maxInt(usize));
}
pub fn positionOf(self: *const Self, file_id: FileId, offset: usize) Position {
    const starts = self.file(file_id).line_starts;
    const idx = lineIndexForOffset(starts, @as(u32, @intCast(offset)));
    const line_start: usize = starts[idx];
    return .{
        .line = idx + 1,
        .column = (offset - line_start) + 1,
    };
}
pub fn positionOfSpanStart(self: *const Self, file_id: FileId, span: Span) Position {
    return self.positionOf(file_id, span.start);
}
pub fn lineSlice(self: *const Self, file_id: FileId, line: usize) ![]const u8 {
    const f = self.file(file_id);
    const text = f.text orelse return error.SourceNotLoaded;
    if (line == 0 or line > f.line_starts.len) return error.InvalidLine;

    const start: usize = f.line_starts[line - 1];
    const end: usize = if (line < f.line_starts.len)
        f.line_starts[line] - 1
    else
        text.len;

    return text[start..end];
}
pub fn spanSlice(self: *const Self, file_id: FileId, span: Span) ![]const u8 {
    const f = self.file(file_id);
    const text = f.text orelse return error.SourceNotLoaded;
    if (span.start > span.end or span.end >= text.len) return error.InvalidSpan;
    return text[span.start .. span.end + 1];
}
fn file(self: *const Self, file_id: FileId) File {
    return self.files.items[file_id];
}
fn fileMut(self: *Self, file_id: FileId) *File {
    return &self.files.items[file_id];
}
fn lineIndexForOffset(starts: []const u32, offset: u32) usize {
    var lo: usize = 0;
    var hi: usize = starts.len;
    while (lo < hi) {
        const mid = lo + (hi - lo) / 2;
        if (starts[mid] <= offset) {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }
    return if (lo == 0) 0 else lo - 1;
}
fn buildLineStarts(allocator: std.mem.Allocator, text: []const u8) ![]u32 {
    var starts: std.ArrayListUnmanaged(u32) = .empty;
    errdefer starts.deinit(allocator);

    try starts.append(allocator, 0);
    for (text, 0..) |b, i| {
        if (b == '\n' and i + 1 < text.len) try starts.append(allocator, @intCast(i + 1));
    }
    return try starts.toOwnedSlice(allocator);
}

test "source manager positions and lazy text" {
    const alloc = std.testing.allocator;
    var sm = Self.init(alloc);
    defer sm.deinit();

    const id = try sm.addFile("mem://test", "one\ntwo\nthree", false);
    try std.testing.expectEqualStrings("mem://test", sm.filePath(id));

    const p1 = sm.positionOf(id, 0);
    try std.testing.expectEqual(@as(usize, 1), p1.line);
    try std.testing.expectEqual(@as(usize, 1), p1.column);

    const p2 = sm.positionOf(id, 5);
    try std.testing.expectEqual(@as(usize, 2), p2.line);
    try std.testing.expectEqual(@as(usize, 2), p2.column);

    try std.testing.expectError(error.SourceNotLoaded, sm.lineSlice(id, 1));
}
