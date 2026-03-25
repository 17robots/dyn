use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use object::write::{Object, StandardSection, Symbol, SymbolSection};
use object::{Architecture, BinaryFormat, Endianness, SymbolFlags, SymbolKind, SymbolScope};

use cranelift_codegen::settings;
use cranelift_codegen::settings::Configurable;
use cranelift_object::{ObjectBuilder, ObjectModule};

use crate::compiler::backend::{BuildArtifact, BuildOptLevel};
use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase};
use crate::compiler::mir::{MirFunction, MirInstr, MirProgram, MirValue, MirValueType};

use super::{compile_function, declare_function_symbols, declare_global_data};
use super::link::try_link_direct;

pub fn build_executable(
    mir: &MirProgram,
    build_dir: &Path,
    output_path: Option<&Path>,
    opt_level: BuildOptLevel,
) -> Result<(BuildArtifact, Vec<Diagnostic>), String> {
    fs::create_dir_all(build_dir).map_err(|err| format!("failed to create build dir: {err}"))?;

    let executable_path = output_path
        .map(PathBuf::from)
        .unwrap_or_else(|| build_dir.join(default_executable_name()));
    let object_path = build_dir.join("dyn_out.o");

    let mut diagnostics = Vec::new();
    if find_main_function(mir).is_none() {
        diagnostics.push(Diagnostic::error(
            DiagnosticPhase::Backend,
            DiagnosticCode::E5002,
            "no main function found in module 'main'",
        ));
        return Ok((
            BuildArtifact {
                executable_path,
                object_path,
            },
            diagnostics,
        ));
    }

    diagnostics.extend(collect_unsupported_integer_width_diagnostics(mir));
    diagnostics.extend(collect_unsupported_float_width_diagnostics(mir));
    if !diagnostics.is_empty() {
        return Ok((
            BuildArtifact {
                executable_path,
                object_path,
            },
            diagnostics,
        ));
    }

    let mut flag_builder = settings::builder();
    flag_builder
        .set("is_pic", "false")
        .map_err(|err| format!("failed to configure target flags: {err}"))?;
    flag_builder
        .set("enable_llvm_abi_extensions", "true")
        .map_err(|err| format!("failed to configure target flags: {err}"))?;
    if let Some(opt) = opt_level.cranelift_opt_level() {
        flag_builder
            .set("opt_level", opt)
            .map_err(|err| format!("failed to configure optimization level: {err}"))?;
    }
    let isa = cranelift_native::builder()
        .map_err(|err| format!("failed to build host isa: {err}"))?
        .finish(settings::Flags::new(flag_builder))
        .map_err(|err| format!("failed to finalize host isa: {err}"))?;

    let object_builder =
        ObjectBuilder::new(isa, "dyn_module", cranelift_module::default_libcall_names())
            .map_err(|err| format!("failed to build object module: {err}"))?;
    let mut module = ObjectModule::new(object_builder);

    let mut symbols = declare_function_symbols(mir, &mut module)?;
    symbols.global_data_ids = declare_global_data(mir, &mut module)?;
    for mir_module in &mir.modules {
        for function in &mir_module.functions {
            compile_function(
                &mut module,
                function,
                mir_module.module_id.0,
                mir_module.key.module_name == "main" && function.name == "main",
                &symbols,
            )?;
        }
    }

    let object = module.finish();
    let obj_bytes = object
        .emit()
        .map_err(|err| format!("failed to emit object bytes: {err}"))?;

    // Always write the object file (useful for debugging).
    fs::write(&object_path, &obj_bytes)
        .map_err(|err| format!("failed to write object file: {err}"))?;

    // Try direct linking first (no external toolchain needed).
    let (_, arch, _) = host_object_format();
    if let Some(syscall_code) = syscall_machine_code(arch) {
        if let Some(result) = try_link_direct(&obj_bytes, syscall_code, "main") {
            match result {
                Ok(exe_bytes) => {
                    fs::write(&executable_path, &exe_bytes).map_err(|err| {
                        format!("failed to write executable: {err}")
                    })?;
                    set_executable(&executable_path)?;
                    return Ok((BuildArtifact { executable_path, object_path }, diagnostics));
                }
                Err(_) => {
                    // Unsupported relocation or other link error — fall through to
                    // external linker. The external linker error (if any) will be reported.
                }
            }
        }
    }

    // Fall back: write syscall object and invoke external linker.
    let runtime_syscall_object_path = build_dir.join("dyn_runtime_syscall.o");
    write_runtime_syscall_object(&runtime_syscall_object_path)?;

    link_executable_with_host_toolchain(
        &object_path,
        &runtime_syscall_object_path,
        &executable_path,
    )?;

    Ok((
        BuildArtifact {
            executable_path,
            object_path,
        },
        diagnostics,
    ))
}

