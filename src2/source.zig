pub const FileId = u32;
pub const Span = struct {
    file: FileId = 0,
    start: u32,
    end: u32,

    pub fn len(self: Span) u32 {
        return self.end - self.start;
    }
};
pub const SourceFile = struct {
    id: FileId,
    path: []const u8,
    text: []const u8,
};
