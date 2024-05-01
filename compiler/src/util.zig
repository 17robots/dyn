pub fn contains(comptime T: type, haystack: []const T, needle: T) bool {
    for (haystack) |item| {
        if (item == needle) {
            return true;
        }
    }
    return false;
}