fn write_runtime_syscall_object(output_path: &Path) -> Result<(), String> {
    if output_path.exists() {
        return Ok(());
    }
    let (binary_format, architecture, endianness) = host_object_format();
    let code = syscall_machine_code(architecture)
        .ok_or_else(|| format!("no dyn_syscall implementation for {:?}", architecture))?;
    let mut obj = Object::new(binary_format, architecture, endianness);
    let section = obj.section_id(StandardSection::Text);
    let offset = obj.append_section_data(section, code, 16);
    let symbol_id = obj.add_symbol(Symbol {
        name: b"dyn_syscall".to_vec(),
        value: offset,
        size: code.len() as u64,
        kind: SymbolKind::Text,
        scope: SymbolScope::Linkage,
        weak: false,
        section: SymbolSection::Section(section),
        flags: SymbolFlags::None,
    });
    let _ = symbol_id;
    let bytes = obj
        .write()
        .map_err(|err| format!("failed to write syscall object: {err}"))?;
    fs::write(output_path, bytes)
        .map_err(|err| format!("failed to write syscall object file: {err}"))
}

pub(crate) fn host_object_format() -> (BinaryFormat, Architecture, Endianness) {
    let format = if cfg!(target_os = "macos") {
        BinaryFormat::MachO
    } else if cfg!(target_os = "windows") {
        BinaryFormat::Coff
    } else {
        BinaryFormat::Elf
    };
    let (arch, endian) = if cfg!(target_arch = "x86_64") {
        (Architecture::X86_64, Endianness::Little)
    } else if cfg!(target_arch = "aarch64") {
        (Architecture::Aarch64, Endianness::Little)
    } else {
        (Architecture::Unknown, Endianness::Little)
    };
    (format, arch, endian)
}

/// Pre-assembled machine code for `dyn_syscall(n, a1, a2, a3, a4, a5, a6) -> isize`.
///
/// The function receives 7 i64 arguments via the platform calling convention and
/// performs a raw OS syscall, returning the result in the platform return register.
pub(crate) fn syscall_machine_code(arch: Architecture) -> Option<&'static [u8]> {
    match arch {
        Architecture::X86_64 => {
            if cfg!(target_os = "macos") {
                // macOS x86-64: syscall number offset by 0x2000000
                // SysV params:  rdi=n, rsi=a1, rdx=a2, rcx=a3, r8=a4, r9=a5, [rsp+8]=a6
                // macOS syscall: rax=n+0x2000000, rdi=a1, rsi=a2, rdx=a3, r10=a4, r8=a5, r9=a6
                Some(&[
                    0x48, 0x89, 0xF8, // mov rax, rdi
                    0x48, 0x05, 0x00, 0x00, 0x00, 0x02, // add rax, 0x2000000
                    0x48, 0x89, 0xF7, // mov rdi, rsi
                    0x48, 0x89, 0xD6, // mov rsi, rdx
                    0x48, 0x89, 0xCA, // mov rdx, rcx
                    0x4D, 0x89, 0xC2, // mov r10, r8
                    0x4D, 0x89, 0xC8, // mov r8,  r9
                    0x4C, 0x8B, 0x4C, 0x24, 0x08, // mov r9, [rsp+8]
                    0x0F, 0x05, // syscall
                    0xC3, // ret
                ])
            } else {
                // Linux x86-64
                // SysV params:  rdi=n, rsi=a1, rdx=a2, rcx=a3, r8=a4, r9=a5, [rsp+8]=a6
                // Linux syscall: rax=n, rdi=a1, rsi=a2, rdx=a3, r10=a4, r8=a5, r9=a6
                Some(&[
                    0x48, 0x89, 0xF8, // mov rax, rdi
                    0x48, 0x89, 0xF7, // mov rdi, rsi
                    0x48, 0x89, 0xD6, // mov rsi, rdx
                    0x48, 0x89, 0xCA, // mov rdx, rcx
                    0x4D, 0x89, 0xC2, // mov r10, r8
                    0x4D, 0x89, 0xC8, // mov r8,  r9
                    0x4C, 0x8B, 0x4C, 0x24, 0x08, // mov r9, [rsp+8]
                    0x0F, 0x05, // syscall
                    0xC3, // ret
                ])
            }
        }
        Architecture::Aarch64 => {
            if cfg!(target_os = "macos") {
                // macOS aarch64: syscall number in x16, svc #0x80
                // SysV params: x0=n, x1=a1, x2=a2, x3=a3, x4=a4, x5=a5, x6=a6
                Some(&[
                    0xF0, 0x03, 0x00, 0xAA, // mov x16, x0
                    0xE0, 0x03, 0x01, 0xAA, // mov x0,  x1
                    0xE1, 0x03, 0x02, 0xAA, // mov x1,  x2
                    0xE2, 0x03, 0x03, 0xAA, // mov x2,  x3
                    0xE3, 0x03, 0x04, 0xAA, // mov x3,  x4
                    0xE4, 0x03, 0x05, 0xAA, // mov x4,  x5
                    0xE5, 0x03, 0x06, 0xAA, // mov x5,  x6
                    0x01, 0x10, 0x00, 0xD4, // svc #0x80
                    0xC0, 0x03, 0x5F, 0xD6, // ret
                ])
            } else {
                // Linux aarch64: syscall number in x8, svc #0
                // SysV params: x0=n, x1=a1, x2=a2, x3=a3, x4=a4, x5=a5, x6=a6
                Some(&[
                    0xE8, 0x03, 0x00, 0xAA, // mov x8,  x0
                    0xE0, 0x03, 0x01, 0xAA, // mov x0,  x1
                    0xE1, 0x03, 0x02, 0xAA, // mov x1,  x2
                    0xE2, 0x03, 0x03, 0xAA, // mov x2,  x3
                    0xE3, 0x03, 0x04, 0xAA, // mov x3,  x4
                    0xE4, 0x03, 0x05, 0xAA, // mov x4,  x5
                    0xE5, 0x03, 0x06, 0xAA, // mov x5,  x6
                    0x01, 0x00, 0x00, 0xD4, // svc #0
                    0xC0, 0x03, 0x5F, 0xD6, // ret
                ])
            }
        }
        _ => None,
    }
}

