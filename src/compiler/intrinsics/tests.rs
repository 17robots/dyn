use super::*;
use std::collections::HashSet;

#[test]
fn runtime_intrinsic_table_is_self_consistent() {
    for intrinsic in RUNTIME_INTRINSICS {
        if is_hidden_runtime_builtin(intrinsic.builtin) {
            assert_eq!(runtime_symbol_for_builtin(intrinsic.builtin), None);
            assert_eq!(runtime_arity_for_builtin(intrinsic.builtin), None);
            assert_eq!(runtime_return_kind_for_builtin(intrinsic.builtin), None);
        } else {
            assert_eq!(
                runtime_symbol_for_builtin(intrinsic.builtin),
                Some(intrinsic.symbol)
            );
            assert_eq!(
                runtime_arity_for_builtin(intrinsic.builtin),
                Some(intrinsic.arity)
            );
            assert_eq!(
                runtime_return_kind_for_builtin(intrinsic.builtin),
                Some(intrinsic.return_kind)
            );
        }
        assert_eq!(
            runtime_arity_for_symbol(intrinsic.symbol),
            Some(intrinsic.arity)
        );
        assert_eq!(
            runtime_return_kind_for_symbol(intrinsic.symbol),
            Some(intrinsic.return_kind)
        );
        assert_eq!(
            runtime_abi_for_symbol(intrinsic.symbol),
            Some((intrinsic.abi_params, intrinsic.abi_return))
        );
    }
}

#[test]
fn hidden_runtime_builtins_are_runtime_intrinsics() {
    for builtin in HIDDEN_RUNTIME_BUILTINS {
        assert!(
            runtime_intrinsic_for_builtin(builtin).is_some(),
            "hidden runtime builtin missing intrinsic spec: {builtin}"
        );
    }
    for builtin in HIDDEN_IO_RUNTIME_BUILTINS {
        assert!(
            runtime_intrinsic_for_builtin(builtin).is_some(),
            "hidden runtime builtin missing intrinsic spec: {builtin}"
        );
    }
}

#[test]
fn runtime_intrinsic_builtins_are_declared_in_allowlists() {
    let mut allow = HashSet::new();
    for builtin in STDLIB_FOUNDATION_BUILTINS {
        assert!(
            allow.insert(*builtin),
            "duplicate builtin in allowlists: {builtin}"
        );
    }
    for builtin in INTERNAL_RUNTIME_BUILTINS {
        assert!(
            allow.insert(*builtin),
            "duplicate builtin in allowlists: {builtin}"
        );
    }

    let mut missing = Vec::new();
    for intrinsic in RUNTIME_INTRINSICS {
        if !allow.contains(intrinsic.builtin) {
            missing.push(intrinsic.builtin);
        }
    }
    missing.sort_unstable();
    assert!(
        missing.is_empty(),
        "runtime intrinsics missing from builtin allowlists: {missing:?}"
    );

    let mut stale = allow
        .into_iter()
        .filter(|builtin| runtime_intrinsic_for_builtin(builtin).is_none())
        .collect::<Vec<_>>();
    stale.sort_unstable();
    assert!(
        stale.is_empty(),
        "builtin allowlists include non-existent intrinsics: {stale:?}"
    );
}

#[test]
fn foundation_builtin_tiers_partition_foundation_surface() {
    let stable = STDLIB_FOUNDATION_STABLE_BUILTINS
        .iter()
        .copied()
        .collect::<HashSet<_>>();
    let transitional = STDLIB_FOUNDATION_TRANSITIONAL_BUILTINS
        .iter()
        .copied()
        .collect::<HashSet<_>>();
    let foundation = STDLIB_FOUNDATION_BUILTINS
        .iter()
        .copied()
        .collect::<HashSet<_>>();

    let mut overlap = stable
        .intersection(&transitional)
        .copied()
        .collect::<Vec<_>>();
    overlap.sort_unstable();
    assert!(
        overlap.is_empty(),
        "stable/transitional builtin tiers overlap: {overlap:?}"
    );

    let mut tier_union = stable.union(&transitional).copied().collect::<Vec<_>>();
    tier_union.sort_unstable();
    let mut foundation_sorted = foundation.into_iter().collect::<Vec<_>>();
    foundation_sorted.sort_unstable();
    assert_eq!(
        tier_union, foundation_sorted,
        "stable+transitional tiers must exactly match foundation builtins"
    );
}

#[test]
fn language_builtins_are_unique_and_distinct_from_runtime_aliases() {
    let mut language = HashSet::new();
    for builtin in LANGUAGE_BUILTINS {
        assert!(
            language.insert(*builtin),
            "duplicate language builtin declaration: {builtin}"
        );
    }

    let runtime = RUNTIME_INTRINSICS
        .iter()
        .map(|intrinsic| intrinsic.builtin)
        .collect::<HashSet<_>>();

    let mut overlap = language
        .into_iter()
        .filter(|builtin| runtime.contains(builtin))
        .collect::<Vec<_>>();
    overlap.sort_unstable();
    assert!(
        overlap.is_empty(),
        "language builtins must not overlap runtime intrinsic aliases: {overlap:?}"
    );
}
