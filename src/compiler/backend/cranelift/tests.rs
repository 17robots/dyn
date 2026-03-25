use super::*;

#[test]
fn sanitize_symbol_name_replaces_non_identifier_chars() {
    assert_eq!(sanitize_symbol_name("ok_name123"), "ok_name123");
    assert_eq!(
        sanitize_symbol_name("with-dash.and space"),
        "with_dash_and_space"
    );
}

#[test]
fn parse_return_scalar_strips_optional_and_errorable_wrappers() {
    match parse_return_scalar(Some("?i64!Err")) {
        ScalarType::Int { ty, signed } => {
            assert_eq!(ty, I64);
            assert!(signed);
        }
        ScalarType::Float { .. } => panic!("expected integer scalar"),
    }

    match parse_return_scalar(Some("?f32!Err")) {
        ScalarType::Float { ty } => assert_eq!(ty, F32),
        ScalarType::Int { .. } => panic!("expected float scalar"),
    }
}

#[test]
fn parse_return_scalar_defaults_to_i32_for_unknown_type() {
    match parse_return_scalar(Some("MyUnknownType")) {
        ScalarType::Int { ty, signed } => {
            assert_eq!(ty, I32);
            assert!(signed);
        }
        ScalarType::Float { .. } => panic!("expected integer scalar"),
    }
}

#[test]
fn parse_return_scalar_supports_type_keyword() {
    match parse_return_scalar(Some("type")) {
        ScalarType::Int { ty, signed } => {
            assert_eq!(ty, I64);
            assert!(!signed);
        }
        ScalarType::Float { .. } => panic!("expected integer scalar"),
    }
}

#[test]
fn parse_return_scalar_supports_u1_keyword() {
    match parse_return_scalar(Some("u1")) {
        ScalarType::Int { ty, signed } => {
            assert_eq!(ty, I8);
            assert!(!signed);
        }
        ScalarType::Float { .. } => panic!("expected integer scalar"),
    }
}

#[test]
fn parse_return_scalar_supports_function_type() {
    match parse_return_scalar(Some("fn(i32) i32")) {
        ScalarType::Int { ty, signed } => {
            assert_eq!(ty, I64);
            assert!(!signed);
        }
        ScalarType::Float { .. } => panic!("expected integer scalar"),
    }
    match parse_return_scalar(Some("fn/1")) {
        ScalarType::Int { ty, signed } => {
            assert_eq!(ty, I64);
            assert!(!signed);
        }
        ScalarType::Float { .. } => panic!("expected integer scalar"),
    }
}

#[test]
fn parse_return_scalar_supports_slice_type() {
    match parse_return_scalar(Some("[]u8")) {
        ScalarType::Int { ty, signed } => {
            assert_eq!(ty, I64);
            assert!(!signed);
        }
        ScalarType::Float { .. } => panic!("expected integer scalar"),
    }
}

#[test]
fn parse_return_scalar_supports_nonstandard_int_widths() {
    match parse_return_scalar(Some("i31")) {
        ScalarType::Int { ty, signed } => {
            assert_eq!(ty, I32);
            assert!(signed);
        }
        ScalarType::Float { .. } => panic!("expected integer scalar"),
    }

    match parse_return_scalar(Some("u7")) {
        ScalarType::Int { ty, signed } => {
            assert_eq!(ty, I8);
            assert!(!signed);
        }
        ScalarType::Float { .. } => panic!("expected integer scalar"),
    }

    match parse_return_scalar(Some("i127")) {
        ScalarType::Int { ty, signed } => {
            assert_eq!(ty, I128);
            assert!(signed);
        }
        ScalarType::Float { .. } => panic!("expected integer scalar"),
    }

    match parse_return_scalar(Some("u128")) {
        ScalarType::Int { ty, signed } => {
            assert_eq!(ty, I128);
            assert!(!signed);
        }
        ScalarType::Float { .. } => panic!("expected integer scalar"),
    }
}

#[test]
fn returns_bytes_slice_from_function_signature_hint() {
    assert!(returns_bytes_slice_from_hint(Some("(value: []u8) []u8")));
    assert!(returns_bytes_slice_from_hint(Some(
        "?(value: []u8) []u8!Err"
    )));
    assert!(!returns_bytes_slice_from_hint(Some("(value: []u8) u32")));
}

#[test]
fn variant_tag_is_stable_fnv1a_32() {
    assert_eq!(variant_tag("Ready"), 197800596);
    assert_eq!(variant_tag("Waiting"), 3376746056);
}

#[test]
fn runtime_syscall_machine_code_is_available_for_host() {
    let (_, arch, _) = super::driver::host_object_format();
    let code = super::driver::syscall_machine_code(arch);
    assert!(
        code.is_some(),
        "no dyn_syscall machine code for host architecture {:?}",
        arch
    );
    assert!(!code.unwrap().is_empty());
}