fn link_executable_with_host_toolchain(
    object_path: &Path,
    runtime_syscall_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    let cc_link_result = try_link_with_c_driver_candidates(
        object_path,
        runtime_syscall_object_path,
        executable_path,
    );
    if cc_link_result.is_ok() {
        return Ok(());
    }

    if cfg!(target_os = "linux") {
        let ld_result = link_executable_with_linux_ld(
            object_path,
            runtime_syscall_object_path,
            executable_path,
        );
        if ld_result.is_ok() {
            return Ok(());
        }
        let cc_error = cc_link_result
            .err()
            .unwrap_or_else(|| "cc-like linker failed".to_string());
        let ld_error = ld_result
            .err()
            .unwrap_or_else(|| "ld fallback failed".to_string());
        return Err(format!(
            "failed to link executable with host C toolchain; {cc_error}; {ld_error}"
        ));
    }

    Err(format!(
        "failed to link executable with host C toolchain; {}",
        cc_link_result
            .err()
            .unwrap_or_else(|| "unknown linker driver failure".to_string())
    ))
}

fn try_link_with_c_driver_candidates(
    object_path: &Path,
    runtime_syscall_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    let mut errors = Vec::new();
    for driver in linker_driver_candidates() {
        let result = if driver == "cl" {
            try_link_with_msvc_cl(
                object_path,
                runtime_syscall_object_path,
                executable_path,
            )
        } else {
            try_link_with_cc_like_driver(
                &driver,
                object_path,
                runtime_syscall_object_path,
                executable_path,
            )
        };
        if result.is_ok() {
            return Ok(());
        }
        errors.push(result.err().unwrap_or_else(|| format!("{driver} failed")));
    }
    if errors.is_empty() {
        return Err("no candidate linker drivers were configured".to_string());
    }
    Err(errors.join("; "))
}

fn try_link_with_cc_like_driver(
    driver: &str,
    object_path: &Path,
    runtime_syscall_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    let mut command = Command::new(driver);
    command
        .arg(object_path)
        .arg(runtime_syscall_object_path)
        .arg("-o")
        .arg(executable_path);
    if cfg!(target_os = "linux") {
        command.arg("-no-pie");
    }
    let status = command
        .status()
        .map_err(|err| format!("failed to invoke linker driver ({driver}): {err}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!(
            "linker driver ({driver}) failed with status {:?}",
            status.code()
        ))
    }
}

