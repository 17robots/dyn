use super::*;
use std::collections::HashSet;

#[test]
fn language_builtins_are_unique() {
    let mut seen = HashSet::new();
    for builtin in LANGUAGE_BUILTINS {
        assert!(
            seen.insert(*builtin),
            "duplicate language builtin declaration: {builtin}"
        );
    }
}
