use super::*;

#[test]
fn runtime_intrinsic_table_is_self_consistent() {
    for intrinsic in RUNTIME_INTRINSICS {
        assert_eq!(
            runtime_symbol_for_builtin(intrinsic.builtin),
            Some(intrinsic.symbol)
        );
        assert_eq!(
            runtime_arity_for_builtin(intrinsic.builtin),
            Some(intrinsic.arity)
        );
        assert_eq!(
            runtime_arity_for_symbol(intrinsic.symbol),
            Some(intrinsic.arity)
        );
        assert_eq!(
            runtime_return_kind_for_builtin(intrinsic.builtin),
            Some(intrinsic.return_kind)
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