fn try_link_with_msvc_cl(
    object_path: &Path,
    runtime_syscall_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    if !cfg!(target_os = "windows") {
        return Err("linker driver (cl) is only available on windows targets".to_string());
    }
    let output_arg = format!("/Fe:{}", executable_path.display());
    let status = Command::new("cl")
        .arg("/nologo")
        .arg(object_path)
        .arg(runtime_syscall_object_path)
        .arg(output_arg)
        .status()
        .map_err(|err| format!("failed to invoke linker driver (cl): {err}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!(
            "linker driver (cl) failed with status {:?}",
            status.code()
        ))
    }
}

fn linker_driver_candidates() -> Vec<String> {
    if let Ok(custom) = std::env::var("DYN_LINKER") {
        let parsed = custom
            .split(',')
            .map(str::trim)
            .filter(|part| !part.is_empty())
            .map(ToString::to_string)
            .collect::<Vec<_>>();
        if !parsed.is_empty() {
            return parsed;
        }
    }

    if cfg!(target_os = "windows") {
        vec![
            "cl".to_string(),
            "clang".to_string(),
            "gcc".to_string(),
            "cc".to_string(),
        ]
    } else {
        vec!["cc".to_string(), "clang".to_string(), "gcc".to_string()]
    }
}


fn set_executable(path: &Path) -> Result<(), String> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(path)
            .map_err(|e| format!("failed to read permissions: {e}"))?
            .permissions();
        perms.set_mode(0o755);
        fs::set_permissions(path, perms)
            .map_err(|e| format!("failed to set executable permissions: {e}"))?;
    }
    #[cfg(not(unix))]
    let _ = path;
    Ok(())
}

fn default_executable_name() -> &'static str {
    if cfg!(target_os = "windows") {
        "dyn_out.exe"
    } else {
        "dyn_out"
    }
}

fn link_executable_with_linux_ld(
    object_path: &Path,
    runtime_syscall_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    let crt_dirs = [
        "/usr/lib",
        "/usr/lib64",
        "/usr/lib/x86_64-linux-gnu",
        "/lib",
        "/lib64",
        "/lib/x86_64-linux-gnu",
    ];
    let linker_paths = [
        "/lib64/ld-linux-x86-64.so.2",
        "/usr/lib/ld-linux-x86-64.so.2",
        "/lib/ld-linux-x86-64.so.2",
        "/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
    ];

    let Some(crt_dir) = crt_dirs.iter().find(|dir| {
        Path::new(dir).join("crt1.o").exists()
            && Path::new(dir).join("crti.o").exists()
            && Path::new(dir).join("crtn.o").exists()
    }) else {
        return Err("failed to locate crt startup objects for linker".to_string());
    };
    let Some(dynamic_linker) = linker_paths.iter().find(|path| Path::new(path).exists()) else {
        return Err("failed to locate system dynamic linker".to_string());
    };

    let status = Command::new("ld")
        .arg("-o")
        .arg(executable_path)
        .arg(Path::new(crt_dir).join("crt1.o"))
        .arg(Path::new(crt_dir).join("crti.o"))
        .arg(object_path)
        .arg(runtime_syscall_object_path)
        .arg(format!("-L{crt_dir}"))
        .arg("-lc")
        .arg(Path::new(crt_dir).join("crtn.o"))
        .arg("-dynamic-linker")
        .arg(dynamic_linker)
        .status()
        .map_err(|err| format!("failed to invoke linker (ld): {err}"))?;
    if !status.success() {
        return Err("linker failed to produce executable".to_string());
    }

    Ok(())
}

fn find_main_function(mir: &MirProgram) -> Option<&MirFunction> {
    mir.modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .and_then(|module| {
            module
                .functions
                .iter()
                .find(|function| function.name == "main")
        })
}

fn collect_unsupported_float_width_diagnostics(mir: &MirProgram) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    for mir_module in &mir.modules {
        for function in &mir_module.functions {
            let mut reasons = Vec::new();
            if function
                .return_type
                .as_deref()
                .and_then(max_float_bits_in_type_text)
                .map(|bits| bits > 64)
                .unwrap_or(false)
            {
                reasons.push("return type".to_string());
            }
            if function.param_type_hints.iter().flatten().any(|hint| {
                max_float_bits_in_type_text(hint)
                    .map(|bits| bits > 64)
                    .unwrap_or(false)
            }) {
                reasons.push("parameter type hint".to_string());
            }
            if function
                .param_types
                .iter()
                .any(mir_type_uses_unsupported_float)
            {
                reasons.push("parameter type".to_string());
            }
            if function_uses_unsupported_float_values(function) {
                reasons.push("MIR value type".to_string());
            }

            if reasons.is_empty() {
                continue;
            }
            reasons.sort();
            reasons.dedup();
            diagnostics.push(Diagnostic::error(
                DiagnosticPhase::Backend,
                DiagnosticCode::E5002,
                format!(
                    "backend currently supports float widths up to f64; function `{}` uses unsupported float width ({})",
                    function.name,
                    reasons.join(", ")
                ),
            ));
        }
    }
    diagnostics
}

