use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::SystemTime;

use cranelift_codegen::settings;
use cranelift_codegen::settings::Configurable;
use cranelift_object::{ObjectBuilder, ObjectModule};

use crate::compiler::backend::{BuildArtifact, BuildOptLevel};
use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase};
use crate::compiler::mir::{MirFunction, MirInstr, MirProgram, MirValue, MirValueType};

use super::{compile_function, declare_function_symbols};

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

    let symbols = declare_function_symbols(mir, &mut module)?;
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
    let bytes = object
        .emit()
        .map_err(|err| format!("failed to emit object bytes: {err}"))?;

    fs::write(&object_path, bytes).map_err(|err| format!("failed to write object file: {err}"))?;

    let runtime_object_path =
        build_dir.join(format!("dyn_runtime_alloc_{}.o", opt_level.file_suffix()));
    compile_runtime_allocator_object(build_dir, &runtime_object_path, opt_level)?;

    let runtime_f128_object_path =
        build_dir.join(format!("dyn_runtime_f128_{}.o", opt_level.file_suffix()));
    compile_runtime_f128_object(build_dir, &runtime_f128_object_path, opt_level)?;

    link_executable_with_host_toolchain(
        &object_path,
        &runtime_object_path,
        &runtime_f128_object_path,
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

fn compile_runtime_allocator_object(
    _build_dir: &Path,
    output_path: &Path,
    opt_level: BuildOptLevel,
) -> Result<(), String> {
    let source_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("src")
        .join("compiler")
        .join("backend");
    let source_path = source_root.join("runtime_support.rs");
    let source_paths = vec![
        source_path.clone(),
        source_root.join("runtime_support").join("vec.rs"),
        source_root.join("runtime_support").join("io.rs"),
        source_root.join("runtime_support").join("system.rs"),
    ];

    if artifact_is_up_to_date(output_path, &source_paths) {
        return Ok(());
    }

    let status = Command::new("rustc")
        .arg("--crate-type=lib")
        .arg("--emit=obj")
        .arg("--edition=2021")
        .arg("-C")
        .arg(format!("opt-level={}", opt_level.rustc_opt_level()))
        .arg("-C")
        .arg("panic=abort")
        .arg(&source_path)
        .arg("-o")
        .arg(output_path)
        .status()
        .map_err(|err| format!("failed to compile runtime support object (rustc): {err}"))?;
    if !status.success() {
        return Err("failed to compile runtime support object".to_string());
    }

    Ok(())
}

fn compile_runtime_f128_object(
    _build_dir: &Path,
    output_path: &Path,
    opt_level: BuildOptLevel,
) -> Result<(), String> {
    let source_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("src")
        .join("compiler")
        .join("backend")
        .join("runtime_support");
    let source_path = source_root.join("f128.c");
    let source_paths = vec![source_path.clone()];

    if artifact_is_up_to_date(output_path, &source_paths) {
        return Ok(());
    }

    let cc = std::env::var("CC").unwrap_or_else(|_| "cc".to_string());
    let status = Command::new(&cc)
        .arg("-std=gnu11")
        .arg(opt_level.cc_opt_flag())
        .arg("-c")
        .arg(&source_path)
        .arg("-o")
        .arg(output_path)
        .status()
        .map_err(|err| format!("failed to compile f128 runtime support object ({cc}): {err}"))?;
    if !status.success() {
        return Err("failed to compile f128 runtime support object".to_string());
    }

    Ok(())
}

fn link_executable_with_host_toolchain(
    object_path: &Path,
    runtime_object_path: &Path,
    runtime_f128_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    let cc_link_result = try_link_with_c_driver_candidates(
        object_path,
        runtime_object_path,
        runtime_f128_object_path,
        executable_path,
    );
    if cc_link_result.is_ok() {
        return Ok(());
    }

    if cfg!(target_os = "linux") {
        let ld_result = link_executable_with_linux_ld(
            object_path,
            runtime_object_path,
            runtime_f128_object_path,
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
    runtime_object_path: &Path,
    runtime_f128_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    let mut errors = Vec::new();
    for driver in linker_driver_candidates() {
        let result = if driver == "cl" {
            try_link_with_msvc_cl(
                object_path,
                runtime_object_path,
                runtime_f128_object_path,
                executable_path,
            )
        } else {
            try_link_with_cc_like_driver(
                &driver,
                object_path,
                runtime_object_path,
                runtime_f128_object_path,
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
    runtime_object_path: &Path,
    runtime_f128_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    let mut command = Command::new(driver);
    command
        .arg(object_path)
        .arg(runtime_object_path)
        .arg(runtime_f128_object_path)
        .arg("-lquadmath")
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
    runtime_object_path: &Path,
    runtime_f128_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    if !cfg!(target_os = "windows") {
        return Err("linker driver (cl) is only available on windows targets".to_string());
    }
    let output_arg = format!("/Fe:{}", executable_path.display());
    let status = Command::new("cl")
        .arg("/nologo")
        .arg(object_path)
        .arg(runtime_object_path)
        .arg(runtime_f128_object_path)
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

fn artifact_is_up_to_date(artifact: &Path, sources: &[PathBuf]) -> bool {
    let Ok(artifact_meta) = fs::metadata(artifact) else {
        return false;
    };
    let Ok(artifact_mtime) = artifact_meta.modified() else {
        return false;
    };
    sources
        .iter()
        .all(|source| source_mtime_not_newer(source, artifact_mtime))
}

fn source_mtime_not_newer(source: &Path, baseline: SystemTime) -> bool {
    let Ok(meta) = fs::metadata(source) else {
        return false;
    };
    let Ok(modified) = meta.modified() else {
        return false;
    };
    modified <= baseline
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
    runtime_object_path: &Path,
    runtime_f128_object_path: &Path,
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
        .arg(runtime_object_path)
        .arg(runtime_f128_object_path)
        .arg(format!("-L{crt_dir}"))
        .arg("-lquadmath")
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
                .map(|bits| bits > 128)
                .unwrap_or(false)
            {
                reasons.push("return type".to_string());
            }
            if function.param_type_hints.iter().flatten().any(|hint| {
                max_float_bits_in_type_text(hint)
                    .map(|bits| bits > 128)
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
                    "backend currently supports float widths up to f128; function `{}` uses unsupported float width ({})",
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
    matches!(ty, MirValueType::Float { bits } if *bits > 128)
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
