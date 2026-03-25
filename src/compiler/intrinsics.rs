pub const LANGUAGE_BUILTINS: &[&str] = &[
    "$self",
    "$alignof",
    "$as",
    "$compile_error",
    "$offsetof",
    "$panic",
    "$sizeof",
    "$syscall",
    "$typeof",
    "$unreachable",
];

#[cfg(test)]
mod tests;