fn collect_unsupported_integer_width_diagnostics(mir: &MirProgram) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    for mir_module in &mir.modules {
        for function in &mir_module.functions {
            let mut reasons = Vec::new();
            if function
                .return_type
                .as_deref()
                .and_then(max_int_bits_in_type_text)
                .map(|bits| bits == 0 || bits > 128)
                .unwrap_or(false)
            {
                reasons.push("return type".to_string());
            }
            if function.param_type_hints.iter().flatten().any(|hint| {
                max_int_bits_in_type_text(hint)
                    .map(|bits| bits == 0 || bits > 128)
                    .unwrap_or(false)
            }) {
                reasons.push("parameter type hint".to_string());
            }
            if function
                .param_types
                .iter()
                .any(mir_type_uses_unsupported_integer)
            {
                reasons.push("parameter type".to_string());
            }
            if function_uses_unsupported_integer_values(function) {
                reasons.push("MIR value type".to_string());
            }

            if reasons.is_empty() {
                continue;
            }
            reasons.sort();
            reasons.dedup();
            diagnostics.push(Diagnostic::error(
                DiagnosticPhase::Backend,
                DiagnosticCode::E5002,
                format!(
                    "backend currently supports integer widths from i1/u1 up to i128/u128; function `{}` uses unsupported integer width ({})",
                    function.name,
                    reasons.join(", ")
                ),
            ));
        }
    }
    diagnostics
}

fn function_uses_unsupported_float_values(function: &MirFunction) -> bool {
    for block in &function.blocks {
        for instr in &block.instructions {
            match instr {
                MirInstr::Eval { ty, value, .. } => {
                    if mir_type_uses_unsupported_float(ty)
                        || mir_value_uses_unsupported_float(value)
                    {
                        return true;
                    }
                }
                MirInstr::Phi { ty, .. } => {
                    if mir_type_uses_unsupported_float(ty) {
                        return true;
                    }
                }
            }
        }
    }
    false
}

fn function_uses_unsupported_integer_values(function: &MirFunction) -> bool {
    for block in &function.blocks {
        for instr in &block.instructions {
            match instr {
                MirInstr::Eval { ty, value, .. } => {
                    if mir_type_uses_unsupported_integer(ty)
                        || mir_value_uses_unsupported_integer(value)
                    {
                        return true;
                    }
                }
                MirInstr::Phi { ty, .. } => {
                    if mir_type_uses_unsupported_integer(ty) {
                        return true;
                    }
                }
            }
        }
    }
    false
}

fn mir_value_uses_unsupported_float(value: &MirValue) -> bool {
    match value {
        MirValue::Cast { target, .. } => mir_type_uses_unsupported_float(target),
        _ => false,
    }
}

fn mir_value_uses_unsupported_integer(value: &MirValue) -> bool {
    match value {
        MirValue::Cast { target, .. } => mir_type_uses_unsupported_integer(target),
        _ => false,
    }
}

fn mir_type_uses_unsupported_float(ty: &MirValueType) -> bool {
    matches!(ty, MirValueType::Float { bits } if *bits > 64)
}

fn mir_type_uses_unsupported_integer(ty: &MirValueType) -> bool {
    matches!(ty, MirValueType::Int { bits, .. } if *bits == 0 || *bits > 128)
}

fn max_float_bits_in_type_text(text: &str) -> Option<u16> {
    text.split(|ch: char| !(ch.is_ascii_alphanumeric() || ch == '_'))
        .filter_map(|token| token.strip_prefix('f'))
        .filter(|digits| !digits.is_empty())
        .filter_map(|digits| digits.parse::<u16>().ok())
        .max()
}

fn max_int_bits_in_type_text(text: &str) -> Option<u16> {
    text.split(|ch: char| !(ch.is_ascii_alphanumeric() || ch == '_'))
        .filter_map(|token| {
            if token == "isize" || token == "usize" {
                return Some(64);
            }
            let digits = token
                .strip_prefix('i')
                .or_else(|| token.strip_prefix('u'))?;
            if digits.is_empty() {
                return None;
            }
            digits.parse::<u16>().ok()
        })
        .max()
}
